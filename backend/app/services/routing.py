from __future__ import annotations

import heapq
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import geopandas as gpd
import networkx as nx
import osmnx as ox
from shapely.geometry import LineString, mapping, shape

from ..models import RoadClosure, RouteAnalysisRequest
from ..settings import PREPARED


SPEEDS_KMH = {
    "motorway": 90, "motorway_link": 55, "trunk": 75, "trunk_link": 50,
    "primary": 60, "primary_link": 45, "secondary": 50, "secondary_link": 40,
    "tertiary": 40, "tertiary_link": 35, "residential": 30, "living_street": 15,
    "service": 20, "unclassified": 30, "track": 15,
}


def analyse_routes(run_roads: Path, request: RouteAnalysisRequest, prepared: Path | None = None) -> dict[str, Any]:
    prepared = prepared or PREPARED
    revision = _roads_revision(prepared)
    graph = _road_graph(revision, str(prepared / "roads.graphml"))
    base_context = _cached_edge_context(str(run_roads), run_roads.stat().st_mtime_ns,
                                        revision, str(prepared / "roads.graphml"), request.exposure_buffer_m)
    closure_by_segment: dict[str, list[RoadClosure]] = {}
    for closure in request.closures:
        closure_by_segment.setdefault(closure.segment_id, []).append(closure)
    context = {edge: {**details, "closures": [closure for segment in details["segments"]
                                              for closure in closure_by_segment.get(segment, [])
                                              if closure.direction == "both"
                                              or (closure.direction == "forward") == details["segment_forward"].get(segment, True)]}
               for edge, details in base_context.items()}
    origin = _nearest_node(graph, request.origin.coordinates)
    destination = _nearest_node(graph, request.destination.coordinates)

    baseline = _static_path(graph, origin, destination)
    baseline_conflicts = _path_conflicts(graph, baseline, request.departure_min, context) if baseline else []
    primary = _time_path(graph, origin, destination, request.departure_min, context)
    routes = _alternatives(graph, primary, origin, destination, request.departure_min,
                           context, request.alternatives)
    payload_routes = [_route_payload(graph, route, request.departure_min, context,
                                     "Primary" if index == 0 else f"Alternative {index}",
                                     request.simulation_horizon_min)
                      for index, route in enumerate(routes)]

    shared = _shared_segments(payload_routes)
    for route in payload_routes:
        route["shared_vulnerable_segments"] = [item for item in route["exposed_segments"] if item in shared]

    withdrawal = None
    if request.withdrawal_destination and primary:
        access = payload_routes[0]
        withdrawal_departure = request.departure_min + access["duration_min"] + request.on_scene_min
        withdrawal_node = _nearest_node(graph, request.withdrawal_destination.coordinates)
        return_path = _time_path(graph, destination, withdrawal_node, withdrawal_departure, context)
        if return_path:
            withdrawal = _route_payload(graph, return_path, withdrawal_departure, context, "Withdrawal",
                                        request.simulation_horizon_min)
        else:
            withdrawal = {
                "label": "Withdrawal", "status": "unavailable", "departure_min": withdrawal_departure,
                "message": "No withdrawal route remains under the selected fire and closure assumptions.",
            }

    horizon = request.simulation_horizon_min
    return {
        "origin": request.origin.model_dump(), "destination": request.destination.model_dump(),
        "departure_min": request.departure_min, "routes": payload_routes,
        "baseline_conflicts": baseline_conflicts, "withdrawal": withdrawal,
        "snap": {
            "origin_distance_m": _node_distance_m(graph, origin, request.origin.coordinates),
            "destination_distance_m": _node_distance_m(graph, destination, request.destination.coordinates),
        },
        "assumptions": {
            "fire_rule": "A road is excluded when modelled exposure occurs before the vehicle finishes crossing it.",
            "speed_source": "Planning speeds estimated from OpenStreetMap road classes; not emergency-response measurements.",
            "simulation_horizon_min": horizon,
        },
    }


def _roads_revision(prepared: Path | None = None) -> str:
    path = (prepared or PREPARED) / "roads.json"
    return json.loads(path.read_text()).get("revision", "unknown") if path.exists() else "unknown"


@lru_cache(maxsize=12)
def _road_graph(revision: str, graph_path: str | None = None) -> nx.MultiDiGraph:
    path = Path(graph_path) if graph_path else PREPARED / "roads.graphml"
    if not path.exists():
        raise ValueError("The routable road network has not been prepared")
    graph = ox.load_graphml(path)
    for _, _, _, data in graph.edges(keys=True, data=True):
        road_class = data.get("highway", "unclassified")
        if isinstance(road_class, list):
            road_class = road_class[0]
        speed = _maxspeed(data.get("maxspeed")) or SPEEDS_KMH.get(str(road_class), 25)
        length = float(data.get("length", 0))
        data["travel_min"] = length / (speed * 1000 / 60) if speed > 0 else math.inf
    return graph


def _maxspeed(value: Any) -> float | None:
    if isinstance(value, list):
        values = [_maxspeed(item) for item in value]
        return min((item for item in values if item), default=None)
    if value is None:
        return None
    try:
        return float(str(value).split()[0])
    except ValueError:
        return None


@lru_cache(maxsize=24)
def _cached_edge_context(run_roads: str, modified_ns: int, roads_revision: str,
                         graph_path: str, buffer_m: float) -> dict[tuple[Any, Any, Any], dict[str, Any]]:
    graph = _road_graph(roads_revision, graph_path)
    roads = gpd.read_file(run_roads).to_crs(3763)
    edges = ox.graph_to_gdfs(graph, nodes=False, fill_edge_geometry=True).to_crs(3763)
    context: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    search_distance = max(8, min(buffer_m, 50))
    index = roads.sindex
    for edge_id, row in edges.iterrows():
        geometry = row.geometry
        candidates = list(index.query(geometry.buffer(search_distance), predicate="intersects"))
        matched = roads.iloc[candidates] if candidates else roads.iloc[[]]
        matched = matched[matched.geometry.distance(geometry) <= search_distance]
        finite = [float(value) for value in matched.get("first_exposure_min", []) if value is not None and not math.isnan(float(value))]
        segment_ids = [str(value) for value in matched.get("segment_id", [])]
        segment_forward = {}
        for matched_row in matched.itertuples():
            edge_start, edge_end = geometry.coords[0], geometry.coords[-1]
            road_start, road_end = matched_row.geometry.coords[0], matched_row.geometry.coords[-1]
            same = ((edge_start[0] - road_start[0]) ** 2 + (edge_start[1] - road_start[1]) ** 2
                    + (edge_end[0] - road_end[0]) ** 2 + (edge_end[1] - road_end[1]) ** 2)
            reverse = ((edge_start[0] - road_end[0]) ** 2 + (edge_start[1] - road_end[1]) ** 2
                       + (edge_end[0] - road_start[0]) ** 2 + (edge_end[1] - road_start[1]) ** 2)
            segment_forward[str(matched_row.segment_id)] = same <= reverse
        coverage_unknown = matched.empty or any(value == "unknown" for value in matched.get("coverage", []))
        context[edge_id] = {
            "deadline": min(finite) if finite else None,
            "unknown": coverage_unknown,
            "segments": segment_ids,
            "segment_forward": segment_forward,
        }
    return context


def _nearest_node(graph: nx.MultiDiGraph, coordinates: tuple[float, float]):
    longitude, latitude = coordinates
    longitude_scale = math.cos(math.radians(latitude))
    return min(graph.nodes, key=lambda node: (
        (float(graph.nodes[node]["y"]) - latitude) ** 2
        + ((float(graph.nodes[node]["x"]) - longitude) * longitude_scale) ** 2
    ))


def _node_distance_m(graph: nx.MultiDiGraph, node, coordinates: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(coordinates[1]), math.radians(coordinates[0])
    lat2, lon2 = math.radians(float(graph.nodes[node]["y"])), math.radians(float(graph.nodes[node]["x"]))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _static_path(graph: nx.MultiDiGraph, origin, destination):
    try:
        nodes = nx.shortest_path(graph, origin, destination, weight="travel_min")
    except nx.NetworkXNoPath:
        return None
    return _node_path_to_edges(graph, nodes)


def _node_path_to_edges(graph: nx.MultiDiGraph, nodes: list) -> list[tuple[Any, Any, Any]]:
    path = []
    for left, right in zip(nodes, nodes[1:]):
        key = min(graph[left][right], key=lambda item: graph[left][right][item]["travel_min"])
        path.append((left, right, key))
    return path


def _time_path(graph: nx.MultiDiGraph, origin, destination, departure: float,
               context: dict, banned: set[tuple[Any, Any, Any]] | None = None):
    banned = banned or set()
    queue = [(departure, 0, origin)]
    best = {origin: departure}
    previous = {}
    serial = 0
    while queue:
        minute, _, node = heapq.heappop(queue)
        if minute != best.get(node):
            continue
        if node == destination:
            break
        for _, neighbour, key, data in graph.out_edges(node, keys=True, data=True):
            edge = (node, neighbour, key)
            if edge in banned:
                continue
            finish = minute + float(data["travel_min"])
            if _edge_conflicts(edge, minute, finish, context):
                continue
            if finish < best.get(neighbour, math.inf):
                best[neighbour] = finish
                previous[neighbour] = edge
                serial += 1
                heapq.heappush(queue, (finish, serial, neighbour))
    if destination not in best:
        return None
    path, node = [], destination
    while node != origin:
        edge = previous[node]
        path.append(edge)
        node = edge[0]
    return list(reversed(path))


def _edge_conflicts(edge, start: float, finish: float, context: dict) -> bool:
    details = context.get(edge, {})
    deadline = details.get("deadline")
    if deadline is not None and deadline <= finish:
        return True
    return any(closure.starts_min <= finish and (closure.ends_min is None or closure.ends_min >= start)
               for closure in details.get("closures", []))


def _path_conflicts(graph, path, departure, context) -> list[dict[str, Any]]:
    conflicts, minute = [], departure
    for edge in path:
        data = graph.edges[edge]
        finish = minute + float(data["travel_min"])
        details = context.get(edge, {})
        deadline = details.get("deadline")
        if deadline is not None and deadline <= finish:
            conflicts.append({"type": "fire", "road": _road_name(data), "exposure_min": deadline,
                              "vehicle_entry_min": minute, "vehicle_exit_min": finish})
        for closure in details.get("closures", []):
            if closure.starts_min <= finish and (closure.ends_min is None or closure.ends_min >= minute):
                conflicts.append({"type": "closure", "road": closure.road_name, "reason": closure.reason,
                                  "starts_min": closure.starts_min, "ends_min": closure.ends_min})
        minute = finish
    return conflicts[:20]


def _alternatives(graph, primary, origin, destination, departure, context, count):
    if not primary:
        return []
    paths = [primary]
    candidates = []
    sample = primary if len(primary) <= 12 else [primary[round(index * (len(primary) - 1) / 11)] for index in range(12)]
    signatures = {tuple(primary)}
    for edge in sample:
        candidate = _time_path(graph, origin, destination, departure, context, {edge})
        if candidate and tuple(candidate) not in signatures:
            signatures.add(tuple(candidate))
            candidates.append(candidate)
    candidates.sort(key=lambda path: sum(float(graph.edges[edge]["travel_min"]) for edge in path))
    for candidate in candidates:
        if len(paths) >= count + 1:
            break
        overlap = len(set(candidate) & set(primary)) / max(1, len(set(candidate) | set(primary)))
        if overlap < .92:
            paths.append(candidate)
    return paths


def _route_payload(graph, path, departure, context, label, horizon=None):
    coordinates, distance, minute = [], 0.0, departure
    unknown, margins, exposed_segments = [], [], []
    for edge in path:
        u, v, _ = edge
        data = graph.edges[edge]
        geometry = data.get("geometry") or LineString([
            (graph.nodes[u]["x"], graph.nodes[u]["y"]),
            (graph.nodes[v]["x"], graph.nodes[v]["y"]),
        ])
        values = list(geometry.coords)
        if coordinates and coordinates[-1] != values[0]:
            values.reverse()
        coordinates.extend(values if not coordinates else values[1:])
        distance += float(data.get("length", 0))
        finish = minute + float(data["travel_min"])
        details = context.get(edge, {})
        if details.get("unknown"):
            unknown.append(_road_name(data))
        if details.get("deadline") is not None:
            margins.append(float(details["deadline"]) - finish)
            exposed_segments.extend(details.get("segments", []))
        minute = finish
    beyond_horizon = horizon is not None and minute > horizon
    status = "unknown" if unknown or beyond_horizon else "clear"
    message = ("The journey extends beyond the selected simulation horizon."
               if beyond_horizon else
               "No modelled conflict within this journey; some road coverage is unknown."
               if unknown else "No modelled conflict within this journey.")
    return {
        "label": label, "status": status, "message": message, "departure_min": departure,
        "arrival_min": minute, "duration_min": minute - departure, "distance_km": distance / 1000,
        "closest_fire_margin_min": min(margins) if margins else None,
        "unknown_roads": sorted(set(unknown))[:10], "exposed_segments": sorted(set(exposed_segments)),
        "feature": {"type": "Feature", "properties": {"label": label, "status": status},
                    "geometry": mapping(LineString(coordinates))},
    }


def _road_name(data) -> str:
    value = data.get("name") or "Unnamed road"
    return str(value[0] if isinstance(value, list) else value)


def _shared_segments(routes: list[dict[str, Any]]) -> set[str]:
    if len(routes) < 2:
        return set()
    counts: dict[str, int] = {}
    for route in routes:
        for segment in set(route["exposed_segments"]):
            counts[segment] = counts.get(segment, 0) + 1
    return {segment for segment, count in counts.items() if count > 1}
