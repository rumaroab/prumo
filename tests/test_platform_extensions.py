from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from fastapi import HTTPException
from rasterio.transform import from_origin
from pyproj import Transformer

from backend.app.engines.archived_external import FarsiteEngine, WrfSfireEngine, _write_lcp, _write_wrf_forcing
from backend.app.engines import ENGINES, compatible_profile
from backend.app.models import Landscape, RunCreate, Scenario, SimulationResult
from backend.app.services.fire_layer import footprint
from backend.app import weather
from backend.app import storage, worker
from backend.app import main as api_main
from backend.app.io import load_result, save_result
from backend.app.runners import LocalContainerRunner, SshSlurmRunner
from backend.app.services.comparison import comparison_payload


class PlatformExtensionTests(unittest.TestCase):
    def landscape(self) -> Landscape:
        fuel = np.array([[101, 142], [165, 99]], dtype="int16")
        return Landscape(fuel, np.full((2, 2), 100, dtype="float32"),
                         np.zeros((2, 2), dtype="float32"), np.zeros((2, 2), dtype="float32"),
                         np.ones((2, 2), dtype=bool), from_origin(0, 60, 30, 30), "EPSG:3763", 30,
                         {"kind": "test"}, np.ones((2, 2), dtype="int16"),
                         np.full((2, 2), .5, dtype="float32"), np.full((2, 2), .3, dtype="float32"))

    def test_legacy_scenario_defaults_to_constant_weather(self):
        scenario = Scenario.model_validate({"ignition": [-8.2, 41.4]})
        self.assertEqual(scenario.weather_source.kind, "constant")
        self.assertEqual(scenario.engine_profile, "default")

    def test_weather_upload_validates_and_normalizes(self):
        payload = ("timestamp,wind_speed_kmh,wind_direction_deg,temperature_c,relative_humidity_pct,precipitation_mm\n"
                   "2026-08-01T12:00:00Z,20,270,30,35,0\n"
                   "2026-08-01T14:00:00Z,25,280,31,30,0\n").encode()
        with tempfile.TemporaryDirectory() as folder, patch.object(weather, "WEATHER", Path(folder)):
            metadata = weather.save_weather_series(payload, "valid.csv")
            self.assertEqual(metadata["rows"], 2)
            self.assertEqual(weather.load_weather_series(metadata["id"])[1]["wind_speed_kmh"], 25)
            weather.validate_weather_coverage(metadata["id"], 120)

    def test_weather_upload_rejects_non_increasing_timestamps(self):
        payload = ("timestamp,wind_speed_kmh,wind_direction_deg,temperature_c,relative_humidity_pct,precipitation_mm\n"
                   "2026-08-01T12:00:00Z,20,270,30,35,0\n"
                   "2026-08-01T12:00:00Z,25,280,31,30,0\n").encode()
        with tempfile.TemporaryDirectory() as folder, patch.object(weather, "WEATHER", Path(folder)):
            with self.assertRaisesRegex(ValueError, "increase strictly"):
                weather.save_weather_series(payload)

    def test_surface_lcp_has_expected_header_and_cell_count(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "landscape.lcp"
            _write_lcp(path, self.landscape())
            self.assertEqual(path.stat().st_size, 7316 + 2 * 2 * 5 * 2)
            with path.open("rb") as stream:
                self.assertEqual(struct.unpack("<iii", stream.read(12)), (20, 20, 41))

    def test_farsite_parser_accepts_wrapper_arrival_grid(self):
        landscape = self.landscape()
        with tempfile.TemporaryDirectory() as folder:
            native = Path(folder)
            np.save(native / "arrival.npy", np.array([[0, 5], [10, np.nan]], dtype="float32"))
            with patch("backend.app.engines.archived_external._ignition_xy", return_value=(15, 45)):
                result = FarsiteEngine().parse(landscape, Scenario(ignition=[0, 0]), native)
            self.assertEqual(result.temporal_resolution_min, 5)
            self.assertEqual(float(result.arrival_minutes[1, 0]), 10)

    def test_wrf_parser_derives_first_nonpositive_lfn_time(self):
        landscape = self.landscape()
        with tempfile.TemporaryDirectory() as folder:
            native = Path(folder)
            lfn = np.ones((3, 2, 2), dtype="float32")
            lfn[1, 0, 1] = -1
            lfn[2, 1, 0] = 0
            np.savez(native / "fire_output.npz", lfn=lfn, times_min=np.array([0, 5, 10]))
            scenario = Scenario(engine="wrf_sfire", engine_profile="coupled-idealized", ignition=[0, 0])
            with patch("backend.app.engines.archived_external._ignition_xy", return_value=(15, 45)):
                result = WrfSfireEngine().parse(landscape, scenario, native)
            self.assertEqual(result.temporal_resolution_min, 5)
            self.assertEqual(float(result.arrival_minutes[0, 1]), 5)
            self.assertEqual(float(result.arrival_minutes[1, 0]), 10)

    def test_wrf_series_forcing_contains_vector_wind(self):
        rows = [{"timestamp": "2026-08-01T12:00:00Z", "wind_speed_kmh": 36,
                 "wind_direction_deg": 270, "temperature_c": 30,
                 "relative_humidity_pct": 35, "precipitation_mm": 0},
                {"timestamp": "2026-08-01T13:00:00Z", "wind_speed_kmh": 18,
                 "wind_direction_deg": 180, "temperature_c": 29,
                 "relative_humidity_pct": 40, "precipitation_mm": 1}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "forcing.nc"
            _write_wrf_forcing(path, rows)
            from scipy.io import netcdf_file
            with netcdf_file(path, "r", mmap=False) as dataset:
                self.assertAlmostEqual(float(dataset.variables["U10"].data[0, 0, 0]), 10, places=4)
                self.assertAlmostEqual(float(dataset.variables["V10"].data[1, 0, 0]), 5, places=4)

    def test_ensemble_fire_layer_contains_probability_bands(self):
        landscape = self.landscape()
        members = [np.array([[0, 5], [np.nan, np.nan]], dtype="float32"),
                   np.array([[0, 15], [5, np.nan]], dtype="float32")]
        result = SimulationResult(members[0], landscape.coverage, landscape.transform, landscape.crs,
                                  1, "ensemble", "1", {}, member_arrivals=members)
        layer = footprint(result, 10)
        self.assertTrue(layer["ensemble"])
        probabilities = {feature["properties"]["probability"] for feature in layer["features"]}
        self.assertIn(.5, probabilities)

    def test_quick_parameter_ensemble_creates_three_child_results(self):
        ignition = (-8.2782, 41.4298)
        x, y = Transformer.from_crs(4326, 3763, always_xy=True).transform(*ignition)
        landscape = Landscape(np.full((5, 5), 142, dtype="int16"), np.full((5, 5), 100, dtype="float32"),
                              np.zeros((5, 5), dtype="float32"), np.zeros((5, 5), dtype="float32"),
                              np.ones((5, 5), dtype=bool), from_origin(x - 75, y + 75, 30, 30),
                              "EPSG:3763", 30, {"kind": "test"})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(storage, "DB", root / "test.sqlite3"), patch.object(worker, "RUNS", root / "runs"), \
                 patch.object(worker, "load_landscape", return_value=landscape), patch.object(worker, "analyse", return_value={}):
                storage.init_db()
                parent = storage.create_run(Scenario(engine="mtt", ignition=ignition, duration_min=10),
                                            mode="parameter_ensemble", ensemble={"kind": "parameter", "preset": "quick"})
                worker.process(parent)
                while child := storage.next_queued():
                    worker.process(child)
                worker._reconcile_parents()
                complete = storage.get_run(parent.id)
                self.assertEqual(complete.status, "ready")
                children = storage.child_runs(parent.id)
                self.assertEqual(len(children), 3)
                self.assertEqual(len(load_result(root / "runs" / parent.id).member_arrivals or []), 3)
                manifest = load_result(root / "runs" / children[0].id).manifest or {}
                self.assertGreaterEqual(manifest["runtime_seconds"], 0)
                self.assertEqual(manifest["weather_source"], {"kind": "constant"})

    def test_partial_ensemble_uses_only_successful_members(self):
        ignition = (-8.2782, 41.4298)
        x, y = Transformer.from_crs(4326, 3763, always_xy=True).transform(*ignition)
        landscape = Landscape(np.full((3, 3), 142, dtype="int16"), np.full((3, 3), 100, dtype="float32"),
                              np.zeros((3, 3), dtype="float32"), np.zeros((3, 3), dtype="float32"),
                              np.ones((3, 3), dtype=bool), from_origin(x - 45, y + 45, 30, 30),
                              "EPSG:3763", 30, {"kind": "test"})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(storage, "DB", root / "test.sqlite3"), patch.object(worker, "RUNS", root / "runs"), \
                 patch.object(worker, "load_landscape", return_value=landscape), patch.object(worker, "analyse", return_value={}):
                storage.init_db()
                parent = storage.create_run(Scenario(engine="mtt", ignition=ignition, duration_min=10),
                                            mode="parameter_ensemble", ensemble={"kind": "parameter", "preset": "quick"})
                worker.process(parent)
                children = storage.child_runs(parent.id)
                worker.process(children[0]); worker.process(children[1])
                storage.update_run(children[2].id, status="failed", stage="failed", progress=100, error="fixture")
                worker._reconcile_parents()
                complete = storage.get_run(parent.id)
                self.assertEqual(complete.status, "partial")
                self.assertEqual(complete.successful_members, 2)
                self.assertEqual(len(load_result(root / "runs" / parent.id).member_arrivals or []), 2)

    def test_engine_comparison_parent_never_exposes_probability_layer(self):
        run = SimpleNamespace(status="ready", mode="engine_comparison", scenario=Scenario(ignition=[0, 0]))
        with patch.object(api_main, "get_run", return_value=run):
            with self.assertRaises(HTTPException) as raised:
                api_main.run_fire("comparison", minute=10)
        self.assertEqual(raised.exception.status_code, 409)

    def test_historical_engines_are_unregistered_and_new_comparisons_are_gone(self):
        self.assertEqual(set(ENGINES), {"mtt", "cell2fire"})
        self.assertIsNone(compatible_profile(ENGINES["mtt"], "series"))
        request = RunCreate(scenario=Scenario(engine="mtt", ignition=[0, 0]), mode="engine_comparison",
                            ensemble={"kind": "comparison", "engines": ["mtt", "cell2fire"]})
        with self.assertRaises(HTTPException) as raised:
            api_main._validate_request(request)
        self.assertEqual(raised.exception.status_code, 410)

    def test_comparison_metrics_follow_selected_minute(self):
        landscape = self.landscape()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            children = []
            for run_id, engine, arrival in (
                ("one", "mtt", np.array([[0, 10], [20, np.nan]], dtype="float32")),
                ("two", "cell2fire", np.array([[0, 20], [20, np.nan]], dtype="float32")),
            ):
                child = SimpleNamespace(id=run_id, status="ready", error=None,
                                        scenario=Scenario(engine=engine, ignition=[0, 0]),
                                        created_at="2026-01-01T00:00:00+00:00",
                                        updated_at="2026-01-01T00:00:05+00:00")
                children.append(child)
                output = root / run_id
                save_result(SimulationResult(arrival, landscape.coverage, landscape.transform, landscape.crs,
                                             1, engine, "test", {}), output)
                (output / "roads-30m.geojson").write_text(json.dumps({"features": [
                    {"properties": {"first_exposure_min": 8}},
                    {"properties": {"first_exposure_min": 15}},
                ]}))
            payload = comparison_payload(SimpleNamespace(), children, 10, root)
            self.assertEqual(payload["minute"], 10)
            self.assertEqual(payload["members"][0]["exposed_roads"], 1)
            self.assertAlmostEqual(payload["agreements"][0]["jaccard"], .5)

    def test_local_runner_cancellation_preserves_logs_and_isolates_network(self):
        class Process:
            returncode = 0
            def poll(self): return None
            def communicate(self, timeout=None): return "engine output", "engine warning"

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "cancel.requested").touch()
            calls = []
            def completed(command, **kwargs):
                calls.append(command)
                return SimpleNamespace(returncode=0, stdout="sha256:image\n", stderr="")
            with patch("backend.app.runners.subprocess.run", side_effect=completed), \
                 patch("backend.app.runners.subprocess.Popen", return_value=Process()) as popen:
                result = LocalContainerRunner().run("engine:test", root, ["simulate"])
            self.assertEqual(result.returncode, 130)
            invocation = popen.call_args.args[0]
            self.assertIn("--network", invocation)
            self.assertEqual(invocation[invocation.index("--network") + 1], "none")
            self.assertEqual(invocation.count("-v"), 1)
            self.assertIn("engine output", (root / "runner.log").read_text())
            self.assertTrue(any(call[:3] == ["docker", "stop", "--time"] for call in calls))

    def test_local_runner_timeout_still_writes_logs(self):
        class Process:
            returncode = 0
            def poll(self): return None
            def communicate(self, timeout=None): return "partial output", "timeout warning"

        with tempfile.TemporaryDirectory() as folder, \
             patch("backend.app.runners.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="id", stderr="")), \
             patch("backend.app.runners.subprocess.Popen", return_value=Process()), \
             patch("backend.app.runners.time.monotonic", side_effect=[0, 2]):
            root = Path(folder)
            with self.assertRaisesRegex(TimeoutError, "runner.log"):
                LocalContainerRunner().run("engine:test", root, ["simulate"], timeout=1)
            self.assertIn("partial output", (root / "runner.log").read_text())

    def test_slurm_runner_records_submission_identity_and_logs(self):
        submitted = []
        states = []
        commands = []
        queue_states = iter(["RUNNING\n", ""])
        def completed(command, **kwargs):
            commands.append(command)
            if "sha256sum" in command: return SimpleNamespace(returncode=0, stdout="abc123  wrapper\n", stderr="")
            if "sbatch" in command: return SimpleNamespace(returncode=0, stdout="789;cluster\n", stderr="")
            if "squeue" in command: return SimpleNamespace(returncode=0, stdout=next(queue_states), stderr="")
            if "sacct" in command: return SimpleNamespace(returncode=0, stdout="COMPLETED\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as folder, \
             patch.dict("os.environ", {"SLURM_HOST": "cluster", "SLURM_BASE_DIR": "/scratch/fire"}), \
             patch("backend.app.runners.shutil.which", return_value="/usr/bin/tool"), \
             patch("backend.app.runners.time.sleep"), \
             patch("backend.app.runners.subprocess.run", side_effect=completed):
            result = SshSlurmRunner().run(Path(folder), ["/opt/fire/run", "input", "output"],
                                          on_submit=submitted.append, on_state=states.append)
            self.assertEqual(result.external_job_id, "789")
            self.assertEqual(result.runtime_identity, "sha256:abc123")
            self.assertEqual(submitted, ["789"])
            self.assertEqual(states, ["RUNNING"])
            script = (Path(folder) / "job.sh").read_text()
            self.assertIn("#SBATCH --output=runner.log", script)
            self.assertTrue(any("sacct" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
