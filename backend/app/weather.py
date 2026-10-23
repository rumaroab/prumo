from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .settings import WEATHER, ensure_dirs

FIELDS = ("timestamp", "wind_speed_kmh", "wind_direction_deg", "temperature_c",
          "relative_humidity_pct", "precipitation_mm")
MAX_BYTES = 2_000_000
MAX_GAP_SECONDS = 6 * 3600


def save_weather_series(payload: bytes, filename: str = "weather.csv", provenance: dict | None = None) -> dict:
    if not payload or len(payload) > MAX_BYTES:
        raise ValueError("Weather CSV must contain between 1 byte and 2 MB")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Weather CSV must be UTF-8") from error
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or tuple(reader.fieldnames) != FIELDS:
        raise ValueError("Weather CSV columns must be: " + ", ".join(FIELDS))
    rows: list[dict] = []
    previous: datetime | None = None
    for number, raw in enumerate(reader, start=2):
        try:
            stamp = datetime.fromisoformat(raw["timestamp"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("timezone missing")
            stamp = stamp.astimezone(timezone.utc)
            speed = float(raw["wind_speed_kmh"])
            direction = float(raw["wind_direction_deg"])
            temperature = float(raw["temperature_c"])
            humidity = float(raw["relative_humidity_pct"])
            rain = float(raw["precipitation_mm"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid weather value on row {number}: {error}") from error
        if not 0 <= speed <= 200 or not 0 <= direction < 360 or not -60 <= temperature <= 60:
            raise ValueError(f"Weather value outside supported limits on row {number}")
        if not 0 <= humidity <= 100 or not 0 <= rain <= 1000:
            raise ValueError(f"Weather value outside supported limits on row {number}")
        if previous and stamp <= previous:
            raise ValueError(f"Timestamps must increase strictly (row {number})")
        if previous and (stamp - previous).total_seconds() > MAX_GAP_SECONDS:
            raise ValueError(f"Weather gap exceeds six hours before row {number}")
        previous = stamp
        rows.append({"timestamp": stamp.isoformat().replace("+00:00", "Z"),
                     "wind_speed_kmh": speed, "wind_direction_deg": direction,
                     "temperature_c": temperature, "relative_humidity_pct": humidity,
                     "precipitation_mm": rain})
    if len(rows) < 2:
        raise ValueError("Weather CSV requires at least two observations")
    ensure_dirs()
    weather_id = uuid4().hex[:12]
    folder = WEATHER / weather_id
    folder.mkdir()
    digest = hashlib.sha256(payload).hexdigest()
    (folder / "source.csv").write_bytes(payload)
    metadata = {"id": weather_id, "filename": Path(filename).name, "sha256": digest,
                "rows": len(rows), "start": rows[0]["timestamp"], "end": rows[-1]["timestamp"],
                "max_gap_hours": MAX_GAP_SECONDS / 3600, "valid": True,
                "validation_report": {"schema": "weather-series-v1", "timestamps_utc": True,
                                      "strictly_increasing": True, "numeric_limits": True,
                                      "maximum_gap_hours": MAX_GAP_SECONDS / 3600}}
    if provenance:
        metadata["provenance"] = provenance
    (folder / "normalized.json").write_text(json.dumps(rows, indent=2))
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2))
    return metadata


def list_weather_series() -> list[dict]:
    ensure_dirs()
    values = []
    for path in WEATHER.glob("*/metadata.json"):
        try:
            values.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(values, key=lambda value: value["start"], reverse=True)


def load_weather_series(weather_id: str) -> list[dict]:
    if not weather_id.replace("-", "").isalnum():
        raise KeyError(weather_id)
    path = WEATHER / weather_id / "normalized.json"
    if not path.exists():
        raise KeyError(weather_id)
    return json.loads(path.read_text())


def validate_weather_coverage(weather_id: str, duration_min: int, absolute_start: datetime | None = None) -> None:
    rows = load_weather_series(weather_id)
    start = datetime.fromisoformat(rows[0]["timestamp"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(rows[-1]["timestamp"].replace("Z", "+00:00"))
    if absolute_start is not None:
        if absolute_start.tzinfo is None:
            raise ValueError("Scenario start time must include a timezone for weather-series alignment")
        absolute_start = absolute_start.astimezone(timezone.utc)
        required_end = absolute_start + timedelta(minutes=duration_min)
        if start != absolute_start or end < required_end:
            raise ValueError("Weather series must start at the scenario's absolute start and cover the complete interval")
    elif (end - start).total_seconds() < duration_min * 60:
        raise ValueError("Weather series does not cover the complete simulation duration")
