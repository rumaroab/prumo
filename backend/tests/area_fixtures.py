"""Small real files for preparation persistence tests (never a network request)."""
import hashlib
import json

import networkx as nx
import numpy as np
import osmnx as ox


def landscape(path, bounds=None, cell=30, **kwargs):
    np.savez_compressed(path/'landscape.npz', fuel=np.full((2, 2), 145),
                        elevation=np.ones((2, 2)), slope=np.zeros((2, 2)),
                        aspect=np.zeros((2, 2)), coverage=np.ones((2, 2), dtype=bool))
    (path/'landscape.json').write_text(json.dumps({'cell_size_m': cell, 'crs': 'EPSG:3763',
        'transform': [cell, 0, 0, 0, -cell, 0]}))


def roads(path, bounds=None):
    graph = nx.MultiDiGraph(crs='EPSG:4326')
    graph.add_node(1, x=-8.30, y=41.4)
    graph.add_node(2, x=-8.29, y=41.4)
    graph.add_edge(1, 2, osmid=12, length=100, oneway=True, maxwidth='2.3')
    ox.save_graphml(graph, path/'roads.graphml')
    content = json.dumps({'type': 'FeatureCollection', 'features': [{'type': 'Feature',
        'geometry': {'type': 'LineString', 'coordinates': [[-8.30, 41.4], [-8.29, 41.4]]},
        'properties': {'segment_id': 'test', 'edge_refs': json.dumps([['1','2',0,'forward']])}}]})
    (path/'roads.geojson').write_text(content)
    (path/'roads.json').write_text(json.dumps({'count': 1, 'revision': hashlib.sha256(content.encode()).hexdigest()[:16]}))


def catalog(path, *args, **kwargs):
    path.write_text(json.dumps({'type': 'FeatureCollection', 'features': []}))
    return []


def buildings(path, *args):
    catalog(path)
    return 0
