from __future__ import annotations

import sqlite3
import tempfile
import unittest
import json
from pathlib import Path

from backend.app import main, storage
from backend.app.models import PointImport, RoadClosure, Scenario, ScenarioCreate, ScenarioPatch, ScenarioPoint, ScenarioRename, ScenarioRunCreate
from fastapi import HTTPException
from pydantic import ValidationError
from backend.app.settings import CONFIG


class ScenarioStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.original_db = storage.DB
        self.original_prepared = main.PREPARED
        self.original_presets = main.WATER_PRESETS
        storage.DB = Path(self.temporary.name) / "test.sqlite3"
        main.PREPARED = Path(self.temporary.name)
        main.WATER_PRESETS = Path(self.temporary.name) / "presets.geojson"

    def tearDown(self) -> None:
        storage.DB = self.original_db
        main.PREPARED = self.original_prepared
        main.WATER_PRESETS = self.original_presets
        self.temporary.cleanup()

    def test_revision_conflict_and_run_snapshot(self) -> None:
        storage.init_db()
        simulation = Scenario(name="Exercise", ignition=(-8.27, 41.43))
        workspace = storage.create_scenario(simulation)
        changed = storage.update_scenario(workspace.id, ScenarioPatch(
            expected_revision=1, name="Exercise", description="Changed", area_id=workspace.area_id,
            simulation=simulation.model_copy(update={"wind_speed_kmh": 40}), points=[],
        ))
        self.assertEqual(changed.revision, 2)
        run = storage.create_run(changed.simulation, scenario_id=changed.id, scenario_revision=changed.revision)
        storage.update_scenario(changed.id, ScenarioPatch(
            expected_revision=2, name="Exercise", description="Changed again", area_id=workspace.area_id,
            simulation=changed.simulation.model_copy(update={"wind_speed_kmh": 60}), points=[],
        ))
        self.assertEqual(storage.get_run(run.id).scenario.wind_speed_kmh, 40)
        self.assertEqual(storage.get_run(run.id).scenario_revision, 2)
        with self.assertRaises(storage.ScenarioConflictError):
            storage.update_scenario(changed.id, ScenarioPatch(
                expected_revision=2, name="Stale", area_id=workspace.area_id,
                simulation=changed.simulation, points=[],
            ))

    def test_run_snapshots_the_scenario_area_package(self) -> None:
        storage.init_db()
        simulation = Scenario(name="Area", ignition=(-8.27, 41.43))
        workspace = storage.create_scenario(simulation, area_id="package-one", area_package_id="package-one",
                                            resource_center=(-8.27, 41.43))
        run = storage.create_run(workspace.simulation, scenario_id=workspace.id,
                                 scenario_revision=workspace.revision)
        changed = storage.update_scenario(workspace.id, ScenarioPatch(
            expected_revision=workspace.revision, name=workspace.name, area_id="package-two",
            area_package_id="package-two", resource_center=(-8.1, 41.2),
            simulation=workspace.simulation, points=[]))
        self.assertEqual(changed.area_package_id, "package-two")
        self.assertEqual(storage.get_run(run.id).area_package_id, "package-one")

    def test_cell_size_defaults_for_legacy_scenarios_and_persists_updates(self) -> None:
        storage.init_db()
        workspace = storage.create_scenario(Scenario(name="Grid", ignition=(-8.27, 41.43)))
        self.assertEqual(workspace.cell_size_m, 30)
        changed = storage.update_scenario(workspace.id, ScenarioPatch(
            expected_revision=workspace.revision, name=workspace.name,
            area_id="fine-package", area_package_id="fine-package", cell_size_m=10,
            simulation=workspace.simulation, points=[]))
        self.assertEqual(changed.cell_size_m, 10)

        legacy = json.loads(storage.ScenarioDefinition(simulation=workspace.simulation).model_dump_json())
        legacy.pop("cell_size_m")
        self.assertEqual(storage.ScenarioDefinition.model_validate(legacy).cell_size_m, 30)

    def test_legacy_migration_is_idempotent_and_links_children(self) -> None:
        scenario = Scenario(name="Legacy", ignition=(-8.27, 41.43))
        with sqlite3.connect(storage.DB) as db:
            db.execute("""CREATE TABLE runs (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, stage TEXT NOT NULL,
                progress INTEGER NOT NULL, scenario TEXT NOT NULL, error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, demo INTEGER DEFAULT 0,
                mode TEXT NOT NULL DEFAULT 'single', parent_id TEXT, member_index INTEGER,
                runner TEXT, external_job_id TEXT, expected_members INTEGER, ensemble TEXT
            )""")
            values = ("parent", "ready", "ready", 100, scenario.model_dump_json(), None,
                      "2026-01-01", "2026-01-01", 0, "parameter_ensemble", None, None, None, None, 1, None)
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
            child = list(values); child[0] = "child"; child[10] = "parent"; child[9] = "single"
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", child)
        storage.init_db(); storage.init_db()
        self.assertEqual(len(storage.list_scenarios()), 1)
        parent = storage.get_run("parent"); child_run = storage.get_run("child")
        self.assertEqual(parent.scenario_id, child_run.scenario_id)
        self.assertEqual(parent.scenario_revision, 1)

    def test_rename_preserves_context_and_result_snapshot(self) -> None:
        storage.init_db()
        point = ScenarioPoint(kind="asset", name="House", coordinates=(-8.27, 41.43))
        workspace = storage.create_scenario(Scenario(name="Original", ignition=(-8.27, 41.43)),
                                            description="Keep this", points=[point])
        run = storage.create_run(workspace.simulation, scenario_id=workspace.id, scenario_revision=1)
        changed = main.rename_scenario_name(workspace.id, ScenarioRename(name="  Renamed  ", expected_revision=1))
        self.assertEqual(changed["name"], "Renamed")
        self.assertEqual(changed["simulation"]["name"], "Renamed")
        self.assertEqual(changed["description"], "Keep this")
        self.assertEqual(changed["points"][0]["id"], point.id)
        self.assertEqual(changed["revision"], 2)
        self.assertEqual(storage.get_run(run.id).scenario.name, "Original")
        with self.assertRaises(HTTPException) as conflict:
            main.rename_scenario_name(workspace.id, ScenarioRename(name="Stale", expected_revision=1))
        self.assertEqual(conflict.exception.status_code, 409)

    def test_names_reject_blank_and_overlong_values(self) -> None:
        for name in ["", "   ", "x" * 121]:
            with self.assertRaises(ValidationError):
                ScenarioRename(name=name, expected_revision=1)
            with self.assertRaises(ValidationError):
                ScenarioCreate(name=name)
            with self.assertRaises(ValidationError):
                ScenarioPatch(name=name, expected_revision=1, simulation=Scenario(ignition=(-8.27, 41.43)))

    def test_delete_hides_results_and_does_not_resurrect_demo_on_restart(self) -> None:
        storage.init_db()
        simulation = Scenario(name="Demo", ignition=(-8.27, 41.43))
        run = storage.create_run(simulation, demo=True, run_id="penha-east", mode="parameter_ensemble")
        child = storage.create_run(simulation, demo=True, parent_id=run.id)
        other = storage.create_scenario(simulation, name="Keep")
        main.remove_scenario(run.scenario_id, expected_revision=1)
        self.assertEqual([s.id for s in storage.list_scenarios()], [other.id])
        self.assertEqual(storage.list_runs(include_children=True), [])
        for run_id in [run.id, child.id]:
            with self.assertRaises(HTTPException) as missing:
                main.run_status(run_id)
            self.assertEqual(missing.exception.status_code, 404)
        with self.assertRaises(HTTPException) as missing:
            main.scenario_run_history(run.scenario_id)
        self.assertEqual(missing.exception.status_code, 404)
        with self.assertRaises(KeyError):
            storage.create_run(simulation, scenario_id=run.scenario_id)
        with self.assertRaises(HTTPException) as missing:
            main.rename_scenario_name(run.scenario_id, ScenarioRename(name="Revive", expected_revision=1))
        self.assertEqual(missing.exception.status_code, 404)
        storage.init_db()
        storage.create_run(simulation, demo=True, run_id="penha-east")
        self.assertEqual([s.id for s in storage.list_scenarios()], [other.id])
        self.assertEqual(storage.list_runs(), [])
        main.remove_scenario(other.id, expected_revision=1)
        self.assertEqual(storage.list_scenarios(), [])
        self.assertIsNotNone(storage.create_scenario(simulation))

    def test_delete_checks_revision_and_active_child_runs(self) -> None:
        storage.init_db()
        run = storage.create_run(Scenario(ignition=(-8.27, 41.43)), demo=True, mode="engine_comparison")
        child = storage.create_run(run.scenario, parent_id=run.id)
        with self.assertRaises(HTTPException) as conflict:
            main.remove_scenario(run.scenario_id, expected_revision=9)
        self.assertEqual(conflict.exception.status_code, 409)
        for status in ["queued", "preparing", "submitted", "running", "postprocessing"]:
            storage.update_run(child.id, status=status)
            with self.assertRaises(HTTPException) as busy:
                main.remove_scenario(run.scenario_id, expected_revision=1)
            self.assertEqual(busy.exception.status_code, 409)
            self.assertIn("active simulation", busy.exception.detail)
        storage.update_run(child.id, status="cancelled")
        main.remove_scenario(run.scenario_id, expected_revision=1)
        with self.assertRaises(HTTPException) as missing:
            main.remove_scenario(run.scenario_id, expected_revision=1)
        self.assertEqual(missing.exception.status_code, 404)

    def test_experiment_metadata_is_editable_without_changing_snapshot(self) -> None:
        storage.init_db()
        workspace = storage.create_scenario(Scenario(name="Scenario", ignition=(-8.27, 41.43)))
        run = storage.create_run(workspace.simulation, scenario_id=workspace.id,
                                 scenario_revision=workspace.revision, name="Baseline", notes="First note")
        changed = storage.update_run_metadata(run.id, "Wind trial", "Second note", 1)
        self.assertEqual(changed.name, "Wind trial")
        self.assertEqual(changed.notes, "Second note")
        self.assertEqual(changed.metadata_revision, 2)
        self.assertEqual(changed.scenario.name, "Scenario")
        with self.assertRaises(storage.RunConflictError):
            storage.update_run_metadata(run.id, "Stale", "", 1)

    def test_metadata_only_scenario_requires_setup_before_experiments(self) -> None:
        storage.init_db()
        created = main.add_scenario(ScenarioCreate(name="Draft", description="Context first", area_id="unprepared"))
        self.assertFalse(created["setup_complete"])
        self.assertEqual(created["description"], "Context first")
        with self.assertRaises(HTTPException) as blocked:
            main.queue_scenario_run(created["id"], ScenarioRunCreate(name="Too early"))
        self.assertEqual(blocked.exception.status_code, 409)
        self.assertIn("Complete scenario", blocked.exception.detail)

    def test_experiment_deletion_hides_members_and_protects_dependencies(self) -> None:
        storage.init_db()
        workspace = storage.create_scenario(Scenario(name="Scenario", ignition=(-8.27, 41.43)))
        source = storage.create_run(workspace.simulation, demo=True, scenario_id=workspace.id,
                                    scenario_revision=1, name="Source")
        dependency = storage.create_run(workspace.simulation, demo=True, mode="allocation_comparison",
                                        ensemble={"kind": "allocation", "source_run_id": source.id},
                                        scenario_id=workspace.id, scenario_revision=1,
                                        name="Containment comparison")
        child = storage.create_run(workspace.simulation, demo=True, parent_id=dependency.id)
        with self.assertRaises(storage.RunDependencyError):
            storage.delete_run(source.id, 1)
        storage.delete_run(dependency.id, 1)
        with self.assertRaises(KeyError):
            storage.get_run(dependency.id)
        with self.assertRaises(KeyError):
            storage.get_run(child.id)
        storage.delete_run(source.id, 1)
        self.assertEqual(storage.scenario_runs(workspace.id), [])

    def test_water_point_defaults_are_explicit(self) -> None:
        point = ScenarioPoint(kind="water_point", name="Manual point", coordinates=(-8.27, 41.43))
        self.assertIsNotNone(point.water)
        self.assertEqual(point.water.availability, "unknown")
        self.assertIsNone(point.water.capacity_m3)

    def test_timed_road_closures_persist_with_the_scenario(self) -> None:
        storage.init_db()
        workspace = storage.create_scenario(Scenario(name="Closures", ignition=(-8.27, 41.43)))
        closure = RoadClosure(segment_id="road-1", road_name="Forest road", starts_min=25,
                              ends_min=60, reason="Police report",
                              geometry={"type": "LineString", "coordinates": [[-8.28, 41.42], [-8.27, 41.43]]})
        changed = storage.update_scenario(workspace.id, ScenarioPatch(
            expected_revision=1, name=workspace.name, area_id=workspace.area_id,
            simulation=workspace.simulation, points=[], closures=[closure],
        ))
        self.assertEqual(changed.closures[0].segment_id, "road-1")
        self.assertEqual(changed.closures[0].starts_min, 25)

    def test_catalog_import_keeps_provenance_and_deduplicates(self) -> None:
        storage.init_db()
        workspace = storage.create_scenario(Scenario(name="Import", ignition=(-8.27, 41.43)))
        catalog = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": {"type": "Point", "coordinates": [-8.28, 41.44]},
            "properties": {"external_id": "node/123", "name": "Hydrant", "source_type": "hydrant"},
        }]}
        (main.PREPARED / "water-points.geojson").write_text(json.dumps(catalog))
        first = main.import_points(workspace.id, PointImport(expected_revision=1, external_ids=["node/123"]))
        second = main.import_points(workspace.id, PointImport(expected_revision=first["revision"], external_ids=["node/123"]))
        self.assertEqual(len(second["points"]), 1)
        self.assertEqual(second["points"][0]["source"], "openstreetmap")
        self.assertEqual(second["points"][0]["external_id"], "node/123")

    def test_bundled_presets_work_offline_and_preserve_icnf_details(self) -> None:
        storage.init_db()
        workspace = storage.create_scenario(Scenario(name="Presets", ignition=(-8.27, 41.43)))
        main.WATER_PRESETS.write_text(self.original_presets.read_text())
        # Failed optional OSM preparation must not erase the bundled presets.
        (main.PREPARED / "water-points.geojson").write_text(json.dumps({
            "type": "FeatureCollection", "features": [], "metadata": {"status": "fetch_failed"},
        }))
        catalog = main.area_water_points(workspace.area_id)
        self.assertEqual(len(catalog["features"]), 44)
        first = main.import_points(workspace.id, PointImport(expected_revision=1, external_ids=["icnf/0308-1"]))
        point = first["points"][0]
        self.assertEqual(point["source"], "icnf")
        self.assertEqual(point["source_updated_at"], "2018-06-19")
        self.assertIn("sigservices.icnf.pt", point["source_url"])
        self.assertEqual(point["data_status"], "reported")
        self.assertEqual(point["water"]["capacity_m3"], 1200)
        self.assertEqual(point["water"]["availability"], "unknown")
        self.assertEqual(point["water"]["verification_status"], "reported")
        self.assertIn("historical", point["notes"])
        self.assertIn("Ownership", point["water"]["access_notes"])
        second = main.import_points(workspace.id, PointImport(
            expected_revision=first["revision"], external_ids=["icnf/0308-1"]))
        self.assertEqual(len(second["points"]), 1)

    def test_all_presets_import_without_claiming_current_availability(self) -> None:
        storage.init_db()
        workspace = storage.create_scenario(Scenario(name="All presets", ignition=(-8.27, 41.43)))
        main.WATER_PRESETS.write_text(self.original_presets.read_text())
        catalog = main.area_water_points(workspace.area_id)
        ids = [f["properties"]["external_id"] for f in catalog["features"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(f["properties"]["municipality"] == "Guimarães" for f in catalog["features"]))
        result = main.import_points(workspace.id, PointImport(expected_revision=1, external_ids=ids))
        self.assertEqual(len(result["points"]), 44)
        self.assertTrue(all(p["water"]["availability"] == "unknown" for p in result["points"]))
        damaged = next(p for p in result["points"] if p["external_id"] == "icnf/48848")
        self.assertIn("Ruptura", damaged["notes"])

    def test_configured_area_contains_every_water_point_preset(self) -> None:
        catalog = json.loads(self.original_presets.read_text())
        west, south, east, north = CONFIG["area"]["bounds"]
        coordinates = [feature["geometry"]["coordinates"] for feature in catalog["features"]]
        self.assertTrue(all(west <= longitude <= east and south <= latitude <= north
                            for longitude, latitude in coordinates))


if __name__ == "__main__":
    unittest.main()
