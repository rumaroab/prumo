// Every response is in memory. The fixture rejects any unexpected API request.
import { createRoot } from "react-dom/client";
import { useState } from "react";
import "leaflet/dist/leaflet.css";
import "../src/styles.css";
import "../src/interface.css";
import "../src/design-tokens.css";
import App from "../src/App";
import { api } from "../src/api";
import { LoadingProvider } from "../src/loading";
import { navigateTo, parseRoute, workspaceHref } from "../src/navigation";
import type { AccessAssessment, Area, MobilityComparison, MobilitySnapshot, Run, ScenarioPoint, ScenarioWorkspace, SessionUser } from "../src/types";

const user: SessionUser = { id: "fixture-user", username: "coordenador", display_name: "Coordenação", role: new URLSearchParams(location.search).has("crew") ? "crew" : "administrator" };
const point = (id: string, longitude: number): ScenarioPoint => ({ id, kind: "water_point", name: `Fonte ${id}`, coordinates: [longitude, 41.45], description: "", notes: "", source: "demo", data_status: "unverified", water: { source_type: "tank", availability: "available", capacity_m3: 20, flow_l_min: 600, access_notes: "", verification_status: "unverified" }, asset: null });
let scenario: ScenarioWorkspace = {
  id: "navigation-fixture", name: "Ocorrência de demonstração com um nome muito comprido em Guimarães e arredores", description: "Dados fictícios para verificar a navegação.",
  area_id: "fixture-area", area_package_id: "fixture-area", resource_center: [-8.3, 41.45], resource_radius_km: 25, fire_margin_km: 5, cell_size_m: 30, revision: 1,
  simulation: { name: "Exercício", engine: "mtt", ignitions: [{ id: "a", name: "Ignição principal", coordinates: [-8.3, 41.45], start_min: 0 }], wind_speed_kmh: 20, wind_direction_deg: 45, moisture: "moderate", duration_min: 120, seed: 42, exposure_buffer_m: 30, weather_source: { kind: "constant" }, engine_profile: "default" },
  points: [point("a", -8.31), point("b", -8.29)], closures: [], teams: [], resource_groups: [], containment_tasks: [], allocation_plans: [], created_at: "2026-10-22T10:00:00Z", updated_at: "2026-10-22T10:00:00Z", start_time: "2026-10-22T10:00:00Z", setup_complete: true, scenario_kind: "legacy",
};
const area: Area = { name: "Área de teste", center: [-8.3, 41.45], bounds: [-8.4, 41.3, -8.2, 41.6], landscape_ready: true, roads_ready: true };
const run: Run = { id: "fixture-run", name: "Resultado de referência", notes: "", metadata_revision: 1, status: "ready", stage: "ready", progress: 100, scenario: scenario.simulation, scenario_id: scenario.id, scenario_revision: 1, area_package_id: scenario.area_package_id, mode: "single", created_at: scenario.created_at, result: { engine: "mtt", engine_version: "fixture", temporal_resolution_min: 1, manifest: {} } };
const runs: Run[] = new URLSearchParams(location.search).has("empty") ? [] : [run, { ...run, id: "fixture-other-run", name: "Segundo resultado" }];
const empty = { type: "FeatureCollection", features: [] };
const snapshot: MobilitySnapshot = { user, scenario, vehicles: [{ id: "vehicle", name: "Autotanque", vehicle_class: "tanker", width_m: null, height_m: null, weight_t: null, off_road: false, notes: "", available: true, revision: 1, water_tank_capacity_l: 5000 }], units: [], movements: [], road_reports: [], events: [], server_time: scenario.created_at, water_sources: scenario.points, water_reports: [], incident_points: [], communications: [] };
const comparison: MobilityComparison = {
  id: "demo-navigation-base", scenario_id: scenario.id, created_at: scenario.created_at,
  run_id: run.id, run_name: run.name, engine: "mtt", forecast_start_at: scenario.created_at,
  departure_min: 0, horizon_min: 120, lead_time_min: 10,
  unit: { id: "fixture-unit", callsign: "TQ-01", organisation: "Bombeiros", vehicle: snapshot.vehicles[0], coordinates: [-8.3, 41.45] },
  delivery_coordinates: [-8.3, 41.45], requested_l: 3000,
  outcomes: scenario.points.map((source, index) => ({ label: index ? "B" : "A", source, assumptions: { point_id: source.id, available_volume_l: 20000, flow_l_min: 600, setup_time_min: 2 }, status: index ? "clear" : "infeasible", reason: "Resultado fictício para testar a interface.", delivered_l: index ? 3000 : 0, stages: [] })),
  road_package_id: null, road_revision: "fixture", model_provenance: {},
};
const population = [1, 2, 3, 4].map((index) => ({ origin: { ...point(`origin-${index}`, -8.3 + index / 1000), kind: "asset" as const, name: `Local ${index}`, population_role: "origin" as const }, status: "clear" as const, reachable_count: 1, options: [] }));
const assessment: AccessAssessment = {
  id: "fixture-assessment", scenario_id: scenario.id, created_at: scenario.created_at,
  comparison_id: comparison.id, comparison, road_revision: "fixture",
  section_id: new URLSearchParams(location.search).has("no-proposal") ? null : "fixture-section",
  population_points: population.map((value) => value.origin), population_vehicle: snapshot.vehicles[0],
  without: { water: comparison.outcomes, population },
  with_proposal: { water: comparison.outcomes.map((value) => ({ ...value, status: "infeasible" })), population: population.map((value, index) => index ? value : { ...value, status: "infeasible", reachable_count: 0 }) },
  summary: { water_changed: true, population_changed: 1 },
};
const withAssessment = new URLSearchParams(location.search).has("assessment");
let failSave = false;
let holdSave = false;
let releaseSave: (() => void) | undefined;
let confirmCount = 0;
let discard = true;
const unexpectedRequests: string[] = [];
window.fetch = async (input) => { unexpectedRequests.push(String(input)); throw new Error("Pedido de rede inesperado na verificação isolada."); };
Object.assign(api, {
  session: async () => {
    if (new URLSearchParams(location.search).has("login")) throw new Error("Sessão de teste terminada.");
    return user;
  },
  scenarios: async () => [scenario],
  scenario: async (id: string) => { if (id === "missing") throw new Error("Ocorrência não encontrada."); return scenario; },
  scenarioRuns: async () => runs,
  area: async () => area,
  areaRoads: async () => empty, roads: async () => empty, fire: async () => empty,
  engines: async () => [], weather: async () => [],
  mobility: async () => { if (new URLSearchParams(location.search).has("offline")) throw new Error("Sem ligação: dados locais."); return snapshot; }, mobilityRoads: async () => empty, routePlans: async () => [],
  mobilityComparisons: async () => withAssessment ? [comparison] : [], accessAssessments: async () => withAssessment ? [assessment] : [], accessRoads: async () => empty,
  mobilityMetrics: async () => ({ scenarios: {} }), exerciseSummaries: async () => ({ scenarios: {} }),
  exerciseSituation: async () => ({}), snapshots: async () => [], missions: async () => [], responsePlans: async () => [], responseExperiments: async () => [], exerciseRuns: async () => [],
  sharedBrief: async () => {
    if (!new URLSearchParams(location.search).has("brief")) throw new Error("Briefing de teste indisponível.");
    const route = { label: "Percurso de exercício", duration_min: 15, distance_km: 8, segment_ids: [], road_names: ["Estrada de exercício"], unknown_constraints: [], feature: { type: "Feature", geometry: { type: "LineString", coordinates: [[-8.31, 41.45], [-8.29, 41.45]] }, properties: {} } };
    return { id: "fixture-movement", unit_id: "fixture-unit", vehicle_id: "vehicle", purpose: "Abastecimento de exercício", origin: { name: "Quartel de exercício", coordinates: [-8.31, 41.45] }, destination: { name: "Setor de exercício", coordinates: [-8.29, 41.45] }, departure_at: scenario.created_at, route: { status: "clear", message: "Dados fictícios", origin_connector_m: 0, destination_connector_m: 0, data_quality: "exact", selected: route, routes: [route] }, status: "assigned", notes: "", dispatcher_contact: "Canal de exercício", revision: 1, brief_version: 1, created_at: scenario.created_at, updated_at: scenario.created_at };
  },
  saveScenario: async (value: ScenarioWorkspace) => {
    if (failSave) throw new Error("Falha de gravação simulada.");
    if (holdSave) await new Promise<void>((resolve) => { releaseSave = resolve; });
    scenario = { ...value, revision: scenario.revision + 1 };
    return scenario;
  },
});
if (new URLSearchParams(location.search).has("light")) document.documentElement.dataset.dsTheme = "light";
const base = `/scenarios/${scenario.id}`;
if (location.pathname.startsWith("/tests/")) history.replaceState({}, "", `${base}/decisions?run=${run.id}`);
// Render the real print rules on screen when native print preview is unavailable.
const printPreview = new URLSearchParams(location.search).has("print-preview");
if (printPreview) {
  function printRules(rules: CSSRuleList): string {
    return Array.from(rules, (rule) => {
      if (rule instanceof CSSMediaRule && rule.conditionText === "print") return Array.from(rule.cssRules, (value) => value.cssText).join("\n");
      return rule instanceof CSSGroupingRule ? printRules(rule.cssRules) : "";
    }).join("\n");
  }
  const style = document.createElement("style");
  style.textContent = Array.from(document.styleSheets, (sheet) => printRules(sheet.cssRules)).join("\n");
  document.head.append(style);
}
createRoot(document.getElementById("root")!).render(<LoadingProvider><App /></LoadingProvider>);
const tick = (ms = 80) => new Promise((resolve) => setTimeout(resolve, ms));
async function until(check: () => boolean, message: string) { for (let i = 0; i < 60; i++) { if (check()) return; await tick(); } throw new Error(message); }
async function go(suffix: string) {
  if (!await navigateTo(base + suffix)) throw new Error(`Navegação recusada: ${suffix}`);
  await tick(180);
  const brand = document.querySelector('.application-brand')?.getBoundingClientRect();
  const context = document.querySelector('.application-breadcrumb')?.getBoundingClientRect();
  const header = document.querySelector('.application-header')?.getBoundingClientRect();
  if (brand && header && Math.abs(brand.y + brand.height / 2 - header.y - header.height / 2) > 1) throw new Error(`Marca desalinhada verticalmente em ${suffix}`);
  if (brand && Math.abs(brand.x + brand.width / 2 - innerWidth / 2) > 1) throw new Error(`Marca fora do centro em ${suffix}`);
  if (brand && context && context.left < brand.right - 1) throw new Error(`Contexto sobrepõe a marca em ${suffix}`);
  const content = document.querySelector('.application-content');
  if (content && content.scrollWidth > content.clientWidth + 1) throw new Error(`Transbordo horizontal em ${suffix}: ${content.scrollWidth}/${content.clientWidth}`);
  checkAlignment();
}
function checkAlignment() {
  for (const logo of document.querySelectorAll('.prumo-brand')) {
    const expected = logo.closest('[data-ds-theme]')?.getAttribute('data-ds-theme') === 'light' ? getComputedStyle(logo).color : 'rgb(145, 195, 213)';
    const accent = logo.querySelector('.prumo-accent');
    if (!accent || getComputedStyle(accent).fill !== expected) throw new Error('A marca PRUMO perdeu a cor aprovada');
    if (logo.getAttribute('aria-label') !== 'PRUMO') throw new Error('A marca PRUMO perdeu o nome acessível');
  }
  for (const link of document.querySelectorAll("a")) {
    if (!link.getClientRects().length) continue;
    const [red, green, blue] = getComputedStyle(link).color.match(/[\d.]+/g)!.map(Number);
    if (blue > red + 12 && blue > green + 8) throw new Error(`Ligação azul: ${link.textContent}`);
  }
  for (const button of document.querySelectorAll('.map-actions .ds-button')) {
    const action = button.getBoundingClientRect();
    for (const obstacle of document.querySelectorAll('.mobility-map .leaflet-control-zoom, .fire-advisory, .mobility-road-legend')) {
      const box = obstacle.getBoundingClientRect();
      if (action.left < box.right && action.right > box.left && action.top < box.bottom && action.bottom > box.top) throw new Error("Ações sobrepõem os controlos ou a informação do mapa");
    }
  }
  for (const grid of document.querySelectorAll(".two-col, .three-col, .decision-pair, .form-field-grid, .coordinate-fields, .import-filters, .population-edit-row, .fire-advisory")) {
    const labels = Array.from(grid.children).filter((child) => child.matches("label") && child.getClientRects().length);
    for (const label of labels) {
      const control = label.querySelector("input:not([type=checkbox]):not([type=radio]), select, textarea");
      if (!control) continue;
      for (const sibling of labels) {
        if (sibling === label) continue;
        const current = label.getBoundingClientRect();
        const next = sibling.getBoundingClientRect();
        if (Math.abs(next.left - current.left) <= 1 && next.top > current.top && next.top < control.getBoundingClientRect().bottom + 4) throw new Error(`Campos sem espaçamento: ${label.textContent} / ${sibling.textContent}`);
        if (Math.abs(next.top - current.top) > 1) continue;
        const peer = sibling.querySelector("input:not([type=checkbox]):not([type=radio]), select, textarea");
        if (peer && Math.abs(control.getBoundingClientRect().top - peer.getBoundingClientRect().top) > 1) throw new Error(`Campos desalinhados: ${label.textContent} / ${sibling.textContent}`);
      }
    }
  }
}
function edit(input: HTMLInputElement, value: string) { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); input.dispatchEvent(new Event("change", { bubbles: true })); }
function Checks() {
  const [results, setResults] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  async function test() {
    setRunning(true); setResults([]);
    const assert = (pass: unknown, label: string) => { if (!pass) throw new Error(label); setResults((items) => [...items, `PASS ${label}`]); };
    const nativeConfirm = window.confirm;
    window.confirm = () => { confirmCount++; return discard; };
    try {
      discard = true; failSave = false; holdSave = false;
      const changedName = `${scenario.name} · revista`;
      await go("/experiments"); await go(`/decisions?run=${run.id}`); confirmCount = 0;
      await until(() => Boolean(document.querySelector(".decision-input")), "Comparação não carregou");
      const header = document.querySelector(".application-header");
      assert(Boolean(header), "Cabeçalho partilhado na comparação");
      assert(Boolean(header?.querySelector('svg[role="img"][aria-label="PRUMO"]')), "Marca PRUMO com nome acessível no cabeçalho");
      assert(document.title === "Abastecimento · PRUMO", "Título da comparação usa PRUMO");
      await go("/experiments");
      assert(document.querySelectorAll(".experiment-row").length === runs.length, "Histórico reutiliza as simulações existentes");
      assert(document.querySelector(".application-header") === header && confirmCount === 0, "Carregamento inicial não cria aviso de rascunho");
      await go("/experiments/new");
      assert(document.querySelectorAll('.application-content h1').length === 1, "Nova simulação mantém um único título principal");
      await go(`/experiments/${run.id}`);
      assert(document.querySelector('h1')?.textContent === run.name, "Ligação direta abre os detalhes da simulação");
      await go(`/simulation?run=${run.id}`);
      await until(() => Boolean(document.querySelector(".viewer-controls")), "Resultado não carregou");
      assert(document.querySelector(".application-header") === header, "Cabeçalho mantém identidade entre áreas");
      assert(workspaceHref(scenario.id, "/decisions").includes(run.id), "Resultado explícito acompanha a mudança de área");
      await go("/mobility/map");
      assert(Boolean(document.querySelector('.mobility-map .map-actions')), "Ações do mapa disponíveis sem sobrepor o zoom");
      await go("/mobility/movements");
      await until(() => Boolean(document.querySelector(".mobility-shell")), "Mobilidade não carregou");
      assert(document.querySelector(".workspace-context h1")?.textContent === "Percursos", "Subendereço abre o quadro de percursos");
      await go("/mobility/units");
      await until(() => Boolean(document.querySelector('dialog[open][aria-label="Unidades e viaturas"]')), "Inventário não abriu");
      assert(Boolean(document.activeElement?.closest("dialog")), "Inventário recebe foco ao abrir diretamente");
      const inventoryInput = document.querySelector('dialog input') as HTMLInputElement;
      edit(inventoryInput, "Viatura ainda por guardar"); await tick();
      discard = false;
      const refused = await navigateTo(base + "/mobility/updates");
      assert(!refused && location.pathname.endsWith("/units"), "Rascunho de inventário cancela navegação sem perda");
      discard = true; await go("/mobility/updates");
      assert(!document.querySelector('dialog[open]'), "Mudança confirmada fecha o inventário");
      history.back(); await until(() => location.pathname.endsWith("/units") && Boolean(document.querySelector('dialog[open]')), "Voltar não restaurou inventário");
      assert(true, "Voltar restaura endereço e inventário");
      history.forward(); await until(() => location.pathname.endsWith("/updates") && !document.querySelector('dialog[open]'), "Avançar não restaurou atualizações");
      assert(true, "Avançar restaura a página correta");
      await go(`/decisions?view=data&run=${run.id}`);
      await until(() => Boolean(document.querySelector(".decision-setup")), "Dados não carregaram");
      assert(document.querySelector(".workspace-context h1")?.textContent === "Dados e integrações", "Ligação antiga view=data continua válida");
      await go(`/decisions?run=${run.id}`);
      const firstNumber = document.querySelector('.decision-input input[type="number"]') as HTMLInputElement;
      assert(Boolean(firstNumber), "Comparação apresenta os controlos existentes");
      edit(firstNumber, "4321"); await tick();
      const before = confirmCount;
      await go(`/decisions?view=data&run=${run.id}`); await go(`/decisions?run=${run.id}`);
      assert(confirmCount === before && (document.querySelector('.decision-input input[type="number"]') as HTMLInputElement).value === "4321", "Troca de separador preserva o rascunho sem aviso");
      await go(`/decisions?perspective=access&run=${run.id}`);
      assert(document.querySelector(".workspace-context h1")?.textContent === "Acessos" && (!document.querySelector(".application-nav") || document.querySelector('.application-nav a[aria-current="page"]')?.textContent === "Acessos"), "Perspetiva selecionada na navegação partilhada");
      await go(`/decisions?perspective=population&run=${run.id}`);
      history.back(); await until(() => parseRoute(location.href).perspective === "access", "Voltar não restaurou a perspetiva");
      history.forward(); await until(() => parseRoute(location.href).perspective === "population", "Avançar não restaurou a perspetiva");
      await go(`/decisions?run=${run.id}`);
      assert(confirmCount === before && (document.querySelector('.decision-input input[type="number"]') as HTMLInputElement).value === "4321", "Perspetivas e histórico preservam os dados da comparação");
      discard = true; await go("/experiments"); await go(`/decisions?run=${run.id}`);
      await until(() => Boolean(document.querySelector('.decision-input input[type="number"]')), "Comparação não voltou a carregar");
      edit(document.querySelector('.decision-input input[type="number"]') as HTMLInputElement, "4321"); await tick();
      discard = false;
      assert(!await navigateTo(base + "/experiments"), "Rascunho de decisão impede saída cancelada");
      history.back(); await tick(350);
      assert(location.search.includes(`run=${run.id}`) && !location.search.includes("view=data"), "Voltar cancelado restaura endereço e editor");
      discard = true; await go("");
      await until(() => Boolean(document.querySelector('.overview-grid input')), "Visão geral não carregou");
      failSave = true;
      edit(document.querySelector('.overview-grid input') as HTMLInputElement, changedName); await tick();
      assert(!await navigateTo(base + "/experiments") && location.pathname === base, "Falha de gravação mantém a página e as alterações");
      await until(() => Boolean(document.querySelector('[role="alert"]')?.textContent?.includes("Falha de gravação simulada")), "Erro de gravação não apresentado");
      assert(document.body.textContent?.includes("Falha de gravação simulada"), "Falha de gravação é apresentada ao utilizador");
      failSave = false; holdSave = true;
      const leaving = navigateTo(base + "/experiments"); await tick();
      assert(location.pathname === base && Boolean(releaseSave), "Navegação aguarda a gravação pendente");
      holdSave = false; releaseSave?.(); await leaving; await tick(180);
      assert(location.pathname.endsWith("/experiments") && scenario.name === changedName, "Gravação termina antes da mudança de página");
      await go("/decisions?run=incompatible"); await tick();
      assert(document.body.textContent?.includes("não é compatível"), "Resultado incompatível apresenta explicação");
      await go("/map");
      assert(document.querySelector(".archive-page") && document.querySelector(".application-header") === header, "Arquivo conserva a navegação e o modo de consulta");
      assert(document.documentElement.scrollWidth <= innerWidth, "Sem transbordo horizontal da página");
      await navigateTo("/brief/fixture"); await tick(180);
      assert(document.title === "Briefing · PRUMO" && !document.querySelector(".application-header"), "Briefing independente mantém título PRUMO");
      assert(unexpectedRequests.length === 0, "Nenhum pedido alcançou APIs reais");
    } catch (error) { setResults((items) => [...items, `FAIL ${String(error)}`]); }
    finally { window.confirm = nativeConfirm; setRunning(false); }
  }
  return <aside style={{ position: "fixed", right: 8, bottom: 8, zIndex: 20000, maxWidth: "min(560px, 95vw)", maxHeight: "40vh", overflow: "auto", background: "#14232d", border: "1px solid #8ed7f0", padding: 12, color: "white" }}><button disabled={running} onClick={() => void test()}>Iniciar verificações de navegação</button><pre data-testid="navigation-results" style={{ whiteSpace: "pre-wrap" }}>{results.join("\n")}</pre></aside>;
}
if (!printPreview) createRoot(document.getElementById("navigation-checks")!).render(<Checks />);
