"""Host operations: the alert watchdog and the encrypted backup.

No fixtures, no credentials, no network. The scripts are imported as modules
and exercised through their pure helpers.
"""
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


alert = _load("ng_alert", "deploy/ec2/newbiegrader-alert.py")
backup = _load("ng_backup", "deploy/ec2/newbiegrader-backup.py")


class AlertWatchdog(unittest.TestCase):
    def test_every_check_is_reported_and_never_raises(self):
        checks = alert.collect_checks()
        self.assertTrue(checks)
        names = {c["name"] for c in checks}
        for expected in ("api health", "api role and queue", "judge worker",
                         "cloudflare tunnel", "durable queue", "disk space",
                         "backup freshness", "journal errors"):
            self.assertIn(expected, names)
        for check in checks:
            self.assertIn("ok", check)
            self.assertIn("detail", check)

    def test_webhook_must_be_a_private_root_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "webhook"
            path.write_text("https://example.invalid/hook", encoding="utf-8")
            os.chmod(path, 0o644)
            with self.assertRaises(SystemExit):
                alert._read_secret(path)
            os.chmod(path, 0o600)
            self.assertEqual(alert._read_secret(path)["url"],
                             "https://example.invalid/hook")

    def test_webhook_accepts_a_json_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "webhook"
            path.write_text(json.dumps({"url": "https://example.invalid/x",
                                        "token": "secret", "to": "U123"}),
                            encoding="utf-8")
            os.chmod(path, 0o600)
            config = alert._read_secret(path)
            self.assertEqual(config["url"], "https://example.invalid/x")
            self.assertEqual(config["token"], "secret")
            self.assertEqual(config["to"], "U123")

    def test_discord_bot_payloads_use_the_right_shape(self):
        payload = {"text": "boom", "line_to": "U123"}
        body, headers = alert._format_for(
            "https://discord.com/api/v10/channels/42/messages", payload, "bot-token")
        self.assertEqual(body, {"content": "boom"})
        self.assertEqual(headers["Authorization"], "Bot bot-token")
        body, headers = alert._format_for(
            "https://discord.com/api/webhooks/1/tok", payload, "")
        self.assertEqual(body, {"content": "boom"})
        self.assertNotIn("Authorization", headers)
        body, headers = alert._format_for("https://hooks.slack.com/services/x", payload, "")
        self.assertEqual(body, {"text": "boom"})

    def test_backup_freshness_is_read_from_the_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "last-backup"
            self.assertIsNone(alert._backup_age_hours(marker))
            marker.write_text("not-a-timestamp", encoding="utf-8")
            self.assertIsNone(alert._backup_age_hours(marker))
            marker.write_text("2026-10-22T00:00:00+00:00", encoding="utf-8")
            age = alert._backup_age_hours(marker)
            self.assertIsInstance(age, float)
            self.assertGreater(age, 0)

    def test_only_a_transition_sends_a_message(self):
        broken = [{"name": "judge worker", "ok": False, "detail": "inactive"}]
        healthy = [{"name": "judge worker", "ok": True, "detail": "active"}]
        state = {"broken": []}
        payload = alert.build_payload(broken, state)
        self.assertIn("judge worker", payload["text"])
        self.assertEqual(payload["broken"], ["judge worker"])
        recovered = alert.build_payload(healthy, {"broken": ["judge worker"]})
        self.assertNotIn("judge worker", recovered["broken"])

    def test_state_file_is_written_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "alert-state.json"
            alert._save_state(path, {"broken": ["x"]})
            self.assertEqual(json.loads(path.read_text())["broken"], ["x"])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


class EncryptedBackup(unittest.TestCase):
    def test_every_schema_table_is_listed(self):
        tables = backup.public_tables(ROOT / "supabase" / "schema.sql")
        for expected in ("submissions", "problems", "users", "judge_jobs",
                         "contests", "profiles", "reports", "admins"):
            self.assertIn(expected, tables)
        self.assertEqual(len(tables), len(set(tables)), "no table may be listed twice")

    def test_backup_covers_the_configuration_and_the_uid_ledger(self):
        for relative in backup.CONFIG_FILES:
            self.assertTrue(relative.startswith("etc/"), relative)
        self.assertIn("allocated-uids", backup.UID_LEDGER)
        self.assertIn("tunnel-token", " ".join(backup.CONFIG_FILES))

    def test_the_private_identity_is_never_read_by_the_host_script(self):
        source = (ROOT / "deploy/ec2" / "newbiegrader-backup.py").read_text(encoding="utf-8")
        self.assertNotIn("identity.txt", source)
        self.assertNotIn("age-keygen -o", source)
        self.assertIn("backup-recipient", source)

    def test_env_reader_handles_quotes_and_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api.env"
            path.write_text('# comment\nA=1\nB="two"\nC=\'three\'\nD=\n',
                            encoding="utf-8")
            values = backup.read_env(path)
            self.assertEqual(values["A"], "1")
            self.assertEqual(values["B"], "two")
            self.assertEqual(values["C"], "three")
            self.assertEqual(values["D"], "")


class HostUnits(unittest.TestCase):
    def test_backup_and_alert_units_exist_and_are_hardened(self):
        for name in ("newbiegrader-backup.service", "newbiegrader-alert.service"):
            path = ROOT / "deploy" / "ec2" / name
            self.assertTrue(path.is_file(), f"missing {name}")
            text = path.read_text(encoding="utf-8")
            self.assertIn("[Unit]", text)
            self.assertIn("ProtectSystem=strict", text)
            self.assertIn("NoNewPrivileges=yes", text)
            self.assertIn("CapabilityBoundingSet=", text)
            self.assertIn("ReadWritePaths=/var/lib/newbiegrader", text)
        for name in ("newbiegrader-backup.timer", "newbiegrader-alert.timer"):
            path = ROOT / "deploy" / "ec2" / name
            self.assertTrue(path.is_file(), f"missing {name}")
            text = path.read_text(encoding="utf-8")
            self.assertIn("[Unit]", text)
            self.assertIn("Persistent=true", text)

    def test_the_units_run_the_scripts_from_the_repository(self):
        self.assertIn("newbiegrader-backup.py",
                      (ROOT / "deploy/ec2/newbiegrader-backup.service").read_text())
        self.assertIn("newbiegrader-alert.py",
                      (ROOT / "deploy/ec2/newbiegrader-alert.service").read_text())

    def test_the_backup_timer_runs_daily_and_survives_a_restart(self):
        text = (ROOT / "deploy/ec2/newbiegrader-backup.timer").read_text(encoding="utf-8")
        self.assertIn("OnCalendar=", text)
        self.assertIn("Persistent=true", text)

    def test_the_alert_timer_runs_often(self):
        text = (ROOT / "deploy/ec2/newbiegrader-alert.timer").read_text(encoding="utf-8")
        self.assertIn("OnUnitActiveSec=", text)
        self.assertIn("Persistent=true", text)


if __name__ == "__main__":
    unittest.main()
