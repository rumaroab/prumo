"""Decision-critical checks for complete water trips and fire-aware road timing."""
from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import networkx as nx

from backend.app.mobility_comparison import (ComparisonRequest, PlanningUnit, SourceChoice,
                                             _choice, _ordinary_trip, _stage, _time_path, compare, preview_import)
from backend.app.models import ScenarioPoint, VehicleProfile, WaterPointDetails


class MobilityComparisonTests(unittest.TestCase):
    def setUp(self):
        self.vehicle = VehicleProfile(name="Test tanker", vehicle_class="tanker", off_road=True,
                                      water_tank_capacity_l=5000, starting_water_l=0, pump_flow_l_min=500)
        self.unit = PlanningUnit(id="u", callsign="TQ", organisation="Test", vehicle=self.vehicle,
                                 coordinates=(-8.0, 41.0))
        self.shared = ComparisonRequest(run_id="run", forecast_start_at=datetime(2026, 8, 18, tzinfo=UTC),
            departure_at=datetime(2026, 8, 18, tzinfo=UTC), unit=self.unit,
            delivery_coordinates=(-8.0, 41.0), requested_l=5000,
            sources=[SourceChoice(point_id="a"), SourceChoice(point_id="b")])
        self.source = ScenarioPoint(id="a", kind="water_point", name="A", coordinates=(-8.001, 41.0),
            water=WaterPointDetails(availability="available", supply_class="finite",
                                    available_volume_l=10000, shared_flow_l_min=300, setup_time_min=0))

    def graph(self):
        graph = nx.MultiDiGraph()
        graph.add_node(1, x=-8.0, y=41.0)
        graph.add_node(2, x=-7.999, y=41.0)
        graph.add_edge(1, 2, key=0, travel_min=6, length=85)
        graph.add_edge(2, 1, key=0, travel_min=6, length=85)
        return graph

    def test_edge_must_stay_clear_until_vehicle_exits(self):
        graph = self.graph()
        context = {(1, 2, 0): {"deadline": 10}, (2, 1, 0): {"deadline": 10}}
        self.assertEqual(_time_path(graph, 1, 2, self.vehicle, {}, {}, context, 0, 120, 0)[0], [(1, 2, 0)])
        self.assertIsNone(_time_path(graph, 1, 2, self.vehicle, {}, {}, context, 5, 120, 0)[0])
        self.assertIsNone(_time_path(graph, 2, 1, self.vehicle, {}, {}, context, 7, 120, 0)[0])

    def test_restriction_and_coverage_are_not_called_safe(self):
        graph = self.graph()
        restricted = VehicleProfile(name="Wide tanker", vehicle_class="tanker", width_m=3)
        graph.edges[1, 2, 0]["maxwidth"] = 2.5
        self.assertIsNone(_time_path(graph, 1, 2, restricted, {}, {}, {}, 0, 120, 0)[0])
        graph.edges[1, 2, 0].pop("maxwidth")
        self.assertEqual(_time_path(graph, 1, 2, self.vehicle, {}, {}, {(1, 2, 0): {"unknown": True}}, 0, 120, 0), (None, True))
        self.assertEqual(_stage(graph, {}, {}, {}, self.vehicle, (-8.0, 41.0), (-7.999, 41.0),
                                7, 10, 0, "Ida")["status"], "unknown")

    def test_source_exposure_during_filling_blocks_delivery(self):
        route = {"status": "clear", "route": {"duration_min": 2, "minimum_forecast_margin_min": 20}}
        with patch("backend.app.mobility_comparison._stage", return_value=route), \
             patch("backend.app.mobility_comparison._point_arrival", return_value=(70, False)):
            outcome = _choice(self.source, SourceChoice(point_id="a"), self.shared, None, {}, {}, {},
                              None, 50, 120, 0)
        self.assertEqual(outcome["status"], "infeasible")
        self.assertEqual(outcome["delivered_l"], 0)
        self.assertEqual(outcome["conflict"]["reason"], "source_exposure")

    def test_filling_can_make_return_infeasible(self):
        outward = {"status": "clear", "route": {"duration_min": 2, "minimum_forecast_margin_min": 20}}
        return_route = {"status": "infeasible", "reason": "Sem percurso elegível durante a deslocação.",
                        "conflict": {"reason": "fire_exposure", "exposure_min": 68}}
        with patch("backend.app.mobility_comparison._stage", side_effect=[outward, return_route]), \
             patch("backend.app.mobility_comparison._point_arrival", return_value=(None, False)):
            outcome = _choice(self.source, SourceChoice(point_id="a"), self.shared, None, {}, {}, {},
                              None, 50, 120, 0)
        self.assertEqual((outcome["status"], outcome["delivered_l"]), ("infeasible", 0))
        self.assertEqual([stage["kind"] for stage in outcome["stages"]], ["outbound", "filling", "inbound"])

    def test_ordinary_route_is_labelled_diagnostic_geometry(self):
        graph = self.graph()
        duration, feature = _ordinary_trip(graph, {}, {}, self.vehicle,
            (-8.0, 41.0), (-7.999, 41.0), (-8.0, 41.0))
        self.assertEqual(duration, 12)
        self.assertTrue(feature["properties"]["diagnostic"])
        self.assertEqual(feature["geometry"]["type"], "MultiLineString")

    def test_missing_flow_and_stock_do_not_count_water(self):
        missing = self.source.model_copy(deep=True)
        missing.water.shared_flow_l_min = None
        self.assertEqual(_choice(missing, SourceChoice(point_id="a"), self.shared, None, {}, {}, {}, None, 0, 120, 0)["status"], "unknown")
        self.source.water.available_volume_l = 1000
        outcome = _choice(self.source, SourceChoice(point_id="a"), self.shared, None, {}, {}, {}, None, 0, 120, 0)
        self.assertEqual((outcome["status"], outcome["delivered_l"]), ("infeasible", 0))
        self.source.water.availability = "unavailable"
        self.assertEqual(_choice(self.source, SourceChoice(point_id="a"), self.shared, None, {}, {}, {}, None, 0, 120, 0)["status"], "infeasible")

    def test_csv_preview_reports_bad_rows_without_saving_units(self):
        content = "unit_id,organisation,callsign,vehicle_class,longitude,latitude,observed_at,tank_capacity_l,starting_water_l,pump_flow_l_min\n"
        content += "u,Fire,TQ,tanker,-8,41,2026-08-18T13:00:00Z,5000,0,500\n"
        content += "bad,Fire,TQ,tanker,wrong,41,2026-08-18T13:00:00Z,5000,0,500\n"
        with patch("backend.app.mobility_comparison._dispatcher"), patch("backend.app.mobility_comparison.get_scenario"):
            result = preview_import("scenario", SimpleNamespace(), {"filename": "exercise.csv", "content": content})
        self.assertEqual(len(result["units"]), 1)
        self.assertEqual(result["units"][0]["source_file"], "exercise.csv")
        self.assertEqual(result["errors"][0]["row"], 3)
        self.assertIn("Valor numérico inválido", result["errors"][0]["message"])

    def test_run_time_reference_cannot_be_relabelled(self):
        run = SimpleNamespace(scenario_id="scenario", status="ready", mode="single",
            run_context={"scenario_start_time": "2026-08-18T01:00:00+00:00"})
        with patch("backend.app.mobility_comparison.get_scenario"), \
             patch("backend.app.mobility_comparison.get_run", return_value=run):
            with self.assertRaisesRegex(ValueError, "different start time"):
                compare("scenario", self.shared)


if __name__ == "__main__":
    unittest.main()
