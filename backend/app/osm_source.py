"""Read complete OSM objects locally, with the bounded Overpass client as fallback."""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path

import osmium
from shapely import intersects_xy, prepare
from shapely.geometry import shape

from .osm_snapshots import (LocalOSMError, REFRESH_SECONDS, SnapshotStore, atomic_json,
                            file_lock, read_json)
from .overpass_download import OverpassClient, validate
from . import osm_native

PROCESSING_VERSION = 1
TYPES = {"n": "node", "w": "way", "r": "relation"}


def _raw(item):
    row = {"type": TYPES[item.type_str()], "id": item.id, "version": item.version,
           "tags": dict(item.tags)}
    if item.is_node():
        row.update(lon=item.lon, lat=item.lat)
    elif item.is_way():
        row["nodes"] = [node.ref for node in item.nodes]
    else:
        row["members"] = [{"type": TYPES[member.type], "ref": member.ref, "role": member.role}
                          for member in item.members]
    return row


def _matches(tags, kind, vehicle_filter):
    if kind == "roads":
        clauses = re.findall(r'\["([^"]+)"(?:(=|!=|~|!~)"([^"]*)")?\]', vehicle_filter)
        if not clauses or "".join(f'["{k}"{op}"{v}"]' if op else f'["{k}"]'
                                  for k, op, v in clauses) != vehicle_filter:
            raise LocalOSMError("Unsupported local road filter")
        for key, operation, value in clauses:
            actual = tags.get(key)
            if not operation and actual is None:
                return False
            if operation == "=" and actual != value:
                return False
            if operation == "!=" and actual == value:
                return False
            if operation == "~" and (actual is None or not re.search(value, actual)):
                return False
            if operation == "!~" and actual is not None and re.search(value, actual):
                return False
        return True
    if kind == "buildings":
        return "building" in tags
    if kind == "water":
        return tags.get("emergency") in {"fire_hydrant", "water_tank", "fire_water_pond"}
    if kind == "stations":
        return tags.get("amenity") == "fire_station"
    raise LocalOSMError(f"Unknown OSM dataset: {kind}")


class _Cancellation(osmium.SimpleHandler):
    def __init__(self, check):
        super().__init__()
        self.check, self.count = check, 0

    def tick(self, item):
        self.count += 1
        if self.count % 16384 == 0:
            self.check()

    node = way = relation = tick


def _scan(paths, entities, check_cancel, tracker=None):
    for path in paths:
        check_cancel()
        stream = osmium.FileProcessor(path, entities).with_filter(_Cancellation(check_cancel))
        if tracker is not None:
            stream = stream.with_filter(tracker.id_filter())
        yield from stream
    check_cancel()


def extract(paths: list[Path], polygon, kind: str, vehicle_filter: str, check_cancel=lambda: None,
            *, selection_paths=None):
    """Select by geographic nodes, then recover references in bounded-memory passes.

    Only IDs inside the requested polygon and selected objects are retained. No
    country-sized coordinate index or country-wide XML is built. Selected ways
    remain complete, including their tagged nodes outside the polygon.
    """
    prepare(polygon)
    west, south, east, north = polygon.bounds
    spatial = osmium.IdTracker()
    rows, selected = {}, set()
    selection_paths = paths if selection_paths is None else selection_paths

    def keep(item, *, root=False):
        row = _raw(item)
        key = row["type"], row["id"]
        previous = rows.get(key)
        if previous is not None and row["version"] == previous["version"] and row != previous:
            raise LocalOSMError("Conflicting objects in overlapping OSM extracts")
        if previous is None or row["version"] > previous["version"]:
            rows[key] = row
        if root:
            selected.add(key)

    for item in _scan(selection_paths, osmium.osm.NODE, check_cancel):
        x, y = item.lon, item.lat
        if west <= x <= east and south <= y <= north and intersects_xy(polygon, x, y):
            spatial.add_node(item.id)
            if kind != "roads" and _matches(item.tags, kind, vehicle_filter):
                keep(item, root=True)
    for item in _scan(selection_paths, osmium.osm.WAY, check_cancel):
        if spatial.contains_any_references(item):
            spatial.add_way(item.id)
            if _matches(item.tags, kind, vehicle_filter):
                keep(item, root=True)
    if kind != "roads":
        candidates, nested, touching = set(), {}, set()
        for item in _scan(selection_paths, osmium.osm.RELATION, check_cancel):
            if spatial.contains_any_references(item):
                touching.add(item.id)
            children = [m.ref for m in item.members if m.type == "r"]
            if children:
                nested[item.id] = children
            if _matches(item.tags, kind, vehicle_filter):
                candidates.add(item.id)
        while True:
            more = {rid for rid, children in nested.items() if any(ref in touching for ref in children)} - touching
            if not more:
                break
            check_cancel()
            touching.update(more)
        roots = touching & candidates
        if roots:
            tracker = osmium.IdTracker()
            for rid in roots:
                tracker.add_relation(rid)
            for item in _scan(paths, osmium.osm.RELATION, check_cancel, tracker):
                keep(item, root=True)

    # Resolve nested relations before ways, and ways before nodes. Cycles are
    # harmless because each object is only requested once; missing refs fail.
    def missing(type_name):
        result = set()
        for row in rows.values():
            if row["type"] == "relation":
                result.update(m["ref"] for m in row["members"] if m["type"] == type_name)
            elif row["type"] == "way" and type_name == "node":
                result.update(row["nodes"])
        return result - {ref for typ, ref in rows if typ == type_name}

    for _ in range(64):
        needed = missing("relation")
        if not needed:
            break
        tracker = osmium.IdTracker()
        for ref in needed:
            tracker.add_relation(ref)
        before = len(rows)
        for item in _scan(paths, osmium.osm.RELATION, check_cancel, tracker):
            keep(item)
        if len(rows) == before:
            raise LocalOSMError("Local OSM relation references are incomplete")
    else:
        raise LocalOSMError("OSM relation nesting exceeds the supported depth")
    for name, entities in (("way", osmium.osm.WAY), ("node", osmium.osm.NODE)):
        tracker = osmium.IdTracker()
        needed = missing(name)
        for ref in needed:
            getattr(tracker, f"add_{name}")(ref)
        if needed:
            for item in _scan(paths, entities, check_cancel, tracker):
                keep(item)
    values = list(rows.values())
    validate({"elements": values}, complete=True)
    if kind in {"water", "stations"}:
        def coordinates(key, visited):
            if key in visited:
                return
            visited.add(key)
            row = rows[key]
            if key[0] == "node":
                yield row["lon"], row["lat"]
            elif key[0] == "way":
                for ref in row["nodes"]:
                    yield from coordinates(("node", ref), visited)
            else:
                for member in row["members"]:
                    yield from coordinates((member["type"], member["ref"]), visited)

        values = []
        for key in sorted(selected):
            row = rows[key]
            if key[0] != "node":
                points = list(coordinates(key, set()))
                if not points:
                    raise LocalOSMError("Local resource has no geometry")
                xs, ys = zip(*points)
                # Overpass `out center` is the bounding-box center, not centroid.
                row["center"] = {"lon": (min(xs) + max(xs)) / 2, "lat": (min(ys) + max(ys)) / 2}
            values.append(row)
    return values


class OSMSource:
    def __init__(self, cache: Path, endpoints, *, working: Path | None = None,
                 check_cancel=lambda: None, progress=lambda **kw: None):
        self.cache, self.working = cache, working
        self.check_cancel, self.progress = check_cancel, progress
        self.store = SnapshotStore(cache / "osm-extracts-v1", check_cancel=check_cancel, progress=progress)
        self.remote = OverpassClient(cache / "overpass-v1", endpoints,
                                     check_cancel=check_cancel, progress=progress)
        self.snapshot, self.attempted = None, False
        self.local_error = None
        self.provenance = {}
        self.oldest_fetched_at = time.time()

    def close(self):
        self.store.close()
        self.remote.close()

    def _snapshot(self):
        if self.attempted:
            return self.snapshot
        self.attempted = True
        pin = read_json(self.working / "osm-source-v1.json", {}) if self.working else {}
        self.snapshot = self.store.load(pin.get("snapshot_id")) or self.store.current()
        if self.snapshot is None:
            self.snapshot = self.store.sync()
        if self.working:
            atomic_json(self.working / "osm-source-v1.json", {"snapshot_id": self.snapshot["id"]})
        self.store.refresh_in_background()
        return self.snapshot

    def _provenance(self, snapshot):
        pointer = read_json(self.store.root / "current.json", {})
        stamp = datetime.fromisoformat(snapshot["data_timestamp"].replace("Z", "+00:00")).timestamp()
        return {"provider": "local", "snapshot_id": snapshot["id"],
                "data_timestamp": snapshot["data_timestamp"], "processing_version": PROCESSING_VERSION,
                "stale": time.time() - stamp > REFRESH_SECONDS,
                "refresh_error": pointer.get("last_error"),
                "attribution": "© OpenStreetMap contributors, ODbL 1.0; extracts by Geofabrik"}

    def restore_metadata(self, metadata):
        provenance = metadata.get("osm_provenance", {})
        if provenance.get("provider") != "local":
            return True
        if provenance.get("processing_version") != PROCESSING_VERSION:
            return False
        # Checkpoint validation never starts a new country download.
        snapshot = self.store.load(provenance.get("snapshot_id"))
        if snapshot is None or (self.snapshot and snapshot["id"] != self.snapshot["id"]):
            return False
        self.snapshot, self.attempted = snapshot, True
        if self.working:
            atomic_json(self.working / "osm-source-v1.json", {"snapshot_id": snapshot["id"]})
        metadata["osm_provenance"] = self._provenance(snapshot)
        self.store.refresh_in_background()
        return True

    def download(self, polygon, kind: str, vehicle_filter: str = "") -> list[dict]:
        self.check_cancel()
        self.provenance = {}
        try:
            self.progress(source_progress={"provider": "local", "phase": "validating"})
            snapshot = self._snapshot()
            if snapshot is None:
                raise LocalOSMError(self.local_error or "Local maps unavailable", "osm_extract_unavailable")
            if not shape(snapshot["coverage"]).covers(polygon):
                raise LocalOSMError("Local maps do not cover the entire selected area", "osm_coverage_missing")
            self.progress(source_progress={"provider": "local", "phase": "extracting"})
            key = hashlib.sha256(json.dumps([PROCESSING_VERSION, snapshot["id"], polygon.wkb_hex,
                                            kind, vehicle_filter]).encode()).hexdigest()
            target = self.cache / "osm-queries-v1" / f"{key}.json"
            with file_lock(target.with_suffix(".lock"), self.check_cancel):
                cached = read_json(target)
                elements = None
                if cached and cached.get("key") == key:
                    try:
                        validate(cached["payload"], complete=kind in {"roads", "buildings"})
                        body = json.dumps(cached["payload"], sort_keys=True).encode()
                        if hashlib.sha256(body).hexdigest() == cached["sha256"]:
                            elements = cached["payload"]["elements"]
                    except (ValueError, KeyError, TypeError, RuntimeError):
                        pass
                if elements is None:
                    paths = [self.store.root / snapshot["id"] / f"{row['region']}.osm.pbf"
                             for row in snapshot["files"]]
                    selected_paths = [path for path, row in zip(paths, snapshot["files"])
                                      if shape(row["coverage"]).intersects(polygon)]
                    try:
                        subsets = osm_native.subset(self.cache, snapshot, kind, polygon, self.check_cancel)
                        if subsets:
                            elements = extract(subsets, polygon, kind, vehicle_filter, self.check_cancel)
                        else:
                            elements = extract(paths, polygon, kind, vehicle_filter, self.check_cancel,
                                               selection_paths=selected_paths)
                    except (LocalOSMError, RuntimeError, OSError):
                        self.check_cancel()
                        # An optional accelerator cannot make valid local maps
                        # unusable. Retry through the complete source files.
                        elements = extract(paths, polygon, kind, vehicle_filter, self.check_cancel,
                                           selection_paths=selected_paths)
                    self.check_cancel()
                    payload = {"elements": elements}
                    atomic_json(target, {"key": key, "payload": payload,
                                         "sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()})
            self.provenance = {**self._provenance(snapshot), "query_key": key}
            self.progress(source_progress={"provider": "local", "phase": "ready"})
            return elements
        except Exception as error:
            self.check_cancel()
            self.local_error = str(error)
            self.progress(source_progress={"provider": "overpass", "phase": "fallback", "reason": str(error)})
            self.provenance = {"provider": "overpass", "fallback_reason": str(error)}
            elements = self.remote.download(polygon, kind, vehicle_filter)
            self.oldest_fetched_at = self.remote.oldest_fetched_at
            return elements
