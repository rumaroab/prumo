import { Box, Button, Card, Typography } from "./ui";
import { engineAvailabilityText, t } from "../locale";
import type { Engine, Filter, Scenario, WeatherSeries } from "../types";

type Props = {
  setupMode?: boolean;
  headingLevel?: "h1" | "h2";
  draft: Scenario;
  engines: Engine[];
  scenarioName: string;
  description: string;
  startTime?: string | null;
  filter: Filter;
  showFire: boolean;
  showRoads: boolean;
  showBasemap: boolean;
  placing: boolean;
  placingIgnitionId?: string;
  pending: boolean;
  weatherSeries: WeatherSeries[];
  onDraft: (value: Scenario) => void;
  onScenarioMeta: (value: {
    name: string;
    description: string;
    startTime?: string | null;
  }) => void;
  onFilter: (value: Filter) => void;
  onLayer: (
    layer: "fire" | "roads" | "basemap" | "points",
    value: boolean,
  ) => void;
  onPlacing: (id: string) => void;
  onRun: () => void;
  onCancel: () => void;
  onWeatherUpload: (file: File) => void;
  onAreaSettings: () => void;
};

export function Controls(props: Props) {
  const set = <K extends keyof Scenario>(key: K, value: Scenario[K]) =>
    props.onDraft({ ...props.draft, [key]: value });
  const selectedEngine = props.engines.find(
    (engine) => engine.id === props.draft.engine,
  );
  const selectedProfile =
    selectedEngine &&
    (props.draft.engine_profile === "default"
      ? selectedEngine.default_profile
      : props.draft.engine_profile);
  const compatibleWeather =
    selectedEngine && selectedProfile
      ? selectedEngine.profile_weather[selectedProfile] ||
        selectedEngine.weather_modes
      : [];
  return (
    <Card
      as="aside"
      density="compact"
      shadow="none"
      className="panel controls"
      aria-label={t("Technical simulation controls")}
    >
      <Box className="tool-intro">
        <Typography as="span" variant="label" className="eyebrow">
          {t("Model workspace")}
        </Typography>
        <Typography as={props.headingLevel || "h1"} variant={props.headingLevel === "h2" ? "h3" : "h1"}>
          {t("Simulation")}
        </Typography>
        <Typography as="p" variant="body">
          {t(
            "Configure and inspect fire behaviour. Completed results feed the operational tools.",
          )}
        </Typography>
      </Box>
      {!props.setupMode && (
        <section className="control-section first">
          <Typography as="h2" variant="h3">
            {t("Scenario details")}
          </Typography>
          <label>
            {t("Name")}
            <input
              value={props.scenarioName}
              onChange={(event) =>
                props.onScenarioMeta({
                  name: event.target.value,
                  description: props.description,
                  startTime: props.startTime,
                })
              }
            />
          </label>
          <label>
            {t("Description")}
            <textarea
              rows={2}
              value={props.description}
              placeholder={t("Purpose or exercise notes")}
              onChange={(event) =>
                props.onScenarioMeta({
                  name: props.scenarioName,
                  description: event.target.value,
                  startTime: props.startTime,
                })
              }
            />
          </label>
          <label>
            {t("Scenario start")}
            <input
              type="datetime-local"
              value={props.startTime?.slice(0, 16) || ""}
              onChange={(event) =>
                props.onScenarioMeta({
                  name: props.scenarioName,
                  description: props.description,
                  startTime: event.target.value || null,
                })
              }
            />
          </label>
          <Button variant="secondary" onClick={props.onAreaSettings}>
            {t("Area coverage and data")}
          </Button>
        </section>
      )}
      {props.draft.name.startsWith(t("Extreme showcase")) && (
        <Typography as="p" variant="small" className="extreme-note">
          <strong>{t("Extreme showcase")}</strong>{" "}
          {t(
            "Synthetic low-moisture and high-wind conditions for demonstrating road exposure over time.",
          )}
        </Typography>
      )}

      <section className="control-section">
        <Typography as="h2" variant="h3">
          {t("Engine settings")}
        </Typography>
        <Box className="two-col">
          <label>
            {t("Engine")}
            <select
              value={props.draft.engine}
              onChange={(event) => {
                const engine = props.engines.find(
                  (item) => item.id === event.target.value,
                );
                props.onDraft({
                  ...props.draft,
                  engine: event.target.value as Scenario["engine"],
                  engine_profile: engine?.default_profile || "default",
                  weather_source: { kind: "constant" },
                });
              }}
            >
              {props.engines.map((engine) => {
                const unsupported =
                  (props.draft.ignitions.length > 1 &&
                    !engine.supports_multiple_ignitions) ||
                  (props.draft.ignitions.some((item) => item.start_min > 0) &&
                    !engine.supports_delayed_ignitions);
                return (
                  <option
                    key={engine.id}
                    value={engine.id}
                    disabled={!engine.available || unsupported}
                  >
                    {engine.display_name}
                    {!engine.available
                      ? " · indisponível"
                      : unsupported
                        ? " · permite apenas uma execução imediata"
                        : ""}
                  </option>
                );
              })}
            </select>
          </label>
          <label>
            {t("Duration")}
            <input
              type="number"
              min="10"
              max="720"
              value={props.draft.duration_min}
              onChange={(event) => {
                const duration = Number(event.target.value);
                props.onDraft({
                  ...props.draft,
                  duration_min: duration,
                  ignitions: props.draft.ignitions.map((item) => ({
                    ...item,
                    start_min: Math.min(item.start_min, duration),
                  })),
                });
              }}
            />
            <span className="unit">min</span>
          </label>
        </Box>

        <Typography as="p" variant="body">
          {t(
            "Single engine simulation. Historical comparisons remain available in the archive.",
          )}
        </Typography>

        {selectedEngine && (
          <details className="advanced">
            <summary>{t("Engine and weather")}</summary>
            <label>
              {t("Profile")}
              <select
                value={selectedProfile}
                onChange={(event) => {
                  const profile = event.target.value;
                  const modes =
                    selectedEngine.profile_weather[profile] ||
                    selectedEngine.weather_modes;
                  const weather_source = modes.includes(
                    props.draft.weather_source.kind,
                  )
                    ? props.draft.weather_source
                    : modes.includes("constant")
                      ? { kind: "constant" as const }
                      : props.weatherSeries[0]
                        ? {
                            kind: "series" as const,
                            id: props.weatherSeries[0].id,
                          }
                        : props.draft.weather_source;
                  props.onDraft({
                    ...props.draft,
                    engine_profile: profile,
                    weather_source,
                  });
                }}
              >
                {selectedEngine.profiles.map((profile) => (
                  <option key={profile} value={profile}>
                    {profile === "default" ? "Predefinido" : profile}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("Weather")}
              <select
                value={
                  props.draft.weather_source.kind === "series"
                    ? props.draft.weather_source.id
                    : "constant"
                }
                onChange={(event) =>
                  set(
                    "weather_source",
                    event.target.value === "constant"
                      ? { kind: "constant" }
                      : { kind: "series", id: event.target.value },
                  )
                }
              >
                {compatibleWeather.includes("constant") && (
                  <option value="constant">
                    {t("Constant scenario controls")}
                  </option>
                )}
                {compatibleWeather.includes("series") &&
                  props.weatherSeries.length === 0 && (
                    <option value="constant" disabled>
                      {t("Upload a weather CSV to use this profile")}
                    </option>
                  )}
                {compatibleWeather.includes("series") &&
                  props.weatherSeries.map((series) => (
                    <option key={series.id} value={series.id}>
                      {series.filename} · {series.rows} {t("rows")}
                    </option>
                  ))}
              </select>
            </label>
            {compatibleWeather.includes("series") && (
              <label className="upload">
                {t("Upload weather CSV")}
                <input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) props.onWeatherUpload(file);
                  }}
                />
              </label>
            )}
            <Typography as="p" variant="body" className="engine-message">
              {engineAvailabilityText(
                selectedEngine.id,
                selectedEngine.available,
                selectedEngine.message,
              )}
            </Typography>
            {selectedEngine.limitations.map((value) => (
              <Typography
                as="p"
                variant="small"
                className="engine-warning"
                key={value}
              >
                {t(value)}
              </Typography>
            ))}
            {selectedEngine.id !== "mtt" &&
              selectedEngine.id !== "cell2fire" && (
                <details>
                  <summary>Detalhes técnicos do adaptador</summary>
                  <Typography as="p" variant="body">
                    {selectedEngine.message}
                  </Typography>
                </details>
              )}
          </details>
        )}
      </section>

      <section className="control-section">
        <Typography as="h2" variant="h3">
          {t("Fire and weather conditions")}
        </Typography>
        <Box className="ignition-list">
          {props.draft.ignitions.map((ignition, index) => (
            <Card
              density="compact"
              shadow="none"
              className="ignition-row"
              key={ignition.id}
            >
              <strong>{index + 1}</strong>
              <input
                aria-label={`Nome da ignição ${index + 1}`}
                value={ignition.name}
                onChange={(event) =>
                  set(
                    "ignitions",
                    props.draft.ignitions.map((item) =>
                      item.id === ignition.id
                        ? { ...item, name: event.target.value }
                        : item,
                    ),
                  )
                }
              />
              <label>
                {t("Minute")}
                <input
                  type="number"
                  min="0"
                  max={props.draft.duration_min}
                  value={ignition.start_min}
                  onChange={(event) =>
                    set(
                      "ignitions",
                      props.draft.ignitions.map((item) =>
                        item.id === ignition.id
                          ? { ...item, start_min: Number(event.target.value) }
                          : item,
                      ),
                    )
                  }
                />
              </label>
              <Button
                variant="secondary"
                aria-pressed={props.placingIgnitionId === ignition.id}
                className={
                  props.placingIgnitionId === ignition.id
                    ? "ds-full active"
                    : "ds-full"
                }
                onClick={() => props.onPlacing(ignition.id)}
              >
                {props.placingIgnitionId === ignition.id
                  ? t("Click map…")
                  : t("Move")}
              </Button>
              {props.draft.ignitions.length > 1 && (
                <Button
                  variant="ghost"
                  onClick={() =>
                    set(
                      "ignitions",
                      props.draft.ignitions.filter(
                        (item) => item.id !== ignition.id,
                      ),
                    )
                  }
                >
                  {t("Remove")}
                </Button>
              )}
              <Typography as="small" variant="small">
                {ignition.coordinates[1].toFixed(5)},{" "}
                {ignition.coordinates[0].toFixed(5)}
              </Typography>
            </Card>
          ))}
        </Box>
        <Button
          variant="secondary"
          className="ds-full"
          onClick={() => {
            const first = props.draft.ignitions[0];
            const id = crypto.randomUUID().replaceAll("-", "").slice(0, 12);
            set("ignitions", [
              ...props.draft.ignitions,
              {
                id,
                name: `Ignição ${props.draft.ignitions.length + 1}`,
                coordinates: first.coordinates,
                start_min: 0,
              },
            ]);
            window.setTimeout(() => props.onPlacing(id), 0);
          }}
        >
          {t("Add fire start")}
        </Button>

        <Box className="two-col">
          <label>
            <span>{t("Wind speed")} <strong>{props.draft.wind_speed_kmh} km/h</strong></span>
            <input
              type="range"
              min="0"
              max="120"
              value={props.draft.wind_speed_kmh}
              onChange={(event) =>
                set("wind_speed_kmh", Number(event.target.value))
              }
            />
          </label>
          <label>
            {t("Direction")}
            <input
              type="number"
              min="0"
              max="359"
              value={props.draft.wind_direction_deg}
              onChange={(event) =>
                set("wind_direction_deg", Number(event.target.value))
              }
            />
            <span className="unit">°</span>
          </label>
        </Box>

        <Box className="two-col">
          <label>
            {t("Random seed")}
            <input
              type="number"
              min="0"
              value={props.draft.seed}
              onChange={(event) => set("seed", Number(event.target.value))}
            />
          </label>
          <label>
            {t("Fuel moisture")}
            <select
              value={props.draft.moisture}
              onChange={(event) =>
                set("moisture", event.target.value as Scenario["moisture"])
              }
            >
              <option value="low">{t("Low")}</option>
              <option value="moderate">{t("Moderate")}</option>
              <option value="high">{t("High")}</option>
            </select>
          </label>
        </Box>
      </section>

      <section className="control-section">
        <Typography as="h2" variant="h3">
          {t("Road exposure assumptions")}
        </Typography>
        <label>
          <span>{t("Exposure buffer")} <strong>{props.draft.exposure_buffer_m} m</strong></span>
          <input
            type="range"
            min="0"
            max="120"
            step="10"
            value={props.draft.exposure_buffer_m}
            onChange={(event) =>
              set("exposure_buffer_m", Number(event.target.value))
            }
          />
        </label>
      </section>

      <Button
        variant="primary"
        className="ds-full"
        onClick={props.pending ? props.onCancel : props.onRun}
      >
        {props.pending ? t("Cancel simulation") : t("Run simulation")}
      </Button>

      {!props.setupMode && (
        <section>
          <Typography as="h2" variant="h3">
            {t("Road filter")}
          </Typography>
          {[
            ["all", t("All roads")],
            ["now", t("Affected now")],
            ["upcoming", t("Newly affected within X")],
            ["by-then", t("All affected by then")],
            ["not-reached", t("Not reached in run")],
            ["unknown", "Cobertura desconhecida"],
          ].map(([value, label]) => (
            <label className="radio" key={value}>
              <input
                type="radio"
                name="filter"
                checked={props.filter === value}
                onChange={() => props.onFilter(value as Filter)}
              />
              {label}
            </label>
          ))}
        </section>
      )}

      {!props.setupMode && (
        <section>
          <Typography as="h2" variant="h3">
            {t("Layers")}
          </Typography>
          <Toggle
            label={t("Area reached by fire")}
            checked={props.showFire}
            onChange={(value) => props.onLayer("fire", value)}
          />
          <Toggle
            label={t("Roads")}
            checked={props.showRoads}
            onChange={(value) => props.onLayer("roads", value)}
          />
          <Toggle
            label={t("Basemap")}
            checked={props.showBasemap}
            onChange={(value) => props.onLayer("basemap", value)}
          />
        </section>
      )}
    </Card>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="toggle">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span />
      {label}
    </label>
  );
}
