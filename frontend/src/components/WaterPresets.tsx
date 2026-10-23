import { Box, Button, Card, Typography } from "./ui";
import { t } from "../locale";
import { useState } from "react";
import type { FeatureCollection, ScenarioPoint } from "../types";

type Props = {
  catalog: FeatureCollection;
  points: ScenarioPoint[];
  importing: boolean;
  onImport: (ids: string[]) => void;
};

export function WaterPresets({ catalog, points, importing, onImport }: Props) {
  const [selected, setSelected] = useState("");
  const available = catalog.features.filter(
    (feature) =>
      !points.some(
        (point) =>
          point.source === (feature.properties?.source || "openstreetmap") &&
          point.external_id === feature.properties?.external_id,
      ),
  );
  const selectedFeature =
    available.find((feature) => feature.properties?.external_id === selected) ||
    available[0];
  const p = selectedFeature?.properties;
  const selectedId = String(p?.external_id || "");
  return (
    <Card density="compact" shadow="none" className="water-presets">
      <Typography as="h3" variant="h3">
        {t("Guimarães water presets")}
      </Typography>
      <Typography as="p" variant="body">
        {catalog.features.length} {t("recorded locations ·")} {available.length}{" "}
        {t("available to add")}
      </Typography>
      <Typography as="p" variant="body">
        {t(
          "Historical records; current availability is unknown. All presets fall within the configured map area.",
        )}
      </Typography>
      {available.length > 0 ? (
        <>
          <label>
            {t("Water-point preset")}
            <select
              value={selectedId}
              onChange={(event) => setSelected(event.target.value)}
            >
              {available.map((feature) => (
                <option
                  key={String(feature.properties?.external_id)}
                  value={String(feature.properties?.external_id)}
                >
                  {String(feature.properties?.name || t("Water point"))}
                  {feature.properties?.parish
                    ? ` · ${feature.properties.parish}`
                    : ""}
                </option>
              ))}
            </select>
          </label>
          <Typography as="p" variant="body">
            {String(p?.description || "")}
          </Typography>
          <Typography as="p" variant="body">
            {String(p?.notes || "Localização OpenStreetMap; não verificada.")}
          </Typography>
          {p?.source_url && (
            <a href={String(p.source_url)} target="_blank" rel="noreferrer">
              {t("View ICNF source")}
            </a>
          )}
          <Box className="point-actions">
            <Button
              variant="secondary"
              disabled={importing}
              onClick={() => onImport([selectedId])}
            >
              {t("Add preset")}
            </Button>
            <Button
              variant="secondary"
              disabled={importing}
              onClick={() =>
                onImport(
                  available.map((feature) =>
                    String(feature.properties?.external_id),
                  ),
                )
              }
            >
              {t("Add all")} {available.length}
            </Button>
          </Box>
        </>
      ) : (
        <Typography as="p" variant="body">
          {catalog.features.length
            ? "Todos os pontos predefinidos já estão nesta ocorrência."
            : "Não existem pontos predefinidos disponíveis."}
        </Typography>
      )}
    </Card>
  );
}
