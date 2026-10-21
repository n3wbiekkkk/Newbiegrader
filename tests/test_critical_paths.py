# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Runtime path regressions. Root-owned files contain synthetic canaries only."""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

import grader
from critical_helpers import synthetic_problem, test_server


@unittest.skipUnless(sys.platform.startswith("linux") and os.geteuid() == 0,
                     "[CRITICAL-SKIP] runtime path checks require Linux/root")
class RuntimePaths(unittest.TestCase):
    def test_critical_python_source_alias_cannot_chmod_its_resolved_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            os.chmod(base, 0o755)
            private = base / "synthetic-private-directory"
            private.mkdir(mode=0o700)
            target = private / "synthetic.py"
            target.write_text("print('synthetic')\n")
            workspace = base / "workspace"
            workspace.mkdir()
            grader.prepare_workspace(workspace)
            source = workspace / "solution.py"
            source.symlink_to(target)
            grader.run_one([sys.executable, str(source)], "", 1, 64, "python")
            self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o700)

    def test_critical_replaced_binary_cannot_chmod_a_root_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            os.chmod(base, 0o755)
            target = base / "synthetic-root-canary"
            target.write_text("SYNTHETIC_PRIVATE_CANARY\n")
            os.chmod(target, 0o600)
            source = ('#define _POSIX_C_SOURCE 200809L\n#include <stdio.h>\n'
                      '#include <unistd.h>\nint main(int argc,char**argv){'
                      'puts("hello");unlink(argv[0]);symlink('
                      + json.dumps(str(target)) + ',argv[0]);return 0;}\n')
            result = test_server().run_submission(synthetic_problem(), ".c", source)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(result.get("error"), "execution environment unavailable")

    def test_critical_replaced_workspace_cannot_chmod_a_root_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "synthetic-private-directory"
            target.mkdir(mode=0o700)
            alias = base / "submission-workspace"
            alias.symlink_to(target, target_is_directory=True)
            result = grader.run_one([str(alias / "sol")], "", 1, 64, "c")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
            self.assertEqual(result["reason"], "sandbox-unavailable")
