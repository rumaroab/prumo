"""Atomic, resumable Geofabrik snapshots, independent of prepared area packages."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import osmium
import requests
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union

VERSION = 1
REFRESH_SECONDS = 7 * 86400
REGIONS = ("portugal", "spain")
BASE_URL = "https://download.geofabrik.de/europe"
_refreshing: set[str] = set()
_refresh_lock = threading.Lock()


class LocalOSMError(RuntimeError):
    def __init__(self, message: str, code="osm_extract_invalid"):
        super().__init__(message)
        self.code, self.retryable = code, True


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    try:
        with temporary.open("w") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


@contextmanager
def file_lock(path: Path, check_cancel=lambda: None, waiting=lambda: None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        while True:
            check_cancel()
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                waiting()
                time.sleep(.25)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def digest(path: Path, algorithm="sha256", check_cancel=lambda: None):
    result = hashlib.new(algorithm)
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            check_cancel()
            result.update(chunk)
    return result.hexdigest()


def parse_poly(content: str):
    """Geofabrik .poly rings include optional holes prefixed with '!'."""
    lines = iter(content.splitlines()[1:])
    shells, holes = [], []
    for line in lines:
        name = line.strip()
        if name == "END":
            break
        if not name:
            continue
        coordinates = []
        for line in lines:
            if line.strip() == "END":
                break
            coordinates.append(tuple(map(float, line.split())))
        polygon = Polygon(coordinates)
        if polygon.is_empty or not polygon.is_valid:
            raise LocalOSMError("Invalid extract coverage polygon")
        (holes if name.startswith("!") else shells).append(polygon)
    result = unary_union(shells).difference(unary_union(holes))
    if result.is_empty or not result.is_valid:
        raise LocalOSMError("Missing extract coverage polygon")
    return result


def validate_pbf(path: Path, check_cancel=lambda: None):
    with osmium.io.Reader(str(path)) as reader:
        stamp = reader.header().get("osmosis_replication_timestamp")
    if not stamp:
        raise LocalOSMError("OSM extract has no source timestamp")
    datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    counts = {"n": 0, "w": 0, "r": 0}
    for index, item in enumerate(osmium.FileProcessor(path)):
        if index % 65536 == 0:
            check_cancel()
        counts[item.type_str()] += 1
    check_cancel()
    if not counts["n"] or not counts["w"]:
        raise LocalOSMError("OSM extract is empty or has no roads")
    return stamp


class SnapshotStore:
    def __init__(self, root: Path, *, check_cancel=lambda: None, progress=lambda **kw: None,
                 session=None):
        self.root, self.check_cancel, self.progress = root, check_cancel, progress
        self.session = session or requests.Session()
        self._validated: dict[str, tuple] = {}

    def close(self):
        self.session.close()

    def current(self):
        pointer = read_json(self.root / "current.json", {})
        return self.load(pointer.get("snapshot_id"))

    def load(self, snapshot_id: str | None):
        if not snapshot_id or not re.fullmatch(r"[a-f0-9]{24}", snapshot_id):
            return None
        folder = self.root / snapshot_id
        manifest = read_json(folder / "manifest.json", {})
        try:
            if (manifest["version"] != VERSION or manifest["id"] != snapshot_id
                    or {row["region"] for row in manifest["files"]} != set(REGIONS)):
                return None
            for row in manifest["files"]:
                path = folder / f"{row['region']}.osm.pbf"
                stat = path.stat()
                signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, row["sha256"])
                if stat.st_size != row["size"]:
                    return None
                if self._validated.get(str(path)) != signature:
                    if digest(path, check_cancel=self.check_cancel) != row["sha256"]:
                        return None
                    self._validated[str(path)] = signature
            coverage = shape(manifest["coverage"])
            if coverage.is_empty or not coverage.is_valid:
                return None
            return manifest
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _emit(self, phase, region=None, downloaded_bytes=None, total_bytes=None):
        self.progress(source_progress={"provider": "local", "phase": phase, "region": region,
                                      "downloaded_bytes": downloaded_bytes, "total_bytes": total_bytes})

    def _text(self, url):
        for attempt in range(3):
            self.check_cancel()
            try:
                with self.session.get(url, timeout=(10, 45)) as response:
                    response.raise_for_status()
                    self.check_cancel()
                    return response.text
            except requests.RequestException as error:
                if attempt == 2 or (error.response is not None and 400 <= error.response.status_code < 500
                                    and error.response.status_code != 429):
                    raise
                for _ in range(4 * (attempt + 1)):
                    self.check_cancel()
                    time.sleep(.25)

    def _source_urls(self):
        # Dated files are immutable and have published checksums. Choose a
        # common day before downloading, avoiding mixed country revisions and
        # mutable '-latest' aliases changing in the middle of a resumed stream.
        dates = []
        for region in REGIONS:
            page = self._text(f"{BASE_URL}/{region}.html")
            dates.append(set(re.findall(rf'{region}-(\d{{6}})\.osm\.pbf\.md5', page)))
        common = set.intersection(*dates)
        if not common:
            raise LocalOSMError("No matching dated Portugal and Spain extracts are available")
        date = max(common)
        return {region: f"{BASE_URL}/{region}-{date}.osm.pbf" for region in REGIONS}

    def _download(self, url: str, region: str, md5: str):
        partials = self.root / ".downloads"
        partials.mkdir(parents=True, exist_ok=True)
        target = partials / f"{region}-{md5}.osm.pbf"
        if target.exists() and digest(target, "md5", self.check_cancel) == md5:
            return target
        part = target.with_suffix(".part")
        deadline = time.monotonic() + 3600
        for attempt in range(3):
            self.check_cancel()
            offset = part.stat().st_size if part.exists() else 0
            if offset and digest(part, "md5", self.check_cancel) == md5:
                os.replace(part, target)
                return target
            try:
                headers = {"User-Agent": "fire-road-exposure/0.4", "Accept-Encoding": "identity"}
                if offset:
                    headers["Range"] = f"bytes={offset}-"
                with self.session.get(url, stream=True, timeout=(10, 45), headers=headers) as response:
                    response.raise_for_status()
                    if response.status_code == 206:
                        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                        if not match or int(match[1]) != offset:
                            part.unlink(missing_ok=True)
                            raise LocalOSMError("Invalid resumed extract response")
                        total = int(match[3])
                    else:
                        offset = 0
                        total = int(response.headers.get("Content-Length", 0)) or None
                    required = max(0, (total or 2_000_000_000) - offset) + 256 * 1024**2
                    if shutil.disk_usage(self.root).free < required:
                        raise LocalOSMError("Insufficient storage for local map download", "insufficient_disk_space")
                    last_update, received = 0.0, offset
                    with part.open("ab" if offset else "wb") as stream:
                        for chunk in response.iter_content(1024 * 1024):
                            self.check_cancel()
                            if time.monotonic() > deadline:
                                raise LocalOSMError("Local map download time limit reached", "osm_extract_unavailable")
                            if chunk:
                                stream.write(chunk)
                                received += len(chunk)
                            if time.monotonic() - last_update >= .5:
                                self._emit("downloading", region, received, total)
                                last_update = time.monotonic()
                        stream.flush()
                        os.fsync(stream.fileno())
                    if total is not None and received != total:
                        raise LocalOSMError("Incomplete local map download")
                self._emit("validating", region, received, total)
                if digest(part, "md5", self.check_cancel) != md5:
                    part.unlink(missing_ok=True)
                    raise LocalOSMError("Local map download checksum mismatch")
                os.replace(part, target)
                return target
            except (requests.RequestException, LocalOSMError) as error:
                if getattr(error, "code", None) == "insufficient_disk_space" or attempt == 2:
                    raise
                # A rejected Range is retried as a clean download, never appended.
                if isinstance(error, requests.HTTPError) and error.response.status_code == 416:
                    part.unlink(missing_ok=True)
                for _ in range((attempt + 1) * 20):
                    self.check_cancel()
                    time.sleep(.25)
        raise LocalOSMError("Local map download failed")

    def sync(self, *, force=False):
        self.root.mkdir(parents=True, exist_ok=True)
        started = time.time()
        with file_lock(self.root / ".sync.lock", self.check_cancel,
                       lambda: self._emit("waiting")):
            pointer = read_json(self.root / "current.json", {})
            current = self.current()
            # A concurrent synchronizer may already have completed this request.
            if current and (pointer.get("checked_at", 0) >= started or
                            (not force and time.time() - pointer.get("checked_at", 0) < REFRESH_SECONDS)):
                return current
            try:
                files, stamps, polygons, paths = [], set(), [], []
                urls = self._source_urls()
                for region in REGIONS:
                    url = urls[region]
                    checksum = self._text(url + ".md5").split()[0].lower()
                    if not re.fullmatch(r"[0-9a-f]{32}", checksum):
                        raise LocalOSMError("Invalid extract checksum response")
                    polygon = parse_poly(self._text(f"{BASE_URL}/{region}.poly"))
                    old = next((row for row in (current or {}).get("files", [])
                                if row["region"] == region and row["md5"] == checksum), None)
                    path = (self.root / current["id"] / f"{region}.osm.pbf" if old else
                            self._download(url, region, checksum))
                    self._emit("validating", region)
                    stamp = current["data_timestamp"] if old else validate_pbf(path, self.check_cancel)
                    stamps.add(stamp)
                    files.append({"region": region, "url": url, "md5": checksum,
                                  "sha256": old["sha256"] if old else digest(path, check_cancel=self.check_cancel),
                                  "size": path.stat().st_size, "coverage": mapping(polygon)})
                    polygons.append(polygon)
                    paths.append(path)
                if len(stamps) != 1:
                    raise LocalOSMError("Portugal and Spain extracts have different data timestamps; retry after the provider finishes updating")
                identity = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:24]
                manifest = {"version": VERSION, "id": identity, "data_timestamp": stamps.pop(),
                            "files": files, "coverage": mapping(unary_union(polygons)), "created_at": time.time()}
                folder = self.root / identity
                folder.mkdir(exist_ok=True)
                for row, path in zip(files, paths):
                    self.check_cancel()
                    destination = folder / f"{row['region']}.osm.pbf"
                    if path != destination:
                        # Hard links retain old snapshots and use no duplicate disk blocks.
                        temporary = destination.with_suffix(f".{uuid4().hex}.tmp")
                        os.link(path, temporary)
                        os.replace(temporary, destination)
                atomic_json(folder / "manifest.json", manifest)
                self.check_cancel()
                atomic_json(self.root / "current.json", {"snapshot_id": identity, "checked_at": time.time(),
                                                         "attempted_at": time.time(), "last_error": None})
                self._emit("ready")
                return manifest
            except Exception as error:
                self.check_cancel()  # User cancellation is not an upstream failure.
                atomic_json(self.root / "current.json", {**pointer, "attempted_at": time.time(),
                                                         "last_error": str(error)[:1000]})
                raise

    def refresh_in_background(self):
        pointer = read_json(self.root / "current.json", {})
        if (time.time() - pointer.get("checked_at", 0) < REFRESH_SECONDS or
                time.time() - pointer.get("attempted_at", 0) < 3600):
            return
        key = str(self.root.resolve())
        with _refresh_lock:
            if key in _refreshing:
                return
            _refreshing.add(key)

        def run():
            store = SnapshotStore(self.root)
            try:
                store.sync()
            except Exception:
                pass  # sync records the failure while retaining the active snapshot.
            finally:
                store.close()
                with _refresh_lock:
                    _refreshing.discard(key)

        threading.Thread(target=run, name="osm-snapshot-refresh", daemon=True).start()
