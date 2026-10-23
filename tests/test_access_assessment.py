"""Decision-critical checks for one exact proposed closure and population access."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import networkx as nx

from backend.app.access_assessment import (_population_pair, _section_id, _sections, default_vehicle)
from backend.app.mobility_comparison import _time_path
from backend.app.models import ScenarioPoint


class AccessAssessmentTests(unittest.TestCase):
    def graph(self):
        graph = nx.MultiDiGraph()
        for node, lon in ((1, -8.000), (2, -7.999), (3, -7.998)):
            graph.add_node(node, x=lon, y=41.0)
        graph.add_edge(1, 2, key=0, name="Rua A", travel_min=2, length=100)
        graph.add_edge(2, 1, key=0, name="Rua A", travel_min=2, length=100)
        graph.add_edge(2, 3, key=0, name="Rua B", travel_min=3, length=100)
        graph.add_edge(3, 2, key=0, name="Rua B", travel_min=3, length=100)
        return graph

    def test_section_closes_only_selected_pair_in_both_directions(self):
        graph = self.graph()
        parent = {"unit": {"coordinates": [-8, 41]}, "delivery_coordinates": [-7.998, 41],
                  "outcomes": [{"source": {"coordinates": [-7.999, 41]}}], "road_revision": "revision"}
        selected = _sections(graph, parent, [])[_section_id("revision", 1, 2, "Rua A")]
        self.assertEqual(set(selected), {(1, 2, 0), (2, 1, 0)})
        self.assertNotIn((2, 3, 0), selected)
        vehicle = default_vehicle()
        self.assertIsNone(_time_path(graph, 1, 2, vehicle, {}, {}, {}, 50, 120, 10, set(selected))[0])
        self.assertIsNone(_time_path(graph, 2, 1, vehicle, {}, {}, {}, 50, 120, 10, set(selected))[0])
        self.assertEqual(_time_path(graph, 2, 3, vehicle, {}, {}, {}, 50, 120, 10, set(selected))[0], [(2, 3, 0)])

    def test_population_route_changes_and_unknown_is_preserved(self):
        graph = self.graph()
        origin = ScenarioPoint(kind="custom", name="Origem", coordinates=(-8, 41), population_role="origin")
        reception = ScenarioPoint(kind="shelter", name="Receção", coordinates=(-7.999, 41), population_role="reception")
        parent = {"departure_min": 50, "horizon_min": 120, "lead_time_min": 10, "exposure_buffer_m": 0}
        vehicle = default_vehicle()
        with patch("backend.app.access_assessment._point_arrival", return_value=(None, False)):
            before = _population_pair(graph, {}, {}, {}, None, parent, vehicle, origin, reception, set())
            after = _population_pair(graph, {}, {}, {}, None, parent, vehicle, origin, reception, {(1, 2, 0), (2, 1, 0)})
            uncertain = _population_pair(graph, {}, {(1, 2, 0): {"unknown": True}}, {}, None,
                                         parent, vehicle, origin, reception, set())
        self.assertEqual((before["status"], before["arrival_min"]), ("clear", 52))
        self.assertEqual(after["status"], "infeasible")
        self.assertEqual(uncertain["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
