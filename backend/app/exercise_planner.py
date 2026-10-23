from __future__ import annotations

import heapq
import math
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable


AVERAGE_SPEED_KMH = 30.0


def distance_km(left: tuple[float, float] | list[float], right: tuple[float, float] | list[float]) -> float:
    lon1, lat1 = map(math.radians, left)
    lon2, lat2 = map(math.radians, right)
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


def travel_minutes(left, right, vehicle: dict[str, Any] | None = None) -> float:
    speed = 22.0 if (vehicle or {}).get("vehicle_class") in {"heavy", "tanker", "bus"} else AVERAGE_SPEED_KMH
    return distance_km(left, right) / speed * 60


def evaluate_plan(snapshot: dict[str, Any], plan: dict[str, Any], horizon_min: float = 120,
                  forecast_id: str | None = None, route_assessor: Callable | None = None) -> dict[str, Any]:
    missions = {value["id"]: value for value in snapshot.get("missions", [])}
    units = {value["id"]: value for value in snapshot.get("units", [])}
    vehicles = {value["id"]: value for value in snapshot.get("vehicles", [])}
    points = {value["id"]: value for value in snapshot.get("points", [])}
    assignments = sorted(plan.get("assignments", []), key=lambda value: (value.get("planned_start_min") or 0, value["id"]))
    selected_missions = {value["mission_id"] for value in assignments}
    results: list[dict[str, Any]] = []
    unknowns: list[str] = []
    assumptions = list(dict.fromkeys([*snapshot.get("assumptions", []), *plan.get("assumptions", [])]))
    unit_clock: dict[str, float] = defaultdict(float)
    unit_location: dict[str, tuple[float, float] | list[float]] = {}
    completed: dict[str, float] = {}
    for unit_id, unit in units.items():
        location = unit.get("latest_location") or {}
        if location.get("coordinates"):
            unit_location[unit_id] = location["coordinates"]
    water_assignments = [value for value in assignments if missions.get(value["mission_id"], {}).get("mission_type") == "water_supply"]
    water_results = _evaluate_water(snapshot, water_assignments, missions, units, vehicles, points, horizon_min,
                                    route_assessor)
    water_by_assignment = {value["assignment_id"]: value for value in water_results}

    for assignment in assignments:
        mission = missions.get(assignment["mission_id"])
        if not mission:
            results.append(_failed(assignment, "Mission is missing from the frozen snapshot"))
            continue
        if assignment["id"] in water_by_assignment:
            value = water_by_assignment[assignment["id"]]
            results.append(value)
            for unit_id in assignment.get("unit_ids", []):
                unit_clock[unit_id] = max(unit_clock[unit_id], value.get("completion_min") or 0)
                unit_location[unit_id] = mission["location"]["coordinates"]
            if value["status"] == "completed" and value.get("completion_min") is not None:
                completed[mission["id"]] = value["completion_min"]
            unknowns.extend(value.get("missing_inputs", []))
            assumptions.extend(value.get("assumptions", []))
            continue
        mission_result = _evaluate_standard(assignment, mission, units, vehicles, unit_clock,
                                            unit_location, completed, horizon_min, snapshot.get("reference_time"),
                                            route_assessor)
        results.append(mission_result)
        unknowns.extend(mission_result.get("missing_inputs", []))
        if mission_result["status"] == "completed" and mission_result.get("completion_min") is not None:
            completed[mission["id"]] = mission_result["completion_min"]

    for mission in missions.values():
        if mission["id"] not in selected_missions and mission.get("status") == "required":
            results.append({"mission_id": mission["id"], "mission_name": mission["name"],
                            "priority": mission["priority"], "status": "unassigned",
                            "message": "No units are assigned", "fulfilment": 0})
    grouped = {str(priority): sum(value.get("fulfilment", 0) for value in results if value.get("priority") == priority)
               for priority in range(5, 0, -1)}
    possible = {str(priority): sum(1 for value in missions.values() if value.get("priority") == priority and value.get("status") == "required")
                for priority in range(5, 0, -1)}
    fulfilment = {key: (grouped[key] / possible[key] if possible[key] else 1.0) for key in grouped}
    resource_time = sum(value.get("resource_time_min", 0) for value in results)
    status = "feasible" if all(value.get("status") == "completed" for value in results) else "incomplete"
    if unknowns:
        status = "unknown" if not any(value.get("status") == "infeasible" for value in results) else "incomplete"
    provisional = sum(report.get("status") == "pending" and report.get("kind") in {"blocked", "restricted"}
                      for report in snapshot.get("road_reports", []))
    return {
        "plan_id": plan["id"], "plan_revision": plan.get("revision", 1), "plan_name": plan["name"],
        "status": status, "missions": results, "fulfilment_by_priority": fulfilment,
        "unresolved_unknowns": sorted(set(unknowns)), "assumptions": sorted(set(assumptions)),
        "total_resource_time_min": round(resource_time, 2), "minimum_forecast_margin_min": None,
        "forecast": {"id": forecast_id, "status": "selected" if forecast_id else "not_assessed",
                     "message": "Selected fire forecast" if forecast_id else "Fire exposure not assessed"},
        "reported_constraints": {"provisional_reports": provisional,
                                 "message": "Pending restrictions remain provisional constraints" if provisional else "No provisional restrictions"},
    }


def _evaluate_standard(assignment, mission, units, vehicles, unit_clock, unit_location, completed, horizon,
                       reference_time, route_assessor):
    missing: list[str] = []
    unit_ids = assignment.get("unit_ids", [])
    if len(unit_ids) < mission.get("required_unit_count", 1):
        return _failed(assignment, "Not enough units", mission)
    for dependency in mission.get("prerequisite_ids", []):
        if dependency not in completed:
            return _failed(assignment, "A prerequisite mission is incomplete", mission)
    arrivals = []
    route_values = []
    resource_time = 0.0
    destination = (mission.get("access_point") or mission["location"])["coordinates"]
    for unit_id in unit_ids:
        unit = units.get(unit_id)
        if not unit:
            return _failed(assignment, "Assigned unit is missing", mission)
        required = set(mission.get("required_capabilities", []))
        if not required.issubset(set(unit.get("capabilities", []))):
            return _failed(assignment, f"{unit.get('callsign', unit_id)} lacks required capabilities", mission)
        vehicle = vehicles.get(unit.get("vehicle_id"))
        if not vehicle or not vehicle.get("available", True) or unit.get("status") == "unavailable":
            return _failed(assignment, "An assigned unit or vehicle is unavailable", mission)
        origin = unit_location.get(unit_id)
        if origin is None:
            missing.append(f"Initial location for {unit.get('callsign', unit_id)}")
            continue
        intended = assignment.get("planned_start_min")
        if intended is not None and unit_clock[unit_id] > intended:
            return _failed(assignment, f"{unit.get('callsign', unit_id)} is double-booked at the intended start", mission)
        available_from = _time_offset(unit.get("available_from"), reference_time)
        available_until = _time_offset(unit.get("available_until"), reference_time)
        start = max(unit_clock[unit_id], mission.get("earliest_start_min", 0), intended or 0,
                    available_from or 0)
        route = route_assessor(unit, vehicle, origin, destination, start,
                               mission.get("service_duration_min", 0), origin) if route_assessor else None
        if route_assessor and (not route or not route.get("selected")):
            return _failed(assignment, f"No assessed route is available for {unit.get('callsign', unit_id)}", mission)
        duration = route["selected"]["duration_min"] if route else travel_minutes(origin, destination, vehicle)
        arrival = start + duration
        if route:
            route_values.append({"unit_id": unit_id, **route})
            if mission["mission_type"] == "fire_response" and (route.get("withdrawal") or {}).get("status") == "unavailable":
                return _failed(assignment, f"No withdrawal route remains for {unit.get('callsign', unit_id)}", mission)
        arrivals.append(arrival)
        resource_time += arrival - unit_clock[unit_id]
        if available_until is not None and arrival > available_until:
            return _failed(assignment, f"{unit.get('callsign', unit_id)} is outside its availability window", mission)
    if missing:
        return {**_base(assignment, mission), "status": "unknown", "message": "Initial locations are incomplete",
                "missing_inputs": missing, "fulfilment": 0, "resource_time_min": 0}
    arrival = max(arrivals)
    if mission["mission_type"] == "transport":
        capacities = [vehicles[units[unit_id]["vehicle_id"]].get("passenger_capacity") for unit_id in unit_ids]
        if any(value is None for value in capacities):
            return {**_base(assignment, mission), "status": "unknown", "message": "Passenger capacity is required",
                    "missing_inputs": ["Passenger capacity"], "fulfilment": 0, "resource_time_min": resource_time}
        trips = math.ceil(mission["people_count"] / max(1, sum(capacities)))
        pickup = mission["pickup"]["coordinates"]
        dropoff = mission["dropoff"]["coordinates"]
        vehicle = vehicles[units[unit_ids[0]]["vehicle_id"]]
        cycle = travel_minutes(destination, pickup, vehicle) + travel_minutes(pickup, dropoff, vehicle) + mission.get("service_duration_min", 0)
        completion = arrival + cycle * trips
    elif mission["mission_type"] == "containment":
        coordinates = (mission.get("containment_geometry") or {}).get("coordinates", [])
        length_m = sum(distance_km(left, right) * 1000 for left, right in zip(coordinates, coordinates[1:]))
        rates = [units[unit_id].get("containment_rate_m_min") for unit_id in unit_ids]
        if any(value is None for value in rates):
            return {**_base(assignment, mission), "status": "unknown", "message": "Containment production rates are required",
                    "missing_inputs": ["Containment production rate"], "fulfilment": 0,
                    "resource_time_min": resource_time}
        completion = arrival + length_m / max(0.001, sum(rates))
    else:
        completion = arrival + mission.get("service_duration_min", 0)
    for unit_id in unit_ids:
        unit = units[unit_id]
        available_until = _time_offset(unit.get("available_until"), reference_time)
        if available_until is not None and completion > available_until:
            return _failed(assignment, f"{unit.get('callsign', unit_id)} becomes unavailable before completion", mission)
        if unit.get("max_deployment_min") is not None and completion - unit_clock[unit_id] > unit["max_deployment_min"]:
            return _failed(assignment, f"{unit.get('callsign', unit_id)} exceeds its deployment limit", mission)
    deadline = mission.get("deadline_min")
    status = "completed" if completion <= horizon and (deadline is None or completion <= deadline) else "infeasible"
    message = "Mission completed within its timing requirements" if status == "completed" else "Mission misses its deadline or evaluation horizon"
    route_unknowns = [f"Route assessment for {value['unit_id']} has unknown constraints"
                      for value in route_values if value.get("status") == "unknown"]
    if status == "completed" and route_unknowns:
        status, message = "unknown", "Timing is feasible but route constraints or forecast coverage remain unknown"
    for unit_id in unit_ids:
        unit_clock[unit_id] = completion
        unit_location[unit_id] = destination
    return {**_base(assignment, mission), "status": status, "message": message,
            "arrival_min": round(arrival, 2), "completion_min": round(completion, 2),
            "withdrawal_status": "not_assessed" if mission["mission_type"] != "fire_response" else "available",
            "routes": route_values, "missing_inputs": route_unknowns,
            "fulfilment": 1 if status in {"completed", "unknown"} else 0,
            "resource_time_min": round(resource_time + mission.get("service_duration_min", 0) * len(unit_ids), 2)}


def _evaluate_water(snapshot, assignments, missions, units, vehicles, points, horizon, route_assessor):
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    results: list[dict[str, Any]] = []
    for assignment in assignments:
        mission = missions[assignment["mission_id"]]
        source = points.get(assignment.get("source_point_id"))
        if not source or source.get("kind") != "water_point":
            results.append({**_base(assignment, mission), "status": "unknown", "message": "Select a water source",
                            "missing_inputs": ["Water source"], "fulfilment": 0, "resource_time_min": 0})
        else:
            by_source[source["id"]].append(assignment)
    for source_id, source_assignments in sorted(by_source.items()):
        source = points[source_id]
        water = source.get("water") or {}
        positions = water.get("filling_positions")
        assumptions: list[str] = []
        if positions is None:
            positions = 1
            assumptions.append("Water source has one filling position")
        flow = water.get("shared_flow_l_min") or water.get("flow_l_min")
        supply_class = water.get("supply_class", "unknown")
        available = water.get("available_volume_l")
        if available is None and water.get("capacity_m3") is not None:
            available = water["capacity_m3"] * 1000
            assumptions.append("Nominal capacity used as available water")
        slots = [0.0] * positions
        source_remaining = available
        vehicle_heap: list[tuple[float, str, str, dict[str, Any], dict[str, Any], float, list[dict[str, Any]], float]] = []
        assignment_state: dict[str, dict[str, Any]] = {}
        for assignment in sorted(source_assignments, key=lambda value: value["id"]):
            mission = missions[assignment["mission_id"]]
            state = {"delivered": 0.0, "first": None, "cycles": [], "wait": 0.0, "busy": 0.0,
                     "missing": [], "route_unknowns": [], "infeasible": [], "assumptions": list(assumptions)}
            assignment_state[assignment["id"]] = state
            if len(assignment.get("unit_ids", [])) < mission.get("required_unit_count", 1):
                state["missing"].append("Required unit count")
            for unit_id in sorted(assignment.get("unit_ids", [])):
                unit, vehicle = units.get(unit_id), None
                if unit:
                    vehicle = vehicles.get(unit.get("vehicle_id"))
                if not unit or not vehicle:
                    state["missing"].append(f"Unit or vehicle {unit_id}")
                    continue
                required = set(mission.get("required_capabilities", []))
                if not required.issubset(set(unit.get("capabilities", []))):
                    state["missing"].append(f"Capabilities for {unit.get('callsign', unit_id)}")
                    continue
                if unit.get("status") == "unavailable" or not vehicle.get("available", True):
                    state["missing"].append(f"Availability for {unit.get('callsign', unit_id)}")
                    continue
                capacity, pump = vehicle.get("water_tank_capacity_l"), vehicle.get("pump_flow_l_min")
                location = (unit.get("latest_location") or {}).get("coordinates")
                if capacity is None or pump is None or location is None:
                    if capacity is None: state["missing"].append(f"Tank capacity for {unit.get('callsign', unit_id)}")
                    if pump is None: state["missing"].append(f"Pump flow for {unit.get('callsign', unit_id)}")
                    if location is None: state["missing"].append(f"Initial location for {unit.get('callsign', unit_id)}")
                    continue
                initial = min(capacity, vehicle.get("starting_water_l") or 0)
                target = mission.get("target_volume_l") or (mission.get("demand_rate_l_min") or 0) * (mission.get("demand_duration_min") or 0)
                delivery = mission["location"]["coordinates"]
                clock = max(mission.get("earliest_start_min", 0), assignment.get("planned_start_min") or 0)
                if initial > 0 and target > 0:
                    route = route_assessor(unit, vehicle, location, delivery, clock, initial / pump, None) if route_assessor else None
                    if route_assessor and (not route or not route.get("selected")):
                        state["missing"].append(f"Delivery route for {unit.get('callsign', unit_id)}")
                        continue
                    if route and route.get("status") == "unknown":
                        state["route_unknowns"].append(f"Initial delivery route for {unit.get('callsign', unit_id)}")
                    arrive = clock + (route["selected"]["duration_min"] if route else travel_minutes(location, delivery, vehicle))
                    unload = min(initial, target) / pump
                    complete = arrive + unload
                    state["cycles"].append({"unit_id": unit_id, "kind": "initial_load", "depart_min": round(clock, 2),
                                            "delivery_min": round(complete, 2), "litres": min(initial, target)})
                    state["delivered"] += min(initial, target)
                    state["first"] = complete
                    state["busy"] += complete - clock
                    clock, location = complete, delivery
                heapq.heappush(vehicle_heap, (clock, assignment["id"], unit_id, vehicle, mission, target, state["cycles"], state["delivered"]))
        while vehicle_heap:
            clock, assignment_id, unit_id, vehicle, mission, target, cycles, delivered = heapq.heappop(vehicle_heap)
            state = assignment_state[assignment_id]
            # Other vehicles serving the same mission may have delivered since this
            # event was queued. Re-read the shared total to avoid over-delivery.
            delivered = state["delivered"]
            if state["missing"] or delivered >= target or clock >= horizon:
                continue
            if supply_class == "unknown" or flow is None:
                state["missing"].extend([value for value, absent in [("Water supply classification", supply_class == "unknown"),
                                                                      ("Water source flow", flow is None)] if absent])
                continue
            capacity, pump = vehicle["water_tank_capacity_l"], vehicle["pump_flow_l_min"]
            needed = min(capacity, target - delivered)
            if supply_class == "finite":
                if source_remaining is None:
                    state["missing"].append("Available source volume")
                    continue
                needed = min(needed, source_remaining)
            if needed <= 0:
                continue
            unit = units[unit_id]
            current = mission["location"]["coordinates"] if cycles else (unit.get("latest_location") or {})["coordinates"]
            route_to_source = route_assessor(unit, vehicle, current, source["coordinates"], clock, 0, None) if route_assessor else None
            if route_assessor and (not route_to_source or not route_to_source.get("selected")):
                state["missing"].append(f"Source route for {unit.get('callsign', unit_id)}")
                continue
            if route_to_source and route_to_source.get("status") == "unknown":
                state["route_unknowns"].append(f"Source route for {unit.get('callsign', unit_id)}")
            at_source = clock + (route_to_source["selected"]["duration_min"] if route_to_source else travel_minutes(current, source["coordinates"], vehicle))
            slot = min(range(len(slots)), key=lambda index: (slots[index], index))
            fill_start = max(at_source, slots[slot])
            state["wait"] += fill_start - at_source
            setup = water.get("setup_time_min")
            if setup is None:
                setup = 0
                if "Water source setup time assumed to be zero" not in state["assumptions"]:
                    state["assumptions"].append("Water source setup time assumed to be zero")
            effective_flow = min(pump, flow / positions)
            fill_end = fill_start + setup + needed / effective_flow
            slots[slot] = fill_end
            route_to_delivery = route_assessor(unit, vehicle, source["coordinates"], mission["location"]["coordinates"], fill_end, needed / pump, source["coordinates"]) if route_assessor else None
            if route_assessor and (not route_to_delivery or not route_to_delivery.get("selected")):
                state["missing"].append(f"Delivery route for {unit.get('callsign', unit_id)}")
                continue
            if route_to_delivery and route_to_delivery.get("status") == "unknown":
                state["route_unknowns"].append(f"Delivery route for {unit.get('callsign', unit_id)}")
            if route_to_delivery and (route_to_delivery.get("withdrawal") or {}).get("status") == "unavailable":
                state["infeasible"].append(f"Return route for {unit.get('callsign', unit_id)}")
            delivery_arrival = fill_end + (route_to_delivery["selected"]["duration_min"] if route_to_delivery else travel_minutes(source["coordinates"], mission["location"]["coordinates"], vehicle))
            complete = delivery_arrival + needed / pump
            if complete > horizon:
                continue
            if supply_class == "finite":
                source_remaining -= needed
            state["delivered"] += needed
            state["first"] = state["first"] if state["first"] is not None else complete
            state["busy"] += complete - clock
            state["cycles"].append({"unit_id": unit_id, "kind": "supply_cycle", "source_id": source_id,
                                    "source_arrival_min": round(at_source, 2), "fill_start_min": round(fill_start, 2),
                                    "fill_end_min": round(fill_end, 2), "delivery_min": round(complete, 2),
                                    "litres": round(needed, 2), "queue_min": round(fill_start - at_source, 2),
                                    "source_route": route_to_source, "delivery_route": route_to_delivery})
            heapq.heappush(vehicle_heap, (complete, assignment_id, unit_id, vehicle, mission, target, cycles, state["delivered"]))
        for assignment in source_assignments:
            mission = missions[assignment["mission_id"]]
            state = assignment_state[assignment["id"]]
            target = mission.get("target_volume_l") or (mission.get("demand_rate_l_min") or 0) * (mission.get("demand_duration_min") or 0)
            if state["infeasible"]:
                status, message = "infeasible", "A required return route becomes unavailable"
            elif state["missing"]:
                status, message = "unknown", "Missing inputs prevent a numerical water-delivery claim"
            elif state["delivered"] >= target:
                status, message = "completed", "Water demand is fulfilled"
            else:
                status, message = "infeasible", "Water demand is not fulfilled within the evaluation horizon"
            deadline = mission.get("deadline_min")
            completion = max((cycle["delivery_min"] for cycle in state["cycles"]), default=None)
            if status == "completed" and deadline is not None and (completion is None or completion > deadline):
                status, message = "infeasible", "Water delivery completes after the deadline"
            if status == "completed" and state["route_unknowns"]:
                status, message = "unknown", "Water volume is deliverable but route constraints or forecast coverage remain unknown"
            results.append({**_base(assignment, mission), "status": status, "message": message,
                            "first_delivery_min": round(state["first"], 2) if state["first"] is not None else None,
                            "completion_min": completion, "delivered_l": round(state["delivered"], 2),
                            "target_l": target, "unmet_l": round(max(0, target - state["delivered"]), 2),
                            "source_wait_min": round(state["wait"], 2), "vehicle_busy_min": round(state["busy"], 2),
                            "cycles": state["cycles"], "missing_inputs": sorted(set([*state["missing"], *state["route_unknowns"]])),
                            "assumptions": state["assumptions"],
                            "fulfilment": min(1, state["delivered"] / target) if target else 0,
                            "resource_time_min": round(state["busy"], 2)})
    return results


def suggest_plans(snapshot: dict[str, Any], mission_ids: list[str], unit_ids: list[str],
                  locked_assignments: list[dict[str, Any]] | None = None, count: int = 4,
                  forecast_id: str | None = None, budget_seconds: float = 60,
                  route_assessor: Callable | None = None) -> dict[str, Any]:
    started = time.monotonic()
    missions = {value["id"]: value for value in snapshot.get("missions", []) if value["id"] in mission_ids}
    units = {value["id"]: value for value in snapshot.get("units", []) if value["id"] in unit_ids}
    if len(missions) > 10 or len(units) > 10:
        raise ValueError("Select no more than 10 missions and 10 units")
    points = [value for value in snapshot.get("points", []) if value.get("kind") == "water_point"]
    locked = locked_assignments or []
    locked_missions = {value["mission_id"] for value in locked}
    eligible: dict[str, list[str]] = {}
    shortages: list[dict[str, Any]] = []
    for mission in missions.values():
        required = set(mission.get("required_capabilities", []))
        choices = sorted(unit_id for unit_id, unit in units.items()
                         if unit.get("status") != "unavailable" and required.issubset(set(unit.get("capabilities", []))))
        eligible[mission["id"]] = choices
        if len(choices) < mission.get("required_unit_count", 1):
            shortages.append({"mission_id": mission["id"], "reason": "Insufficient eligible units"})
    source_shortlists: dict[str, list[dict[str, Any]]] = {}
    for mission in missions.values():
        if mission["mission_type"] == "water_supply":
            target = mission["location"]["coordinates"]
            source_shortlists[mission["id"]] = [
                {"point_id": value["id"], "name": value["name"], "distance_km": round(distance_km(value["coordinates"], target), 2)}
                for value in sorted(points, key=lambda point: (distance_km(point["coordinates"], target), point["id"]))[:5]
            ]
    candidates = []
    ordered = sorted(missions.values(), key=lambda value: (-value["priority"], value["id"]))
    for variant in range(count * 3):
        if time.monotonic() - started >= budget_seconds:
            break
        assignments = [dict(value) for value in locked]
        busy: set[str] = {unit_id for value in assignments for unit_id in value.get("unit_ids", [])}
        for mission in ordered:
            if mission["id"] in locked_missions:
                continue
            choices = eligible[mission["id"]]
            rotated = choices[variant % len(choices):] + choices[:variant % len(choices)] if choices else []
            required = mission.get("required_unit_count", 1)
            selected = [value for value in rotated if value not in busy][:required]
            if len(selected) < required:
                selected = rotated[:required]
            if len(selected) < required:
                continue
            source_id = None
            if mission["mission_type"] == "water_supply" and source_shortlists.get(mission["id"]):
                sources = source_shortlists[mission["id"]]
                source_id = sources[variant % len(sources)]["point_id"]
            assignment_id = f"suggest-{variant}-{mission['id']}"
            assignments.append({"id": assignment_id, "mission_id": mission["id"], "unit_ids": selected,
                                "source_point_id": source_id, "planned_start_min": mission.get("earliest_start_min", 0),
                                "locked": False})
            busy.update(selected)
        plan = {"id": f"candidate-{variant + 1}", "name": f"Candidate {variant + 1}", "revision": 1,
                "assignments": assignments, "assumptions": []}
        evaluation = evaluate_plan(snapshot, plan, forecast_id=forecast_id, route_assessor=route_assessor)
        fingerprint = tuple((value["mission_id"], tuple(value["unit_ids"]), value.get("source_point_id")) for value in assignments)
        if any(item["fingerprint"] == fingerprint for item in candidates):
            continue
        candidates.append({"plan": plan, "evaluation": evaluation, "fingerprint": fingerprint})
        if len(candidates) >= count:
            break
    candidates.sort(key=lambda item: _rank_key(item["evaluation"]))
    return {"plans": [{**item["plan"], "evaluation": item["evaluation"]} for item in candidates[:count]],
            "shortages": shortages, "water_source_shortlists": source_shortlists,
            "partial": time.monotonic() - started >= budget_seconds,
            "message": "Candidate suggestions use a bounded deterministic search; they are not guaranteed global optima."}


def _rank_key(value):
    fulfilment = value["fulfilment_by_priority"]
    return tuple([-fulfilment[str(priority)] for priority in range(5, 0, -1)] +
                 [len(value["unresolved_unknowns"]), -(value.get("minimum_forecast_margin_min") or -1e9),
                  value["total_resource_time_min"], value["plan_id"]])


def _base(assignment, mission):
    return {"assignment_id": assignment["id"], "mission_id": mission["id"], "mission_name": mission["name"],
            "mission_type": mission["mission_type"], "priority": mission["priority"],
            "unit_ids": assignment.get("unit_ids", [])}


def _failed(assignment, message, mission=None):
    base = _base(assignment, mission) if mission else {"assignment_id": assignment["id"],
                                                       "mission_id": assignment.get("mission_id"), "priority": 0}
    return {**base, "status": "infeasible", "message": message, "fulfilment": 0,
            "missing_inputs": [], "resource_time_min": 0}


def _time_offset(value: str | None, reference: str | None) -> float | None:
    if not value or not reference:
        return None
    return (datetime.fromisoformat(value) - datetime.fromisoformat(reference)).total_seconds() / 60
