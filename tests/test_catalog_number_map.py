"""Public numbering manifest; no fixtures, references, credentials or live DB."""
import csv
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CatalogNumberMap(unittest.TestCase):
    def test_approved_map_is_bijective_and_in_difficulty_order(self):
        with (ROOT / 'docs/catalog/problem-numbers-2026-10-20.csv').open() as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 89)
        self.assertEqual(len({row['slug'] for row in rows}), 89)
        self.assertEqual([int(row['new_no']) for row in rows], list(range(1, 90)))
        rank = {'easy': 0, 'medium': 1, 'hard': 2}
        levels = [rank[row['difficulty']] for row in rows]
        self.assertEqual(levels, sorted(levels))
        old = [int(row['old_no']) for row in rows if row['old_no']]
        self.assertEqual(sorted(old), list(range(1, 70)))
        self.assertEqual(sum(not row['old_no'] for row in rows), 20)
        self.assertEqual(next(row['old_no'] for row in rows if row['slug'] == 'lucky_bracelet'), '69')

    def test_https_smoke_rejects_invalid_count_before_any_request(self):
        result = subprocess.run([sys.executable, str(ROOT / 'deploy/ec2/smoke_https.py'),
                                 '--production', '--expected-problems', '0'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--expected-problems must be positive', result.stderr)
