"""Evaluate and freeze the richer Portuguese exercises for supervised and public use.

The 72 comparisons are real evaluator outputs. Existing saved payloads are never
replaced. A fixture version change creates new identities and retains history.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import timedelta
from itertools import combinations
from pathlib import Path

from backend.app.demo_exercises import (VERSION, PACKAGE_ID, SCENARIOS, START, SECTOR,
    DEPARTURES, CLOSURE_ENDS, planning_points, planning_units, simulation)
from backend.app.mobility_comparison import ComparisonRequest, PlanningUnit, SourceChoice, _setup, compare
from backend.app.access_assessment import AssessmentRequest, _setup as access_setup, assess, _section_id, _road_name
from backend.app.mobility_routing import _graph, _revision
from backend.app.io import load_result
from backend.app.services.fire_layer import footprint
from backend.app.settings import RUNS, ROOT
from backend.app.seed_demo import seed as seed_bundled
from backend.app.storage import connect
from backend.app.area_packages import package_path

SCENARIO_ID = SCENARIOS['cell2fire']
MTT_SCENARIO_ID = SCENARIOS['mtt']
RUN_ID = f'cell2fire-{VERSION}'
MTT_RUN_ID = f'mtt-{VERSION}'
PAIRS = list(combinations(range(4), 2))


def _identifier(engine, key, pair, variant):
    return f'demo-rich-{VERSION}-{engine}-{key}-{pair}-{variant}'


def _seed_matrix(engine: str) -> dict:
    seed_bundled()
    _setup()
    scenario_id = SCENARIOS[engine]
    with connect() as db:
        stored = {row['id']: json.loads(row['payload']) for row in db.execute(
            'SELECT id,payload FROM mobility_comparisons WHERE scenario_id=?', (scenario_id,))}
    points = [point for point in planning_points(engine) if point.kind == 'water_point']
    matrix = {}
    for key, unit, vehicle in planning_units(engine):
        for left, right in PAIRS:
            pair = f'{left}{right}'
            for variant, departure in zip(('base', 'delay'), DEPARTURES[engine]):
                identity = _identifier(engine,key,pair,variant)
                lookup = f'{key}|{pair}|{variant}'
                if identity in stored:
                    matrix[lookup] = stored[identity]
                    continue
                request = ComparisonRequest(run_id=f'{engine}-{VERSION}', forecast_start_at=START,
                    departure_at=START+timedelta(minutes=departure),
                    unit=PlanningUnit(id=unit.id,callsign=unit.callsign,organisation=unit.organisation,
                        vehicle=vehicle,coordinates=SECTOR,observed_at=START+timedelta(seconds=1),
                        source_file='perfis-ficticios-exercicio.csv'),
                    delivery_coordinates=SECTOR,requested_l=3000,lead_time_min=10,
                    sources=[SourceChoice(point_id=points[index].id,
                        flow_l_min=points[index].water.shared_flow_l_min,
                        available_volume_l=points[index].water.available_volume_l,
                        setup_time_min=points[index].water.setup_time_min) for index in (left,right)])
                value = compare(scenario_id,request)
                value.update(id=identity,fixture_version=VERSION)
                with connect() as db:
                    db.execute('INSERT INTO mobility_comparisons VALUES (?,?,?,?)',
                        (identity,scenario_id,value['created_at'],json.dumps(value,ensure_ascii=False)))
                matrix[lookup] = value
    return matrix


def seed() -> dict:
    values = _seed_matrix('cell2fire')
    return {'base':values['05|01|base'],'delay':values['05|01|delay'],'matrix':values}


def seed_mtt() -> dict:
    values = _seed_matrix('mtt')
    return {'base':values['05|01|base'],'delay':values['05|01|delay'],'matrix':values}


def _seed_access_matrix(engine: str, matrix: dict) -> dict:
    access_setup()
    prepared = package_path(PACKAGE_ID)
    revision = _revision(prepared)
    graph = _graph(str(prepared/'roads.graphml'),revision)
    edge = next(edge for edge in graph.edges(keys=True) if set(edge[:2]) == set(CLOSURE_ENDS))
    section_id = _section_id(revision,*edge[:2],_road_name(graph.edges[edge]))
    with connect() as db:
        stored = {row['comparison_id']:json.loads(row['payload']) for row in db.execute(
            'SELECT comparison_id,payload FROM access_assessments WHERE scenario_id=?',(SCENARIOS[engine],))}
    points = [point for point in planning_points(engine) if point.population_role]
    values = {}
    for lookup,parent in matrix.items():
        if parent['id'] in stored:
            values[lookup] = stored[parent['id']]
            continue
        value = assess(SCENARIOS[engine],AssessmentRequest(comparison_id=parent['id'],section_id=section_id,points=points))
        value.update(id=f"access-{parent['id']}",fixture_version=VERSION)
        with connect() as db:
            db.execute('INSERT INTO access_assessments VALUES (?,?,?,?,?)',
                (value['id'],SCENARIOS[engine],parent['id'],value['created_at'],json.dumps(value,ensure_ascii=False)))
        values[lookup] = value
    return values


def seed_access(outcomes):
    values = _seed_access_matrix('cell2fire',outcomes.get('matrix') or _seed_matrix('cell2fire'))
    return {'base':values['05|01|base'],'delay':values['05|01|delay'],'matrix':values}


def seed_mtt_access(outcomes):
    values = _seed_access_matrix('mtt',outcomes.get('matrix') or _seed_matrix('mtt'))
    return {'base':values['05|01|base'],'delay':values['05|01|delay'],'matrix':values}


def verify(values, assessments):
    assert len(values['cell2fire']) == len(values['mtt']) == 36
    cell = values['cell2fire']['05|01|base']['outcomes']
    late = values['cell2fire']['05|01|delay']['outcomes']
    assert cell[0]['status'] == 'infeasible' and cell[0]['conflict']['reason'] == 'source_exposure'
    assert cell[1]['status'] == 'clear' and cell[1]['minimum_forecast_margin_min'] >= 5
    assert cell[0]['baseline_duration_min'] < cell[1]['baseline_duration_min']
    assert late[1]['status'] != 'clear' or late[1]['minimum_forecast_margin_min'] < cell[1]['minimum_forecast_margin_min']-5
    mtt = values['mtt']['05|01|base']['outcomes']
    mtt_late = values['mtt']['05|01|delay']['outcomes']
    assert all(row['status'] == 'clear' for row in mtt)
    assert mtt[1]['minimum_forecast_margin_min'] >= 5
    assert mtt_late[1]['status'] == 'infeasible'
    for engine,matrix in values.items():
        output = RUNS/f'{engine}-{VERSION}'
        fire_revision = hashlib.sha256((output/'result.npz').read_bytes()+(output/'result.json').read_bytes()).hexdigest()
        for lookup,value in matrix.items():
            assert value['fire_revision'] == fire_revision, 'A simulação guardada mudou; crie uma nova versão do exercício.'
            assert value['requested_l'] == 3000 and value['lead_time_min'] == 10
            assert value['road_package_id'] == PACKAGE_ID and len(value['outcomes']) == 2
            for outcome in value['outcomes']:
                if outcome['source']['id'].endswith('-d'):
                    assert outcome['status'] == 'unknown'
                    assert any(row['code'] == 'missing_flow' for row in outcome['explanations'])
                if outcome['status'] != 'clear': assert outcome['delivered_l'] == 0
        compact = matrix['03|02|base']['outcomes'][1]
        medium = matrix['05|02|base']['outcomes'][1]
        assert compact['status'] == 'clear', compact
        assert medium['status'] == 'infeasible' and medium['conflict']['reason'] == 'vehicle_restriction',medium
        assert any(row['summary']['water_changed'] for row in assessments[engine].values())
    access = assessments['mtt']['05|01|base']
    before, after = access['without']['population'],access['with_proposal']['population']
    assert any(new['reachable_count'] < old['reachable_count'] for old,new in zip(before,after))
    def earliest(row):
        return min([option['arrival_min'] for option in row['options'] if option['status']=='clear'] or [float('inf')])
    assert any(old['reachable_count']==new['reachable_count'] and earliest(new)>earliest(old)+1
               for old,new in zip(before,after))
    assert any(old['reachable_count']==new['reachable_count'] and earliest(new)==earliest(old)
               for old,new in zip(before,after))
    return {'fixture_version':VERSION,'comparisons':72,'assessments':72,
        'defaults':{engine:{variant:[{'source':row['source']['name'],'status':row['status'],
            'delivery_min':row.get('delivery_min'),'margin_min':row.get('minimum_forecast_margin_min')}
            for row in values[engine][f'05|01|{variant}']['outcomes']] for variant in ['base','delay']}
            for engine in values}}


def export_public_bundle(outcomes: dict | None, path: Path) -> None:
    values = {'cell2fire':(outcomes or seed())['matrix'],'mtt':seed_mtt()['matrix']}
    assessments = {engine:_seed_access_matrix(engine,matrix) for engine,matrix in values.items()}
    report = verify(values,assessments)
    public_fields = ('id','scenario_id','created_at','run_id','run_name','engine','forecast_start_at',
        'departure_min','horizon_min','lead_time_min','exposure_buffer_m','unit','delivery_coordinates',
        'requested_l','outcomes','road_package_id','road_revision','fire_revision')
    scenarios = {}
    for engine,matrix in values.items():
        fire = load_result(RUNS/f'{engine}-{VERSION}')
        public_comparisons = {key:{field:value[field] for field in public_fields} | {'model_provenance':{}}
                              for key,value in matrix.items()}
        public_access = {key:{field:value[field] for field in
            ('id','scenario_id','created_at','comparison_id','road_revision','section_id','closure_feature','summary')}
            | {'with_water':value['with_proposal']['water']} for key,value in assessments[engine].items()}
        population = {variant:{mode:assessments[engine][f'05|01|{variant}'][mode]['population']
                              for mode in ['without','with_proposal']} for variant in ['base','delay']}
        model = simulation(engine)
        scenarios[engine] = {'label':'Cell2Fire' if engine == 'cell2fire' else 'MTT experimental',
            'title':model.name,'departures':DEPARTURES[engine],
            'weather':{'wind_speed_kmh':model.wind_speed_kmh,'wind_direction_deg':model.wind_direction_deg,
                       'moisture':'baixa','duration_min':240},
            'ignitions':[value.model_dump(mode='json') for value in model.ignitions],
            'points':[point.model_dump(mode='json') for point in planning_points(engine)],
            'comparisons':public_comparisons,'assessments':public_access,'population':population,
            'population_vehicle':next(iter(assessments[engine].values()))['population_vehicle'],
            'fire_frames':{str(minute):footprint(fire,minute) for minute in range(0,241)}}
    roads = json.loads((package_path(PACKAGE_ID)/'roads.geojson').read_text())
    # Exact road geometry is retained without source graph internals.
    roads = {'type':'FeatureCollection','features':[{'type':'Feature','geometry':row['geometry'],
        'properties':{'name':row['properties']['name']}} for row in roads['features']]}
    data = {'schema_version':2,'title':'PRUMO · decisões de mobilidade','synthetic':True,
        'description':'Dois exercícios calculados com três autotanques, quatro fontes e consequências partilhadas.',
        'default_scenario':'cell2fire','scenarios':scenarios,'roads':roads,
        'road_provenance':json.loads((package_path(PACKAGE_ID)/'roads.json').read_text()),'verification':report}
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')))
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    export_public_bundle(seed(),ROOT/'public_demo_site'/'demo.json')
