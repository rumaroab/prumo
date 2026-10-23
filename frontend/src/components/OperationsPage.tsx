import { Box, Button, Card, Typography } from "./ui";
import { formatDateTime } from "../locale";
import { useEffect, useRef, useState, type ComponentProps } from "react";
import { api } from "../api";
import type {
  AllocationComparison,
  AllocationPlan,
  Area,
  ContainmentTask,
  FeatureCollection,
  Page,
  RankedAllocationPlan,
  ResponseTeam,
  RoadClosure,
  RouteAnalysis,
  RouteLocation,
  Run,
  ScenarioResourceGroup,
  ScenarioWorkspace,
} from "../types";
import { MapView } from "./MapView";
import { PointsEditor } from "./PointsEditor";
import { Timeline, type TimelineChangeSource } from "./Timeline";
import { isAbortError, useLoading } from "../loading";

type Props = ComponentProps<typeof PointsEditor> & {
  page: Exclude<Page, "simulation">;
  area: Area;
  workspace: ScenarioWorkspace;
  runs: Run[];
  runId?: string;
  notice?: string;
  placing: boolean;
  showPointsKey: number;
  onPlace: (position: [number, number]) => void;
  onCancelPlacement: () => void;
  onSource: (id?: string) => void;
  onSimulation: () => void;
  stationCatalog?: FeatureCollection & { metadata?: Record<string, unknown> };
  importingStations: boolean;
  onImportStations: (ids: string[]) => void;
  onClosures: (closures: RoadClosure[]) => void;
  onTeams: (teams: ResponseTeam[]) => void;
  onResourceGroups: (groups: ScenarioResourceGroup[]) => void;
  onContainmentTasks: (tasks: ContainmentTask[]) => void;
  onAllocationPlans: (plans: AllocationPlan[]) => void;
};

export function OperationsPage(props: Props) {
  const { begin } = useLoading();
  const water = props.page === "water-planning";
  const source = props.runs.find(
    (run) =>
      run.id === props.runId && ["ready", "partial"].includes(run.status),
  );
  const [members, setMembers] = useState<Run[]>([]);
  const [memberId, setMemberId] = useState("");
  const [roads, setRoads] = useState<FeatureCollection>();
  const [fire, setFire] = useState<FeatureCollection>();
  const [fireMinute, setFireMinute] = useState<number>();
  const [minute, setMinute] = useState(0);
  const [forecast, setForecast] = useState(30);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showFire, setShowFire] = useState(true);
  const [showRoads, setShowRoads] = useState(true);
  const [originId, setOriginId] = useState("");
  const [destinationId, setDestinationId] = useState("");
  const [withdrawalId, setWithdrawalId] = useState("");
  const [onScene, setOnScene] = useState(30);
  const [includeWithdrawal, setIncludeWithdrawal] = useState(true);
  const [routeAnalysis, setRouteAnalysis] = useState<RouteAnalysis>();
  const [routeLoading, setRouteLoading] = useState(false);
  const [selectedRoad, setSelectedRoad] = useState<GeoJSON.Feature>();
  const [retryKey, setRetryKey] = useState(0);
  const [drawingLine, setDrawingLine] = useState(false);
  const [lineCoordinates, setLineCoordinates] = useState<[number, number][]>(
    [],
  );
  const [leadTime, setLeadTime] = useState(10);
  const [standoff, setStandoff] = useState(120);
  const [allocationLoading, setAllocationLoading] = useState(false);
  const [rankedPlans, setRankedPlans] = useState<RankedAllocationPlan[]>([]);
  const [allocationBatch, setAllocationBatch] = useState<Run>();
  const [allocationComparison, setAllocationComparison] =
    useState<AllocationComparison>();
  const [selectedInterventionRunId, setSelectedInterventionRunId] =
    useState("");
  const [interventionFire, setInterventionFire] = useState<FeatureCollection>();
  const [teamSeed, setTeamSeed] = useState<ScenarioResourceGroup>();
  const [seedTeam, setSeedTeam] = useState({
    name: "",
    base_point_id: "",
    available_from_min: 0,
    line_rate_m_min: 5,
    max_deployment_min: 240,
    status: "available" as ResponseTeam["status"],
  });
  const playbackMinute = useRef(false);
  const active =
    source?.mode === "engine_comparison"
      ? members.find((run) => run.id === memberId)
      : source;
  const duration = source?.scenario.duration_min || 0;

  useEffect(() => {
    const controller = new AbortController();
    setMembers([]);
    setMemberId("");
    setRoads(undefined);
    setFire(undefined);
    setFireMinute(undefined);
    setMinute(0);
    setError("");
    setSelectedInterventionRunId("");
    setInterventionFire(undefined);
    if (source?.mode === "engine_comparison") {
      const finish = begin("Loading comparison results…");
      api
        .children(source.id, controller.signal)
        .then((children) => {
          if (controller.signal.aborted) return;
          const ready = children.filter((run) => run.status === "ready");
          setMembers(ready);
          setMemberId(ready[0]?.id || "");
          if (!ready.length)
            setError("No completed engine result is available.");
        })
        .catch((error) => {
          if (!isAbortError(error)) setError(error.message);
        })
        .finally(finish);
    }
    return () => {
      controller.abort();
    };
  }, [source?.id, begin, retryKey]);

  useEffect(() => {
    const controller = new AbortController();
    setRoads(undefined);
    setError("");
    if (active) {
      const finish = begin("Loading road exposure…");
      api
        .roads(active.id, active.scenario.exposure_buffer_m, controller.signal)
        .then((data) => {
          if (!controller.signal.aborted) setRoads(data);
        })
        .catch((error) => {
          if (!isAbortError(error)) setError(error.message);
        })
        .finally(finish);
    }
    return () => {
      controller.abort();
    };
  }, [active?.id, begin, retryKey]);

  useEffect(() => {
    const controller = new AbortController();
    const quiet = playbackMinute.current;
    playbackMinute.current = false;
    if (!quiet) {
      setFire(undefined);
      setLoading(Boolean(active));
    }
    if (active) {
      const finish = quiet ? () => {} : begin("Updating map…");
      api
        .fire(active.id, Math.min(minute, duration), controller.signal)
        .then((data) => {
          if (!controller.signal.aborted) {
            setFire(data);
            setFireMinute(Math.min(minute, duration));
            setLoading(false);
          }
        })
        .catch((error) => {
          if (!isAbortError(error)) {
            setError(error.message);
            setLoading(false);
          }
        })
        .finally(finish);
    }
    return () => {
      controller.abort();
    };
  }, [active?.id, minute, duration, begin, retryKey]);

  useEffect(() => {
    const controller = new AbortController();
    if (!selectedInterventionRunId) {
      setInterventionFire(undefined);
      return () => controller.abort();
    }
    api
      .fire(
        selectedInterventionRunId,
        Math.min(minute, duration),
        controller.signal,
      )
      .then((data) => {
        if (!controller.signal.aborted) setInterventionFire(data);
      })
      .catch((failure) => {
        if (!isAbortError(failure))
          setError(
            failure instanceof Error
              ? failure.message
              : "Unable to load intervention perimeter",
          );
      });
    return () => controller.abort();
  }, [selectedInterventionRunId, minute, duration]);

  useEffect(() => {
    if (
      !allocationBatch ||
      ["ready", "partial", "failed", "cancelled"].includes(
        allocationBatch.status,
      )
    )
      return;
    let stopped = false;
    const poll = async () => {
      try {
        const status = await api.status(allocationBatch.id);
        if (stopped) return;
        setAllocationBatch(status);
        if (["running", "ready", "partial"].includes(status.status)) {
          try {
            setAllocationComparison(await api.allocationComparison(status.id));
          } catch {
            /* children may not exist yet */
          }
        }
      } catch (failure) {
        if (!stopped)
          setError(
            failure instanceof Error
              ? failure.message
              : "Unable to read allocation comparison",
          );
      }
    };
    void poll();
    const timer = window.setInterval(poll, 1200);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [allocationBatch?.id, allocationBatch?.status]);

  const affected = roads?.features.filter(
    (feature) =>
      feature.properties?.coverage !== "unknown" &&
      feature.properties?.first_exposure_min != null &&
      Number(feature.properties.first_exposure_min) <= minute,
  ).length;
  const upcoming = roads?.features.filter(
    (feature) =>
      feature.properties?.coverage !== "unknown" &&
      feature.properties?.first_exposure_min != null &&
      Number(feature.properties.first_exposure_min) > minute &&
      Number(feature.properties.first_exposure_min) <=
        Math.min(duration, minute + forecast),
  ).length;
  const waterPoints = props.workspace.points.filter(
    (point) => point.kind === "water_point",
  );
  const bases = props.workspace.points.filter(
    (point) => point.kind === "response_base",
  );
  const destinations = props.workspace.points.filter(
    (point) =>
      ["response_base", "asset", "hazard", "custom"].includes(point.kind) &&
      !(point.kind === "response_base" && point.id === originId),
  );
  const unusedStations =
    props.stationCatalog?.features.filter(
      (feature) =>
        !props.workspace.points.some(
          (point) =>
            point.source === "openstreetmap" &&
            point.external_id === String(feature.properties?.external_id),
        ),
    ) || [];
  const [west, south, east, north] = props.area.bounds;
  const mapBounds: [[number, number], [number, number]] = [
    [south, west],
    [north, east],
  ];

  useEffect(() => {
    if (!bases.some((point) => point.id === originId))
      setOriginId(bases[0]?.id || "");
    if (!bases.some((point) => point.id === withdrawalId))
      setWithdrawalId(bases[0]?.id || "");
    if (!destinations.some((point) => point.id === destinationId))
      setDestinationId(destinations[0]?.id || "");
  }, [props.workspace.points, originId]);

  function location(id: string): RouteLocation | undefined {
    const point = props.workspace.points.find((value) => value.id === id);
    return point && { name: point.name, coordinates: point.coordinates };
  }

  async function calculateRoutes() {
    const origin = location(originId);
    const destination = location(destinationId);
    if (!active || !origin || !destination) return;
    const finish = begin("Comparing routes…");
    setRouteLoading(true);
    setError("");
    setRouteAnalysis(undefined);
    try {
      setRouteAnalysis(
        await api.routes(active.id, {
          origin,
          destination,
          departure_min: minute,
          on_scene_min: onScene,
          withdrawal_destination: includeWithdrawal
            ? location(withdrawalId)
            : undefined,
          closures: props.workspace.closures,
          alternatives: 2,
          exposure_buffer_m: active.scenario.exposure_buffer_m,
          simulation_horizon_min: active.scenario.duration_min,
        }),
      );
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "Route analysis failed",
      );
    } finally {
      setRouteLoading(false);
      finish();
    }
  }

  function updateMap(action: () => void) {
    const finish = begin("Updating map…");
    requestAnimationFrame(() => {
      action();
      finish();
    });
  }

  function updateMinute(value: number, source: TimelineChangeSource) {
    if (source === "playback") {
      playbackMinute.current = true;
      setMinute(value);
    } else updateMap(() => setMinute(value));
  }

  function addClosure() {
    const properties = selectedRoad?.properties;
    if (!selectedRoad?.geometry || !properties?.segment_id) return;
    props.onClosures([
      ...props.workspace.closures,
      {
        id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
        segment_id: String(properties.segment_id),
        road_name: String(properties.name || "Unnamed road"),
        reason: "Reported closure",
        source: "Scenario report",
        direction: "both",
        starts_min: minute,
        ends_min: null,
        geometry: selectedRoad.geometry,
      },
    ]);
    setSelectedRoad(undefined);
    setRouteAnalysis(undefined);
  }

  function addTeam() {
    if (!bases[0]) {
      setError("Add a response base before creating a team.");
      return;
    }
    props.onTeams([
      ...props.workspace.teams,
      {
        id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
        name: `Team ${props.workspace.teams.length + 1}`,
        base_point_id: bases[0].id,
        available_from_min: 0,
        line_rate_m_min: 5,
        max_deployment_min: 240,
        status: "available",
      },
    ]);
  }

  function beginTeamFromOperacionais(group: ScenarioResourceGroup) {
    const number =
      props.workspace.teams.filter(
        (team) => team.source_provenance?.resource_group_id === group.id,
      ).length + 1;
    setTeamSeed(group);
    setSeedTeam({
      name: `${group.name} ${number}`,
      base_point_id: bases[0]?.id || "",
      available_from_min: 0,
      line_rate_m_min: 5,
      max_deployment_min: 240,
      status: "available",
    });
  }

  function createTeamFromOperacionais() {
    if (
      !teamSeed ||
      !seedTeam.base_point_id ||
      !seedTeam.name.trim() ||
      seedTeam.line_rate_m_min <= 0 ||
      seedTeam.max_deployment_min <= 0
    )
      return;
    props.onTeams([
      ...props.workspace.teams,
      {
        id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
        ...seedTeam,
        name: seedTeam.name.trim(),
        source_provenance: {
          provider: teamSeed.provider,
          incident_id: teamSeed.incident_id,
          resource_group_id: teamSeed.id,
          category: "operacionais",
          snapshot_id: teamSeed.snapshot_id,
          reported_count: teamSeed.reported_count,
          planned_count:
            teamSeed.planned_count_override ?? teamSeed.reported_count,
          converted_at: new Date().toISOString(),
        },
      },
    ]);
    setTeamSeed(undefined);
  }

  async function suggestContainment() {
    if (!active) return;
    const finish = begin("Suggesting containment lines…");
    setAllocationLoading(true);
    setError("");
    try {
      const result = await api.containmentSuggestions(
        props.workspace.id,
        active.id,
        standoff,
      );
      const existing = new Set(
        props.workspace.containment_tasks.map((task) =>
          task.protected_asset_ids.join("/"),
        ),
      );
      props.onContainmentTasks([
        ...props.workspace.containment_tasks,
        ...result.tasks.filter(
          (task) => !existing.has(task.protected_asset_ids.join("/")),
        ),
      ]);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Unable to suggest containment lines",
      );
    } finally {
      setAllocationLoading(false);
      finish();
    }
  }

  function finishContainmentLine() {
    if (lineCoordinates.length < 3) {
      setError("Add at least three points before closing the line.");
      return;
    }
    const closed = [...lineCoordinates, lineCoordinates[0]];
    props.onContainmentTasks([
      ...props.workspace.containment_tasks,
      {
        id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
        name: `Manual line ${props.workspace.containment_tasks.length + 1}`,
        geometry: { type: "LineString", coordinates: closed },
        protected_asset_ids: [],
        source: "manual",
        enabled: true,
      },
    ]);
    setLineCoordinates([]);
    setDrawingLine(false);
  }

  async function rankAllocations(useSaved = false) {
    if (!active) return;
    const finish = begin("Ranking team allocations…");
    setAllocationLoading(true);
    setError("");
    try {
      const result = await api.rankAllocations(
        props.workspace.id,
        active.id,
        minute,
        leadTime,
        useSaved ? props.workspace.allocation_plans : undefined,
      );
      setRankedPlans(result.plans);
      if (!useSaved)
        props.onAllocationPlans(
          result.plans.map((plan) => ({
            id: plan.id,
            name: plan.name,
            assignments: plan.assignments.map((assignment) => ({
              task_id: assignment.task_id,
              team_ids: assignment.team_ids,
            })),
          })),
        );
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Unable to rank allocations",
      );
    } finally {
      setAllocationLoading(false);
      finish();
    }
  }

  function updatePlanTeams(planId: string, taskId: string, teamIds: string[]) {
    props.onAllocationPlans(
      props.workspace.allocation_plans.map((plan) => {
        if (plan.id !== planId) return plan;
        const assignments = plan.assignments.filter(
          (assignment) =>
            assignment.task_id !== taskId &&
            !assignment.team_ids.some((id) => teamIds.includes(id)),
        );
        return {
          ...plan,
          assignments: teamIds.length
            ? [...assignments, { task_id: taskId, team_ids: teamIds }]
            : assignments,
        };
      }),
    );
    setRankedPlans([]);
  }

  async function runAdvancedComparison() {
    if (!active || !props.workspace.allocation_plans.length) return;
    const finish = begin("Queueing intervention simulations…");
    setAllocationLoading(true);
    setError("");
    try {
      const batch = await api.compareAllocations(
        props.workspace.id,
        active.id,
        props.workspace.allocation_plans.slice(0, 4).map((plan) => plan.id),
        minute,
        leadTime,
      );
      setAllocationBatch(batch);
      setAllocationComparison(undefined);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Unable to queue advanced comparison",
      );
    } finally {
      setAllocationLoading(false);
      finish();
    }
  }

  const allocationRouteFeatures =
    rankedPlans[0]?.assignments.flatMap((assignment) =>
      assignment.routes.flatMap((route) => [
        {
          ...route.outbound.feature,
          properties: {
            ...route.outbound.feature.properties,
            label: `${route.team_name} access`,
            allocation: true,
          },
        },
        {
          ...route.withdrawal.feature,
          properties: {
            ...route.withdrawal.feature.properties,
            label: `${route.team_name} withdrawal`,
            allocation: true,
          },
        },
      ]),
    ) || [];
  const routeAnalysisFeatures = routeAnalysis
    ? [
        ...routeAnalysis.routes.map((route) => route.feature),
        ...(routeAnalysis.withdrawal && "feature" in routeAnalysis.withdrawal
          ? [routeAnalysis.withdrawal.feature]
          : []),
      ]
    : [];
  const routeFeatures: FeatureCollection | undefined =
    routeAnalysisFeatures.length || allocationRouteFeatures.length
      ? {
          type: "FeatureCollection",
          features: [...routeAnalysisFeatures, ...allocationRouteFeatures],
        }
      : undefined;
  const containmentFeatures: FeatureCollection = {
    type: "FeatureCollection",
    features: props.workspace.containment_tasks.map((task) => ({
      type: "Feature",
      properties: {
        id: task.id,
        name: task.name,
        source: task.source,
        enabled: task.enabled,
      },
      geometry: task.geometry,
    })),
  };

  return (
    <main
      className={`workspace-page operations-page ${water ? "water-tool" : "decision-tool"}`}
    >
      <Box className="control-column">
        <Card
          as="aside"
          density="compact"
          shadow="none"
          className="panel controls"
          aria-label={
            water ? "Water routing controls" : "Decision support controls"
          }
        >
          <Box className="tool-intro">
            <Typography as="span" variant="label" className="eyebrow">
              Operational tool
            </Typography>
            <Typography as="h1" variant="h1">
              {water ? "Water Routing" : "Decision Support"}
            </Typography>
            <Typography as="p" variant="body">
              {water
                ? "Prepare water sources and response bases against a simulated fire."
                : "Review modelled road exposure alongside priority assets and local constraints."}
            </Typography>
          </Box>
          <Card
            as="section"
            density="compact"
            shadow="none"
            className="source-card"
          >
            <Typography as="span" variant="label" className="eyebrow">
              Input from Simulation
            </Typography>
            <label>
              Simulation result
              <select
                value={source?.id || ""}
                onChange={(event) =>
                  props.onSource(event.target.value || undefined)
                }
              >
                <option value="">Select a completed simulation</option>
                {props.runs
                  .filter(
                    (run) =>
                      ["ready", "partial"].includes(run.status) &&
                      run.mode !== "allocation_comparison",
                  )
                  .map((run) => (
                    <option key={run.id} value={run.id}>
                      {resultLabel(run)}
                    </option>
                  ))}
              </select>
            </label>
            {source ? (
              <>
                <Typography as="p" variant="body">
                  {source.scenario.engine} · {source.scenario.duration_min} min
                  · {source.status}
                </Typography>
                <Typography as="small" variant="small">
                  Run {source.id} · revision {source.scenario_revision ?? "—"}
                </Typography>
                <Typography as="p" variant="body">
                  This input stays selected when new simulations finish.
                </Typography>
              </>
            ) : (
              <Typography as="p" variant="body">
                Select a result to load fire and road exposure. You can prepare
                points before a simulation is available.
              </Typography>
            )}
            {source?.mode === "engine_comparison" && (
              <label>
                Engine result
                <select
                  value={memberId}
                  onChange={(event) => setMemberId(event.target.value)}
                >
                  {members.map((member) => (
                    <option key={member.id} value={member.id}>
                      {member.scenario.engine}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <Button variant="ghost" onClick={props.onSimulation}>
              Open technical simulation →
            </Button>
          </Card>
          <section className="analysis-summary">
            <Typography as="h2" variant="h3">
              {water ? "Source inventory" : `Exposure at ${minute} min`}
            </Typography>
            <Box className="context-grid">
              {water ? (
                <>
                  <Stat label="Water points" value={waterPoints.length} />
                  <Stat
                    label="Response bases"
                    value={
                      props.points.filter(
                        (point) => point.kind === "response_base",
                      ).length
                    }
                  />
                  <Stat
                    label="Availability unknown"
                    value={
                      waterPoints.filter(
                        (point) =>
                          !point.water ||
                          point.water.availability === "unknown",
                      ).length
                    }
                  />
                  <Stat
                    label="Verified"
                    value={
                      waterPoints.filter(
                        (point) =>
                          point.water?.verification_status === "verified",
                      ).length
                    }
                  />
                </>
              ) : (
                <>
                  <Stat label="Affected roads" value={affected} />
                  <Stat label="Within forecast" value={upcoming} />
                  <Stat
                    label="Priority assets"
                    value={
                      props.points.filter((point) => point.kind === "asset")
                        .length
                    }
                  />
                  <Stat
                    label="Hazards"
                    value={
                      props.points.filter((point) => point.kind === "hazard")
                        .length
                    }
                  />
                </>
              )}
            </Box>
            <Typography as="p" variant="small" className="empty-note">
              {water
                ? "Route calculation and turnaround estimates are not implemented yet. This workspace prepares their inputs."
                : "Routes compare selected scenario assumptions; they are not deployment recommendations."}
            </Typography>
          </section>
          {props.notice && (
            <Typography
              as="p"
              variant="small"
              className="operation-notice"
              role="status"
            >
              {props.notice}
            </Typography>
          )}
          {!water && (
            <>
              {props.workspace.resource_groups.length > 0 && (
                <section className="control-section fogos-resource-section">
                  <Box className="section-heading">
                    <Box>
                      <Typography as="span" variant="label" className="eyebrow">
                        Source: Fogos.pt
                      </Typography>
                      <Typography as="h2" variant="h3">
                        Mobilized resource context
                      </Typography>
                    </Box>
                  </Box>
                  <Typography as="p" variant="small" className="empty-note">
                    Reported totals are planning context, not confirmed on-scene
                    units. Planned quantities are local and are never written
                    back to Fogos.pt.
                  </Typography>
                  <Box className="fogos-resource-groups">
                    {props.workspace.resource_groups.map((group) => (
                      <ResourceGroupEditor
                        key={group.id}
                        group={group}
                        onChange={(updated) =>
                          props.onResourceGroups(
                            props.workspace.resource_groups.map((value) =>
                              value.id === updated.id ? updated : value,
                            ),
                          )
                        }
                        onCreateTeam={
                          group.category === "operacionais"
                            ? () => beginTeamFromOperacionais(group)
                            : undefined
                        }
                      />
                    ))}
                  </Box>
                  {teamSeed && (
                    <Card
                      density="compact"
                      shadow="none"
                      className="allocation-card team-conversion-form"
                    >
                      <Box className="allocation-heading">
                        <strong>
                          Create a planning team from {teamSeed.name}
                        </strong>
                        <Button
                          variant="secondary"
                          onClick={() => setTeamSeed(undefined)}
                        >
                          Cancel
                        </Button>
                      </Box>
                      {!bases.length && (
                        <Typography
                          role="alert"
                          as="p"
                          variant="small"
                          className="management-error"
                        >
                          Add or import a response base before creating this
                          team.
                        </Typography>
                      )}
                      <label>
                        Team name
                        <input
                          value={seedTeam.name}
                          onChange={(event) =>
                            setSeedTeam((value) => ({
                              ...value,
                              name: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <label>
                        Response base
                        <select
                          value={seedTeam.base_point_id}
                          onChange={(event) =>
                            setSeedTeam((value) => ({
                              ...value,
                              base_point_id: event.target.value,
                            }))
                          }
                        >
                          <option value="">Select a response base</option>
                          {bases.map((base) => (
                            <option key={base.id} value={base.id}>
                              {base.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <Box className="two-col">
                        <label>
                          Availability time (min)
                          <input
                            type="number"
                            min="0"
                            max="720"
                            value={seedTeam.available_from_min}
                            onChange={(event) =>
                              setSeedTeam((value) => ({
                                ...value,
                                available_from_min: Number(event.target.value),
                              }))
                            }
                          />
                        </label>
                        <label>
                          Line-production rate (m/min)
                          <input
                            type="number"
                            min="0.1"
                            max="100"
                            step="0.1"
                            value={seedTeam.line_rate_m_min}
                            onChange={(event) =>
                              setSeedTeam((value) => ({
                                ...value,
                                line_rate_m_min: Number(event.target.value),
                              }))
                            }
                          />
                        </label>
                      </Box>
                      <Box className="two-col">
                        <label>
                          Deployment limit (min)
                          <input
                            type="number"
                            min="1"
                            max="1440"
                            value={seedTeam.max_deployment_min}
                            onChange={(event) =>
                              setSeedTeam((value) => ({
                                ...value,
                                max_deployment_min: Number(event.target.value),
                              }))
                            }
                          />
                        </label>
                        <label>
                          Status
                          <select
                            value={seedTeam.status}
                            onChange={(event) =>
                              setSeedTeam((value) => ({
                                ...value,
                                status: event.target
                                  .value as ResponseTeam["status"],
                              }))
                            }
                          >
                            <option value="available">Available</option>
                            <option value="unavailable">Unavailable</option>
                          </select>
                        </label>
                      </Box>
                      <Button
                        variant="secondary"
                        className="ds-full"
                        disabled={
                          !bases.length ||
                          !seedTeam.base_point_id ||
                          !seedTeam.name.trim() ||
                          seedTeam.line_rate_m_min <= 0 ||
                          seedTeam.max_deployment_min <= 0
                        }
                        onClick={createTeamFromOperacionais}
                      >
                        Confirm and create team
                      </Button>
                      <Typography as="small" variant="small">
                        Fogos.pt source details and current counts are copied
                        into immutable team provenance. Later synchronization
                        will not alter this team.
                      </Typography>
                    </Card>
                  )}
                </section>
              )}
              <section className="control-section station-inventory">
                <Typography as="h2" variant="h3">
                  Fire stations
                </Typography>
                <Typography as="p" variant="small" className="empty-note">
                  {props.stationCatalog?.metadata?.coverage
                    ? String(props.stationCatalog.metadata.coverage)
                    : "Station catalog is unavailable. Manual response bases still work."}
                </Typography>
                <Card density="compact" shadow="none" className="inventory-row">
                  <span>
                    {bases.length} bases in scenario · {unusedStations.length}{" "}
                    catalog records available
                  </span>
                  {unusedStations.length > 0 && (
                    <Button
                      variant="secondary"
                      onClick={() =>
                        props.onImportStations(
                          unusedStations.map((feature) =>
                            String(feature.properties?.external_id),
                          ),
                        )
                      }
                      disabled={props.importingStations}
                    >
                      {props.importingStations
                        ? "Importing…"
                        : "Import all stations"}
                    </Button>
                  )}
                </Card>
              </section>
              <section className="control-section route-planner">
                <Typography as="h2" variant="h3">
                  Access and withdrawal
                </Typography>
                <label>
                  Departure base
                  <select
                    value={originId}
                    onChange={(event) => setOriginId(event.target.value)}
                  >
                    <option value="">Select a response base</option>
                    {bases.map((point) => (
                      <option key={point.id} value={point.id}>
                        {point.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Incident access or staging point
                  <select
                    value={destinationId}
                    onChange={(event) => setDestinationId(event.target.value)}
                  >
                    <option value="">Select a mapped point</option>
                    {destinations.map((point) => (
                      <option key={point.id} value={point.id}>
                        {point.name}
                      </option>
                    ))}
                  </select>
                </label>
                <Box className="two-col">
                  <label>
                    Depart at
                    <input
                      type="number"
                      min="0"
                      max={duration}
                      value={minute}
                      onChange={(event) =>
                        setMinute(
                          Math.max(
                            0,
                            Math.min(duration, Number(event.target.value)),
                          ),
                        )
                      }
                    />
                  </label>
                  <label>
                    Time on scene
                    <input
                      type="number"
                      min="0"
                      max="720"
                      value={onScene}
                      onChange={(event) =>
                        setOnScene(Math.max(0, Number(event.target.value)))
                      }
                    />
                  </label>
                </Box>
                <label className="radio">
                  <input
                    type="checkbox"
                    checked={includeWithdrawal}
                    onChange={(event) =>
                      setIncludeWithdrawal(event.target.checked)
                    }
                  />
                  Analyse withdrawal route
                </label>
                {includeWithdrawal && (
                  <label>
                    Withdraw to
                    <select
                      value={withdrawalId}
                      onChange={(event) => setWithdrawalId(event.target.value)}
                    >
                      <option value="">Select a response base</option>
                      {bases.map((point) => (
                        <option key={point.id} value={point.id}>
                          {point.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <Button
                  variant="secondary"
                  className="ds-full"
                  disabled={
                    !active || !originId || !destinationId || routeLoading
                  }
                  onClick={calculateRoutes}
                >
                  {routeLoading ? "Comparing routes…" : "Compare routes"}
                </Button>
                {!active && (
                  <Typography as="p" variant="small" className="empty-note">
                    Select a completed simulation before comparing routes.
                  </Typography>
                )}
                {active && !bases.length && (
                  <Typography as="p" variant="small" className="empty-note">
                    Import or place a response base to begin routing.
                  </Typography>
                )}
                {active && !destinations.length && (
                  <Typography as="p" variant="small" className="empty-note">
                    Place another response base, priority asset, hazard, or
                    custom point at the intended incident access or staging
                    location.
                  </Typography>
                )}
              </section>
              <section className="control-section allocation-planner">
                <Typography as="h2" variant="h3">
                  Team allocation
                </Typography>
                <Typography as="p" variant="small" className="empty-note">
                  Rank logistics immediately, then optionally test how completed
                  containment lines change the simulated fire.
                </Typography>
                <Box className="allocation-heading">
                  <strong>Teams</strong>
                  <Button variant="secondary" onClick={addTeam}>
                    Add team
                  </Button>
                </Box>
                {props.workspace.teams.length === 0 && (
                  <Typography as="p" variant="small" className="empty-note">
                    Add a response base and at least one team.
                  </Typography>
                )}
                {props.workspace.teams.map((team) => (
                  <Card
                    density="compact"
                    shadow="none"
                    className="allocation-card"
                    key={team.id}
                  >
                    <label>
                      Name
                      <input
                        value={team.name}
                        onChange={(event) =>
                          props.onTeams(
                            props.workspace.teams.map((value) =>
                              value.id === team.id
                                ? { ...value, name: event.target.value }
                                : value,
                            ),
                          )
                        }
                      />
                    </label>
                    <label>
                      Response base
                      <select
                        value={team.base_point_id}
                        onChange={(event) =>
                          props.onTeams(
                            props.workspace.teams.map((value) =>
                              value.id === team.id
                                ? {
                                    ...value,
                                    base_point_id: event.target.value,
                                  }
                                : value,
                            ),
                          )
                        }
                      >
                        {bases.map((base) => (
                          <option key={base.id} value={base.id}>
                            {base.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <Box className="two-col">
                      <label>
                        Available at
                        <input
                          type="number"
                          min="0"
                          max="720"
                          value={team.available_from_min}
                          onChange={(event) =>
                            props.onTeams(
                              props.workspace.teams.map((value) =>
                                value.id === team.id
                                  ? {
                                      ...value,
                                      available_from_min: Number(
                                        event.target.value,
                                      ),
                                    }
                                  : value,
                              ),
                            )
                          }
                        />
                      </label>
                      <label>
                        Line rate m/min
                        <input
                          type="number"
                          min="0.1"
                          step="0.1"
                          value={team.line_rate_m_min}
                          onChange={(event) =>
                            props.onTeams(
                              props.workspace.teams.map((value) =>
                                value.id === team.id
                                  ? {
                                      ...value,
                                      line_rate_m_min: Number(
                                        event.target.value,
                                      ),
                                    }
                                  : value,
                              ),
                            )
                          }
                        />
                      </label>
                    </Box>
                    <Box className="two-col">
                      <label>
                        Max deployment
                        <input
                          type="number"
                          min="1"
                          value={team.max_deployment_min}
                          onChange={(event) =>
                            props.onTeams(
                              props.workspace.teams.map((value) =>
                                value.id === team.id
                                  ? {
                                      ...value,
                                      max_deployment_min: Number(
                                        event.target.value,
                                      ),
                                    }
                                  : value,
                              ),
                            )
                          }
                        />
                      </label>
                      <label>
                        Status
                        <select
                          value={team.status}
                          onChange={(event) =>
                            props.onTeams(
                              props.workspace.teams.map((value) =>
                                value.id === team.id
                                  ? {
                                      ...value,
                                      status: event.target
                                        .value as ResponseTeam["status"],
                                    }
                                  : value,
                              ),
                            )
                          }
                        >
                          <option value="available">Available</option>
                          <option value="unavailable">Unavailable</option>
                        </select>
                      </label>
                    </Box>
                    {team.source_provenance && (
                      <Typography as="small" variant="small">
                        Created from Fogos.pt {team.source_provenance.category}{" "}
                        · reported{" "}
                        {team.source_provenance.reported_count ?? "unavailable"}{" "}
                        · planned{" "}
                        {team.source_provenance.planned_count ?? "unavailable"}{" "}
                        · detached snapshot {team.source_provenance.snapshot_id}
                      </Typography>
                    )}
                    <Button
                      variant="outline"
                      intent="danger"
                      onClick={() => {
                        props.onTeams(
                          props.workspace.teams.filter(
                            (value) => value.id !== team.id,
                          ),
                        );
                        props.onAllocationPlans(
                          props.workspace.allocation_plans.map((plan) => ({
                            ...plan,
                            assignments: plan.assignments
                              .map((assignment) => ({
                                ...assignment,
                                team_ids: assignment.team_ids.filter(
                                  (id) => id !== team.id,
                                ),
                              }))
                              .filter(
                                (assignment) => assignment.team_ids.length,
                              ),
                          })),
                        );
                      }}
                    >
                      Remove team
                    </Button>
                  </Card>
                ))}
                <Box className="allocation-heading">
                  <strong>Containment tasks</strong>
                  <span>{props.workspace.containment_tasks.length}</span>
                </Box>
                <Box className="two-col">
                  <label>
                    Suggested standoff
                    <input
                      type="number"
                      min="30"
                      max="1000"
                      value={standoff}
                      onChange={(event) =>
                        setStandoff(Number(event.target.value))
                      }
                    />
                  </label>
                  <label>
                    Lead time
                    <input
                      type="number"
                      min="0"
                      max="120"
                      value={leadTime}
                      onChange={(event) =>
                        setLeadTime(Number(event.target.value))
                      }
                    />
                  </label>
                </Box>
                <Box className="allocation-actions">
                  <Button
                    variant="secondary"
                    disabled={!active || allocationLoading}
                    onClick={suggestContainment}
                  >
                    Suggest lines
                  </Button>
                  <Button
                    variant="secondary"
                    aria-pressed={drawingLine}
                    className={drawingLine ? "active" : ""}
                    onClick={() => {
                      setDrawingLine((value) => !value);
                      setLineCoordinates([]);
                    }}
                  >
                    {drawingLine ? "Cancel drawing" : "Draw line"}
                  </Button>
                </Box>
                {drawingLine && (
                  <Box className="drawing-tools">
                    <span>{lineCoordinates.length} points</span>
                    <Button
                      variant="secondary"
                      disabled={lineCoordinates.length < 3}
                      onClick={finishContainmentLine}
                    >
                      Close and save
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={!lineCoordinates.length}
                      onClick={() =>
                        setLineCoordinates((value) => value.slice(0, -1))
                      }
                    >
                      Undo point
                    </Button>
                  </Box>
                )}
                {props.workspace.containment_tasks.map((task) => (
                  <Card
                    density="compact"
                    shadow="none"
                    className="allocation-card"
                    key={task.id}
                  >
                    <label>
                      Name
                      <input
                        value={task.name}
                        onChange={(event) =>
                          props.onContainmentTasks(
                            props.workspace.containment_tasks.map((value) =>
                              value.id === task.id
                                ? { ...value, name: event.target.value }
                                : value,
                            ),
                          )
                        }
                      />
                    </label>
                    <label className="radio">
                      <input
                        type="checkbox"
                        checked={task.enabled}
                        onChange={(event) =>
                          props.onContainmentTasks(
                            props.workspace.containment_tasks.map((value) =>
                              value.id === task.id
                                ? { ...value, enabled: event.target.checked }
                                : value,
                            ),
                          )
                        }
                      />
                      Enabled · {task.source}
                    </label>
                    <span className="field-label">Protected assets</span>
                    {props.workspace.points
                      .filter((point) => point.kind === "asset")
                      .map((asset) => (
                        <label className="radio" key={asset.id}>
                          <input
                            type="checkbox"
                            checked={task.protected_asset_ids.includes(
                              asset.id,
                            )}
                            onChange={(event) =>
                              props.onContainmentTasks(
                                props.workspace.containment_tasks.map(
                                  (value) =>
                                    value.id === task.id
                                      ? {
                                          ...value,
                                          protected_asset_ids: event.target
                                            .checked
                                            ? [
                                                ...value.protected_asset_ids,
                                                asset.id,
                                              ]
                                            : value.protected_asset_ids.filter(
                                                (id) => id !== asset.id,
                                              ),
                                        }
                                      : value,
                                ),
                              )
                            }
                          />
                          {asset.name} · priority {asset.asset?.priority || 3}
                        </label>
                      ))}
                    <Button
                      variant="outline"
                      intent="danger"
                      onClick={() => {
                        props.onContainmentTasks(
                          props.workspace.containment_tasks.filter(
                            (value) => value.id !== task.id,
                          ),
                        );
                        props.onAllocationPlans(
                          props.workspace.allocation_plans.map((plan) => ({
                            ...plan,
                            assignments: plan.assignments.filter(
                              (assignment) => assignment.task_id !== task.id,
                            ),
                          })),
                        );
                      }}
                    >
                      Remove line
                    </Button>
                  </Card>
                ))}
                <Box className="allocation-actions">
                  <Button
                    variant="secondary"
                    className="ds-full"
                    disabled={
                      !active ||
                      !props.workspace.teams.length ||
                      !props.workspace.containment_tasks.length ||
                      allocationLoading
                    }
                    onClick={() => void rankAllocations(false)}
                  >
                    {allocationLoading ? "Calculating…" : "Generate four plans"}
                  </Button>
                  {props.workspace.allocation_plans.length > 0 && (
                    <Button
                      variant="secondary"
                      disabled={allocationLoading}
                      onClick={() => void rankAllocations(true)}
                    >
                      Rescore saved plans
                    </Button>
                  )}
                </Box>
                {props.workspace.allocation_plans.map((plan, index) => (
                  <Card
                    density="compact"
                    shadow="none"
                    className="allocation-card plan-editor"
                    key={plan.id}
                  >
                    <label>
                      Plan name
                      <input
                        value={plan.name}
                        onChange={(event) =>
                          props.onAllocationPlans(
                            props.workspace.allocation_plans.map((value) =>
                              value.id === plan.id
                                ? { ...value, name: event.target.value }
                                : value,
                            ),
                          )
                        }
                      />
                    </label>
                    {props.workspace.containment_tasks
                      .filter((task) => task.enabled)
                      .map((task) => (
                        <label key={task.id}>
                          {task.name}
                          <select
                            multiple
                            value={
                              plan.assignments.find(
                                (value) => value.task_id === task.id,
                              )?.team_ids || []
                            }
                            onChange={(event) =>
                              updatePlanTeams(
                                plan.id,
                                task.id,
                                Array.from(
                                  event.target.selectedOptions,
                                  (option) => option.value,
                                ),
                              )
                            }
                          >
                            {props.workspace.teams
                              .filter((team) => team.status === "available")
                              .map((team) => (
                                <option key={team.id} value={team.id}>
                                  {team.name}
                                </option>
                              ))}
                          </select>
                        </label>
                      ))}
                    {rankedPlans[index] && (
                      <Typography as="p" variant="body" className="plan-score">
                        {rankedPlans[index].feasible_tasks} feasible ·{" "}
                        {Math.round(rankedPlans[index].total_effort_min)}{" "}
                        team-minutes
                        {rankedPlans[index].worst_margin_min != null
                          ? ` · ${Math.round(rankedPlans[index].worst_margin_min)} min worst margin`
                          : ""}
                      </Typography>
                    )}
                  </Card>
                ))}
                {rankedPlans.length > 0 && (
                  <Typography
                    as="small"
                    variant="small"
                    className="route-assumption"
                  >
                    Logistics ranking only. It does not estimate changes to fire
                    spread.
                  </Typography>
                )}
                <Button
                  variant="secondary"
                  className="ds-full"
                  disabled={
                    !active ||
                    active.mode !== "single" ||
                    !["mtt", "cell2fire"].includes(active.scenario.engine) ||
                    !props.workspace.allocation_plans.length ||
                    allocationLoading
                  }
                  onClick={runAdvancedComparison}
                >
                  Run advanced comparison
                </Button>
                {active &&
                  (active.mode !== "single" ||
                    !["mtt", "cell2fire"].includes(active.scenario.engine)) && (
                    <Typography as="p" variant="small" className="empty-note">
                      Choose a completed deterministic MTT or Cell2Fire result
                      for the advanced comparison.
                    </Typography>
                  )}
                {allocationBatch && (
                  <Card
                    density="compact"
                    shadow="none"
                    className="allocation-progress"
                  >
                    <strong>{allocationBatch.stage}</strong>
                    <span>{allocationBatch.progress}%</span>
                    {!["ready", "partial", "failed", "cancelled"].includes(
                      allocationBatch.status,
                    ) && (
                      <Button
                        variant="secondary"
                        onClick={() =>
                          void api
                            .cancel(allocationBatch.id)
                            .then(setAllocationBatch)
                        }
                      >
                        Cancel
                      </Button>
                    )}
                  </Card>
                )}
                {allocationComparison?.members.map((member) => {
                  const breached =
                    member.containment.tasks?.reduce(
                      (total, task) => total + task.breached_cells,
                      0,
                    ) || 0;
                  return (
                    <Card
                      as="article"
                      density="compact"
                      shadow="none"
                      className={`route-card ${selectedInterventionRunId === member.run_id ? "selected" : ""}`}
                      key={member.run_id}
                    >
                      <Box>
                        <strong>
                          #{member.rank} {member.plan_name}
                        </strong>
                        <span>{allocationComparison.engine}</span>
                      </Box>
                      <Typography as="p" variant="body">
                        {member.burned_area_ha.toFixed(1)} ha ·{" "}
                        {member.burned_area_change_ha >= 0 ? "+" : ""}
                        {member.burned_area_change_ha.toFixed(1)} ha vs control
                      </Typography>
                      <Typography as="small" variant="small">
                        {member.exposed_roads} exposed roads (
                        {member.road_exposure_change >= 0 ? "+" : ""}
                        {member.road_exposure_change}) · {breached} breached
                        cells
                      </Typography>
                      <Typography as="small" variant="small">
                        Assets reached P5→P1:{" "}
                        {[5, 4, 3, 2, 1]
                          .map(
                            (priority) =>
                              member.reached_by_priority[String(priority)] || 0,
                          )
                          .join(" / ")}
                      </Typography>
                      <Typography as="small" variant="small">
                        {Math.round(member.runtime_seconds)} s simulation ·{" "}
                        {Math.round(member.effort_min)} team-minutes
                      </Typography>
                      <Button
                        variant="secondary"
                        onClick={() =>
                          setSelectedInterventionRunId(member.run_id)
                        }
                      >
                        Show intervention perimeter
                      </Button>
                    </Card>
                  );
                })}
                {selectedInterventionRunId && (
                  <Button
                    variant="ghost"
                    onClick={() => setSelectedInterventionRunId("")}
                  >
                    Show control perimeter
                  </Button>
                )}
                {allocationComparison && (
                  <Typography
                    as="small"
                    variant="small"
                    className="route-assumption"
                  >
                    {allocationComparison.assumption}
                  </Typography>
                )}
              </section>
              <section className="control-section closure-editor">
                <Typography as="h2" variant="h3">
                  Reported closures
                </Typography>
                <Typography as="p" variant="small" className="empty-note">
                  Click a road on the map, then add it as a timed closure. These
                  reports stay separate from modelled fire exposure.
                </Typography>
                {selectedRoad && (
                  <Card
                    density="compact"
                    shadow="none"
                    className="selected-road"
                  >
                    <span>
                      {String(selectedRoad.properties?.name || "Unnamed road")}
                    </span>
                    <Button variant="secondary" onClick={addClosure}>
                      Add closure at {minute} min
                    </Button>
                  </Card>
                )}
                {props.workspace.closures.map((closure) => (
                  <Card
                    density="compact"
                    shadow="none"
                    className="closure-card"
                    key={closure.id}
                  >
                    <strong>{closure.road_name}</strong>
                    <label>
                      Reason
                      <input
                        value={closure.reason}
                        onChange={(event) =>
                          props.onClosures(
                            props.workspace.closures.map((value) =>
                              value.id === closure.id
                                ? { ...value, reason: event.target.value }
                                : value,
                            ),
                          )
                        }
                      />
                    </label>
                    <Box className="two-col">
                      <label>
                        Starts
                        <input
                          type="number"
                          min="0"
                          max="720"
                          value={closure.starts_min}
                          onChange={(event) =>
                            props.onClosures(
                              props.workspace.closures.map((value) =>
                                value.id === closure.id
                                  ? {
                                      ...value,
                                      starts_min: Number(event.target.value),
                                    }
                                  : value,
                              ),
                            )
                          }
                        />
                      </label>
                      <label>
                        Ends
                        <input
                          type="number"
                          min="0"
                          max="720"
                          placeholder="Open-ended"
                          value={closure.ends_min ?? ""}
                          onChange={(event) =>
                            props.onClosures(
                              props.workspace.closures.map((value) =>
                                value.id === closure.id
                                  ? {
                                      ...value,
                                      ends_min:
                                        event.target.value === ""
                                          ? null
                                          : Number(event.target.value),
                                    }
                                  : value,
                              ),
                            )
                          }
                        />
                      </label>
                    </Box>
                    <Box className="two-col">
                      <label>
                        Direction
                        <select
                          value={closure.direction}
                          onChange={(event) =>
                            props.onClosures(
                              props.workspace.closures.map((value) =>
                                value.id === closure.id
                                  ? {
                                      ...value,
                                      direction: event.target
                                        .value as RoadClosure["direction"],
                                    }
                                  : value,
                              ),
                            )
                          }
                        >
                          <option value="both">Both directions</option>
                          <option value="forward">Mapped direction</option>
                          <option value="reverse">Reverse direction</option>
                        </select>
                      </label>
                      <label>
                        Source
                        <input
                          value={closure.source}
                          onChange={(event) =>
                            props.onClosures(
                              props.workspace.closures.map((value) =>
                                value.id === closure.id
                                  ? { ...value, source: event.target.value }
                                  : value,
                              ),
                            )
                          }
                        />
                      </label>
                    </Box>
                    <Button
                      variant="outline"
                      intent="danger"
                      onClick={() =>
                        props.onClosures(
                          props.workspace.closures.filter(
                            (value) => value.id !== closure.id,
                          ),
                        )
                      }
                    >
                      Remove
                    </Button>
                  </Card>
                ))}
              </section>
              {routeAnalysis && <RouteResults analysis={routeAnalysis} />}
            </>
          )}
          <PointsEditor {...props} />
          <section className="control-section">
            <Typography as="h2" variant="h3">
              Map layers
            </Typography>
            <label className="radio">
              <input
                type="checkbox"
                checked={showFire}
                onChange={(event) => {
                  const value = event.target.checked;
                  updateMap(() => setShowFire(value));
                }}
              />
              Simulated fire
            </label>
            <label className="radio">
              <input
                type="checkbox"
                checked={showRoads}
                onChange={(event) => {
                  const value = event.target.checked;
                  updateMap(() => setShowRoads(value));
                }}
              />
              Modelled road exposure
            </label>
          </section>
        </Card>
      </Box>
      <section
        className={props.placing ? "map-shell placing" : "map-shell"}
        aria-label={water ? "Water routing map" : "Decision support map"}
      >
        <MapView
          key={active?.id || "no-source"}
          bounds={mapBounds}
          scenario={active?.scenario || props.workspace.simulation}
          points={props.points}
          showPointsKey={props.showPointsKey}
          roads={roads}
          fire={interventionFire || fire}
          routes={routeFeatures}
          containment={containmentFeatures}
          draftContainment={drawingLine ? lineCoordinates : undefined}
          minute={minute}
          forecast={Math.min(forecast, Math.max(0, duration - minute))}
          filter="all"
          placing={props.placing}
          showFire={showFire}
          showRoads={showRoads}
          showBasemap
          showPoints
          showIgnition={Boolean(active)}
          onIgnition={props.onPlace}
          onPointMove={props.onPointMove}
          onPointDelete={props.onPointDelete}
          onContainmentClick={
            drawingLine
              ? (position) =>
                  setLineCoordinates((value) => [...value, position])
              : undefined
          }
          closedSegmentIds={props.workspace.closures.map(
            (closure) => closure.segment_id,
          )}
          onRoadSelect={(feature) => !water && setSelectedRoad(feature)}
        />
        <Box className="status" role="status">
          {props.placing ? (
            <>
              Click the map to place the point{" "}
              <Button variant="secondary" onClick={props.onCancelPlacement}>
                Cancel
              </Button>
            </>
          ) : error ? (
            <>
              {error}{" "}
              <Button
                variant="secondary"
                onClick={() => {
                  setError("");
                  setRetryKey((value) => value + 1);
                }}
              >
                Try again
              </Button>
            </>
          ) : loading ? (
            "Loading simulation input…"
          ) : source ? (
            `Simulation input · ${active?.scenario.engine || "loading engine"} · ${minute} min`
          ) : (
            "Preparing points · no simulation input selected"
          )}
        </Box>
        {source && (
          <>
            <Card density="compact" shadow="none" className="legend panel">
              <strong>Simulation layers</strong>
              <span>
                <i className="fire-gradient" />
                Simulated fire extent
              </span>
              <span>
                <i className="red" />
                Road reached by selected time
              </span>
              <span>
                <i className="amber forecast-line" />
                Forecast within +{forecast} min
              </span>
              <span>
                <i className="grey" />
                Road not reached in run
              </span>
              {!water && (
                <span>
                  <i className="closure-line" />
                  Reported road closure
                </span>
              )}
              <Typography as="small" variant="small">
                Exposure is not a closure or route-safety determination
              </Typography>
            </Card>
            <Timeline
              minute={minute}
              duration={duration}
              forecast={forecast}
              frameReady={!active || fireMinute === Math.min(minute, duration)}
              pauseSignal={error}
              onMinute={updateMinute}
              onForecast={(value) => updateMap(() => setForecast(value))}
            />
          </>
        )}
      </section>
    </main>
  );
}

export function ResourceGroupEditor({
  group,
  onChange,
  onCreateTeam,
}: {
  group: ScenarioResourceGroup;
  onChange: (group: ScenarioResourceGroup) => void;
  onCreateTeam?: () => void;
}) {
  const planned = group.planned_count_override ?? group.reported_count;
  return (
    <Card
      as="article"
      density="compact"
      shadow="none"
      className="fogos-resource-card"
    >
      <label>
        Nome
        <input
          value={group.name}
          onChange={(event) => onChange({ ...group, name: event.target.value })}
        />
      </label>
      <Box className="resource-counts">
        <span>
          <Typography as="small" variant="small">
            Reportado
          </Typography>
          <strong>{group.reported_count ?? "Indisponível"}</strong>
        </span>
        <span
          className={group.planned_count_override != null ? "overridden" : ""}
        >
          <Typography as="small" variant="small">
            Planeado
          </Typography>
          <strong>{planned ?? "Indisponível"}</strong>
        </span>
      </Box>
      <label>
        Quantidade planeada
        <input
          type="number"
          min="0"
          placeholder={
            group.reported_count == null
              ? "Indisponível"
              : String(group.reported_count)
          }
          value={group.planned_count_override ?? ""}
          onChange={(event) =>
            onChange({
              ...group,
              planned_count_override:
                event.target.value === ""
                  ? null
                  : Math.max(0, Number(event.target.value)),
            })
          }
        />
      </label>
      <Box className="resource-card-actions">
        <Button
          variant="secondary"
          disabled={group.planned_count_override == null}
          onClick={() => onChange({ ...group, planned_count_override: null })}
        >
          Repor valor reportado
        </Button>
        {onCreateTeam && (
          <Button
            variant="secondary"
            className="ds-full"
            onClick={onCreateTeam}
          >
            Criar equipa de planeamento
          </Button>
        )}
      </Box>
      <label>
        Notas
        <textarea
          rows={2}
          value={group.notes}
          onChange={(event) =>
            onChange({ ...group, notes: event.target.value })
          }
        />
      </label>
      <Typography as="small" variant="small">
        Fonte: Fogos.pt · observado em {formatResourceDate(group.observed_at)} ·
        sincronizado em {formatResourceDate(group.synced_at)}
      </Typography>
      {group.planned_count_override != null && (
        <Typography as="small" variant="small" className="override-indicator">
          Alteração local do planeamento ativa
        </Typography>
      )}
    </Card>
  );
}

function formatResourceDate(value?: string | null) {
  if (!value) return "indisponível";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : formatDateTime(date);
}

function RouteResults({ analysis }: { analysis: RouteAnalysis }) {
  return (
    <section className="control-section route-results">
      <Typography as="h2" variant="h3">
        Route comparison
      </Typography>
      {analysis.routes.length === 0 ? (
        <Typography as="p" variant="body" className="route-alert">
          No access route remains under the selected fire and closure
          assumptions.
        </Typography>
      ) : (
        analysis.routes.map((route) => (
          <Card
            as="article"
            density="compact"
            shadow="none"
            className={`route-card ${route.status}`}
            key={route.label}
          >
            <Box>
              <strong>{route.label}</strong>
              <span>
                {route.status === "unknown"
                  ? "Insufficient information"
                  : "No modelled conflict"}
              </span>
            </Box>
            <Typography as="p" variant="body">
              {route.distance_km.toFixed(1)} km ·{" "}
              {Math.round(route.duration_min)} min · arrives{" "}
              {Math.round(route.arrival_min)} min
            </Typography>
            <Typography as="small" variant="small">
              {route.message}
            </Typography>
            {route.closest_fire_margin_min != null && (
              <Typography as="small" variant="small">
                Closest modelled fire margin:{" "}
                {Math.round(route.closest_fire_margin_min)} min
              </Typography>
            )}
            {route.shared_vulnerable_segments.length > 0 && (
              <Typography as="small" variant="small">
                {route.shared_vulnerable_segments.length} fire-exposed road
                segments are shared with another route.
              </Typography>
            )}
          </Card>
        ))
      )}
      {analysis.baseline_conflicts.length > 0 && (
        <Card density="compact" shadow="none" className="route-explanation">
          <strong>Why the ordinary fastest route changed</strong>
          {analysis.baseline_conflicts.slice(0, 5).map((conflict, index) => (
            <Typography as="small" variant="small" key={index}>
              {conflict.type === "fire"
                ? `${conflict.road}: modelled exposure at ${Math.round(conflict.exposure_min!)} min, before traversal finished.`
                : `${conflict.road}: ${conflict.reason}`}
            </Typography>
          ))}
        </Card>
      )}
      {analysis.withdrawal && (
        <Card
          as="article"
          density="compact"
          shadow="none"
          className={`route-card ${analysis.withdrawal.status}`}
        >
          <Box>
            <strong>Withdrawal</strong>
            <span>
              {analysis.withdrawal.status === "unavailable"
                ? "Route unavailable"
                : analysis.withdrawal.status === "unknown"
                  ? "Insufficient information"
                  : "No modelled conflict"}
            </span>
          </Box>
          {"distance_km" in analysis.withdrawal && (
            <Typography as="p" variant="body">
              {analysis.withdrawal.distance_km.toFixed(1)} km ·{" "}
              {Math.round(analysis.withdrawal.duration_min)} min · departs{" "}
              {Math.round(analysis.withdrawal.departure_min)} min
            </Typography>
          )}
          <Typography as="small" variant="small">
            {analysis.withdrawal.message}
          </Typography>
        </Card>
      )}
      <Typography as="small" variant="small" className="route-assumption">
        {analysis.assumptions.fire_rule} {analysis.assumptions.speed_source}
      </Typography>
    </section>
  );
}

function Stat({ label, value }: { label: string; value?: number }) {
  return (
    <Box>
      <span>{label}</span>
      <strong>{value ?? "—"}</strong>
    </Box>
  );
}

export function resultLabel(run: Run) {
  return `${run.scenario.name} · ${run.mode === "single" ? run.scenario.engine : run.mode === "parameter_ensemble" ? "conjunto" : run.mode === "allocation_comparison" ? "comparação de afetações" : "comparação"} · ${run.id.slice(-8)}`;
}
