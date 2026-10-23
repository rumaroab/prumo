import { confirmDiscard, useNavigationGuard } from "../navigation";
import { PreparationFeedback } from "./PreparationFeedback";
import { Button, Dialog, PopupLayout } from "./ui";
import { CoordinateFields } from "./CoordinateFields";
import { LocationMap } from "./LocationMap";
import { datasetLabel, stageLabel, statusLabel, t } from "../locale";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { AreaPreparation, CellSizeM, ScenarioWorkspace } from "../types";
import {
  LandscapeControls,
  marginAllowed,
  useAreaEstimate,
} from "./LandscapeSettings";

type Values = {
  center: [number, number];
  resourceRadius: 10 | 25 | 50;
  fireMargin: 5 | 10 | 25;
  cellSize: CellSizeM;
};
type Props = {
  workspace: ScenarioWorkspace;
  onApply: (packageId: string, values: Values) => Promise<void>;
  onClose: () => void;
};

export function AreaSettings({ workspace, onApply, onClose }: Props) {
  const [center, setCenter] = useState<[number, number]>(
    workspace.resource_center || workspace.simulation.ignitions[0].coordinates,
  );
  const [resourceRadius, setResourceRadius] = useState<10 | 25 | 50>(
    workspace.resource_radius_km,
  );
  const [fireMargin, setFireMargin] = useState<5 | 10 | 25>(
    workspace.fire_margin_km,
  );
  const [cellSize, setCellSize] = useState<CellSizeM>(
    workspace.cell_size_m || 30,
  );
  const [acknowledged, setAcknowledged] = useState(false);
  const [job, setJob] = useState<AreaPreparation>();
  const [error, setError] = useState("");
  const [applying, setApplying] = useState(false);
  const [coordinatesValid, setCoordinatesValid] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const applied = useRef(false);
  const inputSnapshot = JSON.stringify([center, resourceRadius, fireMargin, cellSize]);
  const initialInputs = useRef(inputSnapshot);
  const navigationDirty = inputSnapshot !== initialInputs.current || Boolean(job);
  useNavigationGuard(() => applied.current || (!applying && (!navigationDirty || confirmDiscard())), navigationDirty && !applied.current);

  const estimateRequest = useMemo(
    () => ({
      center,
      resource_radius_km: resourceRadius,
      fire_margin_km: fireMargin,
      cell_size_m: cellSize,
      ignitions: workspace.simulation.ignitions,
    }),
    [
      center,
      resourceRadius,
      fireMargin,
      cellSize,
      workspace.simulation.ignitions,
    ],
  );
  const {
    estimate,
    loading: estimateLoading,
    error: estimateError,
    key: estimateKey,
  } = useAreaEstimate(estimateRequest);
  const jobActive = Boolean(job && ["queued", "running"].includes(job.status));
  const canPrepare = Boolean(
    estimate?.allowed &&
    !estimateLoading &&
    marginAllowed(cellSize, fireMargin) &&
    (!estimate.requires_acknowledgement || acknowledged),
  );

  useEffect(() => {
    setAcknowledged(false);
    setJob((current) =>
      current && !["queued", "running"].includes(current.status)
        ? undefined
        : current,
    );
  }, [estimateKey]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = window.setTimeout(
      () =>
        api
          .preparation(job.id)
          .then(setJob)
          .catch((reason) => setError(String(reason))),
      1000,
    );
    return () => window.clearTimeout(timer);
  }, [job]);

  async function prepare() {
    setError("");
    setSubmitting(true);
    try {
      if (job?.status === "failed") {
        setJob(await api.retryPreparation(job.id));
        return;
      }
      setJob(
        await api.prepareArea({
          ...estimateRequest,
          acknowledge_high_cost: acknowledged,
        }),
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to prepare area",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function apply() {
    if (!job || !["ready", "partial"].includes(job.status)) return;
    setApplying(true);
    try {
      await onApply(job.package_id, {
        center,
        resourceRadius,
        fireMargin,
        cellSize,
      });
      applied.current = true;
      onClose();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to apply prepared area",
      );
    } finally {
      setApplying(false);
    }
  }

  return (
    <Dialog onDismiss={applying ? undefined : onClose} aria-label="Configurar área">
      <PopupLayout title={t("Prepare updated area")} eyebrow={t("Scenario data")} onClose={onClose} closeDisabled={applying}
        map={<LocationMap points={workspace.simulation.ignitions} center={center} resourceRadius={resourceRadius} fireMargin={fireMargin}
          mode="coverage" readOnly={jobActive || applying} onPlace={setCenter} />}
        feedback={<>{estimateError && <p className="failure" role="alert">{estimateError}</p>}{error && <p className="failure" role="alert">{error}</p>}</>}
        actions={<>
          <Button variant="outline" disabled={applying} onClick={async () => {
            try { if (job && jobActive) await api.cancelPreparation(job.id); onClose(); }
            catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível cancelar a preparação."); }
          }}>{t("Cancel")}</Button>
          {job && ["ready", "partial"].includes(job.status)
            ? <Button disabled={applying || !coordinatesValid} onClick={() => void apply()}>{applying ? "A aplicar…" : "Usar área preparada"}</Button>
            : <Button disabled={submitting || jobActive || !canPrepare || !coordinatesValid} onClick={() => void prepare()}>{submitting ? "A iniciar…" : job?.status === "failed" ? "Tentar novamente" : t("Prepare area")}</Button>}
        </>}>
        <p>{t("Recenter or enlarge coverage after moving fire starts. Existing simulation results keep their original area package.")}</p>
        <CoordinateFields value={center} onCommit={setCenter} onValidityChange={setCoordinatesValid} disabled={jobActive || applying} />
        <label>{t("Resource search")}<select disabled={jobActive || applying} value={resourceRadius}
          onChange={event => setResourceRadius(Number(event.target.value) as 10 | 25 | 50)}>
          <option value="10">10 km</option><option value="25">25 km</option><option value="50">50 km</option>
        </select></label>
        <LandscapeControls cellSize={cellSize} fireMargin={fireMargin} estimate={estimate} loading={estimateLoading}
          acknowledged={acknowledged} onCellSize={setCellSize} onFireMargin={setFireMargin} onAcknowledged={setAcknowledged} disabled={jobActive || applying} />
        {job && <section className="popup-form-section" aria-label="Progresso da preparação">
          <progress aria-label="Progresso da preparação" max="100" value={job.progress} />
          <strong>{stageLabel(job.stage, job.status)}</strong><span>{job.progress}%</span>
          <details><summary>Estado das fontes de dados</summary>{Object.entries(job.datasets).map(([key, value]) => <p key={key}>{datasetLabel(key)}: {statusLabel(value.status)}</p>)}</details>
          {job.status === "partial" && <p className="engine-warning" role="status">{t("One or more optional resource catalogs could not be prepared. Terrain and roads are ready.")}</p>}
          <PreparationFeedback job={job} imported />
        </section>}
      </PopupLayout>
    </Dialog>
  );
}
