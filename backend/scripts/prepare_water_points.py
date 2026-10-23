from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import requests

from backend.app.settings import CONFIG, PREPARED, ensure_dirs


OVERPASS_URLS = [
    os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter"),
    "https://overpass.kumi.systems/api/interpreter",
]
ALLOWED = {"fire_hydrant": "hydrant", "water_tank": "tank", "fire_water_pond": "pond"}


def prepare() -> None:
    ensure_dirs()
    west, south, east, north = CONFIG["area"]["bounds"]
    query = f"""[out:json][timeout:120];
    nwr[\"emergency\"~\"^(fire_hydrant|water_tank|fire_water_pond)$\"]({south},{west},{north},{east});
    out center tags;"""
    result, errors = None, []
    for endpoint in dict.fromkeys(OVERPASS_URLS):
        try:
            response = requests.get(endpoint, params={"data": query},
                                    headers={"User-Agent": "fireline-access-local-demo/0.1"}, timeout=150)
            response.raise_for_status()
            result = response.json()
            break
        except (requests.RequestException, ValueError) as error:
            errors.append(f"{endpoint}: {type(error).__name__}")
    features = []
    for element in (result or {}).get("elements", []):
        tags = element.get("tags", {})
        center = element.get("center", element)
        lon, lat = center.get("lon"), center.get("lat")
        emergency = tags.get("emergency")
        if lon is None or lat is None or emergency not in ALLOWED:
            continue
        external_id = f"{element['type']}/{element['id']}"
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "external_id": external_id,
                "name": tags.get("name") or tags.get("ref"),
                "source_type": ALLOWED[emergency],
                "tags": tags,
                "data_status": "unverified",
            },
        })
    payload = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "OpenStreetMap contributors via Overpass API",
            "attribution": "© OpenStreetMap contributors",
            "fetched_at": datetime.now(UTC).isoformat(),
            "bounds": [west, south, east, north],
            "count": len(features),
            "status": "ready" if result is not None else "fetch_failed",
            "error_count": len(errors),
        },
    }
    temporary = PREPARED / "water-points.tmp.geojson"
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    os.replace(temporary, PREPARED / "water-points.geojson")
    if result is None:
        print("Water-point fetch was unavailable; wrote an empty catalog for manual fallback")
    else:
        print(f"Prepared {len(features)} potential firefighting water points")


if __name__ == "__main__":
    prepare()
