import { Box, Typography } from "./ui";
import { formatNumber, t } from "../locale";
import { useEffect, useState } from "react";
import { api } from "../api";
import type {
  AreaPreparationEstimate,
  AreaPreparationRequest,
  CellSizeM,
} from "../types";

const margins: Record<CellSizeM, (5 | 10 | 25)[]> = {
  30: [5, 10, 25],
  20: [5, 10],
  15: [5, 10],
  10: [5],
};

export function marginAllowed(cellSize: CellSizeM, fireMargin: 5 | 10 | 25) {
  return margins[cellSize].includes(fireMargin);
}

export function useAreaEstimate(request: AreaPreparationRequest) {
  const [estimate, setEstimate] = useState<AreaPreparationEstimate>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const key = JSON.stringify({ ...request, acknowledge_high_cost: false });

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setEstimate(undefined);
    const timer = window.setTimeout(() => {
      api
        .estimateArea(
          { ...request, acknowledge_high_cost: false },
          controller.signal,
        )
        .then(setEstimate)
        .catch((reason) => {
          if (!controller.signal.aborted)
            setError(
              reason instanceof Error
                ? reason.message
                : "Unable to estimate landscape size",
            );
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [key]);

  return { estimate, loading, error, key };
}

export function LandscapeControls({
  cellSize,
  fireMargin,
  estimate,
  loading,
  acknowledged,
  onCellSize,
  onFireMargin,
  onAcknowledged,
  disabled = false,
}: {
  cellSize: CellSizeM;
  fireMargin: 5 | 10 | 25;
  estimate?: AreaPreparationEstimate;
  loading: boolean;
  acknowledged: boolean;
  onCellSize: (value: CellSizeM) => void;
  onFireMargin: (value: 5 | 10 | 25) => void;
  onAcknowledged: (value: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <>
      <details>
        <summary>Definições avançadas · {cellSize} m · margem de {fireMargin} km</summary>
        <Box className="form-field-grid">
          <label>
            {t("Simulation cell size")}
            <select
              disabled={disabled}
              value={cellSize}
              onChange={(event) =>
                onCellSize(Number(event.target.value) as CellSizeM)
              }
            >
              <option value="30">{t("30 m — Recommended")}</option>
              <option value="20">20 m</option>
              <option value="15">15 m</option>
              <option value="10">10 m</option>
            </select>
          </label>
          <label>
            {t("Fire margin")}
            <select
              disabled={disabled}
              value={fireMargin}
              onChange={(event) =>
                onFireMargin(Number(event.target.value) as 5 | 10 | 25)
              }
            >
              <option value="5">5 km</option>
              <option value="10" disabled={!margins[cellSize].includes(10)}>
                10 km
                {margins[cellSize].includes(10)
                  ? ""
                  : ` — unavailable at ${cellSize} m`}
              </option>
              <option value="25" disabled={!margins[cellSize].includes(25)}>
                25 km
                {margins[cellSize].includes(25)
                  ? ""
                  : ` — unavailable at ${cellSize} m`}
              </option>
            </select>
          </label>
        </Box>
        <Typography as="small" variant="small">
          {t(
            "Cell size controls simulation resolution, not map quality. Elevation originates at 30 m; land cover originates at 10 m.",
          )}
        </Typography>
      </details>
      <Box
        className={
          estimate && (!estimate.allowed || estimate.cost_level !== "normal")
            ? "engine-warning landscape-estimate"
            : "landscape-estimate"
        }
      >
        {loading ? (
          <Typography as="p" variant="body">
            {t("Estimating landscape size…")}
          </Typography>
        ) : estimate ? (
          <>
            <strong>
              {formatNumber(estimate.grid_columns, 0)} ×{" "}
              {formatNumber(estimate.grid_rows, 0)} {t("cells ·")}{" "}
              {formatNumber(estimate.cell_count, 0)} {t("total")}
            </strong>
            <span>
              {formatNumber(estimate.area_km2)} km² ·{" "}
              {costLabel(estimate.cost_level)}
            </span>
            {!estimate.allowed && (
              <Typography as="p" variant="body">
                {estimate.blocking_reason}
              </Typography>
            )}
            {estimate.requires_acknowledgement && (
              <label className="radio">
                <input
                  type="checkbox"
                  disabled={disabled}
                  checked={acknowledged}
                  onChange={(event) => onAcknowledged(event.target.checked)}
                />
                {t(
                  "I understand that this high-cost landscape may take considerably longer and use substantially more memory.",
                )}
              </label>
            )}
          </>
        ) : null}

      </Box>
    </>
  );
}

function costLabel(value: AreaPreparationEstimate["cost_level"]) {
  return {
    normal: "Custo de processamento normal",
    moderate: "Custo de processamento moderado",
    high: "Custo de processamento elevado",
    very_high: "Custo de processamento muito elevado",
    blocked: "Custo de processamento não suportado",
  }[value];
}
