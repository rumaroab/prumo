from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import osmnx as ox

from backend.app.settings import CONFIG, PREPARED, ensure_dirs


def prepare() -> None:
    ensure_dirs()
    west, south, east, north = CONFIG["area"]["bounds"]
    features = ox.features_from_bbox((west, south, east, north), {"amenity": "fire_station"})
    output = []
    seen: list[tuple[str, float, float]] = []
    for index, row in features.iterrows():
        geometry = row.geometry
        point = geometry if geometry.geom_type == "Point" else geometry.representative_point()
        element_type, osmid = index
        external_id = f"{element_type}/{osmid}"
        name = _value(row.get("name")) or "Unverified fire station"
        if any(previous == name and abs(point.x - x) < .0015 and abs(point.y - y) < .0015
               for previous, x, y in seen):
            continue
        seen.append((name, point.x, point.y))
        output.append({
            "type": "Feature", "geometry": {"type": "Point", "coordinates": [point.x, point.y]},
            "properties": {
                "external_id": external_id, "name": name,
                "source": "openstreetmap", "source_url": f"https://www.openstreetmap.org/{element_type}/{osmid}",
                "source_updated_at": None, "description": "OpenStreetMap amenity=fire_station",
            },
        })
    payload = {"type": "FeatureCollection", "features": output, "metadata": {
        "source": "OpenStreetMap", "license": "ODbL", "count": len(output),
        "source_record_count": len(features),
        "fetched_at": datetime.now(UTC).isoformat(), "bounds": [west, south, east, north],
        "coverage": "Configured area only; completeness and operational status are not guaranteed.",
    }}
    temporary = PREPARED / "fire-stations.tmp.geojson"
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    os.replace(temporary, PREPARED / "fire-stations.geojson")


def _value(value) -> str:
    return "" if value is None or value != value else str(value)


if __name__ == "__main__":
    prepare()
