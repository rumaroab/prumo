from __future__ import annotations

import unittest
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import numpy as np
from rasterio.transform import from_origin

from pydantic import ValidationError

from backend.app.models import (AllocationRankRequest, AssetDetails, ContainmentTask, ResponseTeam,
                                Scenario, ScenarioDefinition, ScenarioPoint, ScenarioWorkspace,
                                SimulationResult)
from backend.app.services.allocation import _completion_min, _solve_plans, rank_plans
from backend.app import storage, worker


def closed_line(offset: float = 0) -> dict:
    return {"type": "LineString", "coordinates": [
        [-8.30 + offset, 41.40], [-8.29 + offset, 41.40],
        [-8.29 + offset, 41.41], [-8.30 + offset, 41.40],
    ]}


class AllocationTests(unittest.TestCase):
    def test_legacy_scenario_defaults_to_empty_operational_data(self) -> None:
        value = ScenarioDefinition(simulation=Scenario(ignition=(-8.3, 41.4)))
        self.assertEqual(value.teams, [])
        self.assertEqual(value.containment_tasks, [])
        self.assertEqual(value.allocation_plans, [])

    def test_containment_lines_must_be_closed(self) -> None:
        with self.assertRaisesRegex(ValidationError, "must be closed"):
            ContainmentTask(geometry={"type": "LineString", "coordinates": [
                [-8.3, 41.4], [-8.29, 41.4], [-8.28, 41.4],
            ]})

    def test_staggered_team_arrivals_combine_production_rates(self) -> None:
        self.assertAlmostEqual(_completion_min(100, [(0, 2), (10, 3)]), 26)

    def test_optimizer_protects_the_higher_priority_asset_first(self) -> None:
        team = ResponseTeam(id="team", name="Team", base_point_id="base")
        high_asset = ScenarioPoint(id="high", kind="asset", name="Hospital",
                                   coordinates=(-8.3, 41.4), asset=AssetDetails(priority=5))
        low_asset = ScenarioPoint(id="low", kind="asset", name="Shed",
                                  coordinates=(-8.29, 41.4), asset=AssetDetails(priority=1))
        high = ContainmentTask(id="high-line", name="Hospital line", geometry=closed_line(),
                               protected_asset_ids=[high_asset.id])
        low = ContainmentTask(id="low-line", name="Shed line", geometry=closed_line(.01),
                              protected_asset_ids=[low_asset.id])
        def evaluation(task):
            return {"task_id": task.id, "task_name": task.name,
                    "protected_asset_ids": task.protected_asset_ids, "team_ids": [team.id],
                    "team_names": [team.name], "status": "feasible", "line_length_m": 100,
                    "completion_min": 20, "fire_arrival_min": 60, "margin_min": 40,
                    "routes": [], "effort_min": 30, "message": "Feasible"}
        plans = _solve_plans([(low, (team,), evaluation(low)), (high, (team,), evaluation(high))],
                             [team], [low, high], {"low": low_asset, "high": high_asset}, 1)
        self.assertEqual(plans[0]["assignments"][0]["task_id"], "high-line")

    def test_allocation_parent_creates_intervention_children(self) -> None:
        original_db = storage.DB
        with tempfile.TemporaryDirectory() as folder:
            storage.DB = Path(folder) / "runs.sqlite3"
            try:
                storage.init_db()
                workspace = storage.create_scenario(Scenario(ignition=(-8.3, 41.4)))
                intervention = {"kind": "timed_containment", "plan_id": "plan-1",
                                "plan_name": "Plan 1", "tasks": []}
                parent = storage.create_run(workspace.simulation, mode="allocation_comparison",
                                            ensemble={"kind": "allocation", "source_run_id": "control",
                                                      "interventions": [intervention]},
                                            scenario_id=workspace.id, scenario_revision=workspace.revision)
                worker._expand_parent(parent)
                children = storage.child_runs(parent.id)
                self.assertEqual(len(children), 1)
                self.assertEqual(children[0].intervention["plan_id"], "plan-1")
            finally:
                storage.DB = original_db

    def test_three_team_demo_generates_four_distinct_valid_plans(self) -> None:
        bases = [ScenarioPoint(id=f"base-{index}", kind="response_base", name=f"Base {index}",
                               coordinates=(-8.39 + index * .01, 41.49)) for index in range(3)]
        assets = [ScenarioPoint(id=f"asset-{index}", kind="asset", name=f"Asset {index}",
                                coordinates=(-8.36 + index * .01, 41.46),
                                asset=AssetDetails(priority=5 - index)) for index in range(3)]
        teams = [ResponseTeam(id=f"team-{index}", name=f"Team {index}",
                              base_point_id=bases[index].id) for index in range(3)]
        tasks = [ContainmentTask(id=f"task-{index}", name=f"Line {index}",
                                 geometry=closed_line(index * .01),
                                 protected_asset_ids=[assets[index].id]) for index in range(3)]
        scenario = Scenario(ignition=(-8.38, 41.48), duration_min=120)
        workspace = ScenarioWorkspace(id="demo", name="Demo", revision=1, simulation=scenario,
                                      points=[*bases, *assets], teams=teams, containment_tasks=tasks,
                                      created_at="2026-01-01T00:00:00", updated_at="2026-01-01T00:00:00")
        arrival = np.full((20, 20), 100, dtype="float32")
        result = SimulationResult(arrival, np.ones_like(arrival, dtype=bool),
                                  from_origin(-8.4, 41.5, .01, .01), "EPSG:4326", 1,
                                  "test", "1", {})

        def route(_path, request, _prepared):
            option = {"label": "Route", "status": "clear", "message": "Clear",
                      "departure_min": request.departure_min,
                      "arrival_min": request.departure_min + 5, "duration_min": 5,
                      "distance_km": 1, "closest_fire_margin_min": 50, "unknown_roads": [],
                      "exposed_segments": [], "shared_vulnerable_segments": [],
                      "feature": {"type": "Feature", "properties": {},
                                  "geometry": {"type": "LineString", "coordinates": []}}}
            withdrawal = None
            if request.withdrawal_destination:
                withdrawal = {**option, "departure_min": request.departure_min + request.on_scene_min + 5,
                              "arrival_min": request.departure_min + request.on_scene_min + 10}
            return {"routes": [option], "withdrawal": withdrawal}

        with patch("backend.app.services.allocation.load_result", return_value=result), \
                patch("backend.app.services.allocation.analyse_routes", side_effect=route):
            ranked = rank_plans(workspace, SimpleNamespace(id="control", scenario=scenario),
                                AllocationRankRequest(run_id="control"), Path("roads"),
                                Path("prepared"), Path("runs"))
        self.assertEqual(len(ranked["plans"]), 4)
        signatures = set()
        for plan in ranked["plans"]:
            assignments = tuple(sorted((item["task_id"], tuple(item["team_ids"]))
                                       for item in plan["assignments"]))
            signatures.add(assignments)
            used = [team_id for item in plan["assignments"] for team_id in item["team_ids"]]
            self.assertEqual(len(used), len(set(used)))
        self.assertEqual(len(signatures), 4)


if __name__ == "__main__":
    unittest.main()
