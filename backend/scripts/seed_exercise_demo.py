"""Create the fully synthetic mission-planning demonstration without network access."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from backend.app.exercise_models import ExerciseLocation, Mission, PlanAssignment, ResponsePlan
from backend.app.exercise_storage import save_mission, save_plan
from backend.app.mobility_storage import add_location, init_mobility_db, save_unit, save_vehicle
from backend.app.models import LocationCreate, OperationalUnit, Scenario, ScenarioPoint, VehicleProfile
from backend.app.settings import CONFIG, ROOT
from backend.app.storage import create_scenario, get_scenario, init_db


FIXTURE = ROOT / "backend" / "demo" / "exercise_demo_v1.json"


def seed_exercise_demo():
    values = json.loads(FIXTURE.read_text())
    init_db(); init_mobility_db()
    try:
        return get_scenario(values["id"])
    except KeyError:
        pass
    points = [ScenarioPoint.model_validate({**value, "description": "Dados fictícios de exercício",
              "notes": "Não é uma observação no terreno", "source": "demo", "data_status": "verified"})
              for value in values["points"]]
    by_point = {value.id: value for value in points}
    scenario = create_scenario(Scenario(name=values["name"], ignition=tuple(CONFIG["area"]["center"])),
        scenario_id=values["id"], name=values["name"], description=values["description"],
        start_time=datetime.fromisoformat(values["reference_time"]), points=points, scenario_kind="exercise")
    for value in values["vehicles"]:
        save_vehicle(scenario.id, VehicleProfile.model_validate(value))
    base = by_point["demo-command"].coordinates
    for value in values["units"]:
        unit = OperationalUnit.model_validate(value)
        save_unit(scenario.id, unit)
        add_location(scenario.id, unit.id, LocationCreate(coordinates=base,
                     observed_at=datetime.fromisoformat(values["reference_time"]), source="dispatcher"))
    for value in values["missions"]:
        location = by_point[value.pop("location_point_id")]
        access_id = value.pop("access_point_id", None)
        mission = Mission.model_validate({**value,
            "location": ExerciseLocation(name=location.name, coordinates=location.coordinates, point_id=location.id),
            "access_point": (ExerciseLocation(name=by_point[access_id].name,
                             coordinates=by_point[access_id].coordinates, point_id=access_id) if access_id else None),
            "pickup": (ExerciseLocation(name="Ponto de recolha a leste", coordinates=by_point["demo-control"].coordinates,
                       point_id="demo-control") if value["mission_type"] == "transport" else None),
            "dropoff": (ExerciseLocation(name=by_point["demo-shelter"].name,
                        coordinates=by_point["demo-shelter"].coordinates, point_id="demo-shelter")
                        if value["mission_type"] == "transport" else None)})
        save_mission(scenario.id, mission)
    assignment_units = {
        "demo-mission-control": ["demo-police"], "demo-mission-fire": ["demo-fire-1"],
        "demo-mission-water": ["demo-fire-1", "demo-fire-2"], "demo-mission-transport": ["demo-civil"],
    }
    for plan_value in values["plans"]:
        assignments = [PlanAssignment(id=f"{plan_value['id']}-{mission_id}", mission_id=mission_id,
            unit_ids=unit_ids, source_point_id=plan_value["water_source_id"] if mission_id == "demo-mission-water" else None)
            for mission_id, unit_ids in assignment_units.items()]
        save_plan(scenario.id, ResponsePlan(id=plan_value["id"], name=plan_value["name"], assignments=assignments,
                                            assumptions=["Dados fictícios de demonstração"]));
    return scenario


if __name__ == "__main__":
    value = seed_exercise_demo()
    print(f"Created {value.name}: /scenarios/{value.id}/map")
