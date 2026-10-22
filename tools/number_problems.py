#!/usr/bin/env python3
"""Manage the numeric problem ids (problems/<id>/config.json -> "no").

The number is data, not order: it lives in the problem folder so it survives
renames, works offline (CLI/validator) and stays the same on every machine. The
website sorts and searches by it, and `#/task/<no>` opens the problem by number.

    python3 tools/number_problems.py --list                  # ตารางเลขโจทย์ทั้งหมด
    python3 tools/number_problems.py --assign                # ให้เลขกับข้อที่ยังไม่มี (ต่อท้าย)
    python3 tools/number_problems.py --set --id hanoi --no 12
    python3 tools/number_problems.py --check                 # ตรวจซ้ำ/ผิดรูปแบบ
    python3 tools/number_problems.py --order <csv>            # ใช้แมปเลขที่อนุมัติแล้ว

Numbering rules:
  * public 1..P ต่อเนื่อง (ไม่มี gap), hidden 1001.. ต่อเนื่อง — สองช่วงห้ามปนกัน
  * hidden = ข้อคอนเทสต์ (`hidden: true`) เท่านั้น เริ่ม 1001 เสมอ
  * ห้าม 0 (0 = ยังไม่กำหนด)
  * `--assign` ต่อเลขในblockของตัวเอง (public ต่อท้าย public, hidden ต่อท้าย hidden)
  * `--set` ใช้เมื่ออยากย้ายข้อไปอยู่เลขที่ต้องการ (เลขที่ว่างเท่านั้น เว้นแต่ --force)
  * `--order <csv>` ใช้แมปที่ commit ไว้ใน docs/catalog/ (slug,old_no,new_no,level,
    difficulty,title) เป็นแหล่งจริงของการเรียงเลข — เขียน no/level/difficulty
    กลับเข้า config.json ทุกข้อในแมป

Difficulty calibration:
  * config.level = 1..5 คือความยากจริงที่ประเมินจากโจทย์ (เทคนิคที่ต้องใช้ +
    ภาระการเขียนโค้ด) ไม่ใช่แค่ความยากของเนื้อเรื่อง
  * config.difficulty = easy|medium|hard เป็นแบดจ์ 3 ระดับที่ UI ใช้
    (level 1-2 = easy, 3 = medium, 4-5 = hard) และต้องตรงกับ level เสมอ
  * เรียงเลขด้วย (level, no) — โจทย์ใหม่ที่มี level จะเข้ากลุ่มของตัวเอง
"""
from __future__ import annotations

import argparse
import csv
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


def config_path(pid: str) -> Path:
    return grader.PROBLEMS_DIR / pid / "config.json"


def read_config(pid: str) -> dict:
    path = config_path(pid)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def write_config(pid: str, cfg: dict) -> None:
    """Write config.json with the canonical key order and a trailing newline."""
    ordered: dict = {}
    for key in ("title", "time_limit", "memory_limit", "checker", "tolerance",
                "difficulty", "level", "tags", "samples", "hidden", "no"):
        if key in cfg:
            ordered[key] = cfg[key]
    for key, value in cfg.items():
        if key not in ordered:
            ordered[key] = value
    path = config_path(pid)
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def set_no(pid: str, no: int) -> None:
    cfg = read_config(pid)
    if no > 0:
        cfg["no"] = no
    else:
        cfg.pop("no", None)
    write_config(pid, cfg)


def cmd_list(probs: list) -> int:
    print(f"{'NO':>4}  {'ID':<24}{'TITLE':<42}{'LVL':<5}{'LEVEL':<8}{'TESTS':>5}  VIS")
    print("-" * 104)
    for p in grader.sort_problems(probs):
        no = str(p.no) if p.no else "—"
        level = p.difficulty or "—"
        vis = "hidden" if p.hidden else "public"
        print(f"{no:>4}  {p.pid:<24}{p.title[:40]:<42}{p.level or '—':<5}{level:<8}"
              f"{len(p.tests):>5}  {vis}")
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
    # The number must rise with the calibrated level, and the coarse badge must
    # match the level band. A drifted label is how the catalog ends up with an
    # easy problem sitting behind a hard one.
    ordered = sorted((p for p in probs if p.no > 0 and p.no < HIDDEN_BASE),
                     key=lambda p: p.no)
    levels = [p.level for p in ordered]
    if levels != sorted(levels):
        drops = [f"{ordered[i].pid}({levels[i]})->{ordered[i+1].pid}({levels[i+1]})"
                 for i in range(len(levels) - 1) if levels[i] > levels[i + 1]]
        print(f"FAIL เลขไม่เรียงตาม level: {'; '.join(drops[:6])}")
        bad = True
    drift = [f"{p.pid} (level {p.level} -> {p.difficulty})" for p in ordered
             if p.level and grader.band_for_level(p.level) != (p.difficulty or "").lower()]
    if drift:
        print(f"FAIL difficulty ไม่ตรงกับ level: {', '.join(drift[:8])}")
        bad = True
    if not bad:
        print(f"OK  public 1..{len(pub)} + hidden {HIDDEN_BASE}..{HIDDEN_BASE + len(hid) - 1} "
              f"({len(seen)} เลขไม่ซ้ำ)" if hid else
              f"OK  {len(seen)} เลขไม่ซ้ำ (1..{len(pub)}) · ต่อเนื่องครบ")
    return 1 if bad else 0


def assign_order(probs: list) -> list:
    """Canonical order for assigning numbers: public first (calibrated level,
    then the current number, then id), contest-only (hidden) problems last so
    students never see gaps in the list they are looking at."""
    return sorted(probs, key=lambda p: (1 if p.hidden else 0,
                                        p.level or 9,
                                        p.no if p.no > 0 else 0,
                                        p.pid))


def cmd_order(csv_path: str, dry_run: bool = False) -> int:
    """Apply an approved number map (docs/catalog/problem-numbers-*.csv).

    The map is the committed source of truth for the catalog order: it carries
    the slug, the number before the migration, the new number, the calibrated
    level, the coarse badge and the title. Applying it rewrites `no`, `level`
    and `difficulty` in every config.json it names.
    """
    path = Path(csv_path)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        print(f"FAIL ไม่พบแมปเลข: {path}", file=sys.stderr)
        return 1
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        print(f"FAIL แมปเลขว่าง: {path}", file=sys.stderr)
        return 1

    local = {p.pid for p in load_all()}
    mapped = [str(r.get("slug") or "") for r in rows]
    unknown = sorted(set(mapped) - local)
    if unknown:
        print(f"FAIL แมประบุโจทย์ที่ไม่มีใน problems/: {', '.join(unknown)}", file=sys.stderr)
        return 1
    absent = sorted(local - set(mapped))
    if absent:
        print(f"FAIL แมปไม่ครอบคลุมโจทย์ {len(absent)} ข้อ: {', '.join(absent)}", file=sys.stderr)
        return 1

    seen: dict = {}
    bad = False
    for row in rows:
        slug = str(row["slug"])
        try:
            new_no = int(row["new_no"])
            level = int(row["level"])
        except (KeyError, TypeError, ValueError):
            print(f"FAIL แถวของ {slug} ไม่มี new_no/level ที่อ่านได้", file=sys.stderr)
            bad = True
            continue
        if new_no in seen:
            print(f"FAIL เลขใหม่ {new_no} ซ้ำ: {seen[new_no]} และ {slug}", file=sys.stderr)
            bad = True
        seen[new_no] = slug
        if level not in grader.VALID_LEVELS:
            print(f"FAIL {slug}: level {level} ไม่อยู่ใน 1..5", file=sys.stderr)
            bad = True
            continue
        band = grader.band_for_level(level)
        want = str(row.get("difficulty") or band).lower()
        if want != band:
            print(f"FAIL {slug}: difficulty {want} ไม่ตรงกับ band ของ level {level} ({band})",
                  file=sys.stderr)
            bad = True
    if sorted(seen) != list(range(1, len(seen) + 1)):
        print(f"FAIL เลขใหม่ไม่ต่อเนื่อง 1..{len(seen)}", file=sys.stderr)
        bad = True
    if bad:
        return 1

    for row in rows:
        slug = str(row["slug"])
        level = int(row["level"])
        cfg = read_config(slug)
        cfg["no"] = int(row["new_no"])
        cfg["level"] = level
        cfg["difficulty"] = grader.band_for_level(level)
        if not dry_run:
            write_config(slug, cfg)
    verb = "dry-run: " if dry_run else ""
    print(f"{verb}ใช้แมป {path.name} — เขียน no/level/difficulty ให้ {len(rows)} ข้อ")
    return 0


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
    g.add_argument("--order", metavar="CSV", help="ใช้แมปเลขที่อนุมัติแล้ว (เช่น "
                                              "docs/catalog/problem-numbers-2026-10-22.csv)")
    ap.add_argument("--id", help="problem id (กับ --set)")
    ap.add_argument("--no", type=int, help="เลขที่ต้องการ (กับ --set, 0 = ลบเลข)")
    ap.add_argument("--force", action="store_true", help="ยอมทับเลขที่ซ้ำ")
    ap.add_argument("--dry-run", action="store_true", help="ไม่เขียนไฟล์ (กับ --order)")
    args = ap.parse_args(argv)

    if args.order:
        return cmd_order(args.order, dry_run=args.dry_run)

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
    if args.no > 0 and clash:
        # --force: remove the clashing problem's number so the target can take it
        # without creating a duplicate. The clashing problem can be re-assigned
        # with --assign afterward.
        set_no(clash[0], 0)
        print(f"{clash[0]}: เลข {args.no} ถูกยกเลิก (ถูกยึดโดย {args.id})")
    set_no(args.id, args.no)
    print(f"{args.id}: เลข {args.no if args.no else '(ลบออก)'}")
    if args.no > 0 and not clash:
        print("next: python3 tools/validate_problem.py " + args.id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
