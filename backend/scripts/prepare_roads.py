from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime

import geopandas as gpd
import osmnx as ox
from shapely.geometry import LineString

from backend.app.settings import CONFIG, PREPARED, ensure_dirs


def prepare() -> None:
    ensure_dirs()
    west, south, east, north = CONFIG["area"]["bounds"]
    graph = _graph_from_osm_api((west, south, east, north))
    for u, v, key, data in graph.edges(keys=True, data=True):
        data["mobility_edge_id"] = f"{u}:{v}:{key}"
    ox.save_graphml(graph, PREPARED / "roads.graphml")
    edges = ox.graph_to_gdfs(graph, nodes=False, fill_edge_geometry=True).reset_index().to_crs(CONFIG["area"]["projected_crs"])
    groups = {}
    for edge in edges.itertuples():
        osmid = str(edge.osmid)
        physical = (osmid, edge.geometry.wkb_hex if edge.u < edge.v else LineString(edge.geometry.coords[::-1]).wkb_hex)
        groups.setdefault(physical, []).append(edge)
    features = []
    for physical, related in groups.items():
        edge = related[0]
        base_start, base_end = edge.geometry.coords[0], edge.geometry.coords[-1]
        refs = json.dumps([[str(item.u), str(item.v), int(item.key),
                            "forward" if item.geometry.coords[0] == base_start and item.geometry.coords[-1] == base_end else "reverse"]
                           for item in related])
        parts = _split(edge.geometry, 100)
        for index, geometry in enumerate(parts):
            segment_id = hashlib.sha1(f"{osmid}:{index}:{geometry.wkb_hex}".encode()).hexdigest()[:16]
            features.append({"segment_id": segment_id, "name": _value(edge.name),
                             "road_class": _value(edge.highway), "edge_refs": refs, "geometry": geometry})
    roads = gpd.GeoDataFrame(features, crs=CONFIG["area"]["projected_crs"]).to_crs(4326)
    temp = PREPARED / "roads.tmp.geojson"
    roads.to_file(temp, driver="GeoJSON")
    os.replace(temp, PREPARED / "roads.geojson")
    road_file = PREPARED / "roads.geojson"
    revision = hashlib.sha256(road_file.read_bytes()).hexdigest()[:16]
    (PREPARED / "roads.json").write_text(json.dumps({
        "source": "OpenStreetMap Overpass API via OSMnx",
        "count": len(roads),
        "version": 4,
        "mobility_version": 1,
        "revision": revision,
        "bounds": [west, south, east, north],
        "fetched_at": datetime.now(UTC).isoformat(),
    }, indent=2))


def _graph_from_osm_api(bounds: tuple[float, float, float, float]):
    # OSMnx subdivides the query automatically when the requested area is too
    # large for one Overpass request. Keep vehicle tracks while excluding ways
    # that are explicitly pedestrian-only or private.
    vehicle_filter = ('["highway"]["highway"!~"footway|path|steps|pedestrian|cycleway"]'
                      '["area"!="yes"]["access"!="private"]')
    for tag in ("maxheight", "maxweight", "maxwidth", "surface", "tracktype", "barrier", "vehicle", "motor_vehicle"):
        if tag not in ox.settings.useful_tags_way:
            ox.settings.useful_tags_way.append(tag)
    for tag in ("barrier", "access", "vehicle", "motor_vehicle"):
        if tag not in ox.settings.useful_tags_node:
            ox.settings.useful_tags_node.append(tag)
    return ox.graph_from_bbox(bounds, network_type="all", custom_filter=vehicle_filter,
                              simplify=True, retain_all=True)


def _split(line: LineString, maximum: float) -> list[LineString]:
    count = max(1, int(line.length // maximum) + 1)
    points = [line.interpolate(i / count, normalized=True) for i in range(count + 1)]
    return [LineString([points[i], points[i + 1]]) for i in range(count)]


def _value(value) -> str:
    if isinstance(value, list):
        return _value(value[0])
    if value is None or value != value:
        return ""
    return str(value)


if __name__ == "__main__":
    prepare()
