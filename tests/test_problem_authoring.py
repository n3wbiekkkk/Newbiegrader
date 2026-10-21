# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Authoring contract regressions; synthetic data only, no local problems/ needed."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import grader
from tools import import_problems_supabase as importer
from tools import make_statement_tex as renderer
from tools import problem_authoring as author
from tools import validate_problem as validator
from tools.statement_build import build_record, check_build


# Deliberately independent grammar: small integer grid and trailing step count.
# Validates every line, bounds, allowed values and separators, not just split().
GRID_VALIDATOR = '''import sys
try:
    lines = sys.stdin.read().splitlines()
    dims = lines[0].split()
    assert len(dims) == 2
    r, c = map(int, dims)
    assert 1 <= r <= 5 and 1 <= c <= 5 and len(lines) == r + 2
    for line in lines[1:1+r]:
        cells = line.split()
        assert len(cells) == c and all(x in ("0", "1", "2") for x in cells)
    assert len(lines[-1].split()) == 1 and 0 <= int(lines[-1]) <= 3
except (ValueError, IndexError, AssertionError):
    raise SystemExit(1)
'''


class ProblemAuthoring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for module, name, value in ((author, "ROOT", self.root),
                                    (renderer, "ROOT", self.root),
                                    (grader, "PROBLEMS_DIR", self.root / "problems"),
                                    (validator, "PROBLEMS_DIR", self.root / "problems"),
                                    (validator, "EXAMPLES_DIR", self.root / "examples")):
            self.stack.enter_context(patch.object(module, name, value))
        # These tests isolate authoring from the judge. The real references are
        # exercised separately by the repository validator / Linux test suite.
        self.stack.enter_context(patch.object(grader, "prepare_command", return_value=(["unused"], "synthetic", "")))
        self.stack.enter_context(patch.object(grader, "judge_test", return_value=("AC", 0.0, 0.0, 0, "", "")))

    def package(self):
        self.pdir = author.create_problem(self.root, "synthetic_grid", "ตารางสังเคราะห์", "Synthetic Grid", 1)
        for i, name in enumerate(["01", "02", "03"] + [str(n) for n in range(1001, 1008)]):
            value = i % 3
            (self.pdir / "tests" / f"{name}.in").write_text(f"1 2\n{value} {value}\n0\n")
            (self.pdir / "tests" / f"{name}.out").write_text(f"{value * 2}\n")
        path = self.pdir / "statement.md"
        path.write_text("# ตารางสังเคราะห์ (Synthetic Grid)\n\nเรื่องและกติกาสังเคราะห์\n"
                        "## Input\nแถวตารางเป็นจำนวนเต็มคั่นด้วยช่องว่าง\n"
                        "## Output\nผลรวมของค่าทุกช่อง\n## ตัวอย่าง\n\n"
                        "## คำอธิบายตัวอย่าง\nค่าผลรวม\n"
                        "## Limits\n- เวลา 1 วินาที, หน่วยความจำ 256 MB\n")
        (self.pdir / "input_validator.py").write_text(GRID_VALIDATOR)
        (self.root / "examples/synthetic_grid_ref.py").write_text(
            "import sys\nprint(sum(map(int, sys.stdin.read().split()[2:-1])))\n")
        (self.pdir / "statement.pdf").write_bytes(b"%PDF-synthetic\n" + b"x" * 1200)
        author.sync_samples(self.pdir, write=True)
        self.record_build()
        return self.pdir

    def record_build(self):
        cfg = json.loads((self.pdir / "config.json").read_text())
        record = build_record(cfg, (self.pdir / "statement.md").read_text(),
                              (self.pdir / "statement.pdf").read_bytes())
        (self.pdir / "statement.build.json").write_text(json.dumps(record))

    def test_new_draft_has_standard_titles_and_fails_until_completed(self):
        pdir = author.create_problem(self.root, "draft", "ฉบับร่าง", "Draft", 7)
        cfg = json.loads((pdir / "config.json").read_text())
        self.assertEqual(cfg["title"], "ฉบับร่าง (Draft)")
        self.assertEqual(cfg["samples"], ["01", "02", "03"])
        res = validator.validate_problem("draft", strict=True)
        self.assertTrue(res["failures"])
        self.assertTrue(any("placeholders" in e for e in res["failures"]))

    def test_duplicate_number_and_existing_package_are_not_overwritten(self):
        self.package()
        before = (self.pdir / "statement.md").read_bytes()
        for pid in ("synthetic_grid", "another_grid"):
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                author.create_problem(self.root, pid, "อีกข้อ", "Another", 1)
        self.assertEqual((self.pdir / "statement.md").read_bytes(), before)
        self.assertFalse((self.root / "problems/another_grid").exists())

    def test_path_traversal_and_bad_titles_are_rejected(self):
        for pid in ("../escape", "BadName", "/tmp/escape", "bad-name"):
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                author.create_problem(self.root, pid, "ชื่อ", "Name", 1)
        with self.assertRaises(ValueError):
            author.create_problem(self.root, "bad_title", "ชื่อ\n## Input", "Name", 1)

    def test_sync_is_read_only_by_default_and_idempotent_when_written(self):
        self.package()
        md = self.pdir / "statement.md"
        old = md.read_text()
        old_tests = {f.name: f.read_bytes() for f in (self.pdir / "tests").iterdir()}
        self.assertTrue(author.sync_samples(self.pdir))
        md.write_text(old.replace("0 0", "00"))
        wrong = md.read_text()
        self.assertFalse(author.sync_samples(self.pdir))
        self.assertEqual(md.read_text(), wrong)
        self.assertFalse(author.sync_samples(self.pdir, write=True))
        self.assertTrue(author.sync_samples(self.pdir, write=True))
        self.assertEqual(md.read_text(), old)
        self.assertEqual(old_tests, {f.name: f.read_bytes() for f in (self.pdir / "tests").iterdir()})

    def test_sync_copies_only_public_tests_and_preserves_other_sections(self):
        self.package()
        md = self.pdir / "statement.md"
        old = md.read_text()
        (self.pdir / "tests/1001.in").write_text("PRIVATE_SYNTHETIC_CANARY\n")
        author.sync_samples(self.pdir, write=True)
        self.assertEqual(md.read_text(), old)
        self.assertNotIn("PRIVATE_SYNTHETIC_CANARY", md.read_text())
        cfg = json.loads((self.pdir / "config.json").read_text())
        cfg["samples"] = ["01", "02", "1001"]
        (self.pdir / "config.json").write_text(json.dumps(cfg))
        with self.assertRaises(ValueError):
            author.sync_samples(self.pdir, write=True)
        self.assertEqual(md.read_text(), old)

    def test_valid_package_passes_strict_checks(self):
        self.package()
        self.assertEqual(validator.validate_problem("synthetic_grid", strict=True)["failures"], [])

    def test_whitespace_mismatch_and_reordered_samples_fail(self):
        self.package()
        md = self.pdir / "statement.md"
        original = md.read_text()
        for wrong in (original.replace("0 0", "0  0"),
                      original.replace("1 1", "11"),
                      original.replace("1 1", "2 2").replace("output:\n2\n", "output:\n4\n")):
            with self.subTest(), patch.object(grader, "load_problem", wraps=grader.load_problem):
                md.write_text(wrong)
                result = validator.validate_problem("synthetic_grid")
                self.assertTrue(any("must match public test" in e for e in result["failures"]))
        md.write_text(original)

    def test_malformed_hidden_grid_is_rejected_without_echoing_data(self):
        self.package()
        (self.pdir / "tests/1001.in").write_text("1 2\n12\n0\n")
        result = validator.validate_problem("synthetic_grid", strict=True)
        self.assertTrue(any("rejected test 1001" in e for e in result["failures"]))
        self.assertNotIn("1 2\n12", str(result))

    def test_grammar_rejects_invalid_bounds_rows_values_and_extra_data(self):
        self.package()
        path = str(self.pdir / "input_validator.py")
        invalid = ["0 2\n0\n", "1 2\n1 2 0\n0\n", "1 2\n1 3\n0\n",
                   "1 2\n1 2\n4\n", "1 2\n1 2\n0\nextra\n", "1 2\n12\n0\n"]
        for data in invalid:
            with self.subTest(data=data):
                result = subprocess.run([sys.executable, "-I", path], input=data.encode(),
                                        capture_output=True, timeout=2)
                self.assertEqual(result.returncode, 1)

    def test_validator_timeout_and_output_do_not_leak_contents(self):
        self.package()
        (self.pdir / "input_validator.py").write_text('print("PRIVATE_SYNTHETIC_CANARY"); raise SystemExit(1)\n')
        result = validator.validate_problem("synthetic_grid")
        self.assertNotIn("PRIVATE_SYNTHETIC_CANARY", str(result))
        self.assertTrue(any("rejected test" in e for e in result["failures"]))
        with patch.object(validator.subprocess, "run", side_effect=subprocess.TimeoutExpired("synthetic", 2)):
            result = validator.validate_problem("synthetic_grid")
        self.assertTrue(any("timed out" in e for e in result["failures"]))

    def test_missing_validator_pdf_and_wrong_limits_fail_strict(self):
        self.package()
        (self.pdir / "input_validator.py").unlink()
        (self.pdir / "statement.pdf").unlink()
        md = self.pdir / "statement.md"
        md.write_text(md.read_text().replace("เวลา 1 วินาที", "เวลา 2 วินาที"))
        errors = validator.validate_problem("synthetic_grid", strict=True)["failures"]
        for expected in ("input_validator.py is required", "statement.pdf is missing", "Limits resource line"):
            self.assertTrue(any(expected in e for e in errors), expected)

    def test_wrong_heading_hints_and_unfinished_placeholders_fail(self):
        self.package()
        cfg = json.loads((self.pdir / "config.json").read_text())
        md = (self.pdir / "statement.md").read_text()
        for wrong in (md.replace("# ตารางสังเคราะห์", "# ผิด"), md + "## Hints\n", md + "TODO: finish\n"):
            self.assertTrue(validator.statement_contract_errors(cfg, wrong))

    def test_strict_empty_checkout_fails_instead_of_skipping(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(validator.main(["--strict"]), 1)

    def test_pdf_mismatch_is_blocked_before_tectonic(self):
        self.package()
        md = self.pdir / "statement.md"
        md.write_text(md.read_text().replace("0 0", "00"))
        with patch.object(renderer.subprocess, "run") as compile_pdf:
            with self.assertRaisesRegex(SystemExit, "PDF preflight failed"):
                renderer.main("synthetic_grid")
            compile_pdf.assert_not_called()

    def test_import_mismatch_is_blocked_before_remote_access(self):
        self.package()
        md = self.pdir / "statement.md"
        md.write_text(md.read_text().replace("0 0", "00"))
        with patch.object(importer, "_client") as client, redirect_stderr(io.StringIO()):
            self.assertEqual(importer.main(["--problem", "synthetic_grid", "--dry-run"]), 1)
            client.assert_not_called()

    def test_strict_import_rejects_missing_validator_before_remote_access(self):
        self.package()
        (self.pdir / "input_validator.py").unlink()
        with patch.object(importer, "_client") as client, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(importer.main(["--problem", "synthetic_grid", "--strict", "--dry-run"]), 1)
            client.assert_not_called()

    def test_changed_statement_pdf_or_layout_invalidates_build_record(self):
        self.package()
        cfg = json.loads((self.pdir / "config.json").read_text())
        md = (self.pdir / "statement.md").read_text()
        self.assertEqual(check_build(self.pdir, cfg, md, required=True), [])
        self.assertTrue(check_build(self.pdir, cfg, md + "changed story", required=True))
        self.assertTrue(check_build(self.pdir, dict(cfg, time_limit=2), md, required=True))
        with patch("tools.statement_build.build_record", return_value={"layout_sha256": "changed"}):
            self.assertTrue(check_build(self.pdir, cfg, md, required=True))
        logo = self.root / "synthetic-logo.png"
        logo.write_bytes(b"synthetic changed logo")
        with patch("tools.statement_build.BRAND_ASSETS", (logo,)):
            self.assertTrue(check_build(self.pdir, cfg, md, required=True))
        (self.pdir / "statement.pdf").write_bytes(b"%PDF-modified")
        self.assertTrue(check_build(self.pdir, cfg, md, required=True))

    def test_preview_build_does_not_replace_installed_pdf_or_build_record(self):
        self.package()
        pdf = (self.pdir / "statement.pdf").read_bytes()
        record = (self.pdir / "statement.build.json").read_bytes()
        preview = self.root / "preview"
        def tectonic(command, **kwargs):
            (Path(command[2]) / "statement.pdf").write_bytes(b"%PDF-synthetic-preview")
            return subprocess.CompletedProcess(command, 0, "", "")
        with patch.object(renderer.subprocess, "run", side_effect=tectonic):
            renderer.main("synthetic_grid", output_dir=preview)
        self.assertTrue((preview / "synthetic_grid.build.json").is_file())
        self.assertEqual((self.pdir / "statement.pdf").read_bytes(), pdf)
        self.assertEqual((self.pdir / "statement.build.json").read_bytes(), record)


if __name__ == "__main__":
    unittest.main()
