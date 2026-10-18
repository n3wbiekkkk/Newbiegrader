#!/usr/bin/env python3
"""Bounded synthetic S04 integration tests in a delegated systemd unit only.

No production problem, database, user workload, real credential or network
connection is used. Any unsupported control is a test failure, never a skip.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import job_resources
import judge_runner


def payload(source, ext=".py", limit=3):
    return {"ext": ext, "source": source, "problem": None,
            "stdin_data": "", "time_limit": limit, "memory_mb": 128,
            "memory_cap_mb": 128, "judge_jobs": 1, "reveal": "none"}


def playground(source, ext=".py", limit=3):
    result = asyncio.run(judge_runner.run_isolated("playground", payload(source, ext, limit), 20))
    if "error" in result:
        raise AssertionError(f"synthetic runner refused: {result['error']}")
    return result


def counters(path):
    return {line.split()[0]: int(line.split()[1]) for line in path.read_text().splitlines()}


def controlled(source, **settings):
    """Trusted bounded kernel probe, not a user submission; secret-free env."""
    with patch.dict(os.environ, settings), job_resources.job_scope() as boundary:
        result = judge_runner.run_bounded(
            [sys.executable, "-c", source], "", 5, output_limit=16384,
            env={"PATH": "/usr/bin:/bin", "TMPDIR": str(boundary.workspace)},
            containment=boundary)
        stats = {name: counters(boundary.group / name)
                 for name in ("memory.events", "pids.events", "cpu.stat")}
        return result, stats


class KernelIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not job_resources.required():
            raise RuntimeError("real cgroup enforcement must be required for these tests")
        job_resources.initialize()

    def tearDown(self):
        root, workspace = job_resources._ready
        self.assertFalse(list(root.glob("job-*")), "leaked job cgroups")
        self.assertFalse(list(workspace.glob("job-*")), "leaked job workspaces")

    def test_python_runs_without_root_groups_or_capabilities(self):
        result = playground('import os,json\nprint(json.dumps([os.getuid(),os.getgid(),os.getgroups()]))')
        self.assertEqual(result["verdict"], "OK", result)
        uid, gid, groups = json.loads(result["stdout"])
        self.assertGreaterEqual(uid, 1000000)
        self.assertEqual(gid, uid)
        self.assertEqual(groups, [])
        caps = playground("from pathlib import Path\nprint('\\n'.join(x for x in Path('/proc/self/status').read_text().splitlines() if x.startswith(('CapEff:','CapAmb:'))))")
        self.assertEqual(caps["verdict"], "OK", caps)
        for line in caps["stdout"].splitlines():
            self.assertEqual(int(line.split()[1], 16), 0)

    def test_cpp_standard_headers_and_stl(self):
        result = playground('#include <iostream>\n#include <vector>\n#include <numeric>\nint main(){std::vector<int> v{1,2,3};std::cout<<std::accumulate(v.begin(),v.end(),0);}', '.cpp')
        self.assertEqual(result["verdict"], "OK", result)
        self.assertEqual(result["stdout"].strip(), "6")

    def test_compiler_and_program_cannot_read_synthetic_host_files(self):
        with tempfile.TemporaryDirectory(dir="/var/lib/newbiegrader") as tmp:
            Path(tmp).chmod(0o755)
            header = Path(tmp) / "root-only.h"
            header.write_text('#define SYNTHETIC_CANARY "CANARY_NOT_A_SECRET"\n')
            header.chmod(0o600)
            result = playground(f'#include "{header}"\nint main(){{}}', '.cpp')
            self.assertEqual(result["verdict"], "CE", result)
            public = Path(tmp) / "world-readable.txt"
            public.write_text("CANARY_NOT_A_SECRET")
            public.chmod(0o644)
            result = playground(f"from pathlib import Path\ntry: Path({str(public)!r}).read_text();print('ALLOWED')\nexcept PermissionError:print('DENIED')")
            self.assertEqual(result["verdict"], "OK", result)
            self.assertEqual(result["stdout"].strip(), "DENIED")

    def test_network_creation_and_cgroup_escape_are_denied(self):
        root = str(job_resources._ready[0] / "manager" / "cgroup.procs")
        source = ("import socket,os\n"
                  "try: socket.socket();print('NETWORK_ALLOWED')\n"
                  "except PermissionError: print('NETWORK_DENIED')\n"
                  f"try: fd=os.open({root!r},os.O_WRONLY);os.close(fd);print('CGROUP_ALLOWED')\n"
                  "except PermissionError: print('CGROUP_DENIED')\n")
        result = playground(source)
        self.assertEqual(result["verdict"], "OK", result)
        self.assertEqual(result["stdout"].split(), ["NETWORK_DENIED", "CGROUP_DENIED"])

    def test_descendants_are_killed_after_success_and_timeout(self):
        source = ("import subprocess,sys,json\n"
                  "p=[subprocess.Popen([sys.executable,'-c','import time;time.sleep(3)'],start_new_session=True) for _ in range(2)]\n"
                  "print(json.dumps([x.pid for x in p]))\n")
        result = playground(source)
        self.assertEqual(result["verdict"], "OK", result)
        for pid in json.loads(result["stdout"]):
            self.assertFalse(Path(f"/proc/{pid}").exists())
        result = playground("import time\ntime.sleep(3)", limit=.3)
        self.assertEqual(result["verdict"], "TLE", result)

    def test_stdout_limit_is_preserved(self):
        # API display truncation (64 KiB) is distinct from the engine's
        # execution ceiling (32 MiB). Write bounded chunks beyond that ceiling.
        result = playground("import os\nfor _ in range(1088): os.write(1,b'x'*32768)", limit=5)
        self.assertEqual(result["verdict"], "OLE")
        self.assertTrue(result["truncated"])

    def test_workspace_byte_and_inode_limits(self):
        source = ("import errno\ntry:\n"
                  " for n in range(3):\n"
                  "  with open(str(n),'wb') as f:\n"
                  "   for _ in range(1536): f.write(b'x'*32768)\n"
                  " print('UNBOUNDED')\n"
                  "except OSError as e: print('BOUNDED' if e.errno==errno.ENOSPC else str(e.errno))\n")
        result = playground(source, limit=5)
        self.assertEqual(result["verdict"], "OK", result)
        self.assertEqual(result["stdout"].strip(), "BOUNDED")
        result = playground("import errno\ntry:\n for n in range(4100): open(str(n),'w').close()\n print('UNBOUNDED')\nexcept OSError as e: print('BOUNDED' if e.errno==errno.ENOSPC else str(e.errno))", limit=5)
        self.assertEqual(result["verdict"], "OK", result)
        self.assertEqual(result["stdout"].strip(), "BOUNDED")

    def test_kernel_aggregate_pids_limit(self):
        # At most six short sleeping children; no recursive spawning.
        source = ("import subprocess,sys,json\np=[];refused=0\n"
                  "try:\n"
                  " for _ in range(10):\n"
                  "  try:p.append(subprocess.Popen([sys.executable,'-c','import time;time.sleep(.3)']))\n"
                  "  except BlockingIOError:refused+=1\n"
                  " print(json.dumps({'refused':refused}))\n"
                  "finally:\n for child in p:child.wait()\n")
        result, stats = controlled(source, GRADER_JOB_PIDS="8")
        self.assertEqual(result.returncode, 0, result)
        self.assertGreater(json.loads(result.stdout)["refused"], 0)
        self.assertGreater(stats["pids.events"]["max"], 0)

    def test_kernel_cpu_throttles_all_children(self):
        result, stats = controlled("import time\nend=time.monotonic()+.6\nwhile time.monotonic()<end: pass", GRADER_JOB_CPU_QUOTA_US="25000")
        self.assertEqual(result.returncode, 0, result)
        self.assertGreater(stats["cpu.stat"]["nr_throttled"], 0)

    def test_kernel_memory_oom_stays_inside_the_job(self):
        # Bounded two-child allocation; kernel group ceiling is only 256 MiB.
        source = ("import subprocess,sys\np=[]\n"
                  "try:\n"
                  " for _ in range(2):p.append(subprocess.Popen([sys.executable,'-c','import time;x=bytearray(128*1024*1024);time.sleep(2)']))\n"
                  " for child in p:child.wait()\n"
                  "finally:\n for child in p:child.terminate() if child.poll() is None else None\n")
        with patch.dict(os.environ, {"GRADER_JOB_MEMORY_MB": "256"}), job_resources.job_scope() as boundary:
            env = judge_runner._runner_env() | {"TMPDIR": str(boundary.workspace)}
            result = judge_runner.run_bounded(
                [sys.executable, str(ROOT / "judge_runner.py"), "--job"],
                json.dumps({"kind": "playground", "payload": payload(source)}), 10,
                output_limit=16384, env=env, cwd=str(ROOT), containment=boundary)
            stats = counters(boundary.group / "memory.events")
            self.assertGreater(stats["oom_kill"], 0)
            self.assertNotEqual(result.returncode, 0)

    def test_cancellation_waits_for_group_and_workspace_cleanup(self):
        async def cancel():
            task = asyncio.create_task(judge_runner.run_isolated("playground", payload("import time;time.sleep(3)"), 10))
            await asyncio.sleep(.2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(cancel())


def main():
    if sys.argv[1:] == ["--diagnose"]:
        source = ("import os,sys,tempfile,traceback\n"
                  f"sys.path.insert(0,{str(ROOT)!r})\n"
                  "print('ENTRY_CAPS',[x for x in Path('/proc/self/status').read_text().splitlines() if x.startswith(('CapEff:','CapPrm:'))],flush=True)\n"
                  "import grader,job_sandbox\n"
                  "try:\n"
                  " with job_sandbox.scope():\n"
                  "  work=Path(tempfile.mkdtemp())\n"
                  "  src=work/'solution.py';src.write_text('print(1)')\n"
                  "  print('BEFORE_PREPARE',[x for x in Path('/proc/self/status').read_text().splitlines() if x.startswith(('CapEff:','CapPrm:'))],flush=True)\n"
                  "  grader.prepare_workspace(work,src);print('PREPARE_OK',flush=True)\n"
                  "  os.chdir(work);job_sandbox._current.get().workspace=os.getcwd()\n"
                  "  uid,gid=grader.sandbox_identity();grader._set_no_new_privileges()\n"
                  "  print([x for x in Path('/proc/self/status').read_text().splitlines() if x.startswith(('CapEff:','CapPrm:','CapBnd:'))],flush=True)\n"
                  "  os.setgroups([]);print('GROUPS_OK',flush=True)\n"
                  "  os.setgid(gid);print('GID_OK',flush=True)\n"
                  "  os.setuid(uid);print('DROP_OK',flush=True)\n"
                  "  job_sandbox.restrict_filesystem();print('LANDLOCK_OK',flush=True)\n"
                  "  job_sandbox.restrict_network();print('SECCOMP_OK',flush=True)\n"
                  "except BaseException:traceback.print_exc()\n"
                  "os._exit(0)\n")
        source = "from pathlib import Path\n" + source
        print(json.dumps({"manager_caps": [x for x in Path('/proc/self/status').read_text().splitlines() if x.startswith(('CapEff:', 'CapPrm:'))]}))
        result, stats = controlled(source)
        print(json.dumps({"diagnostic_stdout": result.stdout, "diagnostic_stderr": result.stderr}))
        return 0
    if sys.argv[1:] == ["--recovery-hold"]:
        with job_resources.job_scope() as boundary:
            Path('/var/lib/newbiegrader/recovery-marker.json').write_text(json.dumps({"cgroup": str(boundary.group), "workspace": str(boundary.workspace), "owner": os.getpid()}))
            judge_runner.run_bounded([sys.executable, "-c", "import time;time.sleep(30)"], "", 35,
                                     output_limit=1024, env={"PATH": "/usr/bin:/bin"}, containment=boundary)
        return 0
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(KernelIsolation)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"synthetic_only": True, "tests": result.testsRun,
                      "failures": len(result.failures), "errors": len(result.errors),
                      "skipped": len(result.skipped), "success": result.wasSuccessful()}))
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
