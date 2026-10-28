from critical_helpers import patch_server_state
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import worker_fleet

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fleet_observer', ROOT/'deploy/host/fleet_snapshot.py')
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class FleetSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'fleet.json'
        self.snapshot = {'schema': 1, 'checked_at': 1000, 'nodes': [
            {'id': 'homeserver', 'configured_workers': 2, 'active_workers': 2,
             'ready_workers': 2, 'online': True, 'checked_at': 1000},
            {'id': 'ubuntu-pc', 'configured_workers': 10, 'active_workers': 10,
             'ready_workers': 10, 'online': True, 'checked_at': 1000}]}

    def write(self):
        self.path.write_text(json.dumps(self.snapshot))
        self.path.chmod(0o640)
        return worker_fleet.read_snapshot(self.path, now=1001)

    def test_counts_fleet_and_only_allows_public_capacity_fields(self):
        self.snapshot['nodes'][1]['secret'] = 'PRIVATE'
        result = self.write()
        self.assertEqual(result['workers'], 12)
        self.assertEqual(result['scope'], 'fleet')
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_offline_or_stale_node_drops_out_without_static_total(self):
        for change in ({'online': False}, {'checked_at': 900}):
            with self.subTest(change=change):
                self.snapshot['nodes'][1].update(change)
                result = self.write()
                self.assertEqual(result['workers'], 2)
                self.assertEqual(result['configured_workers'], 12)
                self.assertFalse(result['nodes'][1]['online'])

    def test_unready_active_supervisors_do_not_count_as_ready_workers(self):
        self.snapshot['nodes'][1]['ready_workers'] = 0
        result = self.write()
        self.assertEqual(result['active_workers'], 12)
        self.assertEqual(result['workers'], 2)

    def test_missing_stale_malformed_and_future_snapshots_are_unknown(self):
        self.assertIsNone(worker_fleet.read_snapshot(self.path)['workers'])
        for stamp in (900, 2000, float('nan'), True):
            self.snapshot['checked_at'] = stamp
            self.assertIsNone(self.write()['workers'])
        self.path.write_text('not json')
        self.assertIsNone(worker_fleet.read_snapshot(self.path)['workers'])

    def test_invalid_duplicate_and_excessive_node_counts_fail_closed(self):
        for change in ({'active_workers': -1}, {'ready_workers': 11},
                       {'configured_workers': 129}, {'ready_workers': True},
                       {'id': 'homeserver'}, {'id': '<script>'}):
            with self.subTest(change=change):
                original = copy.deepcopy(self.snapshot)
                self.snapshot['nodes'][1].update(change)
                self.assertIsNone(self.write()['workers'])
                self.snapshot = original

    def test_symlink_hardlink_world_writable_and_oversized_files_fail_closed(self):
        self.write()
        target = self.path.with_name('symlink')
        target.symlink_to(self.path)
        self.assertIsNone(worker_fleet.read_snapshot(target)['workers'])
        target.unlink()
        os.link(self.path, target)
        self.assertIsNone(worker_fleet.read_snapshot(self.path)['workers'])
        target.unlink()
        self.path.chmod(0o666)
        self.assertIsNone(worker_fleet.read_snapshot(self.path)['workers'])
        self.path.chmod(0o640)
        self.path.write_text('x' * (worker_fleet.MAX_BYTES + 1))
        self.assertIsNone(worker_fleet.read_snapshot(self.path)['workers'])

    def test_remote_timeout_and_stale_metrics_report_offline(self):
        peer = {'id': 'ubuntu-pc', 'workers': 10, 'url': 'http://test.invalid/metrics'}
        with patch.object(observer.urllib.request, 'urlopen', side_effect=TimeoutError):
            result = observer.peer_node(peer, 1000)
        self.assertFalse(result['online'])
        self.assertEqual(result['ready_workers'], 0)

    def test_remote_metrics_are_typed_bounded_and_fresh(self):
        import io
        peer = {'id': 'ubuntu-pc', 'workers': 10, 'url': 'http://test.invalid/metrics'}
        for stamp, active, ready, expected in [(1000,10,10,True), (900,10,10,False),
                                               (1000,11,11,False), (1000,10,'nan',False),
                                               (1000,10,9.5,False), (1000,10,0,True)]:
            body = ('newbiegrader_node_workers_active{node="ubuntu-pc"} '+str(active)+'\n'
                    'newbiegrader_node_workers_ready{node="ubuntu-pc"} '+str(ready)+'\n'
                    'newbiegrader_node_snapshot_seconds{node="ubuntu-pc"} '+str(stamp)+'\n').encode()
            with patch.object(observer.urllib.request, 'urlopen', return_value=io.BytesIO(body)):
                result = observer.peer_node(peer, 1001)
            self.assertEqual(result['online'], expected)

    def test_api_report_changes_do_not_change_execution_capacity(self):
        from critical_helpers import test_server
        server = test_server()
        self.snapshot['checked_at'] = __import__('time').time()
        for node in self.snapshot['nodes']: node['checked_at'] = self.snapshot['checked_at']
        self.write()
        original = server.JUDGE_WORKERS
        with patch.dict(os.environ, {'GRADER_FLEET_STATUS_FILE': str(self.path)}):
            self.assertEqual(server._host_limits()['judge_workers'], 12)
            self.assertEqual(server._host_limits()['local_judge_workers'], original)
            self.assertEqual(server.JUDGE_WORKERS, original)
        with patch.dict(os.environ, {'GRADER_FLEET_STATUS_FILE': ''}):
            self.assertEqual(server._host_limits()['judge_workers'], original)
            self.assertEqual(server._host_limits()['worker_scope'], 'local')

    def test_admin_overview_uses_fleet_and_stale_observation_is_unknown(self):
        import asyncio
        import time
        from contextlib import ExitStack
        from starlette.requests import Request
        from critical_helpers import test_server
        from fake_supabase import FakeSupabase
        server = test_server()
        self.snapshot['checked_at'] = time.time()
        for node in self.snapshot['nodes']:
            node['checked_at'] = self.snapshot['checked_at']
        self.write()
        request = Request({'type': 'http', 'session': {'user': {'email': 'admin@synthetic.invalid'}}})
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {'GRADER_FLEET_STATUS_FILE': str(self.path)}))
            for name, value in {'_sb': FakeSupabase(), '_is_admin': lambda email: True,
                                '_ensure_problems_fresh': lambda: None, '_hidden_pids': lambda: [],
                                '_contest_problem_sets': lambda: (set(), set()), 'PROBLEMS': {},
                                'QUEUE_MODE': 'local'}.items():
                stack.enter_context(patch_server_state(server, name, value))
            result = asyncio.run(server.admin_overview(request))
            self.assertEqual(result['jobs']['workers'], 12)
            self.snapshot['checked_at'] = 0
            self.write()
            result = asyncio.run(server.admin_overview(request))
            self.assertIsNone(result['jobs']['workers'])
