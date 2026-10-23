import { confirmDiscard, useNavigationGuard } from "../navigation";
import { PreparationFeedback } from "./PreparationFeedback";
import { Button, Dialog, PopupLayout } from "./ui";
import { datasetLabel, stageLabel, statusLabel, t } from "../locale";
import { useEffect, useMemo, useRef, useState } from "react";
import { LocationMap } from "./LocationMap";
import { CoordinateFields } from "./CoordinateFields";
import { api } from "../api";
import type {
  AreaPreparation,
  CellSizeM,
  FeatureCollection,
  Ignition,
  ScenarioWorkspace,
} from "../types";
import {
  LandscapeControls,
  marginAllowed,
  useAreaEstimate,
} from "./LandscapeSettings";

type Props = {
  onCreated: (scenario: ScenarioWorkspace) => void;
  onClose?: () => void;
  workspace?: ScenarioWorkspace;
};

const initial: Ignition = {
  id: "fire-1",
  name: "Ignição 1",
  coordinates: [-8.3075, 41.4535],
  start_min: 0,
};

export function ScenarioWizard({ onCreated, onClose, workspace }: Props) {
  const [step, setStep] = useState<
    "location" | "coverage" | "preparing" | "review"
  >("location");
  const startingIgnitions = workspace?.simulation.ignitions || [initial];
  const [name, setName] = useState(workspace?.name || "Nova ocorrência");
  const [center, setCenter] = useState<[number, number]>(
    workspace?.resource_center || startingIgnitions[0].coordinates,
  );
  const [ignitions, setIgnitions] = useState<Ignition[]>(startingIgnitions);
  const [selected, setSelected] = useState(startingIgnitions[0].id);
  const [resourceRadius, setResourceRadius] = useState<10 | 25 | 50>(
    workspace?.resource_radius_km || 25,
  );
  const [fireMargin, setFireMargin] = useState<5 | 10 | 25>(
    workspace?.fire_margin_km || 5,
  );
  const [cellSize, setCellSize] = useState<CellSizeM>(
    workspace?.cell_size_m || 30,
  );
  const [acknowledged, setAcknowledged] = useState(false);
  const [preparation, setPreparation] = useState<AreaPreparation>();
  const [water, setWater] = useState<
    FeatureCollection & { metadata?: Record<string, unknown> }
  >();
  const [stations, setStations] = useState<
    FeatureCollection & { metadata?: Record<string, unknown> }
  >();
  const [includeWater, setIncludeWater] = useState(true);
  const [includeStations, setIncludeStations] = useState(true);
  const [error, setError] = useState("");
  const [finishing, setFinishing] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [coordinatesValid, setCoordinatesValid] = useState(true);

  const finished = useRef(false);
  const inputSnapshot = JSON.stringify([name, center, ignitions, resourceRadius, fireMargin, cellSize, includeWater, includeStations]);
  const initialInputs = useRef(inputSnapshot);
  const navigationDirty = inputSnapshot !== initialInputs.current;
  useNavigationGuard(() => finished.current || (!finishing && (!navigationDirty || confirmDiscard())), navigationDirty && !finished.current);

  const estimateRequest = useMemo(
    () => ({
      center,
      resource_radius_km: resourceRadius,
      fire_margin_km: fireMargin,
      cell_size_m: cellSize,
      ignitions,
    }),
    [center, resourceRadius, fireMargin, cellSize, ignitions],
  );
  const {
    estimate,
    loading: estimateLoading,
    error: estimateError,
    key: estimateKey,
  } = useAreaEstimate(estimateRequest);
  const canPrepare = Boolean(
    estimate?.allowed &&
    !estimateLoading &&
    marginAllowed(cellSize, fireMargin) &&
    (!estimate.requires_acknowledgement || acknowledged),
  );

  useEffect(() => {
    setAcknowledged(false);
  }, [estimateKey]);

  useEffect(() => {
    if (!preparation || !["queued", "running"].includes(preparation.status))
      return;
    const timer = window.setTimeout(
      () =>
        api
          .preparation(preparation.id)
          .then(setPreparation)
          .catch((value) => setError(String(value))),
      1000,
    );
    return () => window.clearTimeout(timer);
  }, [preparation]);

  useEffect(() => {
    if (!workspace) return;
    const stored = window.localStorage.getItem(
      `scenario-preparation/${workspace.id}`,
    );
    if (!stored || preparation) return;
    api
      .preparation(stored)
      .then((job) => {
        setPreparation(job);
        if (["queued", "running"].includes(job.status)) setStep("preparing");
        if (["ready", "partial"].includes(job.status)) setStep("preparing");
      })
      .catch(() =>
        window.localStorage.removeItem(`scenario-preparation/${workspace.id}`),
      );
  }, [workspace, preparation]);

  useEffect(() => {
    if (workspace && preparation)
      window.localStorage.setItem(
        `scenario-preparation/${workspace.id}`,
        preparation.id,
      );
  }, [workspace, preparation]);

  useEffect(() => {
    if (
      !preparation ||
      !["ready", "partial"].includes(preparation.status) ||
      step !== "preparing"
    )
      return;
    Promise.all([
      api.waterCatalog(preparation.package_id),
      api.fireStationCatalog(preparation.package_id),
    ])
      .then(([waterData, stationData]) => {
        setWater(waterData);
        setStations(stationData);
        setStep("review");
      })
      .catch((reason) => {
        setError(
          reason instanceof Error
            ? reason.message
            : "Unable to load prepared resources",
        );
        setStep("review");
      });
  }, [preparation, step]);

  function place(position: [number, number]) {
    setIgnitions((items) =>
      items.map((item) =>
        item.id === selected ? { ...item, coordinates: position } : item,
      ),
    );
    if (step === "location" && selected === ignitions[0].id)
      setCenter(position);
  }

  function addFire() {
    const id = crypto.randomUUID().replaceAll("-", "").slice(0, 12);
    setIgnitions((items) => [
      ...items,
      {
        id,
        name: `Ignição ${items.length + 1}`,
        coordinates: center,
        start_min: 0,
      },
    ]);
    setSelected(id);
  }

  async function prepare() {
    setError("");
    setStep("preparing");
    try {
      setPreparation(
        await api.prepareArea({
          ...estimateRequest,
          acknowledge_high_cost: acknowledged,
        }),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Preparation could not start",
      );
      setStep("coverage");
    }
  }

  async function finish() {
    if (!preparation) return;
    setFinishing(true);
    setError("");
    try {
      let scenario = workspace
        ? await api.saveScenario(
          {
            ...workspace,
            name,
            area_id: preparation.package_id,
            area_package_id: preparation.package_id,
            resource_center: center,
            resource_radius_km: resourceRadius,
            fire_margin_km: fireMargin,
            cell_size_m: cellSize,
            simulation: { ...workspace.simulation, name, ignitions },
          },
          workspace.revision,
        )
        : await api.createScenario({
          name,
          area_id: preparation.package_id,
          area_package_id: preparation.package_id,
          resource_center: center,
          resource_radius_km: resourceRadius,
          fire_margin_km: fireMargin,
          cell_size_m: cellSize,
          simulation: {
            name,
            engine: "mtt",
            ignitions,
            wind_speed_kmh: 20,
            wind_direction_deg: 45,
            moisture: "moderate",
            duration_min: 120,
            seed: 42,
            exposure_buffer_m: 30,
            weather_source: { kind: "constant" },
            engine_profile: "default",
          },
          points: [],
          closures: [],
        });
      if (includeWater && water?.features.length) {
        const ids = water.features
          .map((feature) => String(feature.properties?.external_id || ""))
          .filter(Boolean);
        scenario = await api.importPoints(scenario.id, scenario.revision, ids);
      }
      if (includeStations && stations?.features.length) {
        const ids = stations.features
          .map((feature) => String(feature.properties?.external_id || ""))
          .filter(Boolean);
        scenario = await api.importFireStations(
          scenario.id,
          scenario.revision,
          ids,
        );
      }
      if (workspace)
        window.localStorage.removeItem(`scenario-preparation/${workspace.id}`);
      finished.current = true;
      onCreated(scenario);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Scenario creation failed",
      );
    } finally {
      setFinishing(false);
    }
  }

  const activeIgnition = ignitions.find(item => item.id === selected) || ignitions[0];
  const steps = ["location", "coverage", "preparing", "review"] as const;
  const labels = ["Localização", "Cobertura", "Preparação", "Revisão"];
  const titles = ["Localizar a ocorrência", "Definir a cobertura", "Preparar os dados locais", "Rever os recursos"];
  return (
    <Dialog onDismiss={finishing ? undefined : onClose} aria-label={t("Create location-based scenario")}>
      <PopupLayout title={titles[steps.indexOf(step)]} eyebrow={workspace ? t("Complete scenario setup") : t("New scenario")}
        onClose={onClose} closeDisabled={finishing}
        navigation={<ol className="popup-step-list" aria-label="Etapas de preparação">{steps.map((value, index) =>
          <li key={value} aria-current={step === value ? "step" : undefined}><span>{index + 1}.</span> {labels[index]}</li>)}</ol>}
        map={<LocationMap points={ignitions} selectedId={selected} center={center} resourceRadius={resourceRadius} fireMargin={fireMargin}
          mode={step === "location" ? "point" : "coverage"} readOnly={step !== "location"} onPlace={place} />}
        feedback={error && <p className="failure" role="alert">{error}</p>}
        actions={<>
          {step === "coverage" && <Button variant="outline" onClick={() => setStep("location")}>{t("Back")}</Button>}
          {step === "location" && <Button disabled={!name.trim() || !coordinatesValid} onClick={() => setStep("coverage")}>{t("Choose coverage")}</Button>}
          {step === "coverage" && <Button disabled={!canPrepare} onClick={() => void prepare()}>{t("Prepare area")}</Button>}
          {step === "preparing" && preparation && ["queued", "running"].includes(preparation.status) && <Button variant="outline" onClick={async () => {
            try { const value = await api.cancelPreparation(preparation.id); setPreparation(value); setStep("coverage"); }
            catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível cancelar a preparação."); }
          }}>{t("Cancel")}</Button>}
          {step === "preparing" && preparation?.status === "failed" && <Button disabled={retrying} onClick={async () => {
            setError(""); setRetrying(true);
            try { setPreparation(await api.retryPreparation(preparation.id)); }
            catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível retomar a preparação."); }
            finally { setRetrying(false); }
          }}>{retrying ? "A retomar…" : "Tentar novamente"}</Button>}
          {step === "review" && <>
            <Button variant="outline" disabled={finishing} onClick={() => setStep("coverage")}>{t("Back")}</Button>
            <Button disabled={finishing} onClick={() => void finish()}>{finishing ? t("Saving…") : workspace ? t("Finish setup") : t("Open scenario")}</Button>
          </>}
        </>}>
        {step === "location" && <>
          <label>{t("Scenario name")}<input value={name} disabled={Boolean(workspace)} onChange={event => setName(event.target.value)} /></label>
          <p>Selecione uma ignição e coloque-a no mapa. A primeira ignição define também o centro da pesquisa de recursos.</p>
          <div className="ignition-picker" aria-label="Ignições">
            {ignitions.map((item, index) => <Button key={item.id} variant="outline" aria-pressed={selected === item.id}
              onClick={() => { setSelected(item.id); setCoordinatesValid(true); }}>
              <span>{index + 1}. {item.name} · {item.start_min} min</span>
            </Button>)}
          </div>
          <Button variant="secondary" onClick={() => { addFire(); setCoordinatesValid(true); }}>{t("Add fire start")}</Button>
          <section className="ignition-editor" aria-label="Editar ignição selecionada">
            <div className="ignition-editor-heading"><strong>Ignição {ignitions.indexOf(activeIgnition) + 1}</strong>
              {ignitions.length > 1 && <Button variant="ghost" onClick={() => {
                const remaining = ignitions.filter(value => value.id !== selected); if (selected === ignitions[0].id) setCenter(remaining[0].coordinates); setIgnitions(remaining); setSelected(remaining[0].id); setCoordinatesValid(true);
              }}>{t("Remove")}</Button>}
            </div>
            <label>Nome da ignição<input value={activeIgnition.name} onChange={event => setIgnitions(values => values.map(value => value.id === selected ? { ...value, name: event.target.value } : value))} /></label>
            <label>{t("Start minute")}<input type="number" min="0" max="720" value={activeIgnition.start_min}
              onChange={event => setIgnitions(values => values.map(value => value.id === selected ? { ...value, start_min: Number(event.target.value) } : value))} /></label>
            <CoordinateFields key={selected} value={activeIgnition.coordinates} onCommit={place} onValidityChange={setCoordinatesValid} />
          </section>
        </>}
        {step === "coverage" && <>
          <section className="popup-form-section" aria-label="Resumo da localização"><strong>{name}</strong>
            <p>{ignitions.length} {ignitions.length === 1 ? "ignição" : "ignições"} · centro {center[1].toFixed(5)}, {center[0].toFixed(5)}</p>
            <small>Volte à localização para alterar as ignições.</small>
          </section>
          <label>{t("Resource search")}<select value={resourceRadius} onChange={event => setResourceRadius(Number(event.target.value) as 10 | 25 | 50)}>
            <option value="10">10 km</option><option value="25">25 km</option><option value="50">50 km</option>
          </select></label>
          <LandscapeControls cellSize={cellSize} fireMargin={fireMargin} estimate={estimate} loading={estimateLoading}
            acknowledged={acknowledged} onCellSize={setCellSize} onFireMargin={setFireMargin} onAcknowledged={setAcknowledged} />
          {estimateError && <p className="failure" role="alert">{estimateError}</p>}
        </>}
        {step === "preparing" && <section className="popup-form-section" aria-label="Progresso da preparação">
          <progress aria-label="Progresso da preparação" max="100" value={preparation?.progress || 0} />
          <strong>{preparation ? stageLabel(preparation.stage, preparation.status) : t("Starting…")}</strong>
          <span>{preparation?.progress || 0}%</span>
          {preparation && <>
            <details><summary>Estado das fontes de dados</summary>{Object.entries(preparation.datasets).map(([key, value]) => <p key={key}>{datasetLabel(key)}: {statusLabel(value.status)}</p>)}</details>
            <PreparationFeedback job={preparation} imported={Boolean(workspace)} />
          </>}
        </section>}
        {step === "review" && <div className="popup-form-section">
          <p>{t("The area package is ready. Source dates and any partial-data failures remain attached to this scenario.")}</p>
          {preparation && <PreparationFeedback job={preparation} imported={Boolean(workspace)} />}
          <label><input type="checkbox" checked={includeWater} onChange={event => setIncludeWater(event.target.checked)} />{t("Import all")} {water?.features.length || 0} {t("discovered water points")}</label>
          <label><input type="checkbox" checked={includeStations} onChange={event => setIncludeStations(event.target.checked)} />{t("Import all")} {stations?.features.length || 0} {t("discovered fire stations")}</label>
          {preparation?.status === "partial" && <p className="engine-warning">{t("One or more optional resource catalogs could not be prepared. Terrain and roads are ready.")}</p>}
        </div>}
      </PopupLayout>
    </Dialog>
  );
}
