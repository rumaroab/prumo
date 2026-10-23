from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np

from ..io import load_result


def comparison_payload(parent, children, minute: int, runs_dir: Path) -> dict:
    successful = [child for child in children if child.status == "ready"]
    values = []
    masks: dict[str, np.ndarray] = {}
    for child in successful:
        result = load_result(runs_dir / child.id)
        mask = np.isfinite(result.arrival_minutes) & (result.arrival_minutes <= minute)
        masks[child.scenario.engine] = mask
        burned = int(mask.sum())
        roads_path = runs_dir / child.id / f"roads-{int(child.scenario.exposure_buffer_m)}m.geojson"
        roads = json.loads(roads_path.read_text()) if roads_path.exists() else {"features": []}
        affected = sum(
            feature["properties"].get("first_exposure_min") is not None and
            feature["properties"]["first_exposure_min"] <= minute
            for feature in roads["features"]
        )
        values.append({"run_id": child.id, "engine": child.scenario.engine, "engine_label": result.engine,
                       "burned_cells": burned,
                       "burned_area_ha": burned * abs(result.transform.a * result.transform.e) / 10_000,
                       "exposed_roads": affected, "temporal_resolution_min": result.temporal_resolution_min,
                       "runtime_seconds": max(0, (datetime.fromisoformat(child.updated_at) -
                                                  datetime.fromisoformat(child.created_at)).total_seconds()),
                       "status": child.status})
    failed = [{"run_id": child.id, "engine": child.scenario.engine, "status": child.status,
               "error": child.error} for child in children if child.status != "ready"]
    agreements = []
    names = list(masks)
    for left_index, left in enumerate(names):
        for right in names[left_index + 1:]:
            union = (masks[left] | masks[right]).sum()
            score = float((masks[left] & masks[right]).sum() / union) if union else 1.0
            agreements.append({"left": left, "right": right, "jaccard": score})
    return {"minute": minute, "members": values, "failed": failed, "agreements": agreements}
