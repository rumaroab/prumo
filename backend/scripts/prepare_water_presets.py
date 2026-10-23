"""Refresh the bundled Guimarães presets from ICNF, or rebuild from a saved response."""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import requests

from backend.app.settings import CONFIG, ROOT

SOURCE_URL = "https://sigservices.icnf.pt/server/rest/services/BDG/Pontos_agua/MapServer/0"
QUERY = {"f": "geojson", "where": "Concelho = 'Guimarães'", "outFields": "*",
         "outSR": "4326", "returnGeometry": "true"}
DESTINATION = ROOT / "data" / "presets" / "guimaraes-water-points.geojson"
TYPES = {"Tanque de Rega": "tank", "Charca": "pond", "Lago": "pond",
         "Reservatório DFCI": "reservoir", "Albufeira de açude": "reservoir"}


def build_catalog(raw: dict) -> dict:
    if raw.get("type") != "FeatureCollection" or not raw.get("features") or raw.get("exceededTransferLimit"):
        raise ValueError("ICNF returned an empty, incomplete or invalid catalog; existing presets were not changed")
    features = []
    west, south, east, north = CONFIG["area"]["bounds"]
    for feature in raw["features"]:
        p = feature["properties"]
        if p.get("Concelho") != "Guimarães":
            continue
        lon, lat = feature["geometry"]["coordinates"]
        if feature["geometry"]["type"] != "Point" or not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("Invalid ICNF coordinates")
        # These character substitutions repair the legacy Portuguese encoding in ICNF names.
        name = (p.get("Nome") or p.get("Local") or f"Ponto de água {p['Codigo']}").translate(
            str.maketrans({"ß": "á", "þ": "ç", "·": "ú"}))
        updated = (datetime.fromtimestamp(p["DataActualizacao"] / 1000, UTC).date().isoformat()
                   if p.get("DataActualizacao") else None)
        notes = (f"ICNF historical record; source updated: {updated or 'not specified'}. "
                 f"Recorded condition: {p.get('Operacionalidade') or 'not specified'}. "
                 "Current availability and access have not been verified.")
        access = "; ".join(f"{label}: {p[key]}" for label, key in [
            ("Access class", "Classe"), ("Ownership", "TipoProprietario"),
            ("Water collection", "Captacao"), ("Location", "Local"),
        ] if p.get(key))
        features.append({"type": "Feature", "geometry": feature["geometry"], "properties": {
            "external_id": f"icnf/{p['Codigo']}", "name": name,
            "source": "icnf", "source_url": SOURCE_URL,
            "source_updated_at": updated, "data_status": "reported",
            "municipality": p["Concelho"], "parish": p.get("Freguesia"),
            "within_simulation_area": west <= lon <= east and south <= lat <= north,
            "source_type": TYPES.get(p.get("Tipo"), "other"),
            "description": " · ".join(str(p[k]) for k in ("Tipo", "Freguesia", "Local") if p.get(k)),
            "notes": notes,
            "water": {"source_type": TYPES.get(p.get("Tipo"), "other"),
                      "availability": "unknown", "capacity_m3": p.get("VolumeUtil"),
                      "flow_l_min": None, "access_notes": access, "verification_status": "reported"},
            "source_properties": p,
        }})
    if not features:
        raise ValueError("No Guimarães records returned; existing presets were not changed")
    features.sort(key=lambda f: (not f["properties"]["within_simulation_area"],
                                 f["properties"]["name"].casefold()))
    return {"type": "FeatureCollection", "features": features, "metadata": {
        "source": "ICNF — Rede de Pontos de Água", "source_url": SOURCE_URL,
        "query": QUERY, "fetched_at": datetime.now(UTC).isoformat(),
        "municipality": "Guimarães", "count": len(features), "status": "ready",
        "note": "Historical source records; current availability is unknown. Covered by the configured Guimarães model area.",
    }}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Saved ICNF GeoJSON response (offline rebuild)")
    args = parser.parse_args()
    if args.input:
        raw = json.loads(args.input.read_text())
    else:
        response = requests.get(f"{SOURCE_URL}/query", params=QUERY, timeout=60)
        response.raise_for_status()
        raw = response.json()
    catalog = build_catalog(raw)
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    temporary = DESTINATION.with_suffix(".tmp")
    temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, DESTINATION)
    print(f"Prepared {len(catalog['features'])} Guimarães water-point presets from ICNF")


if __name__ == "__main__":
    main()
