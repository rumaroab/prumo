import { Box, Button, Card, Typography } from "./ui";
import type { ComparisonOutcome, MobilityComparison } from "../types";
import { DecisionAdvisories, scenarioClock } from "./DecisionAdvisories";
import type { FocusDecision } from "./DecisionAdvisories";

function outcomeExplanations(
  outcome: ComparisonOutcome,
  comparison: MobilityComparison,
) {
  const values =
    outcome.explanations?.map((value) => {
      if (value.code !== "small_margin") return value;
      const stage = outcome.stages
        .filter((stage) => stage.route?.minimum_forecast_margin_min != null)
        .sort(
          (a, b) =>
            a.route!.minimum_forecast_margin_min! -
            b.route!.minimum_forecast_margin_min!,
        )[0];
      return stage &&
        Math.abs(
          stage.route!.minimum_forecast_margin_min! - (value.margin_min || 0),
        ) < 0.02
        ? {
            ...value,
            feature: stage.route!.feature,
            event_min: stage.start_min,
            place:
              stage.kind === "inbound"
                ? "Regresso ao setor"
                : "Percurso de ida",
          }
        : value;
    }) || [];
  if (outcome.status === "clear")
    for (const stage of outcome.stages) {
      const conflict = stage.conflict;
      if (
        conflict?.reason !== "fire_exposure" ||
        conflict.exposure_min == null ||
        values.some(
          (value) =>
            value.code === "fire_exposure" && value.stage === stage.kind,
        )
      )
        continue;
      values.unshift({
        code: "fire_exposure",
        category: "modelled_fire",
        severity: "info",
        stage: stage.kind,
        place: conflict.road_name || "Percurso normal",
        message:
          "Foi avaliado um desvio devido à exposição no percurso normal.",
        feature: conflict.feature,
        event_min: conflict.exposure_min - comparison.lead_time_min,
        exposure_min: conflict.exposure_min,
        vehicle_exit_min: conflict.vehicle_exit_min,
        lead_time_min: comparison.lead_time_min,
      });
    }
  return values;
}

export function DecisionResults({
  comparison,
  active,
  onActive,
  onFocus,
}: {
  comparison: MobilityComparison;
  active: "A" | "B" | "both";
  onActive: (value: "A" | "B" | "both") => void;
  onFocus?: FocusDecision;
}) {
  return (
    <section className="decision-results" aria-label="Resultados da comparação">
      <Box className="decision-results-heading">
        <Typography as="h2" variant="h3">
          Resultado
        </Typography>
        <Button
          variant="secondary"
          aria-pressed={active === "both"}
          type="button"
          className={active === "both" ? "chosen" : ""}
          onClick={() => onActive("both")}
        >
          Mostrar ambos
        </Button>
      </Box>
      <Typography as="p" variant="small" className="decision-note">
        {comparison.unit.callsign} · pedido{" "}
        {comparison.requested_l.toLocaleString("pt-PT")} L · partida{" "}
        {scenarioClock(comparison, comparison.departure_min)}
      </Typography>
      {comparison.outcomes.map((outcome) => (
        <Card
          as="article"
          density="compact"
          shadow="none"
          key={outcome.label}
          className={`decision-card ${active === outcome.label ? "chosen" : ""}`}
        >
          <Button
            aria-pressed={active === outcome.label}
            variant="ghost"
            type="button"
            className="decision-card-title"
            onClick={() => onActive(outcome.label as "A" | "B")}
          >
            <b
              className={`decision-letter decision-${outcome.label.toLowerCase()}`}
            >
              {outcome.label}
            </b>
            <strong>{outcome.source.name}</strong>
          </Button>
          <span className={`decision-status ${outcome.status}`}>
            {status(outcome.status)}
          </span>
          <span className="decision-metrics">
            <span>
              Viagem normal
              <strong>
                {outcome.baseline_duration_min == null
                  ? "—"
                  : `${outcome.baseline_duration_min.toFixed(1)} min`}
              </strong>
            </span>
            <span>
              Água entregue
              <strong>
                {Math.round(outcome.delivered_l).toLocaleString("pt-PT")} L
              </strong>
            </span>
            <span>
              Entrega
              <strong>
                {outcome.delivery_min == null
                  ? "—"
                  : scenarioClock(comparison, outcome.delivery_min)}
              </strong>
            </span>
          </span>
          <span className="decision-margin">
            Margem após antecedência:{" "}
            {outcome.minimum_forecast_margin_min == null
              ? "—"
              : `${outcome.minimum_forecast_margin_min.toFixed(1)} min`}
          </span>
          {outcome.status === "clear" && (
            <span className="decision-reason">{outcome.reason}</span>
          )}
          {!outcome.explanations?.length && outcome.conflict && (
            <span className="decision-conflict">
              Conflito: {explainConflict(outcome)}
            </span>
          )}
          <DecisionAdvisories
            explanations={
              outcome.explanations?.length || outcome.status === "clear"
                ? outcomeExplanations(outcome, comparison)
                : [
                    {
                      code: "legacy",
                      category:
                        outcome.status === "unknown"
                          ? "missing_data"
                          : "resource",
                      severity: outcome.status,
                      place: outcome.source.name,
                      message: outcome.reason,
                      feature: outcome.conflict?.feature || {
                        type: "Feature",
                        properties: {},
                        geometry: {
                          type: "Point",
                          coordinates: outcome.source.coordinates,
                        },
                      },
                    },
                  ]
            }
            comparison={comparison}
            onFocus={
              onFocus
                ? (value, moment) => {
                    onActive(outcome.label as "A" | "B");
                    onFocus(value, moment);
                  }
                : undefined
            }
          />
          <span className="decision-assumptions">
            Fonte:{" "}
            {outcome.assumptions.flow_l_min ??
              outcome.source.water?.shared_flow_l_min ??
              "?"}{" "}
            L/min · stock assumido:{" "}
            {outcome.assumptions.available_volume_l == null
              ? "não confirmado"
              : `${outcome.assumptions.available_volume_l} L`}{" "}
            · preparação:{" "}
            {outcome.assumptions.setup_time_min ??
              outcome.source.water?.setup_time_min ??
              "?"}{" "}
            min
          </span>
        </Card>
      ))}
      <Typography as="p" variant="small" className="decision-note">
        Tempos e exposição são estimativas do cenário. Ausência de conflito
        modelado não certifica segurança.
      </Typography>
    </section>
  );
}

export function status(value: ComparisonOutcome["status"]) {
  return value === "clear"
    ? "Viável nas condições simuladas"
    : value === "infeasible"
      ? "Inviável"
      : "Dados insuficientes";
}
export function movingPosition(
  stages: ComparisonOutcome["stages"],
  minute: number,
  origin: [number, number],
): [number, number] {
  let previous = origin;
  for (const stage of stages) {
    if (stage.coordinates) {
      if (minute >= stage.start_min && minute <= stage.end_min)
        return stage.coordinates;
      if (minute > stage.end_min) previous = stage.coordinates;
      continue;
    }
    const timed = stage.route?.trajectory || [];
    if (timed.length) {
      if (minute < stage.start_min) return previous;
      if (minute <= stage.end_min) {
        const nextIndex = timed.findIndex((value) => value.minute >= minute);
        if (nextIndex <= 0) return timed[0].coordinates;
        const before = timed[nextIndex - 1],
          after = timed[nextIndex];
        if (!after) return timed[timed.length - 1].coordinates;
        const fraction =
          (minute - before.minute) /
          Math.max(0.0001, after.minute - before.minute);
        return [
          before.coordinates[0] +
            (after.coordinates[0] - before.coordinates[0]) * fraction,
          before.coordinates[1] +
            (after.coordinates[1] - before.coordinates[1]) * fraction,
        ];
      }
      previous = timed[timed.length - 1].coordinates;
      continue;
    }
    const coordinates =
      stage.route?.feature.geometry?.type === "LineString"
        ? (stage.route.feature.geometry.coordinates as [number, number][])
        : [];
    if (!coordinates.length) continue;
    if (minute < stage.start_min) return previous;
    if (minute <= stage.end_min) {
      const position = Math.min(
        coordinates.length - 1,
        Math.floor(
          ((minute - stage.start_min) /
            Math.max(0.001, stage.end_min - stage.start_min)) *
            (coordinates.length - 1),
        ),
      );
      return coordinates[position];
    }
    previous = coordinates[coordinates.length - 1];
  }
  return previous;
}
export function TimelineEvents({
  comparison,
}: {
  comparison: MobilityComparison;
}) {
  return (
    <Box className="decision-events">
      {comparison.outcomes.map((outcome) => (
        <Box key={outcome.label}>
          <b>{outcome.label}</b>
          {outcome.stages.map((stage, index) => (
            <span key={`${stage.kind}-${index}`}>
              {stageName(stage.kind)} ·{" "}
              {scenarioClock(comparison, stage.start_min)}
              {stage.end_min > stage.start_min
                ? ` → ${scenarioClock(comparison, stage.end_min)}${stage.kind === "outbound" ? " (fonte)" : ""}`
                : ""}
            </span>
          ))}
        </Box>
      ))}
    </Box>
  );
}
function stageName(kind: string) {
  return (
    (
      {
        outbound: "Partida",
        filling: "Enchimento",
        inbound: "Regresso",
        unloading: "Entrega",
      } as Record<string, string>
    )[kind] || kind
  );
}
function explainConflict(outcome: ComparisonOutcome) {
  const conflict = outcome.conflict;
  if (!conflict) return "";
  const where =
    conflict.reason === "source_exposure"
      ? "fonte de água"
      : conflict.reason === "destination_exposure"
        ? "setor"
        : conflict.road_name || "troço assinalado no mapa";
  const timing =
    conflict.exposure_min == null
      ? ""
      : ` · exposição no min ${conflict.exposure_min.toFixed(1)}`;
  return `${where}${timing}${outcome.status === "unknown" ? " · percurso alternativo por confirmar" : ""}`;
}
