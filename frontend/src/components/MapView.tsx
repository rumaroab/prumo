import { MapResize } from "./MapResize";
import { Box, Button } from "./ui";
import { statusLabel, t } from "../locale";
import { useEffect } from "react";
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Polyline,
  Popup,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import { CircleMarker as LeafletCircleMarker, type PathOptions } from "leaflet";
import type {
  FeatureCollection,
  Filter,
  Scenario,
  ScenarioPoint,
} from "../types";
import {
  filterRoads,
  pointColor,
  pointLabel,
  roadAppearance,
  roadPopup,
} from "./mapStyles";

export type MapViewProps = {
  bounds: [[number, number], [number, number]];
  scenario: Scenario;
  roads?: FeatureCollection;
  fire?: FeatureCollection;
  routes?: FeatureCollection;
  containment?: FeatureCollection;
  draftContainment?: [number, number][];
  minute: number;
  forecast: number;
  filter: Filter;
  placing: boolean;
  points: ScenarioPoint[];
  showPointsKey: number;
  showPoints: boolean;
  showFire: boolean;
  showIgnition?: boolean;
  showRoads: boolean;
  showBasemap: boolean;
  onIgnition: (position: [number, number]) => void;
  onPointSelect?: (point: ScenarioPoint) => void;
  onPointMove?: (id: string) => void;
  onPointDelete?: (id: string) => void;
  onRoadSelect?: (feature: GeoJSON.Feature) => void;
  onContainmentClick?: (position: [number, number]) => void;
  closedSegmentIds?: string[];
  externalLayers?: { id: string; label: string; data: FeatureCollection }[];
};

export function MapView(props: MapViewProps) {
  const roads =
    props.roads &&
    filterRoads(props.roads, props.filter, props.minute, props.forecast);
  return (
    <Box className="map-frame">
      <LeafletMapView {...props} roads={roads} />
      <Box className="map-reference" aria-hidden="true">
        <span>WGS 84</span>
        <i />
        EPSG:4326
      </Box>
    </Box>
  );
}

function LeafletMapView(props: MapViewProps) {
  const roads =
    props.roads &&
    filterRoads(props.roads, props.filter, props.minute, props.forecast);
  return (
    <MapContainer
      bounds={props.bounds}
      boundsOptions={{ padding: [24, 24] }}
      preferCanvas
      zoomControl={false}
      className="map"
    >
      <MapResize />
      {props.showBasemap && (
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
      )}
      <MapClick
        active={props.placing}
        containmentActive={Boolean(props.onContainmentClick)}
        onIgnition={props.onIgnition}
        onContainment={props.onContainmentClick}
      />
      <PanTo
        position={[
          props.scenario.ignitions[0].coordinates[1],
          props.scenario.ignitions[0].coordinates[0],
        ]}
      />
      <FitPoints points={props.points} trigger={props.showPointsKey} />
      {props.showFire && props.fire && (
        <GeoJSON
          key={`fire-halo-${props.minute}`}
          data={props.fire}
          style={(feature) => {
            const probability = Number(feature?.properties?.probability || 1);
            return {
              className: "fire-halo",
              color:
                probability >= 0.9
                  ? "#ffb13b"
                  : probability >= 0.5
                    ? "#f45d48"
                    : "#c7355b",
              fillOpacity: 0,
              opacity: 0.3,
              weight: 7,
            };
          }}
        />
      )}
      {props.showFire && props.fire && (
        <GeoJSON
          key={`fire-${props.minute}`}
          data={props.fire}
          style={(feature) =>
            fireAppearance(Number(feature?.properties?.probability || 1))
          }
        />
      )}
      {props.externalLayers?.map((layer) => (
        <GeoJSON
          key={`${layer.id}-${layer.data.features.length}`}
          data={layer.data}
          pointToLayer={(_feature, latlng) =>
            new LeafletCircleMarker(latlng, {
              radius: 5,
              ...externalStyle(layer.id),
            })
          }
          style={() => externalStyle(layer.id)}
          onEachFeature={(feature, value) =>
            value.bindPopup(
              externalPopup(layer.label, feature.properties || {}),
            )
          }
        />
      ))}
      {props.showRoads && roads && (
        <GeoJSON
          key={`${props.filter}-${props.minute}-${props.forecast}-${roads.features.length}-${props.closedSegmentIds?.join("-")}`}
          data={roads}
          style={roadStyle(
            props.minute,
            props.forecast,
            props.closedSegmentIds,
          )}
          onEachFeature={(feature, layer) => {
            layer.bindPopup(roadPopup(feature));
            layer.on("click", () => props.onRoadSelect?.(feature));
          }}
        />
      )}
      {props.routes && (
        <GeoJSON
          key={JSON.stringify(
            props.routes.features.map((feature) => feature.properties?.label),
          )}
          data={props.routes}
          style={(feature) => ({
            color:
              feature?.properties?.label === "Withdrawal"
                ? "#7357a6"
                : feature?.properties?.label === "Primary"
                  ? "#087f5b"
                  : "#2473a6",
            weight: feature?.properties?.label === "Primary" ? 7 : 5,
            opacity: 0.9,
            dashArray:
              feature?.properties?.label === "Withdrawal" ? "9 6" : undefined,
          })}
          onEachFeature={(feature, layer) =>
            layer.bindPopup(
              `<strong>${escapeHtml(String(feature.properties?.label || "Percurso"))}</strong><br>${escapeHtml(statusLabel(String(feature.properties?.status || "")))}`,
            )
          }
        />
      )}
      {props.containment && (
        <GeoJSON
          key={JSON.stringify(
            props.containment.features.map((feature) => feature.properties?.id),
          )}
          data={props.containment}
          style={(feature) => ({
            color:
              feature?.properties?.source === "suggested"
                ? "#8b5cf6"
                : "#6d28d9",
            weight: 4,
            opacity: feature?.properties?.enabled === false ? 0.35 : 0.9,
            dashArray:
              feature?.properties?.source === "suggested" ? "8 5" : undefined,
          })}
          onEachFeature={(feature, layer) =>
            layer.bindPopup(
              `<strong>${escapeHtml(String(feature.properties?.name || "Linha de contenção"))}</strong><br>${escapeHtml(statusLabel(String(feature.properties?.source || "manual")))}`,
            )
          }
        />
      )}
      {props.draftContainment && props.draftContainment.length > 0 && (
        <Polyline
          positions={props.draftContainment.map((value) => [
            value[1],
            value[0],
          ])}
          pathOptions={{ color: "#6d28d9", weight: 4, dashArray: "5 5" }}
        />
      )}
      {props.showPoints &&
        props.points.map((point) => (
          <CircleMarker
            key={point.id}
            center={[point.coordinates[1], point.coordinates[0]]}
            radius={point.kind === "water_point" ? 8 : 7}
            pathOptions={{
              color: "#fff",
              fillColor: pointColor(point.kind),
              fillOpacity: 0.95,
              weight: 2,
            }}
            eventHandlers={{ click: () => props.onPointSelect?.(point) }}
          >
            <Tooltip direction="top" offset={[0, -7]}>
              {point.name}
            </Tooltip>
            <Popup>
              <strong>{point.name}</strong>
              <br />
              {pointLabel(point.kind)} · {statusLabel(point.data_status)}
              <br />
              {point.notes || "Ponto da ocorrência"}
              {point.source_url && (
                <>
                  <br />
                  <a href={point.source_url} target="_blank" rel="noreferrer">
                    {t("View source")}
                  </a>
                </>
              )}
              {(props.onPointMove || props.onPointDelete) && (
                <Box className="map-point-actions">
                  {props.onPointMove && (
                    <Button
                      variant="secondary"
                      type="button"
                      onClick={() => props.onPointMove?.(point.id)}
                    >
                      {t("Move")}
                    </Button>
                  )}
                  {props.onPointDelete && (
                    <Button
                      variant="outline"
                      intent="danger"
                      type="button"
                      onClick={() => {
                        if (
                          window.confirm(
                            `Eliminar “${point.name}”? As equipas e referências de planeamento associadas também serão removidas.`,
                          )
                        )
                          props.onPointDelete?.(point.id);
                      }}
                    >
                      {t("Delete")}
                    </Button>
                  )}
                </Box>
              )}
            </Popup>
          </CircleMarker>
        ))}
      {props.showIgnition !== false &&
        props.scenario.ignitions.map((ignition, index) => {
          const future = ignition.start_min > props.minute;
          return (
            <CircleMarker
              key={ignition.id}
              center={[ignition.coordinates[1], ignition.coordinates[0]]}
              radius={8}
              pathOptions={{
                color: "#fff",
                fillColor: future ? "#7a8580" : "#17211d",
                fillOpacity: future ? 0.65 : 1,
                weight: 2,
              }}
            >
              <Tooltip direction="top" offset={[0, -8]}>
                {index + 1}. {ignition.name} ·{" "}
                {ignition.start_min === 0
                  ? "início"
                  : `${ignition.start_min} min`}
                {future ? " · futura" : ""}
              </Tooltip>
            </CircleMarker>
          );
        })}
    </MapContainer>
  );
}

function externalStyle(id: string): PathOptions {
  if (id === "perimeter")
    return {
      color: "#28c7c7",
      fillColor: "#28c7c7",
      fillOpacity: 0.12,
      weight: 3,
      dashArray: "8 5",
    };
  if (id === "pyrocast")
    return {
      color: "#9c62d9",
      fillColor: "#9c62d9",
      fillOpacity: 0.08,
      weight: 2,
    };
  if (id === "aircraft")
    return {
      color: "#2387d9",
      fillColor: "#2387d9",
      fillOpacity: 0.8,
      weight: 3,
    };
  if (id === "firms")
    return {
      color: "#ff7b2c",
      fillColor: "#ff7b2c",
      fillOpacity: 0.6,
      weight: 2,
    };
  return {
    color: "#2f7f57",
    fillColor: "#2f7f57",
    fillOpacity: 0.1,
    weight: 2,
    dashArray: "6 4",
  };
}

function externalPopup(label: string, properties: Record<string, unknown>) {
  const details = [
    properties.name,
    properties.aircraft_type,
    properties.age_minutes == null
      ? null
      : `há ${Math.round(Number(properties.age_minutes))} min`,
    properties.hour == null
      ? null
      : `contorno acumulado até +${String(properties.hour)} h`,
    properties.source_time ||
      properties.observed_at ||
      properties.last_seen ||
      properties.type,
  ]
    .filter((value) => value != null && value !== "")
    .map((value) => escapeHtml(String(value)));
  return `<strong>${escapeHtml(label)}</strong>${details.length ? `<br>${details.join(" · ")}` : ""}`;
}
function escapeHtml(value: string) {
  return value.replace(
    /[&<>'"]/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[
        character
      ] || character,
  );
}

function MapClick({
  active,
  containmentActive,
  onIgnition,
  onContainment,
}: {
  active: boolean;
  containmentActive: boolean;
  onIgnition: (position: [number, number]) => void;
  onContainment?: (position: [number, number]) => void;
}) {
  useMapEvents({
    click: (event) => {
      const position: [number, number] = [event.latlng.lng, event.latlng.lat];
      if (containmentActive) onContainment?.(position);
      else if (active) onIgnition(position);
    },
  });
  return null;
}

function PanTo({ position }: { position: [number, number] }) {
  const map = useMap();
  useEffect(() => {
    map.panTo(position);
  }, [map, position[0], position[1]]);
  return null;
}

function FitPoints({
  points,
  trigger,
}: {
  points: ScenarioPoint[];
  trigger: number;
}) {
  const map = useMap();
  useEffect(() => {
    if (trigger && points.length)
      map.fitBounds(
        points.map(
          (point) =>
            [point.coordinates[1], point.coordinates[0]] as [number, number],
        ),
        { padding: [60, 60], maxZoom: 15 },
      );
  }, [map, trigger]);
  return null;
}

function roadStyle(
  minute: number,
  forecast: number,
  closedSegmentIds: string[] = [],
) {
  return (feature?: GeoJSON.Feature): PathOptions => {
    const value = roadAppearance(feature, minute, forecast, closedSegmentIds);
    return {
      color: value.color,
      weight: value.width,
      opacity: value.opacity,
      dashArray: value.dash?.join(" "),
    };
  };
}

function fireAppearance(probability: number): PathOptions {
  if (probability >= 0.9)
    return {
      className: "fire-footprint",
      color: "#ffe08a",
      fillColor: "#ffb13b",
      fillOpacity: 0.7,
      opacity: 0.95,
      weight: 1.6,
    };
  if (probability >= 0.5)
    return {
      className: "fire-footprint",
      color: "#ff9b68",
      fillColor: "#f45d48",
      fillOpacity: 0.5,
      opacity: 0.9,
      weight: 1.4,
    };
  return {
    className: "fire-footprint",
    color: "#e26079",
    fillColor: "#c7355b",
    fillOpacity: 0.3,
    opacity: 0.82,
    weight: 1.2,
  };
}
