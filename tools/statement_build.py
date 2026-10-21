# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Offline PDF provenance: detect stale source/layout/fonts without reading PDF text.

Hashes detect accidental drift, not a malicious author or rendering defects.
Visual review of every final page is still required.
"""
import hashlib
import json
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
BRAND_ASSETS = (TOOLS.parent / "static" / "logo-icon.png",)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_record(cfg: dict, md: str, pdf: bytes) -> dict:
    layout = (TOOLS / "make_statement_tex.py").read_bytes()
    fonts = [p for p in (TOOLS / "fonts").iterdir() if p.suffix.lower() in (".ttf", ".otf")]
    for font in sorted(fonts):
        layout += font.name.encode() + bytes.fromhex(digest(font.read_bytes()))
    for asset in BRAND_ASSETS:
        layout += asset.name.encode() + bytes.fromhex(digest(asset.read_bytes()))
    header = {k: cfg.get(k) for k in ("title", "time_limit", "memory_limit")}
    source = json.dumps(header, ensure_ascii=False, sort_keys=True).encode() + b"\x00" + md.encode()
    return {"version": 1, "source_sha256": digest(source),
            "layout_sha256": digest(layout), "pdf_sha256": digest(pdf)}


def check_build(pdir: Path, cfg: dict, md: str, required: bool = False) -> list[str]:
    record_path = pdir / "statement.build.json"
    if not record_path.exists() and not required:
        return []  # Legacy package: strict migration is explicit.
    try:
        pdf = (pdir / "statement.pdf").read_bytes()
        actual = json.loads(record_path.read_text(encoding="utf-8"))
        if actual != build_record(cfg, md, pdf):
            return ["statement PDF build is stale; rebuild with tools/make_statement_tex.py"]
        if not pdf.startswith(b"%PDF-"):
            return ["statement.pdf has no PDF header"]
    except (OSError, ValueError):
        return ["missing or invalid statement.build.json/PDF; build the PDF before strict validation"]
    return []
