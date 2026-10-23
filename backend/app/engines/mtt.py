from __future__ import annotations

import heapq
import hashlib
import importlib.metadata
import json
import math
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
from pyretechnics import conversion as conv
from pyretechnics import fuel_models as fm
from pyretechnics import surface_fire as sf
from pyretechnics import vector_utils as vu
from rasterio.warp import transform

from ..models import Landscape, Scenario, SimulationResult
from ..services.allocation import intervention_cells
from .contract import EngineDescriptor


class MTTEngine:
    name = "mtt"
    version = "experimental-0.3+pyretechnics+timed-containment"
    descriptor = EngineDescriptor(
        "mtt", "Python MTT · experimental", ("default",), "default", ("constant",),
        "local-process", "low", ("Experimental implementation; no FlamMap equivalence claim",),
        supports_multiple_ignitions=True, supports_delayed_ignitions=True,
        execution_pool="process", concurrency_key="mtt-process",
    )

    def available(self) -> tuple[bool, str]:
        return True, "Experimental Python MTT is available"

    def validate(self, scenario: Scenario) -> None:
        return None

    def simulate(self, landscape: Landscape, scenario: Scenario, output: Path,
                 intervention: dict | None = None) -> SimulationResult:
        started = time.perf_counter()
        rows, cols = landscape.fuel.shape
        arrival = np.full((rows, cols), np.inf, dtype=np.float32)
        barrier = np.full((rows, cols), np.inf, dtype=np.float32)
        task_cells = []
        if intervention:
            prototype = SimulationResult(arrival, landscape.coverage, landscape.transform, landscape.crs,
                                         1, self.name, self.version, {})
            barrier, task_cells = intervention_cells(prototype, intervention)
        queue = []
        for ignition in scenario.ignitions:
            x, y = transform("EPSG:4326", landscape.crs, [ignition.coordinates[0]], [ignition.coordinates[1]])
            col, row = ~landscape.transform @ (x[0], y[0])
            start = int(row), int(col)
            if not (0 <= start[0] < rows and 0 <= start[1] < cols):
                raise ValueError(f"{ignition.name} is outside the prepared landscape")
            if not landscape.coverage[start] or _non_burnable(int(landscape.fuel[start])):
                raise ValueError(f"{ignition.name} must be inside a covered burnable cell")
            if ignition.start_min < arrival[start]:
                arrival[start] = ignition.start_min
                heapq.heappush(queue, (float(ignition.start_min), *start))
        links = _links(4)

        while queue:
            minute, row, col = heapq.heappop(queue)
            if minute > float(arrival[row, col]) + 1e-4 or minute > scenario.duration_min:
                continue
            for dr, dc, distance, bearing in links:
                nr, nc = row + dr, col + dc
                if not (0 <= nr < rows and 0 <= nc < cols) or not landscape.coverage[nr, nc]:
                    continue
                if _non_burnable(int(landscape.fuel[nr, nc])):
                    continue
                travel = _travel_minutes(landscape, row, col, dr, dc, distance, bearing, scenario,
                                         minute, barrier, arrival)
                if not np.isfinite(travel):
                    continue
                next_minute = minute + travel
                if next_minute < arrival[nr, nc] and next_minute <= scenario.duration_min:
                    arrival[nr, nc] = next_minute
                    heapq.heappush(queue, (next_minute, nr, nc))

        intervention_summary = _intervention_summary(arrival, barrier, task_cells)
        arrival[~np.isfinite(arrival)] = np.nan
        result = SimulationResult(
            arrival, landscape.coverage, landscape.transform, landscape.crs, 1,
            self.name, self.version,
            {"landscape": landscape.provenance, "links": "integrated straight lattice links within 4 cells",
             "spread_rates": "Pyretechnics surface-fire equations; 0.4 midflame wind adjustment assumption",
             "ignitions": [item.model_dump(mode="json") for item in scenario.ignitions],
             "warning": "Experimental implementation; no FlamMap equivalence claim"},
        )
        result.manifest = {"schema_version": 1, "engine": self.name, "engine_version": self.version,
                           "profile": "default", "runner": "local-process", "command": [],
                           "runtime_identity": f"pyretechnics:{importlib.metadata.version('pyretechnics')}",
                           "input_sha256": _input_hash(landscape, scenario, intervention),
                           "native_spatial_resolution_m": landscape.cell_size_m,
                           "generated_files": [],
                           "weather_source": scenario.weather_source.model_dump(), "output_interval_min": 1,
                           "runtime_seconds": round(time.perf_counter() - started, 3),
                           "warnings": list(self.descriptor.limitations),
                           "intervention": intervention_summary}
        return result


def _input_hash(landscape: Landscape, scenario: Scenario,
                intervention: dict | None = None) -> str:
    digest = hashlib.sha256(scenario.model_dump_json().encode())
    digest.update(json.dumps(intervention, sort_keys=True, separators=(",", ":")).encode())
    for array in (landscape.fuel, landscape.elevation, landscape.slope, landscape.aspect, landscape.coverage):
        digest.update(np.ascontiguousarray(array).tobytes())
    digest.update(landscape.crs.encode())
    digest.update(repr(tuple(landscape.transform)).encode())
    return digest.hexdigest()


def _links(radius: int) -> list[tuple[int, int, float, float]]:
    links = []
    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            if not (dr or dc) or math.gcd(abs(dr), abs(dc)) != 1:
                continue
            distance = math.hypot(dr, dc)
            bearing = math.degrees(math.atan2(dc, -dr)) % 360
            links.append((dr, dc, distance, bearing))
    return links


def _spread_m_min(landscape: Landscape, row: int, col: int, bearing: float, scenario: Scenario) -> float:
    fuel = int(landscape.fuel[row, col])
    slope = round(float(landscape.slope[row, col]) / 5) * 5
    aspect = round(float(landscape.aspect[row, col]) / 15) * 15 % 360
    return _pyretechnics_speed(fuel, scenario.moisture, round(scenario.wind_speed_kmh, 1),
                              round(scenario.wind_direction_deg, 1), slope, aspect, round(bearing, 1))


def _travel_minutes(landscape: Landscape, row: int, col: int, dr: int, dc: int,
                    distance: float, bearing: float, scenario: Scenario, start_minute: float = 0,
                    barrier: np.ndarray | None = None, arrival: np.ndarray | None = None) -> float:
    steps = max(abs(dr), abs(dc)) * 2
    segment = distance * landscape.cell_size_m / steps
    total = 0.0
    for step in range(1, steps + 1):
        sample_row = round(row + dr * step / steps)
        sample_col = round(col + dc * step / steps)
        if not landscape.coverage[sample_row, sample_col] or _non_burnable(int(landscape.fuel[sample_row, sample_col])):
            return float("inf")
        total += segment / _spread_m_min(landscape, sample_row, sample_col, bearing, scenario)
        if barrier is not None and np.isfinite(barrier[sample_row, sample_col]):
            activation = float(barrier[sample_row, sample_col])
            previously_breached = arrival is not None and float(arrival[sample_row, sample_col]) < activation
            if not previously_breached and start_minute + total >= activation:
                return float("inf")
    return total


def _intervention_summary(arrival: np.ndarray, barrier: np.ndarray,
                          task_cells: list[dict]) -> dict:
    tasks = []
    for task in task_cells:
        activation = float(task["activation_min"])
        cells = [tuple(value) for value in task["cells"]]
        breached = sum(np.isfinite(arrival[cell]) and float(arrival[cell]) < activation for cell in cells)
        tasks.append({"task_id": task["task_id"], "task_name": task["task_name"],
                      "activation_min": activation, "cell_count": len(cells),
                      "breached_cells": int(breached), "activated_cells": len(cells) - int(breached)})
    return {"kind": "timed_containment", "tasks": tasks,
            "scheduled_cells": int(np.count_nonzero(np.isfinite(barrier))),
            "breached_cells": sum(task["breached_cells"] for task in tasks)}


def _non_burnable(fuel: int) -> bool:
    return fuel == 0 or 91 <= fuel <= 99


@lru_cache(maxsize=100_000)
def _pyretechnics_speed(fuel: int, moisture: str, wind_kmh: float, wind_direction: float,
                        slope_deg: float, aspect: float, bearing: float) -> float:
    moisture_values = {
        "low": (0.03, 0.04, 0.05, 0.0, 0.45, 0.60),
        "moderate": (0.06, 0.07, 0.08, 0.0, 0.75, 0.90),
        "high": (0.12, 0.14, 0.16, 0.0, 1.00, 1.20),
    }[moisture]
    model = fm.moisturize(fm.get_fuel_model(fuel), moisture_values)
    minimum = sf.calc_surface_fire_behavior_no_wind_no_slope(model)
    slope = math.tan(math.radians(min(slope_deg, 80)))
    midflame_wind = wind_kmh * 1000 / 60 * 0.4
    maximum = sf.calc_surface_fire_behavior_max(minimum, midflame_wind, wind_direction, slope, aspect)
    xy = conv.azimuthal_to_cartesian(1.0, bearing)
    slope_xy = conv.azimuthal_to_cartesian(slope, conv.opposite_direction(aspect))
    direction = vu.as_unit_vector_3d(vu.to_slope_plane(xy, slope_xy))
    behavior = sf.calc_surface_fire_behavior_in_direction(maximum, direction)
    return max(0.01, float(behavior["spread_rate"]))
