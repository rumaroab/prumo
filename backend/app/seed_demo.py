from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from .io import atomic_json, save_result
from .models import Scenario, SimulationResult
from .services.exposure import ANALYSIS_VERSION, analyse, roads_revision
from .settings import CONFIG, PREPARED, RUNS, ensure_dirs
from .storage import create_run, init_db


STANDARD_SCENARIOS = [
    ("penha-east", "Cume a leste", (-8.2782, 41.4298), 285, 24),
    ("penha-south", "Acesso a sul", (-8.2844, 41.4206), 25, 18),
    ("penha-north", "Encosta a norte", (-8.2740, 41.4413), 210, 32),
]

EXTREME_SCENARIOS = [
    ("penha-east", "Demonstração de condições extremas · Cume a oeste", (-8.2660, 41.4320), 270, 120),
    ("penha-north", "Demonstração de condições extremas · Propagação a leste", (-8.3000, 41.4320), 90, 110),
    ("penha-south", "Demonstração de condições extremas · Frente a sudoeste", (-8.2680, 41.4420), 225, 120),
]


def seed() -> None:
    ensure_dirs()
    init_db()
    if not (PREPARED / "landscape.npz").exists():
        _landscape()
    roads_meta = json.loads((PREPARED / "roads.json").read_text()) if (PREPARED / "roads.json").exists() else {}
    if not (PREPARED / "roads.geojson").exists() or not roads_meta:
        _roads()
    if not (PREPARED / "buildings.geojson").exists():
        _buildings()
    from .demo_exercises import seed_inputs, PACKAGE_ID, VERSION
    from .settings import AREAS
    from .engines.cell2fire import Cell2FireEngine
    roads_available = (PREPARED / "roads.graphml").exists() or (AREAS / PACKAGE_ID / "manifest.json").exists()
    fire_available = Cell2FireEngine().available()[0] or all(
        (RUNS / f"{engine}-{VERSION}" / "result.npz").exists() for engine in ("cell2fire", "mtt"))
    if roads_available and fire_available:
        seed_inputs()


def generate_bundled_demos() -> None:
    """Prepare the two selected engine examples used by the decision workspace."""
    seed()


def _grid():
    west, south, east, north = CONFIG["area"]["bounds"]
    convert = Transformer.from_crs(4326, 3763, always_xy=True)
    x0, y0 = convert.transform(west, south)
    x1, y1 = convert.transform(east, north)
    cell = 30
    width, height = int(np.ceil((x1 - x0) / cell)), int(np.ceil((y1 - y0) / cell))
    return x0, y0, x1, y1, width, height, from_origin(x0, y1, cell, cell)


def _landscape() -> None:
    x0, y0, x1, y1, width, height, transform = _grid()
    yy, xx = np.mgrid[:height, :width]
    elevation = 180 + 260 * np.exp(-(((xx - width * .52) / 65) ** 2 + ((yy - height * .54) / 70) ** 2))
    gy, gx = np.gradient(elevation, 30)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    aspect = (np.degrees(np.arctan2(gx, -gy)) + 360) % 360
    fuel = np.full((height, width), 142, dtype="int16")
    fuel[(xx + yy) % 17 < 3] = 165
    coverage = np.ones((height, width), dtype=bool)
    temp = PREPARED / "landscape.tmp.npz"
    np.savez_compressed(temp, fuel=fuel, elevation=elevation.astype("float32"), slope=slope.astype("float32"),
                        aspect=aspect.astype("float32"), coverage=coverage)
    os.replace(temp, PREPARED / "landscape.npz")
    (PREPARED / "landscape.json").write_text(json.dumps({
        "transform": list(transform)[:6], "crs": "EPSG:3763", "cell_size_m": 30,
        "bounds": CONFIG["area"]["bounds"],
        "provenance": {"kind": "bundled illustrative preview", "warning": "Not DGT or field-validated data"},
    }, indent=2))


def _roads() -> None:
    west, south, east, north = CONFIG["area"]["bounds"]
    lines = []
    for index in range(12):
        fraction = (index + 1) / 13
        lat = south + (north - south) * fraction
        lines.append({"segment_id": f"demo-h-{index}", "name": f"Penha approach {index + 1}",
                      "road_class": "secondary" if index % 3 == 0 else "residential",
                      "geometry": LineString([(west, lat), (east, lat + .004 * np.sin(index))])})
    for index in range(10):
        fraction = (index + 1) / 11
        lon = west + (east - west) * fraction
        lines.append({"segment_id": f"demo-v-{index}", "name": f"Ridge connection {index + 1}",
                      "road_class": "track" if index % 4 == 0 else "tertiary",
                      "geometry": LineString([(lon, south), (lon + .004 * np.cos(index), north)])})
    projected = gpd.GeoDataFrame(lines, crs=4326).to_crs(3763)
    segments = []
    for road in projected.itertuples():
        count = max(1, int(road.geometry.length // 100) + 1)
        points = [road.geometry.interpolate(i / count, normalized=True) for i in range(count + 1)]
        for index in range(count):
            segments.append({"segment_id": f"{road.segment_id}-{index}", "name": road.name,
                             "road_class": road.road_class, "geometry": LineString([points[index], points[index + 1]])})
    gpd.GeoDataFrame(segments, crs=3763).to_crs(4326).to_file(PREPARED / "roads.geojson", driver="GeoJSON")
    road_file = PREPARED / "roads.geojson"
    revision = hashlib.sha256(road_file.read_bytes()).hexdigest()[:16]
    (PREPARED / "roads.json").write_text(json.dumps({"source": "bundled illustrative preview", "count": len(segments),
                                                       "version": 3, "revision": revision,
                                                       "bounds": CONFIG["area"]["bounds"]}, indent=2))


def _buildings() -> None:
    project = Transformer.from_crs(4326, 3763, always_xy=True)
    rows = []
    for cluster, (_, _, coordinates, _, _) in enumerate(EXTREME_SCENARIOS):
        center_x, center_y = project.transform(*coordinates)
        for row in range(5):
            for column in range(6):
                x = center_x + (column - 2.5) * 48 + (row % 2) * 12
                y = center_y + (row - 2) * 44
                width, depth = (22, 15) if (row + column) % 3 else (28, 18)
                height = (6, 9, 12)[(row + column + cluster) % 3]
                rows.append({
                    "osm_id": f"demo/{cluster}-{row}-{column}",
                    "building_type": "illustrative",
                    "height_m": height,
                    "height_source": "estimated",
                    "name": "",
                    "geometry": box(x - width / 2, y - depth / 2, x + width / 2, y + depth / 2),
                })
    collection = json.loads(gpd.GeoDataFrame(rows, crs=3763).to_crs(4326).to_json())
    collection["metadata"] = {
        "status": "ready",
        "source": "bundled illustrative preview",
        "count": len(rows),
        "warning": "Synthetic blocks for interface demonstration; not observed structures.",
    }
    (PREPARED / "buildings.geojson").write_text(json.dumps(collection, separators=(",", ":")))


def _load_demo_result(output: Path) -> SimulationResult:
    from .io import load_result
    return load_result(output)


def _load_landscape():
    from .io import load_landscape
    return load_landscape()


def _result_version(output: Path) -> str | None:
    path = output / "result.json"
    return json.loads(path.read_text()).get("engine_version") if path.exists() else None


def _scenario_matches(output: Path, scenario: Scenario) -> bool:
    path = output / "scenario.json"
    return path.exists() and json.loads(path.read_text()) == scenario.model_dump(mode="json")


def _ensure_exposure(output: Path, buffer_m: float) -> None:
    path = output / f"roads-{int(buffer_m)}m.geojson"
    current = json.loads(path.read_text()) if path.exists() else {}
    if current.get("analysis_version") != ANALYSIS_VERSION or current.get("roads_revision") != roads_revision():
        analyse(_load_demo_result(output), buffer_m, output)


def _register_cell2fire() -> None:
    for base_id, name, ignition, direction, speed in STANDARD_SCENARIOS:
        if base_id != "penha-south":
            continue
        run_id = base_id.replace("penha", "cell2fire")
        scenario = Scenario(name=f"{name} · Cell2Fire", engine="cell2fire", ignition=ignition,
                            wind_direction_deg=direction, wind_speed_kmh=speed,
                            duration_min=120, exposure_buffer_m=30)
        output = RUNS / run_id
        if (output / "result.npz").exists():
            _ensure_exposure(output, scenario.exposure_buffer_m)
            create_run(scenario, demo=True, run_id=run_id)


def _register_mtt_decision() -> None:
    """Cache one experimental MTT result for the same locality and road network."""
    from .engines.mtt import MTTEngine

    _, _, ignition, direction, _ = STANDARD_SCENARIOS[1]
    scenario = Scenario(name="Acesso a sul · MTT experimental", engine="mtt", ignition=ignition,
                        wind_direction_deg=direction, wind_speed_kmh=25,
                        moisture="moderate", duration_min=120, exposure_buffer_m=30)
    output = RUNS / "mtt-south"
    engine = MTTEngine()
    if _result_version(output) != engine.version or not _scenario_matches(output, scenario):
        result = engine.simulate(_load_landscape(), scenario, output)
        save_result(result, output)
        for cache in output.glob("fire-*.geojson"):
            cache.unlink()
        analyse(result, scenario.exposure_buffer_m, output)
        atomic_json(output / "scenario.json", scenario.model_dump(mode="json"))
    else:
        _ensure_exposure(output, scenario.exposure_buffer_m)
    create_run(scenario, demo=True, run_id="mtt-south")


def _generate_cell2fire() -> None:
    from .engines.cell2fire import Cell2FireEngine
    from .io import load_landscape

    engine = Cell2FireEngine()
    if not engine.available()[0]:
        return
    landscape = load_landscape()
    for base_id, name, ignition, direction, speed in STANDARD_SCENARIOS:
        if base_id != "penha-south":
            continue
        run_id = base_id.replace("penha", "cell2fire")
        scenario = Scenario(name=f"{name} · Cell2Fire", engine="cell2fire", ignition=ignition,
                            wind_direction_deg=direction, wind_speed_kmh=speed,
                            duration_min=120, exposure_buffer_m=30)
        output = RUNS / run_id
        if not (output / "result.npz").exists():
            result = engine.simulate(landscape, scenario, output)
            save_result(result, output)
        _ensure_exposure(output, scenario.exposure_buffer_m)
        create_run(scenario, demo=True, run_id=run_id)


if __name__ == "__main__":
    generate_bundled_demos()
