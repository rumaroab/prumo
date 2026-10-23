import { PrumoBrand } from "./PrumoBrand";
import { confirmDiscard, navigateTo, parseRoute, rememberRun, updatePageQuery, useAppLocation, useNavigationGuard, workspaceHref } from "../navigation";
import { MapResize } from "./MapResize";
import { ResourceInventoryGroups, unitCategory, vehicleCategory } from "./ResourceInventoryGroups";
import { RoutePlanner } from "./RoutePlanner";
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
  formatDateTime,
  formatNumber,
  formatTime,
  statusLabel as localizedStatus,
  t as uiText,
} from "../locale";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { geoJSON } from "leaflet";
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Polyline,
  Popup,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import { api } from "../api";
import type {
  DemoCommunication,
  FeatureCollection,
  MobilitySnapshot,
  Movement,
  MovementStatus,
  OperationalUnit,
  RoadReport,
  RouteAssessment,
  RoutePlan,
  Run,
  ScenarioWorkspace,
  SessionUser,
  VehicleProfile,
} from "../types";

type Language = "pt" | "en";
type Tab = "map" | "movements" | "updates" | "sources";
const statusOrder: MovementStatus[] = [
  "assigned",
  "accepted",
  "travelling",
  "arrived",
  "cannot_proceed",
  "completed",
  "cancelled",
];
const activeStatuses: MovementStatus[] = [
  "assigned",
  "accepted",
  "travelling",
  "arrived",
  "cannot_proceed",
];

const copy = {
  pt: {
    map: "Incêndio",
    movements: "Percursos",
    updates: "Atualizações",
    sources: "Fontes e unidades",
    newMovement: "Novo movimento",
    units: "Unidades e viaturas",
    planning: "Ferramentas de planeamento",
    connected: "Ligado",
    offline: "Sem ligação",
    refreshed: "Atualizado",
    purpose: "Objetivo",
    destination: "Destino",
    chooseUnit: "Unidade e viatura",
    review: "Rever e atribuir",
    preview: "Calcular percurso",
    assign: "Atribuir movimento",
    noConflict: "Sem conflito registado",
    attention: "Precisa de revisão",
    share: "Partilhar briefing",
  },
  en: {
    map: "Map",
    movements: "Journeys",
    updates: "Updates",
    sources: "Sources & Units",
    newMovement: "New movement",
    units: "Units and vehicles",
    planning: "Planning tools",
    connected: "Connected",
    offline: "Offline",
    refreshed: "Updated",
    purpose: "Purpose",
    destination: "Destination",
    chooseUnit: "Unit and vehicle",
    review: "Review and assign",
    preview: "Calculate route",
    assign: "Assign movement",
    noConflict: "No recorded conflict",
    attention: "Needs review",
    share: "Share brief",
  },
};

export function MobilityApp({
  scenarioId,
  currentUser,
}: {
  scenarioId: string;
  currentUser: SessionUser;
}) {
  const [workspace, setWorkspace] =
    useState<Pick<ScenarioWorkspace, "id" | "name" | "simulation">>();
  const [snapshot, setSnapshot] = useState<MobilitySnapshot>();
  const [roads, setRoads] = useState<FeatureCollection>();
  const [fireRuns, setFireRuns] = useState<Run[]>([]);
  const [fireRunId, setFireRunId] = useState("");
  const [fireMinute, setFireMinute] = useState(0);
  const [fireLayer, setFireLayer] = useState<FeatureCollection>();
  const [fireLayerKey, setFireLayerKey] = useState("");
  const [fireRunsLoading, setFireRunsLoading] = useState(true);
  const [fireRunsError, setFireRunsError] = useState("");
  const [fireLayerError, setFireLayerError] = useState("");
  const fireSelectionTouched = useRef(false);
  const appLocation = useAppLocation();
  const navigationRoute = parseRoute(appLocation);
  const tab: Tab = navigationRoute.tab === "units" ? "sources" : (navigationRoute.tab as Tab) || "map";
  const setTab = (next: Tab) => { void navigateTo(workspaceHref(scenarioId, `/mobility${next === "map" ? "" : `/${next}`}`)); };
  const language: Language = "pt";
  const [selectedMovement, setSelectedMovement] = useState<Movement>();
  const [selectedRoad, setSelectedRoad] = useState<GeoJSON.Feature>();
  const [planning, setPlanning] = useState(false);
  const [routePlans, setRoutePlans] = useState<RoutePlan[]>([]);
  const [selectedPlan, setSelectedPlan] = useState<RoutePlan>();
  const [planOrigin, setPlanOrigin] = useState<[number, number]>();
  const [planDestination, setPlanDestination] = useState<[number, number]>();
  const [planPickTarget, setPlanPickTarget] = useState<"origin" | "destination" | null>(null);
  const [planRoute, setPlanRoute] = useState<RouteAssessment>();
  const inventory = navigationRoute.tab === "units";
  const inventoryReturn = useRef(workspaceHref(scenarioId, "/mobility/sources"));
  const previousLocation = useRef(appLocation);
  useEffect(() => {
    if (inventory && parseRoute(previousLocation.current).tab !== "units") inventoryReturn.current = previousLocation.current;
    previousLocation.current = appLocation;
  }, [appLocation, inventory]);
  const setInventory = (value: boolean) => { void navigateTo(value ? workspaceHref(scenarioId, "/mobility/units") : inventoryReturn.current); };
  const [online, setOnline] = useState(navigator.onLine);
  const [lastRefresh, setLastRefresh] = useState<Date>();
  const [error, setError] = useState("");
  const t = copy[language];

  const readCachedSnapshot = () => {
    try {
      const text = localStorage.getItem(`mobility:${scenarioId}`);
      if (!text) return;
      const cached = JSON.parse(text) as MobilitySnapshot;
      if (cached.scenario.id === scenarioId && cached.user.id === currentUser.id && cached.user.role === currentUser.role) return {
        ...cached, water_sources: cached.water_sources || [], water_reports: cached.water_reports || [], incident_points: cached.incident_points || [],
      };
    } catch { /* An invalid cache must not prevent online recovery. */ }
  };

  const cacheSnapshot = (value: MobilitySnapshot) => {
    try { localStorage.setItem(`mobility:${scenarioId}`, JSON.stringify(value)); }
    catch { /* A full browser cache must not hide freshly loaded server data. */ }
  };

  const refresh = useCallback(
    async (quiet = false) => {
      try {
        const [data, plans] = await Promise.all([
          api.mobility(scenarioId),
          currentUser.role === "crew" ? Promise.resolve([]) : api.routePlans(scenarioId),
        ]);
        setSnapshot(data);
        setRoutePlans(plans);
        setLastRefresh(new Date());
        setOnline(true);
        setSelectedMovement((current) =>
          current
            ? data.movements.find((item) => item.id === current.id)
            : current,
        );
        cacheSnapshot(data);
        if (!quiet) setError("");
      } catch (reason) {
        setOnline(false);
        if (!snapshot) {
          const previous = readCachedSnapshot();
          if (previous) { setSnapshot(previous); setWorkspace(previous.scenario); setLastRefresh(new Date(previous.server_time)); }
        }
        if (!quiet) setError(message(reason));
      }
    },
    [scenarioId, currentUser.role],
  );

  useEffect(() => {
    Promise.all([
      currentUser.role === "crew"
        ? Promise.resolve(undefined)
        : api.scenario(scenarioId),
      api.mobilityRoads(scenarioId),
      api.mobility(scenarioId),
      currentUser.role === "crew" ? Promise.resolve([]) : api.routePlans(scenarioId),
    ])
      .then(([scenario, roadData, mobility, plans]) => {
        setWorkspace(scenario || mobility.scenario);
        setRoads(roadData);
        setSnapshot(mobility);
        cacheSnapshot(mobility);
        setRoutePlans(plans);
        setLastRefresh(new Date());
      })
      .catch((reason) => {
        const cached = readCachedSnapshot();
        if (cached) { setWorkspace(cached.scenario); setSnapshot(cached); setLastRefresh(new Date(cached.server_time)); }
        setOnline(false);
        setError(message(reason));
      });
  }, [scenarioId, currentUser.role]);

  useEffect(() => {
    if (currentUser.role === "crew") return;
    let cancelled = false;
    setFireRunsLoading(true);
    void api
      .scenarioRuns(scenarioId)
      .then((values) => {
        if (cancelled) return;
        const ready = values
          .filter((run) => run.status === "ready" && run.mode === "single")
          .sort(
            (left, right) =>
              Date.parse(right.created_at || "") -
              Date.parse(left.created_at || ""),
          );
        setFireRuns(ready);
        setFireRunsError("");
        if (!fireSelectionTouched.current && ready.length) {
          const requestedId = new URLSearchParams(window.location.search).get(
            "run",
          );
          const selected = requestedId ? ready.find((run) => run.id === requestedId) : ready[0];
          if (selected) { setFireRunId(selected.id); setFireMinute(selected.scenario.duration_min); }
          else setFireRunsError("A simulação pedida está indisponível ou não pode ser usada nesta área.");
        }
      })
      .catch((reason) => {
        if (!cancelled) setFireRunsError(message(reason));
      })
      .finally(() => {
        if (!cancelled) setFireRunsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [scenarioId, currentUser.role]);
  useEffect(() => { if (fireRunId) rememberRun(scenarioId, fireRunId); }, [scenarioId, fireRunId]);
  useEffect(() => {
    const requested = navigationRoute.runId;
    if (requested && fireRuns.length && requested !== fireRunId) {
      const run = fireRuns.find((value) => value.id === requested);
      if (run) { setFireRunId(run.id); setFireMinute(run.scenario.duration_min); }
      else setFireRunsError("A simulação pedida está indisponível ou não pode ser usada nesta área.");
    }
  }, [navigationRoute.runId, fireRuns]);
  useEffect(() => {
    if (!fireRunId) {
      setFireLayer(undefined);
      setFireLayerKey("");
      setFireLayerError("");
      return;
    }
    const controller = new AbortController();
    setFireLayer(undefined);
    setFireLayerKey("");
    setFireLayerError("");
    void api
      .fire(fireRunId, fireMinute, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setFireLayer(value);
          setFireLayerKey(`${fireRunId}/${fireMinute}`);
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setFireLayerError(message(reason));
      });
    return () => controller.abort();
  }, [fireRunId, fireMinute]);

  function selectFireRun(id: string) {
    updatePageQuery("run", id || undefined);
    rememberRun(scenarioId, id || undefined);
    fireSelectionTouched.current = true;
    setFireRunId(id);
    const run = fireRuns.find((item) => item.id === id);
    setFireMinute(run ? run.scenario.duration_min : 0);
  }

  function startPlan(plan?: RoutePlan) {
    setSelectedPlan(plan);
    setPlanOrigin(plan?.origin.coordinates);
    setPlanDestination(plan?.destination.coordinates);
    setPlanRoute(plan?.route);
    setPlanPickTarget(null);
    setSelectedMovement(undefined);
    setSelectedRoad(undefined);
    setPlanning(true);
    setTab("map");
  }

  const demoActive = Boolean(
    snapshot?.demo &&
      ["ready", "running", "paused", "error"].includes(snapshot.demo.state),
  );
  useEffect(() => {
    const timer = window.setInterval(
      () => void refresh(true),
      demoActive ? 2_000 : 10_000,
    );
    const onOnline = () => void refresh();
    const onOffline = () => setOnline(false);
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh(true);
    };
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [demoActive, refresh]);

  if (!workspace || !snapshot)
    return (
      <main className="mobility-loading">
        {error || "A carregar mobilidade…"}
      </main>
    );
  const crewMovement =
    currentUser.role === "crew"
      ? snapshot.movements.find((item) =>
          activeStatuses.includes(item.status),
        ) || snapshot.movements[0]
      : undefined;
  if (currentUser.role === "crew")
    return (
      <CrewView
        scenario={workspace}
        snapshot={snapshot}
        movement={crewMovement}
        language={language}
        onRefresh={() => refresh()}
      />
    );

  const reports = snapshot.road_reports.filter(
    (report) => report.status !== "dismissed",
  );
  const selectedFireRun = fireRuns.find((run) => run.id === fireRunId);
  const visibleFireLayer =
    fireLayerKey === `${fireRunId}/${fireMinute}` ? fireLayer : undefined;
  const confirmedSegments = new Set(
    reports
      .filter(
        (report) =>
          report.status === "confirmed" &&
          (report.kind === "blocked" || report.kind === "restricted"),
      )
      .map((report) => report.segment_id),
  );
  const pendingSegments = new Set(
    reports
      .filter(
        (report) =>
          report.status === "pending" &&
          (report.kind === "blocked" || report.kind === "restricted"),
      )
      .map((report) => report.segment_id),
  );
  return (
    <main className="mobility-shell">
      <div className="workspace-context">
        <Typography as="h1" variant="h3">{navigationRoute.title}</Typography>
        <span role="status" className={online ? "connection good" : "connection bad"}>● {online ? t.connected : t.offline}</span>
        <span>{t.refreshed} {formatTime(lastRefresh)}</span>
        {(reports.some((report) => report.status === "pending") || snapshot.water_reports.some((report) => report.status === "pending")) && <a href={workspaceHref(scenarioId, "/mobility/updates")}>Atualizações por rever: {reports.filter((report) => report.status === "pending").length + snapshot.water_reports.filter((report) => report.status === "pending").length}</a>}
        <a href={workspaceHref(scenarioId, "/simulation")}>Análise do resultado</a>
      </div>
      {snapshot.demo && <DemoBanner demo={snapshot.demo} language={language} />}
      {error && (
        <Box role="alert" className="mobility-error">
          {error}
          <Button variant="secondary" onClick={() => void refresh()}>
            Tentar novamente
          </Button>
        </Box>
      )}
      {tab === "map" && (
        <section className="mobility-map-layout">
          <Box className="mobility-map">
            <Card density="compact" shadow="none" className="fire-advisory">
              <label>
                {uiText("Modeled fire overlay")}{" "}
                <select
                  value={fireRunId}
                  onChange={(event) => selectFireRun(event.target.value)}
                >
                  <option value="">{uiText("Off")}</option>
                  {fireRuns.map((run) => (
                    <option key={run.id} value={run.id}>
                      {run.name} · {run.scenario.engine}
                    </option>
                  ))}
                </select>
              </label>
              {selectedFireRun && (
                <>
                  <label>
                    {uiText("Minute")}{" "}
                    <input
                      type="number"
                      min={0}
                      max={selectedFireRun.scenario.duration_min}
                      value={fireMinute}
                      onChange={(event) =>
                        setFireMinute(
                          Math.max(
                            0,
                            Math.min(
                              selectedFireRun.scenario.duration_min,
                              Number(event.target.value) || 0,
                            ),
                          ),
                        )
                      }
                    />
                  </label>
                  <strong>
                    {uiText("Modeled ·")} {selectedFireRun.scenario.engine} ·{" "}
                    {formatDateTime(selectedFireRun.created_at)}{" "}
                    {uiText("· minute")} {fireMinute}
                  </strong>
                  <Typography as="small" variant="small">
                    Área laranja: propagação modelada.{" "}
                    {uiText(
                      "Advisory only. Road status and route eligibility use confirmed and matched road reports.",
                    )}
                  </Typography>
                </>
              )}
              {selectedFireRun &&
                visibleFireLayer &&
                visibleFireLayer.features.length === 0 && (
                  <Typography as="small" variant="small">
                    O modelo não apresenta área ardida neste minuto; consulte os
                    pontos de ignição registados.
                  </Typography>
                )}
              {!selectedFireRun &&
                !fireRunsLoading &&
                !fireRunsError &&
                !fireRuns.length && (
                  <Typography as="small" variant="small">
                    Sem simulação concluída. Os pontos vermelhos assinalam
                    apenas as ignições registadas.
                  </Typography>
                )}
              {fireLayerError && (
                <Typography as="small" variant="small" role="alert">
                  Não foi possível mostrar o incêndio modelado: {fireLayerError}
                </Typography>
              )}
            </Card>
            <MapContainer
              bounds={[
                [
                  workspace.simulation.ignitions[0].coordinates[1] - 0.08,
                  workspace.simulation.ignitions[0].coordinates[0] - 0.08,
                ],
                [
                  workspace.simulation.ignitions[0].coordinates[1] + 0.08,
                  workspace.simulation.ignitions[0].coordinates[0] + 0.08,
                ],
              ]}
              zoomControl
            >
              <MapResize />
              <TileLayer
                attribution="&copy; OpenStreetMap contributors"
                url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <FitFireBounds fire={visibleFireLayer} runId={fireRunId} />
              {roads && (
                <GeoJSON
                  key={`${planning}:${reports
                    .map((report) => `${report.id}:${report.revision}`)
                    .join("|")}`}
                  data={roads}
                  style={(feature) => {
                    const segment = String(feature?.properties?.segment_id);
                    return {
                      color: confirmedSegments.has(segment)
                        ? "#db4d3f"
                        : pendingSegments.has(segment)
                          ? "#e5a43e"
                          : "#657b86",
                      weight:
                        confirmedSegments.has(segment) ||
                        pendingSegments.has(segment)
                          ? 5
                          : 2,
                      opacity: 0.8,
                    };
                  }}
                  onEachFeature={(feature, layer) =>
                    layer.on({ click: () => { if (!planning) setSelectedRoad(feature); } })
                  }
                />
              )}
              {visibleFireLayer && (
                <GeoJSON
                  key={`${fireRunId}-${fireMinute}`}
                  data={visibleFireLayer}
                  interactive={false}
                  style={{
                    color: "#ed7438",
                    fillColor: "#ed7438",
                    fillOpacity: 0.27,
                    weight: 1,
                  }}
                />
              )}
              {workspace.simulation.ignitions.map((ignition) => (
                <CircleMarker
                  key={ignition.id}
                  center={[ignition.coordinates[1], ignition.coordinates[0]]}
                  radius={7}
                  pathOptions={{
                    color: "#ff684f",
                    fillColor: "#ff684f",
                    fillOpacity: 1,
                    weight: 2,
                  }}
                >
                  <Popup>
                    <strong>{ignition.name}</strong>
                    <br />
                    Ponto de ignição registado · minuto {ignition.start_min}
                  </Popup>
                </CircleMarker>
              ))}
              {[...snapshot.water_sources, ...snapshot.incident_points].map(
                (point) => (
                  <CircleMarker
                    key={point.id}
                    center={[point.coordinates[1], point.coordinates[0]]}
                    radius={6}
                    pathOptions={{
                      color:
                        point.kind === "water_point" ? "#49a9dc" : "#f1cd70",
                      fillOpacity: 0.85,
                    }}
                  >
                    <Popup>
                      <strong>{point.name}</strong>
                      <br />
                      {point.kind === "water_point"
                        ? `${localizedStatus(point.water?.availability || "unknown")} · ${point.water?.access_notes || "Sem notas de acesso"}`
                        : point.description || point.notes}
                    </Popup>
                  </CircleMarker>
                ),
              )}
              {snapshot.units.map(
                (unit) =>
                  unit.latest_location && (
                    <CircleMarker
                      key={unit.id}
                      center={[
                        unit.latest_location.coordinates[1],
                        unit.latest_location.coordinates[0],
                      ]}
                      radius={9}
                      pathOptions={{
                        color:
                          unit.status === "available" ? "#3fb38b" : "#ffb547",
                        fillOpacity: 1,
                      }}
                    >
                      <Popup>
                        <strong>{unit.callsign}</strong>
                        <br />
                        {unit.organisation}
                        <br />
                        {ageLabel(unit.latest_location.observed_at, language)}
                      </Popup>
                    </CircleMarker>
                  ),
              )}
              {selectedMovement?.route.selected?.feature && (
                <GeoJSON
                  data={selectedMovement.route.selected.feature}
                  style={{ color: "#21a6d8", weight: 6, opacity: 0.95 }}
                />
              )}
              {planning && planRoute?.selected?.feature && (
                <GeoJSON data={planRoute.selected.feature} style={{ color: "#21a6d8", weight: 5, opacity: 0.9 }} />
              )}
              {planning && planOrigin && (
                <CircleMarker center={[planOrigin[1], planOrigin[0]]} radius={9}
                  pathOptions={{ color: "#fff", fillColor: "#3fb38b", fillOpacity: 1 }}>
                  <Popup>Origem do plano</Popup>
                </CircleMarker>
              )}
              {planning && planDestination && (
                <CircleMarker center={[planDestination[1], planDestination[0]]} radius={9}
                  pathOptions={{ color: "#fff", fillColor: "#21a6d8", fillOpacity: 1 }}>
                  <Popup>Destino do plano</Popup>
                </CircleMarker>
              )}
              {planning && (
                <PlanPointPicker target={planPickTarget} onPick={(target, coordinates) => {
                  if (target === "origin") setPlanOrigin(coordinates);
                  else setPlanDestination(coordinates);
                  setPlanPickTarget(null);
                }} />
              )}
            </MapContainer>
            {!demoActive && (
              <Box className="map-actions">
                <Button
                  variant="primary"
                  onClick={() => startPlan()}
                >
                  Planear percurso
                </Button>
                <Button variant="secondary" onClick={() => setInventory(true)}>
                  {t.units}
                </Button>
              </Box>
            )}
            <Card
              density="compact"
              shadow="none"
              className="mobility-road-legend"
            >
              {uiText(
                "Roads: red confirmed restriction · amber matched report awaiting review",
              )}
            </Card>
          </Box>
          <aside className="mobility-context">
            {selectedRoad ? (
              <RoadReportPanel
                scenarioId={scenarioId}
                road={selectedRoad}
                reports={reports}
                language={language}
                readOnly={demoActive}
                onClose={() => setSelectedRoad(undefined)}
                onSaved={() => refresh()}
              />
            ) : planning ? (
              <RoutePlanner
                key={selectedPlan?.id || "new"}
                scenarioId={scenarioId}
                snapshot={snapshot}
                plan={selectedPlan}
                origin={planOrigin}
                destination={planDestination}
                activeTarget={planPickTarget}
                onOriginChange={setPlanOrigin}
                onDestinationChange={setPlanDestination}
                onPickTarget={setPlanPickTarget}
                onRouteChange={setPlanRoute}
                onManageUnits={() => setInventory(true)}
                onClose={() => { setPlanning(false); setPlanPickTarget(null); }}
                onSaved={(saved) => {
                  setRoutePlans((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
                  setPlanning(false);
                  setTab("movements");
                  void refresh();
                }}
                onDeleted={() => {
                  setPlanning(false);
                  setTab("movements");
                  void refresh();
                }}
                onAssigned={(movement) => {
                  setSelectedMovement(movement);
                  setPlanning(false);
                  setPlanPickTarget(null);
                  void refresh();
                }}
                readOnly={demoActive}
              />
            ) : selectedMovement ? (
              <MovementDetail
                scenarioId={scenarioId}
                movement={selectedMovement}
                snapshot={snapshot}
                language={language}
                readOnly={demoActive}
                onClose={() => setSelectedMovement(undefined)}
                onChanged={() => refresh()}
              />
            ) : (
              <>
                <FireStart
                  scenarioId={scenarioId}
                  run={selectedFireRun}
                  latestRun={fireRuns[0]}
                  loading={fireRunsLoading}
                  error={fireRunsError}
                  layerError={fireLayerError}
                  onShowLatest={() => selectFireRun(fireRuns[0].id)}
                  onUpdates={() => setTab("updates")}
                  onSources={() => setTab("sources")}
                  onJourney={() => startPlan()}
                />
                <MapSummary
                  snapshot={snapshot}
                  language={language}
                  onMovement={setSelectedMovement}
                />
              </>
            )}
          </aside>
        </section>
      )}
      {tab === "movements" && (
        <MovementBoard
          snapshot={snapshot}
          plans={routePlans}
          language={language}
          onPlanSelect={startPlan}
          onSelect={(movement) => {
            setSelectedMovement(movement);
            setTab("map");
          }}
        />
      )}
      {tab === "updates" && (
        <Updates
          scenarioId={scenarioId}
          snapshot={snapshot}
          roads={roads}
          language={language}
          readOnly={demoActive}
          onChanged={() => refresh()}
          onOpen={(item) => {
            if (item.linked_type === "movement")
              setSelectedMovement(
                snapshot.movements.find((value) => value.id === item.linked_id),
              );
            if (item.linked_type === "road_report") {
              const report = snapshot.road_reports.find(
                (value) => value.id === item.linked_id,
              );
              const road = roads?.features.find(
                (value) => value.properties?.segment_id === report?.segment_id,
              );
              if (road) setSelectedRoad(road);
            }
            setTab("map");
          }}
        />
      )}
      {tab === "sources" && (
        <SourcesUnits
          scenarioId={scenarioId}
          snapshot={snapshot}
          language={language}
          onChanged={() => refresh()}
          onManageUnits={() => setInventory(true)}
        />
      )}
      {inventory && (
        <InventoryDrawer
          scenarioId={scenarioId}
          snapshot={snapshot}
          language={language}
          onClose={() => setInventory(false)}
          onChanged={() => refresh()}
        />
      )}
    </main>
  );
}

function DemoBanner({
  demo,
  language,
}: {
  demo: NonNullable<MobilitySnapshot["demo"]>;
  language: Language;
}) {
  const elapsed = Math.min(demo.elapsed_seconds, demo.duration_seconds);
  const state = {
    ready: tr(language, "pronta", "ready"),
    running: tr(language, "em curso", "running"),
    paused: tr(language, "em pausa", "paused"),
    completed: tr(language, "concluída", "completed"),
    error: tr(language, "interrompida", "stopped"),
    archived: tr(language, "arquivada", "archived"),
  }[demo.state];
  return (
    <Box className={`demo-banner ${demo.state}${demo.error ? " error" : ""}`}>
      <strong>
        {tr(
          language,
          "Demonstração — dados fictícios",
          "Demonstration — fictional data",
        )}
      </strong>
      <span>
        {state} · {demo.stage}
      </span>
      <time>
        {formatClock(elapsed)} / {formatClock(demo.duration_seconds)} ·{" "}
        {demo.speed}×
      </time>
      {demo.error && (
        <Typography as="small" variant="small">
          {demo.error}
        </Typography>
      )}
    </Box>
  );
}

function RoadReportPanel({
  scenarioId,
  road,
  reports,
  language,
  readOnly,
  onClose,
  onSaved,
}: {
  scenarioId: string;
  road: GeoJSON.Feature;
  reports: RoadReport[];
  language: Language;
  readOnly?: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const properties = road.properties || {};
  const segmentId = String(properties.segment_id || "");
  const [kind, setKind] = useState<RoadReport["kind"]>("blocked");
  const [reason, setReason] = useState("");
  const [direction, setDirection] = useState<RoadReport["direction"]>("both");
  const [error, setError] = useState("");
  const [vehicleClasses, setVehicleClasses] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const currentInputs = JSON.stringify([kind, reason, direction, vehicleClasses]);
  const savedInputs = useRef(currentInputs);
  const reportDirty = currentInputs !== savedInputs.current;
  useNavigationGuard((to) => {
    if (to.kind === "mobility" && to.scenarioId === scenarioId && to.tab === "map") return true;
    if (saving) { setError("Aguarde a conclusão da gravação."); return false; }
    return !reportDirty || confirmDiscard();
  }, reportDirty);
  const existing = reports.filter((report) => report.segment_id === segmentId);
  async function save() {
    if (saving) return;
    setSaving(true);
    try {
      await api.addRoadReport(scenarioId, {
        id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
        segment_id: segmentId || null,
        road_name: String(properties.name || "Estrada sem nome"),
        kind,
        reason,
        direction,
        affected_vehicle_classes: vehicleClasses,
        status: "pending",
        source: "dispatcher",
        geometry: road.geometry,
        observed_at: new Date().toISOString(),
        revision: 1,
      });
      savedInputs.current = currentInputs;
      setError("");
      onSaved();
    } catch (e) {
      setError(message(e));
    } finally { setSaving(false); }
  }
  async function closeRestriction(report: RoadReport) {
    try {
      await api.reviewRoadReport(scenarioId, report, "dismissed");
      onSaved();
    } catch (e) {
      setError(message(e));
    }
  }
  if (readOnly)
    return (
      <Card density="compact" shadow="none" className="mobility-panel">
        <Button
          variant="ghost"
          aria-label="Fechar painel"
          className="panel-close"
          onClick={() => { if (!saving && (!reportDirty || confirmDiscard())) onClose(); }}
        >
          ×
        </Button>
        <Typography as="span" variant="label" className="eyebrow">
          {tr(language, "Troço da demonstração", "Demonstration road section")}
        </Typography>
        <Typography as="h2" variant="h3">
          {String(
            properties.name || tr(language, "Estrada sem nome", "Unnamed road"),
          )}
        </Typography>
        {existing.length ? (
          existing.map((item) => (
            <Card
              density="compact"
              shadow="none"
              className={`report-chip ${item.status}`}
              key={item.id}
            >
              {reportLabel(item.kind, language)} · {item.status}
            </Card>
          ))
        ) : (
          <Typography as="p" variant="body">
            {tr(
              language,
              "Sem restrição registada neste troço.",
              "No restriction recorded on this section.",
            )}
          </Typography>
        )}
        <Typography as="p" variant="body">
          {tr(
            language,
            "A sequência é controlada pelo simulador.",
            "The sequence is controlled by the demo runner.",
          )}
        </Typography>
      </Card>
    );
  return (
    <Card density="compact" shadow="none" className="mobility-panel">
      <Button
        variant="ghost"
        aria-label="Fechar painel"
        className="panel-close"
        onClick={() => { if (!saving && (!reportDirty || confirmDiscard())) onClose(); }}
      >
        ×
      </Button>
      <Typography as="span" variant="label" className="eyebrow">
        {tr(language, "Condição da estrada", "Road condition")}
      </Typography>
      <Typography as="h2" variant="h3">
        {String(
          properties.name || tr(language, "Estrada sem nome", "Unnamed road"),
        )}
      </Typography>
      {existing.map((item) => (
        <Card
          density="compact"
          shadow="none"
          className={`report-chip ${item.status}`}
          key={item.id}
        >
          {reportLabel(item.kind, language)} · {localizedStatus(item.status)}
          {item.status === "confirmed" &&
          ["blocked", "restricted"].includes(item.kind) ? (
            <Button
              variant="secondary"
              onClick={() => void closeRestriction(item)}
            >
              {tr(language, "Encerrar restrição", "Close restriction")}
            </Button>
          ) : null}
        </Card>
      ))}
      <label>
        {tr(language, "Estado", "Condition")}
        <select
          value={kind}
          onChange={(event) =>
            setKind(event.target.value as RoadReport["kind"])
          }
        >
          <option value="blocked">
            {tr(language, "Bloqueada", "Blocked")}
          </option>
          <option value="restricted">
            {tr(language, "Condicionada", "Restricted")}
          </option>
          <option value="reopening">
            {tr(language, "Reabertura reportada", "Reopening reported")}
          </option>
          <option value="uncertain">
            {tr(language, "Informação incerta", "Uncertain information")}
          </option>
        </select>
      </label>
      <label>
        {tr(language, "Direção", "Direction")}
        <select
          value={direction}
          onChange={(event) =>
            setDirection(event.target.value as RoadReport["direction"])
          }
        >
          <option value="both">{tr(language, "Ambas", "Both")}</option>
          <option value="forward">
            {tr(language, "Sentido do troço", "Section direction")}
          </option>
          <option value="reverse">
            {tr(language, "Sentido inverso", "Opposite direction")}
          </option>
        </select>
      </label>
      <fieldset>
        <legend>
          {tr(
            language,
            "Viaturas afetadas · vazio significa todas",
            "Affected vehicles · empty means all",
          )}
        </legend>
        <Box className="vehicle-class-grid">
          {[
            ["light", tr(language, "Ligeiro", "Light")],
            ["heavy", tr(language, "Pesado", "Heavy")],
            ["tanker", tr(language, "Autotanque", "Tanker")],
            ["bus", tr(language, "Autocarro", "Bus")],
            ["ambulance", tr(language, "Ambulância", "Ambulance")],
          ].map(([value, label]) => (
            <label className="ack" key={value}>
              <input
                type="checkbox"
                checked={vehicleClasses.includes(value)}
                onChange={(event) =>
                  setVehicleClasses((current) =>
                    event.target.checked
                      ? [...current, value]
                      : current.filter((item) => item !== value),
                  )
                }
              />
              {label}
            </label>
          ))}
        </Box>
      </fieldset>
      <label>
        {tr(language, "Motivo", "Reason")}
        <textarea
          rows={3}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder={tr(
            language,
            "Árvore caída, fumo intenso…",
            "Fallen tree, heavy smoke…",
          )}
        />
      </label>
      <Button variant="primary" className="full" disabled={saving} onClick={() => void save()}>
        {tr(language, "Registar informação", "Record report")}
      </Button>
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
    </Card>
  );
}

function MovementDetail({
  scenarioId,
  movement,
  snapshot,
  language,
  readOnly,
  onClose,
  onChanged,
}: {
  scenarioId: string;
  movement: Movement;
  snapshot: MobilitySnapshot;
  language: Language;
  readOnly?: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const unit = snapshot.units.find((item) => item.id === movement.unit_id);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function action(value: string) {
    try {
      await api.movementAction(scenarioId, movement, value, "radio");
      onChanged();
    } catch (e) {
      setError(message(e));
    }
  }
  async function share() {
    try {
      const value = await api.shareMovement(scenarioId, movement.id);
      await navigator.clipboard.writeText(
        new URL(value.url, window.location.origin).toString(),
      );
    } catch (e) {
      setError(message(e));
    }
  }
  async function replan() {
    if (!unit) return;
    setBusy(true);
    setError("");
    try {
      const route = await api.mobilityRoute(scenarioId, {
        origin: movement.origin,
        destination: movement.destination,
        vehicle_id: movement.vehicle_id,
        departure_at: new Date().toISOString(),
        alternatives: 2,
      });
      if (route.status === "unavailable") throw new Error(route.message);
      const acknowledged =
        route.status === "unknown"
          ? window.confirm(
              "O novo percurso mantém limitações desconhecidas. Confirma os pontos de acesso e pretende publicar uma nova versão?",
            )
          : true;
      if (!acknowledged) return;
      await api.reviseMovementRoute(scenarioId, movement, route, acknowledged);
      onChanged();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  const requiresAck =
    movement.acknowledged_brief_version !== movement.brief_version &&
    movement.status !== "assigned";
  const next = requiresAck
    ? {
        action: "acknowledge_brief",
        label: tr(
          language,
          "Confirmar briefing atualizado",
          "Acknowledge updated brief",
        ),
      }
    : nextAction(movement.status, language);
  return (
    <Card density="compact" shadow="none" className="mobility-panel">
      <Button
        variant="ghost"
        aria-label="Fechar painel"
        className="panel-close"
        onClick={onClose}
      >
        ×
      </Button>
      <Typography as="span" variant="label" className="eyebrow">
        {unit?.callsign} · v{movement.brief_version}
      </Typography>
      <Typography as="h2" variant="h3">
        {movement.destination.name}
      </Typography>
      <Typography as="p" variant="body">
        {movement.purpose}
      </Typography>
      <Box className={`movement-state ${movement.status}`}>
        {statusLabel(movement.status, language)}
      </Box>
      {requiresAck && (
        <Card density="compact" shadow="none" className="brief-ack-pending">
          {tr(
            language,
            `A versão ${movement.brief_version} aguarda confirmação.`,
            `Version ${movement.brief_version} awaits acknowledgment.`,
          )}
        </Card>
      )}
      {movement.needs_review && (
        <Card density="compact" shadow="none" className="route-problem">
          {tr(
            language,
            "A alteração de uma estrada afeta este percurso. Rever antes da partida.",
            "A road change affects this route. Review it before departure.",
          )}
          {!readOnly && (
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => void replan()}
            >
              {busy
                ? tr(language, "A calcular…", "Calculating…")
                : tr(
                    language,
                    "Propor e publicar alternativa",
                    "Propose and publish alternative",
                  )}
            </Button>
          )}
        </Card>
      )}
      <Box className="brief-facts">
        <span>
          {formatNumber(movement.route.selected?.distance_km || 0)} km
        </span>
        <span>
          {Math.round(movement.route.selected?.duration_min || 0)}{" "}
          {tr(language, "min estimados", "estimated min")}
        </span>
        <span>{formatDateTime(movement.departure_at)}</span>
      </Box>
      <ol className="road-list">
        {movement.route.selected?.road_names.map((name) => (
          <li key={name}>{name}</li>
        ))}
      </ol>
      <Box className="movement-actions">
        {next && !readOnly && (
          <Button variant="primary" onClick={() => void action(next.action)}>
            {next.label} {tr(language, "por rádio", "by radio")}
          </Button>
        )}
        <Button
          variant="secondary"
          onClick={() =>
            void navigator.clipboard.writeText(
              `${window.location.origin}/scenarios/${scenarioId}/mobility`,
            )
          }
        >
          {tr(language, "Copiar link da equipa", "Copy crew link")}
        </Button>
        {!readOnly && (
          <Button variant="secondary" onClick={() => void share()}>
            {tr(
              language,
              "Copiar briefing só de leitura",
              "Copy read-only brief",
            )}
          </Button>
        )}
      </Box>
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
    </Card>
  );
}

function MovementBoard({
  snapshot,
  plans,
  language,
  onSelect,
  onPlanSelect,
}: {
  snapshot: MobilitySnapshot;
  plans: RoutePlan[];
  language: Language;
  onSelect: (value: Movement) => void;
  onPlanSelect: (value: RoutePlan) => void;
}) {
  const [organisation, setOrganisation] = useState("all");
  const [attention, setAttention] = useState(false);
  const organisations = [
    ...new Set(snapshot.units.map((unit) => unit.organisation)),
  ];
  const visible = snapshot.movements.filter((movement) => {
    const unit = snapshot.units.find((item) => item.id === movement.unit_id);
    const needsAttention =
      movement.needs_review ||
      (movement.status !== "assigned" &&
        movement.acknowledged_brief_version !== movement.brief_version);
    return (
      (!attention || needsAttention) &&
      (organisation === "all" || unit?.organisation === organisation)
    );
  });
  return (
    <SectionContainer
      as="section"
      containerClassName="ds-stack"
      className="movement-board"
    >
      <Box className="board-toolbar">
        <Typography as="h2" variant="h2">
          {tr(language, "Movimentos", "Movements")}
        </Typography>
        <select
          aria-label="Organização"
          value={organisation}
          onChange={(event) => setOrganisation(event.target.value)}
        >
          <option value="all">
            {tr(language, "Todas as organizações", "All organisations")}
          </option>
          {organisations.map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
        <label className="ack">
          <input
            type="checkbox"
            checked={attention}
            onChange={(event) => setAttention(event.target.checked)}
          />
          {tr(language, "Precisa de atenção", "Needs attention")}
        </label>
      </Box>
      <Card as="section" density="compact" shadow="none" className="route-plan-list">
        <Typography as="h2" variant="h3">Planos <b>{plans.length}</b></Typography>
        {plans.length ? plans.map((plan) => <Button variant="secondary" className="ds-list-action" key={plan.id} onClick={() => onPlanSelect(plan)}>
          <strong>{plan.purpose}</strong>
          <span>{plan.origin.name} → {plan.destination.name}</span>
          <small>{plan.assigned_movement_id ? "Movimento atribuído" : "Sem unidade atribuída"} · {formatTime(plan.updated_at)}</small>
        </Button>) : <Typography as="p" variant="small">Ainda não há planos de percurso guardados.</Typography>}
      </Card>
      <Box className="status-columns">
        {statusOrder.map((status) => {
          const values = visible.filter((item) => item.status === status);
          if (!values.length && ["completed", "cancelled"].includes(status))
            return null;
          return (
            <section key={status}>
              <Typography as="h2" variant="h3">
                {statusLabel(status, language)} <b>{values.length}</b>
              </Typography>
              {values.map((movement) => {
                const unit = snapshot.units.find(
                  (item) => item.id === movement.unit_id,
                );
                return (
                  <Button
                    variant="secondary"
                    key={movement.id}
                    className={movement.needs_review ? "attention" : ""}
                    onClick={() => onSelect(movement)}
                  >
                    <strong>{movement.destination.name}</strong>
                    <span>
                      {unit?.callsign} · {unit?.organisation}
                    </span>
                    <Typography as="small" variant="small">
                      {formatTime(movement.updated_at)}
                    </Typography>
                  </Button>
                );
              })}
            </section>
          );
        })}
      </Box>
    </SectionContainer>
  );
}

function Updates({
  scenarioId,
  snapshot,
  roads,
  language,
  readOnly,
  onChanged,
  onOpen,
}: {
  scenarioId: string;
  snapshot: MobilitySnapshot;
  roads?: FeatureCollection;
  language: Language;
  readOnly?: boolean;
  onChanged: () => void;
  onOpen: (item: DemoCommunication) => void;
}) {
  const pending = snapshot.road_reports.filter(
    (item) => item.status === "pending",
  );
  const [matches, setMatches] = useState<Record<string, string>>({});
  const [directions, setDirections] = useState<
    Record<string, RoadReport["direction"]>
  >({});
  const [roadSearches, setRoadSearches] = useState<Record<string, string>>({});
  const [reviewError, setReviewError] = useState("");
  const reviewDirty = Object.keys(matches).length > 0 || Object.keys(directions).length > 0;
  useNavigationGuard((to) => to.kind === "mobility" && to.scenarioId === scenarioId && to.tab === "updates" || !reviewDirty || confirmDiscard(), reviewDirty);
  const communications = snapshot.communications || [];
  const groups = [
    ...communications
      .reduce((values, item) => {
        const key = `${item.linked_type || "source"}:${item.linked_id || item.callsign}`;
        const current = values.get(key) || [];
        current.push(item);
        values.set(key, current);
        return values;
      }, new Map<string, DemoCommunication[]>())
      .values(),
  ];
  async function review(report: RoadReport, status: "confirmed" | "dismissed") {
    try {
      const segment = matches[report.id] || report.segment_id || undefined;
      await api.reviewRoadReport(
        scenarioId,
        report,
        status,
        segment,
        directions[report.id] || report.direction,
      );
      setMatches((values) => { const next = { ...values }; delete next[report.id]; return next; });
      setDirections((values) => { const next = { ...values }; delete next[report.id]; return next; });
      setReviewError("");
      onChanged();
    } catch (reason) {
      setReviewError(message(reason));
    }
  }
  return (
    <SectionContainer
      as="section"
      containerClassName="ds-stack"
      className="updates-page"
    >
      <header>
        <Typography as="h2" variant="h2">
          {tr(language, "Atualizações", "Updates")}
        </Typography>
        <Typography as="p" variant="body">
          {tr(
            language,
            "Informações por confirmar e alterações recentes. Uma estrada nunca reabre apenas por envelhecimento do reporte.",
            "Reports awaiting review and recent changes. A road never reopens merely because a report is old.",
          )}
        </Typography>
      </header>
      {reviewError && (
        <Typography
          role="alert"
          as="p"
          variant="small"
          className="inline-error"
        >
          {reviewError}
        </Typography>
      )}
      <Box className="updates-grid">
        <Card as="section" density="compact" shadow="none">
          <Typography as="h2" variant="h3">
            {tr(language, "Por confirmar", "Awaiting review")}
          </Typography>
          {pending.length ? (
            pending.map((report) => (
              <Card
                as="article"
                density="compact"
                shadow="none"
                key={report.id}
              >
                <Box>
                  <strong>{report.road_name}</strong>
                  <span>
                    {reportLabel(report.kind, language)} ·{" "}
                    {localizedStatus(report.source)}
                  </span>
                  <Typography as="small" variant="small">
                    {ageLabel(report.observed_at, language)}
                    {Date.now() - new Date(report.observed_at).getTime() >
                    60 * 60_000
                      ? tr(language, " · revalidar", " · revalidate")
                      : ""}
                  </Typography>
                </Box>
                <Typography as="p" variant="body">
                  {report.reason ||
                    tr(
                      language,
                      "Sem observação adicional",
                      "No additional observation",
                    )}
                </Typography>
                {report.observed_location && (
                  <Typography as="small" variant="small">
                    {uiText("Observed at")}{" "}
                    {report.observed_location[1].toFixed(5)},{" "}
                    {report.observed_location[0].toFixed(5)}
                  </Typography>
                )}
                {!report.segment_id && (
                  <strong className="route-problem">
                    {uiText(
                      "Unmatched report · no routing effect until dispatch matches a road",
                    )}
                  </strong>
                )}
                {!readOnly && (
                  <>
                    <label>
                      {uiText("Prepared road")}{" "}
                      <input
                        placeholder={uiText("Search road or segment")}
                        value={roadSearches[report.id] || ""}
                        onChange={(event) =>
                          setRoadSearches((current) => ({
                            ...current,
                            [report.id]: event.target.value,
                          }))
                        }
                      />
                      <select
                        aria-label={uiText("Prepared road")}
                        value={matches[report.id] || report.segment_id || ""}
                        onChange={(event) =>
                          setMatches((current) => ({
                            ...current,
                            [report.id]: event.target.value,
                          }))
                        }
                      >
                        <option value="">{uiText("Choose a segment")}</option>
                        {candidateRoads(
                          roads,
                          report,
                          roadSearches[report.id] || "",
                        ).map((feature) => (
                          <option
                            key={String(feature.properties?.segment_id)}
                            value={String(feature.properties?.segment_id)}
                          >
                            {String(
                              feature.properties?.name ||
                                feature.properties?.segment_id,
                            )}{" "}
                            · {String(feature.properties?.segment_id)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      {uiText("Direction")}{" "}
                      <select
                        value={directions[report.id] || report.direction}
                        onChange={(event) =>
                          setDirections((current) => ({
                            ...current,
                            [report.id]: event.target
                              .value as RoadReport["direction"],
                          }))
                        }
                      >
                        <option value="both">{uiText("Both")}</option>
                        <option value="forward">
                          {uiText("Segment direction")}
                        </option>
                        <option value="reverse">
                          {uiText("Opposite direction")}
                        </option>
                      </select>
                    </label>
                    <footer>
                      <Button
                        variant="primary"
                        disabled={!report.segment_id && !matches[report.id]}
                        onClick={() => void review(report, "confirmed")}
                      >
                        {tr(language, "Confirmar", "Confirm")}
                      </Button>
                      <Button
                        variant="secondary"
                        onClick={() => void review(report, "dismissed")}
                      >
                        {tr(language, "Descartar", "Dismiss")}
                      </Button>
                    </footer>
                  </>
                )}
              </Card>
            ))
          ) : (
            <Typography as="p" variant="small" className="empty-note">
              {tr(
                language,
                "Sem informações pendentes.",
                "No pending reports.",
              )}
            </Typography>
          )}
        </Card>
        <section className="communications-feed">
          <Typography as="h2" variant="h3">
            {communications.length
              ? tr(
                  language,
                  "Comunicações simuladas",
                  "Simulated communications",
                )
              : tr(language, "Atividade recente", "Recent activity")}
          </Typography>
          {communications.length
            ? groups.map((items, index) => (
                <Box
                  className="communication-group"
                  key={`${items[0].linked_id || items[0].callsign}-${index}`}
                >
                  <Typography as="h3" variant="h3">
                    {items[0].callsign} · {items[0].organisation}
                  </Typography>
                  {items.map((item) => (
                    <Card
                      as="article"
                      density="compact"
                      shadow="none"
                      key={item.id}
                    >
                      <Box>
                        <strong>
                          {language === "pt"
                            ? item.message_pt
                            : item.message_en}
                        </strong>
                        <span>
                          <b>{tr(language, "simulada", "simulated")}</b> ·{" "}
                          {localizedStatus(item.source)} ·{" "}
                          {ageLabel(item.received_at, language)}
                        </span>
                      </Box>
                      <footer>
                        <Typography as="small" variant="small">
                          {demoResultLabel(item.result_state, language)}
                        </Typography>
                        {item.linked_type && (
                          <Button
                            variant="secondary"
                            onClick={() => onOpen(item)}
                          >
                            {tr(language, "Abrir registo", "Open record")}
                          </Button>
                        )}
                      </footer>
                    </Card>
                  ))}
                </Box>
              ))
            : snapshot.events.slice(0, 30).map((event) => (
                <Card
                  as="article"
                  density="compact"
                  shadow="none"
                  key={event.id}
                >
                  <strong>{eventLabel(event.kind)}</strong>
                  <span>
                    {localizedStatus(event.source)} ·{" "}
                    {ageLabel(event.created_at, language)}
                  </span>
                </Card>
              ))}
        </section>
      </Box>
    </SectionContainer>
  );
}

function SourcesUnits({
  scenarioId,
  snapshot,
  language,
  onChanged,
  onManageUnits,
}: {
  scenarioId: string;
  snapshot: MobilitySnapshot;
  language: Language;
  onChanged: () => void;
  onManageUnits: () => void;
}) {
  const [error, setError] = useState("");
  async function review(
    id: string,
    status: "confirmed" | "dismissed",
    revision: number,
  ) {
    try {
      await api.reviewWaterReport(scenarioId, id, status, revision);
      setError("");
      onChanged();
    } catch (reason) {
      setError(message(reason));
    }
  }
  return (
    <SectionContainer
      as="section"
      containerClassName="ds-stack"
      className="updates-page"
    >
      <header>
        <Typography as="h2" variant="h2">
          {tr(language, "Fontes e unidades", "Sources & Units")}
        </Typography>
        <Typography as="p" variant="body">
          {tr(
            language,
            "Estado registado e verificação humana. Sem previsões de fila ou abastecimento.",
            "Recorded status and human verification. No queue or delivery predictions.",
          )}
        </Typography>
      </header>
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
      <Box className="updates-grid">
        <Card as="section" density="compact" shadow="none">
          <Typography as="h2" variant="h3">
            {tr(language, "Fontes de água", "Water sources")}
          </Typography>
          {snapshot.water_sources.map((source) => {
            const pending = snapshot.water_reports.filter(
              (report) =>
                report.point_id === source.id && report.status === "pending",
            );
            return (
              <Card
                as="article"
                density="compact"
                shadow="none"
                key={source.id}
              >
                <strong>{source.name}</strong>
                <Typography as="p" variant="body">
                  {localizedStatus(source.water?.availability || "unknown")} ·{" "}
                  {localizedStatus(
                    source.water?.verification_status || "unverified",
                  )}
                </Typography>
                <Typography as="small" variant="small">
                  {source.verified_at
                    ? `${tr(language, "Verificado", "Verified")} ${formatDateTime(source.verified_at)} · ${source.verified_by}`
                    : tr(
                        language,
                        "Sem verificação recente",
                        "No recent verification",
                      )}
                  {source.water?.observed_at
                    ? ` · observado em ${formatDateTime(source.water.observed_at)}`
                    : ""}
                </Typography>
                <Typography as="p" variant="body">
                  {source.water?.access_notes ||
                    tr(language, "Sem notas de acesso", "No access notes")}
                </Typography>
                {pending.map((report) => (
                  <Box key={report.id} className="archive-record">
                    <strong>
                      {localizedStatus(report.availability)} ·{" "}
                      {tr(language, "por confirmar", "pending")}
                    </strong>
                    <Typography as="p" variant="body">
                      {report.note}
                    </Typography>
                    <Typography as="small" variant="small">
                      {formatDateTime(report.observed_at)} ·{" "}
                      {localizedStatus(report.source)}
                    </Typography>
                    <footer>
                      <Button
                        variant="secondary"
                        onClick={() =>
                          void review(report.id, "confirmed", report.revision)
                        }
                      >
                        {uiText("Confirm")}
                      </Button>
                      <Button
                        variant="secondary"
                        onClick={() =>
                          void review(report.id, "dismissed", report.revision)
                        }
                      >
                        {uiText("Dismiss")}
                      </Button>
                    </footer>
                  </Box>
                ))}
                <details>
                  <summary>{uiText("Report history")}</summary>
                  {snapshot.water_reports
                    .filter(
                      (report) =>
                        report.point_id === source.id &&
                        report.status !== "pending",
                    )
                    .map((report) => (
                      <Typography as="p" variant="body" key={report.id}>
                        {localizedStatus(report.availability)} ·{" "}
                        {localizedStatus(report.status)} · {report.note}{" "}
                        {uiText("· observed")}{" "}
                        {formatDateTime(report.observed_at)} ·{" "}
                        {report.reporter_id} {uiText("· reviewed")}{" "}
                        {report.reviewed_at
                          ? formatDateTime(report.reviewed_at)
                          : "—"}{" "}
                        · {report.reviewer_id || "—"}
                      </Typography>
                    ))}
                </details>
              </Card>
            );
          })}
        </Card>
        <Card as="section" density="compact" shadow="none">
          <Typography as="h2" variant="h3">
            {tr(language, "Unidades", "Units")}
          </Typography>
          <Button variant="secondary" onClick={onManageUnits}>
            {tr(
              language,
              "Gerir unidades e viaturas",
              "Manage units and vehicles",
            )}
          </Button>
          <ResourceInventoryGroups items={snapshot.units} category={(unit) => unitCategory(unit, snapshot.vehicles)} renderItem={(unit) => (
            <Card as="article" density="compact" shadow="none" key={unit.id}>
              <strong>{unit.callsign}</strong>
              <Typography as="p" variant="body">
                {unit.organisation} · {localizedStatus(unit.status)}
              </Typography>
              <Typography as="small" variant="small">
                {unit.latest_location
                  ? ageLabel(unit.latest_location.observed_at, language)
                  : tr(language, "Sem localização", "No location")}
              </Typography>
            </Card>
          )} />
          <Typography as="h2" variant="h3">
            {tr(language, "Pontos do incidente", "Incident points")}
          </Typography>
          {snapshot.incident_points.map((point) => (
            <Card as="article" density="compact" shadow="none" key={point.id}>
              <strong>{point.name}</strong>
              <Typography as="p" variant="body">
                {localizedStatus(point.kind)} ·{" "}
                {point.description || point.notes}
              </Typography>
            </Card>
          ))}
        </Card>
      </Box>
    </SectionContainer>
  );
}

function candidateRoads(
  roads: FeatureCollection | undefined,
  report: RoadReport,
  query: string,
): GeoJSON.Feature[] {
  const term = query.trim().toLowerCase();
  const values = (roads?.features || []).filter(
    (feature) =>
      !term ||
      `${feature.properties?.name || ""} ${feature.properties?.segment_id || ""}`
        .toLowerCase()
        .includes(term),
  );
  if (report.observed_location) {
    const [lon, lat] = report.observed_location;
    const distance = (feature: GeoJSON.Feature) => {
      let closest = Infinity;
      const visit = (value: unknown): void => {
        if (!Array.isArray(value)) return;
        if (typeof value[0] === "number" && typeof value[1] === "number") {
          closest = Math.min(
            closest,
            (value[0] - lon) ** 2 + (value[1] - lat) ** 2,
          );
        } else value.forEach(visit);
      };
      visit(
        (
          feature.geometry as
            | GeoJSON.LineString
            | GeoJSON.MultiLineString
            | null
        )?.coordinates,
      );
      return closest;
    };
    values.sort((left, right) => distance(left) - distance(right));
  }
  const selected =
    report.segment_id &&
    roads?.features.find(
      (feature) => String(feature.properties?.segment_id) === report.segment_id,
    );
  return selected && !values.slice(0, 80).includes(selected)
    ? [selected, ...values.slice(0, 79)]
    : values.slice(0, 80);
}

export function InventoryDrawer({
  scenarioId,
  snapshot,
  language,
  onClose,
  onChanged,
}: {
  scenarioId: string;
  snapshot: MobilitySnapshot;
  language: Language;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [activeTab, setActiveTab] = useState<"vehicles" | "units" | "radio">("vehicles");
  const [saving, setSaving] = useState(false);
  const discarded = useRef(false);
  const [drafts, setDrafts] = useState<Set<string>>(() => new Set());
  const clearDraft = (tab: string) => setDrafts((values) => { const next = new Set(values); next.delete(tab); return next; });
  const closeInventory = () => { if (!saving && (!drafts.size || confirmDiscard())) { discarded.current = true; setDrafts(new Set()); onClose(); } };
  useNavigationGuard((to) => {
    if (discarded.current) return true;
    if (to.kind === "mobility" && to.scenarioId === scenarioId && to.tab === "units") return true;
    if (saving) { setError("Aguarde a conclusão da gravação."); return false; }
    return !drafts.size || confirmDiscard();
  }, drafts.size > 0);
  const tabsId = useId();
  const tabs = [{ id: "vehicles", label: "Viaturas" }, { id: "units", label: "Unidades" }, { id: "radio", label: "Check-in por rádio" }] as const;
  const [vehicleName, setVehicleName] = useState("");
  const [vehicleClass, setVehicleClass] =
    useState<VehicleProfile["vehicle_class"]>("light");
  const [width, setWidth] = useState("");
  const [height, setHeight] = useState("");
  const [weight, setWeight] = useState("");
  const [offRoad, setOffRoad] = useState(false);
  const [callsign, setCallsign] = useState("");
  const [organisation, setOrganisation] = useState("");
  const [vehicleId, setVehicleId] = useState(snapshot.vehicles[0]?.id || "");
  const [error, setError] = useState("");
  const [locationUnit, setLocationUnit] = useState(snapshot.units[0]?.id || "");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  async function addVehicle() {
    if (saving) return;
    setSaving(true); setError("");
    try {
      await api.addVehicle(scenarioId, {
        id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
        name: vehicleName,
        vehicle_class: vehicleClass,
        width_m: width ? Number(width) : null,
        height_m: height ? Number(height) : null,
        weight_t: weight ? Number(weight) : null,
        off_road: offRoad,
        notes: "",
        revision: 1,
      });
      setVehicleName("");
      clearDraft("vehicles");
      onChanged();
    } catch (e) {
      setError(message(e));
    } finally { setSaving(false); }
  }
  async function addUnit() {
    if (saving) return;
    setSaving(true); setError("");
    try {
      await api.addUnit(scenarioId, {
        id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
        callsign,
        organisation,
        contact: "",
        vehicle_id: vehicleId,
        status: "available",
        revision: 1,
      });
      setCallsign("");
      clearDraft("units");
      onChanged();
    } catch (e) {
      setError(message(e));
    } finally { setSaving(false); }
  }
  async function recordLocation() {
    if (saving) return;
    setSaving(true); setError("");
    try {
      await api.checkIn(scenarioId, locationUnit, {
        coordinates: [Number(longitude), Number(latitude)],
        observed_at: new Date().toISOString(),
        source: "radio",
        accuracy_m: null,
      });
      setLatitude("");
      clearDraft("radio");
      setLongitude("");
      onChanged();
    } catch (e) {
      setError(message(e));
    } finally { setSaving(false); }
  }
  async function toggleUnit(unit: OperationalUnit) {
    if (saving) return;
    setSaving(true); setError("");
    try {
      await api.setUnitStatus(
        scenarioId,
        unit,
        unit.status === "available" ? "unavailable" : "available",
      );
      onChanged();
    } catch (e) {
      setError(message(e));
    } finally { setSaving(false); }
  }
  return (
    <Dialog onChangeCapture={() => { discarded.current = false; setDrafts((values) => new Set(values).add(activeTab)); }} onDismiss={saving ? undefined : closeInventory} aria-label="Unidades e viaturas" className="drawer-backdrop"
      onMouseDown={event => { if (event.target === event.currentTarget && !saving) closeInventory(); }}>
      <PopupLayout title="Unidades e viaturas" size="drawer" onClose={closeInventory} closeDisabled={saving}
        navigation={<div className="popup-tab-list" role="tablist" aria-label="Tarefas do inventário" onKeyDown={event => {
          const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
          if (!keys.includes(event.key) || saving) return;
          event.preventDefault();
          const index = tabs.findIndex(tab => tab.id === activeTab);
          const next = event.key === "Home" ? 0 : event.key === "End" ? 2 : (index + (event.key === "ArrowRight" ? 1 : 2)) % 3;
          setActiveTab(tabs[next].id);
          event.currentTarget.querySelectorAll<HTMLButtonElement>("button")[next]?.focus();
        }}>
          {tabs.map(tab => <Button key={tab.id} id={`${tabsId}-${tab.id}`} role="tab" aria-controls={`${tabsId}-panel`}
            aria-selected={activeTab === tab.id} tabIndex={activeTab === tab.id ? 0 : -1} variant={activeTab === tab.id ? "secondary" : "outline"}
            disabled={saving} onClick={() => { setActiveTab(tab.id); setError(""); }}>{tab.label}</Button>)}
        </div>}
        feedback={error && <p className="inline-error" role="alert">{error}</p>}
        actions={activeTab === "vehicles" ? <Button disabled={saving || !vehicleName.trim()} onClick={() => void addVehicle()}>{saving ? "A guardar…" : "Adicionar viatura"}</Button>
          : activeTab === "units" ? <Button disabled={saving || !callsign.trim() || !organisation.trim() || !vehicleId} onClick={() => void addUnit()}>{saving ? "A guardar…" : "Adicionar unidade"}</Button>
            : <Button disabled={saving || !locationUnit || !latitude || !longitude} onClick={() => void recordLocation()}>{saving ? "A guardar…" : "Registar localização"}</Button>}>
        <fieldset className="popup-task-fields" disabled={saving}>
          {activeTab === "vehicles" && (<section role="tabpanel" id={`${tabsId}-panel`} aria-labelledby={`${tabsId}-${activeTab}`} className="popup-form-section">
            <Typography as="h2" variant="h3">
              Nova viatura
            </Typography>
            <details><summary>Viaturas registadas ({snapshot.vehicles.length})</summary>
              <ResourceInventoryGroups items={snapshot.vehicles} category={vehicleCategory} renderItem={(vehicle) => (
                <Card
                  density="compact"
                  shadow="none"
                  className="inventory-item"
                  key={vehicle.id}
                >
                  <strong>{vehicle.name}</strong>
                  <span>
                    {localizedStatus(vehicle.vehicle_class)}
                    {vehicle.off_road ? " · todo-o-terreno" : ""}
                  </span>
                </Card>
              )} />
            </details>
            <label>
              Nome
              <input
                value={vehicleName}
                onChange={(event) => setVehicleName(event.target.value)}
              />
            </label>
            <label>
              Classe
              <select
                value={vehicleClass}
                onChange={(event) =>
                  setVehicleClass(
                    event.target.value as VehicleProfile["vehicle_class"],
                  )
                }
              >
                <option value="light">Ligeiro</option>
                <option value="heavy">Pesado</option>
                <option value="tanker">Autotanque</option>
                <option value="bus">Autocarro</option>
                <option value="ambulance">Ambulância</option>
                <option value="other">Outro</option>
                <option value="aircraft">Aeronave</option>
              </select>
            </label>
            <details><summary>Dimensões e acesso (opcional)</summary>
              <Box className="three-col">
                <label>
                  Largura (m)
                  <input
                    type="number"
                    step="0.1"
                    value={width}
                    onChange={(event) => setWidth(event.target.value)}
                  />
                </label>
                <label>
                  Altura (m)
                  <input
                    type="number"
                    step="0.1"
                    value={height}
                    onChange={(event) => setHeight(event.target.value)}
                  />
                </label>
                <label>
                  Peso (t)
                  <input
                    type="number"
                    step="0.1"
                    value={weight}
                    onChange={(event) => setWeight(event.target.value)}
                  />
                </label>
              </Box>
              <label className="ack">
                <input
                  type="checkbox"
                  checked={offRoad}
                  onChange={(event) => setOffRoad(event.target.checked)}
                />
                Apta para piso não pavimentado
              </label>
            </details>
          </section>)}
          {activeTab === "units" && (<section role="tabpanel" id={`${tabsId}-panel`} aria-labelledby={`${tabsId}-${activeTab}`} className="popup-form-section">
            <Typography as="h2" variant="h3">
              Nova unidade
            </Typography>
            <details><summary>Unidades registadas ({snapshot.units.length})</summary>
              <ResourceInventoryGroups items={snapshot.units} category={(unit) => unitCategory(unit, snapshot.vehicles)} renderItem={(unit) => (
                <Card
                  density="compact"
                  shadow="none"
                  className="inventory-item"
                  key={unit.id}
                >
                  <Box>
                    <strong>{unit.callsign}</strong>
                    <span>
                      {unit.organisation} · {localizedStatus(unit.status)} ·{" "}
                      {unit.latest_location
                        ? ageLabel(unit.latest_location.observed_at, language)
                        : tr(language, "sem localização", "no location")}
                    </span>
                  </Box>
                  {["available", "unavailable"].includes(unit.status) && (
                    <Button
                      variant="secondary"
                      onClick={() => void toggleUnit(unit)}
                    >
                      {unit.status === "available"
                        ? tr(language, "Indisponível", "Unavailable")
                        : tr(language, "Disponível", "Available")}
                    </Button>
                  )}
                </Card>
              )} />
            </details>
            <label>
              Indicativo
              <input
                value={callsign}
                onChange={(event) => setCallsign(event.target.value)}
              />
            </label>
            <label>
              Organização
              <input
                value={organisation}
                onChange={(event) => setOrganisation(event.target.value)}
              />
            </label>
            <label>
              Viatura
              <select
                value={vehicleId}
                onChange={(event) => setVehicleId(event.target.value)}
              >
                <option value="">Selecionar</option>
                {snapshot.vehicles.map((vehicle) => (
                  <option key={vehicle.id} value={vehicle.id}>
                    {vehicle.name}
                  </option>
                ))}
              </select>
            </label>
          </section>)}
          {activeTab === "radio" && (<section role="tabpanel" id={`${tabsId}-panel`} aria-labelledby={`${tabsId}-${activeTab}`} className="popup-form-section">
            <Typography as="h2" variant="h3">
              Check-in por rádio
            </Typography>
            <label>
              Unidade
              <select
                value={locationUnit}
                onChange={(event) => setLocationUnit(event.target.value)}
              >
                {snapshot.units.map((unit) => (
                  <option key={unit.id} value={unit.id}>
                    {unit.callsign}
                  </option>
                ))}
              </select>
            </label>
            <Box className="two-col">
              <label>
                {uiText("Latitude")}
                <input
                  type="number"
                  step="0.00001"
                  value={latitude}
                  onChange={(event) => setLatitude(event.target.value)}
                />
              </label>
              <label>
                {uiText("Longitude")}
                <input
                  type="number"
                  step="0.00001"
                  value={longitude}
                  onChange={(event) => setLongitude(event.target.value)}
                />
              </label>
            </Box>
          </section>)}
        </fieldset>
      </PopupLayout>
    </Dialog>
  );
}

function CrewView({
  scenario,
  snapshot,
  movement,
  language,
  onRefresh,
}: {
  scenario: Pick<ScenarioWorkspace, "id" | "name">;
  snapshot: MobilitySnapshot;
  movement?: Movement;
  language: Language;
  onRefresh: () => void;
}) {
  const unit = snapshot.units[0];
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [pendingAction, setPendingAction] = useState<{
    action: string;
    id: string;
  }>();
  const [reporting, setReporting] = useState(false);
  const [roadName, setRoadName] = useState("");
  const [roadReason, setRoadReason] = useState("");
  const [reportLocation, setReportLocation] = useState<[number, number]>();
  useEffect(() => {
    if (movement)
      localStorage.setItem(`brief:${movement.id}`, JSON.stringify(movement));
  }, [movement?.revision]);
  async function action(
    value: string,
    requestId = pendingAction?.action === value
      ? pendingAction.id
      : crypto.randomUUID(),
  ) {
    if (!movement) return;
    setSending(true);
    setPendingAction({ action: value, id: requestId });
    try {
      await api.movementAction(
        scenario.id,
        movement,
        value,
        "crew",
        "",
        requestId,
      );
      setPendingAction(undefined);
      setError("");
      onRefresh();
    } catch (e) {
      setError(`${tr(language, "Não enviado", "Not sent")}: ${message(e)}`);
    } finally {
      setSending(false);
    }
  }
  function locate() {
    if (!unit) return;
    if (!navigator.geolocation) {
      setError("Este dispositivo não disponibiliza localização.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        void api
          .checkIn(scenario.id, unit.id, {
            coordinates: [position.coords.longitude, position.coords.latitude],
            observed_at: new Date(position.timestamp).toISOString(),
            source: "phone",
            accuracy_m: position.coords.accuracy,
          })
          .then(onRefresh)
          .catch((e) => setError(`Não enviado: ${message(e)}`));
      },
      () =>
        setError(
          "Não foi possível obter a localização. Confirme as permissões do dispositivo.",
        ),
      { enableHighAccuracy: true, timeout: 15_000, maximumAge: 60_000 },
    );
  }
  async function reportRoad() {
    try {
      await api.addRoadReport(scenario.id, {
        id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
        segment_id: null,
        road_name: roadName || "Local por identificar",
        kind: "blocked",
        reason: roadReason,
        direction: "both",
        affected_vehicle_classes: [],
        status: "pending",
        source: "crew",
        geometry: null,
        observed_location: reportLocation,
        observed_at: new Date().toISOString(),
        revision: 1,
      });
      setReporting(false);
      setRoadName("");
      setRoadReason("");
      setReportLocation(undefined);
      onRefresh();
    } catch (e) {
      setError(`Não enviado: ${message(e)}`);
    }
  }
  function locateReport() {
    navigator.geolocation?.getCurrentPosition(
      (position) =>
        setReportLocation([
          position.coords.longitude,
          position.coords.latitude,
        ]),
      () =>
        setError(
          "Não foi possível obter a localização. Confirme as permissões do dispositivo.",
        ),
      { enableHighAccuracy: true, timeout: 15_000 },
    );
  }
  if (!movement)
    return (
      <SectionContainer
        as="main"
        containerClassName="ds-stack"
        spacing="compact"
        className="crew-shell"
      >
        <header>
          <strong>{scenario.name}</strong>
        </header>
        <Card
          as="section"
          density="compact"
          shadow="none"
          className="crew-empty"
        >
          <Typography as="h1" variant="h1">
            {tr(language, "Sem movimento atribuído", "No assigned movement")}
          </Typography>
          <Typography as="p" variant="body">
            {tr(
              language,
              "Mantenha o contacto por rádio. Esta página atualiza automaticamente.",
              "Keep radio contact. This page refreshes automatically.",
            )}
          </Typography>
          <Button variant="secondary" onClick={locate}>
            {tr(language, "Partilhar localização", "Share location")}
          </Button>
        </Card>
        <CrewWaterSources
          scenarioId={scenario.id}
          snapshot={snapshot}
          onRefresh={onRefresh}
        />
      </SectionContainer>
    );
  const requiresAck =
    movement.acknowledged_brief_version !== movement.brief_version &&
    movement.status !== "assigned";
  const next = requiresAck
    ? {
        action: "acknowledge_brief",
        label: tr(
          language,
          "Confirmar briefing atualizado",
          "Acknowledge updated brief",
        ),
      }
    : nextAction(movement.status, language);
  return (
    <SectionContainer
      as="main"
      containerClassName="ds-stack"
      spacing="compact"
      className="crew-shell"
    >
      <header>
        <Box>
          <strong>{unit?.callsign}</strong>
          <span>{scenario.name}</span>
        </Box>
      </header>
      {!navigator.onLine && (
        <Box className="offline-banner">
          {tr(
            language,
            "Sem ligação · a mostrar o último briefing guardado",
            "Offline · showing the last saved brief",
          )}
        </Box>
      )}
      <Card as="article" density="default" shadow="card" className="crew-brief">
        <Typography as="span" variant="label" className="eyebrow">
          Briefing v{movement.brief_version} ·{" "}
          {statusLabel(movement.status, language)}
        </Typography>
        <Typography as="h1" variant="h1">
          {movement.destination.name}
        </Typography>
        <Typography as="p" variant="body" className="crew-purpose">
          {movement.purpose}
        </Typography>
        {movement.needs_review && (
          <Card density="compact" shadow="none" className="route-problem">
            {tr(
              language,
              "O percurso foi afetado. Contacte o despacho antes de avançar.",
              "The route was affected. Contact dispatch before proceeding.",
            )}
          </Card>
        )}
        <Card density="compact" shadow="none" className="crew-route-facts">
          <strong>
            {formatNumber(movement.route.selected?.distance_km || 0)} km
          </strong>
          <strong>
            {Math.round(movement.route.selected?.duration_min || 0)} min
          </strong>
          <span>{tr(language, "estimados", "estimated")}</span>
        </Card>
        <ol className="road-list">
          {movement.route.selected?.road_names.map((name) => (
            <li key={name}>{name}</li>
          ))}
        </ol>
        {next && (
          <Button
            variant="primary"
            size="lg"
            className="ds-full ds-crew-action"
            disabled={sending || movement.needs_review}
            onClick={() => void action(next.action)}
          >
            {sending ? tr(language, "A enviar…", "Sending…") : next.label}
          </Button>
        )}
        <Box className="crew-secondary">
          <Button variant="secondary" onClick={locate}>
            {tr(language, "Partilhar localização", "Share location")}
          </Button>
          <Button
            variant="secondary"
            onClick={() => void action("cannot_proceed")}
          >
            {tr(language, "Não consigo avançar", "Cannot proceed")}
          </Button>
          <Button variant="secondary" onClick={() => setReporting(true)}>
            {tr(language, "Reportar estrada", "Report road")}
          </Button>
        </Box>
        {reporting && (
          <Card density="compact" shadow="none" className="crew-report">
            <Typography as="h2" variant="h3">
              {tr(
                language,
                "Reportar estrada bloqueada",
                "Report blocked road",
              )}
            </Typography>
            <label>
              {tr(language, "Estrada ou local", "Road or location")}
              <input
                value={roadName}
                onChange={(event) => setRoadName(event.target.value)}
              />
            </label>
            <label>
              {tr(language, "O que observou?", "What did you observe?")}
              <textarea
                rows={3}
                value={roadReason}
                onChange={(event) => setRoadReason(event.target.value)}
              />
            </label>
            <Button variant="secondary" onClick={locateReport}>
              {uiText("Use observed location")}{" "}
              {reportLocation
                ? `(${reportLocation[1].toFixed(5)}, ${reportLocation[0].toFixed(5)})`
                : uiText("(optional)")}
            </Button>
            <Button
              variant="primary"
              disabled={!roadReason}
              onClick={() => void reportRoad()}
            >
              {tr(language, "Enviar ao despacho", "Send to dispatch")}
            </Button>
            <Button variant="secondary" onClick={() => setReporting(false)}>
              {tr(language, "Cancelar", "Cancel")}
            </Button>
            <Typography as="small" variant="small">
              {tr(
                language,
                "O despacho identificará o troço antes de alterar os percursos.",
                "Dispatch will identify the road section before changing routes.",
              )}
            </Typography>
          </Card>
        )}
        {error && (
          <Typography role="alert" as="p" variant="small" className="unsent">
            {error}
            {pendingAction && (
              <Button
                variant="secondary"
                onClick={() =>
                  void action(pendingAction.action, pendingAction.id)
                }
              >
                {tr(language, "Tentar novamente", "Retry")}
              </Button>
            )}
            <Button
              variant="secondary"
              onClick={() => {
                setError("");
                setPendingAction(undefined);
              }}
            >
              {tr(language, "Fechar", "Close")}
            </Button>
          </Typography>
        )}
        <footer>
          <span>
            {tr(language, "Contacto", "Contact")}:{" "}
            {movement.dispatcher_contact ||
              tr(language, "via rádio", "by radio")}
          </span>
          <span>
            {tr(language, "Emitido", "Issued")}{" "}
            {formatDateTime(movement.created_at)}
          </span>
        </footer>
      </Card>
      <CrewWaterSources
        scenarioId={scenario.id}
        snapshot={snapshot}
        onRefresh={onRefresh}
      />
    </SectionContainer>
  );
}

function CrewWaterSources({
  scenarioId,
  snapshot,
  onRefresh,
}: {
  scenarioId: string;
  snapshot: MobilitySnapshot;
  onRefresh: () => void;
}) {
  const [pointId, setPointId] = useState(snapshot.water_sources[0]?.id || "");
  const [availability, setAvailability] = useState<
    "available" | "unavailable" | "uncertain"
  >("uncertain");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  async function submit() {
    try {
      await api.addWaterReport(scenarioId, {
        point_id: pointId,
        availability,
        note,
        observed_at: new Date().toISOString(),
      });
      setNote("");
      setError("");
      onRefresh();
    } catch (reason) {
      setError(message(reason));
    }
  }
  return (
    <Card as="section" density="compact" shadow="none" className="crew-report">
      <Typography as="h2" variant="h3">
        {uiText("Water source report")}
      </Typography>
      <Typography as="p" variant="body">
        {uiText(
          "Reports are reviewed by dispatch before the recorded status changes.",
        )}
      </Typography>
      <label>
        {uiText("Source")}
        <select
          value={pointId}
          onChange={(event) => setPointId(event.target.value)}
        >
          {snapshot.water_sources.map((source) => (
            <option key={source.id} value={source.id}>
              {source.name} ·{" "}
              {localizedStatus(source.water?.availability || "unknown")}
            </option>
          ))}
        </select>
      </label>
      <label>
        {uiText("Observed status")}
        <select
          value={availability}
          onChange={(event) =>
            setAvailability(event.target.value as typeof availability)
          }
        >
          <option value="available">{uiText("Available")}</option>
          <option value="unavailable">{uiText("Unavailable")}</option>
          <option value="uncertain">{uiText("Uncertain")}</option>
        </select>
      </label>
      <label>
        {uiText("Observation")}
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      <Button
        variant="primary"
        disabled={!pointId || !note.trim()}
        onClick={() => void submit()}
      >
        {uiText("Send to dispatch")}
      </Button>
      {error && (
        <Typography role="alert" as="p" variant="small" className="unsent">
          {error}
        </Typography>
      )}
    </Card>
  );
}

export function SharedBrief({ token }: { token: string }) {
  const [movement, setMovement] = useState<Movement>();
  const [error, setError] = useState("");
  useEffect(() => {
    api
      .sharedBrief(token)
      .then((value) => {
        setMovement(value);
        localStorage.setItem(`shared:${token}`, JSON.stringify(value));
      })
      .catch((reason) => {
        const cached = localStorage.getItem(`shared:${token}`);
        if (cached) setMovement(JSON.parse(cached));
        else setError(message(reason));
      });
  }, [token]);
  if (!movement)
    return (
      <SectionContainer
        as="main"
        containerClassName="ds-stack"
        className="brief-page"
      >
        {error || "A carregar briefing…"}
      </SectionContainer>
    );
  return (
    <SectionContainer
      as="main"
      containerClassName="ds-stack"
      className="brief-page"
    >
      <Card
        as="article"
        density="default"
        shadow="card"
        className="print-brief"
      >
        <header>
          <span className="prumo-brief-brand"><PrumoBrand /><span>Briefing v{movement.brief_version}</span></span>
          <strong>{statusLabel(movement.status)}</strong>
        </header>
        <Typography as="h1" variant="h1">
          {movement.destination.name}
        </Typography>
        <Typography as="h2" variant="h3">
          {movement.purpose}
        </Typography>
        <dl>
          <dt>Origem</dt>
          <dd>{movement.origin.name}</dd>
          <dt>Partida</dt>
          <dd>{formatDateTime(movement.departure_at)}</dd>
          <dt>Percurso</dt>
          <dd>
            {formatNumber(movement.route.selected?.distance_km || 0)} km ·{" "}
            {Math.round(movement.route.selected?.duration_min || 0)} min
            estimados
          </dd>
          <dt>Contacto</dt>
          <dd>{movement.dispatcher_contact || "via rádio"}</dd>
        </dl>
        <ol>
          {movement.route.selected?.road_names.map((name) => (
            <li key={name}>{name}</li>
          ))}
        </ol>
        <Typography as="p" variant="small" className="brief-warning">
          Sem conflito registado não significa percurso seguro. Confirme
          alterações pelo canal operacional.
        </Typography>
        <Button variant="secondary" onClick={() => window.print()}>
          Imprimir
        </Button>
        <footer>
          Emitido {formatDateTime(movement.created_at)} · versão{" "}
          {movement.brief_version}
        </footer>
      </Card>
    </SectionContainer>
  );
}

function MapSummary({
  snapshot,
  language,
  onMovement,
}: {
  snapshot: MobilitySnapshot;
  language: Language;
  onMovement: (value: Movement) => void;
}) {
  const active = snapshot.movements.filter((item) =>
    activeStatuses.includes(item.status),
  );
  return (
    <Card density="compact" shadow="none" className="mobility-panel">
      <Typography as="span" variant="label" className="eyebrow">
        {tr(language, "Situação operacional", "Operational situation")}
      </Typography>
      <Typography as="h2" variant="h3">
        {active.length} {tr(language, "movimentos ativos", "active movements")}
      </Typography>
      <Box className="summary-stats">
        <span>
          <strong>
            {
              snapshot.units.filter((item) => item.status === "available")
                .length
            }
          </strong>{" "}
          {tr(language, "unidades disponíveis", "available units")}
        </span>
        <span>
          <strong>
            {
              snapshot.road_reports.filter((item) => item.status === "pending")
                .length
            }
          </strong>{" "}
          {tr(language, "estradas por confirmar", "roads awaiting review")}
        </span>
        <span>
          <strong>{active.filter((item) => item.needs_review).length}</strong>{" "}
          {tr(language, "percursos a rever", "routes to review")}
        </span>
      </Box>
      {active.map((item) => (
        <Button
          variant="secondary"
          className="summary-movement ds-list-action"
          key={item.id}
          onClick={() => onMovement(item)}
        >
          <strong>{item.destination.name}</strong>
          <span>{statusLabel(item.status, language)}</span>
        </Button>
      ))}
    </Card>
  );
}

function FireStart({
  scenarioId,
  run,
  latestRun,
  loading,
  error,
  layerError,
  onShowLatest,
  onUpdates,
  onSources,
  onJourney,
}: {
  scenarioId: string;
  run?: Run;
  latestRun?: Run;
  loading: boolean;
  error: string;
  layerError: string;
  onShowLatest: () => void;
  onUpdates: () => void;
  onSources: () => void;
  onJourney: () => void;
}) {
  return (
    <Card
      as="section"
      density="compact"
      shadow="none"
      className="mobility-panel fire-start"
      aria-label="Começar pelo incêndio"
    >
      <Typography as="span" variant="label" className="eyebrow">
        1 · Situação do incêndio
      </Typography>
      <Typography as="h2" variant="h3">
        Comece pelo incêndio
      </Typography>
      {loading ? (
        <Typography as="p" variant="body">
          A procurar simulações concluídas…
        </Typography>
      ) : error ? (
        <Typography as="p" variant="body" role="alert">
          Não foi possível consultar as simulações: {error}
        </Typography>
      ) : run ? (
        <>
          <Typography as="p" variant="body">
            O mapa mostra o resultado modelado de{" "}
            <strong>{run.scenario.engine}</strong>, criado em{" "}
            {formatDateTime(run.created_at)}. Selecione o minuto no mapa para
            ver a evolução.
          </Typography>
          {layerError && (
            <Typography as="p" variant="body" role="alert">
              A camada do incêndio não está disponível neste momento.
            </Typography>
          )}
          <ButtonLink
            variant="primary"
            className="ds-full"
            href={`/scenarios/${scenarioId}/simulation?run=${encodeURIComponent(run.id)}`}
          >
            Analisar a evolução do incêndio
          </ButtonLink>
        </>
      ) : latestRun ? (
        <>
          <Typography as="p" variant="body">
            A camada do incêndio está desligada.
          </Typography>
          <Button
            variant="secondary"
            className="fire-start-link"
            onClick={onShowLatest}
          >
            Mostrar o último resultado modelado
          </Button>
        </>
      ) : (
        <>
          <Typography as="p" variant="body">
            Ainda não existe um incêndio modelado para esta ocorrência.
            Configure e execute uma simulação para começar pelo fogo.
          </Typography>
          <ButtonLink
            variant="primary"
            className="ds-full"
            href={`/scenarios/${scenarioId}/experiments/new`}
          >
            Criar simulação de incêndio
          </ButtonLink>
        </>
      )}
      <Box className="fire-next">
        <Typography as="span" variant="label" className="eyebrow">
          2 · Coordenar a resposta
        </Typography>
        <Typography as="p" variant="body">
          Depois de observar o incêndio, reveja os relatos, confirme os recursos
          e planeie os percursos.
        </Typography>
        <Button variant="secondary" onClick={onUpdates}>
          Rever atualizações
        </Button>
        <Button variant="secondary" onClick={onSources}>
          Ver fontes e unidades
        </Button>
        <Button variant="secondary" onClick={onJourney}>
          Planear percurso
        </Button>
      </Box>
    </Card>
  );
}

function FitFireBounds({
  fire,
  runId,
}: {
  fire?: FeatureCollection;
  runId: string;
}) {
  const map = useMap();
  const fittedRun = useRef("");
  useEffect(() => {
    if (!runId) {
      fittedRun.current = "";
      return;
    }
    if (!fire || !runId || fittedRun.current === runId) return;
    const bounds = geoJSON(fire as GeoJSON.GeoJsonObject).getBounds();
    if (!bounds.isValid()) return;
    map.fitBounds(bounds.pad(0.2), { maxZoom: 13 });
    fittedRun.current = runId;
  }, [fire, runId, map]);
  return null;
}
function PlanPointPicker({ target, onPick }: {
  target: "origin" | "destination" | null;
  onPick: (target: "origin" | "destination", value: [number, number]) => void;
}) {
  useMapEvents({
    click: (event) => {
      if (target) onPick(target, [event.latlng.lng, event.latlng.lat]);
    },
  });
  return null;
}
function nextAction(status: MovementStatus, language: Language = "pt") {
  return status === "assigned"
    ? { action: "accept", label: tr(language, "Aceitar", "Accept") }
    : status === "accepted"
      ? { action: "depart", label: tr(language, "Partir", "Depart") }
      : status === "travelling"
        ? { action: "arrive", label: tr(language, "Cheguei", "Arrived") }
        : status === "arrived" || status === "cannot_proceed"
          ? { action: "complete", label: tr(language, "Concluir", "Complete") }
          : null;
}
function statusLabel(value: MovementStatus, language: Language = "pt") {
  const pt = {
    assigned: "Atribuído",
    accepted: "Aceite",
    travelling: "Em deslocação",
    arrived: "No local",
    completed: "Concluído",
    cannot_proceed: "Impedido",
    cancelled: "Cancelado",
  }[value];
  const en = {
    assigned: "Assigned",
    accepted: "Accepted",
    travelling: "Travelling",
    arrived: "On scene",
    completed: "Completed",
    cannot_proceed: "Cannot proceed",
    cancelled: "Cancelled",
  }[value];
  return tr(language, pt, en);
}
function reportLabel(value: RoadReport["kind"], language: Language = "pt") {
  const pt = {
    blocked: "Bloqueada",
    restricted: "Condicionada",
    reopening: "Reabertura reportada",
    uncertain: "Informação incerta",
  }[value];
  const en = {
    blocked: "Blocked",
    restricted: "Restricted",
    reopening: "Reopening reported",
    uncertain: "Uncertain information",
  }[value];
  return tr(language, pt, en);
}
function eventLabel(value: string) {
  return (
    (
      {
        assigned: "Movimento atribuído",
        accept: "Movimento aceite",
        brief_acknowledged: "Briefing atualizado confirmado",
        depart: "Partida confirmada",
        arrive: "Chegada confirmada",
        complete: "Movimento concluído",
        cannot_proceed: "Unidade impedida",
        road_reported: "Condição da estrada reportada",
        road_reviewed: "Condição da estrada revista",
        road_reopened: "Restrição encerrada",
        location: "Localização atualizada",
      } as Record<string, string>
    )[value] || value
  );
}
function ageLabel(value: string, language: Language) {
  const minutes = Math.max(
    0,
    Math.floor((Date.now() - new Date(value).getTime()) / 60000),
  );
  return minutes < 1
    ? language === "pt"
      ? "agora"
      : "now"
    : language === "pt"
      ? `há ${minutes} min${minutes > 15 ? " · desatualizada" : ""}`
      : `${minutes} min ago${minutes > 15 ? " · stale" : ""}`;
}
function localDateTime(value: Date) {
  const offset = value.getTimezoneOffset();
  return new Date(value.getTime() - offset * 60000).toISOString().slice(0, 16);
}
function message(value: unknown) {
  return value instanceof Error ? value.message : "Ocorreu um erro";
}
function tr(_language: Language, portuguese: string, _english: string) {
  return portuguese;
}
function formatClock(seconds: number) {
  const value = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}
function demoResultLabel(value: string, language: Language) {
  const pt = (
    {
      received: "recebida",
      assigned: "atribuído",
      accepted: "aceite",
      travelling: "em deslocação",
      "location received": "localização recebida",
      "pending review": "aguarda revisão",
      confirmed: "confirmado",
      "acknowledgment required": "aguarda confirmação",
      acknowledged: "confirmado",
      "radio fallback": "continuidade por rádio",
      "location received by radio": "localização recebida por rádio",
      arrived: "chegada confirmada",
      completed: "concluído",
      "restriction resolved": "restrição encerrada",
    } as Record<string, string>
  )[value];
  return language === "pt" ? pt || value : value;
}
