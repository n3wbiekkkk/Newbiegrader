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
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


alert = _load("ng_alert", "deploy/host/newbiegrader-alert.py")
backup = _load("ng_backup", "deploy/host/newbiegrader-backup.py")


class AlertWatchdog(unittest.TestCase):
    def test_primary_probe_is_anonymous_and_alerts_in_the_application_route(self):
        url = 'http://100.91.14.10:9187/health'
        from unittest.mock import MagicMock
        context = MagicMock()
        context.__enter__.return_value = SimpleNamespace(status=200,
            read=lambda size: b'{"ok":true,"count":100}', geturl=lambda: url)
        with patch.object(alert.urllib.request, 'urlopen', return_value=context) as open_url:
            alert._primary_probe(url)
        request = open_url.call_args.args[0]
        self.assertIsNone(request.get_header('Cookie'))
        self.assertIsNone(request.get_header('Authorization'))
        self.assertEqual(alert._check_scope('primary backend'), 'newbiegrader')
        for invalid in ('http://example.invalid:9187/health', 'http://127.0.0.1:9187/health',
                        'http://100.91.14.10:9187/api/auth/me'):
            with self.subTest(url=invalid), self.assertRaises(ValueError):
                alert._primary_probe(invalid)

    def test_public_check_uses_https_without_cookies_or_credentials(self):
        response = SimpleNamespace(status=200, read=lambda size: b'{"user":null}',
            geturl=lambda: 'https://public.example.invalid/api/auth/me')
        from unittest.mock import MagicMock
        context = MagicMock()
        context.__enter__.return_value = response
        with patch.object(alert.urllib.request, 'urlopen', return_value=context) as open_url:
            alert._public_identity('https://public.example.invalid')
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, 'https://public.example.invalid/api/auth/me')
        self.assertIsNone(request.get_header('Cookie'))
        self.assertIsNone(request.get_header('Authorization'))
        self.assertEqual(request.get_header('Cache-control'), 'no-cache')

    def test_public_check_rejects_wrong_payload_and_unsafe_urls(self):
        from unittest.mock import MagicMock
        for body in (b'{}', b'{"user":{"email":"synthetic@example.invalid"}}', b'[]', b'not JSON'):
            context = MagicMock()
            context.__enter__.return_value = SimpleNamespace(status=200, read=lambda size: body,
                geturl=lambda: 'https://public.example.invalid/api/auth/me')
            with patch.object(alert.urllib.request, 'urlopen', return_value=context):
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    alert._public_identity('https://public.example.invalid')
        for url in ('http://public.example.invalid', 'https://user:password@example.invalid',
                    'https://example.invalid/path', 'https://example.invalid?token=synthetic'):
            with self.assertRaises(ValueError):
                alert._public_identity(url)

    def test_journal_checks_every_configured_worker(self):
        units = [f"newbiegrader-worker@{i}.service" for i in range(1, 5)]
        with patch.dict(os.environ, {"NEWBIEGRADER_WORKER_UNITS": " ".join(units)}), \
                patch.object(alert.subprocess, "run", return_value=SimpleNamespace(
                    stdout="", returncode=0)) as run:
            self.assertEqual(alert._journal_hits(60), [])
        command = run.call_args.args[0]
        for unit in units + ["newbiegrader-api.service"]:
            self.assertIn(unit, command)

    def test_all_configured_workers_are_required(self):
        units = [f"newbiegrader-worker@{i}.service" for i in range(1, 5)]
        for failed in (None, units[-1]):
            with self.subTest(failed=failed), patch.dict(os.environ, {
                    "NEWBIEGRADER_WORKER_UNITS": " ".join(units)}), \
                    patch.object(alert, "_service_state", side_effect=lambda unit:
                                 "inactive" if unit == failed else "active"):
                check = next(c for c in alert.collect_checks() if c["name"] == "judge worker")
                self.assertEqual(check["ok"], failed is None)
                for unit in units:
                    self.assertIn(unit, check["detail"])

    def test_every_check_is_reported_and_never_raises(self):
        checks = alert.collect_checks()
        self.assertTrue(checks)
        names = {c["name"] for c in checks}
        for expected in ("api health", "api role and queue", "judge worker",
                         "cloudflare tunnel", "durable queue", "disk space",
                         "backup freshness", "account retention", "journal errors"):
            self.assertIn(expected, names)
        for check in checks:
            self.assertIn("ok", check)
            self.assertIn("detail", check)

    def test_retention_requires_enabled_timer_recent_success_and_zero_exit(self):
        completed = 200_000_000_000
        for timer, result, status, exited, hours, expected in (
                ('active', 'success', '0', completed, 24, True),
                ('inactive', 'success', '0', completed, 1, False),
                ('active', 'exit-code', '1', completed, 1, False),
                ('active', 'success', '0', completed, 37, False),
                ('active', 'success', '0', 0, 1, False),
                ('active', 'success', '0', completed, -1, False)):
            with self.subTest(timer=timer, result=result, status=status, hours=hours), \
                    patch.object(alert, '_service_state', return_value=timer), \
                    patch.object(alert, '_systemctl', return_value=(
                        f'Result={result}\nExecMainStatus={status}\nExecMainExitTimestampMonotonic={exited}')), \
                    patch.object(alert.time, 'monotonic', return_value=completed/1_000_000+hours*3600):
                self.assertEqual(alert._retention_health()[0], expected)
        with patch.object(alert, '_service_state', return_value='active'), \
                patch.object(alert, '_systemctl', return_value='unavailable'):
            self.assertFalse(alert._retention_health()[0])

    def test_mail_outage_marker_is_detected_without_provider_details(self):
        with patch.object(alert.subprocess, 'run', return_value=SimpleNamespace(
                stdout='email verification provider unavailable\n', returncode=0)):
            self.assertEqual(alert._journal_hits(60), ['email verification provider unavailable'])

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
        self.assertEqual(body, {"content": "boom", "allowed_mentions": {"parse": []}})
        self.assertEqual(headers["Authorization"], "Bot bot-token")
        body, headers = alert._format_for(
            "https://discord.com/api/webhooks/1/tok", payload, "")
        self.assertEqual(body, {"content": "boom", "allowed_mentions": {"parse": []}})
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

    def test_discord_cards_frame_failure_and_recovery_with_status_colors(self):
        for ok, color, title in ((False, 0xE74C3C, "พบปัญหา"),
                                 (True, 0x2ECC71, "กลับมาปกติแล้ว")):
            with self.subTest(ok=ok):
                payload = alert.build_payload([{"name": "judge worker", "ok": ok}],
                    {"broken": ["judge worker"]} if ok else {}, "Backend")
                embed = payload["embed"]
                self.assertEqual(embed["color"], color)
                self.assertIn(title, embed["title"])
                self.assertNotIn("**", embed["title"])
                self.assertIn("Backend", embed["description"])
                self.assertIn("เวลาไทย", embed["footer"]["text"])
                for url in ("https://discord.com/api/v10/channels/42/messages",
                            "https://discord.com/api/webhooks/1/tok"):
                    body, _ = alert._format_for(url, payload, "synthetic")
                    self.assertEqual(body["embeds"], [embed])
                    self.assertNotIn("content", body)
                    self.assertEqual(body["allowed_mentions"], {"parse": []})
                body, _ = alert._format_for("https://hooks.slack.com/services/x", payload)
                self.assertEqual(body, {"text": payload["text"]})

    def test_only_a_transition_sends_a_message(self):
        broken = [{"name": "judge worker", "ok": False, "detail": "inactive"}]
        healthy = [{"name": "judge worker", "ok": True, "detail": "active"}]
        state = {"broken": []}
        payload = alert.build_payload(broken, state)
        self.assertIn("❌ **ตัวตรวจคำตอบ**", payload["text"])
        self.assertIn("พบปัญหา 1 รายการ", payload["text"])
        self.assertEqual(payload["broken"], ["judge worker"])
        recovered = alert.build_payload(healthy, {"broken": ["judge worker"]})
        self.assertIn("กลับมาปกติแล้ว", recovered["text"])
        self.assertIn("✅ ตัวตรวจคำตอบ", recovered["text"])
        self.assertNotIn("judge worker", recovered["broken"])

    def test_the_host_label_appears_in_the_message(self):
        payload = alert.build_payload([], {"broken": []}, "PC 192.168.100.24")
        self.assertIn("**เครื่อง:** PC 192.168.100.24", payload["text"])

    def test_route_config_requires_two_distinct_discord_channels(self):
        routes = {scope: {"url": f"https://discord.com/api/v10/channels/{i}/messages"}
                  for i, scope in enumerate(("newbiegrader", "homeserver"), 1)}
        self.assertEqual(alert._validate_routes(routes), routes)
        for invalid in ({}, {"newbiegrader": routes["newbiegrader"]},
                        {"newbiegrader": routes["newbiegrader"], "homeserver": routes["newbiegrader"]},
                        {**routes, "homeserver": {"url": "https://discord.com.evil.invalid/api/v10/channels/2/messages"}}):
            with self.subTest(invalid=invalid), self.assertRaises(SystemExit):
                alert._validate_routes(invalid)

    def test_route_transitions_recover_independently_and_do_not_repeat(self):
        secret = {"token": "synthetic", "routes": {
            "newbiegrader": {"url": "community"}, "homeserver": {"url": "private"}}}
        checks = [{"name": "judge worker", "ok": False},
                  {"name": "service Nextcloud", "ok": False}]
        with patch.object(alert, "_post_json") as post:
            state, failed = alert.notify_routes(checks, {}, secret)
            self.assertFalse(failed)
            self.assertEqual([c.args[0] for c in post.call_args_list], ["community", "private"])
            self.assertNotIn("Nextcloud", post.call_args_list[0].args[1]["text"])
            self.assertNotIn("ตัวตรวจคำตอบ", post.call_args_list[1].args[1]["text"])
            post.reset_mock()
            state, _ = alert.notify_routes(checks, state, secret)
            post.assert_not_called()
            checks[0]["ok"] = True
            state, _ = alert.notify_routes(checks, state, secret)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.args[0], "community")
            self.assertIn("กลับมาปกติแล้ว", post.call_args.args[1]["text"])
            self.assertEqual(state["broken"], ["service Nextcloud"])

    def test_failed_route_retries_without_repeating_success_or_leaking_error(self):
        import contextlib
        import io
        secret = {"routes": {"newbiegrader": {"url": "community"}, "homeserver": {"url": "private"}}}
        checks = [{"name": "judge worker", "ok": False}, {"name": "service Nextcloud", "ok": False}]
        errors = io.StringIO()
        with patch.object(alert, "_post_json", side_effect=[None, OSError("PRIVATE_SECRET")]), contextlib.redirect_stderr(errors):
            state, failed = alert.notify_routes(checks, {}, secret)
        self.assertTrue(failed)
        self.assertNotIn("PRIVATE_SECRET", errors.getvalue())
        with patch.object(alert, "_post_json") as post:
            state, failed = alert.notify_routes(checks, state, secret)
            self.assertFalse(failed)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.args[0], "private")

    def test_legacy_incident_migration_is_quiet(self):
        checks = [{"name": "judge worker", "ok": False}, {"name": "service Nextcloud", "ok": False}]
        with patch.object(alert, "_post_json") as post:
            state, failed = alert.notify_routes(checks, {"broken": [c["name"] for c in checks]}, {})
        post.assert_not_called()
        self.assertFalse(failed)
        self.assertEqual(state["routes"]["homeserver"]["broken"], ["service Nextcloud"])

    def test_missing_explicit_route_never_falls_back_to_community(self):
        with patch.object(alert, "_post_json") as post:
            state, failed = alert.notify_routes([{"name": "unknown hardware check", "ok": False}], {},
                {"url": "community", "routes": {"newbiegrader": {"url": "community"}}})
        post.assert_not_called()
        self.assertTrue(failed)
        self.assertEqual(state["broken"], [])

    def test_preview_and_check_only_never_write_state_or_send(self):
        for flag in ("--dry-run", "--check-only"):
            with self.subTest(flag=flag), patch.object(alert, "collect_checks", return_value=[
                    {"name": "judge worker", "ok": False, "detail": "inactive"}]), \
                    patch.object(alert, "_load_state", return_value={}), \
                    patch.object(alert, "_save_state") as save, \
                    patch.object(alert, "_read_secret") as read, \
                    patch.object(alert, "_post_json") as post:
                self.assertEqual(alert.main([flag]), 1)
                save.assert_not_called()
                read.assert_not_called()
                post.assert_not_called()

    def test_message_is_bounded_and_excludes_raw_diagnostics(self):
        checks = [{"name": name, "ok": False, "detail": "PRIVATE_SECRET"}
                  for name in alert.CHECK_MESSAGES]
        checks.extend({"name": "service " + "x" * 100, "ok": False} for _ in range(40))
        payload = alert.build_payload(checks, {}, "@everyone\n**host**")
        self.assertLessEqual(len(payload["text"]), 2000)
        self.assertNotIn("PRIVATE_SECRET", payload["text"])
        self.assertNotIn("@everyone", payload["text"])
        self.assertIn("เวลาไทย", payload["text"])
        embed = payload["embed"]
        self.assertLessEqual(len(embed["title"]), 256)
        self.assertLessEqual(len(embed["description"]), 4096)
        self.assertLessEqual(sum(len(value) for value in (
            embed["title"], embed["description"], embed["footer"]["text"])), 6000)
        self.assertNotIn("PRIVATE_SECRET", json.dumps(embed))

    def test_state_file_is_written_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "alert-state.json"
            alert._save_state(path, {"broken": ["x"]})
            self.assertEqual(json.loads(path.read_text())["broken"], ["x"])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


class EncryptedBackup(unittest.TestCase):
    def test_durable_schema_tables_are_listed(self):
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

    def test_ephemeral_sessions_are_excluded_from_data_exports(self):
        tables = backup.public_tables(ROOT / "supabase" / "schema.sql")
        self.assertIn("users", tables)
        self.assertNotIn("web_sessions", tables)
        self.assertIn("create table if not exists public.web_sessions", (ROOT / "supabase/schema.sql").read_text())

    def test_the_private_identity_is_never_read_by_the_host_script(self):
        source = (ROOT / "deploy/host" / "newbiegrader-backup.py").read_text(encoding="utf-8")
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
            path = ROOT / "deploy" / "host" / name
            self.assertTrue(path.is_file(), f"missing {name}")
            text = path.read_text(encoding="utf-8")
            self.assertIn("[Unit]", text)
            self.assertIn("ProtectSystem=strict", text)
            self.assertIn("NoNewPrivileges=yes", text)
            self.assertIn("CapabilityBoundingSet=", text)
            self.assertIn("ReadWritePaths=/var/lib/newbiegrader", text)
        for name in ("newbiegrader-backup.timer", "newbiegrader-alert.timer"):
            path = ROOT / "deploy" / "host" / name
            self.assertTrue(path.is_file(), f"missing {name}")
            text = path.read_text(encoding="utf-8")
            self.assertIn("[Unit]", text)
            self.assertIn("Persistent=true", text)

    def test_the_units_run_the_scripts_from_the_repository(self):
        self.assertIn("newbiegrader-backup.py",
                      (ROOT / "deploy/host/newbiegrader-backup.service").read_text())
        self.assertIn("newbiegrader-alert.py",
                      (ROOT / "deploy/host/newbiegrader-alert.service").read_text())

    def test_the_backup_timer_runs_daily_and_survives_a_restart(self):
        text = (ROOT / "deploy/host/newbiegrader-backup.timer").read_text(encoding="utf-8")
        self.assertIn("OnCalendar=", text)
        self.assertIn("Persistent=true", text)

    def test_the_alert_timer_runs_often(self):
        text = (ROOT / "deploy/host/newbiegrader-alert.timer").read_text(encoding="utf-8")
        self.assertIn("OnUnitActiveSec=", text)
        self.assertIn("Persistent=true", text)


if __name__ == "__main__":
    unittest.main()
