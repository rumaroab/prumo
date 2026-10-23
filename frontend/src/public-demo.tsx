import { PrumoBrand } from "./components/PrumoBrand";
import {
  Box,
  Button,
  Card,
  SectionContainer,
  Typography,
} from "./components/ui";
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./leaflet-locale";
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Popup,
  TileLayer,
} from "react-leaflet";
import type {
  AccessAssessment,
  FeatureCollection,
  MobilityComparison,
  PopulationResult,
  ScenarioPoint,
  VehicleProfile,
} from "./types";
import {
  DecisionResults,
  TimelineEvents,
  movingPosition,
} from "./components/DecisionResults";
import {
  DecisionFocusLayer,
  scenarioClock,
} from "./components/DecisionAdvisories";
import type {
  FocusDecision,
  FocusRequest,
} from "./components/DecisionAdvisories";
import {
  AccessMapLayers,
  AccessResults,
  ImpactSummary,
  PopulationResults,
  comparisonForAssessment,
} from "./components/AccessViews";
import type { Perspective, ProposalMode } from "./components/AccessViews";
import "leaflet/dist/leaflet.css";
import "./components/decision.css";
import "./components/public-demo.css";
import "./design-tokens.css";

type Variant = "base" | "delay";
type ScenarioKey = "cell2fire" | "mtt";
type PublicAssessment = Pick<
  AccessAssessment,
  | "id"
  | "scenario_id"
  | "created_at"
  | "comparison_id"
  | "road_revision"
  | "section_id"
  | "closure_feature"
  | "summary"
> & { with_water: MobilityComparison["outcomes"] };
type ScenarioExample = {
  label: string;
  title: string;
  departures: [number, number];
  weather: {
    wind_speed_kmh: number;
    wind_direction_deg: number;
    moisture: string;
    duration_min: number;
  };
  ignitions: {
    id: string;
    name: string;
    coordinates: [number, number];
    start_min: number;
  }[];
  points: ScenarioPoint[];
  comparisons: Record<string, MobilityComparison>;
  assessments: Record<string, PublicAssessment>;
  population: Record<Variant, Record<ProposalMode, PopulationResult[]>>;
  population_vehicle: VehicleProfile;
  fire_frames: Record<string, FeatureCollection>;
};
type Bundle = {
  schema_version: number;
  title: string;
  description: string;
  default_scenario: ScenarioKey;
  scenarios: Record<ScenarioKey, ScenarioExample>;
  roads: FeatureCollection;
  road_provenance: { fetched_at?: string; revision: string; source: string };
};
const PAIRS = ["01", "02", "03", "12", "13", "23"];

function PublicDemo() {
  const [bundle, setBundle] = useState<Bundle>();
  const [scenarioKey, setScenarioKey] = useState<ScenarioKey>("cell2fire");
  const [unitKey, setUnitKey] = useState("05");
  const [pair, setPair] = useState("01");
  const [error, setError] = useState("");
  const [variant, setVariant] = useState<Variant>("base");
  const [perspective, setPerspective] = useState<Perspective>("water");
  const [mode, setMode] = useState<ProposalMode>("without");
  const [active, setActive] = useState<"A" | "B" | "both">("both");
  const [originId, setOriginId] = useState("demo-origin-north");
  const [receptionId, setReceptionId] = useState("");
  const [minute, setMinute] = useState(15);
  const [playing, setPlaying] = useState(false);
  const [basemap, setBasemap] = useState(true);
  const [focus, setFocus] = useState<FocusRequest>();
  useEffect(() => {
    fetch("./demo.json")
      .then((response) => {
        if (!response.ok) throw new Error("Dados indisponíveis");
        return response.json();
      })
      .then((data: Bundle) => {
        if (data.schema_version !== 2)
          throw new Error("Atualize a página para carregar este exercício.");
        setBundle(data);
        setMinute(data.scenarios.cell2fire.departures[0]);
      })
      .catch((reason) => setError(String(reason)));
  }, []);
  useEffect(() => {
    if (!playing || !bundle) return;
    const timer = window.setInterval(
      () => setMinute((value) => (value >= 240 ? 0 : Math.min(240, value + 5))),
      850,
    );
    return () => window.clearInterval(timer);
  }, [playing, bundle]);
  const focusDecision: FocusDecision = (value, moment) => {
    if (value.feature) setFocus({ feature: value.feature, token: Date.now() });
    if (moment && value.event_min != null) {
      setMinute(Math.max(0, Math.floor(value.event_min)));
      setPlaying(false);
    }
  };
  function resetFocus() {
    setFocus(undefined);
    setActive("both");
    setPlaying(false);
  }
  if (error)
    return <main className="decision-shell decision-setup">{error}</main>;
  if (!bundle)
    return (
      <main className="decision-shell decision-setup">
        A carregar exercícios calculados…
      </main>
    );

  const example = bundle.scenarios[scenarioKey];
  const lookup = `${unitKey}|${pair}|${variant}`;
  const original = example.comparisons[lookup];
  const stored = example.assessments[lookup];
  const assessment: AccessAssessment = {
    ...stored,
    comparison: original,
    population_points: example.points.filter((point) => point.population_role),
    population_vehicle: example.population_vehicle,
    without: {
      water: original.outcomes,
      population: example.population[variant].without,
    },
    with_proposal: {
      water: stored.with_water,
      population: example.population[variant].with_proposal,
    },
  };
  const comparison = comparisonForAssessment(assessment, mode);
  const frameMinute = Math.max(
    ...Object.keys(example.fire_frames)
      .map(Number)
      .filter((value) => value <= minute),
  );
  const frame = example.fire_frames[String(frameMinute)];
  const sources = example.points.filter(
    (point) => point.kind === "water_point",
  );
  const vehicle = comparison.unit.vehicle;
  const introduction =
    perspective === "water"
      ? [
          "Qual fonte permite completar a viagem?",
          "Escolha uma viatura e duas fontes. A partida, o volume e o incêndio são iguais nas duas alternativas.",
        ]
      : perspective === "access"
        ? [
            "O que muda com este encerramento?",
            "Inspecione o efeito do mesmo troço sobre a viagem de água e os acessos aos pontos de receção.",
          ]
        : [
            "Que opções de acesso ficam disponíveis?",
            "Quatro origens e dois pontos de receção partilham o mesmo incêndio, hora de partida e proposta.",
          ];
  return (
    <main className="decision-shell public-decision">
      <header className="decision-header">
        <Box>
          <Typography as="h1" variant="h3">
            <PrumoBrand />
          </Typography>
          <span>Apoio a decisões de mobilidade</span>
        </Box>
        <span>Exercício público · dados operacionais fictícios</span>
      </header>
      <SectionContainer
        as="section"
        containerClassName="ds-stack"
        className="public-intro"
      >
        <Typography as="span" variant="label">
          Dois exercícios · 72 comparações calculadas
        </Typography>
        <Typography as="h2" variant="h2">
          {introduction[0]}
        </Typography>
        <Typography as="p" variant="body">
          {introduction[1]}
        </Typography>
        <Box className="public-choice" aria-label="Escolher exercício">
          {(["cell2fire", "mtt"] as ScenarioKey[]).map((key) => (
            <Button
              variant="secondary"
              aria-pressed={scenarioKey === key}
              key={key}
              className={scenarioKey === key ? "active" : ""}
              onClick={() => {
                setScenarioKey(key);
                setVariant("base");
                setMinute(bundle.scenarios[key].departures[0]);
                setMode("without");
                setUnitKey("05");
                setPair("01");
                setOriginId("demo-origin-north");
                setReceptionId("");
                resetFocus();
              }}
            >
              {bundle.scenarios[key].label}
            </Button>
          ))}
        </Box>
        <Card density="compact" shadow="none" className="public-scenario-story">
          <strong>{example.title}</strong>
          <span>
            {example.weather.wind_speed_kmh} km/h · direção{" "}
            {example.weather.wind_direction_deg}° · humidade{" "}
            {example.weather.moisture} · horizonte de 4 horas ·{" "}
            {example.ignitions.length}{" "}
            {example.ignitions.length === 1 ? "ignição" : "ignições"}
          </span>
          <Typography as="p" variant="body">
            {scenarioKey === "cell2fire"
              ? "A proximidade pode esconder um enchimento demorado. Avalie também o regresso e a entrega."
              : "Uma segunda ignição é introduzida no minuto 25. Uma restrição de acesso pode mudar as opções de várias entidades."}
          </Typography>
        </Card>
        <Box className="public-controls">
          <label>
            Viatura avaliada
            <select
              aria-label="Viatura avaliada"
              value={unitKey}
              onChange={(event) => {
                setUnitKey(event.target.value);
                resetFocus();
              }}
            >
              {["03", "05", "10"].map((key) => {
                const unit = example.comparisons[`${key}|01|base`].unit;
                return (
                  <option key={key} value={key}>
                    {unit.callsign} · {unit.vehicle.name} ·{" "}
                    {unit.vehicle.water_tank_capacity_l?.toLocaleString(
                      "pt-PT",
                    )}{" "}
                    L
                  </option>
                );
              })}
            </select>
          </label>
          <label>
            Fontes a comparar
            <select
              aria-label="Fontes a comparar"
              value={pair}
              onChange={(event) => {
                setPair(event.target.value);
                resetFocus();
              }}
            >
              {PAIRS.map((value) => (
                <option key={value} value={value}>
                  {sources[Number(value[0])].name} ↔{" "}
                  {sources[Number(value[1])].name}
                </option>
              ))}
            </select>
          </label>
          <Box className="public-choice">
            <Button
              variant="secondary"
              aria-pressed={variant === "base"}
              className={variant === "base" ? "active" : ""}
              onClick={() => {
                setVariant("base");
                setMinute(example.departures[0]);
                resetFocus();
              }}
            >
              Partida às {scenarioClock(original, example.departures[0])}
            </Button>
            <Button
              variant="secondary"
              aria-pressed={variant === "delay"}
              className={variant === "delay" ? "active" : ""}
              onClick={() => {
                setVariant("delay");
                setMinute(example.departures[1]);
                resetFocus();
              }}
            >
              Atrasar 10 minutos
            </Button>
          </Box>
        </Box>
        <Typography as="p" variant="small" className="public-engine-note">
          Pedido comum: <b>3 000 L</b> · bomba: {vehicle.pump_flow_l_min} L/min
          · {vehicle.width_m} m de largura · {vehicle.weight_t} t ·{" "}
          {vehicle.off_road
            ? "admite piso não pavimentado"
            : "perfil rodoviário"}
          . Cada seleção avalia uma viatura individualmente.
        </Typography>
      </SectionContainer>
      <Box
        className="decision-perspectives"
        aria-label="Perspetivas da decisão"
      >
        {(
          [
            ["water", "Abastecimento"],
            ["access", "Acessos"],
            ["population", "Apoio à população"],
          ] as [Perspective, string][]
        ).map(([value, label]) => (
          <Button
            variant="secondary"
            aria-pressed={perspective === value}
            key={value}
            className={perspective === value ? "active" : ""}
            onClick={() => setPerspective(value)}
          >
            {label}
          </Button>
        ))}
        <Box className="decision-variants">
          <Button
            variant="secondary"
            aria-pressed={mode === "without"}
            className={mode === "without" ? "active" : ""}
            onClick={() => {
              setMode("without");
              setFocus(undefined);
            }}
          >
            Sem proposta
          </Button>
          <Button
            variant="secondary"
            aria-pressed={mode === "with_proposal"}
            className={mode === "with_proposal" ? "active" : ""}
            onClick={() => {
              setMode("with_proposal");
              setFocus(undefined);
            }}
          >
            Com encerramento proposto
          </Button>
        </Box>
      </Box>
      <ImpactSummary
        assessment={assessment}
        mode={mode}
        onWater={() => setPerspective("water")}
        onPopulation={() => setPerspective("population")}
      />
      <Box className="public-layout">
        <Box className="decision-map-panel">
          <Box className="decision-map">
            <MapContainer
              center={[41.423, -8.289]}
              zoom={14}
              className="decision-leaflet"
            >
              {basemap && (
                <TileLayer
                  attribution="&copy; OpenStreetMap contributors"
                  url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
              )}
              <GeoJSON
                data={bundle.roads}
                style={{ color: "#637c88", weight: 2, opacity: 0.65 }}
              />
              {frame && (
                <GeoJSON
                  key={`fire-${scenarioKey}-${frameMinute}`}
                  data={frame}
                  style={{
                    color: "#f1793d",
                    fillColor: "#f1793d",
                    fillOpacity: 0.4,
                    weight: 1,
                  }}
                />
              )}
              {example.ignitions.map((ignition) => (
                <CircleMarker
                  key={`ignition-${scenarioKey}-${ignition.id}`}
                  center={[ignition.coordinates[1], ignition.coordinates[0]]}
                  radius={6}
                  pathOptions={{
                    color: "#ffb19a",
                    weight: 3,
                    fillOpacity: minute >= ignition.start_min ? 1 : 0,
                  }}
                >
                  <Popup>
                    {ignition.name} ·{" "}
                    {scenarioClock(comparison, ignition.start_min)} ·{" "}
                    {minute < ignition.start_min
                      ? "ainda não iniciada"
                      : "iniciada no cenário"}
                  </Popup>
                </CircleMarker>
              ))}
              {perspective !== "population" &&
                example.points
                  .filter(
                    (point) =>
                      point.kind === "water_point" ||
                      point.kind === "delivery_point",
                  )
                  .map((point) => (
                    <CircleMarker
                      key={`${scenarioKey}-${point.id}`}
                      center={[point.coordinates[1], point.coordinates[0]]}
                      radius={point.kind === "delivery_point" ? 9 : 7}
                      pathOptions={{
                        color:
                          point.kind === "delivery_point"
                            ? "#f2ca68"
                            : "#3a9ec3",
                        fillOpacity: 1,
                      }}
                    >
                      <Popup>
                        {point.name}
                        {point.water && (
                          <>
                            <br />
                            {point.water.shared_flow_l_min == null
                              ? "Caudal em falta"
                              : `${point.water.shared_flow_l_min} L/min`}{" "}
                            · {point.water.available_volume_l} L de exercício
                          </>
                        )}
                      </Popup>
                    </CircleMarker>
                  ))}
              {perspective !== "population" &&
                comparison.outcomes
                  .filter(
                    (value) => active === "both" || value.label === active,
                  )
                  .flatMap((value) =>
                    value.stages
                      .filter((stage) => stage.route?.feature)
                      .map((stage) => (
                        <GeoJSON
                          key={`${comparison.id}-${mode}-${value.label}-${stage.kind}`}
                          data={stage.route!.feature}
                          style={{
                            color: value.label === "A" ? "#38bdf8" : "#b68cff",
                            weight: active === value.label ? 7 : 5,
                            opacity: 0.9,
                          }}
                        />
                      )),
                  )}
              {perspective !== "population" &&
                comparison.outcomes
                  .filter(
                    (value) =>
                      (active === "both" || value.label === active) &&
                      value.status !== "clear" &&
                      value.baseline_feature,
                  )
                  .map((value) => (
                    <GeoJSON
                      key={`baseline-${comparison.id}-${mode}-${value.label}`}
                      data={value.baseline_feature!}
                      style={{
                        color: "#f9b84e",
                        weight: 3,
                        dashArray: "6 5",
                        opacity: 0.8,
                      }}
                    />
                  ))}
              {perspective !== "population" &&
                comparison.outcomes
                  .filter(
                    (value) => active === "both" || value.label === active,
                  )
                  .map((value) => {
                    const point = movingPosition(
                      value.stages,
                      minute,
                      comparison.unit.coordinates,
                    );
                    return (
                      <CircleMarker
                        key={`${comparison.id}-${value.label}`}
                        center={[point[1], point[0]]}
                        radius={8}
                        pathOptions={{
                          color: "#fff",
                          fillColor:
                            value.label === "A" ? "#38bdf8" : "#b68cff",
                          fillOpacity: 1,
                          weight: 2,
                        }}
                      >
                        <Popup>
                          {comparison.unit.callsign} · posição simulada da
                          alternativa {value.label}
                        </Popup>
                      </CircleMarker>
                    );
                  })}
              <AccessMapLayers
                assessment={assessment}
                mode={mode}
                perspective={perspective}
                selectedSectionId={assessment.section_id || ""}
                selectedOriginId={originId}
                selectedReceptionId={receptionId}
                minute={minute}
              />
              <DecisionFocusLayer focus={focus} />
            </MapContainer>
          </Box>
          <Box className="decision-timeline">
            <Button variant="secondary" onClick={() => setPlaying(!playing)}>
              {playing ? "Pausar" : "Reproduzir"}
            </Button>
            <strong>{scenarioClock(comparison, minute)}</strong>
            <input
              aria-label="Minuto do incêndio"
              type="range"
              min="0"
              max="240"
              step="1"
              value={minute}
              onChange={(event) => {
                setMinute(Number(event.target.value));
                setPlaying(false);
              }}
            />
            <span>min {minute}/240</span>
          </Box>
          {perspective !== "population" && (
            <TimelineEvents comparison={comparison} />
          )}
          <Typography as="p" variant="small" className="decision-map-caption">
            <label className="basemap-switch">
              <input
                type="checkbox"
                checked={basemap}
                onChange={(event) => setBasemap(event.target.checked)}
              />{" "}
              Mapa base
            </label>
            Incêndio às {scenarioClock(comparison, frameMinute)} · posições
            simuladas A/B. Amarelo tracejado: percurso normal para diagnóstico.
            Dourado: encerramento hipotético.
          </Typography>
        </Box>
        <Card
          as="aside"
          density="compact"
          shadow="none"
          className="decision-output"
        >
          {perspective === "water" && (
            <>
              <Typography as="p" variant="small" className="decision-note">
                {mode === "without"
                  ? "Viagens completas sem proposta de encerramento."
                  : "Viagens recalculadas com o encerramento proposto."}
              </Typography>
              <DecisionResults
                comparison={comparison}
                active={active}
                onActive={setActive}
                onFocus={focusDecision}
              />
            </>
          )}
          {perspective === "access" && (
            <>
              <Card density="compact" shadow="none" className="selected-road">
                <Typography as="h3" variant="h3">
                  {String(
                    assessment.closure_feature?.properties?.road_name ||
                      "Troço proposto",
                  )}
                </Typography>
                <Typography as="p" variant="body">
                  Encerramento fictício nos dois sentidos, para todas as
                  viaturas avaliadas, desde a partida até ao fim da simulação.
                </Typography>
                <Button
                  variant="primary"
                  className="ds-full"
                  onClick={() => {
                    if (assessment.closure_feature)
                      focusDecision({
                        code: "closure",
                        category: "restriction",
                        severity: "info",
                        place: "Troço proposto",
                        message: "",
                        feature: assessment.closure_feature,
                      });
                  }}
                >
                  Ver troço no mapa
                </Button>
              </Card>
              <AccessResults
                assessment={assessment}
                mode={mode}
                onWater={(label) => {
                  setPerspective("water");
                  setActive(label);
                }}
                onPopulation={(id) => {
                  setPerspective("population");
                  setOriginId(id);
                  setReceptionId("");
                }}
              />
            </>
          )}
          {perspective === "population" && (
            <PopulationResults
              assessment={assessment}
              mode={mode}
              originId={originId}
              receptionId={receptionId}
              onOrigin={(id) => {
                setOriginId(id);
                setReceptionId("");
              }}
              onReception={setReceptionId}
              onFocus={focusDecision}
            />
          )}
          <details className="decision-provenance">
            <summary>Dados e pressupostos</summary>
            <Typography as="p" variant="body">
              {example.label} · vento constante. A segunda ignição do MTT é um
              pressuposto configurado. Os exercícios não comparam a precisão dos
              motores.
            </Typography>
            <Typography as="p" variant="body">
              Relevo, combustíveis, locais e viaturas são fictícios. Geometria
              rodoviária: OpenStreetMap, recolhida em{" "}
              {bundle.road_provenance.fetched_at
                ? new Date(
                    bundle.road_provenance.fetched_at,
                  ).toLocaleDateString("pt-PT")
                : "data indicada no pacote"}
              .
            </Typography>
            <Typography as="p" variant="body">
              Os limites de gabarito e peso do corredor são pressupostos
              versionados de exercício; o acesso à Reserva do vale tem limite de
              12 t e 2,3 m.
            </Typography>
            <Typography as="p" variant="body">
              Margens já descontam {comparison.lead_time_min} min de
              antecedência. Cada comparação é independente: não há filas nem
              consumo partilhado de água.
            </Typography>
          </details>
        </Card>
      </Box>
      <SectionContainer
        as="footer"
        containerClassName="ds-stack"
        className="public-footer"
      >
        Reprodução interativa de resultados calculados. Introdução de dados
        próprios e novas avaliações disponíveis na aplicação supervisionada.
      </SectionContainer>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PublicDemo />
  </StrictMode>,
);
