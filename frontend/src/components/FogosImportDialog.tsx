import { confirmDiscard, useNavigationGuard } from "../navigation";
import { Box, Button, Card, Dialog, PopupLayout, Typography } from "./ui";
import { formatDateTime, t } from "../locale";
import { useEffect, useRef, useState } from "react";
import { CoordinateFields, validCoordinates } from "./CoordinateFields";
import { LocationMap } from "./LocationMap";
import { api } from "../api";
import type { FogosIncident, FogosStatus, ScenarioWorkspace } from "../types";

type Props = {
  onClose: () => void;
  onCreated: (scenario: ScenarioWorkspace) => void;
  onOpenExisting: (id: string) => void;
};

export function FogosImportDialog({
  onClose,
  onCreated,
  onOpenExisting,
}: Props) {
  const [status, setStatus] = useState<FogosStatus>();
  const [mode, setMode] = useState<"active" | "historical">("active");
  const [municipality, setMunicipality] = useState("");
  const [day, setDay] = useState("");
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<FogosIncident[]>([]);
  const [paginator, setPaginator] = useState<Record<string, unknown> | null>();
  const [selected, setSelected] = useState<FogosIncident>();
  const [snapshotId, setSnapshotId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [startTime, setStartTime] = useState("");
  const [coordinates, setCoordinates] = useState<[number, number] | null>(null);
  const [loading, setLoading] = useState(false);
  const [coordinatesValid, setCoordinatesValid] = useState(false);
  const [error, setError] = useState("");
  const [requestId] = useState(() => crypto.randomUUID());

  const [edited, setEdited] = useState(false);
  const created = useRef(false);
  useNavigationGuard(() => created.current || ((!loading || !selected) && (!edited || confirmDiscard())), edited && !created.current);

  useEffect(() => {
    const controller = new AbortController();
    api
      .fogosStatus(controller.signal)
      .then(setStatus)
      .catch((reason) => setError(message(reason)));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!status?.configured) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api
      .fogosIncidents(
        mode,
        { municipality, day: mode === "historical" ? day : undefined, page },
        controller.signal,
      )
      .then((result) => {
        setItems(result.items);
        setPaginator(result.paginator);
      })
      .catch((reason) => {
        if ((reason as Error).name !== "AbortError") setError(message(reason));
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [status?.configured, mode, municipality, day, page]);

  async function preview(incident: FogosIncident) {
    setLoading(true);
    setError("");
    try {
      const value = await api.fogosImportPreview(incident.incident_id);
      setEdited(false);
      setSelected(value.incident);
      setSnapshotId(value.snapshot.id);
      setName(value.suggested.name);
      setDescription(value.suggested.description);
      setStartTime(localDateTime(value.suggested.start_time));
      setCoordinates(value.suggested.coordinates || null);
    } catch (reason) {
      setError(message(reason));
    } finally {
      setLoading(false);
    }
  }

  async function create() {
    if (!validCoordinates(coordinates) || !coordinatesValid) {
      setError("Escolha uma localização válida antes de continuar.");
      return;
    }
    if (!startTime) {
      setError("É necessária a hora de início comunicada da ocorrência.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const scenario = await api.createScenario(
        {
          name,
          description,
          start_time: new Date(startTime).toISOString(),
          area_id: "unprepared",
          area_package_id: null,
          resource_center: coordinates,
          fogos_snapshot_id: snapshotId,
          simulation: {
            name,
            engine: "mtt",
            ignitions: [
              {
                id: "fire-1",
                name: "Reported fire start",
                coordinates,
                start_min: 0,
              },
            ],
            wind_speed_kmh: 20,
            wind_direction_deg: 45,
            moisture: "moderate",
            duration_min: 120,
            seed: 42,
            exposure_buffer_m: 30,
            weather_source: { kind: "constant" },
            engine_profile: "default",
          },
        },
        requestId,
      );
      created.current = true;
      onCreated(scenario);
    } catch (reason) {
      setError(message(reason));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog onChangeCapture={() => { if (selected) setEdited(true); }} onDismiss={loading && selected ? undefined : onClose} aria-label={t("Import from Fogos.pt")}>
      <PopupLayout title={t("Import from Fogos.pt")} eyebrow={t("New scenario")} size="wide" onClose={onClose} closeDisabled={loading && Boolean(selected)}
        map={selected && <LocationMap points={coordinates ? [{ id: selected.incident_id, name: selected.location, coordinates }] : []}
          selectedId={selected.incident_id} center={coordinates} onPlace={(value) => { setEdited(true); setCoordinates(value); }} readOnly={loading} />}
        feedback={error && <p className="management-error" role="alert">{error}</p>}
        actions={selected ? <>
          <Button variant="outline" disabled={loading} onClick={onClose}>{t("Cancel")}</Button>
          <Button disabled={loading || !name.trim() || !validCoordinates(coordinates) || !coordinatesValid || !startTime} onClick={() => void create()}>{loading ? t("Creating…") : t("Create scenario")}</Button>
        </> : status?.configured ? <>            <Box className="pagination">
          <Button
            variant="secondary"
            disabled={page === 1}
            onClick={() => setPage((value) => Math.max(1, value - 1))}
          >
            {t("Previous")}
          </Button>
          <span>
            {t("Page")} {page}
            {Number(paginator?.totalPages) > 0
              ? ` de ${Number(paginator?.totalPages)}`
              : ""}
          </span>
          <Button
            variant="secondary"
            disabled={
              Number(paginator?.totalPages) > 0
                ? page >= Number(paginator?.totalPages)
                : items.length < 50
            }
            onClick={() => setPage((value) => value + 1)}
          >
            {t("Next")}
          </Button>
        </Box></> : <Button variant="outline" onClick={onClose}>{t("Close")}</Button>}>
        {!status ? (
          <Typography as="p" variant="body">
            {t("Checking integration…")}
          </Typography>
        ) : !status.configured ? (
          <Card
            density="compact"
            shadow="none"
            className="integration-unavailable"
          >
            <Typography as="h2" variant="h3">
              {t("Import unavailable")}
            </Typography>
            <Typography as="p" variant="body">
              {status.message}
            </Typography>
            <Typography as="p" variant="body">
              {t(
                "Manual scenario creation and all existing tools remain available.",
              )}
            </Typography>
          </Card>
        ) : selected ? (
          <>
            <Button
              variant="ghost"
              className="breadcrumb"
              onClick={() => {
                setSelected(undefined);
                setSnapshotId("");
              }}
            >
              {t("← Incident list")}
            </Button>
            <details><summary>Dados comunicados · {selected.location}</summary>
              <Card
                density="compact"
                shadow="none"
                className="source-summary"
              >
                <strong>{selected.location}</strong>
                <span>
                  {selected.status || t("Status unavailable")}{" "}
                  {t("· reported")} {formatDate(selected.reported_at)}
                </span>
                <span>
                  {resourceValue(selected.resources.personnel)} Operacionais ·{" "}
                  {resourceValue(selected.resources.vehicles)} Meios
                  terrestres · {resourceValue(selected.resources.aircraft)}{" "}
                  Meios aéreos
                </span>
                <span>
                  {t("Source refreshed")} {formatDate(selected.updated_at)}
                </span>
              </Card>                </details>

            <label>
              {t("Scenario name")}
              <input
                required
                maxLength={120}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <details><summary>Descrição opcional</summary>
              <label>
                {t("Description")}
                <textarea
                  rows={3}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </label>
            </details>
            <label>
              {t("Reported incident start")}
              <input
                type="datetime-local"
                required
                value={startTime}
                onChange={(event) => setStartTime(event.target.value)}
              />
            </label>
            <CoordinateFields value={coordinates} onCommit={setCoordinates} onValidityChange={setCoordinatesValid} disabled={loading} />
            {!selected.has_usable_coordinates && (
              <Typography
                role="alert"
                as="p"
                variant="small"
                className="management-error"
              >
                {t(
                  "The source coordinate is missing or outside mainland Portugal. Click the map or enter a valid position.",
                )}
              </Typography>
            )}
            {selected.linked_scenarios?.length ? (
              <Box className="existing-links">
                <strong>{t("Already linked")}</strong>
                {selected.linked_scenarios.map((item) => (
                  <Button
                    variant="secondary"
                    key={item.id}
                    onClick={() => onOpenExisting(item.id)}
                  >
                    {t("Open")} {item.name}
                  </Button>
                ))}
                <Typography as="small" variant="small">
                  {t(
                    "You can still create another scenario from the same incident.",
                  )}
                </Typography>
              </Box>
            ) : null}

            <p className="engine-warning">Os meios importados são provisórios. As unidades ficam indisponíveis até confirmação.</p>
            <details><summary>Origem e condições de importação</summary>
              <p>Fonte: <a href={selected.source_url} target="_blank" rel="noreferrer">Fogos.pt</a>. São importados os totais de operacionais, meios terrestres e meios aéreos. Cada viatura ou aeronave comunicada gera um registo provisório e uma unidade com nome numerado. As unidades começam indisponíveis até confirmação. Não são atribuídas localizações nem capacidades não comunicadas.</p>
            </details>
          </>
        ) : (
          <>
            <Box className="import-tabs">
              <Button
                variant="secondary"
                aria-pressed={mode === "active"}
                className={mode === "active" ? "active" : ""}
                onClick={() => {
                  setMode("active");
                  setPage(1);
                }}
              >
                {t("Active incidents")}
              </Button>
              <Button
                variant="secondary"
                aria-pressed={mode === "historical"}
                className={mode === "historical" ? "active" : ""}
                onClick={() => {
                  setMode("historical");
                  setPage(1);
                }}
              >
                {t("Historical search")}
              </Button>
            </Box>
            <Box className="import-filters">
              <label>
                {t("Municipality")}
                <input
                  value={municipality}
                  onChange={(event) => {
                    setMunicipality(event.target.value);
                    setPage(1);
                  }}
                  placeholder={t("Optional")}
                />
              </label>
              {mode === "historical" && (
                <label>
                  {t("Date")}
                  <input
                    type="date"
                    value={day}
                    onChange={(event) => {
                      setDay(event.target.value);
                      setPage(1);
                    }}
                  />
                </label>
              )}
            </Box>
            {loading ? (
              <Typography as="p" variant="body">
                {t("Loading incidents…")}
              </Typography>
            ) : (
              <Box className="incident-list">
                {items.map((item) => (
                  <Card
                    as="article"
                    density="compact"
                    shadow="none"
                    key={item.incident_id}
                  >
                    <Box>
                      <strong>{item.location}</strong>
                      <span>
                        {item.municipality || t("Municipality unavailable")} ·{" "}
                        {item.status || t("Status unavailable")}
                      </span>
                      <Typography as="small" variant="small">
                        {formatDate(item.reported_at)} ·{" "}
                        {resourceValue(item.resources.personnel)} Operacionais ·{" "}
                        {resourceValue(item.resources.vehicles)} Meios
                        terrestres · {resourceValue(item.resources.aircraft)}{" "}
                        Meios aéreos
                      </Typography>
                      <Typography as="small" variant="small">
                        {t("Updated")} {formatDate(item.updated_at)}
                      </Typography>
                    </Box>
                    <Box>
                      {item.linked_scenarios?.length ? (
                        <span className="setup-badge ready">
                          {item.linked_scenarios.length} {t("linked")}
                        </span>
                      ) : null}
                      <Button
                        variant="secondary"
                        disabled={!item.importable}
                        onClick={() => void preview(item)}
                      >
                        {t("Preview")}
                      </Button>
                    </Box>
                  </Card>
                ))}
              </Box>
            )}
            {!loading && !items.length && (
              <Card
                density="compact"
                shadow="none"
                className="management-empty"
              >
                <Typography as="h2" variant="h3">
                  {t("No matching rural-fire incidents")}
                </Typography>
                <Typography as="p" variant="body">
                  {t("Change the filters or try another date.")}
                </Typography>
              </Card>
            )}

            <Typography as="p" variant="small" className="source-disclaimer">
              {t("Source:")}{" "}
              <a href={status.source_url} target="_blank" rel="noreferrer">
                Fogos.pt
              </a>
              {t(
                ". Only rural-fire incidents within mainland Portugal can start simulations.",
              )}
            </Typography>
          </>
        )}
      </PopupLayout>
    </Dialog>
  );
}

function localDateTime(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 16);
}
function formatDate(value?: string | null) {
  return formatDateTime(value);
}
function resourceValue(value: number | null) {
  return value == null ? "indisponível" : String(value);
}
function message(reason: unknown) {
  return reason instanceof Error ? reason.message : "Ocorreu um erro";
}
