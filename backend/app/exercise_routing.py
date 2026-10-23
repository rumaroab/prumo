from __future__ import annotations

import heapq
import json
import math
from pathlib import Path
from typing import Any

from .mobility_routing import (_blocked, _distance, _edge_segments, _eligible, _eligible_node, _graph,
                               _nearest_node, _payload, _quality, _report_index, _revision,
                               restrictions_revision)
from .models import RoadClosure, VehicleProfile
from .services.routing import _cached_edge_context
from .area_packages import package_path
from .io import load_result
from .services.exposure import ANALYSIS_VERSION, analyse, roads_revision
from .settings import RUNS
from .storage import get_run


def assess_exercise_route(prepared: Path, vehicle: VehicleProfile, reports: list[dict[str, Any]],
                          closures: list[RoadClosure], origin, destination, departure_min: float,
                          service_duration_min: float = 0, withdrawal_destination=None,
                          run_roads: Path | None = None, lead_time_min: float = 10,
                          forecast_horizon_min: float | None = None, alternatives: int = 2) -> dict[str, Any]:
    graph_path, road_path = prepared / "roads.graphml", prepared / "roads.geojson"
    if not graph_path.exists() or not road_path.exists():
        raise ValueError("This exercise has no prepared road network")
    revision = _revision(prepared)
    graph = _graph(str(graph_path), revision)
    edge_segments = _edge_segments(str(graph_path), str(road_path), revision)
    indexed_reports = _report_index(reports)
    fire_context = {}
    if run_roads:
        fire_context = _cached_edge_context(str(run_roads), run_roads.stat().st_mtime_ns,
                                            revision, str(graph_path), 30)
    timed_closures: dict[str, list[RoadClosure]] = {}
    for closure in closures:
        timed_closures.setdefault(closure.segment_id, []).append(closure)
    start = _nearest_node(graph, origin.coordinates)
    end = _nearest_node(graph, destination.coordinates)
    primary = _time_vehicle_path(graph, start, end, departure_min, vehicle, indexed_reports,
                                 edge_segments, fire_context, timed_closures, lead_time_min)
    paths = [primary] if primary else []
    if primary:
        for edge in primary[:12]:
            if len(paths) > alternatives:
                break
            candidate = _time_vehicle_path(graph, start, end, departure_min, vehicle, indexed_reports,
                                           edge_segments, fire_context, timed_closures, lead_time_min, {edge})
            if candidate and tuple(candidate) not in {tuple(value) for value in paths}:
                overlap = len(set(candidate) & set(primary)) / max(1, len(set(candidate) | set(primary)))
                if overlap < .92:
                    paths.append(candidate)
    options = [_exercise_payload(graph, path, vehicle, indexed_reports, edge_segments, fire_context,
                                 departure_min, lead_time_min, forecast_horizon_min,
                                 "Primary" if index == 0 else f"Alternative {index}")
               for index, path in enumerate(paths)]
    withdrawal = None
    if primary and withdrawal_destination:
        first = options[0]
        leave = departure_min + first["duration_min"] + service_duration_min
        withdrawal_node = _nearest_node(graph, withdrawal_destination.coordinates)
        path = _time_vehicle_path(graph, end, withdrawal_node, leave, vehicle, indexed_reports,
                                  edge_segments, fire_context, timed_closures, lead_time_min)
        withdrawal = (_exercise_payload(graph, path, vehicle, indexed_reports, edge_segments, fire_context,
                                         leave, lead_time_min, forecast_horizon_min, "Withdrawal") if path else
                      {"label": "Withdrawal", "status": "unavailable", "departure_min": leave,
                       "message": "No withdrawal route remains under the selected constraints."})
    unknown = any(value["status"] == "unknown" for value in options)
    return {"status": "unavailable" if not options else "unknown" if unknown else "clear",
            "message": "No route is available." if not options else "Route requires review." if unknown else "No conflict found in assessed coverage.",
            "routes": options, "selected": options[0] if options else None, "withdrawal": withdrawal,
            "origin_connector_m": _distance(graph, start, origin.coordinates),
            "destination_connector_m": _distance(graph, end, destination.coordinates),
            "data_quality": _quality(prepared), "restrictions_revision": restrictions_revision(reports),
            "forecast_status": "assessed" if run_roads else "not_assessed",
            "assumptions": {"lead_time_min": lead_time_min,
                            "message": "Travel times are planning estimates, not field measurements."}}


def snapshot_route_assessor(snapshot: dict[str, Any], forecast_id: str | None = None):
    """Return the unified vehicle/report/fire assessor used by plan evaluation."""
    prepared = package_path(snapshot.get("prepared_road_package_id"))
    if not (prepared / "roads.graphml").exists() or not (prepared / "roads.geojson").exists():
        return None
    run_roads, horizon = None, None
    if forecast_id:
        run = get_run(forecast_id)
        run_roads = RUNS / run.id / "roads-30m.geojson"
        cached = json.loads(run_roads.read_text()) if run_roads.exists() else {}
        if cached.get("analysis_version") != ANALYSIS_VERSION or cached.get("roads_revision") != roads_revision(prepared):
            analyse(load_result(RUNS / run.id), 30, RUNS / run.id, prepared)
        horizon = run.scenario.duration_min
    closures = [RoadClosure.model_validate(value) for value in snapshot.get("closures", [])]
    reports = snapshot.get("road_reports", [])
    lead = snapshot.get("forecast_lead_time_min", 10)

    def assess(unit, vehicle, origin, destination, departure, service_duration, withdrawal):
        from .exercise_models import ExerciseLocation
        return assess_exercise_route(prepared, VehicleProfile.model_validate(vehicle), reports, closures,
            ExerciseLocation(name="Origin", coordinates=origin),
            ExerciseLocation(name="Destination", coordinates=destination), departure, service_duration,
            ExerciseLocation(name="Withdrawal", coordinates=withdrawal) if withdrawal else None,
            run_roads, lead, horizon, 2)
    return assess


def _time_vehicle_path(graph, origin, destination, departure, vehicle, reports, edge_segments,
                       fire_context, timed_closures, lead, banned=None):
    banned = banned or set()
    queue, best, previous, serial = [(departure, 0, origin)], {origin: departure}, {}, 0
    while queue:
        minute, _, node = heapq.heappop(queue)
        if minute != best.get(node): continue
        if node == destination: break
        for u, v, key, data in graph.out_edges(node, keys=True, data=True):
            edge = (u, v, key)
            if edge in banned or not _eligible(data, vehicle) or not _eligible_node(graph.nodes[v]): continue
            if _blocked(edge, vehicle, reports, edge_segments): continue
            finish = minute + float(data["travel_min"])
            context = fire_context.get(edge, {})
            deadline = context.get("deadline")
            if deadline is not None and finish >= deadline - lead: continue
            blocked = False
            for segment, direction in edge_segments.get(edge, []):
                for closure in timed_closures.get(segment, []):
                    if closure.direction not in {"both", direction}: continue
                    if closure.starts_min <= finish and (closure.ends_min is None or closure.ends_min >= minute):
                        blocked = True
            if blocked: continue
            if finish < best.get(v, math.inf):
                best[v], previous[v], serial = finish, edge, serial + 1
                heapq.heappush(queue, (finish, serial, v))
    if destination not in best: return None
    path, node = [], destination
    while node != origin:
        edge = previous[node]; path.append(edge); node = edge[0]
    return list(reversed(path))


def _exercise_payload(graph, path, vehicle, reports, edge_segments, fire_context, departure,
                      lead, horizon, label):
    base = _payload(graph, path, vehicle, reports, edge_segments, label)
    minute, margins, coverage_unknown = departure, [], False
    for edge in path:
        minute += float(graph.edges[edge]["travel_min"])
        context = fire_context.get(edge, {})
        if context.get("unknown"): coverage_unknown = True
        if context.get("deadline") is not None:
            margins.append(context["deadline"] - lead - minute)
        if horizon is not None and minute > horizon: coverage_unknown = True
    base.update(status="unknown" if coverage_unknown or base["unknown_constraints"] else "clear",
                departure_min=departure, arrival_min=minute,
                minimum_forecast_margin_min=min(margins) if margins else None,
                forecast_coverage="unknown" if coverage_unknown else "known" if fire_context else "not_assessed")
    return base
