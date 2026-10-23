from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

import backend.app.storage as storage
from backend.app.exercise_models import ExerciseLocation, Mission, PlanAssignment, ResponsePlan
from backend.app.exercise_planner import evaluate_plan, suggest_plans
from backend.app.exercise_storage import (ExerciseConflict, act_on_exercise_run, add_exercise_event,
                                          claim_experiment, create_exercise_run, create_experiment_record, create_snapshot,
                                          get_experiment, get_exercise_run,
                                          get_situation, list_missions, save_mission, save_plan)
from backend.app.exercise_jobs import evaluate_experiment_job
from backend.app.mobility_storage import add_location, init_mobility_db, list_movements, save_unit, save_vehicle
from backend.app.models import (LocationCreate, OperationalUnit, Scenario, ScenarioPoint,
                                VehicleProfile, WaterPointDetails)


class ExerciseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_db = storage.DB
        storage.DB = Path(self.temp.name) / "exercise.sqlite3"
        storage.init_db(); init_mobility_db()
        source = ScenarioPoint(id="source", kind="water_point", name="Reservoir", coordinates=(-8.29, 41.43),
            water=WaterPointDetails(availability="available", supply_class="finite", available_volume_l=30000,
                                    shared_flow_l_min=1000, filling_positions=1, setup_time_min=1))
        delivery = ScenarioPoint(id="delivery", kind="delivery_point", name="Sector A", coordinates=(-8.27, 41.44))
        self.scenario = storage.create_scenario(Scenario(name="Exercise", ignition=(-8.27, 41.43)),
            points=[source, delivery], scenario_kind="exercise", start_time=datetime.now(UTC))
        self.vehicles = []
        self.units = []
        for index in range(2):
            vehicle = VehicleProfile(id=f"vehicle-{index}", name=f"Tanker {index}", vehicle_class="tanker",
                                     water_tank_capacity_l=5000, pump_flow_l_min=500,
                                     starting_water_l=0)
            unit = OperationalUnit(id=f"unit-{index}", organisation="Fire service", callsign=f"T-{index}",
                                   vehicle_id=vehicle.id, capabilities=["water_supply", "firefighting"])
            save_vehicle(self.scenario.id, vehicle); save_unit(self.scenario.id, unit)
            add_location(self.scenario.id, unit.id, LocationCreate(coordinates=(-8.30 + index * .001, 41.42),
                         observed_at=datetime.now(UTC), source="dispatcher"))
            self.vehicles.append(vehicle); self.units.append(unit)
        self.mission = save_mission(self.scenario.id, Mission(id="water-mission", name="Supply sector A",
            mission_type="water_supply", priority=5, location=ExerciseLocation(name="Sector A", coordinates=(-8.27, 41.44)),
            target_volume_l=20000, deadline_min=120, required_capabilities=["water_supply"],
            required_unit_count=2, completion_criteria="Deliver 20,000 litres"))

    def tearDown(self):
        storage.DB = self.previous_db
        self.temp.cleanup()

    def plan(self):
        return save_plan(self.scenario.id, ResponsePlan(id="plan", name="Two tankers", assignments=[
            PlanAssignment(id="water-assignment", mission_id=self.mission["id"],
                           unit_ids=[unit.id for unit in self.units], source_point_id="source")]))

    def test_migration_and_snapshot_are_idempotent_and_immutable(self):
        storage.init_db(); storage.init_db()
        with storage.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM schema_migrations WHERE version='2026-10-exercise-workspace-v1'").fetchone()[0]
        self.assertEqual(count, 1)
        first = create_snapshot(self.scenario.id)
        self.scenario = storage.update_scenario(self.scenario.id, storage.ScenarioPatch(
            **{**self.scenario.model_dump(), "expected_revision": self.scenario.revision,
               "description": "Edited later"}))
        frozen = storage.connect
        _ = frozen
        self.assertEqual(first["scenario_revision"], 1)
        self.assertEqual(first["points"][0]["name"], "Reservoir")

    def test_repeated_water_cycles_queue_and_deplete_finite_source(self):
        snapshot = create_snapshot(self.scenario.id)
        plan = self.plan()
        result = evaluate_plan(snapshot, plan, horizon_min=120)
        water = next(value for value in result["missions"] if value["mission_id"] == self.mission["id"])
        self.assertEqual(water["status"], "completed")
        self.assertEqual(water["delivered_l"], 20000)
        self.assertGreater(water["source_wait_min"], 0)
        self.assertGreaterEqual(len(water["cycles"]), 4)

        snapshot["points"][0]["water"]["available_volume_l"] = 10000
        depleted = evaluate_plan(snapshot, plan, horizon_min=120)["missions"][0]
        self.assertEqual(depleted["status"], "infeasible")
        self.assertEqual(depleted["delivered_l"], 10000)
        self.assertEqual(depleted["unmet_l"], 10000)

    def test_missing_capacity_prevents_numeric_claim(self):
        snapshot = create_snapshot(self.scenario.id)
        snapshot["vehicles"][0]["water_tank_capacity_l"] = None
        result = evaluate_plan(snapshot, self.plan())
        water = result["missions"][0]
        self.assertEqual(water["status"], "unknown")
        self.assertTrue(any("Tank capacity" in value for value in water["missing_inputs"]))

    def test_suggestions_are_bounded_locked_and_deterministic(self):
        snapshot = create_snapshot(self.scenario.id)
        locked = [{"id": "locked", "mission_id": self.mission["id"], "unit_ids": [self.units[0].id],
                   "source_point_id": "source", "planned_start_min": 0, "locked": True}]
        first = suggest_plans(snapshot, [self.mission["id"]], [unit.id for unit in self.units], locked, count=4)
        second = suggest_plans(snapshot, [self.mission["id"]], [unit.id for unit in self.units], locked, count=4)
        self.assertLessEqual(len(first["plans"]), 4)
        self.assertEqual(first, second)
        self.assertEqual(first["plans"][0]["assignments"][0]["id"], "locked")

    def test_dependency_cycles_are_rejected(self):
        one = save_mission(self.scenario.id, Mission(id="one", name="One", mission_type="logistics",
            location=ExerciseLocation(name="One", coordinates=(-8.2, 41.4))))
        two = save_mission(self.scenario.id, Mission(id="two", name="Two", mission_type="logistics",
            location=ExerciseLocation(name="Two", coordinates=(-8.2, 41.4)), prerequisite_ids=[one["id"]]))
        changed = Mission.model_validate({**one, "prerequisite_ids": [two["id"]]})
        with self.assertRaises(ValueError):
            save_mission(self.scenario.id, changed, one["revision"])

    def test_rehearsal_isolated_actions_and_injected_events(self):
        plan = self.plan(); snapshot = create_snapshot(self.scenario.id); evaluation = evaluate_plan(snapshot, plan)
        run = create_exercise_run(self.scenario.id, snapshot["id"], plan, evaluation)
        playing = act_on_exercise_run(self.scenario.id, run["id"], "play", run["revision"])
        self.assertEqual(playing["state"], "running")
        paused = add_exercise_event(self.scenario.id, run["id"], "unit_unavailable", 5,
                                    {"unit_id": self.units[0].id})
        self.assertEqual(paused["state"], "paused")
        self.assertIn(self.mission["id"], paused["payload"]["affected_mission_ids"])
        self.assertEqual(list_movements(self.scenario.id), [])
        restarted = act_on_exercise_run(self.scenario.id, run["id"], "restart", paused["revision"])
        self.assertEqual(restarted["elapsed_min"], 0)

    def test_response_experiment_uses_frozen_plan_version(self):
        plan = self.plan(); snapshot = create_snapshot(self.scenario.id)
        request = {"snapshot_id": snapshot["id"], "plan_ids": [plan["id"]], "plan_versions": [plan],
                   "forecast_ids": [], "primary_forecast_id": None, "evaluation_start_min": 0,
                   "horizon_min": 120}
        experiment = create_experiment_record(self.scenario.id, snapshot["id"], request, "request-one")
        self.assertTrue(claim_experiment(experiment["id"]))
        evaluate_experiment_job(self.scenario.id, experiment["id"])
        completed = get_experiment(self.scenario.id, experiment["id"])
        self.assertEqual(completed["status"], "ready")
        self.assertEqual(completed["result"]["plans"][0]["plan_name"], "Two tankers")


if __name__ == "__main__":
    unittest.main()
