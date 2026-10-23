import { formatDateTime } from "../locale";
import { confirmDiscard, navigateTo, workspaceHref, parseRoute, rememberRun, updatePageQuery, useAppLocation, useNavigationGuard } from "../navigation";
import { MapResize } from "./MapResize";
import { Box, Button, ButtonLink, Card, SectionContainer, Typography } from "./ui";
import { useEffect, useMemo, useState } from "react";
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Popup,
  TileLayer,
} from "react-leaflet";
import type {
  AccessAssessment,
  ComparisonInput,
  FeatureCollection,
  MobilityComparison,
  MobilitySnapshot,
  PlanningUnit,
  Run,
  ScenarioPoint,
  ScenarioWorkspace,
  SessionUser,
  SourceChoice,
  VehicleProfile,
} from "../types";
import { api } from "../api";
import { ScenarioLoading } from "../loading";
import {
  DecisionResults,
  TimelineEvents,
  movingPosition,
} from "./DecisionResults";
import { DecisionFocusLayer, scenarioClock } from "./DecisionAdvisories";
import type { FocusRequest, FocusDecision } from "./DecisionAdvisories";
import {
  AccessMapLayers,
  AccessResults,
  ImpactSummary,
  PopulationResults,
  comparisonForAssessment,
} from "./AccessViews";
import type { Perspective, ProposalMode } from "./AccessViews";
import { PopulationDataEditor } from "./PopulationDataEditor";
import "./decision.css";

const CSV_TEMPLATE =
  "unit_id,organisation,callsign,vehicle_class,longitude,latitude,observed_at,tank_capacity_l,starting_water_l,pump_flow_l_min,width_m,height_m,weight_t\nexemplo-01,Bombeiros,TQ-01,tanker,-8.2894,41.4258,2026-08-18T13:00:00Z,5000,0,600,2.5,3.2,16\n";


export function DecisionWorkspace({
  scenarioId,
  currentUser,
}: {
  scenarioId: string;
  currentUser: SessionUser;
}) {
  const [scenario, setScenario] = useState<ScenarioWorkspace>();
  const [mobility, setMobility] = useState<MobilitySnapshot>();
  const [roads, setRoads] = useState<FeatureCollection>();
  const [runs, setRuns] = useState<Run[]>([]);
  const [saved, setSaved] = useState<MobilityComparison[]>([]);
  const [assessments, setAssessments] = useState<AccessAssessment[]>([]);
  const [assessment, setAssessment] = useState<AccessAssessment>();
  const [accessRoads, setAccessRoads] = useState<FeatureCollection>();
  const [proposalMode, setProposalMode] = useState<ProposalMode>("without");
  const [selectedSectionId, setSelectedSectionId] = useState("");
  const [selectedOriginId, setSelectedOriginId] = useState("");
  const [selectedReceptionId, setSelectedReceptionId] = useState("");
  const [populationPoints, setPopulationPoints] = useState<ScenarioPoint[]>([]);
  const [populationVehicle, setPopulationVehicle] = useState<VehicleProfile>({
    id: "planning-light",
    name: "Viatura ligeira de exercício",
    vehicle_class: "light",
    width_m: null,
    height_m: null,
    weight_t: null,
    off_road: false,
    notes: "",
    available: true,
    revision: 1,
  });
  const [populationDirty, setPopulationDirty] = useState(false);
  const [assessmentDirty, setAssessmentDirty] = useState(false);
  const [savingPopulation, setSavingPopulation] = useState(false);
  const appLocation = useAppLocation();
  const navigationRoute = parseRoute(appLocation);
  const pane = navigationRoute.tab === "data" ? "data" : "compare";
  const perspective = navigationRoute.perspective || "water";
  function selectPerspective(value: Perspective) {
    const url = new URL(window.location.href);
    url.searchParams.delete("view");
    if (value === "water") url.searchParams.delete("perspective");
    else url.searchParams.set("perspective", value);
    void navigateTo(url.pathname + url.search);
  }
  const [runId, setRunId] = useState("");
  const [forecastStart, setForecastStart] = useState("");
  const [departure, setDeparture] = useState("");
  const [unitId, setUnitId] = useState("");
  const [imported, setImported] = useState<PlanningUnit[]>([]);
  const [previewErrors, setPreviewErrors] = useState<
    { row: number; message: string }[]
  >([]);
  const [sector, setSector] = useState<[number, number]>();
  const [sources, setSources] = useState<SourceChoice[]>([]);
  const [volume, setVolume] = useState(3000);
  const [focus, setFocus] = useState<FocusRequest>();
  const focusDecision: FocusDecision = (value, moment) => {
    if (value.feature) setFocus({ feature: value.feature, token: Date.now() });
    if (moment && value.event_min != null) {
      setMinute(Math.max(0, Math.floor(value.event_min)));
      setPlaying(false);
    }
  };
  const [lead, setLead] = useState(10);
  const [comparison, setComparison] = useState<MobilityComparison>();
  const [dirty, setDirty] = useState(false);
  const [active, setActive] = useState<"A" | "B" | "both">("both");
  const [minute, setMinute] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [fire, setFire] = useState<FeatureCollection>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.scenario(scenarioId),
      api.mobility(scenarioId),
      api.mobilityRoads(scenarioId),
      api.scenarioRuns(scenarioId),
      api.mobilityComparisons(scenarioId),
      api.accessAssessments(scenarioId),
    ])
      .then(
        ([
          nextScenario,
          nextMobility,
          nextRoads,
          nextRuns,
          nextSaved,
          nextAssessments,
        ]) => {
          if (cancelled) return;
          setScenario(nextScenario);
          setMobility(nextMobility);
          setRoads(nextRoads);
          setSaved(nextSaved);
          setAssessments(nextAssessments);
          setPopulationPoints(
            nextScenario.points.filter((point) => point.population_role),
          );
          const ready = nextRuns.filter(
            (run) => run.mode === "single" && run.status === "ready",
          );
          setRuns(ready);
          const requested = new URLSearchParams(location.search).get("run");
          const compatible = ready.filter(
            (run) => run.area_package_id === nextScenario.area_package_id,
          );
          const selected = requested ? compatible.find((run) => run.id === requested) : compatible[0];
          if (requested && !selected) setError("A simulação pedida está indisponível ou não é compatível com esta ocorrência. Escolha uma simulação de referência concluída.");
          if (selected) selectRun(selected, nextScenario, true);
          const available = nextMobility.units.find((unit) =>
            nextMobility.vehicles.some(
              (vehicle) =>
                vehicle.id === unit.vehicle_id &&
                vehicle.vehicle_class === "tanker" &&
                unit.latest_location,
            ),
          );
          if (available) setUnitId(available.id);
          const points = nextScenario.points
            .filter((point) => point.kind === "water_point")
            .sort(
              (a, b) =>
                Number(b.id.startsWith("decision-source")) -
                Number(a.id.startsWith("decision-source")),
            );
          setSources(
            points
              .slice(0, 2)
              .map((point) => ({
                point_id: point.id,
                flow_l_min:
                  point.water?.shared_flow_l_min ||
                  point.water?.flow_l_min ||
                  null,
                available_volume_l: point.water?.available_volume_l ?? null,
                setup_time_min: point.water?.setup_time_min ?? 0,
              })),
          );
          const target =
            nextScenario.points.find(
              (point) => point.kind === "delivery_point",
            ) ||
            nextScenario.points.find((point) => point.kind === "staging_area");
          setSector(
            target?.coordinates ||
              nextScenario.simulation.ignitions[0].coordinates,
          );
          const preparedExample =
            nextSaved.find(
              (value) =>
                value.run_id === selected?.id &&
                value.id.startsWith("demo-rich-") &&
                value.unit.callsign === "TQ-05" &&
                value.id.endsWith("-01-base"),
            ) ||
            nextSaved.find(
              (value) =>
                value.run_id === selected?.id &&
                value.id.startsWith("demo-") &&
                value.id.endsWith("-base"),
            );
          if (preparedExample && (!requested || preparedExample.run_id === requested))
            restoreComparison(preparedExample, nextAssessments);
        },
      )
      .catch((reason) => setError(message(reason)));
    return () => {
      cancelled = true;
    };
  }, [scenarioId]);

  function selectRun(run: Run, workspace = scenario, initial = false) {
    setRunId(run.id);
    const start =
      run.run_context?.scenario_start_time || workspace?.start_time || "";
    setForecastStart(start ? localDateTime(start) : "");
    setDeparture(
      start
        ? localDateTime(
            new Date(new Date(start).getTime() + 10 * 60000).toISOString(),
          )
        : "",
    );
    setMinute(0);
    setDirty(!initial);
    if (!initial) updatePageQuery("run", run.id);
  }

  const units = useMemo(
    () => [
      ...imported,
      ...(mobility?.units || [])
        .filter((unit) => !imported.some((value) => value.id === unit.id))
        .flatMap((unit) => {
          const vehicle = mobility?.vehicles.find(
            (value) => value.id === unit.vehicle_id,
          );
          return vehicle && unit.latest_location
            ? [
                {
                  id: unit.id,
                  callsign: unit.callsign,
                  organisation: unit.organisation,
                  vehicle,
                  coordinates: unit.latest_location.coordinates,
                  observed_at: unit.latest_location.observed_at,
                } as PlanningUnit,
              ]
            : [];
        }),
    ],
    [mobility, imported],
  );
  const unit = units.find((value) => value.id === unitId);
  const chosenSources = sources.map((value) =>
    scenario?.points.find((point) => point.id === value.point_id),
  );
  const showRunId = comparison?.run_id || runId;
  const displayedRun = runs.find((run) => run.id === showRunId);
  function restoreComparison(
    value: MobilityComparison,
    availableAssessments = assessments,
  ) {
    setComparison(value);
    setDirty(false);
    setRunId(value.run_id);
    setForecastStart(localDateTime(value.forecast_start_at));
    setDeparture(
      localDateTime(
        new Date(
          new Date(value.forecast_start_at).getTime() +
            value.departure_min * 60000,
        ).toISOString(),
      ),
    );
    setImported((values) => [
      value.unit,
      ...values.filter((unit) => unit.id !== value.unit.id),
    ]);
    setUnitId(value.unit.id);
    setSector(value.delivery_coordinates);
    setVolume(value.requested_l);
    setLead(value.lead_time_min);
    setSources(value.outcomes.map((outcome) => outcome.assumptions));
    setMinute(Math.floor(value.departure_min));
    setActive("both");
    setPlaying(false);
    const linked = availableAssessments.find(
      (item) => item.comparison_id === value.id,
    );
    setAssessment(linked);
    setSelectedSectionId(linked?.section_id || "");
    if (linked) setPopulationVehicle(linked.population_vehicle);
    setProposalMode("without");
    setAssessmentDirty(false);
    setSelectedOriginId(
      linked?.population_points.find(
        (point) => point.population_role === "origin",
      )?.id || "",
    );
    setSelectedReceptionId("");
  }
  useEffect(() => {
    if (!comparison) {
      setAccessRoads(undefined);
      return;
    }
    let cancelled = false;
    api
      .accessRoads(scenarioId, comparison.id)
      .then((value) => {
        if (!cancelled) setAccessRoads(value);
      })
      .catch((reason) => {
        if (!cancelled) {
          setAccessRoads(undefined);
          setError(message(reason));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [scenarioId, comparison?.id]);
  useEffect(() => {
    if (!showRunId) {
      setFire(undefined);
      return;
    }
    let stopped = false;
    api
      .fire(showRunId, Math.floor(minute))
      .then((value) => {
        if (!stopped) setFire(value);
      })
      .catch(() => {
        if (!stopped) setFire(undefined);
      });
    return () => {
      stopped = true;
    };
  }, [showRunId, minute]);
  useEffect(() => {
    if (!playing || !displayedRun) return;
    const timer = window.setInterval(
      () =>
        setMinute((value) =>
          value >=
          (comparison?.horizon_min || displayedRun.scenario.duration_min)
            ? 0
            : value + 1,
        ),
      350,
    );
    return () => window.clearInterval(timer);
  }, [playing, displayedRun, comparison?.horizon_min]);

  async function compare() {
    if (
      !unit ||
      !sector ||
      !forecastStart ||
      !departure ||
      sources.length !== 2 ||
      !runId
    )
      return;
    setBusy(true);
    setError("");
    setPlaying(false);
    try {
      const input: ComparisonInput = {
        run_id: runId,
        forecast_start_at: new Date(forecastStart).toISOString(),
        departure_at: new Date(departure).toISOString(),
        unit,
        delivery_coordinates: sector,
        requested_l: volume,
        sources,
        lead_time_min: lead,
      };
      const result = await api.compareMobility(scenarioId, input);
      setComparison(result);
      setSaved((values) => [result, ...values]);
      setDirty(false);
      setAssessment(undefined);
      setSelectedSectionId("");
      setProposalMode("without");
      setAssessmentDirty(false);
      setMinute(Math.max(0, Math.floor(result.departure_min)));
      setActive("both");
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  async function previewCsv(file: File) {
    setError("");
    try {
      const result = await api.previewPlanningCsv(
        scenarioId,
        file.name,
        await file.text(),
      );
      setPreviewErrors(result.errors);
      setImported(result.units);
      if (result.units.length) {
        setUnitId(result.units[0].id);
        setDirty(true);
      }
    } catch (reason) {
      setError(message(reason));
    }
  }

  function changeSource(index: number, id: string) {
    const point = scenario?.points.find((value) => value.id === id);
    const next = [...sources];
    next[index] = {
      point_id: id,
      flow_l_min:
        point?.water?.shared_flow_l_min || point?.water?.flow_l_min || null,
      available_volume_l: point?.water?.available_volume_l ?? null,
      setup_time_min: point?.water?.setup_time_min ?? 0,
    };
    setSources(next);
    setDirty(true);
  }
  function sourceField(
    index: number,
    field: "flow_l_min" | "available_volume_l" | "setup_time_min",
    raw: string,
  ) {
    setSources((values) =>
      values.map((value, i) =>
        i === index
          ? { ...value, [field]: raw === "" ? null : Number(raw) }
          : value,
      ),
    );
    setDirty(true);
  }

  async function assessAccess() {
    if (!comparison || dirty) return;
    setBusy(true);
    setError("");
    setPlaying(false);
    try {
      const result = await api.assessAccess(scenarioId, {
        comparison_id: comparison.id,
        section_id: selectedSectionId || null,
        points: populationPoints,
        population_vehicle: populationVehicle,
      });
      setAssessment(result);
      setAssessments((values) => [result, ...values]);
      setAssessmentDirty(false);
      setProposalMode(selectedSectionId ? "with_proposal" : "without");
      setSelectedOriginId(
        result.population_points.find(
          (point) => point.population_role === "origin",
        )?.id || "",
      );
      setSelectedReceptionId("");
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  async function savePopulation() {
    if (!scenario) return;
    setSavingPopulation(true);
    setError("");
    try {
      const ids = new Set(populationPoints.map((point) => point.id));
      const all = scenario.points
        .filter((point) => !ids.has(point.id))
        .map((point) =>
          point.population_role
            ? ({
                ...point,
                population_role: null,
                population_count: null,
              } as ScenarioPoint)
            : point,
        );
      const result = await api.saveScenario(
        { ...scenario, points: [...all, ...populationPoints] },
        scenario.revision,
      );
      setScenario(result);
      setPopulationDirty(false);
    } catch (reason) {
      setError(message(reason));
    } finally {
      setSavingPopulation(false);
    }
  }

  useEffect(() => { if (runId) rememberRun(scenarioId, runId); }, [scenarioId, runId]);
  useEffect(() => {
    const requested = navigationRoute.runId;
    if (requested && runs.length && requested !== runId) {
      const selected = runs.find((run) => run.id === requested && run.area_package_id === scenario?.area_package_id);
      if (selected) selectRun(selected, scenario, true);
      else setError("A simulação pedida está indisponível ou não é compatível com esta ocorrência.");
    }
  }, [navigationRoute.runId, runs]);
  const unsaved = dirty || populationDirty || assessmentDirty;
  useNavigationGuard((to) => {
    if (to.kind === "decisions" && to.scenarioId === scenarioId && (!to.runId || to.runId === runId)) return true;
    if (busy || savingPopulation) { setError("Aguarde a conclusão da operação antes de sair."); return false; }
    return !unsaved || confirmDiscard();
  }, unsaved);

  if (currentUser.role === "crew")
    return (
      <main className="decision-shell">
        A comparação requer acesso de coordenação.
      </main>
    );
  if (!scenario || !mobility)
    return error ? (
      <main className="decision-shell decision-setup" role="alert">
        {error}
        <ButtonLink variant="ghost" href="/scenarios">← Voltar às ocorrências</ButtonLink>
      </main>
    ) : (
      <ScenarioLoading label="A carregar ocorrência…" />
    );
  const mapCenter = sector || scenario.simulation.ignitions[0].coordinates;
  const shownAssessment =
    assessment?.comparison_id === comparison?.id ? assessment : undefined;
  const displayedComparison =
    shownAssessment && !assessmentDirty
      ? comparisonForAssessment(shownAssessment, proposalMode)
      : comparison;
  const selectedRoad = accessRoads?.features.find(
    (feature) => feature.properties?.section_id === selectedSectionId,
  );
  return (
    <main className="decision-shell">
      <div className="workspace-context decision-context">
        <Typography as="h1" variant="h3">{navigationRoute.title}</Typography>
        <span>Simulação de referência: {displayedRun?.name || "por escolher"}</span>
        <span>Referência: {comparison ? formatDateTime(comparison.forecast_start_at) : forecastStart || "por definir"}</span>
        <span>Resultado criado: {displayedRun?.created_at ? formatDateTime(displayedRun.created_at) : "—"}</span>
      </div>
      {error && (
        <Typography
          as="p"
          variant="small"
          className="decision-error"
          role="alert"
        >
          {error}
        </Typography>
      )}
      {pane === "compare" && (shownAssessment || dirty || assessmentDirty || populationDirty) && (
        <div className="decision-toolbar" aria-label="Resumo da comparação">
          {shownAssessment && <>
            <label className="decision-proposal">
              Proposta
              <select value={proposalMode} onChange={(event) => setProposalMode(event.target.value as ProposalMode)}>
                <option value="without">Sem proposta</option>
                <option value="with_proposal" disabled={!shownAssessment.section_id}>Com encerramento proposto</option>
              </select>
            </label>
            <ImpactSummary
              compact
              assessment={shownAssessment}
              mode={proposalMode}
              onWater={() => selectPerspective("water")}
              onPopulation={() => selectPerspective("population")}
            />
          </>}
          {(dirty || assessmentDirty || populationDirty) && <span className="decision-stale-chip">Por recalcular</span>}
        </div>
      )}
      {pane === "compare" && (
        <details className="decision-reference"><summary>Simulação de referência</summary>
          <Card as="section" className="decision-setup">
            <Typography as="h2" variant="h3">
              Simulação de incêndio
            </Typography>
            <Typography as="p" variant="body">
              Escolha uma simulação concluída para avaliar ambos os percursos
              nas mesmas condições.
            </Typography>
                <label>
                  Simulação de referência
                  <select
                    value={runId}
                    onChange={(event) => {
                      const run = runs.find(
                        (value) => value.id === event.target.value,
                      );
                      if (run) selectRun(run);
                    }}
                  >
                    {runs
                      .filter(
                        (run) =>
                          run.area_package_id === scenario.area_package_id ||
                          run.id === comparison?.run_id,
                      )
                      .map((run) => (
                        <option key={run.id} value={run.id}>
                          {run.name}
                          {run.area_package_id !== scenario.area_package_id
                            ? " · arquivo"
                            : ""}
                        </option>
                      ))}
                  </select>
                </label>
            <a
              href={`/scenarios/${scenarioId}/simulation${runId ? `?run=${encodeURIComponent(runId)}` : ""}`}
            >
              Abrir análise do resultado →
            </a>
            {!runs.length && (
              <Typography as="p" variant="body">
                Sem simulação concluída. Prepare e execute um cenário antes de
                comparar decisões.
              </Typography>
            )}
          </Card>
        </details>
      )}
      {pane === "data" && (
        <SectionContainer spacing="compact">
          <Card as="section" className="decision-setup">
            <Typography as="h2" variant="h3">
              Dados da ocorrência
            </Typography>
            <Typography as="p" variant="body">
              Terreno e estradas:{" "}
              {scenario.area_package_id
                ? `pacote ${scenario.area_package_id}`
                : "rede legada preparada"}
              . Fontes de água:{" "}
              {
                scenario.points.filter((point) => point.kind === "water_point")
                  .length
              }{" "}
              pontos; confirme fluxo e volume atuais antes de comparar.
            </Typography>
            <Typography as="p" variant="body">
              Os dados de ocorrência podem vir de Fogos.pt. Os recursos
              individuais podem ser importados de um ficheiro CSV. Conectores de
              sistemas de despacho não estão configurados.
            </Typography>
            <Typography as="h3" variant="h3">
              Importar viaturas para planeamento
            </Typography>
            <Typography as="p" variant="body">
              Os dados importados ficam neste rascunho e são guardados apenas no
              instantâneo da comparação; não alteram unidades em operação.
            </Typography>
            <a
              href={`data:text/csv;charset=utf-8,${encodeURIComponent(CSV_TEMPLATE)}`}
              download="modelo-viaturas.csv"
            >
              Descarregar modelo CSV
            </a>
            <label>
              Ficheiro CSV
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void previewCsv(file);
                }}
              />
            </label>
            {imported.length > 0 && (
              <Typography as="h3" variant="h3">
                Viaturas no rascunho
              </Typography>
            )}
            {imported.map((value) => (
              <Typography as="p" variant="body" key={value.id}>
                {value.callsign} · {value.organisation} · observado{" "}
                {value.observed_at || "—"} · origem{" "}
                {value.source_file || "registo local"}
              </Typography>
            ))}
            {previewErrors.map((value) => (
              <Typography as="p" variant="body" key={value.row} role="alert">
                Linha {value.row}: {value.message}
              </Typography>
            ))}
            <Typography as="h3" variant="h3">
              Origem das fontes
            </Typography>
            {scenario.points
              .filter((point) => point.kind === "water_point")
              .map((point) => (
                <Typography as="p" variant="body" key={point.id}>
                  {point.name} ·{" "}
                  {point.source === "demo"
                    ? "dados fictícios de exercício"
                    : point.source}{" "}
                  · {point.source_updated_at || "data de origem não indicada"}
                </Typography>
              ))}
            <Typography as="p" variant="body">
              Dados de fontes históricos não confirmam disponibilidade ou stock
              atual. Introduza observações no painel de comparação.
            </Typography>
          </Card>
        </SectionContainer>
      )}
      {pane === "data" && (
        <SectionContainer spacing="compact">
          <Card as="section" className="decision-setup">
            <PopulationDataEditor
              scenario={scenario}
              points={populationPoints}
              vehicle={populationVehicle}
              dirty={populationDirty}
              saving={savingPopulation}
              onPoints={(value) => {
                setPopulationPoints(value);
                setPopulationDirty(true);
                setAssessmentDirty(true);
              }}
              onVehicle={(value) => {
                setPopulationVehicle(value);
                setPopulationDirty(true);
                setAssessmentDirty(true);
              }}
              onSave={() => void savePopulation()}
            />
          </Card>
        </SectionContainer>
      )}
      {pane === "compare" && (
        <Box className="exercise-story">
          <strong>{scenario.name}</strong> · {scenario.description}
        </Box>
      )}
      {pane === "compare" && (
        <Box className="decision-layout">
          <Card
            as="aside"
            density="compact"
            shadow="none"
            className="decision-input"
          >
            {perspective === "water" ? (
              <>
                <Typography as="span" variant="label">
                  Uma situação · duas escolhas
                </Typography>
                <Typography as="h2" variant="h3">
                  Comparar fontes de água
                </Typography>
                <Typography as="p" variant="body">
                  O mesmo camião, hora e incêndio são usados em A e B.
                </Typography>
                {!runs.length && (
                  <a href={`/scenarios/${scenarioId}/experiments/new`}>
                    Criar uma simulação →
                  </a>
                )}
                <label>
                  Início da simulação
                  <input
                    type="datetime-local"
                    value={forecastStart}
                    onChange={(event) => {
                      setForecastStart(event.target.value);
                      setDirty(true);
                    }}
                  />
                </label>
                <label>
                  Partida
                  <input
                    type="datetime-local"
                    value={departure}
                    onChange={(event) => {
                      setDeparture(event.target.value);
                      setDirty(true);
                    }}
                  />
                </label>
                <label>
                  Viatura
                  <select
                    value={unitId}
                    onChange={(event) => {
                      setUnitId(event.target.value);
                      setDirty(true);
                    }}
                  >
                    <option value="">Escolher viatura</option>
                    {units.map((value) => (
                      <option key={value.id} value={value.id}>
                        {value.callsign} · {value.vehicle.name}
                      </option>
                    ))}
                  </select>
                </label>
                {unit && (
                  <Card
                    density="compact"
                    shadow="none"
                    className="vehicle-facts"
                  >
                    <strong>
                      {unit.vehicle.water_tank_capacity_l?.toLocaleString(
                        "pt-PT",
                      )}{" "}
                      L · bomba {unit.vehicle.pump_flow_l_min} L/min
                    </strong>
                    <span>
                      {unit.vehicle.width_m ?? "?"} m de largura ·{" "}
                      {unit.vehicle.weight_t ?? "?"} t ·{" "}
                      {unit.vehicle.off_road
                        ? "acesso a piso não pavimentado"
                        : "circulação rodoviária"}
                    </span>
                    <Typography as="small" variant="small">
                      Partida:{" "}
                      {unit.coordinates
                        .map((value) => value.toFixed(4))
                        .join(", ")}{" "}
                      · localização de{" "}
                      {unit.observed_at
                        ? new Date(unit.observed_at).toLocaleString("pt-PT")
                        : "exercício"}
                      {unit.source_file ? ` · ${unit.source_file}` : ""}
                    </Typography>
                  </Card>
                )}
                <label>
                  Setor de entrega
                  <select
                    value={sector?.join(",") || ""}
                    onChange={(event) => {
                      setSector(
                        event.target.value.split(",").map(Number) as [
                          number,
                          number,
                        ],
                      );
                      setDirty(true);
                    }}
                  >
                    {scenario.points
                      .filter(
                        (point) =>
                          point.kind === "delivery_point" ||
                          point.kind === "staging_area",
                      )
                      .map((point) => (
                        <option
                          key={point.id}
                          value={point.coordinates.join(",")}
                        >
                          {point.name}
                        </option>
                      ))}
                  </select>
                </label>
                <Box className="decision-pair">
                  <label>
                    Água pretendida (L)
                    <input
                      type="number"
                      min="1"
                      value={volume}
                      onChange={(event) => {
                        setVolume(Number(event.target.value));
                        setDirty(true);
                      }}
                    />
                  </label>
                  <label>
                    Antecedência (min)
                    <input
                      type="number"
                      min="0"
                      max="120"
                      value={lead}
                      onChange={(event) => {
                        setLead(Number(event.target.value));
                        setDirty(true);
                      }}
                    />
                  </label>
                </Box>
                {sources.map((choice, index) => (
                  <fieldset key={index} className="decision-source">
                    <legend>Fonte {index === 0 ? "A" : "B"}</legend>
                    <label>
                      Ponto
                      <select
                        value={choice.point_id}
                        onChange={(event) =>
                          changeSource(index, event.target.value)
                        }
                      >
                        <option value="">Escolher</option>
                        {scenario.points
                          .filter((point) => point.kind === "water_point")
                          .map((point) => (
                            <option key={point.id} value={point.id}>
                              {point.name}
                            </option>
                          ))}
                      </select>
                    </label>
                    <Box className="decision-pair">
                      <label>
                        Fluxo L/min
                        <input
                          type="number"
                          min="1"
                          value={choice.flow_l_min ?? ""}
                          onChange={(event) =>
                            sourceField(index, "flow_l_min", event.target.value)
                          }
                        />
                      </label>
                      <label>
                        Água atual L
                        <input
                          type="number"
                          min="0"
                          value={choice.available_volume_l ?? ""}
                          onChange={(event) =>
                            sourceField(
                              index,
                              "available_volume_l",
                              event.target.value,
                            )
                          }
                        />
                      </label>
                    </Box>
                    <label>
                      Preparação min
                      <input
                        type="number"
                        min="0"
                        value={choice.setup_time_min ?? ""}
                        onChange={(event) =>
                          sourceField(
                            index,
                            "setup_time_min",
                            event.target.value,
                          )
                        }
                      />
                    </label>
                    <Typography as="small" variant="small">
                      {verificationLabel(
                        chosenSources[index]?.water?.verification_status,
                      )}{" "}
                      · {sourceLabel(chosenSources[index]?.source)}
                    </Typography>
                  </fieldset>
                ))}
                <Button
                  variant="primary"
                  className="ds-full"
                  disabled={
                    busy ||
                    !runId ||
                    !unit ||
                    !forecastStart ||
                    !departure ||
                    !sector ||
                    sources.length !== 2 ||
                    sources.some((source) => !source.point_id) ||
                    sources[0]?.point_id === sources[1]?.point_id
                  }
                  onClick={() => void compare()}
                >
                  {busy ? "A calcular…" : "Comparar alternativas"}
                </Button>
                {dirty && comparison && (
                  <Typography as="p" variant="body" className="decision-stale">
                    Entradas alteradas. Os resultados abaixo pertencem à
                    comparação anterior.
                  </Typography>
                )}
                <details>
                  <summary>Comparações guardadas ({saved.length})</summary>
                  {saved.map((value) => (
                    <Button
                      variant="secondary"
                      key={value.id}
                      onClick={() => restoreComparison(value)}
                    >
                      {value.unit.callsign} ·{" "}
                      {value.requested_l.toLocaleString("pt-PT")} L · partida{" "}
                      {scenarioClock(value, value.departure_min)}
                      <Typography as="small" variant="small">
                        {value.outcomes
                          .map((outcome) => outcome.source.name)
                          .join(" ↔ ")}
                      </Typography>
                    </Button>
                  ))}
                </details>
              </>
            ) : perspective === "access" ? (
              <>
                <Typography as="span" variant="label">
                  Mesma simulação · outro efeito
                </Typography>
                <Typography as="h2" variant="h3">
                  Acessos
                </Typography>
                <Typography as="p" variant="body">
                  Escolha um troço no mapa. A proposta fecha esse troço nos dois
                  sentidos, para todas as viaturas avaliadas, desde a partida
                  até ao fim da simulação.
                </Typography>
                {!comparison && (
                  <Typography as="p" variant="body">
                    Faça primeiro a comparação de abastecimento.
                  </Typography>
                )}
                {comparison && (
                  <>
                    <Typography as="p" variant="body">
                      Comparação de água:{" "}
                      {new Date(comparison.created_at).toLocaleString("pt-PT")}{" "}
                      · partida min {comparison.departure_min}
                    </Typography>
                    <Box className="access-legend">
                      <span>● Exposição modelada</span>
                      <span>▰ Restrição registada</span>
                      <span>▱ Proposta de exercício</span>
                    </Box>
                    {selectedRoad ? (
                      <Card
                        density="compact"
                        shadow="none"
                        className="selected-road"
                      >
                        <Typography as="h3" variant="h3">
                          {String(
                            selectedRoad.properties?.road_name ||
                              "Troço selecionado",
                          )}
                        </Typography>
                        <Typography as="p" variant="body">
                          {typeof selectedRoad.properties
                            ?.first_exposure_min === "number"
                            ? `Exposição modelada desde o minuto ${Number(selectedRoad.properties.first_exposure_min).toFixed(1)}.`
                            : "Sem exposição modelada neste horizonte."}
                        </Typography>
                        <Typography as="p" variant="body">
                          Gabarito:{" "}
                          {String(selectedRoad.properties?.maxwidth || "?")} m
                          de largura ·{" "}
                          {String(selectedRoad.properties?.maxheight || "?")} m
                          de altura ·{" "}
                          {String(selectedRoad.properties?.maxweight || "?")} t.
                        </Typography>
                        {Boolean(
                          selectedRoad.properties?.exercise_assumption,
                        ) && (
                          <Typography as="p" variant="body">
                            {String(
                              selectedRoad.properties.exercise_assumption,
                            )}
                          </Typography>
                        )}
                        {Boolean(selectedRoad.properties?.coverage_unknown) && (
                          <Typography as="p" variant="body">
                            Cobertura do fogo incompleta neste troço.
                          </Typography>
                        )}
                        {(Array.isArray(selectedRoad.properties?.reports)
                          ? selectedRoad.properties.reports
                          : []
                        ).map(
                          (report: {
                            id: string;
                            kind: string;
                            status: string;
                            observed_at: string;
                          }) => (
                            <Typography as="p" variant="body" key={report.id}>
                              Restrição registada: {report.kind} ·{" "}
                              {report.status} ·{" "}
                              {new Date(report.observed_at).toLocaleString(
                                "pt-PT",
                              )}
                            </Typography>
                          ),
                        )}
                      </Card>
                    ) : (
                      <Typography as="p" variant="body">
                        Selecione um troço no mapa para ver os dados e testar o
                        encerramento.
                      </Typography>
                    )}
                    <Button
                      variant="primary"
                      className="ds-full"
                      disabled={
                        busy || dirty || populationDirty || !selectedSectionId
                      }
                      onClick={() => void assessAccess()}
                    >
                      {busy ? "A calcular…" : "Testar encerramento deste troço"}
                    </Button>
                    {dirty && (
                      <Typography
                        as="p"
                        variant="body"
                        className="decision-stale"
                      >
                        Recalcule primeiro a comparação de água com as novas
                        entradas.
                      </Typography>
                    )}
                    {(assessmentDirty || populationDirty) &&
                      shownAssessment && (
                        <Typography
                          as="p"
                          variant="body"
                          className="decision-stale"
                        >
                          Por recalcular. O resultado mostrado pertence à
                          proposta guardada.
                        </Typography>
                      )}
                    <details>
                      <summary>
                        Avaliações guardadas (
                        {
                          assessments.filter(
                            (value) => value.comparison_id === comparison?.id,
                          ).length
                        }
                        )
                      </summary>
                      {assessments
                        .filter(
                          (value) => value.comparison_id === comparison?.id,
                        )
                        .map((value) => (
                          <Button
                            variant="secondary"
                            key={value.id}
                            onClick={() => {
                              setAssessment(value);
                              setSelectedSectionId(value.section_id || "");
                              setAssessmentDirty(false);
                              setProposalMode(
                                value.section_id ? "with_proposal" : "without",
                              );
                            }}
                          >
                            {new Date(value.created_at).toLocaleString("pt-PT")}{" "}
                            ·{" "}
                            {value.section_id ? "com proposta" : "sem proposta"}
                          </Button>
                        ))}
                    </details>
                  </>
                )}
              </>
            ) : (
              <>
                <Typography as="span" variant="label">Acesso à receção</Typography>
                <Typography as="h2" variant="h3">
                  Apoio à população
                </Typography>
                <Typography as="p" variant="body">
                  As origens e os pontos de receção usam o mesmo incêndio e a
                  mesma hora de partida do abastecimento.
                </Typography>
                <Typography as="p" variant="body">
                  {
                    populationPoints.filter(
                      (point) => point.population_role === "origin",
                    ).length
                  }{" "}
                  origens ·{" "}
                  {
                    populationPoints.filter(
                      (point) => point.population_role === "reception",
                    ).length
                  }{" "}
                  pontos de receção
                </Typography>
                <Button variant="secondary" onClick={() => void navigateTo(workspaceHref(scenarioId, "/decisions?view=data"))}>
                  Editar locais e viatura em Dados →
                </Button>
                {comparison && (
                  <Button
                    variant="primary"
                    className="ds-full"
                    disabled={
                      busy ||
                      dirty ||
                      populationDirty ||
                      !populationPoints.some(
                        (point) => point.population_role === "origin",
                      ) ||
                      !populationPoints.some(
                        (point) => point.population_role === "reception",
                      )
                    }
                    onClick={() => void assessAccess()}
                  >
                    {busy ? "A calcular…" : "Avaliar acessos à receção"}
                  </Button>
                )}
                {!comparison && (
                  <Typography as="p" variant="body">
                    Faça primeiro a comparação de abastecimento.
                  </Typography>
                )}
                {populationDirty && (
                  <Typography as="p" variant="body" className="decision-stale">
                    Guarde os pontos em Dados antes de avaliar.
                  </Typography>
                )}
                {assessmentDirty && shownAssessment && (
                  <Typography as="p" variant="body" className="decision-stale">
                    Por recalcular. Os resultados abaixo pertencem aos dados
                    guardados.
                  </Typography>
                )}
                <Typography as="p" variant="small" className="decision-note">
                  Percursos para uma viatura ligeira de exercício. Pessoas
                  indicadas por local são dados fornecidos; não representam
                  pessoas evacuadas.
                </Typography>
              </>
            )}
          </Card>
          <Box className="decision-map-panel">
            <Box className="decision-map">
              <MapContainer
                center={[mapCenter[1], mapCenter[0]]}
                zoom={15}
                scrollWheelZoom
                className="decision-leaflet"
              >
                <MapResize />
                <TileLayer
                  attribution="&copy; OpenStreetMap contributors"
                  url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                {roads && (
                  <GeoJSON
                    key={scenario.area_package_id || "legacy"}
                    data={roads}
                    style={{ color: "#638094", weight: 2, opacity: 0.55 }}
                  />
                )}
                {fire && (
                  <GeoJSON
                    key={`${showRunId}-${minute}`}
                    data={fire}
                    style={{
                      color: "#f1793d",
                      fillColor: "#f1793d",
                      fillOpacity: 0.35,
                      weight: 1,
                    }}
                  />
                )}
                {scenario.points
                  .filter((point) => point.kind === "water_point")
                  .map((point) => (
                    <CircleMarker
                      key={point.id}
                      center={[point.coordinates[1], point.coordinates[0]]}
                      radius={7}
                      pathOptions={{
                        color: "#3a9ec3",
                        fillColor: "#3a9ec3",
                        fillOpacity: 1,
                      }}
                    >
                      <Popup>{point.name}</Popup>
                    </CircleMarker>
                  ))}
                {(comparison?.delivery_coordinates || sector) && (
                  <CircleMarker
                    center={[
                      (comparison?.delivery_coordinates || sector)![1],
                      (comparison?.delivery_coordinates || sector)![0],
                    ]}
                    radius={9}
                    pathOptions={{
                      color: "#f2ca68",
                      fillColor: "#f2ca68",
                      fillOpacity: 1,
                    }}
                  >
                    <Popup>Setor de entrega</Popup>
                  </CircleMarker>
                )}
                {perspective !== "population" &&
                  displayedComparison &&
                  displayedComparison.outcomes
                    .filter(
                      (value) => active === "both" || value.label === active,
                    )
                    .flatMap((value) =>
                      value.stages
                        .filter((stage) => stage.route?.feature)
                        .map((stage) => (
                          <GeoJSON
                            key={`${displayedComparison.id}-${value.label}-${stage.kind}`}
                            data={stage.route!.feature}
                            style={{
                              color:
                                value.label === "A" ? "#38bdf8" : "#b68cff",
                              weight: active === value.label ? 7 : 5,
                              opacity: 0.9,
                            }}
                          />
                        )),
                    )}
                {perspective !== "population" &&
                  displayedComparison &&
                  displayedComparison.outcomes
                    .filter(
                      (value) =>
                        (active === "both" || value.label === active) &&
                        value.status !== "clear" &&
                        value.baseline_feature,
                    )
                    .map((value) => (
                      <GeoJSON
                        key={`baseline-${value.label}`}
                        data={value.baseline_feature!}
                        style={{
                          color: "#f9b84e",
                          weight: 3,
                          dashArray: "6 5",
                          opacity: 0.8,
                        }}
                      />
                    ))}
                {perspective !== "population" &&
                  displayedComparison &&
                  displayedComparison.outcomes
                    .filter(
                      (value) => active === "both" || value.label === active,
                    )
                    .filter((value) => value.conflict?.feature)
                    .map((value) => (
                      <GeoJSON
                        key={`road-conflict-${value.label}`}
                        data={value.conflict!.feature!}
                        style={{ color: "#ff785f", weight: 7, opacity: 0.9 }}
                      />
                    ))}
                {perspective !== "population" &&
                  displayedComparison &&
                  displayedComparison.outcomes
                    .filter(
                      (value) => active === "both" || value.label === active,
                    )
                    .filter(
                      (value) => value.conflict?.reason === "source_exposure",
                    )
                    .map((value) => (
                      <CircleMarker
                        key={`conflict-${value.label}`}
                        center={[
                          value.source.coordinates[1],
                          value.source.coordinates[0],
                        ]}
                        radius={15}
                        pathOptions={{
                          color: "#ff785f",
                          fillOpacity: 0,
                          weight: 3,
                        }}
                      >
                        <Popup>
                          Conflito na fonte {value.label} · exposição no minuto{" "}
                          {value.conflict?.exposure_min}
                        </Popup>
                      </CircleMarker>
                    ))}
                {perspective !== "population" &&
                  displayedComparison &&
                  displayedComparison.outcomes
                    .filter(
                      (value) => active === "both" || value.label === active,
                    )
                    .map((value) => {
                      const point = movingPosition(
                        value.stages,
                        minute,
                        displayedComparison.unit.coordinates,
                      );
                      return (
                        <CircleMarker
                          key={`sim-${value.label}`}
                          center={[point[1], point[0]]}
                          radius={8}
                          pathOptions={{
                            color: "#fff",
                            fillColor:
                              value.label === "A" ? "#38bdf8" : "#b68cff",
                            fillOpacity: 1,
                            weight: 2,
                          }}
                        >
                          <Popup>
                            Posição simulada {value.label} · minuto {minute}
                          </Popup>
                        </CircleMarker>
                      );
                    })}
                <AccessMapLayers
                  assessment={shownAssessment}
                  mode={proposalMode}
                  perspective={perspective}
                  roads={accessRoads}
                  pointsOverride={populationPoints}
                  selectedSectionId={selectedSectionId}
                  selectedOriginId={selectedOriginId}
                  selectedReceptionId={selectedReceptionId}
                  minute={minute}
                  onRoad={(id) => {
                    setSelectedSectionId(id);
                    setAssessmentDirty(
                      populationDirty || id !== shownAssessment?.section_id,
                    );
                  }}
                />
                <DecisionFocusLayer focus={focus} />
              </MapContainer>
            </Box>
            <Box className="decision-timeline">
              <Button
                variant="secondary"
                onClick={() => setPlaying(!playing)}
                disabled={!displayedRun}
              >
                {playing ? "Pausar" : "Reproduzir"}
              </Button>
              <strong>Min {minute}</strong>
              <input
                aria-label="Minuto da simulação"
                type="range"
                min={0}
                max={
                  comparison?.horizon_min ||
                  displayedRun?.scenario.duration_min ||
                  120
                }
                value={minute}
                onChange={(event) => {
                  setMinute(Number(event.target.value));
                  setPlaying(false);
                }}
              />
              <span>
                {comparison?.horizon_min ||
                  displayedRun?.scenario.duration_min ||
                  120}{" "}
                min
              </span>
            </Box>
            {displayedComparison && perspective !== "population" && (
              <TimelineEvents comparison={displayedComparison} />
            )}
            <Typography as="p" variant="small" className="decision-map-caption">
              Incêndio modelado ·{" "}
              {displayedRun?.scenario.engine || "sem simulação"} · as posições
              das viaturas são simuladas. Linha amarela tracejada: viagem normal
              para diagnóstico, não recomendação.
            </Typography>
          </Box>
          <Card
            as="aside"
            density="compact"
            shadow="none"
            className="decision-output"
          >
            {perspective === "water" && displayedComparison && (
              <>
                <Typography as="p" variant="small" className="decision-note">
                  {proposalMode === "with_proposal" && shownAssessment
                    ? "Resultado com encerramento proposto."
                    : "Resultado sem proposta de encerramento."}
                </Typography>
                <DecisionResults
                  comparison={displayedComparison}
                  active={active}
                  onActive={setActive}
                  onFocus={focusDecision}
                />
              </>
            )}
            {perspective === "access" && shownAssessment && (
              <AccessResults
                assessment={shownAssessment}
                mode={proposalMode}
                onWater={(label) => {
                  selectPerspective("water");
                  setActive(label);
                }}
                onPopulation={(id) => {
                  selectPerspective("population");
                  setSelectedOriginId(id);
                  setSelectedReceptionId("");
                }}
              />
            )}
            {perspective === "population" && shownAssessment && (
              <PopulationResults
                assessment={shownAssessment}
                mode={proposalMode}
                originId={selectedOriginId}
                receptionId={selectedReceptionId}
                onOrigin={(id) => {
                  setSelectedOriginId(id);
                  setSelectedReceptionId("");
                }}
                onReception={setSelectedReceptionId}
                onFocus={focusDecision}
              />
            )}
            {!comparison && (
              <Card density="compact" shadow="none" className="decision-prompt">
                <span>01 / 02</span>
                <Typography as="h2" variant="h3">
                  O que muda quando o incêndio avança?
                </Typography>
                <Typography as="p" variant="body">
                  Escolha duas fontes e compare a viagem completa, incluindo
                  enchimento e regresso ao setor.
                </Typography>
              </Card>
            )}
            {comparison && !shownAssessment && perspective !== "water" && (
              <Card density="compact" shadow="none" className="decision-prompt">
                <Typography as="h2" variant="h3">
                  Uma situação partilhada
                </Typography>
                <Typography as="p" variant="body">
                  Selecione um troço ou avalie os pontos de apoio para ver
                  consequências calculadas sob o mesmo incêndio.
                </Typography>
              </Card>
            )}
            {comparison && (
              <details className="decision-provenance">
                <summary>Origem e pressupostos</summary>
                <Typography as="p" variant="body">
                  Motor: {comparison.engine}
                </Typography>
                <Typography as="p" variant="body">
                  Pacote de estradas:{" "}
                  {comparison.road_package_id || "preparado"} · revisão{" "}
                  {comparison.road_revision}
                </Typography>
                <Typography as="p" variant="body">
                  Resultado guardado:{" "}
                  {new Date(comparison.created_at).toLocaleString("pt-PT")}
                </Typography>
                <Typography as="p" variant="body">
                  As posições e margens são simuladas. Uma proposta não altera
                  registos operacionais.
                </Typography>
              </details>
            )}
          </Card>
        </Box>
      )}
    </main>
  );
}

function localDateTime(iso: string) {
  const value = new Date(iso);
  return new Date(value.getTime() - value.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}
function message(reason: unknown) {
  return reason instanceof Error
    ? reason.message
    : "Não foi possível concluir a operação.";
}
function verificationLabel(value?: string) {
  return (
    (
      {
        verified: "verificada",
        reported: "reportada",
        unverified: "não verificada",
      } as Record<string, string>
    )[value || ""] || "não verificada"
  );
}
function sourceLabel(value?: string) {
  return (
    (
      {
        demo: "exercício",
        openstreetmap: "OpenStreetMap",
        icnf: "ICNF",
        manual: "manual",
      } as Record<string, string>
    )[value || ""] || "origem não indicada"
  );
}
