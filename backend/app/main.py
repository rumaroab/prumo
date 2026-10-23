from __future__ import annotations

import json
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .engines import ENGINES, available_engines, compatible_profile
from .area_packages import (_distance_km, cancel_preparation, create_preparation, estimate_preparation,
                            get_preparation, package_manifest, package_path, recover_preparations,
                            retry_preparation)
from .io import load_landscape, load_result
from .models import (
    AllocationComparisonRequest,
    AllocationRankRequest,
    ContainmentSuggestionsRequest,
    PointCreate,
    PointImport,
    PointPatch,
    RouteAnalysisRequest,
    RunCreate,
    RunMetadataPatch,
    Scenario,
    ScenarioCreate,
    ScenarioPatch,
    ScenarioRename,
    ScenarioPoint,
    ScenarioRunCreate,
    WaterPointDetails,
    AreaPreparationCreate,
    AreaPreparationEstimate,
    FogosImportPreview,
    FogosResourceSync,
    FogosResourceSyncResponse,
    FogosTrackingUpdate,
    FogosWeatherApply,
    ObservationEvaluationCreate,
)
from .runners import SshSlurmRunner
from .seed_demo import seed
from .services.exposure import ANALYSIS_VERSION, analyse, roads_revision
from .services.fire_layer import footprint
from .services.comparison import comparison_payload
from .services.routing import analyse_routes
from .services.allocation import (allocation_comparison as allocation_comparison_payload,
                                  build_intervention, rank_plans, suggest_tasks)
from .settings import CONFIG, FRONTEND, PREPARED, ROOT, RUNS
from .storage import (
    ScenarioConflictError,
    ScenarioBusyError,
    RunBusyError,
    RunConflictError,
    RunDependencyError,
    child_runs,
    create_run,
    create_scenario,
    delete_scenario,
    delete_run,
    get_run as stored_get_run,
    get_scenario,
    init_db,
    list_scenarios,
    rename_scenario,
    scenario_runs,
    update_run,
    update_run_metadata,
    update_scenario,
)
from .weather import list_weather_series, save_weather_series, validate_weather_coverage
from . import fogos, storage
from .services.observation import evaluate as evaluate_observation, list_evaluations
from .mobility_api import SHARED_MODE, resolve_session, router as mobility_router
from .demo_api import router as demo_router
from .exercise_api import router as exercise_router
from .mobility_comparison import router as mobility_comparison_router
from .access_assessment import router as access_assessment_router
from .mobility_demo import scenario_demo_locked
from .mobility_storage import init_mobility_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed()
    init_mobility_db()
    recover_preparations()
    worker = subprocess.Popen([sys.executable, "-m", "backend.app.worker"], cwd=ROOT)
    app.state.worker = worker
    yield
    worker.terminate()
    worker.wait(timeout=5)


app = FastAPI(title="PRUMO", lifespan=lifespan)
app.include_router(mobility_router)
app.include_router(demo_router)
app.include_router(exercise_router)
app.include_router(mobility_comparison_router)
app.include_router(access_assessment_router)


def _api_error_code(detail: object, status_code: int) -> str:
    message = str(detail).lower()
    if "route preview" in message or "calculate the route again" in message or "route is required" in message:
        return "ROUTE_PREVIEW_STALE"
    if "unavailable route" in message or "no route is available" in message:
        return "ROUTE_UNAVAILABLE"
    if "unit" in message and "unavailable" in message:
        return "UNIT_UNAVAILABLE"
    if "report changed" in message or "scenario changed" in message or "movement changed" in message:
        return "REVISION_CONFLICT"
    if status_code == 410:
        return "ARCHIVED_ACTION"
    return f"HTTP_{status_code}"


@app.exception_handler(HTTPException)
async def api_http_exception(_request: Request, error: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, headers=error.headers,
                        content={"detail": jsonable_encoder(error.detail),
                                 "code": _api_error_code(error.detail, error.status_code)})
WATER_PRESETS = ROOT / "data" / "presets" / "guimaraes-water-points.geojson"
FIRE_STATIONS = PREPARED / "fire-stations.geojson"


@app.middleware("http")
async def shared_server_authentication(request: Request, call_next):
    request.state.user = resolve_session(request)
    public = (request.url.path in {"/api/session", "/api/health"}
              or request.url.path.startswith("/api/mobility/shared/")
              or not request.url.path.startswith("/api/"))
    if SHARED_MODE and not public and request.state.user is None:
        return JSONResponse({"detail": "Sign in required", "code": "HTTP_401"}, status_code=401)
    if (SHARED_MODE and request.state.user and request.state.user["role"] == "crew"
            and request.url.path.startswith("/api/")
            and "/mobility" not in request.url.path and request.url.path not in {"/api/session", "/api/health"}):
        return JSONResponse({"detail": "Crew access is limited to assigned mobility work", "code": "HTTP_403"}, status_code=403)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and _retired_action(request.url.path):
        return JSONResponse({"detail": "This planning action is archived. Use the mobility workspace for live coordination.", "code": "ARCHIVED_ACTION",
                             "workspace": _mobility_link(request.url.path)}, status_code=410)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith("/api/scenarios/"):
        parts = request.url.path.split("/")
        if len(parts) > 3 and scenario_demo_locked(parts[3]):
            return JSONResponse({"detail": "This demonstration is controlled by the demo runner", "code": "HTTP_423"}, status_code=423)
    return await call_next(request)


def _mobility_link(path: str) -> str:
    parts = path.split("/")
    return f"/scenarios/{parts[3]}/mobility" if len(parts) > 3 and parts[2] == "scenarios" else "/scenarios"


def _retired_action(path: str) -> bool:
    archived = ("/missions", "/response-plans", "/response-experiments", "/exercise-runs",
                "/exercise-situation", "/situation-snapshots", "/exercise-routes",
                "/exercise-copy", "/allocation-plans", "/allocation-comparisons",
                "/containment-suggestions")
    return ((path.startswith("/api/scenarios/") and any(marker in path for marker in archived))
            or (path.startswith("/api/runs/") and path.endswith("/routes")))


def get_run(run_id: str):
    try:
        run = stored_get_run(run_id)
        if run.scenario_id:
            get_scenario(run.scenario_id)
        return run
    except KeyError:
        raise HTTPException(404, "Run not found")


@app.get("/api/area")
def area(package_id: str | None = None):
    prepared = package_path(package_id)
    landscape = prepared / "landscape.json"
    roads = prepared / "roads.json"
    try:
        manifest = package_manifest(package_id)
    except KeyError:
        raise HTTPException(404, "Area package not found")
    return {**CONFIG["area"], "bounds": manifest.get("resource_bounds", manifest.get("bounds", CONFIG["area"]["bounds"])),
            **{key: manifest[key] for key in ("center", "fire_bounds", "resource_bounds") if key in manifest},
            "package_id": package_id, "manifest": manifest,
            "landscape_ready": landscape.exists(), "roads_ready": roads.exists(),
            "landscape": json.loads(landscape.read_text()) if landscape.exists() else None,
            "roads": json.loads(roads.read_text()) if roads.exists() else None}


@app.post("/api/area-preparations", status_code=202)
def prepare_area(request: AreaPreparationCreate):
    try:
        return create_preparation(request).model_dump(mode="json")
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/api/area-preparations/estimate", response_model=AreaPreparationEstimate)
def estimate_area(request: AreaPreparationCreate):
    try:
        return estimate_preparation(request)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/api/area-preparations/{preparation_id}")
def preparation_status(preparation_id: str):
    try:
        return get_preparation(preparation_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "Area preparation not found")


@app.post("/api/area-preparations/{preparation_id}/cancel")
def stop_preparation(preparation_id: str):
    try:
        return cancel_preparation(preparation_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "Area preparation not found")


@app.post("/api/area-preparations/{preparation_id}/retry", status_code=202)
def retry_area(preparation_id: str):
    try:
        return retry_preparation(preparation_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "Area preparation not found")


@app.get("/api/engines")
def engines():
    return available_engines()


@app.get("/api/integrations/fogos/status")
def fogos_status():
    value = fogos.configuration()
    with storage.connect() as db:
        row = db.execute("""SELECT MAX(last_success_at) AS last_success_at,
                          MAX(CASE WHEN last_error IS NOT NULL THEN last_error END) AS last_error
                          FROM external_incidents WHERE provider='fogos.pt'""").fetchone()
    value["last_success_at"] = row["last_success_at"] if row else None
    value["last_error"] = row["last_error"] if row else None
    value["health"] = ("unavailable" if not value["configured"] else "degraded" if value["last_error"]
                       else "healthy" if value["last_success_at"] else "not_checked")
    return value


@app.get("/api/integrations/fogos/incidents")
def fogos_incidents(mode: str = Query("active", pattern="^(active|historical)$"),
                    municipality: str | None = None, day: str | None = None,
                    after: str | None = None, before: str | None = None,
                    page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=100)):
    try:
        if mode == "historical" and after and not before:
            raise HTTPException(422, "Historical date ranges require both after and before")
        return fogos.list_incidents(mode=mode, municipality=municipality, day=day,
                                    after=after, before=before, page=page, limit=limit)
    except fogos.FogosError as error:
        raise HTTPException(502, str(error))


@app.post("/api/integrations/fogos/import-preview")
def fogos_import_preview(request: FogosImportPreview):
    try:
        return fogos.import_preview(request.incident_id)
    except KeyError:
        raise HTTPException(404, "Fogos.pt incident not found")
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except fogos.FogosError as error:
        raise HTTPException(502, str(error))


@app.get("/api/scenarios")
def scenarios():
    return [scenario.model_dump(mode="json") for scenario in list_scenarios()]


@app.post("/api/scenarios", status_code=201)
def add_scenario(request: ScenarioCreate, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    if (request.scenario_kind == "exercise" or request.source_scenario_id or request.closures or request.teams
            or request.containment_tasks or request.allocation_plans):
        raise HTTPException(410, "Planning inputs are archived; create a prepared incident for Mobility")
    simulation = request.simulation or Scenario(name=request.name, ignition=tuple(CONFIG["area"]["center"]))
    try:
        return create_scenario(simulation, name=request.name, description=request.description,
                               area_id=request.area_id, start_time=request.start_time,
                               resource_center=request.resource_center, resource_radius_km=request.resource_radius_km,
                               fire_margin_km=request.fire_margin_km, cell_size_m=request.cell_size_m,
                               area_package_id=request.area_package_id,
                               points=request.points, closures=request.closures, teams=request.teams,
                               resource_groups=request.resource_groups,
                               containment_tasks=request.containment_tasks,
                               allocation_plans=request.allocation_plans,
                               fogos_snapshot_id=request.fogos_snapshot_id,
                               import_request_id=idempotency_key,
                               scenario_kind=request.scenario_kind,
                               source_scenario_id=request.source_scenario_id).model_dump(mode="json")
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/api/scenarios/{scenario_id}")
def scenario_detail(scenario_id: str):
    try:
        return get_scenario(scenario_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "Scenario not found")


@app.get("/api/scenarios/{scenario_id}/external-incident")
def scenario_external_incident(scenario_id: str):
    try:
        return fogos.context_for_scenario(scenario_id)
    except KeyError:
        raise HTTPException(404, "Scenario is not linked to a Fogos.pt incident")


@app.post("/api/scenarios/{scenario_id}/external-incident/refresh")
def refresh_external_incident(scenario_id: str):
    try:
        return fogos.refresh_scenario(scenario_id)
    except KeyError:
        raise HTTPException(404, "Scenario or Fogos.pt incident not found")
    except fogos.FogosError as error:
        raise HTTPException(502, str(error))


@app.post("/api/scenarios/{scenario_id}/external-incident/sync", response_model=FogosResourceSyncResponse)
def sync_external_incident(scenario_id: str, request: FogosResourceSync):
    try:
        return fogos.sync_scenario_resources(scenario_id, request.expected_revision)
    except KeyError:
        raise HTTPException(404, "Scenario is not linked to a Fogos.pt incident")
    except ScenarioConflictError:
        raise HTTPException(409, "Scenario changed in another browser tab; reload before synchronizing")
    except fogos.FogosError as error:
        raise HTTPException(502, str(error))


@app.get("/api/scenarios/{scenario_id}/external-incident/snapshots")
def external_incident_snapshots(scenario_id: str, product_type: str | None = None):
    try:
        workspace = get_scenario(scenario_id)
        if not workspace.external_incident:
            raise KeyError(scenario_id)
        return fogos.snapshots(workspace.external_incident["incident_id"], product_type)
    except KeyError:
        raise HTTPException(404, "Scenario is not linked to a Fogos.pt incident")


@app.put("/api/scenarios/{scenario_id}/external-incident/tracking")
def external_incident_tracking(scenario_id: str, request: FogosTrackingUpdate):
    try:
        return fogos.set_tracking(scenario_id, request.enabled)
    except KeyError:
        raise HTTPException(404, "Scenario is not linked to a Fogos.pt incident")


@app.get("/api/scenarios/{scenario_id}/fogos/layers/{layer}")
def fogos_layer(scenario_id: str, layer: str):
    if layer not in {"weather", "perimeter", "pyrocast", "risk", "aircraft", "icnf", "vost", "firms"}:
        raise HTTPException(404, "Unknown Fogos.pt layer")
    try:
        return fogos.contextual_layer(scenario_id, layer)
    except KeyError:
        raise HTTPException(404, "Fogos.pt data is unavailable")
    except ValueError as error:
        raise HTTPException(422, str(error))
    except fogos.FogosError as error:
        raise HTTPException(502, str(error))


@app.post("/api/scenarios/{scenario_id}/fogos/weather-series", status_code=201)
def fogos_weather_series(scenario_id: str):
    try:
        return fogos.create_weather_series(scenario_id)
    except KeyError:
        raise HTTPException(404, "Scenario is not linked to a Fogos.pt incident")
    except (ValueError, fogos.FogosError) as error:
        raise HTTPException(422 if isinstance(error, ValueError) else 502, str(error))


@app.post("/api/scenarios/{scenario_id}/fogos/apply-weather")
def apply_fogos_weather(scenario_id: str, request: FogosWeatherApply):
    try:
        workspace = get_scenario(scenario_id)
        context = fogos.context_for_scenario(scenario_id)
        incident = (context.get("latest_incident") or {}).get("normalized", {})
        weather = incident.get("weather")
        if not weather:
            raise HTTPException(422, "Fogos.pt has no usable wind observation for this incident")
        if not incident.get("active"):
            raise HTTPException(422, "Current weather cannot be applied as historical incident conditions")
        simulation = workspace.simulation.model_copy(update={
            "wind_speed_kmh": weather["wind_speed_kmh"],
            "wind_direction_deg": weather["wind_direction_deg"],
            "weather_source": {"kind": "constant", "provenance": {
                "provider": "fogos.pt", "snapshot_id": context["latest_incident"]["id"],
                "observed_at": weather.get("observed_at"),
                "station_id": weather.get("station_id"), "applied_at": datetime.now(UTC).isoformat(),
            }},
        })
        values = workspace.model_dump(exclude={"id", "revision", "created_at", "updated_at",
                                                "setup_complete", "external_incident"})
        values.update({"expected_revision": request.expected_revision, "simulation": simulation})
        return update_scenario(scenario_id, ScenarioPatch(**values)).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "Scenario is not linked to a Fogos.pt incident")
    except ScenarioConflictError:
        raise HTTPException(409, "Scenario changed in another browser tab; reload before applying weather")


@app.patch("/api/scenarios/{scenario_id}")
def edit_scenario(scenario_id: str, request: ScenarioPatch):
    try:
        current = get_scenario(scenario_id)
        if current.scenario_kind == "exercise":
            raise HTTPException(410, "Historical exercise scenarios are read-only")
        if (request.scenario_kind != current.scenario_kind
                or request.source_scenario_id != current.source_scenario_id
                or request.allocation_plans != current.allocation_plans
                or request.containment_tasks != current.containment_tasks
                or request.closures != current.closures or request.teams != current.teams):
            raise HTTPException(410, "Planning records are archived; use the mobility workspace")
        return update_scenario(scenario_id, request).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "Scenario not found")
    except ScenarioConflictError:
        raise HTTPException(409, "Scenario changed in another browser tab; reload before saving")
    except ScenarioBusyError as error:
        raise HTTPException(409, str(error)) from error


@app.patch("/api/scenarios/{scenario_id}/name")
def rename_scenario_name(scenario_id: str, request: ScenarioRename):
    try:
        if get_scenario(scenario_id).scenario_kind == "exercise":
            raise HTTPException(410, "Historical exercise scenarios are read-only")
        return rename_scenario(scenario_id, request.name, request.expected_revision).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "Scenario not found")
    except ScenarioConflictError:
        raise HTTPException(409, "Scenario changed in another browser tab; close and reopen Manage scenarios")


@app.delete("/api/scenarios/{scenario_id}")
def remove_scenario(scenario_id: str, expected_revision: int = Query(..., ge=1)):
    try:
        if get_scenario(scenario_id).scenario_kind == "exercise":
            raise HTTPException(410, "Historical exercise scenarios are retained in the read-only archive")
        delete_scenario(scenario_id, expected_revision)
        return {"deleted": True}
    except KeyError:
        raise HTTPException(404, "Scenario not found")
    except ScenarioConflictError:
        raise HTTPException(409, "Scenario changed in another browser tab; close and reopen Manage scenarios")
    except ScenarioBusyError as error:
        detail = str(error)
        if detail == scenario_id:
            detail = "This scenario has an active simulation. Cancel it or wait for it to finish before deleting."
        raise HTTPException(409, detail) from error


@app.get("/api/scenarios/{scenario_id}/runs")
def scenario_run_history(scenario_id: str):
    try:
        get_scenario(scenario_id)
    except KeyError:
        raise HTTPException(404, "Scenario not found")
    return [_run_payload(run) for run in scenario_runs(scenario_id)]


@app.post("/api/scenarios/{scenario_id}/runs", status_code=202)
def queue_scenario_run(scenario_id: str, request: ScenarioRunCreate):
    try:
        workspace = get_scenario(scenario_id)
    except KeyError:
        raise HTTPException(404, "Scenario not found")
    if workspace.scenario_kind == "exercise":
        raise HTTPException(410, "Historical exercise scenarios are read-only")
    if not workspace.setup_complete:
        raise HTTPException(409, "Complete scenario location and area preparation before creating an experiment")
    _validate_prepared_ignitions(workspace)
    wrapped = RunCreate(scenario=workspace.simulation, mode=request.mode, ensemble=request.ensemble)
    _validate_request(wrapped, workspace.start_time)
    ensemble = request.ensemble.model_dump(mode="json") if request.ensemble else None
    run = create_run(workspace.simulation, mode=request.mode, ensemble=ensemble,
                     scenario_id=workspace.id, scenario_revision=workspace.revision,
                     area_package_id=workspace.area_package_id,
                     name=request.name, notes=request.notes)
    return _run_payload(run)


@app.post("/api/scenarios/{scenario_id}/containment-suggestions")
def containment_suggestions(scenario_id: str, request: ContainmentSuggestionsRequest):
    workspace = _scenario_or_404(scenario_id)
    run = get_run(request.run_id)
    _require_scenario_run(workspace.id, run)
    if run.status not in {"ready", "partial"} or run.mode == "engine_comparison":
        raise HTTPException(409, "Select a completed simulation result")
    return {"tasks": suggest_tasks(workspace, run, request, RUNS)}


@app.post("/api/scenarios/{scenario_id}/allocation-plans/rank")
def allocation_rank(scenario_id: str, request: AllocationRankRequest):
    workspace = _scenario_or_404(scenario_id)
    run = get_run(request.run_id)
    _require_scenario_run(workspace.id, run)
    if run.status not in {"ready", "partial"} or run.mode == "engine_comparison":
        raise HTTPException(409, "Select a completed simulation result")
    prepared = package_path(run.area_package_id)
    road_path = _ensure_run_roads(run, prepared)
    try:
        return rank_plans(workspace, run, request, road_path, prepared, RUNS)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/api/scenarios/{scenario_id}/allocation-comparisons", status_code=202)
def queue_allocation_comparison(scenario_id: str, request: AllocationComparisonRequest):
    workspace = _scenario_or_404(scenario_id)
    source = get_run(request.run_id)
    _require_scenario_run(workspace.id, source)
    if source.status != "ready" or source.mode != "single" or source.scenario.engine not in {"mtt", "cell2fire"}:
        raise HTTPException(409, "Advanced comparison requires a completed deterministic MTT or Cell2Fire result")
    plan_by_id = {plan.id: plan for plan in workspace.allocation_plans}
    if len(set(request.plan_ids)) != len(request.plan_ids) or any(value not in plan_by_id for value in request.plan_ids):
        raise HTTPException(422, "Select one to four distinct saved allocation plans")
    prepared = package_path(source.area_package_id)
    road_path = _ensure_run_roads(source, prepared)
    try:
        interventions = [build_intervention(workspace, source, plan_by_id[plan_id], request.departure_min,
                                            request.lead_time_min, road_path, prepared, RUNS)
                         for plan_id in request.plan_ids]
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    parent = create_run(source.scenario, mode="allocation_comparison",
                        ensemble={"kind": "allocation", "source_run_id": source.id,
                                  "departure_min": request.departure_min,
                                  "lead_time_min": request.lead_time_min,
                                  "interventions": interventions},
                        scenario_id=workspace.id, scenario_revision=workspace.revision,
                        area_package_id=source.area_package_id,
                        name=f"Containment comparison · {source.name}")
    return _run_payload(parent)


@app.post("/api/scenarios/{scenario_id}/points", status_code=201)
def add_point(scenario_id: str, request: PointCreate):
    workspace = _scenario_or_404(scenario_id)
    return _save_points(workspace, request.expected_revision, [*workspace.points, request.point])


@app.patch("/api/scenarios/{scenario_id}/points/{point_id}")
def edit_point(scenario_id: str, point_id: str, request: PointPatch):
    workspace = _scenario_or_404(scenario_id)
    if point_id != request.point.id or not any(point.id == point_id for point in workspace.points):
        raise HTTPException(404, "Point not found")
    points = [request.point if point.id == point_id else point for point in workspace.points]
    return _save_points(workspace, request.expected_revision, points)


@app.delete("/api/scenarios/{scenario_id}/points/{point_id}")
def delete_point(scenario_id: str, point_id: str, expected_revision: int = Query(..., ge=1)):
    workspace = _scenario_or_404(scenario_id)
    points = [point for point in workspace.points if point.id != point_id]
    if len(points) == len(workspace.points):
        raise HTTPException(404, "Point not found")
    return _save_points(workspace, expected_revision, points)


@app.get("/api/areas/{area_id}/water-points")
def area_water_points(area_id: str):
    prepared = PREPARED if area_id == "penha-guimaraes" else package_path(area_id)
    path = prepared / "water-points.geojson"
    catalog = json.loads(path.read_text()) if path.exists() else {
        "type": "FeatureCollection", "features": [],
        "metadata": {"source": "OpenStreetMap", "status": "not_prepared"},
    }
    if area_id == "penha-guimaraes" and WATER_PRESETS.exists():
        presets = json.loads(WATER_PRESETS.read_text())
        catalog = {
            "type": "FeatureCollection",
            "features": [*presets["features"], *catalog.get("features", [])],
            "metadata": {**presets["metadata"], "openstreetmap": catalog.get("metadata", {})},
        }
        catalog["metadata"]["count"] = len(catalog["features"])
    return catalog


@app.get("/api/areas/{area_id}/roads")
def area_roads(area_id: str):
    prepared = PREPARED if area_id == "penha-guimaraes" else package_path(area_id)
    path = prepared / "roads.geojson"
    if not path.exists():
        raise HTTPException(404, "Prepared roads not found")
    return json.loads(path.read_text())


@app.post("/api/scenarios/{scenario_id}/points/import")
def import_points(scenario_id: str, request: PointImport):
    workspace = _scenario_or_404(scenario_id)
    catalog = area_water_points(workspace.area_id)
    selected = {str(value) for value in request.external_ids}
    existing = {(point.source, point.external_id) for point in workspace.points if point.external_id}
    imported = []
    for feature in catalog.get("features", []):
        properties = feature.get("properties", {})
        external_id = str(properties.get("external_id", ""))
        source = properties.get("source", "openstreetmap")
        if external_id not in selected or (source, external_id) in existing:
            continue
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        imported.append(ScenarioPoint(
            kind="water_point", name=properties.get("name") or "Unverified water point",
            coordinates=tuple(coordinates), source=source, external_id=external_id,
            source_url=properties.get("source_url"), source_updated_at=properties.get("source_updated_at"),
            imported_at=datetime.now(UTC),
            description=properties.get("description", ""),
            notes=properties.get("notes", "Imported from OpenStreetMap; verify before use"),
            data_status=properties.get("data_status", "unverified"),
            water=WaterPointDetails(**properties.get("water", {
                "source_type": properties.get("source_type", "other"),
            })),
        ))
        existing.add((source, external_id))
    return _save_points(workspace, request.expected_revision, [*workspace.points, *imported])


@app.get("/api/areas/{area_id}/fire-stations")
def area_fire_stations(area_id: str):
    prepared = PREPARED if area_id == "penha-guimaraes" else package_path(area_id)
    fire_stations = prepared / "fire-stations.geojson"
    if fire_stations.exists():
        return json.loads(fire_stations.read_text())
    return {"type": "FeatureCollection", "features": [], "metadata": {
        "source": "OpenStreetMap", "status": "not_prepared",
        "coverage": "Configured area only; run the fire-station preparation command to refresh.",
    }}


@app.post("/api/scenarios/{scenario_id}/points/import-fire-stations")
def import_fire_stations(scenario_id: str, request: PointImport):
    workspace = _scenario_or_404(scenario_id)
    catalog = area_fire_stations(workspace.area_id)
    selected = set(request.external_ids)
    existing = {(point.source, point.external_id) for point in workspace.points if point.external_id}
    imported = []
    for feature in catalog.get("features", []):
        properties = feature.get("properties", {})
        external_id = str(properties.get("external_id", ""))
        if external_id not in selected or ("openstreetmap", external_id) in existing:
            continue
        imported.append(ScenarioPoint(
            kind="response_base", name=properties.get("name") or "Unverified fire station",
            coordinates=tuple(feature["geometry"]["coordinates"]), source="openstreetmap",
            external_id=external_id, source_url=properties.get("source_url"),
            source_updated_at=properties.get("source_updated_at"), imported_at=datetime.now(UTC),
            description=properties.get("description", "Fire station candidate"),
            notes="Imported from OpenStreetMap; verify operational status and access before use",
            data_status="unverified",
        ))
        existing.add(("openstreetmap", external_id))
    return _save_points(workspace, request.expected_revision, [*workspace.points, *imported])


@app.get("/api/weather-series")
def weather_series():
    return list_weather_series()


@app.post("/api/weather-series", status_code=201)
async def upload_weather(request: Request, x_filename: str = Header("weather.csv")):
    try:
        return save_weather_series(await request.body(), x_filename)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/api/runs", status_code=202)
def queue_run(request: RunCreate):
    _validate_request(request)
    ensemble = request.ensemble.model_dump(mode="json") if request.ensemble else None
    workspace = create_scenario(request.scenario)
    return _run_payload(create_run(request.scenario, mode=request.mode, ensemble=ensemble,
                                   scenario_id=workspace.id, scenario_revision=workspace.revision,
                                   area_package_id=workspace.area_package_id,
                                   name=request.name, notes=request.notes))


@app.patch("/api/runs/{run_id}/metadata")
def edit_run_metadata(run_id: str, request: RunMetadataPatch):
    try:
        historical = get_run(run_id)
        if (historical.mode != "single" or (historical.scenario_id
                                             and get_scenario(historical.scenario_id).scenario_kind == "exercise")):
            raise HTTPException(410, "Historical planning runs are read-only")
        return _run_payload(update_run_metadata(run_id, request.name, request.notes,
                                                request.expected_metadata_revision))
    except KeyError:
        raise HTTPException(404, "Experiment not found")
    except RunConflictError:
        raise HTTPException(409, "Experiment metadata changed in another browser tab; reload and try again")


@app.delete("/api/runs/{run_id}")
def remove_run(run_id: str, expected_metadata_revision: int | None = Query(None, ge=1)):
    raise HTTPException(410, "Saved simulation results are retained in the read-only archive")


@app.post("/api/runs/{run_id}/retry", status_code=202)
def retry(run_id: str):
    try:
        run = get_run(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found")
    if run.mode != "single":
        raise HTTPException(410, "Historical ensembles and comparisons are read-only")
    if run.scenario_id and get_scenario(run.scenario_id).scenario_kind == "exercise":
        raise HTTPException(410, "Historical exercise results are read-only")
    _validate_request(RunCreate(scenario=run.scenario))
    (RUNS / run_id / "cancel.requested").unlink(missing_ok=True)
    update_run(run_id, status="queued", stage="queued", progress=0, error=None, external_job_id=None)
    if run.mode != "single":
        for child in child_runs(run_id):
            if child.status in {"failed", "cancelled", "interrupted"}:
                (RUNS / child.id / "cancel.requested").unlink(missing_ok=True)
                update_run(child.id, status="queued", stage="queued", progress=0, error=None,
                           external_job_id=None)
    return _run_payload(get_run(run_id))


@app.post("/api/runs/{run_id}/cancel")
def cancel(run_id: str):
    try:
        run = get_run(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found")
    targets = [run, *child_runs(run_id)]
    for target in targets:
        if target.status in {"queued", "preparing", "submitted", "running", "postprocessing"}:
            folder = RUNS / target.id
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "cancel.requested").touch()
            if target.runner == "ssh-slurm" and target.external_job_id:
                SshSlurmRunner().cancel(target.external_job_id)
            update_run(target.id, status="cancelled", stage="cancelled", progress=100)
    return _run_payload(get_run(run_id))


@app.get("/api/runs/{run_id}")
def run_status(run_id: str):
    try:
        return _run_payload(get_run(run_id))
    except KeyError:
        raise HTTPException(404, "Run not found")


@app.get("/api/runs/{run_id}/observation-evaluations")
def observation_evaluations(run_id: str):
    try:
        return list_evaluations(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found")


@app.post("/api/runs/{run_id}/observation-evaluations", status_code=201)
def create_observation_evaluation(run_id: str, request: ObservationEvaluationCreate):
    try:
        return evaluate_observation(run_id, request.snapshot_id, request.assumed_observed_at,
                                    request.assumed_run_start_time)
    except KeyError:
        raise HTTPException(404, "Result or observation snapshot not found")
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/api/runs/{run_id}/observation-evaluations/series", status_code=201)
def create_observation_evaluation_series(run_id: str,
                                         assumed_run_start_time: datetime | None = None):
    try:
        run = get_run(run_id)
        workspace = get_scenario(run.scenario_id)
        if not workspace.external_incident:
            raise ValueError("This result is not linked to a Fogos.pt incident")
        items = fogos.snapshots(workspace.external_incident["incident_id"], "perimeter")
        created, skipped = [], []
        for item in reversed(items):
            try:
                created.append(evaluate_observation(run_id, item["id"], None,
                                                    assumed_run_start_time))
            except ValueError as error:
                skipped.append({"snapshot_id": item["id"], "reason": str(error)})
        return {"created": created, "skipped": skipped}
    except KeyError:
        raise HTTPException(404, "Result or scenario not found")
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/api/runs/{run_id}/roads")
def run_roads(run_id: str, buffer_m: float | None = Query(None, ge=0, le=200)):
    run = get_run(run_id)
    if run.status not in {"ready", "partial"}:
        raise HTTPException(409, "Run is not ready")
    if run.mode == "engine_comparison":
        raise HTTPException(409, "Select a comparison member run")
    selected = run.scenario.exposure_buffer_m if buffer_m is None else buffer_m
    path = RUNS / run_id / f"roads-{int(selected)}m.geojson"
    cached = json.loads(path.read_text()) if path.exists() else {}
    prepared = package_path(run.area_package_id)
    if cached.get("analysis_version") != ANALYSIS_VERSION or cached.get("roads_revision") != roads_revision(prepared):
        analyse(load_result(RUNS / run_id), selected, RUNS / run_id, prepared)
    return json.loads(path.read_text())


@app.get("/api/runs/{run_id}/fire")
def run_fire(run_id: str, minute: int = Query(0, ge=0, le=720)):
    run = get_run(run_id)
    if run.status not in {"ready", "partial"}:
        raise HTTPException(409, "Run is not ready")
    if run.mode == "engine_comparison":
        raise HTTPException(409, "Select a comparison member run")
    minute = min(minute, run.scenario.duration_min)
    cache = RUNS / run_id / f"fire-{minute}.geojson"
    if not cache.exists():
        cache.write_text(json.dumps(footprint(load_result(RUNS / run_id), minute)))
    return json.loads(cache.read_text())


@app.post("/api/runs/{run_id}/routes")
def run_routes(run_id: str, request: RouteAnalysisRequest):
    try:
        run = get_run(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found")
    if run.status not in {"ready", "partial"} or run.mode == "engine_comparison":
        raise HTTPException(409, "Select a completed single or ensemble member result")
    road_path = RUNS / run_id / f"roads-{int(request.exposure_buffer_m)}m.geojson"
    cached = json.loads(road_path.read_text()) if road_path.exists() else {}
    prepared = package_path(run.area_package_id)
    if cached.get("analysis_version") != ANALYSIS_VERSION or cached.get("roads_revision") != roads_revision(prepared):
        analyse(load_result(RUNS / run_id), request.exposure_buffer_m, RUNS / run_id, prepared)
    try:
        selected = request if request.simulation_horizon_min is not None else request.model_copy(
            update={"simulation_horizon_min": run.scenario.duration_min})
        return analyse_routes(road_path, selected, prepared)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/api/runs/{run_id}/children")
def run_children(run_id: str):
    try:
        get_run(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found")
    return [_run_payload(run) for run in child_runs(run_id)]


@app.get("/api/runs/{run_id}/comparison")
def run_comparison(run_id: str, minute: int | None = Query(None, ge=0, le=720)):
    run = get_run(run_id)
    if run.mode != "engine_comparison" or run.status not in {"ready", "partial"}:
        raise HTTPException(409, "Comparison is not ready")
    selected = min(run.scenario.duration_min, run.scenario.duration_min if minute is None else minute)
    return comparison_payload(run, child_runs(run_id), selected, RUNS)


@app.get("/api/runs/{run_id}/allocation-comparison")
def run_allocation_comparison(run_id: str):
    run = get_run(run_id)
    if run.mode != "allocation_comparison" or run.status not in {"ready", "partial", "running"}:
        raise HTTPException(409, "Allocation comparison is not available")
    source_id = (run.ensemble or {}).get("source_run_id")
    if not source_id:
        raise HTTPException(422, "Allocation comparison has no control result")
    return allocation_comparison_payload(run, child_runs(run.id), get_run(source_id),
                                         _scenario_or_404(run.scenario_id), RUNS)


def _scenario_or_404(scenario_id: str):
    try:
        return get_scenario(scenario_id)
    except KeyError:
        raise HTTPException(404, "Scenario not found")


def _require_scenario_run(scenario_id: str, run) -> None:
    if run.scenario_id != scenario_id:
        raise HTTPException(422, "The selected result belongs to another scenario")


def _ensure_run_roads(run, prepared: Path) -> Path:
    selected = run.scenario.exposure_buffer_m
    road_path = RUNS / run.id / f"roads-{int(selected)}m.geojson"
    cached = json.loads(road_path.read_text()) if road_path.exists() else {}
    if cached.get("analysis_version") != ANALYSIS_VERSION or cached.get("roads_revision") != roads_revision(prepared):
        analyse(load_result(RUNS / run.id), selected, RUNS / run.id, prepared)
    return road_path


def _save_points(workspace, expected_revision: int, points: list[ScenarioPoint]):
    if workspace.scenario_kind == "exercise":
        raise HTTPException(410, "Historical exercise points are read-only; use Mobility for current incident reports")
    patch = ScenarioPatch(expected_revision=expected_revision, name=workspace.name,
                          description=workspace.description, area_id=workspace.area_id,
                          resource_center=workspace.resource_center,
                          resource_radius_km=workspace.resource_radius_km,
                          fire_margin_km=workspace.fire_margin_km,
                          cell_size_m=workspace.cell_size_m,
                          area_package_id=workspace.area_package_id,
                          start_time=workspace.start_time, simulation=workspace.simulation, points=points,
                          closures=workspace.closures, teams=workspace.teams,
                          containment_tasks=workspace.containment_tasks,
                          allocation_plans=workspace.allocation_plans,
                          resource_groups=workspace.resource_groups,
                          scenario_kind=workspace.scenario_kind,
                          source_scenario_id=workspace.source_scenario_id)
    try:
        return update_scenario(workspace.id, patch).model_dump(mode="json")
    except ScenarioConflictError:
        raise HTTPException(409, "Scenario changed in another browser tab; reload before saving")


def _validate_request(request: RunCreate, absolute_start: datetime | None = None) -> None:
    scenario = request.scenario
    if request.mode != "single":
        raise HTTPException(410, "New fire jobs are single-engine only; older comparisons remain in the archive")
    engine = ENGINES.get(scenario.engine)
    if engine is None:
        raise HTTPException(422, f"Engine {scenario.engine} is not installed")
    multiple = len(scenario.ignitions) > 1
    delayed = any(item.start_min for item in scenario.ignitions)
    if scenario.weather_source.kind == "series":
        try:
            validate_weather_coverage(scenario.weather_source.id, scenario.duration_min, absolute_start)
        except (KeyError, ValueError) as error:
            raise HTTPException(422, str(error)) from error
    if request.ensemble is not None:
        raise HTTPException(422, "Single runs cannot include ensemble settings")
    try:
        available, reason = engine.available()
    except Exception as error:
        raise HTTPException(422, f"Engine availability check failed: {error}") from error
    if not available:
        raise HTTPException(422, reason)
    if scenario.engine_profile not in engine.descriptor.profiles:
        raise HTTPException(422, f"{engine.descriptor.display_name} does not support profile {scenario.engine_profile}")
    profile_weather = engine.descriptor.profile_weather.get(scenario.engine_profile, engine.descriptor.weather_modes)
    if scenario.weather_source.kind not in profile_weather:
        raise HTTPException(422, f"{engine.descriptor.display_name} does not support {scenario.weather_source.kind} weather")
    if multiple and not engine.descriptor.supports_multiple_ignitions:
        raise HTTPException(422, f"{engine.descriptor.display_name} does not support multiple fire starts")
    if delayed and not engine.descriptor.supports_delayed_ignitions:
        raise HTTPException(422, f"{engine.descriptor.display_name} does not support delayed fire starts")
    if hasattr(engine, "validate"):
        try:
            engine.validate(scenario)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error


def _validate_prepared_ignitions(workspace) -> None:
    if workspace.resource_center and any(
        _distance_km(workspace.resource_center, item.coordinates) > workspace.resource_radius_km
        for item in workspace.simulation.ignitions
    ):
        raise HTTPException(422, "A fire start is outside the scenario resource radius; change the center or radius and prepare the area again")
    prepared = package_path(workspace.area_package_id)
    try:
        landscape = load_landscape(prepared)
    except (FileNotFoundError, KeyError, ValueError) as error:
        raise HTTPException(422, "The scenario area package is unavailable; prepare it again") from error
    from rasterio.warp import transform
    for ignition in workspace.simulation.ignitions:
        x, y = transform("EPSG:4326", landscape.crs, [ignition.coordinates[0]], [ignition.coordinates[1]])
        col, row = ~landscape.transform @ (x[0], y[0])
        row, col = int(row), int(col)
        rows, cols = landscape.fuel.shape
        if not (0 <= row < rows and 0 <= col < cols) or not landscape.coverage[row, col]:
            raise HTTPException(422, f"{ignition.name} is outside valid prepared terrain; prepare a larger fire area")
        fuel = int(landscape.fuel[row, col])
        if fuel == 0 or 91 <= fuel <= 99:
            raise HTTPException(422, f"{ignition.name} is on a nonburnable cell; move it before running")


def _run_payload(run):
    value = run.model_dump(mode="json")
    children = child_runs(run.id) if run.mode != "single" and run.parent_id is None else []
    if children:
        value["children"] = [child.model_dump(mode="json") for child in children]
    result_path = RUNS / run.id / "result.json"
    if result_path.exists():
        meta = json.loads(result_path.read_text())
        value["result"] = {"engine": meta["engine"], "engine_version": meta["engine_version"],
                           "temporal_resolution_min": meta["temporal_resolution_min"],
                           "manifest": meta.get("manifest", {})}
    return value


if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/{path:path}")
    def frontend(path: str):
        candidate = FRONTEND / path
        return FileResponse(candidate if candidate.is_file() else FRONTEND / "index.html")
