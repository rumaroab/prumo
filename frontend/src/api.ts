import type { AllocationComparison, AllocationPlan, AllocationRanking, Area, AreaPreparation, AreaPreparationEstimate, AreaPreparationRequest, Comparison, ContainmentTask, Engine, EngineName, ExerciseRun, ExerciseSituation, ExerciseSummary, FeatureCollection, FogosContext, FogosIncident, FogosSnapshot, FogosStatus, FogosSyncResponse, LocationObservation, Mission, MobilityMetrics, MobilitySnapshot, Movement, ObservationEvaluation, OperationalUnit, PlanAssignment, ResponseExperiment, ResponsePlan, RoadClosure, RoadReport, RoadVehicleClass, RouteAnalysis, RouteAssessment, RouteLocation, RoutePlan, Run, RunMode, Scenario, ScenarioWorkspace, SessionUser, SituationSnapshot, VehicleProfile, WeatherSeries } from "./types";
import type { AccessAssessment, AccessAssessmentInput, ComparisonInput, MobilityComparison, PlanningUnit } from "./types";
import { apiErrorMessage } from "./locale";

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    let detail: unknown;
    let code: unknown;
    try { const body = JSON.parse(text); detail = body.detail; code = body.code; } catch { detail = text; }
    throw new Error(apiErrorMessage(detail, response.status, code));
  }
  return response.json();
}

export const api = {
  session: () => request<SessionUser>("/api/session"),
  login: (username: string, password: string) => request<SessionUser>("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }) }),
  logout: () => request<{ signed_out: boolean }>("/api/session", { method: "DELETE" }),
  area: (signal?: AbortSignal, packageId?: string | null) => request<Area>(`/api/area${packageId ? `?package_id=${packageId}` : ""}`, { signal }),
  engines: (signal?: AbortSignal) => request<Engine[]>("/api/engines", { signal }),
  scenarios: (signal?: AbortSignal) => request<ScenarioWorkspace[]>("/api/scenarios", { signal }),
  scenario: (id: string, signal?: AbortSignal) => request<ScenarioWorkspace>(`/api/scenarios/${id}`, { signal }),
  scenarioRuns: (id: string, signal?: AbortSignal) => request<Run[]>(`/api/scenarios/${id}/runs`, { signal }),
  renameScenario: (id: string, name: string, expectedRevision: number) => request<ScenarioWorkspace>(`/api/scenarios/${id}/name`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, expected_revision: expectedRevision }),
  }),
  deleteScenario: (id: string, expectedRevision: number) => request<{ deleted: boolean }>(`/api/scenarios/${id}?expected_revision=${expectedRevision}`, { method: "DELETE" }),
  createScenario: (value: string | Record<string, unknown> = "Custom scenario", idempotencyKey?: string) => request<ScenarioWorkspace>("/api/scenarios", {
    method: "POST", headers: { "Content-Type": "application/json", ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}) }, body: JSON.stringify(typeof value === "string" ? { name: value } : value),
  }),
  fogosStatus: (signal?: AbortSignal) => request<FogosStatus>("/api/integrations/fogos/status", { signal }),
  fogosIncidents: (mode: "active" | "historical", filters: { municipality?: string; day?: string; page?: number }, signal?: AbortSignal) => {
    const query = new URLSearchParams({ mode, page: String(filters.page || 1) });
    if (filters.municipality) query.set("municipality", filters.municipality);
    if (filters.day) query.set("day", filters.day);
    return request<{ items: FogosIncident[]; paginator?: Record<string, unknown> | null; attribution: string; source_url: string }>(`/api/integrations/fogos/incidents?${query}`, { signal });
  },
  fogosImportPreview: (incidentId: string) => request<{ snapshot: FogosSnapshot; incident: FogosIncident; suggested: { name: string; description: string; start_time?: string | null; coordinates?: [number, number] | null } }>("/api/integrations/fogos/import-preview", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ incident_id: incidentId }),
  }),
  fogosContext: (scenarioId: string, signal?: AbortSignal) => request<FogosContext>(`/api/scenarios/${scenarioId}/external-incident`, { signal }),
  refreshFogos: (scenarioId: string) => request<FogosContext>(`/api/scenarios/${scenarioId}/external-incident/refresh`, { method: "POST" }),
  syncFogos: (scenarioId: string, expectedRevision: number) => request<FogosSyncResponse>(`/api/scenarios/${scenarioId}/external-incident/sync`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: expectedRevision }),
  }),
  fogosSnapshots: (scenarioId: string, productType?: string, signal?: AbortSignal) => request<FogosSnapshot[]>(`/api/scenarios/${scenarioId}/external-incident/snapshots${productType ? `?product_type=${encodeURIComponent(productType)}` : ""}`, { signal }),
  setFogosTracking: (scenarioId: string, enabled: boolean) => request<FogosContext>(`/api/scenarios/${scenarioId}/external-incident/tracking`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }),
  }),
  fogosLayer: (scenarioId: string, layer: "weather" | "perimeter" | "pyrocast" | "risk" | "aircraft" | "icnf" | "vost" | "firms", signal?: AbortSignal) => request<unknown>(`/api/scenarios/${scenarioId}/fogos/layers/${layer}`, { signal }),
  applyFogosWeather: (scenarioId: string, expectedRevision: number) => request<ScenarioWorkspace>(`/api/scenarios/${scenarioId}/fogos/apply-weather`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: expectedRevision }),
  }),
  createFogosWeatherSeries: (scenarioId: string) => request<WeatherSeries>(`/api/scenarios/${scenarioId}/fogos/weather-series`, { method: "POST" }),
  observationEvaluations: (runId: string, signal?: AbortSignal) => request<ObservationEvaluation[]>(`/api/runs/${runId}/observation-evaluations`, { signal }),
  createObservationEvaluation: (runId: string, snapshotId: string, assumedObservedAt?: string, assumedRunStartTime?: string) => request<ObservationEvaluation>(`/api/runs/${runId}/observation-evaluations`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ snapshot_id: snapshotId, assumed_observed_at: assumedObservedAt || null, assumed_run_start_time: assumedRunStartTime || null }),
  }),
  createObservationSeries: (runId: string, assumedRunStartTime?: string) => request<{ created: ObservationEvaluation[]; skipped: { snapshot_id: string; reason: string }[] }>(`/api/runs/${runId}/observation-evaluations/series${assumedRunStartTime ? `?assumed_run_start_time=${encodeURIComponent(assumedRunStartTime)}` : ""}`, { method: "POST" }),
  saveScenario: (scenario: ScenarioWorkspace, expectedRevision: number) => request<ScenarioWorkspace>(`/api/scenarios/${scenario.id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      expected_revision: expectedRevision, name: scenario.name, description: scenario.description,
      area_id: scenario.area_id, start_time: scenario.start_time, simulation: scenario.simulation, points: scenario.points,
      resource_center: scenario.resource_center, resource_radius_km: scenario.resource_radius_km,
      fire_margin_km: scenario.fire_margin_km, cell_size_m: scenario.cell_size_m,
      area_package_id: scenario.area_package_id,
      closures: scenario.closures, teams: scenario.teams, resource_groups: scenario.resource_groups,
      containment_tasks: scenario.containment_tasks,
      allocation_plans: scenario.allocation_plans,
      scenario_kind: scenario.scenario_kind, source_scenario_id: scenario.source_scenario_id,
    }),
  }),
  weather: (signal?: AbortSignal) => request<WeatherSeries[]>("/api/weather-series", { signal }),
  estimateArea: (value: AreaPreparationRequest, signal?: AbortSignal) => request<AreaPreparationEstimate>("/api/area-preparations/estimate", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value), signal,
  }),
  prepareArea: (value: AreaPreparationRequest) => request<AreaPreparation>("/api/area-preparations", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value),
  }),
  preparation: (id: string) => request<AreaPreparation>(`/api/area-preparations/${id}`),
  cancelPreparation: (id: string) => request<AreaPreparation>(`/api/area-preparations/${id}/cancel`, { method: "POST" }),
  retryPreparation: (id: string) => request<AreaPreparation>(`/api/area-preparations/${id}/retry`, { method: "POST" }),
  uploadWeather: (file: File) => request<WeatherSeries>("/api/weather-series", {
    method: "POST", headers: { "Content-Type": "text/csv", "X-Filename": file.name }, body: file,
  }),
  run: (scenario: Scenario, mode: RunMode, ensemble?: { kind: "parameter"; preset: "quick" | "standard" } | { kind: "comparison"; engines: EngineName[] }) => request<Run>("/api/runs", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario, mode, ensemble }),
  }),
  runScenario: (id: string, mode: RunMode, ensemble?: { kind: "parameter"; preset: "quick" | "standard" } | { kind: "comparison"; engines: EngineName[] }, name?: string, notes = "") => request<Run>(`/api/scenarios/${id}/runs`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode, ensemble, name, notes }),
  }),
  updateRunMetadata: (id: string, name: string, notes: string, expectedMetadataRevision: number) => request<Run>(`/api/runs/${id}/metadata`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, notes, expected_metadata_revision: expectedMetadataRevision }),
  }),
  deleteRun: (id: string, expectedMetadataRevision: number) => request<{ deleted: boolean }>(`/api/runs/${id}?expected_metadata_revision=${expectedMetadataRevision}`, { method: "DELETE" }),
  waterCatalog: (areaId: string, signal?: AbortSignal) => request<FeatureCollection & { metadata?: Record<string, unknown> }>(`/api/areas/${areaId}/water-points`, { signal }),
  areaRoads: (areaId: string, signal?: AbortSignal) => request<FeatureCollection>(`/api/areas/${areaId}/roads`, { signal }),
  fireStationCatalog: (areaId: string, signal?: AbortSignal) => request<FeatureCollection & { metadata?: Record<string, unknown> }>(`/api/areas/${areaId}/fire-stations`, { signal }),
  importPoints: (scenarioId: string, expectedRevision: number, externalIds: string[]) => request<ScenarioWorkspace>(`/api/scenarios/${scenarioId}/points/import`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: expectedRevision, external_ids: externalIds }),
  }),
  importFireStations: (scenarioId: string, expectedRevision: number, externalIds: string[]) => request<ScenarioWorkspace>(`/api/scenarios/${scenarioId}/points/import-fire-stations`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: expectedRevision, external_ids: externalIds }),
  }),
  status: (id: string) => request<Run>(`/api/runs/${id}`),
  roads: (id: string, buffer: number, signal?: AbortSignal) => request<FeatureCollection>(`/api/runs/${id}/roads?buffer_m=${buffer}`, { signal }),
  fire: (id: string, minute: number, signal?: AbortSignal) => request<FeatureCollection>(`/api/runs/${id}/fire?minute=${minute}`, { signal }),
  routes: (id: string, value: { origin: RouteLocation; destination: RouteLocation; departure_min: number; on_scene_min: number; withdrawal_destination?: RouteLocation; closures: RoadClosure[]; alternatives: number; exposure_buffer_m: number; simulation_horizon_min: number }, signal?: AbortSignal) => request<RouteAnalysis>(`/api/runs/${id}/routes`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value), signal,
  }),
  containmentSuggestions: (scenarioId: string, runId: string, standoffM = 120) => request<{ tasks: (ContainmentTask & { asset_arrival_min: number; standoff_m: number })[] }>(`/api/scenarios/${scenarioId}/containment-suggestions`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ run_id: runId, standoff_m: standoffM, max_tasks: 6 }),
  }),
  rankAllocations: (scenarioId: string, runId: string, departureMin: number, leadTimeMin: number, configurations?: AllocationPlan[]) => request<AllocationRanking>(`/api/scenarios/${scenarioId}/allocation-plans/rank`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ run_id: runId, departure_min: departureMin, lead_time_min: leadTimeMin, count: 4, configurations }),
  }),
  compareAllocations: (scenarioId: string, runId: string, planIds: string[], departureMin: number, leadTimeMin: number) => request<Run>(`/api/scenarios/${scenarioId}/allocation-comparisons`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ run_id: runId, plan_ids: planIds, departure_min: departureMin, lead_time_min: leadTimeMin }),
  }),
  allocationComparison: (id: string, signal?: AbortSignal) => request<AllocationComparison>(`/api/runs/${id}/allocation-comparison`, { signal }),
  children: (id: string, signal?: AbortSignal) => request<Run[]>(`/api/runs/${id}/children`, { signal }),
  comparison: (id: string, minute?: number, signal?: AbortSignal) => request<Comparison>(`/api/runs/${id}/comparison${minute == null ? "" : `?minute=${minute}`}`, { signal }),
  cancel: (id: string) => request<Run>(`/api/runs/${id}/cancel`, { method: "POST" }),
  mobility: (scenarioId: string, signal?: AbortSignal) => request<MobilitySnapshot>(`/api/scenarios/${scenarioId}/mobility`, { signal }),
  mobilityComparisons: (scenarioId: string) => request<MobilityComparison[]>(`/api/scenarios/${scenarioId}/mobility-comparisons`),
  compareMobility: (scenarioId: string, value: ComparisonInput) => request<MobilityComparison>(`/api/scenarios/${scenarioId}/mobility-comparisons`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) }),
  accessRoads: (scenarioId: string, comparisonId: string) => request<FeatureCollection>(`/api/scenarios/${scenarioId}/mobility-comparisons/${comparisonId}/access-roads`),
  accessAssessments: (scenarioId: string) => request<AccessAssessment[]>(`/api/scenarios/${scenarioId}/access-assessments`),
  assessAccess: (scenarioId: string, value: AccessAssessmentInput) => request<AccessAssessment>(`/api/scenarios/${scenarioId}/access-assessments`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) }),
  previewPlanningCsv: (scenarioId: string, filename: string, content: string) => request<{ filename: string; units: PlanningUnit[]; errors: { row: number; message: string }[]; imported_at: string }>(`/api/scenarios/${scenarioId}/mobility-comparisons/import-preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename, content }) }),
  mobilityMetrics: (signal?: AbortSignal) => request<{ scenarios: Record<string, MobilityMetrics>; server_time: string }>("/api/mobility/metrics", { signal }),
  exerciseSummaries: (signal?: AbortSignal) => request<{ scenarios: Record<string, ExerciseSummary>; server_time: string }>("/api/exercise-summaries", { signal }),
  createExerciseCopy: (scenarioId: string, value: { name?: string; description?: string; reference_time?: string; forecast_ids?: string[] } = {}, idempotencyKey = crypto.randomUUID()) => request<ScenarioWorkspace>(`/api/scenarios/${scenarioId}/exercise-copy`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }, body: JSON.stringify(value) }),
  exerciseSituation: (scenarioId: string, signal?: AbortSignal) => request<ExerciseSituation>(`/api/scenarios/${scenarioId}/exercise-situation`, { signal }),
  saveExerciseSituation: (scenarioId: string, value: ExerciseSituation) => request<ExerciseSituation>(`/api/scenarios/${scenarioId}/exercise-situation`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...value, expected_revision: value.revision }) }),
  snapshots: (scenarioId: string, signal?: AbortSignal) => request<SituationSnapshot[]>(`/api/scenarios/${scenarioId}/situation-snapshots`, { signal }),
  createSnapshot: (scenarioId: string, forecastIds: string[] = [], assumptionOverrides: string[] = []) => request<SituationSnapshot>(`/api/scenarios/${scenarioId}/situation-snapshots`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ forecast_ids: forecastIds, assumption_overrides: assumptionOverrides }) }),
  missions: (scenarioId: string, signal?: AbortSignal) => request<Mission[]>(`/api/scenarios/${scenarioId}/missions`, { signal }),
  addMission: (scenarioId: string, mission: Mission) => request<Mission>(`/api/scenarios/${scenarioId}/missions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(mission) }),
  saveMission: (scenarioId: string, mission: Mission) => request<Mission>(`/api/scenarios/${scenarioId}/missions/${mission.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: mission.revision, mission }) }),
  archiveMission: (scenarioId: string, mission: Mission) => request<{ archived: boolean }>(`/api/scenarios/${scenarioId}/missions/${mission.id}?expected_revision=${mission.revision}`, { method: "DELETE" }),
  responsePlans: (scenarioId: string, signal?: AbortSignal) => request<ResponsePlan[]>(`/api/scenarios/${scenarioId}/response-plans`, { signal }),
  addResponsePlan: (scenarioId: string, plan: ResponsePlan) => request<ResponsePlan>(`/api/scenarios/${scenarioId}/response-plans`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(plan) }),
  saveResponsePlan: (scenarioId: string, plan: ResponsePlan) => request<ResponsePlan>(`/api/scenarios/${scenarioId}/response-plans/${plan.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: plan.revision, plan }) }),
  archiveResponsePlan: (scenarioId: string, plan: ResponsePlan) => request<{ archived: boolean }>(`/api/scenarios/${scenarioId}/response-plans/${plan.id}?expected_revision=${plan.revision}`, { method: "DELETE" }),
  suggestResponsePlans: (scenarioId: string, missionIds: string[], unitIds: string[], lockedAssignments: PlanAssignment[] = [], count = 4) => request<{ plans: (ResponsePlan & { evaluation: Record<string, unknown> })[]; shortages: Record<string, unknown>[]; water_source_shortlists: Record<string, unknown[]>; partial: boolean; message: string }>(`/api/scenarios/${scenarioId}/response-plans/suggestions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mission_ids: missionIds, unit_ids: unitIds, locked_assignments: lockedAssignments, count }) }),
  responseExperiments: (scenarioId: string, signal?: AbortSignal) => request<ResponseExperiment[]>(`/api/scenarios/${scenarioId}/response-experiments`, { signal }),
  createResponseExperiment: (scenarioId: string, planIds: string[], forecastIds: string[] = [], horizonMin = 120, idempotencyKey = crypto.randomUUID()) => request<ResponseExperiment>(`/api/scenarios/${scenarioId}/response-experiments`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }, body: JSON.stringify({ plan_ids: planIds, forecast_ids: forecastIds, horizon_min: horizonMin }) }),
  exerciseRuns: (scenarioId: string, signal?: AbortSignal) => request<ExerciseRun[]>(`/api/scenarios/${scenarioId}/exercise-runs`, { signal }),
  createExerciseRun: (scenarioId: string, plan: ResponsePlan, idempotencyKey = crypto.randomUUID()) => request<ExerciseRun>(`/api/scenarios/${scenarioId}/exercise-runs`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }, body: JSON.stringify({ plan_id: plan.id, plan_revision: plan.revision }) }),
  exerciseRunAction: (scenarioId: string, run: ExerciseRun, action: "play" | "pause" | "step" | "restart" | "set_speed", speed?: 1 | 5 | 20) => request<ExerciseRun>(`/api/scenarios/${scenarioId}/exercise-runs/${run.id}/actions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, speed, expected_revision: run.revision, idempotency_key: crypto.randomUUID() }) }),
  advanceExerciseRun: (scenarioId: string, runId: string, minutes = 1) => request<ExerciseRun>(`/api/scenarios/${scenarioId}/exercise-runs/${runId}/advance`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ minutes }) }),
  addExerciseEvent: (scenarioId: string, runId: string, kind: "road_blockage" | "road_reopening" | "unit_unavailable" | "water_source_change", offsetMin: number, payload: Record<string, unknown>) => request<ExerciseRun>(`/api/scenarios/${scenarioId}/exercise-runs/${runId}/events`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind, offset_min: offsetMin, payload, idempotency_key: crypto.randomUUID() }) }),
  mobilityRoads: (scenarioId: string, signal?: AbortSignal) => request<FeatureCollection>(`/api/scenarios/${scenarioId}/mobility/roads`, { signal }),
  addVehicle: (scenarioId: string, value: VehicleProfile) => request<VehicleProfile>(`/api/scenarios/${scenarioId}/mobility/vehicles`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) }),
  addUnit: (scenarioId: string, value: OperationalUnit) => request<OperationalUnit>(`/api/scenarios/${scenarioId}/mobility/units`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) }),
  setUnitStatus: (scenarioId: string, unit: OperationalUnit, status: "available" | "unavailable") => request<OperationalUnit>(`/api/scenarios/${scenarioId}/mobility/units/${unit.id}/status`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, expected_revision: unit.revision }) }),
  checkIn: (scenarioId: string, unitId: string, value: Pick<LocationObservation, "coordinates" | "observed_at" | "source" | "accuracy_m">) => request<LocationObservation>(`/api/scenarios/${scenarioId}/mobility/units/${unitId}/locations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) }),
  addRoadReport: (scenarioId: string, value: RoadReport) => request<RoadReport>(`/api/scenarios/${scenarioId}/mobility/road-reports`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) }),
  reviewRoadReport: (scenarioId: string, report: RoadReport, status: "confirmed" | "dismissed", segmentId?: string, direction?: RoadReport["direction"]) => request<RoadReport>(`/api/scenarios/${scenarioId}/mobility/road-reports/${report.id}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, expected_revision: report.revision, segment_id: segmentId || report.segment_id, direction: direction || report.direction }) }),
  addWaterReport: (scenarioId: string, value: { point_id: string; availability: "available" | "unavailable" | "uncertain"; note: string; observed_at: string }) => request(`/api/scenarios/${scenarioId}/mobility/water-reports`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) }),
  reviewWaterReport: (scenarioId: string, reportId: string, status: "confirmed" | "dismissed", expectedRevision: number) => request(`/api/scenarios/${scenarioId}/mobility/water-reports/${reportId}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, expected_revision: expectedRevision }) }),
  mobilityRoute: (scenarioId: string, value: { origin: RouteLocation; destination: RouteLocation; vehicle_id?: string; vehicle_class?: RoadVehicleClass; departure_at: string; alternatives: number }) => request<RouteAssessment>(`/api/scenarios/${scenarioId}/mobility/routes`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) }),
  routePlans: (scenarioId: string) => request<RoutePlan[]>(`/api/scenarios/${scenarioId}/mobility/route-plans`),
  saveRoutePlan: (scenarioId: string, value: Omit<RoutePlan, "id" | "scenario_id" | "route" | "revision" | "assigned_movement_id" | "created_at" | "updated_at"> & { preview_signature: string; expected_revision?: number }, planId?: string) => request<RoutePlan>(`/api/scenarios/${scenarioId}/mobility/route-plans${planId ? `/${planId}` : ""}`, { method: planId ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) }),
  deleteRoutePlan: (scenarioId: string, plan: RoutePlan) => request<{ deleted: boolean }>(`/api/scenarios/${scenarioId}/mobility/route-plans/${plan.id}?expected_revision=${plan.revision}`, { method: "DELETE" }),
  createMovement: (scenarioId: string, value: Record<string, unknown>) => request<Movement>(`/api/scenarios/${scenarioId}/mobility/movements`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) }),
  movement: (scenarioId: string, movementId: string) => request<Movement>(`/api/scenarios/${scenarioId}/mobility/movements/${movementId}`),
  movementAction: (scenarioId: string, movement: Movement, action: string, source: "crew" | "radio" | "dispatcher" = "crew", note = "", requestId: string = crypto.randomUUID()) => request<Movement>(`/api/scenarios/${scenarioId}/mobility/movements/${movement.id}/actions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, source, note, expected_revision: movement.revision, expected_brief_version: movement.brief_version, request_id: requestId }) }),
  reviseMovementRoute: (scenarioId: string, movement: Movement, route: RouteAssessment, suitabilityAcknowledged: boolean) => request<Movement>(`/api/scenarios/${scenarioId}/mobility/movements/${movement.id}/route`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ preview_signature: route.preview_signature, departure_at: route.departure_at, suitability_acknowledged: suitabilityAcknowledged, expected_revision: movement.revision }) }),
  shareMovement: (scenarioId: string, movementId: string) => request<{ token: string; url: string; expires_hours: number }>(`/api/scenarios/${scenarioId}/mobility/movements/${movementId}/shares`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expires_hours: 12 }) }),
  sharedBrief: (token: string) => request<Movement>(`/api/mobility/shared/${token}`),
};
