import { useEffect, useLayoutEffect, useRef, useSyncExternalStore } from "react";
export type Workspace = "overview" | "simulations" | "mobility" | "decisions" | "archive";
export type AppRoute = { kind: "list" | "overview" | "experiments" | "new-experiment" | "experiment" | "simulation" | "mobility" | "decisions" | "archive" | "brief" | "missing"; scenarioId?: string; runId?: string; token?: string; workspace?: Workspace; tab?: string; perspective?: "water" | "access" | "population"; title: string };
const mobilityTitles: Record<string, string> = { map: "Mapa", movements: "Percursos", units: "Unidades e viaturas", updates: "Atualizações", sources: "Fontes e meios" };
export function parseRoute(href: string): AppRoute {
  const url = new URL(href, "http://fireline.local");
  const path = url.pathname.replace(/\/$/, "") || "/";
  const runId = url.searchParams.get("run") || undefined;
  if (path === "/" || path === "/scenarios") return { kind: "list", title: "Ocorrências" };
  const brief = path.match(/^\/brief\/([^/]+)$/);
  if (brief) return { kind: "brief", token: brief[1], title: "Briefing" };
  const match = path.match(/^\/scenarios\/([^/]+)(?:\/(.*))?$/);
  if (!match) return { kind: "missing", title: "Página indisponível" };
  const [, scenarioId, tail = ""] = match;
  const base = { scenarioId, runId };
  if (!tail) return { ...base, kind: "overview", workspace: "overview", title: "Visão geral" };
  if (tail === "experiments") return { ...base, kind: "experiments", workspace: "simulations", title: "Simulações guardadas" };
  if (tail === "experiments/new") return { ...base, kind: "new-experiment", workspace: "simulations", title: "Nova simulação" };
  if (/^experiments\/[^/]+$/.test(tail)) return { ...base, runId: tail.split("/")[1], kind: "experiment", workspace: "simulations", title: "Detalhes da simulação" };
  if (tail === "simulation") return { ...base, kind: "simulation", workspace: "simulations", title: "Análise do resultado" };
  if (tail === "mobility" || tail.startsWith("mobility/")) {
    const tab = tail.split("/")[1] || "map";
    if (!mobilityTitles[tab]) return { ...base, kind: "missing", title: "Página indisponível" };
    return { ...base, kind: "mobility", workspace: "mobility", tab, title: mobilityTitles[tab] };
  }
  if (tail === "decisions") {
    const tab = url.searchParams.get("view") === "data" ? "data" : "compare";
    const selected = url.searchParams.get("perspective");
    const perspective = selected === "access" || selected === "population" ? selected : "water";
    return { ...base, kind: "decisions", workspace: "decisions", tab, perspective: tab === "compare" ? perspective : undefined, title: tab === "data" ? "Dados e integrações" : perspective === "access" ? "Acessos" : perspective === "population" ? "Apoio à população" : "Abastecimento" };
  }
  if (/^(map|missions|plans|resources|updates|response-experiments|rehearsals|water-planning|decision-support)(\/|$)/.test(tail)) return { ...base, kind: "archive", workspace: "archive", title: "Arquivo de planos" };
  return { ...base, kind: "missing", title: "Página indisponível" };
}
const changeEvent = "fireline:navigation";
const guards = new Set<(to: AppRoute) => boolean | void | Promise<boolean | void>>();
let moving = false;
let checkingGuards = false;
let discardDecision: boolean | undefined;
let installed = false;
let currentIndex = 0;
let restoring: { index: number; done: () => void } | undefined;
const selectedRuns = new Map<string, string>();
export const locationSnapshot = () => window.location.pathname + window.location.search + window.location.hash;
function announce() { const route = parseRoute(locationSnapshot()); if (route.scenarioId && route.runId) rememberRun(route.scenarioId, route.runId); window.dispatchEvent(new Event(changeEvent)); }
export function useAppLocation() { return useSyncExternalStore((notify) => { window.addEventListener(changeEvent, notify); return () => window.removeEventListener(changeEvent, notify); }, locationSnapshot); }
export function rememberRun(scenarioId: string, runId?: string) { if (runId) selectedRuns.set(scenarioId, runId); else selectedRuns.delete(scenarioId); }
export function workspaceHref(scenarioId: string, suffix: string) {
  const url = new URL(`/scenarios/${scenarioId}${suffix}`, window.location.origin);
  const current = parseRoute(locationSnapshot());
  const run = current.scenarioId === scenarioId && current.runId ? current.runId : selectedRuns.get(scenarioId);
  if (run && /\/(simulation|decisions|mobility)/.test(suffix)) url.searchParams.set("run", run);
  return url.pathname + url.search;
}
async function canLeave(to: AppRoute) {
  checkingGuards = true; discardDecision = undefined;
  try { for (const guard of guards) if (await guard(to) === false) return false; return true; }
  catch { return false; } // The owning editor displays save failures and remains mounted.
  finally { checkingGuards = false; discardDecision = undefined; }
}
export async function navigateTo(href: string, replace = false): Promise<boolean> {
  const url = new URL(href, window.location.href);
  if (url.origin !== window.location.origin) return false;
  const target = url.pathname + url.search + url.hash;
  if (target === locationSnapshot()) return true;
  if (moving) return false;
  moving = true;
  try {
    if (!await canLeave(parseRoute(target))) return false;
    if (!replace) currentIndex += 1;
    window.history[replace ? "replaceState" : "pushState"]({ ...window.history.state, firelineIndex: currentIndex }, "", target);
    announce(); return true;
  } finally { moving = false; }
}
/** Replace only the local selection; keep the live editor mounted. */
export function updatePageQuery(name: string, value?: string) {
  const url = new URL(window.location.href);
  if (value) url.searchParams.set(name, value); else url.searchParams.delete(name);
  window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash); announce();
}
export function installNavigation() {
  if (installed) return () => {};
  installed = true;
  currentIndex = window.history.state?.firelineIndex ?? 0;
  window.history.replaceState({ ...window.history.state, firelineIndex: currentIndex }, "", locationSnapshot());
  const click = (event: MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = (event.target instanceof Element ? event.target.closest("a[href]") : null) as HTMLAnchorElement | null;
    if (!anchor || anchor.hasAttribute("download") || (anchor.target && anchor.target !== "_self")) return;
    const url = new URL(anchor.href);
    if (url.origin !== window.location.origin || !/^\/(scenarios(?:\/|$)|brief\/)/.test(url.pathname)) return;
    event.preventDefault(); void navigateTo(url.href);
  };
  const pop = async () => {
    const nextIndex = window.history.state?.firelineIndex;
    if (restoring) {
      if (typeof nextIndex === "number" && nextIndex !== restoring.index) { window.history.go(restoring.index - nextIndex); return; }
      const { done } = restoring; restoring = undefined; done(); return;
    }
    const href = locationSnapshot();
    if (typeof nextIndex !== "number") { announce(); return; }
    const delta = nextIndex - currentIndex;
    if (!delta) { announce(); return; }
    // Undo the history step before awaiting saves; cancellation retains URL and editor.
    await new Promise<void>((resolve) => { restoring = { index: currentIndex, done: resolve }; window.history.go(-delta); });
    if (moving) return;
    moving = true;
    try { if (await canLeave(parseRoute(href))) {
      await new Promise<void>((resolve) => { restoring = { index: nextIndex, done: resolve }; window.history.go(delta); });
      currentIndex = nextIndex; announce();
    } } finally { moving = false; }
  };
  document.addEventListener("click", click); window.addEventListener("popstate", pop);
  return () => { installed = false; document.removeEventListener("click", click); window.removeEventListener("popstate", pop); };
}
export function useNavigationGuard(handler: (to: AppRoute) => boolean | void | Promise<boolean | void>, dirty = false) {
  const latest = useRef(handler); latest.current = handler;
  useLayoutEffect(() => { const guard = (to: AppRoute) => latest.current(to); guards.add(guard); return () => { guards.delete(guard); }; }, []);
  useEffect(() => { if (!dirty) return; const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; }; window.addEventListener("beforeunload", unload); return () => window.removeEventListener("beforeunload", unload); }, [dirty]);
}
export function confirmDiscard() {
  if (checkingGuards && discardDecision !== undefined) return discardDecision;
  const confirmed = window.confirm("Existem alterações por guardar. Sair e descartar estas alterações?");
  if (checkingGuards) discardDecision = confirmed;
  return confirmed;
}
