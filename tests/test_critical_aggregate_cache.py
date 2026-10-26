"""Synthetic slow reads: concurrent callers, cancellation, invalidation/errors."""
import asyncio
from contextlib import ExitStack
import threading
import unittest
from unittest.mock import patch

from critical_helpers import test_server

server = test_server()


class AggregateCache(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in (('_cache', {}), ('_cache_inflight', {}), ('_cache_generation', 0)):
            self.stack.enter_context(patch.object(server, name, value))

    def slow_builder(self, result=None, error=None):
        loop = asyncio.get_running_loop()
        started, release = asyncio.Event(), threading.Event()
        self.addCleanup(release.set)
        calls = []

        def build():
            calls.append(1)
            loop.call_soon_threadsafe(started.set)
            if not release.wait(3):
                raise RuntimeError('synthetic read did not release')
            if error:
                raise error
            return result
        return build, started, release, calls

    async def test_concurrent_cold_stats_share_one_database_read(self):
        build, started, release, calls = self.slow_builder({'subs': 7})
        tasks = [asyncio.create_task(server._acached('stats', 30, build)) for _ in range(32)]
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(*tasks)
        self.assertEqual(results, [{'subs': 7}] * 32)
        self.assertEqual(len(calls), 1)
        self.assertEqual(await server._acached('stats', 30, build), {'subs': 7})
        self.assertEqual(len(calls), 1)
        self.assertEqual(server._cache_inflight, {})

    async def test_disconnected_waiter_does_not_cancel_shared_read(self):
        build, started, release, calls = self.slow_builder({'subs': 9})
        first = asyncio.create_task(server._acached('stats', 30, build))
        second = asyncio.create_task(server._acached('stats', 30, build))
        await asyncio.wait_for(started.wait(), 1)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        release.set()
        self.assertEqual(await second, {'subs': 9})
        self.assertEqual(len(calls), 1)
        self.assertEqual(server._cache_inflight, {})

    async def test_invalidated_read_cannot_overwrite_new_stats(self):
        build, started, release, _ = self.slow_builder({'subs': 1})
        old = asyncio.create_task(server._acached('stats', 30, build))
        await asyncio.wait_for(started.wait(), 1)
        server._bust_cache()
        self.assertEqual(await server._acached('stats', 30, lambda: {'subs': 2}), {'subs': 2})
        release.set()
        self.assertEqual(await old, {'subs': 1})
        self.assertEqual(server._cache['stats'][1], {'subs': 2})
        self.assertEqual(server._cache_inflight, {})

    async def test_shared_failure_is_not_cached_and_next_read_retries(self):
        build, started, release, calls = self.slow_builder(error=RuntimeError('synthetic outage'))
        tasks = [asyncio.create_task(server._acached('stats', 30, build)) for _ in range(8)]
        await asyncio.wait_for(started.wait(), 1)
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        self.assertTrue(all(isinstance(result, RuntimeError) for result in results))
        self.assertEqual(len(calls), 1)
        self.assertNotIn('stats', server._cache)
        self.assertEqual(server._cache_inflight, {})
        self.assertEqual(await server._acached('stats', 30, lambda: {'subs': 3}), {'subs': 3})

    async def test_expired_stats_refresh_once(self):
        server._cache['stats'] = (-1000, {'subs': 0})
        self.assertEqual(await server._acached('stats', 30, lambda: {'subs': 4}), {'subs': 4})


class QueueHintSharing(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in (('_cache', {}), ('_cache_inflight', {}),
                            ('_cache_generation', 0), ('QUEUE_MODE', 'database')):
            self.stack.enter_context(patch.object(server, name, value))

    async def test_64_concurrent_hints_share_read_but_next_request_is_fresh(self):
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def diagnostics(name):
            calls.append(name)
            started.set()
            await release.wait()
            return {'queued': 16 + len(calls)}

        with patch.object(server, '_queue_rpc', side_effect=diagnostics):
            tasks = [asyncio.create_task(server._queue_position_hint()) for _ in range(64)]
            await asyncio.wait_for(started.wait(), 1)
            await asyncio.sleep(0)
            release.set()
            self.assertEqual(await asyncio.gather(*tasks), [17] * 64)
            self.assertEqual(calls, ['diagnostics'])
            self.assertEqual(await server._queue_position_hint(), 18)
        self.assertEqual(calls, ['diagnostics', 'diagnostics'])
        self.assertFalse(server._cache_inflight)

    async def test_shared_outage_returns_unknown_without_replay_and_next_read_recovers(self):
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def diagnostics(name):
            calls.append(name)
            if len(calls) == 1:
                started.set()
                await release.wait()
                raise server.HTTPException(503, 'synthetic database outage')
            return {'queued': 9}

        with patch.object(server, '_queue_rpc', side_effect=diagnostics):
            tasks = [asyncio.create_task(server._queue_position_hint()) for _ in range(8)]
            await asyncio.wait_for(started.wait(), 1)
            await asyncio.sleep(0)
            release.set()
            self.assertEqual(await asyncio.gather(*tasks), [None] * 8)
            self.assertEqual(calls, ['diagnostics'])
            self.assertNotIn('queue_position_hint', server._cache)
            self.assertEqual(await server._queue_position_hint(), 9)
        self.assertEqual(len(calls), 2)

    async def test_disconnected_hint_waiter_does_not_cancel_shared_read(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def diagnostics(_name):
            started.set()
            await release.wait()
            return {'queued': 3}

        with patch.object(server, '_queue_rpc', side_effect=diagnostics) as rpc:
            first = asyncio.create_task(server._queue_position_hint())
            second = asyncio.create_task(server._queue_position_hint())
            await asyncio.wait_for(started.wait(), 1)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            release.set()
            self.assertEqual(await second, 3)
            self.assertEqual(rpc.call_count, 1)
        self.assertFalse(server._cache_inflight)

    async def test_local_hint_keeps_local_queue_path(self):
        with patch.object(server, 'QUEUE_MODE', 'local'), \
                patch.object(server, '_queue_depth_cached', return_value=4), \
                patch.object(server, '_queue_rpc') as rpc:
            self.assertEqual(await server._queue_position_hint(), 4)
            rpc.assert_not_called()


if __name__ == '__main__':
    unittest.main()
