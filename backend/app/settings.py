from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SOURCE = DATA / "source"
PREPARED = DATA / "prepared"
AREAS = DATA / "areas"
PREPARATIONS = DATA / "preparations"
SOURCE_CACHE = DATA / "source-cache"
RUNS = DATA / "runs"
DEMO = DATA / "demo"
WEATHER = DATA / "weather"
DB = DATA / "platform.sqlite3"
FRONTEND = ROOT / "frontend" / "dist"
CONFIG = json.loads((ROOT / "config.json").read_text())


def ensure_dirs() -> None:
    for path in (DATA, SOURCE, PREPARED, AREAS, PREPARATIONS, SOURCE_CACHE, RUNS, DEMO, WEATHER):
        path.mkdir(parents=True, exist_ok=True)
