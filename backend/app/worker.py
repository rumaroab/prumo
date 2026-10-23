from __future__ import annotations

import json
import os
import time
import traceback
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from threading import Event, Thread

import numpy as np
from pyproj import CRS
from rasterio.transform import Affine

from .engines import ENGINES, compatible_profile
from .area_packages import package_path
from .io import load_landscape, load_result, save_result
from .models import Scenario, SimulationResult
from .services.exposure import analyse
from .services.comparison import comparison_payload
from .settings import RUNS, ensure_dirs
from .storage import (active_parents, child_runs, claim_run, create_run, init_db,
                      queued_runs, recoverable_remote_runs, update_run)
from .fogos import tracking_loop
from .exercise_jobs import evaluate_experiment_job
from .exercise_storage import claim_experiment, next_queued_experiment


def process(run) -> None:
    if run.mode != "single" and run.parent_id is None:
        _expand_parent(run)
        return
    output = RUNS / run.id
    output.mkdir(parents=True, exist_ok=True)
    try:
        update_run(run.id, status="running", stage="preparing", progress=10, error=None)
        prepared = package_path(run.area_package_id)
        landscape = load_landscape(prepared)
        engine = ENGINES.get(run.scenario.engine)
        if engine is None:
            raise RuntimeError(f"Engine {run.scenario.engine} is no longer installed; historical results remain readable")
        available, reason = engine.available()
        if not available:
            raise RuntimeError(reason)
        descriptor = engine.descriptor
        weather_modes = descriptor.profile_weather.get(run.scenario.engine_profile, descriptor.weather_modes)
        if run.scenario.weather_source.kind not in weather_modes:
            raise ValueError(f"{descriptor.display_name} does not support {run.scenario.weather_source.kind} weather")
        engine.validate(run.scenario)
        runner_name = engine.runner_name() if hasattr(engine, "runner_name") else descriptor.runner
        update_run(run.id, runner=runner_name, stage="simulating", progress=25)
        result = (engine.simulate(landscape, run.scenario, output, intervention=run.intervention)
                  if run.intervention else engine.simulate(landscape, run.scenario, output))
        validate_result(result, landscape, run.scenario.engine)
        reached = np.isfinite(result.arrival_minutes)
        boundary_reached = bool(reached[0, :].any() or reached[-1, :].any()
                                or reached[:, 0].any() or reached[:, -1].any())
        result.provenance["boundary_reached"] = boundary_reached
        result.provenance["area_package_id"] = run.area_package_id or "legacy"
        if result.manifest is not None:
            result.manifest["area_package_id"] = run.area_package_id or "legacy"
            result.manifest["boundary_reached"] = boundary_reached
        if (output / "cancel.requested").exists():
            update_run(run.id, status="cancelled", stage="cancelled", progress=100)
            return
        save_result(result, output)
        update_run(run.id, status="postprocessing", stage="postprocessing", progress=80)
        analyse(result, run.scenario.exposure_buffer_m, output, prepared)
        if (output / "cancel.requested").exists():
            update_run(run.id, status="cancelled", stage="cancelled", progress=100)
            return
        update_run(run.id, status="ready", stage="ready", progress=100)
    except Exception as error:
        (output / "error.log").write_text(traceback.format_exc())
        if (output / "cancel.requested").exists():
            update_run(run.id, status="cancelled", stage="cancelled", error=None, progress=100)
        else:
            update_run(run.id, status="failed", stage="failed", error=str(error), progress=100)


def validate_result(result: SimulationResult, landscape, engine_id: str) -> None:
    """Reject malformed plug-in output before it can become a published fire layer."""
    if not isinstance(result, SimulationResult) or result.engine != engine_id:
        raise ValueError("Engine returned an invalid result identity")
    if not isinstance(result.arrival_minutes, np.ndarray) or not isinstance(result.coverage, np.ndarray):
        raise ValueError("Engine result grids must be arrays")
    if result.arrival_minutes.shape != landscape.fuel.shape or result.coverage.shape != landscape.fuel.shape:
        raise ValueError("Engine result grid shape differs from the prepared area")
    if result.coverage.dtype != np.bool_ or not result.coverage.any() or np.any(result.coverage & ~landscape.coverage):
        raise ValueError("Engine result coverage is invalid")
    if not isinstance(result.transform, Affine) or not np.allclose(tuple(result.transform)[:6], tuple(landscape.transform)[:6]):
        raise ValueError("Engine result coordinates differ from the prepared area")
    try:
        result_crs = CRS.from_user_input(result.crs)
        landscape_crs = CRS.from_user_input(landscape.crs)
    except Exception as error:
        raise ValueError("Engine result CRS is invalid") from error
    if result_crs != landscape_crs:
        raise ValueError("Engine result CRS differs from the prepared area")
    if (not np.issubdtype(result.arrival_minutes.dtype, np.number)
            or np.any(result.arrival_minutes[np.isfinite(result.arrival_minutes)] < 0)
            or not np.isfinite(result.arrival_minutes[result.coverage]).any()):
        raise ValueError("Engine result arrival times are invalid")
    if not np.isfinite(result.temporal_resolution_min) or result.temporal_resolution_min <= 0:
        raise ValueError("Engine result time resolution is invalid")
    if not result.engine_version or not isinstance(result.provenance, dict) or not result.provenance:
        raise ValueError("Engine result provenance is missing")
    if result.member_arrivals and any(not isinstance(member, np.ndarray) or member.shape != landscape.fuel.shape
                                      for member in result.member_arrivals):
        raise ValueError("Engine member grid shape is invalid")


def _dispatch(run) -> None:
    try:
        process(run)
    except Exception as error:
        output = RUNS / run.id
        output.mkdir(parents=True, exist_ok=True)
        (output / "error.log").write_text(traceback.format_exc())
        update_run(run.id, status="failed", stage="failed", error=str(error), progress=100)


def _expand_parent(run) -> None:
    if child_runs(run.id):
        update_run(run.id, status="running", stage="running members", progress=5)
        return
    ensemble = run.ensemble or {}
    scenarios: list[Scenario] = []
    if run.mode == "parameter_ensemble":
        preset = ensemble.get("preset", "quick")
        variations = ([(1.0, 0), (.8, -15), (1.2, 15)] if preset == "quick" else
                      [(factor, offset) for factor in (.8, 1.0, 1.2) for offset in (-15, 0, 15)])
        for index, (factor, offset) in enumerate(variations):
            scenario = run.scenario.model_copy(deep=True)
            scenario.name = f"{run.scenario.name} · member {index + 1}"
            scenario.wind_speed_kmh = min(120, round(run.scenario.wind_speed_kmh * factor, 2))
            scenario.wind_direction_deg = (run.scenario.wind_direction_deg + offset) % 360
            scenario.seed = run.scenario.seed + index
            scenarios.append(scenario)
    elif run.mode == "engine_comparison":
        for engine_name in ensemble.get("engines", []):
            scenario = run.scenario.model_copy(deep=True)
            scenario.engine = engine_name
            engine = ENGINES[engine_name]
            profile = compatible_profile(engine, scenario.weather_source.kind)
            if profile is None:
                update_run(run.id, status="failed", stage="failed", progress=100,
                           error=f"{engine_name} has no profile for {scenario.weather_source.kind} weather")
                return
            scenario.engine_profile = profile
            scenario.name = f"{run.scenario.name} · {engine_name}"
            scenarios.append(scenario)
    elif run.mode == "allocation_comparison":
        interventions = ensemble.get("interventions", [])
        if not interventions:
            update_run(run.id, status="failed", stage="failed", progress=100,
                       error="Allocation comparison has no plans")
            return
        update_run(run.id, status="running", stage="queued plans", progress=5,
                   expected_members=len(interventions))
        for index, intervention in enumerate(interventions):
            scenario = run.scenario.model_copy(deep=True)
            scenario.name = f"{run.scenario.name} · {intervention.get('plan_name', f'plan {index + 1}')}"
            create_run(scenario, parent_id=run.id, member_index=index, intervention=intervention)
        return
    if not scenarios:
        update_run(run.id, status="failed", stage="failed", progress=100, error="Ensemble has no members")
        return
    update_run(run.id, status="running", stage="queued members", progress=5, expected_members=len(scenarios))
    for index, scenario in enumerate(scenarios):
        create_run(scenario, parent_id=run.id, member_index=index)


def _reconcile_parents() -> None:
    terminal = {"ready", "failed", "cancelled", "interrupted"}
    for parent in active_parents():
        children = child_runs(parent.id)
        if not children:
            continue
        completed = sum(child.status in terminal for child in children)
        update_run(parent.id, progress=min(95, 5 + int(90 * completed / len(children))),
                   stage=f"members {completed}/{len(children)}")
        if completed != len(children):
            continue
        successful = [child for child in children if child.status == "ready"]
        if not successful:
            update_run(parent.id, status="failed", stage="failed", progress=100, error="All ensemble members failed")
            continue
        try:
            if parent.mode == "parameter_ensemble":
                _aggregate_parameter(parent, successful)
            elif parent.mode == "engine_comparison":
                _write_comparison(parent, children)
            else:
                _write_allocation(parent, children)
            status = "ready" if len(successful) == len(children) else "partial"
            update_run(parent.id, status=status, stage=status, progress=100,
                       error=None if status == "ready" else f"{len(children) - len(successful)} members failed")
        except Exception as error:
            output = RUNS / parent.id
            output.mkdir(parents=True, exist_ok=True)
            (output / "error.log").write_text(traceback.format_exc())
            update_run(parent.id, status="failed", stage="failed", progress=100, error=str(error))


def _aggregate_parameter(parent, successful) -> None:
    results = [load_result(RUNS / child.id) for child in successful]
    stack = np.stack([result.arrival_minutes for result in results])
    first = results[0]
    horizon = float(parent.scenario.duration_min)
    censored = np.where(np.isfinite(stack), stack, horizon + first.temporal_resolution_min)
    p10, median, p90 = (np.percentile(censored, percentile, axis=0).astype("float32")
                        for percentile in (10, 50, 90))
    for grid in (p10, median, p90):
        grid[(grid > horizon) | ~first.coverage] = np.nan
    output = RUNS / parent.id
    output.mkdir(parents=True, exist_ok=True)
    result = SimulationResult(
        median, first.coverage, first.transform, first.crs, first.temporal_resolution_min,
        f"{first.engine} parameter ensemble", "ensemble-1",
        {"member_run_ids": [child.id for child in successful], "successful_members": len(successful),
         "expected_members": parent.expected_members, "horizon_min": parent.scenario.duration_min},
        manifest={"schema_version": 1, "kind": "parameter_ensemble",
                  "preset": (parent.ensemble or {}).get("preset", "quick"),
                  "area_package_id": parent.area_package_id or "legacy",
                  "boundary_reached": any(bool(item.provenance.get("boundary_reached")) for item in results)},
        member_arrivals=[item.arrival_minutes for item in results],
    )
    save_result(result, output)
    np.savez_compressed(output / "percentiles.npz", p10=p10, p50=median, p90=p90)
    analyse(result, parent.scenario.exposure_buffer_m, output, package_path(parent.area_package_id))


def _write_comparison(parent, children) -> None:
    output = RUNS / parent.id
    output.mkdir(parents=True, exist_ok=True)
    payload = comparison_payload(parent, children, parent.scenario.duration_min, RUNS)
    (output / "comparison.json").write_text(json.dumps(payload, indent=2))


def _write_allocation(parent, children) -> None:
    output = RUNS / parent.id
    output.mkdir(parents=True, exist_ok=True)
    (output / "allocation-comparison.json").write_text(json.dumps({
        "source_run_id": (parent.ensemble or {}).get("source_run_id"),
        "member_run_ids": [child.id for child in children],
    }, indent=2))


def main() -> None:
    ensure_dirs()
    init_db()
    tracking_stop = Event()
    Thread(target=tracking_loop, args=(tracking_stop,), daemon=True,
           name="fogos-tracking").start()
    # Reattach to scheduler jobs before accepting new work. SshSlurmRunner
    # polls the existing job ID and downloads its outputs when it completes.
    for run in recoverable_remote_runs():
        process(run)
    limits = {
        "local-docker": int(os.getenv("LOCAL_RUNNER_CONCURRENCY", "2")),
        "ssh-slurm": int(os.getenv("SLURM_RUNNER_CONCURRENCY", "4")),
        "mtt-process": int(os.getenv("MTT_PROCESS_CONCURRENCY", "2")),
        "cell2fire-subprocess": int(os.getenv("CELL2FIRE_SUBPROCESS_CONCURRENCY", "2")),
        "local-process": int(os.getenv("IN_PROCESS_CONCURRENCY", "2")),
        "orchestrator": 1,
    }
    for engine in ENGINES.values():
        key = engine.descriptor.concurrency_key
        setting = "FIRELINE_ENGINE_CONCURRENCY_" + key.upper().replace("-", "_")
        limits[key] = max(1, int(os.getenv(setting, str(limits.get(key, 1)))))
    futures: dict[Future, str] = {}
    exercise_future: Future | None = None
    process_keys = {engine.descriptor.concurrency_key for engine in ENGINES.values()
                    if engine.descriptor.execution_pool == "process"}
    thread_workers = sum(value for name, value in limits.items() if name not in process_keys)
    with ThreadPoolExecutor(max_workers=thread_workers, thread_name_prefix="fire-run") as thread_executor, \
            ProcessPoolExecutor(max_workers=sum(limits[key] for key in process_keys) or 1) as process_executor:
        while True:
            if exercise_future and exercise_future.done():
                exercise_future.result()
                exercise_future = None
            for future in list(futures):
                if future.done():
                    # process() records failures; result() still exposes dispatcher bugs.
                    future.result()
                    del futures[future]
            in_use = {name: sum(value == name for value in futures.values()) for name in limits}
            for run in queued_runs():
                if run.mode != "single" and run.parent_id is None:
                    runner_name = "orchestrator"
                else:
                    engine = ENGINES.get(run.scenario.engine)
                    runner_name = engine.descriptor.concurrency_key if engine else "local-process"
                if in_use.get(runner_name, 0) >= limits.get(runner_name, 1):
                    continue
                if claim_run(run.id):
                    executor = process_executor if runner_name in process_keys else thread_executor
                    futures[executor.submit(_dispatch, run)] = runner_name
                    in_use[runner_name] = in_use.get(runner_name, 0) + 1
            if exercise_future is None:
                experiment = next_queued_experiment()
                if experiment and claim_experiment(experiment["id"]):
                    exercise_future = thread_executor.submit(
                        evaluate_experiment_job, experiment["scenario_id"], experiment["id"])
            _reconcile_parents()
            time.sleep(.5)


if __name__ == "__main__":
    main()
