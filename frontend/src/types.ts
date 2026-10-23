export type EngineName = string;
export type DecisionExplanation = { code: string; category: "modelled_fire" | "restriction" | "missing_data" | "resource"; severity: string; place: string; message: string; feature?: GeoJSON.Feature | null; event_min?: number | null; exposure_min?: number | null; vehicle_exit_min?: number | null; lead_time_min?: number; margin_min?: number; constraint?: string; actual?: number; limit?: number; exercise_assumption?: string | null; stage?: string | null; unit?: string };
export type PlanningUnit = { id: string; callsign: string; organisation: string; vehicle: VehicleProfile; coordinates: [number, number]; observed_at?: string | null; source_file?: string | null };
export type SourceChoice = { point_id: string; available_volume_l?: number | null; flow_l_min?: number | null; setup_time_min?: number | null };
export type ComparisonInput = { run_id: string; forecast_start_at: string; departure_at: string; unit: PlanningUnit; delivery_coordinates: [number, number]; requested_l: number; sources: SourceChoice[]; lead_time_min: number };
export type TripStage = { kind: string; start_min: number; end_min: number; coordinates?: [number, number]; status?: string; route?: { feature: GeoJSON.Feature; duration_min: number; minimum_forecast_margin_min?: number | null; trajectory?: { minute: number; coordinates: [number, number] }[] }; baseline_feature?: GeoJSON.Feature | null; conflict?: { reason: string; segment_ids?: string[]; road_name?: string; feature?: GeoJSON.Feature | null; vehicle_exit_min?: number; exposure_min?: number } | null };
export type ComparisonOutcome = { label: string; source: ScenarioPoint; assumptions: SourceChoice; status: "clear" | "infeasible" | "unknown"; reason: string; explanations?: DecisionExplanation[]; change_reason?: string; delivered_l: number; delivery_min?: number; minimum_forecast_margin_min?: number | null; baseline_duration_min?: number | null; baseline_feature?: GeoJSON.Feature | null; stages: TripStage[]; conflict?: TripStage["conflict"] };
export type MobilityComparison = { id: string; scenario_id: string; created_at: string; run_id: string; run_name: string; engine: string; forecast_start_at: string; departure_min: number; horizon_min: number; lead_time_min: number; unit: PlanningUnit; delivery_coordinates: [number, number]; requested_l: number; outcomes: ComparisonOutcome[]; road_package_id: string | null; road_revision: string; model_provenance: Record<string, unknown> };
export type PopulationOption = { reception_id: string; status: "clear" | "infeasible" | "unknown"; reason: string; explanations?: DecisionExplanation[]; arrival_min?: number; duration_min?: number; minimum_forecast_margin_min?: number | null; route?: TripStage["route"]; conflict?: TripStage["conflict"] };
export type PopulationResult = { origin: ScenarioPoint; status: "clear" | "infeasible" | "unknown"; reachable_count: number; best_reception_id?: string | null; change_reason?: string; explanations?: DecisionExplanation[]; options: PopulationOption[] };
export type AccessVariant = { water: ComparisonOutcome[]; population: PopulationResult[] };
export type AccessAssessment = { id: string; scenario_id: string; created_at: string; comparison_id: string; comparison: MobilityComparison; road_revision: string; section_id?: string | null; closure_feature?: GeoJSON.Feature | null; population_points: ScenarioPoint[]; population_vehicle: VehicleProfile; without: AccessVariant; with_proposal: AccessVariant; summary: { water_changed: boolean; population_changed: number } };
export type AccessAssessmentInput = { comparison_id: string; section_id?: string | null; points: ScenarioPoint[]; population_vehicle: VehicleProfile };
export type CellSizeM = 10 | 15 | 20 | 30;
export type Area = {
  name: string;
  center: [number, number];
  bounds: [number, number, number, number];
  landscape_ready: boolean;
  roads_ready: boolean;
  package_id?: string | null;
  fire_bounds?: [number, number, number, number];
  resource_bounds?: [number, number, number, number];
  manifest?: Record<string, unknown>;
};
export type RunMode = "single" | "parameter_ensemble" | "engine_comparison" | "allocation_comparison";
export type Engine = {
  id: EngineName;
  display_name: string;
  profiles: string[];
  default_profile: string;
  weather_modes: ("constant" | "series")[];
  profile_weather: Record<string, ("constant" | "series")[]>;
  runner: string;
  compute_class: string;
  limitations: string[];
  available: boolean;
  message: string;
  supports_multiple_ignitions: boolean;
  supports_delayed_ignitions: boolean;
  execution_pool?: "thread" | "process";
  concurrency_key?: string;
};
export type Ignition = { id: string; name: string; coordinates: [number, number]; start_min: number };
export type WeatherSource = { kind: "constant"; provenance?: Record<string, unknown> | null } | { kind: "series"; id: string };
export type Scenario = {
  name: string;
  engine: EngineName;
  ignitions: Ignition[];
  wind_speed_kmh: number;
  wind_direction_deg: number;
  moisture: "low" | "moderate" | "high";
  duration_min: number;
  seed: number;
  exposure_buffer_m: number;
  weather_source: WeatherSource;
  engine_profile: string;
};
export type PointKind = "response_base" | "water_point" | "asset" | "hazard" | "staging_area" | "access_control" | "shelter" | "delivery_point" | "custom";
export type WaterPointDetails = {
  source_type: "hydrant" | "tank" | "reservoir" | "pond" | "other";
  availability: "available" | "unavailable" | "unknown";
  capacity_m3: number | null;
  flow_l_min: number | null;
  access_notes: string;
  verification_status: "unverified" | "reported" | "verified";
  observed_at?: string | null;
  supply_class?: "finite" | "continuous" | "unknown";
  available_volume_l?: number | null;
  shared_flow_l_min?: number | null;
  filling_positions?: number | null;
  setup_time_min?: number | null;
};
export type AssetDetails = { priority: number };
export type ScenarioPoint = {
  id: string;
  kind: PointKind;
  name: string;
  coordinates: [number, number];
  description: string;
  notes: string;
  source: "manual" | "openstreetmap" | "icnf" | "demo";
  source_url?: string | null;
  source_updated_at?: string | null;
  external_id?: string | null;
  imported_at?: string | null;
  data_status: "unverified" | "reported" | "verified";
  water?: WaterPointDetails | null;
  asset?: AssetDetails | null;
  population_role?: "origin" | "reception" | null;
  population_count?: number | null;
};
export type ResponseTeam = {
  id: string; name: string; base_point_id: string; available_from_min: number;
  line_rate_m_min: number; max_deployment_min: number; status: "available" | "unavailable";
  source_provenance?: TeamSourceProvenance | null;
};
export type ResourceCategory = "operacionais" | "meios_terrestres" | "meios_aereos";
export type ScenarioResourceGroup = {
  id: string; category: ResourceCategory; name: string; notes: string;
  reported_count: number | null; planned_count_override: number | null;
  provider: "fogos.pt"; incident_id: string; snapshot_id: string;
  observed_at?: string | null; synced_at: string;
};
export type TeamSourceProvenance = {
  provider: "fogos.pt"; incident_id: string; resource_group_id: string;
  category: "operacionais"; snapshot_id: string; reported_count: number | null;
  planned_count: number | null; converted_at: string;
};
export type ContainmentTask = {
  id: string; name: string; geometry: GeoJSON.LineString; protected_asset_ids: string[];
  source: "suggested" | "manual"; enabled: boolean;
};
export type AllocationAssignment = { task_id: string; team_ids: string[] };
export type AllocationPlan = { id: string; name: string; assignments: AllocationAssignment[] };
export type RoadClosure = {
  id: string;
  segment_id: string;
  road_name: string;
  reason: string;
  source: string;
  direction: "both" | "forward" | "reverse";
  starts_min: number;
  ends_min: number | null;
  geometry: GeoJSON.Geometry;
};
export type ScenarioWorkspace = {
  id: string;
  name: string;
  description: string;
  area_id: string;
  resource_center?: [number, number] | null;
  resource_radius_km: 10 | 25 | 50;
  fire_margin_km: 5 | 10 | 25;
  cell_size_m: CellSizeM;
  area_package_id?: string | null;
  start_time?: string | null;
  revision: number;
  simulation: Scenario;
  points: ScenarioPoint[];
  closures: RoadClosure[];
  teams: ResponseTeam[];
  resource_groups: ScenarioResourceGroup[];
  containment_tasks: ContainmentTask[];
  allocation_plans: AllocationPlan[];
  created_at: string;
  updated_at: string;
  setup_complete: boolean;
  external_incident?: ExternalIncidentLink | null;
  scenario_kind: "legacy" | "exercise";
  source_scenario_id?: string | null;
};
export type ExternalIncidentLink = {
  provider: "fogos.pt"; incident_id: string; import_snapshot_id: string;
  original_longitude?: number | null; original_latitude?: number | null; linked_at: string;
  source_url?: string | null; latest_snapshot_id?: string | null; last_success_at?: string | null;
  next_poll_at?: string | null; last_error?: string | null; tracking_enabled: boolean;
  tracking_next_attempt?: string | null; tracking_failures?: number | null;
};
export type Run = {
  id: string;
  status: string;
  stage: string;
  progress: number;
  scenario: Scenario;
  error?: string;
  mode: RunMode;
  parent_id?: string;
  member_index?: number;
  runner?: string;
  successful_members?: number;
  expected_members?: number;
  children?: Run[];
  result?: { engine: string; engine_version: string; temporal_resolution_min: number; manifest: Record<string, unknown> };
  scenario_id?: string | null;
  scenario_revision?: number | null;
  area_package_id?: string | null;
  intervention?: Record<string, unknown> | null;
  created_at?: string;
  updated_at?: string;
  name: string;
  notes: string;
  metadata_revision: number;
  run_context?: { scenario_start_time?: string | null; weather_source?: WeatherSource; external_incident?: ExternalIncidentLink | null } | null;
};
export type FogosStatus = { configured: boolean; message: string; provider: string; attribution: string; source_url: string; last_success_at?: string | null };
export type FogosIncident = {
  provider: string; incident_id: string; source_url: string; reported_at?: string | null; updated_at?: string | null;
  location: string; detail_location?: string | null; district?: string | null; municipality?: string | null; parish?: string | null;
  coordinates?: [number, number] | null; has_usable_coordinates: boolean; nature?: string | null; nature_code?: string;
  is_rural_fire: boolean; status?: string | null; status_code?: number | null; active: boolean; importable: boolean;
  resources: { personnel: number | null; vehicles: number | null; aircraft: number | null; firefighting_aircraft: number | null };
  weather?: { wind_speed_kmh: number; wind_direction_deg: number; wind_direction_label?: string | null; temperature_c?: number | null;
    relative_humidity_pct?: number | null; precipitation_mm?: number | null; station_id?: string | null; station_name?: string | null;
    station_distance_km?: number | null; observed_at?: string | null } | null;
  weather_warnings: Record<string, unknown>[]; linked_scenarios?: { id: string; name: string }[];
};
export type FogosSnapshot = { id: string; provider: string; incident_id: string; product_type: string; checksum: string;
  source_url?: string | null; retrieved_at: string; observed_at?: string | null; quality_notes: string[]; normalized: Record<string, unknown> };
export type FogosContext = { link: ExternalIncidentLink; import_snapshot?: FogosSnapshot | null; latest_incident?: (FogosSnapshot & { normalized: FogosIncident }) | null;
  snapshots: FogosSnapshot[]; attribution: string; source_url?: string | null };
export type FogosResourceChange = { category: ResourceCategory; name: string; before: number | null; after: number | null; created: boolean };
export type FogosSyncResponse = { scenario: ScenarioWorkspace; context: FogosContext; changes: FogosResourceChange[] };
export type ObservationEvaluation = { id: string; run_id: string; snapshot_ids: string[]; observed_at: string; time_basis: string;
  assumption?: string | null; metric_version: string; created_at: string; metrics: { aligned_minute: number; intersection_over_union?: number | null;
    simulated_area_ha: number; observed_area_ha: number; observed_total_area_ha?: number; area_difference_ha: number; hausdorff_distance_m?: number | null;
    observation_outside_coverage_fraction: number; partial: boolean; crs: string; source_resolution: string }; observation?: FeatureCollection };
export type AreaPreparation = {
  id: string;
  package_id: string;
  status: "queued" | "running" | "ready" | "partial" | "failed" | "cancelled";
  stage: string;
  progress: number;
  datasets: Record<string, {
    status?: string; source?: string; error?: string;
    osm_provenance?: {
      provider: "local" | "overpass";
      snapshot_id?: string;
      data_timestamp?: string;
      stale?: boolean;
      refresh_error?: string | null;
      fallback_reason?: string;
    };
  }>;
  error?: string | null;
  failure_code?: string | null;
  retryable?: boolean | null;
  retry_at?: string | null;
  tile_progress?: { completed: number; total: number } | null;
  source_progress?: {
    provider: "local" | "overpass";
    phase: "waiting" | "downloading" | "validating" | "extracting" | "ready" | "fallback";
    region?: string | null;
    downloaded_bytes?: number | null;
    total_bytes?: number | null;
    reason?: string;
  } | null;
};
export type AreaPreparationRequest = {
  center: [number, number];
  resource_radius_km: 10 | 25 | 50;
  fire_margin_km: 5 | 10 | 25;
  cell_size_m: CellSizeM;
  ignitions: Ignition[];
  acknowledge_high_cost?: boolean;
};
export type AreaPreparationEstimate = {
  fire_bounds: [number, number, number, number];
  grid_rows: number;
  grid_columns: number;
  cell_count: number;
  area_km2: number;
  cell_size_m: CellSizeM;
  cost_level: "normal" | "moderate" | "high" | "very_high" | "blocked";
  requires_acknowledgement: boolean;
  allowed: boolean;
  blocking_reason?: string | null;
};
export type WeatherSeries = { id: string; filename: string; sha256: string; rows: number; start: string; end: string; valid: boolean };
export type Comparison = { minute: number; members: { run_id: string; engine: EngineName; engine_label: string; burned_area_ha: number; exposed_roads: number; temporal_resolution_min: number; runtime_seconds: number; status: string }[]; failed: { run_id: string; engine: EngineName; status: string; error?: string }[]; agreements: { left: EngineName; right: EngineName; jaccard: number }[] };
export type FeatureCollection = GeoJSON.FeatureCollection<GeoJSON.Geometry, Record<string, unknown>>;
export type RouteLocation = { name: string; coordinates: [number, number] };
export type RouteOption = {
  label: string;
  status: "clear" | "unknown" | "unavailable";
  message: string;
  departure_min: number;
  arrival_min: number;
  duration_min: number;
  distance_km: number;
  closest_fire_margin_min: number | null;
  unknown_roads: string[];
  exposed_segments: string[];
  shared_vulnerable_segments: string[];
  feature: GeoJSON.Feature<GeoJSON.LineString, Record<string, unknown>>;
};
export type RouteAnalysis = {
  origin: RouteLocation;
  destination: RouteLocation;
  departure_min: number;
  routes: RouteOption[];
  baseline_conflicts: { type: "fire" | "closure"; road: string; exposure_min?: number; vehicle_entry_min?: number; vehicle_exit_min?: number; reason?: string }[];
  withdrawal: RouteOption | { label: string; status: "unavailable"; departure_min: number; message: string } | null;
  snap: { origin_distance_m: number; destination_distance_m: number };
  assumptions: { fire_rule: string; speed_source: string; simulation_horizon_min: number };
};
export type AllocationAssignmentEvaluation = {
  task_id: string; task_name: string; protected_asset_ids: string[]; team_ids: string[]; team_names: string[];
  status: "feasible" | "unknown" | "infeasible"; line_length_m: number;
  completion_min: number | null; fire_arrival_min: number | null; margin_min: number | null;
  routes: { team_id: string; team_name: string; outbound: RouteOption; withdrawal: RouteOption }[];
  effort_min: number; message: string;
};
export type RankedAllocationPlan = {
  id: string; name: string; rank?: number; assignments: AllocationAssignmentEvaluation[];
  protected_by_priority: Record<string, number>; feasible_tasks: number; unknown_tasks: number;
  worst_margin_min: number | null; total_effort_min: number;
};
export type AllocationRanking = {
  plans: RankedAllocationPlan[]; message?: string;
  assumptions: { kind: string; lead_time_min: number; fire_effect: string; line_rule: string };
};
export type AllocationComparison = {
  run_id: string; source_run_id: string; engine: EngineName; control: { burned_area_ha: number; exposed_roads: number };
  members: { rank: number; run_id: string; plan_id: string; plan_name: string; burned_area_ha: number;
    burned_area_change_ha: number; reached_by_priority: Record<string, number>; runtime_seconds: number;
    exposed_roads: number; road_exposure_change: number; effort_min: number;
    assets: { asset_id: string; name: string; priority: number; control_arrival_min: number | null;
      arrival_min: number | null; delay_min: number | null }[];
    containment: { tasks?: { task_id: string; task_name: string; activation_min: number; cell_count: number;
      activated_cells: number; breached_cells: number; unused_cells?: number }[]; breached_cells?: number } }[];
  failed: { run_id: string; plan_name: string; status: string; error?: string }[]; assumption: string;
};
export type Filter = "all" | "now" | "upcoming" | "by-then" | "not-reached" | "unknown";
export type Page = "simulation" | "water-planning" | "decision-support";

export type SessionUser = { id: string; username: string; display_name: string; role: "administrator" | "dispatcher" | "crew" };
export type FogosResourceProvenance = {
  provider: "fogos.pt"; incident_id: string; snapshot_id: string;
  category: "meios_terrestres" | "meios_aereos"; sequence: number;
  placeholder: true; observed_at?: string | null;
};
export type VehicleProfile = {
  id: string; name: string; vehicle_class: "light" | "heavy" | "tanker" | "bus" | "ambulance" | "other" | "aircraft";
  import_provenance?: FogosResourceProvenance | null;
  width_m: number | null; height_m: number | null; weight_t: number | null; off_road: boolean; notes: string; revision: number;
  water_tank_capacity_l?: number | null; pump_flow_l_min?: number | null; passenger_capacity?: number | null;
  starting_water_l?: number | null; available?: boolean;
};
export type LocationObservation = {
  id: string; unit_id: string; coordinates: [number, number]; observed_at: string; received_at: string;
  source: "phone" | "radio" | "dispatcher"; accuracy_m: number | null;
};
export type OperationalUnit = {
  id: string; organisation: string; callsign: string; contact: string; vehicle_id: string | null;
  notes?: string; import_provenance?: FogosResourceProvenance | null;
  status: "available" | "assigned" | "travelling" | "on_scene" | "unavailable"; revision: number;
  latest_location?: LocationObservation | null;
  capabilities?: string[]; available_from?: string | null; available_until?: string | null;
  max_deployment_min?: number | null; containment_rate_m_min?: number | null;
};
export type RoadReport = {
  id: string; segment_id: string | null; road_name: string; kind: "blocked" | "restricted" | "reopening" | "uncertain";
  reason: string; direction: "both" | "forward" | "reverse"; affected_vehicle_classes: string[];
  status: "pending" | "confirmed" | "dismissed"; source: "crew" | "radio" | "dispatcher";
  geometry: GeoJSON.Geometry | null; observed_location?: [number, number] | null; observed_at: string; created_at?: string; reviewed_at?: string | null; revision: number;
};
export type WaterSourceReport = { id: string; point_id: string; availability: "available" | "unavailable" | "uncertain";
  note: string; observed_at: string; created_at: string; source: string; reporter_id: string;
  status: "pending" | "confirmed" | "dismissed"; revision: number; reviewer_id?: string | null; reviewed_at?: string | null };
export type RouteAssessment = {
  status: "clear" | "unknown" | "unavailable"; message: string; warnings?: string[]; segment_ids?: string[];
  restrictions_revision?: string;
  preview_signature?: string; departure_at?: string; prepared_revision?: string; vehicle_revision?: number;
  origin_connector_m: number; destination_connector_m: number; data_quality: "exact" | "legacy";
  assumption?: string; selected?: MobilityRoute; routes: MobilityRoute[];
};
export type RoadVehicleClass = "light" | "heavy" | "tanker" | "bus" | "ambulance" | "other";
export type RoutePlan = {
  id: string; scenario_id: string; purpose: string; origin: RouteLocation; destination: RouteLocation;
  departure_at: string; vehicle_class: RoadVehicleClass; route: RouteAssessment;
  revision: number; assigned_movement_id: string | null; created_at: string; updated_at: string;
};
export type MobilityRoute = {
  label: string; duration_min: number; distance_km: number; segment_ids: string[]; road_names: string[];
  unknown_constraints: string[]; feature: GeoJSON.Feature<GeoJSON.LineString>;
};
export type MovementStatus = "assigned" | "accepted" | "travelling" | "arrived" | "completed" | "cannot_proceed" | "cancelled";
export type Movement = {
  id: string; unit_id: string; vehicle_id: string; purpose: string; origin: RouteLocation; destination: RouteLocation;
  departure_at: string; route: RouteAssessment; status: MovementStatus; notes: string; dispatcher_contact: string;
  revision: number; brief_version: number; acknowledged_brief_version?: number | null; needs_review: boolean; created_at: string; updated_at: string;
  vehicle_snapshot?: VehicleProfile;
};
export type MovementEvent = {
  id: string; scenario_id: string; movement_id?: string | null; kind: string; actor_id?: string | null;
  source: string; payload: Record<string, unknown>; created_at: string;
};
export type DemoRun = {
  id: string; scenario_id: string; state: "ready" | "running" | "paused" | "completed" | "error" | "archived";
  speed: number; current_index: number; total_events: number; elapsed_seconds: number; duration_seconds: number;
  stage: string; error?: string | null; is_demo: true;
  next_event?: { id: string; at_seconds: number; message_pt: string; message_en: string } | null;
};
export type DemoCommunication = {
  id: string; run_id: string; scenario_id: string; event_id: string; callsign: string; organisation: string;
  source: string; message_pt: string; message_en: string; observed_at: string; received_at: string;
  linked_type?: "movement" | "road_report" | "unit" | null; linked_id?: string | null; result_state: string;
};
export type MobilitySnapshot = {
  user: SessionUser; scenario: Pick<ScenarioWorkspace, "id" | "name" | "simulation">; vehicles: VehicleProfile[]; units: OperationalUnit[]; road_reports: RoadReport[];
  movements: Movement[]; events: MovementEvent[]; server_time: string;
  water_sources: (ScenarioPoint & { verified_by?: string; verified_at?: string })[]; water_reports: WaterSourceReport[]; incident_points: ScenarioPoint[];
  demo?: DemoRun | null; communications?: DemoCommunication[];
};
export type MobilityMetrics = {
  total_units: number;
  available_units: number;
  active_movements: number;
  pending_road_reports: number;
  routes_needing_review: number;
};

export type ExerciseSummary = {
  scenario_kind: "legacy" | "exercise"; reference_time: string | null; total_units: number | null;
  available_units: number | null; outstanding_missions: number | null; saved_plans: number | null;
  completed_experiments: number | null; active_rehearsal?: { id: string; state: string; elapsed_min: number } | null;
  data_status: "ready" | "loading" | "unavailable";
};
export type ExerciseSituation = {
  scenario_id: string; reference_time: string; summary: string; assumptions: string[];
  selected_forecast_ids: string[]; forecast_alignments: Record<string, string>; forecast_lead_time_min: number; revision: number;
  created_at?: string; updated_at?: string;
};
export type ExerciseLocation = { name: string; coordinates: [number, number]; point_id?: string | null };
export type MissionType = "access_control" | "fire_response" | "water_supply" | "transport" | "logistics" | "containment";
export type Mission = {
  id: string; scenario_id?: string; name: string; mission_type: MissionType; priority: number;
  status: "required" | "planned" | "completed" | "cancelled"; location: ExerciseLocation;
  access_point?: ExerciseLocation | null; earliest_start_min: number; deadline_min?: number | null;
  service_duration_min: number; required_capabilities: string[]; required_unit_count: number;
  prerequisite_ids: string[]; completion_criteria: string; target_volume_l?: number | null;
  demand_rate_l_min?: number | null; demand_duration_min?: number | null; people_count?: number | null;
  pickup?: ExerciseLocation | null; dropoff?: ExerciseLocation | null; cargo_requirements?: string;
  containment_geometry?: GeoJSON.Geometry | null; revision: number; created_at?: string; updated_at?: string;
};
export type PlanAssignment = {
  id: string; mission_id: string; unit_ids: string[]; source_point_id?: string | null;
  planned_start_min?: number | null; locked: boolean;
};
export type ResponsePlan = {
  id: string; scenario_id?: string; name: string; description: string; assignments: PlanAssignment[];
  assumptions: string[]; revision: number; created_at?: string; updated_at?: string;
};
export type SituationSnapshot = {
  id: string; scenario_id: string; reference_time: string; scenario_revision: number; situation_revision: number;
  situation: ExerciseSituation; points: ScenarioPoint[]; closures: RoadClosure[]; vehicles: VehicleProfile[];
  units: OperationalUnit[]; road_reports: RoadReport[]; missions: Mission[]; forecast_ids: string[];
  assumptions: string[]; created_at: string;
};
export type PlanEvaluation = {
  plan_id: string; plan_revision: number; plan_name: string; status: "feasible" | "incomplete" | "unknown";
  missions: Record<string, unknown>[]; fulfilment_by_priority: Record<string, number>;
  unresolved_unknowns: string[]; assumptions: string[]; total_resource_time_min: number;
  minimum_forecast_margin_min: number | null; forecast: { id?: string | null; status: string; message: string };
};
export type ResponseExperiment = {
  id: string; scenario_id: string; snapshot_id: string; status: string; progress: number; stage: string;
  request: Record<string, unknown>; result?: { plans: { plan_id: string; plan_name: string; conditions: PlanEvaluation[]; worst_case_fulfilment: Record<string, number> }[]; message: string } | null;
  error?: string | null; created_at: string; updated_at: string;
};
export type ExerciseRun = {
  id: string; scenario_id: string; snapshot_id: string; plan_id: string; plan_revision: number;
  state: "paused" | "running" | "completed"; speed: 1 | 5 | 20; elapsed_min: number; revision: number;
  payload: { plan: ResponsePlan; evaluation: PlanEvaluation; schedule: Record<string, unknown>[]; affected_mission_ids?: string[] };
  mission_states: Record<string, string>; events: { id: string; kind: string; offset_min: number; payload: Record<string, unknown>; created_at: string; simulated: true }[];
  created_at: string; updated_at: string;
};
