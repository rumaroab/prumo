from __future__ import annotations

import hashlib
import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from threading import Event, Lock
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests

from . import storage
from .fogos_resources import reconcile_resource_groups
from .models import ScenarioPatch

BASE_URL = "https://api.fogos.pt"
PROVIDER = "fogos.pt"
RURAL_FIRE_CODES = {"3101", "3103", "3105", "3111", "3109", "4335"}
TERMINAL_STATUS_CODES = {7, 8, 9, 10, 11, 12}
WIND_DEGREES = {1: 0.0, 2: 45.0, 3: 90.0, 4: 135.0, 5: 180.0,
                6: 225.0, 7: 270.0, 8: 315.0, 9: 0.0}
DETAIL_INTERVAL = timedelta(minutes=5)
PERIMETER_INTERVAL = timedelta(minutes=10)
SIMULATION_INTERVAL = timedelta(hours=1)


class FogosError(RuntimeError):
    def __init__(self, message: str, retry_after_seconds: int | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = Lock()


def configuration() -> dict[str, Any]:
    key = os.getenv("FOGOS_API_KEY", "").strip()
    agent = os.getenv("FOGOS_USER_AGENT", "").strip()
    configured = bool(key and agent)
    return {
        "configured": configured,
        "message": "Fogos.pt integration is ready" if configured else
                   "Set FOGOS_API_KEY and FOGOS_USER_AGENT on the backend",
        "provider": PROVIDER,
        "attribution": "Source: Fogos.pt",
        "source_url": "https://fogos.pt",
    }


def _headers() -> dict[str, str]:
    status = configuration()
    if not status["configured"]:
        raise FogosError(status["message"])
    return {"X-API-Key": os.environ["FOGOS_API_KEY"],
            "User-Agent": os.environ["FOGOS_USER_AGENT"], "Accept": "application/json"}


def _request(path: str, params: dict[str, Any] | None = None, *, accept: str = "application/json") -> tuple[Any, dict[str, str]]:
    headers = _headers()
    headers["Accept"] = accept
    try:
        response = requests.get(f"{BASE_URL}{path}", params=params, headers=headers, timeout=(5, 20))
    except requests.RequestException as error:
        raise FogosError(f"Fogos.pt is unavailable: {error}") from error
    if response.status_code == 429:
        retry = response.headers.get("Retry-After", "later")
        try:
            retry_seconds = max(1, int(retry))
        except (TypeError, ValueError):
            retry_seconds = 300
        raise FogosError(f"Fogos.pt rate limit reached; retry {retry}", retry_seconds)
    if response.status_code == 404:
        raise KeyError(path)
    if not response.ok:
        raise FogosError(f"Fogos.pt returned HTTP {response.status_code}")
    if accept == "application/json":
        try:
            return response.json(), dict(response.headers)
        except ValueError as error:
            raise FogosError("Fogos.pt returned invalid JSON") from error
    return response.text, dict(response.headers)


def _timestamp(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("sec")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC).isoformat()
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).isoformat()
        except ValueError:
            return None
    return None


def normalize_incident(value: dict[str, Any]) -> dict[str, Any]:
    incident_id = str(value.get("id") or value.get("sadoId") or value.get("_id", ""))
    coordinate_status = "missing"
    try:
        longitude, latitude = float(value.get("lng")), float(value.get("lat"))
        if -9.7 <= longitude <= -6.0 and 36.8 <= latitude <= 42.3:
            coordinates = [longitude, latitude]
            coordinate_status = "usable"
        else:
            coordinates = None
            coordinate_status = "outside_mainland"
    except (TypeError, ValueError):
        coordinates = None
    weather = value.get("weather") if isinstance(value.get("weather"), dict) else None
    normalized_weather = None
    if weather:
        speed = weather.get("intensidadeVentoKM")
        direction_id = weather.get("idDireccVento")
        try:
            speed = float(speed)
            direction_id = int(direction_id)
            if speed == -99 or direction_id not in WIND_DEGREES:
                raise ValueError
            normalized_weather = {
                "wind_speed_kmh": speed, "wind_direction_deg": WIND_DEGREES[direction_id],
                "wind_direction_label": weather.get("direccVento"),
                "temperature_c": _weather_number(weather.get("temperatura")),
                "relative_humidity_pct": _weather_number(weather.get("humidade")),
                "precipitation_mm": _weather_number(weather.get("precAcumulada")),
                "station_id": weather.get("stationId"), "station_name": weather.get("stationLocation"),
                "station_distance_km": weather.get("stationDistance"), "observed_at": _timestamp(weather.get("date")),
            }
        except (TypeError, ValueError):
            normalized_weather = None
    nature_code = str(value.get("naturezaCode") or "")
    personnel = _resource_count(value.get("man"))
    vehicles = _resource_count(value.get("terrain"))
    aircraft = _resource_count(value.get("aerial"))
    helicopter = _resource_count(value.get("heliFight"))
    plane = _resource_count(value.get("planeFight"))
    firefighting_aircraft = (None if helicopter is None and plane is None
                             else (helicopter or 0) + (plane or 0))
    return {
        "provider": PROVIDER, "incident_id": incident_id,
        "source_url": f"https://fogos.pt/fogo/{incident_id}" if incident_id else "https://fogos.pt",
        "reported_at": _timestamp(value.get("dateTime")), "updated_at": _timestamp(value.get("updated")),
        "location": value.get("location") or value.get("localidade") or "Reported incident",
        "detail_location": value.get("detailLocation"), "district": value.get("district"),
        "municipality": value.get("concelho"), "parish": value.get("freguesia"),
        "coordinates": coordinates, "has_usable_coordinates": coordinates is not None,
        "coordinate_status": coordinate_status,
        "nature": value.get("natureza"), "nature_code": nature_code,
        "is_rural_fire": nature_code in RURAL_FIRE_CODES or bool(value.get("isFire")),
        "status": value.get("status"), "status_code": value.get("statusCode"),
        "active": bool(value.get("active")),
        "resources": {"personnel": personnel, "vehicles": vehicles,
                      "aircraft": aircraft, "firefighting_aircraft": firefighting_aircraft},
        "weather": normalized_weather, "weather_warnings": _normalize_warnings(value.get("weatherWarnings") or []),
        "importable": bool(incident_id and (nature_code in RURAL_FIRE_CODES or value.get("isFire"))
                           and coordinate_status != "outside_mainland"),
    }


def _resource_count(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def _weather_number(value: Any) -> float | None:
    try:
        result = float(value)
        return None if result == -99 else result
    except (TypeError, ValueError):
        return None


def _normalize_warnings(values: list[Any]) -> list[dict[str, Any]]:
    result = []
    lisbon = ZoneInfo("Europe/Lisbon")
    for value in values:
        if not isinstance(value, dict):
            continue
        item = dict(value)
        for source, target in (("startTime", "starts_at"), ("endTime", "ends_at")):
            stamp = _timestamp(value.get(source))
            item[target] = stamp
            item[f"{target}_lisbon"] = (datetime.fromisoformat(stamp).astimezone(lisbon).isoformat()
                                          if stamp else None)
        item["timezone"] = "Europe/Lisbon"
        result.append(item)
    return result


def list_incidents(*, mode: str = "active", municipality: str | None = None,
                   day: str | None = None, after: str | None = None,
                   before: str | None = None, page: int = 1, limit: int = 50) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": max(1, min(limit, 100)), "page": max(1, page)}
    if municipality:
        params["concelho"] = municipality
    path = "/v2/incidents/active"
    if mode == "historical":
        path = "/v2/incidents/search"
        if day:
            params["day"] = day
        elif after and before:
            params.update({"after": after, "before": before})
    cache_key = f"incidents:{path}:{json.dumps(params, sort_keys=True, default=str)}"
    payload = _cached_json(cache_key, path, params, 30)
    raw = payload.get("data", []) if isinstance(payload, dict) else []
    incidents = [normalize_incident(item) for item in raw if isinstance(item, dict)]
    incidents = [item for item in incidents if item["is_rural_fire"]]
    with storage.connect() as db:
        for item in incidents:
            rows = db.execute("""SELECT s.id,s.name FROM scenario_external_incidents l
                               JOIN scenarios s ON s.id=l.scenario_id AND s.deleted_at IS NULL
                               WHERE l.provider=? AND l.incident_id=?""",
                              (PROVIDER, item["incident_id"])).fetchall()
            item["linked_scenarios"] = [dict(row) for row in rows]
    return {"items": incidents, "paginator": payload.get("paginator") if isinstance(payload, dict) else None,
            "mode": mode, "attribution": "Source: Fogos.pt", "source_url": "https://fogos.pt"}


def fetch_incident(incident_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, _ = _request("/fires", {"id": incident_id})
    raw = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not isinstance(raw, dict):
        raise KeyError(incident_id)
    return raw, normalize_incident(raw)


def save_snapshot(incident_id: str, product_type: str, raw: Any, normalized: Any,
                  source_url: str, observed_at: str | None = None,
                  quality_notes: list[str] | None = None) -> dict[str, Any]:
    serialized = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    checksum = hashlib.sha256(serialized.encode()).hexdigest()
    stamp = datetime.now(UTC).isoformat()
    snapshot_id = uuid4().hex[:16]
    with storage.connect() as db:
        existing = db.execute("""SELECT * FROM external_snapshots
                               WHERE provider=? AND incident_id=? AND product_type=? AND checksum=?""",
                              (PROVIDER, incident_id, product_type, checksum)).fetchone()
        if existing:
            snapshot_id = existing["id"]
        else:
            db.execute("""INSERT INTO external_snapshots
                (id,provider,incident_id,product_type,checksum,raw_payload,normalized,source_url,retrieved_at,observed_at,quality_notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (snapshot_id, PROVIDER, incident_id, product_type, checksum, serialized,
                 json.dumps(normalized, default=str), source_url, stamp, observed_at,
                 json.dumps(quality_notes or [])))
        db.execute("""INSERT INTO external_fetches
            (id,provider,incident_id,product_type,snapshot_id,fetched_at,status)
            VALUES (?,?,?,?,?,?,?)""", (uuid4().hex[:16], PROVIDER, incident_id, product_type,
                                        snapshot_id, stamp, "success"))
        db.execute("""INSERT INTO external_incidents
            (provider,incident_id,source_url,latest_snapshot_id,last_success_at,last_error)
            VALUES (?,?,?,?,?,NULL)
            ON CONFLICT(provider,incident_id) DO UPDATE SET source_url=excluded.source_url,
              latest_snapshot_id=CASE WHEN ?='incident' THEN excluded.latest_snapshot_id ELSE external_incidents.latest_snapshot_id END,
              last_success_at=excluded.last_success_at,last_error=NULL""",
            (PROVIDER, incident_id, source_url, snapshot_id, stamp, product_type))
        row = db.execute("SELECT * FROM external_snapshots WHERE id=?", (snapshot_id,)).fetchone()
    return _snapshot_dict(row)


def import_preview(incident_id: str) -> dict[str, Any]:
    raw, normalized = fetch_incident(incident_id)
    if not normalized["is_rural_fire"]:
        raise ValueError("Only rural-fire incidents can be imported for simulation")
    if normalized["coordinate_status"] == "outside_mainland":
        raise ValueError("This incident is outside the platform's mainland Portugal coverage")
    snapshot = save_snapshot(incident_id, "incident", raw, normalized, normalized["source_url"],
                             normalized.get("updated_at") or normalized.get("reported_at"))
    with storage.connect() as db:
        rows = db.execute("""SELECT s.id,s.name FROM scenario_external_incidents l
            JOIN scenarios s ON s.id=l.scenario_id AND s.deleted_at IS NULL
            WHERE l.provider=? AND l.incident_id=?""", (PROVIDER, incident_id)).fetchall()
    preview = {**normalized, "linked_scenarios": [dict(row) for row in rows]}
    return {"snapshot": snapshot, "incident": preview,
            "suggested": {"name": f"{normalized['location']} · Fogos.pt",
                          "description": f"Imported from Fogos.pt incident {incident_id}",
                          "start_time": normalized.get("reported_at"),
                          "coordinates": normalized.get("coordinates")}}


def _snapshot_dict(row) -> dict[str, Any]:
    value = dict(row)
    value["normalized"] = json.loads(value.pop("normalized"))
    value["quality_notes"] = json.loads(value["quality_notes"])
    value.pop("raw_payload", None)
    return value


def snapshots(incident_id: str, product_type: str | None = None) -> list[dict[str, Any]]:
    with storage.connect() as db:
        query = "SELECT * FROM external_snapshots WHERE provider=? AND incident_id=?"
        values: list[Any] = [PROVIDER, incident_id]
        if product_type:
            query += " AND product_type=?"
            values.append(product_type)
        rows = db.execute(query + " ORDER BY retrieved_at DESC", values).fetchall()
    return [_snapshot_dict(row) for row in rows]


def snapshot(snapshot_id: str):
    with storage.connect() as db:
        row = db.execute("SELECT * FROM external_snapshots WHERE id=?", (snapshot_id,)).fetchone()
    if not row:
        raise KeyError(snapshot_id)
    value = _snapshot_dict(row)
    with storage.connect() as db:
        raw = db.execute("SELECT raw_payload FROM external_snapshots WHERE id=?", (snapshot_id,)).fetchone()
    value["raw_payload"] = json.loads(raw["raw_payload"])
    return value


def context_for_scenario(scenario_id: str) -> dict[str, Any]:
    workspace = storage.get_scenario(scenario_id)
    link = workspace.external_incident
    if not link:
        raise KeyError(scenario_id)
    values = snapshots(link["incident_id"])
    latest_incident = next((item for item in values if item["product_type"] == "incident"), None)
    imported = next((item for item in values if item["id"] == link["import_snapshot_id"]), None)
    return {"link": link, "import_snapshot": imported, "latest_incident": latest_incident,
            "snapshots": values, "attribution": "Source: Fogos.pt", "source_url": link.get("source_url")}


def refresh_scenario(scenario_id: str) -> dict[str, Any]:
    workspace = storage.get_scenario(scenario_id)
    if not workspace.external_incident:
        raise KeyError(scenario_id)
    incident_id = workspace.external_incident["incident_id"]
    raw, normalized = fetch_incident(incident_id)
    save_snapshot(incident_id, "incident", raw, normalized, normalized["source_url"],
                  normalized.get("updated_at") or normalized.get("reported_at"))
    return context_for_scenario(scenario_id)


def sync_scenario_resources(scenario_id: str, expected_revision: int) -> dict[str, Any]:
    workspace = storage.get_scenario(scenario_id)
    if not workspace.external_incident:
        raise KeyError(scenario_id)
    if workspace.revision != expected_revision:
        raise storage.ScenarioConflictError(scenario_id)
    incident_id = workspace.external_incident["incident_id"]
    try:
        raw, normalized = fetch_incident(incident_id)
    except KeyError as error:
        raise FogosError("Fogos.pt incident is unavailable") from error
    saved = save_snapshot(incident_id, "incident", raw, normalized, normalized["source_url"],
                          normalized.get("updated_at") or normalized.get("reported_at"))
    groups, changes = reconcile_resource_groups(workspace.resource_groups, saved)
    if [group.model_dump() for group in groups] != [group.model_dump() for group in workspace.resource_groups]:
        values = workspace.model_dump(exclude={"id", "revision", "created_at", "updated_at",
                                                "setup_complete", "external_incident"})
        values.update({"expected_revision": expected_revision, "resource_groups": groups})
        workspace = storage.update_scenario(scenario_id, ScenarioPatch(**values))
    return {"scenario": workspace.model_dump(mode="json"),
            "context": context_for_scenario(scenario_id), "changes": changes}


def set_tracking(scenario_id: str, enabled: bool) -> dict[str, Any]:
    workspace = storage.get_scenario(scenario_id)
    if not workspace.external_incident:
        raise KeyError(scenario_id)
    incident_id = workspace.external_incident["incident_id"]
    now = datetime.now(UTC).isoformat()
    with storage.connect() as db:
        db.execute("""INSERT INTO tracking_subscriptions
            (provider,incident_id,enabled,next_details_at,next_perimeter_at,next_simulation_at)
            VALUES (?,?,?,?,?,?) ON CONFLICT(provider,incident_id) DO UPDATE SET enabled=excluded.enabled,
            failure_count=CASE WHEN excluded.enabled=1 THEN 0 ELSE failure_count END,last_error=NULL,
            next_details_at=CASE WHEN excluded.enabled=1 THEN excluded.next_details_at ELSE next_details_at END,
            next_perimeter_at=CASE WHEN excluded.enabled=1 THEN excluded.next_perimeter_at ELSE next_perimeter_at END,
            next_simulation_at=CASE WHEN excluded.enabled=1 THEN excluded.next_simulation_at ELSE next_simulation_at END""",
            (PROVIDER, incident_id, int(enabled), now, now, now))
    return context_for_scenario(scenario_id)


def fetch_product(incident_id: str, product_type: str) -> dict[str, Any]:
    paths = {"perimeter": f"/v2/incidents/{incident_id}/perimeter",
             "pyrocast": f"/v2/incidents/{incident_id}/simulation"}
    if product_type not in paths:
        raise ValueError(product_type)
    payload, headers = _request(paths[product_type])
    observed = _source_observation_time(payload) if product_type == "perimeter" else None
    normalized = {"geojson": payload, "stale": headers.get("X-Stale") == "true",
                  "fetched_at": headers.get("X-Fetched-At") or payload.get("fetched_at")}
    notes = (["MTG satellite evidence uses approximately 2–4 km pixels"] if product_type == "perimeter"
             else ["PyroCast is an external scenario, not an observation"])
    if headers.get("X-Stale") == "true":
        notes.append("The upstream response was marked stale")
    if isinstance(payload, dict):
        if payload.get("disclaimer"):
            notes.append(str(payload["disclaimer"]))
        for error in payload.get("errors") or []:
            if isinstance(error, dict):
                notes.append(str(error.get("message") or error.get("code") or "Product unavailable"))
    return save_snapshot(incident_id, product_type, payload, normalized,
                         f"{BASE_URL}{paths[product_type]}", _timestamp(observed) or observed, notes)


def _source_observation_time(payload: Any) -> str | None:
    candidates: list[str] = []
    if not isinstance(payload, dict):
        return None
    for feature in payload.get("features", []):
        properties = feature.get("properties", {}) if isinstance(feature, dict) else {}
        for key in ("observed_at", "last_seen", "latest_detection_at"):
            value = _timestamp(properties.get(key))
            if value:
                candidates.append(value)
        detections = properties.get("detections") or []
        if isinstance(detections, list):
            for detection in detections:
                if isinstance(detection, dict):
                    for key in ("observed_at", "detected_at", "timestamp", "time"):
                        value = _timestamp(detection.get(key))
                        if value:
                            candidates.append(value)
                            break
    return max(candidates) if candidates else None


def contextual_layer(scenario_id: str, layer: str) -> Any:
    workspace = storage.get_scenario(scenario_id)
    if not workspace.external_incident:
        raise KeyError(scenario_id)
    incident_id = workspace.external_incident["incident_id"]
    context = context_for_scenario(scenario_id)
    incident = context["latest_incident"]["normalized"] if context.get("latest_incident") else {}
    if layer in {"perimeter", "pyrocast"}:
        existing = snapshots(incident_id, layer)
        item = existing[0] if existing else fetch_product(incident_id, layer)
        collection = item["normalized"]["geojson"]
        if layer == "pyrocast" and isinstance(collection, dict):
            collection = {**collection, "features": sorted(collection.get("features", []),
                key=lambda feature: feature.get("properties", {}).get("hour", 0), reverse=True)}
        return collection
    if layer == "weather":
        return {"weather": incident.get("weather"), "warnings": incident.get("weather_warnings", []),
                "attribution": "Source: Fogos.pt / IPMA"}
    if layer == "risk":
        municipality = incident.get("municipality")
        payload = _cached_json(f"risk:{municipality}", "/v2/rcm/parish", {"concelho": municipality}, 300)
        today = datetime.now(ZoneInfo("Europe/Lisbon")).date()
        return {"municipality": municipality, "data": payload.get("data", payload),
                "dates": {"today": today.isoformat(), "tomorrow": (today + timedelta(days=1)).isoformat(),
                          "after": (today + timedelta(days=2)).isoformat()},
                "retrieved_at": datetime.now(UTC).isoformat()}
    if layer == "aircraft":
        payload = _cached_json("aircraft:6h", "/v2/planes/recent", {"hours": 6}, 60)
        return aircraft_geojson(payload)
    if layer in {"icnf", "vost", "firms"}:
        suffix = {"icnf": "kml", "vost": "kmlVost", "firms": "kmlFirms"}[layer]
        text, _ = _request(f"/v2/incidents/{incident_id}/{suffix}", accept="application/vnd.google-earth.kml+xml")
        return kml_to_geojson(text, layer)
    raise ValueError(layer)


def kml_to_geojson(text: str, source: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise FogosError("Fogos.pt returned invalid KML") from error
    features = []
    for element in root.iter():
        if not element.tag.endswith("coordinates") or not element.text:
            continue
        coordinates = []
        for token in element.text.replace("\n", " ").split():
            try:
                longitude, latitude = token.split(",")[:2]
                coordinates.append([float(longitude), float(latitude)])
            except (ValueError, IndexError):
                continue
        if not coordinates:
            continue
        geometry = ({"type": "Point", "coordinates": coordinates[0]} if len(coordinates) == 1 else
                    {"type": "Polygon", "coordinates": [coordinates]} if coordinates[0] == coordinates[-1] else
                    {"type": "LineString", "coordinates": coordinates})
        features.append({"type": "Feature", "geometry": geometry, "properties": {"source": source}})
    return {"type": "FeatureCollection", "features": features, "source": source,
            "attribution": "Source: Fogos.pt"}


def _cached_json(key: str, path: str, params: dict[str, Any], ttl_seconds: int) -> Any:
    now_value = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and now_value - cached[0] < ttl_seconds:
            return cached[1]
    payload, _ = _request(path, params)
    with _CACHE_LOCK:
        _CACHE[key] = (now_value, payload)
    return payload


def aircraft_geojson(payload: Any) -> dict[str, Any]:
    aircraft = payload.get("data", []) if isinstance(payload, dict) else []
    features: list[dict[str, Any]] = []
    current_time = datetime.now(UTC)
    for item in aircraft:
        if not isinstance(item, dict):
            continue
        positions = []
        for position in item.get("positions", []):
            try:
                positions.append((float(position["lon"]), float(position["lat"]), position))
            except (KeyError, TypeError, ValueError):
                continue
        if not positions:
            continue
        common = {"icao": item.get("icao"), "registration": item.get("registration"),
                  "name": item.get("name"), "aircraft_type": item.get("aircraft_type"),
                  "kind": item.get("kind"), "operator": item.get("operator"),
                  "source": "Fogos.pt aircraft tracking", "assignment": "not inferred"}
        if len(positions) > 1:
            features.append({"type": "Feature", "geometry": {"type": "LineString",
                "coordinates": [[lon, lat] for lon, lat, _ in positions]},
                "properties": {**common, "type": "track", "observed_at": positions[-1][2].get("sampled_at")}})
        lon, lat, last = positions[-1]
        observed_at = _timestamp(last.get("sampled_at"))
        age_minutes = None
        if observed_at:
            age_minutes = max(0, (current_time - datetime.fromisoformat(observed_at)).total_seconds() / 60)
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {**common, "type": "latest position", "observed_at": observed_at,
                           "age_minutes": age_minutes, "altitude_ft": last.get("altitude"),
                           "ground_speed_knots": last.get("ground_speed")}})
    return {"type": "FeatureCollection", "features": features, "retrieved_at": current_time.isoformat(),
            "attribution": "Source: Fogos.pt / aircraft tracking",
            "disclaimer": "Aircraft proximity does not imply incident assignment or availability."}


def create_weather_series(scenario_id: str) -> dict[str, Any]:
    from .weather import save_weather_series
    workspace = storage.get_scenario(scenario_id)
    if not workspace.external_incident or not workspace.start_time:
        raise ValueError("The imported scenario requires a start time")
    context = context_for_scenario(scenario_id)
    incident = context["latest_incident"]["normalized"]
    weather = incident.get("weather") or {}
    station_id = weather.get("station_id")
    if not station_id:
        raise ValueError("Fogos.pt has no usable weather station for this incident")
    observations, _ = _request("/v2/weather/observations")
    rows: list[tuple[datetime, float, float, float, float, float]] = []
    for timestamp, stations in observations.items():
        observation = stations.get(str(station_id)) if isinstance(stations, dict) else None
        if not observation:
            continue
        values = [observation.get(key) for key in ("intensidadeVentoKM", "idDireccVento", "temperatura", "humidade", "precAcumulada")]
        try:
            values = [float(value) for value in values]
            direction_code = int(values[1])
        except (TypeError, ValueError):
            continue
        if any(value == -99 for value in values) or direction_code not in WIND_DEGREES:
            continue
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            parsed = parsed.astimezone(UTC)
        except (TypeError, ValueError):
            continue
        rows.append((parsed, values[0], WIND_DEGREES[direction_code], values[2], values[3], values[4]))
    rows.sort()
    start = workspace.start_time.astimezone(UTC)
    end = start + timedelta(minutes=workspace.simulation.duration_min)
    if len(rows) < 2 or rows[0][0] > start or rows[-1][0] < end:
        raise ValueError("Fogos.pt hourly observations do not cover this simulation interval")
    selected = [_weather_at(rows, start),
                *[row for row in rows if start < row[0] < end],
                _weather_at(rows, end)]
    if any((right[0] - left[0]).total_seconds() > 6 * 3600 for left, right in zip(selected, selected[1:])):
        raise ValueError("Fogos.pt observations contain a gap longer than six hours")
    weather_snapshot = save_snapshot(workspace.external_incident["incident_id"], "weather", observations,
        {"station_id": station_id, "rows": [[value.isoformat(), *rest] for value, *rest in selected]},
        f"{BASE_URL}/v2/weather/observations", selected[-1][0].isoformat(),
        ["Hourly IPMA station observations; history is limited to the upstream rolling window"])
    header = "timestamp,wind_speed_kmh,wind_direction_deg,temperature_c,relative_humidity_pct,precipitation_mm\n"
    body = header + "".join(f"{row[0].isoformat()},{row[1]},{row[2]},{row[3]},{row[4]},{row[5]}\n" for row in selected)
    return save_weather_series(body.encode(), f"fogos-{workspace.external_incident['incident_id']}.csv",
        {"provider": PROVIDER, "incident_id": workspace.external_incident["incident_id"],
         "snapshot_id": weather_snapshot["id"], "station_id": station_id,
         "interval_start": start.isoformat(), "interval_end": end.isoformat()})


def _weather_at(rows: list[tuple], target: datetime) -> tuple:
    for row in rows:
        if row[0] == target:
            return row
    before = max((row for row in rows if row[0] < target), key=lambda row: row[0], default=None)
    after = min((row for row in rows if row[0] > target), key=lambda row: row[0], default=None)
    if not before or not after:
        raise ValueError("Fogos.pt hourly observations do not bracket the simulation interval")
    fraction = (target - before[0]).total_seconds() / (after[0] - before[0]).total_seconds()
    direction_delta = ((after[2] - before[2] + 180) % 360) - 180
    values = [before[index] + fraction * (after[index] - before[index]) for index in (1, 3, 4, 5)]
    direction = (before[2] + fraction * direction_delta) % 360
    return (target, values[0], direction, values[1], values[2], values[3])


def run_tracking_once() -> int:
    now = datetime.now(UTC)
    stamp = now.isoformat()
    with storage.connect() as db:
        candidates = db.execute("""SELECT * FROM tracking_subscriptions
            WHERE enabled=1 AND (lease_until IS NULL OR lease_until<?)
            AND (next_details_at IS NULL OR next_details_at<=? OR next_perimeter_at IS NULL
                 OR next_perimeter_at<=? OR next_simulation_at IS NULL OR next_simulation_at<=?)""",
            (stamp, stamp, stamp, stamp)).fetchall()
    processed = 0
    for candidate in candidates:
        incident_id = candidate["incident_id"]
        lease = (now + timedelta(minutes=2)).isoformat()
        with storage.connect() as db:
            changed = db.execute("""UPDATE tracking_subscriptions SET lease_until=?
                                  WHERE provider=? AND incident_id=? AND enabled=1
                                  AND (lease_until IS NULL OR lease_until<?)""",
                                 (lease, PROVIDER, incident_id, now.isoformat())).rowcount
        if not changed:
            continue
        try:
            terminal = False
            details_due = not candidate["next_details_at"] or candidate["next_details_at"] <= stamp
            perimeter_due = not candidate["next_perimeter_at"] or candidate["next_perimeter_at"] <= stamp
            simulation_due = not candidate["next_simulation_at"] or candidate["next_simulation_at"] <= stamp
            if details_due:
                raw, normalized = fetch_incident(incident_id)
                save_snapshot(incident_id, "incident", raw, normalized, normalized["source_url"],
                              normalized.get("updated_at") or normalized.get("reported_at"))
                terminal = normalized.get("status_code") in TERMINAL_STATUS_CODES
            product_errors = []
            if terminal or perimeter_due:
                error = _capture_optional_product(incident_id, "perimeter")
                if error:
                    product_errors.append(error)
            if terminal or simulation_due:
                error = _capture_optional_product(incident_id, "pyrocast")
                if error:
                    product_errors.append(error)
            next_details = (now + DETAIL_INTERVAL).isoformat() if details_due else candidate["next_details_at"]
            next_perimeter = (now + PERIMETER_INTERVAL).isoformat() if perimeter_due or terminal else candidate["next_perimeter_at"]
            next_simulation = (now + SIMULATION_INTERVAL).isoformat() if simulation_due or terminal else candidate["next_simulation_at"]
            last_error = "; ".join(product_errors) or None
            with storage.connect() as db:
                db.execute("""UPDATE tracking_subscriptions SET enabled=?,lease_until=NULL,last_error=?,
                    failure_count=?,next_details_at=?,next_perimeter_at=?,next_simulation_at=?
                    WHERE provider=? AND incident_id=?""",
                    (0 if terminal else 1, last_error, 1 if product_errors else 0, next_details,
                     next_perimeter, next_simulation, PROVIDER, incident_id))
                db.execute("UPDATE external_incidents SET terminal=?,next_poll_at=?,last_error=? WHERE provider=? AND incident_id=?",
                           (int(terminal), next_details, last_error, PROVIDER, incident_id))
            processed += 1
        except Exception as error:
            failures = int(candidate["failure_count"] or 0) + 1
            requested = getattr(error, "retry_after_seconds", None)
            delay_seconds = requested or min(3600, 300 * (2 ** min(failures - 1, 4)))
            next_attempt = (now + timedelta(seconds=delay_seconds)).isoformat()
            _record_fetch_error(incident_id, "incident", error)
            with storage.connect() as db:
                db.execute("""UPDATE tracking_subscriptions SET lease_until=NULL,last_error=?,failure_count=?,next_details_at=?
                              WHERE provider=? AND incident_id=?""",
                           (str(error), failures, next_attempt, PROVIDER, incident_id))
                db.execute("UPDATE external_incidents SET last_error=?,next_poll_at=? WHERE provider=? AND incident_id=?",
                           (str(error), next_attempt, PROVIDER, incident_id))
    return processed


def _capture_optional_product(incident_id: str, product_type: str) -> str | None:
    try:
        fetch_product(incident_id, product_type)
        return None
    except Exception as error:
        _record_fetch_error(incident_id, product_type, error)
        return f"{product_type}: {error}"


def _record_fetch_error(incident_id: str, product_type: str, error: Exception) -> None:
    with storage.connect() as db:
        db.execute("""INSERT INTO external_fetches
            (id,provider,incident_id,product_type,snapshot_id,fetched_at,status,error)
            VALUES (?,?,?,?,NULL,?,'error',?)""",
            (uuid4().hex[:16], PROVIDER, incident_id, product_type, datetime.now(UTC).isoformat(), str(error)))


def tracking_loop(stop: Event) -> None:
    while not stop.wait(30):
        if configuration()["configured"]:
            run_tracking_once()
