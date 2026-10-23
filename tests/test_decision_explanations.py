"""Evidence behind the richer demo's warnings and exercise road assumptions."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC,datetime
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import numpy as np
import osmnx as ox
from affine import Affine

from backend.app.decision_explanations import explain_outcome
from backend.app.mobility_comparison import ComparisonRequest,PlanningUnit,SourceChoice,_choice,_stage,_point_arrival
from backend.app.mobility_routing import _graph
from backend.app.models import ScenarioPoint,WaterPointDetails,VehicleProfile,SimulationResult


class DecisionExplanationTests(unittest.TestCase):
    def setUp(self):
        self.vehicle=VehicleProfile(name='Intermédio',vehicle_class='tanker',weight_t=16,
            water_tank_capacity_l=5000,starting_water_l=0,pump_flow_l_min=600,off_road=True)
        self.shared=ComparisonRequest(run_id='run',forecast_start_at=datetime(2026,8,18,tzinfo=UTC),
            departure_at=datetime(2026,8,18,tzinfo=UTC),unit=PlanningUnit(id='u',callsign='TQ-05',
            organisation='Exercício',vehicle=self.vehicle,coordinates=(-8,41)),
            delivery_coordinates=(-8,41),requested_l=3000,sources=[SourceChoice(point_id='a'),SourceChoice(point_id='b')])
        self.source=ScenarioPoint(id='a',kind='water_point',name='Depósito da encosta',coordinates=(-7.999,41),
            water=WaterPointDetails(availability='available',supply_class='finite',available_volume_l=12000,
                                   shared_flow_l_min=250,setup_time_min=2))

    def test_filling_warning_has_time_limit_and_original_exposure(self):
        outward={'status':'clear','route':{'duration_min':2,'minimum_forecast_margin_min':20}}
        with patch('backend.app.mobility_comparison._stage',return_value=outward),patch('backend.app.mobility_comparison._point_arrival',return_value=(40,False)):
            value=_choice(self.source,SourceChoice(point_id='a'),self.shared,None,{}, {}, {},None,20,240,30)
        explain_outcome(value,self.source,SourceChoice(point_id='a'),self.shared)
        warning=value['explanations'][0]
        self.assertEqual(value['status'],'infeasible')
        self.assertEqual((warning['stage'],warning['exposure_min'],warning['event_min']),('filling',40,30))
        self.assertEqual(warning['vehicle_exit_min'],36)
        self.assertEqual(warning['feature']['geometry']['coordinates'],self.source.coordinates)
        self.assertEqual(value['delivered_l'],0)

    def test_missing_flow_and_insufficient_stock_have_distinct_evidence(self):
        self.source.water.shared_flow_l_min=None
        value=_choice(self.source,SourceChoice(point_id='a'),self.shared,None,{}, {}, {},None,0,240,30)
        explain_outcome(value,self.source,SourceChoice(point_id='a'),self.shared)
        self.assertEqual((value['status'],value['explanations'][0]['code']),('unknown','missing_flow'))
        self.source.water.shared_flow_l_min=250
        self.source.water.available_volume_l=2000
        value=_choice(self.source,SourceChoice(point_id='a'),self.shared,None,{}, {}, {},None,0,240,30)
        explain_outcome(value,self.source,SourceChoice(point_id='a'),self.shared)
        self.assertEqual((value['status'],value['explanations'][0]['code']),('infeasible','insufficient_stock'))
        self.assertIn('2000 L',value['explanations'][0]['message'])

    def graph(self):
        graph=nx.MultiDiGraph(crs='epsg:4326')
        graph.add_node(1,x=-8.,y=41.)
        graph.add_node(2,x=-7.999,y=41.)
        for u,v in [(1,2),(2,1)]:
            graph.add_edge(u,v,key=0,name='Acesso à reserva',length=85,travel_min=2,maxweight='12',
                           exercise_assumption='Limite fictício de exercício')
        return graph

    def test_capacity_failure_takes_precedence_over_insufficient_stock(self):
        self.shared.unit.vehicle.water_tank_capacity_l=2000
        self.source.water.available_volume_l=1000
        value=_choice(self.source,SourceChoice(point_id='a'),self.shared,None,{}, {}, {},None,0,240,30)
        explain_outcome(value,self.source,SourceChoice(point_id='a'),self.shared)
        self.assertEqual(value['explanations'][0]['code'],'vehicle_capacity')
        self.assertEqual(value['explanations'][0]['feature']['geometry']['coordinates'],self.shared.unit.coordinates)

    def test_weight_failure_points_to_exact_road_with_limit(self):
        graph=self.graph()
        value=_stage(graph,{}, {}, {},self.vehicle,(-8,41),(-7.999,41),0,240,10,'Ida')
        self.assertEqual(value['status'],'infeasible')
        self.assertEqual(value['conflict']['reason'],'vehicle_restriction')
        self.assertEqual((value['conflict']['actual'],value['conflict']['limit']),(16,12))
        self.assertEqual(value['conflict']['feature']['geometry']['type'],'LineString')

    def test_missing_height_remains_unknown(self):
        graph=self.graph()
        for edge in graph.edges(keys=True):graph.edges[edge]['maxweight']='40'
        vehicle=self.vehicle.model_copy(update={'height_m':3.2})
        value=_stage(graph,{}, {}, {},vehicle,(-8,41),(-7.999,41),0,240,10,'Ida')
        self.assertEqual(value['status'],'unknown')
        self.assertIn('altura livre desconhecida',value['route']['unknown_constraints'][0])

    def test_overlay_is_revision_bound_and_only_changes_named_edges(self):
        graph=self.graph()
        for edge in graph.edges(keys=True):graph.edges[edge].pop('maxweight')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'roads.graphml';ox.save_graphml(graph,path)
            path.with_name('exercise-road-assumptions.json').write_text(json.dumps({'road_revision':'r1',
                'sections':[{'edge':[1,2,0],'attributes':{'maxweight':'12'},'description':'Exercício'}]}))
            result=_graph(str(path),'r1')
            self.assertEqual(result.edges[1,2,0]['maxweight'],'12')
            self.assertNotIn('maxweight',result.edges[2,1,0])
            with self.assertRaisesRegex(ValueError,'revisão'):_graph(str(path),'r2')

    def test_exposure_sampling_keeps_unknown_coverage(self):
        arrivals=np.full((5,5),np.nan,dtype='float32');arrivals[2,2]=20
        coverage=np.ones((5,5),dtype=bool)
        result=SimulationResult(arrivals,coverage,Affine(.001,0,-8.0025,0,-.001,41.0025),'EPSG:4326',1,'test','1',{})
        # Coordinates are in the result CRS here; use a tiny buffer in its units.
        self.assertEqual(_point_arrival(result,(-8,41),0),(20.,False))
        coverage[2,2]=False
        self.assertEqual(_point_arrival(result,(-8,41),0),(None,True))

    def test_fixture_generator_refuses_to_replace_a_saved_fire_result(self):
        from backend.app import demo_exercises
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);prepared=root/'prepared';prepared.mkdir()
            (prepared/'landscape.json').write_text('{}')
            output=root/f'mtt-{demo_exercises.VERSION}';output.mkdir()
            (output/'fixture.json').write_text('{"signature":"old-inputs"}')
            (output/'result.npz').write_bytes(b'original-saved-result')
            with patch.object(demo_exercises,'RUNS',root),patch.object(demo_exercises,'prepare',return_value=prepared),patch.object(demo_exercises,'_registered_result',return_value=True):
                with self.assertRaisesRegex(RuntimeError,'nova versão'):demo_exercises.generate('mtt')
            self.assertEqual((output/'result.npz').read_bytes(),b'original-saved-result')


if __name__=='__main__':unittest.main()
