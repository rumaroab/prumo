import { useEffect, useRef, useState, type ReactNode } from "react";
import { PrumoBrand } from "./PrumoBrand";
import { api } from "../api";
import { parseRoute, useAppLocation, workspaceHref, type Workspace } from "../navigation";
import { Button, Dialog } from "./ui";
import "../navigation.css";
const groups: { id: Workspace; label: string; links: [string, string][] }[] = [
  { id: "simulations", label: "Simulações", links: [["/experiments", "Simulações guardadas"], ["/simulation", "Análise do resultado"]] },
  { id: "mobility", label: "Unidades e deslocações", links: [["/mobility", "Mapa"], ["/mobility/movements", "Percursos"], ["/mobility/units", "Unidades e viaturas"], ["/mobility/updates", "Atualizações"], ["/mobility/sources", "Fontes e meios"]] },
  { id: "decisions", label: "Apoio à decisão", links: [["/decisions", "Abastecimento"], ["/decisions?perspective=access", "Acessos"], ["/decisions?perspective=population", "Apoio à população"], ["/decisions?view=data", "Dados e integrações"]] },
];
export function AppShell({ children }: { children: ReactNode }) {
  const location = useAppLocation(); const route = parseRoute(location);
  const hasScenario = Boolean(route.scenarioId);
  const [name, setName] = useState<{ id: string; name: string }>();
  const [wide, setWide] = useState(() => matchMedia("(min-width: 1200px)").matches);
  const [open, setOpen] = useState(false); const [hidden, setHidden] = useState(false);
  const [expanded, setExpanded] = useState<Partial<Record<Workspace, boolean>>>({});
  const pageKey = `${route.kind}/${route.scenarioId || ""}/${route.tab || ""}/${route.perspective || ""}`;
  const page = useRef<HTMLDivElement>(null); const initial = useRef(true);
  useEffect(() => { const media = matchMedia("(min-width: 1200px)"); const changed = () => { setWide(media.matches); setOpen(false); }; media.addEventListener("change", changed); return () => media.removeEventListener("change", changed); }, []);
  useEffect(() => { let active = true; if (route.scenarioId) api.scenario(route.scenarioId).then((value) => { if (active) setName({ id: value.id, name: value.name }); }).catch(() => {}); return () => { active = false; }; }, [route.scenarioId, location]);
  useEffect(() => {
    setOpen(false);
    if (route.workspace) setExpanded((values) => ({ ...values, [route.workspace!]: true }));
    const focusPage = !initial.current;
    initial.current = false;
    const frame = requestAnimationFrame(() => {
      if (focusPage) { page.current?.scrollTo(0, 0); page.current?.focus({ preventScroll: true }); }
    });
    return () => cancelAnimationFrame(frame);
  }, [pageKey, route.workspace, route.title]);
  const selectedName = name && name.id === route.scenarioId ? name.name : "Ocorrência";
  const nav = (drawer = false) => <nav className="application-nav" aria-label="Navegação principal" id={drawer ? "navigation-drawer" : "navigation-sidebar"}>
    {drawer && <div className="application-nav-heading"><strong>Navegação</strong><Button variant="ghost" onClick={() => setOpen(false)}>Fechar menu</Button></div>}
    <a href="/scenarios" aria-current={route.kind === "list" ? "page" : undefined}>Ocorrências</a>
    {route.scenarioId && <>
      <p className="application-nav-context" title={selectedName}>{selectedName}</p>
      <a href={`/scenarios/${route.scenarioId}`} aria-current={route.kind === "overview" ? "page" : undefined}>Visão geral</a>
      {groups.map((group) => <section key={group.id} className="application-nav-group" data-active={route.workspace === group.id}>
        <button type="button" aria-expanded={Boolean(expanded[group.id])} aria-controls={`${drawer ? "drawer" : "sidebar"}-${group.id}`} onClick={() => setExpanded((values) => ({ ...values, [group.id]: !values[group.id] }))}>{group.label}<span aria-hidden="true">{expanded[group.id] ? "−" : "+"}</span></button>
        <div id={`${drawer ? "drawer" : "sidebar"}-${group.id}`} hidden={!expanded[group.id]}>
          {group.links.map(([suffix, label]) => { const target = parseRoute(`/scenarios/${route.scenarioId}${suffix}`); const active = target.kind === route.kind && target.tab === route.tab && target.perspective === route.perspective; return <a key={suffix} href={workspaceHref(route.scenarioId!, suffix)} aria-current={active ? "page" : undefined}>{label}</a>; })}
          {group.id === "simulations" && ["experiment", "new-experiment"].includes(route.kind) && <a href={location} aria-current="page">{route.title}</a>}
        </div>
      </section>)}
      <a className="application-nav-archive" href={`/scenarios/${route.scenarioId}/map`} aria-current={route.kind === "archive" ? "page" : undefined}>Arquivo de planos <small>Apenas consulta</small></a>
    </>}
  </nav>;
  return <div className="application-shell" data-sidebar={hasScenario && wide && !hidden}>
    <a href="#application-content" className="application-skip">Saltar para o conteúdo</a>
    <header className="application-header">
      {hasScenario && <Button variant="ghost" className="application-nav-toggle" aria-label={wide && !hidden || open ? "Fechar navegação" : "Abrir navegação"} aria-expanded={wide ? !hidden : open} aria-controls={wide ? "navigation-sidebar" : "navigation-drawer"} onClick={() => wide ? setHidden((value) => !value) : setOpen((value) => !value)}><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" aria-hidden="true" focusable="false"><path d="M4 6h16M4 12h16M4 18h16" /></svg></Button>}
      <a href="/scenarios" className="application-brand"><PrumoBrand /></a>
      <nav className="application-breadcrumb" aria-label="Localização atual">{route.scenarioId && <><a title={selectedName} href={`/scenarios/${route.scenarioId}`}>{selectedName}</a><span aria-hidden="true">/</span></>}<span aria-current="page" title={route.title}>{route.title}</span></nav>
    </header>
    {hasScenario && wide && !hidden && <aside className="application-sidebar">{nav()}</aside>}
    {hasScenario && !wide && open && <Dialog className="application-nav-dialog" aria-label="Navegação principal" onDismiss={() => setOpen(false)} onClick={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>{nav(true)}</Dialog>}
    <div className="application-content" id="application-content" ref={page} tabIndex={-1}>{children}</div>
  </div>;
}
