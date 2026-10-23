"""Public numbering manifest; no fixtures, references, credentials or live DB."""
import csv
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import grader  # noqa: E402

CURRENT_MAP = ROOT / 'docs/catalog/problem-numbers-2026-10-22.csv'
PREVIOUS_MAP = ROOT / 'docs/catalog/problem-numbers-2026-10-20.csv'


def read_map(path):
    with path.open(encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


class CatalogNumberMap(unittest.TestCase):
    def test_current_map_is_bijective_and_in_difficulty_order(self):
        rows = read_map(CURRENT_MAP)
        self.assertEqual(len(rows), 89)
        self.assertEqual(len({row['slug'] for row in rows}), 89)
        self.assertEqual([int(row['new_no']) for row in rows], list(range(1, 90)))

    def test_numbers_rise_with_the_calibrated_level(self):
        rows = read_map(CURRENT_MAP)
        levels = [int(row['level']) for row in rows]
        self.assertEqual(levels, sorted(levels),
                         "a problem number must not fall as the calibrated level rises")
        for row in rows:
            self.assertIn(int(row['level']), grader.VALID_LEVELS)

    def test_band_matches_the_level_and_the_bands_do_not_go_backwards(self):
        rows = read_map(CURRENT_MAP)
        rank = {'easy': 0, 'medium': 1, 'hard': 2}
        bands = []
        for row in rows:
            level = int(row['level'])
            self.assertEqual(row['difficulty'], grader.band_for_level(level),
                             f"{row['slug']}: band must follow level {level}")
            bands.append(rank[row['difficulty']])
        self.assertEqual(bands, sorted(bands))

    def test_map_records_the_numbers_it_replaced(self):
        rows = read_map(CURRENT_MAP)
        old = sorted(int(row['old_no']) for row in rows if row['old_no'])
        self.assertEqual(old, list(range(1, 90)))

    def test_previous_map_is_still_the_historical_record(self):
        rows = read_map(PREVIOUS_MAP)
        self.assertEqual(len(rows), 89)
        self.assertEqual(len({row['slug'] for row in rows}), 89)
        self.assertEqual([int(row['new_no']) for row in rows], list(range(1, 90)))

    def test_local_packages_match_the_approved_map(self):
        # problems/ is a private working copy; skip where it is absent (CI).
        if not grader.PROBLEMS_DIR.is_dir():
            self.skipTest("no local problems/ to compare against the map")
        rows = read_map(CURRENT_MAP)
        for row in rows:
            slug = row['slug']
            path = grader.PROBLEMS_DIR / slug / 'config.json'
            self.assertTrue(path.is_file(), f"missing package {slug}")
            import json
            cfg = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(int(cfg['no']), int(row['new_no']), f"{slug}: number drifted")
            self.assertEqual(int(cfg['level']), int(row['level']), f"{slug}: level drifted")
            self.assertEqual(cfg['difficulty'], row['difficulty'], f"{slug}: band drifted")

    def test_number_tool_accepts_the_approved_map(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / 'tools/number_problems.py'), '--order',
             str(CURRENT_MAP), '--dry-run'],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_https_smoke_rejects_invalid_count_before_any_request(self):
        result = subprocess.run([sys.executable, str(ROOT / 'deploy/host/smoke_https.py'),
                                 '--production', '--expected-problems', '0'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--expected-problems must be positive', result.stderr)
