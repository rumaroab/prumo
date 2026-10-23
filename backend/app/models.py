from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

import numpy as np
from pydantic import BaseModel, Field, field_validator, model_serializer, model_validator
from rasterio.transform import Affine

EngineName = str
RunMode = Literal["single", "parameter_ensemble", "engine_comparison", "allocation_comparison"]
PointKind = Literal[
    "response_base", "water_point", "asset", "hazard", "staging_area",
    "access_control", "shelter", "delivery_point", "custom",
]
CellSizeM = Literal[10, 15, 20, 30]


class ConstantWeather(BaseModel):
    kind: Literal["constant"] = "constant"
    provenance: dict[str, Any] | None = None

    @model_serializer(mode="wrap")
    def omit_empty_provenance(self, handler):
        value = handler(self)
        if value.get("provenance") is None:
            value.pop("provenance", None)
        return value


class SeriesWeather(BaseModel):
    kind: Literal["series"]
    id: str


WeatherSource = ConstantWeather | SeriesWeather


@dataclass(slots=True)
class Landscape:
    fuel: np.ndarray
    elevation: np.ndarray
    slope: np.ndarray
    aspect: np.ndarray
    coverage: np.ndarray
    transform: Affine
    crs: str
    cell_size_m: float
    provenance: dict
    fuel_anderson13: np.ndarray | None = None
    fuel_load_kg_m2: np.ndarray | None = None
    fuel_depth_m: np.ndarray | None = None


class Ignition(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str = Field(default="Fire 1", min_length=1, max_length=120)
    coordinates: tuple[float, float]
    start_min: int = Field(0, ge=0, le=720)

    @field_validator("coordinates")
    @classmethod
    def valid_coordinates(cls, value):
        lon, lat = value
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError("Ignition coordinates must be valid longitude and latitude")
        return value


class Scenario(BaseModel):
    name: str = "Custom scenario"
    engine: EngineName = "mtt"
    ignitions: list[Ignition] = Field(min_length=1)
    wind_speed_kmh: float = Field(20, ge=0, le=120)
    wind_direction_deg: float = Field(45, ge=0, lt=360)
    moisture: Literal["low", "moderate", "high"] = "moderate"
    duration_min: int = Field(120, ge=10, le=720)
    seed: int = 42
    exposure_buffer_m: float = Field(30, ge=0, le=200)
    weather_source: WeatherSource = Field(default_factory=ConstantWeather)
    engine_profile: str = "default"

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_ignition(cls, value):
        if isinstance(value, dict) and not value.get("ignitions") and value.get("ignition") is not None:
            value = dict(value)
            value["ignitions"] = [{"id": "fire-1", "name": "Fire 1",
                                     "coordinates": value.pop("ignition"), "start_min": 0}]
        return value

    @model_validator(mode="after")
    def validate_ignitions(self):
        ids = [ignition.id for ignition in self.ignitions]
        if len(ids) != len(set(ids)):
            raise ValueError("Ignition IDs must be unique")
        if any(ignition.start_min > self.duration_min for ignition in self.ignitions):
            raise ValueError("Ignition start time must be within the simulation duration")
        return self

    @property
    def ignition(self) -> tuple[float, float]:
        """Compatibility accessor for engines that only accept the first start."""
        return self.ignitions[0].coordinates


class WaterPointDetails(BaseModel):
    source_type: Literal["hydrant", "tank", "reservoir", "pond", "other"] = "other"
    availability: Literal["available", "unavailable", "unknown"] = "unknown"
    capacity_m3: float | None = Field(None, ge=0)
    flow_l_min: float | None = Field(None, ge=0)
    access_notes: str = ""
    verification_status: Literal["unverified", "reported", "verified"] = "unverified"
    observed_at: datetime | None = None
    supply_class: Literal["finite", "continuous", "unknown"] = "unknown"
    available_volume_l: float | None = Field(None, ge=0)
    shared_flow_l_min: float | None = Field(None, ge=0)
    filling_positions: int | None = Field(None, ge=1, le=20)
    setup_time_min: float | None = Field(None, ge=0, le=240)


class AssetDetails(BaseModel):
    priority: int = Field(3, ge=1, le=5)


class ScenarioPoint(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    kind: PointKind
    name: str = Field(min_length=1, max_length=120)
    coordinates: tuple[float, float]
    description: str = ""
    notes: str = ""
    source: Literal["manual", "openstreetmap", "icnf", "demo"] = "manual"
    source_url: str | None = None
    source_updated_at: str | None = None
    external_id: str | None = None
    imported_at: datetime | None = None
    data_status: Literal["unverified", "reported", "verified"] = "unverified"
    water: WaterPointDetails | None = None
    asset: AssetDetails | None = None
    population_role: Literal["origin", "reception"] | None = None
    population_count: int | None = Field(None, ge=0)

    def model_post_init(self, __context: Any) -> None:
        lon, lat = self.coordinates
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError("Point coordinates must be valid longitude and latitude")
        if self.kind == "water_point" and self.water is None:
            self.water = WaterPointDetails()
        if self.kind != "water_point":
            self.water = None
        if self.kind == "asset" and self.asset is None:
            self.asset = AssetDetails()
        if self.kind != "asset":
            self.asset = None


class ResponseTeam(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str = Field(default="New team", min_length=1, max_length=120)
    base_point_id: str
    available_from_min: float = Field(0, ge=0, le=720)
    line_rate_m_min: float = Field(5, gt=0, le=100)
    max_deployment_min: float = Field(240, gt=0, le=1440)
    status: Literal["available", "unavailable"] = "available"
    source_provenance: "TeamSourceProvenance | None" = None


ResourceCategory = Literal["operacionais", "meios_terrestres", "meios_aereos"]


class ScenarioResourceGroup(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    category: ResourceCategory
    name: str = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=2000)
    reported_count: int | None = Field(None, ge=0)
    planned_count_override: int | None = Field(None, ge=0)
    provider: Literal["fogos.pt"] = "fogos.pt"
    incident_id: str = Field(min_length=1, max_length=120)
    snapshot_id: str = Field(min_length=1, max_length=80)
    observed_at: str | None = None
    synced_at: str


class TeamSourceProvenance(BaseModel):
    provider: Literal["fogos.pt"] = "fogos.pt"
    incident_id: str = Field(min_length=1, max_length=120)
    resource_group_id: str = Field(min_length=1, max_length=120)
    category: Literal["operacionais"] = "operacionais"
    snapshot_id: str = Field(min_length=1, max_length=80)
    reported_count: int | None = Field(None, ge=0)
    planned_count: int | None = Field(None, ge=0)
    converted_at: str


class ContainmentTask(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str = Field(default="Containment line", min_length=1, max_length=120)
    geometry: dict[str, Any]
    protected_asset_ids: list[str] = Field(default_factory=list)
    source: Literal["suggested", "manual"] = "manual"
    enabled: bool = True

    @field_validator("geometry")
    @classmethod
    def closed_line(cls, value):
        if value.get("type") != "LineString":
            raise ValueError("Containment geometry must be a LineString")
        coordinates = value.get("coordinates") or []
        if len(coordinates) < 4 or coordinates[0] != coordinates[-1]:
            raise ValueError("Containment line must be closed and contain at least three vertices")
        for coordinate in coordinates:
            if len(coordinate) < 2 or not -180 <= coordinate[0] <= 180 or not -90 <= coordinate[1] <= 90:
                raise ValueError("Containment coordinates must be valid longitude and latitude")
        return value


class AllocationAssignment(BaseModel):
    task_id: str
    team_ids: list[str] = Field(min_length=1)

    @field_validator("team_ids")
    @classmethod
    def distinct_teams(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("A team may appear only once in an assignment")
        return value


class AllocationPlan(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str = Field(default="Allocation plan", min_length=1, max_length=120)
    assignments: list[AllocationAssignment] = Field(default_factory=list)

    @model_validator(mode="after")
    def teams_are_not_reused(self):
        team_ids = [team_id for assignment in self.assignments for team_id in assignment.team_ids]
        if len(team_ids) != len(set(team_ids)):
            raise ValueError("A team may serve only one task in a plan")
        task_ids = [assignment.task_id for assignment in self.assignments]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("A task may appear only once in a plan")
        return self


class RoadClosure(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    segment_id: str
    road_name: str = "Unnamed road"
    reason: str = "Reported closure"
    source: str = "Scenario report"
    direction: Literal["both", "forward", "reverse"] = "both"
    starts_min: float = Field(0, ge=0, le=720)
    ends_min: float | None = Field(None, ge=0, le=720)
    geometry: dict[str, Any]

    @field_validator("ends_min")
    @classmethod
    def valid_window(cls, value: float | None, info):
        if value is not None and value < info.data.get("starts_min", 0):
            raise ValueError("Closure end must be after its start")
        return value


class ScenarioDefinition(BaseModel):
    scenario_kind: Literal["legacy", "exercise"] = "legacy"
    source_scenario_id: str | None = None
    description: str = ""
    area_id: str = "penha-guimaraes"
    resource_center: tuple[float, float] | None = None
    resource_radius_km: Literal[10, 25, 50] = 25
    fire_margin_km: Literal[5, 10, 25] = 5
    cell_size_m: CellSizeM = 30
    area_package_id: str | None = None
    start_time: datetime | None = None
    simulation: Scenario
    points: list[ScenarioPoint] = Field(default_factory=list)
    closures: list[RoadClosure] = Field(default_factory=list)
    teams: list[ResponseTeam] = Field(default_factory=list)
    resource_groups: list[ScenarioResourceGroup] = Field(default_factory=list)
    containment_tasks: list[ContainmentTask] = Field(default_factory=list)
    allocation_plans: list[AllocationPlan] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_operational_references(self):
        _validate_operational_references(self.points, self.teams, self.containment_tasks,
                                         self.allocation_plans, self.resource_groups)
        return self


class ScenarioWorkspace(BaseModel):
    id: str
    name: str
    description: str = ""
    area_id: str = "penha-guimaraes"
    resource_center: tuple[float, float] | None = None
    resource_radius_km: Literal[10, 25, 50] = 25
    fire_margin_km: Literal[5, 10, 25] = 5
    cell_size_m: CellSizeM = 30
    area_package_id: str | None = None
    start_time: datetime | None = None
    revision: int
    simulation: Scenario
    points: list[ScenarioPoint] = Field(default_factory=list)
    closures: list[RoadClosure] = Field(default_factory=list)
    teams: list[ResponseTeam] = Field(default_factory=list)
    resource_groups: list[ScenarioResourceGroup] = Field(default_factory=list)
    containment_tasks: list[ContainmentTask] = Field(default_factory=list)
    allocation_plans: list[AllocationPlan] = Field(default_factory=list)
    created_at: str
    updated_at: str
    setup_complete: bool = False
    external_incident: dict[str, Any] | None = None
    scenario_kind: Literal["legacy", "exercise"] = "legacy"
    source_scenario_id: str | None = None

    @model_validator(mode="after")
    def valid_operational_references(self):
        _validate_operational_references(self.points, self.teams, self.containment_tasks,
                                         self.allocation_plans, self.resource_groups)
        return self


class ScenarioName(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class ScenarioRename(ScenarioName):
    expected_revision: int = Field(ge=1)


class ScenarioCreate(ScenarioName):
    name: str = Field("Custom scenario", min_length=1, max_length=120)
    description: str = ""
    area_id: str = "penha-guimaraes"
    resource_center: tuple[float, float] | None = None
    resource_radius_km: Literal[10, 25, 50] = 25
    fire_margin_km: Literal[5, 10, 25] = 5
    cell_size_m: CellSizeM = 30
    area_package_id: str | None = None
    start_time: datetime | None = None
    simulation: Scenario | None = None
    points: list[ScenarioPoint] = Field(default_factory=list)
    closures: list[RoadClosure] = Field(default_factory=list)
    teams: list[ResponseTeam] = Field(default_factory=list)
    resource_groups: list[ScenarioResourceGroup] = Field(default_factory=list)
    containment_tasks: list[ContainmentTask] = Field(default_factory=list)
    allocation_plans: list[AllocationPlan] = Field(default_factory=list)
    fogos_snapshot_id: str | None = None
    scenario_kind: Literal["legacy", "exercise"] = "legacy"
    source_scenario_id: str | None = None

    @model_validator(mode="after")
    def valid_operational_references(self):
        _validate_operational_references(self.points, self.teams, self.containment_tasks,
                                         self.allocation_plans, self.resource_groups)
        return self


class ScenarioPatch(ScenarioName):
    expected_revision: int
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    area_id: str = "penha-guimaraes"
    resource_center: tuple[float, float] | None = None
    resource_radius_km: Literal[10, 25, 50] = 25
    fire_margin_km: Literal[5, 10, 25] = 5
    cell_size_m: CellSizeM = 30
    area_package_id: str | None = None
    start_time: datetime | None = None
    simulation: Scenario
    points: list[ScenarioPoint] = Field(default_factory=list)
    closures: list[RoadClosure] = Field(default_factory=list)
    teams: list[ResponseTeam] = Field(default_factory=list)
    resource_groups: list[ScenarioResourceGroup] | None = None
    containment_tasks: list[ContainmentTask] = Field(default_factory=list)
    allocation_plans: list[AllocationPlan] = Field(default_factory=list)
    scenario_kind: Literal["legacy", "exercise"] = "legacy"
    source_scenario_id: str | None = None

    @model_validator(mode="after")
    def valid_operational_references(self):
        _validate_operational_references(self.points, self.teams, self.containment_tasks,
                                         self.allocation_plans, self.resource_groups or [])
        return self


def _validate_operational_references(points: list[ScenarioPoint], teams: list[ResponseTeam],
                                     tasks: list[ContainmentTask], plans: list[AllocationPlan],
                                     resource_groups: list[ScenarioResourceGroup] | None = None) -> None:
    base_ids = {point.id for point in points if point.kind == "response_base"}
    asset_ids = {point.id for point in points if point.kind == "asset"}
    team_ids = {team.id for team in teams}
    task_ids = {task.id for task in tasks}
    if len(team_ids) != len(teams) or len(task_ids) != len(tasks):
        raise ValueError("Team and containment task IDs must be unique")
    groups = resource_groups or []
    if len({group.id for group in groups}) != len(groups):
        raise ValueError("Resource group IDs must be unique")
    if len({group.category for group in groups}) != len(groups):
        raise ValueError("Resource group categories must be unique")
    if any(team.base_point_id not in base_ids for team in teams):
        raise ValueError("Every team must reference an existing response base")
    if any(asset_id not in asset_ids for task in tasks for asset_id in task.protected_asset_ids):
        raise ValueError("Containment tasks may reference only existing assets")
    if any(team_id not in team_ids for plan in plans for assignment in plan.assignments
           for team_id in assignment.team_ids):
        raise ValueError("Allocation plans may reference only existing teams")
    if any(assignment.task_id not in task_ids for plan in plans for assignment in plan.assignments):
        raise ValueError("Allocation plans may reference only existing containment tasks")


class PointCreate(BaseModel):
    expected_revision: int
    point: ScenarioPoint


class PointPatch(PointCreate):
    pass


class PointImport(BaseModel):
    expected_revision: int
    external_ids: list[str]


class RouteLocation(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    coordinates: tuple[float, float]


class RouteAnalysisRequest(BaseModel):
    origin: RouteLocation
    destination: RouteLocation
    departure_min: float = Field(0, ge=0, le=720)
    on_scene_min: float = Field(0, ge=0, le=720)
    withdrawal_destination: RouteLocation | None = None
    closures: list[RoadClosure] = Field(default_factory=list)
    alternatives: int = Field(2, ge=0, le=3)
    exposure_buffer_m: float = Field(30, ge=0, le=200)
    simulation_horizon_min: float | None = Field(None, ge=0, le=720)


# Live mobility records intentionally live outside ScenarioDefinition.  They use
# wall-clock timestamps and their own revisions so a field update cannot mark a
# fire simulation stale or overwrite another dispatcher's work.
class FogosResourceProvenance(BaseModel):
    provider: Literal["fogos.pt"] = "fogos.pt"
    incident_id: str
    snapshot_id: str
    category: Literal["meios_terrestres", "meios_aereos"]
    sequence: int = Field(ge=1)
    placeholder: Literal[True] = True
    observed_at: datetime | None = None


class VehicleProfile(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str = Field(min_length=1, max_length=120)
    vehicle_class: Literal["light", "heavy", "tanker", "bus", "ambulance", "other", "aircraft"] = "light"
    import_provenance: FogosResourceProvenance | None = None
    width_m: float | None = Field(None, gt=0, le=10)
    height_m: float | None = Field(None, gt=0, le=10)
    weight_t: float | None = Field(None, gt=0, le=100)
    off_road: bool = False
    notes: str = ""
    water_tank_capacity_l: float | None = Field(None, ge=0)
    pump_flow_l_min: float | None = Field(None, ge=0)
    passenger_capacity: int | None = Field(None, ge=0, le=200)
    starting_water_l: float | None = Field(None, ge=0)
    available: bool = True
    revision: int = 1

    @model_validator(mode="after")
    def valid_starting_water(self):
        if (self.starting_water_l is not None and self.water_tank_capacity_l is not None
                and self.starting_water_l > self.water_tank_capacity_l):
            raise ValueError("Starting water cannot exceed tank capacity")
        return self


class LocationObservation(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    unit_id: str
    coordinates: tuple[float, float]
    observed_at: datetime
    received_at: datetime | None = None
    source: Literal["phone", "radio", "dispatcher"] = "dispatcher"
    accuracy_m: float | None = Field(None, ge=0, le=10000)


class OperationalUnit(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    organisation: str = Field(min_length=1, max_length=120)
    callsign: str = Field(min_length=1, max_length=80)
    contact: str = Field(default="", max_length=160)
    notes: str = ""
    import_provenance: FogosResourceProvenance | None = None
    vehicle_id: str | None = None
    status: Literal["available", "assigned", "travelling", "on_scene", "unavailable"] = "available"
    capabilities: list[str] = Field(default_factory=list)
    available_from: datetime | None = None
    available_until: datetime | None = None
    max_deployment_min: float | None = Field(None, gt=0, le=1440)
    containment_rate_m_min: float | None = Field(None, gt=0, le=100)
    revision: int = 1
    latest_location: LocationObservation | None = None


class RoadReport(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    segment_id: str | None = None
    road_name: str = "Unnamed road"
    kind: Literal["blocked", "restricted", "reopening", "uncertain"]
    reason: str = ""
    direction: Literal["both", "forward", "reverse"] = "both"
    affected_vehicle_classes: list[str] = Field(default_factory=list)
    status: Literal["pending", "confirmed", "dismissed"] = "pending"
    source: Literal["crew", "radio", "dispatcher"] = "dispatcher"
    geometry: dict[str, Any] | None = None
    observed_location: tuple[float, float] | None = None
    observed_at: datetime
    created_at: datetime | None = None
    reviewed_at: datetime | None = None
    revision: int = 1

    @field_validator("observed_location")
    @classmethod
    def valid_observed_location(cls, value):
        if value is not None and not (-180 <= value[0] <= 180 and -90 <= value[1] <= 90):
            raise ValueError("Observed location must be longitude and latitude")
        return value


class MobilityRouteRequest(BaseModel):
    origin: RouteLocation
    destination: RouteLocation
    vehicle_id: str | None = None
    vehicle_class: Literal["light", "heavy", "tanker", "bus", "ambulance", "other"] | None = None
    departure_at: datetime
    alternatives: int = Field(2, ge=0, le=2)

    @model_validator(mode="after")
    def one_vehicle_source(self):
        if bool(self.vehicle_id) == bool(self.vehicle_class):
            raise ValueError("Choose one vehicle or one planning vehicle type")
        return self


class RoutePlanInput(BaseModel):
    purpose: str = Field(min_length=1, max_length=160)
    origin: RouteLocation
    destination: RouteLocation
    departure_at: datetime
    vehicle_class: Literal["light", "heavy", "tanker", "bus", "ambulance", "other"]
    preview_signature: str
    expected_revision: int | None = Field(None, ge=1)


class MovementCreate(BaseModel):
    unit_id: str
    vehicle_id: str
    purpose: str = Field(min_length=1, max_length=160)
    origin: RouteLocation
    destination: RouteLocation
    departure_at: datetime
    preview_signature: str = ""
    route: dict[str, Any] | None = None
    suitability_acknowledged: bool = False
    notes: str = ""
    dispatcher_contact: str = ""
    route_plan_id: str | None = None
    route_plan_revision: int | None = Field(None, ge=1)


class MovementAction(BaseModel):
    action: Literal["accept", "acknowledge_brief", "depart", "arrive", "complete", "cannot_proceed", "cancel"]
    expected_revision: int = Field(ge=1)
    expected_brief_version: int = Field(ge=1)
    source: Literal["crew", "radio", "dispatcher"] = "crew"
    note: str = ""
    request_id: str = Field(min_length=8, max_length=80)


class MovementRevision(BaseModel):
    preview_signature: str = ""
    route: dict[str, Any] | None = None
    expected_revision: int = Field(ge=1)
    departure_at: datetime | None = None
    suitability_acknowledged: bool = False


class RoadReportReview(BaseModel):
    status: Literal["confirmed", "dismissed"]
    expected_revision: int = Field(ge=1)
    segment_id: str | None = None
    direction: Literal["both", "forward", "reverse"] | None = None


class WaterSourceReportCreate(BaseModel):
    point_id: str
    availability: Literal["available", "unavailable", "uncertain"]
    note: str = Field(min_length=1, max_length=1000)
    observed_at: datetime

    @field_validator("note")
    @classmethod
    def meaningful_note(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Describe the water-source observation")
        return value.strip()


class WaterSourceReportReview(BaseModel):
    status: Literal["confirmed", "dismissed"]
    expected_revision: int = Field(ge=1)


class LocationCreate(BaseModel):
    coordinates: tuple[float, float]
    observed_at: datetime
    source: Literal["phone", "radio", "dispatcher"] = "dispatcher"
    accuracy_m: float | None = Field(None, ge=0, le=10000)


class ShareCreate(BaseModel):
    expires_hours: int = Field(12, ge=1, le=24)


class ContainmentSuggestionsRequest(BaseModel):
    run_id: str
    standoff_m: float = Field(120, ge=30, le=1000)
    max_tasks: int = Field(6, ge=1, le=12)


class AllocationRankRequest(BaseModel):
    run_id: str
    departure_min: float = Field(0, ge=0, le=720)
    lead_time_min: float = Field(10, ge=0, le=120)
    count: int = Field(4, ge=1, le=4)
    configurations: list[AllocationPlan] | None = None


class AllocationComparisonRequest(BaseModel):
    run_id: str
    plan_ids: list[str] = Field(min_length=1, max_length=4)
    departure_min: float = Field(0, ge=0, le=720)
    lead_time_min: float = Field(10, ge=0, le=120)


@dataclass(slots=True)
class SimulationResult:
    arrival_minutes: np.ndarray
    coverage: np.ndarray
    transform: Affine
    crs: str
    temporal_resolution_min: float
    engine: str
    engine_version: str
    provenance: dict
    manifest: dict[str, Any] | None = None
    member_arrivals: list[np.ndarray] | None = None


class ParameterEnsemble(BaseModel):
    kind: Literal["parameter"] = "parameter"
    preset: Literal["quick", "standard"] = "quick"


class EngineComparison(BaseModel):
    kind: Literal["comparison"] = "comparison"
    engines: list[EngineName] = Field(min_length=2)

    @field_validator("engines")
    @classmethod
    def distinct_engines(cls, value: list[EngineName]) -> list[EngineName]:
        if len(set(value)) != len(value):
            raise ValueError("Comparison engines must be distinct")
        return value


EnsembleConfig = ParameterEnsemble | EngineComparison


class RunCreate(BaseModel):
    scenario: Scenario
    mode: RunMode = "single"
    ensemble: EnsembleConfig | None = None
    name: str | None = Field(None, min_length=1, max_length=120)
    notes: str = ""


class ScenarioRunCreate(BaseModel):
    mode: RunMode = "single"
    ensemble: EnsembleConfig | None = None
    name: str | None = Field(None, min_length=1, max_length=120)
    notes: str = ""


class RunMetadataPatch(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    notes: str = ""
    expected_metadata_revision: int = Field(ge=1)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class RunRecord(BaseModel):
    id: str
    status: str
    stage: str
    progress: int
    scenario: Scenario
    error: str | None = None
    created_at: str
    updated_at: str
    mode: RunMode = "single"
    parent_id: str | None = None
    member_index: int | None = None
    runner: str | None = None
    external_job_id: str | None = None
    successful_members: int | None = None
    expected_members: int | None = None
    ensemble: dict[str, Any] | None = None
    scenario_id: str | None = None
    scenario_revision: int | None = None
    area_package_id: str | None = None
    intervention: dict[str, Any] | None = None
    name: str
    notes: str = ""
    metadata_revision: int = 1
    run_context: dict[str, Any] | None = None


class FogosImportPreview(BaseModel):
    incident_id: str = Field(min_length=1, max_length=120)


class FogosTrackingUpdate(BaseModel):
    enabled: bool


class FogosWeatherApply(BaseModel):
    expected_revision: int = Field(ge=1)


class FogosResourceSync(BaseModel):
    expected_revision: int = Field(ge=1)


class FogosResourceChange(BaseModel):
    category: ResourceCategory
    name: str
    before: int | None = None
    after: int | None = None
    created: bool = False


class FogosResourceSyncResponse(BaseModel):
    scenario: ScenarioWorkspace
    context: dict[str, Any]
    changes: list[FogosResourceChange]


class ObservationEvaluationCreate(BaseModel):
    snapshot_id: str = Field(min_length=1, max_length=80)
    assumed_observed_at: datetime | None = None
    assumed_run_start_time: datetime | None = None


class AreaPreparationCreate(BaseModel):
    center: tuple[float, float]
    resource_radius_km: Literal[10, 25, 50] = 25
    fire_margin_km: Literal[5, 10, 25] = 5
    cell_size_m: CellSizeM = 30
    ignitions: list[Ignition] = Field(min_length=1)
    acknowledge_high_cost: bool = False


class AreaPreparationEstimate(BaseModel):
    fire_bounds: tuple[float, float, float, float]
    grid_rows: int
    grid_columns: int
    cell_count: int
    area_km2: float
    cell_size_m: CellSizeM
    cost_level: Literal["normal", "moderate", "high", "very_high", "blocked"]
    requires_acknowledgement: bool
    allowed: bool
    blocking_reason: str | None = None


class AreaPreparation(BaseModel):
    id: str
    package_id: str
    status: Literal["queued", "running", "ready", "partial", "failed", "cancelled"]
    stage: str
    progress: int
    request: AreaPreparationCreate
    datasets: dict[str, dict[str, Any]] = Field(default_factory=dict)
    error: str | None = None
    failure_code: str | None = None
    retryable: bool | None = None
    retry_at: str | None = None
    tile_progress: dict[str, int] | None = None
    source_progress: dict[str, Any] | None = None
    created_at: str
    updated_at: str
