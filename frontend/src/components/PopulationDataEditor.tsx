import { confirmDiscard, useNavigationGuard } from "../navigation";
import { Button, Card, Typography } from "./ui";
import { useState } from "react";
import type {
  ScenarioPoint,
  ScenarioWorkspace,
  VehicleProfile,
} from "../types";

export function PopulationDataEditor({
  scenario,
  points,
  vehicle,
  dirty,
  saving,
  onPoints,
  onVehicle,
  onSave,
}: {
  scenario: ScenarioWorkspace;
  points: ScenarioPoint[];
  vehicle: VehicleProfile;
  dirty: boolean;
  saving: boolean;
  onPoints: (value: ScenarioPoint[]) => void;
  onVehicle: (value: VehicleProfile) => void;
  onSave: () => void;
}) {
  const [existingId, setExistingId] = useState("");
  const [name, setName] = useState("");
  const [longitude, setLongitude] = useState("");
  const [latitude, setLatitude] = useState("");
  const [role, setRole] = useState<"origin" | "reception">("origin");
  const [error, setError] = useState("");
  const pointDraft = Boolean(existingId || name || longitude || latitude);
  useNavigationGuard((to) => to.kind === "decisions" && to.scenarioId === scenario.id && to.tab === "data" || !pointDraft || confirmDiscard(), pointDraft);
  const available = scenario.points.filter(
    (point) =>
      !points.some((value) => value.id === point.id) &&
      point.kind !== "water_point",
  );
  function add() {
    const selected = available.find((point) => point.id === existingId);
    if (selected) {
      onPoints([...points, { ...selected, population_role: role }]);
      setExistingId("");
      setError("");
      return;
    }
    const lon = Number(longitude),
      lat = Number(latitude);
    if (
      !name.trim() ||
      !longitude.trim() ||
      !latitude.trim() ||
      !Number.isFinite(lon) ||
      !Number.isFinite(lat) ||
      lon < -180 ||
      lon > 180 ||
      lat < -90 ||
      lat > 90
    ) {
      setError("Indique nome e coordenadas válidas.");
      return;
    }
    onPoints([
      ...points,
      {
        id: crypto.randomUUID().slice(0, 12),
        kind: role === "reception" ? "shelter" : "custom",
        name: name.trim(),
        coordinates: [lon, lat],
        description: "Ponto de acesso para planeamento",
        notes: "",
        source: "manual",
        data_status: "unverified",
        population_role: role,
        population_count: null,
      },
    ]);
    setName("");
    setLongitude("");
    setLatitude("");
    setError("");
  }
  return (
    <section className="population-editor">
      <Typography as="h3" variant="h3">
        Pontos de apoio à população
      </Typography>
      <Typography as="p" variant="body">
        Defina entradas rodoviárias de origens e pontos de receção. Estes dados
        são pressupostos do cenário; não contêm registos pessoais.
      </Typography>
      {points.map((point) => (
        <Card
          density="compact"
          shadow="none"
          className="population-edit-row"
          key={point.id}
        >
          <label>
            Nome
            <input
              value={point.name}
              onChange={(event) =>
                onPoints(
                  points.map((value) =>
                    value.id === point.id
                      ? { ...value, name: event.target.value }
                      : value,
                  ),
                )
              }
            />
          </label>
          <label>
            Função
            <select
              value={point.population_role || "origin"}
              onChange={(event) =>
                onPoints(
                  points.map((value) =>
                    value.id === point.id
                      ? {
                          ...value,
                          population_role: event.target.value as
                            | "origin"
                            | "reception",
                        }
                      : value,
                  ),
                )
              }
            >
              <option value="origin">Origem</option>
              <option value="reception">Receção</option>
            </select>
          </label>
          <label>
            Longitude
            <input
              type="number"
              step="any"
              value={point.coordinates[0]}
              onChange={(event) =>
                onPoints(
                  points.map((value) =>
                    value.id === point.id
                      ? {
                          ...value,
                          coordinates: [
                            Number(event.target.value),
                            value.coordinates[1],
                          ],
                        }
                      : value,
                  ),
                )
              }
            />
          </label>
          <label>
            Latitude
            <input
              type="number"
              step="any"
              value={point.coordinates[1]}
              onChange={(event) =>
                onPoints(
                  points.map((value) =>
                    value.id === point.id
                      ? {
                          ...value,
                          coordinates: [
                            value.coordinates[0],
                            Number(event.target.value),
                          ],
                        }
                      : value,
                  ),
                )
              }
            />
          </label>
          {point.population_role === "origin" && (
            <label>
              Pessoas indicadas
              <input
                type="number"
                min="0"
                value={point.population_count ?? ""}
                onChange={(event) =>
                  onPoints(
                    points.map((value) =>
                      value.id === point.id
                        ? {
                            ...value,
                            population_count:
                              event.target.value === ""
                                ? null
                                : Number(event.target.value),
                          }
                        : value,
                    ),
                  )
                }
              />
            </label>
          )}
          <label>
            Data da origem
            <input
              placeholder="AAAA-MM-DD"
              value={point.source_updated_at || ""}
              onChange={(event) =>
                onPoints(
                  points.map((value) =>
                    value.id === point.id
                      ? {
                          ...value,
                          source_updated_at: event.target.value || null,
                        }
                      : value,
                  ),
                )
              }
            />
          </label>
          <Typography as="small" variant="small">
            {point.source === "demo" ? "Exercício fictício" : point.source} ·{" "}
            {point.source_updated_at || "data de origem não indicada"}
          </Typography>
          <Button
            variant="secondary"
            type="button"
            onClick={() =>
              onPoints(points.filter((value) => value.id !== point.id))
            }
          >
            Retirar da avaliação
          </Button>
        </Card>
      ))}
      <Typography as="h4" variant="h3">
        Adicionar ponto
      </Typography>
      <Card density="compact" shadow="none" className="population-edit-row">
        <label>
          Função
          <select
            value={role}
            onChange={(event) =>
              setRole(event.target.value as "origin" | "reception")
            }
          >
            <option value="origin">Origem</option>
            <option value="reception">Receção</option>
          </select>
        </label>
        <label>
          Usar ponto existente
          <select
            value={existingId}
            onChange={(event) => setExistingId(event.target.value)}
          >
            <option value="">Criar novo ponto</option>
            {available.map((point) => (
              <option key={point.id} value={point.id}>
                {point.name}
              </option>
            ))}
          </select>
        </label>
        {!existingId && (
          <>
            <label>
              Nome
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              Longitude
              <input
                type="number"
                step="any"
                value={longitude}
                onChange={(event) => setLongitude(event.target.value)}
              />
            </label>
            <label>
              Latitude
              <input
                type="number"
                step="any"
                value={latitude}
                onChange={(event) => setLatitude(event.target.value)}
              />
            </label>
          </>
        )}
        <Button variant="secondary" type="button" onClick={add}>
          Adicionar à avaliação
        </Button>
        {error && (
          <Typography as="p" variant="body" role="alert">
            {error}
          </Typography>
        )}
      </Card>
      <Typography as="h3" variant="h3">
        Viatura ligeira para testar o acesso
      </Typography>
      <Typography as="p" variant="body">
        Uma viatura de circulação rodoviária é usada para todos os percursos de
        apoio à população. Dimensões em branco são pressupostos não verificados.
      </Typography>
      <Card density="compact" shadow="none" className="population-edit-row">
        {(["width_m", "height_m", "weight_t"] as const).map((key, index) => (
          <label key={key}>
            {["Largura (m)", "Altura (m)", "Peso (t)"][index]}
            <input
              type="number"
              min="0"
              step="any"
              value={vehicle[key] ?? ""}
              onChange={(event) =>
                onVehicle({
                  ...vehicle,
                  [key]:
                    event.target.value === ""
                      ? null
                      : Number(event.target.value),
                })
              }
            />
          </label>
        ))}
      </Card>
      <Button
        variant="primary"
        type="button"
        className="ds-full"
        disabled={saving || !dirty}
        onClick={onSave}
      >
        {saving ? "A guardar…" : "Guardar pontos no cenário"}
      </Button>
      <Typography as="p" variant="small" className="decision-note">
        Os resultados já guardados usam o seu próprio instantâneo e não mudam
        com esta edição.
      </Typography>
    </section>
  );
}
