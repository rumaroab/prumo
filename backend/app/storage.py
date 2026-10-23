from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from .models import (
    RunMode,
    RunRecord,
    Scenario,
    ScenarioDefinition,
    ScenarioPatch,
    ScenarioPoint,
    ScenarioWorkspace,
)
from .settings import DB, ensure_dirs


class ScenarioConflictError(RuntimeError):
    pass


class ScenarioBusyError(RuntimeError):
    pass


class RunConflictError(RuntimeError):
    pass


class RunBusyError(RuntimeError):
    pass


class RunDependencyError(RuntimeError):
    def __init__(self, name: str):
        self.name = name
        super().__init__(name)


def now() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def connect():
    ensure_dirs()
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_db() -> None:
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY, applied_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS scenarios (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL,
            definition TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        if "deleted_at" not in {row[1] for row in db.execute("PRAGMA table_info(scenarios)")}:
            db.execute("ALTER TABLE scenarios ADD COLUMN deleted_at TEXT")
        db.execute("""CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, stage TEXT NOT NULL,
            progress INTEGER NOT NULL, scenario TEXT NOT NULL, error TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, demo INTEGER DEFAULT 0
        )""")
        existing = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
        additions = {
            "mode": "TEXT NOT NULL DEFAULT 'single'", "parent_id": "TEXT", "member_index": "INTEGER",
            "runner": "TEXT", "external_job_id": "TEXT", "expected_members": "INTEGER", "ensemble": "TEXT",
            "scenario_id": "TEXT", "scenario_revision": "INTEGER",
            "intervention": "TEXT",
            "area_package_id": "TEXT",
            "name": "TEXT", "notes": "TEXT NOT NULL DEFAULT ''",
            "metadata_revision": "INTEGER NOT NULL DEFAULT 1", "deleted_at": "TEXT",
            "run_context": "TEXT",
        }
        for column, definition in additions.items():
            if column not in existing:
                db.execute(f"ALTER TABLE runs ADD COLUMN {column} {definition}")
        _migrate_scenarios(db)
        db.execute("""UPDATE runs SET name=COALESCE(NULLIF(name, ''),
                    json_extract(scenario, '$.name'), 'Experiment')""")
        db.execute("CREATE INDEX IF NOT EXISTS runs_scenario_id ON runs(scenario_id, created_at DESC)")
        db.execute("""CREATE TABLE IF NOT EXISTS external_incidents (
            provider TEXT NOT NULL, incident_id TEXT NOT NULL, source_url TEXT,
            latest_snapshot_id TEXT, last_success_at TEXT, next_poll_at TEXT,
            last_error TEXT, terminal INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(provider, incident_id)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS external_snapshots (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, incident_id TEXT NOT NULL,
            product_type TEXT NOT NULL, checksum TEXT NOT NULL, raw_payload TEXT NOT NULL,
            normalized TEXT NOT NULL, source_url TEXT, retrieved_at TEXT NOT NULL,
            observed_at TEXT, quality_notes TEXT NOT NULL DEFAULT '[]',
            UNIQUE(provider, incident_id, product_type, checksum)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS external_fetches (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, incident_id TEXT NOT NULL,
            product_type TEXT NOT NULL, snapshot_id TEXT, fetched_at TEXT NOT NULL,
            status TEXT NOT NULL, error TEXT
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS scenario_external_incidents (
            scenario_id TEXT PRIMARY KEY, provider TEXT NOT NULL, incident_id TEXT NOT NULL,
            import_snapshot_id TEXT NOT NULL, original_longitude REAL, original_latitude REAL,
            linked_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS scenario_import_requests (
            request_key TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS tracking_subscriptions (
            provider TEXT NOT NULL, incident_id TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
            next_details_at TEXT, next_perimeter_at TEXT, next_simulation_at TEXT,
            lease_until TEXT, last_error TEXT, failure_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(provider, incident_id)
        )""")
        tracking_columns = {row[1] for row in db.execute("PRAGMA table_info(tracking_subscriptions)")}
        if "failure_count" not in tracking_columns:
            db.execute("ALTER TABLE tracking_subscriptions ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0")
        db.execute("""CREATE TABLE IF NOT EXISTS observation_evaluations (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL, snapshot_ids TEXT NOT NULL,
            observed_at TEXT NOT NULL, time_basis TEXT NOT NULL, assumption TEXT,
            metrics TEXT NOT NULL, metric_version TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS external_snapshots_incident ON external_snapshots(provider,incident_id,product_type,retrieved_at)")
        db.execute("CREATE INDEX IF NOT EXISTS observation_evaluations_run ON observation_evaluations(run_id,created_at)")
        _init_exercise_schema(db)
        db.execute("INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES (?,?)",
                   ("2026-10-exercise-workspace-v1", now()))
        db.execute("PRAGMA user_version=6")
        db.execute("""UPDATE runs SET status='interrupted', stage='interrupted'
                    WHERE status IN ('preparing','running','postprocessing') AND external_job_id IS NULL
                    AND deleted_at IS NULL
                    AND (mode='single' OR parent_id IS NOT NULL)""")


def _init_exercise_schema(db: sqlite3.Connection) -> None:
    """Create additive exercise tables without changing historical fire records."""
    db.executescript("""
    CREATE TABLE IF NOT EXISTS exercise_situations (
      scenario_id TEXT PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS situation_snapshots (
      id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, payload TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS situation_snapshots_scenario
      ON situation_snapshots(scenario_id,created_at DESC);
    CREATE TABLE IF NOT EXISTS exercise_missions (
      id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, payload TEXT NOT NULL,
      revision INTEGER NOT NULL, archived_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS exercise_missions_scenario
      ON exercise_missions(scenario_id,archived_at,created_at);
    CREATE TABLE IF NOT EXISTS response_plans (
      id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, payload TEXT NOT NULL,
      revision INTEGER NOT NULL, archived_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS response_plans_scenario
      ON response_plans(scenario_id,archived_at,created_at);
    CREATE TABLE IF NOT EXISTS response_experiments (
      id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
      status TEXT NOT NULL, progress INTEGER NOT NULL, stage TEXT NOT NULL,
      request TEXT NOT NULL, result TEXT, error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS response_experiments_scenario
      ON response_experiments(scenario_id,created_at DESC);
    CREATE TABLE IF NOT EXISTS exercise_runs (
      id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
      plan_id TEXT NOT NULL, plan_revision INTEGER NOT NULL, state TEXT NOT NULL,
      speed REAL NOT NULL, elapsed_min REAL NOT NULL, payload TEXT NOT NULL,
      revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS exercise_runs_scenario
      ON exercise_runs(scenario_id,created_at DESC);
    CREATE TABLE IF NOT EXISTS exercise_events (
      id TEXT PRIMARY KEY, run_id TEXT NOT NULL, scenario_id TEXT NOT NULL,
      kind TEXT NOT NULL, offset_min REAL NOT NULL, payload TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS exercise_events_run ON exercise_events(run_id,offset_min,created_at);
    CREATE TABLE IF NOT EXISTS exercise_idempotency (
      scenario_id TEXT NOT NULL, action TEXT NOT NULL, request_key TEXT NOT NULL,
      record_id TEXT NOT NULL, created_at TEXT NOT NULL,
      PRIMARY KEY(scenario_id,action,request_key)
    );
    CREATE TABLE IF NOT EXISTS exercise_artifact_refs (
      scenario_id TEXT NOT NULL, source_scenario_id TEXT NOT NULL, run_id TEXT NOT NULL,
      created_at TEXT NOT NULL, PRIMARY KEY(scenario_id,run_id)
    );
    """)
    db.execute("""UPDATE response_experiments SET status='interrupted',stage='interrupted',updated_at=?
                  WHERE status='running'""", (now(),))


def _migrate_scenarios(db: sqlite3.Connection) -> None:
    rows = db.execute("SELECT * FROM runs WHERE parent_id IS NULL AND scenario_id IS NULL ORDER BY created_at").fetchall()
    for row in rows:
        simulation = Scenario.model_validate_json(row["scenario"])
        scenario_id = f"scenario-{row['id']}"
        definition = ScenarioDefinition(simulation=simulation, points=_demo_points(row["id"]))
        db.execute("""INSERT OR IGNORE INTO scenarios
            (id,name,revision,definition,created_at,updated_at) VALUES (?,?,?,?,?,?)""",
            (scenario_id, simulation.name, 1, definition.model_dump_json(), row["created_at"], row["updated_at"]))
        db.execute("UPDATE runs SET scenario_id=?, scenario_revision=1 WHERE id=? OR parent_id=?",
                   (scenario_id, row["id"], row["id"]))


def _demo_points(run_id: str) -> list[ScenarioPoint]:
    if run_id != "penha-east":
        return []
    return [
        ScenarioPoint(id="demo-base", kind="response_base", name="Base de resposta · exercício",
                      coordinates=(-8.2894, 41.4258), source="demo", notes="Ponto fictício de demonstração"),
        ScenarioPoint(id="demo-water", kind="water_point", name="Ponto de água · exercício",
                      coordinates=(-8.2784, 41.4327), source="demo", notes="Ponto fictício, não verificado"),
        ScenarioPoint(id="demo-asset", kind="asset", name="Local prioritário · exercício",
                      coordinates=(-8.2672, 41.4371), source="demo", notes="Ponto fictício de demonstração"),
        ScenarioPoint(id="demo-hazard", kind="hazard", name="Condicionamento de acesso · exercício",
                      coordinates=(-8.2821, 41.4237), source="demo", notes="Ponto fictício de demonstração"),
    ]


def create_scenario(simulation: Scenario, *, name: str | None = None, description: str = "",
                    area_id: str = "penha-guimaraes", start_time=None,
                    resource_center=None, resource_radius_km: int = 25, fire_margin_km: int = 5,
                    cell_size_m: int = 30,
                    area_package_id: str | None = None,
                    points: list[ScenarioPoint] | None = None, closures=None, teams=None,
                    containment_tasks=None, allocation_plans=None, resource_groups=None,
                    scenario_id: str | None = None, fogos_snapshot_id: str | None = None,
                    import_request_id: str | None = None,
                    scenario_kind: str = "legacy", source_scenario_id: str | None = None) -> ScenarioWorkspace:
    scenario_id = scenario_id or uuid4().hex[:12]
    stamp = now()
    selected_name = name or simulation.name
    simulation = simulation.model_copy(update={"name": selected_name})
    definition = ScenarioDefinition(description=description, area_id=area_id, start_time=start_time,
                                    scenario_kind=scenario_kind, source_scenario_id=source_scenario_id,
                                    resource_center=resource_center or simulation.ignition,
                                    resource_radius_km=resource_radius_km, fire_margin_km=fire_margin_km,
                                    cell_size_m=cell_size_m,
                                    area_package_id=area_package_id,
                                    simulation=simulation, points=points or [], closures=closures or [],
                                    teams=teams or [], containment_tasks=containment_tasks or [],
                                    allocation_plans=allocation_plans or [],
                                    resource_groups=resource_groups or [])
    if fogos_snapshot_id:
        from .mobility_storage import init_mobility_db
        init_mobility_db()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if fogos_snapshot_id and import_request_id:
            previous = db.execute("SELECT scenario_id FROM scenario_import_requests WHERE request_key=?",
                                  (import_request_id,)).fetchone()
            if previous:
                return get_scenario(previous["scenario_id"])
        snapshot = None
        if fogos_snapshot_id:
            snapshot = db.execute("""SELECT * FROM external_snapshots
                                   WHERE id=? AND provider='fogos.pt' AND product_type='incident'""",
                                  (fogos_snapshot_id,)).fetchone()
            if not snapshot:
                raise ValueError("Fogos.pt import snapshot is unavailable")
            source_values = json.loads(snapshot["normalized"])
            if not source_values.get("importable"):
                raise ValueError("This Fogos.pt incident is not eligible for mainland rural-fire simulation")
            lon, lat = definition.simulation.ignition
            if not definition.start_time:
                raise ValueError("Fogos.pt imports require the reported incident start time")
            if len(definition.simulation.ignitions) != 1 or definition.simulation.ignitions[0].start_min != 0:
                raise ValueError("Fogos.pt imports require one reported ignition at minute zero")
            if not (-9.7 <= lon <= -6.0 and 36.8 <= lat <= 42.3):
                raise ValueError("Confirm a location within mainland Portugal before importing")
            if tuple(definition.resource_center or ()) != tuple(definition.simulation.ignition):
                raise ValueError("The imported scenario resource centre must match the confirmed fire location")
            from .fogos_resources import reconcile_resource_groups
            seeded_groups, _ = reconcile_resource_groups(definition.resource_groups, {
                **dict(snapshot), "normalized": source_values,
            })
            definition = definition.model_copy(update={"resource_groups": seeded_groups})
        db.execute("""INSERT INTO scenarios
            (id,name,revision,definition,created_at,updated_at) VALUES (?,?,?,?,?,?)""",
            (scenario_id, selected_name, 1, definition.model_dump_json(), stamp, stamp))
        if snapshot:
            normalized = source_values
            coordinates = normalized.get("coordinates") or [None, None]
            db.execute("""INSERT INTO scenario_external_incidents
                (scenario_id,provider,incident_id,import_snapshot_id,original_longitude,original_latitude,linked_at)
                VALUES (?,?,?,?,?,?,?)""",
                (scenario_id, "fogos.pt", snapshot["incident_id"], fogos_snapshot_id,
                 coordinates[0], coordinates[1], stamp))
            if import_request_id:
                db.execute("""INSERT INTO scenario_import_requests(request_key,scenario_id,created_at)
                              VALUES (?,?,?)""", (import_request_id, scenario_id, stamp))
            from .fogos_resources import import_mobility_inventory
            import_mobility_inventory(db, scenario_id, {**dict(snapshot), "normalized": source_values}, stamp)
    return get_scenario(scenario_id)


def get_scenario(scenario_id: str) -> ScenarioWorkspace:
    with connect() as db:
        row = db.execute("SELECT * FROM scenarios WHERE id=? AND deleted_at IS NULL", (scenario_id,)).fetchone()
    if not row:
        raise KeyError(scenario_id)
    return _workspace(row)


def list_scenarios() -> list[ScenarioWorkspace]:
    with connect() as db:
        rows = db.execute("SELECT * FROM scenarios WHERE deleted_at IS NULL ORDER BY created_at").fetchall()
    return [_workspace(row) for row in rows]


def update_scenario(scenario_id: str, patch: ScenarioPatch) -> ScenarioWorkspace:
    simulation = patch.simulation.model_copy(update={"name": patch.name})
    with connect() as db:
        current = db.execute("SELECT definition FROM scenarios WHERE id=? AND deleted_at IS NULL",
                             (scenario_id,)).fetchone()
        previous = ScenarioDefinition.model_validate_json(current["definition"]) if current else None
        definition = ScenarioDefinition(description=patch.description, area_id=patch.area_id,
                                        scenario_kind=patch.scenario_kind,
                                        source_scenario_id=patch.source_scenario_id,
                                        start_time=patch.start_time, resource_center=patch.resource_center,
                                        resource_radius_km=patch.resource_radius_km,
                                        fire_margin_km=patch.fire_margin_km,
                                        cell_size_m=patch.cell_size_m,
                                        area_package_id=patch.area_package_id,
                                        simulation=simulation, points=patch.points,
                                        closures=patch.closures, teams=patch.teams,
                                        resource_groups=(patch.resource_groups if patch.resource_groups is not None
                                                         else previous.resource_groups if previous else []),
                                        containment_tasks=patch.containment_tasks,
                                        allocation_plans=patch.allocation_plans)
        if current:
            removed_points = {point.id for point in previous.points} - {point.id for point in patch.points}
            if removed_points:
                active_plans = db.execute("SELECT payload FROM response_plans WHERE scenario_id=? AND archived_at IS NULL",
                                          (scenario_id,)).fetchall()
                if any(assignment.get("source_point_id") in removed_points for row in active_plans
                       for assignment in json.loads(row["payload"]).get("assignments", [])):
                    raise ScenarioBusyError("Reassign response plans before removing a referenced resource")
                active_runs = db.execute("SELECT payload FROM exercise_runs WHERE scenario_id=? AND state IN ('paused','running')",
                                         (scenario_id,)).fetchall()
                if any(assignment.get("source_point_id") in removed_points for row in active_runs
                       for assignment in json.loads(row["payload"]).get("plan", {}).get("assignments", [])):
                    raise ScenarioBusyError("Reassign or complete the active rehearsal before removing this resource")
        cursor = db.execute("""UPDATE scenarios SET name=?, revision=revision+1, definition=?, updated_at=?
            WHERE id=? AND revision=? AND deleted_at IS NULL""",
            (patch.name, definition.model_dump_json(), now(), scenario_id, patch.expected_revision))
        if cursor.rowcount == 0:
            exists = db.execute("SELECT 1 FROM scenarios WHERE id=? AND deleted_at IS NULL", (scenario_id,)).fetchone()
            if not exists:
                raise KeyError(scenario_id)
            raise ScenarioConflictError(scenario_id)
    return get_scenario(scenario_id)


def rename_scenario(scenario_id: str, name: str, expected_revision: int) -> ScenarioWorkspace:
    workspace = get_scenario(scenario_id)
    return update_scenario(scenario_id, ScenarioPatch(
        **{**workspace.model_dump(), "name": name, "expected_revision": expected_revision}))


def delete_scenario(scenario_id: str, expected_revision: int) -> None:
    # Retain a tombstone and result files so startup cannot resurrect bundled examples.
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT revision FROM scenarios WHERE id=? AND deleted_at IS NULL",
                         (scenario_id,)).fetchone()
        if not row:
            raise KeyError(scenario_id)
        if row["revision"] != expected_revision:
            raise ScenarioConflictError(scenario_id)
        active = db.execute("""SELECT 1 FROM runs WHERE scenario_id=?
            AND status IN ('queued','preparing','submitted','running','postprocessing') LIMIT 1""",
            (scenario_id,)).fetchone()
        if active:
            raise ScenarioBusyError(scenario_id)
        exercise_ref = db.execute("""SELECT r.scenario_id FROM exercise_artifact_refs r
                                  JOIN scenarios s ON s.id=r.scenario_id AND s.deleted_at IS NULL
                                  WHERE r.source_scenario_id=? LIMIT 1""", (scenario_id,)).fetchone()
        if exercise_ref:
            raise ScenarioBusyError(f"Scenario is retained by exercise {exercise_ref['scenario_id']}")
        link = db.execute("SELECT provider,incident_id FROM scenario_external_incidents WHERE scenario_id=?",
                          (scenario_id,)).fetchone()
        db.execute("UPDATE scenarios SET deleted_at=?, updated_at=?, revision=revision+1 WHERE id=?",
                   (now(), now(), scenario_id))
        if link:
            remaining = db.execute("""SELECT 1 FROM scenario_external_incidents l
                JOIN scenarios s ON s.id=l.scenario_id AND s.deleted_at IS NULL
                WHERE l.provider=? AND l.incident_id=? LIMIT 1""",
                (link["provider"], link["incident_id"])).fetchone()
            if not remaining:
                db.execute("""UPDATE tracking_subscriptions SET enabled=0,lease_until=NULL
                              WHERE provider=? AND incident_id=?""",
                           (link["provider"], link["incident_id"]))


def _workspace(row: sqlite3.Row) -> ScenarioWorkspace:
    definition = ScenarioDefinition.model_validate_json(row["definition"])
    with connect() as db:
        linked = db.execute("""SELECT l.*,i.source_url,i.latest_snapshot_id,i.last_success_at,
                              i.next_poll_at,i.last_error,t.enabled AS tracking_enabled,
                              t.next_details_at AS tracking_next_attempt,t.failure_count AS tracking_failures
                              FROM scenario_external_incidents l
                              LEFT JOIN external_incidents i ON i.provider=l.provider AND i.incident_id=l.incident_id
                              LEFT JOIN tracking_subscriptions t ON t.provider=l.provider AND t.incident_id=l.incident_id
                              WHERE l.scenario_id=?""", (row["id"],)).fetchone()
    external = dict(linked) if linked else None
    if external:
        external["tracking_enabled"] = bool(external.get("tracking_enabled"))
    return ScenarioWorkspace(id=row["id"], name=row["name"], revision=row["revision"],
                             created_at=row["created_at"], updated_at=row["updated_at"],
                             setup_complete=bool(definition.area_package_id or definition.area_id == "penha-guimaraes"),
                             external_incident=external,
                             **definition.model_dump())


def create_run(scenario: Scenario, *, demo: bool = False, run_id: str | None = None,
               mode: RunMode = "single", parent_id: str | None = None, member_index: int | None = None,
               expected_members: int | None = None, ensemble: dict | None = None,
               scenario_id: str | None = None, scenario_revision: int | None = None,
               area_package_id: str | None = None, intervention: dict | None = None,
               name: str | None = None, notes: str = "", run_context: dict | None = None) -> RunRecord:
    run_id = run_id or uuid4().hex[:12]
    stamp = now()
    status = "ready" if demo else "queued"
    stage = "ready" if demo else "queued"
    progress = 100 if demo else 0
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if demo:
            existing_demo = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if existing_demo:
                return _record(existing_demo)
        if parent_id and scenario_id is None:
            parent = db.execute("SELECT scenario_id,scenario_revision,area_package_id,run_context FROM runs WHERE id=?", (parent_id,)).fetchone()
            if parent:
                scenario_id, scenario_revision = parent["scenario_id"], parent["scenario_revision"]
                area_package_id = parent["area_package_id"]
                run_context = run_context or (json.loads(parent["run_context"]) if parent["run_context"] else None)
        if scenario_id is None:
            existing = db.execute("SELECT scenario_id,scenario_revision FROM runs WHERE id=?", (run_id,)).fetchone()
            if existing:
                scenario_id, scenario_revision = existing["scenario_id"], existing["scenario_revision"]
        if scenario_id is not None and not db.execute(
            "SELECT 1 FROM scenarios WHERE id=? AND deleted_at IS NULL", (scenario_id,)
        ).fetchone():
            raise KeyError(scenario_id)
        if area_package_id is None and scenario_id is not None:
            scenario_row = db.execute("SELECT definition FROM scenarios WHERE id=?", (scenario_id,)).fetchone()
            if scenario_row:
                area_package_id = ScenarioDefinition.model_validate_json(scenario_row["definition"]).area_package_id
        if run_context is None and scenario_id is not None:
            scenario_row = db.execute("SELECT definition FROM scenarios WHERE id=?", (scenario_id,)).fetchone()
            link = db.execute("SELECT * FROM scenario_external_incidents WHERE scenario_id=?", (scenario_id,)).fetchone()
            definition = ScenarioDefinition.model_validate_json(scenario_row["definition"]) if scenario_row else None
            external_context = None
            if link:
                imported = db.execute("""SELECT id,provider,incident_id,product_type,checksum,normalized,
                    source_url,retrieved_at,observed_at,quality_notes FROM external_snapshots WHERE id=?""",
                    (link["import_snapshot_id"],)).fetchone()
                external_context = {**dict(link), "import_snapshot": {
                    **dict(imported), "normalized": json.loads(imported["normalized"]),
                    "quality_notes": json.loads(imported["quality_notes"]),
                }} if imported else dict(link)
            weather_context = scenario.weather_source.model_dump()
            if weather_context.get("kind") == "series":
                from .weather import list_weather_series
                weather_context["series"] = next((item for item in list_weather_series()
                                                   if item["id"] == weather_context.get("id")), None)
            run_context = {
                "scenario_start_time": definition.start_time.isoformat() if definition and definition.start_time else None,
                "weather_source": weather_context,
                "external_incident": external_context,
            }
        if scenario_id is None:
            scenario_id = f"scenario-{run_id}" if demo else uuid4().hex[:12]
            scenario_revision = 1
            definition = ScenarioDefinition(simulation=scenario, points=_demo_points(run_id))
            db.execute("""INSERT INTO scenarios
                (id,name,revision,definition,created_at,updated_at) VALUES (?,?,?,?,?,?)""",
                (scenario_id, scenario.name, 1, definition.model_dump_json(), stamp, stamp))
        db.execute("""INSERT OR REPLACE INTO runs
            (id,status,stage,progress,scenario,error,created_at,updated_at,demo,mode,parent_id,member_index,
             runner,external_job_id,expected_members,ensemble,scenario_id,scenario_revision,area_package_id,intervention,
             name,notes,metadata_revision,deleted_at,run_context)
            VALUES (?,?,?,?,?,NULL,?,?,?, ?,?,?,NULL,NULL,?,?,?,?,?,?, ?,?,1,NULL,?)""",
            (run_id, status, stage, progress, scenario.model_dump_json(), stamp, stamp, int(demo), mode,
             parent_id, member_index, expected_members, json.dumps(ensemble) if ensemble else None,
             scenario_id, scenario_revision, area_package_id,
             json.dumps(intervention) if intervention else None, name or scenario.name, notes,
             json.dumps(run_context) if run_context else None))
    return get_run(run_id)


def update_run(run_id: str, **values) -> None:
    allowed = {"status", "stage", "progress", "error", "runner", "external_job_id", "expected_members"}
    values = {key: value for key, value in values.items() if key in allowed}
    values["updated_at"] = now()
    sql = ", ".join(f"{key}=?" for key in values)
    with connect() as db:
        db.execute(f"UPDATE runs SET {sql} WHERE id=?", (*values.values(), run_id))


def get_run(run_id: str) -> RunRecord:
    with connect() as db:
        row = db.execute("SELECT * FROM runs WHERE id=? AND deleted_at IS NULL", (run_id,)).fetchone()
    if not row:
        raise KeyError(run_id)
    return _record(row)


def list_runs(*, include_children: bool = False) -> list[RunRecord]:
    with connect() as db:
        where = "" if include_children else "AND parent_id IS NULL"
        rows = db.execute(f"""SELECT runs.* FROM runs JOIN scenarios ON scenarios.id=runs.scenario_id
            WHERE scenarios.deleted_at IS NULL AND runs.deleted_at IS NULL {where} ORDER BY demo DESC, runs.created_at DESC""").fetchall()
    return [_record(row) for row in rows]


def scenario_runs(scenario_id: str) -> list[RunRecord]:
    with connect() as db:
        rows = db.execute("""SELECT * FROM runs WHERE scenario_id=? AND parent_id IS NULL AND deleted_at IS NULL
            ORDER BY created_at DESC""", (scenario_id,)).fetchall()
    return [_record(row) for row in rows]


def child_runs(parent_id: str) -> list[RunRecord]:
    with connect() as db:
        rows = db.execute("SELECT * FROM runs WHERE parent_id=? AND deleted_at IS NULL ORDER BY member_index", (parent_id,)).fetchall()
    return [_record(row) for row in rows]


def active_parents() -> list[RunRecord]:
    with connect() as db:
        rows = db.execute("SELECT * FROM runs WHERE deleted_at IS NULL AND parent_id IS NULL AND mode!='single' AND status IN ('running','submitted')").fetchall()
    return [_record(row) for row in rows]


def next_queued() -> RunRecord | None:
    with connect() as db:
        row = db.execute("SELECT id FROM runs WHERE deleted_at IS NULL AND status='queued' ORDER BY created_at LIMIT 1").fetchone()
    return get_run(row["id"]) if row else None


def queued_runs(limit: int = 50) -> list[RunRecord]:
    with connect() as db:
        rows = db.execute("SELECT * FROM runs WHERE deleted_at IS NULL AND status='queued' ORDER BY created_at LIMIT ?", (limit,)).fetchall()
    return [_record(row) for row in rows]


def claim_run(run_id: str) -> bool:
    """Atomically reserve a queued run for one dispatcher thread."""
    with connect() as db:
        changed = db.execute("""UPDATE runs SET status='preparing', stage='preparing', progress=1, updated_at=?
                              WHERE id=? AND status='queued' AND deleted_at IS NULL""", (now(), run_id)).rowcount
    return changed == 1


def recoverable_remote_runs() -> list[RunRecord]:
    """Runs whose Slurm identity survived an application restart."""
    with connect() as db:
        rows = db.execute("""SELECT * FROM runs
                           WHERE runner='ssh-slurm' AND external_job_id IS NOT NULL
                           AND deleted_at IS NULL
                           AND status IN ('submitted','running') ORDER BY created_at""").fetchall()
    return [_record(row) for row in rows]


def _record(row: sqlite3.Row) -> RunRecord:
    values = dict(row)
    values.pop("demo", None)
    values["scenario"] = Scenario.model_validate_json(values["scenario"])
    values["ensemble"] = json.loads(values["ensemble"]) if values.get("ensemble") else None
    values["intervention"] = json.loads(values["intervention"]) if values.get("intervention") else None
    values["run_context"] = json.loads(values["run_context"]) if values.get("run_context") else None
    if values.get("parent_id") is None and values.get("mode") != "single":
        children = child_runs(values["id"])
        values["successful_members"] = sum(child.status == "ready" for child in children)
    return RunRecord(**values)


def update_run_metadata(run_id: str, name: str, notes: str, expected_revision: int) -> RunRecord:
    with connect() as db:
        changed = db.execute("""UPDATE runs SET name=?, notes=?, metadata_revision=metadata_revision+1, updated_at=?
                              WHERE id=? AND parent_id IS NULL AND deleted_at IS NULL
                              AND metadata_revision=?""",
                             (name, notes, now(), run_id, expected_revision)).rowcount
        if not changed:
            exists = db.execute("SELECT 1 FROM runs WHERE id=? AND parent_id IS NULL AND deleted_at IS NULL",
                                (run_id,)).fetchone()
            if not exists:
                raise KeyError(run_id)
            raise RunConflictError(run_id)
    return get_run(run_id)


def delete_run(run_id: str, expected_revision: int) -> None:
    active_statuses = ("queued", "preparing", "submitted", "running", "postprocessing")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM runs WHERE id=? AND parent_id IS NULL AND deleted_at IS NULL",
                         (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        if row["metadata_revision"] != expected_revision:
            raise RunConflictError(run_id)
        placeholders = ",".join("?" for _ in active_statuses)
        active = db.execute(f"""SELECT 1 FROM runs WHERE deleted_at IS NULL AND (id=? OR parent_id=?)
                              AND status IN ({placeholders}) LIMIT 1""",
                            (run_id, run_id, *active_statuses)).fetchone()
        if active:
            raise RunBusyError(run_id)
        dependants = db.execute("""SELECT name,ensemble FROM runs WHERE deleted_at IS NULL
                                 AND parent_id IS NULL AND mode='allocation_comparison'""").fetchall()
        for dependant in dependants:
            ensemble = json.loads(dependant["ensemble"]) if dependant["ensemble"] else {}
            if ensemble.get("source_run_id") == run_id:
                raise RunDependencyError(dependant["name"] or "Containment comparison")
        exercise_ref = db.execute("SELECT scenario_id FROM exercise_artifact_refs WHERE run_id=? LIMIT 1",
                                  (run_id,)).fetchone()
        if exercise_ref:
            raise RunDependencyError(f"Exercise {exercise_ref['scenario_id']}")
        stamp = now()
        db.execute("UPDATE runs SET deleted_at=?, updated_at=? WHERE id=? OR parent_id=?",
                   (stamp, stamp, run_id, run_id))
