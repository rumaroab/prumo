import { confirmDiscard, navigateTo, parseRoute, useAppLocation, useNavigationGuard } from "../navigation";
import {
  Box,
  Button,
  ButtonLink,
  Card,
  Dialog,
  PopupLayout,
  SectionContainer,
  Typography,
} from "./ui";
import {
  apiErrorMessage,
  formatDateTime,
  formatNumber,
  stageLabel,
  statusLabel,
  t,
} from "../locale";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ScenarioLoading } from "../loading";
import { api } from "../api";
import type {
  Area,
  Engine,
  ExerciseSummary,
  Filter,
  FogosContext,
  FogosIncident,
  FogosResourceChange,
  MobilityMetrics,
  Run,
  RunMode,
  ScenarioWorkspace,
  WeatherSeries,
} from "../types";
import { Controls } from "./Controls";
import { MapView } from "./MapView";
import { ScenarioWizard } from "./ScenarioWizard";
import { ResourceGroupEditor, resultLabel } from "./OperationsPage";
import { FogosImportDialog } from "./FogosImportDialog";

type ManagementRoute =
  | { kind: "list" }
  | { kind: "overview"; scenarioId: string }
  | { kind: "experiments"; scenarioId: string }
  | { kind: "new-experiment"; scenarioId: string }
  | { kind: "experiment"; scenarioId: string; runId: string };

const activeStatuses = [
  "queued",
  "preparing",
  "submitted",
  "running",
  "postprocessing",
];
const emptyMobilityMetrics: MobilityMetrics = {
  total_units: 0,
  available_units: 0,
  active_movements: 0,
  pending_road_reports: 0,
  routes_needing_review: 0,
};

export function ManagementApp() {
  const appLocation = useAppLocation();
  const route = useMemo(() => readManagementRoute(appLocation), [appLocation]);
  const [scenarios, setScenarios] = useState<ScenarioWorkspace[]>([]);
  const [workspace, setWorkspace] = useState<ScenarioWorkspace>();
  const [runs, setRuns] = useState<Run[]>([]);
  const [mobilityByScenario, setMobilityByScenario] = useState<
    Record<string, MobilityMetrics>
  >({});
  const [exerciseByScenario, setExerciseByScenario] = useState<
    Record<string, ExerciseSummary>
  >({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showSetup, setShowSetup] = useState(false);
  const workspaceRef = useRef<ScenarioWorkspace | undefined>(undefined);
  const serverRevision = useRef(0);
  const editVersion = useRef(0);
  const savedVersion = useRef(0);
  const saveTimer = useRef<number | undefined>(undefined);
  const activeSave = useRef<Promise<ScenarioWorkspace> | null>(null);
  const [saveState, setSaveState] = useState<"saved" | "saving" | "failed">(
    "saved",
  );

  const navigate = useCallback((next: ManagementRoute, replace = false) => {
    const url = next.kind === "list" ? "/scenarios" : `/scenarios/${next.scenarioId}${next.kind === "overview" ? "" : next.kind === "experiments" ? "/experiments" : next.kind === "new-experiment" ? "/experiments/new" : `/experiments/${next.runId}`}`;
    void navigateTo(url, replace);
  }, []);

  useEffect(() => {
    setLoading(true);
    setError("");
    api
      .scenarios()
      .then((values) => {
        setScenarios(values);
        void api
          .mobilityMetrics()
          .then((result) => setMobilityByScenario(result.scenarios))
          .catch(() => {});
        void api
          .exerciseSummaries()
          .then((result) => setExerciseByScenario(result.scenarios))
          .catch(() => {});
      })
      .catch((reason) => setError(message(reason)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (route.kind === "list") {
      setWorkspace(undefined);
      setRuns([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.all([
      api.scenario(route.scenarioId),
      api.scenarioRuns(route.scenarioId),
      api.mobilityMetrics().catch(() => undefined),
    ])
      .then(([scenario, history, mobility]) => {
        if (cancelled) return;
        workspaceRef.current = scenario;
        serverRevision.current = scenario.revision;
        editVersion.current = 0;
        savedVersion.current = 0;
        setWorkspace(scenario);
        setRuns(history);
        setSaveState("saved");
        if (mobility) setMobilityByScenario(mobility.scenarios);
        if (
          route.kind === "experiment" &&
          !history.some((run) => run.id === route.runId)
        )
          setError(t("This experiment is unavailable or has been deleted."));
      })
      .catch((reason) => {
        if (!cancelled) setError(message(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [route]);

  useEffect(() => {
    if (
      route.kind === "list" ||
      !runs.some((run) => activeStatuses.includes(run.status))
    )
      return;
    const timer = window.setInterval(
      () =>
        api
          .scenarioRuns(route.scenarioId)
          .then(setRuns)
          .catch(() => {}),
      1200,
    );
    return () => window.clearInterval(timer);
  }, [route, runs]);

  const saveNow = useCallback(async () => {
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    if (activeSave.current) await activeSave.current;
    const current = workspaceRef.current;
    if (!current || savedVersion.current === editVersion.current)
      return current;
    const version = editVersion.current;
    setSaveState("saving");
    const request = api.saveScenario(current, serverRevision.current);
    activeSave.current = request;
    try {
      const saved = await request;
      serverRevision.current = saved.revision;
      savedVersion.current = version;
      const latest = workspaceRef.current;
      const merged =
        latest && editVersion.current > version
          ? { ...latest, revision: saved.revision }
          : saved;
      workspaceRef.current = merged;
      setWorkspace(merged);
      setSaveState(editVersion.current > version ? "saving" : "saved");
      setScenarios((values) =>
        values.map((value) => (value.id === saved.id ? merged : value)),
      );
    } catch (reason) {
      setSaveState("failed");
      setError(message(reason));
      throw reason;
    } finally {
      activeSave.current = null;
    }
    if (savedVersion.current < editVersion.current) return saveNow();
    return workspaceRef.current;
  }, []);

  useNavigationGuard(async () => { if (workspaceRef.current) await saveNow(); }, saveState !== "saved");

  const editWorkspace = useCallback(
    (change: (current: ScenarioWorkspace) => ScenarioWorkspace) => {
      if (!workspaceRef.current) return;
      const next = change(workspaceRef.current);
      next.simulation = { ...next.simulation, name: next.name };
      workspaceRef.current = next;
      editVersion.current += 1;
      setWorkspace(next);
      setSaveState("saving");
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(
        () => void saveNow().catch(() => {}),
        600,
      );
    },
    [saveNow],
  );

  if (loading && (route.kind !== "list" || !scenarios.length))
    return (
      <ScenarioLoading
        label={t(route.kind === "list" ? "Loading scenarios…" : "Loading scenario…")}
      />
    );
  if (route.kind === "list")
    return (
      <ScenarioList
        scenarios={scenarios}
        mobilityByScenario={mobilityByScenario}
        error={error}
        setScenarios={setScenarios}
        exerciseByScenario={exerciseByScenario}
        onOpen={(id) => {
          const scenario = scenarios.find((item) => item.id === id);
          if (scenario?.scenario_kind === "exercise")
            void navigateTo(`/scenarios/${id}/map`);
          else if (scenario?.setup_complete)
            void navigateTo(`/scenarios/${id}/decisions`);
          else navigate({ kind: "overview", scenarioId: id });
        }}
      />
    );
  if (!workspace)
    return (
      <Missing
        error={error || "Ocorrência não encontrada"}
        onBack={() => navigate({ kind: "list" })}
      />
    );

  const refreshScenario = (scenario: ScenarioWorkspace) => {
    const firstPreparation =
      !workspaceRef.current?.setup_complete && scenario.setup_complete;
    workspaceRef.current = scenario;
    serverRevision.current = scenario.revision;
    editVersion.current = 0;
    savedVersion.current = 0;
    setWorkspace(scenario);
    setScenarios((values) =>
      values.map((value) => (value.id === scenario.id ? scenario : value)),
    );
    setShowSetup(false);
    if (firstPreparation)
      void navigateTo(`/scenarios/${scenario.id}/experiments/new`);
    else if (scenario.setup_complete)
      void navigateTo(`/scenarios/${scenario.id}/decisions`);
  };

  if (route.kind === "new-experiment")
    return (
      <ExperimentSetup
        workspace={workspace}
        saveNow={saveNow}
        editWorkspace={editWorkspace}
        saveState={saveState}
        onBack={() => navigate({ kind: "overview", scenarioId: workspace.id })}
        onCreated={(run) => {
          setRuns((values) => [run, ...values]);
          navigate({
            kind: "experiment",
            scenarioId: workspace.id,
            runId: run.id,
          });
        }}
      />
    );

  if (route.kind === "experiment") {
    const run = runs.find((item) => item.id === route.runId);
    return (
      <ExperimentDetail
        workspace={workspace}
        run={run}
        error={error}
        onBack={() => navigate({ kind: "overview", scenarioId: workspace.id })}
        onChanged={(changed) =>
          setRuns((values) =>
            values.map((value) => (value.id === changed.id ? changed : value)),
          )
        }
      />
    );
  }

  return (
    <>
      <ScenarioOverview
        simulationsOnly={route.kind === "experiments"}
        workspace={workspace}
        runs={runs}
        mobility={mobilityByScenario[workspace.id]}
        exercise={exerciseByScenario[workspace.id]}
        error={error}
        saveState={saveState}
        editWorkspace={editWorkspace}
        saveNow={saveNow}
        onBack={() => void saveNow().then(() => navigate({ kind: "list" }))}
        onSetup={() => void saveNow().then(() => setShowSetup(true))}
        onViewer={() =>
          void saveNow().then(() =>
            void navigateTo(`/scenarios/${workspace.id}/decisions`),
          )
        }
        onNew={() =>
          void saveNow().then(() =>
            navigate({ kind: "new-experiment", scenarioId: workspace.id }),
          )
        }
        onScenarioChanged={refreshScenario}
        onExperiment={(runId) =>
          void saveNow().then(() =>
            navigate({ kind: "experiment", scenarioId: workspace.id, runId }),
          )
        }
      />
      {showSetup && (
        <ScenarioWizard
          workspace={workspace}
          onCreated={refreshScenario}
          onClose={() => setShowSetup(false)}
        />
      )}
    </>
  );
}

export function ScenarioList({
  scenarios,
  mobilityByScenario,
  exerciseByScenario,
  error,
  setScenarios,
  onOpen,
}: {
  scenarios: ScenarioWorkspace[];
  mobilityByScenario: Record<string, MobilityMetrics>;
  exerciseByScenario: Record<string, ExerciseSummary>;
  error: string;
  setScenarios: React.Dispatch<React.SetStateAction<ScenarioWorkspace[]>>;
  onOpen: (id: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [creatingBusy, setCreatingBusy] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [startTime, setStartTime] = useState("");
  const [deleting, setDeleting] = useState<string>();
  const [localError, setLocalError] = useState("");
  const [createMode, setCreateMode] = useState<"manual" | "fogos">("manual");
  const scenarioSubmitted = useRef(false);
  const scenarioDraftDirty = creating && Boolean(name || description || startTime);
  useNavigationGuard(() => scenarioSubmitted.current || !scenarioDraftDirty || (!creatingBusy && confirmDiscard()), scenarioDraftDirty);
  const visible = scenarios.filter((item) =>
    `${item.name} ${item.description}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );

  async function create() {
    if (creatingBusy) return;
    setCreatingBusy(true);
    setLocalError("");
    try {
      const scenario = await api.createScenario({
        name,
        description,
        start_time: startTime || null,
        area_id: "unprepared",
        area_package_id: null,
        resource_center: null,
      });
      setScenarios((values) => [...values, scenario]);
      scenarioSubmitted.current = true;
      onOpen(scenario.id);
    } catch (reason) {
      setLocalError(message(reason));
    } finally {
      setCreatingBusy(false);
    }
  }

  async function remove(scenario: ScenarioWorkspace) {
    setLocalError("");
    try {
      await api.deleteScenario(scenario.id, scenario.revision);
      setScenarios((values) =>
        values.filter((value) => value.id !== scenario.id),
      );
      setDeleting(undefined);
    } catch (reason) {
      setLocalError(message(reason));
    }
  }

  return (
    <SectionContainer
      as="main"
      containerClassName="ds-stack"
      className="management-shell"
    >
      <header className="management-header">
        <Box>
          <Typography as="h1" variant="h1">
            {t("Scenarios")}
          </Typography>
          <Typography as="p" variant="body">
            {t("Manage scenario context before opening maps and results.")}
          </Typography>
        </Box>
        <Button
          variant="primary"
          onClick={() => {
            setLocalError("");
            setCreateMode("manual");
            setCreating(true);
          }}
        >
          {t("New scenario")}
        </Button>
      </header>
      {(error || localError) && (
        <Typography
          as="p"
          variant="small"
          className="management-error"
          role="alert"
        >
          {localError || error}
        </Typography>
      )}
      <Box className="list-toolbar">
        <input
          aria-label={t("Search scenarios")}
          type="search"
          placeholder={t("Search scenarios")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <span>
          {visible.length} {visible.length === 1 ? "ocorrência" : "ocorrências"}
        </span>
      </Box>
      <section className="scenario-cards">
        {visible.map((scenario) => (
          <Card
            as="article"
            density="default"
            shadow="card"
            className="scenario-card"
            key={scenario.id}
          >
            <Box className="scenario-card-topline">
              <span className="scenario-index">
                SCN/{scenario.id.slice(-8).toUpperCase()} ·{" "}
                {scenario.scenario_kind === "exercise"
                  ? t("ARCHIVED PLAN")
                  : t("INCIDENT")}
              </span>
              <span
                className={`setup-badge ${scenario.setup_complete ? "ready" : "incomplete"}`}
              >
                {scenario.scenario_kind === "exercise"
                  ? "Arquivada"
                  : scenario.setup_complete
                    ? "Preparada"
                    : t("Setup needed")}
              </span>
            </Box>
            <Typography as="h2" variant="h2">
              <Button
                variant="ghost"
                className="scenario-open ds-heading-action"
                onClick={() => onOpen(scenario.id)}
              >
                {scenario.name}
              </Button>
            </Typography>
            <Typography as="p" variant="body">
              {scenario.description || t("No description recorded")}
            </Typography>
            {scenario.scenario_kind === "exercise" ? (
              <ExerciseMetricStrip metrics={exerciseByScenario[scenario.id]} />
            ) : (
              <Box className="card-metadata">
                <span>
                  {scenario.simulation.ignitions.length}{" "}
                  {scenario.simulation.ignitions.length === 1
                    ? "ignição"
                    : "ignições"}
                </span>
                <span>
                  {scenario.cell_size_m || 30} {t("m cells")}
                </span>
                <span>
                  {scenario.resource_radius_km || "—"} {t("km resource radius")}
                </span>
              </Box>
            )}
            <MobilityMetricStrip
              metrics={mobilityByScenario[scenario.id] || emptyMobilityMetrics}
              compact
            />
            <Typography as="small" variant="small">
              {t("Updated")} {formatDate(scenario.updated_at)}
            </Typography>
            {scenario.scenario_kind !== "exercise" &&
              (deleting === scenario.id ? (
                <Box className="confirm-row">
                  <span>{t("Delete this scenario and hide its results?")}</span>
                  <Button
                    variant="outline"
                    intent="danger"
                    onClick={() => void remove(scenario)}
                  >
                    {t("Delete")}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => setDeleting(undefined)}
                  >
                    {t("Keep")}
                  </Button>
                </Box>
              ) : (
                <Button
                  variant="ghost"
                  intent="danger"
                  onClick={() => setDeleting(scenario.id)}
                >
                  {t("Delete")}
                </Button>
              ))}
          </Card>
        ))}
      </section>
      {!visible.length && (
        <Card density="compact" shadow="none" className="management-empty">
          <Typography as="h2" variant="h2">
            {t("No scenarios found")}
          </Typography>
          <Typography as="p" variant="body">
            {t("Create one or change the search.")}
          </Typography>
        </Card>
      )}
      {creating && createMode === "manual" && (
        <Dialog onDismiss={creatingBusy ? undefined : () => setCreating(false)} aria-label={t("New scenario")}>
          <PopupLayout title={t("Start with the context")} eyebrow={t("New scenario")} onClose={() => setCreating(false)} closeDisabled={creatingBusy}
            navigation={<Box className="popup-tab-list" aria-label="Origem da ocorrência">
              <Button variant="secondary" aria-pressed={true} disabled={creatingBusy}>{t("Manual")}</Button>
              <Button variant="outline" disabled={creatingBusy} onClick={() => { setLocalError(""); setCreateMode("fogos"); }}>{t("Import from Fogos.pt")}</Button>
            </Box>}
            feedback={localError && <p className="management-error" role="alert">{localError}</p>}
            actions={<>
              <Button variant="outline" disabled={creatingBusy} onClick={() => setCreating(false)}>{t("Cancel")}</Button>
              <Button type="submit" form="new-occurrence-form" disabled={creatingBusy}>{creatingBusy ? t("Creating…") : t("Create scenario")}</Button>
            </>}>
            <form id="new-occurrence-form" onSubmit={event => { event.preventDefault(); void create(); }}>
              <label>{t("Name")}<input autoFocus required maxLength={120} value={name} disabled={creatingBusy} onChange={event => setName(event.target.value)} /></label>
              <label>{t("Scenario start")}<input type="datetime-local" value={startTime} disabled={creatingBusy} onChange={event => setStartTime(event.target.value)} /></label>
              <details><summary>Descrição opcional</summary><label>{t("Description")}<textarea rows={3} value={description} disabled={creatingBusy} onChange={event => setDescription(event.target.value)} /></label></details>
            </form>
          </PopupLayout>
        </Dialog>
      )}
      {creating && createMode === "fogos" && (
        <FogosImportDialog
          onClose={() => setCreating(false)}
          onOpenExisting={(id) => {
            setCreating(false);
            onOpen(id);
          }}
          onCreated={(scenario) => {
            setScenarios((values) => [...values, scenario]);
            setCreating(false);
            onOpen(scenario.id);
          }}
        />
      )}
    </SectionContainer>
  );
}

function SavedSimulations({ workspace, runs }: { workspace: ScenarioWorkspace; runs: Run[] }) {
  const [filter, setFilter] = useState("all");
  const filtered =
    filter === "all"
      ? runs
      : runs.filter((run) =>
          filter === "active"
            ? activeStatuses.includes(run.status)
            : run.status === filter,
        );
  return (
<Card
          as="section"
          density="default"
          shadow="card"
          className="management-panel experiments-panel"
        >
          <Box className="section-heading">
            <Box>
              <Typography as="span" variant="label" className="eyebrow">
                {t("Fire simulations")}
              </Typography>
              <Typography as="h2" variant="h2">
                {t("Advanced fire analysis")}
              </Typography>
            </Box>
            <select
              aria-label={t("Filter experiment status")}
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            >
              <option value="all">{t("All statuses")}</option>
              <option value="active">{t("Active")}</option>
              <option value="ready">{t("Ready")}</option>
              <option value="partial">{t("Partial")}</option>
              <option value="failed">{t("Failed")}</option>
              <option value="cancelled">{t("Cancelled")}</option>
            </select>
          </Box>
          <Box className="experiment-list">
            {filtered.map((run) => (
              <ButtonLink
                variant="secondary"
                className="experiment-row ds-row-action"
                key={run.id}
                href={`/scenarios/${workspace.id}/experiments/${run.id}`}
              >
                <span className={`status-pill ${statusLabel(run.status)}`}>
                  {statusLabel(run.status)}
                </span>
                <span>
                  <strong>{run.name || resultLabel(run)}</strong>
                  <Typography as="small" variant="small">
                    EXP/{run.id.slice(-8).toUpperCase()} · {modeLabel(run.mode)}{" "}
                    · {run.scenario.engine} · {formatDate(run.created_at)}
                  </Typography>
                </span>
                <span className="progress-value">
                  {activeStatuses.includes(run.status)
                    ? `${run.progress}%`
                    : "→"}
                </span>
              </ButtonLink>
            ))}
          </Box>
          {!filtered.length && (
            <Card density="compact" shadow="none" className="management-empty">
              <Typography as="h2" variant="h2">
                {t("No experiments here")}
              </Typography>
              <Typography as="p" variant="body">
                {workspace.setup_complete
                  ? t("Create an experiment to produce the first result.")
                  : t("Complete scenario setup first.")}
              </Typography>
            </Card>
          )}
        </Card>
  );
}

function ScenarioOverview({
  simulationsOnly = false,
  workspace,
  runs,
  mobility = emptyMobilityMetrics,
  exercise,
  error,
  saveState,
  editWorkspace,
  saveNow,
  onBack,
  onSetup,
  onViewer,
  onNew,
  onExperiment,
  onScenarioChanged,
}: {
  simulationsOnly?: boolean;
  workspace: ScenarioWorkspace;
  runs: Run[];
  mobility?: MobilityMetrics;
  exercise?: ExerciseSummary;
  error: string;
  saveState: string;
  editWorkspace: (
    change: (current: ScenarioWorkspace) => ScenarioWorkspace,
  ) => void;
  saveNow: () => Promise<ScenarioWorkspace | undefined>;
  onBack: () => void;
  onSetup: () => void;
  onViewer: (runId?: string) => void;
  onNew: () => void;
  onExperiment: (id: string) => void;
  onScenarioChanged: (scenario: ScenarioWorkspace) => void;
}) {
  if (simulationsOnly) return <SectionContainer as="main" containerClassName="ds-stack" className="management-shell">
    <header className="management-header"><Typography as="h1" variant="h1">Simulações guardadas</Typography>
      {workspace.setup_complete ? <Button variant="primary" onClick={onNew}>Nova simulação</Button> : <Button variant="primary" onClick={onSetup}>Completar preparação</Button>}
    </header>
    {error && <p role="alert">{error}</p>}
    <SavedSimulations workspace={workspace} runs={runs} />
  </SectionContainer>;
  return (
    <SectionContainer
      as="main"
      containerClassName="ds-stack"
      className="management-shell"
    >
      <header className="management-header scenario-heading">
        <Box>
          <Typography as="span" variant="label" className="eyebrow">
            {t("Incident · SCN/")}
            {workspace.id.slice(-8).toUpperCase()}
          </Typography>
          <Typography as="h1" variant="h1">
            Visão geral
          </Typography>
          <Box className="scenario-facts">
            <span>
              {workspace.setup_complete
                ? t("Prepared area")
                : t("Setup required")}
            </span>
            <span>
              {runs.length}{" "}
              {runs.length === 1
                ? "simulação de incêndio"
                : "simulações de incêndio"}
            </span>
            {exercise?.reference_time && (
              <span>
                {t("Situation")} {formatDate(exercise.reference_time)}
              </span>
            )}
          </Box>
        </Box>
        <Box className="header-actions">
          {workspace.scenario_kind === "exercise" ? (
            <>
              <ButtonLink
                variant="primary"
                href={`/scenarios/${workspace.id}/map`}
              >
                {t("View read-only archive")}
              </ButtonLink>
              {workspace.setup_complete && (
                <Button variant="secondary" onClick={() => onViewer()}>
                  Comparar decisões
                </Button>
              )}
            </>
          ) : workspace.setup_complete ? (
            <>
              <Button variant="primary" onClick={() => onViewer()}>
                Comparar decisões
              </Button>
              <Button variant="secondary" onClick={onNew}>
                {t("New fire simulation")}
              </Button>
              <ButtonLink
                variant="secondary"
                href={`/scenarios/${workspace.id}/map`}
              >
                {t("Planning archive")}
              </ButtonLink>
            </>
          ) : (
            <Button variant="primary" onClick={onSetup}>
              {t("Complete setup")}
            </Button>
          )}
        </Box>
      </header>
      {error && (
        <Typography
          role="alert"
          as="p"
          variant="small"
          className="management-error"
        >
          {error}
        </Typography>
      )}
      <Box className="overview-grid">
        <Card
          as="section"
          density="default"
          shadow="card"
          className="management-panel"
        >
          <Box className="section-heading">
            <Box>
              <Typography as="span" variant="label" className="eyebrow">
                {t("Metadata")}
              </Typography>
              <Typography as="h2" variant="h2">
                {t("Scenario details")}
              </Typography>
            </Box>
            <span className={`save-state ${saveState}`}>
              {saveState === "saving"
                ? t("Saving…")
                : saveState === "failed"
                  ? t("Save failed")
                  : t("Saved")}
            </span>
          </Box>
          <label>
            {t("Name")}
            <input
              readOnly={workspace.scenario_kind === "exercise"}
              value={workspace.name}
              onChange={(event) =>
                editWorkspace((current) => ({
                  ...current,
                  name: event.target.value,
                }))
              }
            />
          </label>
          <label>
            {t("Description")}
            <textarea
              readOnly={workspace.scenario_kind === "exercise"}
              rows={5}
              value={workspace.description}
              onChange={(event) =>
                editWorkspace((current) => ({
                  ...current,
                  description: event.target.value,
                }))
              }
            />
          </label>
          <label>
            {t("Scenario start")}
            <input
              readOnly={workspace.scenario_kind === "exercise"}
              type="datetime-local"
              value={workspace.start_time?.slice(0, 16) || ""}
              onChange={(event) =>
                editWorkspace((current) => ({
                  ...current,
                  start_time: event.target.value || null,
                }))
              }
            />
          </label>
          <Card density="compact" shadow="none" className="setup-summary">
            <strong>
              {workspace.setup_complete
                ? t("Prepared area")
                : t("Area not prepared")}
            </strong>
            <span>
              {workspace.setup_complete
                ? `${workspace.cell_size_m || 30} m por célula · ${workspace.resource_radius_km} km de pesquisa de recursos · ${workspace.fire_margin_km} km de margem do incêndio`
                : t(
                    "Location, fire starts, coverage, and public data are still required.",
                  )}
            </span>
            {workspace.setup_complete &&
              workspace.scenario_kind !== "exercise" && (
                <Button variant="secondary" onClick={onSetup}>
                  {t("Update area setup")}
                </Button>
              )}
          </Card>
        </Card>
        {workspace.scenario_kind === "exercise" && (
          <Card
            as="section"
            density="default"
            shadow="card"
            className="management-panel"
          >
            <Box className="section-heading">
              <Box>
                <Typography as="span" variant="label" className="eyebrow">
                  {t("Read-only archive")}
                </Typography>
                <Typography as="h2" variant="h2">
                  {t("Historical planning situation")}
                </Typography>
              </Box>
              <ButtonLink
                variant="secondary"
                href={`/scenarios/${workspace.id}/map`}
              >
                {t("View archive")}
              </ButtonLink>
            </Box>
            <ExerciseMetricStrip metrics={exercise} />
            <Typography as="small" variant="small">
              {t("Archived metrics describe the saved exercise situation at")}{" "}
              {formatDate(exercise?.reference_time)}
              {t(
                ". Historical experiments are not presented as current state.",
              )}
            </Typography>
          </Card>
        )}
        <SavedSimulations workspace={workspace} runs={runs} />
        {workspace.external_incident && (
          <Card
            as="section"
            density="default"
            shadow="card"
            className="management-panel external-incident-panel"
            aria-label={t("Fogos.pt resource context")}
          >
            <FogosContextPanel
              workspace={workspace}
              editWorkspace={editWorkspace}
              saveNow={saveNow}
              onScenarioChanged={onScenarioChanged}
            />
          </Card>
        )}
        <Card
          as="details"
          density="default"
          shadow="card"
          className="management-panel mobility-metrics-panel"
        >
          <summary>Unidades e deslocações</summary>
          <MobilityMetricStrip metrics={mobility} />
          <ButtonLink
            variant="secondary"
            href={`/scenarios/${workspace.id}/mobility`}
          >
            Abrir mapa de deslocações
          </ButtonLink>
        </Card>
      </Box>
    </SectionContainer>
  );
}

function ExerciseMetricStrip({ metrics }: { metrics?: ExerciseSummary }) {
  if (!metrics)
    return (
      <Box className="exercise-metric-strip loading">
        {t("Loading exercise metrics…")}
      </Box>
    );
  if (metrics.data_status !== "ready")
    return (
      <Box className="exercise-metric-strip unavailable">
        {t("Exercise metrics unavailable")}
      </Box>
    );
  return (
    <>
      <Box className="exercise-metric-strip">
        <span>
          <strong>
            {metrics.available_units}/{metrics.total_units}
          </strong>
          <Typography as="small" variant="small">
            {t("Units available")}
          </Typography>
        </span>
        <span>
          <strong>{metrics.outstanding_missions}</strong>
          <Typography as="small" variant="small">
            {t("Outstanding missions")}
          </Typography>
        </span>
        <span>
          <strong>{metrics.saved_plans}</strong>
          <Typography as="small" variant="small">
            {t("Response plans")}
          </Typography>
        </span>
        <span>
          <strong>{metrics.completed_experiments}</strong>
          <Typography as="small" variant="small">
            {t("Completed experiments")}
          </Typography>
        </span>
      </Box>
      {metrics.active_rehearsal && (
        <Typography as="p" variant="body" className="simulated-progress">
          <strong>{t("Simulated rehearsal:")}</strong>{" "}
          {statusLabel(metrics.active_rehearsal.state)} {t("· minute")}{" "}
          {formatNumber(metrics.active_rehearsal.elapsed_min)}
        </Typography>
      )}
    </>
  );
}

function MobilityMetricStrip({
  metrics,
  compact = false,
}: {
  metrics: MobilityMetrics;
  compact?: boolean;
}) {
  const attention =
    metrics.pending_road_reports + metrics.routes_needing_review;
  return (
    <Box
      className={
        compact ? "mobility-metric-strip compact" : "mobility-metric-strip"
      }
      aria-label={t("Mobility metrics")}
    >
      <span>
        <strong>{metrics.active_movements}</strong>
        <Typography as="small" variant="small">
          {t("Active movements")}
        </Typography>
      </span>
      <span>
        <strong>
          {metrics.available_units}/{metrics.total_units}
        </strong>
        <Typography as="small" variant="small">
          {t("Units available")}
        </Typography>
      </span>
      <span className={attention ? "attention" : ""}>
        <strong>{metrics.pending_road_reports}</strong>
        <Typography as="small" variant="small">
          {t("Road reviews")}
        </Typography>
      </span>
      <span className={metrics.routes_needing_review ? "attention" : ""}>
        <strong>{metrics.routes_needing_review}</strong>
        <Typography as="small" variant="small">
          {t("Route reviews")}
        </Typography>
      </span>
    </Box>
  );
}

function FogosContextPanel({
  workspace,
  editWorkspace,
  saveNow,
  onScenarioChanged,
}: {
  workspace: ScenarioWorkspace;
  editWorkspace: (
    change: (current: ScenarioWorkspace) => ScenarioWorkspace,
  ) => void;
  saveNow: () => Promise<ScenarioWorkspace | undefined>;
  onScenarioChanged: (scenario: ScenarioWorkspace) => void;
}) {
  const [context, setContext] = useState<FogosContext>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [syncChanges, setSyncChanges] = useState<FogosResourceChange[]>([]);
  const [syncCompleted, setSyncCompleted] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api
      .fogosContext(workspace.id, controller.signal)
      .then(setContext)
      .catch((reason) => setError(message(reason)));
    return () => controller.abort();
  }, [
    workspace.id,
    workspace.external_incident?.latest_snapshot_id,
    workspace.external_incident?.tracking_enabled,
  ]);
  if (!context)
    return (
      <Box className="fogos-context">
        <Typography as="span" variant="label" className="eyebrow">
          {t("Fogos.pt context")}
        </Typography>
        <Typography as="p" variant="body">
          {error || t("Loading source context…")}
        </Typography>
      </Box>
    );
  const imported = context.import_snapshot?.normalized as unknown as
    | FogosIncident
    | undefined;
  const latest = context.latest_incident?.normalized;
  const changed =
    imported && latest
      ? [
          imported.status !== latest.status
            ? `Estado: ${statusLabel(imported.status || "unknown")} → ${statusLabel(latest.status || "unknown")}`
            : "",
          imported.resources.personnel !== latest.resources.personnel
            ? `Operacionais: ${resourceValue(imported.resources.personnel)} → ${resourceValue(latest.resources.personnel)}`
            : "",
          imported.resources.vehicles !== latest.resources.vehicles
            ? `Meios terrestres: ${resourceValue(imported.resources.vehicles)} → ${resourceValue(latest.resources.vehicles)}`
            : "",
          imported.resources.aircraft !== latest.resources.aircraft
            ? `Meios aéreos: ${resourceValue(imported.resources.aircraft)} → ${resourceValue(latest.resources.aircraft)}`
            : "",
        ].filter(Boolean)
      : [];
  async function action(label: string, task: () => Promise<void>) {
    setBusy(label);
    setError("");
    try {
      await task();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy("");
    }
  }
  async function synchronize() {
    const saved = await saveNow();
    if (!saved) return;
    const result = await api.syncFogos(saved.id, saved.revision);
    setContext(result.context);
    setSyncChanges(result.changes);
    setSyncCompleted(true);
    onScenarioChanged(result.scenario);
  }
  return (
    <Box className="fogos-context">
      <Box className="section-heading">
        <Box>
          <Typography as="span" variant="label" className="eyebrow">
            {t("Fogos.pt context")}
          </Typography>
          <Typography as="h3" variant="h3">
            {latest?.location || imported?.location || context.link.incident_id}
          </Typography>
        </Box>
        <a
          href={context.source_url || "https://fogos.pt"}
          target="_blank"
          rel="noreferrer"
        >
          {t("Source ↗")}
        </a>
      </Box>
      {latest && (
        <Card density="compact" shadow="none" className="source-summary">
          <span>
            {latest.status || t("Status unavailable")} {t("· updated")}{" "}
            {formatDate(latest.updated_at)}
          </span>
          <span>
            {resourceValue(latest.resources.personnel)} Operacionais ·{" "}
            {resourceValue(latest.resources.vehicles)} Meios terrestres ·{" "}
            {resourceValue(latest.resources.aircraft)} Meios aéreos
          </span>
        </Card>
      )}
      {changed.length > 0 && (
        <Card density="compact" shadow="none" className="source-changes">
          <strong>{t("Changed since import")}</strong>
          {changed.map((value) => (
            <span key={value}>{value}</span>
          ))}
        </Card>
      )}
      {workspace.resource_groups.length > 0 && (
        <>
          <Box className="fogos-resource-groups">
            {workspace.resource_groups.map((group) => (
              <ResourceGroupEditor
                key={group.id}
                group={group}
                onChange={(updated) =>
                  editWorkspace((current) => ({
                    ...current,
                    resource_groups: current.resource_groups.map((value) =>
                      value.id === updated.id ? updated : value,
                    ),
                  }))
                }
              />
            ))}
          </Box>
          <Typography as="small" variant="small">
            {t(
              "These are mobilized totals reported by Fogos.pt, not confirmed individual or on-scene units.",
            )}
          </Typography>
        </>
      )}
      {syncChanges.length > 0 && (
        <Card density="compact" shadow="none" className="source-changes">
          <strong>{t("Last synchronization")}</strong>
          {syncChanges.map((change) => (
            <span key={change.category}>
              {change.name}: {resourceValue(change.before)} →{" "}
              {resourceValue(change.after)}
              {change.created ? " · adicionado à ocorrência" : ""}
            </span>
          ))}
        </Card>
      )}
      {syncChanges.length === 0 && syncCompleted && (
        <Card density="compact" shadow="none" className="source-changes">
          <strong>{t("Last synchronization")}</strong>
          <span>{t("No reported quantity changes.")}</span>
        </Card>
      )}
      {latest?.weather && (
        <Card density="compact" shadow="none" className="weather-context">
          <strong>{t("Nearest-station weather")}</strong>
          <span>
            {latest.weather.wind_speed_kmh} km/h ·{" "}
            {latest.weather.wind_direction_deg}° ·{" "}
            {latest.weather.temperature_c ?? "—"} °C · RH{" "}
            {latest.weather.relative_humidity_pct ?? "—"}%
          </span>
          <Typography as="small" variant="small">
            {latest.weather.station_name || t("Station")}
            {latest.weather.station_distance_km != null
              ? ` · ${latest.weather.station_distance_km} km away`
              : ""}{" "}
            · {formatDate(latest.weather.observed_at)}
          </Typography>
          {latest.active ? (
            <Button
              variant="secondary"
              disabled={Boolean(busy)}
              onClick={() =>
                void action("weather", async () =>
                  onScenarioChanged(
                    await api.applyFogosWeather(
                      workspace.id,
                      workspace.revision,
                    ),
                  ),
                )
              }
            >
              {t("Apply wind to constant weather")}
            </Button>
          ) : (
            <Typography as="small" variant="small">
              {t(
                "Current station weather cannot be applied as historical incident conditions.",
              )}
            </Typography>
          )}
          <Button
            variant="secondary"
            disabled={Boolean(busy)}
            onClick={() =>
              void action("series", async () => {
                const series = await api.createFogosWeatherSeries(workspace.id);
                alert(
                  `A série meteorológica ${series.filename} está disponível para motores compatíveis.`,
                );
              })
            }
          >
            {t("Create hourly weather series")}
          </Button>
        </Card>
      )}
      {latest?.weather_warnings?.length ? (
        <Card density="compact" shadow="none" className="source-changes">
          <strong>{t("Current weather warnings")}</strong>
          {latest.weather_warnings.map((warning, index) => (
            <span key={`${String(warning.idAreaAviso || "warning")}-${index}`}>
              {String(warning.awarenessLevelID || t("Warning"))} ·{" "}
              {String(
                warning.awarenessTypeName || warning.text || t("IPMA warning"),
              )}{" "}
              ·{" "}
              {formatDate(
                String(warning.starts_at_lisbon || warning.startTime || ""),
              )}
              –
              {formatDate(
                String(warning.ends_at_lisbon || warning.endTime || ""),
              )}
            </span>
          ))}
          <Typography as="small" variant="small">
            {t(
              "Europe/Lisbon times. Current warnings may not describe a historical scenario.",
            )}
          </Typography>
        </Card>
      ) : null}
      <Box className="fogos-actions">
        <Button
          variant="secondary"
          disabled={Boolean(busy)}
          onClick={() => void action("sync", synchronize)}
        >
          {busy === "sync"
            ? t("Synchronizing…")
            : t("Sync scenario from Fogos.pt")}
        </Button>
        <label>
          <input
            type="checkbox"
            checked={context.link.tracking_enabled}
            disabled={Boolean(busy)}
            onChange={(event) =>
              void action("tracking", async () =>
                setContext(
                  await api.setFogosTracking(
                    workspace.id,
                    event.target.checked,
                  ),
                ),
              )
            }
          />{" "}
          {t("Track incident in background")}
        </label>
      </Box>
      <Typography as="small" variant="small">
        {context.snapshots.length} {t("immutable Fogos.pt snapshot")}
        {context.snapshots.length === 1 ? "" : "s"}{" "}
        {t("retained in source history.")}
      </Typography>
      {context.link.tracking_enabled && (
        <Typography as="small" variant="small">
          {t("Last success:")} {formatDate(context.link.last_success_at)}{" "}
          {t("· next attempt:")}{" "}
          {formatDate(
            context.link.tracking_next_attempt || context.link.next_poll_at,
          )}{" "}
          {t("· failures:")} {context.link.tracking_failures || 0}
        </Typography>
      )}
      <Typography as="small" variant="small">
        {t(
          "Tracking is opt-in and snapshot-only. Only this manual synchronization updates reported group totals; it never alters teams, mobility, routes, containment, or model inputs.",
        )}
      </Typography>
      {(error || context.link.last_error) && (
        <Typography
          role="alert"
          as="p"
          variant="small"
          className="management-error"
        >
          {error || context.link.last_error}
        </Typography>
      )}
    </Box>
  );
}

function ExperimentSetup({
  workspace,
  saveNow,
  editWorkspace,
  saveState,
  onBack,
  onCreated,
}: {
  workspace: ScenarioWorkspace;
  saveNow: () => Promise<ScenarioWorkspace | undefined>;
  editWorkspace: (
    change: (current: ScenarioWorkspace) => ScenarioWorkspace,
  ) => void;
  saveState: string;
  onBack: () => void;
  onCreated: (run: Run) => void;
}) {
  const [engines, setEngines] = useState<Engine[]>([]);
  const [weather, setWeather] = useState<WeatherSeries[]>([]);
  const [area, setArea] = useState<Area>();
  const [name, setName] = useState(
    `Simulação ${new Intl.DateTimeFormat("pt-PT").format(new Date())}`,
  );
  const [notes, setNotes] = useState("");
  const [placing, setPlacing] = useState<string>();
  const [error, setError] = useState("");
  const [launching, setLaunching] = useState(false);
  const initialName = useRef(name);
  const submitted = useRef(false);
  const draftDirty = name !== initialName.current || Boolean(notes);
  useNavigationGuard(() => submitted.current || (!launching && (!draftDirty || confirmDiscard())), draftDirty && !submitted.current);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      api.engines(controller.signal),
      api.weather(controller.signal),
      api.area(controller.signal, workspace.area_package_id),
    ])
      .then(([e, w, a]) => {
        setEngines(e);
        setWeather(w);
        setArea(a);
      })
      .catch((reason) => setError(message(reason)));
    return () => controller.abort();
  }, [workspace.area_package_id]);
  async function launch() {
    setLaunching(true);
    setError("");
    try {
      const saved = await saveNow();
      if (!saved) return;
      const created = await api.runScenario(saved.id, "single", undefined, name.trim(), notes);
      submitted.current = true;
      onCreated(created);
    } catch (reason) {
      setError(message(reason));
    } finally {
      setLaunching(false);
    }
  }
  if (!area) return <ScenarioLoading label={t("Loading scenario…")} />;
  const bounds = area.fire_bounds || area.bounds;
  const mapBounds: [[number, number], [number, number]] = [
    [bounds[1], bounds[0]],
    [bounds[3], bounds[2]],
  ];
  return (
    <main className="experiment-setup-page">
      <Box className="setup-topbar">
        <span className={`save-state ${saveState}`}>
          {saveState === "saving"
            ? t("Saving draft…")
            : saveState === "failed"
              ? t("Save failed")
              : t("Draft saved")}
        </span>
      </Box>
      <Box className="experiment-setup-grid">
        <Box className="setup-controls">
          <Card
            as="section"
            density="compact"
            shadow="none"
            className="experiment-meta"
          >
            <Typography as="span" variant="label" className="eyebrow">
              {t("New experiment")}
            </Typography>
            <Typography as="h1" variant="h1">
              {t("Configure experiment")}
            </Typography>
            <label>
              {t("Experiment name")}
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              {t("Notes")}
              <textarea
                rows={3}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
            </label>
          </Card>
          <Controls
            headingLevel="h2"
            setupMode
            draft={workspace.simulation}
            engines={engines}
            scenarioName={workspace.name}
            description={workspace.description}
            startTime={workspace.start_time}
            filter={"all" as Filter}
            showFire
            showRoads
            showBasemap
            placing={Boolean(placing)}
            placingIgnitionId={placing}
            pending={launching}
            weatherSeries={weather}
            onDraft={(simulation) =>
              editWorkspace((current) => ({ ...current, simulation }))
            }
            onScenarioMeta={() => {}}
            onFilter={() => {}}
            onLayer={() => {}}
            onPlacing={(id) =>
              setPlacing((value) => (value === id ? undefined : id))
            }
            onRun={() => void launch()}
            onCancel={() => {}}
            onWeatherUpload={async (file) => {
              try {
                const uploaded = await api.uploadWeather(file);
                setWeather((values) => [uploaded, ...values]);
                editWorkspace((current) => ({
                  ...current,
                  simulation: {
                    ...current.simulation,
                    weather_source: { kind: "series", id: uploaded.id },
                  },
                }));
              } catch (reason) {
                setError(message(reason));
              }
            }}
            onAreaSettings={() => {}}
          />
          {error && (
            <Typography
              role="alert"
              as="p"
              variant="small"
              className="management-error"
            >
              {error}
            </Typography>
          )}
        </Box>
        <section className={placing ? "map-shell placing" : "map-shell"}>
          <MapView
            bounds={mapBounds}
            scenario={workspace.simulation}
            points={[]}
            showPointsKey={0}
            minute={0}
            forecast={0}
            filter="all"
            placing={Boolean(placing)}
            showFire={false}
            showRoads={false}
            showBasemap
            showPoints={false}
            onIgnition={(position) => {
              if (!placing) return;
              editWorkspace((current) => ({
                ...current,
                simulation: {
                  ...current.simulation,
                  ignitions: current.simulation.ignitions.map((item) =>
                    item.id === placing
                      ? { ...item, coordinates: position }
                      : item,
                  ),
                },
              }));
              setPlacing(undefined);
            }}
          />
          <Box className="status">
            <span className="dot" />
            {placing
              ? t("Click the map to place the fire start")
              : t("Location editor")}
          </Box>
        </section>
      </Box>
    </main>
  );
}

function ExperimentDetail({
  workspace,
  run,
  error,
  onBack,
  onChanged,
}: {
  workspace: ScenarioWorkspace;
  run?: Run;
  error: string;
  onBack: () => void;
  onChanged: (run: Run) => void;
}) {
  const [name, setName] = useState(run?.name || "");
  const [notes, setNotes] = useState(run?.notes || "");
  const [localError, setLocalError] = useState("");
  useEffect(() => {
    setName(run?.name || "");
    setNotes(run?.notes || "");
  }, [run?.id, run?.metadata_revision]);
  const metadataDirty = Boolean(run && (name !== (run.name || "") || notes !== (run.notes || "")));
  const [metadataSaving, setMetadataSaving] = useState(false);
  useNavigationGuard(() => {
    if (metadataSaving) { setLocalError("Aguarde a conclusão da gravação."); return false; }
    return !metadataDirty || confirmDiscard();
  }, metadataDirty);
  if (!run)
    return (
      <Missing error={error || t("Experiment not found")} onBack={onBack} />
    );
  async function saveMetadata() {
    if (metadataSaving) return;
    setMetadataSaving(true);
    try {
      onChanged(
        await api.updateRunMetadata(
          run!.id,
          name,
          notes,
          run!.metadata_revision,
        ),
      );
      setLocalError("");
    } catch (reason) {
      setLocalError(message(reason));
    } finally { setMetadataSaving(false); }
  }
  async function cancel() {
    try {
      onChanged(await api.cancel(run!.id));
    } catch (reason) {
      setLocalError(message(reason));
    }
  }
  const viewable =
    ["ready", "partial"].includes(run.status) &&
    run.mode !== "allocation_comparison";
  const manifestWarnings = Array.isArray(run.result?.manifest?.warnings)
    ? run.result!.manifest.warnings.filter(
        (value): value is string => typeof value === "string",
      )
    : [];
  const warnings = run.result?.manifest?.boundary_reached
    ? ["O incêndio alcançou o limite da área preparada.", ...manifestWarnings]
    : manifestWarnings;
  const operationalFire =
    run.status === "ready" &&
    run.mode === "single" &&
    workspace.scenario_kind !== "exercise";
  return (
    <SectionContainer
      as="main"
      containerClassName="ds-stack"
      className="management-shell"
    >
      <header className="management-header">
        <Box>
          <Typography as="span" variant="label" className="eyebrow">
            {t("Experiment")}
          </Typography>
          <Typography as="h1" variant="h1">
            {run.name}
          </Typography>
          <Typography as="p" variant="body">
            {modeLabel(run.mode)} {t("· created")} {formatDate(run.created_at)}
          </Typography>
        </Box>
        <Box className="header-actions">
          {viewable && (
            <ButtonLink
              variant="primary"
              href={
                operationalFire
                  ? `/scenarios/${workspace.id}/decisions?run=${encodeURIComponent(run.id)}`
                  : `/scenarios/${workspace.id}/simulation?run=${encodeURIComponent(run.id)}`
              }
            >
              {operationalFire ? "Comparar decisões" : t("View result")}
            </ButtonLink>
          )}
          {activeStatuses.includes(run.status) && (
            <Button
              variant="outline"
              intent="danger"
              onClick={() => void cancel()}
            >
              {t("Cancel experiment")}
            </Button>
          )}
        </Box>
      </header>
      {(error || localError) && (
        <Typography
          role="alert"
          as="p"
          variant="small"
          className="management-error"
        >
          {localError || error}
        </Typography>
      )}
      <Box className="overview-grid">
        <Card
          as="section"
          density="default"
          shadow="card"
          className="management-panel"
        >
          <Box className="section-heading">
            <Box>
              <Typography as="span" variant="label" className="eyebrow">
                {t("Status")}
              </Typography>
              <Typography as="h2" variant="h2">
                {statusLabel(run.status)}
              </Typography>
            </Box>
            <strong>{run.progress}%</strong>
          </Box>
          <progress max="100" value={run.progress} />
          <Typography as="p" variant="body">
            {stageLabel(run.stage, run.status)}
            {run.error ? ` · ${apiErrorMessage(run.error, 500)}` : ""}
          </Typography>
          {run.error && (
            <details>
              <summary>Detalhes técnicos originais</summary>
              <Typography as="p" variant="body">
                {run.error}
              </Typography>
            </details>
          )}
          {run.children?.length ? (
            <Box className="member-list">
              {run.children.map((child) => (
                <Box key={child.id}>
                  <span>{child.scenario.engine}</span>
                  <strong>{statusLabel(child.status)}</strong>
                </Box>
              ))}
            </Box>
          ) : null}
        </Card>
        <Card
          as="section"
          density="default"
          shadow="card"
          className="management-panel"
        >
          <Typography as="span" variant="label" className="eyebrow">
            {t("Experiment metadata")}
          </Typography>
          {run.mode === "single" && workspace.scenario_kind !== "exercise" ? (
            <>
              <label>
                {t("Name")}
                <input
                  maxLength={120}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </label>
              <label>
                {t("Notes")}
                <textarea
                  rows={6}
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                />
              </label>
              <Button
                variant="primary"
                disabled={!name.trim() || metadataSaving} onClick={() => void saveMetadata()}
              >
                {t("Save metadata")}
              </Button>
            </>
          ) : (
            <>
              <strong>{t("Read-only historical run")}</strong>
              <Typography as="p" variant="body">
                {run.name}
              </Typography>
              <Typography as="p" variant="body">
                {run.notes}
              </Typography>
            </>
          )}
        </Card>
        <Card
          as="section"
          density="default"
          shadow="card"
          className="management-panel inputs-panel"
        >
          <Typography as="span" variant="label" className="eyebrow">
            {t("Recorded inputs")}
          </Typography>
          <Typography as="h2" variant="h2">
            {t("Immutable simulation snapshot")}
          </Typography>
          <dl>
            <dt>{t("Engine")}</dt>
            <dd>{run.scenario.engine}</dd>
            <dt>{t("Duration")}</dt>
            <dd>{run.scenario.duration_min} min</dd>
            <dt>{t("Wind")}</dt>
            <dd>
              {run.scenario.wind_speed_kmh} km/h ·{" "}
              {run.scenario.wind_direction_deg}°
            </dd>
            <dt>{t("Moisture")}</dt>
            <dd>{statusLabel(run.scenario.moisture)}</dd>
            <dt>{t("Fire starts")}</dt>
            <dd>{run.scenario.ignitions.length}</dd>
            <dt>{t("Scenario revision")}</dt>
            <dd>{run.scenario_revision || "—"}</dd>
          </dl>
        </Card>
        {(run.result || warnings.length > 0) && (
          <Card
            as="section"
            density="default"
            shadow="card"
            className="management-panel inputs-panel"
          >
            <Typography as="span" variant="label" className="eyebrow">
              {t("Result")}
            </Typography>
            <Typography as="h2" variant="h2">
              {t("Output summary")}
            </Typography>
            {run.result && (
              <dl>
                <dt>{t("Engine output")}</dt>
                <dd>{run.result.engine}</dd>
                <dt>{t("Engine version")}</dt>
                <dd>{run.result.engine_version}</dd>
                <dt>{t("Time resolution")}</dt>
                <dd>{run.result.temporal_resolution_min} min</dd>
              </dl>
            )}
            {warnings.length > 0 && (
              <Box className="result-note-list">
                <strong>{t("Model notes")}</strong>
                {warnings.map((value) => (
                  <Typography as="p" variant="body" key={value}>
                    {value}
                  </Typography>
                ))}
              </Box>
            )}
          </Card>
        )}
      </Box>
    </SectionContainer>
  );
}

function Missing({ error, onBack }: { error: string; onBack: () => void }) {
  return (
    <SectionContainer
      as="main"
      containerClassName="ds-stack"
      className="management-shell"
    >
      <Card density="compact" shadow="none" className="management-empty">
        <Typography as="h1" variant="h1">
          {t("Unavailable")}
        </Typography>
        <Typography as="p" variant="body">
          {error}
        </Typography>
        <Button variant="secondary" onClick={onBack}>
          {t("Return to scenarios")}
        </Button>
      </Card>
    </SectionContainer>
  );
}
function message(reason: unknown) {
  return reason instanceof Error ? reason.message : "Ocorreu um erro";
}
function resourceValue(value: number | null) {
  return value == null ? "indisponível" : String(value);
}
function formatDate(value?: string | null) {
  return formatDateTime(value);
}
function modeLabel(mode: RunMode) {
  return mode === "single"
    ? "Simulação individual"
    : mode === "parameter_ensemble"
      ? "Conjunto de incerteza"
      : mode === "engine_comparison"
        ? "Comparação de motores"
        : "Comparação de contenção";
}

function readManagementRoute(href: string): ManagementRoute {
  const route = parseRoute(href);
  if (["overview", "experiments", "new-experiment", "experiment"].includes(route.kind)) return route as ManagementRoute;
  return { kind: "list" };
}
