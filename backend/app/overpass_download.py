"""Bounded, resumable Overpass downloads. OSMnx only processes local data."""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from uuid import uuid4

import requests
from shapely.geometry import box

CACHE_VERSION = 1
CACHE_TTL = 24 * 60 * 60
# Mainland Portugal: these fixed geographic cells are below 10 km on both axes,
# including projection rotation. Geographic clipping avoids gaps from projecting
# straight bbox edges to a different CRS and back without densifying them.
TILE_LONGITUDE_DEG = .1
TILE_LATITUDE_DEG = .08
TILE_BUDGET = 300
DATASET_BUDGET = 600
RETRY_DELAYS = (10, 20, 40)


class OverpassFailure(RuntimeError):
    def __init__(self, message: str, code: str = "overpass_unavailable", retryable: bool = True):
        super().__init__(message)
        self.code, self.retryable = code, retryable


def tiles(polygon):
    """Fixed national grid, clipped in the query CRS without shrinking coverage."""
    west, south, east, north = polygon.bounds
    for y in range(math.floor(south / TILE_LATITUDE_DEG), math.ceil(north / TILE_LATITUDE_DEG)):
        for x in range(math.floor(west / TILE_LONGITUDE_DEG), math.ceil(east / TILE_LONGITUDE_DEG)):
            part = polygon.intersection(box(x*TILE_LONGITUDE_DEG, y*TILE_LATITUDE_DEG,
                                            (x+1)*TILE_LONGITUDE_DEG, (y+1)*TILE_LATITUDE_DEG))
            if part.is_empty or part.area == 0:
                continue
            for piece in getattr(part, "geoms", [part]):
                if piece.geom_type == "Polygon":
                    yield piece


def validate(payload: dict, complete: bool = False) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise OverpassFailure("Overpass returned an invalid JSON response", "overpass_invalid_response")
    if payload.get("remark"):
        message = str(payload["remark"])[:500]
        permanent = any(word in message.lower() for word in ("parse error", "static error"))
        raise OverpassFailure(message, "overpass_request_rejected" if permanent else "overpass_runtime_error", not permanent)
    for item in payload["elements"]:
        if (not isinstance(item, dict) or item.get("type") not in {"node", "way", "relation"}
                or not isinstance(item.get("id"), int)):
            raise OverpassFailure("Overpass returned an invalid OSM element", "overpass_invalid_response")
        if not isinstance(item.get("tags", {}), dict):
            raise OverpassFailure("Overpass returned invalid OSM tags", "overpass_invalid_response")
        if item["type"] == "node" and not all(isinstance(item.get(k), (float, int)) for k in ("lat", "lon")):
            raise OverpassFailure("Overpass returned a node without coordinates", "overpass_invalid_response")
    if complete:
        ids = {(row["type"], row["id"]) for row in payload["elements"]}
        for row in payload["elements"]:
            refs = ([("node", ref) for ref in row.get("nodes", [])] if row["type"] == "way" else
                    [(member["type"], member["ref"]) for member in row.get("members", [])])
            if any(ref not in ids for ref in refs) or (row["type"] == "way" and not refs):
                raise OverpassFailure("Overpass returned incomplete OSM references", "overpass_incomplete_data")


def write_xml(elements: list[dict], path: Path) -> None:
    """Convert complete raw elements, never separately simplified tile graphs."""
    nodes = {item["id"] for item in elements if item["type"] == "node"}
    root = ET.Element("osm", version="0.6", generator="fire-road-exposure")
    for item in sorted(elements, key=lambda row: (row["type"], row["id"])):
        node = ET.SubElement(root, item["type"], id=str(item["id"]))
        if item["type"] == "node":
            node.set("lat", str(item["lat"])); node.set("lon", str(item["lon"]))
        elif item["type"] == "way":
            if not item.get("nodes") or not set(item["nodes"]).issubset(nodes):
                raise OverpassFailure("Downloaded OSM way has missing nodes", "overpass_incomplete_data")
            for ref in item["nodes"]:
                ET.SubElement(node, "nd", ref=str(ref))
        else:
            for member in item.get("members", []):
                ET.SubElement(node, "member", type=member["type"], ref=str(member["ref"]),
                              role=member.get("role", ""))
        for key, value in item.get("tags", {}).items():
            ET.SubElement(node, "tag", k=key, v=str(value))
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class OverpassClient:
    def __init__(self, cache: Path, endpoints, *, check_cancel=lambda: None,
                 progress=lambda **kwargs: None, session=None):
        self.cache = cache
        self.endpoints = tuple(dict.fromkeys(url.rstrip("/").removesuffix("/interpreter") + "/interpreter"
                                            for url in endpoints))
        self.check_cancel, self.progress = check_cancel, progress
        self.session = session or requests.Session()
        self.dataset_deadline = 0.0
        self.retry_after: dict[str, float] = {}
        self.preferred_endpoint = 0
        self.oldest_fetched_at = time.time()

    def close(self):
        self.session.close()

    def download(self, polygon, kind: str, vehicle_filter: str = "") -> list[dict]:
        self.dataset_deadline = time.monotonic() + DATASET_BUDGET
        self.oldest_fetched_at = time.time()
        pieces = list(tiles(polygon))
        merged = {}
        for index, piece in enumerate(pieces):
            self.check_cancel()
            self.progress(completed=index, total=len(pieces), retry_at=None)
            coordinates = " ".join(f"{lat:.7f} {lon:.7f}" for lon, lat in piece.exterior.coords)
            selector = f'(poly:"{coordinates}")'
            if kind == "roads":
                body = f'(way{vehicle_filter}{selector};>;);out body;'
            elif kind == "buildings":
                body = f'(nwr["building"]{selector};>>;);out body;'
            else:
                tags = ('["amenity"="fire_station"]' if kind == "stations" else
                        '["emergency"~"^(fire_hydrant|water_tank|fire_water_pond)$"]')
                body = f'nwr{tags}{selector};out center body;'
            query = '[out:json][timeout:30];' + body
            payload = self.fetch(query)
            for item in payload["elements"]:
                merged[item["type"], item["id"]] = item
            self.progress(completed=index+1, total=len(pieces), retry_at=None)
        return list(merged.values())

    def fetch(self, query: str) -> dict:
        self.check_cancel()
        complete = "out body;" in query
        key = hashlib.sha256(f"{CACHE_VERSION}|{query}".encode()).hexdigest()
        path = self.cache / f"{key}.json"
        try:
            cached = json.loads(path.read_text())
            if cached["version"] == CACHE_VERSION and 0 <= time.time()-cached["fetched_at"] < CACHE_TTL:
                validate(cached["payload"], complete)
                self.oldest_fetched_at = min(self.oldest_fetched_at, cached["fetched_at"])
                return cached["payload"]
        except (OSError, ValueError, KeyError, TypeError, OverpassFailure):
            pass
        deadline = min(time.monotonic()+TILE_BUDGET, self.dataset_deadline or float("inf"))
        errors = []
        first_endpoint = self.preferred_endpoint
        for attempt in range(4):
            self.check_cancel()
            endpoint_index = (first_endpoint + attempt) % len(self.endpoints)
            endpoint = self.endpoints[endpoint_index]
            delay = max(0, self.retry_after.get(endpoint, 0)-time.time())
            if attempt:
                delay = max(delay, RETRY_DELAYS[attempt-1] * random.uniform(1, 1.1))
            self._wait(delay, deadline)
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                break
            try:
                # A streaming response lets cancellation/deadline checks run during downloads.
                with self.session.post(endpoint, data={"data": query}, stream=True,
                                       timeout=(min(10, remaining), min(45, remaining)),
                                       headers={"User-Agent": "fire-road-exposure/0.3"}) as response:
                    if response.status_code == 429 or 500 <= response.status_code <= 599:
                        self.retry_after[endpoint] = time.time() + _retry_after(response.headers.get("Retry-After"))
                        raise OverpassFailure(f"{endpoint}: HTTP {response.status_code}")
                    if not response.ok:
                        raise OverpassFailure(f"{endpoint}: HTTP {response.status_code}", "overpass_request_rejected", False)
                    content = bytearray()
                    for chunk in response.iter_content(64*1024):
                        self.check_cancel()
                        if time.monotonic() >= deadline:
                            raise OverpassFailure("Overpass download budget exhausted", "overpass_timeout")
                        content.extend(chunk)
                    try:
                        payload = json.loads(content)
                    except (ValueError, UnicodeError) as error:
                        raise OverpassFailure("Overpass returned malformed data", "overpass_invalid_response") from error
                    validate(payload, complete)
                self.check_cancel()
                self.preferred_endpoint = endpoint_index
                self.cache.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(f".{uuid4().hex}.tmp")
                try:
                    temporary.write_text(json.dumps({"version": CACHE_VERSION, "fetched_at": time.time(),
                                                     "endpoint": endpoint, "payload": payload}))
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
                return payload
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError,
                    OverpassFailure) as error:
                if isinstance(error, OverpassFailure) and not error.retryable:
                    raise
                errors.append(f"{endpoint}: {str(error)[:300]}")
        raise OverpassFailure("OpenStreetMap Overpass unavailable after bounded retries: " + "; ".join(errors))

    def _wait(self, seconds: float, deadline: float):
        if time.monotonic()+seconds >= deadline:
            raise OverpassFailure("Overpass retry budget exhausted; saved downloads can be resumed", "overpass_timeout")
        if seconds:
            self.progress(retry_at=datetime.fromtimestamp(time.time()+seconds, UTC).isoformat())
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            self.check_cancel()
            time.sleep(min(.25, max(0, end-time.monotonic())))
        self.progress(retry_at=None)


def _retry_after(value: str | None) -> float:
    try:
        return max(0, float(value)) if value else 0
    except ValueError:
        try:
            return max(0, parsedate_to_datetime(value).timestamp()-time.time())
        except (ValueError, TypeError, OverflowError):
            return 0
