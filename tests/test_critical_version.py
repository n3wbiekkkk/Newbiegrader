# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Deployment verification using public code hashes, without real data."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import Request, Response
from critical_helpers import test_server

server = test_server()


class CriticalVersion(unittest.TestCase):
    def test_critical_fingerprint_changes_with_code_not_secrets_or_test_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in server.BUILD_SOURCE_FILES:
                (root / name).write_text("# synthetic source: " + name + "\n")
            original = server._source_fingerprint(root)
            (root / ".env").write_text("SESSION_SECRET=synthetic-do-not-hash\n")
            (root / "hidden-test.in").write_text("synthetic-hidden-input\n")
            with patch.dict("os.environ", {"SESSION_SECRET": "synthetic-runtime-secret"}):
                self.assertEqual(server._source_fingerprint(root), original)
            (root / "grader.py").write_text("# synthetic changed engine\n")
            self.assertNotEqual(server._source_fingerprint(root), original)

    def test_critical_version_returns_the_boot_source_fingerprint(self):
        request = Request({"type": "http", "session": {}})
        with patch.object(server, "PROBLEMS", {}), \
                patch.object(server, "_ensure_problems_fresh"), \
                patch.object(server, "_hidden_pids", return_value=set()), \
                patch.object(server, "_source_fingerprint", side_effect=AssertionError("must use boot hash")):
            body = server.version(request, Response())
        digest = hashlib.sha256()
        for name in server.BUILD_SOURCE_FILES:
            digest.update(name.encode("ascii") + b"\0")
            digest.update((server.ROOT / name).read_bytes())
            digest.update(b"\0")
        self.assertEqual(body["build_sha256"], digest.hexdigest())
        self.assertRegex(body["build_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
