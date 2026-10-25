"""Presence protocol/health checks use synthetic credentials and local servers only."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

spec = importlib.util.spec_from_file_location("ng_presence", Path(__file__).resolve().parents[1] /
    "deploy/host/discord_presence.py")
presence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(presence)


class PresenceConfiguration(unittest.TestCase):
    def test_private_credential_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'credential'
            path.write_text(json.dumps({'token': 'synthetic-token'}))
            path.chmod(0o600)
            self.assertEqual(presence.read_token(path), 'synthetic-token')
            path.chmod(0o440)
            self.assertEqual(presence.read_token(path), 'synthetic-token')
            with patch.object(Path, 'lstat', return_value=SimpleNamespace(
                    st_mode=0o100440, st_gid=os.getegid() + 100000)):
                with self.assertRaises(ValueError):
                    presence.read_token(path)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                presence.read_token(path)
            path.chmod(0o600)
            link = Path(d) / 'link'; link.symlink_to(path)
            with self.assertRaises(ValueError):
                presence.read_token(link)
            path.write_text(json.dumps({'token': 'bad token'}))
            with self.assertRaises(ValueError):
                presence.read_token(path)

    def test_gateway_credentials_only_go_to_discord_tls_hosts(self):
        self.assertEqual(presence.gateway_url('wss://gateway.discord.gg'),
                         'wss://gateway.discord.gg/?v=10&encoding=json')
        self.assertTrue(presence.gateway_url('wss://gateway-us-east1-b.discord.gg').startswith('wss://'))
        for value in ['ws://gateway.discord.gg', 'wss://gateway.discord.gg.attacker.invalid',
                      'wss://attacker.invalid', 'wss://token@gateway.discord.gg',
                      'wss://gateway.discord.gg:444', 'wss://gateway.discord.gg/path',
                      'wss://gateway.discord.gg?token=synthetic']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                presence.gateway_url(value)
        with self.assertRaises(ValueError):
            presence.get_json('https://attacker.invalid', 'synthetic-token')

    def test_online_requires_all_workers_local_api_and_public_identity(self):
        units = [f'newbiegrader-worker@{i}.service' for i in range(1, 5)]
        result = SimpleNamespace(returncode=0, stdout='active\n' * 6)
        def get(url):
            if url.startswith('http://127.0.0.1:'):
                return {'ok': True, 'count': 89}
            self.assertEqual(url, 'https://public.example.invalid/api/auth/me')
            return {'user': None}
        with patch.object(presence.subprocess, 'run', return_value=result) as run, \
                patch.object(presence, 'get_json', side_effect=get):
            self.assertTrue(presence.health_ok('https://public.example.invalid', units))
            self.assertTrue(all(x in run.call_args.args[0] for x in units))
            self.assertFalse(presence.health_ok('https://public.example.invalid', units[:-1]))
            self.assertFalse(presence.health_ok('http://public.example.invalid', units))
            result.returncode = 3
            self.assertFalse(presence.health_ok('https://public.example.invalid', units))
        with patch.object(presence.subprocess, 'run', return_value=SimpleNamespace(
                returncode=0, stdout='active\n' * 6)), \
                patch.object(presence, 'get_json', side_effect=OSError('synthetic outage')):
            self.assertFalse(presence.health_ok('https://public.example.invalid', units))

    def test_catalog_growth_does_not_hide_healthy_website(self):
        units = [f'newbiegrader-worker@{i}.service' for i in range(1, 5)]
        result = SimpleNamespace(returncode=0, stdout='active\n' * 6)
        for count in (89, 100, 101, 0, -1, True, "100", None):
            with self.subTest(count=count), \
                    patch.object(presence.subprocess, 'run', return_value=result), \
                    patch.object(presence, 'get_json', side_effect=[
                        {'ok': True, 'count': count}, {'user': None}]):
                self.assertEqual(presence.health_ok('https://public.example.invalid', units),
                                 type(count) is int and count > 0)

    def test_two_worker_recovery_requires_both_workers_and_rejects_arbitrary_units(self):
        units = ['newbiegrader-worker@1.service', 'newbiegrader-worker@2.service']
        with patch.object(presence.subprocess, 'run', return_value=SimpleNamespace(
                returncode=0, stdout='active\n' * 4)), \
                patch.object(presence, 'get_json', side_effect=[{'ok': True, 'count': 100}, {'user': None}]):
            self.assertTrue(presence.health_ok('https://public.example.invalid', units))
        with patch.object(presence.subprocess, 'run') as run:
            for invalid in ([], units[:1], units[::-1], units[:1] * 2,
                            ['newbiegrader-worker@1.service', 'other.service']):
                self.assertFalse(presence.health_ok('https://public.example.invalid', invalid))
            run.assert_not_called()
        with patch.object(presence.subprocess, 'run', return_value=SimpleNamespace(
                returncode=0, stdout='active\ninactive\nactive\nactive\n')):
            self.assertFalse(presence.health_ok('https://public.example.invalid', units))

    def test_public_probe_never_follows_redirects_or_sends_credentials(self):
        from unittest.mock import MagicMock
        for body in [b'{"user":null}', b'{}']:
            response = MagicMock()
            response.__enter__.return_value = SimpleNamespace(status=200, read=lambda size: body)
            opener = MagicMock(); opener.open.return_value = response
            with patch.object(presence.urllib.request, 'build_opener', return_value=opener) as build:
                presence.get_json('https://public.example.invalid/api/auth/me')
                req = opener.open.call_args.args[0]
                self.assertIsNone(req.get_header('Authorization'))
                self.assertIsNone(req.get_header('Cookie'))
                self.assertEqual(req.get_header('Cache-control'), 'no-cache')
                self.assertTrue(any(isinstance(x, presence.NoRedirect) for x in build.call_args.args))
        handler = presence.NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, '', None, 'https://attacker.invalid'))


class PresenceGateway(unittest.IsolatedAsyncioTestCase):
    async def run_peer(self, peer, bot):
        async with serve(peer, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f'ws://127.0.0.1:{port}', ping_interval=None) as ws:
                return await bot.connection(ws)

    async def test_real_websocket_health_transitions_and_clean_stop(self):
        statuses = []; hello_auth = []; heartbeat = []; closes = []
        done = asyncio.Event()
        heartbeat_seen = asyncio.Event()
        values = iter([True, False, True])
        bot = presence.Gateway('synthetic-token', lambda: next(values, True), interval=0.02)
        async def peer(ws):
            await ws.send(json.dumps({'op': 10, 'd': {'heartbeat_interval': 50}}))
            auth = json.loads(await ws.recv()); hello_auth.append(auth)
            await ws.send(json.dumps({'op': 0, 't': 'READY', 's': 7, 'd': {
                'session_id': 'synthetic-session', 'resume_gateway_url': 'wss://gateway.discord.gg'}}))
            try:
                async for raw in ws:
                    event = json.loads(raw)
                    if event['op'] == 1:
                        heartbeat.append(event['d'])
                        heartbeat_seen.set()
                        await ws.send('{"op":11,"d":null}')
                    elif event['op'] == 3:
                        statuses.append(event['d']['status'])
                        if statuses[-3:] == ['online', 'invisible', 'online']:
                            done.set()
            finally:
                closes.append(ws.close_code)
        task = asyncio.create_task(self.run_peer(peer, bot))
        await asyncio.wait_for(asyncio.gather(done.wait(), heartbeat_seen.wait()), 3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.01)
        self.assertEqual(hello_auth[0]['op'], 2)
        self.assertEqual(hello_auth[0]['d']['intents'], 0)
        self.assertEqual(hello_auth[0]['d']['presence']['status'], 'invisible')
        self.assertEqual(bot.session_id, 'synthetic-session')
        self.assertTrue(heartbeat)
        self.assertEqual(closes, [1000])

    async def test_missing_heartbeat_ack_closes_and_preserves_resume(self):
        bot = presence.Gateway('synthetic-token', lambda: True)
        async def peer(ws):
            await ws.send('{"op":10,"d":{"heartbeat_interval":30}}')
            await ws.recv()
            await ws.send(json.dumps({'op': 0, 't': 'READY', 's': 8, 'd': {
                'session_id': 'synthetic', 'resume_gateway_url': 'wss://gateway.discord.gg'}}))
            await ws.wait_closed()
        with self.assertRaises(presence.Reconnect):
            await asyncio.wait_for(self.run_peer(peer, bot), 3)
        self.assertEqual(bot.session_id, 'synthetic')
        self.assertEqual(bot.seq, 8)

    async def test_invalid_resume_session_discards_state_without_new_identify(self):
        bot = presence.Gateway('synthetic-token', lambda: True)
        bot.session_id = 'synthetic'; bot.seq = 5; bot.resume_url = 'wss://gateway.discord.gg'
        sent = []
        async def peer(ws):
            await ws.send('{"op":10,"d":{"heartbeat_interval":5000}}')
            sent.append(json.loads(await ws.recv()))
            await ws.send('{"op":9,"d":false}')
            await ws.wait_closed()
        with patch.object(presence.random, 'uniform', return_value=0):
            with self.assertRaises(presence.Reconnect):
                await asyncio.wait_for(self.run_peer(peer, bot), 3)
        self.assertEqual(sent[0]['op'], 6)
        self.assertIsNone(bot.session_id)
        self.assertIsNone(bot.seq)

    async def test_resumed_connection_rechecks_health_before_online(self):
        bot = presence.Gateway('synthetic-token', lambda: False)
        bot.session_id = 'synthetic'; bot.seq = 5; bot.resume_url = 'wss://gateway.discord.gg'
        statuses = []; done = asyncio.Event()
        async def peer(ws):
            await ws.send('{"op":10,"d":{"heartbeat_interval":5000}}')
            auth = json.loads(await ws.recv()); self.assertEqual(auth['op'], 6)
            await ws.send('{"op":0,"t":"RESUMED","s":6,"d":{}}')
            async for raw in ws:
                event = json.loads(raw)
                if event['op'] == 3:
                    statuses.append(event['d']['status'])
                    if len(statuses) == 2:
                        done.set()
        task = asyncio.create_task(self.run_peer(peer, bot))
        await asyncio.wait_for(done.wait(), 3); task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(statuses, ['invisible', 'invisible'])


if __name__ == '__main__':
    unittest.main()
