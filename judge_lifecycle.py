"""Owned judging attempts, supervised execution and fenced completion.

Status observations are never the authority for an attempt's ownership. The
caller holds its host slot around run(), including cancellation and cleanup.
Admission, problem preparation and submission policy use their existing modules.
"""
import asyncio
import copy
from dataclasses import dataclass
import time


@dataclass
class Completion:
    result: dict | None = None
    stored: dict | None = None
    error: str = ''
    submission: dict | None = None


@dataclass(frozen=True)
class _Ownership:
    job_id: str
    worker_id: str | None
    attempt: int | None

    @classmethod
    def capture(cls, job):
        return cls(job['id'], job.get('worker_id'), job.get('attempt'))


class DatabaseJobs:
    def __init__(self, rpc, observations, changed, *, heartbeat_seconds, lease_seconds):
        self._rpc = rpc
        self._observations = observations
        self._changed = changed
        self._heartbeat_seconds = heartbeat_seconds
        self._lease_seconds = lease_seconds

    async def watch(self, ownership):
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            valid = await self._rpc('heartbeat', p_id=ownership.job_id,
                                    p_worker=ownership.worker_id, p_attempt=ownership.attempt,
                                    p_lease_seconds=self._lease_seconds)
            if not valid:
                raise RuntimeError('judge ownership lost')

    async def finish(self, ownership, job, completion):
        response = await self._rpc('finish', p_id=ownership.job_id,
                                   p_worker=ownership.worker_id, p_attempt=ownership.attempt,
                                   p_error=completion.error,
                                   p_result=completion.stored if completion.stored is not None else completion.result,
                                   p_submission=completion.submission)
        if response.get('applied'):
            self._changed()
        self._observations.pop(ownership.job_id, None)


class LocalJobs:
    watch = None

    def __init__(self, observations, active_jobs, update, prune, clock):
        self._observations = observations
        self._active_jobs = active_jobs
        self._update = update
        self._prune = prune
        self._clock = clock

    async def finish(self, ownership, job, completion):
        job = dict(job)
        job['status'] = 'error' if completion.error else 'done'
        job['error'] = completion.error
        if completion.result is not None:
            job['result'] = completion.result if job.get('kind') == 'playground' else (
                completion.stored if completion.stored is not None else completion.result)
        job['finished_at'] = self._clock()
        job.setdefault('created_monotonic', time.monotonic())
        job.pop('source', None)
        job.pop('payload', None)
        self._observations[ownership.job_id] = job
        email = job.get('user_email') or ''
        if email in self._active_jobs:
            self._active_jobs[email].discard(ownership.job_id)
            if not self._active_jobs[email]:
                self._active_jobs.pop(email, None)
        await self._update(ownership.job_id, {
            'status': job['status'], 'error': completion.error,
            'finished_at': job['finished_at'], 'source': '',
            'result': completion.stored if completion.stored is not None else completion.result})
        self._prune()


class JobLifecycle:
    def __init__(self, backend, disclosure, runner):
        self._backend = backend
        self._disclosure = disclosure
        self._runner = runner

    async def run(self, claimed, work):
        """Prepare and judge an owned copy, then complete with its claim fence.

        work(job, execute) returns Completion. execute supervises the existing
        isolated runner and heartbeat; its return guarantees descendant cleanup.
        Neither status readers nor work can replace the captured claim fence.
        """
        job = copy.deepcopy(claimed)
        ownership = _Ownership.capture(job)

        async def execute(operation, payload, timeout):
            return await self._execute(ownership, operation, payload, timeout)

        completion = await work(job, execute)
        await self._complete(ownership, job, completion)

    async def complete(self, job, completion):
        """Complete a trusted owned snapshot, e.g. a local worker failure."""
        job = copy.deepcopy(job)
        await self._complete(_Ownership.capture(job), job, completion)

    async def _execute(self, ownership, operation, payload, timeout):
        execution = asyncio.create_task(self._runner(operation, payload, timeout))
        heartbeat = asyncio.create_task(self._backend.watch(ownership)) if self._backend.watch else None
        try:
            if heartbeat:
                done, _ = await asyncio.wait((execution, heartbeat), return_when=asyncio.FIRST_COMPLETED)
                if heartbeat in done:
                    await heartbeat
            return await execution
        finally:
            execution.cancel()
            if heartbeat:
                heartbeat.cancel()
            await asyncio.gather(execution, *([heartbeat] if heartbeat else []), return_exceptions=True)

    async def _complete(self, ownership, job, completion):
        result, stored = completion.result, completion.stored
        if job.get('kind') != 'playground':
            if result is not None:
                result = self._disclosure.completion_result(job, result)
            if stored is not None or result is not None:
                stored = self._disclosure.stored_result(job, stored if stored is not None else result)
        await self._backend.finish(ownership, job, Completion(
            result=result, stored=stored, error=completion.error, submission=completion.submission))
