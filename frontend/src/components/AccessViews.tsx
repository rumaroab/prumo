import { Box, Button, Card, Typography } from "./ui";
import { useEffect } from "react";
import L from "leaflet";
import { CircleMarker, GeoJSON, Popup, useMap } from "react-leaflet";
import type {
  AccessAssessment,
  FeatureCollection,
  MobilityComparison,
  PopulationResult,
  ScenarioPoint,
} from "../types";
import { DecisionAdvisories, scenarioClock } from "./DecisionAdvisories";
import type { FocusDecision } from "./DecisionAdvisories";

export type Perspective = "water" | "access" | "population";
export type ProposalMode = "without" | "with_proposal";

export function comparisonForAssessment(
  value: AccessAssessment,
  mode: ProposalMode,
): MobilityComparison {
  return { ...value.comparison, outcomes: value[mode].water };
}

export function accessStatus(status: string) {
  return status === "clear"
    ? "Percurso viável nas condições simuladas"
    : status === "infeasible"
      ? "Sem percurso viável nas condições simuladas"
      : "Dados insuficientes";
}

export function ImpactSummary({
  assessment,
  mode,
  compact = false,
  onWater,
  onPopulation,
}: {
  assessment: AccessAssessment;
  mode: ProposalMode;
  compact?: boolean;
  onWater: () => void;
  onPopulation: () => void;
}) {
  const water = assessment[mode].water;
  const population = assessment[mode].population;
  const reachable = population.filter(
    (value) => value.status === "clear",
  ).length;
  const lost = assessment.without.population.filter(
    (value, index) =>
      value.status === "clear" &&
      assessment.with_proposal.population[index]?.status === "infeasible",
  ).length;
  const fewer = assessment.without.population.filter(
    (value, index) =>
      assessment.with_proposal.population[index]?.reachable_count <
      value.reachable_count,
  ).length;
  return (
    <Box className={compact ? "access-summary access-summary-compact" : "access-summary"} aria-label="Resumo partilhado">
      <Button variant={compact ? "ghost" : "secondary"} onClick={onWater}>
        <span>Abastecimento</span>
        <strong>
          A{" "}
          {water[0]?.status === "clear"
            ? "viável"
            : water[0]?.status === "unknown"
              ? "dados insuficientes"
              : "inviável"}{" "}
          · B{" "}
          {water[1]?.status === "clear"
            ? "viável"
            : water[1]?.status === "unknown"
              ? "dados insuficientes"
              : "inviável"}
        </strong>
      </Button>
      <Button variant={compact ? "ghost" : "secondary"} onClick={onPopulation}>
        <span>Apoio à população</span>
        <strong>
          {reachable}/{population.length} locais com percurso
          {mode === "with_proposal"
            ? ` · ${fewer} com menos opções${lost ? ` · ${lost} sem percurso` : ""}`
            : compact ? "" : " · sem proposta"}
        </strong>
      </Button>
    </Box>
  );
}

export function AccessResults({
  assessment,
  mode,
  onWater,
  onPopulation,
}: {
  assessment: AccessAssessment;
  mode: ProposalMode;
  onWater: (label: "A" | "B") => void;
  onPopulation: (originId: string) => void;
}) {
  const before = assessment.without.water;
  const after = assessment.with_proposal.water;
  const population = assessment[mode].population;
  const clear = population.filter((value) => value.status === "clear").length;
  const unknown = population.filter(
    (value) => value.status === "unknown",
  ).length;
  const lost = assessment.without.population.filter(
    (value, index) =>
      value.status === "clear" &&
      assessment.with_proposal.population[index]?.status === "infeasible",
  ).length;
  const fewer = assessment.without.population.filter(
    (value, index) =>
      assessment.with_proposal.population[index]?.reachable_count <
      value.reachable_count,
  ).length;
  return (
    <section className="access-results">
      <Typography as="h2" variant="h3">
        Efeito nos acessos
      </Typography>
      {before.map((old, index) => {
        const next = after[index];
        return (
          <Button
            variant="secondary"
            className="access-impact ds-list-action"
            key={old.label}
            onClick={() => onWater(old.label as "A" | "B")}
          >
            <strong>Autotanque · fonte {old.label}</strong>
            <span>Sem proposta: {shortStatus(old.status)}</span>
            <span>Com proposta: {shortStatus(next.status)}</span>
            {old.status === "clear" && next.status === "clear" && (
              <span>
                Entrega: min {old.delivery_min?.toFixed(1)} →{" "}
                {next.delivery_min?.toFixed(1)}
              </span>
            )}
            <Typography as="small" variant="small">
              {next.change_reason ||
                (next.status === "clear"
                  ? `${Math.round(next.delivered_l)} L entregues nas condições simuladas.`
                  : next.reason)}
            </Typography>
          </Button>
        );
      })}
      <Card density="compact" shadow="none" className="access-impact-count">
        <strong>Apoio à população</strong>
        <span>
          {clear} de {population.length} origens com percurso viável
        </span>
        <span>{unknown} com dados insuficientes</span>
        {mode === "with_proposal" && (
          <>
            <span>{fewer} origens com menos pontos de receção acessíveis</span>
            {lost > 0 && (
              <span>{lost} sem qualquer percurso viável avaliado</span>
            )}
          </>
        )}
      </Card>
      {population
        .filter((value, index) =>
          Boolean(assessment.with_proposal.population[index]?.change_reason),
        )
        .map((value) => (
          <Button
            variant="secondary"
            className="access-impact ds-list-action"
            key={value.origin.id}
            onClick={() => onPopulation(value.origin.id)}
          >
            {value.origin.name} → {accessStatus(value.status)}
          </Button>
        ))}
      {assessment.closure_feature && (
        <Typography as="p" variant="small" className="decision-note">
          O troço assinalado é uma proposta de exercício. O incêndio e as
          restrições registadas são os mesmos nas duas variantes.
        </Typography>
      )}
    </section>
  );
}

export function PopulationResults({
  assessment,
  mode,
  originId,
  receptionId,
  onOrigin,
  onReception,
  onFocus,
}: {
  assessment: AccessAssessment;
  mode: ProposalMode;
  originId: string;
  receptionId: string;
  onOrigin: (id: string) => void;
  onReception: (id: string) => void;
  onFocus?: FocusDecision;
}) {
  const rows = [...assessment[mode].population].sort((left, right) => {
    const changed = (value: PopulationResult) =>
      Boolean(
        assessment.with_proposal.population.find(
          (other) => other.origin.id === value.origin.id,
        )?.change_reason,
      );
    const loss = (value: PopulationResult) =>
      (assessment.without.population.find(
        (other) => other.origin.id === value.origin.id,
      )?.reachable_count || 0) -
      (assessment.with_proposal.population.find(
        (other) => other.origin.id === value.origin.id,
      )?.reachable_count || 0);
    return (
      loss(right) - loss(left) ||
      Number(changed(right)) - Number(changed(left)) ||
      left.origin.name.localeCompare(right.origin.name)
    );
  });
  const selected = rows.find((row) => row.origin.id === originId) || rows[0];
  const receptions = new Map(
    assessment.population_points
      .filter((point) => point.population_role === "reception")
      .map((point) => [point.id, point]),
  );
  return (
    <section className="population-results">
      <Typography as="h2" variant="h3">
        Apoio à população
      </Typography>
      <Typography as="p" variant="small" className="decision-note">
        Percurso de cada origem até pontos de receção definidos para este
        exercício. A contagem de pessoas é um dado fornecido, não uma estimativa
        de evacuação.
      </Typography>
      {rows.length === 0 && (
        <Typography as="p" variant="body">
          Defina origens e pontos de receção em Dados e avalie os acessos.
        </Typography>
      )}
      {rows.map((row) => (
        <Button
          variant="secondary"
          key={row.origin.id}
          className={[
            `population-row ${selected?.origin.id === row.origin.id ? "chosen" : ""}`,
            "ds-list-action",
          ]
            .filter(Boolean)
            .join(" ")}
          onClick={() => onOrigin(row.origin.id)}
        >
          <strong>{row.origin.name}</strong>
          <span className={`decision-status ${row.status}`}>
            {accessStatus(row.status)}
          </span>
          <Typography as="small" variant="small">
            {row.reachable_count} pontos de receção com percurso ·{" "}
            {row.origin.population_count == null
              ? "população não indicada"
              : `${row.origin.population_count} pessoas indicadas`}
          </Typography>
        </Button>
      ))}
      {selected && (
        <Card density="compact" shadow="none" className="population-detail">
          <Typography as="h3" variant="h3">
            {selected.origin.name}
          </Typography>
          {mode === "with_proposal" && (
            <>
              <Typography as="p" variant="body">
                {
                  assessment.without.population.find(
                    (row) => row.origin.id === selected.origin.id,
                  )?.reachable_count
                }{" "}
                → {selected.reachable_count} pontos de receção com percurso
                viável.
              </Typography>
              <DecisionAdvisories
                explanations={selected.explanations || []}
                comparison={assessment.comparison}
                onFocus={onFocus}
              />
            </>
          )}
          {selected.options.map((option) => {
            const destination = receptions.get(option.reception_id);
            return (
              <Button
                variant="secondary"
                key={option.reception_id}
                className={[
                  `population-option ${receptionId === option.reception_id || (!receptionId && selected.best_reception_id === option.reception_id) ? "chosen" : ""}`,
                  "ds-list-action",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onClick={() => onReception(option.reception_id)}
              >
                <strong>{destination?.name || option.reception_id}</strong>
                <span>{accessStatus(option.status)}</span>
                {option.status === "clear" ? (
                  <Typography as="small" variant="small">
                    Chegada{" "}
                    {option.arrival_min == null
                      ? "—"
                      : scenarioClock(
                          assessment.comparison,
                          option.arrival_min,
                        )}{" "}
                    · viagem {option.duration_min?.toFixed(1)} min · margem após
                    antecedência{" "}
                    {option.minimum_forecast_margin_min == null
                      ? "não atingida no horizonte"
                      : `${option.minimum_forecast_margin_min.toFixed(1)} min`}
                  </Typography>
                ) : (
                  <Typography as="small" variant="small">
                    {option.reason}
                  </Typography>
                )}
              </Button>
            );
          })}
          {(() => {
            const option =
              selected.options.find(
                (value) =>
                  value.reception_id ===
                  (receptionId || selected.best_reception_id),
              ) || selected.options[0];
            return (
              option && (
                <DecisionAdvisories
                  explanations={option.explanations || []}
                  comparison={assessment.comparison}
                  onFocus={onFocus}
                />
              )
            );
          })()}
          <Typography as="p" variant="small" className="decision-note">
            O percurso avalia acesso rodoviário à entrada. Não confirma
            capacidade nem permanência segura no edifício.
          </Typography>
        </Card>
      )}
    </section>
  );
}

export function AccessMapLayers({
  assessment,
  mode,
  perspective,
  roads,
  selectedSectionId,
  selectedOriginId,
  selectedReceptionId,
  minute,
  onRoad,
  pointsOverride,
}: {
  assessment?: AccessAssessment;
  mode: ProposalMode;
  perspective: Perspective;
  roads?: FeatureCollection;
  selectedSectionId?: string;
  selectedOriginId?: string;
  selectedReceptionId?: string;
  minute: number;
  onRoad?: (id: string) => void;
  pointsOverride?: ScenarioPoint[];
}) {
  const points = assessment?.population_points || pointsOverride || [];
  const selected =
    assessment?.[mode].population.find(
      (row) => row.origin.id === selectedOriginId,
    ) || assessment?.[mode].population[0];
  const option =
    selected?.options.find(
      (item) => item.reception_id === selectedReceptionId,
    ) ||
    selected?.options.find(
      (item) => item.reception_id === selected.best_reception_id,
    ) ||
    selected?.options[0];
  const map = useMap();
  useEffect(() => {
    if (perspective !== "population" || !option?.route?.feature) return;
    const bounds = L.geoJSON(option.route.feature).getBounds();
    if (bounds.isValid())
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
  }, [map, perspective, option?.route?.feature]);
  return (
    <>
      {perspective === "access" &&
        roads?.features.map((feature, index) => {
          const props = feature.properties || {};
          const id = String(props.section_id || "");
          const exposure =
            typeof props.first_exposure_min === "number"
              ? props.first_exposure_min
              : null;
          const reports = Array.isArray(props.reports) ? props.reports : [];
          const recorded = reports.some(
            (report: { kind?: string; status?: string }) =>
              report.status === "confirmed" &&
              ["blocked", "restricted"].includes(report.kind || ""),
          );
          return (
            <GeoJSON
              key={`access-${assessment?.road_revision || "draft"}-${id || index}`}
              data={feature}
              style={{
                color:
                  id === selectedSectionId
                    ? "#f5c970"
                    : recorded
                      ? "#e07666"
                      : props.coverage_unknown
                        ? "#c7a758"
                        : exposure != null && exposure <= minute
                          ? "#f07859"
                          : "#65aec1",
                weight: id === selectedSectionId ? 8 : 4,
                opacity: 0.85,
                dashArray: recorded ? "5 4" : undefined,
              }}
              eventHandlers={onRoad ? { click: () => onRoad(id) } : undefined}
            >
              <Popup>
                {String(props.road_name || "Troço")} ·{" "}
                {exposure == null
                  ? "sem exposição modelada neste horizonte"
                  : `exposição desde min ${exposure.toFixed(1)}`}
              </Popup>
            </GeoJSON>
          );
        })}
      {assessment?.closure_feature && (
        <GeoJSON
          key={`proposal-${assessment.id}-${mode}`}
          data={assessment.closure_feature}
          style={{
            color: "#f5c970",
            weight: mode === "with_proposal" ? 10 : 5,
            opacity: mode === "with_proposal" ? 0.9 : 0.5,
            dashArray: "7 5",
          }}
        />
      )}
      {perspective === "population" && option?.route?.feature && (
        <GeoJSON
          key={`pop-route-${assessment?.id}-${mode}-${selected?.origin.id}-${option.reception_id}`}
          data={option.route.feature}
          style={{ color: "#8fe4bd", weight: 7, opacity: 0.9 }}
        />
      )}
      {perspective !== "water" &&
        points.map((point: ScenarioPoint) => (
          <CircleMarker
            key={point.id}
            center={[point.coordinates[1], point.coordinates[0]]}
            radius={point.id === selected?.origin.id ? 10 : 7}
            pathOptions={{
              color: point.population_role === "origin" ? "#f6d48e" : "#8fe4bd",
              fillColor:
                point.population_role === "origin" ? "#f6d48e" : "#8fe4bd",
              fillOpacity: 0.95,
            }}
          >
            <Popup>
              {point.name} ·{" "}
              {point.population_role === "origin" ? "origem" : "receção"} ·
              dados de exercício
            </Popup>
          </CircleMarker>
        ))}
    </>
  );
}

function shortStatus(value: string) {
  return value === "clear"
    ? "viável"
    : value === "unknown"
      ? "dados insuficientes"
      : "inviável";
}
