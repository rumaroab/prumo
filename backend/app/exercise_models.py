from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def _id() -> str:
    return uuid4().hex[:12]


class ExerciseSituation(BaseModel):
    scenario_id: str = ""
    reference_time: datetime
    summary: str = ""
    assumptions: list[str] = Field(default_factory=list)
    selected_forecast_ids: list[str] = Field(default_factory=list, max_length=3)
    forecast_alignments: dict[str, datetime] = Field(default_factory=dict)
    forecast_lead_time_min: float = Field(10, ge=0, le=120)
    revision: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("reference_time")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Reference time must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def alignment_timezones(self):
        for run_id, value in self.forecast_alignments.items():
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"Forecast alignment for {run_id} must include a timezone")
        self.forecast_alignments = {key: value.astimezone(UTC) for key, value in self.forecast_alignments.items()}
        return self


class SituationUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    reference_time: datetime
    summary: str = ""
    assumptions: list[str] = Field(default_factory=list)
    selected_forecast_ids: list[str] = Field(default_factory=list, max_length=3)
    forecast_alignments: dict[str, datetime] = Field(default_factory=dict)
    forecast_lead_time_min: float = Field(10, ge=0, le=120)


MissionType = Literal["access_control", "fire_response", "water_supply", "transport", "logistics", "containment"]


class ExerciseLocation(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    coordinates: tuple[float, float]
    point_id: str | None = None

    @field_validator("coordinates")
    @classmethod
    def valid_coordinates(cls, value):
        lon, lat = value
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError("Coordinates must be valid longitude and latitude")
        return value


class Mission(BaseModel):
    id: str = Field(default_factory=_id)
    scenario_id: str = ""
    name: str = Field(min_length=1, max_length=120)
    mission_type: MissionType
    priority: int = Field(3, ge=1, le=5)
    status: Literal["required", "planned", "completed", "cancelled"] = "required"
    location: ExerciseLocation
    access_point: ExerciseLocation | None = None
    earliest_start_min: float = Field(0, ge=0, le=1440)
    deadline_min: float | None = Field(None, ge=0, le=1440)
    service_duration_min: float = Field(0, ge=0, le=1440)
    required_capabilities: list[str] = Field(default_factory=list)
    required_unit_count: int = Field(1, ge=1, le=10)
    prerequisite_ids: list[str] = Field(default_factory=list)
    completion_criteria: str = ""
    target_volume_l: float | None = Field(None, gt=0)
    demand_rate_l_min: float | None = Field(None, gt=0)
    demand_duration_min: float | None = Field(None, gt=0, le=1440)
    people_count: int | None = Field(None, gt=0, le=100000)
    pickup: ExerciseLocation | None = None
    dropoff: ExerciseLocation | None = None
    cargo_requirements: str = ""
    containment_geometry: dict[str, Any] | None = None
    revision: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def specialised_requirements(self):
        if self.deadline_min is not None and self.deadline_min < self.earliest_start_min:
            raise ValueError("Deadline must be after the earliest start")
        if self.mission_type == "water_supply" and self.target_volume_l is None and self.demand_rate_l_min is None:
            raise ValueError("Water supply needs a target volume or demand rate")
        if self.mission_type == "transport" and (self.people_count is None or not self.pickup or not self.dropoff):
            raise ValueError("Transport needs people, pickup, and destination")
        if self.mission_type == "fire_response" and self.access_point is None:
            raise ValueError("Fire response needs an explicit vehicle access point")
        if self.mission_type == "containment":
            geometry = self.containment_geometry or {}
            coordinates = geometry.get("coordinates") or []
            if geometry.get("type") != "LineString" or len(coordinates) < 2:
                raise ValueError("Containment needs a LineString geometry")
        return self


class RevisionedMission(BaseModel):
    expected_revision: int = Field(ge=1)
    mission: Mission


class PlanAssignment(BaseModel):
    id: str = Field(default_factory=_id)
    mission_id: str
    unit_ids: list[str] = Field(min_length=1, max_length=10)
    source_point_id: str | None = None
    planned_start_min: float | None = Field(None, ge=0, le=1440)
    locked: bool = False

    @field_validator("unit_ids")
    @classmethod
    def unique_units(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Assignment units must be unique")
        return value


class ResponsePlan(BaseModel):
    id: str = Field(default_factory=_id)
    scenario_id: str = ""
    name: str = Field(default="Response plan", min_length=1, max_length=120)
    description: str = ""
    assignments: list[PlanAssignment] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    revision: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RevisionedPlan(BaseModel):
    expected_revision: int = Field(ge=1)
    plan: ResponsePlan


class SnapshotCreate(BaseModel):
    forecast_ids: list[str] = Field(default_factory=list, max_length=3)
    assumption_overrides: list[str] = Field(default_factory=list)


class SuggestionRequest(BaseModel):
    snapshot_id: str | None = None
    mission_ids: list[str] = Field(min_length=1, max_length=10)
    unit_ids: list[str] = Field(min_length=1, max_length=10)
    locked_assignments: list[PlanAssignment] = Field(default_factory=list)
    forecast_id: str | None = None
    count: int = Field(4, ge=1, le=4)


class ResponseExperimentCreate(BaseModel):
    snapshot_id: str | None = None
    plan_ids: list[str] = Field(min_length=1, max_length=4)
    forecast_ids: list[str] = Field(default_factory=list, max_length=3)
    primary_forecast_id: str | None = None
    evaluation_start_min: float = Field(0, ge=0, le=1440)
    horizon_min: float = Field(120, ge=15, le=240)


class ExerciseRunCreate(BaseModel):
    snapshot_id: str | None = None
    plan_id: str
    plan_revision: int = Field(ge=1)


class ExerciseRunAction(BaseModel):
    action: Literal["play", "pause", "step", "restart", "set_speed"]
    expected_revision: int = Field(ge=1)
    speed: Literal[1, 5, 20] | None = None
    idempotency_key: str | None = None


class ExerciseEventCreate(BaseModel):
    kind: Literal["road_blockage", "road_reopening", "unit_unavailable", "water_source_change"]
    offset_min: float = Field(ge=0, le=1440)
    payload: dict[str, Any]
    idempotency_key: str | None = None


class ExerciseRouteRequest(BaseModel):
    unit_id: str
    vehicle_id: str
    origin: ExerciseLocation
    destination: ExerciseLocation
    departure_min: float = Field(0, ge=0, le=1440)
    service_duration_min: float = Field(0, ge=0, le=1440)
    withdrawal_destination: ExerciseLocation | None = None
    forecast_id: str | None = None
    lead_time_min: float = Field(10, ge=0, le=120)
    alternatives: int = Field(2, ge=0, le=3)
