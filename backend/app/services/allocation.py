from __future__ import annotations

import itertools
import json
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from pyproj import Transformer
from rasterio.features import rasterize
from scipy.optimize import Bounds, LinearConstraint, milp
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import transform as transform_geometry

from ..io import load_result
from ..models import (AllocationAssignment, AllocationPlan, AllocationRankRequest,
                      ContainmentSuggestionsRequest, ContainmentTask, RouteAnalysisRequest,
                      RouteLocation, ScenarioWorkspace)
from .routing import analyse_routes


def suggest_tasks(workspace: ScenarioWorkspace, run, request: ContainmentSuggestionsRequest,
                  runs_dir: Path) -> list[dict[str, Any]]:
    result = load_result(runs_dir / run.id)
    forward = Transformer.from_crs("EPSG:4326", result.crs, always_xy=True).transform
    reverse = Transformer.from_crs(result.crs, "EPSG:4326", always_xy=True).transform
    threatened = []
    for asset in (point for point in workspace.points if point.kind == "asset"):
        minute = _point_arrival(result, asset.coordinates)
        if minute is not None and minute <= run.scenario.duration_min:
            threatened.append((-(asset.asset.priority if asset.asset else 3), minute, asset))
    tasks = []
    for _, arrival, asset in sorted(threatened, key=lambda value: (value[0], value[1], value[2].id)):
        center = transform_geometry(forward, Point(asset.coordinates))
        ring = center.buffer(request.standoff_m, resolution=12).exterior
        cells = _geometry_cells(result, ring)
        if not cells or any(not result.coverage[row, col] for row, col in cells):
            continue
        geographic = transform_geometry(reverse, ring)
        task = ContainmentTask(
            name=f"Defensive line · {asset.name}", geometry=mapping(geographic),
            protected_asset_ids=[asset.id], source="suggested",
        )
        tasks.append({**task.model_dump(mode="json"), "asset_arrival_min": arrival,
                      "standoff_m": request.standoff_m})
        if len(tasks) >= request.max_tasks:
            break
    return tasks


def rank_plans(workspace: ScenarioWorkspace, run, request: AllocationRankRequest,
               road_path: Path, prepared: Path, runs_dir: Path) -> dict[str, Any]:
    result = load_result(runs_dir / run.id)
    teams = [team for team in workspace.teams if team.status == "available"]
    tasks = [task for task in workspace.containment_tasks if task.enabled]
    if len(teams) > 8:
        raise ValueError("Fast ranking supports at most eight available teams")
    if not teams or not tasks:
        return {"plans": [], "message": "Add at least one available team and containment task.",
                "assumptions": _assumptions(request)}
    bases = {point.id: point for point in workspace.points if point.kind == "response_base"}
    assets = {point.id: point for point in workspace.points if point.kind == "asset"}
    evaluations: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    options = []
    for task in tasks:
        for size in range(1, len(teams) + 1):
            for coalition in itertools.combinations(teams, size):
                evaluation = _evaluate_assignment(task, coalition, bases, assets, result, run,
                                                  request, road_path, prepared, workspace.closures)
                key = task.id, tuple(team.id for team in coalition)
                evaluations[key] = evaluation
                if evaluation["status"] != "infeasible":
                    options.append((task, coalition, evaluation))

    if request.configurations is not None:
        normalized = {(task_id, tuple(sorted(team_ids))): value for (task_id, team_ids), value in evaluations.items()}
        plans = [_evaluate_plan(plan, normalized, assets) for plan in request.configurations]
        plans.sort(key=_plan_sort_key)
        return {"plans": plans, "assumptions": _assumptions(request)}

    plans = _solve_plans(options, teams, tasks, assets, request.count)
    for plan in plans:
        plan["assignments"] = [evaluations[(item["task_id"], tuple(item["team_ids"]))]
                               for item in plan["assignments"]]
    plans.sort(key=_plan_sort_key)
    for index, plan in enumerate(plans):
        plan["rank"] = index + 1
        plan["name"] = f"Suggested plan {index + 1}"
    return {"plans": plans, "assumptions": _assumptions(request)}


def build_intervention(workspace: ScenarioWorkspace, run, plan: AllocationPlan,
                       departure_min: float, lead_time_min: float, road_path: Path,
                       prepared: Path, runs_dir: Path) -> dict[str, Any]:
    ranked = rank_plans(workspace, run, AllocationRankRequest(
        run_id=run.id, departure_min=departure_min, lead_time_min=lead_time_min,
        configurations=[plan]), road_path, prepared, runs_dir)
    if not ranked["plans"]:
        raise ValueError(f"Plan {plan.name} has no assignments")
    evaluated = ranked["plans"][0]
    tasks = []
    for assignment in evaluated["assignments"]:
        if assignment["status"] == "infeasible":
            raise ValueError(f"{assignment['task_name']} is not feasible under the selected forecast")
        task = next(value for value in workspace.containment_tasks if value.id == assignment["task_id"])
        tasks.append({"task_id": task.id, "task_name": task.name, "geometry": task.geometry,
                      "protected_asset_ids": task.protected_asset_ids,
                      "activation_min": assignment["completion_min"],
                      "team_ids": assignment["team_ids"]})
    return {"schema_version": 1, "kind": "timed_containment", "plan_id": plan.id,
            "plan_name": plan.name, "source_run_id": run.id, "tasks": tasks,
            "evaluation": evaluated, "assumption": "Completed unbreached lines are impermeable."}


def intervention_cells(result, intervention: dict[str, Any]) -> tuple[np.ndarray, list[dict[str, Any]]]:
    schedule = np.full(result.arrival_minutes.shape, np.inf, dtype="float32")
    task_cells = []
    forward = Transformer.from_crs("EPSG:4326", result.crs, always_xy=True).transform
    for task in intervention.get("tasks", []):
        geometry = transform_geometry(forward, shape(task["geometry"]))
        cells = _geometry_cells(result, geometry)
        activation = float(task["activation_min"])
        for row, col in cells:
            schedule[row, col] = min(schedule[row, col], activation)
        task_cells.append({**task, "cells": [[row, col] for row, col in cells]})
    return schedule, task_cells


def allocation_comparison(parent, children, source_run, workspace: ScenarioWorkspace,
                          runs_dir: Path) -> dict[str, Any]:
    control = load_result(runs_dir / source_run.id)
    assets = [point for point in workspace.points if point.kind == "asset"]
    control_area = _burned_area(control)
    control_roads = _road_exposure(source_run, runs_dir)
    members, failed = [], []
    for child in children:
        if child.status != "ready":
            if child.status in {"failed", "cancelled", "interrupted"}:
                failed.append({"run_id": child.id, "status": child.status, "error": child.error,
                               "plan_name": (child.intervention or {}).get("plan_name", "Plan")})
            continue
        result = load_result(runs_dir / child.id)
        exposed_roads = _road_exposure(child, runs_dir)
        asset_results = []
        reached_by_priority = {str(priority): 0 for priority in range(1, 6)}
        for asset in assets:
            baseline = _point_arrival(control, asset.coordinates)
            intervention = _point_arrival(result, asset.coordinates)
            priority = asset.asset.priority if asset.asset else 3
            if intervention is not None:
                reached_by_priority[str(priority)] += 1
            asset_results.append({"asset_id": asset.id, "name": asset.name, "priority": priority,
                                  "control_arrival_min": baseline, "arrival_min": intervention,
                                  "delay_min": None if baseline is None or intervention is None else intervention - baseline})
        manifest = result.manifest or {}
        members.append({
            "run_id": child.id, "plan_id": (child.intervention or {}).get("plan_id"),
            "plan_name": (child.intervention or {}).get("plan_name", "Plan"),
            "burned_area_ha": _burned_area(result),
            "burned_area_change_ha": _burned_area(result) - control_area,
            "exposed_roads": exposed_roads,
            "road_exposure_change": exposed_roads - control_roads,
            "assets": asset_results, "reached_by_priority": reached_by_priority,
            "containment": manifest.get("intervention", {}),
            "runtime_seconds": manifest.get("runtime_seconds", 0),
            "effort_min": (child.intervention or {}).get("evaluation", {}).get("total_effort_min", 0),
        })
    members.sort(key=lambda value: tuple(value["reached_by_priority"][str(priority)] for priority in range(5, 0, -1))
                 + (value["burned_area_ha"], value["effort_min"], value["plan_name"]))
    for index, member in enumerate(members):
        member["rank"] = index + 1
    return {"run_id": parent.id, "source_run_id": source_run.id, "engine": source_run.scenario.engine,
            "control": {"burned_area_ha": control_area, "exposed_roads": control_roads},
            "members": members, "failed": failed,
            "assumption": "Completed unbreached containment lines are deterministic impermeable barriers."}


def _road_exposure(run, runs_dir: Path) -> int:
    path = runs_dir / run.id / f"roads-{int(run.scenario.exposure_buffer_m)}m.geojson"
    if not path.exists():
        return 0
    roads = json.loads(path.read_text())
    return sum(feature.get("properties", {}).get("first_exposure_min") is not None
               for feature in roads.get("features", []))


def _evaluate_assignment(task, coalition, bases, assets, result, run, request, road_path, prepared, closures):
    line = shape(task.geometry)
    forward = Transformer.from_crs("EPSG:4326", result.crs, always_xy=True).transform
    projected = transform_geometry(forward, line)
    length_m = float(projected.length)
    cells = _geometry_cells(result, projected)
    exposures = [float(result.arrival_minutes[row, col]) for row, col in cells
                 if np.isfinite(result.arrival_minutes[row, col])]
    fire_arrival = min(exposures) if exposures else None
    access = []
    for team in coalition:
        base = bases.get(team.base_point_id)
        if base is None:
            return _assignment_payload(task, coalition, "infeasible", length_m, None, fire_arrival,
                                       None, [], "Team response base is missing.")
        access_point = _nearest_line_point(line, base.coordinates)
        departure = max(request.departure_min, team.available_from_min)
        route = analyse_routes(road_path, RouteAnalysisRequest(
            origin=RouteLocation(name=base.name, coordinates=base.coordinates),
            destination=RouteLocation(name=task.name, coordinates=access_point),
            departure_min=departure, closures=closures, alternatives=0,
            exposure_buffer_m=run.scenario.exposure_buffer_m,
            simulation_horizon_min=run.scenario.duration_min), prepared)
        if not route["routes"]:
            return _assignment_payload(task, coalition, "infeasible", length_m, None, fire_arrival,
                                       None, access, f"{team.name} has no feasible access route.")
        selected = route["routes"][0]
        access.append({"team": team, "base": base, "access_point": access_point,
                       "departure": departure, "arrival": selected["arrival_min"],
                       "outbound": selected})
    completion = _completion_min(length_m, [(item["arrival"], item["team"].line_rate_m_min) for item in access])
    route_payloads, total_effort, unknown = [], 0.0, False
    for item in access:
        team, base = item["team"], item["base"]
        route = analyse_routes(road_path, RouteAnalysisRequest(
            origin=RouteLocation(name=base.name, coordinates=base.coordinates),
            destination=RouteLocation(name=task.name, coordinates=item["access_point"]),
            departure_min=item["departure"], on_scene_min=max(0, completion - item["arrival"]),
            withdrawal_destination=RouteLocation(name=base.name, coordinates=base.coordinates),
            closures=closures, alternatives=0, exposure_buffer_m=run.scenario.exposure_buffer_m,
            simulation_horizon_min=run.scenario.duration_min), prepared)
        withdrawal = route.get("withdrawal")
        if not route["routes"] or not withdrawal or withdrawal.get("status") == "unavailable":
            return _assignment_payload(task, coalition, "infeasible", length_m, completion, fire_arrival,
                                       None, route_payloads, f"{team.name} has no feasible withdrawal route.")
        return_min = withdrawal["arrival_min"]
        if return_min - item["departure"] > team.max_deployment_min:
            return _assignment_payload(task, coalition, "infeasible", length_m, completion, fire_arrival,
                                       None, route_payloads, f"{team.name} exceeds its deployment limit.")
        unknown = unknown or route["routes"][0]["status"] == "unknown" or withdrawal["status"] == "unknown"
        total_effort += return_min - item["departure"]
        route_payloads.append({"team_id": team.id, "team_name": team.name,
                               "outbound": route["routes"][0], "withdrawal": withdrawal})
    margin = None if fire_arrival is None else fire_arrival - completion
    feasible = fire_arrival is None or margin >= request.lead_time_min
    status = "unknown" if unknown or fire_arrival is None else "feasible" if feasible else "infeasible"
    message = ("Line exposure was not reached within the selected run; timing remains horizon-limited."
               if fire_arrival is None else "Line completes before the configured lead-time threshold."
               if feasible else "The line does not complete before the configured lead-time threshold.")
    return _assignment_payload(task, coalition, status, length_m, completion, fire_arrival,
                               margin, route_payloads, message, total_effort)


def _assignment_payload(task, coalition, status, length, completion, fire_arrival, margin, routes, message,
                        effort=0.0):
    return {"task_id": task.id, "task_name": task.name,
            "protected_asset_ids": task.protected_asset_ids,
            "team_ids": [team.id for team in coalition],
            "team_names": [team.name for team in coalition], "status": status,
            "line_length_m": length, "completion_min": completion,
            "fire_arrival_min": fire_arrival, "margin_min": margin, "routes": routes,
            "effort_min": effort, "message": message}


def _solve_plans(options, teams, tasks, assets, count):
    if not options:
        return []
    rows = []
    upper = []
    for team in teams:
        rows.append([1.0 if team in coalition else 0.0 for _, coalition, _ in options]); upper.append(1.0)
    for task in tasks:
        rows.append([1.0 if task.id == selected.id else 0.0 for selected, _, _ in options]); upper.append(1.0)
    constraints = [LinearConstraint(np.asarray(rows), np.zeros(len(rows)), np.asarray(upper))]
    coefficients = []
    for task, _, evaluation in options:
        priority = sum(10 ** ((assets[asset_id].asset.priority if assets[asset_id].asset else 3) - 1)
                       for asset_id in task.protected_asset_ids if asset_id in assets)
        known = 1 if evaluation["status"] == "feasible" else 0
        margin = max(-120, min(720, evaluation["margin_min"] or 0))
        coefficients.append(-(priority * 10000 + known * 1000 + margin - evaluation["effort_min"] / 1000))
    solutions = []
    extra_rows = []
    for _ in range(count):
        selected_constraints = constraints
        if extra_rows:
            selected_constraints = [*constraints, LinearConstraint(np.asarray(extra_rows),
                                                                    np.zeros(len(extra_rows)),
                                                                    np.asarray([sum(row) - 1 for row in extra_rows]))]
        solved = milp(np.asarray(coefficients), integrality=np.ones(len(options)),
                      bounds=Bounds(0, 1), constraints=selected_constraints,
                      options={"time_limit": 2})
        if not solved.success:
            break
        selected = [index for index, value in enumerate(solved.x) if value > .5]
        if not selected:
            break
        assignments = [{"task_id": options[index][0].id,
                        "team_ids": [team.id for team in options[index][1]]} for index in selected]
        plan = AllocationPlan(name="Suggested plan", assignments=[AllocationAssignment(**item) for item in assignments])
        evaluated = _evaluate_plan(plan, {(task.id, tuple(team.id for team in coalition)): evaluation
                                          for task, coalition, evaluation in options}, assets)
        solutions.append(evaluated)
        row = np.zeros(len(options))
        row[selected] = 1
        extra_rows.append(row)
    return solutions


def _evaluate_plan(plan, evaluations, assets):
    assignments = []
    counts = {str(priority): 0 for priority in range(1, 6)}
    margins, effort = [], 0.0
    for assignment in plan.assignments:
        evaluation = evaluations.get((assignment.task_id, tuple(sorted(assignment.team_ids))))
        if evaluation is None:
            evaluation = {"task_id": assignment.task_id, "task_name": assignment.task_id,
                          "team_ids": assignment.team_ids, "team_names": [], "status": "infeasible",
                          "line_length_m": 0, "completion_min": None, "fire_arrival_min": None,
                          "margin_min": None, "routes": [], "effort_min": 0,
                          "message": "This edited team combination was not evaluated."}
        assignments.append(evaluation)
        effort += evaluation["effort_min"]
        if evaluation["margin_min"] is not None:
            margins.append(evaluation["margin_min"])
        if evaluation["status"] == "feasible":
            for asset_id in evaluation.get("protected_asset_ids", []):
                if asset_id in assets:
                    counts[str(assets[asset_id].asset.priority if assets[asset_id].asset else 3)] += 1
    return {"id": plan.id, "name": plan.name, "assignments": assignments,
            "protected_by_priority": counts,
            "feasible_tasks": sum(value["status"] == "feasible" for value in assignments),
            "unknown_tasks": sum(value["status"] == "unknown" for value in assignments),
            "worst_margin_min": min(margins) if margins else None,
            "total_effort_min": effort}


def _plan_sort_key(plan):
    counts = plan.get("protected_by_priority", {})
    return tuple(-counts.get(str(priority), 0) for priority in range(5, 0, -1)) + (
        -plan.get("feasible_tasks", 0), -(plan.get("worst_margin_min") or -math.inf),
        plan.get("total_effort_min", math.inf), plan.get("id", ""))


def _completion_min(length_m, arrivals):
    remaining = length_m
    ordered = sorted(arrivals)
    minute, rate = ordered[0][0], 0.0
    for arrival, added_rate in ordered:
        if rate and arrival > minute:
            possible = rate * (arrival - minute)
            if possible >= remaining:
                return minute + remaining / rate
            remaining -= possible
        minute = max(minute, arrival)
        rate += added_rate
    return minute + remaining / rate


def _nearest_line_point(line, coordinates):
    point = Point(coordinates)
    nearest = line.interpolate(line.project(point))
    return nearest.x, nearest.y


def _point_arrival(result, coordinates):
    forward = Transformer.from_crs("EPSG:4326", result.crs, always_xy=True)
    x, y = forward.transform(*coordinates)
    col, row = ~result.transform @ (x, y)
    row, col = int(row), int(col)
    if not (0 <= row < result.arrival_minutes.shape[0] and 0 <= col < result.arrival_minutes.shape[1]):
        return None
    value = result.arrival_minutes[row, col]
    return float(value) if np.isfinite(value) else None


def _geometry_cells(result, geometry):
    mask = rasterize([(mapping(geometry), 1)], out_shape=result.arrival_minutes.shape,
                     transform=result.transform, fill=0, all_touched=True, dtype="uint8")
    return [tuple(map(int, value)) for value in np.argwhere(mask == 1)]


def _burned_area(result):
    return round(float(np.count_nonzero(np.isfinite(result.arrival_minutes)))
                 * abs(result.transform.a * result.transform.e) / 10000, 3)


def _assumptions(request):
    return {"kind": "logistics_ranking", "lead_time_min": request.lead_time_min,
            "fire_effect": "The fixed-forecast ranking does not estimate changes to fire spread.",
            "line_rule": "The whole line must be completed before the lead-time threshold."}
