from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
from rasterio.transform import Affine

from .models import Landscape, SimulationResult
from .settings import PREPARED


def atomic_json(path: Path, value) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2))
    os.replace(temp, path)


def load_landscape(prepared: Path | None = None) -> Landscape:
    prepared = prepared or PREPARED
    arrays = np.load(prepared / "landscape.npz")
    meta = json.loads((prepared / "landscape.json").read_text())
    fuel = arrays["fuel"]
    anderson, load, depth = _fuel_translations(fuel)
    return Landscape(
        fuel=fuel, elevation=arrays["elevation"], slope=arrays["slope"],
        aspect=arrays["aspect"], coverage=arrays["coverage"].astype(bool),
        transform=Affine(*meta["transform"]), crs=meta["crs"],
        cell_size_m=meta["cell_size_m"], provenance=meta["provenance"],
        fuel_anderson13=arrays["fuel_anderson13"] if "fuel_anderson13" in arrays else anderson,
        fuel_load_kg_m2=arrays["fuel_load_kg_m2"] if "fuel_load_kg_m2" in arrays else load,
        fuel_depth_m=arrays["fuel_depth_m"] if "fuel_depth_m" in arrays else depth,
    )


def save_result(result: SimulationResult, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    temp = output / "result.tmp.npz"
    values = {"arrival": result.arrival_minutes, "coverage": result.coverage}
    if result.member_arrivals:
        values["members"] = np.stack(result.member_arrivals)
    np.savez_compressed(temp, **values)
    os.replace(temp, output / "result.npz")
    atomic_json(output / "result.json", {
        "transform": list(result.transform)[:6], "crs": result.crs,
        "temporal_resolution_min": result.temporal_resolution_min,
        "engine": result.engine, "engine_version": result.engine_version,
        "provenance": result.provenance, "manifest": result.manifest or {},
    })


def load_result(output: Path) -> SimulationResult:
    arrays = np.load(output / "result.npz")
    meta = json.loads((output / "result.json").read_text())
    return SimulationResult(
        arrival_minutes=arrays["arrival"], coverage=arrays["coverage"].astype(bool),
        transform=Affine(*meta["transform"]), crs=meta["crs"],
        temporal_resolution_min=meta["temporal_resolution_min"], engine=meta["engine"],
        engine_version=meta["engine_version"], provenance=meta["provenance"],
        manifest=meta.get("manifest", {}),
        member_arrivals=[member for member in arrays["members"]] if "members" in arrays else None,
    )


def _fuel_translations(fuel: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Demonstration-only SB40 translations used by engines needing physical/Anderson fuels."""
    anderson = np.zeros(fuel.shape, dtype="int16")
    load = np.zeros(fuel.shape, dtype="float32")
    depth = np.zeros(fuel.shape, dtype="float32")
    groups = [
        ((101, 109), 1, .20, .30), ((121, 124), 2, .45, .35),
        ((141, 149), 4, .75, .90), ((161, 165), 8, .90, .25),
        ((181, 189), 9, 1.10, .20), ((201, 204), 12, 1.40, .45),
    ]
    for (low, high), category, mass, bed_depth in groups:
        selected = (fuel >= low) & (fuel <= high)
        anderson[selected], load[selected], depth[selected] = category, mass, bed_depth
    return anderson, load, depth
