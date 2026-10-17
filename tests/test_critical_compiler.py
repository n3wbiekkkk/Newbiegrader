"""Critical compiler regressions, independent of the private problem set."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

import grader
from judge_runner import BoundedResult
from critical_helpers import synthetic_problem, test_server


class CriticalCompilerPlumbing(unittest.TestCase):
    def test_critical_workspace_does_not_follow_source_or_directory_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "synthetic-private-file"
            target.write_text("synthetic canary only\n")
            os.chmod(target, 0o600)
            before = target.stat()
            workdir = base / "job"
            workdir.mkdir()
            src = workdir / "solution.c"
            src.symlink_to(target)
            alias = base / "alias"
            alias.symlink_to(workdir, target_is_directory=True)
            with patch.object(grader.sys, "platform", "linux"), \
                    patch.object(grader.os, "geteuid", return_value=0), \
                    patch.object(grader, "sandbox_identity", return_value=(65534, 65534)):
                for directory, source in ((workdir, src), (alias, None)):
                    with self.subTest(directory=directory.name), \
                            self.assertRaises(grader.SandboxUnavailable):
                        grader.prepare_workspace(directory, source)
            after = target.stat()
            self.assertEqual((before.st_uid, before.st_gid, before.st_mode),
                             (after.st_uid, after.st_gid, after.st_mode))

    def test_critical_source_is_private_before_directory_ownership_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            src = workdir / "solution.c"
            src.write_text("int main(void){return 0;}\n")
            changed = []

            def record(fd, uid, gid):
                changed.append(os.fstat(fd).st_ino)

            with patch.object(grader.sys, "platform", "linux"), \
                    patch.object(grader.os, "geteuid", return_value=0), \
                    patch.object(grader, "sandbox_identity", return_value=(65534, 65534)), \
                    patch.object(grader.os, "fchown", side_effect=record):
                grader.prepare_workspace(workdir, src)
            self.assertEqual(changed, [src.stat().st_ino, workdir.stat().st_ino])
            self.assertEqual(src.stat().st_mode & 0o777, 0o600)
            self.assertEqual(workdir.stat().st_mode & 0o777, 0o700)

    def test_critical_standard_c_and_cpp_stl_compile_and_judge(self):
        self.assertTrue(shutil.which("gcc") and shutil.which("g++"),
                        "[CRITICAL-FAIL] gcc and g++ must be installed")
        server = test_server()
        sources = {
            ".c": '#include <stdio.h>\nint main(void){puts("hello");return 0;}\n',
            ".cpp": '#include <iostream>\n#include <vector>\n#include <algorithm>\n'
                    'int main(){std::vector<int> v{2,1};std::sort(v.begin(),v.end());'
                    'if(v[0]==1)std::cout<<"hello\\n";}\n',
        }
        with patch.dict(os.environ, {"GRADER_REQUIRE_NETNS": "0"}):
            for ext, source in sources.items():
                with self.subTest(language=ext):
                    result = server.run_submission(synthetic_problem(), ext, source)
                    self.assertTrue(result.get("accepted"), result)
                    self.assertEqual(result["passed"], 2)

    def test_critical_compile_wraps_linux_root_when_memory_limit_is_off(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(grader.sys, "platform", "linux"), \
                patch.object(grader.os, "geteuid", return_value=0), \
                patch.object(grader, "prepare_workspace"), \
                patch.object(grader, "COMPILE_MEMORY_MB", 0), \
                patch("judge_runner.run_bounded", return_value=BoundedResult("", "", 0, "")) as run:
            grader._compile(["synthetic-compiler"], Path(tmp))
        self.assertIn("--compile-sandbox", run.call_args.args[0])

    def test_critical_each_privilege_drop_failure_exits_before_exec(self):
        # Run mocked failures in disposable processes: never change this test
        # runner's UID or hard resource limits, including on non-root hosts.
        for failing in ("setgroups", "setgid", "setuid"):
            with self.subTest(operation=failing):
                source = (
                    "from unittest.mock import patch\nimport grader\n"
                    "with patch.object(grader.sys, 'platform', 'linux'), "
                    "patch.object(grader.os, 'geteuid', return_value=0), "
                    "patch.object(grader, '_set_no_new_privileges'), "
                    "patch.object(grader, 'sandbox_identity', return_value=(65534,65534)), "
                    "patch.object(grader.os, 'setgroups'), "
                    "patch.object(grader.os, 'setgid'), "
                    "patch.object(grader.os, 'setuid'):\n"
                    f" getattr(grader.os, {failing!r}).side_effect = OSError('synthetic failure')\n"
                    " grader.build_limits(0, 10, network=False)()\n"
                    " print('UNTRUSTED-COMMAND-RAN')\n")
                result = subprocess.run([sys.executable, "-c", source],
                                        capture_output=True, text=True, timeout=15,
                                        env=grader.judge_env(), cwd=grader.ROOT)
                self.assertEqual(result.returncode, grader.PRIVILEGE_REFUSED_RC)
                self.assertIn(grader.PRIVILEGE_REFUSED_MARKER, result.stderr)
                self.assertNotIn("UNTRUSTED-COMMAND-RAN", result.stdout)

    def test_critical_hardening_failure_exits_before_privilege_drop_or_exec(self):
        source = (
            "from unittest.mock import patch\nimport grader\n"
            "with patch.object(grader.sys, 'platform', 'linux'), "
            "patch.object(grader.os, 'geteuid', return_value=0), "
            "patch.object(grader, '_set_no_new_privileges', side_effect=OSError('synthetic failure')), "
            "patch.object(grader.os, 'setuid', side_effect=lambda uid: print('PRIVILEGE-DROP-RAN',flush=True)):\n"
            " grader.build_limits(0, 10, network=False)()\n"
            " print('UNTRUSTED-COMMAND-RAN')\n")
        result = subprocess.run([sys.executable, "-c", source],
                                capture_output=True, text=True, timeout=15,
                                env=grader.judge_env(), cwd=grader.ROOT)
        self.assertEqual(result.returncode, grader.PRIVILEGE_REFUSED_RC)
        self.assertIn(grader.PRIVILEGE_REFUSED_MARKER, result.stderr)
        self.assertNotIn("PRIVILEGE-DROP-RAN", result.stdout)
        self.assertNotIn("UNTRUSTED-COMMAND-RAN", result.stdout)

    def test_critical_drop_refusal_is_job_error_not_ce_or_re(self):
        refused = BoundedResult("", grader.PRIVILEGE_REFUSED_MARKER,
                                grader.PRIVILEGE_REFUSED_RC, "")
        with tempfile.TemporaryDirectory() as tmp, \
                patch("judge_runner.run_bounded", return_value=refused):
            with self.assertRaises(grader.SandboxUnavailable):
                grader._compile(["synthetic-compiler"], Path(tmp))
            result = grader.run_one([sys.executable, "-c", "pass"], "", 3, 128)
        self.assertEqual(result["reason"], "sandbox-unavailable")
        server = test_server()
        with patch.object(grader, "prepare_workspace", side_effect=grader.SandboxUnavailable("synthetic")):
            self.assertEqual(server.run_submission(synthetic_problem(), ".c", "int main(void){return 0;}"),
                             {"error": "execution environment unavailable"})
            self.assertEqual(server._run_playground(None, ".c", "int main(void){return 0;}", "", 3, 128),
                             {"error": "execution environment unavailable"})


class CriticalCompilerRoot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not sys.platform.startswith("linux") or os.geteuid() != 0:
            reason = "[CRITICAL-SKIP] compiler isolation requires Linux/root; actual UID drop is UNVERIFIED"
            print(reason, file=sys.stderr, flush=True)
            raise unittest.SkipTest(reason)
        if not shutil.which("gcc") or not shutil.which("g++"):
            raise AssertionError("[CRITICAL-FAIL] gcc and g++ must be installed")

    def private_canary(self, tmp):
        os.chmod(tmp, 0o755)
        path = Path(tmp) / "root-only.h"
        marker = "ROOT_ONLY_CANARY_" + uuid.uuid4().hex
        path.write_text(marker + "\n")
        os.chmod(path, 0o600)
        self.assertEqual(path.stat().st_uid, 0)
        return path, marker

    def test_critical_no_new_privileges_reaches_compiler_runtime_and_children(self):
        child = ('from pathlib import Path;import json,os;'
                 's=Path("/proc/self/status").read_text();'
                 'print(json.dumps([os.getuid(),os.geteuid(),'
                 'next(v.split()[1] for v in s.splitlines() if v.startswith("NoNewPrivs:"))]))')
        driver = (f"import subprocess,sys\n{child}\n"
                  f"subprocess.run([sys.executable,'-c',{child!r}],check=True)\n")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"GRADER_REQUIRE_NETNS": "0"}):
            compiled = grader._compile([sys.executable, "-c", driver], Path(tmp))
            runtime = grader.run_one([sys.executable, "-c", driver], "", 5, 128, "python")
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        self.assertEqual(runtime["returncode"], 0, runtime["stderr"])
        expected = [grader.sandbox_identity()[0]] * 2 + ["1"]
        for output in (compiled.stdout, runtime["stdout"]):
            identities = [json.loads(line) for line in output.splitlines()]
            self.assertEqual(identities, [expected, expected])

    def test_critical_runtime_cannot_gain_root_from_synthetic_setuid_binary(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"GRADER_REQUIRE_NETNS": "0"}):
            base = Path(tmp)
            os.chmod(base, 0o755)
            source = base / "trusted-setuid-fixture.c"
            binary = base / "trusted-setuid-fixture"
            source.write_text('#include <stdio.h>\n#include <unistd.h>\n'
                              'int main(void){printf("%d:%d\\n",getuid(),geteuid());return 0;}\n')
            # Trusted fixture setup, never a user-supplied program.
            subprocess.run(["gcc", str(source), "-o", str(binary)], check=True,
                           capture_output=True, timeout=30)
            os.chmod(binary, 0o4755)
            self.assertEqual(binary.stat().st_uid, 0)
            self.assertTrue(binary.stat().st_mode & 0o4000)
            # Exec from the synthetic program so run_one does not normalize the
            # fixture executable's mode while preparing a submission workspace.
            driver = f"import os;os.execv({str(binary)!r}, [{str(binary)!r}])"
            result = grader.run_one([sys.executable, "-c", driver], "", 5, 128, "python")
            self.assertTrue(binary.stat().st_mode & 0o4000)
        uid = grader.sandbox_identity()[0]
        self.assertEqual(result["returncode"], 0, result["stderr"])
        self.assertEqual(result["stdout"].strip(), f"{uid}:{uid}")

    def test_critical_c_and_cpp_cannot_include_root_private_canary(self):
        server = test_server()
        with tempfile.TemporaryDirectory() as tmp:
            private, marker = self.private_canary(tmp)
            for ext in (".c", ".cpp"):
                with self.subTest(language=ext):
                    result = server.run_submission(synthetic_problem(), ext,
                        f'#include "{private}"\nint main(void) {{return 0;}}\n')
                    self.assertEqual(result["verdict"], "CE")
                    self.assertNotIn(marker, json.dumps(result))
                    self.assertIn("Permission denied", result["compile_error"])

    def test_critical_assembler_cannot_embed_root_private_canary(self):
        with tempfile.TemporaryDirectory() as tmp:
            private, marker = self.private_canary(tmp)
            workdir = Path(tmp) / "compile"
            workdir.mkdir()
            src = workdir / "solution.c"
            src.write_text(f'__asm__(".incbin \\\"{private}\\\"\\n");\nint main(void){{return 0;}}\n')
            with self.assertRaises(grader.CompileError) as raised:
                grader.prepare_command(src, workdir)
            self.assertTrue(private.is_file())
            self.assertNotIn(marker, str(raised.exception))
            # GNU as on arm64 reports an unreadable .incbin as "file not found";
            # x86 builds report EACCES. Both must deny this existing root file.
            self.assertRegex(str(raised.exception), r"(?i)(permission denied|file not found)")
            self.assertFalse((workdir / "sol").exists())

    def test_critical_compiler_and_descendants_have_no_root_identity(self):
        child = "import os,json;print(json.dumps([os.getuid(),os.getgid(),os.getgroups()]))"
        driver = ("import os,json,subprocess,sys\n"
                  "print(json.dumps([os.getuid(),os.getgid(),os.getgroups()]),flush=True)\n"
                  f"subprocess.run([sys.executable,'-c',{child!r}],check=True)\n")
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GRADER_REQUIRE_NETNS": "1"}):
            result = grader._compile([sys.executable, "-c", driver], Path(tmp))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(tmp).stat().st_mode & 0o777, 0o700)
            self.assertEqual(Path(tmp).stat().st_uid, grader.sandbox_identity()[0])
        identities = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(identities), 2)
        for identity in identities:
            self.assertEqual(identity, [*grader.sandbox_identity(), []])

if __name__ == "__main__":
    unittest.main()
