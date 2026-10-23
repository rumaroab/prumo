from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from pyproj import Transformer
from rasterio.transform import from_origin

from backend.app.engines.cell2fire import Cell2FireEngine
from backend.app.engines.mtt import MTTEngine
from backend.app.models import Ignition, Landscape, Scenario
from backend.app.models import AreaPreparationCreate
from backend.app.area_packages import _package_key, _validate_request


class MultipleIgnitionTests(unittest.TestCase):
    def landscape(self, size: int = 20, cell_size_m: int = 30) -> tuple[Landscape, callable]:
        transform = from_origin(100000, 200000, cell_size_m, cell_size_m)
        landscape = Landscape(
            fuel=np.full((size, size), 142, dtype="int16"),
            elevation=np.full((size, size), 100, dtype="float32"),
            slope=np.zeros((size, size), dtype="float32"),
            aspect=np.zeros((size, size), dtype="float32"),
            coverage=np.ones((size, size), dtype=bool), transform=transform,
            crs="EPSG:3763", cell_size_m=cell_size_m, provenance={"kind": "test"},
        )
        reverse = Transformer.from_crs(3763, 4326, always_xy=True)

        def coordinates(row: int, col: int) -> tuple[float, float]:
            x, y = transform * (col + .5, row + .5)
            return reverse.transform(x, y)

        return landscape, coordinates

    def test_legacy_input_becomes_one_new_style_ignition(self) -> None:
        scenario = Scenario.model_validate({"ignition": [-8.2, 41.4]})
        self.assertEqual(scenario.ignition, (-8.2, 41.4))
        self.assertEqual(scenario.ignitions[0].start_min, 0)
        self.assertNotIn("ignition", scenario.model_dump())
        self.assertIn("ignitions", scenario.model_dump())

    def test_mtt_honours_delayed_starts_and_combines_fronts(self) -> None:
        landscape, point = self.landscape(30)
        scenario = Scenario(
            duration_min=10,
            ignitions=[
                Ignition(id="one", name="Fire 1", coordinates=point(3, 3), start_min=5),
                Ignition(id="two", name="Fire 2", coordinates=point(26, 26), start_min=8),
            ],
        )
        with tempfile.TemporaryDirectory() as folder:
            result = MTTEngine().simulate(landscape, scenario, Path(folder))
        finite = result.arrival_minutes[np.isfinite(result.arrival_minutes)]
        self.assertGreaterEqual(float(finite.min()), 5)
        self.assertEqual(float(result.arrival_minutes[3, 3]), 5)
        self.assertEqual(float(result.arrival_minutes[26, 26]), 8)

    def test_mtt_accepts_finer_uniform_grid(self) -> None:
        landscape, point = self.landscape(20, cell_size_m=10)
        scenario = Scenario(duration_min=10, ignitions=[
            Ignition(id="fine", name="Fine grid", coordinates=point(10, 10), start_min=0)])
        with tempfile.TemporaryDirectory() as folder:
            result = MTTEngine().simulate(landscape, scenario, Path(folder))
        self.assertEqual(result.arrival_minutes.shape, (20, 20))
        self.assertEqual(result.manifest["native_spatial_resolution_m"], 10)
        self.assertTrue(np.isfinite(result.arrival_minutes[10, 10]))

    def test_mtt_timed_containment_blocks_only_after_activation(self) -> None:
        landscape, point = self.landscape(20)
        scenario = Scenario(duration_min=720, ignitions=[
            Ignition(id="one", name="Fire", coordinates=point(10, 2), start_min=0)])
        geometry = {"type": "LineString", "coordinates": [point(row, 3) for row in range(20)]}
        with tempfile.TemporaryDirectory() as folder:
            baseline = MTTEngine().simulate(landscape, scenario, Path(folder) / "baseline")
            early = MTTEngine().simulate(landscape, scenario, Path(folder) / "early", intervention={
                "tasks": [{"task_id": "line", "task_name": "Early line", "geometry": geometry,
                           "activation_min": 0, "team_ids": ["team"]}]})
            late = MTTEngine().simulate(landscape, scenario, Path(folder) / "late", intervention={
                "tasks": [{"task_id": "line", "task_name": "Late line", "geometry": geometry,
                           "activation_min": 1000, "team_ids": ["team"]}]})
        self.assertTrue(np.isfinite(baseline.arrival_minutes[10, 4]))
        self.assertTrue(np.isnan(early.arrival_minutes[10, 4]))
        np.testing.assert_allclose(baseline.arrival_minutes, late.arrival_minutes, equal_nan=True)
        self.assertGreater(early.manifest["intervention"]["scheduled_cells"], 0)

    def test_area_cache_reuses_geometry_when_only_timing_changes(self) -> None:
        first = AreaPreparationCreate(center=(-8.3, 41.4), ignitions=[
            Ignition(id="one", name="First", coordinates=(-8.3, 41.4), start_min=0)])
        changed = AreaPreparationCreate(center=(-8.3, 41.4), ignitions=[
            Ignition(id="renamed", name="Later", coordinates=(-8.3, 41.4), start_min=90)])
        self.assertEqual(_package_key(first), _package_key(changed))

    def test_area_rejects_ignition_outside_resource_radius(self) -> None:
        request = AreaPreparationCreate(center=(-8.3, 41.4), resource_radius_km=10, ignitions=[
            Ignition(name="Far fire", coordinates=(-8.0, 41.4), start_min=0)])
        with self.assertRaisesRegex(ValueError, "outside the selected resource radius"):
            _validate_request(request)

    def test_cell2fire_native_patch_injects_a_delayed_second_fire(self) -> None:
        engine = Cell2FireEngine()
        if not engine.available()[0] or not engine._supports_scheduled_ignitions():
            self.skipTest("Patched Cell2Fire binary is not built")
        landscape, point = self.landscape(20)
        scenario = Scenario(
            engine="cell2fire", duration_min=10,
            ignitions=[
                Ignition(id="one", name="Fire 1", coordinates=point(2, 2), start_min=0),
                Ignition(id="two", name="Fire 2", coordinates=point(17, 17), start_min=4),
            ],
        )
        with tempfile.TemporaryDirectory() as folder:
            result = engine.simulate(landscape, scenario, Path(folder))
            events = (Path(folder) / "cell2fire-native" / "ignition_events.csv").read_text()
        self.assertEqual(float(result.arrival_minutes[2, 2]), 0)
        self.assertEqual(float(result.arrival_minutes[17, 17]), 4)
        self.assertIn("4,", events)
        self.assertIn("scheduled-ignitions-v1", result.manifest["native_patch"])

    def test_cell2fire_waits_for_later_fire_after_first_dies(self) -> None:
        engine = Cell2FireEngine()
        if not engine.available()[0] or not engine._supports_scheduled_ignitions():
            self.skipTest("Patched Cell2Fire binary is not built")
        landscape, point = self.landscape(12)
        landscape.fuel[:] = 99
        landscape.fuel[2, 2] = 142
        landscape.fuel[9, 9] = 142
        scenario = Scenario(engine="cell2fire", duration_min=10, ignitions=[
            Ignition(id="one", name="First isolated fire", coordinates=point(2, 2), start_min=0),
            Ignition(id="two", name="Later isolated fire", coordinates=point(9, 9), start_min=6),
        ])
        with tempfile.TemporaryDirectory() as folder:
            result = engine.simulate(landscape, scenario, Path(folder))
            events = (Path(folder) / "cell2fire-native" / "ignition_events.csv").read_text()
        self.assertEqual(float(result.arrival_minutes[9, 9]), 6)
        self.assertIn("6,", events)

    def test_cell2fire_activates_timed_firebreak_cells(self) -> None:
        engine = Cell2FireEngine()
        if not engine.available()[0] or not engine._supports_timed_firebreaks():
            self.skipTest("Timed-firebreak Cell2Fire binary is not built")
        landscape, point = self.landscape(12)
        scenario = Scenario(engine="cell2fire", duration_min=10, ignitions=[
            Ignition(id="one", name="Fire", coordinates=point(6, 2), start_min=0)])
        geometry = {"type": "LineString", "coordinates": [point(row, 6) for row in range(12)]}
        with tempfile.TemporaryDirectory() as folder:
            result = engine.simulate(landscape, scenario, Path(folder), intervention={
                "tasks": [{"task_id": "line", "task_name": "Timed line", "geometry": geometry,
                           "activation_min": 0, "team_ids": ["team"]}]})
            events = (Path(folder) / "cell2fire-native" / "timed_firebreak_events.csv").read_text()
        self.assertIn("activated", events)
        self.assertGreater(result.manifest["intervention"]["scheduled_cells"], 0)


if __name__ == "__main__":
    unittest.main()
