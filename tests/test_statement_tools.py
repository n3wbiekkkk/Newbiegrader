"""Statement layout and safe publishing, with synthetic public data only."""
import copy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import grader
from fake_supabase import FakeSupabase
from tools import import_problems_supabase as importer
from tools import make_statement_tex as renderer
from tools.validate_problem import parse_samples


class StatementLayout(unittest.TestCase):
    def test_website_brand_is_centered_above_the_title_without_a_trailing_dot(self):
        tex = renderer.build("synthetic", "เรื่อง (Example)", 1, 256, "เนื้อเรื่อง")
        header = renderer.brand_header()
        self.assertEqual(tex.count(header), 1)
        self.assertIn("\\centering", header)
        self.assertIn("logo-icon.png", header)
        self.assertIn("\\wordmarkfont", header)
        self.assertIn("newbie{\\mdseries\\color{brandmuted}grader}", header)
        self.assertNotIn("grader.", header)
        self.assertIn("\\hrule height 0.4pt", header)
        self.assertLess(tex.index(header), tex.index("\\fontsize{26}{31}"))

    def test_top_margin_and_brand_spacing_are_compact(self):
        self.assertIn("\\geometry{top=1.2cm,bottom=2.2cm,left=2.2cm,right=2.2cm}",
                      renderer.PREAMBLE)
        self.assertIn("\\vspace{6pt}\\hrule height 0.4pt\\vspace{10pt}",
                      renderer.brand_header())

    def test_compact_bilingual_header_and_right_page_number(self):
        # GitHub checks out this repo under a directory named Newbiegrader.
        # Its font path is legitimate source text, not a rendered footer label.
        preamble = renderer.PREAMBLE.replace(str(renderer.FONTDIR),
                                             "/synthetic/Newbiegrader/tools/fonts")
        with patch.object(renderer, "PREAMBLE", preamble):
            tex = renderer.build("synthetic", "เรื่องสังเคราะห์ (Synthetic)", 10.0, 128,
                                 "# Ignored title\n\nเนื้อเรื่อง\n")
        self.assertIn("\\fontsize{26}{31}", tex)
        self.assertIn("\\fontsize{16}{22}", tex)
        self.assertIn("10 seconds, 128 megabytes", tex)
        self.assertIn("\\fancyfoot[R]", tex)
        self.assertNotIn("Ignored title", tex)
        footer = next(line for line in tex.splitlines() if line.startswith("\\fancyfoot[R]"))
        self.assertNotIn("Newbiegrader", footer)
        self.assertIn("\\thepage", footer)
        self.assertIn("Path=/synthetic/Newbiegrader/tools/fonts/", tex)

    def test_limits_line_handles_integer_and_fractional_seconds(self):
        for seconds, expected in ((1, "1 second,"), (10, "10 seconds,"),
                                  (0.5, "0.5 seconds,")):
            with self.subTest(seconds=seconds):
                self.assertIn(expected, renderer._limits_line(seconds, 256))

    def test_samples_share_a_table_with_repeated_headers_and_preserved_lines(self):
        samples = [("1\n\n2", "3"), ("4", "5\n6"), ("7", "8")]
        tex = renderer.render_samples_table(samples)
        self.assertEqual(tex.count("\\begin{longtable}"), 1)
        self.assertEqual(tex.count("ตัวอย่างข้อมูลนำเข้า"), 2)
        self.assertIn("\\endfirsthead", tex)
        self.assertIn("\\endhead", tex)
        self.assertIn("1\\newline\n~\\newline\n2", tex)
        self.assertNotIn("rowcolor", tex)

    def test_wide_grids_use_readable_font_inside_column_width(self):
        self.assertEqual(renderer.sample_font_size([("1", "2")]), 12)
        size = renderer.sample_font_size([("1", "-" * 50)])
        self.assertGreaterEqual(size, 7)
        self.assertLessEqual(50 * size * 0.5, 222)

    def test_spaced_grid_input_keeps_compact_grid_output(self):
        # Public Forest Fire Spread example: cells are input as integers,
        # while output rows remain compact strings.
        inp = "3 3\n0 1 0\n1 2 1\n0 1 0\n1"
        out = "020\n202\n020"
        md = f"## ตัวอย่าง\n```\ninput:\n{inp}\n\noutput:\n{out}\n```\n"
        self.assertEqual(parse_samples(md), [(inp, out)])
        tex = renderer.build("forest_fire_spread", "ไฟป่าลาม (Forest Fire Spread)",
                             1, 256, md)
        self.assertIn("0 1 0\\newline\n1 2 1\\newline\n0 1 0", tex)
        self.assertIn("020\\newline\n202\\newline\n020", tex)

    def test_headings_reserve_space_and_nested_rules_keep_indentation(self):
        tex = renderer.build("synthetic", "เรื่อง", 1, 256,
                             "## Input\n- outer\n  - inner\n1. ordered\n\n## Output\nanswer")
        self.assertIn("\\Needspace{80pt}", tex)
        self.assertIn("\\leftskip}{12pt}", tex)
        self.assertIn("\\leftskip}{24pt}", tex)
        self.assertIn("\\textbullet", tex)
        self.assertIn("ordered", tex)

    def test_duplicate_resource_limits_are_removed_but_other_constraints_remain(self):
        base = "## Limits\n- เวลา 1 วินาที, หน่วยความจำ 256 MB\n"
        tex = renderer.build("synthetic", "เรื่อง", 1, 256, base)
        self.assertNotIn("ข้อจำกัด", tex)
        tex = renderer.build("synthetic", "เรื่อง", 1, 256, base + "- ค่าสูงสุด 100\n")
        self.assertIn("ข้อจำกัด", tex)
        self.assertIn("ค่าสูงสุด", tex)
        self.assertNotIn("การให้คะแนน", tex)

    def test_sample_tail_uses_measured_height_and_retains_multipage_fallback(self):
        tex = renderer.build("synthetic", "เรื่อง", 1, 256,
                             "## ตัวอย่าง\n```\ninput:\n1\noutput:\n2\n```\n"
                             "## คำอธิบายตัวอย่าง\nคำอธิบาย\n")
        self.assertIn("\\setbox\\statementtailbox=\\vbox", tex)
        self.assertIn("\\begin{tabular}", tex)
        self.assertIn("\\begin{longtable}", tex)
        self.assertIn("\\advance\\statementtailheight by2\\baselineskip", tex)


class StatementPublishing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.pdir = root / "synthetic"
        self.pdir.mkdir()
        self.cfg = {"no": 7, "title": "เรื่อง (Synthetic)", "time_limit": 1.0,
                    "memory_limit": 128}
        (self.pdir / "config.json").write_text(json.dumps(self.cfg))
        (self.pdir / "statement.md").write_text("# เรื่อง\n\nSynthetic new story\n")
        self.pdf = b"%PDF-1.4\nsynthetic statement\n"
        (self.pdir / "statement.pdf").write_bytes(self.pdf)
        self.fake = FakeSupabase()
        self.row = dict(self.cfg, slug="synthetic", statement_md="old story",
                        statement_pdf_path="synthetic/statement.pdf", updated_at="v1",
                        hidden=True, is_published=False, tests_hash="untouched-test-hash",
                        samples_data=[{"name": "01", "input": "synthetic public sample"}],
                        hidden_tests=[{"name": "1001", "sha256": "synthetic-manifest"}])
        self.fake.table("problems").insert(self.row).execute()
        self.fake.storage.from_("judge-assets").upload(self.row["statement_pdf_path"], b"%PDF-old")
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(grader, "PROBLEMS_DIR", root))
        self.upload = self.stack.enter_context(
            patch.object(importer, "_upload_many", side_effect=self.upload_many))

    def upload_many(self, client, bucket, jobs, dry):
        self.assertFalse(dry)
        self.assertEqual(len(jobs), 1)
        path, content, kind = jobs[0]
        self.assertIn("/statements/", path)
        self.assertEqual(kind, "application/pdf")
        # Prose remains old until the upload has succeeded.
        self.assertEqual(self.fake.tables["problems"][0]["statement_md"], "old story")
        self.fake.storage.from_(bucket).upload(path, content)

    def publish(self, dry=False):
        return importer.import_statement_one(self.fake, "judge-assets", "synthetic", dry)

    def test_updates_only_prose_pdf_and_timestamp_and_is_idempotent(self):
        old = copy.deepcopy(self.fake.tables["problems"][0])
        self.assertEqual(self.publish()[0], "updated")
        row = self.fake.tables["problems"][0]
        for key in old.keys() - {"statement_md", "statement_pdf_path", "updated_at"}:
            self.assertEqual(row[key], old[key], key)
        self.assertIn(hashlib.sha256(self.pdf).hexdigest(), row["statement_pdf_path"])
        self.assertEqual(self.fake.storage.from_("judge-assets").download(row["statement_pdf_path"]), self.pdf)
        self.assertEqual(self.fake.storage.from_("judge-assets").download(old["statement_pdf_path"]), b"%PDF-old")
        self.assertEqual(self.publish()[0], "skipped")
        self.assertEqual(self.upload.call_count, 1)

    def test_dry_run_writes_nothing(self):
        old = copy.deepcopy(self.fake.tables["problems"])
        self.assertEqual(self.publish(dry=True)[0], "updated")
        self.assertEqual(self.fake.tables["problems"], old)
        self.upload.assert_not_called()

    def test_upload_failure_keeps_old_row_and_old_pdf(self):
        old = copy.deepcopy(self.fake.tables["problems"])
        self.upload.side_effect = RuntimeError("synthetic outage")
        self.assertEqual(self.publish()[0], "failed")
        self.assertEqual(self.fake.tables["problems"], old)

    def test_concurrent_edit_is_not_overwritten(self):
        def race(client, bucket, jobs, dry):
            self.fake.tables["problems"][0].update(updated_at="v2", statement_md="concurrent edit")
        self.upload.side_effect = race
        self.assertEqual(self.publish()[0], "failed")
        self.assertEqual(self.fake.tables["problems"][0]["statement_md"], "concurrent edit")

    def test_missing_problem_invalid_pdf_and_metadata_mismatch_fail_closed(self):
        for mode in ("missing", "invalid", "mismatch"):
            with self.subTest(mode=mode):
                self.fake.tables["problems"] = [copy.deepcopy(self.row)]
                (self.pdir / "statement.pdf").write_bytes(self.pdf)
                if mode == "missing":
                    self.fake.tables["problems"] = []
                elif mode == "invalid":
                    (self.pdir / "statement.pdf").write_bytes(b"not a PDF")
                else:
                    self.fake.tables["problems"][0]["no"] = 99
                self.assertEqual(self.publish()[0], "failed")
                self.upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
