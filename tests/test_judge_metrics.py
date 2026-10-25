import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.parse

spec = importlib.util.spec_from_file_location('judge_metrics',Path(__file__).resolve().parents[1]/'deploy/host/judge_metrics.py')
metrics = importlib.util.module_from_spec(spec);spec.loader.exec_module(metrics)


class JudgeMetrics(unittest.TestCase):
    def test_user_wrong_answers_are_separate_from_backend_errors(self):
        jobs = [{'kind':'submit','status':'done','started_at':'2026-10-25T00:00:00Z','finished_at':'2026-10-25T00:00:02Z'},
                {'kind':'submit','status':'error','started_at':'2026-10-25T00:00:00Z','finished_at':'2026-10-25T00:00:04Z'}]
        result=metrics.summarize(jobs,[{'verdict':'WA','accepted':False},{'verdict':'AC','accepted':True}])
        self.assertEqual(result['backend_errors'],1);self.assertEqual(result['failed'],1)
        self.assertEqual(result['p50'],2);self.assertEqual(result['p95'],4)

    def test_empty_window_has_no_invented_duration(self):
        result=metrics.summarize([],[])
        self.assertEqual(result['samples'],0);self.assertNotIn('p50',result)

    def test_invalid_and_negative_durations_are_excluded(self):
        for row in [{},{'started_at':'bad','finished_at':'bad'},
                    {'started_at':'2026-10-25T00:00:04Z','finished_at':'2026-10-25T00:00:02Z'}]:
            self.assertIsNone(metrics.duration(row))

    def test_database_fields_are_allowlisted_and_truncation_reported(self):
        calls=[]
        def request(settings,path,body=None):calls.append(path);return []
        with patch.object(metrics,'request_json',side_effect=request):metrics.statistics({},1000)
        for path in calls:
            query=urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            self.assertEqual(query['limit'],['1000'])
            self.assertNotIn('source',query['select'][0]);self.assertNotIn('result',query['select'][0]);self.assertNotIn('email',query['select'][0])
        result=metrics.summarize([],[{'verdict':'AC','accepted':True}]*1000)
        self.assertEqual(result['truncated'],1)

    def test_bad_destination_is_rejected_before_sending_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'env';path.write_text('SUPABASE_URL=https://untrusted.invalid\nSUPABASE_KEY=synthetic\n')
            with self.assertRaises(ValueError):metrics.read_settings(path)

    def test_outage_exports_unavailable_without_fabricated_counts_or_secrets(self):
        with patch.object(metrics,'read_settings',side_effect=OSError('SYNTHETIC_PRIVATE')):
            self.assertEqual(metrics.collect({'env_file':'/synthetic'},1000),['newbiegrader_judge_metrics_up 0'])

    def test_config_disabled_never_reads_credentials(self):
        with patch.object(metrics,'read_settings') as read:
            self.assertEqual(metrics.collect(None),[]);read.assert_not_called()
