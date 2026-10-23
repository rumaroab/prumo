from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from .models import (LocationCreate, LocationObservation, MovementAction, MovementCreate, MovementRevision,
                     OperationalUnit, RoadReport, RoutePlanInput, VehicleProfile)
from .mobility_routing import restrictions_revision
from .area_packages import package_path
from .storage import connect, now


ACTIVE_MOVEMENT = ("assigned", "accepted", "travelling", "arrived", "cannot_proceed")


class MobilityConflict(RuntimeError):
    pass


class MobilityNotFound(KeyError):
    pass


def init_mobility_db() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
          password_hash TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL,
          created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS mobility_memberships (
          scenario_id TEXT NOT NULL, user_id TEXT NOT NULL, unit_id TEXT,
          PRIMARY KEY(scenario_id,user_id)
        );
        CREATE TABLE IF NOT EXISTS mobility_vehicles (
          id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, payload TEXT NOT NULL,
          revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mobility_units (
          id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, payload TEXT NOT NULL,
          revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mobility_locations (
          id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, unit_id TEXT NOT NULL,
          payload TEXT NOT NULL, observed_at TEXT NOT NULL, received_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS mobility_locations_unit ON mobility_locations(unit_id,observed_at DESC);
        CREATE TABLE IF NOT EXISTS mobility_road_reports (
          id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, payload TEXT NOT NULL,
          revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mobility_water_reports (
          id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, point_id TEXT NOT NULL,
          payload TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mobility_water_status (
          scenario_id TEXT NOT NULL, point_id TEXT NOT NULL, availability TEXT NOT NULL,
          observed_at TEXT NOT NULL, reviewed_at TEXT NOT NULL, reviewer_id TEXT NOT NULL,
          report_id TEXT NOT NULL, PRIMARY KEY(scenario_id,point_id)
        );
        CREATE TABLE IF NOT EXISTS mobility_movements (
          id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, unit_id TEXT NOT NULL, vehicle_id TEXT NOT NULL,
          status TEXT NOT NULL, payload TEXT NOT NULL, revision INTEGER NOT NULL,
          brief_version INTEGER NOT NULL, needs_review INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS mobility_active_unit ON mobility_movements(unit_id)
          WHERE status IN ('assigned','accepted','travelling','arrived','cannot_proceed');
        CREATE UNIQUE INDEX IF NOT EXISTS mobility_active_vehicle ON mobility_movements(vehicle_id)
          WHERE status IN ('assigned','accepted','travelling','arrived','cannot_proceed');
        CREATE TABLE IF NOT EXISTS mobility_route_plans (
          id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, payload TEXT NOT NULL,
          revision INTEGER NOT NULL, assigned_movement_id TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS mobility_route_plans_scenario
          ON mobility_route_plans(scenario_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS mobility_movement_versions (
          movement_id TEXT NOT NULL, version INTEGER NOT NULL, snapshot TEXT NOT NULL,
          created_at TEXT NOT NULL, PRIMARY KEY(movement_id,version)
        );
        CREATE TABLE IF NOT EXISTS mobility_events (
          id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, movement_id TEXT, kind TEXT NOT NULL,
          actor_id TEXT, source TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
          request_id TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS mobility_shares (
          token_hash TEXT PRIMARY KEY, movement_id TEXT NOT NULL, expires_at TEXT NOT NULL,
          revoked_at TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mobility_demo_runs (
          id TEXT PRIMARY KEY, scenario_id TEXT UNIQUE NOT NULL, owner_id TEXT,
          script_id TEXT NOT NULL, script_version INTEGER NOT NULL, script_checksum TEXT NOT NULL,
          fixture_checksum TEXT NOT NULL, state TEXT NOT NULL, speed REAL NOT NULL,
          current_index INTEGER NOT NULL DEFAULT 0, elapsed_seconds REAL NOT NULL DEFAULT 0,
          stage TEXT NOT NULL, error TEXT, lease_hash TEXT, lease_expires_at TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT, archived_at TEXT
        );
        CREATE TABLE IF NOT EXISTS mobility_demo_events (
          run_id TEXT NOT NULL, event_id TEXT NOT NULL, event_index INTEGER NOT NULL,
          planned_offset_seconds REAL NOT NULL, status TEXT NOT NULL, receipt TEXT NOT NULL,
          applied_at TEXT NOT NULL, PRIMARY KEY(run_id,event_id)
        );
        CREATE TABLE IF NOT EXISTS mobility_demo_entities (
          run_id TEXT NOT NULL, alias TEXT NOT NULL, entity_type TEXT NOT NULL,
          record_id TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
          PRIMARY KEY(run_id,alias)
        );
        CREATE TABLE IF NOT EXISTS mobility_demo_communications (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, scenario_id TEXT NOT NULL, event_id TEXT NOT NULL,
          callsign TEXT NOT NULL, organisation TEXT NOT NULL, source TEXT NOT NULL,
          message_pt TEXT NOT NULL, message_en TEXT NOT NULL,
          observed_at TEXT NOT NULL, received_at TEXT NOT NULL,
          linked_type TEXT, linked_id TEXT, result_state TEXT NOT NULL,
          UNIQUE(run_id,event_id)
        );
        CREATE INDEX IF NOT EXISTS mobility_demo_communications_scenario
          ON mobility_demo_communications(scenario_id,received_at DESC);
        """)
    _bootstrap_admin()


def _bootstrap_admin() -> None:
    username = os.getenv("FIRELINE_BOOTSTRAP_ADMIN", "").strip()
    password = os.getenv("FIRELINE_BOOTSTRAP_ADMIN_PASSWORD", "")
    if not username or not password:
        return
    if len(password) < 12:
        raise RuntimeError("FIRELINE_BOOTSTRAP_ADMIN_PASSWORD must contain at least 12 characters")
    with connect() as db:
        if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            db.execute("INSERT INTO users VALUES (?,?,?,?,?,1,?)",
                       (uuid4().hex[:12], username, username, hash_password(password), "administrator", now()))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, rounds, salt, expected = encoded.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def login(username: str, password: str) -> tuple[str, dict[str, Any]]:
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            raise PermissionError("Invalid username or password")
        token = secrets.token_urlsafe(32)
        stamp = datetime.now(UTC)
        db.execute("INSERT INTO sessions VALUES (?,?,?,?)",
                   (hashlib.sha256(token.encode()).hexdigest(), row["id"],
                    (stamp + timedelta(hours=12)).isoformat(), stamp.isoformat()))
    return token, _user_payload(row)


def session_user(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    with connect() as db:
        row = db.execute("""SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id
                          WHERE sessions.token_hash=? AND sessions.expires_at>? AND users.active=1""",
                         (hashlib.sha256(token.encode()).hexdigest(), now())).fetchone()
    return _user_payload(row) if row else None


def logout(token: str | None) -> None:
    if not token:
        return
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))


def _user_payload(row) -> dict[str, Any]:
    return {"id": row["id"], "username": row["username"], "display_name": row["display_name"], "role": row["role"]}


def create_user(username: str, display_name: str, password: str, role: str) -> dict[str, Any]:
    if role not in {"administrator", "dispatcher", "crew"}:
        raise ValueError("Invalid role")
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    user_id = uuid4().hex[:12]
    with connect() as db:
        db.execute("INSERT INTO users VALUES (?,?,?,?,?,1,?)",
                   (user_id, username.strip(), display_name.strip(), hash_password(password), role, now()))
        row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return _user_payload(row)


def list_vehicles(scenario_id: str) -> list[dict]:
    return _list_payloads("mobility_vehicles", scenario_id)


def list_route_plans(scenario_id: str) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT payload FROM mobility_route_plans WHERE scenario_id=? ORDER BY updated_at DESC",
                          (scenario_id,)).fetchall()
    return [json.loads(row["payload"]) for row in rows]


def save_route_plan(scenario_id: str, value: RoutePlanInput, route: dict,
                    plan_id: str | None = None) -> dict:
    stamp = now()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if plan_id:
            row = db.execute("SELECT payload,revision,assigned_movement_id FROM mobility_route_plans "
                             "WHERE id=? AND scenario_id=?", (plan_id, scenario_id)).fetchone()
            if not row:
                raise MobilityNotFound(plan_id)
            if row["assigned_movement_id"] or row["revision"] != value.expected_revision:
                raise MobilityConflict("O plano mudou ou já foi atribuído; atualize a página.")
            previous = json.loads(row["payload"])
            revision = row["revision"] + 1
            created_at = previous["created_at"]
        else:
            plan_id = uuid4().hex[:12]
            revision = 1
            created_at = stamp
        payload = {"id": plan_id, "scenario_id": scenario_id,
                   **value.model_dump(mode="json", exclude={"preview_signature", "expected_revision"}),
                   "route": {key: item for key, item in route.items() if key != "preview_signature"},
                   "revision": revision, "assigned_movement_id": None,
                   "created_at": created_at, "updated_at": stamp}
        if revision == 1:
            db.execute("INSERT INTO mobility_route_plans VALUES (?,?,?,?,?,?,?)",
                       (plan_id, scenario_id, json.dumps(payload), revision, None, created_at, stamp))
        else:
            db.execute("UPDATE mobility_route_plans SET payload=?,revision=?,updated_at=? WHERE id=?",
                       (json.dumps(payload), revision, stamp, plan_id))
    return payload


def delete_route_plan(scenario_id: str, plan_id: str, expected_revision: int) -> None:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT revision,assigned_movement_id FROM mobility_route_plans "
                         "WHERE id=? AND scenario_id=?", (plan_id, scenario_id)).fetchone()
        if not row:
            raise MobilityNotFound(plan_id)
        if row["assigned_movement_id"] or row["revision"] != expected_revision:
            raise MobilityConflict("O plano mudou ou já foi atribuído; atualize a página.")
        db.execute("DELETE FROM mobility_route_plans WHERE id=?", (plan_id,))


def save_vehicle(scenario_id: str, value: VehicleProfile) -> dict:
    return _insert_payload("mobility_vehicles", scenario_id, value.id, value.model_dump(mode="json"))


def list_units(scenario_id: str) -> list[dict]:
    values = _list_payloads("mobility_units", scenario_id)
    with connect() as db:
        for value in values:
            row = db.execute("SELECT payload FROM mobility_locations WHERE unit_id=? ORDER BY observed_at DESC LIMIT 1",
                             (value["id"],)).fetchone()
            value["latest_location"] = json.loads(row["payload"]) if row else None
    return values


def mobility_metrics(scenario_ids: list[str]) -> dict[str, dict[str, int]]:
    """Return compact operational counts without loading complete mobility snapshots."""
    ids = list(dict.fromkeys(scenario_ids))
    metrics = {scenario_id: {
        "total_units": 0,
        "available_units": 0,
        "active_movements": 0,
        "pending_road_reports": 0,
        "routes_needing_review": 0,
    } for scenario_id in ids}
    if not ids:
        return metrics
    placeholders = ",".join("?" for _ in ids)
    with connect() as db:
        units = db.execute(
            f"SELECT scenario_id,payload FROM mobility_units WHERE scenario_id IN ({placeholders})", ids
        ).fetchall()
        movements = db.execute(
            f"SELECT scenario_id,status,needs_review FROM mobility_movements WHERE scenario_id IN ({placeholders})", ids
        ).fetchall()
        reports = db.execute(
            f"SELECT scenario_id,payload FROM mobility_road_reports WHERE scenario_id IN ({placeholders})", ids
        ).fetchall()
    for row in units:
        value = metrics[row["scenario_id"]]
        value["total_units"] += 1
        if json.loads(row["payload"]).get("status") == "available":
            value["available_units"] += 1
    for row in movements:
        if row["status"] not in ACTIVE_MOVEMENT:
            continue
        value = metrics[row["scenario_id"]]
        value["active_movements"] += 1
        if row["needs_review"]:
            value["routes_needing_review"] += 1
    for row in reports:
        if json.loads(row["payload"]).get("status") == "pending":
            metrics[row["scenario_id"]]["pending_road_reports"] += 1
    return metrics


def save_unit(scenario_id: str, value: OperationalUnit) -> dict:
    with connect() as db:
        if value.vehicle_id and not db.execute("SELECT 1 FROM mobility_vehicles WHERE id=? AND scenario_id=?", (value.vehicle_id, scenario_id)).fetchone():
            raise MobilityNotFound(value.vehicle_id)
    payload = value.model_dump(mode="json", exclude={"latest_location"})
    return _insert_payload("mobility_units", scenario_id, value.id, payload)


def update_unit_status(scenario_id: str, unit_id: str, status: str, expected_revision: int) -> dict:
    if status not in {"available", "unavailable"}:
        raise ValueError("Units can be manually marked available or unavailable")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        active = db.execute("SELECT 1 FROM mobility_movements WHERE unit_id=? AND status IN ('assigned','accepted','travelling','arrived','cannot_proceed')", (unit_id,)).fetchone()
        if active:
            raise MobilityConflict("Complete or cancel the active movement before changing availability")
        row = db.execute("SELECT payload,revision FROM mobility_units WHERE id=? AND scenario_id=?", (unit_id, scenario_id)).fetchone()
        if not row:
            raise MobilityNotFound(unit_id)
        if row["revision"] != expected_revision:
            raise MobilityConflict("Unit changed; refresh before updating")
        payload = json.loads(row["payload"])
        payload.update(status=status, revision=expected_revision + 1)
        db.execute("UPDATE mobility_units SET payload=?,revision=?,updated_at=? WHERE id=?",
                   (json.dumps(payload), expected_revision + 1, now(), unit_id))
    return payload


def add_location(scenario_id: str, unit_id: str, value: LocationCreate) -> dict:
    with connect() as db:
        if not db.execute("SELECT 1 FROM mobility_units WHERE id=? AND scenario_id=?", (unit_id, scenario_id)).fetchone():
            raise MobilityNotFound(unit_id)
        received = datetime.now(UTC)
        observation = LocationObservation(unit_id=unit_id, received_at=received, **value.model_dump())
        payload = observation.model_dump(mode="json")
        db.execute("INSERT INTO mobility_locations VALUES (?,?,?,?,?,?)",
                   (observation.id, scenario_id, unit_id, json.dumps(payload), payload["observed_at"], payload["received_at"]))
        _event(db, scenario_id, None, "location", None, value.source, payload)
    return payload


def list_road_reports(scenario_id: str) -> list[dict]:
    return _list_payloads("mobility_road_reports", scenario_id)


def list_water_reports(scenario_id: str) -> list[dict]:
    return _list_payloads("mobility_water_reports", scenario_id)


def water_statuses(scenario_id: str) -> dict[str, dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM mobility_water_status WHERE scenario_id=?", (scenario_id,)).fetchall()
    return {row["point_id"]: dict(row) for row in rows}


def save_water_report(scenario_id: str, point_id: str, availability: str, note: str,
                      observed_at: str, actor_id: str, source: str) -> dict:
    stamp = now()
    payload = {"id": uuid4().hex[:12], "point_id": point_id, "availability": availability,
               "note": note, "observed_at": observed_at, "created_at": stamp,
               "source": source, "reporter_id": actor_id, "status": "pending", "revision": 1,
               "reviewer_id": None, "reviewed_at": None}
    with connect() as db:
        db.execute("INSERT INTO mobility_water_reports VALUES (?,?,?,?,?,?,?)",
                   (payload["id"], scenario_id, point_id, json.dumps(payload), 1, stamp, stamp))
        _event(db, scenario_id, None, "water_reported", actor_id, source, payload)
    return payload


def review_water_report(scenario_id: str, report_id: str, status: str, expected_revision: int,
                        reviewer_id: str) -> dict:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM mobility_water_reports WHERE id=? AND scenario_id=?",
                         (report_id, scenario_id)).fetchone()
        if not row:
            raise MobilityNotFound(report_id)
        if row["revision"] != expected_revision:
            raise MobilityConflict("Water report changed; refresh before reviewing")
        payload = json.loads(row["payload"])
        if payload["status"] != "pending":
            raise MobilityConflict("Water report was already reviewed")
        payload.update(status=status, reviewer_id=reviewer_id, reviewed_at=now(), revision=expected_revision + 1)
        db.execute("UPDATE mobility_water_reports SET payload=?,revision=?,updated_at=? WHERE id=?",
                   (json.dumps(payload), expected_revision + 1, now(), report_id))
        if status == "confirmed":
            db.execute("""INSERT INTO mobility_water_status VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT(scenario_id,point_id) DO UPDATE SET
                       availability=excluded.availability,observed_at=excluded.observed_at,
                       reviewed_at=excluded.reviewed_at,reviewer_id=excluded.reviewer_id,
                       report_id=excluded.report_id""",
                       (scenario_id, payload["point_id"], payload["availability"], payload["observed_at"],
                        payload["reviewed_at"], reviewer_id, report_id))
        _event(db, scenario_id, None, "water_reviewed", reviewer_id, "dispatcher", payload)
    return payload


def save_road_report(scenario_id: str, value: RoadReport, actor_id: str | None = None) -> dict:
    stamp = datetime.now(UTC)
    value.created_at = stamp
    payload = value.model_dump(mode="json")
    with connect() as db:
        db.execute("INSERT INTO mobility_road_reports VALUES (?,?,?,?,?,?)",
                   (value.id, scenario_id, json.dumps(payload), 1, stamp.isoformat(), stamp.isoformat()))
        _event(db, scenario_id, None, "road_reported", actor_id, value.source, payload)
        if value.kind in {"blocked", "restricted"} and value.segment_id:
            _flag_affected(db, scenario_id, value.segment_id)
    return payload


def review_road_report(scenario_id: str, report_id: str, status: str, expected_revision: int,
                       actor_id: str | None = None, segment_id: str | None = None,
                       direction: str | None = None) -> dict:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM mobility_road_reports WHERE id=? AND scenario_id=?", (report_id, scenario_id)).fetchone()
        if not row:
            raise MobilityNotFound(report_id)
        if row["revision"] != expected_revision:
            raise MobilityConflict(report_id)
        payload = json.loads(row["payload"])
        if segment_id:
            payload["segment_id"] = segment_id
        if direction:
            payload["direction"] = direction
        if status == "confirmed" and not payload.get("segment_id"):
            raise MobilityConflict("Match the report to a prepared road before confirming it")
        payload.update(status=status, reviewed_at=now(), revision=expected_revision + 1)
        db.execute("UPDATE mobility_road_reports SET payload=?,revision=?,updated_at=? WHERE id=?",
                   (json.dumps(payload), expected_revision + 1, now(), report_id))
        _event(db, scenario_id, None, "road_reviewed", actor_id, "dispatcher", {"report_id": report_id, "status": status})
        if status == "confirmed" and payload.get("kind") in {"blocked", "restricted"} and payload.get("segment_id"):
            _flag_affected(db, scenario_id, payload["segment_id"])
        if status == "confirmed" and payload.get("kind") == "reopening" and payload.get("segment_id"):
            previous = db.execute("SELECT * FROM mobility_road_reports WHERE scenario_id=? AND id<>?",
                                  (scenario_id, report_id)).fetchall()
            for item in previous:
                active = json.loads(item["payload"])
                if (active.get("segment_id") == payload["segment_id"]
                        and active.get("kind") in {"blocked", "restricted"}
                        and active.get("status") == "confirmed"):
                    active.update(status="dismissed", reviewed_at=now(), revision=item["revision"] + 1,
                                  closed_by_report_id=report_id)
                    db.execute("UPDATE mobility_road_reports SET payload=?,revision=?,updated_at=? WHERE id=?",
                               (json.dumps(active), item["revision"] + 1, now(), item["id"]))
                    _event(db, scenario_id, None, "road_reopened", actor_id, "dispatcher",
                           {"report_id": item["id"], "reopening_report_id": report_id})
    return payload


def list_movements(scenario_id: str, unit_id: str | None = None) -> list[dict]:
    with connect() as db:
        sql = "SELECT * FROM mobility_movements WHERE scenario_id=?"
        args: tuple[Any, ...] = (scenario_id,)
        if unit_id:
            sql += " AND unit_id=?"
            args += (unit_id,)
        rows = db.execute(sql + " ORDER BY created_at DESC", args).fetchall()
    return [_movement_payload(row) for row in rows]


def create_movement(scenario_id: str, value: MovementCreate, actor_id: str | None = None,
                    route: dict[str, Any] | None = None) -> dict:
    route = route if route is not None else value.route
    if route is None:
        raise MobilityConflict("A server-calculated route is required")
    stamp = now()
    movement_id = uuid4().hex[:12]
    payload = {"id": movement_id, **value.model_dump(mode="json", exclude={"preview_signature", "route"}), "route": route,
               "status": "assigned", "revision": 1,
               "brief_version": 1, "acknowledged_brief_version": None,
               "needs_review": False, "created_at": stamp, "updated_at": stamp}
    if route.get("status") == "unavailable":
        raise MobilityConflict("An unavailable route cannot be assigned")
    if route.get("status") == "unknown" and not value.suitability_acknowledged:
        raise ValueError("Acknowledge unresolved route suitability before assignment")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if value.route_plan_id:
            plan_row = db.execute("SELECT payload,revision,assigned_movement_id FROM mobility_route_plans "
                                  "WHERE id=? AND scenario_id=?", (value.route_plan_id, scenario_id)).fetchone()
            if not plan_row or plan_row["assigned_movement_id"]:
                raise MobilityConflict("O plano já não está disponível para atribuição.")
            plan = json.loads(plan_row["payload"])
            if (plan_row["revision"] != value.route_plan_revision or plan["purpose"] != value.purpose
                    or plan["destination"] != value.destination.model_dump(mode="json")):
                raise MobilityConflict("O plano mudou; abra-o novamente antes de atribuir.")
        records = {}
        for table, record_id in (("mobility_units", value.unit_id), ("mobility_vehicles", value.vehicle_id)):
            record = db.execute(f"SELECT payload FROM {table} WHERE id=? AND scenario_id=?", (record_id, scenario_id)).fetchone()
            if not record:
                raise MobilityNotFound(record_id)
            records[table] = json.loads(record["payload"])
        unit = records["mobility_units"]
        vehicle = records["mobility_vehicles"]
        if vehicle.get("vehicle_class") == "aircraft":
            raise MobilityConflict("Os meios aéreos não utilizam movimentos rodoviários.")
        if unit.get("vehicle_id") != value.vehicle_id or unit.get("status") != "available" or vehicle.get("available") is False:
            raise MobilityConflict("The unit is unavailable or is not assigned to this vehicle")
        if value.route_plan_id:
            latest = db.execute("SELECT payload FROM mobility_locations WHERE scenario_id=? AND unit_id=? "
                                "ORDER BY observed_at DESC LIMIT 1", (scenario_id, value.unit_id)).fetchone()
            if not latest or tuple(json.loads(latest["payload"])["coordinates"]) != value.origin.coordinates:
                raise MobilityConflict("A localização da unidade mudou; calcule o percurso novamente.")
        departure = value.departure_at.astimezone(UTC)
        if ((unit.get("available_from") and departure < datetime.fromisoformat(unit["available_from"]).astimezone(UTC))
                or (unit.get("available_until") and departure > datetime.fromisoformat(unit["available_until"]).astimezone(UTC))):
            raise MobilityConflict("The unit is unavailable at the planned departure time")
        if route.get("vehicle_revision") is not None and vehicle.get("revision") != route.get("vehicle_revision"):
            raise MobilityConflict("The vehicle changed after the route preview")
        _assert_prepared_revision(db, scenario_id, route)
        current_reports = [json.loads(row["payload"]) for row in db.execute(
            "SELECT payload FROM mobility_road_reports WHERE scenario_id=? ORDER BY created_at", (scenario_id,)).fetchall()]
        current_restrictions = restrictions_revision(current_reports)
        preview_revision = route.get("restrictions_revision")
        if preview_revision and preview_revision != current_restrictions:
            raise MobilityConflict("Road reports changed after the route preview; calculate the route again")
        payload["vehicle_snapshot"] = records["mobility_vehicles"]
        payload["route"]["restrictions_revision"] = current_restrictions
        try:
            db.execute("INSERT INTO mobility_movements VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (movement_id, scenario_id, value.unit_id, value.vehicle_id, "assigned", json.dumps(payload),
                        1, 1, 0, stamp, stamp))
        except sqlite3.IntegrityError as error:
            raise MobilityConflict("Unit or vehicle already has an active movement") from error
        db.execute("INSERT INTO mobility_movement_versions VALUES (?,?,?,?)", (movement_id, 1, json.dumps(payload), stamp))
        if value.route_plan_id:
            plan.update(assigned_movement_id=movement_id, revision=plan_row["revision"] + 1, updated_at=stamp)
            db.execute("UPDATE mobility_route_plans SET payload=?,revision=?,assigned_movement_id=?,updated_at=? "
                       "WHERE id=?", (json.dumps(plan), plan["revision"], movement_id, stamp, value.route_plan_id))
        _set_unit_status(db, value.unit_id, "assigned")
        _event(db, scenario_id, movement_id, "assigned", actor_id, "dispatcher", {"brief_version": 1})
    return payload


ACTION_TRANSITIONS = {
    "accept": ({"assigned"}, "accepted"), "depart": ({"accepted"}, "travelling"),
    "arrive": ({"travelling"}, "arrived"), "complete": ({"arrived", "cannot_proceed"}, "completed"),
    "cannot_proceed": ({"assigned", "accepted", "travelling"}, "cannot_proceed"),
    "cancel": ({"assigned", "accepted", "travelling", "arrived", "cannot_proceed"}, "cancelled"),
}


def act_on_movement(scenario_id: str, movement_id: str, action: MovementAction,
                    actor_id: str | None = None) -> dict:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        duplicate = db.execute("SELECT movement_id FROM mobility_events WHERE request_id=?", (action.request_id,)).fetchone()
        if duplicate:
            row = db.execute("SELECT * FROM mobility_movements WHERE id=?", (duplicate["movement_id"],)).fetchone()
            return _movement_payload(row)
        row = db.execute("SELECT * FROM mobility_movements WHERE id=? AND scenario_id=?", (movement_id, scenario_id)).fetchone()
        if not row:
            raise MobilityNotFound(movement_id)
        if row["revision"] != action.expected_revision or row["brief_version"] != action.expected_brief_version:
            raise MobilityConflict("Movement or brief changed; refresh before updating")
        payload = json.loads(row["payload"])
        if action.action == "depart" and row["needs_review"]:
            raise MobilityConflict("The assigned route needs dispatcher review before departure")
        if (action.action in {"depart", "arrive", "complete"}
                and payload.get("acknowledged_brief_version") != row["brief_version"]):
            raise MobilityConflict("The current brief must be acknowledged before the movement can progress")
        if action.action == "acknowledge_brief":
            if row["status"] not in ACTIVE_MOVEMENT:
                raise MobilityConflict("Only an active movement brief can be acknowledged")
            target = row["status"]
            payload["acknowledged_brief_version"] = row["brief_version"]
        else:
            allowed, target = ACTION_TRANSITIONS[action.action]
            if row["status"] not in allowed:
                raise MobilityConflict(f"Cannot {action.action} a {row['status']} movement")
            if action.action == "accept":
                payload["acknowledged_brief_version"] = row["brief_version"]
        payload.update(status=target, revision=row["revision"] + 1, updated_at=now())
        db.execute("UPDATE mobility_movements SET status=?,payload=?,revision=?,updated_at=? WHERE id=?",
                   (target, json.dumps(payload), row["revision"] + 1, payload["updated_at"], movement_id))
        unit_status = {"travelling": "travelling", "arrived": "on_scene", "completed": "available",
                       "cancelled": "available", "cannot_proceed": "assigned"}.get(target)
        if unit_status:
            _set_unit_status(db, row["unit_id"], unit_status)
        kind = "brief_acknowledged" if action.action == "acknowledge_brief" else action.action
        _event(db, scenario_id, movement_id, kind, actor_id, action.source,
               {"note": action.note, "brief_version": row["brief_version"]}, action.request_id)
    return payload


def revise_movement(scenario_id: str, movement_id: str, value: MovementRevision,
                    actor_id: str | None = None, route: dict[str, Any] | None = None) -> dict:
    route = route if route is not None else value.route
    if route is None:
        raise MobilityConflict("A server-calculated route is required")
    if route.get("status") == "unknown" and not value.suitability_acknowledged:
        raise ValueError("Acknowledge unresolved route suitability before publishing the revision")
    if route.get("status") == "unavailable":
        raise ValueError("An unavailable route cannot be assigned")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM mobility_movements WHERE id=? AND scenario_id=?", (movement_id, scenario_id)).fetchone()
        if not row:
            raise MobilityNotFound(movement_id)
        if row["revision"] != value.expected_revision:
            raise MobilityConflict("Movement changed; refresh before publishing a new route")
        if row["status"] not in ACTIVE_MOVEMENT:
            raise MobilityConflict("Only an active movement can receive a revised route")
        unit_row = db.execute("SELECT payload FROM mobility_units WHERE id=? AND scenario_id=?", (row["unit_id"], scenario_id)).fetchone()
        vehicle_row = db.execute("SELECT payload FROM mobility_vehicles WHERE id=? AND scenario_id=?", (row["vehicle_id"], scenario_id)).fetchone()
        if not unit_row or not vehicle_row:
            raise MobilityConflict("The assigned unit or vehicle is unavailable")
        if json.loads(unit_row["payload"]).get("vehicle_id") != row["vehicle_id"]:
            raise MobilityConflict("The unit is no longer associated with this vehicle")
        if json.loads(vehicle_row["payload"]).get("available") is False:
            raise MobilityConflict("The vehicle is unavailable")
        if route.get("vehicle_revision") is not None and json.loads(vehicle_row["payload"]).get("revision") != route.get("vehicle_revision"):
            raise MobilityConflict("The vehicle changed after the route preview")
        _assert_prepared_revision(db, scenario_id, route)
        current_reports = [json.loads(item["payload"]) for item in db.execute(
            "SELECT payload FROM mobility_road_reports WHERE scenario_id=? ORDER BY created_at", (scenario_id,)).fetchall()]
        current_restrictions = restrictions_revision(current_reports)
        if route.get("restrictions_revision") and route["restrictions_revision"] != current_restrictions:
            raise MobilityConflict("Road reports changed after the route preview; calculate the route again")
        payload = json.loads(row["payload"])
        route["restrictions_revision"] = current_restrictions
        version, revision, stamp = row["brief_version"] + 1, row["revision"] + 1, now()
        payload.update(route=route, brief_version=version, revision=revision,
                       needs_review=False, updated_at=stamp)
        db.execute("UPDATE mobility_movements SET payload=?,revision=?,brief_version=?,needs_review=0,updated_at=? WHERE id=?",
                   (json.dumps(payload), revision, version, stamp, movement_id))
        db.execute("INSERT INTO mobility_movement_versions VALUES (?,?,?,?)", (movement_id, version, json.dumps(payload), stamp))
        _event(db, scenario_id, movement_id, "route_revised", actor_id, "dispatcher", {"brief_version": version})
    return payload


def movement(scenario_id: str, movement_id: str) -> dict:
    with connect() as db:
        row = db.execute("SELECT * FROM mobility_movements WHERE id=? AND scenario_id=?", (movement_id, scenario_id)).fetchone()
    if not row:
        raise MobilityNotFound(movement_id)
    return _movement_payload(row)


def list_events(scenario_id: str, limit: int = 100) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM mobility_events WHERE scenario_id=? ORDER BY created_at DESC LIMIT ?",
                          (scenario_id, limit)).fetchall()
    return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]


def create_share(movement_id: str, hours: int = 12) -> str:
    token = secrets.token_urlsafe(24)
    stamp = datetime.now(UTC)
    with connect() as db:
        db.execute("INSERT INTO mobility_shares VALUES (?,?,?,?,?)",
                   (hashlib.sha256(token.encode()).hexdigest(), movement_id,
                    (stamp + timedelta(hours=hours)).isoformat(), None, stamp.isoformat()))
    return token


def revoke_share(token: str) -> None:
    with connect() as db:
        changed = db.execute("UPDATE mobility_shares SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                             (now(), hashlib.sha256(token.encode()).hexdigest())).rowcount
    if not changed:
        raise MobilityNotFound(token)


def shared_movement(token: str) -> dict:
    with connect() as db:
        row = db.execute("""SELECT mobility_movements.* FROM mobility_shares
                          JOIN mobility_movements ON mobility_movements.id=mobility_shares.movement_id
                          WHERE token_hash=? AND expires_at>? AND revoked_at IS NULL""",
                         (hashlib.sha256(token.encode()).hexdigest(), now())).fetchone()
    if not row:
        raise MobilityNotFound(token)
    value = _movement_payload(row)
    allowed = {"id", "purpose", "origin", "destination", "departure_at", "route", "status",
               "notes", "dispatcher_contact", "brief_version", "acknowledged_brief_version",
               "needs_review", "created_at", "updated_at"}
    return {key: item for key, item in value.items() if key in allowed}


def _insert_payload(table: str, scenario_id: str, record_id: str, payload: dict) -> dict:
    payload["revision"] = 1
    stamp = now()
    with connect() as db:
        db.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?,?)",
                   (record_id, scenario_id, json.dumps(payload), 1, stamp, stamp))
    return payload


def _list_payloads(table: str, scenario_id: str) -> list[dict]:
    with connect() as db:
        rows = db.execute(f"SELECT payload FROM {table} WHERE scenario_id=? ORDER BY created_at", (scenario_id,)).fetchall()
    return [json.loads(row["payload"]) for row in rows]


def _movement_payload(row) -> dict:
    payload = json.loads(row["payload"])
    payload.update(status=row["status"], revision=row["revision"], brief_version=row["brief_version"],
                   needs_review=bool(row["needs_review"]))
    return payload


def _set_unit_status(db, unit_id: str, status: str) -> None:
    row = db.execute("SELECT payload,revision FROM mobility_units WHERE id=?", (unit_id,)).fetchone()
    if not row:
        return
    payload = json.loads(row["payload"])
    payload.update(status=status, revision=row["revision"] + 1)
    db.execute("UPDATE mobility_units SET payload=?,revision=?,updated_at=? WHERE id=?",
               (json.dumps(payload), row["revision"] + 1, now(), unit_id))


def _assert_prepared_revision(db, scenario_id: str, route: dict[str, Any]) -> None:
    expected = route.get("prepared_revision")
    if expected is None:  # Internal historical/demo routes do not carry a preview signature.
        return
    row = db.execute("SELECT definition FROM scenarios WHERE id=?", (scenario_id,)).fetchone()
    if not row:
        raise MobilityNotFound(scenario_id)
    package_id = json.loads(row["definition"]).get("area_package_id")
    try:
        metadata = package_path(package_id) / "roads.json"
        current = json.loads(metadata.read_text()).get("revision", "unknown") if metadata.exists() else "unknown"
    except (KeyError, OSError, ValueError) as error:
        raise MobilityConflict("Prepared road data changed; calculate the route again") from error
    if current != expected:
        raise MobilityConflict("Prepared road data changed; calculate the route again")


def _flag_affected(db, scenario_id: str, segment_id: str) -> None:
    rows = db.execute("SELECT * FROM mobility_movements WHERE scenario_id=? AND status IN ('assigned','accepted','travelling','arrived','cannot_proceed')",
                      (scenario_id,)).fetchall()
    for row in rows:
        payload = json.loads(row["payload"])
        segments = payload.get("route", {}).get("segment_ids", [])
        if segment_id in segments:
            payload["needs_review"] = True
            db.execute("UPDATE mobility_movements SET needs_review=1,payload=?,updated_at=? WHERE id=?",
                       (json.dumps(payload), now(), row["id"]))


def _event(db, scenario_id: str, movement_id: str | None, kind: str, actor_id: str | None,
           source: str, payload: dict, request_id: str | None = None) -> None:
    db.execute("INSERT INTO mobility_events VALUES (?,?,?,?,?,?,?,?,?)",
               (uuid4().hex[:12], scenario_id, movement_id, kind, actor_id, source,
                json.dumps(payload), now(), request_id))
