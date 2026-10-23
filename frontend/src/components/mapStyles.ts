import type { FeatureCollection, Filter, ScenarioPoint } from "../types";

export function filterRoads(collection: FeatureCollection, filter: Filter, minute: number, forecast: number): FeatureCollection {
  return { ...collection, features: collection.features.filter(feature => {
    const exposure = feature.properties?.first_exposure_min as number | null;
    const unknown = feature.properties?.coverage === "unknown";
    if (filter === "all") return true;
    if (filter === "unknown") return unknown;
    if (unknown) return false;
    if (filter === "not-reached") return exposure == null;
    if (exposure == null) return false;
    if (filter === "now") return exposure <= minute;
    if (filter === "upcoming") return exposure > minute && exposure <= minute + forecast;
    return exposure <= minute + forecast;
  }) };
}

export function roadAppearance(feature: GeoJSON.Feature | undefined, minute: number, forecast: number, closedSegmentIds: string[] = []) {
  const p = feature?.properties || {};
  if (closedSegmentIds.includes(String(p.segment_id))) return { color: "#f0c3c0", width: 5, opacity: 1, dash: [3, 3] };
  if (p.coverage === "unknown") return { color: "#8ba4b5", width: 2.5, opacity: .85, dash: [2, 5] };
  if (p.member_arrival_minutes) {
    const members = p.member_arrival_minutes as (number | null)[];
    const values = members.filter(value => value != null) as number[];
    const probability = values.filter(value => value <= minute).length / members.length;
    if (probability > 0) return { color: probability >= .9 ? "#ff5d45" : probability >= .5 ? "#f47a45" : "#c83e62", width: 2 + probability * 3, opacity: .5 + probability * .5 };
  }
  if (p.first_exposure_min == null) return { color: "#6d8190", width: 1.1, opacity: .3 };
  if (p.first_exposure_min <= minute) return { color: "#ff5d45", width: 4.5, opacity: 1 };
  if (p.first_exposure_min <= minute + forecast) return { color: "#ffb547", width: 4, opacity: 1, dash: [8, 5] };
  return { color: "#6d8190", width: 1.1, opacity: .3 };
}

export function roadPopup(feature: GeoJSON.Feature) {
  const p = feature.properties || {};
  const exposure = !p.engine ? "Sem resultado de simulação selecionado" : p.first_exposure_min == null ? "Não alcançada nesta simulação" : `${Math.round(Number(p.first_exposure_min))} min`;
  const uncertainty = p.member_arrival_minutes ? `<br>Probabilidade de exposição até ao horizonte: ${Math.round(Number(p.reached_fraction) * 100)}%<br>P10 / P50 / P90: ${formatPercentile(p.arrival_p10_min)} / ${formatPercentile(p.arrival_p50_min)} / ${formatPercentile(p.arrival_p90_min)}` : "";
  return `<strong>${escapeHtml(String(p.name || "Estrada sem nome"))}</strong><br>${escapeHtml(roadClassLabel(String(p.road_class || "")))}<br>Primeira exposição modelada: ${exposure}${uncertainty}<br>${escapeHtml(String(p.engine || ""))}`;
}

export function pointColor(kind: ScenarioPoint["kind"]) {
  return { response_base: "#2e6d55", water_point: "#2776b8", asset: "#7357a6", hazard: "#d47621",
    staging_area: "#7a5c35", access_control: "#b4492e", shelter: "#3f7b72", delivery_point: "#276a8f", custom: "#53615a" }[kind];
}

export function pointLabel(kind: ScenarioPoint["kind"]) {
  return { response_base: "Base de resposta", water_point: "Ponto de água", asset: "Bem prioritário", hazard: "Perigo",
    staging_area: "Área de concentração", access_control: "Ponto de controlo de acesso", shelter: "Abrigo", delivery_point: "Ponto de entrega", custom: "Ponto personalizado" }[kind];
}

function roadClassLabel(value: string) {
  return ({ motorway: "Autoestrada", trunk: "Via principal", primary: "Estrada primária", secondary: "Estrada secundária",
    tertiary: "Estrada terciária", residential: "Via residencial", service: "Via de serviço", track: "Caminho", unclassified: "Via não classificada" } as Record<string, string>)[value] || value;
}

export function escapeHtml(value: string) {
  return value.replace(/[&<>'"]/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]!);
}

function formatPercentile(value: unknown) { return value == null ? "não alcançada" : `${Math.round(Number(value))} min`; }
