import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

observer = module('optional_fleet', 'deploy/host/fleet_snapshot.py')
watchdog = module('optional_watchdog', 'deploy/host/newbiegrader-alert.py')


class OptionalHomeIntegration(unittest.TestCase):
    def test_disabled_exporters_need_no_external_module(self):
        with patch('importlib.import_module') as load:
            self.assertEqual(observer.auxiliary_metrics({'id': 'pc'}), [])
        load.assert_not_called()

    def test_missing_exporter_reports_unavailable_without_breaking_fleet_observation(self):
        with patch('importlib.import_module', side_effect=ImportError):
            lines = observer.auxiliary_metrics({'id': 'pc', 'hardware_metrics': True})
        self.assertEqual(lines, ['newbiegrader_auxiliary_exporter_up{exporter="hardware"} 0'])

    def test_external_exporter_values_are_preserved(self):
        plugin = types.SimpleNamespace(collect=lambda node: ['sensor{node="'+node+'"} 45'])
        with patch('importlib.import_module', return_value=plugin):
            lines = observer.auxiliary_metrics({'id': 'pc', 'hardware_metrics': True})
        self.assertIn('sensor{node="pc"} 45', lines)
        self.assertIn('newbiegrader_auxiliary_exporter_up{exporter="hardware"} 1', lines)

    def test_watchdog_optional_module_is_explicit_and_fail_closed(self):
        self.assertEqual(watchdog._extra_health_checks(''), [])
        with patch.dict('sys.modules', {'private_service_health': None}):
            checks = watchdog._extra_health_checks('{"cloud":"https://example.invalid"}')
        self.assertFalse(checks[0]['ok'])

    def test_watchdog_uses_external_service_health_contract(self):
        plugin = types.ModuleType('private_service_health')
        plugin.collect_checks = lambda raw: [{'name': 'service cloud', 'ok': False, 'detail': 'unavailable'}]
        with patch.dict('sys.modules', {'private_service_health': plugin}):
            checks = watchdog._extra_health_checks('{}')
        self.assertFalse(checks[0]['ok'])
