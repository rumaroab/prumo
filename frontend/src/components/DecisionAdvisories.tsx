import { Box, Button, Card, Typography } from "./ui";
import { useEffect } from "react";
import { CircleMarker, GeoJSON, useMap } from "react-leaflet";
import L from "leaflet";
import type { DecisionExplanation, MobilityComparison } from "../types";

export type FocusRequest = { feature: GeoJSON.Feature; token: number };
export type FocusDecision = (
  explanation: DecisionExplanation,
  moment?: boolean,
) => void;

export function scenarioClock(
  comparison: Pick<MobilityComparison, "forecast_start_at">,
  minute: number,
  precise = false,
) {
  return new Date(
    new Date(comparison.forecast_start_at).getTime() + minute * 60000,
  ).toLocaleTimeString("pt-PT", {
    hour: "2-digit",
    minute: "2-digit",
    second: precise ? "2-digit" : undefined,
    timeZone: "Europe/Lisbon",
  });
}

const categories = {
  modelled_fire: "Incêndio simulado",
  restriction: "Restrição / exercício",
  missing_data: "Informação em falta",
  resource: "Recurso disponível",
};
const stages: Record<string, string> = {
  filling: "O enchimento terminaria",
  unloading: "A entrega terminaria",
  outbound: "A passagem de ida terminaria",
  inbound: "A passagem de regresso terminaria",
};

export function DecisionAdvisories({
  explanations,
  comparison,
  onFocus,
}: {
  explanations: DecisionExplanation[];
  comparison: MobilityComparison;
  onFocus?: FocusDecision;
}) {
  if (!explanations.length) return null;
  return (
    <Box className="decision-advisories" aria-label="Avisos da decisão">
      {explanations.map((value, index) => {
        let detail = value.message;
        if (value.exposure_min != null && value.event_min != null) {
          const finish = value.vehicle_exit_min;
          detail = `${finish == null ? "O percurso ultrapassa a janela disponível." : `${stages[value.stage || ""] || "A passagem terminaria"} às ${scenarioClock(comparison, finish, true)}.`} Limite às ${scenarioClock(comparison, value.event_min, true)}: exposição modelada às ${scenarioClock(comparison, value.exposure_min, true)}, menos ${value.lead_time_min ?? comparison.lead_time_min} min de antecedência.${value.severity === "info" ? " Foi avaliado um percurso alternativo." : ""}`;
        } else if (value.code === "vehicle_restriction") {
          detail = `${value.unit || comparison.unit.callsign}: ${value.constraint || "restrição de acesso"}${value.actual != null && value.limit != null ? ` ${value.actual} > limite ${value.limit}${value.constraint === "peso" ? " t" : " m"}` : " incompatível com esta viatura"}.${value.exercise_assumption ? " Limite fictício configurado para este exercício." : ""}`;
        } else if (value.code === "proposed_closure")
          detail =
            "O encerramento proposto impede esta etapa da viagem. Consulte o troço e compare com a variante sem proposta.";
        else if (value.code === "recorded_restriction")
          detail =
            "Uma restrição registada impede a passagem desta viatura no troço assinalado.";
        return (
          <Card
            density="compact"
            shadow="none"
            key={`${value.code}-${index}`}
            className={`decision-advisory ${value.severity}`}
          >
            <Typography as="small" variant="small">
              {categories[value.category]}
            </Typography>
            <strong>{value.place}</strong>
            <Typography as="p" variant="body">
              {detail}
            </Typography>
            {onFocus && (
              <Box className="advisory-actions">
                {value.feature && (
                  <Button
                    variant="secondary"
                    type="button"
                    onClick={() => onFocus(value)}
                  >
                    Ver no mapa
                  </Button>
                )}
                {value.event_min != null && (
                  <Button
                    variant="secondary"
                    type="button"
                    onClick={() => onFocus(value, true)}
                  >
                    Ver momento · {scenarioClock(comparison, value.event_min)}
                  </Button>
                )}
              </Box>
            )}
          </Card>
        );
      })}
    </Box>
  );
}

export function DecisionFocusLayer({ focus }: { focus?: FocusRequest }) {
  const map = useMap();
  useEffect(() => {
    if (!focus) return;
    const bounds = L.geoJSON(focus.feature).getBounds();
    if (bounds.isValid())
      map.fitBounds(bounds, { padding: [65, 65], maxZoom: 16, animate: true });
  }, [map, focus]);
  if (!focus) return null;
  const geometry = focus.feature.geometry;
  return geometry.type === "Point" ? (
    <CircleMarker
      key={focus.token}
      center={[geometry.coordinates[1], geometry.coordinates[0]]}
      radius={18}
      pathOptions={{ color: "#fff1a3", weight: 4, fillOpacity: 0.2 }}
    />
  ) : (
    <GeoJSON
      key={focus.token}
      data={focus.feature}
      style={{ color: "#fff1a3", weight: 9, opacity: 0.9, dashArray: "4 5" }}
    />
  );
}
