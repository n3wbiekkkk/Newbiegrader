import unittest
import contextlib
import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from deploy.host.fleet_peer_push import main, node_metrics


class PeerMetricsTests(unittest.TestCase):
    def metrics(self, stamp=1000):
        return ('newbiegrader_node_workers_active{node="homeserver"} 2\n'
                'newbiegrader_node_workers_ready{node="homeserver"} 1\n'
                'newbiegrader_node_workers_configured{node="homeserver"} 2\n'
                f'newbiegrader_node_snapshot_seconds{{node="homeserver"}} {stamp}\n')

    def test_exports_only_selected_node_worker_observations(self):
        extra = ('newbiegrader_private_app{node="homeserver"} 1\n'
                 'newbiegrader_node_workers_active{node="other"} 10\n')
        result = node_metrics(self.metrics() + extra, 'homeserver', now=1001)
        self.assertEqual(len(result.splitlines()), 4)
        self.assertNotIn('private_app', result)
        self.assertNotIn('other', result)

    def test_rejects_missing_duplicate_and_nonfinite_observations(self):
        for raw in (self.metrics().replace('ready', 'unknown'),
                    self.metrics() + self.metrics().splitlines()[0] + '\n',
                    self.metrics().replace(' 2\n', ' nan\n'),
                    self.metrics().replace(' 1\n', ' 2.5\n'),
                    self.metrics().replace(' 1\n', ' 3\n')):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                node_metrics(raw, 'homeserver', now=1001)

    def test_stale_or_future_metrics_cannot_refresh_peer_health(self):
        for stamp in (950, 1010):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                node_metrics(self.metrics(stamp), 'homeserver', now=1000)

    def test_relays_fresh_remote_pc_observations_without_other_metrics(self):
        source = 'http://100.88.67.72:9100/metrics'
        target = 'http://100.91.14.10:9187/ubuntu-pc.prom'
        raw = self.metrics().replace('homeserver', 'ubuntu-pc')
        raw += 'private_app_secret{node="ubuntu-pc"} 12345\n'
        upstream = MagicMock()
        upstream.__enter__.return_value = SimpleNamespace(
            status=200, geturl=lambda: source, read=lambda size: raw.encode())
        destination = MagicMock()
        destination.__enter__.return_value = SimpleNamespace(status=201)
        with patch('sys.argv', ['push', '--metrics-url', source, '--node', 'ubuntu-pc',
                               '--destination', target]), \
                patch('deploy.host.fleet_peer_push.time.time', return_value=1001), \
                patch('deploy.host.fleet_peer_push.urllib.request.urlopen',
                      side_effect=[upstream, destination]) as open_url, \
                contextlib.redirect_stdout(io.StringIO()):
            main()
        sent = open_url.call_args_list[1].args[0]
        self.assertEqual(sent.full_url, target)
        self.assertEqual(sent.get_method(), 'PUT')
        self.assertIn(b'node="ubuntu-pc"', sent.data)
        self.assertNotIn(b'private_app', sent.data)
        self.assertNotIn(b'homeserver', sent.data)

    def test_stale_remote_pc_metrics_are_not_forwarded(self):
        source = 'http://100.88.67.72:9100/metrics'
        upstream = MagicMock()
        upstream.__enter__.return_value = SimpleNamespace(
            status=200, geturl=lambda: source,
            read=lambda size: self.metrics(stamp=900).replace('homeserver', 'ubuntu-pc').encode())
        output = io.StringIO()
        with patch('sys.argv', ['push', '--metrics-url', source, '--node', 'ubuntu-pc',
                               '--destination', 'http://100.91.14.10:9187/ubuntu-pc.prom']), \
                patch('deploy.host.fleet_peer_push.time.time', return_value=1001), \
                patch('deploy.host.fleet_peer_push.urllib.request.urlopen',
                      return_value=upstream) as open_url, contextlib.redirect_stdout(output):
            main()
        self.assertEqual(open_url.call_count, 1)
        self.assertIn('false', output.getvalue())
