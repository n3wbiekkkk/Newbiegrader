#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Create consistent private problem packages and sync public sample blocks.

No database access, PDF styling options, test generation or overwrite mode.
See docs/making-problems.md for the authoring and review contract.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMPLATES = ROOT / "tools" / "templates" / "problem"
ID_RE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z")
SAMPLES_HEADING = "## ตัวอย่าง"


def problem_id(value: str) -> str:
    if not ID_RE.fullmatch(value):
        raise ValueError("problem ID must be lowercase snake_case")
    return value


def create_problem(root: Path, pid: str, thai: str, english: str, no: int,
                   hidden: bool = False) -> Path:
    problem_id(pid)
    if (not thai.strip() or not english.strip()
            or not any("\u0e00" <= c <= "\u0e7f" for c in thai)
            or not re.search(r"[A-Za-z]", english)
            or any(c in thai + english for c in "\r\n()")):
        raise ValueError("supply a Thai title and an English title without newlines or parentheses")
    if isinstance(no, bool) or no < 1 or (hidden and no < 1001) or (not hidden and no >= 1001):
        raise ValueError("public numbers use 1..1000; contest numbers use 1001+")
    pdir = root / "problems" / pid
    ref = root / "examples" / f"{pid}_ref.py"
    if pdir.exists() or ref.exists() or ref.with_suffix(".cpp").exists():
        raise ValueError("problem or reference already exists; nothing overwritten")
    for cfg_path in (root / "problems").glob("*/config.json"):
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        if cfg.get("no") == no:
            raise ValueError(f"problem number {no} is already in use")
    title = f"{thai.strip()} ({english.strip()})"
    cfg = {"title": title, "time_limit": 1.0, "memory_limit": 256,
           "checker": "token", "tolerance": 1e-6, "difficulty": "easy",
           "tags": ["Implementation"], "samples": ["01", "02", "03"], "no": no}
    if hidden:
        cfg["hidden"] = True
    # Read every template before creating anything. Drafts deliberately fail
    # validation until their rules, fixtures, validator and reference are real.
    statement = (TEMPLATES / "statement.md").read_text(encoding="utf-8").replace("{{TITLE}}", title)
    validator = (TEMPLATES / "input_validator.py.txt").read_text(encoding="utf-8")
    reference = (TEMPLATES / "reference.py.txt").read_text(encoding="utf-8")
    pdir.mkdir(parents=True)
    (pdir / "tests").mkdir()
    ref.parent.mkdir(parents=True, exist_ok=True)
    (pdir / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (pdir / "statement.md").write_text(statement, encoding="utf-8")
    (pdir / "input_validator.py").write_text(validator, encoding="utf-8")
    ref.write_text(reference, encoding="utf-8")
    return pdir


def sync_samples(pdir: Path, write: bool = False) -> bool:
    """Return whether the sample section already matches; touch that section only."""
    cfg = json.loads((pdir / "config.json").read_text(encoding="utf-8"))
    names = cfg.get("samples")
    if (not isinstance(names, list) or len(names) < 3
            or any(not isinstance(n, str) or not re.fullmatch(r"(?:0[1-9]|[1-9][0-9])", n) for n in names)
            or len(set(names)) != len(names)):
        raise ValueError("config.samples must list at least 3 unique public names (01..99)")
    md_path = pdir / "statement.md"
    md = md_path.read_text(encoding="utf-8")
    headings = list(re.finditer(r"^## .+$", md, flags=re.M))
    hits = [m for m in headings if m.group() == SAMPLES_HEADING]
    if len(hits) != 1:
        raise ValueError("statement must have exactly one '## ตัวอย่าง' section")
    start = hits[0].start()
    end = next((m.start() for m in headings if m.start() > start), len(md))
    blocks = []
    for name in names:
        pair = []
        for ext in ("in", "out"):
            raw = (pdir / "tests" / f"{name}.{ext}").read_bytes()
            if b"\r" in raw or b"```" in raw or not raw.endswith(b"\n"):
                raise ValueError(f"public sample {name}.{ext} requires LF, final newline and no fence delimiter")
            pair.append(raw.decode("utf-8").removesuffix("\n"))
        blocks.append(f"```\ninput:\n{pair[0]}\n\noutput:\n{pair[1]}\n```\n")
    updated = md[:start] + SAMPLES_HEADING + "\n\n" + "\n".join(blocks) + "\n" + md[end:]
    same = updated == md
    if write and not same:
        md_path.write_text(updated, encoding="utf-8")
    return same


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="create an intentionally incomplete private draft")
    new.add_argument("id")
    new.add_argument("--thai", required=True)
    new.add_argument("--english", required=True)
    new.add_argument("--no", required=True, type=int)
    new.add_argument("--hidden", action="store_true")
    sync = commands.add_parser("sync-samples", help="derive statement examples from declared public tests only")
    sync.add_argument("id")
    sync.add_argument("--write", action="store_true", help="replace only the sample section (default: check, exit 1 if stale)")
    args = parser.parse_args(argv)
    try:
        problem_id(args.id)
        if args.command == "new":
            create_problem(ROOT, args.id, args.thai, args.english, args.no, args.hidden)
            print(f"Created draft {args.id}; complete TODOs and run strict validation before publishing")
            return 0
        same = sync_samples(ROOT / "problems" / args.id, args.write)
        print(f"{args.id}: " + ("samples match" if same else "samples updated" if args.write else "samples stale; run with --write"))
        return 0 if same or args.write else 1
    except (ValueError, OSError) as exc:
        print(f"authoring failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
