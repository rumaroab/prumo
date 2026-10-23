from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Body, Header, HTTPException, Request

from .exercise_models import (ExerciseEventCreate, ExerciseRouteRequest, ExerciseRunAction, ExerciseRunCreate, ExerciseSituation,
                              Mission, ResponseExperimentCreate, ResponsePlan, RevisionedMission, RevisionedPlan,
                              SnapshotCreate, SituationUpdate, SuggestionRequest)
from .exercise_planner import evaluate_plan, suggest_plans
from .exercise_routing import assess_exercise_route, snapshot_route_assessor
from .exercise_storage import (ExerciseConflict, act_on_exercise_run, add_exercise_event, archive_mission,
                               archive_plan, attach_forecast, cancel_experiment, create_exercise_run,
                               create_experiment_record, create_snapshot, exercise_summary,
                               get_exercise_run, get_experiment, get_plan, get_situation,
                               get_snapshot, list_exercise_runs, list_experiments, list_missions, list_plans,
                               list_snapshots, require_exercise, retry_experiment, save_mission, save_plan, idempotent_record,
                               update_situation, advance_exercise_run)
from .mobility_api import _dispatcher
from .mobility_storage import add_location, list_movements, list_road_reports, list_units, list_vehicles, save_unit, save_vehicle
from .area_packages import package_path
from .io import load_result
from .models import LocationCreate, OperationalUnit, ScenarioPoint, VehicleProfile
from .services.exposure import ANALYSIS_VERSION, analyse, roads_revision
from .settings import RUNS
from .storage import connect, create_scenario, get_run, get_scenario, list_scenarios, now, scenario_runs


router = APIRouter()


def _errors(task):
    try:
        return task()
    except KeyError as error:
        raise HTTPException(404, "Exercise record not found") from error
    except ExerciseConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/api/exercise-summaries")
def exercise_summaries(request: Request):
    _dispatcher(request)
    return {"scenarios": {scenario.id: exercise_summary(scenario.id) for scenario in list_scenarios()},
            "server_time": datetime.now(UTC).isoformat()}


@router.post("/api/scenarios/{scenario_id}/exercise-copy", status_code=201)
def exercise_copy(scenario_id: str, request: Request, payload: dict = Body(default={}),
                  idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    _dispatcher(request)

    def copy():
        if idempotency_key:
            existing = idempotent_record(scenario_id, "exercise-copy", idempotency_key)
            if existing:
                return get_scenario(existing).model_dump(mode="json")
        source = get_scenario(scenario_id)
        point_ids: dict[str, str] = {}
        points = []
        for point in source.points:
            point_id = uuid4().hex[:12]
            point_ids[point.id] = point_id
            points.append(point.model_copy(update={"id": point_id, "notes":
                f"{point.notes}\nCopied from scenario {source.id}".strip()}))
        name = str(payload.get("name") or f"{source.name} — exercise")
        created = create_scenario(source.simulation.model_copy(update={"name": name}), name=name,
            description=str(payload.get("description") or source.description), area_id=source.area_id,
            start_time=payload.get("reference_time") or source.start_time or datetime.now(UTC),
            resource_center=source.resource_center, resource_radius_km=source.resource_radius_km,
            fire_margin_km=source.fire_margin_km, cell_size_m=source.cell_size_m,
            area_package_id=source.area_package_id, points=points, closures=source.closures,
            teams=[], resource_groups=source.resource_groups,
            scenario_kind="exercise", source_scenario_id=source.id,
            import_request_id=idempotency_key)
        vehicle_ids: dict[str, str] = {}
        for value in list_vehicles(source.id):
            previous = value.pop("revision", None)
            _ = previous
            copied = VehicleProfile.model_validate({**value, "id": uuid4().hex[:12], "revision": 1})
            vehicle_ids[value["id"]] = copied.id
            save_vehicle(created.id, copied)
        active = {value["unit_id"]: value for value in list_movements(source.id)
                  if value.get("status") in {"assigned", "accepted", "travelling", "arrived", "cannot_proceed"}}
        for value in list_units(source.id):
            original_id = value["id"]
            location = value.pop("latest_location", None)
            value.pop("revision", None)
            vehicle_id = vehicle_ids.get(value["vehicle_id"])
            if not vehicle_id:
                continue
            copied = OperationalUnit.model_validate({**value, "id": uuid4().hex[:12], "vehicle_id": vehicle_id,
                "revision": 1, "status": "available"})
            save_unit(created.id, copied)
            if location:
                add_location(created.id, copied.id, LocationCreate(coordinates=location["coordinates"],
                    observed_at=location["observed_at"], source=location.get("source", "dispatcher"),
                    accuracy_m=location.get("accuracy_m")))
            if original_id in active:
                situation = get_situation(created.id)
                assumptions = [*situation.get("assumptions", []),
                               f"Existing source commitment retained as context for {copied.callsign}: {active[original_id].get('purpose', 'movement')}"]
                update_situation(created.id, ExerciseSituation.model_validate({**situation, "assumptions": assumptions}),
                                 situation["revision"])
        source_points = {point.id: point for point in source.points}
        team_unit_ids: dict[str, str] = {}
        for team in source.teams:
            # Legacy containment teams had no authoritative vehicle identity. Keep
            # their known rate and base, but leave the vehicle incomplete for the
            # exercise author to map explicitly.
            incomplete = OperationalUnit(id=uuid4().hex[:12], organisation="Legacy containment resource",
                callsign=team.name, vehicle_id=None, status="available", capabilities=["containment"],
                max_deployment_min=team.max_deployment_min, containment_rate_m_min=team.line_rate_m_min)
            save_unit(created.id, incomplete)
            team_unit_ids[team.id] = incomplete.id
            base = source_points.get(team.base_point_id)
            if base:
                add_location(created.id, incomplete.id, LocationCreate(coordinates=base.coordinates,
                    observed_at=payload.get("reference_time") or source.start_time or datetime.now(UTC),
                    source="dispatcher"))
        task_mission_ids: dict[str, str] = {}
        for task in source.containment_tasks:
            coordinates = task.geometry.get("coordinates") or []
            if not coordinates:
                continue
            mission = Mission(name=task.name, mission_type="containment", priority=3,
                location={"name": f"{task.name} access", "coordinates": coordinates[0]},
                containment_geometry=task.geometry, required_capabilities=["containment"],
                completion_criteria="Complete the retained legacy containment line",
                cargo_requirements=("Protected copied assets: " + ", ".join(point_ids.get(value, value)
                                    for value in task.protected_asset_ids)) if task.protected_asset_ids else "")
            saved_mission = save_mission(created.id, mission)
            task_mission_ids[task.id] = saved_mission["id"]
        for legacy_plan in source.allocation_plans:
            assignments = []
            for assignment in legacy_plan.assignments:
                mission_id = task_mission_ids.get(assignment.task_id)
                unit_ids = [team_unit_ids[value] for value in assignment.team_ids if value in team_unit_ids]
                if mission_id and unit_ids:
                    assignments.append({"mission_id": mission_id, "unit_ids": unit_ids, "locked": True})
            if assignments:
                save_plan(created.id, ResponsePlan(name=f"Imported: {legacy_plan.name}",
                    description="Explicit mapping from the legacy containment allocation.",
                    assignments=assignments, assumptions=["Vehicles remain incomplete until explicitly mapped."]))
        for run_id in payload.get("forecast_ids", []):
            attach_forecast(created.id, source.id, run_id)
        if idempotency_key:
            with connect() as db:
                db.execute("INSERT OR IGNORE INTO exercise_idempotency VALUES (?,?,?,?,?)",
                           (scenario_id, "exercise-copy", idempotency_key, created.id, now()))
        return created.model_dump(mode="json")
    return _errors(copy)


@router.get("/api/scenarios/{scenario_id}/exercise-situation")
def read_situation(scenario_id: str, request: Request):
    _dispatcher(request)
    return _errors(lambda: get_situation(scenario_id))


@router.put("/api/scenarios/{scenario_id}/exercise-situation")
def edit_situation(scenario_id: str, value: SituationUpdate, request: Request):
    _dispatcher(request)
    situation = ExerciseSituation(scenario_id=scenario_id, **value.model_dump(exclude={"expected_revision"}))
    return _errors(lambda: update_situation(scenario_id, situation, value.expected_revision))


@router.get("/api/scenarios/{scenario_id}/situation-snapshots")
def snapshots(scenario_id: str, request: Request):
    _dispatcher(request)
    return _errors(lambda: list_snapshots(scenario_id))


@router.post("/api/scenarios/{scenario_id}/situation-snapshots", status_code=201)
def snapshot(scenario_id: str, value: SnapshotCreate, request: Request):
    _dispatcher(request)
    return _errors(lambda: create_snapshot(scenario_id, value.forecast_ids, value.assumption_overrides))


@router.get("/api/scenarios/{scenario_id}/missions")
def missions(scenario_id: str, request: Request):
    _dispatcher(request)
    return _errors(lambda: list_missions(scenario_id))


@router.post("/api/scenarios/{scenario_id}/missions", status_code=201)
def add_mission(scenario_id: str, value: Mission, request: Request):
    _dispatcher(request)
    return _errors(lambda: save_mission(scenario_id, value))


@router.put("/api/scenarios/{scenario_id}/missions/{mission_id}")
def edit_mission(scenario_id: str, mission_id: str, value: RevisionedMission, request: Request):
    _dispatcher(request)
    if value.mission.id != mission_id:
        raise HTTPException(422, "Mission ID does not match the route")
    return _errors(lambda: save_mission(scenario_id, value.mission, value.expected_revision))


@router.delete("/api/scenarios/{scenario_id}/missions/{mission_id}")
def remove_mission(scenario_id: str, mission_id: str, expected_revision: int, request: Request):
    _dispatcher(request)
    _errors(lambda: archive_mission(scenario_id, mission_id, expected_revision))
    return {"archived": True}


@router.get("/api/scenarios/{scenario_id}/response-plans")
def plans(scenario_id: str, request: Request):
    _dispatcher(request)
    return _errors(lambda: list_plans(scenario_id))


@router.post("/api/scenarios/{scenario_id}/response-plans", status_code=201)
def add_plan(scenario_id: str, value: ResponsePlan, request: Request):
    _dispatcher(request)
    return _errors(lambda: save_plan(scenario_id, value))


@router.put("/api/scenarios/{scenario_id}/response-plans/{plan_id}")
def edit_plan(scenario_id: str, plan_id: str, value: RevisionedPlan, request: Request):
    _dispatcher(request)
    if value.plan.id != plan_id:
        raise HTTPException(422, "Plan ID does not match the route")
    return _errors(lambda: save_plan(scenario_id, value.plan, value.expected_revision))


@router.delete("/api/scenarios/{scenario_id}/response-plans/{plan_id}")
def remove_plan(scenario_id: str, plan_id: str, expected_revision: int, request: Request):
    _dispatcher(request)
    _errors(lambda: archive_plan(scenario_id, plan_id, expected_revision))
    return {"archived": True}


@router.post("/api/scenarios/{scenario_id}/response-plans/suggestions")
def suggestions(scenario_id: str, value: SuggestionRequest, request: Request):
    _dispatcher(request)

    def generate():
        snapshot_value = get_snapshot(scenario_id, value.snapshot_id) if value.snapshot_id else create_snapshot(scenario_id)
        return suggest_plans(snapshot_value, value.mission_ids, value.unit_ids,
                             [item.model_dump(mode="json") for item in value.locked_assignments],
                             value.count, value.forecast_id,
                             route_assessor=snapshot_route_assessor(snapshot_value, value.forecast_id))
    return _errors(generate)


@router.post("/api/scenarios/{scenario_id}/exercise-routes")
def exercise_route(scenario_id: str, value: ExerciseRouteRequest, request: Request):
    _dispatcher(request)

    def assess():
        scenario = require_exercise(scenario_id)
        vehicle_value = next((item for item in list_vehicles(scenario_id) if item["id"] == value.vehicle_id), None)
        unit_value = next((item for item in list_units(scenario_id) if item["id"] == value.unit_id), None)
        if not vehicle_value or not unit_value or unit_value["vehicle_id"] != value.vehicle_id:
            raise ValueError("Select a scenario unit and its assigned vehicle")
        run_roads = None
        horizon = None
        if value.forecast_id:
            create_snapshot(scenario_id, [value.forecast_id])  # Validates scenario or explicitly attached access.
            run = get_run(value.forecast_id)
            if run.mode == "engine_comparison":
                raise ValueError("Select a completed deterministic result or an explicit comparison member")
            run_roads = RUNS / run.id / "roads-30m.geojson"
            prepared = package_path(run.area_package_id)
            cached = json.loads(run_roads.read_text()) if run_roads.exists() else {}
            if cached.get("analysis_version") != ANALYSIS_VERSION or cached.get("roads_revision") != roads_revision(prepared):
                analyse(load_result(RUNS / run.id), 30, RUNS / run.id, prepared)
            horizon = run.scenario.duration_min
        return assess_exercise_route(package_path(scenario.area_package_id), VehicleProfile.model_validate(vehicle_value),
            list_road_reports(scenario_id),
            scenario.closures, value.origin, value.destination, value.departure_min,
            value.service_duration_min, value.withdrawal_destination, run_roads, value.lead_time_min,
            horizon, value.alternatives)
    return _errors(assess)


@router.get("/api/scenarios/{scenario_id}/response-experiments")
def experiments(scenario_id: str, request: Request):
    _dispatcher(request)
    return _errors(lambda: list_experiments(scenario_id))


@router.post("/api/scenarios/{scenario_id}/response-experiments", status_code=202)
def add_experiment(scenario_id: str, value: ResponseExperimentCreate, request: Request,
                   idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    _dispatcher(request)

    def create():
        snapshot_value = get_snapshot(scenario_id, value.snapshot_id) if value.snapshot_id else create_snapshot(scenario_id, value.forecast_ids)
        current_plans = {plan["id"]: plan for plan in list_plans(scenario_id)}
        if any(plan_id not in current_plans for plan_id in value.plan_ids):
            raise ValueError("Every selected response plan must be active")
        frozen_request = value.model_copy(update={"snapshot_id": snapshot_value["id"]}).model_dump(mode="json")
        frozen_request["plan_versions"] = [current_plans[plan_id] for plan_id in value.plan_ids]
        record = create_experiment_record(scenario_id, snapshot_value["id"],
                                          frozen_request,
                                          idempotency_key)
        return record
    return _errors(create)


@router.get("/api/scenarios/{scenario_id}/response-experiments/{experiment_id}")
def experiment(scenario_id: str, experiment_id: str, request: Request):
    _dispatcher(request)
    return _errors(lambda: get_experiment(scenario_id, experiment_id))


@router.post("/api/scenarios/{scenario_id}/response-experiments/{experiment_id}/cancel")
def stop_experiment(scenario_id: str, experiment_id: str, request: Request):
    _dispatcher(request)
    return _errors(lambda: cancel_experiment(scenario_id, experiment_id))


@router.post("/api/scenarios/{scenario_id}/response-experiments/{experiment_id}/retry", status_code=202)
def retry_response_experiment(scenario_id: str, experiment_id: str, request: Request):
    _dispatcher(request)
    return _errors(lambda: retry_experiment(scenario_id, experiment_id))


@router.get("/api/scenarios/{scenario_id}/exercise-runs")
def exercise_runs(scenario_id: str, request: Request):
    _dispatcher(request)
    return _errors(lambda: list_exercise_runs(scenario_id))


@router.post("/api/scenarios/{scenario_id}/exercise-runs", status_code=201)
def add_exercise_run(scenario_id: str, value: ExerciseRunCreate, request: Request,
                     idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    _dispatcher(request)

    def create():
        plan = get_plan(scenario_id, value.plan_id)
        if plan["revision"] != value.plan_revision:
            raise ExerciseConflict("Select the current response-plan version before rehearsing")
        snapshot_value = get_snapshot(scenario_id, value.snapshot_id) if value.snapshot_id else create_snapshot(scenario_id)
        evaluation = evaluate_plan(snapshot_value, plan, route_assessor=snapshot_route_assessor(snapshot_value))
        return create_exercise_run(scenario_id, snapshot_value["id"], plan, evaluation, idempotency_key)
    return _errors(create)


@router.get("/api/scenarios/{scenario_id}/exercise-runs/{run_id}")
def exercise_run(scenario_id: str, run_id: str, request: Request):
    _dispatcher(request)
    return _errors(lambda: get_exercise_run(scenario_id, run_id))


@router.post("/api/scenarios/{scenario_id}/exercise-runs/{run_id}/actions")
def exercise_run_action(scenario_id: str, run_id: str, value: ExerciseRunAction, request: Request):
    _dispatcher(request)
    return _errors(lambda: act_on_exercise_run(scenario_id, run_id, value.action, value.expected_revision,
                                               value.speed, value.idempotency_key))


@router.post("/api/scenarios/{scenario_id}/exercise-runs/{run_id}/advance")
def exercise_run_advance(scenario_id: str, run_id: str, request: Request, minutes: float = Body(1, embed=True)):
    _dispatcher(request)
    return _errors(lambda: advance_exercise_run(scenario_id, run_id, max(0, min(minutes, 60))))


@router.post("/api/scenarios/{scenario_id}/exercise-runs/{run_id}/events", status_code=201)
def exercise_event(scenario_id: str, run_id: str, value: ExerciseEventCreate, request: Request):
    _dispatcher(request)
    return _errors(lambda: add_exercise_event(scenario_id, run_id, value.kind, value.offset_min,
                                              value.payload, value.idempotency_key))
