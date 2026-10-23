"""Immutable, advisory comparisons of two complete water-refill journeys."""
from __future__ import annotations

import csv
import heapq
import hashlib
import io
import json
import math
from functools import lru_cache
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from pyproj import Transformer
from rasterio.transform import rowcol, xy
from shapely.geometry import LineString, MultiLineString, mapping
from shapely.ops import transform as project_geometry

from .area_packages import package_path
from .decision_explanations import explain_outcome
from .exercise_routing import _exercise_payload
from .io import load_result
from .mobility_api import _dispatcher
from .mobility_routing import (_blocked, _distance, _edge_segments, _eligible, _eligible_node,
                               _graph, _nearest_node, _path, _report_index, _revision)
from .mobility_storage import list_road_reports, list_units, list_vehicles, water_statuses
from .models import VehicleProfile
from .services.exposure import ANALYSIS_VERSION, analyse, roads_revision
from .settings import RUNS
from .storage import connect, get_run, get_scenario, now


router = APIRouter()


class PlanningUnit(BaseModel):
    id: str
    callsign: str
    organisation: str
    vehicle: VehicleProfile
    coordinates: tuple[float, float]
    observed_at: datetime | None = None
    source_file: str | None = None


class SourceChoice(BaseModel):
    point_id: str
    # These are explicitly supplied exercise observations, never inferred from nominal capacity.
    available_volume_l: float | None = Field(None, ge=0)
    flow_l_min: float | None = Field(None, gt=0)
    setup_time_min: float | None = Field(None, ge=0)


class ComparisonRequest(BaseModel):
    run_id: str
    forecast_start_at: datetime
    departure_at: datetime
    unit: PlanningUnit
    delivery_coordinates: tuple[float, float]
    requested_l: float = Field(gt=0)
    sources: list[SourceChoice] = Field(min_length=2, max_length=2)
    lead_time_min: float = Field(10, ge=0, le=120)

    @field_validator("forecast_start_at", "departure_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Use a date and time with timezone")
        return value.astimezone(UTC)

    @field_validator("sources")
    @classmethod
    def distinct_sources(cls, value: list[SourceChoice]) -> list[SourceChoice]:
        if value[0].point_id == value[1].point_id:
            raise ValueError("Choose two different water sources")
        return value


def _setup():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS mobility_comparisons (
            id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, created_at TEXT NOT NULL,
            payload TEXT NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS mobility_comparisons_scenario ON mobility_comparisons(scenario_id,created_at DESC)")


@lru_cache(maxsize=8)
def _projectors(crs: str):
    return (Transformer.from_crs("EPSG:4326", crs, always_xy=True),
            Transformer.from_crs(crs, "EPSG:4326", always_xy=True))


def _point_arrival(result, point: tuple[float, float], buffer_m: float) -> tuple[float | None, bool]:
    x, y = _projectors(result.crs)[0].transform(*point)
    raw_col, raw_row = ~result.transform * (x, y)
    center_row, center_col = math.floor(raw_row), math.floor(raw_col)
    cell_m = max(abs(result.transform.a), abs(result.transform.e))
    radius = max(1, math.ceil(buffer_m / cell_m) + 1)
    rows, cols = np.meshgrid(np.arange(center_row-radius, center_row+radius+1),
                             np.arange(center_col-radius, center_col+radius+1), indexing="ij")
    transform = result.transform
    cx = transform.a*(cols+.5) + transform.b*(rows+.5) + transform.c
    cy = transform.d*(cols+.5) + transform.e*(rows+.5) + transform.f
    selected = np.hypot(cx-x, cy-y) <= buffer_m + cell_m*.71
    inside = (rows >= 0) & (rows < result.coverage.shape[0]) & (cols >= 0) & (cols < result.coverage.shape[1])
    valid = selected & inside
    rr, cc = rows[valid], cols[valid]
    covered = result.coverage[rr, cc]
    values = result.arrival_minutes[rr[covered], cc[covered]]
    finite = values[np.isfinite(values)]
    return (float(finite.min()) if finite.size else None,
            bool((selected & ~inside).any() or (~covered).any() or not selected.any()))


class FireEdgeContext(dict):
    """Sample the routed edge itself; legacy display segments can span many edges."""
    def __init__(self, graph, result, edge_segments, buffer_m):
        super().__init__()
        self.graph, self.result, self.edge_segments, self.buffer_m = graph, result, edge_segments, buffer_m

    def get(self, edge, default=None):
        if edge not in self:
            u, v, _ = edge
            geometry = self.graph.edges[edge].get("geometry") or LineString([
                (self.graph.nodes[u]["x"], self.graph.nodes[u]["y"]),
                (self.graph.nodes[v]["x"], self.graph.nodes[v]["y"])])
            projected = project_geometry(_projectors(self.result.crs)[0].transform, geometry)
            steps = max(1, math.ceil(projected.length / max(15, self.buffer_m)))
            deadlines, unknown = [], False
            for index in range(steps + 1):
                point = projected.interpolate(index / steps, normalized=True)
                lonlat = _projectors(self.result.crs)[1].transform(point.x, point.y)
                arrival, outside = _point_arrival(self.result, lonlat, self.buffer_m)
                unknown |= outside
                if arrival is not None:
                    deadlines.append(arrival)
            self[edge] = {"deadline": min(deadlines) if deadlines else None, "unknown": unknown,
                          "segments": [value for value, _ in self.edge_segments.get(edge, [])]}
        return super().get(edge, default)


@lru_cache(maxsize=8)
def _shared_fire_context(graph_path, roads_path, revision, result_path, result_stamp, buffer_m):
    graph = _graph(graph_path, revision)
    edges = _edge_segments(graph_path, roads_path, revision)
    result = load_result(Path(result_path))
    identity = hashlib.sha256((Path(result_path) / "result.npz").read_bytes() +
                              (Path(result_path) / "result.json").read_bytes()).hexdigest()
    return FireEdgeContext(graph, result, edges, buffer_m), result, identity


def _time_path(graph, start, end, vehicle, reports, edge_segments, context, departure, horizon, lead,
               closed_edges=None):
    """A* with an optimistic 120 km/h bound; unexplored coverage cannot yield a clear route."""
    destination = (graph.nodes[end]["x"], graph.nodes[end]["y"])
    queue, best, previous, serial = [(_distance(graph, start, destination) / 2000 + departure, departure, 0, start)], {start: departure}, {}, 0
    unknown_seen = False
    while queue:
        _, minute, _, node = heapq.heappop(queue)
        if minute != best.get(node):
            continue
        if node == end:
            path = []
            while node != start:
                edge = previous[node]
                path.append(edge)
                node = edge[0]
            return list(reversed(path)), unknown_seen
        for u, v, key, data in graph.out_edges(node, keys=True, data=True):
            edge = (u, v, key)
            if edge in (closed_edges or ()) or not _eligible(data, vehicle) or not _eligible_node(graph.nodes[v]):
                continue
            if _blocked(edge, vehicle, reports, edge_segments):
                continue
            finish = minute + float(data["travel_min"])
            if finish > horizon:
                continue
            details = context.get(edge, {})
            if details.get("unknown"):
                unknown_seen = True
                continue
            deadline = details.get("deadline")
            if deadline is not None and finish >= deadline - lead:
                continue
            if finish < best.get(v, math.inf):
                best[v], previous[v], serial = finish, edge, serial + 1
                heuristic = _distance(graph, v, destination) / 2000
                heapq.heappush(queue, (finish + heuristic, finish, serial, v))
    return None, unknown_seen


def _baseline_conflict(graph, path, context, departure, lead):
    minute = departure
    for edge in path or []:
        minute += float(graph.edges[edge]["travel_min"])
        deadline = context.get(edge, {}).get("deadline")
        if deadline is not None and minute >= deadline - lead:
            return {"reason": "fire_exposure", "segment_ids": context.get(edge, {}).get("segments", []),
                    "road_name": str(graph.edges[edge].get("name") or "Troço de acesso"),
                    "feature": _route_geometry(graph, [edge]),
                    "vehicle_exit_min": round(minute, 2), "exposure_min": round(deadline, 2)}
    return None


def _restriction_conflict(graph, first, last, vehicle, reports, edge_segments, closed_edges):
    # A permissive path is diagnostic evidence only, never a suggested journey.
    permissive = VehicleProfile(name="Diagnóstico", vehicle_class=vehicle.vehicle_class, off_road=True)
    diagnostic = _path(graph, first, last, permissive, {}, edge_segments)
    for edge in diagnostic or []:
        data = graph.edges[edge]
        common = {"road_name": str(data.get("name") or "Acesso local"),
                  "feature": _route_geometry(graph, [edge]),
                  "exercise_assumption": data.get("exercise_assumption")}
        if edge in (closed_edges or ()):
            return {**common, "reason": "proposed_closure"}
        if _blocked(edge, vehicle, reports, edge_segments):
            return {**common, "reason": "recorded_restriction"}
        for field, attribute, label in [("width_m", "maxwidth", "largura"), ("height_m", "maxheight", "altura"), ("weight_t", "maxweight", "peso")]:
            from .mobility_routing import _number
            actual, limit = getattr(vehicle, field), _number(data.get(attribute))
            if actual is not None and limit is not None and actual > limit:
                return {**common, "reason": "vehicle_restriction", "constraint": label, "actual": actual, "limit": limit}
        if not _eligible(data, vehicle):
            return {**common, "reason": "vehicle_restriction", "constraint": "piso incompatível"}
    return None


def _route_geometry(graph, path):
    coordinates = []
    for u, v, key in path or []:
        line = graph.edges[u, v, key].get("geometry") or LineString([
            (graph.nodes[u]["x"], graph.nodes[u]["y"]),
            (graph.nodes[v]["x"], graph.nodes[v]["y"]),
        ])
        vertices = list(line.coords)
        start = (graph.nodes[u]["x"], graph.nodes[u]["y"])
        if math.dist(vertices[-1], start) < math.dist(vertices[0], start):
            vertices.reverse()
        coordinates.extend(vertices if not coordinates else vertices[1:])
    return {"type": "Feature", "geometry": mapping(LineString(coordinates)), "properties": {"diagnostic": True}} if len(coordinates) >= 2 else None


def _trajectory(graph, path, departure):
    """Timed coordinates follow each routed edge's own travel time."""
    samples = []
    minute = departure
    for u, v, key in path:
        data = graph.edges[u, v, key]
        line = data.get("geometry") or LineString([
            (graph.nodes[u]["x"], graph.nodes[u]["y"]),
            (graph.nodes[v]["x"], graph.nodes[v]["y"]),
        ])
        vertices = list(line.coords)
        start = (graph.nodes[u]["x"], graph.nodes[u]["y"])
        if math.dist(vertices[-1], start) < math.dist(vertices[0], start):
            vertices.reverse()
        lengths = [math.dist(vertices[i], vertices[i + 1]) for i in range(len(vertices) - 1)]
        total = sum(lengths) or 1
        elapsed = 0.0
        if not samples:
            samples.append({"minute": round(minute, 4), "coordinates": vertices[0]})
        for length, point in zip(lengths, vertices[1:]):
            elapsed += length
            samples.append({"minute": round(minute + float(data["travel_min"]) * elapsed / total, 4),
                            "coordinates": point})
        minute += float(data["travel_min"])
    return samples


def _stage(graph, edge_segments, report_index, context, vehicle, origin, destination,
           departure, horizon, lead, label, closed_edges=None):
    first, last = _nearest_node(graph, origin), _nearest_node(graph, destination)
    connector = max(_distance(graph, first, origin), _distance(graph, last, destination))
    baseline = _path(graph, first, last, vehicle, report_index, edge_segments, closed_edges)
    path, coverage_limited = _time_path(graph, first, last, vehicle, report_index,
                                        edge_segments, context, departure, horizon, lead, closed_edges)
    diagnostic = _baseline_conflict(graph, baseline, context, departure, lead)
    if path is None:
        diagnostic = diagnostic or _restriction_conflict(graph, first, last, vehicle, report_index, edge_segments, closed_edges)
        status = "unknown" if coverage_limited or baseline and departure + sum(float(graph.edges[e]["travel_min"]) for e in baseline) > horizon else "infeasible"
        return {"status": status, "reason": "Cobertura ou horizonte insuficiente para avaliar o percurso." if status == "unknown" else "Sem percurso elegível durante a deslocação.",
                "conflict": diagnostic, "baseline_feature": _route_geometry(graph, baseline),
                "baseline_duration_min": sum(float(graph.edges[e]["travel_min"]) for e in baseline) if baseline else None}
    if not path:
        return {"status": "unknown", "reason": "Origem e destino ligam ao mesmo nó; percurso não avaliado.",
                "conflict": diagnostic}
    route = _exercise_payload(graph, path, vehicle, report_index, edge_segments, context,
                              departure, lead, horizon, label)
    route["trajectory"] = _trajectory(graph, path, departure)
    route["status"] = "unknown" if route["status"] == "unknown" or connector > 30 else "clear"
    route["connector_m"] = round(connector)
    return {"status": route["status"], "route": route, "conflict": diagnostic,
            "baseline_duration_min": sum(float(graph.edges[e]["travel_min"]) for e in baseline) if baseline else None}


def _choice(source, selected, shared, graph, edge_segments, reports, context, result, departure, horizon,
            exposure_buffer_m, closed_edges=None):
    vehicle = shared.unit.vehicle
    water = source.water
    if water is None or water.availability == "unavailable":
        return {"status": "infeasible", "reason": "Fonte de água indisponível.", "delivered_l": 0, "stages": []}
    if water.availability == "unknown":
        return {"status": "unknown", "reason": "Disponibilidade da fonte desconhecida.", "delivered_l": 0, "stages": []}
    flow = selected.flow_l_min or water.shared_flow_l_min or water.flow_l_min
    volume = selected.available_volume_l if selected.available_volume_l is not None else water.available_volume_l
    if not flow or vehicle.pump_flow_l_min is None or vehicle.water_tank_capacity_l is None:
        return {"status": "unknown", "reason": "Faltam dados de fluxo, bomba ou capacidade da viatura.", "delivered_l": 0, "stages": []}
    if water.supply_class != "continuous" and volume is None:
        return {"status": "unknown", "reason": "Volume de água atualmente disponível não confirmado.", "delivered_l": 0, "stages": []}
    needed = shared.requested_l
    if needed > vehicle.water_tank_capacity_l - (vehicle.starting_water_l or 0):
        return {"status": "infeasible", "reason": "Volume pedido excede a capacidade livre do depósito.", "delivered_l": 0, "stages": []}
    if volume is not None and needed > volume:
        return {"status": "infeasible", "reason": "A fonte não dispõe do volume pedido.", "delivered_l": 0, "stages": []}
    lead, start = shared.lead_time_min, departure
    outbound = _stage(graph, edge_segments, reports, context, vehicle, shared.unit.coordinates,
                      source.coordinates, start, horizon, lead, "Ida", closed_edges)
    stages = [{"kind": "outbound", "start_min": round(start, 2), "end_min": round(start + outbound.get("route", {}).get("duration_min", 0), 2), **outbound}]
    if outbound["status"] != "clear":
        return {"status": outbound["status"], "reason": outbound.get("reason") or "Percurso de ida com dados insuficientes.",
                "delivered_l": 0, "stages": stages, "conflict": outbound.get("conflict")}
    fill_start = stages[-1]["end_min"]
    setup = selected.setup_time_min if selected.setup_time_min is not None else water.setup_time_min
    if setup is None:
        return {"status": "unknown", "reason": "Tempo de preparação da fonte desconhecido.", "delivered_l": 0, "stages": stages}
    fill_end = fill_start + setup + needed / min(flow, vehicle.pump_flow_l_min)
    source_arrival, source_unknown = _point_arrival(result, source.coordinates, exposure_buffer_m)
    stages.append({"kind": "filling", "start_min": round(fill_start, 2), "end_min": round(fill_end, 2), "coordinates": source.coordinates})
    if source_unknown or fill_end > horizon:
        return {"status": "unknown", "reason": "Cobertura ou horizonte insuficiente durante o enchimento.", "delivered_l": 0, "stages": stages}
    if source_arrival is not None and fill_end >= source_arrival - lead:
        return {"status": "infeasible", "reason": "O enchimento termina depois do limite de exposição configurado.", "delivered_l": 0,
                "stages": stages, "conflict": {"reason": "source_exposure", "exposure_min": source_arrival, "vehicle_exit_min": round(fill_end, 2)}}
    inbound = _stage(graph, edge_segments, reports, context, vehicle, source.coordinates,
                     shared.delivery_coordinates, fill_end, horizon, lead, "Regresso", closed_edges)
    stages.append({"kind": "inbound", "start_min": round(fill_end, 2),
                   "end_min": round(fill_end + inbound.get("route", {}).get("duration_min", 0), 2), **inbound})
    if inbound["status"] != "clear":
        return {"status": inbound["status"], "reason": inbound.get("reason") or "Regresso sem dados suficientes.",
                "delivered_l": 0, "stages": stages, "conflict": inbound.get("conflict")}
    unload_end = stages[-1]["end_min"] + needed / vehicle.pump_flow_l_min
    destination_arrival, destination_unknown = _point_arrival(result, shared.delivery_coordinates, exposure_buffer_m)
    stages.append({"kind": "unloading", "start_min": stages[-1]["end_min"],
                   "end_min": round(unload_end, 2), "coordinates": shared.delivery_coordinates})
    if destination_unknown or unload_end > horizon:
        return {"status": "unknown", "reason": "Cobertura ou horizonte insuficiente durante a entrega.", "delivered_l": 0, "stages": stages}
    if destination_arrival is not None and unload_end >= destination_arrival - lead:
        return {"status": "infeasible", "reason": "A entrega termina depois do limite de exposição configurado.", "delivered_l": 0,
                "stages": stages, "conflict": {"reason": "destination_exposure", "exposure_min": destination_arrival, "vehicle_exit_min": round(unload_end, 2)}}
    margins = [stage.get("route", {}).get("minimum_forecast_margin_min") for stage in stages]
    margins += [deadline - lead - finish for deadline, finish in [(source_arrival, fill_end), (destination_arrival, unload_end)] if deadline is not None]
    return {"status": "clear", "reason": "Viagem completa avaliável nas condições simuladas.",
            "delivered_l": needed, "delivery_min": round(unload_end, 2),
            "minimum_forecast_margin_min": round(min(value for value in margins if value is not None), 2) if any(value is not None for value in margins) else None,
            "baseline_duration_min": round(sum(stage.get("baseline_duration_min") or 0 for stage in stages), 2),
            "stages": stages}


def _ordinary_trip(graph, edge_segments, reports, vehicle, origin, source, delivery, closed_edges=None):
    total = 0.0
    lines = []
    for left, right in ((origin, source), (source, delivery)):
        first, last = _nearest_node(graph, left), _nearest_node(graph, right)
        path = _path(graph, first, last, vehicle, reports, edge_segments, closed_edges)
        if path is None:
            return None, None
        total += sum(float(graph.edges[edge]["travel_min"]) for edge in path)
        feature = _route_geometry(graph, path)
        if feature:
            lines.append(LineString(feature["geometry"]["coordinates"]))
    geometry = {"type": "Feature", "properties": {"diagnostic": True},
                "geometry": mapping(MultiLineString(lines))} if lines else None
    return round(total, 2), geometry


def compare(scenario_id: str, request: ComparisonRequest) -> dict:
    if request.unit.vehicle.vehicle_class == "aircraft":
        raise ValueError("Os meios aéreos não utilizam comparações de percursos rodoviários.")
    scenario = get_scenario(scenario_id)
    run = get_run(request.run_id)
    if run.scenario_id != scenario_id or run.status != "ready" or run.mode != "single":
        raise ValueError("Select a completed single-engine simulation for this scenario")
    anchored = (run.run_context or {}).get("scenario_start_time")
    if anchored and request.forecast_start_at != datetime.fromisoformat(anchored).astimezone(UTC):
        raise ValueError("The fire run has a different start time; use the run's recorded time reference")
    if run.area_package_id != scenario.area_package_id:
        raise ValueError("A simulação usa outro pacote de estradas; selecione a simulação atual para recalcular.")
    prepared = package_path(run.area_package_id)
    if not (prepared / "roads.graphml").exists() or not (prepared / "roads.geojson").exists():
        raise ValueError("Prepare the road network before comparing journeys")
    context, result, fire_revision = _shared_fire_context(str(prepared / "roads.graphml"),
        str(prepared / "roads.geojson"), _revision(prepared), str(RUNS / run.id),
        ((RUNS / run.id / "result.npz").stat().st_mtime_ns,
         (RUNS / run.id / "result.json").stat().st_mtime_ns), run.scenario.exposure_buffer_m)
    buffer_m = run.scenario.exposure_buffer_m
    road_path = RUNS / run.id / f"roads-{int(buffer_m)}m.geojson"
    if not road_path.exists() or json.loads(road_path.read_text()).get("analysis_version") != ANALYSIS_VERSION or json.loads(road_path.read_text()).get("roads_revision") != roads_revision(prepared):
        analyse(result, buffer_m, RUNS / run.id, prepared)
    revision = _revision(prepared)
    graph_path = prepared / "roads.graphml"
    graph = _graph(str(graph_path), revision)
    edge_segments = _edge_segments(str(graph_path), str(prepared / "roads.geojson"), revision)
    reports = list_road_reports(scenario_id)
    report_index = _report_index(reports)
    departure = (request.departure_at - request.forecast_start_at).total_seconds() / 60
    if departure < 0 or departure > run.scenario.duration_min:
        raise ValueError("Departure must fall inside the selected simulation")
    sources = {point.id: point for point in scenario.points if point.kind == "water_point"}
    latest_status = water_statuses(scenario_id)
    outcomes = []
    for label, choice in zip(("A", "B"), request.sources):
        source = sources.get(choice.point_id)
        if source is None:
            raise ValueError(f"Water source {choice.point_id} does not belong to this scenario")
        snapshot = source.model_copy(deep=True)
        if source.id in latest_status:
            value = latest_status[source.id]
            snapshot.water.availability = "unknown" if value["availability"] == "uncertain" else value["availability"]
        if snapshot.water.availability == "unknown" and choice.available_volume_l is not None:
            snapshot.water.availability = "available"
        outcome = _choice(snapshot, choice, request, graph,
                          edge_segments, report_index, context, result, departure, run.scenario.duration_min, buffer_m)
        baseline_time, baseline_feature = _ordinary_trip(graph, edge_segments, report_index,
            request.unit.vehicle, request.unit.coordinates, snapshot.coordinates, request.delivery_coordinates)
        outcome["baseline_duration_min"] = baseline_time
        outcome["baseline_feature"] = baseline_feature
        explain_outcome(outcome, snapshot, choice, request)
        outcomes.append({"label": label, "source": snapshot.model_dump(mode="json"),
                         "assumptions": choice.model_dump(mode="json"), **outcome})
    return {"id": uuid4().hex[:12], "scenario_id": scenario_id, "created_at": now(),
            "run_id": run.id, "run_name": run.name, "engine": result.engine,
            "forecast_start_at": request.forecast_start_at.isoformat(), "departure_min": round(departure, 2),
            "horizon_min": run.scenario.duration_min, "road_package_id": scenario.area_package_id,
            "road_revision": revision, "analysis_version": ANALYSIS_VERSION,
            "fire_revision": fire_revision,
            "lead_time_min": request.lead_time_min, "exposure_buffer_m": buffer_m,
            "unit": request.unit.model_dump(mode="json"), "delivery_coordinates": request.delivery_coordinates,
            "requested_l": request.requested_l, "road_reports": reports, "outcomes": outcomes,
            "model_provenance": result.provenance}


@router.post("/api/scenarios/{scenario_id}/mobility-comparisons", status_code=201)
def create_comparison(scenario_id: str, value: ComparisonRequest, request: Request):
    _dispatcher(request)
    try:
        payload = compare(scenario_id, value)
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    _setup()
    with connect() as db:
        db.execute("INSERT INTO mobility_comparisons VALUES (?,?,?,?)",
                   (payload["id"], scenario_id, payload["created_at"], json.dumps(payload)))
    return payload


@router.get("/api/scenarios/{scenario_id}/mobility-comparisons")
def list_comparisons(scenario_id: str, request: Request):
    _dispatcher(request)
    get_scenario(scenario_id)
    _setup()
    with connect() as db:
        rows = db.execute("SELECT payload FROM mobility_comparisons WHERE scenario_id=? ORDER BY created_at DESC LIMIT 100", (scenario_id,)).fetchall()
    return [json.loads(row["payload"]) for row in rows]


@router.get("/api/scenarios/{scenario_id}/mobility-comparisons/{comparison_id}")
def get_comparison(scenario_id: str, comparison_id: str, request: Request):
    _dispatcher(request)
    _setup()
    with connect() as db:
        row = db.execute("SELECT payload FROM mobility_comparisons WHERE scenario_id=? AND id=?",
                         (scenario_id, comparison_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Comparison not found")
    return json.loads(row["payload"])


CSV_COLUMNS = ("unit_id", "organisation", "callsign", "vehicle_class", "longitude", "latitude",
               "observed_at", "tank_capacity_l", "starting_water_l", "pump_flow_l_min")


@router.post("/api/scenarios/{scenario_id}/mobility-comparisons/import-preview")
def preview_import(scenario_id: str, request: Request, payload: dict):
    _dispatcher(request)
    get_scenario(scenario_id)
    name, content = str(payload.get("filename", "snapshot.csv")), str(payload.get("content", ""))
    if len(content) > 250_000:
        raise HTTPException(413, "CSV is too large")
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    missing = [key for key in CSV_COLUMNS if key not in (reader.fieldnames or [])]
    if missing:
        raise HTTPException(422, f"Colunas em falta: {', '.join(missing)}")
    units, errors = [], []
    for number, row in enumerate(reader, 2):
        try:
            for key in CSV_COLUMNS:
                if not (row.get(key) or "").strip():
                    raise ValueError(f"Campo obrigatório em falta: {key}.")
            def numeric(key):
                try:
                    return float(row[key])
                except (TypeError, ValueError) as error:
                    raise ValueError(f"Valor numérico inválido em {key}.") from error
            try:
                observed = datetime.fromisoformat(row["observed_at"])
            except ValueError as error:
                raise ValueError("Data de observação inválida.") from error
            if observed.tzinfo is None:
                raise ValueError("A data de observação precisa de fuso horário.")
            vehicle = VehicleProfile(name=f"Viatura {row['callsign']}", vehicle_class=row["vehicle_class"],
                 water_tank_capacity_l=numeric("tank_capacity_l"),
                 starting_water_l=numeric("starting_water_l"), pump_flow_l_min=numeric("pump_flow_l_min"),
                 width_m=numeric("width_m") if row.get("width_m") else None,
                 height_m=numeric("height_m") if row.get("height_m") else None,
                 weight_t=numeric("weight_t") if row.get("weight_t") else None)
            unit = PlanningUnit(id=row["unit_id"], callsign=row["callsign"], organisation=row["organisation"],
                vehicle=vehicle, coordinates=(numeric("longitude"), numeric("latitude")),
                observed_at=observed, source_file=name)
            if not (-180 <= unit.coordinates[0] <= 180 and -90 <= unit.coordinates[1] <= 90):
                raise ValueError("Coordenadas fora do intervalo válido.")
            units.append(unit.model_dump(mode="json"))
        except (KeyError, ValueError, TypeError) as error:
            detail = str(error)
            errors.append({"row": number, "message": detail if isinstance(error, ValueError) and not hasattr(error, "errors") else "Dados da viatura inválidos; confirme classe e limites."})
    return {"filename": name, "units": units, "errors": errors, "imported_at": now()}
