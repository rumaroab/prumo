from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import osmium
import requests
from shapely.geometry import box, mapping

from backend.app import area_packages as areas
from backend.app import osm_snapshots as snapshots
from backend.app import osm_source as source
from backend.app import preparation_checkpoints as checkpoints
from backend.tests import area_fixtures

FILTER = ('["highway"]["highway"!~"footway|path|steps|pedestrian|cycleway"]'
          '["area"!="yes"]["access"!="private"]')
STAMP = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
POLY = "region\n1\n -9 40\n -7 40\n -7 42\n -9 42\n -9 40\nEND\nEND\n"


def pbf(path, stamp=STAMP, *, extra_node=False):
    header = osmium.io.Header()
    header.set("osmosis_replication_timestamp", stamp)
    nodes = [(1, -8.304, 41.4, {"barrier": "gate", "access": "yes"}),
             (2, -8.300, 41.4, {}), (3, -8.296, 41.4, {}), (4, -8.292, 41.4, {}),
             (11, -8.300, 41.401, {}), (12, -8.299, 41.401, {}),
             (13, -8.299, 41.402, {}), (14, -8.300, 41.402, {}),
             (20, -8.300, 41.4005, {"emergency": "fire_hydrant"}),
             (21, -8.301, 41.4006, {"amenity": "fire_station"})]
    if extra_node:
        nodes.append((99, -8.299, 41.4005, {"emergency": "water_tank"}))
    with osmium.SimpleWriter(path, header=header) as writer:
        for ident, x, y, tags in nodes:
            writer.add_node(osmium.osm.mutable.Node(id=ident, version=1, location=(x, y), tags=tags))
        for ident, refs, tags in [
            (10, [1, 2, 3, 4], {"highway": "residential", "oneway": "yes", "maxwidth": "2.3", "maxweight": "7.5"}),
            (11, [1, 4], {"highway": "path"}),
            (12, [1, 4], {"highway": "service", "access": "private"}),
            (20, [11, 12, 13, 14, 11], {}),
            (21, [11, 12, 13], {"amenity": "fire_station"}),
            (22, [11, 14], {"emergency": "water_tank"}),
        ]:
            writer.add_way(osmium.osm.mutable.Way(id=ident, version=1, nodes=refs, tags=tags))
        writer.add_relation(osmium.osm.mutable.Relation(id=30, version=1,
            members=[("w", 20, "outer")], tags={"type": "multipolygon", "building": "yes"}))
        writer.add_relation(osmium.osm.mutable.Relation(id=31, version=1,
            members=[("w", 22, "")], tags={"emergency": "fire_water_pond"}))
        writer.add_relation(osmium.osm.mutable.Relation(id=32, version=1,
            members=[("r", 31, "")], tags={"emergency": "fire_water_pond"}))


def activate(root, files, stamp=STAMP, cover=None):
    identity = hashlib.sha256((stamp + str(files)).encode()).hexdigest()[:24]
    folder = root / identity
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for region, src in zip(snapshots.REGIONS, files):
        dest = folder / f"{region}.osm.pbf"
        dest.write_bytes(src.read_bytes())
        rows.append({"region": region, "url": "https://example.test/" + region,
                     "size": dest.stat().st_size, "md5": snapshots.digest(dest, "md5"),
                     "sha256": snapshots.digest(dest), "coverage": mapping(cover or box(-9,40,-7,42))})
    manifest = {"version": 1, "id": identity, "files": rows, "data_timestamp": stamp,
                "created_at": time.time(), "coverage": mapping(cover or box(-9,40,-7,42))}
    snapshots.atomic_json(folder / "manifest.json", manifest)
    snapshots.atomic_json(root / "current.json", {"snapshot_id": identity, "checked_at": time.time(),
                                                "attempted_at": time.time(), "last_error": None})
    return manifest


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.a, self.b = self.root / "a.osm.pbf", self.root / "b.osm.pbf"
        pbf(self.a); pbf(self.b)
        self.polygon = box(-8.301, 41.399, -8.295, 41.403)
        self.network = self.stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("unexpected network")))

    def client(self):
        cache = self.root / "cache"
        self.manifest = activate(cache / "osm-extracts-v1", [self.a,self.b])
        client = source.OSMSource(cache, ["https://overpass.test/api"], working=self.root / "working")
        self.addCleanup(client.close)
        return client


class LocalTests(FixtureCase):
    def test_cross_border_ways_complete_and_tags_preserved(self):
        data = source.extract([self.a,self.b], self.polygon, "roads", FILTER)
        ways = [row for row in data if row["type"] == "way"]
        self.assertEqual([row["id"] for row in ways], [10])
        self.assertEqual(ways[0]["nodes"], [1,2,3,4])
        self.assertEqual(ways[0]["tags"]["maxwidth"], "2.3")
        self.assertEqual(next(row for row in data if row["id"]==1)["tags"]["barrier"], "gate")
        self.assertEqual(len(data),5)

    def test_building_multipolygon_and_nested_resources(self):
        buildings = source.extract([self.a,self.b], self.polygon, "buildings", "")
        self.assertEqual({(row["type"],row["id"]) for row in buildings},
                         {("relation",30),("way",20),*(('node',x) for x in (11,12,13,14))})
        water = source.extract([self.a,self.b], self.polygon, "water", "")
        self.assertEqual({(r["type"],r["id"]) for r in water},
                         {("node",20),("way",22),("relation",31),("relation",32)})
        for row in water:
            if row["type"] != "node":
                self.assertEqual(row["center"], {"lon":-8.3,"lat":41.4015})
        stations = source.extract([self.a,self.b],self.polygon,"stations","")
        self.assertEqual(len(stations),2)
        self.assertEqual(next(r for r in stations if r['type']=='way')['center'],
                         {'lon':(-8.300-8.299)/2,'lat':(41.401+41.402)/2})

    def test_local_and_single_query_road_graphs_match(self):
        client = self.client()
        bounds = [-8.305,41.399,-8.291,41.403]
        token = areas._current_client.set(client)
        try:
            local = areas._download_road_graph(bounds,FILTER)
        finally:
            areas._current_client.reset(token)
        # Independent single-query fixture: do not derive expected data using
        # the local extractor being tested.
        golden = [{'type':'way','id':10,'nodes':[1,2,3,4],
                   'tags':{'highway':'residential','oneway':'yes','maxwidth':'2.3','maxweight':'7.5'}}]
        for ident,x in [(1,-8.304),(2,-8.300),(3,-8.296),(4,-8.292)]:
            golden.append({'type':'node','id':ident,'lon':x,'lat':41.4,
                           'tags':{'barrier':'gate','access':'yes'} if ident==1 else {}})
        remote = Mock(); remote.download.return_value=golden
        token = areas._current_client.set(remote)
        try:
            online = areas._download_road_graph(bounds,FILTER)
        finally:
            areas._current_client.reset(token)
        self.assertEqual(set(local.edges),set(online.edges))
        self.assertEqual(dict(local.nodes),dict(online.nodes))
        for u,v,k,data in local.edges(keys=True,data=True):
            for attr in ('oneway','maxwidth','maxweight','length'):
                self.assertEqual(data[attr],online.edges[u,v,k][attr])
        self.assertFalse(local.has_edge(4,1))
        self.network.assert_not_called()

    def test_distinct_country_roads_join_at_shared_node(self):
        paths=[]
        for region, way, pairs in [('west',40,[(1,-8.304),(2,-8.300)]),
                                  ('east',41,[(2,-8.300),(3,-8.296)])]:
            path=self.root/f'{region}.osm.pbf'; paths.append(path)
            with osmium.SimpleWriter(path) as writer:
                for ident,x in pairs:
                    writer.add_node(osmium.osm.mutable.Node(id=ident,version=1,location=(x,41.4)))
                writer.add_way(osmium.osm.mutable.Way(id=way,version=1,nodes=[p[0] for p in pairs],
                               tags={'highway':'service','oneway':'yes'}))
        result=source.extract(paths,self.polygon,'roads',FILTER)
        self.assertEqual({r['id'] for r in result if r['type']=='node'},{1,2,3})
        self.assertEqual([r['nodes'] for r in result if r['type']=='way'],[[1,2],[2,3]])

    def test_local_building_reader_preserves_multipolygon_geometry(self):
        client=self.client()
        token=areas._current_client.set(client)
        try:
            buildings=areas._download_buildings(list(self.polygon.bounds))
        finally:
            areas._current_client.reset(token)
        self.assertEqual(len(buildings),1)
        self.assertTrue(buildings.iloc[0].geometry.equals(box(-8.300,41.401,-8.299,41.402)))

    @unittest.skipUnless(source.osm_native.executable(), 'optional Osmium CLI is unavailable')
    def test_native_subsets_match_python_for_roads_buildings_and_resources(self):
        client=self.client()
        for kind in ('roads','buildings','water','stations'):
            with self.subTest(kind=kind):
                paths=source.osm_native.subset(client.cache,self.manifest,kind,self.polygon,lambda:None)
                self.assertTrue(paths)
                local=source.extract(paths,self.polygon,kind,FILTER if kind=='roads' else '')
                expected=source.extract([self.a,self.b],self.polygon,kind,FILTER if kind=='roads' else '')
                sort=lambda rows:sorted(rows,key=lambda row:(row['type'],row['id']))
                self.assertEqual(sort(local),sort(expected))

    def test_python_reader_still_works_without_native_tool(self):
        client=self.client()
        with patch.object(source.osm_native,'executable',return_value=None):
            result=client.download(self.polygon,'roads',FILTER)
        self.assertEqual({row['id'] for row in result if row['type']=='way'},{10})
        self.network.assert_not_called()

    def test_local_cache_corruption_rebuilds_and_zero_network(self):
        client = self.client()
        original = client.download(self.polygon,'roads',FILTER)
        with patch.object(source,'extract',side_effect=AssertionError('should reuse cache')):
            self.assertEqual(client.download(self.polygon,'roads',FILTER),original)
        path = next((client.cache/'osm-queries-v1').glob('*.json'))
        damaged=json.loads(path.read_text()); damaged['payload']['elements']=[]
        path.write_text(json.dumps(damaged))
        self.assertEqual(client.download(self.polygon,'roads',FILTER),original)
        self.network.assert_not_called()

    def test_missing_coverage_falls_back_with_original_polygon(self):
        client=self.client(); client.remote.download=Mock(return_value=[])
        polygon=box(-10,40,-7,42)
        client.download(polygon,'roads',FILTER)
        self.assertEqual(client.remote.download.call_args.args,(polygon,'roads',FILTER))
        self.assertEqual(client.provenance['provider'],'overpass')

    def test_corrupt_snapshot_falls_back_and_reports_reason(self):
        client=self.client(); client.remote.download=Mock(return_value=[])
        (client.store.root/self.manifest['id']/'portugal.osm.pbf').write_bytes(b'corrupt')
        with patch.object(client.store,'sync',side_effect=snapshots.LocalOSMError('maps unavailable')) as sync:
            client.download(self.polygon,'roads',FILTER)
            client.download(self.polygon,'buildings')
            self.assertEqual(sync.call_count,1)
        self.assertIn('maps unavailable',client.provenance['fallback_reason'])

    def test_restart_retains_pinned_snapshot_after_refresh(self):
        client=self.client()
        original=client.download(self.polygon,'water')
        pinned=client.snapshot['id']
        next_file=self.root/'new.osm.pbf'; pbf(next_file,extra_node=True)
        activate(client.store.root,[next_file,next_file])
        restarted=source.OSMSource(client.cache,[],working=client.working)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.download(self.polygon,'water'),original)
        self.assertEqual(restarted.snapshot['id'],pinned)

    def test_local_checkpoint_survives_ttl_but_invalid_source_rebuilds(self):
        client=self.client(); client.download(self.polygon,'roads',FILTER)
        folder=self.root/'checkpoint'; folder.mkdir(); area_fixtures.roads(folder)
        metadata={'status':'ready','osm_provenance':client.provenance}
        checkpoints.save(folder,'roads',metadata)
        marker=folder/'roads.checkpoint.json'; value=json.loads(marker.read_text())
        value['saved_at']=0; marker.write_text(json.dumps(value))
        restored=checkpoints.restore(folder,'roads')
        self.assertIsNotNone(restored)
        self.assertTrue(client.restore_metadata(restored))
        (client.store.root/self.manifest['id']/'spain.osm.pbf').write_bytes(b'bad')
        self.assertFalse(client.restore_metadata(restored))

    def test_cancelled_local_extraction_never_falls_back(self):
        client=self.client(); client.remote.download=Mock()
        def cancel(*args,**kw):
            client.check_cancel=Mock(side_effect=areas._Cancelled())
            raise areas._Cancelled()
        with patch.object(source,'extract',side_effect=cancel):
            with self.assertRaises(areas._Cancelled): client.download(self.polygon,'roads',FILTER)
        client.remote.download.assert_not_called()
        self.assertFalse(list((client.cache/'osm-queries-v1').glob('*.json')))

    def test_incomplete_references_rejected(self):
        bad=self.root/'incomplete.osm.pbf'
        with osmium.SimpleWriter(bad) as writer:
            writer.add_node(osmium.osm.mutable.Node(id=1,location=(-8.3,41.4)))
            writer.add_way(osmium.osm.mutable.Way(id=2,nodes=[1,999],tags={'highway':'service'}))
        with self.assertRaisesRegex(RuntimeError,'incomplete'):
            source.extract([bad],self.polygon,'roads',FILTER)


class HTTPResponse:
    def __init__(self, content, status=200, headers=None, error=None):
        self.content, self.status_code, self.headers = content,status,headers or {'Content-Length':str(len(content))}
        self.error=error
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def raise_for_status(self): pass
    def iter_content(self, size):
        yield self.content
        if self.error: raise self.error


class SnapshotTests(FixtureCase):
    # Snapshot tests use the same tiny real PBF fixtures; no national downloads.
    def store(self):
        store=snapshots.SnapshotStore(self.root/'store',session=Mock())
        self.addCleanup(store.close)
        store._source_urls=Mock(return_value={r:'https://example.test/'+r for r in snapshots.REGIONS})
        def text(url):
            if url.endswith('.poly'): return POLY
            return snapshots.digest(self.a if 'portugal' in url else self.b,'md5')
        store._text=Mock(side_effect=text)
        store._download=Mock(side_effect=lambda url,region,md5:self.a if region=='portugal' else self.b)
        return store

    def test_sync_activates_only_valid_matching_timestamp_pair(self):
        store=self.store(); result=store.sync()
        self.assertEqual(result['data_timestamp'],STAMP)
        self.assertEqual(store.current()['id'],result['id'])
        self.assertEqual(store._download.call_count,2)
        store.sync()
        self.assertEqual(store._download.call_count,2)

    def test_mismatched_or_failed_refresh_keeps_previous_snapshot(self):
        store=self.store(); before=store.sync()
        old=self.b; self.b=self.root/'different.osm.pbf'
        pbf(self.b,'2026-01-01T00:00:00Z')
        with self.assertRaisesRegex(snapshots.LocalOSMError,'different data timestamps'): store.sync(force=True)
        self.assertEqual(store.current()['id'],before['id'])
        self.assertTrue(snapshots.read_json(store.root/'current.json')['last_error'])
        self.b=old
        store._source_urls.side_effect=requests.ConnectionError('offline')
        with self.assertRaises(requests.ConnectionError): store.sync(force=True)
        self.assertEqual(store.current()['id'],before['id'])

    def test_unreadable_pbf_with_valid_checksum_cannot_replace_snapshot(self):
        store=self.store(); before=store.sync()
        self.b=self.root/'bad.osm.pbf'; self.b.write_bytes(b'not a PBF')
        with self.assertRaises(RuntimeError): store.sync(force=True)
        self.assertEqual(store.current()['id'],before['id'])

    def test_cancel_before_activation_keeps_previous_snapshot(self):
        store=self.store(); before=store.sync()
        original=snapshots.atomic_json
        def write(path,value):
            original(path,value)
            if path.name=='manifest.json':
                store.check_cancel=Mock(side_effect=areas._Cancelled())
        with patch.object(snapshots,'atomic_json',side_effect=write):
            with self.assertRaises(areas._Cancelled): store.sync(force=True)
        store.check_cancel=lambda:None
        self.assertEqual(store.current()['id'],before['id'])

    def test_download_resume_and_ignored_range(self):
        for resume in (True,False):
            with self.subTest(resume=resume):
                store=snapshots.SnapshotStore(self.root/str(resume),session=Mock())
                self.addCleanup(store.close); store.root.mkdir()
                data=b'abcdef'; md5=hashlib.md5(data).hexdigest()
                store.session.get.side_effect=[HTTPResponse(b'abc',headers={'Content-Length':'6'},
                    error=requests.ConnectionError('interrupted')),
                    HTTPResponse(b'def',206,{'Content-Range':'bytes 3-5/6'}) if resume else HTTPResponse(data)]
                with patch.object(snapshots.time,'sleep'):
                    path=store._download('https://example.test/file','portugal',md5)
                self.assertEqual(path.read_bytes(),data)
                self.assertEqual(store.session.get.call_args.kwargs['headers']['Range'],'bytes=3-')

    def test_bad_checksum_or_insufficient_storage_never_activates(self):
        store=snapshots.SnapshotStore(self.root/'download',session=Mock()); store.root.mkdir()
        self.addCleanup(store.close)
        store.session.get.return_value=HTTPResponse(b'bad')
        with patch.object(snapshots.time,'sleep'):
            with self.assertRaisesRegex(snapshots.LocalOSMError,'checksum'):
                store._download('url','portugal',hashlib.md5(b'good').hexdigest())
        self.assertFalse(list(store.root.rglob('*.osm.pbf')))
        with patch.object(snapshots.shutil,'disk_usage',return_value=Mock(free=0)):
            with self.assertRaises(snapshots.LocalOSMError) as context:
                store._download('url','portugal',hashlib.md5(b'good').hexdigest())
        self.assertEqual(context.exception.code,'insufficient_disk_space')
        self.assertIsNone(store.current())

    def test_cancellation_preserves_download_for_restart(self):
        store=snapshots.SnapshotStore(self.root/'download',session=Mock()); store.root.mkdir()
        self.addCleanup(store.close)
        response=HTTPResponse(b'abc'); store.session.get.return_value=response
        checks=0
        def cancel():
            nonlocal checks
            checks+=1
            if checks>=3: raise areas._Cancelled()
        store.check_cancel=cancel
        with self.assertRaises(areas._Cancelled): store._download('url','portugal',hashlib.md5(b'abc').hexdigest())
        self.assertIsNone(store.current())
        self.assertTrue(list(store.root.rglob('*.part')))

    def test_concurrent_sync_downloads_once(self):
        first=self.store(); second=self.store()
        entered,release=threading.Event(),threading.Event()
        original=first._download.side_effect
        def download(*args):
            entered.set(); release.wait(2)
            return original(*args)
        first._download.side_effect=download
        second.progress=lambda **kw: release.set()
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(first.sync); self.assertTrue(entered.wait(2))
            b=pool.submit(second.sync)
            self.assertEqual(a.result()['id'],b.result()['id'])
        self.assertEqual(first._download.call_count+second._download.call_count,2)

    def test_stale_snapshot_remains_usable_and_failed_refresh_is_visible(self):
        client=self.client()
        client.snapshot=client.store.current()
        client.snapshot['data_timestamp']=(datetime.now(UTC)-timedelta(days=20)).isoformat()
        pointer=snapshots.read_json(client.store.root/'current.json')
        snapshots.atomic_json(client.store.root/'current.json',{**pointer,'last_error':'offline'})
        provenance=client._provenance(client.snapshot)
        self.assertTrue(provenance['stale'])
        self.assertEqual(provenance['refresh_error'],'offline')


if __name__ == '__main__':
    unittest.main()
