"""Exercise upgrade rollback with a disposable prefix and stubbed host commands."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PythonUpgrade(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.prefix = self.root/'runtime'
        self.bin = self.root/'commands'; self.bin.mkdir()
        self.release = self.root/'release'; self.release.mkdir()
        (self.release/'deploy/host').mkdir(parents=True)
        (self.release/'deploy/host/requirements.lock').write_text('# synthetic\n')
        source = (ROOT/'deploy/host/upgrade_python.sh').read_text()
        source = source.replace('PREFIX=/usr/local/lib/newbiegrader',
                                'PREFIX='+str(self.prefix))
        self.script = self.root/'upgrade_python.sh'; self.script.write_text(source)
        (self.root/'bootstrap.sh').write_bytes((ROOT/'deploy/host/bootstrap.sh').read_bytes())
        self.executable(self.prefix/'venv/bin/python', '#!/bin/sh\necho 3.11.17\n')
        (self.prefix/'venv/old-marker').write_text('preserve-old-runtime')
        self.executable(self.bin/'id', '#!/bin/sh\necho 0\n')
        self.executable(self.bin/'systemctl', '#!/bin/sh\ntest "${MOCK_ACTIVE:-}" = "$3"\n')
        self.executable(self.bin/'runuser', '#!/bin/sh\nshift 3\nexec "$@"\n')
        self.executable(self.prefix/'bootstrap/bin/pip', '#!/bin/sh\nexit 0\n')
        self.executable(self.prefix/'bootstrap/bin/uv', '''#!/bin/sh
set -eu
case "$1 $2" in
    "python install")
        mkdir -p "$UV_PYTHON_INSTALL_DIR/synthetic"
        echo public-runtime > "$UV_PYTHON_INSTALL_DIR/synthetic/public-file"
        ;;
    "venv --python")
        mkdir -p "$4/bin"
        printf '#!/bin/sh\\nexit 0\\n' > "$4/bin/python"
        chmod 755 "$4/bin/python"
        ;;
    "pip install")
        if test "${MOCK_INSTALL_FAIL:-0}" = 1; then exit 42; fi
        ;;
esac
''')
        self.env = dict(os.environ, PATH=str(self.bin)+os.pathsep+os.environ['PATH'])

    def executable(self, path, source):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source); path.chmod(0o755)

    def run_script(self, *args, **settings):
        # Start with an operator's private umask; the installer must normalize it.
        return subprocess.run(['/bin/sh', '-c', 'umask 077; exec /bin/sh "$@"',
                               'upgrade-test', str(self.script), *map(str,args)],
                              env=dict(self.env, **settings), capture_output=True, text=True)

    def test_failed_install_restores_previous_runtime(self):
        result = self.run_script(self.release, MOCK_INSTALL_FAIL='1')
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual((self.prefix/'venv/old-marker').read_text(), 'preserve-old-runtime')
        self.assertFalse((self.prefix/'venv.previous').exists())

    def test_success_and_explicit_rollback_preserve_both_runtimes(self):
        result = self.run_script(self.release)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.prefix/'venv.previous/old-marker').is_file())
        self.assertEqual((self.prefix/'python/synthetic/public-file').stat().st_mode & 0o777, 0o644)
        result = self.run_script('--rollback')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.prefix/'venv/old-marker').is_file())
        self.assertTrue((self.prefix/'venv.failed/bin/python').is_file())

    def test_active_unit_refuses_before_runtime_mutation(self):
        result = self.run_script(self.release, MOCK_ACTIVE='newbiegrader-api.service')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Stop these units', result.stderr)
        self.assertTrue((self.prefix/'venv/old-marker').is_file())
        self.assertFalse((self.prefix/'python').exists())
