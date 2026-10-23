#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from quicfire_tools import SimulationInputs, SimulationOutputs
from quicfire_tools.utils import write_dat_file


source, output, binary = map(Path, sys.argv[1:4])
spec = json.loads((source / "run.json").read_text())
weather = json.loads((source / "weather.json").read_text())
ny, nx = spec["shape"]
cell = float(spec["cell_size_m"])
fuel_load = np.load(source / "fuel_load_kg_m2.npy")
fuel_depth = np.maximum(np.load(source / "fuel_depth_m.npy"), .1)
moisture = {"low": 5.0, "moderate": 10.0, "high": 18.0}.get(spec.get("moisture", "moderate"), 10.0)
dz = .25
fire_nz = max(1, min(20, int(np.ceil(float(fuel_depth.max()) / dz))))

deck = output / "deck"
deck.mkdir(parents=True, exist_ok=True)
simulation = SimulationInputs.create_simulation(
    nx=nx, ny=ny, fire_nz=fire_nz,
    wind_speed=max(.01, float(weather[0]["wind_speed_kmh"]) / 3.6),
    wind_direction=int(round(float(weather[0]["wind_direction_deg"]))) % 360,
    simulation_time=int(spec["duration_min"] * 60),
)
simulation.set_custom_simulation(fuel_density=True, fuel_moisture=True, fuel_height=True,
                                 ignition=False, topo=True, interpolate=False)
simulation.set_rectangle_ignition(x_min=spec["ignition_local_xy"][0], y_min=spec["ignition_local_xy"][1],
                                  x_length=max(cell, 2), y_length=max(cell, 2))
simulation.set_output_files(fuel_dens=True)
simulation.qu_simparams.dx = cell
simulation.qu_simparams.dy = cell
simulation.quic_fire.dz = dz
wind_times = [int(datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).timestamp()) for row in weather]
sensor_type = simulation.wind_sensors.sensor_array[0].__class__
simulation.wind_sensors.sensor_array = [sensor_type(
    name="sensor1", wind_times=wind_times,
    wind_speeds=[max(.01, float(row["wind_speed_kmh"]) / 3.6) for row in weather],
    wind_directions=[int(round(float(row["wind_direction_deg"]))) % 360 for row in weather],
    sensor_heights=6.1, x_location=1, y_location=1,
)]
simulation.qu_simparams.wind_times = wind_times
simulation.quic_fire.time_now = wind_times[0]
simulation.write_inputs(deck)

centers = (np.arange(fire_nz, dtype="float32") + .5)[:, None, None] * dz
occupied = centers < fuel_depth[None, :, :]
density = np.where(occupied, (fuel_load / fuel_depth)[None, :, :], 0).astype("float32")
write_dat_file(density, deck / "treesrhof.dat")
write_dat_file(np.full_like(density, moisture), deck / "treesmoist.dat")
write_dat_file(np.broadcast_to(fuel_depth, density.shape).astype("float32"), deck / "treesfueldepth.dat")
write_dat_file(np.load(source / "elevation_m.npy").astype("float32"), deck / "topo.dat")
shutil.copy2(binary, deck / "QUICFire")
(deck / "QUICFire").chmod(0o755)
subprocess.run(["./QUICFire"], cwd=deck, check=True)

outputs = SimulationOutputs(deck / "Output", fire_nz=fire_nz, ny=ny, nx=nx, dy=cell, dx=cell)
fuel = outputs.to_numpy("fuels-dens")
# Collapse every vertical fuel layer so first activity is detected anywhere in
# the fuel column rather than only in the lowest QUIC-Fire layer.
column_fuel = fuel.sum(axis=1)
initial = column_fuel[0]
arrival = np.full((ny, nx), np.nan, dtype="float32")
times = outputs.get_output("fuels-dens").times
for index, stamp in enumerate(times):
    burned = (initial > 0) & (column_fuel[index] < initial * .99) & ~np.isfinite(arrival)
    arrival[burned] = float(stamp) / 60
np.save(output / "arrival.npy", arrival)
