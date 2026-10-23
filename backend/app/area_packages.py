from __future__ import annotations

import hashlib
import fcntl
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
import json
import math
import os
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import geopandas as gpd
import numpy as np
import osmnx as ox
import rasterio
import requests
from pyproj import Transformer
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from shapely.geometry import LineString, mapping, box

from . import preparation_checkpoints as checkpoints
from .overpass_download import OverpassClient, OverpassFailure, write_xml
from .osm_source import OSMSource

from .io import _fuel_translations
from .models import AreaPreparation, AreaPreparationCreate, AreaPreparationEstimate
from .settings import AREAS, CONFIG, PREPARATIONS, PREPARED, SOURCE_CACHE, ensure_dirs

PORTUGAL_MAINLAND_BOUNDS = (-9.65, 36.80, -6.05, 42.20)
ICNF_WATER_URL = "https://sigservices.icnf.pt/server/rest/services/BDG/Pontos_agua/MapServer/0/query"
OVERPASS_URLS = (os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter"),
                 "https://overpass.kumi.systems/api/interpreter")
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="area-preparation")
_record_lock = threading.RLock()
_current_client: ContextVar[OSMSource | OverpassClient | None] = ContextVar("area_osm_client", default=None)
ALLOWED_FIRE_MARGINS = {30: {5, 10, 25}, 20: {5, 10}, 15: {5, 10}, 10: {5}}


def package_path(package_id: str | None) -> Path:
    return AREAS / package_id if package_id else PREPARED


def package_manifest(package_id: str | None) -> dict:
    path = package_path(package_id) / "manifest.json"
    if path.exists():
        return json.loads(path.read_text())
    if package_id is None:
        return {"id": "legacy", "status": "ready", "legacy": True,
                "bounds": CONFIG["area"]["bounds"], "center": CONFIG["area"]["center"]}
    raise KeyError(package_id)


@contextmanager
def _process_lock(name: str, *, blocking: bool = True):
    PREPARATIONS.mkdir(parents=True, exist_ok=True)
    with (PREPARATIONS / name).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def create_preparation(request: AreaPreparationCreate) -> AreaPreparation:
    ensure_dirs()
    _validate_request(request)
    package_id = _package_key(request)
    with _record_lock, _process_lock(".creation.lock"):
        for path in PREPARATIONS.glob("*.json"):
            existing = AreaPreparation.model_validate_json(path.read_text())
            if existing.package_id == package_id and existing.status in {"queued", "running"}:
                return existing
        ready = AREAS / package_id / "manifest.json"
        cached = json.loads(ready.read_text()) if ready.exists() else {}
        stamp = _now()
        record = AreaPreparation(id=uuid4().hex[:12], package_id=package_id,
                                 status=cached.get("status", "ready") if ready.exists() else "queued",
                                 stage="ready" if ready.exists() else "queued",
                                 progress=100 if ready.exists() else 0, request=request,
                                 datasets=cached.get("datasets", {}), created_at=stamp, updated_at=stamp)
        _write_record(record)
        if not ready.exists():
            _executor.submit(_run, record.id)
        return record


def estimate_preparation(request: AreaPreparationCreate) -> AreaPreparationEstimate:
    _validate_location(request)
    grid = _grid_spec(request)
    cell = request.cell_size_m
    columns, rows = grid["columns"], grid["rows"]
    cell_count = rows * columns

    cost_level = _cost_level(cell_count)

    allowed, reason = True, None
    if request.fire_margin_km not in ALLOWED_FIRE_MARGINS[cell]:
        allowed = False
        choices = ", ".join(f"{value} km" for value in sorted(ALLOWED_FIRE_MARGINS[cell]))
        reason = f"{cell} m cells support fire margins of {choices}"
    elif cell_count > 3_000_000:
        allowed = False
        reason = "The prepared landscape would exceed the 3,000,000-cell limit"
    elif cell_count > 2_000_000 and cell != 30:
        allowed = False
        reason = "Landscapes above 2,000,000 cells require 30 m resolution"

    return AreaPreparationEstimate(
        fire_bounds=grid["fire_bounds"], grid_rows=rows, grid_columns=columns,
        cell_count=cell_count, area_km2=round(cell_count * cell * cell / 1_000_000, 2),
        cell_size_m=cell, cost_level=cost_level,
        requires_acknowledgement=allowed and cell_count > 1_000_000,
        allowed=allowed, blocking_reason=reason,
    )


def _cost_level(cell_count: int) -> str:
    if cell_count <= 500_000:
        return "normal"
    if cell_count <= 1_000_000:
        return "moderate"
    if cell_count <= 2_000_000:
        return "high"
    if cell_count <= 3_000_000:
        return "very_high"
    return "blocked"


def _grid_spec(request: AreaPreparationCreate) -> dict:
    cell = request.cell_size_m
    forward = Transformer.from_crs(4326, 3763, always_xy=True)
    reverse = Transformer.from_crs(3763, 4326, always_xy=True)
    points = [forward.transform(*item.coordinates) for item in request.ignitions]
    margin = request.fire_margin_km * 1000
    west = math.floor((min(x for x, _ in points) - margin) / cell) * cell
    south = math.floor((min(y for _, y in points) - margin) / cell) * cell
    east = math.ceil((max(x for x, _ in points) + margin) / cell) * cell
    north = math.ceil((max(y for _, y in points) + margin) / cell) * cell
    lon0, lat0 = reverse.transform(west, south)
    lon1, lat1 = reverse.transform(east, north)
    return {"projected_bounds": (west, south, east, north),
            "fire_bounds": (lon0, lat0, lon1, lat1),
            "columns": int(round((east - west) / cell)),
            "rows": int(round((north - south) / cell))}


def get_preparation(preparation_id: str) -> AreaPreparation:
    path = PREPARATIONS / f"{preparation_id}.json"
    if not path.exists():
        raise KeyError(preparation_id)
    return AreaPreparation.model_validate_json(path.read_text())


def cancel_preparation(preparation_id: str) -> AreaPreparation:
    with _record_lock, _process_lock(".publication.lock"):
        record = get_preparation(preparation_id)
        if record.status in {"queued", "running"}:
            (PREPARATIONS / f"{preparation_id}.cancel").touch()
            record.status, record.stage = "cancelled", "cancelled"
            record.retry_at = None
            record.updated_at = _now()
            _write_record(record)
        return record


def retry_preparation(preparation_id: str) -> AreaPreparation:
    previous = get_preparation(preparation_id)
    return create_preparation(previous.request)


def recover_preparations() -> None:
    ensure_dirs()
    for path in PREPARATIONS.glob("*.json"):
        record = AreaPreparation.model_validate_json(path.read_text())
        if record.status in {"queued", "running"}:
            try:
                with _process_lock(f".{record.package_id}.lock", blocking=False):
                    record = get_preparation(record.id)
                    if record.status not in {"queued", "running"}:
                        continue
                    record.status = "failed"
                    record.stage = "interrupted"
                    record.error = "Area preparation was interrupted; retry it to continue."
                    record.failure_code, record.retryable, record.retry_at = "interrupted", True, None
                    record.updated_at = _now()
                    _write_record(record)
            except BlockingIOError:
                # Another live worker owns this package (e.g. during an app restart).
                continue


def _run(preparation_id: str) -> None:
    record = get_preparation(preparation_id)
    with _process_lock(f".{record.package_id}.lock"):
        _run_locked(record)


def _run_locked(record: AreaPreparation) -> None:
    temporary = AREAS / f".{record.package_id}.{record.id}.tmp"
    working = PREPARATIONS / ".checkpoints-v1" / record.package_id

    def progress(**values):
        _check_cancel(record)
        if "source_progress" in values:
            record.source_progress = values["source_progress"]
            record.tile_progress = None
        if "completed" in values:
            record.tile_progress = {key: values[key] for key in ("completed", "total")}
        record.retry_at = values.get("retry_at")
        record.updated_at = _now()
        _write_record(record)

    client = OSMSource(SOURCE_CACHE, OVERPASS_URLS, working=working,
                       check_cancel=lambda: _check_cancel(record), progress=progress)
    token = _current_client.set(client)
    try:
        _check_cancel(record)
        record.status = "running"
        working.mkdir(parents=True, exist_ok=True)
        estimate = estimate_preparation(record.request)
        grid = _grid_spec(record.request)
        fire_bounds = list(estimate.fire_bounds)
        resource_bounds = _radius_bounds(record.request.center, record.request.resource_radius_km + 5)

        def step(dataset, label, percentage, build, source, optional=False):
            _stage(record, label, percentage)
            restored = checkpoints.restore(working, dataset)
            if restored and (dataset == "landscape" or client.restore_metadata(restored)):
                record.datasets[dataset] = restored
                _write_record(record)
                return
            (working / f"{dataset}.checkpoint.json").unlink(missing_ok=True)
            record.datasets[dataset] = {"status": "running", "source": source}
            _write_record(record)
            try:
                metadata = {"status": "ready", "source": source, **(build() or {})}
                if dataset != "landscape":
                    metadata["osm_fetched_at"] = client.oldest_fetched_at
                    metadata["osm_provenance"] = client.provenance
                _check_cancel(record)
                checkpoints.validate(working, dataset)
                if metadata["status"] == "ready":
                    checkpoints.save(working, dataset, metadata)
            except _Cancelled:
                raise
            except Exception as error:
                if not optional:
                    record.datasets[dataset] = {"status": "failed", "source": source, "error": str(error),
                                                "osm_provenance": client.provenance}
                    raise
                _empty_catalog(working / checkpoints.FILES[dataset][0], f"{label} preparation failed", error)
                metadata = {"status": "failed", "source": source, "error": str(error),
                            "osm_provenance": client.provenance}
            record.datasets[dataset] = metadata
            _check_cancel(record)
            _write_record(record)

        step("landscape", "terrain and land cover", 5,
             lambda: _prepare_landscape(working, fire_bounds, record.request.cell_size_m,
                                        projected_bounds=grid["projected_bounds"]),
             "Copernicus GLO-30 and ESA WorldCover 2021")
        step("roads", "roads", 48, lambda: _prepare_roads(working, resource_bounds), "OpenStreetMap")
        step("buildings", "buildings", 62,
             lambda: {"count": _prepare_buildings(working / "buildings.geojson", fire_bounds)},
             "OpenStreetMap", True)

        def resources(kind, filename):
            warnings = _prepare_resources(working / filename, record.request, kind)
            return {"status": "partial" if warnings else "ready",
                    **({"error": "; ".join(warnings)} if warnings else {})}

        step("water_points", "water points", 74,
             lambda: resources("water", "water-points.geojson"), "ICNF and OpenStreetMap", True)
        step("fire_stations", "fire stations", 87,
             lambda: resources("stations", "fire-stations.geojson"), "OpenStreetMap", True)
        partial = any(value["status"] != "ready" for value in record.datasets.values())
        _check_cancel(record)
        checkpoints.validate(working, "landscape")
        checkpoints.validate(working, "roads")
        shutil.rmtree(temporary, ignore_errors=True)
        temporary.mkdir(parents=True)
        for names in checkpoints.FILES.values():
            for name in names:
                shutil.copy2(working / name, temporary / name)
        manifest = {"id": record.package_id, "schema_version": 3, "preparation_version": 2,
                    "status": "partial" if partial else "ready", "created_at": _now(),
                    "center": record.request.center, "resource_radius_km": record.request.resource_radius_km,
                    "fire_margin_km": record.request.fire_margin_km,
                    "resource_bounds": resource_bounds, "fire_bounds": fire_bounds,
                    "cell_size_m": record.request.cell_size_m,
                    "grid_rows": estimate.grid_rows, "grid_columns": estimate.grid_columns,
                    "cell_count": estimate.cell_count, "area_km2": estimate.area_km2,
                    "cost_level": estimate.cost_level, "crs": "EPSG:3763", "datasets": record.datasets,
                    "source_resolutions_m": {"elevation": 30, "land_cover": 10},
                    "fuel_mapping": CONFIG["worldcover_to_fuel"],
                    "warning": ("WorldCover-to-fuel translation is illustrative and not locally calibrated. "
                                "Elevation originates at 30 m and land cover at 10 m.")}
        _atomic_json(temporary / "manifest.json", manifest)
        with _record_lock, _process_lock(".publication.lock"):
            _check_cancel(record)
            destination = AREAS / record.package_id
            if destination.exists():
                existing = package_manifest(record.package_id)
                record.datasets = existing["datasets"]
                partial = existing["status"] == "partial"
            else:
                os.replace(temporary, destination)
            record.status = "partial" if partial else "ready"
            record.stage, record.progress, record.error = "ready", 100, None
            record.failure_code, record.retryable = None, None
            record.retry_at, record.tile_progress = None, None
            record.source_progress = None
            record.updated_at = _now()
            _write_record(record)
    except _Cancelled:
        pass
    except Exception as error:
        # Cancellation wins even when an in-flight request fails before its next check.
        try:
            _check_cancel(record)
            record.status = "failed"
            record.error, record.updated_at = str(error), _now()
            record.failure_code = getattr(error, "code", "preparation_failed")
            record.retryable = getattr(error, "retryable", True)
            record.retry_at = None
            _write_record(record)
        except _Cancelled:
            pass
    finally:
        _current_client.reset(token)
        client.close()
        shutil.rmtree(temporary, ignore_errors=True)


def _prepare_landscape(destination: Path, bounds: list[float], cell: int = 30,
                       *, projected_bounds: tuple[float, float, float, float] | None = None) -> None:
    if projected_bounds is None:
        projected = Transformer.from_crs(4326, 3763, always_xy=True)
        west, south = projected.transform(bounds[0], bounds[1])
        east, north = projected.transform(bounds[2], bounds[3])
        west, south = math.floor(west / cell) * cell, math.floor(south / cell) * cell
        east, north = math.ceil(east / cell) * cell, math.ceil(north / cell) * cell
    else:
        west, south, east, north = projected_bounds
    width, height = int((east - west) / cell), int((north - south) / cell)
    target_transform = from_origin(west, north, cell, cell)
    elevation = np.full((height, width), np.nan, dtype="float32")
    cover = np.full((height, width), np.nan, dtype="float32")
    for lon, lat in _degree_tiles(bounds):
        stem = _copernicus_dem_stem(lon, lat)
        url = f"https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/{stem}/{stem}.tif"
        path = _download(url, SOURCE_CACHE / "copernicus-dem" / f"{stem}.tif")
        _reproject_fill(path, elevation, target_transform, Resampling.bilinear)
    for lon, lat in _worldcover_tiles(bounds):
        tile = f"{_lat(lat)}{_lon(lon)}"
        name = f"ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
        url = f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/{name}"
        path = _download(url, SOURCE_CACHE / "worldcover-2021" / name)
        _reproject_fill(path, cover, target_transform, Resampling.nearest)
    coverage = np.isfinite(elevation) & np.isfinite(cover)
    if not coverage.any():
        raise ValueError("Downloaded terrain and land-cover tiles do not cover the selected fire area")
    fuel = np.full(cover.shape, 99, dtype="int16")
    for source, target in CONFIG["worldcover_to_fuel"].items():
        fuel[cover == int(source)] = target
    elevation_clean = np.nan_to_num(elevation, nan=0).astype("float32")
    rise_y, rise_x = np.gradient(elevation_clean, cell)
    slope = np.degrees(np.arctan(np.hypot(rise_x, rise_y))).astype("float32")
    aspect = ((np.degrees(np.arctan2(rise_x, -rise_y)) + 360) % 360).astype("float32")
    anderson, load, depth = _fuel_translations(fuel)
    np.savez_compressed(destination / "landscape.npz", fuel=fuel, elevation=elevation_clean,
                        slope=slope, aspect=aspect, coverage=coverage,
                        fuel_anderson13=anderson, fuel_load_kg_m2=load, fuel_depth_m=depth)
    _atomic_json(destination / "landscape.json", {
        "transform": list(target_transform)[:6], "crs": "EPSG:3763", "cell_size_m": cell, "bounds": bounds,
        "provenance": {"kind": "public-source preparation", "elevation": "Copernicus DEM GLO-30 2021",
                       "land_cover": "ESA WorldCover 2021 v200", "fuel_mapping": CONFIG["worldcover_to_fuel"],
                       "source_resolutions_m": {"elevation": 30, "land_cover": 10},
                       "warning": ("Copernicus DEM is a 30 m surface model; finer grids interpolate terrain. "
                                   "Fuel translation is illustrative.")}})


def _prepare_roads(destination: Path, bounds: list[float]) -> None:
    west, south, east, north = bounds
    vehicle_filter = ('["highway"]["highway"!~"footway|path|steps|pedestrian|cycleway"]'
                      '["area"!="yes"]["access"!="private"]')
    graph = _download_road_graph(bounds, vehicle_filter)
    for u, v, key, data in graph.edges(keys=True, data=True):
        data["mobility_edge_id"] = f"{u}:{v}:{key}"
    ox.save_graphml(graph, destination / "roads.graphml")
    edges = ox.graph_to_gdfs(graph, nodes=False, fill_edge_geometry=True).reset_index().to_crs(3763)
    groups: dict[tuple[str, str], list] = {}
    for edge in edges.itertuples():
        osmid = str(edge.osmid)
        geometry = edge.geometry
        physical = (osmid, geometry.wkb_hex if edge.u < edge.v else LineString(geometry.coords[::-1]).wkb_hex)
        groups.setdefault(physical, []).append(edge)
    features = []
    for physical, related in groups.items():
        edge = related[0]
        osmid, geometry = str(edge.osmid), edge.geometry
        base_start, base_end = edge.geometry.coords[0], edge.geometry.coords[-1]
        refs = json.dumps([[str(item.u), str(item.v), int(item.key),
                            "forward" if item.geometry.coords[0] == base_start and item.geometry.coords[-1] == base_end else "reverse"]
                           for item in related])
        count = max(1, int(geometry.length // 100) + 1)
        points = [geometry.interpolate(i / count, normalized=True) for i in range(count + 1)]
        for index in range(count):
            part = LineString([points[index], points[index + 1]])
            segment_id = hashlib.sha1(f"{osmid}:{index}:{part.wkb_hex}".encode()).hexdigest()[:16]
            value = lambda item: str(item[0] if isinstance(item, list) else item or "")
            features.append({"segment_id": segment_id, "name": value(edge.name),
                             "road_class": value(edge.highway), "edge_refs": refs, "geometry": part})
    roads = gpd.GeoDataFrame(features, crs=3763).to_crs(4326)
    roads.to_file(destination / "roads.geojson", driver="GeoJSON")
    revision = hashlib.sha256((destination / "roads.geojson").read_bytes()).hexdigest()[:16]
    _atomic_json(destination / "roads.json", {"source": "OpenStreetMap", "count": len(roads),
                                               "revision": revision, "mobility_version": 1,
                                               "bounds": bounds, "fetched_at": _now()})


def _prepare_buildings(path: Path, bounds: list[float]) -> int:
    buildings = _download_buildings(bounds)
    features = []
    if not buildings.empty:
        if buildings.crs is None:
            buildings = buildings.set_crs(4326)
        projected = buildings.to_crs(3763)
        projected.geometry = projected.geometry.simplify(.5, preserve_topology=True)
        geographic = projected.to_crs(4326).reset_index()
        for index, row in geographic.iterrows():
            geometry = row.geometry
            if geometry is None or geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
                continue
            properties = _building_properties(row.to_dict(), index)
            features.append({"type": "Feature", "geometry": mapping(geometry), "properties": properties})
    _atomic_json(path, {"type": "FeatureCollection", "features": features, "metadata": {
        "status": "ready", "source": "OpenStreetMap", "count": len(features),
        "bounds": bounds, "fetched_at": _now(),
    }})
    return len(features)


def _building_properties(values: dict, fallback_id: object = "") -> dict:
    building_type = _text(values.get("building")) or "yes"
    height = _positive_number(values.get("height"))
    if height is not None:
        source = "reported"
    else:
        levels = _positive_number(values.get("building:levels"))
        if levels is not None:
            height, source = levels * 3, "levels"
        else:
            taller = {"apartments", "commercial", "industrial", "office", "retail", "warehouse"}
            height, source = (9 if building_type.lower() in taller else 6), "estimated"
    height = round(min(60, max(3, height)), 2)
    raw_id = _text(values.get("id")) or _text(values.get("osmid")) or _text(fallback_id)
    element = _text(values.get("element")) or _text(values.get("element_type")) or "feature"
    return {
        "osm_id": f"{element}/{raw_id}",
        "building_type": building_type,
        "height_m": height,
        "height_source": source,
        "name": _text(values.get("name")),
    }


def _positive_number(value: object) -> float | None:
    text = _text(value).replace(",", ".")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group())
    return number if number > 0 else None


def _text(value: object) -> str:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return str(value).strip()


@contextmanager
def _download_client():
    client = _current_client.get()
    if client is not None:
        yield client
    else:
        client = OSMSource(SOURCE_CACHE, OVERPASS_URLS)
        try:
            yield client
        finally:
            client.close()


def _download_buildings(bounds: list[float]):
    polygon = box(*bounds)
    with _download_client() as client, tempfile.TemporaryDirectory() as folder:
        elements = client.download(polygon, "buildings")
        if not elements or not any("building" in row.get("tags", {}) for row in elements):
            return gpd.GeoDataFrame(geometry=[], crs=4326)
        path = Path(folder) / "buildings.osm"
        write_xml(elements, path)
        return ox.features_from_xml(path, polygon=polygon, tags={"building": True})


def _prepare_resources(path: Path, request: AreaPreparationCreate, kind: str) -> list[str]:
    features, errors = [], []
    if kind == "stations":
        try:
            features.extend(_overpass(request, "response_base"))
        except _Cancelled:
            raise
        except Exception as error:
            errors.append(f"OpenStreetMap: {error}")
    else:
        try:
            features.extend(_overpass(request, "water_point"))
        except _Cancelled:
            raise
        except Exception as error:
            errors.append(f"OpenStreetMap: {error}")
        try:
            features.extend(_icnf(request))
        except _Cancelled:
            raise
        except Exception as error:
            errors.append(f"ICNF: {error}")
    if errors and not features:
        raise RuntimeError("; ".join(errors))
    payload = {"type": "FeatureCollection", "features": features,
               "metadata": {"status": "partial" if errors else "ready", "count": len(features), "fetched_at": _now(),
                            "warnings": errors,
                            "center": request.center, "radius_km": request.resource_radius_km}}
    _atomic_json(path, payload)
    return errors


def _overpass(request: AreaPreparationCreate, kind: str) -> list[dict]:
    # Query construction is centralised so every OSM dataset has the same limits.
    with _download_client() as client:
        elements = client.download(box(*_radius_bounds(request.center, request.resource_radius_km)),
                                   "stations" if kind == "response_base" else "water")
    result = {"elements": elements}
    features = []
    types = {"fire_hydrant": "hydrant", "water_tank": "tank", "fire_water_pond": "pond"}
    for item in result.get("elements", []):
        center = item.get("center", item)
        coordinates = (center.get("lon"), center.get("lat"))
        if None in coordinates or _distance_km(request.center, coordinates) > request.resource_radius_km:
            continue
        tags = item.get("tags", {})
        external_id = f"osm/{item['type']}/{item['id']}"
        properties = {"external_id": external_id, "source": "openstreetmap", "data_status": "unverified",
                      "name": tags.get("name") or ("Fire station" if kind == "response_base" else "Water point"),
                      "source_url": f"https://www.openstreetmap.org/{item['type']}/{item['id']}", "tags": tags}
        if kind == "water_point":
            properties["source_type"] = types.get(tags.get("emergency"), "other")
            properties["water"] = {"source_type": properties["source_type"], "availability": "unknown",
                                     "capacity_m3": None, "flow_l_min": None, "access_notes": "",
                                     "verification_status": "unverified"}
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": coordinates},
                         "properties": properties})
    return features


def _download_road_graph(bounds: list[float], vehicle_filter: str):
    polygon = box(*bounds)
    projected, crs = ox.projection.project_geometry(polygon)
    buffered, _ = ox.projection.project_geometry(projected.buffer(500), crs=crs, to_latlong=True)
    for tag in ("maxheight", "maxweight", "maxwidth", "surface", "tracktype", "barrier", "vehicle", "motor_vehicle"):
        if tag not in ox.settings.useful_tags_way:
            ox.settings.useful_tags_way.append(tag)
    for tag in ("barrier", "access", "vehicle", "motor_vehicle"):
        if tag not in ox.settings.useful_tags_node:
            ox.settings.useful_tags_node.append(tag)
    with _download_client() as client, tempfile.TemporaryDirectory() as folder:
        elements = client.download(buffered, "roads", vehicle_filter)
        path = Path(folder) / "roads.osm"
        write_xml(elements, path)
        graph = ox.graph_from_xml(path, simplify=False, retain_all=True, bidirectional=False)
    graph = ox.truncate.truncate_graph_polygon(graph, buffered, truncate_by_edge=False)
    graph = ox.simplification.simplify_graph(graph)
    result = ox.truncate.truncate_graph_polygon(graph, polygon, truncate_by_edge=False)
    import networkx as nx
    nx.set_node_attributes(result, ox.stats.count_streets_per_node(graph, nodes=result.nodes), "street_count")
    return result


def _icnf(request: AreaPreparationCreate) -> list[dict]:
    projected = Transformer.from_crs(4326, 3763, always_xy=True)
    center_x, center_y = projected.transform(*request.center)
    radius = request.resource_radius_km * 1000
    offset, features = 0, []
    while True:
        client = _current_client.get()
        if client:
            client.check_cancel()
        params = {"f": "geojson", "where": "1=1", "outFields": "*", "outSR": 4326,
                  "geometry": f"{center_x-radius},{center_y-radius},{center_x+radius},{center_y+radius}",
                  "geometryType": "esriGeometryEnvelope", "inSR": 3763,
                  "spatialRel": "esriSpatialRelIntersects", "resultOffset": offset, "resultRecordCount": 2000}
        response = requests.get(ICNF_WATER_URL, params=params, timeout=90)
        response.raise_for_status()
        page = response.json()
        rows = page.get("features", [])
        for feature in rows:
            coordinates = feature.get("geometry", {}).get("coordinates", [])
            if len(coordinates) != 2 or _distance_km(request.center, coordinates) > request.resource_radius_km:
                continue
            p = feature.get("properties", {})
            code = str(p.get("Codigo") or p.get("ID"))
            name = (p.get("Nome") or p.get("Local") or f"Ponto de água {code}").translate(
                str.maketrans({"ß": "á", "þ": "ç", "·": "ú"}))
            source_type = {"Tanque de Rega": "tank", "Charca": "pond", "Lago": "pond",
                           "Reservatório DFCI": "reservoir", "Albufeira de açude": "reservoir"}.get(p.get("Tipo"), "other")
            updated = (datetime.fromtimestamp(p["DataActualizacao"] / 1000, UTC).date().isoformat()
                       if p.get("DataActualizacao") else None)
            access = "; ".join(f"{label}: {p[key]}" for label, key in (
                ("Access class", "Classe"), ("Ownership", "TipoProprietario"),
                ("Water collection", "Captacao"), ("Location", "Local")) if p.get(key))
            features.append({"type": "Feature", "geometry": feature["geometry"], "properties": {
                "external_id": f"icnf/{code}", "source": "icnf", "name": name,
                "source_url": ICNF_WATER_URL.rsplit("/query", 1)[0], "source_type": source_type,
                "source_updated_at": updated, "data_status": "reported",
                "description": " · ".join(str(p[key]) for key in ("Tipo", "Freguesia", "Local") if p.get(key)),
                "notes": f"Historical ICNF record; source updated: {updated or 'not specified'}. Current availability is unknown.",
                "water": {"source_type": source_type, "availability": "unknown", "capacity_m3": p.get("VolumeUtil"),
                          "flow_l_min": None, "access_notes": access, "verification_status": "reported"},
                "source_properties": p}})
        if not page.get("exceededTransferLimit") or not rows:
            break
        offset += len(rows)
    return features


def _reproject_fill(path: Path, destination: np.ndarray, transform, resampling: Resampling) -> None:
    with rasterio.open(path) as source:
        current = np.full(destination.shape, np.nan, dtype="float32")
        reproject(source.read(1), current, src_transform=source.transform, src_crs=source.crs,
                  src_nodata=source.nodata,
                  dst_transform=transform, dst_crs="EPSG:3763", dst_nodata=np.nan, resampling=resampling)
        selected = np.isfinite(current)
        destination[selected] = current[selected]


def _download(url: str, destination: Path) -> Path:
    client = _current_client.get()
    if client:
        client.check_cancel()
    if destination.exists() and destination.stat().st_size:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, stream=True, timeout=180,
                            headers={"User-Agent": "fire-road-exposure/0.2"})
    response.raise_for_status()
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("wb") as stream:
        for chunk in response.iter_content(1024 * 1024):
            if client:
                client.check_cancel()
            if chunk:
                stream.write(chunk)
    os.replace(temporary, destination)
    return destination


def _fire_bounds(request: AreaPreparationCreate) -> list[float]:
    return list(estimate_preparation(request).fire_bounds)


def _radius_bounds(center: tuple[float, float], radius_km: float) -> list[float]:
    lon, lat = center
    return [lon - radius_km / (111.32 * math.cos(math.radians(lat))), lat - radius_km / 110.574,
            lon + radius_km / (111.32 * math.cos(math.radians(lat))), lat + radius_km / 110.574]


def _degree_tiles(bounds):
    for lat in range(math.floor(bounds[1]), math.ceil(bounds[3])):
        for lon in range(math.floor(bounds[0]), math.ceil(bounds[2])):
            yield lon, lat


def _worldcover_tiles(bounds):
    south = math.floor(bounds[1] / 3) * 3
    west = math.floor(bounds[0] / 3) * 3
    for lat in range(south, math.ceil(bounds[3]), 3):
        for lon in range(west, math.ceil(bounds[2]), 3):
            yield lon, lat


def _lat(value: int) -> str:
    return f"{'N' if value >= 0 else 'S'}{abs(value):02d}"


def _lon(value: int) -> str:
    return f"{'E' if value >= 0 else 'W'}{abs(value):03d}"


def _copernicus_dem_stem(lon: int, lat: int) -> str:
    return f"Copernicus_DSM_COG_10_{_lat(lat)}_00_{_lon(lon)}_00_DEM"


def _distance_km(first, second) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (*first, *second))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


def _validate_request(request: AreaPreparationCreate) -> None:
    estimate = estimate_preparation(request)
    if not estimate.allowed:
        raise ValueError(estimate.blocking_reason or "The requested landscape is not supported")
    if estimate.requires_acknowledgement and not request.acknowledge_high_cost:
        raise ValueError("Confirm the high computational cost before preparing this landscape")


def _validate_location(request: AreaPreparationCreate) -> None:
    west, south, east, north = PORTUGAL_MAINLAND_BOUNDS
    lon, lat = request.center
    if not west <= lon <= east or not south <= lat <= north:
        raise ValueError("Scenario center must be in mainland Portugal")
    for ignition in request.ignitions:
        if _distance_km(request.center, ignition.coordinates) > request.resource_radius_km:
            raise ValueError(f"{ignition.name} is outside the selected resource radius")


def _package_key(request: AreaPreparationCreate) -> str:
    payload = {"center": request.center, "resource_radius_km": request.resource_radius_km,
               "fire_margin_km": request.fire_margin_km, "cell_size_m": request.cell_size_m,
               "ignition_coordinates": [item.coordinates for item in request.ignitions]}
    payload["sources"] = {"dem": "copernicus-glo30-2021", "landcover": "worldcover-2021-v200",
                          "roads": "osm-live", "buildings": "osm-live", "schema": 3}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]


def _stage(record: AreaPreparation, stage: str, progress: int) -> None:
    _check_cancel(record)
    record.stage, record.progress, record.updated_at = stage, progress, _now()
    record.retry_at, record.tile_progress = None, None
    record.source_progress = None
    _write_record(record)


def _check_cancel(record: AreaPreparation) -> None:
    if (PREPARATIONS / f"{record.id}.cancel").exists():
        record.status, record.stage, record.updated_at = "cancelled", "cancelled", _now()
        record.retry_at = None
        _write_record(record)
        raise _Cancelled()


def _empty_catalog(path: Path, message: str, error: Exception) -> None:
    _atomic_json(path, {"type": "FeatureCollection", "features": [],
                        "metadata": {"status": "failed", "message": message, "error": str(error)}})


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + f".{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    os.replace(temporary, path)


def _write_record(record: AreaPreparation) -> None:
    with _record_lock:
        if (PREPARATIONS / f"{record.id}.cancel").exists() and record.status not in {"ready", "partial"}:
            record.status, record.stage, record.retry_at = "cancelled", "cancelled", None
        _atomic_json(PREPARATIONS / f"{record.id}.json", record.model_dump(mode="json"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


class _Cancelled(Exception):
    pass
