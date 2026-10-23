from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
from shapely.geometry import Point, box

from backend.tests import area_fixtures as fixtures
from backend.app import area_packages
from backend.app.models import AreaPreparation, AreaPreparationCreate, Ignition


class AreaPackageTests(unittest.TestCase):
    def request(self) -> AreaPreparationCreate:
        return AreaPreparationCreate(center=(-8.3, 41.4), ignitions=[
            Ignition(id="fire", name="Fire", coordinates=(-8.3, 41.4), start_min=0)])

    def record(self, request: AreaPreparationCreate, package_id: str = "package") -> AreaPreparation:
        return AreaPreparation(id="job", package_id=package_id, status="queued", stage="queued", progress=0,
                               request=request, created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z")

    def test_copernicus_dem_stem_includes_coordinate_decimal_suffixes(self) -> None:
        self.assertEqual(
            area_packages._copernicus_dem_stem(-9, 41),
            "Copernicus_DSM_COG_10_N41_00_W009_00_DEM",
        )
        self.assertEqual(
            area_packages._copernicus_dem_stem(7, -3),
            "Copernicus_DSM_COG_10_S03_00_E007_00_DEM",
        )

    def test_preparation_publishes_atomically_and_records_partial_catalogs(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            areas, preparations = root / "areas", root / "preparations"
            areas.mkdir(); preparations.mkdir()
            request = self.request()
            with patch.object(area_packages, "AREAS", areas), patch.object(area_packages, "PREPARATIONS", preparations), \
                 patch.object(area_packages, "_prepare_landscape", side_effect=fixtures.landscape), patch.object(area_packages, "_prepare_roads", side_effect=fixtures.roads), \
                 patch.object(area_packages, "_prepare_buildings", side_effect=fixtures.buildings), \
                 patch.object(area_packages, "_prepare_resources", side_effect=lambda path, *args: fixtures.catalog(path) or (["OpenStreetMap unavailable"] if path.name.startswith("water") else [])):
                area_packages._write_record(self.record(request))
                area_packages._run("job")
                completed = area_packages.get_preparation("job")
            self.assertEqual(completed.status, "partial")
            manifest = json.loads((areas / "package" / "manifest.json").read_text())
            self.assertEqual(manifest["datasets"]["water_points"]["status"], "partial")
            self.assertEqual(manifest["datasets"]["buildings"]["status"], "ready")
            self.assertEqual(manifest["schema_version"], 3)
            self.assertFalse(any(path.name.endswith(".tmp") for path in areas.iterdir()))

    def test_cell_size_margin_matrix_and_cost_acknowledgement(self) -> None:
        allowed = {(30, 5), (30, 10), (30, 25), (20, 5), (20, 10),
                   (15, 5), (15, 10), (10, 5)}
        for cell_size in (30, 20, 15, 10):
            for margin in (5, 10, 25):
                with self.subTest(cell_size=cell_size, margin=margin):
                    request = self.request().model_copy(update={"cell_size_m": cell_size,
                                                                "fire_margin_km": margin})
                    estimate = area_packages.estimate_preparation(request)
                    self.assertEqual(estimate.allowed, (cell_size, margin) in allowed)

        high = self.request().model_copy(update={"cell_size_m": 10, "fire_margin_km": 5})
        estimate = area_packages.estimate_preparation(high)
        self.assertEqual(estimate.cost_level, "high")
        self.assertTrue(estimate.requires_acknowledgement)
        with self.assertRaisesRegex(ValueError, "Confirm the high computational cost"):
            area_packages._validate_request(high)
        area_packages._validate_request(high.model_copy(update={"acknowledge_high_cost": True}))

    def test_cost_threshold_boundaries(self) -> None:
        expected = {
            500_000: "normal", 500_001: "moderate", 1_000_000: "moderate",
            1_000_001: "high", 2_000_000: "high", 2_000_001: "very_high",
            3_000_000: "very_high", 3_000_001: "blocked",
        }
        for count, level in expected.items():
            with self.subTest(count=count):
                self.assertEqual(area_packages._cost_level(count), level)

    def test_estimate_uses_all_ignitions_and_resource_radius_does_not_change_grid(self) -> None:
        base = self.request()
        small = area_packages.estimate_preparation(base.model_copy(update={"resource_radius_km": 10}))
        large = area_packages.estimate_preparation(base.model_copy(update={"resource_radius_km": 50}))
        self.assertEqual((small.grid_rows, small.grid_columns, small.cell_count),
                         (large.grid_rows, large.grid_columns, large.cell_count))

        ignitions = [base.ignitions[0], Ignition(id="second", name="Second",
                                                coordinates=(-8.15, 41.4), start_min=0)]
        spread = base.model_copy(update={"cell_size_m": 10, "resource_radius_km": 25,
                                        "ignitions": ignitions, "acknowledge_high_cost": True})
        estimate = area_packages.estimate_preparation(spread)
        self.assertGreater(estimate.cell_count, 2_000_000)
        self.assertFalse(estimate.allowed)
        self.assertIn("require 30 m", estimate.blocking_reason or "")

        wide = base.model_copy(update={"cell_size_m": 30, "fire_margin_km": 25,
                                      "ignitions": [base.ignitions[0], Ignition(
                                          id="wide", name="Wide", coordinates=(-8.23, 41.4), start_min=0)],
                                      "acknowledge_high_cost": True})
        estimate = area_packages.estimate_preparation(wide)
        self.assertGreater(estimate.cell_count, 3_000_000)
        self.assertFalse(estimate.allowed)
        self.assertIn("3,000,000-cell limit", estimate.blocking_reason or "")

    def test_package_key_includes_cell_size_but_not_acknowledgement(self) -> None:
        request = self.request()
        acknowledged = request.model_copy(update={"acknowledge_high_cost": True})
        finer = request.model_copy(update={"cell_size_m": 20})
        self.assertEqual(area_packages._package_key(request), area_packages._package_key(acknowledged))
        self.assertNotEqual(area_packages._package_key(request), area_packages._package_key(finer))

    def test_preparation_records_selected_grid_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            areas, preparations = root / "areas", root / "preparations"
            areas.mkdir(); preparations.mkdir()
            request = self.request().model_copy(update={"cell_size_m": 20})
            with patch.object(area_packages, "AREAS", areas), patch.object(area_packages, "PREPARATIONS", preparations), \
                 patch.object(area_packages, "_prepare_landscape", side_effect=fixtures.landscape) as landscape, \
                 patch.object(area_packages, "_prepare_roads", side_effect=fixtures.roads), \
                 patch.object(area_packages, "_prepare_buildings", side_effect=fixtures.buildings), \
                 patch.object(area_packages, "_prepare_resources", side_effect=fixtures.catalog):
                area_packages._write_record(self.record(request))
                area_packages._run("job")
            manifest = json.loads((areas / "package" / "manifest.json").read_text())
            self.assertEqual(manifest["cell_size_m"], 20)
            self.assertEqual(manifest["cell_count"], manifest["grid_rows"] * manifest["grid_columns"])
            self.assertEqual(manifest["source_resolutions_m"], {"elevation": 30, "land_cover": 10})
            self.assertEqual(landscape.call_args.args[2], 20)

    def test_landscape_arrays_use_selected_cell_size_and_estimated_shape(self) -> None:
        request = self.request().model_copy(update={"cell_size_m": 20})
        estimate = area_packages.estimate_preparation(request)
        grid = area_packages._grid_spec(request)
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(area_packages, "_degree_tiles", return_value=[(-9, 41)]), \
             patch.object(area_packages, "_worldcover_tiles", return_value=[(-9, 39)]), \
             patch.object(area_packages, "_download", return_value=Path(folder) / "source.tif"), \
             patch.object(area_packages, "_reproject_fill", side_effect=lambda _path, values, *_args: values.fill(100)):
            destination = Path(folder)
            area_packages._prepare_landscape(destination, list(estimate.fire_bounds), 20,
                                              projected_bounds=grid["projected_bounds"])
            arrays = np.load(destination / "landscape.npz")
            metadata = json.loads((destination / "landscape.json").read_text())
            shape = arrays["fuel"].shape
            flat_slope = bool(np.allclose(arrays["slope"], 0))
        self.assertEqual(shape, (estimate.grid_rows, estimate.grid_columns))
        self.assertEqual(metadata["cell_size_m"], 20)
        self.assertTrue(flat_slope)

    def test_building_failure_publishes_partial_package(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            areas, preparations = root / "areas", root / "preparations"
            areas.mkdir(); preparations.mkdir()
            request = self.request()
            with patch.object(area_packages, "AREAS", areas), patch.object(area_packages, "PREPARATIONS", preparations), \
                 patch.object(area_packages, "_prepare_landscape", side_effect=fixtures.landscape), patch.object(area_packages, "_prepare_roads", side_effect=fixtures.roads), \
                 patch.object(area_packages, "_prepare_buildings", side_effect=RuntimeError("buildings offline")), \
                 patch.object(area_packages, "_prepare_resources", side_effect=fixtures.catalog):
                area_packages._write_record(self.record(request))
                area_packages._run("job")
                completed = area_packages.get_preparation("job")
            self.assertEqual(completed.status, "partial")
            manifest = json.loads((areas / "package" / "manifest.json").read_text())
            self.assertEqual(manifest["datasets"]["buildings"]["status"], "failed")
            buildings = json.loads((areas / "package" / "buildings.geojson").read_text())
            self.assertEqual(buildings["features"], [])

    def test_building_heights_use_reported_levels_and_defaults(self) -> None:
        self.assertEqual(area_packages._building_properties({"height": "14.5 m"})["height_m"], 14.5)
        levels = area_packages._building_properties({"building:levels": "4"})
        self.assertEqual((levels["height_m"], levels["height_source"]), (12, "levels"))
        apartments = area_packages._building_properties({"building": "apartments"})
        self.assertEqual((apartments["height_m"], apartments["height_source"]), (9, "estimated"))
        self.assertEqual(area_packages._building_properties({"height": "1000"})["height_m"], 60)

    def test_building_preparation_keeps_only_polygon_footprints(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "buildings.geojson"
            source = gpd.GeoDataFrame(
                {"building": ["house", "yes"], "height": ["8 m", None], "osmid": [1, 2]},
                geometry=[box(560000, 4550000, 560020, 4550015), Point(560030, 4550030)], crs=3763,
            )
            with patch.object(area_packages, "_download_buildings", return_value=source):
                count = area_packages._prepare_buildings(path, [-8.4, 41.3, -8.2, 41.5])
            payload = json.loads(path.read_text())
            self.assertEqual(count, 1)
            self.assertEqual(payload["features"][0]["geometry"]["type"], "Polygon")
            self.assertEqual(payload["features"][0]["properties"]["height_m"], 8)

    def test_required_dataset_failure_does_not_publish_package(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            areas, preparations = root / "areas", root / "preparations"
            areas.mkdir(); preparations.mkdir()
            with patch.object(area_packages, "AREAS", areas), patch.object(area_packages, "PREPARATIONS", preparations), \
                 patch.object(area_packages, "_prepare_landscape", side_effect=RuntimeError("terrain offline")):
                area_packages._write_record(self.record(self.request()))
                area_packages._run("job")
                completed = area_packages.get_preparation("job")
            self.assertEqual(completed.status, "failed")
            self.assertIn("terrain offline", completed.error or "")
            self.assertFalse((areas / "package").exists())

    def test_cached_package_skips_background_work(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            areas, preparations = root / "areas", root / "preparations"
            areas.mkdir(); preparations.mkdir()
            request = self.request()
            package_id = area_packages._package_key(request)
            (areas / package_id).mkdir()
            (areas / package_id / "manifest.json").write_text(json.dumps({
                "id": package_id, "status": "ready", "datasets": {"roads": {"status": "ready"}}}))
            with patch.object(area_packages, "AREAS", areas), patch.object(area_packages, "PREPARATIONS", preparations), \
                 patch.object(area_packages, "_executor") as executor:
                record = area_packages.create_preparation(request)
            self.assertEqual(record.status, "ready")
            executor.submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
