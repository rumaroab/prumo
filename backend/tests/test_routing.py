from __future__ import annotations

import unittest

import networkx as nx

from backend.app.models import RoadClosure
from backend.app.services.routing import _path_conflicts, _static_path, _time_path


class RoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = nx.MultiDiGraph()
        for node, x, y in [(1, 0, 0), (2, 1, 0), (3, 0, 1), (4, 1, 1)]:
            self.graph.add_node(node, x=x, y=y)
        self.graph.add_edge(1, 2, key=0, travel_min=5, length=1000, name="Fast first")
        self.graph.add_edge(2, 4, key=0, travel_min=5, length=1000, name="Fast exposed")
        self.graph.add_edge(1, 3, key=0, travel_min=6, length=1200, name="Alternative first")
        self.graph.add_edge(3, 4, key=0, travel_min=6, length=1200, name="Alternative second")
        self.context = {
            (1, 2, 0): {"deadline": None, "unknown": False, "segments": ["a"], "closures": []},
            (2, 4, 0): {"deadline": 8, "unknown": False, "segments": ["b"], "closures": []},
            (1, 3, 0): {"deadline": None, "unknown": False, "segments": ["c"], "closures": []},
            (3, 4, 0): {"deadline": None, "unknown": False, "segments": ["d"], "closures": []},
        }

    def test_route_uses_traversal_time_and_avoids_future_exposure(self) -> None:
        baseline = _static_path(self.graph, 1, 4)
        self.assertEqual(baseline, [(1, 2, 0), (2, 4, 0)])
        conflicts = _path_conflicts(self.graph, baseline, 0, self.context)
        self.assertEqual(conflicts[0]["road"], "Fast exposed")
        self.assertEqual(_time_path(self.graph, 1, 4, 0, self.context), [(1, 3, 0), (3, 4, 0)])

    def test_active_reported_closure_can_make_destination_unreachable(self) -> None:
        closure = RoadClosure(segment_id="c", road_name="Alternative first", starts_min=0,
                              ends_min=10, reason="Tree across carriageway",
                              geometry={"type": "LineString", "coordinates": []})
        self.context[(1, 3, 0)]["closures"] = [closure]
        self.assertIsNone(_time_path(self.graph, 1, 4, 0, self.context))
        self.assertEqual(_time_path(self.graph, 1, 4, 20, self.context), [(1, 3, 0), (3, 4, 0)])


if __name__ == "__main__":
    unittest.main()
