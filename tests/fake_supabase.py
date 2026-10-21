# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Minimal in-memory stand-in for the Supabase client used by server.py.

Enough of the PostgREST query builder to run the API end-to-end without a
database: select/insert/update/delete/upsert + eq/in_/order/limit, plus the two
aggregate views (leaderboard_scores, problem_stats). Not a general client.
"""
from __future__ import annotations

import copy
import datetime as dt
import threading
import uuid


class _Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self._op = "select"
        self._payload = None
        self._filters = []
        self._order = []
        self._limit = None
        self._offset = 0
        self._count = None

    # --- builder ---
    def select(self, cols="*", count=None):
        self._op = "select"
        self._cols = cols
        self._count = count
        return self

    def insert(self, row):
        self._op = "insert"
        self._payload = row
        return self

    def update(self, patch):
        self._op = "update"
        self._payload = patch
        return self

    def upsert(self, row, on_conflict=None):
        self._op = "upsert"
        self._payload = row
        self._on_conflict = on_conflict
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, set(vals)))
        return self

    def order(self, col, desc=False):
        self._order.append((col, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._offset = start
        self._limit = end - start + 1
        return self

    # --- execution ---
    def _rows(self):
        if self.table == "leaderboard_scores":
            return self.db.leaderboard_scores()
        if self.table == "problem_stats":
            return self.db.problem_stats()
        return self.db.tables.setdefault(self.table, [])

    def _match(self, row):
        for op, col, val in self._filters:
            got = row.get(col)
            if op == "eq" and got != val:
                return False
            if op == "in" and got not in val:
                return False
        return True

    def execute(self):
        with self.db.lock:
            return self._execute()

    def _execute(self):
        rows = self._rows()
        if self._op == "select":
            if self.table in ("leaderboard_scores", "problem_stats"):
                self.db.check_view_columns(self.table, getattr(self, "_cols", "*"))
            out = [copy.deepcopy(r) for r in rows if self._match(r)]
            for col, desc in reversed(self._order):
                out.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=bool(desc))
            total = len(out)
            out = out[self._offset:]
            if self._limit:
                out = out[: self._limit]
            return _Resp(out, count=(total if self._count else None))
        if self._op == "insert":
            row = dict(self._payload)
            self.db.check_columns(self.table, row)
            row.setdefault("id", str(uuid.uuid4()))
            row.setdefault("created_at", dt.datetime.now(dt.timezone.utc).isoformat())
            rows.append(row)
            return _Resp([copy.deepcopy(row)])
        if self._op == "upsert":
            row = dict(self._payload)
            self.db.check_columns(self.table, row)
            keys = [k.strip() for k in str(self._on_conflict or "id").split(",")]
            for i, existing in enumerate(rows):
                if all(existing.get(k) == row.get(k) for k in keys):
                    merged = {**existing, **row}
                    rows[i] = merged
                    return _Resp([copy.deepcopy(merged)])
            row.setdefault("created_at", dt.datetime.now(dt.timezone.utc).isoformat())
            rows.append(row)
            return _Resp([copy.deepcopy(row)])
        if self._op == "update":
            self.db.check_columns(self.table, self._payload.keys())
            touched = []
            for row in rows:
                if self._match(row):
                    row.update(self._payload)
                    touched.append(copy.deepcopy(row))
            return _Resp(touched)
        if self._op == "delete":
            self.db.check_columns(self.table, {f[1]: True for f in self._filters})
            keep = [r for r in rows if not self._match(r)]
            gone = len(rows) - len(keep)
            rows[:] = keep
            return _Resp([])
        raise AssertionError(f"unsupported op {self._op}")


class FakeSupabase:
    """`create_client()` replacement: `client.table("submissions")...`.

    `columns` (optional): per-table whitelist — writing a key outside it raises,
    like a real Postgres table rejecting an unknown column (use this to simulate a
    database that has not run the latest schema migration).
    `missing` (optional): tables that raise on every access (missing relation).
    `views` (optional): set False to make the aggregate views raise too.
    """

    def __init__(self, columns: dict | None = None, missing: set | None = None,
                 views: bool = True, view_columns: set | None = None,
                 storage_fail: set | None = None):
        self.tables: dict = {}
        self.lock = threading.RLock()
        self.columns = columns or {}
        self.missing = missing or set()
        self.views = views
        # Columns the aggregate views expose (prod had a leaderboard_scores
        # without `name` for a while, so tests need to ask for a missing one).
        self.view_columns = view_columns or {"user_email", "problem", "best",
                                            "accepted", "last_at", "name"}
        # Storage: bucket -> {path -> bytes}. Private bucket, no public URLs.
        self.buckets: dict = {}
        # Paths that raise on download (simulate storage outage / missing asset).
        self.storage_fail: set = set(storage_fail or set())
        self.storage = _FakeStorage(self)
        # Supabase client attributes used by problem_store._download()
        self.supabase_url = "http://localhost:54321"
        self.supabase_key = "fake-key-for-testing"

    def check_view_columns(self, table: str, cols: object) -> None:
        if not isinstance(cols, str) or cols.strip() in ("", "*"):
            return
        missing = [c.strip() for c in cols.split(",")
                   if c.strip() and c.strip() not in self.view_columns]
        if missing:
            raise Exception(f'column "{missing[0]}" does not exist')

    def table(self, name):
        if name in self.missing:
            raise Exception(f'relation "public.{name}" does not exist')
        return _Query(self, name)

    def check_columns(self, table: str, row: dict) -> None:
        allowed = self.columns.get(table)
        if not allowed:
            return
        unknown = [k for k in row if k not in allowed]
        if unknown:
            raise Exception(f'column "{unknown[0]}" of relation "{table}" does not exist')

    def rpc(self, name, params=None):
        if name.startswith("auth_"):
            return _AuthRPC(self, name, params or {})
        return _QueueRPC(self, name, params or {})

    # --- views ---
    def leaderboard_scores(self):
        if not self.views:
            raise Exception('relation "public.leaderboard_scores" does not exist')
        agg: dict = {}
        newest: dict = {}
        for r in self.tables.get("submissions", []):
            email = r.get("user_email") or ""
            if not email or r.get("contest_id"):
                continue     # contest scores live in the contest board only
            key = (email, r.get("problem") or "")
            cur = agg.setdefault(key, {"user_email": email, "problem": key[1],
                                       "best": 0, "accepted": False, "last_at": "",
                                       "name": ""})
            cur["best"] = max(cur["best"], r.get("score") or 0)
            cur["accepted"] = cur["accepted"] or bool(r.get("accepted"))
            at = str(r.get("created_at") or "")
            cur["last_at"] = max(cur["last_at"], at)
            name = (r.get("name") or "").strip()
            # mirror the SQL: newest non-empty name wins
            if name and at >= newest.get(key, ""):
                newest[key] = at
                cur["name"] = name
        return list(agg.values())

    def problem_stats(self):
        if not self.views:
            raise Exception('relation "public.problem_stats" does not exist')
        agg: dict = {}
        for r in self.tables.get("submissions", []):
            if r.get("contest_id"):
                continue     # contest scores live in the contest board only
            p = agg.setdefault(r.get("problem") or "",
                               {"problem": r.get("problem") or "", "subs": 0,
                                "accepted": 0, "best": 0, "total_score": 0,
                                "solvers": set()})
            p["subs"] += 1
            if r.get("accepted"):
                p["accepted"] += 1
                if r.get("user_email"):
                    p["solvers"].add(r["user_email"])
            p["best"] = max(p["best"], r.get("score") or 0)
            p["total_score"] += r.get("score") or 0
        for p in agg.values():
            p["solvers"] = len(p["solvers"])
        return list(agg.values())

    # --- test helpers ---
    def rows(self, table):
        return self.tables.setdefault(table, [])


class _AuthRPC:
    """Synthetic transaction model; also verify the real SQL in auth_sql.sql."""
    def __init__(self, db, name, params):
        self.db, self.name, self.params = db, name, params

    def execute(self):
        with self.db.lock:
            return _Resp(copy.deepcopy(self._execute()))

    def _execute(self):
        p = self.params
        if self.name == "auth_email_budget":
            now = dt.datetime.now(dt.timezone.utc).timestamp()
            email, network = p["p_email_key"], p["p_network_key"]
            limits = ([("send:global", 100, 86400), ("send:network:" + network, 50, 3600),
                       ("send:hour:" + email, 5, 3600), ("send:minute:" + email, 1, 60)]
                      if p["p_action"] == "request" else
                      [("verify:global", 1000, 3600), ("verify:network:" + network, 100, 900),
                       ("verify:email:" + email, 8, 900)])
            rows = self.db.rows("auth_rate_buckets")
            rows[:] = [r for r in rows if r["expires_at"] > now]
            for key, limit, seconds in limits:
                row = next((r for r in rows if r["bucket"] == key), None)
                if row and row["attempts"] >= limit:
                    return {"allowed": False, "retry_after": max(1, int(row["expires_at"] - now) + 1)}
            for key, limit, seconds in limits:
                row = next((r for r in rows if r["bucket"] == key), None)
                if row:
                    row["attempts"] += 1
                else:
                    rows.append({"bucket": key, "attempts": 1, "expires_at": now + seconds})
            return {"allowed": True}
        self.db.table("users")
        email = p["p_email"]
        row = next((r for r in self.db.rows("users") if r["email"] == email), None)
        if self.name == "auth_google_identity" and row and row.get("email_verified_at"):
            if row.get("google_subject") != p["p_subject"]:
                return {"link_required": True}
            return {k: row[k] for k in ("email", "name", "auth_version")}
        if self.name == "auth_email_complete" and row and row.get("email_auth_subject") \
                and row["email_auth_subject"] != p["p_subject"]:
            raise ValueError("identity subject mismatch")
        if not row:
            row = {"email": email, "auth_version": 0}
            self.db.rows("users").append(row)
        row.update({"auth_version": row.get("auth_version", 0) + 1,
                    "name": p["p_name"], "email_verified_at": dt.datetime.now(dt.timezone.utc).isoformat()})
        if self.name == "auth_google_identity":
            row.update({"password_hash": "", "google_subject": p["p_subject"]})
        elif self.name == "auth_email_complete":
            row.update({"password_hash": p["p_password_hash"], "email_auth_subject": p["p_subject"]})
        else:
            raise AssertionError(self.name)
        return {k: row[k] for k in ("email", "name", "auth_version")}


class _FakeStorage:
    """Minimal stand-in for supabase storage (private bucket, no public URLs)."""

    def __init__(self, db: "FakeSupabase"):
        self.db = db

    def from_(self, bucket: str) -> "_FakeBucket":
        return _FakeBucket(self.db, bucket)


class _FakeBucket:
    def __init__(self, db: "FakeSupabase", bucket: str):
        self.db = db
        self.bucket = bucket

    def _store(self) -> dict:
        return self.db.buckets.setdefault(self.bucket, {})

    def upload(self, path: str, data, options=None):
        if isinstance(data, str):
            data = data.encode("utf-8")
        elif hasattr(data, "read"):
            data = data.read()
        data = bytes(data)
        with self.db.lock:
            self._store()[path] = data
        return {"path": path}

    def update(self, path: str, data, options=None):
        return self.upload(path, data, options)

    def download(self, path: str) -> bytes:
        with self.db.lock:
            if path in self.db.storage_fail or (self.bucket, path) in self.db.storage_fail:
                raise Exception(f"storage unavailable for {path!r}")
            store = self._store()
            if path not in store:
                raise Exception(f"object not found: {path!r}")
            return bytes(store[path])

    def list(self, prefix: str = "") -> list:
        with self.db.lock:
            return [{"name": p} for p in sorted(self._store()) if p.startswith(prefix)]

    def remove(self, paths: list) -> list:
        with self.db.lock:
            store = self._store()
            for p in paths:
                store.pop(p, None)
        return []


class _QueueRPC:
    """Transactional stand-in for schema.sql RPCs, including ownership fencing."""
    def __init__(self, db, name, params):
        self.db, self.name, self.params = db, name, params

    def execute(self):
        with self.db.lock:
            self.db.table("judge_jobs")  # model missing migration/database outage
            return _Resp(copy.deepcopy(self._execute()))

    def _execute(self):
        p = self.params
        rows = self.db.rows("judge_jobs")
        now = dt.datetime.now(dt.timezone.utc)
        def at(value):
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
        if self.name == "judge_queue_diagnostics":
            return {status: sum(r.get("status") == status for r in rows)
                    for status in ("queued", "running")}
        if self.name == "judge_queue_admit":
            row = copy.deepcopy(p["p_job"])
            email = row.get("user_email") or ""
            if p["p_track_active"] and email and any(
                    r.get("user_email") == email and r.get("track_active", True)
                    and r.get("status") in ("queued", "running") for r in rows):
                return {"error": "you already have a submission judging, please wait", "status_code": 409}
            if sum(r.get("status") == "queued" for r in rows) >= p["p_queue_max"]:
                return {"error": "judge queue is full — try again in a moment", "status_code": 503, "retry_after": 30}
            limit, window = p.get("p_quota_limit", 0), p.get("p_quota_window", 0)
            kind = "run" if row.get("kind") == "playground" else "submit"
            events = self.db.rows("judge_quota_events")
            if limit > 0 and window > 0 and email:
                events[:] = [e for e in events if at(e["admitted_at"]) > now-dt.timedelta(days=7)]
                hits = [e for e in events if e["user_email"] == email and e["kind"] == kind
                        and at(e["admitted_at"]) > now-dt.timedelta(seconds=window)]
                if len(hits) >= limit:
                    retry = max(1, int((at(hits[0]["admitted_at"])+dt.timedelta(seconds=window)-now).total_seconds())+1)
                    return {"error": "quota exceeded", "status_code": 429, "retry_after": retry}
                events.append({"user_email": email, "kind": kind, "admitted_at": now.isoformat()})
            defaults = {"id": str(uuid.uuid4()), "status": "queued", "created_at": now.isoformat(),
                        "result": None, "error": "", "attempt": 0, "payload": {},
                        "track_active": p["p_track_active"], "worker_id": None, "lease_until": None,
                        "submission_id": None}
            defaults.update(row)
            rows.append(defaults)
            return {"job": defaults}
        if self.name == "judge_queue_claim":
            for row in rows:
                if row.get("status") == "queued" and at(row["created_at"]) < now-dt.timedelta(hours=24):
                    row.update(status="error", error="stale job dropped", finished_at=now.isoformat())
            candidates = [r for r in rows if r.get("status") == "queued" or
                          (r.get("status") == "running" and r.get("lease_until") and at(r["lease_until"]) <= now)]
            if not candidates:
                return None
            row = min(candidates, key=lambda r: (r.get("kind") == "rejudge", r["created_at"], r["id"]))
            row.update(status="running", worker_id=p["p_worker"], attempt=row.get("attempt", 0)+1,
                       started_at=now.isoformat(), error="", finished_at=None,
                       lease_until=(now+dt.timedelta(seconds=max(1,p["p_lease_seconds"]))).isoformat())
            return row
        row = next((r for r in rows if r["id"] == p.get("p_id")), None)
        owner = row and row.get("worker_id") == p.get("p_worker") and row.get("attempt") == p.get("p_attempt")
        valid = owner and row.get("status") == "running" and row.get("lease_until") and at(row["lease_until"]) > now
        if self.name == "judge_queue_heartbeat":
            if valid:
                row["lease_until"] = (now+dt.timedelta(seconds=max(1,p["p_lease_seconds"]))).isoformat()
            return bool(valid)
        if self.name == "judge_queue_finish":
            if owner and row.get("status") in ("done", "error"):
                return {"applied": True, "submission_id": row.get("submission_id")}
            if not valid:
                return {"applied": False}
            sid = None
            submission = p.get("p_submission")
            if submission is not None and not p.get("p_error"):
                submission = {**submission, "job_id": row["id"]}
                if row.get("target_id"):
                    res = self.db.table("submissions").update(submission).eq("id",row["target_id"]).execute()
                else:
                    res = self.db.table("submissions").insert(submission).execute()
                sid = res.data[0]["id"] if res.data else None
            result = p.get("p_result")
            row.update(status="error" if p.get("p_error") else "done", error=p.get("p_error") or "",
                       result={**result, "id": sid} if result is not None else None,
                       finished_at=now.isoformat(), lease_until=None, submission_id=sid)
            return {"applied": True, "submission_id": sid}
        raise AssertionError(f"unexpected rpc {self.name}")
