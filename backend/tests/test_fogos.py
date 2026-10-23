from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi import HTTPException
from pyproj import Transformer
from rasterio.transform import from_origin

from backend.app import fogos, main, storage, weather
from backend.app.io import save_result
from backend.app.models import (FogosResourceSync, ResponseTeam, Scenario, ScenarioPatch,
                                ScenarioPoint, SimulationResult)
from backend.app.services import observation


class FogosIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.original_db = storage.DB
        self.original_runs = observation.RUNS
        self.original_weather = weather.WEATHER
        storage.DB = Path(self.temporary.name) / "test.sqlite3"
        observation.RUNS = Path(self.temporary.name) / "runs"
        weather.WEATHER = Path(self.temporary.name) / "weather"
        observation.RUNS.mkdir()
        weather.WEATHER.mkdir()
        fogos._CACHE.clear()
        storage.init_db()

    def tearDown(self) -> None:
        storage.DB = self.original_db
        observation.RUNS = self.original_runs
        weather.WEATHER = self.original_weather
        self.temporary.cleanup()

    def incident(self, **changes):
        value = {
            "id": "20260001", "dateTime": {"sec": 1_700_000_000}, "updated": {"sec": 1_700_000_300},
            "location": "Serra de Teste", "concelho": "Guimarães", "district": "Braga",
            "lat": 41.45, "lng": -8.30, "naturezaCode": "3101", "natureza": "Incêndio rural",
            "status": "Em Curso", "statusCode": 5, "active": True, "isFire": True,
            "man": 40, "terrain": 12, "aerial": 2, "heliFight": 1, "planeFight": 1,
            "weather": {"stationId": 12, "stationLocation": "Test station", "stationDistance": 4.2,
                        "intensidadeVentoKM": 18, "idDireccVento": 3, "direccVento": "E",
                        "temperatura": 29, "humidade": 31, "precAcumulada": 0,
                        "date": "2026-10-20T12:00:00+01:00"},
            "weatherWarnings": [],
        }
        value.update(changes)
        return value

    def import_snapshot(self):
        raw = self.incident()
        normalized = fogos.normalize_incident(raw)
        return fogos.save_snapshot(normalized["incident_id"], "incident", raw, normalized,
                                   normalized["source_url"], normalized["reported_at"])

    def test_normalization_rejects_bad_coordinates_and_weather_sentinels(self) -> None:
        value = fogos.normalize_incident(self.incident(lat=33, lng=-15,
            weather={"intensidadeVentoKM": -99, "idDireccVento": 3}))
        self.assertTrue(value["is_rural_fire"])
        self.assertIsNone(value["coordinates"])
        self.assertIsNone(value["weather"])

    def test_missing_resource_counts_remain_unavailable(self) -> None:
        value = fogos.normalize_incident(self.incident(man=None, terrain="", aerial=None,
                                                        heliFight=None, planeFight=None))
        self.assertEqual(value["resources"], {
            "personnel": None, "vehicles": None, "aircraft": None,
            "firefighting_aircraft": None,
        })

    def test_snapshots_deduplicate_payload_but_record_each_success(self) -> None:
        raw = self.incident()
        normalized = fogos.normalize_incident(raw)
        first = fogos.save_snapshot("20260001", "incident", raw, normalized, normalized["source_url"])
        second = fogos.save_snapshot("20260001", "incident", raw, normalized, normalized["source_url"])
        self.assertEqual(first["id"], second["id"])
        with storage.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM external_snapshots").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM external_fetches WHERE status='success'").fetchone()[0], 2)

    def test_import_is_idempotent_and_provenance_survives_autosave(self) -> None:
        snapshot = self.import_snapshot()
        start = datetime(2026, 10, 20, 10, tzinfo=UTC)
        simulation = Scenario(name="Imported", ignition=(-8.30, 41.45))
        first = storage.create_scenario(simulation, name="Imported", area_id="unprepared",
            start_time=start, resource_center=(-8.30, 41.45), fogos_snapshot_id=snapshot["id"],
            import_request_id="same-browser-request")
        second = storage.create_scenario(simulation, name="Imported", area_id="unprepared",
            start_time=start, resource_center=(-8.30, 41.45), fogos_snapshot_id=snapshot["id"],
            import_request_id="same-browser-request")
        self.assertEqual(first.id, second.id)
        self.assertEqual([group.name for group in first.resource_groups],
                         ["Operacionais", "Meios terrestres", "Meios aéreos"])
        self.assertEqual([group.reported_count for group in first.resource_groups], [40, 12, 2])
        self.assertEqual([group.id for group in first.resource_groups],
                         ["fogos-operacionais", "fogos-meios_terrestres", "fogos-meios_aereos"])
        changed = storage.update_scenario(first.id, ScenarioPatch(
            expected_revision=first.revision, name="Edited", description="Autosaved", area_id=first.area_id,
            resource_center=first.resource_center, start_time=first.start_time, simulation=first.simulation))
        self.assertEqual(changed.external_incident["incident_id"], "20260001")
        self.assertEqual(changed.external_incident["original_longitude"], -8.30)
        self.assertEqual(len(changed.resource_groups), 3)

    def test_manual_sync_preserves_local_fields_and_is_idempotent(self) -> None:
        snapshot = self.import_snapshot()
        workspace = storage.create_scenario(Scenario(name="Imported", ignition=(-8.30, 41.45)),
            resource_center=(-8.30, 41.45), start_time=datetime(2026, 10, 20, 10, tzinfo=UTC),
            fogos_snapshot_id=snapshot["id"])
        groups = [group.model_copy(update={"name": "My crews", "notes": "Local note",
                  "planned_count_override": 25}) if group.category == "operacionais" else group
                  for group in workspace.resource_groups]
        personnel_source = groups[0]
        base = ScenarioPoint(kind="response_base", name="Base", coordinates=(-8.31, 41.44))
        team = ResponseTeam(name="Crew Alpha", base_point_id=base.id, line_rate_m_min=7,
            source_provenance={"provider": "fogos.pt", "incident_id": personnel_source.incident_id,
                "resource_group_id": personnel_source.id, "category": "operacionais",
                "snapshot_id": personnel_source.snapshot_id,
                "reported_count": personnel_source.reported_count, "planned_count": 25,
                "converted_at": "2026-10-20T12:00:00+00:00"})
        values = workspace.model_dump(exclude={"id", "revision", "created_at", "updated_at",
                                                "setup_complete", "external_incident"})
        values["resource_groups"] = groups
        values.update({"points": [base], "teams": [team]})
        workspace = storage.update_scenario(workspace.id, ScenarioPatch(
            **values, expected_revision=workspace.revision))
        updated_raw = self.incident(man=55, terrain=13, aerial=None)
        with patch.object(fogos, "fetch_incident",
                          return_value=(updated_raw, fogos.normalize_incident(updated_raw))):
            result = fogos.sync_scenario_resources(workspace.id, workspace.revision)
        synced = storage.get_scenario(workspace.id)
        personnel = next(group for group in synced.resource_groups if group.category == "operacionais")
        self.assertEqual((personnel.name, personnel.notes, personnel.planned_count_override),
                         ("My crews", "Local note", 25))
        self.assertEqual([group.reported_count for group in synced.resource_groups], [55, 13, None])
        self.assertEqual(synced.teams[0], team)
        self.assertEqual({change["category"] for change in result["changes"]},
                         {"operacionais", "meios_terrestres", "meios_aereos"})
        first_revision = synced.revision
        with patch.object(fogos, "fetch_incident",
                          return_value=(updated_raw, fogos.normalize_incident(updated_raw))):
            repeated = fogos.sync_scenario_resources(workspace.id, synced.revision)
        self.assertEqual(repeated["changes"], [])
        self.assertEqual(repeated["scenario"]["revision"], first_revision)
        self.assertEqual(len(repeated["scenario"]["resource_groups"]), 3)

    def test_import_creates_numbered_ground_and_air_inventory_atomically(self) -> None:
        from backend.app.mobility_storage import list_vehicles, list_units
        from backend.app.mobility_api import mobility_snapshot
        from starlette.requests import Request
        snapshot = self.import_snapshot()
        values = dict(resource_center=(-8.30, 41.45), start_time=datetime(2026, 10, 20, 10, tzinfo=UTC),
                      fogos_snapshot_id=snapshot['id'], import_request_id='inventory-import')
        first = storage.create_scenario(Scenario(name='Imported', ignition=(-8.30, 41.45)), **values)
        repeated = storage.create_scenario(Scenario(name='Imported', ignition=(-8.30, 41.45)), **values)
        self.assertEqual(first.id, repeated.id)
        vehicles, units = list_vehicles(first.id), list_units(first.id)
        self.assertEqual((len(vehicles), len(units)), (14, 14))
        self.assertEqual(sum(v['vehicle_class']=='aircraft' for v in vehicles), 2)
        self.assertEqual(sum(v['vehicle_class']=='other' for v in vehicles), 12)
        self.assertEqual({v['name'] for v in vehicles if v['vehicle_class']=='aircraft'}, {'Aeronave 01','Aeronave 02'})
        self.assertIn('Viatura terrestre 12', {v['name'] for v in vehicles})
        by_id={v['id']:v for v in vehicles}
        for unit in units:
            vehicle=by_id[unit['vehicle_id']]
            self.assertIsNone(unit['latest_location'])
            self.assertEqual(unit['status'],'unavailable')
            self.assertEqual(unit['capabilities'],[])
            self.assertEqual(unit['import_provenance'],vehicle['import_provenance'])
            self.assertTrue(unit['import_provenance']['placeholder'])
            self.assertEqual(unit['import_provenance']['snapshot_id'],snapshot['id'])
            for field in ('width_m','height_m','weight_t','water_tank_capacity_l','pump_flow_l_min','passenger_capacity'):
                self.assertIsNone(vehicle[field])
        result=mobility_snapshot(first.id,Request({'type':'http'}))
        self.assertEqual(len(result['vehicles']),14)
        self.assertEqual(len(result['units']),14)

    def test_missing_zero_and_partial_asset_counts_do_not_invent_inventory(self) -> None:
        from backend.app.mobility_storage import list_vehicles, list_units
        for terrain,aerial,expected in [(None,None,0),(0,0,0),(3,0,3),(0,2,2)]:
            with self.subTest(terrain=terrain,aerial=aerial):
                raw=self.incident(terrain=terrain,aerial=aerial)
                normalized=fogos.normalize_incident(raw)
                snapshot=fogos.save_snapshot(normalized['incident_id'],'incident',raw,normalized,normalized['source_url'])
                workspace=storage.create_scenario(Scenario(name='Imported',ignition=(-8.30,41.45)),
                    resource_center=(-8.30,41.45),start_time=datetime(2026,10,20,10,tzinfo=UTC),fogos_snapshot_id=snapshot['id'])
                self.assertEqual(len(list_vehicles(workspace.id)),expected)
                self.assertEqual(len(list_units(workspace.id)),expected)

    def test_import_failure_rolls_back_scenario_link_and_inventory(self) -> None:
        from backend.app import fogos_resources
        snapshot=self.import_snapshot()
        original=fogos_resources.import_mobility_inventory
        def fail_after_inventory(*args):
            original(*args)
            raise RuntimeError('interrupted import')
        with patch.object(fogos_resources,'import_mobility_inventory',side_effect=fail_after_inventory):
            with self.assertRaisesRegex(RuntimeError,'interrupted import'):
                storage.create_scenario(Scenario(name='Imported',ignition=(-8.30,41.45)),
                    resource_center=(-8.30,41.45),start_time=datetime(2026,10,20,10,tzinfo=UTC),
                    fogos_snapshot_id=snapshot['id'],import_request_id='rollback')
        with storage.connect() as db:
            for table in ('scenarios','scenario_external_incidents','scenario_import_requests','mobility_vehicles','mobility_units'):
                self.assertEqual(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0],0)

    def test_resource_sync_preserves_imported_inventory_and_manual_changes(self) -> None:
        from backend.app.mobility_storage import list_vehicles,list_units
        snapshot=self.import_snapshot()
        workspace=storage.create_scenario(Scenario(name='Imported',ignition=(-8.30,41.45)),
            resource_center=(-8.30,41.45),start_time=datetime(2026,10,20,10,tzinfo=UTC),fogos_snapshot_id=snapshot['id'])
        vehicle=list_vehicles(workspace.id)[0]
        with storage.connect() as db:
            vehicle['name']='Nome confirmado localmente'
            db.execute('UPDATE mobility_vehicles SET payload=? WHERE id=?',(json.dumps(vehicle),vehicle['id']))
        before=(list_vehicles(workspace.id),list_units(workspace.id))
        raw=self.incident(terrain=15,aerial=4)
        with patch.object(fogos,'fetch_incident',return_value=(raw,fogos.normalize_incident(raw))):
            fogos.sync_scenario_resources(workspace.id,workspace.revision)
        self.assertEqual((list_vehicles(workspace.id),list_units(workspace.id)),before)

    def test_manual_sync_rejects_stale_revision_before_fetch(self) -> None:
        snapshot = self.import_snapshot()
        workspace = storage.create_scenario(Scenario(name="Imported", ignition=(-8.30, 41.45)),
            resource_center=(-8.30, 41.45), start_time=datetime(2026, 10, 20, 10, tzinfo=UTC),
            fogos_snapshot_id=snapshot["id"])
        with patch.object(fogos, "fetch_incident") as fetch, self.assertRaises(storage.ScenarioConflictError):
            fogos.sync_scenario_resources(workspace.id, workspace.revision + 1)
        fetch.assert_not_called()

    def test_sync_endpoint_reports_unlinked_conflict_and_upstream_failures(self) -> None:
        manual = storage.create_scenario(Scenario(name="Manual", ignition=(-8.30, 41.45)))
        with self.assertRaises(HTTPException) as unlinked:
            main.sync_external_incident(manual.id, FogosResourceSync(expected_revision=manual.revision))
        self.assertEqual(unlinked.exception.status_code, 404)
        snapshot = self.import_snapshot()
        linked = storage.create_scenario(Scenario(name="Linked", ignition=(-8.30, 41.45)),
            resource_center=(-8.30, 41.45), start_time=datetime(2026, 10, 20, 10, tzinfo=UTC),
            fogos_snapshot_id=snapshot["id"])
        with self.assertRaises(HTTPException) as conflict:
            main.sync_external_incident(linked.id, FogosResourceSync(expected_revision=linked.revision + 1))
        self.assertEqual(conflict.exception.status_code, 409)
        with patch.object(fogos, "fetch_incident", side_effect=fogos.FogosError("offline")), \
             self.assertRaises(HTTPException) as upstream:
            main.sync_external_incident(linked.id, FogosResourceSync(expected_revision=linked.revision))
        self.assertEqual(upstream.exception.status_code, 502)

    def test_manual_sync_backfills_legacy_import_once(self) -> None:
        snapshot = self.import_snapshot()
        workspace = storage.create_scenario(Scenario(name="Legacy import", ignition=(-8.30, 41.45)),
            resource_center=(-8.30, 41.45), start_time=datetime(2026, 10, 20, 10, tzinfo=UTC),
            fogos_snapshot_id=snapshot["id"])
        with storage.connect() as db:
            row = db.execute("SELECT definition FROM scenarios WHERE id=?", (workspace.id,)).fetchone()
            definition = json.loads(row["definition"])
            definition.pop("resource_groups")
            db.execute("UPDATE scenarios SET definition=? WHERE id=?", (json.dumps(definition), workspace.id))
        legacy = storage.get_scenario(workspace.id)
        self.assertEqual(legacy.resource_groups, [])
        raw = self.incident()
        with patch.object(fogos, "fetch_incident", return_value=(raw, fogos.normalize_incident(raw))):
            result = fogos.sync_scenario_resources(workspace.id, legacy.revision)
        self.assertEqual(len(result["scenario"]["resource_groups"]), 3)
        self.assertTrue(all(change["created"] for change in result["changes"]))

    def test_run_and_children_inherit_immutable_import_and_weather_context(self) -> None:
        snapshot = self.import_snapshot()
        simulation = Scenario(name="Imported", ignition=(-8.30, 41.45), weather_source={"kind": "constant",
            "provenance": {"provider": "fogos.pt", "snapshot_id": snapshot["id"]}})
        workspace = storage.create_scenario(simulation, area_id="unprepared", resource_center=(-8.30, 41.45),
            start_time=datetime(2026, 10, 20, 10, tzinfo=UTC), fogos_snapshot_id=snapshot["id"])
        parent = storage.create_run(workspace.simulation, mode="parameter_ensemble", scenario_id=workspace.id,
                                    scenario_revision=workspace.revision)
        child = storage.create_run(workspace.simulation, parent_id=parent.id)
        storage.update_scenario(workspace.id, ScenarioPatch(expected_revision=workspace.revision,
            name=workspace.name, area_id=workspace.area_id, resource_center=workspace.resource_center,
            start_time=datetime(2026, 10, 21, 10, tzinfo=UTC), simulation=workspace.simulation))
        context = storage.get_run(child.id).run_context
        self.assertEqual(context, parent.run_context)
        self.assertEqual(context["external_incident"]["import_snapshot"]["checksum"], snapshot["checksum"])
        self.assertEqual(context["scenario_start_time"], "2026-10-20T10:00:00+00:00")

    def test_aircraft_tracks_are_geojson_and_cached(self) -> None:
        payload = {"success": True, "data": [{"icao": "abc", "name": "Heli", "kind": "helicopter",
            "aircraft_type": "AS50", "positions": [
                {"lon": -8.3, "lat": 41.4, "sampled_at": "2026-10-20T10:00:00Z"},
                {"lon": -8.2, "lat": 41.5, "sampled_at": "2026-10-20T10:05:00Z"}]}]}
        with patch.object(fogos, "_request", return_value=(payload, {})) as request:
            first = fogos._cached_json("planes-test", "/v2/planes/recent", {"hours": 6}, 60)
            second = fogos._cached_json("planes-test", "/v2/planes/recent", {"hours": 6}, 60)
        self.assertIs(first, second)
        request.assert_called_once()
        collection = fogos.aircraft_geojson(payload)
        self.assertEqual([item["geometry"]["type"] for item in collection["features"]], ["LineString", "Point"])
        self.assertEqual(collection["features"][1]["properties"]["assignment"], "not inferred")

    def test_weather_interpolation_uses_shortest_direction_arc(self) -> None:
        start = datetime(2026, 10, 20, 10, tzinfo=UTC)
        rows = [(start, 10.0, 350.0, 20.0, 40.0, 0.0),
                (start + timedelta(hours=1), 20.0, 10.0, 30.0, 60.0, 2.0)]
        value = fogos._weather_at(rows, start + timedelta(minutes=30))
        self.assertAlmostEqual(value[1], 15)
        self.assertAlmostEqual(value[2], 0)
        self.assertAlmostEqual(value[4], 50)

    def test_weather_series_requires_and_retains_complete_absolute_interval(self) -> None:
        snapshot = self.import_snapshot()
        start = datetime(2026, 10, 20, 10, 30, tzinfo=UTC)
        workspace = storage.create_scenario(Scenario(name="Weather", ignition=(-8.30, 41.45), duration_min=120),
            resource_center=(-8.30, 41.45), start_time=start, fogos_snapshot_id=snapshot["id"])
        observations = {}
        for hour in range(10, 14):
            observations[f"2026-10-20T{hour:02d}:00"] = {"12": {
                "intensidadeVentoKM": 10 + hour, "idDireccVento": 3, "temperatura": 25,
                "humidade": 40, "precAcumulada": 0}}
        with patch.object(fogos, "_request", return_value=(observations, {})):
            series = fogos.create_weather_series(workspace.id)
        self.assertEqual(series["start"], "2026-10-20T10:30:00Z")
        self.assertEqual(series["end"], "2026-10-20T12:30:00Z")
        self.assertEqual(series["provenance"]["provider"], "fogos.pt")
        self.assertIsNotNone(series["provenance"]["snapshot_id"])
        incomplete = {"2026-10-20T11:00": observations["2026-10-20T11:00"]}
        with patch.object(fogos, "_request", return_value=(incomplete, {})), \
             self.assertRaisesRegex(ValueError, "cover"):
            fogos.create_weather_series(workspace.id)

    def test_tracking_uses_one_incident_subscription_and_finalizes_terminal_incident(self) -> None:
        snapshot = self.import_snapshot()
        start = datetime(2026, 10, 20, 10, tzinfo=UTC)
        simulation = Scenario(name="Tracked", ignition=(-8.30, 41.45))
        first = storage.create_scenario(simulation, resource_center=(-8.30, 41.45), start_time=start,
                                        fogos_snapshot_id=snapshot["id"])
        storage.create_scenario(simulation, resource_center=(-8.30, 41.45), start_time=start,
                                fogos_snapshot_id=snapshot["id"])
        fogos.set_tracking(first.id, True)
        closed_raw = self.incident(status="Conclusão", statusCode=8, active=False)
        with patch.object(fogos, "fetch_incident", return_value=(closed_raw, fogos.normalize_incident(closed_raw))), \
             patch.object(fogos, "fetch_product", side_effect=KeyError("not available")):
            self.assertEqual(fogos.run_tracking_once(), 1)
        with storage.connect() as db:
            subscription = db.execute("SELECT * FROM tracking_subscriptions").fetchone()
            self.assertEqual(subscription["enabled"], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tracking_subscriptions").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM external_fetches WHERE status='error'").fetchone()[0], 2)
        self.assertEqual(storage.get_scenario(first.id).resource_groups[0].reported_count, 40)

    def test_tracking_honours_rate_limit_backoff(self) -> None:
        snapshot = self.import_snapshot()
        workspace = storage.create_scenario(Scenario(name="Tracked", ignition=(-8.30, 41.45)),
            resource_center=(-8.30, 41.45), start_time=datetime(2026, 10, 20, 10, tzinfo=UTC),
            fogos_snapshot_id=snapshot["id"])
        fogos.set_tracking(workspace.id, True)
        before = datetime.now(UTC)
        with patch.object(fogos, "fetch_incident", side_effect=fogos.FogosError("limited", 900)):
            self.assertEqual(fogos.run_tracking_once(), 0)
        with storage.connect() as db:
            subscription = db.execute("SELECT * FROM tracking_subscriptions").fetchone()
        self.assertEqual(subscription["failure_count"], 1)
        self.assertGreaterEqual(datetime.fromisoformat(subscription["next_details_at"]), before + timedelta(minutes=14))

    def _evaluation_fixture(self, observed_geometry, observed_minute=60, coverage=None):
        snapshot = self.import_snapshot()
        start = datetime(2026, 10, 20, 10, tzinfo=UTC)
        simulation = Scenario(name="Evaluation", ignition=(-8.30, 41.45), duration_min=120)
        workspace = storage.create_scenario(simulation, area_id="unprepared", resource_center=(-8.30, 41.45),
            start_time=start, fogos_snapshot_id=snapshot["id"])
        run = storage.create_run(simulation, demo=True, run_id=f"run-{observed_minute}-{len(storage.list_runs(include_children=True))}",
                                 scenario_id=workspace.id, scenario_revision=workspace.revision)
        arrival = np.full((3, 3), np.nan, dtype="float32"); arrival[1, 1] = 10
        coverage_grid = np.ones((3, 3), dtype=bool) if coverage is None else coverage
        result = SimulationResult(arrival, coverage_grid, from_origin(-925000, 5100000, 1000, 1000),
                                  "EPSG:3857", 1, "test", "1", {})
        save_result(result, observation.RUNS / run.id)
        collection = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": observed_geometry, "properties": {"last_seen": (start + timedelta(minutes=observed_minute)).isoformat()}}]}
        perimeter = fogos.save_snapshot("20260001", "perimeter", collection, {"geojson": collection},
            "https://api.fogos.pt/perimeter", (start + timedelta(minutes=observed_minute)).isoformat())
        return run, perimeter, start

    def cell_polygon(self, col: int, row: int):
        inverse = Transformer.from_crs(3857, 4326, always_xy=True)
        west, north = -925000 + col * 1000, 5100000 - row * 1000
        east, south = west + 1000, north - 1000
        points = [inverse.transform(west, south), inverse.transform(east, south),
                  inverse.transform(east, north), inverse.transform(west, north), inverse.transform(west, south)]
        return {"type": "Polygon", "coordinates": [points]}

    def test_evaluation_identical_disjoint_and_out_of_horizon(self) -> None:
        run, perimeter, _ = self._evaluation_fixture(self.cell_polygon(1, 1))
        identical = observation.evaluate(run.id, perimeter["id"])
        self.assertGreater(identical["metrics"]["intersection_over_union"], .999)
        run2, perimeter2, _ = self._evaluation_fixture(self.cell_polygon(0, 0))
        disjoint = observation.evaluate(run2.id, perimeter2["id"])
        self.assertEqual(disjoint["metrics"]["intersection_over_union"], 0)
        run3, perimeter3, _ = self._evaluation_fixture(self.cell_polygon(1, 1), observed_minute=180)
        with self.assertRaisesRegex(ValueError, "outside"):
            observation.evaluate(run3.id, perimeter3["id"])

    def test_partial_coverage_suppresses_boundary_distance(self) -> None:
        multi = {"type": "MultiPolygon", "coordinates": [self.cell_polygon(1, 1)["coordinates"],
                                                             self.cell_polygon(2, 1)["coordinates"]]}
        coverage = np.zeros((3, 3), dtype=bool); coverage[1, 1] = True
        run, perimeter, _ = self._evaluation_fixture(multi, coverage=coverage)
        value = observation.evaluate(run.id, perimeter["id"])["metrics"]
        self.assertTrue(value["partial"])
        self.assertGreater(value["observation_outside_coverage_fraction"], .49)
        self.assertIsNone(value["hausdorff_distance_m"])

    def test_retrieval_time_requires_explicit_assumption_and_empty_geometry_is_rejected(self) -> None:
        run, perimeter, start = self._evaluation_fixture(self.cell_polygon(1, 1))
        with storage.connect() as db:
            db.execute("UPDATE external_snapshots SET observed_at=NULL WHERE id=?", (perimeter["id"],))
        with self.assertRaisesRegex(ValueError, "explicit assumption"):
            observation.evaluate(run.id, perimeter["id"])
        value = observation.evaluate(run.id, perimeter["id"], start + timedelta(minutes=60))
        self.assertEqual(value["time_basis"], "user supplied observation timestamp")
        empty = {"type": "FeatureCollection", "features": []}
        item = fogos.save_snapshot("20260001", "perimeter", empty, {"geojson": empty}, "source",
                                   (start + timedelta(minutes=60)).isoformat())
        with self.assertRaisesRegex(ValueError, "no usable"):
            observation.evaluate(run.id, item["id"])


if __name__ == "__main__":
    unittest.main()
