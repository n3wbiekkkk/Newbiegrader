"""Minimal in-memory stand-in for the Supabase client used by server.py.

Enough of the PostgREST query builder to run the API end-to-end without a
database: select/insert/update/delete/upsert + eq/in_/order/limit, plus the two
aggregate views (leaderboard_scores, problem_stats). Not a general client.
"""
from __future__ import annotations

import copy
import datetime as dt
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
        self._order = None
        self._limit = None
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
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
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
        rows = self._rows()
        if self._op == "select":
            out = [copy.deepcopy(r) for r in rows if self._match(r)]
            if self._order:
                col, desc = self._order
                out.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=bool(desc))
            total = len(out)
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
            key = self._on_conflict or "id"
            for i, existing in enumerate(rows):
                if existing.get(key) == row.get(key):
                    merged = {**existing, **row}
                    rows[i] = merged
                    return _Resp([copy.deepcopy(merged)])
            row.setdefault("created_at", dt.datetime.now(dt.timezone.utc).isoformat())
            rows.append(row)
            return _Resp([copy.deepcopy(row)])
        if self._op == "update":
            touched = []
            for row in rows:
                if self._match(row):
                    row.update(self._payload)
                    touched.append(copy.deepcopy(row))
            return _Resp(touched)
        if self._op == "delete":
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
                 views: bool = True):
        self.tables: dict = {}
        self.columns = columns or {}
        self.missing = missing or set()
        self.views = views

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

    def rpc(self, name, params=None):  # not used by the API surface we test
        raise AssertionError(f"unexpected rpc {name}")

    # --- views ---
    def leaderboard_scores(self):
        if not self.views:
            raise Exception('relation "public.leaderboard_scores" does not exist')
        agg: dict = {}
        for r in self.tables.get("submissions", []):
            email = r.get("user_email") or ""
            if not email:
                continue
            key = (email, r.get("problem") or "")
            cur = agg.setdefault(key, {"user_email": email, "problem": key[1],
                                       "best": 0, "accepted": False, "last_at": ""})
            cur["best"] = max(cur["best"], r.get("score") or 0)
            cur["accepted"] = cur["accepted"] or bool(r.get("accepted"))
            cur["last_at"] = max(cur["last_at"], str(r.get("created_at") or ""))
        return list(agg.values())

    def problem_stats(self):
        if not self.views:
            raise Exception('relation "public.problem_stats" does not exist')
        agg: dict = {}
        for r in self.tables.get("submissions", []):
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
