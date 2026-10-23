import { useEffect, useMemo, useRef, useState } from "react";
import { Circle, CircleMarker, MapContainer, Rectangle, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import { latLng, latLngBounds, type LatLngBoundsExpression } from "leaflet";
import { Button } from "./ui";
import type { Ignition } from "../types";
import { validCoordinates } from "./CoordinateFields";

export type MapPoint = { id: string; name: string; coordinates: [number, number] };
type Props = {
  points: MapPoint[];
  selectedId?: string;
  center?: [number, number] | null;
  resourceRadius?: number;
  fireMargin?: number;
  mode?: "point" | "coverage";
  readOnly?: boolean;
  onPlace?: (point: [number, number]) => void;
};

export function fireAreaBounds(ignitions: Pick<Ignition, "coordinates">[], marginKm: number, centerLatitude?: number): [[number, number], [number, number]] | undefined {
  const points = ignitions.filter(item => validCoordinates(item.coordinates));
  if (!points.length) return;
  const lat = centerLatitude ?? points.reduce((sum, item) => sum + item.coordinates[1], 0) / points.length;
  const latMargin = marginKm / 110.574;
  const lonMargin = marginKm / (111.32 * Math.cos(lat * Math.PI / 180));
  return [[Math.min(...points.map(p => p.coordinates[1])) - latMargin, Math.min(...points.map(p => p.coordinates[0])) - lonMargin],
  [Math.max(...points.map(p => p.coordinates[1])) + latMargin, Math.max(...points.map(p => p.coordinates[0])) + lonMargin]];
}

export function LocationMap({ points, selectedId, center, resourceRadius, fireMargin, mode = "point", readOnly, onPlace }: Props) {
  const [recenter, setRecenter] = useState(0);
  const usable = points.filter(p => validCoordinates(p.coordinates));
  const selected = usable.find(p => p.id === selectedId) || usable[0];
  const focus = selected?.coordinates || (validCoordinates(center ?? null) ? center! : undefined);
  const fireBounds = fireMargin ? fireAreaBounds(usable, fireMargin, center?.[1]) : undefined;
  const bounds = useMemo(() => {
    if (mode !== "coverage") return;
    const area = latLngBounds([]);
    if (fireBounds) area.extend(fireBounds);
    if (validCoordinates(center ?? null) && resourceRadius) area.extend(latLng(center![1], center![0]).toBounds(resourceRadius * 2000));
    return area.isValid() ? [[area.getSouth(), area.getWest()], [area.getNorth(), area.getEast()]] as [[number, number], [number, number]] : undefined;
  }, [mode, JSON.stringify(fireBounds), center?.[0], center?.[1], resourceRadius]);
  return <div className="location-map">
    <MapContainer className="location-map-canvas" center={focus ? [focus[1], focus[0]] : [39.6, -8]} zoom={focus ? 12 : 6}>
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <MapViewport focus={focus} bounds={bounds} targetKey={`${mode}/${selectedId || ""}`} recenter={recenter} />
      <MapPlacement onPlace={readOnly ? undefined : onPlace} />
      {validCoordinates(center ?? null) && resourceRadius && <Circle center={[center![1], center![0]]} radius={resourceRadius * 1000} pathOptions={{ color: "#4799cd", fillOpacity: 0.04, dashArray: "7 7" }} />}
      {mode === "coverage" && validCoordinates(center ?? null) && <CircleMarker center={[center![1], center![0]]} radius={5} pathOptions={{ color: "#fff", fillColor: "#4799cd", fillOpacity: 1, weight: 2 }}><Tooltip>Centro da pesquisa de recursos</Tooltip></CircleMarker>}
      {fireBounds && <Rectangle bounds={fireBounds} pathOptions={{ color: "#ef5b35", fillOpacity: 0.04 }} />}
      {usable.map((point, index) => <CircleMarker key={point.id} center={[point.coordinates[1], point.coordinates[0]]} radius={point.id === selectedId ? 9 : 7}
        pathOptions={{ color: "#fff", fillColor: point.id === selectedId ? "#e06c43" : "#17211d", fillOpacity: 1, weight: 2 }}>
        <Tooltip direction="top">{index + 1}. {point.name}</Tooltip>
      </CircleMarker>)}
    </MapContainer>
    <div className="location-map-toolbar"><Button variant="secondary" size="sm" onClick={() => setRecenter(value => value + 1)}>Recentrar mapa</Button></div>
    <p className="location-map-hint">{readOnly ? "Pré-visualização da localização e da cobertura." : "Clique no mapa para posicionar o ponto selecionado."}</p>
  </div>;
}

/** Reframe geographic changes; resize refits coverage without reacting to form edits. */
export function MapViewport({ focus, bounds, targetKey, recenter }: { focus?: [number, number]; bounds?: LatLngBoundsExpression; targetKey: string; recenter: number }) {
  const map = useMap();
  const previous = useRef("");
  const target = useRef({ focus, bounds });
  target.current = { focus, bounds };
  const key = JSON.stringify([targetKey, bounds || focus, recenter]);
  useEffect(() => {
    const element = map.getContainer();
    let frame = 0;
    const resize = () => {
      cancelAnimationFrame(frame); frame = requestAnimationFrame(() => {
        const centerBeforeResize = map.getCenter();
        const zoomBeforeResize = map.getZoom();
        map.invalidateSize({ pan: false, animate: false });
        if (target.current.bounds) map.fitBounds(target.current.bounds, { padding: [32, 32], maxZoom: 14, animate: false });
        else map.setView(centerBeforeResize, zoomBeforeResize, { animate: false });
      });
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    resize();
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [map]);
  useEffect(() => {
    if (previous.current === key) return;
    previous.current = key;
    const frame = requestAnimationFrame(() => {
      map.invalidateSize({ pan: false, animate: false });
      if (bounds) map.fitBounds(bounds, { padding: [32, 32], maxZoom: 14, animate: false });
      else if (focus) map.setView([focus[1], focus[0]], targetKey === "point/" ? 12 : Math.max(map.getZoom(), 12), { animate: false });
    });
    return () => { cancelAnimationFrame(frame); previous.current = ""; };
  }, [key, map]);
  return null;
}
function MapPlacement({ onPlace }: { onPlace?: (point: [number, number]) => void }) {
  useMapEvents({ click: event => onPlace?.([event.latlng.lng, event.latlng.lat]) });
  return null;
}
