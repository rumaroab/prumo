from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import numpy as np
from pyproj import Transformer
from rasterio.features import shapes
from shapely import make_valid
from shapely.geometry import GeometryCollection, shape
from shapely.ops import transform, unary_union

from .. import fogos, storage
from ..io import load_result
from ..settings import RUNS

METRIC_VERSION = "observed-agreement-v1"


def _union_features(collection: dict) -> object:
    geometries = []
    for feature in collection.get("features", []):
        geometry = feature.get("geometry")
        if geometry:
            value = shape(geometry)
            if not value.is_empty:
                geometries.append(make_valid(value))
    return unary_union(geometries) if geometries else GeometryCollection()


def evaluate(run_id: str, snapshot_id: str, assumed_observed_at: datetime | None = None,
             assumed_run_start_time: datetime | None = None) -> dict:
    run = storage.get_run(run_id)
    if run.status != "ready" or run.mode != "single":
        raise ValueError("Select a completed deterministic result or a completed comparison child")
    item = fogos.snapshot(snapshot_id)
    if item["product_type"] != "perimeter":
        raise ValueError("Numerical observation comparison requires an MTG perimeter snapshot")
    linked = (run.run_context or {}).get("external_incident") or {}
    if not linked and run.scenario_id:
        linked = storage.get_scenario(run.scenario_id).external_incident or {}
    if linked.get("incident_id") != item["incident_id"]:
        raise ValueError("The observation snapshot belongs to a different incident")
    collection = item["normalized"].get("geojson") or item["raw_payload"]
    observed_wgs84 = _union_features(collection)
    if observed_wgs84.is_empty:
        raise ValueError("This snapshot has no usable observed polygon")

    observed_text = item.get("observed_at")
    if observed_text:
        observed_at = datetime.fromisoformat(observed_text.replace("Z", "+00:00"))
        time_basis = "source observation timestamp"
        assumption = None
    elif assumed_observed_at:
        observed_at = assumed_observed_at
        time_basis = "user supplied observation timestamp"
        assumption = f"Observation timestamp assumed as {observed_at.isoformat()}"
    else:
        raise ValueError("The source has no observation timestamp; supply an explicit assumption")

    run_start_text = (run.run_context or {}).get("scenario_start_time")
    if run_start_text:
        run_start = datetime.fromisoformat(run_start_text.replace("Z", "+00:00"))
    elif assumed_run_start_time:
        run_start = assumed_run_start_time
        assumption = ((assumption + "; ") if assumption else "") + f"Run start assumed as {run_start.isoformat()}"
    else:
        raise ValueError("This result predates immutable run times; supply an explicit run start assumption")
    if observed_at.tzinfo is None or run_start.tzinfo is None:
        raise ValueError("Comparison timestamps must include a timezone")
    observed_at = observed_at.astimezone(UTC)
    run_start = run_start.astimezone(UTC)
    minute = (observed_at - run_start).total_seconds() / 60
    if minute < 0 or minute > run.scenario.duration_min:
        raise ValueError("The observation falls outside this simulation's time horizon")

    result = load_result(RUNS / run.id)
    reached = np.isfinite(result.arrival_minutes) & (result.arrival_minutes <= minute) & result.coverage
    simulated_parts = [shape(geometry) for geometry, value in shapes(
        reached.astype("uint8"), mask=reached, transform=result.transform) if value]
    simulated = unary_union(simulated_parts) if simulated_parts else GeometryCollection()
    coverage_parts = [shape(geometry) for geometry, value in shapes(
        result.coverage.astype("uint8"), mask=result.coverage, transform=result.transform) if value]
    coverage = unary_union(coverage_parts)
    projector = Transformer.from_crs(4326, result.crs, always_xy=True)
    observed = transform(projector.transform, observed_wgs84)
    if observed.is_empty or observed.area <= 0:
        raise ValueError("The observed polygon could not be projected")

    observed_inside = observed.intersection(coverage)
    outside_fraction = max(0.0, min(1.0, 1 - observed_inside.area / observed.area))
    if observed_inside.is_empty:
        raise ValueError("The observation is outside the model coverage")
    intersection = simulated.intersection(observed_inside).area if not simulated.is_empty else 0.0
    union = simulated.union(observed_inside).area if not simulated.is_empty else observed_inside.area
    metrics = {
        "aligned_minute": minute,
        "intersection_over_union": intersection / union if union else None,
        "simulated_area_ha": simulated.area / 10_000,
        "observed_area_ha": observed_inside.area / 10_000,
        "observed_total_area_ha": observed.area / 10_000,
        "area_difference_ha": (simulated.area - observed_inside.area) / 10_000,
        "hausdorff_distance_m": None if outside_fraction > 1e-6 or simulated.is_empty else simulated.boundary.hausdorff_distance(observed_inside.boundary),
        "observation_outside_coverage_fraction": outside_fraction,
        "partial": outside_fraction > 1e-6,
        "crs": result.crs,
        "source_resolution": "approximately 2–4 km MTG pixels",
    }
    evaluation_id = uuid4().hex[:16]
    stamp = datetime.now(UTC).isoformat()
    with storage.connect() as db:
        db.execute("""INSERT INTO observation_evaluations
            (id,run_id,snapshot_ids,observed_at,time_basis,assumption,metrics,metric_version,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (evaluation_id, run.id, json.dumps([snapshot_id]), observed_at.isoformat(), time_basis,
             assumption, json.dumps(metrics), METRIC_VERSION, stamp))
    return {"id": evaluation_id, "run_id": run.id, "snapshot_ids": [snapshot_id],
            "observed_at": observed_at.isoformat(), "time_basis": time_basis,
            "assumption": assumption, "metrics": metrics, "metric_version": METRIC_VERSION,
            "created_at": stamp, "observation": collection}


def list_evaluations(run_id: str) -> list[dict]:
    storage.get_run(run_id)
    with storage.connect() as db:
        rows = db.execute("SELECT * FROM observation_evaluations WHERE run_id=? ORDER BY created_at DESC",
                          (run_id,)).fetchall()
    values = []
    for row in rows:
        value = dict(row)
        value["snapshot_ids"] = json.loads(value["snapshot_ids"])
        value["metrics"] = json.loads(value["metrics"])
        values.append(value)
    return values
