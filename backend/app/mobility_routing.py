from __future__ import annotations

import heapq
import hashlib
import json
import math
import hmac
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any

import geopandas as gpd
import networkx as nx
import osmnx as ox
from shapely.geometry import LineString, mapping

from .models import MobilityRouteRequest, VehicleProfile
from .storage import connect


SPEEDS = {"motorway": 90, "trunk": 75, "primary": 60, "secondary": 50,
          "tertiary": 40, "residential": 30, "living_street": 15,
          "service": 20, "unclassified": 30, "track": 15}
BLOCKING_REPORTS = {"blocked", "restricted"}

def _preview_key() -> bytes:
    configured = os.getenv("FIRELINE_ROUTE_PREVIEW_KEY")
    if configured:
        return hashlib.sha256(configured.encode()).digest()
    # One database-backed key works across API workers and survives restarts.
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS mobility_route_signing (id INTEGER PRIMARY KEY CHECK(id=1), secret TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO mobility_route_signing VALUES (1,?)", (secrets.token_hex(32),))
        row = db.execute("SELECT secret FROM mobility_route_signing WHERE id=1").fetchone()
    return bytes.fromhex(row["secret"])


def route_mobility(prepared: Path, request: MobilityRouteRequest, vehicle: VehicleProfile,
                   reports: list[dict[str, Any]]) -> dict[str, Any]:
    if vehicle.vehicle_class == "aircraft":
        raise ValueError("Os meios aéreos não utilizam o planeamento de percursos rodoviários.")
    graph_path = prepared / "roads.graphml"
    road_path = prepared / "roads.geojson"
    if not graph_path.exists() or not road_path.exists():
        raise ValueError("This area has no prepared road network")
    revision = _revision(prepared)
    graph = _graph(str(graph_path), revision)
    edge_segments = _edge_segments(str(graph_path), str(road_path), revision)
    restrictions = _report_index(reports)
    origin = _nearest_node(graph, request.origin.coordinates)
    destination = _nearest_node(graph, request.destination.coordinates)
    connector_origin = _distance(graph, origin, request.origin.coordinates)
    connector_destination = _distance(graph, destination, request.destination.coordinates)
    primary = _path(graph, origin, destination, vehicle, restrictions, edge_segments)
    if not primary:
        return {"status": "unavailable", "message": "No route is available for this vehicle and the current reports.",
                "routes": [], "origin_connector_m": connector_origin,
                "destination_connector_m": connector_destination, "data_quality": _quality(prepared)}
    paths = [primary]
    for edge in primary[:12]:
        if len(paths) > request.alternatives:
            break
        candidate = _path(graph, origin, destination, vehicle, restrictions, edge_segments, {edge})
        if candidate and tuple(candidate) not in {tuple(path) for path in paths}:
            overlap = len(set(candidate) & set(primary)) / max(1, len(set(candidate) | set(primary)))
            if overlap < .92:
                paths.append(candidate)
    options = [_payload(graph, path, vehicle, restrictions, edge_segments,
                        "Recomendada" if index == 0 else f"Alternativa {index}")
               for index, path in enumerate(paths)]
    warnings = []
    if connector_origin > 100:
        warnings.append(f"A origem está a {round(connector_origin)} m da estrada preparada; confirme o ponto de acesso.")
    if connector_destination > 100:
        warnings.append(f"O destino está a {round(connector_destination)} m da estrada preparada; confirme o ponto de acesso.")
    quality = _quality(prepared)
    if quality == "legacy":
        warnings.append("Pacote rodoviário antigo: algumas limitações de veículos podem não estar disponíveis.")
    primary_status = "unknown" if warnings or options[0]["unknown_constraints"] else "clear"
    result = {"status": primary_status, "message": "Sem conflito registado." if primary_status == "clear" else "Requer confirmação das limitações indicadas.",
            "routes": options, "selected": options[0], "segment_ids": options[0]["segment_ids"],
            "restrictions_revision": restrictions_revision(reports),
            "warnings": warnings, "origin_connector_m": connector_origin,
            "destination_connector_m": connector_destination, "data_quality": quality,
            "departure_at": request.departure_at.isoformat(), "prepared_revision": revision,
            "vehicle_revision": vehicle.revision,
            "assumption": "Tempos estimados; sem conflito registado não significa percurso seguro."}
    result["preview_signature"] = preview_signature(request, result, vehicle)
    return result


def preview_signature(request: MobilityRouteRequest, route: dict[str, Any], vehicle: VehicleProfile) -> str:
    """Authenticate every field that can alter an assignment or its selected path."""
    signed = {"request": request.model_dump(mode="json"), "route": route,
              "vehicle": vehicle.model_dump(mode="json")}
    signed["route"] = {key: value for key, value in route.items() if key != "preview_signature"}
    canonical = json.dumps(signed, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hmac.new(_preview_key(), canonical, hashlib.sha256).hexdigest()


def restrictions_revision(reports: list[dict[str, Any]]) -> str:
    values = [{key: report.get(key) for key in ("id", "revision", "status", "kind", "segment_id", "direction", "affected_vehicle_classes")}
              for report in reports]
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]


def _revision(prepared: Path) -> str:
    metadata = prepared / "roads.json"
    return json.loads(metadata.read_text()).get("revision", "unknown") if metadata.exists() else "unknown"


def _quality(prepared: Path) -> str:
    metadata = prepared / "roads.json"
    version = json.loads(metadata.read_text()).get("mobility_version", 0) if metadata.exists() else 0
    return "exact" if version >= 1 else "legacy"


@lru_cache(maxsize=12)
def _graph(path: str, revision: str) -> nx.MultiDiGraph:
    graph = ox.load_graphml(path)
    overlay = Path(path).with_name("exercise-road-assumptions.json")
    if overlay.exists():
        values = json.loads(overlay.read_text())
        if values.get("road_revision") != revision:
            raise ValueError("A revisão dos pressupostos rodoviários de exercício não corresponde ao pacote.")
        for item in values.get("sections", []):
            edge = tuple(item["edge"])
            if not graph.has_edge(*edge):
                raise ValueError("Um pressuposto de exercício refere um troço inexistente.")
            graph.edges[edge].update(item["attributes"])
            graph.edges[edge]["exercise_assumption"] = item.get("description", "Pressuposto fictício de exercício")
    for _, _, _, data in graph.edges(keys=True, data=True):
        road_class = _first(data.get("highway")) or "unclassified"
        speed = _number(data.get("maxspeed")) or SPEEDS.get(road_class, 25)
        data["travel_min"] = float(data.get("length", 0)) / (speed * 1000 / 60)
    return graph


@lru_cache(maxsize=12)
def _edge_segments(graph_path: str, road_path: str, revision: str) -> dict[tuple[Any, Any, Any], list[tuple[str, str]]]:
    graph = _graph(graph_path, revision)
    node_lookup = {str(node): node for node in graph.nodes}
    exact: dict[tuple[Any, Any, Any], list[tuple[str, str]]] = {}
    roads = gpd.read_file(road_path)
    if "edge_refs" in roads.columns:
        for row in roads.itertuples():
            try:
                refs = json.loads(row.edge_refs) if isinstance(row.edge_refs, str) else row.edge_refs
            except (ValueError, TypeError):
                refs = []
            for ref in refs or []:
                edge = (node_lookup.get(str(ref[0]), ref[0]), node_lookup.get(str(ref[1]), ref[1]), int(ref[2]))
                exact.setdefault(edge, []).append((str(row.segment_id), str(ref[3]) if len(ref) > 3 else "both"))
        if exact:
            return exact
    projected_roads = roads.to_crs(3763)
    index = projected_roads.sindex
    edges = ox.graph_to_gdfs(graph, nodes=False, fill_edge_geometry=True).to_crs(3763)
    for edge, row in edges.iterrows():
        candidates = list(index.query(row.geometry.buffer(10), predicate="intersects"))
        matched = projected_roads.iloc[candidates] if candidates else projected_roads.iloc[[]]
        matched = matched[matched.geometry.distance(row.geometry) <= 10]
        values = []
        for matched_row in matched.itertuples():
            edge_values = list(row.geometry.coords)
            road_values = list(matched_row.geometry.coords)
            same = ((edge_values[0][0]-road_values[0][0])**2 + (edge_values[0][1]-road_values[0][1])**2 +
                    (edge_values[-1][0]-road_values[-1][0])**2 + (edge_values[-1][1]-road_values[-1][1])**2)
            reverse = ((edge_values[0][0]-road_values[-1][0])**2 + (edge_values[0][1]-road_values[-1][1])**2 +
                       (edge_values[-1][0]-road_values[0][0])**2 + (edge_values[-1][1]-road_values[0][1])**2)
            values.append((str(matched_row.segment_id), "forward" if same <= reverse else "reverse"))
        exact[edge] = values
    return exact


def _report_index(reports: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        if report.get("status") not in {"pending", "confirmed"} or not report.get("segment_id"):
            continue
        if report.get("kind") == "reopening" and report.get("status") != "confirmed":
            continue
        result.setdefault(report["segment_id"], []).append(report)
    return result


def _path(graph, origin, destination, vehicle, reports, edge_segments, banned=None):
    banned = banned or set()
    queue = [(0.0, 0, origin)]
    best = {origin: 0.0}
    previous = {}
    serial = 0
    while queue:
        minute, _, node = heapq.heappop(queue)
        if minute != best.get(node):
            continue
        if node == destination:
            break
        for u, v, key, data in graph.out_edges(node, keys=True, data=True):
            edge = (u, v, key)
            if edge in banned or not _eligible(data, vehicle) or not _eligible_node(graph.nodes[v]):
                continue
            if _blocked(edge, vehicle, reports, edge_segments):
                continue
            finish = minute + float(data["travel_min"])
            if finish < best.get(v, math.inf):
                best[v] = finish
                previous[v] = edge
                serial += 1
                heapq.heappush(queue, (finish, serial, v))
    if destination not in best:
        return None
    path, node = [], destination
    while node != origin:
        edge = previous[node]
        path.append(edge)
        node = edge[0]
    return list(reversed(path))


def _eligible(data, vehicle: VehicleProfile) -> bool:
    if vehicle.vehicle_class == "aircraft":
        return False
    if _first(data.get("access")) in {"no", "private"} or _first(data.get("motor_vehicle")) == "no":
        return False
    limits = ((vehicle.width_m, data.get("maxwidth")), (vehicle.height_m, data.get("maxheight")),
              (vehicle.weight_t, data.get("maxweight")))
    if any(actual is not None and _number(limit) is not None and actual > _number(limit) for actual, limit in limits):
        return False
    surface = _first(data.get("surface"))
    if surface in {"unpaved", "gravel", "dirt", "ground", "sand"} and not vehicle.off_road:
        return False
    return True


def _eligible_node(data) -> bool:
    barrier = _first(data.get("barrier"))
    if barrier in {"bollard", "block", "jersey_barrier", "cycle_barrier"}:
        return False
    return _first(data.get("access")) not in {"no", "private"}


def _blocked(edge, vehicle, reports, edge_segments):
    for segment, edge_direction in edge_segments.get(edge, []):
        items = reports.get(segment, [])
        for item in items:
            if item["kind"] not in BLOCKING_REPORTS:
                continue
            if item.get("direction", "both") not in {"both", edge_direction}:
                continue
            classes = item.get("affected_vehicle_classes") or []
            if not classes or vehicle.vehicle_class in classes:
                return True
    return False


def _payload(graph, path, vehicle, reports, edge_segments, label):
    coordinates, distance, duration, segments, roads, unknown = [], 0.0, 0.0, [], [], []
    for edge in path:
        u, v, _ = edge
        data = graph.edges[edge]
        geometry = data.get("geometry") or LineString([(graph.nodes[u]["x"], graph.nodes[u]["y"]),
                                                        (graph.nodes[v]["x"], graph.nodes[v]["y"])])
        values = list(geometry.coords)
        if coordinates and coordinates[-1] != values[0]:
            values.reverse()
        coordinates.extend(values if not coordinates else values[1:])
        distance += float(data.get("length", 0))
        duration += float(data.get("travel_min", 0))
        segments.extend(segment for segment, _ in edge_segments.get(edge, []))
        name = _first(data.get("name")) or "Estrada sem nome"
        if not roads or roads[-1] != name:
            roads.append(name)
        if vehicle.width_m is not None and data.get("maxwidth") is None:
            unknown.append(f"largura desconhecida em {name}")
        if vehicle.weight_t is not None and data.get("maxweight") is None:
            unknown.append(f"limite de peso desconhecido em {name}")
        if vehicle.height_m is not None and data.get("maxheight") is None:
            unknown.append(f"altura livre desconhecida em {name}")
        if _first(graph.nodes[v].get("barrier")) in {"gate", "lift_gate"}:
            unknown.append(f"estado do portão desconhecido em {name}")
    return {"label": label, "duration_min": duration, "distance_km": distance / 1000,
            "segment_ids": sorted(set(segments)), "road_names": roads,
            "unknown_constraints": sorted(set(unknown))[:8],
            "feature": {"type": "Feature", "properties": {"label": label},
                        "geometry": mapping(LineString(coordinates))}}


def _nearest_node(graph, coordinates):
    lon, lat = coordinates
    scale = math.cos(math.radians(lat))
    return min(graph.nodes, key=lambda node: (float(graph.nodes[node]["y"]) - lat) ** 2 +
               ((float(graph.nodes[node]["x"]) - lon) * scale) ** 2)


def _distance(graph, node, coordinates):
    lat1, lon1 = math.radians(coordinates[1]), math.radians(coordinates[0])
    lat2, lon2 = math.radians(float(graph.nodes[node]["y"])), math.radians(float(graph.nodes[node]["x"]))
    a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def _first(value):
    return str(value[0] if isinstance(value, list) and value else value or "").lower()


def _number(value):
    if value is None:
        return None
    try:
        return float(str(_first(value)).replace(",", ".").split()[0])
    except ValueError:
        return None
