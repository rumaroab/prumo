from __future__ import annotations

from .exercise_planner import evaluate_plan
from .exercise_routing import snapshot_route_assessor
from .exercise_storage import (experiment_cancelled, get_experiment, get_snapshot,
                               update_experiment)


def evaluate_experiment_job(scenario_id: str, experiment_id: str) -> None:
    """Evaluate frozen plan versions; safe to run in the single exercise-worker slot."""
    try:
        experiment = get_experiment(scenario_id, experiment_id)
        if experiment_cancelled(experiment_id):
            return
        snapshot = get_snapshot(scenario_id, experiment["snapshot_id"])
        request = experiment["request"]
        conditions = request.get("forecast_ids") or [None]
        plans_by_id = {value["id"]: value for value in request.get("plan_versions", [])}
        results = []
        for plan_index, plan_id in enumerate(request["plan_ids"]):
            if experiment_cancelled(experiment_id):
                return
            plan = plans_by_id.get(plan_id)
            if not plan:
                raise ValueError(f"Frozen response plan {plan_id} is unavailable")
            condition_results = [evaluate_plan(snapshot, plan, request["horizon_min"], forecast_id,
                                                snapshot_route_assessor(snapshot, forecast_id))
                                 for forecast_id in conditions]
            results.append({"plan_id": plan_id, "plan_name": plan["name"], "conditions": condition_results,
                            "worst_case_fulfilment": {str(priority): min(value["fulfilment_by_priority"][str(priority)]
                                for value in condition_results) for priority in range(5, 0, -1)}})
            update_experiment(experiment_id, status="running",
                              progress=10 + int(80 * (plan_index + 1) / len(request["plan_ids"])),
                              stage=f"evaluated {plan_index + 1} of {len(request['plan_ids'])} plans")
        result = {"plans": results, "snapshot_id": experiment["snapshot_id"], "horizon_min": request["horizon_min"],
                  "primary_forecast_id": request.get("primary_forecast_id"),
                  "message": "Condition results are shown separately; no opaque overall best-plan score is assigned."}
        update_experiment(experiment_id, status="ready", progress=100, stage="complete", result=result)
    except Exception as error:
        update_experiment(experiment_id, status="failed", progress=100, stage="failed", error=str(error))
