from __future__ import annotations

import json
import hmac
import os
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Cookie, HTTPException, Request, Response

from .area_packages import package_path
from .models import (LocationCreate, MobilityRouteRequest, MovementAction, MovementCreate, MovementRevision, RoutePlanInput,
                     OperationalUnit, RoadReport, RoadReportReview, ShareCreate, VehicleProfile,
                     WaterSourceReportCreate, WaterSourceReportReview)
from .mobility_routing import route_mobility
from .mobility_demo import demo_snapshot
from .mobility_storage import (MobilityConflict, MobilityNotFound, act_on_movement, add_location,
                               create_movement, create_share, create_user, list_events,
                               list_movements, list_road_reports, list_route_plans, list_units, list_vehicles,
                               list_water_reports, review_water_report, save_water_report, water_statuses,
                               login, logout, mobility_metrics, movement, review_road_report, revise_movement, revoke_share, save_road_report,
                               save_route_plan, delete_route_plan, save_unit, save_vehicle, session_user, shared_movement, update_unit_status)
from .storage import connect, get_scenario, list_scenarios


router = APIRouter()
SHARED_MODE = os.getenv("FIRELINE_SHARED_MODE", "0").lower() in {"1", "true", "yes"}


def _user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if user:
        return user
    if not SHARED_MODE:
        return {"id": "local", "username": "local", "display_name": "Local dispatcher", "role": "administrator"}
    raise HTTPException(401, "Sign in required")


def _dispatcher(request: Request) -> dict:
    user = _user(request)
    if user["role"] not in {"administrator", "dispatcher"}:
        raise HTTPException(403, "Dispatcher access required")
    return user


def _crew_unit(scenario_id: str, user: dict) -> str | None:
    if user["role"] != "crew":
        return None
    with connect() as db:
        row = db.execute("SELECT unit_id FROM mobility_memberships WHERE scenario_id=? AND user_id=?",
                         (scenario_id, user["id"])).fetchone()
    if not row or not row["unit_id"]:
        raise HTTPException(403, "No unit is assigned to this user for this incident")
    return row["unit_id"]


@router.get("/api/health")
def health():
    return {"status": "ok", "shared_mode": SHARED_MODE}


@router.post("/api/session")
def create_session(response: Response, payload: dict = Body(...)):
    try:
        token, user = login(str(payload.get("username", "")), str(payload.get("password", "")))
    except PermissionError as error:
        raise HTTPException(401, str(error)) from error
    response.set_cookie("fireline_session", token, httponly=True, samesite="strict", secure=SHARED_MODE,
                        max_age=12 * 3600, path="/")
    return user


@router.get("/api/session")
def read_session(request: Request):
    return _user(request)


@router.delete("/api/session")
def delete_session(response: Response, fireline_session: str | None = Cookie(None)):
    logout(fireline_session)
    response.delete_cookie("fireline_session", path="/")
    return {"signed_out": True}


@router.post("/api/users", status_code=201)
def add_user(request: Request, payload: dict = Body(...)):
    user = _user(request)
    if user["role"] != "administrator":
        raise HTTPException(403, "Administrator access required")
    try:
        return create_user(str(payload["username"]), str(payload.get("display_name") or payload["username"]),
                           str(payload["password"]), str(payload["role"]))
    except (KeyError, ValueError) as error:
        raise HTTPException(422, str(error)) from error


@router.put("/api/scenarios/{scenario_id}/mobility/memberships/{user_id}")
def set_membership(scenario_id: str, user_id: str, request: Request, payload: dict = Body(...)):
    _dispatcher(request)
    get_scenario(scenario_id)
    with connect() as db:
        db.execute("INSERT INTO mobility_memberships(scenario_id,user_id,unit_id) VALUES (?,?,?) "
                   "ON CONFLICT(scenario_id,user_id) DO UPDATE SET unit_id=excluded.unit_id",
                   (scenario_id, user_id, payload.get("unit_id")))
    return {"scenario_id": scenario_id, "user_id": user_id, "unit_id": payload.get("unit_id")}


@router.get("/api/scenarios/{scenario_id}/mobility")
def mobility_snapshot(scenario_id: str, request: Request):
    user = _user(request)
    try:
        workspace = get_scenario(scenario_id)
    except KeyError:
        raise HTTPException(404, "Scenario not found")
    unit_id = _crew_unit(scenario_id, user)
    reports = list_road_reports(scenario_id)
    water_reports = list_water_reports(scenario_id)
    current_sources = water_statuses(scenario_id)
    sources = []
    for point in workspace.points:
        if point.kind != "water_point":
            continue
        source = point.model_dump(mode="json")
        current = current_sources.get(point.id)
        if current:
            source["water"]["availability"] = "unknown" if current["availability"] == "uncertain" else current["availability"]
            source["water"]["verification_status"] = "verified"
            source["water"]["observed_at"] = current["observed_at"]
            source["verified_by"] = current["reviewer_id"]
            source["verified_at"] = current["reviewed_at"]
        sources.append(source)
    if user["role"] == "crew":
        reports = [report for report in reports if report["status"] == "confirmed"]
        water_reports = [report for report in water_reports
                         if report["status"] == "confirmed" or report["reporter_id"] == user["id"]]
    demo, communications = demo_snapshot(scenario_id)
    return {"user": user, "scenario": {"id": workspace.id, "name": workspace.name,
                                         "simulation": workspace.simulation.model_dump(mode="json")},
            "vehicles": list_vehicles(scenario_id) if not unit_id else [],
            "units": [item for item in list_units(scenario_id) if not unit_id or item["id"] == unit_id],
            "road_reports": reports, "movements": list_movements(scenario_id, unit_id),
            "water_sources": sources, "water_reports": water_reports,
            "incident_points": [point.model_dump(mode="json") for point in workspace.points
                                if point.kind in {"hazard", "access_control", "staging_area", "shelter", "response_base"}],
            "events": list_events(scenario_id, 100) if not unit_id else [],
            "demo": demo, "communications": communications if not unit_id else [],
            "server_time": datetime.now(UTC).isoformat()}


@router.get("/api/mobility/metrics")
def all_mobility_metrics(request: Request):
    _dispatcher(request)
    scenario_ids = [scenario.id for scenario in list_scenarios()]
    return {"scenarios": mobility_metrics(scenario_ids), "server_time": datetime.now(UTC).isoformat()}


@router.get("/api/scenarios/{scenario_id}/mobility/roads")
def mobility_roads(scenario_id: str, request: Request):
    user = _user(request)
    if user["role"] == "crew":
        _crew_unit(scenario_id, user)
    try:
        workspace = get_scenario(scenario_id)
    except KeyError:
        raise HTTPException(404, "Scenario not found")
    path = package_path(workspace.area_package_id) / "roads.geojson"
    if not path.exists():
        raise HTTPException(409, "Prepare the scenario road area before opening mobility")
    return json.loads(path.read_text())


@router.post("/api/scenarios/{scenario_id}/mobility/vehicles", status_code=201)
def add_vehicle(scenario_id: str, value: VehicleProfile, request: Request):
    _dispatcher(request); get_scenario(scenario_id)
    return save_vehicle(scenario_id, value)


@router.post("/api/scenarios/{scenario_id}/mobility/units", status_code=201)
def add_unit(scenario_id: str, value: OperationalUnit, request: Request):
    _dispatcher(request); get_scenario(scenario_id)
    try:
        return save_unit(scenario_id, value)
    except MobilityNotFound:
        raise HTTPException(422, "Select an existing vehicle")


@router.patch("/api/scenarios/{scenario_id}/mobility/units/{unit_id}/status")
def set_unit_status(scenario_id: str, unit_id: str, request: Request, payload: dict = Body(...)):
    _dispatcher(request)
    try:
        return update_unit_status(scenario_id, unit_id, str(payload.get("status")), int(payload.get("expected_revision", 0)))
    except MobilityNotFound:
        raise HTTPException(404, "Unit not found")
    except MobilityConflict as error:
        raise HTTPException(409, str(error)) from error
    except (ValueError, TypeError) as error:
        raise HTTPException(422, str(error)) from error


@router.post("/api/scenarios/{scenario_id}/mobility/units/{unit_id}/locations", status_code=201)
def check_in(scenario_id: str, unit_id: str, value: LocationCreate, request: Request):
    user = _user(request)
    own_unit = _crew_unit(scenario_id, user)
    if own_unit and own_unit != unit_id:
        raise HTTPException(403, "Crew users can update only their assigned unit")
    try:
        return add_location(scenario_id, unit_id, value)
    except MobilityNotFound:
        raise HTTPException(404, "Unit not found")


@router.post("/api/scenarios/{scenario_id}/mobility/road-reports", status_code=201)
def add_report(scenario_id: str, value: RoadReport, request: Request):
    user = _user(request)
    _crew_unit(scenario_id, user) if user["role"] == "crew" else None
    if user["role"] == "crew":
        value.source, value.status = "crew", "pending"
        value.segment_id = None
    return save_road_report(scenario_id, value, user["id"])


@router.post("/api/scenarios/{scenario_id}/mobility/water-reports", status_code=201)
def add_water_report(scenario_id: str, value: WaterSourceReportCreate, request: Request):
    user = _user(request)
    if user["role"] == "crew":
        _crew_unit(scenario_id, user)
    workspace = get_scenario(scenario_id)
    if not any(point.id == value.point_id and point.kind == "water_point" for point in workspace.points):
        raise HTTPException(422, "Select an existing water source")
    return save_water_report(scenario_id, value.point_id, value.availability, value.note,
                             value.observed_at.isoformat(), user["id"], "crew" if user["role"] == "crew" else "dispatcher")


@router.post("/api/scenarios/{scenario_id}/mobility/water-reports/{report_id}/review")
def review_source_report(scenario_id: str, report_id: str, value: WaterSourceReportReview, request: Request):
    user = _dispatcher(request)
    try:
        return review_water_report(scenario_id, report_id, value.status, value.expected_revision, user["id"])
    except MobilityNotFound:
        raise HTTPException(404, "Water report not found")
    except MobilityConflict as error:
        raise HTTPException(409, str(error)) from error


@router.post("/api/scenarios/{scenario_id}/mobility/road-reports/{report_id}/review")
def review_report(scenario_id: str, report_id: str, value: RoadReportReview, request: Request):
    user = _dispatcher(request)
    if value.segment_id:
        roads = mobility_roads(scenario_id, request)
        if value.segment_id not in {str(feature.get("properties", {}).get("segment_id")) for feature in roads.get("features", [])}:
            raise HTTPException(422, "Select a segment from the prepared road network")
    try:
        return review_road_report(scenario_id, report_id, value.status, value.expected_revision, user["id"],
                                  value.segment_id, value.direction)
    except MobilityNotFound:
        raise HTTPException(404, "Road report not found")
    except MobilityConflict:
        raise HTTPException(409, "Road report changed; refresh before reviewing")


@router.post("/api/scenarios/{scenario_id}/mobility/routes")
def preview_route(scenario_id: str, value: MobilityRouteRequest, request: Request):
    _dispatcher(request)
    workspace = get_scenario(scenario_id)
    vehicle = (next((VehicleProfile.model_validate(item) for item in list_vehicles(scenario_id)
                     if item["id"] == value.vehicle_id), None) if value.vehicle_id else
               VehicleProfile(id=f"planning-{value.vehicle_class}", name="Viatura de planeamento",
                              vehicle_class=value.vehicle_class))
    if not vehicle:
        raise HTTPException(404, "Vehicle not found")
    try:
        return route_mobility(package_path(workspace.area_package_id), value, vehicle, list_road_reports(scenario_id))
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/api/scenarios/{scenario_id}/mobility/route-plans")
def route_plans(scenario_id: str, request: Request):
    _dispatcher(request)
    get_scenario(scenario_id)
    return list_route_plans(scenario_id)


def _plan_route_request(value: RoutePlanInput) -> MobilityRouteRequest:
    return MobilityRouteRequest(origin=value.origin, destination=value.destination,
                                vehicle_class=value.vehicle_class, departure_at=value.departure_at)


@router.post("/api/scenarios/{scenario_id}/mobility/route-plans", status_code=201)
def add_route_plan(scenario_id: str, value: RoutePlanInput, request: Request):
    _dispatcher(request)
    try:
        route = _verified_route(scenario_id, _plan_route_request(value), value.preview_signature, request)
        return save_route_plan(scenario_id, value, route)
    except MobilityConflict as error:
        raise HTTPException(409, str(error)) from error


@router.put("/api/scenarios/{scenario_id}/mobility/route-plans/{plan_id}")
def update_route_plan(scenario_id: str, plan_id: str, value: RoutePlanInput, request: Request):
    _dispatcher(request)
    try:
        route = _verified_route(scenario_id, _plan_route_request(value), value.preview_signature, request)
        return save_route_plan(scenario_id, value, route, plan_id)
    except MobilityNotFound:
        raise HTTPException(404, "Route plan not found")
    except MobilityConflict as error:
        raise HTTPException(409, str(error)) from error


@router.delete("/api/scenarios/{scenario_id}/mobility/route-plans/{plan_id}")
def discard_route_plan(scenario_id: str, plan_id: str, expected_revision: int, request: Request):
    _dispatcher(request)
    try:
        delete_route_plan(scenario_id, plan_id, expected_revision)
        return {"deleted": True}
    except MobilityNotFound:
        raise HTTPException(404, "Route plan not found")
    except MobilityConflict as error:
        raise HTTPException(409, str(error)) from error


@router.post("/api/scenarios/{scenario_id}/mobility/movements", status_code=201)
def assign_movement(scenario_id: str, value: MovementCreate, request: Request):
    user = _dispatcher(request)
    try:
        route = _verified_route(scenario_id, MobilityRouteRequest(origin=value.origin, destination=value.destination,
                                vehicle_id=value.vehicle_id, departure_at=value.departure_at), value.preview_signature, request)
        return create_movement(scenario_id, value, user["id"], route=route)
    except MobilityNotFound:
        raise HTTPException(422, "Unit or vehicle not found")
    except MobilityConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/api/scenarios/{scenario_id}/mobility/movements/{movement_id}")
def get_movement(scenario_id: str, movement_id: str, request: Request):
    user = _user(request)
    unit_id = _crew_unit(scenario_id, user)
    try:
        value = movement(scenario_id, movement_id)
    except MobilityNotFound:
        raise HTTPException(404, "Movement not found")
    if unit_id and value["unit_id"] != unit_id:
        raise HTTPException(403, "This movement is assigned to another unit")
    return value


@router.post("/api/scenarios/{scenario_id}/mobility/movements/{movement_id}/actions")
def movement_action(scenario_id: str, movement_id: str, value: MovementAction, request: Request):
    user = _user(request)
    unit_id = _crew_unit(scenario_id, user)
    current = movement(scenario_id, movement_id)
    if unit_id and current["unit_id"] != unit_id:
        raise HTTPException(403, "This movement is assigned to another unit")
    if user["role"] == "crew":
        value.source = "crew"
    try:
        return act_on_movement(scenario_id, movement_id, value, user["id"])
    except MobilityConflict as error:
        raise HTTPException(409, str(error)) from error


@router.post("/api/scenarios/{scenario_id}/mobility/movements/{movement_id}/route")
def revise_movement_route(scenario_id: str, movement_id: str, value: MovementRevision, request: Request):
    user = _dispatcher(request)
    try:
        current = movement(scenario_id, movement_id)
        route = _verified_route(scenario_id, MobilityRouteRequest(origin=current["origin"], destination=current["destination"],
                                vehicle_id=current["vehicle_id"], departure_at=value.departure_at), value.preview_signature, request)
        return revise_movement(scenario_id, movement_id, value, user["id"], route=route)
    except MobilityNotFound:
        raise HTTPException(404, "Movement not found")
    except MobilityConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/api/scenarios/{scenario_id}/mobility/movements/{movement_id}/shares")
def share_movement(scenario_id: str, movement_id: str, value: ShareCreate, request: Request):
    _dispatcher(request)
    movement(scenario_id, movement_id)
    token = create_share(movement_id, value.expires_hours)
    return {"token": token, "url": f"/brief/{token}", "expires_hours": value.expires_hours}


@router.delete("/api/scenarios/{scenario_id}/mobility/shares/{token}")
def delete_share(scenario_id: str, token: str, request: Request):
    _dispatcher(request); get_scenario(scenario_id)
    try:
        revoke_share(token)
    except MobilityNotFound:
        raise HTTPException(404, "Share not found")
    return {"revoked": True}


@router.get("/api/mobility/shared/{token}")
def read_shared_brief(token: str):
    try:
        return shared_movement(token)
    except MobilityNotFound:
        raise HTTPException(404, "This brief is unavailable or has expired")


def resolve_session(request: Request) -> dict | None:
    return session_user(request.cookies.get("fireline_session"))


def _verified_route(scenario_id: str, route_request: MobilityRouteRequest, signature: str, request: Request) -> dict:
    route = preview_route(scenario_id, route_request, request)
    if route.get("status") == "unavailable" or not hmac.compare_digest(route.get("preview_signature", ""), signature):
        raise MobilityConflict("Route preview is stale or differs from the current journey; calculate it again")
    return route
