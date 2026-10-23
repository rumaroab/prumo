from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
from rasterio.features import shapes
from shapely.geometry import shape

from ..models import SimulationResult


def footprint(result: SimulationResult, minute: int) -> dict:
    if result.member_arrivals:
        stack = np.stack(result.member_arrivals)
        probability = np.mean(np.isfinite(stack) & (stack <= minute), axis=0)
        features = []
        for threshold in (.1, .5, .9):
            reached = probability >= threshold
            geometries = [shape(geometry) for geometry, value in shapes(
                reached.astype("uint8"), mask=reached, transform=result.transform) if value]
            if not geometries:
                continue
            series = gpd.GeoSeries(geometries, crs=result.crs).to_crs(4326)
            frame = json.loads(gpd.GeoDataFrame({"minute": [minute] * len(series),
                                                  "probability": [threshold] * len(series)},
                                                 geometry=series).to_json())
            features.extend(frame["features"])
        return {"type": "FeatureCollection", "features": features, "ensemble": True}
    reached = np.isfinite(result.arrival_minutes) & (result.arrival_minutes <= minute)
    geometries = [shape(geometry) for geometry, value in shapes(reached.astype("uint8"), mask=reached, transform=result.transform) if value]
    if not geometries:
        return {"type": "FeatureCollection", "features": []}
    series = gpd.GeoSeries(geometries, crs=result.crs).to_crs(4326)
    return json.loads(gpd.GeoDataFrame({"minute": [minute] * len(series)}, geometry=series).to_json())
