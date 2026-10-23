from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from backend.app.settings import CONFIG, PREPARED, ensure_dirs


def prepare(elevation_path: Path, cover_path: Path) -> None:
    ensure_dirs()
    area = CONFIG["area"]
    transformer = Transformer.from_crs(4326, area["projected_crs"], always_xy=True)
    west, south = transformer.transform(area["bounds"][0], area["bounds"][1])
    east, north = transformer.transform(area["bounds"][2], area["bounds"][3])
    margin = area["processing_margin_m"]
    west, south, east, north = west - margin, south - margin, east + margin, north + margin
    cell = area["cell_size_m"]
    width, height = int(np.ceil((east - west) / cell)), int(np.ceil((north - south) / cell))
    target_transform = from_origin(west, north, cell, cell)

    elevation = _read_aligned(elevation_path, height, width, target_transform, area["projected_crs"], Resampling.bilinear)
    cover = _read_aligned(cover_path, height, width, target_transform, area["projected_crs"], Resampling.nearest)
    coverage = np.isfinite(elevation) & np.isfinite(cover)
    elevation = np.nan_to_num(elevation, nan=0).astype("float32")
    cover = np.nan_to_num(cover, nan=-1).astype("int16")
    rise_y, rise_x = np.gradient(elevation, cell)
    slope = np.degrees(np.arctan(np.hypot(rise_x, rise_y))).astype("float32")
    aspect = ((np.degrees(np.arctan2(rise_x, -rise_y)) + 360) % 360).astype("float32")
    mapping = {int(key): value for key, value in CONFIG["worldcover_to_fuel"].items()}
    fuel = np.full(cover.shape, 99, dtype="int16")
    for source, target in mapping.items():
        fuel[cover == source] = target

    temp = PREPARED / "landscape.tmp.npz"
    from backend.app.io import _fuel_translations
    anderson, fuel_load, fuel_depth = _fuel_translations(fuel)
    np.savez_compressed(temp, fuel=fuel, elevation=elevation, slope=slope, aspect=aspect, coverage=coverage,
                        fuel_anderson13=anderson, fuel_load_kg_m2=fuel_load, fuel_depth_m=fuel_depth)
    os.replace(temp, PREPARED / "landscape.npz")
    metadata = {
        "transform": list(target_transform)[:6], "crs": area["projected_crs"], "cell_size_m": cell,
        "bounds": area["bounds"],
        "provenance": {
            "kind": "real-source preparation", "elevation": str(elevation_path.resolve()),
            "land_cover": str(cover_path.resolve()), "fuel_mapping": mapping,
            "warning": "Demonstration fuel mapping; not locally calibrated",
            "fuel_translation_version": 1,
            "fuel_translation_warning": "Anderson and physical fuel properties are illustrative crosswalks",
        },
    }
    _atomic_json(PREPARED / "landscape.json", metadata)


def _read_aligned(path, height, width, transform, crs, resampling):
    destination = np.full((height, width), np.nan, dtype="float32")
    with rasterio.open(path) as source:
        reproject(source.read(1), destination, src_transform=source.transform, src_crs=source.crs,
                  dst_transform=transform, dst_crs=crs, dst_nodata=np.nan, resampling=resampling)
    return destination


def _atomic_json(path: Path, value) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2))
    os.replace(temp, path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--elevation", type=Path, required=True)
    parser.add_argument("--land-cover", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.elevation, args.land_cover)
