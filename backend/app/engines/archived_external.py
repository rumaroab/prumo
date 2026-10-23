from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize
from rasterio.warp import Resampling, reproject, transform
from pyproj import CRS
from shapely.geometry import Point, mapping

from ..models import Landscape, Scenario, SimulationResult
from ..runners import LocalContainerRunner, SshSlurmRunner
from ..weather import load_weather_series, validate_weather_coverage
from .contract import EngineDescriptor


class ExternalEngine:
    descriptor: EngineDescriptor
    image_env: str
    default_image: str
    version: str
    timeout = 1800
    cpus = 2
    memory = "4g"

    @property
    def name(self) -> str:
        return self.descriptor.id

    def image(self) -> str:
        return os.getenv(self.image_env, self.default_image)

    def runner_name(self) -> str:
        return self.descriptor.runner

    def available(self) -> tuple[bool, str]:
        runner = LocalContainerRunner()
        ready, reason = runner.available()
        if not ready:
            return False, reason
        if not runner.image_available(self.image()):
            return False, f"Build or pull container image {self.image()}"
        return True, f"{self.descriptor.display_name} container is available"

    def simulate(self, landscape: Landscape, scenario: Scenario, output: Path) -> SimulationResult:
        started = time.perf_counter()
        self.validate(scenario)
        source, native = output / f"{self.name}-input", output / f"{self.name}-native"
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(native, ignore_errors=True)
        source.mkdir(parents=True, exist_ok=True)
        native.mkdir(parents=True, exist_ok=True)
        input_manifest = self.prepare(landscape, scenario, source)
        command, mounts = self.command(source, native, scenario)
        runner = LocalContainerRunner()
        execution = runner.run(self.image(), output, command, timeout=self.timeout, cpus=self.cpus,
                               memory=self.memory, mounts=mounts)
        if execution.returncode:
            raise RuntimeError(f"{self.descriptor.display_name} exited with code {execution.returncode}; see runner.log")
        result = self.parse(landscape, scenario, native)
        result.manifest = {
            "schema_version": 1, "engine": self.name, "engine_version": self.version,
            "profile": self.profile(scenario), "runner": execution.runner,
            "command": execution.command, "image": self.image(), "runtime_identity": execution.runtime_identity,
            "weather_source": scenario.weather_source.model_dump(),
            "input_sha256": _tree_hash(source), "input": input_manifest,
            "generated_files": sorted(str(path.relative_to(source)) for path in source.rglob("*") if path.is_file()),
            "native_spatial_resolution_m": input_manifest.get("cell_size_m"),
            "output_interval_min": result.temporal_resolution_min,
            "runtime_seconds": round(time.perf_counter() - started, 3),
            "warnings": list(self.descriptor.limitations),
        }
        return result

    def profile(self, scenario: Scenario) -> str:
        return self.descriptor.default_profile if scenario.engine_profile == "default" else scenario.engine_profile

    def validate(self, scenario: Scenario) -> None:
        profile = self.profile(scenario)
        if profile not in self.descriptor.profiles:
            raise ValueError(f"Unsupported {self.name} profile: {profile}")
        if scenario.weather_source.kind not in self.descriptor.weather_modes:
            raise ValueError(f"{self.descriptor.display_name} profile does not support {scenario.weather_source.kind} weather")
        if scenario.weather_source.kind == "series":
            validate_weather_coverage(scenario.weather_source.id, scenario.duration_min)

    def prepare(self, landscape: Landscape, scenario: Scenario, source: Path) -> dict:
        raise NotImplementedError

    def command(self, source: Path, native: Path, scenario: Scenario) -> tuple[list[str], list[tuple[Path, str]]]:
        raise NotImplementedError

    def parse(self, landscape: Landscape, scenario: Scenario, native: Path) -> SimulationResult:
        raise NotImplementedError


class FarsiteEngine(ExternalEngine):
    descriptor = EngineDescriptor(
        "farsite", "FARSITE · surface demo", ("surface-standard",), "surface-standard",
        ("constant", "series"), "local-docker", "medium",
        ("Unmaintained Linux fork pinned for reproducibility", "Surface fire only; crown fire and spotting disabled",
         "Five-minute perimeter output; not projection-aware internally"),
    )
    image_env, default_image = "FARSITE_IMAGE", "forest-fire-farsite:4537d60"
    version = "4537d60ab013fa91d0b49d8efb385ffb1b3ddd13"

    def prepare(self, landscape: Landscape, scenario: Scenario, source: Path) -> dict:
        _write_ascii(source / "elevation.asc", landscape.elevation, landscape, 2)
        _write_ascii(source / "slope.asc", landscape.slope, landscape, 2)
        _write_ascii(source / "aspect.asc", landscape.aspect, landscape, 2)
        _write_ascii(source / "fuel.asc", landscape.fuel, landscape, 0)
        _write_lcp(source / "landscape.lcp", landscape)
        (source / "landscape.prj").write_text(CRS.from_user_input(landscape.crs).to_wkt())
        x, y = _ignition_xy(landscape, scenario)
        radius = max(landscape.cell_size_m / 2, 5)
        gpd.GeoDataFrame({"id": [1]}, geometry=[Point(x, y).buffer(radius)], crs=landscape.crs).to_file(
            source / "ignition.shp")
        rows = _weather_rows(scenario)
        _write_farsite_raws(source / "weather.raws", rows)
        _write_farsite_inputs(source / "farsite.input", rows, scenario)
        (source / "commands.txt").write_text(
            "/work/farsite-input/landscape.lcp /work/farsite-input/farsite.input "
            "/work/farsite-input/ignition.shp 0 /work/farsite-native/run 1\n")
        control = {"duration_min": scenario.duration_min, "perimeter_interval_min": 5,
                   "crs": landscape.crs, "surface_only": True, "spotting": False,
                   "ignition": "ignition.shp", "weather": "weather.raws"}
        (source / "run.json").write_text(json.dumps(control, indent=2))
        return {"format": "FARSITE surface input bundle", "cell_size_m": landscape.cell_size_m,
                "fuel_translation": "Scott-Burgan 40", "perimeter_interval_min": 5}

    def command(self, source: Path, native: Path, scenario: Scenario):
        return ["/opt/farsite/TestFARSITE", "/work/farsite-input/commands.txt"], []

    def parse(self, landscape: Landscape, scenario: Scenario, native: Path) -> SimulationResult:
        direct = native / "arrival.npy"
        if direct.exists():
            arrival = np.load(direct).astype("float32")
        else:
            arrival = np.full(landscape.fuel.shape, np.nan, dtype="float32")
            perimeters = sorted(native.glob("perimeter-*.geojson"), key=lambda path: _minute_from_name(path))
            perimeter_shape = next(iter(native.glob("*_Perimeters.shp")), None)
            if perimeter_shape:
                frame = gpd.read_file(perimeter_shape).set_crs(landscape.crs, allow_override=True)
                time_column = next((column for column in frame.columns if column.lower().startswith("elapsed")), None)
                if not time_column:
                    raise RuntimeError("FARSITE perimeter output has no elapsed-time field")
                for minute in sorted(frame[time_column].unique()):
                    selected = frame[frame[time_column] == minute]
                    burned = rasterize(((geometry, 1) for geometry in selected.geometry), out_shape=arrival.shape,
                                       transform=landscape.transform, fill=0, all_touched=True).astype(bool)
                    arrival[burned & ~np.isfinite(arrival)] = float(minute)
            elif not perimeters:
                raise RuntimeError("FARSITE produced no arrival.npy or perimeter GeoJSON outputs")
            else:
                for path in perimeters:
                    minute = _minute_from_name(path)
                    frame = gpd.read_file(path).to_crs(landscape.crs)
                    burned = rasterize(((geometry, 1) for geometry in frame.geometry), out_shape=arrival.shape,
                                       transform=landscape.transform, fill=0, all_touched=True).astype(bool)
                    arrival[burned & ~np.isfinite(arrival)] = minute
        _set_ignition_arrival(arrival, landscape, scenario)
        return _result(arrival, landscape, "FARSITE surface demo", self.version, 5,
                       {"surface_only": True, "native_output": str(native)}, scenario.duration_min)


class QuicFireEngine(ExternalEngine):
    descriptor = EngineDescriptor(
        "quicfire", "QUIC-Fire · licensed", ("coarse-demo",), "coarse-demo", ("constant", "series"),
        "local-docker", "high", ("Requires a separately licensed QUIC-Fire executable",
        "3D fuels are synthetic values derived from the demonstration land-cover crosswalk"),
    )
    image_env, default_image = "QUICFIRE_IMAGE", "forest-fire-quicfire:0.11"
    version = "quicfire-tools-0.11"
    timeout, cpus, memory = 7200, 4, "8g"

    def binary(self) -> Path | None:
        value = os.getenv("QUICFIRE_BIN")
        return Path(value) if value else None

    def available(self) -> tuple[bool, str]:
        binary = self.binary()
        if not binary or not binary.is_file():
            return False, "Set QUICFIRE_BIN to the licensed executable"
        return super().available()

    def prepare(self, landscape: Landscape, scenario: Scenario, source: Path) -> dict:
        np.save(source / "fuel_load_kg_m2.npy", landscape.fuel_load_kg_m2)
        np.save(source / "fuel_depth_m.npy", landscape.fuel_depth_m)
        np.save(source / "elevation_m.npy", landscape.elevation)
        np.save(source / "coverage.npy", landscape.coverage)
        _write_weather_json(source / "weather.json", scenario)
        x, y = _ignition_xy(landscape, scenario)
        rows = landscape.fuel.shape[0]
        west, north = landscape.transform.c, landscape.transform.f
        south = north - rows * landscape.cell_size_m
        spec = {"shape": list(landscape.fuel.shape), "cell_size_m": landscape.cell_size_m,
                "crs": landscape.crs, "transform": list(landscape.transform)[:6],
                "duration_min": scenario.duration_min, "ignition_xy": [x, y],
                "ignition_local_xy": [x - west, y - south], "moisture": scenario.moisture,
                "vertical_model": "uniform load through mapped fuel depth", "output_interval_s": 60}
        (source / "run.json").write_text(json.dumps(spec, indent=2))
        binary = self.binary()
        return {"format": "quicfire-tools input bundle", "cell_size_m": landscape.cell_size_m,
                "fuel_translation": "synthetic physical v1", "output_interval_min": 1,
                "licensed_executable_sha256": _file_hash(binary) if binary else None}

    def command(self, source: Path, native: Path, scenario: Scenario):
        binary = self.binary()
        assert binary is not None
        return (["/opt/forest-fire/run-quicfire", "/work/quicfire-input", "/work/quicfire-native",
                 "/licensed/quicfire"], [(binary, "/licensed/quicfire")])

    def parse(self, landscape: Landscape, scenario: Scenario, native: Path) -> SimulationResult:
        path = native / "arrival.npy"
        if not path.exists():
            path = native / "fire_times.npy"
        if not path.exists():
            raise RuntimeError("QUIC-Fire wrapper produced no arrival output")
        values = np.load(path)
        arrival = values.astype("float32") if values.ndim == 2 else _first_active(values)
        arrival = _resample_array(arrival, landscape.fuel.shape, landscape.transform, landscape.transform)
        _set_ignition_arrival(arrival, landscape, scenario)
        return _result(arrival, landscape, "QUIC-Fire", self.version, 1,
                       {"fuel_model": "synthetic 3D v1", "native_output": str(native)}, scenario.duration_min)


class WrfSfireEngine(ExternalEngine):
    descriptor = EngineDescriptor(
        "wrf_sfire", "WRF-SFIRE", ("coupled-idealized", "standalone-series"), "coupled-idealized",
        ("constant", "series"), "ssh-slurm", "very-high",
        ("Anderson fuel crosswalk is illustrative", "Coupled profile accepts constant initial conditions only",
         "Standalone series profile is one-way and has no fire-to-atmosphere feedback"),
        {"coupled-idealized": ("constant",), "standalone-series": ("series",)},
    )
    image_env, default_image = "WRF_SFIRE_IMAGE", "forest-fire-wrf-sfire:9801186"
    version = "9801186f3ef8a500ec106aecfdcb051c4d1e38db"
    timeout, cpus, memory = 21600, 8, "16g"

    def available(self) -> tuple[bool, str]:
        if os.getenv("WRF_SFIRE_RUNNER", "slurm") == "slurm":
            return SshSlurmRunner().available()
        ready, reason = super().available()
        if not ready:
            return ready, reason
        checked = __import__("subprocess").run(
            ["docker", "run", "--rm", "--network", "none", "--entrypoint", "/bin/sh", self.image(),
             "-c", "test -x /opt/wrf-sfire/bin/prepare-and-run"], capture_output=True)
        if checked.returncode:
            return False, "WRF-SFIRE image needs a validated /opt/wrf-sfire/bin/prepare-and-run runtime"
        return True, "Validated local WRF-SFIRE runtime is available"

    def runner_name(self) -> str:
        return "ssh-slurm" if os.getenv("WRF_SFIRE_RUNNER", "slurm") == "slurm" else "local-docker"

    def validate(self, scenario: Scenario) -> None:
        super().validate(scenario)
        profile = self.profile(scenario)
        if profile == "coupled-idealized" and scenario.weather_source.kind != "constant":
            raise ValueError("coupled-idealized requires constant initial weather")
        if profile == "standalone-series" and scenario.weather_source.kind != "series":
            raise ValueError("standalone-series requires an uploaded weather series")

    def prepare(self, landscape: Landscape, scenario: Scenario, source: Path) -> dict:
        np.save(source / "terrain_m.npy", landscape.elevation)
        np.save(source / "fuel_anderson13.npy", landscape.fuel_anderson13)
        _write_weather_json(source / "weather.json", scenario)
        rows = _weather_rows(scenario)
        if self.profile(scenario) == "standalone-series":
            _write_wrf_forcing(source / "forcing.nc", rows)
        else:
            speed = scenario.wind_speed_kmh / 3.6
            (source / "idealized_sounding.txt").write_text(
                "# height_m potential_temperature_k water_vapor_g_kg wind_speed_m_s wind_direction_deg\n"
                f"0 303 8 {speed:.3f} {scenario.wind_direction_deg:.2f}\n"
                f"1000 310 5 {speed:.3f} {scenario.wind_direction_deg:.2f}\n"
                f"3000 325 2 {speed:.3f} {scenario.wind_direction_deg:.2f}\n")
        x, y = _ignition_xy(landscape, scenario)
        spec = {"profile": self.profile(scenario), "shape": list(landscape.fuel.shape),
                "cell_size_m": landscape.cell_size_m, "crs": landscape.crs,
                "transform": list(landscape.transform)[:6], "duration_min": scenario.duration_min,
                "ignition_xy": [x, y], "fire_refinement": 10, "output_interval_s": 60}
        (source / "run.json").write_text(json.dumps(spec, indent=2))
        return {"format": "WRF-SFIRE prepared domain", "cell_size_m": landscape.cell_size_m / 10,
                "fuel_translation": "Anderson 13 illustrative v1", "profile": self.profile(scenario)}

    def command(self, source: Path, native: Path, scenario: Scenario):
        command = ["/opt/forest-fire/run-wrf-sfire", "/work/wrf_sfire-input", "/work/wrf_sfire-native"]
        return command, []

    def simulate(self, landscape: Landscape, scenario: Scenario, output: Path) -> SimulationResult:
        if os.getenv("WRF_SFIRE_RUNNER", "slurm") != "slurm":
            return super().simulate(landscape, scenario, output)
        started = time.perf_counter()
        self.validate(scenario)
        from ..storage import get_run, update_run
        try:
            persisted_job_id = get_run(output.name).external_job_id
        except KeyError:
            persisted_job_id = None
        source, native = output / "wrf_sfire-input", output / "wrf_sfire-native"
        if persisted_job_id is None:
            shutil.rmtree(source, ignore_errors=True)
            shutil.rmtree(native, ignore_errors=True)
        source.mkdir(parents=True, exist_ok=True); native.mkdir(parents=True, exist_ok=True)
        input_manifest = self.prepare(landscape, scenario, source)
        command = ["/opt/forest-fire/run-wrf-sfire", "wrf_sfire-input", "wrf_sfire-native"]
        # Persist the scheduler identity immediately so cancellation and restart
        # recovery do not depend on this Python process remaining alive.
        execution = SshSlurmRunner().run(
            output, command, timeout=self.timeout,
            on_submit=lambda job_id: update_run(output.name, status="submitted", stage="submitted",
                                                 external_job_id=job_id),
            on_state=lambda state: update_run(
                output.name,
                status="running" if state.upper() in {"RUNNING", "COMPLETING"} else "submitted",
                stage=f"slurm: {state.lower()}",
            ),
            existing_job_id=persisted_job_id,
        )
        if execution.returncode:
            raise RuntimeError(f"WRF-SFIRE Slurm job {execution.external_job_id} failed")
        result = self.parse(landscape, scenario, native)
        result.manifest = {"schema_version": 1, "engine": self.name, "engine_version": self.version,
                           "profile": self.profile(scenario), "runner": execution.runner,
                           "external_job_id": execution.external_job_id, "command": command,
                           "runtime_identity": execution.runtime_identity,
                           "weather_source": scenario.weather_source.model_dump(), "input": input_manifest,
                           "input_sha256": _tree_hash(source), "warnings": list(self.descriptor.limitations),
                           "generated_files": sorted(str(path.relative_to(source)) for path in source.rglob("*") if path.is_file()),
                           "native_spatial_resolution_m": input_manifest.get("cell_size_m"),
                           "runtime_seconds": round(time.perf_counter() - started, 3),
                           "output_interval_min": result.temporal_resolution_min}
        return result

    def parse(self, landscape: Landscape, scenario: Scenario, native: Path) -> SimulationResult:
        direct = native / "arrival.npy"
        resolution = 1.0
        if direct.exists():
            arrival = np.load(direct).astype("float32")
        else:
            archive = native / "fire_output.npz"
            if not archive.exists():
                raise RuntimeError("WRF-SFIRE wrapper produced no arrival.npy or fire_output.npz")
            values = np.load(archive)
            lfn = values["lfn"]
            times = values["times_min"]
            if len(times) > 1:
                resolution = float(np.median(np.diff(times)))
            arrival = np.full(lfn.shape[1:], np.nan, dtype="float32")
            for index, minute in enumerate(times):
                newly = (lfn[index] <= 0) & ~np.isfinite(arrival)
                arrival[newly] = float(minute)
            if "fxlat" in values and "fxlong" in values:
                arrival = _resample_wrf_grid(arrival, values["fxlat"], values["fxlong"], landscape)
        arrival = _resample_array(arrival, landscape.fuel.shape, landscape.transform, landscape.transform)
        _set_ignition_arrival(arrival, landscape, scenario)
        return _result(arrival, landscape, f"WRF-SFIRE · {self.profile(scenario)}", self.version, resolution,
                       {"coupling": "two-way" if self.profile(scenario) == "coupled-idealized" else "one-way",
                        "native_output": str(native)}, scenario.duration_min)


def _result(arrival, landscape, engine, version, resolution, provenance, horizon=None):
    arrival = np.asarray(arrival, dtype="float32")
    arrival[~np.isfinite(arrival)] = np.nan
    arrival[arrival < 0] = np.nan
    if horizon is not None:
        arrival[arrival > horizon] = np.nan
    arrival[~landscape.coverage] = np.nan
    return SimulationResult(arrival, landscape.coverage, landscape.transform, landscape.crs,
                            resolution, engine, version, provenance)


def _set_ignition_arrival(arrival: np.ndarray, landscape: Landscape, scenario: Scenario) -> None:
    x, y = _ignition_xy(landscape, scenario)
    col, row = ~landscape.transform @ (x, y)
    row, col = int(row), int(col)
    if not (0 <= row < arrival.shape[0] and 0 <= col < arrival.shape[1]):
        raise ValueError("Ignition is outside prepared landscape coverage")
    if not landscape.coverage[row, col]:
        raise ValueError("Ignition is outside prepared landscape coverage")
    arrival[row, col] = 0


def _write_ascii(path: Path, array: np.ndarray, landscape: Landscape, decimals: int) -> None:
    rows, cols = array.shape
    south = landscape.transform.f + rows * landscape.transform.e
    header = (f"ncols {cols}\nnrows {rows}\nxllcorner {landscape.transform.c}\n"
              f"yllcorner {south}\ncellsize {landscape.cell_size_m}\nNODATA_value -9999\n")
    with path.open("w") as stream:
        stream.write(header)
        np.savetxt(stream, np.where(landscape.coverage, array, -9999), fmt=f"%.{decimals}f")


def _write_weather_json(path: Path, scenario: Scenario) -> None:
    path.write_text(json.dumps(_weather_rows(scenario), indent=2))


def _write_wrf_forcing(path: Path, rows: list[dict]) -> None:
    """Write uniform, time-varying surface forcing for the one-way profile."""
    from scipy.io import netcdf_file

    with netcdf_file(path, "w") as dataset:
        dataset.createDimension("Time", len(rows))
        dataset.createDimension("DateStrLen", 19)
        dataset.createDimension("south_north", 1)
        dataset.createDimension("west_east", 1)
        times = dataset.createVariable("Times", "c", ("Time", "DateStrLen"))
        u10 = dataset.createVariable("U10", "f", ("Time", "south_north", "west_east"))
        v10 = dataset.createVariable("V10", "f", ("Time", "south_north", "west_east"))
        temp = dataset.createVariable("T2", "f", ("Time", "south_north", "west_east"))
        humidity = dataset.createVariable("RH2", "f", ("Time", "south_north", "west_east"))
        rain = dataset.createVariable("RAINNC", "f", ("Time", "south_north", "west_east"))
        for index, row in enumerate(rows):
            stamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).strftime("%Y-%m-%d_%H:%M:%S")
            times[index, :] = np.frombuffer(stamp.encode("ascii"), dtype="S1")
            radians = np.radians(float(row["wind_direction_deg"]))
            speed = float(row["wind_speed_kmh"]) / 3.6
            u10[index, 0, 0] = -speed * np.sin(radians)
            v10[index, 0, 0] = -speed * np.cos(radians)
            temp[index, 0, 0] = float(row["temperature_c"]) + 273.15
            humidity[index, 0, 0] = float(row["relative_humidity_pct"])
            rain[index, 0, 0] = float(row["precipitation_mm"])


def _weather_rows(scenario: Scenario) -> list[dict]:
    if scenario.weather_source.kind == "series":
        rows = load_weather_series(scenario.weather_source.id)
    else:
        start = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
        rows = [{"timestamp": (start + timedelta(minutes=minute)).isoformat().replace("+00:00", "Z"),
                 "wind_speed_kmh": scenario.wind_speed_kmh, "wind_direction_deg": scenario.wind_direction_deg,
                 "temperature_c": 30, "relative_humidity_pct": {"low": 20, "moderate": 40, "high": 70}[scenario.moisture],
                 "precipitation_mm": 0} for minute in range(0, scenario.duration_min + 60, 60)]
    return rows


def _write_farsite_raws(path: Path, rows: list[dict]) -> None:
    lines = ["RAWS_ELEVATION: 0", "RAWS_UNITS: Metric", f"RAWS: {len(rows)}"]
    for row in rows:
        stamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        lines.append(f"{stamp.year} {stamp.month} {stamp.day} {stamp:%H%M} {row['temperature_c']:.1f} "
                     f"{row['relative_humidity_pct']:.1f} {row['precipitation_mm']:.2f} "
                     f"{row['wind_speed_kmh']:.2f} {row['wind_direction_deg']:.1f} 0")
    path.write_text("\n".join(lines) + "\n")


def _write_farsite_inputs(path: Path, rows: list[dict], scenario: Scenario) -> None:
    start = datetime.fromisoformat(rows[0]["timestamp"].replace("Z", "+00:00"))
    end = start + timedelta(minutes=scenario.duration_min)
    moisture = {"low": (3, 4, 5, 45, 60), "moderate": (6, 7, 8, 75, 90),
                "high": (12, 14, 16, 100, 120)}[scenario.moisture]
    path.write_text(
        "FARSITE INPUTS FILE VERSION 1.0\n"
        f"FARSITE_START_TIME: {start.month:02d} {start.day:02d} {start:%H%M}\n"
        f"FARSITE_END_TIME: {end.month:02d} {end.day:02d} {end:%H%M}\n"
        "FARSITE_TIMESTEP: 5\nFARSITE_DISTANCE_RES: 30.0\nFARSITE_PERIMETER_RES: 30.0\n"
        "FARSITE_MIN_IGNITION_VERTEX_DISTANCE: 5.0\nFARSITE_SPOT_GRID_RESOLUTION: 30.0\n"
        "FARSITE_SPOT_PROBABILITY: 0\nFARSITE_SPOT_IGNITION_DELAY: 0\nFARSITE_MINIMUM_SPOT_DISTANCE: 30\n"
        "FARSITE_ACCELERATION_ON: 1\nFARSITE_FILL_BARRIERS: 1\nSPOTTING_SEED: 42\n\n"
        f"FUEL_MOISTURES_DATA: 1\n0 {' '.join(str(value) for value in moisture)}\n\n"
        "RAWS_FILE: /work/farsite-input/weather.raws\n\nFOLIAR_MOISTURE_CONTENT: 100\n"
        "CROWN_FIRE_METHOD: Finney\nNUMBER_PROCESSORS: 1\n")


def _write_lcp(path: Path, landscape: Landscape) -> None:
    rows, cols = landscape.fuel.shape
    west, north = landscape.transform.c, landscape.transform.f
    east = west + cols * landscape.cell_size_m
    south = north - rows * landscape.cell_size_m
    themes = [landscape.elevation, landscape.slope, landscape.aspect, landscape.fuel,
              np.zeros(landscape.fuel.shape, dtype="int16")]
    themes += [np.zeros(landscape.fuel.shape, dtype="int16") for _ in range(5)]
    with path.open("wb") as stream:
        def write(fmt: str, *values) -> None:
            stream.write(struct.pack("<" + fmt, *values))
        write("iii", 20, 20, 41)
        write("dddd", west, east, south, north)
        for theme in themes:
            valid = np.asarray(theme)[landscape.coverage]
            low, high = (int(np.nanmin(valid)), int(np.nanmax(valid))) if valid.size else (0, 0)
            unique = np.unique(valid.astype("int32"))
            categories = unique[:100].tolist()
            write("iii", low, high, len(categories) if len(unique) <= 100 else -1)
            write("100i", *(categories + [0] * (100 - len(categories))))
        write("ii", cols, rows)
        write("dddd", east, west, north, south)
        write("i", 0)
        write("dd", landscape.cell_size_m, landscape.cell_size_m)
        write("10h", 0, 1, 2, 0, 1, 1, 1, 1, 1, 1)
        for name in ("elevation", "slope", "aspect", "fuel", "cover", "height", "base", "density", "duff", "woody"):
            encoded = name.encode()[:255]
            stream.write(encoded + b"\0" * (256 - len(encoded)))
        description = b"Forest Fire platform surface-only demonstration landscape"
        stream.write(description + b"\0" * (512 - len(description)))
        elevation = np.clip(np.rint(landscape.elevation), -32768, 32767).astype("<i2")
        slope = np.clip(np.rint(landscape.slope), 0, 90).astype("<i2")
        aspect = np.clip(np.rint(landscape.aspect), 0, 360).astype("<i2")
        fuel = np.where(landscape.coverage, landscape.fuel, 99).astype("<i2")
        cover = np.zeros(landscape.fuel.shape, dtype="<i2")
        np.stack([elevation, slope, aspect, fuel, cover], axis=-1).tofile(stream)


def _ignition_xy(landscape: Landscape, scenario: Scenario) -> tuple[float, float]:
    x, y = transform("EPSG:4326", landscape.crs, [scenario.ignition[0]], [scenario.ignition[1]])
    return x[0], y[0]


def _minute_from_name(path: Path) -> float:
    return float(path.stem.rsplit("-", 1)[-1])


def _first_active(values: np.ndarray) -> np.ndarray:
    arrival = np.full(values.shape[-2:], np.nan, dtype="float32")
    for index, grid in enumerate(values):
        arrival[(grid > 0) & ~np.isfinite(arrival)] = index
    return arrival


def _resample_array(array, shape, source_transform, target_transform):
    if array.shape == shape:
        return array.astype("float32")
    target = np.full(shape, np.nan, dtype="float32")
    reproject(array.astype("float32"), target, src_transform=source_transform, src_crs="EPSG:3763",
              dst_transform=target_transform, dst_crs="EPSG:3763", resampling=Resampling.nearest,
              src_nodata=np.nan, dst_nodata=np.nan)
    return target


def _resample_wrf_grid(array: np.ndarray, latitude: np.ndarray, longitude: np.ndarray,
                       landscape: Landscape) -> np.ndarray:
    """Georeference a regular WRF fire grid from FXLAT/FXLONG before canonical resampling."""
    from rasterio.transform import from_bounds

    latitude = np.asarray(latitude).squeeze()
    longitude = np.asarray(longitude).squeeze()
    if latitude.shape != array.shape or longitude.shape != array.shape:
        raise RuntimeError("WRF-SFIRE FXLAT/FXLONG shape does not match LFN")
    # Rasterio rows run north to south; WRF grids commonly run south to north.
    if float(np.nanmean(latitude[0])) < float(np.nanmean(latitude[-1])):
        latitude, longitude, array = latitude[::-1], longitude[::-1], array[::-1]
    half_x = (float(np.nanmax(longitude)) - float(np.nanmin(longitude))) / max(1, array.shape[1] - 1) / 2
    half_y = (float(np.nanmax(latitude)) - float(np.nanmin(latitude))) / max(1, array.shape[0] - 1) / 2
    source_transform = from_bounds(float(np.nanmin(longitude)) - half_x, float(np.nanmin(latitude)) - half_y,
                                   float(np.nanmax(longitude)) + half_x, float(np.nanmax(latitude)) + half_y,
                                   array.shape[1], array.shape[0])
    target = np.full(landscape.fuel.shape, np.nan, dtype="float32")
    reproject(array.astype("float32"), target, src_transform=source_transform, src_crs="EPSG:4326",
              dst_transform=landscape.transform, dst_crs=landscape.crs, resampling=Resampling.nearest,
              src_nodata=np.nan, dst_nodata=np.nan)
    return target


def _tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(value for value in path.rglob("*") if value.is_file()):
        digest.update(str(item.relative_to(path)).encode())
        digest.update(item.read_bytes())
    return digest.hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
