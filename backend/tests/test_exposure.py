from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import numpy as np
from rasterio.transform import from_origin
from shapely.geometry import LineString

from backend.app.models import SimulationResult
from backend.app.services import exposure


class ExposureTests(unittest.TestCase):
    def test_windowed_analysis_finds_arrival_and_handles_outside_roads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared = Path(directory)
            original_prepared = exposure.PREPARED
            exposure.PREPARED = prepared
            try:
                roads = gpd.GeoDataFrame([
                    {"segment_id": "reached", "name": "Reached road", "road_class": "track",
                     "geometry": LineString([(-8.89, 41.85), (-8.81, 41.85)])},
                    {"segment_id": "outside", "name": "Outside road", "road_class": "track",
                     "geometry": LineString([(-8.0, 41.0), (-7.9, 41.0)])},
                ], crs=4326)
                roads.to_file(prepared / "roads.geojson", driver="GeoJSON")
                (prepared / "roads.json").write_text(json.dumps({"revision": "test"}))
                arrival = np.full((3, 3), np.nan, dtype="float32")
                arrival[1, 1] = 12
                result = SimulationResult(arrival, np.ones((3, 3), dtype=bool),
                                          from_origin(-9, 42, .1, .1), "EPSG:4326", 1,
                                          "test", "1", {})

                collection = exposure.analyse(result, 0, prepared)

                properties = {feature["properties"]["segment_id"]: feature["properties"]
                              for feature in collection["features"]}
                self.assertEqual(properties["reached"]["first_exposure_min"], 12)
                self.assertIsNone(properties["outside"]["first_exposure_min"])
                self.assertEqual(properties["outside"]["coverage"], "unknown")
                self.assertEqual(collection["analysis_version"], exposure.ANALYSIS_VERSION)
            finally:
                exposure.PREPARED = original_prepared


if __name__ == "__main__":
    unittest.main()
