from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fastapi import HTTPException
from starlette.requests import Request
import backend.app.area_packages as area_packages
import backend.app.fogos as fogos
import backend.app.settings as settings
import backend.app.storage as storage
from backend.app.mobility_demo import (DemoConflict, acquire_demo_lease, apply_demo_event,
                                       control_demo, create_demo_run, demo_run, demo_snapshot,
                                       heartbeat_demo, load_demo_script, scenario_demo_locked)
from backend.app.mobility_routing import _edge_segments, _graph
from backend.app.mobility_storage import init_mobility_db, list_road_reports
from backend.app.models import Scenario
from backend.app.storage import create_scenario, get_scenario, init_db
from backend.app.demo_api import _administrator


class MobilityDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous = (storage.DB, settings.AREAS, settings.DEMO, area_packages.AREAS)
        storage.DB = self.root / "platform.sqlite3"
        settings.AREAS = self.root / "areas"
        settings.DEMO = self.root / "demo"
        settings.AREAS.mkdir()
        settings.DEMO.mkdir()
        area_packages.AREAS = settings.AREAS
        _graph.cache_clear()
        _edge_segments.cache_clear()
        init_db()
        init_mobility_db()

    def tearDown(self):
        storage.DB, settings.AREAS, settings.DEMO, area_packages.AREAS = self.previous
        _graph.cache_clear()
        _edge_segments.cache_clear()
        self.temp.cleanup()

    def replay(self, *, restart: bool = False):
        run = create_demo_run("administrator", speed=2, restart=restart)
        token, _ = acquire_demo_lease(run["id"])
        script, _ = load_demo_script()
        receipts = []
        for event in script.events:
            receipts.append(apply_demo_event(run["id"], event.id, token, event.at_seconds))
            if demo_run(run["id"])["state"] != "completed":
                heartbeat_demo(run["id"], token, event.at_seconds)
        return demo_run(run["id"]), receipts

    @staticmethod
    def normalized(receipts):
        return [(item["event_id"], item["result"].get("status"), item["result"].get("state"),
                 tuple(item["result"].get("segment_ids", [])), item["result"].get("brief_version"),
                 item["result"].get("acknowledged_brief_version")) for item in receipts]

    def test_two_replays_have_the_same_business_outcome(self):
        first, receipts_one = self.replay()
        second, receipts_two = self.replay(restart=True)
        self.assertEqual(self.normalized(receipts_one), self.normalized(receipts_two))
        self.assertEqual(first["state"], "completed")
        self.assertEqual(second["current_index"], 25)
        self.assertTrue(Path(second["report_path"]).exists())
        report = json.loads(Path(second["report_path"]).read_text())
        self.assertTrue(report["assertions_passed"])

        transport = next(item for item in receipts_two if item["event_id"] == "e013-assign-transport")
        self.assertNotIn("ribeira-bridge", transport["result"]["segment_ids"])
        self.assertIn("outer-road", transport["result"]["segment_ids"])
        reroute = next(item for item in receipts_two if item["event_id"] == "e011-reroute-fire")
        self.assertNotIn("north-access", reroute["result"]["segment_ids"])
        self.assertNotEqual(reroute["result"]["brief_version"], reroute["result"]["acknowledged_brief_version"])

        reports = list_road_reports(second["scenario_id"])
        blockage = next(item for item in reports if item["kind"] == "blocked")
        reopening = next(item for item in reports if item["kind"] == "reopening")
        self.assertEqual(blockage["status"], "dismissed")
        self.assertEqual(reopening["status"], "confirmed")
        snapshot, communications = demo_snapshot(second["scenario_id"])
        self.assertEqual(snapshot["state"], "completed")
        self.assertEqual(len(communications), 25)
        workspace = get_scenario(second["scenario_id"])
        self.assertEqual([group.name for group in workspace.resource_groups],
                         ["Operacionais", "Meios terrestres", "Meios aéreos"])
        self.assertEqual([group.reported_count for group in workspace.resource_groups], [31, 11, 2])
        operacionais = workspace.resource_groups[0]
        self.assertEqual(operacionais.planned_count_override, 18)
        self.assertIn("sintética", operacionais.notes)
        self.assertEqual(len(workspace.teams), 1)
        provenance = workspace.teams[0].source_provenance
        self.assertEqual(provenance.reported_count, 24)
        self.assertEqual(provenance.planned_count, 18)
        self.assertNotEqual(provenance.snapshot_id, operacionais.snapshot_id)
        self.assertEqual(len(fogos.snapshots(workspace.external_incident["incident_id"], "incident")), 2)

    def test_lease_controls_duplicate_delivery_and_restart_isolation(self):
        normal = create_scenario(Scenario(name="Existing", ignitions=[{
            "id": "existing-fire", "name": "Existing", "coordinates": (-8.2, 41.4), "start_min": 0,
        }]), scenario_id="existing-scenario")
        run = create_demo_run("administrator")
        token, _ = acquire_demo_lease(run["id"])
        with self.assertRaises(DemoConflict):
            acquire_demo_lease(run["id"])
        self.assertEqual(heartbeat_demo(run["id"], token, 10)["elapsed_seconds"], 10)
        self.assertEqual(control_demo(run["id"], "pause")["state"], "paused")
        self.assertEqual(heartbeat_demo(run["id"], token, 100)["elapsed_seconds"], 10)
        self.assertEqual(control_demo(run["id"], "resume")["state"], "running")
        receipt = apply_demo_event(run["id"], "e001-ready", token, 0)
        duplicate = apply_demo_event(run["id"], "e001-ready", token, 0)
        self.assertEqual(receipt, duplicate)
        self.assertTrue(scenario_demo_locked(run["scenario_id"]))

        replacement = create_demo_run("administrator", restart=True)
        self.assertNotEqual(replacement["scenario_id"], run["scenario_id"])
        self.assertEqual(demo_run(run["id"])["state"], "archived")
        self.assertFalse(scenario_demo_locked(run["scenario_id"]))
        self.assertEqual(get_scenario(normal.id).name, "Existing")

    def test_internal_endpoints_are_disabled_and_require_an_administrator(self):
        request = Request({"type": "http", "method": "GET", "path": "/api/internal/demo/status",
                           "headers": [], "query_string": b""})
        with patch.dict("os.environ", {"FIRELINE_DEMO_ENABLED": "0"}):
            with self.assertRaises(HTTPException) as disabled:
                _administrator(request)
            self.assertEqual(disabled.exception.status_code, 404)
        request.state.user = {"id": "dispatcher", "username": "dispatcher",
                              "display_name": "Dispatcher", "role": "dispatcher"}
        with patch.dict("os.environ", {"FIRELINE_DEMO_ENABLED": "1"}):
            with self.assertRaises(HTTPException) as forbidden:
                _administrator(request)
            self.assertEqual(forbidden.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
