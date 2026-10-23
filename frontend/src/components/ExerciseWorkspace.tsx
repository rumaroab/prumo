import { PrumoBrand } from "./PrumoBrand";
import { Box, Button, Card, SectionContainer, Typography } from "./ui";
import { ResourceInventoryGroups, unitCategory, vehicleCategory } from "./ResourceInventoryGroups";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  Area,
  ExerciseRun,
  ExerciseSituation,
  FeatureCollection,
  Mission,
  MissionType,
  MobilitySnapshot,
  PlanAssignment,
  PointKind,
  ResponseExperiment,
  ResponsePlan,
  Run,
  ScenarioPoint,
  ScenarioWorkspace,
} from "../types";
import { MapView } from "./MapView";
import { PointsEditor } from "./PointsEditor";

type ExercisePage = "map" | "missions" | "plans" | "resources" | "updates";
const pages: { id: ExercisePage; label: string; hint: string }[] = [
  { id: "map", label: "Map", hint: "Shared situation" },
  { id: "missions", label: "Missions", hint: "Required outcomes" },
  { id: "plans", label: "Plans & Experiments", hint: "Allocate and compare" },
  { id: "resources", label: "Resources", hint: "Units and locations" },
  { id: "updates", label: "Updates", hint: "Exercise activity" },
];

export function ExerciseWorkspace({ scenarioId }: { scenarioId: string }) {
  const [page, setPage] = useState<ExercisePage>(readPage());
  const [workspace, setWorkspace] = useState<ScenarioWorkspace>();
  const [area, setArea] = useState<Area>();
  const [situation, setSituation] = useState<ExerciseSituation>();
  const [mobility, setMobility] = useState<MobilitySnapshot>();
  const [missions, setMissions] = useState<Mission[]>([]);
  const [plans, setPlans] = useState<ResponsePlan[]>([]);
  const [experiments, setExperiments] = useState<ResponseExperiment[]>([]);
  const [exerciseRuns, setExerciseRuns] = useState<ExerciseRun[]>([]);
  const [fireRuns, setFireRuns] = useState<Run[]>([]);
  const [selectedForecast, setSelectedForecast] = useState<string>();
  const [fire, setFire] = useState<FeatureCollection>();
  const [roads, setRoads] = useState<FeatureCollection>();
  const [preset, setPreset] = useState<"situation" | "water" | "access">(
    "situation",
  );
  const [selectedPoint, setSelectedPoint] = useState<ScenarioPoint>();
  const [placing, setPlacing] = useState<PointKind>();
  const [showPointsKey, setShowPointsKey] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  async function load() {
    setError("");
    try {
      const [
        scenario,
        situationValue,
        mobilityValue,
        missionValues,
        planValues,
        experimentValues,
        runValues,
        fireValues,
      ] = await Promise.all([
        api.scenario(scenarioId),
        api.exerciseSituation(scenarioId),
        api.mobility(scenarioId),
        api.missions(scenarioId),
        api.responsePlans(scenarioId),
        api.responseExperiments(scenarioId),
        api.exerciseRuns(scenarioId),
        api.scenarioRuns(scenarioId),
      ]);
      if (scenario.scenario_kind !== "exercise")
        throw new Error(
          "This is a legacy scenario. Create an exercise copy from its profile.",
        );
      setWorkspace(scenario);
      setSituation(situationValue);
      setMobility(mobilityValue);
      setMissions(missionValues);
      setPlans(planValues);
      setExperiments(experimentValues);
      setExerciseRuns(runValues);
      setFireRuns(fireValues);
      setSelectedForecast(
        new URLSearchParams(window.location.search).get("run") ||
          situationValue.selected_forecast_ids[0],
      );
      const areaValue = await api.area(undefined, scenario.area_package_id);
      setArea(areaValue);
      try {
        setRoads(await api.mobilityRoads(scenarioId));
      } catch {
        setRoads(undefined);
      }
    } catch (reason) {
      setError(message(reason));
    }
  }
  useEffect(() => {
    void load();
  }, [scenarioId]);
  useEffect(() => {
    const listener = () => setPage(readPage());
    window.addEventListener("popstate", listener);
    return () => window.removeEventListener("popstate", listener);
  }, []);
  useEffect(() => {
    if (!selectedForecast) {
      setFire(undefined);
      return;
    }
    api
      .fire(selectedForecast, 0)
      .then(setFire)
      .catch(() => setFire(undefined));
  }, [selectedForecast]);
  useEffect(() => {
    if (
      !experiments.some((value) => ["queued", "running"].includes(value.status))
    )
      return;
    const timer = window.setInterval(
      () =>
        api
          .responseExperiments(scenarioId)
          .then(setExperiments)
          .catch(() => {}),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [scenarioId, experiments]);

  function navigate(next: ExercisePage) {
    window.history.pushState({}, "", `/scenarios/${scenarioId}/${next}`);
    setPage(next);
  }
  async function action(label: string, work: () => Promise<void>) {
    setBusy(label);
    setError("");
    try {
      await work();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy("");
    }
  }
  async function saveWorkspace(next = workspace) {
    if (!next) return;
    const saved = await api.saveScenario(next, next.revision);
    setWorkspace(saved);
  }

  if (!workspace || !situation || !mobility || !area)
    return (
      <main className="exercise-loading">
        <span className="pulse" />
        {error || "Loading exercise workspace…"}
      </main>
    );
  const boundsValue = area.resource_bounds || area.bounds;
  const bounds: [[number, number], [number, number]] = [
    [boundsValue[1], boundsValue[0]],
    [boundsValue[3], boundsValue[2]],
  ];
  const recordedUnits: ScenarioPoint[] = mobility.units
    .filter((unit) => unit.latest_location)
    .map((unit) => ({
      id: `unit-${unit.id}`,
      kind: "custom",
      name: `[Recorded] ${unit.callsign}`,
      coordinates: unit.latest_location!.coordinates,
      description: `${unit.organisation} · ${unit.status}`,
      notes: `Observed ${formatDate(unit.latest_location!.observed_at)}`,
      source: "manual",
      data_status: "reported",
      water: null,
      asset: null,
    }));
  const selectedRehearsal = exerciseRuns[0];
  const simulatedUnits: ScenarioPoint[] = selectedRehearsal
    ? selectedRehearsal.payload.plan.assignments.flatMap((assignment) => {
        const state = selectedRehearsal.mission_states[assignment.mission_id];
        const mission = missions.find(
          (value) => value.id === assignment.mission_id,
        );
        if (!mission || !["working", "completed", "blocked"].includes(state))
          return [];
        return assignment.unit_ids.map((unitId) => {
          const unit = mobility.units.find((value) => value.id === unitId);
          return {
            id: `simulated-${unitId}-${assignment.mission_id}`,
            kind: "custom" as const,
            name: `[Simulated] ${unit?.callsign || unitId}`,
            coordinates: mission.location.coordinates,
            description: `${mission.name} · ${state}`,
            notes: `Exercise minute ${selectedRehearsal.elapsed_min.toFixed(1)}`,
            source: "demo" as const,
            data_status: "unverified" as const,
            water: null,
            asset: null,
          };
        });
      })
    : [];
  const mapPoints = [
    ...filteredPoints(workspace.points, preset),
    ...recordedUnits,
    ...simulatedUnits,
  ];
  const routeLayer = selectedRehearsal
    ? rehearsalRoutes(selectedRehearsal)
    : undefined;

  return (
    <Box className="exercise-shell">
      <header className="exercise-header">
        <Box className="exercise-brand">
          <a href="/scenarios"><PrumoBrand /></a>
          <a href={`/scenarios/${scenarioId}`}>{workspace.name}</a>
        </Box>
        <nav aria-label="Exercise workspace">
          {pages.map((item) => (
            <a
              key={item.id}
              className={page === item.id ? "active" : ""}
              href={`/scenarios/${scenarioId}/${item.id}`}
              onClick={(event) => {
                event.preventDefault();
                navigate(item.id);
              }}
            >
              <strong>{item.label}</strong>
              <Typography as="small" variant="small">
                {item.hint}
              </Typography>
            </a>
          ))}
        </nav>
        <a
          className="fire-analysis-link"
          href={`/scenarios/${scenarioId}/simulation${selectedForecast ? `?run=${selectedForecast}` : ""}`}
        >
          Fire analysis ↗
        </a>
      </header>
      {error && (
        <Box className="exercise-error" role="alert">
          {error}
          <Button variant="secondary" onClick={() => setError("")}>
            Dismiss
          </Button>
        </Box>
      )}
      {page === "map" && (
        <main className="exercise-map-page">
          <Card
            as="aside"
            density="compact"
            shadow="none"
            className="exercise-sidebar"
          >
            <Typography as="span" variant="label" className="eyebrow">
              Exercise situation
            </Typography>
            <Typography as="h1" variant="h1">
              {workspace.name}
            </Typography>
            <Typography as="p" variant="body">
              {situation.summary ||
                "Describe the starting conditions and define the missions that responders must complete."}
            </Typography>
            <label>
              Reference time
              <input
                type="datetime-local"
                value={localDateTime(situation.reference_time)}
                onChange={(event) =>
                  setSituation({
                    ...situation,
                    reference_time: new Date(event.target.value).toISOString(),
                  })
                }
              />
            </label>
            <label>
              Situation summary
              <textarea
                rows={4}
                value={situation.summary}
                onChange={(event) =>
                  setSituation({ ...situation, summary: event.target.value })
                }
              />
            </label>
            <Button
              variant="secondary"
              disabled={Boolean(busy)}
              onClick={() =>
                void action("situation", async () =>
                  setSituation(
                    await api.saveExerciseSituation(scenarioId, situation),
                  ),
                )
              }
            >
              Save situation
            </Button>
            <section>
              <Typography as="h2" variant="h3">
                Map preset
              </Typography>
              <Box className="preset-buttons">
                {(
                  [
                    ["situation", "Situation"],
                    ["water", "Water supply"],
                    ["access", "Access & intervention"],
                  ] as const
                ).map(([id, label]) => (
                  <Button
                    variant="secondary"
                    aria-pressed={preset === id}
                    className={preset === id ? "active" : ""}
                    key={id}
                    onClick={() => setPreset(id)}
                  >
                    {label}
                  </Button>
                ))}
              </Box>
            </section>
            <section>
              <Typography as="h2" variant="h3">
                Fire forecast
              </Typography>
              <select
                value={selectedForecast || ""}
                onChange={(event) => {
                  const value = event.target.value || undefined;
                  setSelectedForecast(value);
                  setSituation({
                    ...situation,
                    selected_forecast_ids: value ? [value] : [],
                  });
                }}
              >
                <option value="">
                  No forecast · fire exposure not assessed
                </option>
                {fireRuns
                  .filter((run) => ["ready", "partial"].includes(run.status))
                  .map((run) => (
                    <option key={run.id} value={run.id}>
                      {run.name}
                    </option>
                  ))}
              </select>
              {selectedForecast &&
                !fireRuns.find((run) => run.id === selectedForecast)
                  ?.run_context?.scenario_start_time && (
                  <label>
                    Forecast minute zero
                    <input
                      type="datetime-local"
                      value={
                        situation.forecast_alignments?.[selectedForecast]
                          ? localDateTime(
                              situation.forecast_alignments[selectedForecast],
                            )
                          : ""
                      }
                      onChange={(event) =>
                        setSituation({
                          ...situation,
                          forecast_alignments: {
                            ...(situation.forecast_alignments || {}),
                            [selectedForecast]: new Date(
                              event.target.value,
                            ).toISOString(),
                          },
                        })
                      }
                    />
                  </label>
                )}
              <Typography as="small" variant="small">
                Recorded observations, modelled forecasts, and simulated
                positions remain separate.
              </Typography>
            </section>
            <section className="exercise-counts">
              <Box>
                <strong>
                  {
                    mobility.units.filter((unit) => unit.status === "available")
                      .length
                  }
                  /{mobility.units.length}
                </strong>
                <span>units available</span>
              </Box>
              <Box>
                <strong>
                  {
                    missions.filter((value) => value.status === "required")
                      .length
                  }
                </strong>
                <span>missions outstanding</span>
              </Box>
              <Box>
                <strong>{plans.length}</strong>
                <span>saved plans</span>
              </Box>
            </section>
            {selectedPoint && (
              <Card
                as="section"
                density="compact"
                shadow="none"
                className="selection-card"
              >
                <Typography as="span" variant="label" className="eyebrow">
                  Selected location
                </Typography>
                <Typography as="h2" variant="h3">
                  {selectedPoint.name}
                </Typography>
                <Typography as="p" variant="body">
                  {selectedPoint.description ||
                    selectedPoint.notes ||
                    "No details recorded"}
                </Typography>
                <Typography as="small" variant="small">
                  {selectedPoint.data_status} · {selectedPoint.source}
                </Typography>
                {selectedPoint.kind === "water_point" && (
                  <Button
                    variant="secondary"
                    onClick={() => navigate("missions")}
                  >
                    Plan water supply
                  </Button>
                )}
                <Button
                  variant="secondary"
                  onClick={() => {
                    setPlacing(selectedPoint.kind);
                  }}
                >
                  Move point
                </Button>
              </Card>
            )}
          </Card>
          <section
            className={placing ? "exercise-map placing" : "exercise-map"}
          >
            <MapView
              bounds={bounds}
              scenario={workspace.simulation}
              points={mapPoints}
              showPointsKey={showPointsKey}
              roads={roads}
              fire={fire}
              routes={routeLayer}
              minute={0}
              forecast={120}
              filter="all"
              placing={Boolean(placing)}
              showFire={Boolean(fire)}
              showIgnition={false}
              showRoads
              showBasemap
              showPoints
              onIgnition={(position) => {
                if (!placing) return;
                const existing =
                  selectedPoint &&
                  workspace.points.some(
                    (value) => value.id === selectedPoint.id,
                  )
                    ? selectedPoint
                    : undefined;
                const point = existing
                  ? { ...existing, coordinates: position }
                  : newExercisePoint(placing, position);
                const next = {
                  ...workspace,
                  points: existing
                    ? workspace.points.map((value) =>
                        value.id === point.id ? point : value,
                      )
                    : [...workspace.points, point],
                };
                setWorkspace(next);
                setSelectedPoint(point);
                setPlacing(undefined);
                void action("point", () => saveWorkspace(next));
              }}
              onPointSelect={(point) => {
                if (!point.id.startsWith("unit-")) setSelectedPoint(point);
              }}
              onPointMove={(id) => {
                const point = workspace.points.find((value) => value.id === id);
                if (point) {
                  setSelectedPoint(point);
                  setPlacing(point.kind);
                }
              }}
              onPointDelete={(id) => {
                if (
                  plans.some((plan) =>
                    plan.assignments.some(
                      (value) => value.source_point_id === id,
                    ),
                  )
                ) {
                  setError(
                    "This point is referenced by a response plan. Reassign it before archiving the point.",
                  );
                  return;
                }
                const next = {
                  ...workspace,
                  points: workspace.points.filter((value) => value.id !== id),
                };
                setWorkspace(next);
                setSelectedPoint(undefined);
                void action("point", () => saveWorkspace(next));
              }}
            />
          </section>
        </main>
      )}
      {page === "missions" && (
        <MissionsPage
          missions={missions}
          center={
            workspace.resource_center ||
            workspace.simulation.ignitions[0].coordinates
          }
          busy={busy}
          onAction={action}
          onChange={setMissions}
          scenarioId={scenarioId}
        />
      )}
      {page === "plans" && (
        <PlansPage
          scenarioId={scenarioId}
          missions={missions}
          mobility={mobility}
          points={workspace.points}
          plans={plans}
          experiments={experiments}
          exerciseRuns={exerciseRuns}
          busy={busy}
          onAction={action}
          onPlans={setPlans}
          onExperiments={setExperiments}
          onRuns={setExerciseRuns}
        />
      )}
      {page === "resources" && (
        <ResourcesPage
          workspace={workspace}
          mobility={mobility}
          busy={busy}
          placing={placing}
          onPlacing={setPlacing}
          onWorkspace={setWorkspace}
          onMobility={setMobility}
          onAction={action}
          onSaveWorkspace={saveWorkspace}
          onShowPoints={() => setShowPointsKey((value) => value + 1)}
        />
      )}
      {page === "updates" && (
        <UpdatesPage mobility={mobility} rehearsal={selectedRehearsal} />
      )}
    </Box>
  );
}

function MissionsPage({
  missions,
  center,
  busy,
  scenarioId,
  onAction,
  onChange,
}: {
  missions: Mission[];
  center: [number, number];
  busy: string;
  scenarioId: string;
  onAction: (label: string, work: () => Promise<void>) => Promise<void>;
  onChange: (value: Mission[]) => void;
}) {
  const [draft, setDraft] = useState<Mission>(() =>
    newMission("access_control", center),
  );
  function type(value: MissionType) {
    setDraft(newMission(value, center));
  }
  async function create() {
    await onAction("mission", async () => {
      const saved = await api.addMission(scenarioId, draft);
      onChange([...missions, saved]);
      setDraft(newMission(draft.mission_type, center));
    });
  }
  return (
    <SectionContainer
      as="main"
      containerClassName="ds-stack"
      className="exercise-content"
    >
      <header>
        <Typography as="span" variant="label" className="eyebrow">
          Required outcomes
        </Typography>
        <Typography as="h1" variant="h1">
          Missions
        </Typography>
        <Typography as="p" variant="body">
          Arrival and mission completion are tracked separately. Dependencies
          must form an acyclic chain.
        </Typography>
      </header>
      <Box className="exercise-two-column">
        <Card
          as="section"
          density="default"
          shadow="card"
          className="exercise-panel mission-form"
        >
          <Typography as="h2" variant="h3">
            New mission
          </Typography>
          <label>
            Template
            <select
              value={draft.mission_type}
              onChange={(event) => type(event.target.value as MissionType)}
            >
              {missionTypes.map((value) => (
                <option key={value} value={value}>
                  {missionLabel(value)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Name
            <input
              value={draft.name}
              onChange={(event) =>
                setDraft({ ...draft, name: event.target.value })
              }
            />
          </label>
          <Box className="two-col">
            <label>
              Priority
              <select
                value={draft.priority}
                onChange={(event) =>
                  setDraft({ ...draft, priority: Number(event.target.value) })
                }
              >
                {[5, 4, 3, 2, 1].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <label>
              Units required
              <input
                type="number"
                min="1"
                max="10"
                value={draft.required_unit_count}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    required_unit_count: Number(event.target.value),
                  })
                }
              />
            </label>
          </Box>
          <label>
            Required capabilities
            <input
              value={draft.required_capabilities.join(", ")}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  required_capabilities: split(event.target.value),
                })
              }
              placeholder="water_supply, firefighting"
            />
          </label>
          <Box className="two-col">
            <label>
              Earliest start (min)
              <input
                type="number"
                min="0"
                value={draft.earliest_start_min}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    earliest_start_min: Number(event.target.value),
                  })
                }
              />
            </label>
            <label>
              Deadline (min)
              <input
                type="number"
                min="0"
                value={draft.deadline_min ?? ""}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    deadline_min: event.target.value
                      ? Number(event.target.value)
                      : null,
                  })
                }
              />
            </label>
          </Box>
          <label>
            Service duration (min)
            <input
              type="number"
              min="0"
              value={draft.service_duration_min}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  service_duration_min: Number(event.target.value),
                })
              }
            />
          </label>
          <label>
            Location name
            <input
              value={draft.location.name}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  location: { ...draft.location, name: event.target.value },
                })
              }
            />
          </label>
          <Coordinates
            value={draft.location.coordinates}
            onChange={(coordinates) =>
              setDraft({
                ...draft,
                location: { ...draft.location, coordinates },
              })
            }
          />
          {draft.mission_type === "fire_response" && (
            <>
              <label>
                Vehicle access point name
                <input
                  value={draft.access_point?.name || ""}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      access_point: {
                        name: event.target.value,
                        coordinates: draft.access_point?.coordinates || center,
                      },
                    })
                  }
                />
              </label>
              <Coordinates
                value={draft.access_point?.coordinates || center}
                onChange={(coordinates) =>
                  setDraft({
                    ...draft,
                    access_point: {
                      name: draft.access_point?.name || "Sector access",
                      coordinates,
                    },
                  })
                }
              />
            </>
          )}
          {draft.mission_type === "water_supply" && (
            <label>
              Target volume (L)
              <input
                type="number"
                min="1"
                value={draft.target_volume_l || 10000}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    target_volume_l: Number(event.target.value),
                  })
                }
              />
            </label>
          )}
          {draft.mission_type === "transport" && (
            <label>
              People to transport
              <input
                type="number"
                min="1"
                value={draft.people_count || 1}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    people_count: Number(event.target.value),
                    pickup: draft.pickup || {
                      name: "Pickup",
                      coordinates: center,
                    },
                    dropoff: draft.dropoff || {
                      name: "Destination",
                      coordinates: center,
                    },
                  })
                }
              />
            </label>
          )}
          <label>
            Prerequisites
            <select
              multiple
              value={draft.prerequisite_ids}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  prerequisite_ids: Array.from(
                    event.target.selectedOptions,
                  ).map((value) => value.value),
                })
              }
            >
              {missions.map((value) => (
                <option key={value.id} value={value.id}>
                  {value.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Completion criteria
            <textarea
              rows={2}
              value={draft.completion_criteria}
              onChange={(event) =>
                setDraft({ ...draft, completion_criteria: event.target.value })
              }
            />
          </label>
          <Button
            variant="secondary"
            disabled={Boolean(busy) || !draft.name.trim()}
            onClick={() => void create()}
          >
            Create mission
          </Button>
        </Card>
        <Card
          as="section"
          density="default"
          shadow="card"
          className="exercise-panel"
        >
          <Box className="section-heading">
            <Box>
              <Typography as="span" variant="label" className="eyebrow">
                Planning set
              </Typography>
              <Typography as="h2" variant="h3">
                {missions.length} mission{missions.length === 1 ? "" : "s"}
              </Typography>
            </Box>
            <Typography as="small" variant="small">
              Choose up to 10 when suggesting a plan.
            </Typography>
          </Box>
          <Box className="mission-list">
            {missions.map((mission) => (
              <Card
                as="article"
                density="compact"
                shadow="none"
                key={mission.id}
              >
                <Box>
                  <span className={`priority p${mission.priority}`}>
                    P{mission.priority}
                  </span>
                  <strong>{mission.name}</strong>
                  <Typography as="small" variant="small">
                    {missionLabel(mission.mission_type)} · earliest{" "}
                    {mission.earliest_start_min} min
                    {mission.deadline_min == null
                      ? ""
                      : ` · due ${mission.deadline_min} min`}
                  </Typography>
                </Box>
                <Button
                  variant="outline"
                  intent="danger"
                  onClick={() =>
                    void onAction("archive", async () => {
                      await api.archiveMission(scenarioId, mission);
                      onChange(
                        missions.filter((value) => value.id !== mission.id),
                      );
                    })
                  }
                >
                  Archive
                </Button>
              </Card>
            ))}
          </Box>
          {!missions.length && (
            <Typography as="p" variant="body" className="exercise-empty">
              No missions yet. Add the outcomes responders need to achieve.
            </Typography>
          )}
        </Card>
      </Box>
    </SectionContainer>
  );
}

function PlansPage({
  scenarioId,
  missions,
  mobility,
  points,
  plans,
  experiments,
  exerciseRuns,
  busy,
  onAction,
  onPlans,
  onExperiments,
  onRuns,
}: {
  scenarioId: string;
  missions: Mission[];
  mobility: MobilitySnapshot;
  points: ScenarioPoint[];
  plans: ResponsePlan[];
  experiments: ResponseExperiment[];
  exerciseRuns: ExerciseRun[];
  busy: string;
  onAction: (label: string, work: () => Promise<void>) => Promise<void>;
  onPlans: (value: ResponsePlan[]) => void;
  onExperiments: (value: ResponseExperiment[]) => void;
  onRuns: (value: ExerciseRun[]) => void;
}) {
  const [selectedMission, setSelectedMission] = useState("");
  const [selectedUnit, setSelectedUnit] = useState("");
  const [source, setSource] = useState("");
  const [name, setName] = useState("Manual response plan");
  const [assignments, setAssignments] = useState<PlanAssignment[]>([]);
  const [compare, setCompare] = useState<string[]>([]);
  const [horizon, setHorizon] = useState(120);
  const [rehearsal, setRehearsal] = useState<ExerciseRun | undefined>(
    exerciseRuns[0],
  );
  const [eventKind, setEventKind] = useState<
    | "road_blockage"
    | "road_reopening"
    | "unit_unavailable"
    | "water_source_change"
  >("road_blockage");
  const [eventTarget, setEventTarget] = useState("");
  useEffect(() => setRehearsal(exerciseRuns[0]), [exerciseRuns]);
  useEffect(() => {
    if (!rehearsal || rehearsal.state !== "running") return;
    const timer = window.setInterval(
      () =>
        api
          .advanceExerciseRun(scenarioId, rehearsal.id, 0.25)
          .then((value) => {
            setRehearsal(value);
            onRuns(
              exerciseRuns.map((item) => (item.id === value.id ? value : item)),
            );
          })
          .catch(() => {}),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [rehearsal?.id, rehearsal?.state, rehearsal?.revision]);
  const waterSources = points.filter((value) => value.kind === "water_point");
  async function createPlan() {
    await onAction("plan", async () => {
      const plan: ResponsePlan = {
        id: uid(),
        name,
        description: "",
        assignments,
        assumptions: [],
        revision: 1,
      };
      const saved = await api.addResponsePlan(scenarioId, plan);
      onPlans([...plans, saved]);
      setAssignments([]);
    });
  }
  async function suggest() {
    await onAction("suggestions", async () => {
      const result = await api.suggestResponsePlans(
        scenarioId,
        missions.slice(0, 10).map((value) => value.id),
        mobility.units.slice(0, 10).map((value) => value.id),
      );
      const saved: ResponsePlan[] = [];
      for (const candidate of result.plans) {
        const { evaluation: _evaluation, ...plan } = candidate;
        saved.push(
          await api.addResponsePlan(scenarioId, {
            ...plan,
            id: uid(),
            scenario_id: undefined,
            revision: 1,
          }),
        );
      }
      onPlans([...plans, ...saved]);
    });
  }
  async function comparePlans() {
    await onAction("experiment", async () => {
      const created = await api.createResponseExperiment(
        scenarioId,
        compare,
        [],
        horizon,
      );
      onExperiments([created, ...experiments]);
      window.setTimeout(
        () => api.responseExperiments(scenarioId).then(onExperiments),
        300,
      );
    });
  }
  async function rehearse(plan: ResponsePlan) {
    await onAction("rehearsal", async () => {
      const created = await api.createExerciseRun(scenarioId, plan);
      onRuns([created, ...exerciseRuns]);
      setRehearsal(created);
    });
  }
  async function control(
    actionName: "play" | "pause" | "step" | "restart" | "set_speed",
    speed?: 1 | 5 | 20,
  ) {
    if (!rehearsal) return;
    await onAction("playback", async () => {
      const changed = await api.exerciseRunAction(
        scenarioId,
        rehearsal,
        actionName,
        speed,
      );
      setRehearsal(changed);
      onRuns(
        exerciseRuns.map((value) =>
          value.id === changed.id ? changed : value,
        ),
      );
    });
  }
  async function injectEvent() {
    if (!rehearsal || !eventTarget) return;
    await onAction("event", async () => {
      const key =
        eventKind === "unit_unavailable"
          ? "unit_id"
          : eventKind === "water_source_change"
            ? "source_point_id"
            : "segment_id";
      const changed = await api.addExerciseEvent(
        scenarioId,
        rehearsal.id,
        eventKind,
        rehearsal.elapsed_min,
        { [key]: eventTarget },
      );
      setRehearsal(changed);
      onRuns(
        exerciseRuns.map((value) =>
          value.id === changed.id ? changed : value,
        ),
      );
      setEventTarget("");
    });
  }
  return (
    <SectionContainer
      as="main"
      containerClassName="ds-stack"
      className="exercise-content"
    >
      <header>
        <Typography as="span" variant="label" className="eyebrow">
          Allocation laboratory
        </Typography>
        <Typography as="h1" variant="h1">
          Plans & Experiments
        </Typography>
        <Typography as="p" variant="body">
          Manual and suggested plans use the same evaluator. Completed
          experiments retain frozen inputs.
        </Typography>
      </header>
      <Box className="exercise-grid-three">
        <Card
          as="section"
          density="default"
          shadow="card"
          className="exercise-panel"
        >
          <Typography as="h2" variant="h3">
            Build a plan
          </Typography>
          <label>
            Name
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            Mission
            <select
              value={selectedMission}
              onChange={(event) => setSelectedMission(event.target.value)}
            >
              <option value="">Choose mission</option>
              {missions.map((value) => (
                <option key={value.id} value={value.id}>
                  {value.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Unit
            <select
              value={selectedUnit}
              onChange={(event) => setSelectedUnit(event.target.value)}
            >
              <option value="">Choose unit</option>
              {mobility.units.map((value) => (
                <option key={value.id} value={value.id}>
                  {value.callsign} ·{" "}
                  {value.capabilities?.join(", ") || "capabilities unrecorded"}
                </option>
              ))}
            </select>
          </label>
          {missions.find((value) => value.id === selectedMission)
            ?.mission_type === "water_supply" && (
            <label>
              Water source
              <select
                value={source}
                onChange={(event) => setSource(event.target.value)}
              >
                <option value="">Choose source</option>
                {waterSources.map((value) => (
                  <option key={value.id} value={value.id}>
                    {value.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <Button
            variant="secondary"
            disabled={!selectedMission || !selectedUnit}
            onClick={() => {
              setAssignments([
                ...assignments,
                {
                  id: uid(),
                  mission_id: selectedMission,
                  unit_ids: [selectedUnit],
                  source_point_id: source || null,
                  locked: false,
                },
              ]);
              setSelectedMission("");
              setSelectedUnit("");
              setSource("");
            }}
          >
            Add assignment
          </Button>
          <Box className="assignment-list">
            {assignments.map((value) => (
              <Box key={value.id}>
                <span>
                  {missions.find((item) => item.id === value.mission_id)?.name}{" "}
                  →{" "}
                  {
                    mobility.units.find((item) => item.id === value.unit_ids[0])
                      ?.callsign
                  }
                </span>
                <Button
                  aria-label="Remover atribuição"
                  variant="secondary"
                  onClick={() =>
                    setAssignments(
                      assignments.filter((item) => item.id !== value.id),
                    )
                  }
                >
                  ×
                </Button>
              </Box>
            ))}
          </Box>
          <Button
            variant="secondary"
            disabled={Boolean(busy) || !assignments.length}
            onClick={() => void createPlan()}
          >
            Save manual plan
          </Button>
          <Button
            variant="secondary"
            disabled={
              Boolean(busy) || !missions.length || !mobility.units.length
            }
            onClick={() => void suggest()}
          >
            Suggest up to four plans
          </Button>
          <Typography as="small" variant="small">
            Suggestions search up to 10 selected missions and units and explain
            uncovered work.
          </Typography>
        </Card>
        <Card
          as="section"
          density="default"
          shadow="card"
          className="exercise-panel"
        >
          <Typography as="h2" variant="h3">
            Saved plans
          </Typography>
          <Box className="plan-list">
            {plans.map((plan) => (
              <Card as="article" density="compact" shadow="none" key={plan.id}>
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={compare.includes(plan.id)}
                    disabled={!compare.includes(plan.id) && compare.length >= 4}
                    onChange={(event) =>
                      setCompare(
                        event.target.checked
                          ? [...compare, plan.id]
                          : compare.filter((value) => value !== plan.id),
                      )
                    }
                  />
                  <span>
                    <strong>{plan.name}</strong>
                    <Typography as="small" variant="small">
                      {plan.assignments.length} assignment
                      {plan.assignments.length === 1 ? "" : "s"} · version{" "}
                      {plan.revision}
                    </Typography>
                  </span>
                </label>
                <Button variant="secondary" onClick={() => void rehearse(plan)}>
                  Rehearse plan
                </Button>
              </Card>
            ))}
          </Box>
          <label>
            Evaluation horizon <strong>{horizon} min</strong>
            <input
              type="range"
              min="15"
              max="240"
              step="15"
              value={horizon}
              onChange={(event) => setHorizon(Number(event.target.value))}
            />
          </label>
          <Button
            variant="secondary"
            disabled={Boolean(busy) || !compare.length}
            onClick={() => void comparePlans()}
          >
            Compare selected plans
          </Button>
        </Card>
        <Card
          as="section"
          density="default"
          shadow="card"
          className="exercise-panel"
        >
          <Typography as="h2" variant="h3">
            Experiments
          </Typography>
          {experiments.map((value) => (
            <Card
              as="article"
              density="compact"
              shadow="none"
              className="experiment-result"
              key={value.id}
            >
              <Box>
                <span className={`status-pill ${value.status}`}>
                  {value.status}
                </span>
                <strong>
                  {value.result?.plans.length ||
                    (value.request.plan_ids as string[] | undefined)?.length ||
                    0}{" "}
                  plans
                </strong>
                <Typography as="small" variant="small">
                  {formatDate(value.created_at)} · snapshot {value.snapshot_id}
                </Typography>
              </Box>
              {value.result?.plans.map((plan) => (
                <Card
                  density="compact"
                  shadow="none"
                  className="comparison-summary"
                  key={plan.plan_id}
                >
                  <strong>{plan.plan_name}</strong>
                  <span>
                    P5 {percent(plan.worst_case_fulfilment["5"])} · P4{" "}
                    {percent(plan.worst_case_fulfilment["4"])} · P3{" "}
                    {percent(plan.worst_case_fulfilment["3"])}
                  </span>
                </Card>
              ))}
              {value.error && (
                <Typography
                  role="alert"
                  as="p"
                  variant="small"
                  className="inline-error"
                >
                  {value.error}
                </Typography>
              )}
            </Card>
          ))}
          {!experiments.length && (
            <Typography as="p" variant="body" className="exercise-empty">
              Select saved plans to create the first response experiment.
            </Typography>
          )}
        </Card>
      </Box>
      {rehearsal && (
        <Card
          as="section"
          density="default"
          shadow="card"
          className="exercise-panel rehearsal-panel"
        >
          <Box>
            <Typography as="span" variant="label" className="eyebrow">
              Simulated rehearsal
            </Typography>
            <Typography as="h2" variant="h3">
              {rehearsal.payload.plan.name}
            </Typography>
            <Typography as="p" variant="body">
              {rehearsal.state} · minute {rehearsal.elapsed_min.toFixed(1)} ·{" "}
              {rehearsal.speed}×
            </Typography>
          </Box>
          <Box className="playback-controls">
            <Button
              variant="secondary"
              onClick={() =>
                void control(rehearsal.state === "running" ? "pause" : "play")
              }
            >
              {rehearsal.state === "running" ? "Pause" : "Play"}
            </Button>
            <Button variant="secondary" onClick={() => void control("step")}>
              Step
            </Button>
            <Button variant="secondary" onClick={() => void control("restart")}>
              Restart
            </Button>
            {([1, 5, 20] as const).map((value) => (
              <Button
                variant="secondary"
                aria-pressed={rehearsal.speed === value}
                className={rehearsal.speed === value ? "active" : ""}
                key={value}
                onClick={() => void control("set_speed", value)}
              >
                {value}×
              </Button>
            ))}
          </Box>
          <Box className="rehearsal-timeline">
            {Object.entries(rehearsal.mission_states).map(([id, state]) => (
              <Box key={id}>
                <strong>
                  {missions.find((value) => value.id === id)?.name || id}
                </strong>
                <span>{state}</span>
              </Box>
            ))}
          </Box>
          <Box className="exercise-event-form">
            <label>
              Inject simulated event
              <select
                value={eventKind}
                onChange={(event) => {
                  setEventKind(event.target.value as typeof eventKind);
                  setEventTarget("");
                }}
              >
                <option value="road_blockage">Road blockage</option>
                <option value="road_reopening">Road reopening</option>
                <option value="unit_unavailable">Unit unavailable</option>
                <option value="water_source_change">Water-source change</option>
              </select>
            </label>
            {eventKind === "unit_unavailable" ? (
              <label>
                Unit
                <select
                  value={eventTarget}
                  onChange={(event) => setEventTarget(event.target.value)}
                >
                  <option value="">Choose unit</option>
                  {mobility.units.map((value) => (
                    <option key={value.id} value={value.id}>
                      {value.callsign}
                    </option>
                  ))}
                </select>
              </label>
            ) : eventKind === "water_source_change" ? (
              <label>
                Water source
                <select
                  value={eventTarget}
                  onChange={(event) => setEventTarget(event.target.value)}
                >
                  <option value="">Choose source</option>
                  {waterSources.map((value) => (
                    <option key={value.id} value={value.id}>
                      {value.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <label>
                Road segment ID
                <input
                  value={eventTarget}
                  onChange={(event) => setEventTarget(event.target.value)}
                  placeholder="Prepared segment ID"
                />
              </label>
            )}
            <Button
              variant="secondary"
              disabled={!eventTarget}
              onClick={() => void injectEvent()}
            >
              Inject and pause
            </Button>
          </Box>
          {rehearsal.payload.affected_mission_ids?.length ? (
            <Card density="compact" shadow="none" className="replan-alert">
              <strong>Affected missions</strong>
              <span>
                {rehearsal.payload.affected_mission_ids
                  .map(
                    (id) =>
                      missions.find((value) => value.id === id)?.name || id,
                  )
                  .join(", ")}
              </span>
              <Button variant="secondary" onClick={() => void suggest()}>
                Suggest revised candidate plans
              </Button>
              <Typography as="small" variant="small">
                The original rehearsal branch remains immutable for comparison.
              </Typography>
            </Card>
          ) : null}
          <Typography as="small" variant="small">
            Playback is simulated. It never changes live unit status, movement
            records, briefs, or field observations.
          </Typography>
        </Card>
      )}
    </SectionContainer>
  );
}

function ResourcesPage({
  workspace,
  mobility,
  busy,
  placing,
  onPlacing,
  onWorkspace,
  onMobility,
  onAction,
  onSaveWorkspace,
  onShowPoints,
}: {
  workspace: ScenarioWorkspace;
  mobility: MobilitySnapshot;
  busy: string;
  placing?: PointKind;
  onPlacing: (value?: PointKind) => void;
  onWorkspace: (value: ScenarioWorkspace) => void;
  onMobility: (value: MobilitySnapshot) => void;
  onAction: (label: string, work: () => Promise<void>) => Promise<void>;
  onSaveWorkspace: (value?: ScenarioWorkspace) => Promise<void>;
  onShowPoints: () => void;
}) {
  const [vehicleName, setVehicleName] = useState("");
  const [vehicleClass, setVehicleClass] = useState<
    "light" | "heavy" | "tanker" | "bus" | "ambulance" | "other" | "aircraft"
  >("light");
  const [tank, setTank] = useState("");
  const [pump, setPump] = useState("");
  const [passengers, setPassengers] = useState("");
  const [callsign, setCallsign] = useState("");
  const [organisation, setOrganisation] = useState("");
  const [vehicleId, setVehicleId] = useState("");
  const [capabilities, setCapabilities] = useState("");
  async function addVehicle() {
    await onAction("vehicle", async () => {
      const value = await api.addVehicle(workspace.id, {
        id: uid(),
        name: vehicleName,
        vehicle_class: vehicleClass,
        width_m: null,
        height_m: null,
        weight_t: null,
        off_road: false,
        notes: "",
        revision: 1,
        water_tank_capacity_l: tank ? Number(tank) : null,
        pump_flow_l_min: pump ? Number(pump) : null,
        passenger_capacity: passengers ? Number(passengers) : null,
        starting_water_l: 0,
        available: true,
      });
      onMobility({ ...mobility, vehicles: [...mobility.vehicles, value] });
      setVehicleName("");
    });
  }
  async function addUnit() {
    await onAction("unit", async () => {
      const value = await api.addUnit(workspace.id, {
        id: uid(),
        organisation,
        callsign,
        contact: "",
        vehicle_id: vehicleId,
        status: "available",
        capabilities: split(capabilities),
        revision: 1,
      });
      onMobility({ ...mobility, units: [...mobility.units, value] });
      setCallsign("");
    });
  }
  return (
    <SectionContainer
      as="main"
      containerClassName="ds-stack"
      className="exercise-content"
    >
      <header>
        <Typography as="span" variant="label" className="eyebrow">
          Scenario inventory
        </Typography>
        <Typography as="h1" variant="h1">
          Resources
        </Typography>
        <Typography as="p" variant="body">
          Capabilities and capacities are explicit. Organisation and vehicle
          class never invent operational capability.
        </Typography>
      </header>
      <Box className="exercise-grid-three">
        <Card
          as="section"
          density="default"
          shadow="card"
          className="exercise-panel"
        >
          <Typography as="h2" variant="h3">
            Vehicles
          </Typography>
          <ResourceInventoryGroups items={mobility.vehicles} category={vehicleCategory} renderItem={(value) => (
            <Card
              as="article"
              density="compact"
              shadow="none"
              className="resource-row"
              key={value.id}
            >
              <strong>{value.name}</strong>
              <span>
                {value.vehicle_class}
                {value.water_tank_capacity_l
                  ? ` · ${value.water_tank_capacity_l} L`
                  : ""}
                {value.passenger_capacity
                  ? ` · ${value.passenger_capacity} people`
                  : ""}
              </span>
            </Card>
          )} />
          <label>
            Name
            <input
              value={vehicleName}
              onChange={(event) => setVehicleName(event.target.value)}
            />
          </label>
          <label>
            Class
            <select
              value={vehicleClass}
              onChange={(event) =>
                setVehicleClass(event.target.value as typeof vehicleClass)
              }
            >
              {["light", "heavy", "tanker", "bus", "ambulance", "other", "aircraft"].map(
                (value) => (
                  <option key={value}>{value}</option>
                ),
              )}
            </select>
          </label>
          <Box className="two-col">
            <label>
              Tank litres
              <input
                type="number"
                value={tank}
                onChange={(event) => setTank(event.target.value)}
              />
            </label>
            <label>
              Pump L/min
              <input
                type="number"
                value={pump}
                onChange={(event) => setPump(event.target.value)}
              />
            </label>
          </Box>
          <label>
            Passenger capacity
            <input
              type="number"
              value={passengers}
              onChange={(event) => setPassengers(event.target.value)}
            />
          </label>
          <Button
            variant="primary"
            disabled={Boolean(busy) || !vehicleName}
            onClick={() => void addVehicle()}
          >
            Add vehicle
          </Button>
        </Card>
        <Card
          as="section"
          density="default"
          shadow="card"
          className="exercise-panel"
        >
          <Typography as="h2" variant="h3">
            Units
          </Typography>
          <ResourceInventoryGroups items={mobility.units} category={(unit) => unitCategory(unit, mobility.vehicles)} renderItem={(value) => (
            <Card
              as="article"
              density="compact"
              shadow="none"
              className="resource-row"
              key={value.id}
            >
              <strong>{value.callsign}</strong>
              <span>
                {value.organisation} · {value.status}
              </span>
              <Typography as="small" variant="small">
                {value.capabilities?.join(", ") || "Capabilities not recorded"}
              </Typography>
            </Card>
          )} />
          <label>
            Callsign
            <input
              value={callsign}
              onChange={(event) => setCallsign(event.target.value)}
            />
          </label>
          <label>
            Organisation
            <input
              value={organisation}
              onChange={(event) => setOrganisation(event.target.value)}
            />
          </label>
          <label>
            Vehicle
            <select
              value={vehicleId}
              onChange={(event) => setVehicleId(event.target.value)}
            >
              <option value="">Choose vehicle</option>
              {mobility.vehicles.map((value) => (
                <option key={value.id} value={value.id}>
                  {value.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Capabilities
            <input
              value={capabilities}
              onChange={(event) => setCapabilities(event.target.value)}
              placeholder="firefighting, water_supply"
            />
          </label>
          <Button
            variant="primary"
            disabled={Boolean(busy) || !callsign || !organisation || !vehicleId}
            onClick={() => void addUnit()}
          >
            Add unit
          </Button>
        </Card>
        <Card
          as="section"
          density="default"
          shadow="card"
          className="exercise-panel point-resources"
        >
          <PointsEditor
            points={workspace.points}
            kinds={[
              "water_point",
              "response_base",
              "staging_area",
              "access_control",
              "shelter",
              "delivery_point",
              "asset",
              "hazard",
              "custom",
            ]}
            placementLabel={placing ? "Click the map tab to place" : undefined}
            onShowPoints={onShowPoints}
            onPointPlacement={onPlacing}
            onPointMove={(id) =>
              onPlacing(workspace.points.find((value) => value.id === id)?.kind)
            }
            onPointUpdate={(point) =>
              onWorkspace({
                ...workspace,
                points: workspace.points.map((value) =>
                  value.id === point.id ? point : value,
                ),
              })
            }
            onPointDelete={(id) =>
              onWorkspace({
                ...workspace,
                points: workspace.points.filter((value) => value.id !== id),
              })
            }
          />
          <Button
            variant="secondary"
            disabled={Boolean(busy)}
            onClick={() =>
              void onAction("points", () => onSaveWorkspace(workspace))
            }
          >
            Save location changes
          </Button>
          <Typography as="small" variant="small">
            Referenced resources are retained in frozen experiments and
            rehearsals.
          </Typography>
        </Card>
      </Box>
    </SectionContainer>
  );
}

function UpdatesPage({
  mobility,
  rehearsal,
}: {
  mobility: MobilitySnapshot;
  rehearsal?: ExerciseRun;
}) {
  return (
    <SectionContainer
      as="main"
      containerClassName="ds-stack"
      className="exercise-content"
    >
      <header>
        <Typography as="span" variant="label" className="eyebrow">
          Timestamped evidence and activity
        </Typography>
        <Typography as="h1" variant="h1">
          Updates
        </Typography>
        <Typography as="p" variant="body">
          Reported observations and simulated events are deliberately separated.
        </Typography>
      </header>
      <Box className="exercise-two-column">
        <Card
          as="section"
          density="default"
          shadow="card"
          className="exercise-panel"
        >
          <Typography as="h2" variant="h3">
            Recorded and reported
          </Typography>
          {mobility.road_reports.map((value) => (
            <Card
              as="article"
              density="compact"
              shadow="none"
              className="update-row"
              key={value.id}
            >
              <span className={`status-pill ${value.status}`}>
                {value.status}
              </span>
              <Box>
                <strong>
                  {value.kind} · {value.road_name}
                </strong>
                <Typography as="p" variant="body">
                  {value.reason || "No reason recorded"}
                </Typography>
                <Typography as="small" variant="small">
                  {formatDate(value.observed_at)} · {value.source}
                </Typography>
              </Box>
            </Card>
          ))}
          {!mobility.road_reports.length && (
            <Typography as="p" variant="body" className="exercise-empty">
              No road reports recorded.
            </Typography>
          )}
        </Card>
        <Card
          as="section"
          density="default"
          shadow="card"
          className="exercise-panel"
        >
          <Typography as="h2" variant="h3">
            Simulated rehearsal activity
          </Typography>
          {rehearsal?.events.map((value) => (
            <Card
              as="article"
              density="compact"
              shadow="none"
              className="update-row simulated"
              key={value.id}
            >
              <span className="status-pill">simulated</span>
              <Box>
                <strong>{value.kind.replaceAll("_", " ")}</strong>
                <Typography as="p" variant="body">
                  Exercise minute {value.offset_min}
                </Typography>
                <Typography as="small" variant="small">
                  {formatDate(value.created_at)}
                </Typography>
              </Box>
            </Card>
          ))}
          {!rehearsal?.events.length && (
            <Typography as="p" variant="body" className="exercise-empty">
              No simulated events injected.
            </Typography>
          )}
        </Card>
      </Box>
    </SectionContainer>
  );
}

function Coordinates({
  value,
  onChange,
}: {
  value: [number, number];
  onChange: (value: [number, number]) => void;
}) {
  return (
    <Box className="two-col">
      <label>
        Longitude
        <input
          type="number"
          step="0.000001"
          value={value[0]}
          onChange={(event) => onChange([Number(event.target.value), value[1]])}
        />
      </label>
      <label>
        Latitude
        <input
          type="number"
          step="0.000001"
          value={value[1]}
          onChange={(event) => onChange([value[0], Number(event.target.value)])}
        />
      </label>
    </Box>
  );
}
const missionTypes: MissionType[] = [
  "access_control",
  "fire_response",
  "water_supply",
  "transport",
  "logistics",
  "containment",
];
function newMission(type: MissionType, center: [number, number]): Mission {
  return {
    id: uid(),
    name: missionLabel(type),
    mission_type: type,
    priority: 3,
    status: "required",
    location: { name: "Mission location", coordinates: center },
    access_point:
      type === "fire_response"
        ? { name: "Sector access", coordinates: center }
        : null,
    earliest_start_min: 0,
    deadline_min: null,
    service_duration_min: 30,
    required_capabilities: [],
    required_unit_count: 1,
    prerequisite_ids: [],
    completion_criteria: "",
    target_volume_l: type === "water_supply" ? 10000 : null,
    people_count: type === "transport" ? 1 : null,
    pickup:
      type === "transport" ? { name: "Pickup", coordinates: center } : null,
    dropoff:
      type === "transport"
        ? { name: "Destination", coordinates: center }
        : null,
    containment_geometry:
      type === "containment"
        ? {
            type: "LineString",
            coordinates: [center, [center[0] + 0.001, center[1] + 0.001]],
          }
        : null,
    revision: 1,
  };
}
function missionLabel(value: MissionType) {
  return (
    {
      access_control: "Access control",
      fire_response: "Fire response",
      water_supply: "Water supply",
      transport: "Transport",
      logistics: "Logistics / support",
      containment: "Containment",
    } as Record<MissionType, string>
  )[value];
}
function filteredPoints(
  points: ScenarioPoint[],
  preset: "situation" | "water" | "access",
) {
  return points.filter((point) =>
    preset === "water"
      ? ["water_point", "response_base", "delivery_point"].includes(point.kind)
      : preset === "access"
        ? [
            "response_base",
            "staging_area",
            "access_control",
            "asset",
            "hazard",
            "shelter",
          ].includes(point.kind)
        : true,
  );
}
function newExercisePoint(
  kind: PointKind,
  coordinates: [number, number],
): ScenarioPoint {
  return {
    id: uid(),
    kind,
    name: `New ${kind.replaceAll("_", " ")}`,
    coordinates,
    description: "",
    notes: "",
    source: "manual",
    data_status: "unverified",
    water:
      kind === "water_point"
        ? {
            source_type: "other",
            availability: "unknown",
            capacity_m3: null,
            flow_l_min: null,
            access_notes: "",
            verification_status: "unverified",
            supply_class: "unknown",
            available_volume_l: null,
            shared_flow_l_min: null,
            filling_positions: null,
            setup_time_min: null,
          }
        : null,
    asset: kind === "asset" ? { priority: 3 } : null,
  };
}
function readPage(): ExercisePage {
  const match = window.location.pathname.match(
    /\/(map|missions|plans|resources|updates)\/?$/,
  );
  return (match?.[1] as ExercisePage) || "map";
}
function uid() {
  return crypto.randomUUID().replaceAll("-", "").slice(0, 12);
}
function split(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}
function message(reason: unknown) {
  return reason instanceof Error ? reason.message : "Something went wrong";
}
function formatDate(value?: string | null) {
  return value
    ? new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value))
    : "Time unavailable";
}
function localDateTime(value: string) {
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}
function percent(value?: number) {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}
function rehearsalRoutes(run: ExerciseRun): FeatureCollection | undefined {
  const features: GeoJSON.Feature[] = [];
  for (const result of run.payload.evaluation.missions) {
    const routes = Array.isArray(result.routes)
      ? (result.routes as {
          selected?: { feature?: GeoJSON.Feature };
          withdrawal?: { feature?: GeoJSON.Feature };
        }[])
      : [];
    for (const route of routes) {
      if (route.selected?.feature)
        features.push({
          ...route.selected.feature,
          properties: {
            ...(route.selected.feature.properties || {}),
            label: "Primary",
            status: "Planned route",
          },
        });
      if (route.withdrawal?.feature)
        features.push({
          ...route.withdrawal.feature,
          properties: {
            ...(route.withdrawal.feature.properties || {}),
            label: "Withdrawal",
            status: "Planned withdrawal",
          },
        });
    }
    const cycles = Array.isArray(result.cycles)
      ? (result.cycles as {
          source_route?: { selected?: { feature?: GeoJSON.Feature } };
          delivery_route?: { selected?: { feature?: GeoJSON.Feature } };
        }[])
      : [];
    for (const cycle of cycles) {
      if (cycle.source_route?.selected?.feature)
        features.push({
          ...cycle.source_route.selected.feature,
          properties: {
            ...(cycle.source_route.selected.feature.properties || {}),
            label: "Source leg",
            status: "Simulated water cycle",
          },
        });
      if (cycle.delivery_route?.selected?.feature)
        features.push({
          ...cycle.delivery_route.selected.feature,
          properties: {
            ...(cycle.delivery_route.selected.feature.properties || {}),
            label: "Delivery leg",
            status: "Simulated water cycle",
          },
        });
    }
  }
  return features.length
    ? ({ type: "FeatureCollection", features } as FeatureCollection)
    : undefined;
}
