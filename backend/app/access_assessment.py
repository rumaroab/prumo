"""Advisory road-closure and population-access assessments for saved water decisions."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from .area_packages import package_path
from .io import load_result
from .decision_explanations import explain_outcome, point_feature
from .mobility_api import _dispatcher
from .mobility_comparison import (ComparisonRequest, FireEdgeContext, PlanningUnit, SourceChoice,
                                  _choice, _ordinary_trip, _point_arrival, _route_geometry,
                                  _stage, _shared_fire_context)
from .mobility_routing import _edge_segments, _graph, _report_index, _revision
from .models import ScenarioPoint, VehicleProfile
from .services.exposure import ANALYSIS_VERSION
from .settings import RUNS
from .storage import connect, get_run, get_scenario, now

router = APIRouter()


def default_vehicle() -> VehicleProfile:
    return VehicleProfile(id="planning-light", name="Viatura ligeira de exercício",
                          vehicle_class="light", off_road=False)


class AssessmentRequest(BaseModel):
    comparison_id: str
    section_id: str | None = None
    points: list[ScenarioPoint] = Field(default_factory=list)
    population_vehicle: VehicleProfile = Field(default_factory=default_vehicle)

    @model_validator(mode="after")
    def valid_points(self):
        selected = [point for point in self.points if point.population_role]
        if len(selected) != len(self.points) or len({point.id for point in selected}) != len(selected):
            raise ValueError("Selecione pontos de apoio distintos com função definida.")
        if self.population_vehicle.vehicle_class != "light" or self.population_vehicle.off_road:
            raise ValueError("Use uma viatura ligeira de circulação rodoviária para avaliar acessos.")
        return self


def _setup():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS access_assessments (
            id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, comparison_id TEXT NOT NULL,
            created_at TEXT NOT NULL, payload TEXT NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS access_assessments_scenario ON access_assessments(scenario_id,created_at DESC)")


def _parent(scenario_id: str, comparison_id: str) -> dict:
    # The existing endpoint checks both the scenario scope and dispatcher access.
    _setup()
    with connect() as db:
        row = db.execute("SELECT payload FROM mobility_comparisons WHERE scenario_id=? AND id=?",
                         (scenario_id, comparison_id)).fetchone()
    if row is None:
        raise ValueError("Comparação de abastecimento não encontrada neste cenário.")
    return json.loads(row["payload"])


def _context(scenario_id: str, parent: dict):
    scenario = get_scenario(scenario_id)
    run = get_run(parent["run_id"])
    if run.scenario_id != scenario_id or run.status != "ready":
        raise ValueError("A simulação guardada não está disponível para recalcular.")
    package_id = parent.get("road_package_id")
    prepared = package_path(package_id)
    if _revision(prepared) != parent["road_revision"] or parent.get("analysis_version") != ANALYSIS_VERSION:
        raise ValueError("A revisão de estradas ou da análise mudou; volte a comparar o abastecimento.")
    graph_path = prepared / "roads.graphml"
    roads_path = prepared / "roads.geojson"
    if not graph_path.exists() or not roads_path.exists() or not (RUNS / run.id).exists():
        raise ValueError("Faltam estradas ou resultado do incêndio para esta revisão.")
    if "road_reports" not in parent:
        raise ValueError("A comparação não contém um instantâneo das restrições; crie outra comparação.")
    revision = parent["road_revision"]
    graph = _graph(str(graph_path), revision)
    edge_segments = _edge_segments(str(graph_path), str(roads_path), revision)
    context, result, fire_revision = _shared_fire_context(str(graph_path), str(roads_path), revision,
        str(RUNS / run.id), ((RUNS / run.id / "result.npz").stat().st_mtime_ns,
                           (RUNS / run.id / "result.json").stat().st_mtime_ns), parent["exposure_buffer_m"])
    if parent.get("fire_revision") and parent["fire_revision"] != fire_revision:
        raise ValueError("O resultado do incêndio mudou; a avaliação requer a versão original.")
    reports = _report_index(parent["road_reports"])
    return graph, edge_segments, context, reports, result


def _section_id(revision: str, u, v, name: str) -> str:
    ends = sorted((str(u), str(v)))
    return hashlib.sha256(f"{revision}|{ends[0]}|{ends[1]}|{name}".encode()).hexdigest()[:16]


def _road_name(data) -> str:
    raw = data.get("name")
    return str(raw[0] if isinstance(raw, list) and raw else raw or "Troço sem nome")


def _sections(graph, parent: dict, points: list[ScenarioPoint]):
    locations = [parent["unit"]["coordinates"], parent["delivery_coordinates"]]
    locations += [value["source"]["coordinates"] for value in parent["outcomes"]]
    locations += [point.coordinates for point in points]
    left = min(value[0] for value in locations) - .006
    right = max(value[0] for value in locations) + .006
    bottom = min(value[1] for value in locations) - .006
    top = max(value[1] for value in locations) + .006
    sections = defaultdict(list)
    for u, v, key, data in graph.edges(keys=True, data=True):
        visible = lambda node: left <= graph.nodes[node]["x"] <= right and bottom <= graph.nodes[node]["y"] <= top
        if not (visible(u) or visible(v)):
            continue
        name = _road_name(data)
        sections[_section_id(parent["road_revision"], u, v, name)].append((u, v, key))
    return sections


def road_catalog(scenario_id: str, comparison_id: str) -> dict:
    parent = _parent(scenario_id, comparison_id)
    graph, edge_segments, context, reports, _ = _context(scenario_id, parent)
    points = [point for point in get_scenario(scenario_id).points if point.population_role]
    features = []
    for section_id, edges in _sections(graph, parent, points).items():
        edge = edges[0]
        details = context.get(edge)
        segments = sorted({segment for item in edges for segment, _ in edge_segments.get(item, [])})
        recorded = [report for segment in segments for report in reports.get(segment, [])]
        geometry = _route_geometry(graph, [edge])
        if geometry is None:
            continue
        geometry["properties"] = {
            "section_id": section_id, "road_name": _road_name(graph.edges[edge]),
            "first_exposure_min": details["deadline"], "coverage_unknown": details["unknown"],
            "reports": recorded,
            "exercise_assumption": graph.edges[edge].get("exercise_assumption"),
            "maxwidth": graph.edges[edge].get("maxwidth"),
            "maxheight": graph.edges[edge].get("maxheight"),
            "maxweight": graph.edges[edge].get("maxweight"),
        }
        features.append(geometry)
    return {"type": "FeatureCollection", "features": features,
            "road_revision": parent["road_revision"], "comparison_id": comparison_id}


def _population_pair(graph, edge_segments, context, reports, result, parent, vehicle,
                     origin: ScenarioPoint, reception: ScenarioPoint, closed_edges):
    start = parent["departure_min"]
    horizon = parent["horizon_min"]
    lead = parent["lead_time_min"]
    buffer = parent["exposure_buffer_m"]
    origin_arrival, origin_unknown = _point_arrival(result, origin.coordinates, buffer)
    destination_arrival, destination_unknown = _point_arrival(result, reception.coordinates, buffer)
    if origin_unknown or destination_unknown:
        return {"reception_id": reception.id, "status": "unknown", "reason": "Cobertura desconhecida no ponto de origem ou receção."}
    if origin_arrival is not None and start >= origin_arrival - lead:
        return {"reception_id": reception.id, "status": "infeasible", "reason": "A origem já está exposta à partida.",
                "conflict": {"reason": "origin_exposure", "exposure_min": origin_arrival}}
    stage = _stage(graph, edge_segments, reports, context, vehicle, origin.coordinates,
                   reception.coordinates, start, horizon, lead, "Acesso", closed_edges)
    route = stage.get("route")
    arrival = start + route["duration_min"] if route else None
    if stage["status"] != "clear":
        return {"reception_id": reception.id, "status": stage["status"],
                "reason": stage.get("reason") or "Dados do percurso insuficientes.",
                "route": route, "conflict": stage.get("conflict")}
    if arrival is None or arrival > horizon:
        return {"reception_id": reception.id, "status": "unknown", "reason": "Percurso além do horizonte simulado."}
    if destination_arrival is not None and arrival >= destination_arrival - lead:
        return {"reception_id": reception.id, "status": "infeasible",
                "reason": "O acesso à receção fica exposto antes da chegada.",
                "conflict": {"reason": "destination_exposure", "exposure_min": destination_arrival,
                             "vehicle_exit_min": round(arrival, 2)}}
    margins = [route.get("minimum_forecast_margin_min")]
    margins += [deadline - lead - minute for deadline, minute in
                ((origin_arrival, start), (destination_arrival, arrival)) if deadline is not None]
    return {"reception_id": reception.id, "status": "clear", "reason": "Percurso avaliável nas condições simuladas.",
            "arrival_min": round(arrival, 2), "duration_min": round(route["duration_min"], 2),
            "minimum_forecast_margin_min": round(min(value for value in margins if value is not None), 2)
            if any(value is not None for value in margins) else None,
            "route": route}


def _population(graph, edge_segments, context, reports, result, parent, points, vehicle, closed_edges):
    receptions = [point for point in points if point.population_role == "reception"]
    rows = []
    for origin in (point for point in points if point.population_role == "origin"):
        options = [_population_pair(graph, edge_segments, context, reports, result, parent, vehicle,
                                    origin, reception, closed_edges) for reception in receptions]
        for option in options:
            if option["status"] == "clear":
                continue
            conflict = option.get("conflict") or {}
            exposure = conflict.get("exposure_min")
            feature = conflict.get("feature") or point_feature(origin.coordinates)
            if conflict.get("reason") == "destination_exposure":
                feature = point_feature(next(point.coordinates for point in receptions if point.id == option["reception_id"]))
            option["explanations"] = [{"code": conflict.get("reason") or "population_access",
                "category": "missing_data" if option["status"] == "unknown" else "modelled_fire"
                    if exposure is not None else "restriction",
                "severity": option["status"], "place": conflict.get("road_name") or origin.name,
                "message": option["reason"], "feature": feature,
                "exposure_min": exposure, "event_min": exposure-parent["lead_time_min"] if exposure is not None else None,
                "vehicle_exit_min": conflict.get("vehicle_exit_min"), "lead_time_min": parent["lead_time_min"]}]
        feasible = sorted((option for option in options if option["status"] == "clear"),
                          key=lambda option: (option["arrival_min"], option["reception_id"]))
        status = "clear" if feasible else "unknown" if not options or any(
            option["status"] == "unknown" for option in options) else "infeasible"
        rows.append({"origin": origin.model_dump(mode="json"), "status": status,
                     "reachable_count": len(feasible), "best_reception_id": feasible[0]["reception_id"] if feasible else None,
                     "options": options})
    return rows


def assess(scenario_id: str, value: AssessmentRequest) -> dict:
    parent = _parent(scenario_id, value.comparison_id)
    graph, edge_segments, context, reports, result = _context(scenario_id, parent)
    sections = _sections(graph, parent, value.points)
    if value.section_id and value.section_id not in sections:
        raise ValueError("O troço proposto não pertence à revisão de estradas desta comparação.")
    closed_edges = set(sections.get(value.section_id, []))
    selected_feature = None
    if closed_edges:
        edge = next(iter(closed_edges))
        selected_feature = _route_geometry(graph, [edge])
        if selected_feature:
            selected_feature["properties"] = {"section_id": value.section_id,
                                              "road_name": _road_name(graph.edges[edge]),
                                              "first_exposure_min": context.get(edge)["deadline"],
                                              "coverage_unknown": context.get(edge)["unknown"]}
    before_population = _population(graph, edge_segments, context, reports, result, parent,
                                    value.points, value.population_vehicle, set())
    after_population = _population(graph, edge_segments, context, reports, result, parent,
                                   value.points, value.population_vehicle, closed_edges) if closed_edges else before_population
    after_water = []
    if closed_edges:
        request = ComparisonRequest(
            run_id=parent["run_id"], forecast_start_at=datetime.fromisoformat(parent["forecast_start_at"]),
            departure_at=datetime.fromisoformat(parent["forecast_start_at"]) + timedelta(minutes=parent["departure_min"]),
            unit=PlanningUnit.model_validate(parent["unit"]), delivery_coordinates=parent["delivery_coordinates"],
            requested_l=parent["requested_l"],
            sources=[SourceChoice.model_validate(item["assumptions"]) for item in parent["outcomes"]],
            lead_time_min=parent["lead_time_min"])
        for original in parent["outcomes"]:
            source = ScenarioPoint.model_validate(original["source"])
            choice = SourceChoice.model_validate(original["assumptions"])
            outcome = _choice(source, choice, request, graph, edge_segments, reports, context, result,
                              parent["departure_min"], parent["horizon_min"], parent["exposure_buffer_m"], closed_edges)
            explain_outcome(outcome, source, choice, request, closure_feature=selected_feature)
            ordinary, feature = _ordinary_trip(graph, edge_segments, reports, request.unit.vehicle,
                request.unit.coordinates, source.coordinates, request.delivery_coordinates, closed_edges)
            after_water.append({"label": original["label"], "source": original["source"],
                                "assumptions": original["assumptions"], "baseline_duration_min": ordinary,
                                "baseline_feature": feature, **outcome})
    else:
        after_water = parent["outcomes"]
    before_water = parent["outcomes"]
    road_name = selected_feature["properties"]["road_name"] if selected_feature else ""
    for before, after in zip(before_water, after_water):
        if closed_edges and (before.get("status"), before.get("delivery_min")) != (
                after.get("status"), after.get("delivery_min")):
            delta = (after.get("delivery_min") or 0) - (before.get("delivery_min") or 0)
            status_labels = {"clear": "viável", "unknown": "dados insuficientes", "infeasible": "inviável"}
            after["change_reason"] = (f"O encerramento de {road_name} acrescenta {delta:.1f} minutos à entrega."
                if before["status"] == after["status"] == "clear" else
                f"Com o encerramento de {road_name}, esta viagem passa de {status_labels[before['status']]} para {status_labels[after['status']]}.")
    def best_arrival(row):
        return next((option.get("arrival_min") for option in row["options"]
                     if option["reception_id"] == row.get("best_reception_id")), None)
    for before, after in zip(before_population, after_population):
        if closed_edges and (before["status"], before["reachable_count"], best_arrival(before)) != (
                after["status"], after["reachable_count"], best_arrival(after)):
            delta = (best_arrival(after) or 0) - (best_arrival(before) or 0)
            after["change_reason"] = (f"Com o encerramento de {road_name}, a viagem demora mais {delta:.1f} minutos. Continua viável nas condições simuladas."
                if before["status"] == after["status"] == "clear" else
                f"Com o encerramento de {road_name}, {after['origin']['name']} deixa de ter um percurso viável avaliado."
                if before["status"] == "clear" and after["status"] == "infeasible" else
                f"O encerramento de {road_name} altera os pontos de receção acessíveis. Consulte os resultados de cada percurso.")
            after["explanations"] = [{"code": "closure_impact", "category": "restriction",
                "severity": "info" if after["status"] == "clear" else after["status"],
                "place": road_name, "message": after["change_reason"], "feature": selected_feature,
                "event_min": parent["departure_min"]}]
    water_changed = any((before.get("status"), before.get("delivery_min")) !=
                        (after.get("status"), after.get("delivery_min"))
                        for before, after in zip(before_water, after_water))
    population_changed = sum(bool(after.get("change_reason")) for after in after_population)
    return {"id": uuid4().hex[:12], "scenario_id": scenario_id, "created_at": now(),
            "comparison_id": parent["id"], "comparison": parent,
            "road_revision": parent["road_revision"], "section_id": value.section_id,
            "closure_feature": selected_feature,
            "population_points": [point.model_dump(mode="json") for point in value.points],
            "population_vehicle": value.population_vehicle.model_dump(mode="json"),
            "without": {"water": before_water, "population": before_population},
            "with_proposal": {"water": after_water, "population": after_population},
            "summary": {"water_changed": water_changed, "population_changed": population_changed}}


@router.get("/api/scenarios/{scenario_id}/mobility-comparisons/{comparison_id}/access-roads")
def get_access_roads(scenario_id: str, comparison_id: str, request: Request):
    _dispatcher(request)
    try:
        return road_catalog(scenario_id, comparison_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/api/scenarios/{scenario_id}/access-assessments", status_code=201)
def create_assessment(scenario_id: str, value: AssessmentRequest, request: Request):
    _dispatcher(request)
    try:
        payload = assess(scenario_id, value)
    except (ValueError, KeyError) as error:
        raise HTTPException(422, str(error)) from error
    _setup()
    with connect() as db:
        db.execute("INSERT INTO access_assessments VALUES (?,?,?,?,?)",
                   (payload["id"], scenario_id, value.comparison_id,
                    payload["created_at"], json.dumps(payload)))
    return payload


@router.get("/api/scenarios/{scenario_id}/access-assessments")
def list_assessments(scenario_id: str, request: Request):
    _dispatcher(request)
    get_scenario(scenario_id)
    _setup()
    with connect() as db:
        rows = db.execute("SELECT payload FROM access_assessments WHERE scenario_id=? ORDER BY created_at DESC LIMIT 100",
                          (scenario_id,)).fetchall()
    return [json.loads(row["payload"]) for row in rows]


@router.get("/api/scenarios/{scenario_id}/access-assessments/{assessment_id}")
def get_assessment(scenario_id: str, assessment_id: str, request: Request):
    _dispatcher(request)
    _setup()
    with connect() as db:
        row = db.execute("SELECT payload FROM access_assessments WHERE scenario_id=? AND id=?",
                         (scenario_id, assessment_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Avaliação não encontrada neste cenário.")
    return json.loads(row["payload"])
