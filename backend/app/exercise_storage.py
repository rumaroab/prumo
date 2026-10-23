from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .exercise_models import ExerciseSituation, Mission, ResponsePlan
from .mobility_storage import list_movements, list_road_reports, list_units, list_vehicles
from .storage import connect, get_run, get_scenario, now, scenario_runs


class ExerciseConflict(RuntimeError):
    pass


def _payload(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _loads(value: str | None) -> Any:
    return json.loads(value) if value else None


def require_exercise(scenario_id: str):
    scenario = get_scenario(scenario_id)
    if scenario.scenario_kind != "exercise":
        raise ValueError("Create an exercise copy before using the exercise workspace")
    return scenario


def get_situation(scenario_id: str) -> dict[str, Any]:
    scenario = require_exercise(scenario_id)
    with connect() as db:
        row = db.execute("SELECT * FROM exercise_situations WHERE scenario_id=?", (scenario_id,)).fetchone()
        if not row:
            reference = scenario.start_time
            if reference is None:
                reference = datetime.now(UTC)
            elif reference.tzinfo is None:
                reference = reference.replace(tzinfo=UTC)
            value = ExerciseSituation(scenario_id=scenario_id, reference_time=reference,
                                      created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
            db.execute("INSERT INTO exercise_situations VALUES (?,?,?,?,?)",
                       (scenario_id, _payload(value), 1, now(), now()))
            return value.model_dump(mode="json")
    value = ExerciseSituation.model_validate(_loads(row["payload"])).model_dump(mode="json")
    value.update(revision=row["revision"], created_at=row["created_at"], updated_at=row["updated_at"])
    return value


def update_situation(scenario_id: str, value: ExerciseSituation, expected_revision: int) -> dict[str, Any]:
    require_exercise(scenario_id)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT revision,created_at FROM exercise_situations WHERE scenario_id=?",
                         (scenario_id,)).fetchone()
        if not row:
            get_situation(scenario_id)
            raise ExerciseConflict("Situation was created; refresh before saving")
        if row["revision"] != expected_revision:
            raise ExerciseConflict("Situation changed; refresh before saving")
        stamp = now()
        payload = value.model_copy(update={"scenario_id": scenario_id, "revision": expected_revision + 1,
                                           "created_at": datetime.fromisoformat(row["created_at"]),
                                           "updated_at": datetime.fromisoformat(stamp)})
        db.execute("UPDATE exercise_situations SET payload=?,revision=?,updated_at=? WHERE scenario_id=?",
                   (_payload(payload), expected_revision + 1, stamp, scenario_id))
    return payload.model_dump(mode="json")


def list_missions(scenario_id: str, include_archived: bool = False) -> list[dict[str, Any]]:
    require_exercise(scenario_id)
    condition = "" if include_archived else "AND archived_at IS NULL"
    with connect() as db:
        rows = db.execute(f"SELECT * FROM exercise_missions WHERE scenario_id=? {condition} ORDER BY created_at,id",
                          (scenario_id,)).fetchall()
    return [_record(row) for row in rows]


def save_mission(scenario_id: str, mission: Mission, expected_revision: int | None = None) -> dict[str, Any]:
    require_exercise(scenario_id)
    stamp = now()
    mission = mission.model_copy(update={"scenario_id": scenario_id})
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM exercise_missions WHERE id=? AND scenario_id=?",
                         (mission.id, scenario_id)).fetchone()
        if row:
            if expected_revision is None or row["revision"] != expected_revision:
                raise ExerciseConflict("Mission changed; refresh before saving")
            mission = mission.model_copy(update={"revision": expected_revision + 1,
                                                 "created_at": datetime.fromisoformat(row["created_at"]),
                                                 "updated_at": datetime.fromisoformat(stamp)})
            _validate_mission_dependencies(db, scenario_id, mission)
            db.execute("UPDATE exercise_missions SET payload=?,revision=?,updated_at=? WHERE id=?",
                       (_payload(mission), mission.revision, stamp, mission.id))
        else:
            mission = mission.model_copy(update={"revision": 1, "created_at": datetime.fromisoformat(stamp),
                                                 "updated_at": datetime.fromisoformat(stamp)})
            _validate_mission_dependencies(db, scenario_id, mission)
            db.execute("INSERT INTO exercise_missions VALUES (?,?,?,?,?,?,?)",
                       (mission.id, scenario_id, _payload(mission), 1, None, stamp, stamp))
    return mission.model_dump(mode="json")


def archive_mission(scenario_id: str, mission_id: str, expected_revision: int) -> None:
    with connect() as db:
        active = db.execute("SELECT payload FROM response_plans WHERE scenario_id=? AND archived_at IS NULL",
                            (scenario_id,)).fetchall()
        if any(mission_id == assignment.get("mission_id") for row in active
               for assignment in _loads(row["payload"]).get("assignments", [])):
            raise ExerciseConflict("Archive or edit response plans that still reference this mission")
        cursor = db.execute("UPDATE exercise_missions SET archived_at=?,updated_at=?,revision=revision+1 "
                            "WHERE id=? AND scenario_id=? AND revision=? AND archived_at IS NULL",
                            (now(), now(), mission_id, scenario_id, expected_revision))
        if not cursor.rowcount:
            raise ExerciseConflict("Mission changed or is unavailable")


def _validate_mission_dependencies(db, scenario_id: str, pending: Mission) -> None:
    rows = db.execute("SELECT id,payload FROM exercise_missions WHERE scenario_id=? AND archived_at IS NULL",
                      (scenario_id,)).fetchall()
    values = {row["id"]: _loads(row["payload"]) for row in rows}
    values[pending.id] = pending.model_dump(mode="json")
    for dependency in pending.prerequisite_ids:
        if dependency not in values or dependency == pending.id:
            raise ValueError("Mission prerequisites must reference another active mission")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(mission_id: str):
        if mission_id in visiting:
            raise ValueError("Mission prerequisites cannot contain a cycle")
        if mission_id in visited:
            return
        visiting.add(mission_id)
        for dependency in values[mission_id].get("prerequisite_ids", []):
            if dependency in values:
                visit(dependency)
        visiting.remove(mission_id)
        visited.add(mission_id)

    for mission_id in values:
        visit(mission_id)


def list_plans(scenario_id: str, include_archived: bool = False) -> list[dict[str, Any]]:
    require_exercise(scenario_id)
    condition = "" if include_archived else "AND archived_at IS NULL"
    with connect() as db:
        rows = db.execute(f"SELECT * FROM response_plans WHERE scenario_id=? {condition} ORDER BY created_at,id",
                          (scenario_id,)).fetchall()
    return [_record(row) for row in rows]


def get_plan(scenario_id: str, plan_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM response_plans WHERE id=? AND scenario_id=? AND archived_at IS NULL",
                         (plan_id, scenario_id)).fetchone()
    if not row:
        raise KeyError(plan_id)
    return _record(row)


def save_plan(scenario_id: str, plan: ResponsePlan, expected_revision: int | None = None) -> dict[str, Any]:
    require_exercise(scenario_id)
    missions = {value["id"] for value in list_missions(scenario_id)}
    units = {value["id"] for value in list_units(scenario_id)}
    points = {value.id for value in get_scenario(scenario_id).points}
    for assignment in plan.assignments:
        if assignment.mission_id not in missions:
            raise ValueError("Plan assignments must reference active missions")
        if any(unit_id not in units for unit_id in assignment.unit_ids):
            raise ValueError("Plan assignments must reference scenario units")
        if assignment.source_point_id and assignment.source_point_id not in points:
            raise ValueError("Plan water sources must reference scenario points")
    stamp = now()
    plan = plan.model_copy(update={"scenario_id": scenario_id})
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM response_plans WHERE id=? AND scenario_id=?", (plan.id, scenario_id)).fetchone()
        if row:
            if expected_revision is None or row["revision"] != expected_revision:
                raise ExerciseConflict("Response plan changed; refresh before saving")
            plan = plan.model_copy(update={"revision": expected_revision + 1,
                                           "created_at": datetime.fromisoformat(row["created_at"]),
                                           "updated_at": datetime.fromisoformat(stamp)})
            db.execute("UPDATE response_plans SET payload=?,revision=?,updated_at=? WHERE id=?",
                       (_payload(plan), plan.revision, stamp, plan.id))
        else:
            plan = plan.model_copy(update={"revision": 1, "created_at": datetime.fromisoformat(stamp),
                                           "updated_at": datetime.fromisoformat(stamp)})
            db.execute("INSERT INTO response_plans VALUES (?,?,?,?,?,?,?)",
                       (plan.id, scenario_id, _payload(plan), 1, None, stamp, stamp))
    return plan.model_dump(mode="json")


def archive_plan(scenario_id: str, plan_id: str, expected_revision: int) -> None:
    with connect() as db:
        used = db.execute("SELECT 1 FROM exercise_runs WHERE scenario_id=? AND plan_id=? LIMIT 1",
                          (scenario_id, plan_id)).fetchone()
        # Referenced plans remain stored; archiving only removes them from the active authoring list.
        cursor = db.execute("UPDATE response_plans SET archived_at=?,updated_at=?,revision=revision+1 "
                            "WHERE id=? AND scenario_id=? AND revision=? AND archived_at IS NULL",
                            (now(), now(), plan_id, scenario_id, expected_revision))
        if not cursor.rowcount:
            raise ExerciseConflict("Response plan changed or is unavailable")
        _ = used


def create_snapshot(scenario_id: str, forecast_ids: list[str] | None = None,
                    assumption_overrides: list[str] | None = None) -> dict[str, Any]:
    scenario = require_exercise(scenario_id)
    situation = get_situation(scenario_id)
    allowed_runs = {run.id: run for run in scenario_runs(scenario_id) if run.status in {"ready", "partial"}}
    attached = attached_forecasts(scenario_id)
    all_allowed = {*allowed_runs, *attached}
    requested = forecast_ids if forecast_ids is not None else situation.get("selected_forecast_ids", [])
    if any(run_id not in all_allowed for run_id in requested):
        raise ValueError("Forecast must be a completed scenario result or explicitly attached historical result")
    forecast_conditions = []
    for run_id in requested:
        run = get_run(run_id)
        context = run.run_context or {}
        anchor = context.get("scenario_start_time") or situation.get("forecast_alignments", {}).get(run_id)
        if not anchor:
            raise ValueError(f"Forecast {run_id} has no recorded minute-zero time; provide an explicit exercise alignment")
        forecast_conditions.append({"run_id": run_id, "minute_zero": anchor,
                                    "duration_min": run.scenario.duration_min, "mode": run.mode,
                                    "source_scenario_id": run.scenario_id})
    snapshot_id = uuid4().hex[:12]
    payload = {
        "id": snapshot_id, "scenario_id": scenario_id, "reference_time": situation["reference_time"],
        "scenario_revision": scenario.revision, "situation_revision": situation["revision"],
        "situation": situation, "points": [point.model_dump(mode="json") for point in scenario.points],
        "closures": [value.model_dump(mode="json") for value in scenario.closures],
        "vehicles": list_vehicles(scenario_id), "units": list_units(scenario_id),
        "road_reports": list_road_reports(scenario_id), "existing_commitments": list_movements(scenario_id),
        "missions": list_missions(scenario_id), "forecast_ids": requested,
        "forecast_conditions": forecast_conditions,
        "forecast_lead_time_min": situation.get("forecast_lead_time_min", 10),
        "assumptions": [*situation.get("assumptions", []), *(assumption_overrides or [])],
        "prepared_road_package_id": scenario.area_package_id,
        "created_at": now(),
    }
    with connect() as db:
        db.execute("INSERT INTO situation_snapshots VALUES (?,?,?,?)",
                   (snapshot_id, scenario_id, _payload(payload), payload["created_at"]))
    return payload


def get_snapshot(scenario_id: str, snapshot_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT payload FROM situation_snapshots WHERE id=? AND scenario_id=?",
                         (snapshot_id, scenario_id)).fetchone()
    if not row:
        raise KeyError(snapshot_id)
    return _loads(row["payload"])


def list_snapshots(scenario_id: str) -> list[dict[str, Any]]:
    require_exercise(scenario_id)
    with connect() as db:
        rows = db.execute("SELECT payload FROM situation_snapshots WHERE scenario_id=? ORDER BY created_at DESC",
                          (scenario_id,)).fetchall()
    return [_loads(row["payload"]) for row in rows]


def attach_forecast(scenario_id: str, source_scenario_id: str, run_id: str) -> None:
    source = get_scenario(source_scenario_id)
    if not any(run.id == run_id and run.status in {"ready", "partial"} for run in scenario_runs(source.id)):
        raise ValueError("Only completed fire results can be attached")
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO exercise_artifact_refs VALUES (?,?,?,?)",
                   (scenario_id, source_scenario_id, run_id, now()))


def attached_forecasts(scenario_id: str) -> dict[str, str]:
    with connect() as db:
        rows = db.execute("SELECT run_id,source_scenario_id FROM exercise_artifact_refs WHERE scenario_id=?",
                          (scenario_id,)).fetchall()
    return {row["run_id"]: row["source_scenario_id"] for row in rows}


def exercise_summary(scenario_id: str) -> dict[str, Any]:
    scenario = get_scenario(scenario_id)
    if scenario.scenario_kind != "exercise":
        return {"scenario_kind": "legacy", "reference_time": None, "total_units": None,
                "available_units": None, "outstanding_missions": None, "saved_plans": None,
                "completed_experiments": None, "active_rehearsal": None, "data_status": "unavailable"}
    situation = get_situation(scenario_id)
    units = list_units(scenario_id)
    with connect() as db:
        experiments = db.execute("SELECT COUNT(*) AS value FROM response_experiments WHERE scenario_id=? AND status IN ('ready','partial')",
                                 (scenario_id,)).fetchone()["value"]
        rehearsal = db.execute("SELECT id,state,elapsed_min FROM exercise_runs WHERE scenario_id=? ORDER BY created_at DESC LIMIT 1",
                               (scenario_id,)).fetchone()
    missions = list_missions(scenario_id)
    return {"scenario_kind": "exercise", "reference_time": situation["reference_time"],
            "total_units": len(units), "available_units": sum(value.get("status") == "available" for value in units),
            "outstanding_missions": sum(value.get("status") == "required" for value in missions),
            "saved_plans": len(list_plans(scenario_id)), "completed_experiments": experiments,
            "active_rehearsal": dict(rehearsal) if rehearsal else None, "data_status": "ready"}


def create_experiment_record(scenario_id: str, snapshot_id: str, request: dict[str, Any],
                             request_key: str | None = None) -> dict[str, Any]:
    require_exercise(scenario_id)
    if request_key:
        existing = idempotent_record(scenario_id, "response-experiment", request_key)
        if existing:
            return get_experiment(scenario_id, existing)
    experiment_id, stamp = uuid4().hex[:12], now()
    with connect() as db:
        db.execute("INSERT INTO response_experiments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (experiment_id, scenario_id, snapshot_id, "queued", 0, "queued", _payload(request),
                    None, None, 0, stamp, stamp))
        if request_key:
            db.execute("INSERT INTO exercise_idempotency VALUES (?,?,?,?,?)",
                       (scenario_id, "response-experiment", request_key, experiment_id, stamp))
    return get_experiment(scenario_id, experiment_id)


def update_experiment(experiment_id: str, *, status: str, progress: int, stage: str,
                      result: dict[str, Any] | None = None, error: str | None = None) -> None:
    with connect() as db:
        db.execute("UPDATE response_experiments SET status=?,progress=?,stage=?,result=?,error=?,updated_at=? WHERE id=?",
                   (status, progress, stage, _payload(result) if result is not None else None, error, now(), experiment_id))


def get_experiment(scenario_id: str, experiment_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM response_experiments WHERE id=? AND scenario_id=?",
                         (experiment_id, scenario_id)).fetchone()
    if not row:
        raise KeyError(experiment_id)
    return {"id": row["id"], "scenario_id": row["scenario_id"], "snapshot_id": row["snapshot_id"],
            "status": row["status"], "progress": row["progress"], "stage": row["stage"],
            "request": _loads(row["request"]), "result": _loads(row["result"]), "error": row["error"],
            "cancel_requested": bool(row["cancel_requested"]), "created_at": row["created_at"],
            "updated_at": row["updated_at"]}


def list_experiments(scenario_id: str) -> list[dict[str, Any]]:
    require_exercise(scenario_id)
    with connect() as db:
        rows = db.execute("SELECT id FROM response_experiments WHERE scenario_id=? ORDER BY created_at DESC",
                          (scenario_id,)).fetchall()
    return [get_experiment(scenario_id, row["id"]) for row in rows]


def cancel_experiment(scenario_id: str, experiment_id: str) -> dict[str, Any]:
    with connect() as db:
        cursor = db.execute("UPDATE response_experiments SET cancel_requested=1,status='cancelled',stage='cancelled',updated_at=? "
                            "WHERE id=? AND scenario_id=? AND status IN ('queued','running')",
                            (now(), experiment_id, scenario_id))
    if not cursor.rowcount:
        return get_experiment(scenario_id, experiment_id)
    return get_experiment(scenario_id, experiment_id)


def retry_experiment(scenario_id: str, experiment_id: str) -> dict[str, Any]:
    with connect() as db:
        cursor = db.execute("UPDATE response_experiments SET cancel_requested=0,status='queued',stage='queued',progress=0,error=NULL,result=NULL,updated_at=? "
                            "WHERE id=? AND scenario_id=? AND status IN ('failed','interrupted','cancelled')",
                            (now(), experiment_id, scenario_id))
    if not cursor.rowcount:
        current = get_experiment(scenario_id, experiment_id)
        if current["status"] not in {"queued", "running"}:
            raise ExerciseConflict("Only failed, interrupted, or cancelled experiments can be retried")
    return get_experiment(scenario_id, experiment_id)


def experiment_cancelled(experiment_id: str) -> bool:
    with connect() as db:
        row = db.execute("SELECT cancel_requested FROM response_experiments WHERE id=?", (experiment_id,)).fetchone()
    return bool(row and row["cancel_requested"])


def next_queued_experiment() -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT id,scenario_id FROM response_experiments WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
    return get_experiment(row["scenario_id"], row["id"]) if row else None


def claim_experiment(experiment_id: str) -> bool:
    with connect() as db:
        changed = db.execute("UPDATE response_experiments SET status='running',stage='loading frozen inputs',progress=5,updated_at=? "
                             "WHERE id=? AND status='queued'", (now(), experiment_id)).rowcount
    return changed == 1


def create_exercise_run(scenario_id: str, snapshot_id: str, plan: dict[str, Any], evaluation: dict[str, Any],
                        request_key: str | None = None) -> dict[str, Any]:
    require_exercise(scenario_id)
    if request_key:
        existing = idempotent_record(scenario_id, "exercise-run", request_key)
        if existing:
            return get_exercise_run(scenario_id, existing)
    run_id, stamp = uuid4().hex[:12], now()
    schedule = []
    for mission in evaluation.get("missions", []):
        if mission.get("status") not in {"completed", "infeasible"}:
            continue
        start = mission.get("arrival_min") or mission.get("first_delivery_min") or 0
        completion = mission.get("completion_min") or start
        schedule.extend([
            {"offset_min": max(0, start - 0.01), "kind": "mission_travelling", "mission_id": mission["mission_id"],
             "unit_ids": mission.get("unit_ids", [])},
            {"offset_min": start, "kind": "mission_working", "mission_id": mission["mission_id"],
             "unit_ids": mission.get("unit_ids", [])},
            {"offset_min": completion, "kind": "mission_completed" if mission.get("status") == "completed" else "mission_blocked",
             "mission_id": mission["mission_id"], "unit_ids": mission.get("unit_ids", [])},
        ])
    schedule.sort(key=lambda value: (value["offset_min"], value["kind"], value["mission_id"]))
    payload = {"plan": plan, "evaluation": evaluation, "schedule": schedule, "injected_events": [],
               "branch": 1, "simulated": True}
    with connect() as db:
        db.execute("INSERT INTO exercise_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (run_id, scenario_id, snapshot_id, plan["id"], plan.get("revision", 1), "paused", 1,
                    0, _payload(payload), 1, stamp, stamp))
        if request_key:
            db.execute("INSERT INTO exercise_idempotency VALUES (?,?,?,?,?)",
                       (scenario_id, "exercise-run", request_key, run_id, stamp))
    return get_exercise_run(scenario_id, run_id)


def get_exercise_run(scenario_id: str, run_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM exercise_runs WHERE id=? AND scenario_id=?", (run_id, scenario_id)).fetchone()
        events = db.execute("SELECT * FROM exercise_events WHERE run_id=? ORDER BY offset_min,created_at", (run_id,)).fetchall()
    if not row:
        raise KeyError(run_id)
    payload = _loads(row["payload"])
    elapsed = row["elapsed_min"]
    latest_states: dict[str, str] = {}
    for event in payload.get("schedule", []):
        if event["offset_min"] <= elapsed:
            latest_states[event["mission_id"]] = event["kind"].replace("mission_", "")
    return {"id": row["id"], "scenario_id": row["scenario_id"], "snapshot_id": row["snapshot_id"],
            "plan_id": row["plan_id"], "plan_revision": row["plan_revision"], "state": row["state"],
            "speed": row["speed"], "elapsed_min": elapsed, "revision": row["revision"],
            "payload": payload, "mission_states": latest_states,
            "events": [{"id": value["id"], "kind": value["kind"], "offset_min": value["offset_min"],
                        "payload": _loads(value["payload"]), "created_at": value["created_at"], "simulated": True}
                       for value in events], "created_at": row["created_at"], "updated_at": row["updated_at"]}


def list_exercise_runs(scenario_id: str) -> list[dict[str, Any]]:
    require_exercise(scenario_id)
    with connect() as db:
        rows = db.execute("SELECT id FROM exercise_runs WHERE scenario_id=? ORDER BY created_at DESC", (scenario_id,)).fetchall()
    return [get_exercise_run(scenario_id, row["id"]) for row in rows]


def act_on_exercise_run(scenario_id: str, run_id: str, action: str, expected_revision: int,
                        speed: float | None = None, request_key: str | None = None) -> dict[str, Any]:
    if request_key:
        existing = idempotent_record(scenario_id, f"exercise-run-action:{run_id}", request_key)
        if existing:
            return get_exercise_run(scenario_id, run_id)
    current = get_exercise_run(scenario_id, run_id)
    if current["revision"] != expected_revision:
        raise ExerciseConflict("Exercise run changed; refresh before controlling playback")
    state, elapsed, selected_speed = current["state"], current["elapsed_min"], current["speed"]
    if action == "play": state = "running"
    elif action == "pause": state = "paused"
    elif action == "restart": state, elapsed = "paused", 0
    elif action == "step":
        state = "paused"
        future = [value["offset_min"] for value in current["payload"].get("schedule", []) if value["offset_min"] > elapsed]
        elapsed = min(future) if future else elapsed
    elif action == "set_speed":
        if speed not in {1, 5, 20}: raise ValueError("Playback speed must be 1, 5, or 20")
        selected_speed = speed
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        cursor = db.execute("UPDATE exercise_runs SET state=?,speed=?,elapsed_min=?,revision=revision+1,updated_at=? "
                            "WHERE id=? AND scenario_id=? AND revision=?",
                            (state, selected_speed, elapsed, now(), run_id, scenario_id, expected_revision))
        if not cursor.rowcount:
            raise ExerciseConflict("Exercise run changed; refresh before controlling playback")
        if request_key:
            db.execute("INSERT INTO exercise_idempotency VALUES (?,?,?,?,?)",
                       (scenario_id, f"exercise-run-action:{run_id}", request_key, run_id, now()))
    return get_exercise_run(scenario_id, run_id)


def advance_exercise_run(scenario_id: str, run_id: str, minutes: float) -> dict[str, Any]:
    current = get_exercise_run(scenario_id, run_id)
    if current["state"] != "running":
        return current
    last = max((value["offset_min"] for value in current["payload"].get("schedule", [])), default=0)
    elapsed = min(last, current["elapsed_min"] + minutes * current["speed"])
    state = "completed" if elapsed >= last else "running"
    with connect() as db:
        db.execute("UPDATE exercise_runs SET state=?,elapsed_min=?,revision=revision+1,updated_at=? WHERE id=? AND scenario_id=?",
                   (state, elapsed, now(), run_id, scenario_id))
    return get_exercise_run(scenario_id, run_id)


def add_exercise_event(scenario_id: str, run_id: str, kind: str, offset_min: float,
                       payload: dict[str, Any], request_key: str | None = None) -> dict[str, Any]:
    if request_key:
        existing = idempotent_record(scenario_id, f"exercise-event:{run_id}", request_key)
        if existing:
            return get_exercise_run(scenario_id, run_id)
    current = get_exercise_run(scenario_id, run_id)
    event_id, stamp = uuid4().hex[:12], now()
    run_payload = current["payload"]
    run_payload.setdefault("injected_events", []).append({"id": event_id, "kind": kind,
                                                           "offset_min": offset_min, "payload": payload})
    affected = []
    target_id = payload.get("unit_id") or payload.get("source_point_id") or payload.get("segment_id")
    for assignment in run_payload.get("plan", {}).get("assignments", []):
        if (target_id in assignment.get("unit_ids", []) or target_id == assignment.get("source_point_id")
                or kind in {"road_blockage", "road_reopening"}):
            affected.append(assignment["mission_id"])
    run_payload["affected_mission_ids"] = sorted(set(affected))
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO exercise_events VALUES (?,?,?,?,?,?,?)",
                   (event_id, run_id, scenario_id, kind, offset_min, _payload(payload), stamp))
        db.execute("UPDATE exercise_runs SET state='paused',payload=?,revision=revision+1,updated_at=? WHERE id=?",
                   (_payload(run_payload), stamp, run_id))
        if request_key:
            db.execute("INSERT INTO exercise_idempotency VALUES (?,?,?,?,?)",
                       (scenario_id, f"exercise-event:{run_id}", request_key, event_id, stamp))
    return get_exercise_run(scenario_id, run_id)


def idempotent_record(scenario_id: str, action: str, request_key: str) -> str | None:
    with connect() as db:
        row = db.execute("SELECT record_id FROM exercise_idempotency WHERE scenario_id=? AND action=? AND request_key=?",
                         (scenario_id, action, request_key)).fetchone()
    return row["record_id"] if row else None


def _record(row) -> dict[str, Any]:
    value = _loads(row["payload"])
    value.update(revision=row["revision"], created_at=row["created_at"], updated_at=row["updated_at"])
    if "archived_at" in row.keys():
        value["archived_at"] = row["archived_at"]
    return value
