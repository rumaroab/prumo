// Browser fixtures use in-memory responses. They never create incidents or preparation jobs.
import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { MapContainer, useMap } from "react-leaflet";
import { latLng, latLngBounds, type Map as LeafletMap } from "leaflet";
import "leaflet/dist/leaflet.css";
import "../src/styles.css";
import "../src/interface.css";
import "../src/design-tokens.css";
import { api } from "../src/api";
import { ScenarioWizard } from "../src/components/ScenarioWizard";
import { AreaSettings } from "../src/components/AreaSettings";
import { FogosImportDialog } from "../src/components/FogosImportDialog";
import { ScenarioManager } from "../src/components/ScenarioManager";
import { ScenarioList } from "../src/components/ManagementApp";
import { InventoryDrawer } from "../src/components/MobilityApp";
import { CoordinateFields, validCoordinates } from "../src/components/CoordinateFields";
import { MapViewport, fireAreaBounds } from "../src/components/LocationMap";
import { Button, Card, Dialog, PopupLayout } from "../src/components/ui";
import type { AreaPreparation, FogosIncident, MobilitySnapshot, ScenarioWorkspace } from "../src/types";

const query = new URLSearchParams(location.search);
if (!query.has("resume")) localStorage.removeItem("scenario-preparation/popup-fixture");
const workspace: ScenarioWorkspace = {
  id: "popup-fixture", name: "Ocorrência de demonstração com um nome muito comprido em Guimarães e arredores", description: "Dados fictícios para verificar o formulário.",
  area_id: "fixture", area_package_id: null, resource_center: [-8.3075, 41.4535], resource_radius_km: 25, fire_margin_km: 5, cell_size_m: 30, revision: 1,
  simulation: {
    name: "Exercício", engine: "mtt", ignitions: [{ id: "a", name: "Ignição principal com designação extensa", coordinates: [-8.3075, 41.4535], start_min: 0 },
    { id: "b", name: "Ignição secundária em outro local", coordinates: [-7.7, 40.5], start_min: 25 }], wind_speed_kmh: 20, wind_direction_deg: 45, moisture: "moderate", duration_min: 120, seed: 42, exposure_buffer_m: 30, weather_source: { kind: "constant" }, engine_profile: "default"  
},
  points: [], closures: [], teams: [], resource_groups: [], containment_tasks: [], allocation_plans: [], created_at: "2026-10-22T10:00:00Z", updated_at: "2026-10-22T10:00:00Z", setup_complete: false, scenario_kind: "legacy",
};
const incident: FogosIncident = { provider: "fogos.pt", incident_id: "fixture", source_url: "https://fogos.pt/", reported_at: "2026-10-22T10:00:00Z", updated_at: "2026-10-22T10:15:00Z", location: "Localização com nome extenso · Guimarães", municipality: "Guimarães", coordinates: [-8.3075, 41.4535], has_usable_coordinates: !query.has("missing"), is_rural_fire: true, status: "Em curso", active: true, importable: true, resources: { personnel: 18, vehicles: 5, aircraft: 1, firefighting_aircraft: 1 }, weather_warnings: [] };
let retry = false;
const job = (): AreaPreparation => ({ id: "popup-fixture-job", package_id: "fixture-area", status: query.get("state") === "running" ? "running" : query.get("state") === "failed" && !retry ? "failed" : "partial", stage: "ready", progress: 100, datasets: { terrain: { status: "ready" }, roads: { status: "ready" }, water: { status: "failed", error: "Fonte opcional indisponível" } }, error: query.get("state") === "failed" && !retry ? "Serviço de mapas temporariamente indisponível" : null, retryable: true });
const emptyCatalog = { type: "FeatureCollection", features: [] };
Object.assign(api, {
  estimateArea: async () => ({ fire_bounds: [-8.4, 41.3, -8.2, 41.6], grid_rows: 400, grid_columns: 400, cell_count: query.has("cost") ? 1500000 : 160000, area_km2: 144, cell_size_m: 30, cost_level: query.has("cost") ? "high" : "normal", requires_acknowledgement: query.has("cost"), allowed: true }),
  prepareArea: async () => ({ ...job(), status: "queued" }), preparation: async () => job(),
  retryPreparation: async () => { retry = true; return { ...job(), status: "queued" }; }, cancelPreparation: async () => ({ ...job(), status: "cancelled" }),
  waterCatalog: async () => emptyCatalog, fireStationCatalog: async () => emptyCatalog,
  createScenario: async () => { if (query.has("fail")) throw new Error("Não foi possível guardar. Tente novamente."); return workspace; },
  saveScenario: async () => workspace, importPoints: async () => workspace, importFireStations: async () => workspace,
  fogosStatus: async () => ({ configured: !query.has("unavailable"), message: "Integração indisponível neste exercício", provider: "fogos.pt", attribution: "Fogos.pt", source_url: "https://fogos.pt/" }),
  fogosIncidents: async () => ({ items: [incident], paginator: { totalPages: 1 }, attribution: "Fogos.pt", source_url: "https://fogos.pt/" }),
  fogosImportPreview: async () => ({ incident, snapshot: { id: "fixture-snapshot" }, suggested: { name: workspace.name, description: "Descrição opcional da fonte", start_time: "2026-10-22T10:00:00Z", coordinates: query.has("missing") ? null : incident.coordinates } }),
  addVehicle: async () => ({}), addUnit: async () => ({}), setUnitStatus: async () => ({}), checkIn: async () => ({}),
});
const snapshot = { vehicles: [{ id: "v1", name: "Viatura de demonstração com designação longa", vehicle_class: "tanker", revision: 1 }], units: [{ id: "u1", callsign: "Unidade de demonstração", organisation: "Organização de demonstração", vehicle_id: "v1", status: "available", revision: 1 }] } as MobilitySnapshot;

function Fixtures() {
  const [scene, setScene] = useState(query.get("scene") || "");
  const [notice, setNotice] = useState("");
  const [scenarios, setScenarios] = useState([workspace]);
  const [coordinate, setCoordinate] = useState<[number, number] | null>([-8.3, 41.4]);
  const [valid, setValid] = useState(true);
  const close = () => setScene("");
  const done = () => { setNotice("Ação concluída com dados de teste."); close(); };
  return <>
    <main style={{ padding: 24 }}><h1>Verificação dos formulários</h1><p>Respostas controladas; não altera os dados da aplicação.</p>
      <div className="popup-tab-list">{[["wizard", "Abrir preparação"], ["area", "Abrir cobertura"], ["fogos", "Abrir importação"], ["manager", "Abrir gestor"], ["inventory", "Abrir inventário"], ["manual", "Abrir criação manual"], ["coordinates", "Abrir coordenadas"], ["regressions", "Executar verificações do mapa"]].map(([id, label]) => <Button key={id} onClick={() => setScene(id)}>{label}</Button>)}</div>
      {notice && <p role="status">{notice}</p>}
      {scene === "manual" && <ScenarioList scenarios={scenarios} mobilityByScenario={{}} exerciseByScenario={{}} error="" setScenarios={setScenarios} onOpen={done} />}
      {scene === "regressions" && <ViewportRegressions />}
    </main>
    {scene === "wizard" && <ScenarioWizard workspace={workspace} onClose={close} onCreated={done} />}
    {scene === "area" && <AreaSettings workspace={workspace} onClose={close} onApply={async () => done()} />}
    {scene === "fogos" && <FogosImportDialog onClose={close} onCreated={done} onOpenExisting={done} />}
    {scene === "manager" && <ScenarioManager scenarios={scenarios} onClose={close} onRename={async (scenario, name) => setScenarios(values => values.map(item => item.id === scenario.id ? { ...item, name } : item))} onDelete={async scenario => setScenarios(values => values.filter(item => item.id !== scenario.id))} />}
    {scene === "inventory" && <InventoryDrawer scenarioId={workspace.id} snapshot={snapshot} language="pt" onClose={close} onChanged={() => setNotice("Registo de teste atualizado.")} />}
    {scene === "coordinates" && <Dialog onDismiss={close} aria-label="Verificar coordenadas"><PopupLayout title="Coordenadas" onClose={close} actions={<Button disabled={!valid}>Continuar</Button>}>
      <CoordinateFields value={coordinate} onCommit={setCoordinate} onValidityChange={setValid} /><output data-testid="committed-coordinate">{JSON.stringify(coordinate)}</output>
    </PopupLayout></Dialog>}
  </>;
}

function Probe({ ready }: { ready: (map: LeafletMap) => void }) { const map = useMap(); useEffect(() => { ready(map); }, [map]); return null; }
function ViewportRegressions() {
  const mapRef = useRef<LeafletMap | null>(null);
  const [target, setTarget] = useState<{ focus?: [number, number]; bounds?: [[number, number], [number, number]]; targetKey: string; recenter: number }>({ focus: [-8.3, 41.4], targetKey: "point/a", recenter: 0 });
  const [width, setWidth] = useState("100%");
  const [results, setResults] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const tick = () => new Promise(resolve => setTimeout(resolve, 120));
  const assert = (value: boolean, message: string) => { if (!value) throw new Error(message); setResults(items => [...items, `PASS ${message}`]); };
  const matches = (map: LeafletMap, point: [number, number]) => { const pixel = map.latLngToContainerPoint([point[1], point[0]]); const size = map.getSize(); return Math.abs(pixel.x - size.x / 2) <= 1 && Math.abs(pixel.y - size.y / 2) <= 1; };
  async function run() {
    setRunning(true); setResults([]);
    try {
      await tick(); const map = mapRef.current!;
      setTarget({ focus: [-8.3, 41.4], targetKey: "point/a", recenter: 1 }); await tick();
      assert(matches(map, [-8.3, 41.4]), "Initial target centered");
      setTarget({ focus: [-7.7, 40.5], targetKey: "point/b", recenter: 1 }); await tick();
      assert(matches(map, [-7.7, 40.5]), "Selecting a different point recenters");
      setTarget({ focus: [-7.6, 40.6], targetKey: "point/b", recenter: 1 }); await tick();
      assert(matches(map, [-7.6, 40.6]), "Committed coordinates update the viewport");
      setWidth("480px"); await tick(); await tick();
      assert(matches(map, [-7.6, 40.6]), "Point remains centered after popup resizing");
      map.panTo([40.8, -7.2], { animate: false }); setTarget(value => ({ ...value })); await tick();
      assert(matches(map, [-7.2, 40.8]), "Unrelated rendering preserves manual panning");
      setWidth("100%"); await tick(); await tick();
      assert(matches(map, [-7.2, 40.8]), "Resizing preserves a manually chosen point viewport");
      const coverage = latLngBounds(fireAreaBounds(workspace.simulation.ignitions, 25)!);
      coverage.extend(latLng(41.4535, -8.3075).toBounds(100000));
      const bounds: [[number, number], [number, number]] = [[coverage.getSouth(), coverage.getWest()], [coverage.getNorth(), coverage.getEast()]];
      setTarget({ bounds, targetKey: "coverage", recenter: 1 }); await tick();
      assert(map.getBounds().contains(coverage), "Coverage fits ignitions, margin and resource radius");
      setWidth("320px"); await tick(); await tick();
      assert(map.getSize().x <= 320 && map.getBounds().contains(coverage), "Resizing updates Leaflet and retains complete coverage");
      map.panTo([39.2, -9], { animate: false }); setTarget(value => ({ ...value })); await tick();
      assert(matches(map, [-9, 39.2]), "Coverage does not reset on unrelated edits");
      setTarget(value => ({ ...value, recenter: value.recenter + 1 })); await tick();
      assert(map.getBounds().contains(coverage), "Explicit recenter restores coverage");
      assert(!validCoordinates(null) && !validCoordinates([NaN, 41]) && !validCoordinates([181, 41]) && validCoordinates([-8, 41]), "Incomplete and invalid coordinate pairs are rejected");
    } catch (error) { setResults(items => [...items, `FAIL ${String(error)}`]); }
    finally { setRunning(false); setWidth("100%"); }
  }
  return <Card><Button disabled={running} onClick={() => void run()}>{running ? "A verificar…" : "Iniciar verificações"}</Button>
    <div style={{ width, maxWidth: "100%", height: 360, marginTop: 16 }}><MapContainer center={[41.4, -8.3]} zoom={12} style={{ height: "100%", width: "100%" }}><MapViewport {...target} /><Probe ready={map => { mapRef.current = map; }} /></MapContainer></div>
    <ol data-testid="regression-results" aria-live="polite">{results.map((result, index) => <li key={index}>{result}</li>)}</ol>
  </Card>;
}
createRoot(document.getElementById("root")!).render(<Fixtures />);
