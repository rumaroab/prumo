/** The interface is currently published in European Portuguese only. */
import messages from "./ptPT.json";
export const LOCALE = "pt-PT" as const;

export function t(text: string): string {
  return (messages as Record<string, string>)[text] || text;
}

export function formatDateTime(value?: string | Date | null): string {
  if (!value) return "Data indisponível";
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? "Data indisponível" : new Intl.DateTimeFormat(LOCALE, {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
}

export function formatTime(value?: string | Date | null): string {
  if (!value) return "Hora indisponível";
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? "Hora indisponível" : new Intl.DateTimeFormat(LOCALE, {
    hour: "2-digit", minute: "2-digit", timeZoneName: "short",
  }).format(date);
}

export function formatNumber(value: number, maximumFractionDigits = 1): string {
  return new Intl.NumberFormat(LOCALE, { maximumFractionDigits }).format(value);
}

const statusLabels: Record<string, string> = {
  queued: "Em fila", preparing: "Em preparação", submitted: "Submetido", running: "Em curso",
  interrupted: "Interrompido", simulating: "A simular", "running members": "A executar simulações",
  paused: "Em pausa", archived: "Arquivado",
  "queued members": "Simulações em fila", "queued plans": "Planos em fila",
  "terrain and land cover": "Terreno e cobertura do solo", roads: "Estradas", buildings: "Edifícios",
  "water points": "Pontos de água", "fire stations": "Quartéis",
  postprocessing: "A processar resultados", ready: "Concluído", partial: "Parcial", failed: "Falhou",
  cancelled: "Cancelado", pending: "Por confirmar", confirmed: "Confirmado", dismissed: "Dispensado",
  available: "Disponível", unavailable: "Indisponível", uncertain: "Incerta", unknown: "Desconhecida",
  assigned: "Atribuído", accepted: "Aceite", travelling: "Em deslocação", arrived: "No local",
  completed: "Concluído", cannot_proceed: "Impedido", blocked: "Bloqueada", restricted: "Condicionada",
  reopening: "Reabertura reportada", both: "Ambos os sentidos", forward: "Sentido do troço", reverse: "Sentido oposto",
  unverified: "Não verificado", reported: "Reportado", verified: "Verificado",
  crew: "Equipa", dispatcher: "Despacho", radio: "Rádio", phone: "Telemóvel", manual: "Manual",
  water_point: "Ponto de água", response_base: "Base de resposta", priority_asset: "Bem prioritário",
  hazard: "Perigo", staging_area: "Área de concentração", access_control: "Controlo de acesso",
  shelter: "Abrigo", delivery_point: "Ponto de entrega", custom: "Ponto personalizado",
  light: "Ligeiro", heavy: "Pesado", tanker: "Autotanque", bus: "Autocarro", ambulance: "Ambulância", other: "Outro", aircraft: "Aeronave",
  low: "Baixa", moderate: "Moderada", high: "Alta",
};

export function statusLabel(value: string | null | undefined): string {
  return value ? statusLabels[value] || value : "Por confirmar";
}

export function stageLabel(stage: string | null | undefined, status = "running"): string {
  if (!stage) return statusLabel(status);
  const members = /^members (\d+)\/(\d+)$/.exec(stage);
  if (members) return `Simulações concluídas: ${members[1]}/${members[2]}`;
  return statusLabels[stage] || statusLabel(status);
}

const datasetLabels: Record<string, string> = {
  terrain: "Terreno", land_cover: "Cobertura do solo", landscape: "Terreno e cobertura do solo", roads: "Estradas", buildings: "Edifícios",
  water_points: "Pontos de água", fire_stations: "Quartéis", elevation: "Elevação",
};

export function datasetLabel(value: string): string {
  return datasetLabels[value] || "Conjunto de dados";
}

export function engineAvailabilityText(engineId: string, available: boolean, message: string): string {
  if (engineId === "mtt") return available ? "MTT experimental disponível." : "MTT indisponível.";
  if (engineId === "cell2fire") {
    if (!available) return "Cell2Fire indisponível. Compile o motor incluído no projeto.";
    return message.replace(" + scheduled ignitions", " · ignições programadas");
  }
  return available ? "Adaptador disponível." : "Adaptador indisponível ou com falha ao carregar.";
}

const apiErrors: Record<string, string> = {
  "Sign in required": "É necessário iniciar sessão.",
  "Invalid credentials": "Utilizador ou palavra-passe incorretos.",
  "Dispatcher access required": "Esta ação requer acesso de despacho.",
  "Administrator access required": "Esta ação requer acesso de administrador.",
  "No unit is assigned to this user for this incident": "Não existe uma unidade associada a este utilizador nesta ocorrência.",
  "Scenario not found": "Ocorrência não encontrada.",
  "Run not found": "Simulação não encontrada.",
  "Unit not found": "Unidade não encontrada.",
  "Vehicle not found": "Viatura não encontrada.",
  "Unit or vehicle not found": "Unidade ou viatura não encontrada.",
  "Movement not found": "Movimento não encontrado.",
  "Road report not found": "Reporte da estrada não encontrado.",
  "Water report not found": "Reporte da fonte de água não encontrado.",
  "Select an existing vehicle": "Selecione uma viatura existente.",
  "Select an existing water source": "Selecione uma fonte de água existente.",
  "Select a segment from the prepared road network": "Selecione um troço da rede viária preparada.",
  "Road report changed; refresh before reviewing": "O reporte mudou. Atualize a página antes de o rever.",
  "Prepare the scenario road area before opening mobility": "Prepare a rede viária da ocorrência antes de abrir a Mobilidade.",
  "This movement is assigned to another unit": "Este movimento está atribuído a outra unidade.",
  "This brief is unavailable or has expired": "Este briefing está indisponível ou expirou.",
  "Invalid username or password": "Utilizador ou palavra-passe incorretos.",
  "Units can be manually marked available or unavailable": "As unidades só podem ser marcadas manualmente como disponíveis ou indisponíveis.",
  "Complete or cancel the active movement before changing availability": "Conclua ou cancele o movimento ativo antes de alterar a disponibilidade.",
  "Unit changed; refresh before updating": "A unidade mudou. Atualize antes de continuar.",
  "Water report changed; refresh before reviewing": "O reporte da fonte de água mudou. Atualize antes de o rever.",
  "Water report was already reviewed": "Este reporte da fonte de água já foi revisto.",
  "Match the report to a prepared road before confirming it": "Identifique o troço preparado antes de confirmar o reporte.",
  "A server-calculated route is required": "Calcule novamente o percurso antes de continuar.",
  "An unavailable route cannot be assigned": "Não é possível atribuir um percurso indisponível.",
  "Acknowledge unresolved route suitability before assignment": "Confirme as limitações desconhecidas antes de atribuir o percurso.",
  "Acknowledge unresolved route suitability before publishing the revision": "Confirme as limitações desconhecidas antes de publicar a revisão.",
  "The unit is unavailable or is not assigned to this vehicle": "A unidade está indisponível ou não está associada a esta viatura.",
  "The unit is unavailable at the planned departure time": "A unidade estará indisponível à hora de partida prevista.",
  "The vehicle changed after the route preview": "A viatura mudou desde o cálculo do percurso. Calcule-o novamente.",
  "Road reports changed after the route preview; calculate the route again": "Os reportes de estrada mudaram. Calcule novamente o percurso.",
  "Unit or vehicle already has an active movement": "A unidade ou a viatura já tem um movimento ativo.",
  "Movement or brief changed; refresh before updating": "O movimento ou briefing mudou. Atualize antes de continuar.",
  "The assigned route needs dispatcher review before departure": "O percurso atribuído exige revisão pelo despacho antes da partida.",
  "The current brief must be acknowledged before the movement can progress": "Confirme o briefing atual antes de avançar.",
  "Only an active movement brief can be acknowledged": "Só é possível confirmar o briefing de um movimento ativo.",
  "Movement changed; refresh before publishing a new route": "O movimento mudou. Atualize antes de publicar outro percurso.",
  "Only an active movement can receive a revised route": "Só um movimento ativo pode receber um percurso revisto.",
  "The assigned unit or vehicle is unavailable": "A unidade ou viatura atribuída está indisponível.",
  "The unit is no longer associated with this vehicle": "A unidade já não está associada a esta viatura.",
  "The vehicle is unavailable": "A viatura está indisponível.",
  "Prepared road data changed; calculate the route again": "Os dados da rede viária preparada mudaram. Calcule novamente o percurso.",
  "Historical exercise scenarios are read-only": "Os cenários históricos são apenas de consulta.",
  "Planning records are archived; use the mobility workspace": "Os registos de planeamento estão no arquivo. Use a área de Mobilidade.",
};

export function apiErrorMessage(detail: unknown, status: number, code?: unknown): string {
  if (code === "ROUTE_PREVIEW_STALE") return "O percurso mudou. Calcule uma nova proposta antes de continuar.";
  if (code === "ROUTE_UNAVAILABLE") return "Não existe um percurso disponível para esta deslocação.";
  if (code === "UNIT_UNAVAILABLE") return "A unidade está indisponível. Confirme a viatura e a atribuição.";
  if (code === "ARCHIVED_ACTION") return "Esta ação foi arquivada. Use a área de Mobilidade.";
  if (typeof detail === "string") {
    if (apiErrors[detail]) return apiErrors[detail];
    if (/^\s*[^\x00-\x7F]/.test(detail) || /\b(ocorrência|percurso|viatura|estrada|utilizador|sessão|unidade|atualize|dados)\b/i.test(detail)) return detail;
    if (/route preview|preview.*stale|route.*changed/i.test(detail)) return "O percurso mudou. Calcule uma nova proposta antes de atribuir.";
    if (/unavailable route|no available route|no route/i.test(detail)) return "Não existe um percurso disponível para esta deslocação.";
    if (/unit.*unavailable|vehicle.*unavailable/i.test(detail)) return "A unidade ou a viatura está indisponível.";
    if (/scenario changed|revision/i.test(detail)) return "A ocorrência foi alterada noutra janela. Atualize antes de continuar.";
  }
  if (status === 401) return "A sessão terminou. Inicie sessão novamente.";
  if (status === 403) return "Não tem permissão para esta ação.";
  if (status === 404) return "O registo pedido não foi encontrado.";
  if (status === 409) return "Os dados mudaram. Atualize e tente novamente.";
  if (status === 410) return "Esta ação foi arquivada. Use a área de Mobilidade.";
  if (status === 422) return "Verifique os dados introduzidos e tente novamente.";
  return "Não foi possível concluir o pedido. Tente novamente.";
}
