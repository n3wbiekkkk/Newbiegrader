import importlib.util,json
from pathlib import Path
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('extra_health',Path(__file__).resolve().parents[1]/'deploy/host/newbiegrader-alert.py');alert=importlib.util.module_from_spec(spec);spec.loader.exec_module(alert)


class ExtraHealth(unittest.TestCase):
    def test_disabled_has_no_network(self):
        with patch.object(alert,'_get_json') as get:
            self.assertEqual(alert._extra_health_checks(''),[]);get.assert_not_called()

    def test_nextcloud_ready_is_explicit_and_maintenance_fails(self):
        raw=json.dumps({'Nextcloud':'https://cloud.example.invalid/status.php'})
        for maintenance in (False,True):
            with patch.object(alert,'_get_json',return_value={'installed':True,'maintenance':maintenance,'needsDbUpgrade':False}):
                self.assertEqual(alert._extra_health_checks(raw)[0]['ok'],not maintenance)

    def test_unsafe_urls_are_rejected_before_request_and_errors_are_redacted(self):
        for url in ('http://cloud.example.invalid','https://user:password@cloud.example.invalid','https://cloud.example.invalid?secret=value'):
            with patch.object(alert,'_get_json') as get:
                self.assertFalse(alert._extra_health_checks(json.dumps({'test':url}))[0]['ok']);get.assert_not_called()
        with patch.object(alert,'_get_json',side_effect=OSError('PRIVATE_SECRET')):
            checks=alert._extra_health_checks(json.dumps({'test':'https://cloud.example.invalid/status.php'}))
        self.assertNotIn('PRIVATE_SECRET',json.dumps(checks));self.assertFalse(checks[0]['ok'])
