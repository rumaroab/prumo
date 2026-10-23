# PRUMO

A fire-aware mobility decision workspace. A coordinator can compare two water-source choices for one tanker under the same completed fire simulation. The result evaluates the full refill trip—outbound travel, filling, return and delivery—and distinguishes feasible, infeasible and insufficient-data outcomes. Modelled exposure never changes an operational road closure record.

Prepared scenarios now open at `/scenarios/{id}/decisions`. The former coordination workspace remains under **Outras ferramentas** and historical planning pages stay read-only. The default comparison changes only the water source; departure, tanker, demand and fire stay shared. A saved comparison preserves its inputs, fire run, road revision, route geometry and timed stages. Scrubbing playback does not recalculate it.

## Quick start from a fresh checkout

Use a terminal on macOS or Linux; Windows users need WSL. Install these prerequisites first:

- [Git](https://git-scm.com/downloads) to clone the repository and the optional Cell2Fire source.
- [Node.js](https://nodejs.org/en/download) 22.12 or newer with npm; use an LTS release.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for Python dependencies. The project requires Python 3.12; [uv downloads it automatically](https://docs.astral.sh/uv/guides/install-python/) if a compatible installation is missing.
- A C compiler: the pinned `pyretechnics` Python dependency builds native extensions during installation. On macOS, run `xcode-select --install`; on Debian/Ubuntu or WSL, run `sudo apt-get update` followed by `sudo apt-get install build-essential`. Other Linux distributions need their equivalent development tools.

Clone this repository using its GitHub **Code** button, open a terminal in the cloned folder, and run:

```bash
./start.sh
```

The filename is `start.sh`, without a leading dot. The script installs the locked Python and frontend dependencies, builds the interface, and starts PRUMO at <http://127.0.0.1:8000>. The application creates its local database and illustrative preview data and starts its simulation worker automatically. Keep the terminal open; press **Ctrl+C** to stop. Dependency installation needs internet access on the first run.

Create an occurrence, place its fire start, and prepare the area. Preparation downloads terrain and map data; the first country-map download is approximately **1.9 GB**, with additional storage needed for caches and prepared areas. MTT is available from the Python installation. Cell2Fire needs the separate [native engine setup](#cell2fire).

`start.sh` does **not** install system tools, compile Cell2Fire, download scenario maps in advance, or calculate the hackathon examples. A fresh checkout has no saved scenarios, runs, or comparisons; follow the demonstration steps below to create them. The first launch can show an empty scenario list.

Local databases, downloaded maps, simulations, public demo builds, videos, and everything under `outputs/` are excluded from Git. Source presets in `data/presets/` are included. Re-running `start.sh` refreshes dependencies and the frontend build while retaining your database and saved results.

If startup fails:

- **Missing tool or unsupported Node.js:** install the prerequisites above, reopen the terminal, and retry.
- **Permission denied:** run `chmod +x start.sh`, then `./start.sh`.
- **Port 8000 is busy:** run `FIRELINE_PORT=8001 ./start.sh` and open <http://127.0.0.1:8001>.
- **Cell2Fire is unavailable:** complete its native setup, or select MTT for a new simulation.

## Hackathon demonstration

After the first startup has installed the dependencies, stop the app with **Ctrl+C** and complete the [Cell2Fire setup](#cell2fire). From the repository root, fetch the Guimarães road graph and calculate the two examples:

```bash
uv run --locked python -m backend.scripts.prepare_roads
uv run --locked python -m backend.scripts.seed_decision_demo
./start.sh
```

Road preparation needs internet access and writes `data/prepared/roads.graphml`. The seed uses that graph and the patched Cell2Fire binary to generate both fire runs, their comparisons, and access assessments; this can take several minutes. The graph is fetched from current OpenStreetMap data, so results can differ from an earlier demonstration. Open **Comparar decisões** in either generated scenario.

The seed upgrades the two scenarios in place and keeps existing saved comparisons, assessments and fire runs. Make an integrity-checked SQLite backup before upgrading a database that contains work you need to retain. For a clean demonstration database, stop the application and run `.venv/bin/python -m backend.scripts.reset_and_seed_pt`; this backs up the old database first.

The two fictional exercises are:

- **Abastecer antes de perder o acesso · Cell2Fire**: one ignition, 40 km/h constant wind, low moisture and a four-hour horizon. The nearby 250 L/min source has five minutes of setup. At minute 15 it misses its filling window; the 900 L/min alternative delivers 3,000 L at minute 31.51 with 6.66 minutes remaining after the ten-minute lead time. Departing at minute 25 requires a detour and leaves 1.34 minutes of margin.
- **Duas ignições, um corredor em disputa · MTT**: 45 km/h constant wind, low moisture, and ignitions at minutes 0 and 25. Both default choices work at minute 18; at minute 28 the municipal-source trip is infeasible. The proposed closure removes one reception option for the northern origin and adds a detour for the campus origin, while another origin retains its earliest journey.

Each scenario has three individually selectable tankers (3,000/5,000/10,000 L), four sources, four population origins, two reception access points and one delivery sector. Source pairs, vehicle profiles and the two departures produce **72 saved water comparisons and 72 associated access assessments** across both exercises. Shared sources have no queue or stock depletion across alternatives. The source with no flow observation stays explicitly unknown. The 4,000 L reserve has a fictional access limit of 12 t and 2.3 m, so the compact tanker can use it while larger profiles cannot.

The road geometry comes from the cached OpenStreetMap package. The bounded corridor's clearance assumptions are enumerated in `exercise-road-assumptions.json` inside the immutable exercise area package; original road files are retained. Terrain, fuels, operational locations, stock, flow and vehicle profiles are fictional. MTT remains experimental, and these complementary exercises do not compare engine accuracy or predict suppression outcomes.

Warnings retain structured evidence, the affected stage, scenario-relative times, route geometry and provenance. The interface displays the exposure limit after the configured lead time, offers map/time navigation, and distinguishes lost reception options from loss of all assessed access.

The **Dados** panel downloads a UTF-8 CSV template for unit and vehicle snapshots. Preview reports row errors before use. Imported units exist only in the planning draft and the saved comparison snapshot; they never update operational units or dispatch a journey. Tank capacity, initial water and pump flow are required for a full-trip calculation, while vehicle dimensions are optional. Current source flow and stock must be entered as observations or explicit exercise assumptions; historical reservoir capacity is not current stock.

The public replay is a standalone static site containing the two calculated examples and fictional operational inputs. Build it with `npm --prefix frontend run build:public` and `.venv/bin/python -m backend.scripts.package_public_demo`; serve `public_demo_site/dist` as static files. It lets visitors choose a tanker and any two sources, switch the prepared departure and closure variants, scrub minute-by-minute fire playback and inspect explanations. Population results and road geometry are shared within the bundle. The basemap can be switched off to inspect the bundled geometry alone. Arbitrary inputs, uploads and simulation runs remain in the supervised application. The site bundles roads and fire footprints so the comparison remains legible if basemap tiles fail.

Public-data integration includes Fogos.pt scenario import and prepared terrain, roads and water candidates. Vendor command-system connectors are future work.

The legacy mobility and mission-management sections below document retained tools and records. See [consolidation and engine adapter guide](docs/CONSOLIDATION.md).

## Using the application

First-time preparation opens the single-engine simulation setup. When the run completes, open **Comparar decisões** to choose a tanker and two water sources. The fire result remains available under **Simulação**; the modeled fire never changes operational road status or route eligibility.

The local default keeps the no-login development workflow; a controlled multi-user deployment enables shared mode and HTTPS. See [Mobility pilot deployment and exercise](docs/MOBILITY_PILOT.md).

The Fire Analysis viewer retains its 2D map and timeline for modeled results. Former Water Routing, Decision Support, and exercise URLs open the read-only planning archive.

Startup reopens saved scenarios and registers the Guimarães examples when their road graph and engine inputs are available. New scenarios use a guided flow: place one or more timed fire starts, choose resource and fire-area coverage, prepare the public data, review discovered resources, and open the workspace. The basemap and preparation of a new area need internet access; saved area packages and results do not.

## Location-based scenarios

New scenario preparation supports mainland Portugal and stores an immutable, versioned area package under `data/areas/`. The default resource search is 25 km around the incident center, with 10 km and 50 km choices. Fire grids default to 30 m cells; 20 m, 15 m, and 10 m options expose progressively smaller permitted fire margins and live cell-count estimates. Landscapes above one million cells require explicit acknowledgement, non-30 m grids stop at two million cells, and every grid stops at three million cells. Roads receive an additional 5 km routing margin.

Required landscape inputs come from Copernicus DEM GLO-30 and ESA WorldCover 2021 v200. OpenStreetMap supplies roads, building footprints, water candidates, and fire-station candidates; the ICNF water service supplies additional historical water records. Terrain or road failure stops preparation. Building and resource-source failures are retained as a visible partial-data result. Downloads and prepared packages are cached, while each scenario and simulation run retains its selected package identity.

Use **Area coverage and data** inside an existing scenario after moving fire starts beyond the prepared grid, changing the search center, or increasing a radius. Earlier results remain linked to their original package. A result warns when simulated fire reaches the model boundary.

## Fogos.pt integration

Fogos.pt is an optional, additive scenario source. Configure the backend process before startup; the key is used only by the server and is never returned to the browser:

```bash
export FOGOS_API_KEY="your-issued-key"
export FOGOS_USER_AGENT="PRUMO/0.1 contact@example.org"
./start.sh
```

**New scenario → Import from Fogos.pt** searches active incidents or historical dates, saves an immutable source snapshot, and creates an ordinary unprepared scenario with one reported fire start at minute zero. The reported start time is retained as an absolute reconstruction anchor. Manual creation remains the default and unchanged. Only rural-fire incidents within mainland Portugal coverage are eligible; a missing source coordinate must be placed manually before creation.

Each reported terrestrial vehicle and aircraft also creates one provisional vehicle and one linked operational unit, in the same database transaction as the incident import. Default names are `Viatura terrestre 01` / `Unidade terrestre 01` and `Aeronave 01` / `Unidade aérea 01`. Inventories show terrestrial and aerial groups separately. Missing counts remain unknown, zero counts create no assets, and personnel totals do not invent individual crews. Source incident, snapshot, category and sequence remain attached to each generated record. Duplicate import requests do not duplicate assets.

Imported units start unavailable until a dispatcher confirms their availability; their location, organisation, vehicle specifications and capabilities are not inferred. Aircraft are retained in the inventory and excluded from road-route planning and road movements. Later source synchronization updates the reported aggregate groups and preserves local unit and vehicle records.

Imported scenario overviews show current source context, explicit weather actions, and opt-in background tracking. Tracking shares one persisted schedule per incident, collects details every five minutes, MTG evidence every ten minutes, and PyroCast hourly, with leases and failure backoff. External map layers start disabled and do not alter fire propagation, road exposure, containment, routing, teams, or mobility decisions.

Completed deterministic results can be compared with archived MTG perimeter snapshots in **Fire results → Compare with observations**. Comparisons use the immutable absolute run start, project both footprints into the run CRS, retain time assumptions and source snapshots, and report area agreement, areas, Hausdorff distance, and coverage clipping. MTG is coarse 2–4 km satellite evidence rather than a measured official burned perimeter; PyroCast remains a separately labelled external model scenario. Locally available perimeter history begins when tracking starts—historical incident search does not provide past MTG archives retroactively.

## Multiple fire starts

A scenario contains one or more named ignition points, each with an integer start minute. MTT and the locally patched Cell2Fire runtime support simultaneous and delayed starts in one shared simulation state. If an earlier fire reaches a later ignition cell first, the earlier arrival is retained. Optional external engines remain limited to one start at minute zero and are disabled for incompatible scenarios.

The pinned Cell2Fire source includes the local `scheduled-ignitions-v1+timed-firebreaks-v1` extensions. Rebuild it after pulling source changes:

```bash
cd vendor/C2F-W/Cell2Fire
make -B -f makefile.macos
```

A full rebuild is necessary after native header changes. The macOS makefile now includes header dependencies. The moisture setting is passed explicitly to the native coefficient scenario (low: 1, moderate: 3, high: 4), an exercise adapter assumption recorded in the command provenance.

The adapter checks the binary for that extension before accepting multiple or delayed starts and records the patch and binary hash in run provenance.

## Team allocation and timed containment

Decision Support can store priority levels, response teams, and closed containment tasks. It can suggest defensive rings around threatened assets or accept a line drawn on the map. Fast ranking uses the selected immutable fire result to compare access, withdrawal, combined production time, deployment limits, and a configurable completion lead. These results are logistics rankings and do not change or predict the fire outcome.

Saved plans can be compared through deterministic MTT or Cell2Fire intervention runs. A containment line becomes an impermeable one-cell barrier only after the assigned teams complete the whole task. Cells reached before that time remain breached. Each comparison reuses the selected result as its control, runs up to four configurations as child jobs, and reports asset arrivals, burned area, line breaches, effort, and runtime. This barrier rule is an explicit demonstration assumption rather than a calibrated suppression model.

## Development

For backend development with automatic reload, run from the repository root:

```bash
uv sync --locked
npm --prefix frontend ci --include=dev
npm --prefix frontend run build
uv run --locked uvicorn backend.app.main:app --reload
```

The API starts and stops its worker automatically; do not launch a second worker for normal local development.

For frontend development, use `npm run dev` in `frontend/`; it proxies `/api` to port 8000.

## Prepare real inputs

Area preparation reads roads, buildings, water points and fire stations from
local Geofabrik OpenStreetMap extracts for Portugal and Spain. Spain preserves
the complete selected coverage near the border. The first use installs the
extracts automatically (approximately 1.9 GB, plus working storage); install or
refresh them explicitly with:

```bash
uv run python -m backend.scripts.sync_osm_extracts
```

For faster first-time processing of large country files, install the optional
Osmium CLI (`brew install osmium-tool` on macOS, `apt install osmium-tool` on
Debian/Ubuntu). When available on `PATH`, or selected with `OSMIUM_TOOL`, it
creates reference-complete local subsets before Python processes them. The
Python reader remains available if the accelerator is absent or fails. Its
validated intermediate files are reused from `data/source-cache/osm-native-v1`.

Versioned snapshots live in `data/source-cache/osm-extracts-v1`. Matching dated
country files are downloaded sequentially and validated against the provider's
checksums and PBF source timestamps before the active snapshot changes.
Interrupted downloads resume where supported. A preparation pins its snapshot,
so a refresh cannot change an exercise midway through processing. Refreshes are
checked in the background when preparation starts and the last successful check
is older than seven days; a failed refresh retains the last valid maps. Failed
refresh checks are spaced at least one hour apart. Retained snapshots are not
automatically deleted because unfinished preparations may still reference them.
OSM attribution and source dates are recorded with the datasets.

Only the selected area is processed into XML, retaining complete ways, referenced
node tags and building relation members. Validated local query results are
reused from `data/source-cache/osm-queries-v1`, keyed by snapshot, bounds, filter
and processing version. OSMnx constructs the combined directed road graph once,
with the same routing and graph boundary buffers as before.

If local files are unusable or cannot cover the entire query, the application
falls back to Overpass without shrinking the area. The fallback uses sequential
tiles smaller than 10 × 10 km. One HTTP client handles up to four attempts per
tile, 10 s connect / 45 s read timeouts, 10/20/40 s backoff with jitter, and
`Retry-After` support. Retry budgets are five minutes per tile and ten minutes
per dataset. `OVERPASS_URL` still overrides the primary endpoint; the configured
secondary endpoint is retained. OSMnx reads the downloaded data locally.

Validated Overpass responses are cached for 24 hours in `data/source-cache/overpass-v1`.
Completed datasets and checksums are kept in
`data/preparations/.checkpoints-v1`, so **Tentar novamente** resumes a failed
preparation without rebuilding valid terrain or downloading completed tiles.
Local dataset checkpoints are tied to the pinned snapshot and processing
version, and remain reusable while their validated source snapshot exists;
Overpass dataset checkpoints retain their 24-hour policy.
Cancellation and interruption retain these checkpoints. Published area packages
are immutable; roads must be complete before publication, while unavailable
optional catalogs are reported as partial. First-time map installation, terrain,
Fogos.pt and ICNF still require their upstream services; having local OSM maps
does not make the whole platform offline. Preparation responses retain their
existing fields and add optional `source_progress` (provider, phase, region,
downloaded and total bytes). Dataset `osm_provenance` records snapshot identity,
actual data date, processing version and stale/failed-refresh warnings. Existing
`failure_code`, `retryable`, `retry_at` and `tile_progress` remain compatible.

The standalone legacy preparation commands below remain separate from the
application's resumable preparation pipeline.

Download a DGT terrain GeoTIFF and an ESA WorldCover 2021 GeoTIFF that cover the configured area, then run:

```bash
uv run python -m backend.scripts.prepare_landscape \
  --elevation data/source/elevation.tif \
  --land-cover data/source/worldcover.tif

uv run python -m backend.scripts.prepare_roads
uv run python -m backend.scripts.prepare_water_points
uv run python -m backend.scripts.prepare_fire_stations
```

The roads command downloads the configured bounds through OpenStreetMap's Overpass API, automatically subdivides large areas, keeps motor roads and vehicle tracks, and writes both the directed topology and display segments. The water-point command caches explicitly tagged firefighting hydrants, tanks, and ponds as unverified candidates. The fire-station command caches `amenity=fire_station` records within the configured area, removes adjacent duplicate building records with the same name, and retains their source links. A scenario copies imported points so later web changes cannot silently alter an exercise. Manual point placement remains available when a catalog is empty or preparation is offline.

Decision Support checks every road at its estimated traversal time. A segment is excluded when a reported closure is active or simulated fire exposure occurs before the vehicle finishes crossing it. Route summaries show estimated time and distance, reasons the ordinary fastest route was rejected, shared fire-exposed segments, missing coverage, and a separately timed withdrawal journey. Road-class speeds are planning estimates rather than emergency-response measurements, and “no modelled conflict” is not a safety determination.

The **Water Routing → Water sources and bases → Guimarães water presets** picker includes 44 locations from [ICNF's Rede de Pontos de Água](https://sigservices.icnf.pt/server/rest/services/BDG/Pontos_agua/MapServer/0), retrieved on 19 October 2026 and bundled in `data/presets/guimaraes-water-points.geojson`. Add individual presets or all remaining points; repeated imports do not duplicate them. The configured map and model boundary includes every preset with roughly one kilometre of padding, and **Show all points on map** fits the current scenario points.

The ICNF records are historical (the four DFCI reservoir records were updated in June 2018; many other records have no update date). Imports retain the recorded condition, ownership, access class, source link, date, and reported capacity where supplied. Their verification is **Reported** and current availability stays **Unknown**, including records historically marked operational, dry, or damaged. Raw ICNF attributes remain in each preset's `source_properties`; minor legacy encoding errors in display names are corrected. This is not a complete current municipal inventory.

Refresh the bundled presets with `uv run python -m backend.scripts.prepare_water_presets`, or rebuild offline with `--input path/to/icnf-response.geojson`. A failed refresh leaves the existing file intact. Optional OSM preparation cannot erase the bundled presets.

Preparation writes atomically to `data/prepared/`. The editable WorldCover-to-fuel mapping is in `config.json`. It is a demonstration assumption, not a Portuguese fuel calibration.

## Scenario workspaces

Use the scenario list at `/scenarios` to search, create, open, or delete scenarios. New scenarios save their name, description, and start time first; location, coverage, and public-data preparation can then be completed from the scenario overview. Active simulations must finish or be cancelled before their scenario can be deleted. Deleted scenarios and their results are unavailable through the app; records and output files are retained internally, and deleted bundled examples stay deleted after restart. Renaming preserves existing result snapshots.

Each top-level simulation run is presented as an experiment. The scenario overview lists single simulations, ensembles, engine comparisons, and containment comparisons together. Experiment names and notes can be edited without changing the immutable simulation snapshot. Experiments can be cancelled while active and removed from history after completion; results used by a retained containment comparison remain protected until that comparison is removed.

Scenario edits autosave with revision checks. A simulation run records an immutable snapshot of the scenario revision that created it, while response bases, water points, assets, hazards, and custom points remain scenario context and do not affect fire propagation. Selecting an old result never replaces current inputs; the Simulation workspace identifies changes to model inputs. Editing operational points does not mark a fire simulation as stale. The operational tools retain the input run ID in their URL, identify its original revision, and read its immutable model settings rather than the current simulation draft.

## Cell2Fire

Cell2Fire is optional for new scenarios and required for the two calculated hackathon examples. `start.sh` does not build it.

The local setup uses C2F-W revision `83b0c3bc31fa9bd500ff11400671e48bdc98a237`. The downloaded vendor tree is excluded from Git; its local ignition, containment, and build changes are preserved in `patches/cell2fire.patch`.

On macOS, install the Xcode command-line tools (`xcode-select --install`) and [Homebrew](https://brew.sh/) if needed, then install the native libraries:

```bash
brew install boost libomp libtiff catch2
```

On Debian/Ubuntu or WSL, install the build prerequisites:

```bash
sudo apt-get update
sudo apt-get install build-essential libboost-random-dev libtiff-dev catch2
```

From the repository root, clone the pinned source and apply the patch once:

```bash
git clone https://github.com/fire2a/C2F-W.git vendor/C2F-W
git -C vendor/C2F-W checkout 83b0c3bc31fa9bd500ff11400671e48bdc98a237
git -C vendor/C2F-W apply ../../patches/cell2fire.patch
```

Build with the command for your platform:

```bash
# macOS
make -C vendor/C2F-W/Cell2Fire -f makefile.macos

# Linux / WSL
make -C vendor/C2F-W/Cell2Fire
```

The adapter finds that binary automatically; `CELL2FIRE_BIN` can override it. It stages common landscape inputs, invokes the native program, captures its log, and derives cell arrival minutes from Cell2Fire's message output.

## Additional engines

The active application bundles MTT and Cell2Fire. FARSITE, QUIC-Fire, and WRF-SFIRE are archived integrations; the commands below describe their retained runtime tooling and do not enable them in the current registry. Installing a supported adapter is described in [the engine adapter guide](docs/CONSOLIDATION.md). The interface never substitutes one model for another.

Build the pinned Linux FARSITE image with:

```bash
docker build --platform linux/amd64 -t forest-fire-farsite:4537d60 containers/farsite
```

The adapter writes a five-theme surface-fire LCP, ignition shapefile, metric RAWS weather, and a FARSITE command file. It disables crown fire and spotting because the demonstration landscape has no calibrated canopy inputs. Native five-minute perimeters are converted to the shared arrival grid.

QUIC-Fire is closed source and must be obtained separately. Build the open wrapper, then point the platform at the licensed executable:

```bash
docker build --platform linux/amd64 -t forest-fire-quicfire:0.11 containers/quicfire
export QUICFIRE_BIN=/absolute/path/to/QUICFire
```

The wrapper uses `quicfire-tools` 0.11.0, writes a spatial synthetic 3D fuel field from the demonstration crosswalk, runs the mounted executable, and converts the first one-percent fuel-density reduction into arrival minutes.

WRF-SFIRE defaults to a remote Slurm runner because its compiler, MPI, NetCDF, and compute requirements are site-specific:

```bash
export SLURM_HOST=user@cluster.example
export SLURM_BASE_DIR=/scratch/user/forest-fire
export SLURM_PARTITION=compute
```

The remote installation must provide `/opt/forest-fire/run-wrf-sfire` and produce `wrf_sfire-native/arrival.npy` or `fire_output.npz`. For a validated local image, set `WRF_SFIRE_RUNNER=local-docker` and `WRF_SFIRE_IMAGE`; the image must contain `/opt/wrf-sfire/bin/prepare-and-run`. The supplied Dockerfile pins the source but deliberately does not claim a portable WRF build.

Generate the bundled MTT/Cell2Fire examples plus each configured optional-engine example explicitly:

```bash
uv run python -m backend.scripts.generate_engine_demos
```

Heavyweight engines are never run during application startup.

## Weather series

The advanced controls accept a UTF-8 CSV with this exact header:

```csv
timestamp,wind_speed_kmh,wind_direction_deg,temperature_c,relative_humidity_pct,precipitation_mm
2026-08-01T12:00:00Z,20,270,30,35,0
2026-08-01T13:00:00Z,24,280,31,30,0
```

Timestamps must include a timezone, increase strictly, have gaps no larger than six hours, and cover the complete run. The original file, normalized observations, checksum, and validation metadata are retained under `data/weather/`.

## Ensembles and comparisons

- **Uncertainty ensemble** runs three or nine deterministic wind variations through one engine and reports P10/P50/P90 arrival plus exposure probability.
- **Engine comparison** runs the same shared scenario through two or more available engines, keeps their maps separate, and compares burned area, exposed roads, runtime metadata, and temporal resolution.

Ensemble members are ordinary child jobs with their own logs and provenance. A parent becomes `partial` when at least one member succeeds and another fails. Runs can be cancelled from the interface; container jobs receive a graceful Docker stop and Slurm jobs use their recorded scheduler identity.

Runner concurrency can be tuned with `IN_PROCESS_CONCURRENCY`, `LOCAL_RUNNER_CONCURRENCY`, and `SLURM_RUNNER_CONCURRENCY`. Submitted Slurm job IDs are stored immediately, so the worker can resume polling after a restart without storing SSH credentials in SQLite.

## Tests

```bash
UV_CACHE_DIR=.uv-cache uv run python -m unittest discover -s tests -v
UV_CACHE_DIR=.uv-cache uv run python -m unittest discover -s backend/tests -v
npm --prefix frontend run build
```

The normal suite exercises parser fixtures, weather validation, runner cancellation/timeouts, partial ensembles, and comparison rules without requiring external simulators. After configuring all site-specific runtimes, run the opt-in end-to-end checks with:

```bash
RUN_EXTERNAL_ENGINE_SMOKES=1 UV_CACHE_DIR=.uv-cache uv run python -m unittest tests.test_external_smoke -v
```

Each unavailable engine is skipped with its precise Docker, licence, or Slurm setup reason.

## Meaning of results

- **Affected now** means simulated first exposure is at or before the selected scenario minute.
- **Within X minutes** means first exposure is after the selected minute and no later than that future time.
- **Not reached** means the road was not reached within this run's time horizon.
- **Unknown** means required landscape coverage is missing.

The default 30 m proximity buffer is a visible scenario assumption. Results do not infer police closures, visibility, smoke, traffic, or vehicle safety.

## Presentation material

A slide-ready explanation and comparison of all implemented engines is available in [ENGINE_PRESENTATION.md](ENGINE_PRESENTATION.md).
# Mission-based exercise workspace

The application now separates fire modelling from operational exercises:

1. Define an exercise situation and reference time.
2. Record scenario-specific units, vehicles, water sources, and important locations.
3. Define police, fire-service, civil-protection, transport, logistics, water-supply, or containment missions.
4. Build a manual response plan or request up to four deterministic candidate allocations.
5. Compare as many as four frozen plan versions against one immutable situation snapshot and up to three fire forecasts.
6. Rehearse a selected plan in an isolated simulated run.

Open an exercise at `/scenarios/{id}/map`. The primary workspace pages are Map, Missions, Plans & Experiments, Resources, and Updates. Existing `/mobility`, fire-result, water-planning, decision-support, and shared-brief links remain available for legacy workflows. Fire simulations are labelled separately and remain available through **Fire analysis**.

This section describes the retained mission-based workspace. The current primary workflow is **Comparar decisões**, as described above.

Exercise APIs are scenario-scoped under:

- `/api/scenarios/{id}/exercise-situation`
- `/api/scenarios/{id}/situation-snapshots`
- `/api/scenarios/{id}/missions`
- `/api/scenarios/{id}/response-plans`
- `/api/scenarios/{id}/response-experiments`
- `/api/scenarios/{id}/exercise-runs`

Exercise playback never calls live movement, crew-action, notification, or observation endpoints. Injected road, source, and availability changes are stored only in the exercise run.

## Synthetic exercise fixture

Create the offline demonstration with:

```bash
.venv/bin/python -m backend.scripts.seed_exercise_demo
```

The fixture is explicitly synthetic and includes police, firefighting, and civil-protection resources, two water sources with different stock/flow behaviour, constrained roads, competing missions, and two response plans. It does not fetch external data.

## Database migration and restore

Exercise tables are created by an additive, idempotent migration recorded in `schema_migrations`. Existing scenario IDs, fire runs, mobility records, briefs, and stored artifacts are not rewritten.

Before deploying a build that enables the workspace, stop the application and copy `data/platform.sqlite3` to a timestamped backup. Start the application once and verify the `2026-10-exercise-workspace-v1` entry in `schema_migrations`. To restore, stop the application, retain the failed database for diagnosis, replace `data/platform.sqlite3` with the backup, and start the previous application build. Fire-result files under `data/runs` are independent of the SQLite migration and should be retained.
