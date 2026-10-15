#!/usr/bin/env python3
"""Manage the numeric problem ids (problems/<id>/config.json -> "no").

The number is data, not order: it lives in the problem folder so it survives
renames, works offline (CLI/validator) and stays the same on every machine. The
website sorts and searches by it, and `#/task/<no>` opens the problem by number.

    python3 tools/number_problems.py --list                  # ตารางเลขโจทย์ทั้งหมด
    python3 tools/number_problems.py --assign                # ให้เลขกับข้อที่ยังไม่มี (ต่อท้าย)
    python3 tools/number_problems.py --set --id hanoi --no 12
    python3 tools/number_problems.py --check                 # ตรวจซ้ำ/ผิดรูปแบบ

Numbering rules:
  * public 1..P ต่อเนื่อง (ไม่มี gap), hidden 1001.. ต่อเนื่อง — สองช่วงห้ามปนกัน
  * hidden = ข้อคอนเทสต์ (`hidden: true`) เท่านั้น เริ่ม 1001 เสมอ
  * ห้าม 0 (0 = ยังไม่กำหนด)
  * `--assign` ต่อเลขในblockของตัวเอง (public ต่อท้าย public, hidden ต่อท้าย hidden)
  * `--set` ใช้เมื่ออยากย้ายข้อไปอยู่เลขที่ต้องการ (เลขที่ว่างเท่านั้น เว้นแต่ --force)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import grader  # noqa: E402


def load_all() -> list:
    probs = []
    for pdir in sorted(grader.PROBLEMS_DIR.iterdir()):
        if not pdir.is_dir():
            continue
        try:
            probs.append(grader.load_problem(pdir.name))
        except SystemExit:
            continue
    return probs


def set_no(pid: str, no: int) -> None:
    path = grader.PROBLEMS_DIR / pid / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if no > 0:
        cfg["no"] = no
    else:
        cfg.pop("no", None)
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


def cmd_list(probs: list) -> int:
    print(f"{'NO':>4}  {'ID':<24}{'TITLE':<42}{'LEVEL':<8}{'TESTS':>5}  VIS")
    print("-" * 100)
    for p in grader.sort_problems(probs):
        no = str(p.no) if p.no else "—"
        level = p.difficulty or "—"
        vis = "hidden" if p.hidden else "public"
        print(f"{no:>4}  {p.pid:<24}{p.title[:40]:<42}{level:<8}{len(p.tests):>5}  {vis}")
    numbered = [p for p in probs if p.no > 0]
    print(f"\n{len(numbered)}/{len(probs)} ข้อมีเลข · ว่าง: "
          f"{', '.join(p.pid for p in grader.sort_problems(probs) if not p.no) or 'ไม่มี'}")
    return 0


HIDDEN_BASE = 1001  # contest-only problems live here, never mixed with public


def cmd_check(probs: list) -> int:
    seen: dict = {}
    dupes, missing = [], []
    for p in probs:
        if p.no <= 0:
            missing.append(p.pid)
            continue
        if p.no in seen:
            dupes.append((p.no, seen[p.no], p.pid))
        else:
            seen[p.no] = p.pid
    for no, a, b in sorted(dupes):
        print(f"FAIL เลข {no} ถูกใช้ซ้ำ: {a} และ {b}")
    if missing:
        print(f"WARN ยังไม่มีเลข {len(missing)} ข้อ: {', '.join(sorted(missing))}")
    if dupes:
        return 1
    pub = sorted(n for n in seen if n < HIDDEN_BASE)
    hid = sorted(n for n in seen if n >= HIDDEN_BASE)
    bad = False
    if pub != list(range(1, len(pub) + 1)):
        print(f"FAIL public ไม่ต่อเนื่อง 1..{len(pub)}: มี {pub[:8]}{'...' if len(pub) > 8 else ''}")
        bad = True
    if hid != list(range(HIDDEN_BASE, HIDDEN_BASE + len(hid))):
        print(f"FAIL hidden ไม่ต่อเนื่อง {HIDDEN_BASE}..: มี {hid}")
        bad = True
    cross = [p.pid for p in probs
             if (p.hidden and 0 < p.no < HIDDEN_BASE) or (not p.hidden and p.no >= HIDDEN_BASE)]
    if cross:
        print(f"FAIL ข้อ public/hidden อยู่ผิดช่วง: {', '.join(sorted(cross))}")
        bad = True
    if not bad:
        print(f"OK  public 1..{len(pub)} + hidden {HIDDEN_BASE}..{HIDDEN_BASE + len(hid) - 1} "
              f"({len(seen)} เลขไม่ซ้ำ)" if hid else
              f"OK  {len(seen)} เลขไม่ซ้ำ (1..{len(pub)}) · ต่อเนื่องครบ")
    return 1 if bad else 0


def assign_order(probs: list) -> list:
    """Canonical order for assigning numbers: public first (easy -> medium ->
    hard, then id), contest-only (hidden) problems last so students never see
    gaps in the list they are looking at."""
    return sorted(probs, key=lambda p: (1 if p.hidden else 0,
                                        grader.DIFFICULTY_RANK.get(
                                            (p.difficulty or "").lower(), 9),
                                        p.pid))


def cmd_assign(probs: list, renumber: bool = False) -> int:
    if renumber:
        for p in probs:
            set_no(p.pid, 0)
            p.no = 0
        print(f"ล้างเลขเดิมของ {len(probs)} ข้อ แล้วเริ่มให้ใหม่ตามลำดับ "
              "(public easy→medium→hard, ข้อคอนเทสต์ต่อท้าย)")
    used = {p.no for p in probs if p.no > 0}
    todo = [p for p in assign_order(probs) if not p.no]
    if not todo:
        print("ทุกข้อมีเลขแล้ว")
        return 0
    # public and hidden draw from separate blocks so the ranges never mix
    nxt_pub = max([n for n in used if n < HIDDEN_BASE] or [0]) + 1
    nxt_hid = max([n for n in used if n >= HIDDEN_BASE] or [HIDDEN_BASE - 1]) + 1
    for p in todo:
        if p.hidden:
            while nxt_hid in used:
                nxt_hid += 1
            set_no(p.pid, nxt_hid)
            print(f"{p.pid:<24} -> เลข {nxt_hid}  ({p.difficulty or '—'}, contest-only)")
            used.add(nxt_hid)
            nxt_hid += 1
        else:
            while nxt_pub in used:
                nxt_pub += 1
            set_no(p.pid, nxt_pub)
            print(f"{p.pid:<24} -> เลข {nxt_pub}  ({p.difficulty or '—'})")
            used.add(nxt_pub)
            nxt_pub += 1
    print(f"\nให้เลข {len(todo)} ข้อ — รัน `python3 tools/number_problems.py --check` แล้ว "
          "`python3 tools/validate_problem.py` ต่อ")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="จัดการเลขโจทย์ (numeric problem ids)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="ตารางเลขโจทย์ทั้งหมด")
    g.add_argument("--check", action="store_true", help="ตรวจเลขซ้ำ/ขาด")
    g.add_argument("--assign", action="store_true", help="ให้เลขกับข้อที่ยังไม่มี (ต่อท้าย)")
    g.add_argument("--renumber", action="store_true",
                   help="ล้างเลขเดิมทั้งหมดแล้วให้ใหม่ตามลำดับมาตรฐาน (public ก่อน, คอนเทสต์ท้าย)")
    g.add_argument("--set", action="store_true", help="ตั้งเลขให้ข้อหนึ่ง (ใช้กับ --id/--no)")
    ap.add_argument("--id", help="problem id (กับ --set)")
    ap.add_argument("--no", type=int, help="เลขที่ต้องการ (กับ --set, 0 = ลบเลข)")
    ap.add_argument("--force", action="store_true", help="ยอมทับเลขที่ซ้ำ")
    args = ap.parse_args(argv)

    probs = load_all()
    if args.list:
        return cmd_list(probs)
    if args.check:
        return cmd_check(probs)
    if args.assign:
        return cmd_assign(probs)
    if args.renumber:
        return cmd_assign(probs, renumber=True)

    if not args.id or args.no is None:
        ap.error("--set ต้องมี --id และ --no")
    if not (grader.PROBLEMS_DIR / args.id).is_dir():
        ap.error(f"problem folder not found: problems/{args.id}")
    if args.no < 0:
        ap.error("--no ต้อง >= 0 (0 = ลบเลข)")
    clash = [p.pid for p in probs if p.no == args.no and p.pid != args.id]
    if args.no > 0 and clash and not args.force:
        ap.error(f"เลข {args.no} ถูกใช้โดย {clash[0]} (ใส่ --force ถ้าต้องการสลับ)")
    set_no(args.id, args.no)
    print(f"{args.id}: เลข {args.no if args.no else '(ลบออก)'}")
    if args.no > 0 and not clash:
        print("next: python3 tools/validate_problem.py " + args.id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
