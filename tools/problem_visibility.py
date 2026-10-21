#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Mark a problem as contest-only (kept out of the public Task list) or public.

Contest problems are normal problem folders (statement.md/pdf + tests + a ref
solution). What changes is visibility:

    python3 tools/problem_visibility.py --id my_cup_a --hidden     # contest set
    python3 tools/problem_visibility.py --id my_cup_a --public     # back in Tasks
    python3 tools/problem_visibility.py --list                     # show what is hidden

`hidden: true` in problems/<id>/config.json is permanent (the problem is only
reachable from contest pages and the admin panel). Alternatively leave a problem
public and let a single contest hide it: the admin contest form has
"ซ่อนโจทย์ชุดนี้จากหน้า Task" (contests.hide_from_tasks), which applies to every
problem listed in that contest.

After changing visibility, run the validator and restart the server (problems are
loaded at boot):
    python3 tools/validate_problem.py <id>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import grader  # noqa: E402


def _write(pdir: Path, hidden: bool) -> None:
    cfg_path = pdir / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    if hidden:
        cfg["hidden"] = True
    else:
        cfg.pop("hidden", None)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    print(f"{pdir.name}: {'hidden (contest-only)' if hidden else 'public (shows in Tasks)'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Set problem visibility (contest-only or public)")
    ap.add_argument("--id", help="problem id (folder under problems/)")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--hidden", action="store_true", help="hide from the public Task list")
    group.add_argument("--public", action="store_true", help="show in the public Task list")
    group.add_argument("--list", action="store_true", help="list hidden problems")
    args = ap.parse_args(argv)

    if args.list:
        rows = []
        for pdir in sorted(grader.PROBLEMS_DIR.iterdir()):
            if not pdir.is_dir():
                continue
            try:
                p = grader.load_problem(pdir.name)
            except SystemExit:
                continue
            if p.hidden:
                rows.append(f"{p.pid:<24}{p.title}  ({len(p.tests)} tests, {len(p.samples)} public)")
        print("\n".join(rows) if rows else "ไม่มีโจทย์ที่ซ่อนอยู่ (ทุกข้อขึ้นในหน้า Task)")
        return 0

    if not args.id:
        ap.error("give --id or --list")
    pdir = grader.PROBLEMS_DIR / args.id
    if not pdir.is_dir():
        ap.error(f"problem folder not found: {pdir}")
    if not (args.hidden or args.public):
        ap.error("choose --hidden or --public")

    _write(pdir, bool(args.hidden))
    if args.hidden:
        print("next: python3 tools/validate_problem.py " + args.id)
        print("      then pick it in the contest form (Settings -> admin) and restart the server")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
