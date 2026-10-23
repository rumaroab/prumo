import { PrumoBrand } from "./components/PrumoBrand";
import { AppShell } from "./components/AppShell";
import { installNavigation, navigateTo, parseRoute, rememberRun, useAppLocation, useNavigationGuard } from "./navigation";
import {
  Box,
  Button,
  ButtonLink,
  Card,
  SectionContainer,
  Typography,
} from "./components/ui";
import { formatDateTime, formatNumber, statusLabel, t } from "./locale";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { MapView } from "./components/MapView";
import { Timeline, type TimelineChangeSource } from "./components/Timeline";
import { resultLabel } from "./components/OperationsPage";
import { ScenarioManager } from "./components/ScenarioManager";
import { ScenarioWizard } from "./components/ScenarioWizard";
import { AreaSettings } from "./components/AreaSettings";
import { ManagementApp } from "./components/ManagementApp";
import { MobilityApp, SharedBrief } from "./components/MobilityApp";
import { DecisionWorkspace } from "./components/DecisionWorkspace";
import { PlanningArchive } from "./components/PlanningArchive";
import { isAbortError, useLoading } from "./loading";
import type {
  Area,
  CellSizeM,
  Comparison,
  Engine,
  FeatureCollection,
  Filter,
  FogosSnapshot,
  ObservationEvaluation,
  Page,
  PointKind,
  Run,
  ScenarioPoint,
  ScenarioWorkspace,
  SessionUser,
  WeatherSeries,
} from "./types";

type SaveState = "saved" | "saving" | "failed";
type Placement =
  | { type: "ignition"; id: string }
  | { type: "new"; kind: PointKind }
  | { type: "move"; id: string }
  | null;
type Route = { scenarioId?: string; page: Page; runId?: string };
export function ViewerApp() {
  const { begin } = useLoading();
  const appLocation = useAppLocation();
  const route = useMemo<Route>(() => { const value = parseRoute(appLocation); return { scenarioId: value.scenarioId, page: "simulation", runId: value.runId }; }, [appLocation]);
  const [area, setArea] = useState<Area>();
  const [scenarios, setScenarios] = useState<ScenarioWorkspace[]>([]);
  const [workspace, setWorkspace] = useState<ScenarioWorkspace>();
  const [runs, setRuns] = useState<Run[]>([]);
  const [engines, setEngines] = useState<Engine[]>([]);
  const [weatherSeries, setWeatherSeries] = useState<WeatherSeries[]>([]);
  const [displayed, setDisplayed] = useState<Run>();
  const [activeRun, setActiveRun] = useState<Run>();
  const [roads, setRoads] = useState<FeatureCollection>();
  const [fire, setFire] = useState<FeatureCollection>();
  const [fireMinute, setFireMinute] = useState<number>();
  const [minute, setMinute] = useState(90);
  const [forecast, setForecast] = useState(30);
  const [filter, setFilter] = useState<Filter>("all");
  const [layers, setLayers] = useState({
    fire: true,
    roads: true,
    basemap: true,
    points: true,
  });
  const [placement, setPlacement] = useState<Placement>(null);
  const [message, setMessage] = useState(t("Loading scenario…"));
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [comparison, setComparison] = useState<Comparison>();
  const [showPointsKey, setShowPointsKey] = useState(0);
  const [managing, setManaging] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editingArea, setEditingArea] = useState(false);
  const [scenariosLoaded, setScenariosLoaded] = useState(false);
  const [startupError, setStartupError] = useState("");
  const [startupAttempt, setStartupAttempt] = useState(0);
  const [readError, setReadError] = useState("");
  const [readRetry, setReadRetry] = useState(0);
  const [fogosLayerData, setFogosLayerData] = useState<
    Record<string, FeatureCollection>
  >({});
  const [fogosLayerEnabled, setFogosLayerEnabled] = useState<
    Record<string, boolean>
  >({});
  const [fogosLayerError, setFogosLayerError] = useState("");
  const [observationLayer, setObservationLayer] = useState<FeatureCollection>();

  const selectedSources = useRef<Record<string, string | undefined>>({});
  if (route.scenarioId)
    selectedSources.current[`${route.scenarioId}/${route.page}`] = route.runId;
  const currentRoute = useRef(route);
  currentRoute.current = route;

  const workspaceRef = useRef<ScenarioWorkspace | null>(null);
  const serverRevision = useRef(0);
  const editVersion = useRef(0);
  const savedVersion = useRef(0);
  const saveTimer = useRef<number | null>(null);
  const activeSave = useRef<Promise<ScenarioWorkspace> | null>(null);
  const lastFireKey = useRef("");
  const playbackMinute = useRef(false);
  const retryRoute = useRef<Route | null>(null);

  const navigate = useCallback((scenarioId: string, page: Page, runId?: string, replace = false) => {
    selectedSources.current[`${scenarioId}/${page}`] = runId;
    setPlacement(null);
    void navigateTo(`/scenarios/${scenarioId}/${page}${runId ? `?run=${encodeURIComponent(runId)}` : ""}`, replace);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const finish = begin(t("Starting PRUMO…"));
    setStartupError("");
    Promise.all([
      api.area(controller.signal),
      api.engines(controller.signal),
      api.scenarios(controller.signal),
      api.weather(controller.signal),
    ])
      .then(([areaData, engineData, scenarioData, weather]) => {
        setArea(areaData);
        setEngines(engineData);
        setScenarios(scenarioData);
        setWeatherSeries(weather);
        setScenariosLoaded(true);
        const valid = scenarioData.some((item) => item.id === route.scenarioId);
        if (!valid)
          setReadError(t("This scenario is unavailable or has been deleted."));
      })
      .catch((error) => {
        if (!isAbortError(error)) {
          setStartupError(
            error instanceof Error
              ? error.message
              : "Unable to start the workspace",
          );
          setMessage(
            error instanceof Error
              ? error.message
              : "Unable to start the workspace",
          );
        }
      })
      .finally(finish);
    return () => {
      controller.abort();
      finish();
    };
  }, [startupAttempt, begin, navigate]);

  const fetchLayers = useCallback(
    async (run: Run, openingMinute: number, signal?: AbortSignal) => {
      const [roadData, fireData] = await Promise.all([
        api.roads(run.id, run.scenario.exposure_buffer_m, signal),
        api.fire(run.id, openingMinute, signal),
      ]);
      return { roadData, fireData };
    },
    [],
  );

  const show = useCallback(
    async (run: Run, signal?: AbortSignal) => {
      if (!["ready", "partial"].includes(run.status)) return;
      const openingMinute = Math.min(90, run.scenario.duration_min);
      let target = run;
      let summary: Comparison | undefined;
      if (run.mode === "engine_comparison") {
        const [children, comparisonData] = await Promise.all([
          api.children(run.id, signal),
          api.comparison(run.id, openingMinute, signal),
        ]);
        const ready = children.find((child) => child.status === "ready");
        if (!ready)
          throw new Error(t("No comparison member completed successfully"));
        target = ready;
        summary = comparisonData;
      }
      const { roadData, fireData } = await fetchLayers(
        target,
        openingMinute,
        signal,
      );
      if (signal?.aborted) return;
      setDisplayed(run);
      setMinute(openingMinute);
      setActiveRun(target);
      setRoads(roadData);
      setFire(fireData);
      setFireMinute(openingMinute);
      setComparison(summary);
      lastFireKey.current = `${target.id}/${openingMinute}`;
      if (summary)
        setMessage(
          `${summary.members.length} motores comparados${summary.failed.length ? ` · ${summary.failed.length} falharam` : ""}`,
        );
      else {
        const resolution = run.result?.temporal_resolution_min;
        setMessage(
          run.mode === "parameter_ensemble"
            ? `${run.successful_members}/${run.expected_members} simulações do conjunto${resolution ? ` · resolução de ${resolution} min` : ""}`
            : run.scenario.name.startsWith(t("Extreme showcase"))
              ? t("Extreme synthetic showcase · not a forecast")
              : `${run.result?.engine || t("Model result")}${resolution ? ` · resolução de ${resolution} min` : ""}`,
        );
      }
    },
    [fetchLayers],
  );

  useEffect(() => {
    if (!route.scenarioId) return;
    const controller = new AbortController();
    const finish = begin(t("Loading scenario…"));
    Promise.all([
      api.scenario(route.scenarioId, controller.signal),
      api.scenarioRuns(route.scenarioId, controller.signal),
    ])
      .then(async ([item, history]) => {
        if (controller.signal.aborted) return;
        if (item.scenario_kind === "exercise" && route.page !== "simulation") {
          const destination =
            route.page === "water-planning"
              ? "resources?panel=water"
              : `map${route.runId ? `?run=${encodeURIComponent(route.runId)}` : ""}`;
          window.location.replace(`/scenarios/${item.id}/${destination}`);
          return;
        }
        item.closures ||= [];
        item.teams ||= [];
        item.resource_groups ||= [];
        item.containment_tasks ||= [];
        item.allocation_plans ||= [];
        const areaData = await api.area(
          controller.signal,
          item.area_package_id,
        );
        if (controller.signal.aborted) return;
        setArea(areaData);
        workspaceRef.current = item;
        serverRevision.current = item.revision;
        editVersion.current = 0;
        savedVersion.current = 0;
        setWorkspace(item);
        setRuns(history);
        setSaveState("saved");
        setPlacement(null);
        setFogosLayerData({});
        setFogosLayerEnabled({});
        setFogosLayerError("");
        setObservationLayer(undefined);
        const requestedResult =
          route.page === "simulation" && Boolean(route.runId);
        const selected = requestedResult
          ? history.find(
              (run) =>
                run.id === route.runId &&
                ["ready", "partial"].includes(run.status),
            )
          : history.find((run) => ["ready", "partial"].includes(run.status));
        const preparedRoads = api
          .areaRoads(item.area_id, controller.signal)
          .catch(() => undefined);
        if (requestedResult && !selected) {
          await preparedRoads;
          setDisplayed(undefined);
          setActiveRun(undefined);
          setRoads(undefined);
          setFire(undefined);
          setReadError(
            t("This result is unavailable, unfinished, or has been deleted."),
          );
        } else if (selected) {
          if (route.page === "simulation" && selected.id !== route.runId)
            navigate(item.id, "simulation", selected.id, true);
          await Promise.all([show(selected, controller.signal), preparedRoads]);
        } else {
          const prepared = await preparedRoads;
          setDisplayed(undefined);
          setActiveRun(undefined);
          setRoads(undefined);
          setFire(undefined);
          setMessage(t("Scenario has no completed simulation yet"));
          setRoads(prepared);
        }
      })
      .catch(async (error) => {
        if (controller.signal.aborted || isAbortError(error)) return;
        const failure =
          error instanceof Error ? error.message : "Unable to load scenario";
        setMessage(failure);
        setReadError(failure);
        retryRoute.current = { ...route };
        try {
          const available = await api.scenarios();
          if (controller.signal.aborted) return;
          setScenarios(available);
          if (!available.some((item) => item.id === route.scenarioId)) {
            workspaceRef.current = null;
            setWorkspace(undefined);
            setReadError(
              t("This scenario is unavailable or has been deleted."),
            );
          }
        } catch {
          /* Keep the original load error visible. */
        }
      })
      .finally(finish);
    return () => {
      controller.abort();
      finish();
    };
  }, [route.scenarioId, readRetry, begin, navigate, show]);

  useEffect(() => {
    if (
      route.page !== "simulation" ||
      !route.runId ||
      !runs.length ||
      displayed?.id === route.runId
    )
      return;
    const selected = runs.find((run) => run.id === route.runId);
    if (!selected) return;
    const controller = new AbortController();
    const finish = begin(t("Loading simulation result…"));
    show(selected, controller.signal)
      .catch((error) => {
        if (!isAbortError(error)) {
          const failure =
            error instanceof Error
              ? error.message
              : "Unable to load simulation result";
          setMessage(failure);
          setReadError(failure);
          retryRoute.current = { ...route };
          if (displayed)
            navigate(route.scenarioId!, "simulation", displayed.id, true);
        }
      })
      .finally(finish);
    return () => {
      controller.abort();
      finish();
    };
  }, [
    route.page,
    route.runId,
    runs,
    displayed?.id,
    show,
    begin,
    navigate,
    readRetry,
  ]);

  useEffect(() => {
    if (!activeRun) return;
    const key = `${activeRun.id}/${minute}`;
    if (lastFireKey.current === key) return;
    const quiet = playbackMinute.current;
    playbackMinute.current = false;
    const controller = new AbortController();
    const finish = quiet ? () => {} : begin(t("Updating map…"));
    const comparisonRequest =
      displayed?.mode === "engine_comparison"
        ? api.comparison(displayed.id, minute, controller.signal)
        : Promise.resolve(undefined);
    Promise.all([
      api.fire(activeRun.id, minute, controller.signal),
      comparisonRequest,
    ])
      .then(([fireData, comparisonData]) => {
        if (controller.signal.aborted) return;
        setFire(fireData);
        setFireMinute(minute);
        if (comparisonData) setComparison(comparisonData);
        lastFireKey.current = key;
      })
      .catch((error) => {
        if (!isAbortError(error)) {
          const failure =
            error instanceof Error ? error.message : "Unable to update map";
          setMessage(failure);
          setReadError(failure);
          retryRoute.current = { ...route };
        }
      })
      .finally(finish);
    return () => {
      controller.abort();
      finish();
    };
  }, [activeRun, minute, displayed?.id, displayed?.mode, begin, readRetry]);

  const saveNow = useCallback(async (): Promise<ScenarioWorkspace> => {
    if (saveTimer.current !== null) {
      window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
    }
    if (activeSave.current) await activeSave.current;
    const current = workspaceRef.current;
    if (!current) throw new Error("Scenario is not loaded");
    if (savedVersion.current === editVersion.current) return current;
    const version = editVersion.current;
    setSaveState("saving");
    const request = api.saveScenario(current, serverRevision.current);
    activeSave.current = request;
    try {
      const saved = await request;
      serverRevision.current = saved.revision;
      savedVersion.current = version;
      if (version === editVersion.current) {
        workspaceRef.current = saved;
        setWorkspace(saved);
        setSaveState("saved");
      } else if (workspaceRef.current) {
        workspaceRef.current = {
          ...workspaceRef.current,
          revision: saved.revision,
        };
        setWorkspace(workspaceRef.current);
      }
      setScenarios((items) =>
        items.map((item) =>
          item.id === saved.id ? workspaceRef.current || saved : item,
        ),
      );
    } catch (error) {
      setSaveState("failed");
      setMessage(
        error instanceof Error ? error.message : "Scenario save failed",
      );
      throw error;
    } finally {
      activeSave.current = null;
    }
    if (savedVersion.current < editVersion.current) return saveNow();
    return workspaceRef.current!;
  }, []);

  useNavigationGuard(async () => { if (workspaceRef.current) await saveNow(); }, saveState !== "saved");
  useEffect(() => { if (route.scenarioId && displayed) rememberRun(route.scenarioId, displayed.id); }, [route.scenarioId, displayed?.id]);

  const editWorkspace = useCallback(
    (change: (current: ScenarioWorkspace) => ScenarioWorkspace) => {
      if (!workspaceRef.current) return;
      const next = change(workspaceRef.current);
      next.simulation = { ...next.simulation, name: next.name };
      workspaceRef.current = next;
      editVersion.current += 1;
      setWorkspace(next);
      setSaveState("saving");
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(() => {
        void saveNow().catch(() => {});
      }, 600);
    },
    [saveNow],
  );

  async function uploadWeather(file: File) {
    const finish = begin(t("Uploading and validating weather…"));
    try {
      const uploaded = await api.uploadWeather(file);
      setWeatherSeries((current) => [uploaded, ...current]);
      editWorkspace((current) => ({
        ...current,
        simulation: {
          ...current.simulation,
          weather_source: { kind: "series", id: uploaded.id },
        },
      }));
      setMessage(`Meteorologia validada · ${uploaded.rows} observações`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Weather upload failed",
      );
    } finally {
      finish();
    }
  }

  async function selectComparison(runId: string) {
    if (!displayed) return;
    const controller = new AbortController();
    const finish = begin(t("Loading engine result…"));
    try {
      const children = await api.children(displayed.id, controller.signal);
      const target = children.find((child) => child.id === runId);
      if (target) {
        const { roadData, fireData } = await fetchLayers(
          target,
          minute,
          controller.signal,
        );
        setRoads(roadData);
        setFire(fireData);
        setActiveRun(target);
        lastFireKey.current = `${target.id}/${minute}`;
      }
    } catch (error) {
      if (!isAbortError(error))
        setMessage(
          error instanceof Error
            ? error.message
            : "Unable to load engine result",
        );
    } finally {
      finish();
    }
  }

  function place(position: [number, number]) {
    if (!placement) return;
    if (placement.type === "ignition")
      editWorkspace((current) => ({
        ...current,
        simulation: {
          ...current.simulation,
          ignitions: current.simulation.ignitions.map((item) =>
            item.id === placement.id
              ? { ...item, coordinates: position }
              : item,
          ),
        },
      }));
    if (placement.type === "new")
      editWorkspace((current) => ({
        ...current,
        points: [...current.points, newPoint(placement.kind, position)],
      }));
    if (placement.type === "move")
      editWorkspace((current) => ({
        ...current,
        points: current.points.map((point) =>
          point.id === placement.id
            ? { ...point, coordinates: position }
            : point,
        ),
      }));
    setPlacement(null);
  }

  async function createNewScenario() {
    try {
      if (workspaceRef.current) await saveNow();
      setCreating(true);
    } catch {
      /* saveNow already exposes the error */
    }
  }

  function scenarioCreated(created: ScenarioWorkspace) {
    setCreating(false);
    setScenarios((current) => [...current, created]);
    if (created.setup_complete)
      void navigateTo(`/scenarios/${created.id}/experiments/new`);
    else navigate(created.id, "simulation");
  }

  async function applyArea(
    packageId: string,
    values: {
      center: [number, number];
      resourceRadius: 10 | 25 | 50;
      fireMargin: 5 | 10 | 25;
      cellSize: CellSizeM;
    },
  ) {
    editWorkspace((current) => ({
      ...current,
      area_id: packageId,
      area_package_id: packageId,
      resource_center: values.center,
      resource_radius_km: values.resourceRadius,
      fire_margin_km: values.fireMargin,
      cell_size_m: values.cellSize,
    }));
    const saved = await saveNow();
    const [areaData, preparedRoads] = await Promise.all([
      api.area(undefined, packageId),
      api.areaRoads(packageId),
    ]);
    setArea(areaData);
    setRoads(preparedRoads);
    setFire(undefined);
    setMessage(
      `Área preparada aplicada · revisão ${saved.revision} da ocorrência`,
    );
  }

  async function selectScenario(id: string) {
    const finish = begin(t("Loading scenario…"));
    try {
      await saveNow();
      navigate(id, route.page, selectedSources.current[`${id}/${route.page}`]);
    } catch {
      /* saveNow already exposes the error */
    } finally {
      finish();
    }
  }

  async function openManager() {
    const finish = begin(t("Loading scenarios…"));
    try {
      if (workspaceRef.current) await saveNow();
      setScenarios(await api.scenarios());
      setManaging(true);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Unable to manage scenarios",
      );
    } finally {
      finish();
    }
  }

  async function renameScenario(scenario: ScenarioWorkspace, name: string) {
    const finish = begin(t("Renaming scenario…"));
    try {
      const saved = await api.renameScenario(
        scenario.id,
        name,
        scenario.revision,
      );
      setScenarios((items) =>
        items.map((item) => (item.id === saved.id ? saved : item)),
      );
      if (workspaceRef.current?.id === saved.id) {
        workspaceRef.current = saved;
        serverRevision.current = saved.revision;
        setWorkspace(saved);
        setSaveState("saved");
      }
    } finally {
      finish();
    }
  }

  async function deleteScenario(scenario: ScenarioWorkspace) {
    const finish = begin(t("Deleting scenario…"));
    try {
      await api.deleteScenario(scenario.id, scenario.revision);
      const remaining = scenarios.filter((item) => item.id !== scenario.id);
      setScenarios(remaining);
      for (const key of Object.keys(selectedSources.current)) {
        if (key.startsWith(`${scenario.id}/`))
          delete selectedSources.current[key];
      }
      if (workspaceRef.current?.id === scenario.id) {
        if (saveTimer.current !== null) {
          window.clearTimeout(saveTimer.current);
          saveTimer.current = null;
        }
        workspaceRef.current = null;
        setWorkspace(undefined);
        setRuns([]);
        setDisplayed(undefined);
        setActiveRun(undefined);
        setRoads(undefined);
        setFire(undefined);
        setComparison(undefined);
        setMessage(t("Loading scenario…"));
        if (remaining[0])
          navigate(remaining[0].id, route.page, undefined, true);
        else {
          void navigateTo("/scenarios", true);
        }
      }
    } finally {
      finish();
    }
  }

  const manager = managing && (
    <ScenarioManager
      scenarios={scenarios}
      currentId={route.scenarioId}
      onRename={renameScenario}
      onDelete={deleteScenario}
      onClose={() => setManaging(false)}
    />
  );

  if (startupError && !area)
    return (
      <Card
        density="compact"
        shadow="none"
        className="startup-error"
        role="alert"
      >
        <Typography as="span" variant="label" className="eyebrow">
          <PrumoBrand />
        </Typography>
        <Typography as="h1" variant="h3">
          {t("Unable to load the workspace")}
        </Typography>
        <Typography as="p" variant="body">
          {t(startupError)}
        </Typography>
        <Button
          variant="secondary"
          onClick={() => setStartupAttempt((value) => value + 1)}
        >
          {t("Try again")}
        </Button>
      </Card>
    );
  const wizard = creating && (
    <ScenarioWizard
      onCreated={scenarioCreated}
      onClose={scenarios.length ? () => setCreating(false) : undefined}
    />
  );
  const areaEditor = editingArea && workspace && (
    <AreaSettings
      workspace={workspace}
      onApply={applyArea}
      onClose={() => setEditingArea(false)}
    />
  );
  if (scenariosLoaded && !scenarios.length)
    return (
      <Card density="compact" shadow="none" className="empty-scenarios">
        <Typography as="span" variant="label" className="eyebrow">
          <PrumoBrand />
        </Typography>
        <Typography as="h1" variant="h3">
          {t("No scenarios yet")}
        </Typography>
        <Typography as="p" variant="body">
          {t(
            "Create a scenario to configure a fire simulation and prepare your operational points.",
          )}
        </Typography>
        <Button variant="secondary" onClick={createNewScenario}>
          {t("Create scenario")}
        </Button>
        {message !== t("Loading scenario…") && (
          <Typography as="p" variant="body" role="status">
            {t(message)}
          </Typography>
        )}
        {manager}
        {wizard}
        {areaEditor}
      </Card>
    );
  if ((!workspace || !area) && readError)
    return (
      <Card
        density="compact"
        shadow="none"
        className="startup-error"
        role="alert"
      >
        <Typography as="span" variant="label" className="eyebrow">
          {t("Viewer unavailable")}
        </Typography>
        <Typography as="h1" variant="h1">
          {t("Cannot open this link")}
        </Typography>
        <Typography as="p" variant="body">
          {t(readError)}
        </Typography>
        <ButtonLink variant="secondary" href="/scenarios">
          {t("Return to scenarios")}
        </ButtonLink>
      </Card>
    );
  if (!workspace || !area)
    return (
      <>
        <Box className="loading-screen">
          <span className="pulse" />
          {t(message)}
        </Box>
        {manager}
        {wizard}
        {areaEditor}
      </>
    );

  function openResult(id?: string, page = route.page) {
    if (!workspace) return;
    const finish = begin(t("Loading simulation result…"));
    requestAnimationFrame(() => {
      navigate(workspace.id, page, id);
      finish();
    });
  }

  function updateMap(action: () => void) {
    const finish = begin(t("Updating map…"));
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

  function retryReads() {
    const target = retryRoute.current;
    setReadError("");
    setReadRetry((value) => value + 1);
    if (
      target?.scenarioId &&
      (target.scenarioId !== route.scenarioId ||
        target.page !== route.page ||
        target.runId !== route.runId)
    ) {
      navigate(target.scenarioId, target.page, target.runId);
    }
  }

  async function toggleFogosLayer(layer: string, enabled: boolean) {
    setFogosLayerEnabled((values) => ({ ...values, [layer]: enabled }));
    if (!enabled || fogosLayerData[layer] || !workspace) return;
    setFogosLayerError("");
    try {
      const value = await api.fogosLayer(
        workspace.id,
        layer as
          | "perimeter"
          | "pyrocast"
          | "aircraft"
          | "icnf"
          | "vost"
          | "firms",
      );
      const collection = asFeatureCollection(value);
      if (!collection)
        throw new Error("This Fogos.pt product has no displayable geometry.");
      setFogosLayerData((values) => ({ ...values, [layer]: collection }));
    } catch (reason) {
      setFogosLayerEnabled((values) => ({ ...values, [layer]: false }));
      setFogosLayerError(
        reason instanceof Error ? reason.message : "Fogos.pt layer unavailable",
      );
    }
  }

  const duration =
    displayed?.scenario.duration_min || workspace.simulation.duration_min;
  const [west, south, east, north] = area.fire_bounds || area.bounds;
  const mapBounds: [[number, number], [number, number]] = [
    [south, west],
    [north, east],
  ];
  // Operational edits change the workspace revision, but do not invalidate fire inputs.
  const stale =
    displayed &&
    Object.keys(workspace.simulation).some(
      (key) =>
        key !== "name" &&
        JSON.stringify(
          workspace.simulation[key as keyof typeof workspace.simulation],
        ) !==
          JSON.stringify(
            displayed.scenario[key as keyof typeof displayed.scenario],
          ),
    );
  const warnings = resultWarnings(activeRun || displayed);
  return (
    <Box className={`app-frame${route.page === "simulation" ? " simulation-frame" : ""}`}>
      {wizard}
      {areaEditor}
      <ViewerContextBar displayed={displayed} saveState={saveState} />
      {manager}
      {readError && (
        <Box className="load-error" role="alert">
          <span>{t(readError)}</span>
          <Button variant="secondary" onClick={retryReads}>
            {t("Try again")}
          </Button>
        </Box>
      )}
      {route.page === "simulation" && stale && (
        <Box className="revision-banner">
          {t(
            "Simulation inputs have changed since this result. Run the simulation to generate an updated output.",
          )}
        </Box>
      )}
      {route.page === "simulation" ? (
        <main className="workspace-page simulation-page">
          <Box className="control-column">
            <ViewerControls
              workspace={workspace}
              runs={runs}
              displayed={displayed}
              filter={filter}
              layers={layers}
              onResult={(id) => openResult(id)}
              onFilter={(value) => updateMap(() => setFilter(value))}
              onLayer={(layer, value) =>
                updateMap(() =>
                  setLayers((current) => ({ ...current, [layer]: value })),
                )
              }
            />
            {displayed && (
              <Card
                as="section"
                density="compact"
                shadow="none"
                className="result-handoff panel"
              >
                <Typography as="span" variant="label" className="eyebrow">
                  {t("Modeled result")}
                </Typography>
                <Typography as="p" variant="body">
                  {resultLabel(displayed)}
                </Typography>
                <a
                  href={`/scenarios/${workspace.id}/decisions${displayed.mode === "single" ? `?run=${encodeURIComponent(displayed.id)}` : ""}`}
                >
                  Comparar decisões de mobilidade
                </a>
              </Card>
            )}
            {workspace.external_incident && (
              <FogosLayersPanel
                scenarioId={workspace.id}
                enabled={fogosLayerEnabled}
                error={fogosLayerError}
                onToggle={toggleFogosLayer}
              />
            )}
            {workspace.external_incident && activeRun && (
              <ObservationComparisonPanel
                workspace={workspace}
                run={activeRun}
                onObservation={(value, alignedMinute) => {
                  setObservationLayer(value);
                  if (alignedMinute != null)
                    setMinute(
                      Math.max(
                        0,
                        Math.min(duration, Math.round(alignedMinute)),
                      ),
                    );
                }}
              />
            )}
          </Box>
          <section className={placement ? "map-shell placing" : "map-shell"}>
            <MapView
              key={activeRun?.id || "draft"}
              bounds={mapBounds}
              scenario={
                placement?.type === "ignition"
                  ? workspace.simulation
                  : activeRun?.scenario || workspace.simulation
              }
              points={[]}
              showPointsKey={showPointsKey}
              roads={roads}
              fire={fire}
              minute={minute}
              forecast={Math.min(forecast, Math.max(0, duration - minute))}
              filter={filter}
              placing={Boolean(placement)}
              showFire={layers.fire}
              showRoads={layers.roads}
              showBasemap={layers.basemap}
              showPoints={false}
              onIgnition={place}
              externalLayers={[
                ...Object.entries(fogosLayerData)
                  .filter(([key]) => fogosLayerEnabled[key])
                  .map(([id, data]) => ({
                    id,
                    label: fogosLayerLabel(id),
                    data,
                  })),
                ...(observationLayer
                  ? [
                      {
                        id: "perimeter",
                        label: "Observação MTG arquivada selecionada",
                        data: observationLayer,
                      },
                    ]
                  : []),
              ]}
            />
            <Box className="status">
              <span className="dot" />
              {t(message)}
            </Box>
            {comparison && (
              <Card
                density="compact"
                shadow="none"
                className="comparison panel"
              >
                <strong>
                  {t("Engine comparison ·")} {comparison.minute} min
                </strong>
                {comparison.members.map((member) => (
                  <Button
                    variant="secondary"
                    aria-pressed={activeRun?.id === member.run_id}
                    className={activeRun?.id === member.run_id ? "active" : ""}
                    key={member.run_id}
                    onClick={() => selectComparison(member.run_id)}
                  >
                    <span>{member.engine_label}</span>
                    <Typography as="small" variant="small">
                      {formatNumber(member.burned_area_ha)} ha ·{" "}
                      {member.exposed_roads} estradas ·{" "}
                      {member.temporal_resolution_min} {t("min resolution ·")}{" "}
                      {Math.round(member.runtime_seconds)} {t("s runtime")}
                    </Typography>
                  </Button>
                ))}
                {comparison.failed.map((member) => (
                  <Typography
                    as="small"
                    variant="small"
                    className="failure"
                    key={member.run_id}
                  >
                    {member.engine}: {statusLabel(member.status)}
                    {member.error ? ` · ${member.error}` : ""}
                  </Typography>
                ))}
                {comparison.agreements.map((value) => (
                  <Typography
                    as="small"
                    variant="small"
                    className="agreement"
                    key={`${value.left}-${value.right}`}
                  >
                    {value.left} / {value.right}:{" "}
                    {Math.round(value.jaccard * 100)}
                    {t("% area agreement")}
                  </Typography>
                ))}
              </Card>
            )}
            <Card density="compact" shadow="none" className="legend panel">
              {displayed?.mode === "parameter_ensemble" ? (
                <>
                  <strong>{t("Fire reach probability")}</strong>
                  <span>
                    <i className="probability high" />
                    {t("90% or more")}
                  </span>
                  <span>
                    <i className="probability medium" />
                    {t("50% or more")}
                  </span>
                  <span>
                    <i className="probability low" />
                    {t("10% or more")}
                  </span>
                  <Typography as="small" variant="small">
                    {t(
                      "Warmer areas indicate greater ensemble agreement. Road popups include P10/P50/P90 arrival.",
                    )}
                  </Typography>
                </>
              ) : (
                <>
                  <strong>{t("Simulation layers")}</strong>
                  <span>
                    <i className="fire-gradient" />
                    {t("Simulated fire extent")}
                  </span>
                  <span>
                    <i className="red" />
                    {t("Road reached by selected time")}
                  </span>
                  <span>
                    <i className="amber forecast-line" />
                    {t("Forecast within +")}
                    {forecast} min
                  </span>
                  <span>
                    <i className="grey" />
                    {t("Road not reached in run")}
                  </span>
                  <Typography as="small" variant="small">
                    {t("Model output · not a confirmed road closure")}
                  </Typography>
                </>
              )}
            </Card>
            <Box className="map-bottom">
              {warnings.length > 0 && (
                <Card
                  density="compact"
                  shadow="none"
                  className="result-warnings panel"
                >
                  <strong>{t("Model notes")}</strong>
                  {warnings.map((value) => (
                    <Typography as="small" variant="small" key={value}>
                      {t(value)}
                    </Typography>
                  ))}
                </Card>
              )}
              <Timeline
                minute={minute}
                duration={duration}
                forecast={forecast}
                frameReady={!activeRun || fireMinute === minute}
                pauseSignal={t(readError)}
                onMinute={updateMinute}
                onForecast={(value) => updateMap(() => setForecast(value))}
              />
            </Box>
          </section>
        </main>
      ) : (
        <PlanningArchive scenarioId={workspace.id} />
      )}
    </Box>
  );
}

function ViewerContextBar(props: { displayed?: Run; saveState: SaveState }) {
  return <div className="workspace-context" aria-label="Contexto do resultado">
    <span>Resultado: {props.displayed?.name || "Área preparada"}</span>
    <span role="status">{props.saveState === "saving" ? "A guardar…" : props.saveState === "failed" ? "Falha ao guardar" : "Guardado"}</span>
  </div>;
}

function ViewerControls(props: {
  workspace: ScenarioWorkspace;
  runs: Run[];
  displayed?: Run;
  filter: Filter;
  layers: { fire: boolean; roads: boolean; basemap: boolean; points: boolean };
  onResult: (id: string) => void;
  onFilter: (value: Filter) => void;
  onLayer: (
    layer: "fire" | "roads" | "basemap" | "points",
    value: boolean,
  ) => void;
}) {
  return (
    <Card
      as="aside"
      density="compact"
      shadow="none"
      className="panel controls viewer-controls"
    >
      <Box className="tool-intro">
        <Typography as="span" variant="label" className="eyebrow">
          {t("Result workspace")}
        </Typography>
        <Typography as="h1" variant="h1">
          Análise do resultado
        </Typography>
        <Typography as="p" variant="body">
          {t(
            "Inspect an immutable simulation output and its modelled road exposure.",
          )}
        </Typography>
      </Box>
      <section className="first">
        <Typography as="h2" variant="h3">
          {t("Result")}
        </Typography>
        <label>
          {t("Experiment")}
          <select
            value={props.displayed?.id || ""}
            onChange={(event) => props.onResult(event.target.value)}
          >
            <option value="">{t("Prepared scenario")}</option>
            {props.runs.map((run) => (
              <option
                key={run.id}
                value={run.id}
                disabled={!["ready", "partial"].includes(run.status)}
              >
                {run.name || resultLabel(run)}
              </option>
            ))}
          </select>
        </label>
        {props.displayed && (
          <Typography as="p" variant="small" className="empty-note">
            {props.displayed.notes ||
              `${props.displayed.scenario.engine} · ${props.displayed.scenario.duration_min} minutes`}
          </Typography>
        )}
      </section>
      <section>
        <Typography as="h2" variant="h3">
          {t("Road filter")}
        </Typography>
        {[
          ["all", t("All roads")],
          ["now", t("Affected now")],
          ["upcoming", t("Newly affected within X")],
          ["by-then", t("All affected by then")],
          ["not-reached", t("Not reached in run")],
          ["unknown", "Cobertura desconhecida"],
        ].map(([value, label]) => (
          <label className="radio" key={value}>
            <input
              type="radio"
              name="viewer-filter"
              checked={props.filter === value}
              onChange={() => props.onFilter(value as Filter)}
            />
            {label}
          </label>
        ))}
      </section>
      <section>
        <Typography as="h2" variant="h3">
          {t("Layers")}
        </Typography>
        {(
          [
            ["fire", t("Area reached by fire")],
            ["roads", t("Roads")],
            ["basemap", t("Basemap")],
          ] as const
        ).map(([key, label]) => (
          <label className="toggle" key={key}>
            <input
              type="checkbox"
              checked={props.layers[key]}
              onChange={(event) => props.onLayer(key, event.target.checked)}
            />
            <span />
            {label}
          </label>
        ))}
      </section>
      <ButtonLink
        variant="secondary"
        className="viewer-manage-link"
        href={`/scenarios/${props.workspace.id}`}
      >
        {t("Manage scenario and experiments")}
      </ButtonLink>
    </Card>
  );
}

function FogosLayersPanel({
  scenarioId,
  enabled,
  error,
  onToggle,
}: {
  scenarioId: string;
  enabled: Record<string, boolean>;
  error: string;
  onToggle: (layer: string, enabled: boolean) => void;
}) {
  const [weather, setWeather] = useState<Record<string, unknown>>();
  const [risk, setRisk] = useState<Record<string, unknown>>();
  const [contextError, setContextError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api
      .fogosLayer(scenarioId, "weather", controller.signal)
      .then((value) => setWeather(value as Record<string, unknown>))
      .catch((reason) =>
        setContextError(
          reason instanceof Error ? reason.message : "Context unavailable",
        ),
      );
    return () => controller.abort();
  }, [scenarioId]);
  const observation = weather?.weather as
    | Record<string, unknown>
    | null
    | undefined;
  const warnings = Array.isArray(weather?.warnings) ? weather.warnings : [];
  const riskData = risk?.data as Record<string, unknown> | undefined;
  const riskDates = risk?.dates as Record<string, unknown> | undefined;
  return (
    <Card
      as="details"
      density="compact"
      shadow="none"
      className="panel fogos-layers"
    >
      <summary>{t("Fogos.pt context & layers")}</summary>
      <Typography as="p" variant="body">
        {t("External evidence stays separate from the selected simulation.")}
      </Typography>
      {(
        [
          ["perimeter", t("MTG perimeter")],
          ["pyrocast", "PyroCast +1h to +6h"],
          ["aircraft", t("Recent aircraft")],
          ["icnf", t("ICNF geometry")],
          ["vost", t("VOST area")],
          ["firms", t("FIRMS hotspots")],
        ] as const
      ).map(([key, label]) => (
        <label className="toggle" key={key}>
          <input
            type="checkbox"
            checked={Boolean(enabled[key])}
            onChange={(event) => void onToggle(key, event.target.checked)}
          />
          <span />
          {label}
        </label>
      ))}
      {observation && (
        <Box className="external-context-summary">
          <strong>{t("Nearest-station weather")}</strong>
          <span>
            {String(observation.wind_speed_kmh ?? "—")} km/h ·{" "}
            {String(observation.wind_direction_deg ?? "—")}° ·{" "}
            {String(observation.temperature_c ?? "—")} °C · RH{" "}
            {String(observation.relative_humidity_pct ?? "—")}%
          </span>
          <Typography as="small" variant="small">
            {String(observation.station_name || t("Station"))} ·{" "}
            {formatExternalDate(observation.observed_at)}
          </Typography>
        </Box>
      )}
      {warnings.length > 0 && (
        <Typography as="small" variant="small">
          {warnings.length}{" "}
          {warnings.length === 1
            ? "aviso meteorológico atual"
            : "avisos meteorológicos atuais"}
          {t("; current warnings may not describe historical conditions.")}
        </Typography>
      )}
      <Button
        variant="secondary"
        onClick={() =>
          api
            .fogosLayer(scenarioId, "risk")
            .then((value) => {
              setRisk(value as Record<string, unknown>);
              setContextError("");
            })
            .catch((reason) =>
              setContextError(
                reason instanceof Error ? reason.message : "Risk unavailable",
              ),
            )
        }
      >
        {t("Load municipality fire risk")}
      </Button>
      {risk && (
        <Box className="external-context-summary">
          <strong>
            {t("Municipality risk ·")}{" "}
            {String(risk.municipality || t("Unknown municipality"))}
          </strong>
          {(["today", "tomorrow", "after"] as const).map((key) => (
            <span key={key}>
              {String(riskDates?.[key] || key)} ·{" "}
              {String(riskData?.[key] || "indisponível")}
            </span>
          ))}
          <Typography as="small" variant="small">
            {t(
              "These are current dated layers, including when the scenario itself is historical.",
            )}
          </Typography>
        </Box>
      )}
      {(error || contextError) && (
        <Typography
          role="alert"
          as="p"
          variant="small"
          className="inline-error"
        >
          {error || contextError}
        </Typography>
      )}
      <Typography as="small" variant="small">
        {t(
          "MTG is coarse satellite evidence (approximately 2–4 km). PyroCast is an external model reference. Aircraft proximity does not imply assignment or availability.",
        )}
      </Typography>
    </Card>
  );
}

function ObservationComparisonPanel({
  workspace,
  run,
  onObservation,
}: {
  workspace: ScenarioWorkspace;
  run: Run;
  onObservation: (value?: FeatureCollection, alignedMinute?: number) => void;
}) {
  const [snapshots, setSnapshots] = useState<FogosSnapshot[]>([]);
  const [evaluations, setEvaluations] = useState<ObservationEvaluation[]>([]);
  const [selected, setSelected] = useState("");
  const [observedAssumption, setObservedAssumption] = useState("");
  const [runStartAssumption, setRunStartAssumption] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const eligible = run.status === "ready" && run.mode === "single";
  useEffect(() => {
    if (!eligible) return;
    const controller = new AbortController();
    Promise.all([
      api.fogosSnapshots(workspace.id, "perimeter", controller.signal),
      api.observationEvaluations(run.id, controller.signal),
    ])
      .then(([items, saved]) => {
        setSnapshots(items);
        setEvaluations(saved);
        setSelected((value) => value || items[0]?.id || "");
      })
      .catch((reason) => {
        if (!isAbortError(reason))
          setError(
            reason instanceof Error
              ? reason.message
              : "Comparisons unavailable",
          );
      });
    return () => controller.abort();
  }, [workspace.id, run.id, eligible]);
  useEffect(() => {
    const item = snapshots.find((value) => value.id === selected);
    const geometry = asFeatureCollection(
      (item?.normalized as { geojson?: unknown } | undefined)?.geojson,
    );
    onObservation(geometry || undefined);
  }, [selected, snapshots]);
  async function compare() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const value = await api.createObservationEvaluation(
        run.id,
        selected,
        observedAssumption
          ? new Date(observedAssumption).toISOString()
          : undefined,
        runStartAssumption
          ? new Date(runStartAssumption).toISOString()
          : undefined,
      );
      setEvaluations((items) => [value, ...items]);
      onObservation(value.observation, value.metrics.aligned_minute);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Comparison failed");
    } finally {
      setBusy(false);
    }
  }
  async function compareSeries() {
    setBusy(true);
    setError("");
    try {
      const value = await api.createObservationSeries(
        run.id,
        runStartAssumption
          ? new Date(runStartAssumption).toISOString()
          : undefined,
      );
      setEvaluations((items) => [...value.created.reverse(), ...items]);
      if (!value.created.length)
        setError(
          value.skipped[0]?.reason ||
            "No archived snapshot falls within this result.",
        );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Series comparison failed",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card
      as="details"
      density="compact"
      shadow="none"
      className="panel observation-comparison"
    >
      <summary>{t("Compare with observations")}</summary>
      {!eligible ? (
        <Typography as="p" variant="body">
          {t(
            "Select a completed deterministic run or a completed engine-comparison child.",
          )}
        </Typography>
      ) : snapshots.length === 0 ? (
        <Typography as="p" variant="body">
          {t(
            "No archived MTG perimeter is available yet. Local history begins when tracking collects a perimeter.",
          )}
        </Typography>
      ) : (
        <>
          <label>
            {t("Archived MTG snapshot")}
            <select
              value={selected}
              onChange={(event) => setSelected(event.target.value)}
            >
              {snapshots.map((item) => (
                <option key={item.id} value={item.id}>
                  {formatExternalDate(item.observed_at || item.retrieved_at)} ·{" "}
                  {item.observed_at ? t("source time") : t("retrieval only")}
                </option>
              ))}
            </select>
          </label>
          {!snapshots.find((item) => item.id === selected)?.observed_at && (
            <label>
              {t("Assumed observation time")}
              <input
                type="datetime-local"
                value={observedAssumption}
                onChange={(event) => setObservedAssumption(event.target.value)}
              />
            </label>
          )}
          {!run.run_context?.scenario_start_time && (
            <label>
              {t("Assumed run start")}
              <input
                type="datetime-local"
                value={runStartAssumption}
                onChange={(event) => setRunStartAssumption(event.target.value)}
              />
            </label>
          )}
          <Box className="comparison-actions">
            <Button
              variant="secondary"
              disabled={busy || !selected}
              onClick={() => void compare()}
            >
              {t("Compare snapshot")}
            </Button>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => void compareSeries()}
            >
              {t("Compare available series")}
            </Button>
          </Box>
        </>
      )}
      {error && (
        <Typography
          role="alert"
          as="p"
          variant="small"
          className="inline-error"
        >
          {error}
        </Typography>
      )}
      {evaluations.slice(0, 5).map((value) => (
        <Card
          as="article"
          density="compact"
          shadow="none"
          className="evaluation-result"
          key={value.id}
        >
          <strong>
            {Math.round((value.metrics.intersection_over_union || 0) * 100)}
            {t("% area agreement")}
          </strong>
          <span>
            {formatExternalDate(value.observed_at)} ·{" "}
            {formatNumber(value.metrics.aligned_minute)} min
          </span>
          <dl>
            <dt>{t("Simulated")}</dt>
            <dd>{formatNumber(value.metrics.simulated_area_ha)} ha</dd>
            <dt>{t("Observed in coverage")}</dt>
            <dd>{formatNumber(value.metrics.observed_area_ha)} ha</dd>
            {value.metrics.partial &&
              value.metrics.observed_total_area_ha != null && (
                <>
                  <dt>{t("Observed total")}</dt>
                  <dd>
                    {formatNumber(value.metrics.observed_total_area_ha)} ha
                  </dd>
                </>
              )}
            <dt>{t("Difference in coverage")}</dt>
            <dd>{formatNumber(value.metrics.area_difference_ha)} ha</dd>
            <dt>{t("Boundary distance")}</dt>
            <dd>
              {value.metrics.hausdorff_distance_m == null
                ? "Omitido (comparação parcial)"
                : `${Math.round(value.metrics.hausdorff_distance_m)} m`}
            </dd>
            <dt>{t("Outside coverage")}</dt>
            <dd>
              {Math.round(
                value.metrics.observation_outside_coverage_fraction * 100,
              )}
              %
            </dd>
          </dl>
          <Typography as="small" variant="small">
            {statusLabel(value.time_basis)} ·{" "}
            {statusLabel(value.metrics.source_resolution)}
            {value.metrics.partial ? " · comparação parcial" : ""}
          </Typography>
        </Card>
      ))}
      <Typography as="small" variant="small">
        {t(
          "Agreement is with coarse satellite evidence, not ground truth. Saved scores retain their snapshots, assumptions, coverage and metric version.",
        )}
      </Typography>
    </Card>
  );
}

function asFeatureCollection(value: unknown): FeatureCollection | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as {
    type?: string;
    features?: unknown[];
    data?: unknown;
    geojson?: unknown;
  };
  if (
    candidate.type === "FeatureCollection" &&
    Array.isArray(candidate.features)
  )
    return value as FeatureCollection;
  return (
    asFeatureCollection(candidate.geojson) ||
    asFeatureCollection(candidate.data)
  );
}
function fogosLayerLabel(id: string) {
  return (
    (
      {
        perimeter: "Perímetro do satélite MTG",
        pyrocast: "Modelo externo PyroCast",
        aircraft: "Aeronaves recentes",
        icnf: "Geometria ICNF",
        vost: "Área de interesse VOST",
        firms: "Pontos quentes FIRMS",
      } as Record<string, string>
    )[id] || "Camada do Fogos.pt"
  );
}
function formatExternalDate(value: unknown) {
  return formatDateTime(typeof value === "string" ? value : null);
}

function resultWarnings(run?: Run): string[] {
  const value = run?.result?.manifest?.warnings;
  const warnings = Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
  if (run?.result?.manifest?.boundary_reached)
    warnings.unshift(
      "O incêndio alcançou o limite da área preparada. Aumente a margem e execute novamente antes de interpretar a extremidade.",
    );
  return warnings;
}


function newPoint(
  kind: PointKind,
  coordinates: [number, number],
): ScenarioPoint {
  const labels: Record<PointKind, string> = {
    response_base: "Nova base de resposta",
    water_point: "Novo ponto de água",
    asset: "Novo bem prioritário",
    hazard: "Novo perigo",
    staging_area: "Nova área de concentração",
    access_control: "Novo ponto de controlo de acesso",
    shelter: "Novo abrigo",
    delivery_point: "Novo ponto de entrega",
    custom: "Novo ponto personalizado",
  };
  return {
    id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
    kind,
    name: labels[kind],
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
          }
        : null,
    asset: kind === "asset" ? { priority: 3 } : null,
  };
}

function RoutedApp({ currentUser }: { currentUser: SessionUser }) {
  const appLocation = useAppLocation();
  const route = parseRoute(appLocation);
  useEffect(() => { if (window.location.pathname === "/") void navigateTo("/scenarios", true); }, []);
  if (route.kind === "brief") return <SharedBrief token={route.token!} />;
  const content = currentUser.role === "crew" && route.scenarioId
    ? <MobilityApp key={route.scenarioId} scenarioId={route.scenarioId} currentUser={currentUser} />
    : route.kind === "mobility" ? <MobilityApp key={route.scenarioId} scenarioId={route.scenarioId!} currentUser={currentUser} />
    : route.kind === "decisions" ? <DecisionWorkspace key={route.scenarioId} scenarioId={route.scenarioId!} currentUser={currentUser} />
    : route.kind === "archive" ? <PlanningArchive key={route.scenarioId} scenarioId={route.scenarioId!} />
    : route.kind === "simulation" ? <ViewerApp key={route.scenarioId} />
    : route.kind === "missing" ? <main className="navigation-missing"><h1>Página indisponível</h1><p>Verifique o endereço ou escolha uma área no menu.</p><a href="/scenarios">Voltar às ocorrências</a></main>
    : <ManagementApp />;
  return currentUser.role === "crew" ? content : <AppShell>{content}</AppShell>;
}

export default function App() {
  useEffect(installNavigation, []);
  const appLocation = useAppLocation();
  const publicBrief = parseRoute(appLocation).kind === "brief";
  const [user, setUser] = useState<SessionUser | null | undefined>(
    publicBrief
      ? {
          id: "public",
          username: "public",
          display_name: "Public",
          role: "crew",
        }
      : undefined,
  );
  useEffect(() => {
    const title = user === undefined ? "" : user === null ? "Iniciar sessão" : parseRoute(appLocation).title;
    document.title = title ? `${title} · PRUMO` : "PRUMO";
  }, [appLocation, user]);
  useEffect(() => {
    if (publicBrief) return;
    let active = true;
    setUser(undefined);
    api.session().then((value) => { if (active) setUser(value); }).catch(() => { if (active) setUser(null); });
    return () => { active = false; };
  }, [publicBrief]);
  if (user === undefined)
    return <main className="auth-loading">A iniciar PRUMO…</main>;
  if (user === null) return <Login onSignedIn={setUser} />;
  return <RoutedApp currentUser={user} />;
}

function Login({ onSignedIn }: { onSignedIn: (user: SessionUser) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSignedIn(await api.login(username, password));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Não foi possível iniciar sessão",
      );
      setBusy(false);
    }
  }
  return (
    <SectionContainer
      as="main"
      containerClassName="ds-stack"
      className="login-page"
    >
      <Card as="form" shadow="raised" onSubmit={(event) => void submit(event)}>
        <Typography as="span" variant="label" className="eyebrow">
          Piloto de mobilidade
        </Typography>
        <Typography as="h1" variant="h1">
          <PrumoBrand className="prumo-brand--login" />
        </Typography>
        <Typography as="p" variant="body">
          Coordenação de deslocações junto de incêndios.
        </Typography>
        <label>
          Utilizador
          <input
            autoFocus
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label>
          Palavra-passe
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error && (
          <Typography
            role="alert"
            as="p"
            variant="small"
            className="inline-error"
          >
            {error}
          </Typography>
        )}
        <Button
          variant="primary"
          type="submit"
          disabled={busy || !username || !password}
        >
          {busy ? "A entrar…" : "Entrar"}
        </Button>
      </Card>
    </SectionContainer>
  );
}
