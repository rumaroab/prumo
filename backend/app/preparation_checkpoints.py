"""Validated dataset checkpoints, separate from immutable published packages."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import osmnx as ox

FILES = {
    "landscape": ("landscape.npz", "landscape.json"),
    "roads": ("roads.graphml", "roads.geojson", "roads.json"),
    "buildings": ("buildings.geojson",),
    "water_points": ("water-points.geojson",),
    "fire_stations": ("fire-stations.geojson",),
}
VERSION = 2


def validate(directory: Path, dataset: str):
    for filename in FILES[dataset]:
        path = directory / filename
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Incomplete {dataset}: missing {filename}")
        if path.suffix in {".json", ".geojson"}:
            value = json.loads(path.read_text())
            if path.suffix == ".geojson" and not isinstance(value.get("features"), list):
                raise ValueError(f"Invalid catalog: {filename}")
    if dataset == "landscape":
        with np.load(directory / "landscape.npz", allow_pickle=False) as arrays:
            shape = arrays["fuel"].shape
            if len(shape) != 2 or not arrays["coverage"].any():
                raise ValueError("Incomplete terrain coverage")
            for key in ("elevation", "slope", "aspect", "coverage"):
                if arrays[key].shape != shape:
                    raise ValueError("Inconsistent terrain dimensions")
    elif dataset == "roads":
        graph = ox.load_graphml(directory / "roads.graphml")
        if not graph.number_of_edges():
            raise ValueError("Prepared road network is empty")
        roads = json.loads((directory / "roads.geojson").read_text())
        metadata = json.loads((directory / "roads.json").read_text())
        if not roads["features"] or metadata["count"] != len(roads["features"]):
            raise ValueError("Incomplete road geometry")
        if metadata["revision"] != hashlib.sha256((directory / "roads.geojson").read_bytes()).hexdigest()[:16]:
            raise ValueError("Road geometry revision mismatch")


def restore(directory: Path, dataset: str) -> dict | None:
    try:
        marker = json.loads((directory / f"{dataset}.checkpoint.json").read_text())
        fetched_at = min(marker["saved_at"], marker["metadata"].get("osm_fetched_at", marker["saved_at"]))
        provenance = marker["metadata"].get("osm_provenance", {})
        local = provenance.get("provider") == "local"
        if marker["version"] not in {1, VERSION} or (local and marker["version"] != VERSION):
            return None
        if dataset != "landscape" and not local and not 0 <= time.time()-fetched_at < 86400:
            return None
        if any(hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest
               for name, digest in marker["files"].items()):
            return None
        if set(marker["files"]) != set(FILES[dataset]):
            return None
        validate(directory, dataset)
        return marker["metadata"]
    except Exception:
        # A checkpoint is only an optimisation: unreadable archives, XML and
        # stale formats must rebuild instead of making recovery impossible.
        return None


def save(directory: Path, dataset: str, metadata: dict):
    validate(directory, dataset)
    marker = {"version": VERSION, "saved_at": time.time(), "metadata": metadata,
              "files": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                        for name in FILES[dataset]}}
    target = directory / f"{dataset}.checkpoint.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(marker))
    os.replace(temporary, target)
