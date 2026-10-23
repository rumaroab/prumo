# Progress

## Current state

- Stage 0: complete — project layout, dependency manifests, model contracts, and documentation created.
- Stage 1: complete — responsive React/Leaflet map shell, controls, timeline, legend, and layer toggles implemented.
- Stage 2: complete — 6,337 display segments were extracted from live OpenStreetMap data for the configured Penha bounds. The cached graph preserves 2,858 nodes and 6,081 directed edges.
- Stage 3: complete in code — local raster preparation command aligns terrain/land cover at 30 m and records provenance. Real source rasters still need to be placed in `data/source/`.
- Stage 4: complete — C2F-W revision `83b0c3bc` downloaded and built locally; the adapter writes aligned inputs, runs the native engine, captures logs, and converts message output to arrival minutes.
- Stage 5: complete — raster-to-road exposure analysis supports 0 m or configured proximity buffers and preserves unknown coverage.
- Stage 6: complete — SQLite-backed jobs, separate worker, API, run progress, retained results, timeline, filters, and map interaction implemented.
- Stage 7: complete as an experimental Python engine — Pyretechnics surface-fire rates feed integrated, multi-bearing minimum-travel-time lattice links.
- Stage 8: complete — three standard Cell2Fire examples and three synthetic extreme MTT showcases are saved with one-command local startup. The extreme presets expose 212–323 road segments over 240 minutes.
- Scenario workspaces: complete — scenario URLs, revisioned autosave, immutable linked runs, and shared state now connect Simulation, Water Planning, and Decision Support.
- Operational points: complete for scenario context — response bases, water points, assets, hazards, and custom points can be placed, edited, moved, and removed. OpenStreetMap imports keep provenance and remain unverified.

## Exact next action

Run `./start.sh`, open `http://127.0.0.1:8000`, and inspect the Westward ridge scenario across all three tabs. For real terrain, fuel, roads, and water-point inputs, follow the preparation commands in `README.md`.

## Artifacts

- Runtime database: `data/platform.sqlite3`
- Prepared landscape: `data/prepared/landscape.npz` and `landscape.json`
- OpenStreetMap source extract: `data/source/penha-roads.osm`
- Prepared roads: `data/prepared/roads.geojson`, `roads.graphml`, and `roads.json`
- Prepared water-point catalog: `data/prepared/water-points.geojson` when fetched
- Run results: `data/runs/<run-id>/`
- Bundled demo: `data/demo/`

## Known blockers and limits

- DGT terrain and ESA WorldCover files are not bundled; licensing/provenance stays with downloaded source data.
- C2F-W source and build output are kept in ignored `vendor/C2F-W`; a fresh clone needs the documented build step.
- The Python MTT engine is experimental and does not claim FlamMap equivalence.
