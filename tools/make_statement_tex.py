#!/usr/bin/env python3
"""Generate a beautiful Thai statement.pdf from problems/<id>/statement.md
using LaTeX (tectonic + TH Sarabun New).

House style (matches the TOI reference statements, e.g. monsters.TH.pdf):
- header: 36pt bold title, then a 21pt limits line
  ("1 second, 256 megabytes"), no problem-id line, no rule
- story paragraphs in full at 17pt — do NOT shorten
- math stays at 12pt (as in the reference: $n$ renders smaller than
  the surrounding 17pt Thai), Latin runs in Latin Modern Roman,
  code/sample cells in Inconsolata
- every fenced sample (input:/output:) becomes one ROW of a single bordered
  longtable ("ตัวอย่างข้อมูลนำเข้า" / "ตัวอย่างข้อมูลส่งออก", 17pt
  regular header, 14pt Inconsolata cells); the table breaks across
  pages with a repeated header
- list items render as plain lines (no bullets)
- footer on every page: "Newbiegrader | <page>"

Requires: tectonic (brew install tectonic). Fonts in tools/fonts/.

Usage: python3 tools/make_statement_tex.py <problem_id>
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def normalize_pdf(data: bytes) -> bytes:
    """Make tectonic output byte-deterministic: same .tex always yields
    the same bytes. Neutralizes per-run randomness:
    - font subset tags (e.g. /XKCDQZ+Sarabun -> /AAAAAA+Name)
    - /CreationDate / /ModDate stamps
    - trailer /ID pair
    (Rendered pages are identical either way; this also keeps git diffs clean.)"""
    data = re.sub(rb"/[A-Z]{6}\+([A-Za-z]+)",
                  lambda m: b"/AAAAAA+" + m.group(1), data)
    data = re.sub(rb"/(CreationDate|ModDate) \(D:[^)]*\)",
                  rb"/\1 (D:20000101000000+00'00')", data)
    data = re.sub(rb"/ID\s*\[\s*<[0-9A-Fa-f]*>\s*<[0-9A-Fa-f]*>\s*\]",
                  b"/ID [<00000000000000000000000000000000>"
                  b"<00000000000000000000000000000000>]", data)
    return data

ROOT = Path(__file__).parent.parent
FONTDIR = (Path(__file__).parent / "fonts").resolve()

ACCENT = "00695C"  # deep teal


def esc_plain(s: str) -> str:
    return (s.replace("\\", "\\textbackslash{}")
             .replace("&", "\\&").replace("%", "\\%")
             .replace("$", "\\$")
             .replace("#", "\\#").replace("_", "\\_")
             .replace("{", "\\{").replace("}", "\\}")
             .replace("~", "\\textasciitilde{}"))


def has_thai(s: str) -> bool:
    return any(0x0E00 <= ord(c) <= 0x0E7F for c in s)


def tex_code(s: str, msmall: bool = False) -> str:
    # code spans are usually ASCII; Thai inside falls back to Sarabun bold.
    # ^ must become math even in code (else XeTeX errors).
    # A lone ASCII letter is a variable, not code: set it as math italic
    # so `n` and plain n look identical ($n$).
    if has_thai(s):
        return "\\textbf{" + esc_plain(s) + "}"
    if re.fullmatch(r"[A-Za-z]", s or ""):
        return "\\mth{" + s + "}" if msmall else "$" + s + "$"
    out = []
    for m in re.split(r"([A-Za-z0-9]\^\w+)", s):
        if re.fullmatch(r"[A-Za-z0-9]\^\w+", m or ""):
            out.append("\\mth{" + m + "}" if msmall else "$" + m + "$")
        else:
            out.append("\\texttt{" + esc_plain(m) + "}" if m else "")
    return "".join(out)


def _is_thai(ch: str) -> bool:
    return 0x0E00 <= ord(ch) <= 0x0E7F


def _latin_tex(t: str, bold: bool, sans: bool = False, msmall: bool = False) -> str:
    # Latin/digit runs use Latin Modern Roman (tools/fonts/, GUST license),
    # the same face as the TOI reference statements. (Thai itself is set in
    # TH Sarabun New.)
    # Grouping MUST be {\eng{}...} (braces outside): \eng{...} leaks the
    # font change past its own braces to the end of the document in this
    # toolchain (all Thai after the first Latin run would set in Prompt).
    # A lone space is {\eng{}\ } — a bare space after \eng{} is swallowed.
    t = esc_plain(t)
    t = t.replace("<=", "$\\le$").replace(">=", "$\\ge$").replace("!=", "$\\ne$")
    # Arrows have no glyph in the serif/main fonts (tofu): set them as math.
    t = t.replace("→", "$\\rightarrow$").replace("↔", "$\\leftrightarrow$")
    t = re.sub(r"(\d+)\^(\d+)", r"$\1^\2$", t)
    t = re.sub(r"\b([A-Za-z])\^(\d+)\b", r"$\1^\2$", t)
    # Lone Latin letters are variables: set them as math italic ($N$), the way
    # they look inside equations. Only outside existing $...$ segments.
    segs = re.split(r"(\$[^$]*\$)", t)
    for i in range(0, len(segs), 2):
        segs[i] = re.sub(r"(?<![A-Za-z$])([A-Za-z])(?![A-Za-z])",
                          r"$\1$", segs[i])
    t = "".join(segs)
    return _eng_wrap(t, bold, msmall)


def _eng_wrap(t: str, bold: bool, msmall: bool = False) -> str:
    """Wrap a Latin run in the Latin Modern family without leaking or eating space.

    Form MUST be {\\eng{}...} (braces outside): \\eng{...} leaks the font
    change past its own braces to the end of the document in this toolchain.
    Spaces adjacent to the switch are emitted bare (main font): a space right
    after \\eng machinery is swallowed even outside the braces.
    msmall=True (17.3pt body context) drops the run back to \\normalsize
    (12pt), exactly like the reference statements.
    """
    m = re.match(r"( *)(.*?)(\ *)$", t, re.S)
    lead, core, trail = m.group(1), m.group(2), m.group(3)
    lead = " " if lead else ""
    trail = " " if trail else ""
    if not core:
        return " "
    if bold:
        core = "\\textbf{{\\eng{}" + core + "}}"
    else:
        core = "{\\eng{}" + core + "}"
    if msmall:
        core = "{\\normalsize " + core + "}"
    return lead + core + trail


def tex_inline(s: str, bold: bool = False, sans: bool = False,
               msmall: bool = False) -> str:
    """Markdown line -> LaTeX: **bold**, `code`, math shorthands.
    Thai runs stay in Sarabun; Latin/digit runs go to Latin Modern Roman
    (bold when requested). Pass sans=True for display titles.
    Raw math segments (\(...\), \[...\], $$...$$) pass through untouched so
    authors can write real LaTeX; a whole-line $$...$$ becomes display math.
    msmall=True (17.3pt body context): raw math goes through \\mth/\\dmth
    (back to 12pt, like the reference) and Latin/code math follows.
    """
    out = []
    for seg in re.split(r"(\\\[.+?\\\]|\\\(.+?\\\)|\$\$.+?\$\$)", s):
        if not seg:
            continue
        if seg.startswith("\\("):
            inner = seg[2:-2]
            out.append("\\mth{" + inner + "}" if msmall else "$" + inner + "$")
        elif seg.startswith("\\[") or seg.startswith("$$"):
            inner = seg[2:-2]
            out.append("\\dmth{" + inner + "}" if msmall else "\\[" + inner + "\\]")
        else:
            out.append(_tex_inline_text(seg, bold, sans, msmall))
    return "".join(out)


def _tex_inline_text(s: str, bold: bool = False, sans: bool = False,
                     msmall: bool = False) -> str:
    parts = re.split(r"(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`)", s)
    out = []
    for p in parts:
        if not p:
            continue
        b = bold
        if p.startswith("**"):
            p, b = p[2:-2], True
            for run_th, chunk in _runs(p):
                out.append("\\textbf{" + esc_plain(chunk) + "}" if run_th
                           else _latin_tex(chunk, True, sans, msmall))
            continue
        if p.startswith("__") and not p.startswith("___"):
            inner = "".join(
                esc_plain(chunk) if run_th else _latin_tex(chunk, b, sans, msmall)
                for run_th, chunk in _runs(p[2:-2]))
            out.append("\\underline{" + inner + "}")
            continue
        if p.startswith("`"):
            out.append(tex_code(p[1:-1], msmall))
            continue
        for run_th, chunk in _runs(p):
            out.append(esc_plain(chunk) if run_th else _latin_tex(chunk, b, sans, msmall))
    return "".join(out)


def _runs(s: str):
    out = []
    for ch in s:
        th = _is_thai(ch)
        if out and out[-1][0] == th:
            out[-1][1] += ch
        else:
            out.append([th, ch])
    return [(th, chunk) for th, chunk in out]


def md_blocks(md: str):
    blocks, lines, i, buf = [], md.split("\n"), 0, []
    def flush():
        if buf and "\n".join(buf).strip():
            blocks.append(("p", "\n".join(buf)))
        buf.clear()
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            flush()
            code, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            blocks.append(("code", "\n".join(code)))
        elif line.startswith("## "):
            flush()
            blocks.append(("h2", line[3:].strip()))
        elif line.startswith("# "):
            flush()
            blocks.append(("h1", line[2:].strip()))
        elif re.match(r"^\s*(?:[-*]|\d+[.)])\s+", line):
            flush()
            if re.match(r"^\s*\d+[.)]\s+", line):
                blocks.append(("li", line.strip()))
            else:
                blocks.append(("li", re.sub(r"^\s*[-*]\s+", "", line)))
        else:
            buf.append(line)
        i += 1
    flush()
    return blocks


def split_sample(code: str):
    """Split a sample fence into (input, output) at an 'output:' marker."""
    lines = code.split("\n")
    for j, ln in enumerate(lines):
        if ln.strip().lower().rstrip(":") == "output":
            return "\n".join(lines[:j]), "\n".join(lines[j + 1:])
    return code, ""


def tex_verbatim(s: str) -> str:
    # sample boxes are \ttfamily text (not real verbatim): escape everything
    return (s.replace("\\", "\\textbackslash{}")
             .replace("&", "\\&").replace("%", "\\%")
             .replace("$", "\\$").replace("#", "\\#")
             .replace("_", "\\_").replace("{", "\\{").replace("}", "\\}")
             .replace("~", "\\textasciitilde{}").replace("^", "\\^{}"))


def render_samples_table(samples: list) -> str:
    """All fenced samples as ONE bordered table (house style): a header row
    plus one row per sample. longtable lets tall samples break across pages
    with the header repeated. Cells are small monospace; source lines are
    joined with LaTeX line breaks (sample I/O is ASCII-only by convention).
    The cell font auto-shrinks when a sample line is wider than the column
    (e.g. a 50-column output grid) so long lines never overflow the page.
    """

    def cell(body: str) -> str:
        # Inside a p-column cell, \\ would end the table ROW: use \newline
        # for line breaks within the cell.
        lines = body.rstrip("\n").split("\n")
        return "\\newline\n".join(tex_verbatim(l) if l.strip() else "~"
                                  for l in lines) or "~"

    # Widest sample line drives the monospace size: ~28 chars fit at 14pt in a
    # 0.44\linewidth column, so shrink proportionally beyond that (min 6pt).
    maxlen = 0
    for inp, outp in samples:
        for ln in (inp + "\n" + outp).split("\n"):
            maxlen = max(maxlen, len(ln))
    size = 14 if maxlen <= 28 else max(6, (28 * 14) // maxlen)
    lineskip = round(size * 17 / 14, 1)
    font = "{\\fontsize{%d}{%s}\\selectfont\\ttfamily " % (size, lineskip)

    head = ("\\rowcolor[gray]{0.94}\n"
            "{\\centering\\fontsize{17.3}{21} ตัวอย่างข้อมูลนำเข้า\\par} &\n"
            "{\\centering\\fontsize{17.3}{21} ตัวอย่างข้อมูลส่งออก\\par} \\\\\n"
            "\\hline\n")
    parts = ["{\\setlength{\\tabcolsep}{8pt}\\renewcommand{\\arraystretch}{1.4}"
             "\\arrayrulecolor[gray]{0.7}\n",
             "\\begin{longtable}{|p{0.44\\linewidth}|p{0.44\\linewidth}|}\n",
             "\\hline\n", head,
             "\\endfirsthead\n", "\\hline\n", head, "\\endhead\n"]
    for inp, outp in samples:
        parts.append(font + cell(inp) + "} &\n"
                     + font + cell(outp) + "} \\\\\n"
                     "\\hline\n")
    parts.append("\\end{longtable}}\n\n\\medskip\n")
    return "".join(parts)


PREAMBLE = """\\documentclass[a4paper,12pt]{article}
\\usepackage{fontspec}
\\usepackage{xltxtra}
\\usepackage{geometry}
\\usepackage[table]{xcolor}
\\usepackage{amsmath}
\\usepackage{longtable}
\\usepackage{array}
\\usepackage{needspace}
\\usepackage{fancyhdr}
\\geometry{top=2.2cm,bottom=2.2cm,left=2.2cm,right=2.2cm}
\\definecolor{accent}{HTML}{ACCENT}
\\setmainfont[
  Path=FONTPATH,
  Extension=.ttf,
  UprightFont=thsarabunnew,
  BoldFont=thsarabunnew-bold,
  ItalicFont=thsarabunnew-italic,
  BoldItalicFont=thsarabunnew-bolditalic
]{thsarabunnew}
\\newfontfamily\\eng[
  Path=FONTPATH,
  Extension=.otf,
  UprightFont=lmroman-regular,
  BoldFont=lmroman-bold,
  ItalicFont=lmroman-italic,
  BoldItalicFont=lmroman-bolditalic
]{lmroman}
\\setmonofont[
  Path=FONTPATH,
  Extension=.ttf,
  UprightFont=inconsolata-regular,
  BoldFont=inconsolata-bold
]{inconsolata}
\\renewcommand{\\normalsize}{\\fontsize{12}{20}\\selectfont}
\\setlength{\\parskip}{8pt}
\\setlength{\\parindent}{0pt}
\\pagestyle{fancy}
\\fancyhf{}
\\fancyfoot[C]{\\small{\\eng{}Newbiegrader} \\quad\\textbar\\quad {\\eng{}\\thepage}}
\\renewcommand{\\headrulewidth}{0pt}
% Body Thai is 17.3pt but math/Latin stay at 12pt (exactly like the
% reference): mth/dmth typeset math back at normalsize.
\\newcommand{\\mth}[1]{{\\normalsize $#1$}}
\\newcommand{\\dmth}[1]{{\\normalsize \\[#1\\]}}
\\begin{document}
\\normalsize
\\raggedright
""".replace("ACCENT", ACCENT).replace("FONTPATH", str(FONTDIR) + "/")


def _limits_line(tl: float, mem: int) -> str:
    t = str(tl).rstrip("0").rstrip(".")
    unit = "second" if float(t) == 1 else "seconds"
    return "{\\fontsize{21}{26}\\selectfont{\\eng{}" + t + " " + unit + ", " + str(mem) + " megabytes}}\n\n"


# House style uses Thai section headings, matching the reference statement.
H2_TH = {
    "input": "ข้อมูลนำเข้า",
    "output": "ข้อมูลส่งออก",
    "ตัวอย่าง": "ตัวอย่างข้อมูลนำเข้าและข้อมูลส่งออก",
    "limits": "ข้อจำกัด",
    "subtask": "การให้คะแนน",
    "subtasks": "การให้คะแนน",
}


def build(pid: str, title: str, tl: float, mem: int, md: str) -> str:
    blocks = [b for b in md.split("\n") if b.strip()]
    _ = blocks
    parts = [PREAMBLE]
    # One big bold title line, Thai + English alike (Latin runs fall
    # through to Latin Modern via tex_inline, as in the reference).
    parts.append("{\\fontsize{36}{42}\\selectfont\\bfseries " + tex_inline(title) + "}\n\n")
    parts.append("\\vspace{8pt}\n")
    parts.append(_limits_line(tl, mem))
    parts.append("\\vspace{10pt}\n")
    story_done = False
    blocks = md_blocks(md)
    # Every fenced sample becomes one ROW of a single table placed where the
    # first fence stood (all fences live under ## ตัวอย่าง by convention).
    samples = []
    for kind, text in blocks:
        if kind != "code":
            continue
        inp, outp = split_sample(text)
        # drop a leading 'input:' marker, whether alone on its line or
        # prefixing the first value ("input: 12")
        m = re.match(r"(?i)^input:\s*(.*)$", inp.split("\n")[0].strip(),
                     re.S)
        if m:
            first, rest = m.group(1), "\n".join(inp.split("\n")[1:])
            inp = (first + ("\n" + rest if rest else "")).strip("\n")
        samples.append((inp, outp))
    table_done = False
    for kind, text in blocks:
        if kind == "h1":
            continue  # title already in header
        if kind == "h2":
            story_done = True
            parts.append("\\vspace{28pt}\n{\\fontsize{25}{30}\\bfseries " + tex_inline(H2_TH.get(text.lower(), text)) + "}\n\n\\vspace{14pt}\n\\nopagebreak\n")
        elif kind == "code":
            story_done = True
            if not table_done:
                parts.append(render_samples_table(samples))
                table_done = True
        elif kind == "li":
            story_done = True
            parts.append("{\\fontsize{17.3}{20}\\selectfont " + tex_inline(text, msmall=True) + "}\\\\\n")
        else:
            # Markdown paragraph: blank lines separate paragraphs; a single
            # soft line break inside one joins with a space so the story flows
            # as solid full-width blocks (as in the reference).
            # Body is 17pt; math stays 12pt (like the reference) because raw
            # \fontsize does not touch the math setup (only \normalsize does).
            for para in re.split(r"\n[ \t]*\n", text):
                lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
                if not lines:
                    continue
                parts.append("{\\fontsize{17.3}{20}\\selectfont " + tex_inline(" ".join(lines), msmall=True) + "}\n\n")
    parts.append("\\end{document}\n")
    return "".join(parts)


def main(pid: str) -> None:
    pdir = ROOT / "problems" / pid
    cfg = json.loads((pdir / "config.json").read_text(encoding="utf-8"))
    md = (pdir / "statement.md").read_text(encoding="utf-8")
    tex = build(pid, cfg["title"], float(cfg.get("time_limit", 1.0)),
                int(cfg.get("memory_limit", 256)), md)
    # Byte-deterministic builds: same .tex always yields identical bytes
    # (fixes xdvipdfmx subset tags/checksums/IDs). normalize_pdf pins dates.
    os.environ.setdefault("SOURCE_DATE_EPOCH", "0")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "statement.tex"
        src.write_text(tex, encoding="utf-8")
        r = subprocess.run(["tectonic", "-o", tmp, str(src)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(r.stdout[-3000:])
            print(r.stderr[-3000:])
            raise SystemExit(f"tectonic failed for {pid}")
        shutil.move(str(Path(tmp) / "statement.pdf"), str(pdir / "statement.pdf"))
    out = pdir / "statement.pdf"
    out.write_bytes(normalize_pdf(out.read_bytes()))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1])
