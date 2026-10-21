"""Bounded synthetic checks: failed limits must never execute user code."""
import os
import subprocess
import sys
import unittest

import grader


class CriticalResourceSetup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not sys.platform.startswith("linux") or os.geteuid() != 0:
            reason = "[CRITICAL-SKIP] resource setup checks require Linux/root"
            print(reason, file=sys.stderr, flush=True)
            raise unittest.SkipTest(reason)

    def test_critical_each_limit_failure_refuses_before_user_code(self):
        for name in ("RLIMIT_AS", "RLIMIT_DATA", "RLIMIT_CPU", "RLIMIT_NPROC",
                     "RLIMIT_FSIZE", "RLIMIT_CORE", "RLIMIT_NOFILE"):
            for error in ("OSError", "ValueError"):
                with self.subTest(limit=name, error=error):
                    code = (
                        "import resource,grader\nfrom unittest.mock import patch\n"
                        "original=resource.setrlimit\n"
                        "def apply(which,values):\n"
                        f" if which==resource.{name}: raise {error}('synthetic refusal')\n"
                        " return original(which,values)\n"
                        "with patch.object(resource,'setrlimit',side_effect=apply):\n"
                        " grader.build_limits(128,3,network=False)()\n"
                        " print('SYNTHETIC_UNTRUSTED_RAN')\n")
                    result = subprocess.run([sys.executable, "-c", code],
                        env=grader.judge_env(), cwd=grader.ROOT,
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, grader.PRIVILEGE_REFUSED_RC)
                    self.assertIn(grader.PRIVILEGE_REFUSED_MARKER, result.stderr)
                    self.assertNotIn("SYNTHETIC_UNTRUSTED_RAN", result.stdout)

    def test_critical_limits_are_installed_before_dropping_identity(self):
        code = (
            "import resource,grader\nfrom unittest.mock import patch\n"
            "seen=[]\n"
            "def limit(which,values):seen.append(which)\n"
            "def drop():\n"
            " assert set(seen)=={resource.RLIMIT_AS,resource.RLIMIT_DATA,"
            "resource.RLIMIT_CPU,resource.RLIMIT_NPROC,resource.RLIMIT_FSIZE,"
            "resource.RLIMIT_CORE,resource.RLIMIT_NOFILE}\n"
            " print('SYNTHETIC_LIMIT_ORDER_OK',flush=True)\n"
            " raise OSError('synthetic stop before credential change')\n"
            "with patch.object(resource,'setrlimit',side_effect=limit), "
            "patch.object(grader,'_set_no_new_privileges',side_effect=drop):\n"
            " grader.build_limits(128,3,network=False)()\n")
        result = subprocess.run([sys.executable, "-c", code],
            env=grader.judge_env(), cwd=grader.ROOT,
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, grader.PRIVILEGE_REFUSED_RC)
        self.assertIn("SYNTHETIC_LIMIT_ORDER_OK", result.stdout)
