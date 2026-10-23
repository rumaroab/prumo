from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import networkx as nx
import osmnx as ox
import requests
from pyproj import Transformer
from shapely.geometry import box
from shapely.ops import transform, unary_union

from backend.app import area_packages as areas
from backend.app import overpass_download as osm
from backend.app import preparation_checkpoints as checkpoints
from backend.app.models import AreaPreparationCreate, Ignition
from backend.tests import area_fixtures as fixtures


class Clock:
    value = 0.0
    def now(self):
        return self.value
    def sleep(self, seconds):
        self.value += seconds


class Response:
    def __init__(self, payload=None, status=200, headers=None, content=None):
        self.status_code, self.headers, self.ok = status, headers or {}, 200 <= status < 400
        self.content = content if content is not None else json.dumps(payload or {'elements': []}).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def iter_content(self, size):
        yield self.content


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.clock = Clock()
        for name, value in [('monotonic', self.clock.now), ('time', self.clock.now), ('sleep', self.clock.sleep)]:
            self.stack.enter_context(patch.object(osm.time, name, value))
        self.stack.enter_context(patch.object(osm.random, 'uniform', return_value=1))
        self.session = Mock(); self.progress = Mock()
        self.client = osm.OverpassClient(self.root, ['https://primary.test/api', 'https://fallback.test/api'],
                                         session=self.session, progress=self.progress)
        self.session.post.return_value = Response()

    def test_primary_failure_uses_fallback_and_bounded_timeouts(self):
        self.session.post.side_effect = [Response(status=502), Response()]
        self.assertEqual(self.client.fetch('query'), {'elements': []})
        self.assertEqual(self.session.post.call_args_list[1].args[0], 'https://fallback.test/api/interpreter')
        self.assertEqual(self.session.post.call_args.kwargs['timeout'], (10, 45))
        self.assertEqual(self.clock.value, 10)

    def test_all_endpoints_unavailable_stops_after_four_attempts(self):
        self.session.post.side_effect = requests.ReadTimeout('timeout')
        with self.assertRaises(osm.OverpassFailure):
            self.client.fetch('query')
        self.assertEqual(self.session.post.call_count, 4)
        self.assertEqual(self.clock.value, 70)
        self.assertFalse(list(self.root.glob('*.json')))

    def test_retry_after_is_honoured_for_the_same_endpoint(self):
        requests_at = []
        def post(*args, **kwargs):
            requests_at.append(self.clock.value)
            return [Response(status=429, headers={'Retry-After':'100'}), Response(status=503), Response()][len(requests_at)-1]
        self.session.post.side_effect = post
        self.client.fetch('query')
        self.assertEqual(requests_at, [0, 10, 100])

    def test_retry_after_beyond_budget_stops_without_extra_request(self):
        self.session.post.side_effect = [Response(status=429, headers={'Retry-After':'1000'}), Response(status=503)]
        with self.assertRaisesRegex(osm.OverpassFailure, 'budget'):
            self.client.fetch('query')
        self.assertEqual(self.session.post.call_count, 2)

    def test_permanent_request_error_is_not_retried(self):
        self.session.post.return_value = Response(status=400)
        with self.assertRaises(osm.OverpassFailure) as error:
            self.client.fetch('query')
        self.assertFalse(error.exception.retryable)
        self.assertEqual(self.session.post.call_count, 1)

    def test_invalid_responses_are_not_cached(self):
        for response in [Response(content=b'<html>gateway</html>'), Response({'remark':'runtime error: timeout', 'elements':[]}),
                         Response({'elements':[{'id':1,'type':'node'}]}), Response({'unexpected':[]})]:
            with self.subTest(content=response.content):
                self.session.post.return_value = response
                with self.assertRaises(osm.OverpassFailure):
                    self.client.fetch(response.content.decode())
                self.assertFalse(list(self.root.glob('*.json')))

    def test_partial_way_is_not_cached(self):
        self.session.post.return_value = Response({'elements':[{'type':'way','id':12,'nodes':[1,2]}]})
        with self.assertRaises(osm.OverpassFailure):
            self.client.fetch('query;out body;')
        self.assertFalse(list(self.root.glob('*.json')))

    def test_cache_reused_across_endpoints_but_expired_and_corrupt_entries_refetched(self):
        self.client.fetch('query')
        alternate = osm.OverpassClient(self.root, ['https://third.test/api'], session=self.session)
        alternate.fetch('query')
        self.assertEqual(self.session.post.call_count, 1)
        self.clock.value += osm.CACHE_TTL+1
        alternate.fetch('query')
        self.assertEqual(self.session.post.call_count, 2)
        next(self.root.glob('*.json')).write_text('{broken')
        alternate.fetch('query')
        self.assertEqual(self.session.post.call_count, 3)

    def test_dataset_budget_stops_retry(self):
        self.client.dataset_deadline = 5
        self.session.post.return_value = Response(status=503)
        with self.assertRaisesRegex(osm.OverpassFailure, 'budget'):
            self.client.fetch('query')
        self.assertEqual(self.session.post.call_count, 1)
        self.assertEqual(self.session.post.call_args.kwargs['timeout'], (5, 5))

    def test_cancel_during_backoff_stops_retry(self):
        def cancel():
            if self.clock.value >= 1:
                raise areas._Cancelled()
        self.client.check_cancel = cancel
        self.session.post.return_value = Response(status=502)
        with self.assertRaises(areas._Cancelled):
            self.client.fetch('query')
        self.assertEqual(self.session.post.call_count, 1)
        self.assertLessEqual(self.clock.value, 1)

    def test_failed_tile_stops_dataset_and_retry_reuses_successful_tiles(self):
        polygons = [box(-8.31,41.4,-8.30,41.41), box(-8.30,41.4,-8.29,41.41)]
        self.session.post.side_effect = [Response()] + [Response(status=503)]*4
        with patch.object(osm, 'tiles', return_value=iter(polygons)):
            with self.assertRaises(osm.OverpassFailure):
                self.client.download(box(-8.31,41.4,-8.29,41.41), 'water')
        self.assertEqual(len(list(self.root.glob('*.json'))), 1)
        self.session.post.side_effect = None
        self.session.post.return_value = Response()
        with patch.object(osm, 'tiles', return_value=iter(polygons)):
            self.client.download(box(-8.31,41.4,-8.29,41.41), 'water')
        self.assertEqual(self.session.post.call_count, 6)

    def test_tiles_cover_area_and_are_no_larger_than_10km(self):
        polygon = box(-7.63,40.69,-6.90,41.24)
        pieces = list(osm.tiles(polygon))
        self.assertGreater(len(pieces), 36)
        self.assertLess(polygon.symmetric_difference(unary_union(pieces)).area, 1e-9)
        project = Transformer.from_crs(4326,3763,always_xy=True).transform
        for piece in pieces:
            west,south,east,north = transform(project,piece).bounds
            self.assertLessEqual(east-west, 10000.001)
            self.assertLessEqual(north-south, 10000.001)

    def test_cross_tile_network_matches_single_query_and_keeps_restrictions(self):
        nodes = [{'type':'node','id':i,'lon':-8.30+i*.001,'lat':41.4} for i in [1,2,3]]
        ways = [{'type':'way','id':10+i,'nodes':[i,i+1],
                 'tags':{'highway':'residential','name':'Rua','oneway':'yes','maxwidth':'2.3','maxweight':'12'}} for i in [1,2]]
        pieces = [box(-8.31,41.39,-8.30,41.41),box(-8.30,41.39,-8.28,41.41)]
        with patch.object(osm, 'tiles', return_value=iter(pieces)), \
             patch.object(self.client, 'fetch', side_effect=[{'elements':nodes[:2]+ways[:1]}, {'elements':nodes+ways}]), \
             patch.object(areas.ox, 'graph_from_bbox', side_effect=AssertionError('network API forbidden')):
            token = areas._current_client.set(self.client)
            try:
                graph = areas._download_road_graph([-8.31,41.39,-8.28,41.41], '["highway"]')
            finally:
                areas._current_client.reset(token)
        path = self.root/'single.osm'
        osm.write_xml(nodes+ways,path)
        expected = ox.graph_from_xml(path, simplify=True, retain_all=True)
        self.assertEqual(set(graph.edges), set(expected.edges))
        self.assertEqual(graph.number_of_edges(), 1)
        self.assertTrue(nx.has_path(graph,1,3))
        self.assertFalse(nx.has_path(graph,3,1))
        self.assertEqual(graph.edges[1,3,0]['maxwidth'],'2.3')
        self.assertEqual(graph.edges[1,3,0]['maxweight'],'12')


class PreparationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.areas, self.preps = self.root/'areas', self.root/'preparations'
        self.areas.mkdir(); self.preps.mkdir()
        for name,value in [('AREAS',self.areas),('PREPARATIONS',self.preps),('SOURCE_CACHE',self.root/'cache')]:
            self.stack.enter_context(patch.object(areas,name,value))
        self.stack.enter_context(patch.object(areas,'ensure_dirs'))
        self.executor = self.stack.enter_context(patch.object(areas,'_executor'))
        self.landscape = self.stack.enter_context(patch.object(areas,'_prepare_landscape', side_effect=fixtures.landscape))
        self.roads = self.stack.enter_context(patch.object(areas,'_prepare_roads', side_effect=fixtures.roads))
        self.stack.enter_context(patch.object(areas,'_prepare_buildings', side_effect=fixtures.buildings))
        self.stack.enter_context(patch.object(areas,'_prepare_resources', side_effect=fixtures.catalog))
        self.stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('unexpected network')))
        self.request = AreaPreparationCreate(center=(-8.3,41.4), resource_radius_km=25,
            ignitions=[Ignition(id='fire',name='Imported fire',coordinates=(-8.3,41.4))])
        self.job = areas.create_preparation(self.request)

    def test_duplicate_request_reuses_job(self):
        duplicate = areas.create_preparation(self.request)
        self.assertEqual(duplicate.id,self.job.id)
        self.assertEqual(self.executor.submit.call_count,1)

    def test_failure_preserves_terrain_and_retry_resumes_it(self):
        self.roads.side_effect = osm.OverpassFailure('offline')
        areas._run(self.job.id)
        failed = areas.get_preparation(self.job.id)
        self.assertEqual((failed.status,failed.stage,failed.failure_code),('failed','roads','overpass_unavailable'))
        self.assertFalse((self.areas/self.job.package_id).exists())
        self.roads.side_effect = fixtures.roads
        retry = areas.retry_preparation(self.job.id)
        areas._run(retry.id)
        ready = areas.get_preparation(retry.id)
        self.assertEqual(ready.status,'ready')
        self.assertEqual(self.landscape.call_count,1)
        self.assertEqual(ready.request,self.request)
        self.assertEqual(ready.request.resource_radius_km,25)

    def test_corrupt_checkpoint_is_rebuilt(self):
        self.roads.side_effect = osm.OverpassFailure('offline')
        areas._run(self.job.id)
        folder = self.preps/'.checkpoints-v1'/self.job.package_id
        (folder/'landscape.npz').write_bytes(b'invalid')
        self.roads.side_effect = fixtures.roads
        retry = areas.retry_preparation(self.job.id); areas._run(retry.id)
        self.assertEqual(areas.get_preparation(retry.id).status,'ready')
        self.assertEqual(self.landscape.call_count,2)

    def test_restart_marks_interrupted_but_preserves_checkpoint(self):
        self.roads.side_effect = osm.OverpassFailure('offline')
        areas._run(self.job.id)
        record = areas.get_preparation(self.job.id); record.status='running'; areas._write_record(record)
        areas.recover_preparations()
        self.assertEqual(areas.get_preparation(self.job.id).failure_code,'interrupted')
        self.assertIsNotNone(checkpoints.restore(self.preps/'.checkpoints-v1'/self.job.package_id,'landscape'))

    def test_cancelled_queued_job_does_not_start(self):
        areas.cancel_preparation(self.job.id); areas._run(self.job.id)
        self.assertEqual(areas.get_preparation(self.job.id).status,'cancelled')
        self.landscape.assert_not_called()

    def test_recovery_does_not_interrupt_a_live_package_worker(self):
        with areas._process_lock(f'.{self.job.package_id}.lock'):
            areas.recover_preparations()
        self.assertEqual(areas.get_preparation(self.job.id).status, 'queued')

    def test_expired_road_checkpoint_is_rebuilt(self):
        original = areas._atomic_json
        def cancel_before_publish(path, value):
            original(path, value)
            if path.name == 'manifest.json':
                areas.cancel_preparation(self.job.id)
        with patch.object(areas, '_atomic_json', side_effect=cancel_before_publish):
            areas._run(self.job.id)
        marker = self.preps/'.checkpoints-v1'/self.job.package_id/'roads.checkpoint.json'
        value = json.loads(marker.read_text()); value['saved_at'] = 0
        marker.write_text(json.dumps(value))
        retry = areas.retry_preparation(self.job.id); areas._run(retry.id)
        self.assertEqual(areas.get_preparation(retry.id).status, 'ready')
        self.assertEqual(self.roads.call_count, 2)
        self.assertEqual(self.landscape.call_count, 1)

    def test_cancellation_before_publication_cannot_publish(self):
        original = areas._atomic_json
        def write(path,value):
            original(path,value)
            if path.name=='manifest.json':
                areas.cancel_preparation(self.job.id)
        with patch.object(areas,'_atomic_json', side_effect=write):
            areas._run(self.job.id)
        self.assertEqual(areas.get_preparation(self.job.id).status,'cancelled')
        self.assertFalse((self.areas/self.job.package_id).exists())
        retry = areas.retry_preparation(self.job.id); areas._run(retry.id)
        self.assertEqual(areas.get_preparation(retry.id).status,'ready')
        self.assertEqual(self.landscape.call_count,1)
        self.assertEqual(self.roads.call_count,1)

    def test_missing_road_files_never_publish(self):
        self.roads.side_effect = None
        self.roads.return_value = None
        areas._run(self.job.id)
        self.assertEqual(areas.get_preparation(self.job.id).status,'failed')
        self.assertFalse((self.areas/self.job.package_id).exists())

    def test_optional_failure_still_publishes_partial(self):
        with patch.object(areas,'_prepare_buildings', side_effect=osm.OverpassFailure('offline')):
            areas._run(self.job.id)
        self.assertEqual(areas.get_preparation(self.job.id).status,'partial')
        self.assertTrue((self.areas/self.job.package_id/'roads.graphml').exists())

    def test_old_preparation_records_keep_compatible_defaults(self):
        value = self.job.model_dump()
        for key in ('failure_code','retryable','retry_at','tile_progress'):
            value.pop(key)
        (self.preps/f'{self.job.id}.json').write_text(json.dumps(value,default=str))
        self.assertIsNone(areas.get_preparation(self.job.id).failure_code)


if __name__ == '__main__':
    unittest.main()
