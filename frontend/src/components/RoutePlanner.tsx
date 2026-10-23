import { confirmDiscard, useNavigationGuard } from "../navigation";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { MobilitySnapshot, Movement, RoadVehicleClass, RouteAssessment, RouteLocation, RoutePlan } from "../types";
import { CoordinateFields, validCoordinates } from "./CoordinateFields";
import { unitCategory } from "./ResourceInventoryGroups";
import { Button, Card, Typography } from "./ui";

const vehicleTypes: { value: RoadVehicleClass; label: string }[] = [
  { value: "light", label: "Viatura ligeira" },
  { value: "heavy", label: "Viatura pesada" },
  { value: "tanker", label: "Autotanque" },
  { value: "bus", label: "Autocarro" },
  { value: "ambulance", label: "Ambulância" },
  { value: "other", label: "Outra viatura rodoviária" },
];

type PointTarget = "origin" | "destination";

export function RoutePlanner({ scenarioId, snapshot, plan, origin, destination, activeTarget,
  onOriginChange, onDestinationChange, onPickTarget, onRouteChange, onManageUnits,
  onClose, onSaved, onDeleted, onAssigned, readOnly = false,
}: {
  scenarioId: string;
  snapshot: MobilitySnapshot;
  plan?: RoutePlan;
  origin?: [number, number];
  destination?: [number, number];
  activeTarget: PointTarget | null;
  onOriginChange: (value: [number, number]) => void;
  onDestinationChange: (value: [number, number]) => void;
  onPickTarget: (value: PointTarget | null) => void;
  onRouteChange: (value?: RouteAssessment) => void;
  onManageUnits: () => void;
  onClose: () => void;
  onSaved: (value: RoutePlan) => void;
  onDeleted: () => void;
  onAssigned: (value: Movement) => void;
  readOnly?: boolean;
}) {
  const [purpose, setPurpose] = useState(plan?.purpose || "");
  const [originName, setOriginName] = useState(plan?.origin.name || "");
  const [destinationName, setDestinationName] = useState(plan?.destination.name || "");
  const [vehicleClass, setVehicleClass] = useState<RoadVehicleClass>(plan?.vehicle_class || "light");
  const [departure, setDeparture] = useState(() => localDateTime(plan ? new Date(plan.departure_at) : new Date()));
  const [route, setRoute] = useState<RouteAssessment | undefined>(plan?.route);
  const [freshPreview, setFreshPreview] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [originValid, setOriginValid] = useState(Boolean(origin));
  const [destinationValid, setDestinationValid] = useState(Boolean(destination));
  const [unitId, setUnitId] = useState("");
  const [assignmentRoute, setAssignmentRoute] = useState<RouteAssessment>();
  const [originAck, setOriginAck] = useState(false);
  const [suitabilityAck, setSuitabilityAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const locked = readOnly || Boolean(plan?.assigned_movement_id);
  const pointsKey = JSON.stringify([origin, destination]);
  const previousPoints = useRef(pointsKey);
  const available = snapshot.units.filter((unit) => unit.status === "available" && unit.latest_location &&
    unitCategory(unit, snapshot.vehicles) === "terrestrial" &&
    snapshot.vehicles.some((vehicle) => vehicle.id === unit.vehicle_id && vehicle.available !== false));
  const importedCount = snapshot.units.filter((unit) => unit.import_provenance).length;
  const unit = available.find((item) => item.id === unitId);
  const vehicle = snapshot.vehicles.find((item) => item.id === unit?.vehicle_id);
  const originNeedsAck = Boolean(unit?.latest_location &&
    (Date.now() - Date.parse(unit.latest_location.observed_at) > 15 * 60_000 ||
      (unit.latest_location.accuracy_m || 0) > 100));

  useNavigationGuard((to) => {
    if (to.kind === "mobility" && to.scenarioId === scenarioId && to.tab === "map") return true;
    if (busy) { setError("Aguarde a conclusão da operação antes de sair."); return false; }
    return !dirty || confirmDiscard();
  }, dirty);
  function invalidate() {
    setRoute(undefined);
    setFreshPreview(false);
    setAssignmentRoute(undefined);
    setOriginAck(false);
    setSuitabilityAck(false);
    setDirty(true);
    onRouteChange(undefined);
  }

  useEffect(() => {
    if (previousPoints.current === pointsKey) return;
    previousPoints.current = pointsKey;
    invalidate();
  }, [pointsKey]);

  function namedPoint(name: string, point: [number, number]): RouteLocation {
    return { name: name.trim() || `Ponto ${point[1].toFixed(5)}, ${point[0].toFixed(5)}`, coordinates: point };
  }

  function formValues() {
    const start = origin || null;
    const end = destination || null;
    if (!purpose.trim() || !originValid || !destinationValid ||
        !validCoordinates(start) || !validCoordinates(end) ||
        !departure || Number.isNaN(Date.parse(departure))) {
      setError("Indique o objetivo, dois pontos válidos e a hora de partida.");
      return null;
    }
    return {
      purpose: purpose.trim(), origin: namedPoint(originName, start),
      destination: namedPoint(destinationName, end),
      departure_at: new Date(departure).toISOString(), vehicle_class: vehicleClass,
    };
  }

  async function preview() {
    const values = formValues();
    if (!values) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.mobilityRoute(scenarioId, { ...values, alternatives: 2 });
      setRoute(result);
      onRouteChange(result);
      setFreshPreview(result.status !== "unavailable");
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    const values = formValues();
    if (!values || !route?.preview_signature || !freshPreview || route.status === "unavailable") {
      setError("Calcule o percurso antes de guardar o plano.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const saved = await api.saveRoutePlan(scenarioId, {
        ...values, preview_signature: route.preview_signature, expected_revision: plan?.revision,
      }, plan?.id);
      setDirty(false);
      onSaved(saved);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    if (!plan || !window.confirm("Descartar este plano de percurso?")) return;
    setBusy(true);
    setError("");
    try {
      await api.deleteRoutePlan(scenarioId, plan);
      onDeleted();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function previewAssignment() {
    if (!plan || dirty || !unit?.latest_location || !vehicle) return;
    if (originNeedsAck && !originAck) {
      setError("Confirme a origem da unidade porque a localização está desatualizada ou é imprecisa.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api.mobilityRoute(scenarioId, {
        origin: { name: unit.callsign, coordinates: unit.latest_location.coordinates },
        destination: plan.destination, vehicle_id: vehicle.id,
        departure_at: plan.departure_at, alternatives: 2,
      });
      setAssignmentRoute(result);
      setSuitabilityAck(false);
      onRouteChange(result);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function assign() {
    if (!plan || !unit?.latest_location || !vehicle || !assignmentRoute?.preview_signature ||
        assignmentRoute.status === "unavailable") return;
    setBusy(true);
    setError("");
    try {
      onAssigned(await api.createMovement(scenarioId, {
        unit_id: unit.id, vehicle_id: vehicle.id, purpose: plan.purpose,
        origin: { name: unit.callsign, coordinates: unit.latest_location.coordinates },
        destination: plan.destination, departure_at: plan.departure_at,
        preview_signature: assignmentRoute.preview_signature,
        suitability_acknowledged: suitabilityAck,
        dispatcher_contact: unit.contact, notes: "",
        route_plan_id: plan.id, route_plan_revision: plan.revision,
      }));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  function pointFields(target: PointTarget, value: [number, number] | undefined,
    name: string, setName: (value: string) => void, setPoint: (value: [number, number]) => void,
    setValid: (value: boolean) => void) {
    return <fieldset>
      <legend>{target === "origin" ? "1 · Origem" : "2 · Destino"}</legend>
      <Button variant={activeTarget === target ? "primary" : "secondary"} size="sm"
        disabled={locked} onClick={() => onPickTarget(activeTarget === target ? null : target)}>
        {activeTarget === target ? "Clique no mapa…" : "Escolher no mapa"}
      </Button>
      <CoordinateFields value={value || null} onCommit={setPoint} onValidityChange={setValid}
        onEdit={invalidate} disabled={locked} />
      <label><span>Nome do ponto <small className="route-optional">(opcional)</small></span>
        <input value={name} disabled={locked} onChange={(event) => { setName(event.target.value); invalidate(); }}
          placeholder="Ex.: posto de comando" />
      </label>
      {value && <Typography as="small" variant="small">Ponto selecionado: {value[1].toFixed(5)}, {value[0].toFixed(5)}</Typography>}
    </fieldset>;
  }

  return <Card density="compact" shadow="none" className="mobility-panel route-planner">
    <Button variant="ghost" aria-label="Fechar painel" className="panel-close" onClick={onClose}>×</Button>
    <Typography as="span" variant="label" className="eyebrow">Plano de percurso</Typography>
    <Typography as="h2" variant="h3">{plan ? "Rever plano" : "Planear percurso"}</Typography>
    <label>Objetivo
      <input value={purpose} disabled={locked} onChange={(event) => { setPurpose(event.target.value); invalidate(); }}
        placeholder="Ex.: controlar acesso à aldeia" />
    </label>
    {pointFields("origin", origin, originName, setOriginName, onOriginChange, setOriginValid)}
    {pointFields("destination", destination, destinationName, setDestinationName, onDestinationChange, setDestinationValid)}
    <fieldset>
      <legend>3 · Tipo de viatura e partida</legend>
      <label>Tipo de viatura
        <select value={vehicleClass} disabled={locked} onChange={(event) => {
          setVehicleClass(event.target.value as RoadVehicleClass); invalidate();
        }}>
          {vehicleTypes.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
        </select>
      </label>
      <Typography as="small" variant="small">Estimativa para este tipo de viatura. Dimensões e peso ainda não foram confirmados.</Typography>
      <label>Partida
        <input type="datetime-local" value={departure} disabled={locked} onChange={(event) => {
          setDeparture(event.target.value); invalidate();
        }} />
      </label>
    </fieldset>
    <fieldset>
      <legend>4 · Rever percurso</legend>
      {!locked && <Button variant="primary" className="full" disabled={busy} onClick={() => void preview()}>
        {busy ? "A calcular…" : "Calcular percurso"}
      </Button>}
      {route && <Card density="compact" shadow="none" className={`route-assessment ${route.status}`}>
        {route.status === "unavailable" ? <strong>Percurso indisponível</strong> :
          <strong>{(route.selected?.distance_km || 0).toLocaleString("pt-PT")} km · {Math.round(route.selected?.duration_min || 0)} min</strong>}
        <span>{route.message}</span>
        {plan && !freshPreview && <small>Estimativa guardada em {new Date(plan.updated_at).toLocaleString("pt-PT")}; recalcule antes de alterar.</small>}
        {route.warnings?.map((warning) => <small key={warning}>{warning}</small>)}
        {route.selected?.unknown_constraints.map((warning) => <small key={warning}>{warning}</small>)}
      </Card>}
      {!locked && <Button variant="secondary" className="full"
        disabled={busy || !freshPreview || route?.status === "unavailable"} onClick={() => void save()}>
        {plan ? "Guardar alterações" : "Guardar plano"}
      </Button>}
    </fieldset>
    <Card density="compact" shadow="none" className="route-unit-summary">
      <strong>{importedCount ? `${importedCount} unidades importadas · ` : ""}{available.length} prontas para atribuição</strong>
      {importedCount > 0 && <Typography as="small" variant="small">Os registos do Fogos.pt são provisórios; só aparecem para atribuição depois de confirmar disponibilidade e localização.</Typography>}
      <Button variant="ghost" size="sm" onClick={onManageUnits}>Ver unidades</Button>
    </Card>
    {plan?.assigned_movement_id ? <Typography as="p" variant="small">Este plano já originou um movimento atribuído.</Typography> :
      plan && !locked && <fieldset>
        <legend>Atribuir movimento mais tarde</legend>
        {dirty ? <Typography as="p" variant="small">Guarde as alterações antes de atribuir uma unidade.</Typography> :
          available.length ? <>
            <label>Unidade pronta
              <select value={unitId} onChange={(event) => { setUnitId(event.target.value); setAssignmentRoute(undefined); setSuitabilityAck(false); setOriginAck(false); onRouteChange(route); }}>
                <option value="">Selecionar unidade</option>
                {available.map((item) => <option value={item.id} key={item.id}>{item.callsign} · {item.organisation}</option>)}
              </select>
            </label>
            {unit?.latest_location && <small>Origem real: {unit.latest_location.coordinates[1].toFixed(5)}, {unit.latest_location.coordinates[0].toFixed(5)} · {new Date(unit.latest_location.observed_at).toLocaleString("pt-PT")}</small>}
            {originNeedsAck && <label className="ack"><input type="checkbox" checked={originAck} onChange={(event) => setOriginAck(event.target.checked)} />Confirmo esta origem por rádio ou conhecimento operacional.</label>}
            <Button variant="secondary" className="full" disabled={busy || !unit} onClick={() => void previewAssignment()}>Calcular para esta unidade</Button>
            {assignmentRoute && <Card density="compact" shadow="none" className={`route-assessment ${assignmentRoute.status}`}>
              <strong>{assignmentRoute.status === "unavailable" ? "Percurso indisponível" : `${(assignmentRoute.selected?.distance_km || 0).toLocaleString("pt-PT")} km · ${Math.round(assignmentRoute.selected?.duration_min || 0)} min`}</strong>
              <span>{assignmentRoute.message}</span>
              {assignmentRoute.warnings?.map((warning) => <small key={warning}>{warning}</small>)}
              {assignmentRoute.selected?.unknown_constraints.map((warning) => <small key={warning}>{warning}</small>)}
            </Card>}
            {assignmentRoute?.status === "unknown" && <label className="ack"><input type="checkbox" checked={suitabilityAck} onChange={(event) => setSuitabilityAck(event.target.checked)} />Confirmo o ponto de acesso e as limitações desconhecidas.</label>}
            {assignmentRoute && assignmentRoute.status !== "unavailable" && <Button variant="primary" className="full"
              disabled={busy || (assignmentRoute.status === "unknown" && !suitabilityAck)} onClick={() => void assign()}>Atribuir movimento</Button>}
          </> : <Typography as="p" variant="small">Nenhuma unidade está pronta. O plano pode ser usado sem atribuição.</Typography>}
      </fieldset>}
    {plan && !locked && <Button variant="ghost" disabled={busy} onClick={() => void discard()}>Descartar plano</Button>}
    {error && <Typography as="p" variant="small" role="alert" className="inline-error">{error}</Typography>}
  </Card>;
}

function localDateTime(value: Date) {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : String(reason);
}
