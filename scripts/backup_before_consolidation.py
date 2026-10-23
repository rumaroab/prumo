"""Gate a Fireline deployment on drained jobs, then back up SQLite and run artifacts."""

from __future__ import annotations

import argparse
import sqlite3
import tarfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "platform.sqlite3"
RUNS = ROOT / "data" / "runs"
ACTIVE = ("queued", "preparing", "submitted", "running", "postprocessing")


def backup(destination: Path) -> Path:
    if not DB.is_file():
        raise RuntimeError(f"Database not found: {DB}")
    with sqlite3.connect(DB) as source:
        placeholders = ",".join("?" for _ in ACTIVE)
        active = source.execute(f"SELECT id,status FROM runs WHERE status IN ({placeholders})", ACTIVE).fetchall()
        if active:
            raise RuntimeError(f"Drain {len(active)} active fire jobs before backup: {active[:5]}")
        for table in ("response_experiments",):
            if source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                count = source.execute(f"SELECT count(*) FROM {table} WHERE status IN ('queued','running')").fetchone()[0]
                if count:
                    raise RuntimeError(f"Drain {count} active {table} jobs before backup")
        destination.mkdir(parents=True, exist_ok=False)
        with sqlite3.connect(destination / DB.name) as target:
            source.backup(target)
    with tarfile.open(destination / "runs.tar.gz", "w:gz") as archive:
        if RUNS.exists():
            archive.add(RUNS, arcname="runs")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path,
                        default=ROOT / "data" / "backups" / datetime.now(UTC).strftime("consolidation-%Y%m%dT%H%M%SZ"))
    args = parser.parse_args()
    print(backup(args.destination))
