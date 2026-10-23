from __future__ import annotations

import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds, transform as window_transform
from shapely.geometry import mapping

from ..io import atomic_json
from ..models import SimulationResult
from ..settings import PREPARED

ANALYSIS_VERSION = 6


def roads_revision(prepared: Path | None = None) -> str | None:
    metadata = (prepared or PREPARED) / "roads.json"
    return json.loads(metadata.read_text()).get("revision") if metadata.exists() else None


def analyse(result: SimulationResult, buffer_m: float, output: Path, prepared: Path | None = None) -> dict:
    prepared = prepared or PREPARED
    display_roads = gpd.read_file(prepared / "roads.geojson")
    roads = display_roads.to_crs(result.crs)
    features = []
    raster_height, raster_width = result.arrival_minutes.shape
    for row, display_geometry in zip(roads.itertuples(), display_roads.geometry):
        area = row.geometry.buffer(buffer_m) if buffer_m else row.geometry
        raw_window = from_bounds(*area.bounds, transform=result.transform)
        row_start = max(0, math.floor(raw_window.row_off))
        row_stop = min(raster_height, math.ceil(raw_window.row_off + raw_window.height))
        col_start = max(0, math.floor(raw_window.col_off))
        col_stop = min(raster_width, math.ceil(raw_window.col_off + raw_window.width))
        if row_stop < row_start:
            row_stop = row_start
        if col_stop < col_start:
            col_stop = col_start
        window = Window(col_start, row_start, col_stop - col_start, row_stop - row_start)
        coverage = result.coverage[row_start:row_stop, col_start:col_stop]
        if coverage.size:
            selected = geometry_mask([area], coverage.shape, window_transform(window, result.transform),
                                     invert=True, all_touched=True)
            covered = selected & coverage
        else:
            selected = covered = np.zeros(coverage.shape, dtype=bool)
        values = result.arrival_minutes[row_start:row_stop, col_start:col_stop][covered]
        finite = values[np.isfinite(values)]
        status = "unknown" if not selected.any() or (selected & ~coverage).any() else "covered"
        exposure = float(finite.min()) if finite.size else None
        member_exposures = None
        percentiles = (None, None, None)
        reached_fraction = None
        if result.member_arrivals:
            member_exposures = []
            for member in result.member_arrivals:
                member_values = member[row_start:row_stop, col_start:col_stop][covered]
                member_finite = member_values[np.isfinite(member_values)]
                member_exposures.append(float(member_finite.min()) if member_finite.size else None)
            reached = np.array([value for value in member_exposures if value is not None], dtype="float32")
            reached_fraction = len(reached) / len(member_exposures)
            horizon = result.provenance.get("horizon_min")
            if horizon is not None:
                censored = np.array([value if value is not None else float(horizon) + result.temporal_resolution_min
                                     for value in member_exposures], dtype="float32")
                raw = np.percentile(censored, [10, 50, 90])
                percentiles = tuple(float(value) if value <= float(horizon) else None for value in raw)
            elif reached.size:
                percentiles = tuple(float(value) for value in np.percentile(reached, [10, 50, 90]))
        road_class = row.road_class
        if isinstance(road_class, (list, tuple, np.ndarray)):
            road_class = str(road_class[0]) if len(road_class) else "road"
        feature = {
            "type": "Feature",
            "geometry": mapping(display_geometry),
            "properties": {
                "segment_id": row.segment_id, "name": row.name or "Unnamed road",
                "road_class": road_class or "road", "first_exposure_min": exposure,
                "coverage": status, "engine": result.engine,
                "member_arrival_minutes": member_exposures,
                "arrival_p10_min": percentiles[0], "arrival_p50_min": percentiles[1],
                "arrival_p90_min": percentiles[2], "reached_fraction": reached_fraction,
            },
        }
        features.append(feature)
    collection = {"type": "FeatureCollection", "features": features, "buffer_m": buffer_m,
                  "analysis_version": ANALYSIS_VERSION, "roads_revision": roads_revision(prepared)}
    atomic_json(output / f"roads-{int(buffer_m)}m.geojson", collection)
    return collection
