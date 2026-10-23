from __future__ import annotations

import csv
import hashlib
import math
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from rasterio.warp import transform

from ..models import Landscape, Scenario, SimulationResult
from ..services.allocation import intervention_cells
from ..settings import CONFIG, ROOT
from .contract import EngineDescriptor


class Cell2FireEngine:
    name = "cell2fire"
    descriptor = EngineDescriptor(
        "cell2fire", "Cell2Fire C2F-W", ("default",), "default", ("constant",),
        "local-process", "medium", ("Uses a demonstration Portuguese land-cover to fuel mapping",),
        supports_multiple_ignitions=True, supports_delayed_ignitions=True,
        execution_pool="thread", concurrency_key="cell2fire-subprocess",
    )

    def binary(self) -> Path:
        configured = os.getenv("CELL2FIRE_BIN")
        return Path(configured) if configured else ROOT / "vendor" / "C2F-W" / "Cell2Fire" / "Cell2Fire"

    def available(self) -> tuple[bool, str]:
        binary = self.binary()
        if not binary.is_file() or not os.access(binary, os.X_OK):
            return False, "Build vendor/C2F-W/Cell2Fire with make -f makefile.macos"
        patch = " + scheduled ignitions" if self._supports_scheduled_ignitions() else ""
        return True, f"C2F-W {CONFIG['cell2fire']['revision'][:8]}{patch}"

    def validate(self, scenario: Scenario) -> None:
        if scenario.weather_source.kind != "constant":
            raise ValueError("Cell2Fire currently accepts constant weather only")
        scheduled = len(scenario.ignitions) > 1 or any(item.start_min for item in scenario.ignitions)
        if scheduled and not self._supports_scheduled_ignitions():
            raise ValueError("This Cell2Fire binary does not include the scheduled-ignitions patch; rebuild the pinned vendor source")

    def simulate(self, landscape: Landscape, scenario: Scenario, output: Path,
                 intervention: dict | None = None) -> SimulationResult:
        started = time.perf_counter()
        available, reason = self.available()
        if not available:
            raise RuntimeError(reason)
        source = output / "cell2fire-input"
        native = output / "cell2fire-native"
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(native, ignore_errors=True)
        source.mkdir(parents=True, exist_ok=True)
        native.mkdir(parents=True, exist_ok=True)
        _write_ascii(source / "fuels.asc", landscape.fuel, landscape)
        _write_ascii(source / "elevation.asc", landscape.elevation, landscape, decimals=2)
        _write_ascii(source / "slope.asc", landscape.slope, landscape, decimals=2)
        _write_ascii(source / "saz.asc", landscape.aspect, landscape, decimals=2)
        lookup = ROOT / "vendor" / "C2F-W" / "data" / "ScottAndBurgan" / "Vilopriu_2013-asc" / "spain_lookup_table.csv"
        shutil.copy2(lookup, source / "spain_lookup_table.csv")
        ignitions = [(item, _ignition_cell(landscape, item.coordinates)) for item in scenario.ignitions]
        scheduled = len(ignitions) > 1 or any(item.start_min for item, _ in ignitions)
        if scheduled and not self._supports_scheduled_ignitions():
            raise ValueError("This Cell2Fire binary does not include the scheduled-ignitions patch; rebuild the pinned vendor source")
        if scheduled:
            with (source / "ScheduledIgnitions.csv").open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["Minute", "Ncell", "Id", "Name"])
                for item, cell in ignitions:
                    writer.writerow([item.start_min, cell, item.id, item.name])
        else:
            (source / "Ignitions.csv").write_text(f"Year,Ncell\n1,{ignitions[0][1]}\n")
        _write_weather(source / "Weather.csv", scenario)

        task_cells = []
        if intervention:
            if not self._supports_timed_firebreaks():
                raise ValueError("This Cell2Fire binary does not include the timed-firebreak patch; rebuild the pinned vendor source")
            prototype = SimulationResult(np.empty(landscape.fuel.shape), landscape.coverage,
                                         landscape.transform, landscape.crs, 1, self.name, "", {})
            _, task_cells = intervention_cells(prototype, intervention)
            with (source / "TimedFirebreakCells.csv").open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["ActivationMinute", "CellNumber", "TaskId"])
                for task in task_cells:
                    minute = math.ceil(float(task["activation_min"]))
                    task["cell_numbers"] = []
                    for row, col in task["cells"]:
                        cell = row * landscape.fuel.shape[1] + col + 1
                        task["cell_numbers"].append(cell)
                        writer.writerow([minute, cell, task["task_id"]])

        command = [str(self.binary()), "--input-instance-folder", str(source), "--output-folder", str(native),
                   "--sim", "S", "--nsims", "1", "--sim-years", "1", "--seed", str(scenario.seed),
                   "--scenario", str({"low": 1, "moderate": 3, "high": 4}[scenario.moisture]),
                   "--nthreads", "1", "--weather", "rows", "--nweathers", "1",
                   "--output-messages", "--grids", "--final-grid", "--Fire-Period-Length", "1",
                   "--max-fire-periods", str(scenario.duration_min), "--IgnitionRad", "0"]
        command.append("--scheduled-ignitions" if scheduled else "--ignitions")
        if intervention:
            command += ["--TimedFirebreakCells", str(source / "TimedFirebreakCells.csv")]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        (output / "cell2fire.log").write_text(completed.stdout + "\n" + completed.stderr)
        if completed.returncode:
            raise RuntimeError(f"Cell2Fire exited with code {completed.returncode}; see cell2fire.log")
        messages = native / "Messages" / "MessagesFile1.csv"
        arrival = _arrival_from_messages(messages, landscape.fuel.shape,
                                         [(cell, item.start_min) for item, cell in ignitions],
                                         native / "ignition_events.csv")
        version = f"{CONFIG['cell2fire']['revision']}+{CONFIG['cell2fire'].get('local_patch', 'unpatched')}"
        result = SimulationResult(
            arrival, landscape.coverage, landscape.transform, landscape.crs, 1,
            self.name, version,
            {"landscape": landscape.provenance, "command": command, "messages": str(messages),
             "ignitions": [item.model_dump(mode="json") for item in scenario.ignitions]},
        )
        result.manifest = {"schema_version": 1, "engine": self.name,
                           "engine_version": version, "profile": "default",
                           "native_patch": CONFIG["cell2fire"].get("local_patch"),
                           "runner": "local-process", "command": command,
                           "runtime_identity": f"sha256:{_sha256(self.binary())}",
                           "input_sha256": _tree_hash(source),
                           "native_spatial_resolution_m": landscape.cell_size_m,
                           "generated_files": sorted(str(path.relative_to(source)) for path in source.rglob("*") if path.is_file()),
                           "weather_source": scenario.weather_source.model_dump(), "output_interval_min": 1,
                           "runtime_seconds": round(time.perf_counter() - started, 3),
                           "warnings": list(self.descriptor.limitations),
                           "intervention": _firebreak_summary(native / "timed_firebreak_events.csv", task_cells)}
        return result

    def _supports_scheduled_ignitions(self) -> bool:
        try:
            return b"ScheduledIgnitions.csv" in self.binary().read_bytes()
        except OSError:
            return False

    def _supports_timed_firebreaks(self) -> bool:
        try:
            return b"TimedFirebreakCells.csv" in self.binary().read_bytes()
        except OSError:
            return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(value for value in path.rglob("*") if value.is_file()):
        digest.update(str(item.relative_to(path)).encode())
        digest.update(item.read_bytes())
    return digest.hexdigest()


def _write_ascii(path: Path, array: np.ndarray, landscape: Landscape, decimals: int = 0) -> None:
    rows, cols = array.shape
    south = landscape.transform.f + rows * landscape.transform.e
    header = (f"ncols {cols}\nnrows {rows}\nxllcorner {landscape.transform.c}\n"
              f"yllcorner {south}\ncellsize {landscape.cell_size_m}\nNODATA_value -9999\n")
    values = np.where(landscape.coverage, array, -9999)
    with path.open("w") as stream:
        stream.write(header)
        np.savetxt(stream, values, fmt=f"%.{decimals}f")


def _ignition_cell(landscape: Landscape, coordinates: tuple[float, float]) -> int:
    x, y = transform("EPSG:4326", landscape.crs, [coordinates[0]], [coordinates[1]])
    col, row = ~landscape.transform @ (x[0], y[0])
    row, col = int(row), int(col)
    rows, cols = landscape.fuel.shape
    if not (0 <= row < rows and 0 <= col < cols) or not landscape.coverage[row, col]:
        raise ValueError("Ignition is outside prepared landscape coverage")
    if int(landscape.fuel[row, col]) == 0 or 91 <= int(landscape.fuel[row, col]) <= 99:
        raise ValueError("Ignition must be inside a burnable cell")
    return row * cols + col + 1


def _write_weather(path: Path, scenario: Scenario) -> None:
    start = datetime(2026, 8, 1, 12)
    count = max(2, scenario.duration_min // 60 + 2)
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Instance", "datetime", "WS", "WD", "FireScenario"])
        for hour in range(count):
            writer.writerow(["PenhaDemo", (start + timedelta(hours=hour)).strftime("%m/%d/%y %H:%M"),
                             scenario.wind_speed_kmh, scenario.wind_direction_deg, 1])


def _arrival_from_messages(path: Path, shape: tuple[int, int],
                           ignitions: list[tuple[int, int]], events: Path | None = None) -> np.ndarray:
    arrival = np.full(shape, np.nan, dtype="float32")
    cols = shape[1]
    for cell, minute in ignitions:
        location = divmod(cell - 1, cols)
        current = arrival[location]
        arrival[location] = minute if np.isnan(current) else min(current, minute)
    if events and events.exists() and events.stat().st_size:
        with events.open(newline="") as stream:
            for row in csv.DictReader(stream):
                if row.get("status") != "ignited":
                    continue
                location = divmod(int(row["cell"]) - 1, cols)
                minute = float(row["minute"])
                current = arrival[location]
                arrival[location] = minute if np.isnan(current) else min(current, minute)
    if not path.exists() or not path.stat().st_size:
        return arrival
    rows = np.atleast_2d(np.loadtxt(path, delimiter=","))
    for _, target, minute, _ in rows:
        row, col = divmod(int(target) - 1, cols)
        current = arrival[row, col]
        arrival[row, col] = minute if np.isnan(current) else min(current, minute)
    return arrival


def _firebreak_summary(events: Path, task_cells: list[dict]) -> dict:
    statuses: dict[int, str] = {}
    if events.exists() and events.stat().st_size:
        with events.open(newline="") as stream:
            for row in csv.DictReader(stream):
                statuses[int(row["cell"])] = row["status"]
    tasks = []
    for task in task_cells:
        # The adapter adds explicit cell IDs before this summary when possible.
        cells = task.get("cell_numbers", [])
        task_statuses = [statuses.get(cell, "unused") for cell in cells]
        tasks.append({"task_id": task["task_id"], "task_name": task["task_name"],
                      "activation_min": math.ceil(float(task["activation_min"])),
                      "cell_count": len(task["cells"]),
                      "activated_cells": task_statuses.count("activated"),
                      "breached_cells": task_statuses.count("breached"),
                      "unused_cells": task_statuses.count("unused")})
    return {"kind": "timed_containment", "tasks": tasks,
            "scheduled_cells": sum(task["cell_count"] for task in tasks),
            "breached_cells": sum(task["breached_cells"] for task in tasks)}
