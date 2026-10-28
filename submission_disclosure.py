"""Submission disclosure, independent of HTTP and database transports.

The source adapter supplies current facts. This module owns audience policy,
projection and the distinction between stored feedback and live disclosure.
The credential-free executor continues to use judge_execution directly.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Callable, Protocol

from judge_execution import (
    REVEAL_ALL, REVEAL_NONE, REVEAL_PRACTICE, REVEAL_SAMPLES, _redact_results,
)


class DisclosureSource(Protocol):
    def contests(self) -> list[dict]: ...
    def peer_contests(self) -> list[dict]: ...
    def publication(self, pid: str) -> dict | None: ...
    def sample_names(self, pid: str) -> set[str]: ...
    def resolve_pid(self, token: str) -> str: ...
    def is_admin(self, email: str) -> bool: ...
    def contest(self, cid: str) -> dict: ...


class DisclosureDenied(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        self.status_code = 503 if reason == "unavailable" else 403
        super().__init__("peer inspection locked: " + reason)


class ContestUnavailable(Exception):
    """An expected missing/unreachable Contest lookup, rather than an adapter bug."""


def contest_times_valid(contest: object) -> bool:
    if not isinstance(contest, dict):
        return False
    try:
        start = dt.datetime.fromisoformat(str(contest.get("starts_at")).replace("Z", "+00:00"))
        end = dt.datetime.fromisoformat(str(contest.get("ends_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return False
    return start.tzinfo is not None and end.tzinfo is not None and end > start


def public_display_name(name: object) -> str:
    return name if isinstance(name, str) and name.strip() and "@" not in name else "นักเรียน"


_CASE_VERDICTS = frozenset({"AC", "WA", "TLE", "MLE", "OLE", "CE", "RE"})
_COMPLETED_VERDICTS = _CASE_VERDICTS | {"REJECTED"}
_PUBLIC_FIELDS = (
    "id", "created_at", "problem", "language", "name", "filename", "verdict",
    "accepted", "passed", "total", "score", "counts", "contest_id",
)


class SubmissionDisclosure:
    history_columns = ",".join(_PUBLIC_FIELDS)

    def __init__(self, source: DisclosureSource, *, clock: Callable[[], dt.datetime] | None = None):
        self.source = source
        self._now = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    def _window(self, contest: dict) -> str:
        start = dt.datetime.fromisoformat(str(contest.get("starts_at")).replace("Z", "+00:00"))
        end = dt.datetime.fromisoformat(str(contest.get("ends_at")).replace("Z", "+00:00"))
        now = self._now()
        return "upcoming" if now < start else "ended" if now > end else "running"

    def _contest_reveal(self, contest: dict | None, owner: str) -> str:
        if self.source.is_admin(owner):
            return REVEAL_ALL
        if contest is not None and not contest_times_valid(contest):
            return REVEAL_NONE
        if contest and self._window(contest) == "running" and contest.get("show_samples") is False:
            return REVEAL_NONE
        return REVEAL_SAMPLES

    def admission_reveal(self, contest: dict | None, owner: str, pid: str) -> str:
        """Choose the trusted execution snapshot; an omitted Contest is no bypass."""
        if contest is not None:
            return self._contest_reveal(contest, owner)
        protected = False
        try:
            for row in self.source.contests():
                if pid not in {self.source.resolve_pid(str(x)) for x in (row.get("problems") or [])}:
                    continue
                if not contest_times_valid(row):
                    return REVEAL_NONE
                window = self._window(row)
                if window != "ended":
                    protected = True
                    if window == "running" and row.get("show_samples") is False:
                        return REVEAL_NONE
        except Exception:
            return REVEAL_NONE
        return REVEAL_SAMPLES if protected else REVEAL_PRACTICE

    def _owner_reveal(self, row: dict) -> str:
        cid, owner, pid = row.get("contest_id"), row.get("user_email", ""), row.get("problem", "")
        if not cid:
            return self.admission_reveal(None, owner, pid)
        try:
            for contest in self.source.contests():
                if str(contest.get("id")) == str(cid):
                    return self._contest_reveal(contest, owner)
        except Exception:
            return REVEAL_NONE
        return REVEAL_NONE

    def _project_result(self, row: dict, result: dict, reveal: str) -> dict:
        if row.get("contest_id") and reveal == REVEAL_PRACTICE:
            reveal = REVEAL_SAMPLES
        samples = self.source.sample_names(row.get("problem", ""))
        raw = [{**case, "public": case.get("test") in samples and not case.get("hidden", False)}
               for case in result.get("results", [])]
        return {**result, "results": _redact_results(raw, reveal)}

    def job_result(self, job: dict) -> dict | None:
        result = job.get("result") if job.get("status", "queued") == "done" else None
        if not isinstance(result, dict):
            return None
        if job.get("kind") == "playground":
            return result
        return self._project_result(job, result, self._owner_reveal(job))

    def history_detail(self, row: dict, viewer: str) -> dict:
        owner = row.get("user_email") or ""
        if owner != viewer and not self.source.is_admin(viewer):
            access = self.peer_access(viewer, row.get("problem", ""), row.get("contest_id"))
            completed = (row.get("kind", "submit") in {"submit", "rejudge"}
                         and row.get("status", "done") == "done"
                         and row.get("verdict") in _COMPLETED_VERDICTS)
            if not access["allowed"] or not completed:
                raise DisclosureDenied(access["reason"] or "incomplete submission")
            return self._peer_detail(row)
        result = dict(row)
        result.pop("user_email", None)
        result["results"] = self._project_result(row, {"results": row.get("results", [])},
                                                  self._owner_reveal(row))["results"]
        return result

    def stored_result(self, job: dict, result: dict) -> dict:
        """Persist admission-authorized feedback, never a viewer's elevated view."""
        reveal = REVEAL_NONE if job.get("reveal") == REVEAL_NONE else REVEAL_SAMPLES
        if job.get("reveal") == REVEAL_PRACTICE and not job.get("contest_id"):
            reveal = REVEAL_PRACTICE
        return self._project_result(job, result, reveal)

    def completion_result(self, job: dict, result: dict) -> dict:
        return self._project_result(job, result, job.get("reveal") or REVEAL_SAMPLES)

    def hidden_sample_problems(self, exclude_cid: str = "") -> set[str]:
        hidden = set()
        for row in self.source.contests():
            if exclude_cid and row.get("id") == exclude_cid:
                continue
            if not contest_times_valid(row) or (self._window(row) == "running"
                                                and row.get("show_samples") is False):
                for token in row.get("problems") or []:
                    try:
                        hidden.add(self.source.resolve_pid(str(token)))
                    except Exception:
                        pass
        return hidden

    def problem_access_reason(self, pid: str, contest_id: str | None = None) -> str:
        """Fresh peer/solution disclosure; missing facts never grant access."""
        try:
            publication = self.source.publication(pid)
        except Exception:
            return "unavailable"
        if publication is None or not publication["is_published"]:
            return "hidden"
        try:
            rows = self.source.peer_contests()
            if not isinstance(rows, list):
                return "unavailable"
            related = []
            now = self._now()
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("problems"), list):
                    return "unavailable"
                if pid not in {self.source.resolve_pid(str(x)) for x in row["problems"]}:
                    continue
                if not contest_times_valid(row):
                    return "contest"
                end = dt.datetime.fromisoformat(str(row.get("ends_at")).replace("Z", "+00:00"))
                if now <= end:
                    return "contest"
                related.append(row)
            if contest_id and not any(row.get("id") == contest_id for row in related):
                return "contest"
            if publication["hidden"] and not related:
                return "hidden"
            return ""
        except Exception:
            return "unavailable"

    def peer_access(self, viewer: str, pid: str, contest_id: str | None = None) -> dict:
        if self.source.is_admin(viewer):
            return {"allowed": True, "reason": ""}
        if not viewer:
            return {"allowed": False, "reason": "login"}
        reason = self.problem_access_reason(pid, contest_id)
        return {"allowed": not reason, "reason": reason}

    @staticmethod
    def public_history(row: dict) -> dict:
        public = {key: row[key] for key in _PUBLIC_FIELDS if key in row
                  and (row[key] is None or isinstance(row[key], (str, int, float, bool)))}
        counts = row.get("counts")
        public["counts"] = {key: value for key, value in counts.items()
                            if key in _CASE_VERDICTS and type(value) is int and value >= 0} \
            if isinstance(counts, dict) else {}
        public["name"] = public_display_name(row.get("name"))
        return public

    def _peer_detail(self, row: dict) -> dict:
        public = self.public_history(row)
        public["code"] = row.get("code") if isinstance(row.get("code"), str) else ""
        public["peer_inspection"] = True
        public["results"] = []
        for case in row.get("results", []) if isinstance(row.get("results"), list) else []:
            if not isinstance(case, dict):
                continue
            verdict = case.get("verdict")
            safe = {"verdict": verdict if isinstance(verdict, str) and verdict in _CASE_VERDICTS else "UNKNOWN",
                    "hidden": True}
            for key in ("wall_s", "cpu_s", "peak_mb"):
                value = case.get(key)
                safe[key] = value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
            public["results"].append(safe)
        return public

    def rejudge_policy(self) -> Callable[[object, str, str], str]:
        """One rejudge batch retains its original request-local policy snapshots."""
        contests = {}
        practice = {}

        def select(cid: object, owner: str, pid: str) -> str:
            if not cid:
                if pid not in practice:
                    practice[pid] = self.admission_reveal(None, owner, pid)
                return practice[pid]
            key = str(cid)
            if key not in contests:
                try:
                    contests[key] = self.source.contest(key)
                except ContestUnavailable:
                    contests[key] = None
            contest = contests[key]
            return self._contest_reveal(contest, owner) if contest is not None else REVEAL_NONE

        return select
