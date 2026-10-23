from __future__ import annotations

import tempfile
import json
import asyncio
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from fastapi import HTTPException
from starlette.requests import Request
from rasterio.transform import from_origin

import backend.app.storage as storage
from backend.app import mobility_api, worker
from backend.app import main as api_main
from backend.app.engines import _discover
import backend.app.engines as engine_registry
from backend.app.engines.contract import EngineDescriptor
from backend.app.io import load_result, save_result
from backend.app.mobility_routing import _report_index, preview_signature, restrictions_revision
from backend.app.mobility_storage import (MobilityConflict, create_movement, create_user, init_mobility_db,
    list_water_reports, review_road_report, review_water_report, save_road_report, save_unit,
    save_vehicle, save_water_report, water_statuses, login, session_user)
from backend.app.models import (Landscape, MobilityRouteRequest, MovementCreate, OperationalUnit, RoadReport, RouteLocation,
    Scenario, ScenarioPoint, SimulationResult, VehicleProfile, WaterSourceReportCreate, RoadReportReview,
    MovementAction,
    WaterSourceReportReview)


class ConsolidatedMobilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = storage.DB
        storage.DB = Path(self.temp.name) / "test.sqlite3"
        storage.init_db(); init_mobility_db()
        storage.create_scenario(Scenario(ignition=(-8.28, 41.43)), scenario_id="incident",
            points=[ScenarioPoint(id="water-1", kind="water_point", name="Reservoir",
                                  coordinates=(-8.28, 41.44))])
        self.vehicle = VehicleProfile(name="Patrol", vehicle_class="light")
        self.unit = OperationalUnit(organisation="Fire", callsign="F1", vehicle_id=self.vehicle.id)
        save_vehicle("incident", self.vehicle); save_unit("incident", self.unit)
        self.request = SimpleNamespace(state=SimpleNamespace(user={"id": "dispatcher", "role": "dispatcher"}))

    def tearDown(self):
        storage.DB = self.old_db
        self.temp.cleanup()

    def value(self, signature="correct"):
        return MovementCreate(unit_id=self.unit.id, vehicle_id=self.vehicle.id, purpose="Reach village",
            origin=RouteLocation(name="Base", coordinates=(-8.29, 41.43)),
            destination=RouteLocation(name="Village", coordinates=(-8.28, 41.44)),
            departure_at=datetime.now(UTC), preview_signature=signature)

    def route(self, status="clear"):
        return {"status": status, "preview_signature": "correct", "vehicle_revision": 1,
                "restrictions_revision": restrictions_revision([]), "segment_ids": ["road-1"],
                "selected": {"road_names": ["Road 1"]}}

    def test_assignment_requires_current_signed_server_route(self):
        with patch.object(mobility_api, "preview_route", return_value=self.route()):
            with self.assertRaises(HTTPException) as raised:
                mobility_api.assign_movement("incident", self.value("spoofed"), self.request)
            self.assertEqual(raised.exception.status_code, 409)
            value = self.value(); value.route = {"status": "clear", "segment_ids": ["spoofed"]}
            assigned = mobility_api.assign_movement("incident", value, self.request)
        self.assertEqual(assigned["route"]["segment_ids"], ["road-1"])
        self.assertNotIn("preview_signature", assigned)

    def test_preview_signature_covers_route_vehicle_and_restrictions(self):
        value = self.value()
        request = MobilityRouteRequest(origin=value.origin, destination=value.destination,
                                       vehicle_id=value.vehicle_id, departure_at=value.departure_at)
        route = self.route()
        original = preview_signature(request, route, self.vehicle)
        changed = {**route, "segment_ids": ["road-2"]}
        self.assertNotEqual(original, preview_signature(request, changed, self.vehicle))
        changed = {**route, "restrictions_revision": "new"}
        self.assertNotEqual(original, preview_signature(request, changed, self.vehicle))
        self.assertNotEqual(original, preview_signature(request, route, self.vehicle.model_copy(update={"width_m": 2.5})))

    def test_report_change_invalidates_assignment_in_storage(self):
        save_road_report("incident", RoadReport(segment_id="road-1", kind="blocked", road_name="Road 1",
            reason="Smoke", source="dispatcher", observed_at=datetime.now(UTC)))
        with patch.object(mobility_api, "preview_route", return_value=self.route()):
            with self.assertRaises(HTTPException) as raised:
                mobility_api.assign_movement("incident", self.value(), self.request)
        self.assertEqual(raised.exception.status_code, 409)

    def test_prepared_road_revision_invalidates_assignment(self):
        route = {**self.route(), "prepared_revision": "outdated"}
        with self.assertRaises(MobilityConflict):
            create_movement("incident", self.value(), route=route)

    def test_unavailable_unit_vehicle_or_route_cannot_be_assigned(self):
        mismatched = VehicleProfile(name="Other", vehicle_class="light")
        save_vehicle("incident", mismatched)
        value = self.value(); value.vehicle_id = mismatched.id
        with self.assertRaises(MobilityConflict):
            create_movement("incident", value, route=self.route())
        with self.assertRaises(MobilityConflict):
            create_movement("incident", self.value(), route=self.route("unavailable"))
        with storage.connect() as db:
            row = db.execute("SELECT payload FROM mobility_units WHERE id=?", (self.unit.id,)).fetchone()
            unit = json.loads(row["payload"]); unit["status"] = "unavailable"
            db.execute("UPDATE mobility_units SET payload=? WHERE id=?", (json.dumps(unit), self.unit.id))
        with self.assertRaises(MobilityConflict):
            create_movement("incident", self.value(), route=self.route())
        with storage.connect() as db:
            unit["status"] = "available"
            db.execute("UPDATE mobility_units SET payload=? WHERE id=?", (json.dumps(unit), self.unit.id))
            row = db.execute("SELECT payload FROM mobility_vehicles WHERE id=?", (self.vehicle.id,)).fetchone()
            vehicle = json.loads(row["payload"]); vehicle["available"] = False
            db.execute("UPDATE mobility_vehicles SET payload=? WHERE id=?", (json.dumps(vehicle), self.vehicle.id))
        with self.assertRaises(MobilityConflict):
            create_movement("incident", self.value(), route=self.route())

    def test_unmatched_report_stays_out_of_routing_until_matched(self):
        report = save_road_report("incident", RoadReport(kind="blocked", road_name="Unknown", reason="Tree",
            observed_location=(-8.28, 41.44), source="crew", observed_at=datetime.now(UTC)))
        self.assertIsNone(report["segment_id"])
        with self.assertRaises(MobilityConflict):
            review_road_report("incident", report["id"], "confirmed", 1)
        matched = review_road_report("incident", report["id"], "confirmed", 1,
                                     segment_id="road-1", direction="forward")
        self.assertEqual((matched["segment_id"], matched["direction"]), ("road-1", "forward"))

    def test_matched_pending_restriction_is_conservative(self):
        pending = save_road_report("incident", RoadReport(segment_id="road-1", kind="blocked",
            road_name="Road 1", reason="Smoke", source="dispatcher", observed_at=datetime.now(UTC)))
        self.assertIn("road-1", _report_index([pending]))
        unmatched = save_road_report("incident", RoadReport(kind="blocked", road_name="Unknown",
            reason="Smoke", source="crew", observed_at=datetime.now(UTC)))
        self.assertNotIn(None, _report_index([unmatched]))

    def test_water_review_records_observation_and_reviewer(self):
        report = save_water_report("incident", "water-1", "unavailable", "Dry", datetime.now(UTC).isoformat(),
                                   "crew-1", "crew")
        self.assertEqual(water_statuses("incident"), {})
        reviewed = review_water_report("incident", report["id"], "confirmed", 1, "dispatcher-1")
        self.assertEqual(reviewed["reporter_id"], "crew-1")
        self.assertEqual(reviewed["reviewer_id"], "dispatcher-1")
        self.assertEqual(water_statuses("incident")["water-1"]["availability"], "unavailable")
        self.assertEqual(list_water_reports("incident")[0]["observed_at"], report["observed_at"])

    def test_crew_source_report_requires_dispatch_review_in_snapshot(self):
        crew = SimpleNamespace(state=SimpleNamespace(user={"id": "crew-1", "role": "crew"}))
        with storage.connect() as db:
            db.execute("INSERT INTO mobility_memberships VALUES (?,?,?)", ("incident", "crew-1", self.unit.id))
        report = mobility_api.add_water_report("incident", WaterSourceReportCreate(
            point_id="water-1", availability="unavailable", note="Dry", observed_at=datetime.now(UTC)), crew)
        pending = mobility_api.mobility_snapshot("incident", self.request)
        self.assertEqual(pending["water_sources"][0]["water"]["availability"], "unknown")
        self.assertEqual(pending["water_reports"][0]["status"], "pending")
        mobility_api.review_source_report("incident", report["id"],
            WaterSourceReportReview(status="confirmed", expected_revision=1), self.request)
        confirmed = mobility_api.mobility_snapshot("incident", self.request)
        self.assertEqual(confirmed["water_sources"][0]["water"]["availability"], "unavailable")

    def test_archive_gets_work_and_retired_writes_return_410(self):
        request = Request({"type": "http", "method": "POST", "path": "/api/scenarios/incident/missions",
                           "query_string": b"", "headers": []})
        async def next_request(_request):
            raise AssertionError("Retired action reached its write handler")
        response = asyncio.run(api_main.shared_server_authentication(request, next_request))
        self.assertEqual(response.status_code, 410)
        self.assertIn(b"/scenarios/incident/mobility", response.body)

    def test_dispatcher_and_crew_journey_and_report_flow(self):
        user = create_user("crew-flow", "Crew flow", "long-test-password", "crew")
        with storage.connect() as db:
            db.execute("INSERT INTO mobility_memberships VALUES (?,?,?)", ("incident", user["id"], self.unit.id))
        token, _ = login("crew-flow", "long-test-password")
        crew = SimpleNamespace(state=SimpleNamespace(user=session_user(token)))
        with patch.object(mobility_api, "preview_route", return_value=self.route()):
            assigned = mobility_api.assign_movement("incident", self.value(), self.request)
        movement = mobility_api.mobility_snapshot("incident", crew)["movements"][0]
        self.assertEqual(movement["id"], assigned["id"])
        accepted = mobility_api.movement_action("incident", movement["id"], MovementAction(
            action="accept", expected_revision=1, expected_brief_version=1,
            request_id="crew-flow-action-1"), crew)
        self.assertEqual(accepted["status"], "accepted")
        reported = mobility_api.add_report("incident", RoadReport(segment_id="road-1", road_name="Road 1",
            kind="blocked", reason="Tree", observed_location=(-8.28, 41.44),
            observed_at=datetime.now(UTC)), crew)
        self.assertIsNone(reported["segment_id"])
        with patch.object(mobility_api, "mobility_roads", return_value={"features": [{"properties": {"segment_id": "road-1"}}]}):
            mobility_api.review_report("incident", reported["id"], RoadReportReview(
                status="confirmed", expected_revision=1, segment_id="road-1", direction="both"), self.request)
        self.assertTrue(mobility_api.mobility_snapshot("incident", self.request)["movements"][0]["needs_review"])
        source = mobility_api.add_water_report("incident", WaterSourceReportCreate(
            point_id="water-1", availability="unavailable", note="Dry",
            observed_at=datetime.now(UTC)), crew)
        self.assertEqual(mobility_api.mobility_snapshot("incident", self.request)["water_sources"][0]["water"]["availability"], "unknown")
        mobility_api.review_source_report("incident", source["id"],
            WaterSourceReportReview(status="confirmed", expected_revision=1), self.request)
        self.assertEqual(mobility_api.mobility_snapshot("incident", self.request)["water_sources"][0]["water"]["availability"], "unavailable")


class EngineRegistryTests(unittest.TestCase):
    def test_entry_point_loads_and_duplicate_or_broken_adapter_fails_safely(self):
        descriptor = EngineDescriptor("sample", "Sample", ("default",), "default", ("constant",),
                                      "local-process", "low", (), execution_pool="thread", concurrency_key="sample")
        adapter = SimpleNamespace(descriptor=descriptor, available=lambda: (True, "ready"),
                                  validate=lambda scenario: None, simulate=lambda *args: None)
        entries = [SimpleNamespace(name="sample", load=lambda: adapter),
                   SimpleNamespace(name="mtt", load=lambda: adapter),
                   SimpleNamespace(name="broken", load=lambda: 1 / 0)]
        with patch("backend.app.engines.entry_points", return_value=entries):
            engines, failures = _discover()
        self.assertIn("sample", engines)
        self.assertEqual(set(engines), {"mtt", "cell2fire", "sample"})
        self.assertIn("mtt", failures)
        self.assertIn("broken", failures)
        with patch.object(engine_registry, "ENGINES", engines), patch.object(engine_registry, "ENGINE_FAILURES", failures):
            listed = engine_registry.available_engines()
        self.assertTrue(any(item["id"] == "sample" and item["available"] for item in listed))
        self.assertTrue(any(item["id"] == "broken" and not item["available"] for item in listed))
        with patch.dict(api_main.ENGINES, {"sample": adapter}):
            api_main._validate_request(api_main.RunCreate(
                scenario=Scenario(engine="sample", ignition=(-8.28, 41.43))))

    def test_bad_result_is_rejected_before_publish(self):
        coverage = np.ones((2, 2), dtype=bool)
        landscape = Landscape(np.ones((2, 2)), np.ones((2, 2)), np.zeros((2, 2)), np.zeros((2, 2)),
                              coverage, from_origin(0, 60, 30, 30), "EPSG:3763", 30, {"test": True})
        result = SimulationResult(np.zeros((3, 3)), coverage, landscape.transform, landscape.crs,
                                  1, "sample", "1", {"input": "test"})
        with self.assertRaisesRegex(ValueError, "grid shape"):
            worker.validate_result(result, landscape, "sample")

    def test_historical_unregistered_engine_result_remains_readable(self):
        with patch("backend.app.engines.entry_points", return_value=[]):
            self.assertNotIn("farsite", _discover()[0])
        old = SimulationResult(np.zeros((2, 2)), np.ones((2, 2), dtype=bool),
                               from_origin(0, 60, 30, 30), "EPSG:3763", 5,
                               "farsite", "legacy", {"source": "archive"})
        with tempfile.TemporaryDirectory() as folder:
            save_result(old, Path(folder))
            self.assertEqual(load_result(Path(folder)).engine, "farsite")
            previous_db = storage.DB
            storage.DB = Path(folder) / "history.sqlite3"
            try:
                storage.init_db()
                scenario = storage.create_scenario(Scenario(engine="farsite", ignition=(-8.28, 41.43)))
                run = storage.create_run(scenario.simulation, scenario_id=scenario.id)
                result_dir = Path(folder) / "runs" / run.id
                save_result(old, result_dir)
                storage.update_run(run.id, status="ready", stage="ready", progress=100)
                with patch.object(api_main, "RUNS", Path(folder) / "runs"):
                    self.assertEqual(api_main.run_status(run.id)["result"]["engine"], "farsite")
            finally:
                storage.DB = previous_db

    def test_retired_mutations_and_new_comparisons_are_disabled(self):
        self.assertTrue(api_main._retired_action("/api/scenarios/incident/missions"))
        self.assertTrue(api_main._retired_action("/api/scenarios/incident/allocation-plans/rank"))
        self.assertFalse(api_main._retired_action("/api/scenarios/incident/mobility/movements"))
        with self.assertRaises(Exception) as raised:
            api_main._validate_request(api_main.RunCreate(
                scenario=Scenario(ignition=(-8.28, 41.43)), mode="parameter_ensemble",
                ensemble={"kind": "parameter", "preset": "quick"}))
        self.assertEqual(raised.exception.status_code, 410)
