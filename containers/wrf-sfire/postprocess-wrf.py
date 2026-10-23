#!/usr/bin/env python3
"""Reduce native WRF-SFIRE NetCDF output to portable parser fixtures/artifacts."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import netCDF4
import numpy as np


output = Path(sys.argv[1])
files = sorted(output.glob("wrfout*"))
if not files:
    if (output / "arrival.npy").exists() or (output / "fire_output.npz").exists():
        raise SystemExit(0)
    raise SystemExit("WRF-SFIRE produced no wrfout, arrival.npy, or fire_output.npz")

lfn_frames: list[np.ndarray] = []
stamps: list[datetime] = []
optional: dict[str, list[np.ndarray]] = {"FIRE_AREA": [], "GRNHFX": [], "FIRE_HFX": []}
fxlat = fxlong = None
for path in files:
    with netCDF4.Dataset(path) as dataset:
        if "LFN" not in dataset.variables:
            continue
        lfn = np.asarray(dataset.variables["LFN"][:], dtype="float32")
        if lfn.ndim == 2:
            lfn = lfn[None, ...]
        lfn_frames.extend(lfn)
        raw_times = netCDF4.chartostring(dataset.variables["Times"][:])
        stamps.extend(datetime.strptime(str(value), "%Y-%m-%d_%H:%M:%S") for value in raw_times)
        if fxlat is None:
            fxlat = np.asarray(dataset.variables["FXLAT"][:], dtype="float32").squeeze()
            fxlong = np.asarray(dataset.variables["FXLONG"][:], dtype="float32").squeeze()
        for name in optional:
            if name in dataset.variables:
                optional[name].extend(np.asarray(dataset.variables[name][:], dtype="float32"))

if not lfn_frames or not stamps or fxlat is None or fxlong is None:
    raise SystemExit("WRF-SFIRE output is missing LFN, Times, FXLAT, or FXLONG")
origin = stamps[0]
times = np.asarray([(stamp - origin).total_seconds() / 60 for stamp in stamps], dtype="float32")
np.savez_compressed(output / "fire_output.npz", lfn=np.stack(lfn_frames), times_min=times,
                    fxlat=fxlat, fxlong=fxlong)
artifacts = {name.lower(): np.stack(values) for name, values in optional.items() if values}
if artifacts:
    np.savez_compressed(output / "optional_fire_outputs.npz", **artifacts)
