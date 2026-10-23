"""Optional Osmium CLI acceleration; the Python reader remains the fallback."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from .osm_snapshots import LocalOSMError, atomic_json, digest, file_lock, read_json

EXPRESSIONS = {
    "roads": "w/highway",
    "buildings": "nwr/building",
    "water": "nwr/emergency=fire_hydrant,water_tank,fire_water_pond",
    "stations": "nwr/amenity=fire_station",
}


def executable():
    return shutil.which(os.getenv("OSMIUM_TOOL", "osmium"))


def _run(arguments, check_cancel):
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=errors)
        try:
            while True:
                check_cancel()
                try:
                    code = process.wait(timeout=.25)
                    break
                except subprocess.TimeoutExpired:
                    continue
            check_cancel()
            if code:
                errors.seek(0)
                raise LocalOSMError("Native OSM extraction failed: " + errors.read(2000).decode(errors="replace"))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def _artifact(target, identity, build, check_cancel):
    with file_lock(target.with_suffix(".lock"), check_cancel):
        marker = read_json(target.with_suffix(".json"), {})
        try:
            if (marker.get("identity") == identity and target.stat().st_size == marker["size"]
                    and digest(target, check_cancel=check_cancel) == marker["sha256"]):
                return target
        except (OSError, KeyError):
            pass
        temporary = target.with_suffix(f".{uuid4().hex}.osm.pbf")
        try:
            build(temporary)
            check_cancel()
            checksum = digest(temporary, check_cancel=check_cancel)
            os.replace(temporary, target)
            atomic_json(target.with_suffix(".json"), {"identity": identity, "size": target.stat().st_size,
                                                     "sha256": checksum})
        finally:
            temporary.unlink(missing_ok=True)
        return target


def subset(cache: Path, snapshot: dict, kind: str, polygon, check_cancel):
    tool = executable()
    if not tool:
        return None
    # Filter country data once per dataset before extracting geographic areas.
    # This avoids pulling country boundaries or whole public-transport networks
    # into an extract when completing relation members. Referenced tags remain
    # intact (the CLI's --remove-tags option is deliberately not used).
    from shapely.geometry import shape
    paths = []
    for row in snapshot["files"]:
        if not shape(row["coverage"]).intersects(polygon):
            continue
        root = cache / "osm-native-v1" / snapshot["id"]
        root.mkdir(parents=True, exist_ok=True)
        raw = cache / "osm-extracts-v1" / snapshot["id"] / f"{row['region']}.osm.pbf"
        filtered = root / f"{kind}-{row['region']}.osm.pbf"
        identity = f"1|{row['sha256']}|{EXPRESSIONS[kind]}"

        def filter_file(destination):
            if shutil.disk_usage(root).free < row["size"] + 256 * 1024**2:
                raise LocalOSMError("Insufficient storage for accelerated local extraction", "insufficient_disk_space")
            _run([tool, "tags-filter", str(raw), EXPRESSIONS[kind], "-o", str(destination)], check_cancel)

        _artifact(filtered, identity, filter_file, check_cancel)
        bounds = ",".join(str(value) for value in polygon.bounds)
        area_key = hashlib.sha256(f"{identity}|{bounds}".encode()).hexdigest()
        area = root / f"area-{area_key}.osm.pbf"

        def extract_file(destination):
            _run([tool, "extract", "--strategy=smart", "--option=types=any", "--bbox=" + bounds,
                  str(filtered), "-o", str(destination)], check_cancel)

        _artifact(area, area_key, extract_file, check_cancel)
        paths.append(area)
    return paths
