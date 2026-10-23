import { Box, Button, Card, Typography } from "./ui";
import { t } from "../locale";
import { useState, type ReactNode } from "react";
import type { PointKind, ScenarioPoint } from "../types";

const pointLabels: Record<PointKind, string> = {
  water_point: "Water point",
  response_base: "Response base",
  asset: "Priority asset",
  hazard: "Hazard",
  staging_area: "Staging area",
  access_control: "Access-control point",
  shelter: "Shelter",
  delivery_point: "Delivery point",
  custom: "Custom point",
};

type Props = {
  points: ScenarioPoint[];
  kinds: PointKind[];
  waterPresets?: ReactNode;
  placementLabel?: string;
  onShowPoints: () => void;
  onPointPlacement: (kind: PointKind) => void;
  onPointMove: (id: string) => void;
  onPointUpdate: (point: ScenarioPoint) => void;
  onPointDelete: (id: string) => void;
};

export function PointsEditor(props: Props) {
  const [pointKind, setPointKind] = useState<PointKind>(props.kinds[0]);
  return (
    <section className="control-section points-editor">
      <Typography as="h2" variant="h3">
        {props.kinds.includes("water_point")
          ? t("Water sources and bases")
          : t("Assets and constraints")}
      </Typography>
      {props.waterPresets}
      {props.points.length > 0 && (
        <Button
          variant="secondary"
          className="ds-full"
          onClick={props.onShowPoints}
        >
          {t("Show all points on map")}
        </Button>
      )}
      <Box className="point-add">
        <select
          aria-label={t("Point type")}
          value={pointKind}
          onChange={(event) => setPointKind(event.target.value as PointKind)}
        >
          {props.kinds.map((kind) => (
            <option key={kind} value={kind}>
              {t(pointLabels[kind])}
            </option>
          ))}
        </select>
        <Button
          variant="secondary"
          className="ds-full"
          onClick={() => props.onPointPlacement(pointKind)}
        >
          {props.placementLabel || t("Place on map")}
        </Button>
      </Box>
      {props.points.length === 0 && (
        <Typography as="p" variant="small" className="empty-note">
          {t("Add a point to begin preparing this tool.")}
        </Typography>
      )}
      {props.points.map((point) => (
        <PointEditor
          key={point.id}
          point={point}
          kinds={props.kinds}
          onChange={props.onPointUpdate}
          onMove={() => props.onPointMove(point.id)}
          onDelete={() => props.onPointDelete(point.id)}
        />
      ))}
    </section>
  );
}

function PointEditor({
  point,
  onChange,
  onMove,
  onDelete,
  kinds,
}: {
  kinds: PointKind[];
  point: ScenarioPoint;
  onChange: (point: ScenarioPoint) => void;
  onMove: () => void;
  onDelete: () => void;
}) {
  return (
    <Card as="details" density="compact" shadow="none" className="point-card">
      <summary>
        <i className={`point-dot ${point.kind}`} />
        {point.name}
      </summary>
      <label>
        {t("Name")}
        <input
          value={point.name}
          onChange={(event) => onChange({ ...point, name: event.target.value })}
        />
      </label>
      <label>
        {t("Type")}
        <select
          value={point.kind}
          onChange={(event) => {
            const kind = event.target.value as PointKind;
            onChange({
              ...point,
              kind,
              water:
                kind === "water_point" ? point.water || defaultWater() : null,
              asset: kind === "asset" ? point.asset || { priority: 3 } : null,
            });
          }}
        >
          {kinds.map((kind) => (
            <option key={kind} value={kind}>
              {t(pointLabels[kind])}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("Description")}
        <textarea
          rows={2}
          value={point.description}
          onChange={(event) =>
            onChange({ ...point, description: event.target.value })
          }
        />
      </label>
      <label>
        {t("Notes")}
        <textarea
          rows={2}
          value={point.notes}
          onChange={(event) =>
            onChange({ ...point, notes: event.target.value })
          }
        />
      </label>
      {point.kind === "asset" && (
        <label>
          {t("Priority")}
          <select
            value={point.asset?.priority || 3}
            onChange={(event) =>
              onChange({
                ...point,
                asset: { priority: Number(event.target.value) },
              })
            }
          >
            {[5, 4, 3, 2, 1].map((priority) => (
              <option key={priority} value={priority}>
                {priority}
                {priority === 5
                  ? " · mais alta"
                  : priority === 1
                    ? " · mais baixa"
                    : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      {point.kind === "water_point" && point.water && (
        <Box className="water-fields">
          <Box className="two-col">
            <label>
              {t("Source")}
              <select
                value={point.water.source_type}
                onChange={(event) =>
                  onChange({
                    ...point,
                    water: {
                      ...point.water!,
                      source_type: event.target.value as NonNullable<
                        ScenarioPoint["water"]
                      >["source_type"],
                    },
                  })
                }
              >
                <option value="hydrant">{t("Hydrant")}</option>
                <option value="tank">{t("Tank")}</option>
                <option value="reservoir">{t("Reservoir")}</option>
                <option value="pond">{t("Pond")}</option>
                <option value="other">{t("Other")}</option>
              </select>
            </label>
            <label>
              {t("Availability")}
              <select
                value={point.water.availability}
                onChange={(event) =>
                  onChange({
                    ...point,
                    water: {
                      ...point.water!,
                      availability: event.target.value as NonNullable<
                        ScenarioPoint["water"]
                      >["availability"],
                    },
                  })
                }
              >
                <option value="unknown">{t("Unknown")}</option>
                <option value="available">{t("Available")}</option>
                <option value="unavailable">{t("Unavailable")}</option>
              </select>
            </label>
          </Box>
          <Box className="two-col">
            <label>
              {t("Capacity m³")}
              <input
                type="number"
                min="0"
                value={point.water.capacity_m3 ?? ""}
                onChange={(event) =>
                  onChange({
                    ...point,
                    water: {
                      ...point.water!,
                      capacity_m3:
                        event.target.value === ""
                          ? null
                          : Number(event.target.value),
                    },
                  })
                }
              />
            </label>
            <label>
              {t("Flow L/min")}
              <input
                type="number"
                min="0"
                value={point.water.flow_l_min ?? ""}
                onChange={(event) =>
                  onChange({
                    ...point,
                    water: {
                      ...point.water!,
                      flow_l_min:
                        event.target.value === ""
                          ? null
                          : Number(event.target.value),
                    },
                  })
                }
              />
            </label>
          </Box>
          <Box className="two-col">
            <label>
              {t("Supply model")}
              <select
                value={point.water.supply_class || "unknown"}
                onChange={(event) =>
                  onChange({
                    ...point,
                    water: {
                      ...point.water!,
                      supply_class: event.target.value as
                        | "finite"
                        | "continuous"
                        | "unknown",
                    },
                  })
                }
              >
                <option value="unknown">{t("Unknown")}</option>
                <option value="finite">{t("Finite")}</option>
                <option value="continuous">{t("Continuous")}</option>
              </select>
            </label>
            <label>
              {t("Available litres")}
              <input
                type="number"
                min="0"
                value={point.water.available_volume_l ?? ""}
                onChange={(event) =>
                  onChange({
                    ...point,
                    water: {
                      ...point.water!,
                      available_volume_l:
                        event.target.value === ""
                          ? null
                          : Number(event.target.value),
                    },
                  })
                }
              />
            </label>
          </Box>
          <Box className="two-col">
            <label>
              {t("Shared flow L/min")}
              <input
                type="number"
                min="0"
                value={point.water.shared_flow_l_min ?? ""}
                onChange={(event) =>
                  onChange({
                    ...point,
                    water: {
                      ...point.water!,
                      shared_flow_l_min:
                        event.target.value === ""
                          ? null
                          : Number(event.target.value),
                    },
                  })
                }
              />
            </label>
            <label>
              {t("Filling positions")}
              <input
                type="number"
                min="1"
                value={point.water.filling_positions ?? ""}
                placeholder={t("Assume 1")}
                onChange={(event) =>
                  onChange({
                    ...point,
                    water: {
                      ...point.water!,
                      filling_positions:
                        event.target.value === ""
                          ? null
                          : Number(event.target.value),
                    },
                  })
                }
              />
            </label>
          </Box>
          <label>
            {t("Filling setup time (min)")}
            <input
              type="number"
              min="0"
              value={point.water.setup_time_min ?? ""}
              onChange={(event) =>
                onChange({
                  ...point,
                  water: {
                    ...point.water!,
                    setup_time_min:
                      event.target.value === ""
                        ? null
                        : Number(event.target.value),
                  },
                })
              }
            />
          </label>
          <label>
            {t("Access notes")}
            <textarea
              rows={2}
              value={point.water.access_notes}
              onChange={(event) =>
                onChange({
                  ...point,
                  water: { ...point.water!, access_notes: event.target.value },
                })
              }
            />
          </label>
          <label>
            {t("Verification")}
            <select
              value={point.water.verification_status}
              onChange={(event) => {
                const status = event.target.value as NonNullable<
                  ScenarioPoint["water"]
                >["verification_status"];
                onChange({
                  ...point,
                  data_status: status,
                  water: { ...point.water!, verification_status: status },
                });
              }}
            >
              <option value="unverified">{t("Unverified")}</option>
              <option value="reported">{t("Reported")}</option>
              <option value="verified">{t("Verified")}</option>
            </select>
          </label>
        </Box>
      )}
      <Typography as="p" variant="small" className="point-source">
        {t("Source:")}{" "}
        {point.source === "openstreetmap"
          ? `OpenStreetMap · ${point.external_id}`
          : point.source === "icnf"
            ? `ICNF · ${point.external_id}`
            : point.source}
        {point.source_url && (
          <>
            {" "}
            ·{" "}
            <a href={point.source_url} target="_blank" rel="noreferrer">
              {t("Source record layer")}
            </a>
          </>
        )}
        {point.source === "icnf" && (
          <>
            <br />
            {t("Source updated:")}{" "}
            {point.source_updated_at || t("not specified")}
          </>
        )}
      </Typography>
      <Box className="point-actions">
        <Button variant="secondary" onClick={onMove}>
          {t("Move")}
        </Button>
        <Button variant="outline" intent="danger" onClick={onDelete}>
          {t("Delete")}
        </Button>
      </Box>
    </Card>
  );
}

function defaultWater() {
  return {
    source_type: "other" as const,
    availability: "unknown" as const,
    capacity_m3: null,
    flow_l_min: null,
    access_notes: "",
    verification_status: "unverified" as const,
    supply_class: "unknown" as const,
    available_volume_l: null,
    shared_flow_l_min: null,
    filling_positions: null,
    setup_time_min: null,
  };
}
