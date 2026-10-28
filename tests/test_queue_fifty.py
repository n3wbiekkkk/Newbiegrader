"""Fifty distinct HTTP sessions; fake DB admission, no throughput claim."""
from critical_helpers import patch_server_state
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from unittest.mock import patch
import unittest
from fastapi.testclient import TestClient
from critical_helpers import synthetic_problem, test_server
from fake_supabase import FakeSupabase

server = test_server()


class FiftyAdmissions(unittest.TestCase):
    def test_fifty_accounts_admit_once_and_fifty_first_is_confirmed_rejection(self):
        db = FakeSupabase()
        async def admit(i):
            return await server._create_job({'user_email': f'user{i}@example.invalid',
                'problem': 'synthetic', 'language': 'python', 'source': 'print(1)', 'kind': 'submit'})
        with patch.object(server, '_sb', db), patch.object(server, 'QUEUE_MODE', 'database'), \
                patch.object(server, 'QUEUE_MAX', 50):
            async def burst():
                return await asyncio.gather(*(admit(i) for i in range(50)))
            rows = asyncio.run(burst())
            self.assertEqual(len({r['id'] for r in rows}), 50)
            with self.assertRaises(server.HTTPException) as error:
                asyncio.run(admit(50))
            self.assertEqual(error.exception.status_code, 503)
            self.assertEqual(error.exception.headers['X-Newbiegrader-Admission'], 'rejected-queue-full')
            self.assertIn('คิวตรวจเต็ม', error.exception.detail)

    def test_fifty_signed_in_http_clients_submit_in_one_burst(self):
        db = FakeSupabase()
        problem = synthetic_problem()
        password = 'synthetic-burst-password'
        password_hash = server._hash_password(password)
        clients = []
        with ExitStack() as stack:
            for name, value in {'_sb': db, 'QUEUE_MODE': 'database', 'QUEUE_MAX': 50,
                'PROBLEMS': {problem.pid: problem}, '_login_tries': {}, '_account_tries': {},
                '_PROFILE_NAME_CACHE': {}, '_contest_pid_cache': {'at': 0, 'all': set(), 'hide': set()}}.items():
                stack.enter_context(patch_server_state(server, name, value))
            stack.enter_context(patch.object(server, '_ensure_problems_fresh'))
            for i in range(51):
                email = f'burst-{i}@example.invalid'
                db.rows('users').append({'email': email, 'name': f'Synthetic {i}',
                    'password_hash': password_hash, 'auth_version': 1,
                    'email_verified_at': '2026-10-24T00:00:00Z'})
                client = TestClient(server.app, base_url='https://testserver',
                    client=(f'198.51.100.{i+1}', 50000), headers={'Origin': server.FRONTEND_URL})
                stack.callback(client.close)
                # Real cookie creation/verification, with no lifespan judge workers.
                response = client.post('/api/auth/password', json={'email': email, 'password': password})
                self.assertEqual(response.status_code, 200, response.text)
                clients.append(client)
            def submit(client):
                return client.post('/api/submit', data={'problem': problem.pid,
                    'language': 'python', 'code': 'print(1)'})
            with ThreadPoolExecutor(max_workers=50) as pool:
                responses = list(pool.map(submit, clients[:50]))
            self.assertTrue(all(r.status_code == 202 for r in responses),
                            [(r.status_code, r.text) for r in responses if r.status_code != 202])
            self.assertEqual(len({r.json()['job_id'] for r in responses}), 50)
            full = submit(clients[50])
            self.assertEqual(full.status_code, 503, full.text)
            self.assertEqual(full.headers['X-Newbiegrader-Admission'], 'rejected-queue-full')
            self.assertEqual(full.headers['Retry-After'], '30')
            self.assertEqual(len(db.rows('judge_jobs')), 50)
