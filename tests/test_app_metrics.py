import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('fleet_app_metrics', Path(__file__).resolve().parents[1] / 'deploy/host/fleet_snapshot.py')
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class AppMetricsTests(unittest.TestCase):
    def test_healthy_grader_uses_catalog_contract(self):
        config = {'id': 'home', 'apps': {'grader': {'url': 'https://example.invalid/api/health', 'kind': 'grader'}}}
        for body, expected in ((b'{"ok":true,"count":100}', 1), (b'{"ok":true,"count":99}', 0), (b'[]', 0)):
            with patch.object(observer.urllib.request, 'urlopen', return_value=io.BytesIO(body)) as get:
                lines = observer.app_metrics(config)
                self.assertIn('newbiegrader_app_up{node="home",app="grader"} '+str(expected), lines)
                self.assertEqual(get.call_args.args[0].get_header('User-agent'), 'Newbiegrader-fleet-observer/1')

    def test_timeout_and_oversized_response_are_unavailable_without_exception_details(self):
        config = {'id': 'pc', 'apps': {'cloud': {'url': 'https://example.invalid/status.php', 'kind': 'nextcloud'}}}
        for failure in (TimeoutError('PRIVATE'), None):
            with patch.object(observer.urllib.request, 'urlopen', side_effect=failure,
                              return_value=io.BytesIO(b'x'*16385)):
                lines = observer.app_metrics(config)
            self.assertIn('newbiegrader_app_up{node="pc",app="cloud"} 0', lines)
            self.assertNotIn('PRIVATE', '\n'.join(lines))
