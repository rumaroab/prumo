from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import shutil
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

import networkx as nx
import osmnx as ox
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import LineString, mapping

from . import settings
from .area_packages import package_path
from .models import (LocationCreate, MobilityRouteRequest, MovementAction, MovementCreate,
                     MovementRevision, OperationalUnit, ResponseTeam, RoadReport, RouteLocation,
                     Scenario, ScenarioPatch, ScenarioPoint, VehicleProfile)
from .fogos_resources import reconcile_resource_groups, seed_resource_groups
from .mobility_routing import route_mobility
from .mobility_storage import (act_on_movement, add_location, create_movement,
                               list_road_reports, list_units, list_vehicles, movement,
                               review_road_report, revise_movement, save_road_report, save_unit,
                               save_vehicle)
from .storage import connect, create_scenario, get_scenario, now, update_scenario
from . import fogos


SCRIPT_PATH = settings.ROOT / "backend" / "demo" / "mobility_demo_v1.json"
ACTIVE_STATES = {"ready", "running", "paused", "error"}
LEASE_SECONDS = 12
FIXTURE_BUILDER_VERSION = 2


class DemoConflict(RuntimeError):
    pass


class DemoEventDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(min_length=3, max_length=80)
    at_seconds: float = Field(ge=0)
    type: Literal["communication", "assign", "movement_action", "location", "road_report",
                  "review_report", "revise_route"]
    unit: str | None = None
    movement: str | None = None
    report: str | None = None
    source: Literal["phone", "radio", "dispatcher", "crew"] = "radio"
    message_pt: str = Field(min_length=1)
    message_en: str = Field(min_length=1)
    result_state: str = Field(min_length=1)

    @model_validator(mode="after")
    def required_references(self):
        required = {
            "assign": ("unit", "movement", "destination", "purpose"),
            "movement_action": ("unit", "movement", "action"),
            "location": ("unit", "coordinates"),
            "road_report": ("unit", "report", "segment_id", "kind", "direction", "reason"),
            "review_report": ("unit", "report", "status"),
            "revise_route": ("unit", "movement"),
        }.get(self.type, ())
        for field in required:
            if not getattr(self, field):
                raise ValueError(f"{self.type} requires {field}")
        return self


class DemoScript(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    version: int = Field(ge=1)
    title: str
    duration_seconds: int = Field(gt=0)
    center: tuple[float, float]
    fogos_resource_demo: "DemoFogosResourceConfig"
    nodes: list[dict[str, Any]]
    roads: list[dict[str, Any]]
    destinations: dict[str, dict[str, Any]]
    vehicles: list[dict[str, Any]]
    units: list[dict[str, Any]]
    events: list[DemoEventDefinition]

    @model_validator(mode="after")
    def deterministic_order(self):
        ids = [event.id for event in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("Demo event IDs must be unique")
        offsets = [event.at_seconds for event in self.events]
        if offsets != sorted(offsets):
            raise ValueError("Demo events must be ordered by at_seconds")
        if offsets and offsets[-1] != self.duration_seconds:
            raise ValueError("The final event must match duration_seconds")
        aliases = [item["alias"] for item in self.vehicles + self.units]
        if len(aliases) != len(set(aliases)):
            raise ValueError("Demo aliases must be unique")
        road_ids = [item["id"] for item in self.roads]
        if len(road_ids) != len(set(road_ids)):
            raise ValueError("Demo road IDs must be unique")
        node_ids = {item["id"] for item in self.nodes}
        vehicle_aliases = {item["alias"] for item in self.vehicles}
        unit_aliases = {item["alias"] for item in self.units}
        if any(road.get("from") not in node_ids or road.get("to") not in node_ids for road in self.roads):
            raise ValueError("Every demo road must reference installed nodes")
        if any(unit.get("vehicle") not in vehicle_aliases for unit in self.units):
            raise ValueError("Every demo unit must reference an installed vehicle")
        movements: set[str] = set()
        reports: set[str] = set()
        for event in self.events:
            values = event.model_dump()
            if event.unit and event.unit not in unit_aliases:
                raise ValueError(f"Event {event.id} references unknown unit {event.unit}")
            if event.type == "assign":
                if values["destination"] not in self.destinations:
                    raise ValueError(f"Event {event.id} references an unknown destination")
                movements.add(event.movement)
            elif event.movement and event.movement not in movements:
                raise ValueError(f"Event {event.id} references a movement before it is assigned")
            if event.type == "road_report":
                if values["segment_id"] not in road_ids:
                    raise ValueError(f"Event {event.id} references an unknown road segment")
                reports.add(event.report)
            elif event.report and event.report not in reports:
                raise ValueError(f"Event {event.id} references a road report before it exists")
        return self


class DemoResourceCounts(BaseModel):
    operacionais: int = Field(ge=0)
    meios_terrestres: int = Field(ge=0)
    meios_aereos: int = Field(ge=0)


class DemoFogosResourceConfig(BaseModel):
    imported: DemoResourceCounts
    synchronized: DemoResourceCounts
    planned_operacionais: int = Field(ge=0)


DemoScript.model_rebuild()


def load_demo_script() -> tuple[DemoScript, str]:
    raw = SCRIPT_PATH.read_bytes()
    return DemoScript.model_validate_json(raw), hashlib.sha256(raw).hexdigest()


def install_demo_fixture() -> tuple[str, str]:
    script, script_checksum = load_demo_script()
    checksum = _fixture_checksum(script_checksum)
    package_id = f"mobility-demo-v{script.version}-{checksum[:12]}"
    target = settings.AREAS / package_id
    metadata = target / "roads.json"
    if metadata.exists():
        current = json.loads(metadata.read_text())
        if current.get("fixture_checksum") != checksum:
            raise RuntimeError("Installed mobility demo fixture checksum does not match its script")
        return package_id, checksum
    if target.exists():
        raise RuntimeError("The installed mobility demo fixture is incomplete; remove only that demo package and restart")

    temporary = settings.AREAS / f".{package_id}.{uuid4().hex[:8]}.tmp"
    settings.AREAS.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        nodes = {item["id"]: tuple(item["coordinates"]) for item in script.nodes}
        node_keys = {node_id: index for index, node_id in enumerate(nodes, start=1)}
        graph = nx.MultiDiGraph(crs="EPSG:4326")
        for node_id, (lon, lat) in nodes.items():
            graph.add_node(node_keys[node_id], x=float(lon), y=float(lat), demo_alias=node_id)
        features = []
        for road in script.roads:
            start, end = nodes[road["from"]], nodes[road["to"]]
            line = LineString([start, end])
            length = _haversine_m(start, end)
            common = {"name": road["name"], "highway": "secondary", "length": length,
                      "maxspeed": float(road["speed_kmh"]), "maxwidth": 3.5,
                      "maxheight": 4.2, "maxweight": float(road["maxweight"]),
                      "surface": "asphalt", "geometry": line.wkt,
                      "mobility_edge_id": road["id"]}
            start_key, end_key = node_keys[road["from"]], node_keys[road["to"]]
            graph.add_edge(start_key, end_key, key=0, **common)
            graph.add_edge(end_key, start_key, key=0, **common)
            features.append({"type": "Feature", "properties": {
                "segment_id": road["id"], "name": road["name"], "road_class": "secondary",
                "maxweight": road["maxweight"],
                "edge_refs": json.dumps([[start_key, end_key, 0, "forward"],
                                          [end_key, start_key, 0, "reverse"]]),
            }, "geometry": mapping(line)})
        ox.save_graphml(graph, filepath=temporary / "roads.graphml")
        road_collection = {"type": "FeatureCollection", "features": features,
                           "metadata": {"demo": True, "fixture_checksum": checksum}}
        road_bytes = json.dumps(road_collection, sort_keys=True, separators=(",", ":")).encode()
        (temporary / "roads.geojson").write_bytes(road_bytes)
        road_revision = hashlib.sha256(road_bytes).hexdigest()[:16]
        bounds = _bounds(nodes.values())
        (temporary / "roads.json").write_text(json.dumps({
            "source": "bundled deterministic mobility demonstration", "count": len(features),
            "version": 1, "mobility_version": 1, "revision": road_revision,
            "fixture_checksum": checksum, "bounds": bounds,
        }, indent=2))
        (temporary / "manifest.json").write_text(json.dumps({
            "id": package_id, "status": "ready", "demo": True, "immutable": True,
            "center": script.center, "bounds": bounds, "resource_bounds": bounds,
            "fixture_checksum": checksum,
            "datasets": {"roads": {"status": "ready", "source": "synthetic demonstration fixture"}},
        }, indent=2))
        try:
            os.replace(temporary, target)
        except FileExistsError:
            shutil.rmtree(temporary)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return package_id, checksum


def _save_demo_fogos_snapshot(script: DemoScript, run_id: str, counts: DemoResourceCounts,
                              observed_at: datetime, phase: str) -> dict[str, Any]:
    incident_id = f"demo-{run_id}"
    raw = {
        "id": incident_id, "dateTime": observed_at.isoformat(), "updated": observed_at.isoformat(),
        "location": "DEMO · Serra da Penha", "concelho": "Guimarães", "district": "Braga",
        "lat": script.center[1], "lng": script.center[0], "naturezaCode": "3101",
        "natureza": "Incêndio rural · demonstração sintética", "status": "Em Curso",
        "statusCode": 5, "active": True, "isFire": True,
        "man": counts.operacionais, "terrain": counts.meios_terrestres,
        "aerial": counts.meios_aereos, "demo_phase": phase,
    }
    normalized = fogos.normalize_incident(raw)
    normalized["source_url"] = "https://fogos.pt"
    return fogos.save_snapshot(incident_id, "incident", raw, normalized, normalized["source_url"],
                               observed_at.isoformat(), [
                                   "Synthetic offline fixture for demonstrating Fogos.pt resource reconciliation",
                                   "Not an observation and not suitable for operational use",
                               ])


def create_demo_run(owner_id: str | None, speed: float = 1.0, restart: bool = False) -> dict[str, Any]:
    if speed not in {1.0, 2.0}:
        raise ValueError("Demo speed must be 1 or 2")
    script, script_checksum = load_demo_script()
    package_id, fixture_checksum = install_demo_fixture()
    current = current_demo_run()
    if current and current["script_checksum"] != script_checksum:
        restart = True
    if current and not restart:
        if current["state"] in {"ready", "running", "paused"}:
            return current
        raise DemoConflict("The previous demonstration has finished or stopped; use restart for a clean run")

    run_id = uuid4().hex[:12]
    scenario_id = f"mobility-demo-{run_id}"
    scenario = Scenario(name=script.title, ignitions=[{
        "id": "demo-fire", "name": "Foco demonstrativo", "coordinates": script.center, "start_min": 0,
    }], duration_min=120, seed=42)
    created_at = datetime.now(UTC)
    imported_snapshot = _save_demo_fogos_snapshot(
        script, run_id, script.fogos_resource_demo.imported, created_at - timedelta(minutes=8), "import")
    resource_groups = [group.model_copy(update={
        "notes": "Demonstração sintética do fluxo Fogos.pt; não representa recursos reais.",
        "planned_count_override": (script.fogos_resource_demo.planned_operacionais
                                    if group.category == "operacionais" else None),
    }) for group in seed_resource_groups(imported_snapshot)]
    base_coordinates = tuple(next(item["coordinates"] for item in script.nodes if item["id"] == "base"))
    planning_base = ScenarioPoint(id=f"demo-planning-base-{run_id[:6]}", kind="response_base",
        name="Base de resposta DEMO", coordinates=base_coordinates, source="demo",
        notes="Local sintético para demonstrar criação guiada de equipas.", data_status="verified")
    operacionais = next(group for group in resource_groups if group.category == "operacionais")
    planning_team = ResponseTeam(id=f"demo-planning-team-{run_id[:6]}", name="Equipa Operacionais DEMO",
        base_point_id=planning_base.id, available_from_min=10, line_rate_m_min=5,
        max_deployment_min=240, status="available", source_provenance={
            "provider": "fogos.pt", "incident_id": operacionais.incident_id,
            "resource_group_id": operacionais.id, "category": "operacionais",
            "snapshot_id": operacionais.snapshot_id, "reported_count": operacionais.reported_count,
            "planned_count": operacionais.planned_count_override, "converted_at": created_at.isoformat(),
        })
    workspace = create_scenario(scenario, name=script.title,
                    description=("Cenário determinístico com dados totalmente fictícios. Inclui um fluxo "
                                 "Fogos.pt sintético e offline para demonstrar importação, sincronização e "
                                 "proveniência sem representar um incidente real."),
                    area_package_id=package_id, resource_center=script.center,
                    start_time=created_at - timedelta(minutes=8), points=[planning_base],
                    teams=[planning_team], resource_groups=resource_groups,
                    fogos_snapshot_id=imported_snapshot["id"], scenario_id=scenario_id)
    synchronized_snapshot = _save_demo_fogos_snapshot(
        script, run_id, script.fogos_resource_demo.synchronized, created_at, "synchronized")
    synchronized_groups, _ = reconcile_resource_groups(workspace.resource_groups, synchronized_snapshot)
    scenario_values = workspace.model_dump(exclude={"id", "revision", "created_at", "updated_at",
                                                        "setup_complete", "external_incident"})
    scenario_values.update({"expected_revision": workspace.revision,
                            "resource_groups": synchronized_groups})
    update_scenario(scenario_id, ScenarioPatch(**scenario_values))
    aliases: list[tuple[str, str, str, dict[str, Any]]] = []
    unit_values: dict[str, OperationalUnit] = {}
    suffix = run_id[:6]
    try:
        vehicle_ids: dict[str, str] = {}
        for item in script.vehicles:
            payload = dict(item)
            alias = payload.pop("alias")
            payload["id"] = f"{payload['id']}-{suffix}"
            vehicle = VehicleProfile.model_validate(payload)
            save_vehicle(scenario_id, vehicle)
            vehicle_ids[alias] = vehicle.id
            aliases.append((alias, "vehicle", vehicle.id, {}))
        for item in script.units:
            payload = dict(item)
            alias, vehicle_alias, location = payload.pop("alias"), payload.pop("vehicle"), payload.pop("location")
            payload["id"] = f"{payload['id']}-{suffix}"
            payload["vehicle_id"] = vehicle_ids[vehicle_alias]
            unit = OperationalUnit.model_validate(payload)
            save_unit(scenario_id, unit)
            add_location(scenario_id, unit.id, LocationCreate(
                coordinates=tuple(location), observed_at=datetime.now(UTC), source="radio", accuracy_m=10))
            unit_values[alias] = unit
            aliases.append((alias, "unit", unit.id, {"vehicle_alias": vehicle_alias}))
        _preflight_demo(scenario_id, package_id, script, unit_values)
    except Exception:
        with connect() as db:
            db.execute("UPDATE scenarios SET deleted_at=? WHERE id=?", (now(), scenario_id))
        raise

    stamp = now()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if restart:
            previous = db.execute("SELECT scenario_id FROM mobility_demo_runs WHERE archived_at IS NULL").fetchall()
            db.execute("UPDATE mobility_demo_runs SET state='archived',archived_at=?,updated_at=? WHERE archived_at IS NULL",
                       (stamp, stamp))
            for row in previous:
                db.execute("UPDATE scenarios SET deleted_at=? WHERE id=?", (stamp, row["scenario_id"]))
        db.execute("""INSERT INTO mobility_demo_runs
            (id,scenario_id,owner_id,script_id,script_version,script_checksum,fixture_checksum,state,speed,
             current_index,elapsed_seconds,stage,error,lease_hash,lease_expires_at,created_at,updated_at,
             completed_at,archived_at) VALUES (?,?,?,?,?,?,?,?,?,0,0,'Preparação concluída',NULL,NULL,NULL,?,?,NULL,NULL)""",
                   (run_id, scenario_id, owner_id, script.id, script.version, script_checksum, fixture_checksum,
                    "ready", speed, stamp, stamp))
        for alias, entity_type, record_id, payload in aliases:
            db.execute("INSERT INTO mobility_demo_entities VALUES (?,?,?,?,?)",
                       (run_id, alias, entity_type, record_id, json.dumps(payload)))
    return demo_run(run_id)


def current_demo_run() -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM mobility_demo_runs WHERE archived_at IS NULL ORDER BY created_at DESC LIMIT 1").fetchone()
    return _run_payload(row) if row else None


def demo_run(run_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM mobility_demo_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise KeyError(run_id)
    return _run_payload(row)


def acquire_demo_lease(run_id: str) -> tuple[str, dict[str, Any]]:
    token = secrets.token_urlsafe(24)
    stamp = datetime.now(UTC)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM mobility_demo_runs WHERE id=? AND archived_at IS NULL", (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        if row["state"] in {"completed", "error"} or row["error"]:
            raise DemoConflict("This demonstration cannot continue; restart it for a clean run")
        if row["lease_hash"] and row["lease_expires_at"] and datetime.fromisoformat(row["lease_expires_at"]) > stamp:
            raise DemoConflict("Another demo runner currently owns this run")
        state = "running" if row["state"] == "ready" else row["state"]
        expires = stamp + timedelta(seconds=LEASE_SECONDS)
        db.execute("UPDATE mobility_demo_runs SET state=?,lease_hash=?,lease_expires_at=?,updated_at=? WHERE id=?",
                   (state, _token_hash(token), expires.isoformat(), stamp.isoformat(), run_id))
    return token, demo_run(run_id)


def heartbeat_demo(run_id: str, token: str, elapsed_seconds: float) -> dict[str, Any]:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = _lease_row(db, run_id, token)
        elapsed = (max(float(row["elapsed_seconds"]), min(float(elapsed_seconds), _duration()))
                   if row["state"] == "running" else float(row["elapsed_seconds"]))
        expires = datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)
        db.execute("UPDATE mobility_demo_runs SET elapsed_seconds=?,lease_expires_at=?,updated_at=? WHERE id=?",
                   (elapsed, expires.isoformat(), now(), run_id))
    return demo_run(run_id)


def control_demo(run_id: str, action: Literal["pause", "resume"]) -> dict[str, Any]:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM mobility_demo_runs WHERE id=? AND archived_at IS NULL", (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        if row["error"]:
            raise DemoConflict("This demonstration stopped on an error; restart it after correcting the cause")
        if action == "pause" and row["state"] == "running":
            state = "paused"
        elif action == "resume" and row["state"] == "paused":
            state = "running"
        elif row["state"] in {"completed", "error"}:
            raise DemoConflict("A completed or stopped demonstration cannot change playback state")
        else:
            state = row["state"]
        db.execute("UPDATE mobility_demo_runs SET state=?,updated_at=? WHERE id=?", (state, now(), run_id))
    return demo_run(run_id)


def apply_demo_event(run_id: str, event_id: str, token: str, elapsed_seconds: float) -> dict[str, Any]:
    script, script_checksum = load_demo_script()
    with connect() as db:
        row = _lease_row(db, run_id, token)
        existing = db.execute("SELECT receipt FROM mobility_demo_events WHERE run_id=? AND event_id=?",
                              (run_id, event_id)).fetchone()
        if existing:
            return json.loads(existing["receipt"])
        if row["state"] != "running":
            raise DemoConflict("The demonstration is not running")
        if (row["script_checksum"] != script_checksum
                or row["fixture_checksum"] != _fixture_checksum(script_checksum)):
            raise DemoConflict("The installed demo script or road fixture changed after this run started")
        index = int(row["current_index"])
        if index >= len(script.events) or script.events[index].id != event_id:
            expected = script.events[index].id if index < len(script.events) else "none"
            raise DemoConflict(f"Expected event {expected}, received {event_id}")
        event = script.events[index]
        if elapsed_seconds + .01 < event.at_seconds:
            raise DemoConflict("The next event is not due yet")

    try:
        result, linked_type, linked_id = _perform_event(run_id, event)
        receipt = {"run_id": run_id, "event_id": event.id, "event_index": index,
                   "planned_offset_seconds": event.at_seconds, "status": "applied", "result": result}
        _record_applied_event(run_id, index, event, receipt, linked_type, linked_id, elapsed_seconds)
        return receipt
    except Exception as error:
        fail_demo_run(run_id, f"{event.id}: {error}")
        raise


def fail_demo_run(run_id: str, error: str) -> None:
    with connect() as db:
        db.execute("UPDATE mobility_demo_runs SET state='paused',error=?,lease_hash=NULL,lease_expires_at=NULL,updated_at=? WHERE id=?",
                   (error, now(), run_id))


def demo_snapshot(scenario_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    with connect() as db:
        row = db.execute("SELECT * FROM mobility_demo_runs WHERE scenario_id=?", (scenario_id,)).fetchone()
        messages = db.execute("SELECT * FROM mobility_demo_communications WHERE scenario_id=? ORDER BY received_at DESC",
                              (scenario_id,)).fetchall()
    demo = _run_payload(row) if row else None
    if demo:
        visible = {"id", "scenario_id", "state", "speed", "current_index", "total_events",
                   "elapsed_seconds", "duration_seconds", "stage", "error", "next_event", "is_demo"}
        demo = {key: value for key, value in demo.items() if key in visible}
    return (demo,
            [dict(item) for item in messages])


def scenario_demo_locked(scenario_id: str) -> bool:
    with connect() as db:
        row = db.execute("SELECT state FROM mobility_demo_runs WHERE scenario_id=? AND archived_at IS NULL",
                         (scenario_id,)).fetchone()
    return bool(row and row["state"] in ACTIVE_STATES)


def _perform_event(run_id: str, event: DemoEventDefinition) -> tuple[dict[str, Any], str | None, str | None]:
    run = demo_run(run_id)
    scenario_id = run["scenario_id"]
    values = event.model_dump()
    unit = _entity(run_id, event.unit) if event.unit else None
    if event.type == "communication":
        linked = _linked_entity(run_id, values)
        return {"state": event.result_state}, linked[0], linked[1]
    if event.type == "assign":
        unit_value = next(item for item in list_units(scenario_id) if item["id"] == unit)
        vehicle = next(VehicleProfile.model_validate(item) for item in list_vehicles(scenario_id)
                       if item["id"] == unit_value["vehicle_id"])
        destination = load_demo_script()[0].destinations[values["destination"]]
        origin = RouteLocation(name=unit_value["callsign"], coordinates=unit_value["latest_location"]["coordinates"])
        target = RouteLocation.model_validate(destination)
        request = MobilityRouteRequest(origin=origin, destination=target, vehicle_id=vehicle.id,
                                       departure_at=datetime.now(UTC), alternatives=2)
        route = route_mobility(package_path(run["package_id"]), request, vehicle,
                               list_road_reports(scenario_id))
        if route["status"] == "unavailable":
            raise DemoConflict(route["message"])
        for segment in values.get("forbidden_segments") or []:
            if segment in route.get("segment_ids", []):
                raise DemoConflict(f"Vehicle route incorrectly uses forbidden segment {segment}")
        created = create_movement(scenario_id, MovementCreate(
            unit_id=unit_value["id"], vehicle_id=vehicle.id, purpose=values["purpose"],
            origin=origin, destination=target, departure_at=request.departure_at, route=route,
            suitability_acknowledged=route["status"] == "unknown", dispatcher_contact="Coordenação DEMO"),
            run.get("owner_id"))
        _put_entity(run_id, values["movement"], "movement", created["id"], {})
        return _movement_result(created), "movement", created["id"]
    if event.type == "movement_action":
        movement_id = _entity(run_id, event.movement)
        current = movement(scenario_id, movement_id)
        updated = act_on_movement(scenario_id, movement_id, MovementAction(
            action=values["action"], expected_revision=current["revision"],
            expected_brief_version=current["brief_version"], source=event.source,
            note="Comunicação simulada", request_id=f"demo-{run_id}-{event.id}"), run.get("owner_id"))
        return _movement_result(updated), "movement", movement_id
    if event.type == "location":
        location = add_location(scenario_id, unit, LocationCreate(
            coordinates=tuple(values["coordinates"]), observed_at=datetime.now(UTC),
            source=event.source, accuracy_m=10 if event.source == "phone" else None))
        return {"location_id": location["id"], "source": location["source"]}, "unit", unit
    if event.type == "road_report":
        report_id = f"demo-{run_id[:6]}-{event.report}"
        feature = _road_feature(run["package_id"], values["segment_id"])
        report = save_road_report(scenario_id, RoadReport(
            id=report_id, segment_id=values["segment_id"], road_name=feature["properties"]["name"],
            kind=values["kind"], reason=values["reason"], direction=values["direction"],
            affected_vehicle_classes=[], status="pending", source="radio",
            geometry=feature["geometry"], observed_at=datetime.now(UTC)), run.get("owner_id"))
        _put_entity(run_id, event.report, "road_report", report_id, {})
        return {"report_id": report_id, "status": report["status"], "kind": report["kind"]}, "road_report", report_id
    if event.type == "review_report":
        report_id = _entity(run_id, event.report)
        report = next(item for item in list_road_reports(scenario_id) if item["id"] == report_id)
        reviewed = review_road_report(scenario_id, report_id, values["status"], report["revision"], run.get("owner_id"))
        return {"report_id": report_id, "status": reviewed["status"], "kind": reviewed["kind"]}, "road_report", report_id
    if event.type == "revise_route":
        movement_id = _entity(run_id, event.movement)
        current = movement(scenario_id, movement_id)
        unit_value = next(item for item in list_units(scenario_id) if item["id"] == unit)
        vehicle = next(VehicleProfile.model_validate(item) for item in list_vehicles(scenario_id)
                       if item["id"] == current["vehicle_id"])
        origin = RouteLocation(name=unit_value["callsign"], coordinates=unit_value["latest_location"]["coordinates"])
        target = RouteLocation.model_validate(current["destination"])
        request = MobilityRouteRequest(origin=origin, destination=target, vehicle_id=vehicle.id,
                                       departure_at=datetime.now(UTC), alternatives=2)
        route = route_mobility(package_path(run["package_id"]), request, vehicle,
                               list_road_reports(scenario_id))
        if route["status"] == "unavailable":
            raise DemoConflict(route["message"])
        revised = revise_movement(scenario_id, movement_id, MovementRevision(
            route=route, expected_revision=current["revision"],
            suitability_acknowledged=route["status"] == "unknown"), run.get("owner_id"))
        if revised.get("acknowledged_brief_version") == revised["brief_version"]:
            raise DemoConflict("A revised brief was incorrectly left acknowledged")
        return _movement_result(revised), "movement", movement_id
    raise DemoConflict(f"Unsupported event type {event.type}")


def _record_applied_event(run_id: str, index: int, event: DemoEventDefinition, receipt: dict[str, Any],
                          linked_type: str | None, linked_id: str | None, elapsed_seconds: float) -> None:
    run = demo_run(run_id)
    unit_id = _entity(run_id, event.unit) if event.unit else None
    units = list_units(run["scenario_id"])
    unit = next((item for item in units if item["id"] == unit_id), None)
    observed = now()
    script, _ = load_demo_script()
    complete = index + 1 == len(script.events)
    state, completed_at = ("completed", observed) if complete else (run["state"], None)
    stage = _stage(event.at_seconds, complete)
    communication_id = f"demo-{run_id[:6]}-{event.id}"
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        duplicate = db.execute("SELECT receipt FROM mobility_demo_events WHERE run_id=? AND event_id=?",
                               (run_id, event.id)).fetchone()
        if duplicate:
            return
        db.execute("INSERT INTO mobility_demo_events VALUES (?,?,?,?,?,?,?)",
                   (run_id, event.id, index, event.at_seconds, "applied", json.dumps(receipt), observed))
        db.execute("""INSERT INTO mobility_demo_communications
            (id,run_id,scenario_id,event_id,callsign,organisation,source,message_pt,message_en,
             observed_at,received_at,linked_type,linked_id,result_state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (communication_id, run_id, run["scenario_id"], event.id,
                    unit["callsign"] if unit else "Coordenação",
                    unit["organisation"] if unit else "Coordenação",
                    event.source, event.message_pt, event.message_en, observed, observed,
                    linked_type, linked_id, event.result_state))
        db.execute("""UPDATE mobility_demo_runs SET current_index=?,elapsed_seconds=?,stage=?,state=?,
                    completed_at=?,lease_hash=?,lease_expires_at=?,updated_at=? WHERE id=?""",
                   (index + 1, max(float(run["elapsed_seconds"]), event.at_seconds, elapsed_seconds), stage, state, completed_at,
                    db.execute("SELECT lease_hash FROM mobility_demo_runs WHERE id=?", (run_id,)).fetchone()[0],
                    (datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)).isoformat(),
                    observed, run_id))
    if complete:
        _write_execution_report(run_id)


def _write_execution_report(run_id: str) -> None:
    run = demo_run(run_id)
    with connect() as db:
        events = [json.loads(row["receipt"]) for row in db.execute(
            "SELECT receipt FROM mobility_demo_events WHERE run_id=? ORDER BY event_index", (run_id,)).fetchall()]
        reports = [json.loads(row["payload"]) for row in db.execute(
            "SELECT payload FROM mobility_road_reports WHERE scenario_id=?", (run["scenario_id"],)).fetchall()]
    script, _ = load_demo_script()
    by_id = {item["event_id"]: item for item in events}
    heavy_segments = by_id.get("e013-assign-transport", {}).get("result", {}).get("segment_ids", [])
    reroute = by_id.get("e011-reroute-fire", {}).get("result", {})
    acknowledgment = by_id.get("e012-ack-route", {}).get("result", {})
    radio_location = by_id.get("e017-social-radio-location", {}).get("result", {})
    blockage = next((item for item in reports if item.get("kind") == "blocked"), {})
    reopening = next((item for item in reports if item.get("kind") == "reopening"), {})
    workspace = get_scenario(run["scenario_id"])
    groups = {group.category: group for group in workspace.resource_groups}
    source_team = next((team for team in workspace.teams if team.source_provenance), None)
    assertions = {
        "all_events_applied": len(events) == len(script.events),
        "completed": run["state"] == "completed",
        "heavy_vehicle_avoids_bridge": "ribeira-bridge" not in heavy_segments and "outer-road" in heavy_segments,
        "reroute_avoids_blockage": "north-access" not in reroute.get("segment_ids", []),
        "revised_brief_acknowledged": acknowledgment.get("acknowledged_brief_version") == acknowledgment.get("brief_version"),
        "radio_fallback_recorded": radio_location.get("source") == "radio",
        "reopening_resolved_restriction": blockage.get("status") == "dismissed" and reopening.get("status") == "confirmed",
        "fogos_groups_synchronized": [groups[key].reported_count for key in
            ("operacionais", "meios_terrestres", "meios_aereos")] == [
                script.fogos_resource_demo.synchronized.operacionais,
                script.fogos_resource_demo.synchronized.meios_terrestres,
                script.fogos_resource_demo.synchronized.meios_aereos],
        "local_resource_override_preserved": groups.get("operacionais") is not None
            and groups["operacionais"].planned_count_override == script.fogos_resource_demo.planned_operacionais,
        "converted_team_detached": source_team is not None
            and source_team.source_provenance.snapshot_id != groups["operacionais"].snapshot_id,
    }
    report = {"run_id": run_id, "scenario_id": run["scenario_id"], "script_id": run["script_id"],
              "script_version": run["script_version"], "script_checksum": run["script_checksum"],
              "fixture_checksum": run["fixture_checksum"], "state": run["state"],
              "events_applied": len(events), "events_expected": len(script.events),
              "assertions": assertions, "assertions_passed": all(assertions.values()),
              "events": events, "completed_at": run["completed_at"]}
    directory = settings.DEMO / "mobility-reports"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{run_id}.json"
    temporary = directory / f".{run_id}.tmp"
    temporary.write_text(json.dumps(report, indent=2))
    os.replace(temporary, target)


def _run_payload(row) -> dict[str, Any]:
    script, _ = load_demo_script()
    index = int(row["current_index"])
    next_event = script.events[index] if index < len(script.events) else None
    package_id = f"mobility-demo-v{script.version}-{row['fixture_checksum'][:12]}"
    report_path = settings.DEMO / "mobility-reports" / f"{row['id']}.json"
    return {key: row[key] for key in row.keys() if key != "lease_hash"} | {
        "speed": float(row["speed"]), "elapsed_seconds": float(row["elapsed_seconds"]),
        "current_index": index, "total_events": len(script.events), "duration_seconds": script.duration_seconds,
        "next_event": ({"id": next_event.id, "at_seconds": next_event.at_seconds,
                        "message_pt": next_event.message_pt, "message_en": next_event.message_en}
                       if next_event else None),
        "scenario_url": f"/scenarios/{row['scenario_id']}/mobility", "package_id": package_id,
        "report_path": str(report_path) if report_path.exists() else None, "is_demo": True,
    }


def _lease_row(db, run_id: str, token: str):
    row = db.execute("SELECT * FROM mobility_demo_runs WHERE id=? AND archived_at IS NULL", (run_id,)).fetchone()
    if not row:
        raise KeyError(run_id)
    expires = datetime.fromisoformat(row["lease_expires_at"]) if row["lease_expires_at"] else None
    if not row["lease_hash"] or not secrets.compare_digest(row["lease_hash"], _token_hash(token)):
        raise DemoConflict("The demo runner lease is not valid")
    if not expires or expires <= datetime.now(UTC):
        raise DemoConflict("The demo runner lease expired; start the runner again to resume")
    return row


def _entity(run_id: str, alias: str | None) -> str:
    if not alias:
        raise DemoConflict("Missing demo entity alias")
    with connect() as db:
        row = db.execute("SELECT record_id FROM mobility_demo_entities WHERE run_id=? AND alias=?",
                         (run_id, alias)).fetchone()
    if not row:
        raise DemoConflict(f"Unknown demo entity {alias}")
    return row["record_id"]


def _put_entity(run_id: str, alias: str, entity_type: str, record_id: str, payload: dict[str, Any]) -> None:
    with connect() as db:
        db.execute("INSERT INTO mobility_demo_entities VALUES (?,?,?,?,?) ON CONFLICT(run_id,alias) DO UPDATE SET record_id=excluded.record_id,payload=excluded.payload",
                   (run_id, alias, entity_type, record_id, json.dumps(payload)))


def _linked_entity(run_id: str, values: dict[str, Any]) -> tuple[str | None, str | None]:
    for field, entity_type in (("movement", "movement"), ("report", "road_report"), ("unit", "unit")):
        if values.get(field):
            return entity_type, _entity(run_id, values[field])
    return None, None


def _road_feature(package_id: str, segment_id: str) -> dict[str, Any]:
    collection = json.loads((package_path(package_id) / "roads.geojson").read_text())
    feature = next((item for item in collection["features"] if item["properties"]["segment_id"] == segment_id), None)
    if not feature:
        raise DemoConflict(f"Road segment {segment_id} is absent from the installed fixture")
    return feature


def _preflight_demo(scenario_id: str, package_id: str, script: DemoScript,
                    units: dict[str, OperationalUnit]) -> None:
    vehicles = {item["id"]: VehicleProfile.model_validate(item) for item in list_vehicles(scenario_id)}
    initial_locations = {item["alias"]: tuple(item["location"]) for item in script.units}
    assignments: dict[str, DemoEventDefinition] = {}
    for event in script.events:
        values = event.model_dump()
        if event.type != "assign":
            continue
        assignments[event.movement] = event
        unit = units[event.unit]
        request = MobilityRouteRequest(
            origin=RouteLocation(name=unit.callsign, coordinates=initial_locations[event.unit]),
            destination=RouteLocation.model_validate(script.destinations[values["destination"]]),
            vehicle_id=unit.vehicle_id, departure_at=datetime.now(UTC), alternatives=2)
        route = route_mobility(package_path(package_id), request, vehicles[unit.vehicle_id], [])
        if route["status"] == "unavailable":
            raise DemoConflict(f"Preflight found no route for {event.id}")
        if any(segment in route["segment_ids"] for segment in values.get("forbidden_segments") or []):
            raise DemoConflict(f"Preflight route for {event.id} violates its expected vehicle restriction")
    blocked = next((event for event in script.events if event.type == "road_report" and event.model_dump().get("kind") == "blocked"), None)
    revision = next((event for event in script.events if event.type == "revise_route"), None)
    if blocked and revision:
        assignment = assignments[revision.movement]
        unit = units[revision.unit]
        destination = script.destinations[assignment.model_dump()["destination"]]
        report = {"id": "preflight", "revision": 1, "status": "pending", "kind": "blocked",
                  "segment_id": blocked.model_dump()["segment_id"], "direction": "both",
                  "affected_vehicle_classes": []}
        route = route_mobility(package_path(package_id), MobilityRouteRequest(
            origin=RouteLocation(name=unit.callsign, coordinates=initial_locations[revision.unit]),
            destination=RouteLocation.model_validate(destination), vehicle_id=unit.vehicle_id,
            departure_at=datetime.now(UTC), alternatives=2), vehicles[unit.vehicle_id], [report])
        if route["status"] == "unavailable" or report["segment_id"] in route["segment_ids"]:
            raise DemoConflict("Preflight could not produce the scripted replacement route")


def _movement_result(value: dict[str, Any]) -> dict[str, Any]:
    return {"movement_id": value["id"], "status": value["status"], "revision": value["revision"],
            "brief_version": value["brief_version"],
            "acknowledged_brief_version": value.get("acknowledged_brief_version"),
            "segment_ids": value.get("route", {}).get("segment_ids", [])}


def _stage(offset: float, complete: bool = False) -> str:
    if complete:
        return "Demonstração concluída"
    if offset < 120:
        return "Atribuições e partidas"
    if offset < 225:
        return "Bloqueio e novo percurso"
    if offset < 285:
        return "Restrições por tipo de viatura"
    if offset < 345:
        return "Continuidade por rádio"
    return "Chegadas e conclusão"


def _duration() -> int:
    return load_demo_script()[0].duration_seconds


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fixture_checksum(script_checksum: str) -> str:
    return hashlib.sha256(f"{script_checksum}:fixture-builder-{FIXTURE_BUILDER_VERSION}".encode()).hexdigest()


def _haversine_m(start: tuple[float, float], end: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (*start, *end))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bounds(coordinates) -> list[float]:
    values = list(coordinates)
    lons, lats = [item[0] for item in values], [item[1] for item in values]
    return [min(lons) - .002, min(lats) - .002, max(lons) + .002, max(lats) + .002]
