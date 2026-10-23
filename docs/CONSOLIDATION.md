# Mobility consolidation

## Operational workflow

A prepared incident opens in Mobility. Dispatch assigns a vehicle-linked available unit only after a server route preview. The preview signature covers journey coordinates and departure time, the selected route, vehicle profile, prepared road revision, and current road reports. Assignment and route revision recalculate the route server-side. A changed preview returns HTTP 409; unavailable routes cannot be assigned.

Crew road reports may include observed coordinates. Crew reports start unmatched. Dispatch matches a prepared road segment and direction before confirming; unmatched reports remain visible in Updates and do not alter routing. Matched pending block or restriction reports are treated conservatively while awaiting review. Confirmed road changes flag affected movement briefs.

Water source cards show the recorded status, observation time, access notes, and pending reports. Crew reports are reviewed by dispatch. Confirmation writes an audited source status; dismissal retains the report. The operational workspace makes no queue or delivery-time predictions.

Fire overlays are optional and labeled modeled with engine, run time, and minute. They do not participate in road eligibility or route calculation. Historical timed planning closures are not converted to confirmed mobility restrictions.

## Engine adapter contract

The active registry bundles `mtt` and `cell2fire`. An installed package can expose an adapter via a Python entry point in the `fireline.engines` group. The entry point name is the adapter ID and must match its descriptor ID. The adapter provides `descriptor`, `available() -> (bool, str)`, `validate(scenario)`, and `simulate(landscape, scenario, output) -> SimulationResult`. Use `backend.app.engines.contract.EngineDescriptor` for the descriptor; declare weather modes, ignition support, `execution_pool` (`thread` or `process`), and a `concurrency_key`. The worker limits each concurrency key with `FIRELINE_ENGINE_CONCURRENCY_<KEY>`.

Example package metadata:

```toml
[project.entry-points."fireline.engines"]
sample = "sample_fire.adapter:SampleEngine"
```

Install the package in the same Python environment as the API and worker, then restart both. `/api/engines` reports available and failed adapters. Duplicate IDs are rejected without replacing a bundled engine. New run creation checks runtime availability and scenario compatibility. Before publishing, the worker validates output identity, grid shape and coverage, affine transform, CRS, time resolution, and provenance. Saved results from unregistered engines continue to load from their stored artifacts. Source for the three retired adapters remains in `backend/app/engines/archived_external.py` and is excluded from the active registry.

## Archive and rollout

Old planning URLs open a read-only archive of saved inputs and results. Their GET APIs remain available; retired mutations return HTTP 410 and a Mobility link. New fire jobs are single-engine only. Historical ensembles and comparisons remain readable.

Before deploying, stop admission of old jobs, wait for active fire and response experiments to finish, and run:

```bash
python3 scripts/backup_before_consolidation.py
```

The script refuses to back up while those jobs are active and creates a SQLite backup and compressed run-artifact archive. Restore both together if rollback is needed. Do not automatically convert planning closures to live restrictions.
