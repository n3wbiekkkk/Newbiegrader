#!/usr/bin/env python3
"""Generate Thai statement.pdf from problems/<id>/statement.md.

Use when the source is English/text (no Thai PDF from user).
Requires: fpdf2, uharfbuzz, TH Sarabun fonts (local Mac only).

Usage: python3 tools/make_statement_pdf.py <problem_id>
"""
import re
import sys
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).parent.parent
FONT_DIR = Path.home() / "Library" / "Fonts"
FONTS = {
    "": "THSarabunIT๙.ttf",
    "B": "THSarabunIT๙ Bold.ttf",
    "I": "THSarabunIT๙ Italic.ttf",
    "BI": "THSarabunIT๙ BoldItalic.ttf",
}


class StatementPDF(FPDF):
    pass


def md_blocks(md: str):
    """Split markdown into ('h1'|'h2'|'code'|'li'|'p', text) blocks."""
    blocks = []
    lines = md.split("\n")
    i = 0
    buf: list[str] = []
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            if buf:
                blocks.append(("p", "\n".join(buf)))
                buf = []
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            blocks.append(("code", "\n".join(code)))
        elif line.startswith("# "):
            if buf:
                blocks.append(("p", "\n".join(buf)))
                buf = []
            blocks.append(("h1", line[2:]))
        elif line.startswith("## "):
            if buf:
                blocks.append(("p", "\n".join(buf)))
                buf = []
            blocks.append(("h2", line[3:]))
        elif line.lstrip().startswith("- "):
            if buf:
                blocks.append(("p", "\n".join(buf)))
                buf = []
            blocks.append(("li", line.lstrip()[2:]))
        else:
            buf.append(line)
        i += 1
    if buf and "\n".join(buf).strip():
        blocks.append(("p", "\n".join(buf)))
    return blocks


def _cls(ch: str) -> str:
    o = ord(ch)
    if 0x0E00 <= o <= 0x0E7F:
        return "T"
    try:
        ch.encode("latin-1")
        return "L"
    except UnicodeEncodeError:
        return "T"  # Sarabun covers symbols like — • ≤


def script_segs(text: str):
    """Split into (is_thai, chunk) keeping order. Latin/digit runs use a
    core font (this Sarabun file draws ASCII digits as Thai digits, and
    core fonts lack some symbols, so non-latin-1 goes to Sarabun)."""
    out: list = []
    for ch in text:
        c = _cls(ch)
        if out and out[-1][0] == c:
            out[-1][1] += ch
        else:
            out.append([c, ch])
    return [(c == "T", chunk) for c, chunk in out]


def write_rich(pdf: StatementPDF, text: str, size: int, bold: bool = False,
               latin_font: str = "Helvetica"):
    """Write paragraph honoring **bold** and `code` spans, with Thai runs
    in Sarabun and Latin/digit runs in a core font (digits stay Arabic)."""
    parts = re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text)
    for part in parts:
        if not part:
            continue
        b = bold
        latin = latin_font
        if part.startswith("**"):
            part, b = part[2:-2], True
        elif part.startswith("`"):
            part, latin = part[1:-1], "Courier"
        for is_thai, chunk in script_segs(part):
            if is_thai:
                pdf.set_font("Sarabun", "B" if b else "", size)
            else:
                pdf.set_font(latin, "B" if b else "", size if latin == "Courier" else size)
            pdf.write(8, chunk)
    pdf.ln(6)


def main(pid: str) -> None:
    pdir = ROOT / "problems" / pid
    md = (pdir / "statement.md").read_text(encoding="utf-8")
    out = pdir / "statement.pdf"

    pdf = StatementPDF(format="A4")
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(True, margin=20)
    pdf.set_text_shaping(True)
    for style, fname in FONTS.items():
        pdf.add_font("Sarabun", style, str(FONT_DIR / fname))
    pdf.add_page()

    for kind, text in md_blocks(md):
        if kind == "h1":
            write_rich(pdf, text, 24, bold=True)
            pdf.ln(2)
        elif kind == "h2":
            write_rich(pdf, text, 18, bold=True)
            pdf.ln(1)
        elif kind == "code":
            pdf.set_fill_color(245, 245, 245)
            pdf.set_font("Courier", "", 11)
            pdf.multi_cell(0, 6, text, fill=True)
            pdf.ln(2)
        elif kind == "li":
            pdf.set_font("Sarabun", "", 14)
            x = pdf.get_x()
            pdf.cell(6, 8, chr(0x2022))  # bullet in Sarabun (core fonts lack U+2022)
            write_rich(pdf, text, 14)
            pdf.set_x(x)
        else:
            if text.strip():
                write_rich(pdf, text, 14)

    pdf.output(str(out))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1])
