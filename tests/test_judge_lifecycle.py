"""Owned-attempt contracts through the same interface used by workers."""
import asyncio
import copy
import datetime as dt
import unittest
from unittest.mock import AsyncMock, Mock

from fake_supabase import FakeSupabase
from judge_lifecycle import Completion, DatabaseJobs, JobLifecycle, LocalJobs


class JudgeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.observations = {}
        self.changed = Mock()

        async def rpc(name, **params):
            return self.db.rpc('judge_queue_' + name, params).execute().data

        self.rpc = rpc

    def claim(self):
        admitted = self.db.rpc('judge_queue_admit', {
            'p_job': {'id': 'owned', 'kind': 'playground', 'user_email': 'owner@example.invalid',
                      'status': 'queued', 'source': 'print(1)', 'payload': {'input': 'private'}},
            'p_queue_max': 5, 'p_track_active': True, 'p_quota_limit': 0,
            'p_quota_window': 0}).execute().data
        self.assertNotIn('error', admitted)
        return self.db.rpc('judge_queue_claim', {'p_worker': 'first', 'p_lease_seconds': 30}).execute().data

    def backend(self, rpc=None, heartbeat_seconds=10):
        return DatabaseJobs(rpc or self.rpc, self.observations, self.changed,
                            heartbeat_seconds=heartbeat_seconds, lease_seconds=30)

    async def test_database_completion_uses_owned_copy_despite_poll_and_caller_mutation(self):
        claimed = self.claim()
        entered, release = asyncio.Event(), asyncio.Event()

        async def runner(*args):
            entered.set()
            await release.wait()
            return {'stdout': 'old result'}

        async def work(job, execute):
            result = await execute('playground', {}, 5)
            # Even accidental mutation in preparation cannot replace the fence.
            job.update(worker_id='second', attempt=99)
            return Completion(result=result)

        lifecycle = JobLifecycle(self.backend(), None, runner)
        pending = asyncio.create_task(lifecycle.run(claimed, work))
        await entered.wait()
        self.db.rows('judge_jobs')[0]['lease_until'] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).isoformat()
        newer = self.db.rpc('judge_queue_claim', {'p_worker': 'second', 'p_lease_seconds': 30}).execute().data
        self.observations['owned'] = copy.deepcopy(newer)
        claimed.update(newer)
        release.set()
        await pending
        current = self.db.rows('judge_jobs')[0]
        self.assertEqual(current['status'], 'running')
        self.assertEqual(current['worker_id'], 'second')
        self.assertEqual(current['attempt'], newer['attempt'])
        self.changed.assert_not_called()

    async def test_database_success_persists_result_and_invalidates_observations(self):
        claimed = self.claim()

        async def work(job, execute):
            result = await execute('playground', {}, 5)
            return Completion(result=result)

        self.observations['owned'] = copy.deepcopy(claimed)
        runner = AsyncMock(return_value={'stdout': 'completed'})
        await JobLifecycle(self.backend(), None, runner).run(claimed, work)
        self.assertEqual(self.db.rows('judge_jobs')[0]['status'], 'done')
        self.assertEqual(self.db.rows('judge_jobs')[0]['result']['stdout'], 'completed')
        self.assertNotIn('owned', self.observations)
        self.changed.assert_called_once()

    async def test_lost_heartbeat_waits_for_cleanup_before_attempting_completion(self):
        claimed = self.claim()
        cleaned = asyncio.Event()

        async def runner(*args):
            try:
                await asyncio.Future()
            finally:
                await asyncio.sleep(.01)
                cleaned.set()

        async def rpc(name, **params):
            if name == 'heartbeat':
                return False
            self.assertTrue(cleaned.is_set())
            return await self.rpc(name, **params)

        async def work(job, execute):
            with self.assertRaisesRegex(RuntimeError, 'ownership lost'):
                await execute('playground', {}, 5)
            return Completion(error='ownership lost')

        await JobLifecycle(self.backend(rpc, .001), None, runner).run(claimed, work)
        self.assertTrue(cleaned.is_set())

    async def test_parent_cancellation_waits_for_cleanup_and_never_finishes(self):
        claimed = self.claim()
        entered, cleaned = asyncio.Event(), asyncio.Event()

        async def runner(*args):
            try:
                entered.set()
                await asyncio.Future()
            finally:
                await asyncio.sleep(.01)
                cleaned.set()

        async def work(job, execute):
            return Completion(result=await execute('playground', {}, 5))

        pending = asyncio.create_task(JobLifecycle(self.backend(), None, runner).run(claimed, work))
        await entered.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertTrue(cleaned.is_set())
        self.assertEqual(self.db.rows('judge_jobs')[0]['status'], 'running')
        self.changed.assert_not_called()

    async def test_ambiguous_finish_is_not_replayed(self):
        claimed = self.claim()
        rpc = AsyncMock(side_effect=OSError('ambiguous finish'))
        self.observations['owned'] = claimed
        with self.assertRaises(OSError):
            await JobLifecycle(self.backend(rpc), None, None).complete(claimed, Completion(error='failed'))
        rpc.assert_awaited_once()
        self.assertIn('owned', self.observations)

    async def test_local_completion_redacts_and_releases_source_payload_and_admission(self):
        job = {'id': 'local', 'kind': 'submit', 'user_email': 'owner',
               'source': 'private source', 'payload': {'input': 'private input'}}
        active = {'owner': {'local'}}
        update, prune = AsyncMock(), Mock()
        disclosure = Mock()
        disclosure.completion_result.return_value = {'verdict': 'WA', 'results': []}
        disclosure.stored_result.return_value = {'verdict': 'WA', 'results': []}
        backend = LocalJobs(self.observations, active, update, prune, lambda: 'finished')
        await JobLifecycle(backend, disclosure, None).complete(job, Completion(result={'private': 'raw'}))
        observed = self.observations['local']
        self.assertEqual(observed['status'], 'done')
        self.assertNotIn('source', observed)
        self.assertNotIn('payload', observed)
        self.assertNotIn('private', str(observed['result']))
        self.assertEqual(active, {})
        self.assertEqual(update.call_args.args[1]['source'], '')
        prune.assert_called_once()


if __name__ == '__main__':
    unittest.main()
