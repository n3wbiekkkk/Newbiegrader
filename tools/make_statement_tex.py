#!/usr/bin/env python3
"""Generate a beautiful Thai statement.pdf from problems/<id>/statement.md
using LaTeX (tectonic + TH Sarabun).

Story paragraphs (before the first ##) are kept in full — do NOT shorten.
Math shorthands (<=, >=, 10^9, x^2) become real LaTeX math.
Sample fences with input:/output: markers become side-by-side boxes.

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


def tex_code(s: str) -> str:
    # code spans are usually ASCII; Thai inside falls back to Sarabun bold.
    # ^ must become math even in code (else XeTeX errors).
    if has_thai(s):
        return "\\textbf{" + esc_plain(s) + "}"
    out = []
    for m in re.split(r"([A-Za-z0-9]\^\w+)", s):
        if re.fullmatch(r"[A-Za-z0-9]\^\w+", m or ""):
            out.append("$" + m + "$")
        else:
            out.append("\\texttt{" + esc_plain(m) + "}" if m else "")
    return "".join(out)


def _is_thai(ch: str) -> bool:
    return 0x0E00 <= ord(ch) <= 0x0E7F


def _latin_tex(t: str, bold: bool) -> str:
    t = esc_plain(t)
    t = t.replace("<=", "$\\le$").replace(">=", "$\\ge$").replace("!=", "$\\ne$")
    t = re.sub(r"(\d+)\^(\d+)", r"$\1^\2$", t)
    t = re.sub(r"\b([A-Za-z])\^(\d+)\b", r"$\1^\2$", t)
    if bold:
        return "\\textsf{\\textbf{" + t + "}}"
    return "\\textsf{" + t + "}"


def tex_inline(s: str, bold: bool = False) -> str:
    """Markdown line -> LaTeX: **bold**, `code`, math shorthands.
    Thai runs stay in Sarabun; Latin/digit runs go to the TeX sans font
    (this Sarabun file draws ASCII digits as Thai digits)."""
    parts = re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", s)
    out = []
    for p in parts:
        if not p:
            continue
        b = bold
        if p.startswith("**"):
            p, b = p[2:-2], True
            for run_th, chunk in _runs(p):
                out.append("\\textbf{" + esc_plain(chunk) + "}" if run_th
                           else _latin_tex(chunk, True))
            continue
        if p.startswith("`"):
            out.append(tex_code(p[1:-1]))
            continue
        for run_th, chunk in _runs(p):
            out.append(esc_plain(chunk) if run_th else _latin_tex(chunk, b))
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
        elif line.lstrip().startswith("- "):
            flush()
            blocks.append(("li", line.lstrip()[2:]))
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
    # samples are ASCII judge data; escape only TeX specials for verbatim-lite
    return s.replace("\\", "\\textbackslash{}")


def render_sample(inp: str, outp: str) -> str:
    def box(title, body):
        return ("\\begin{minipage}[t]{0.48\\linewidth}\n"
                "{\\small\\bfseries\\color{accent} " + title + "}\n"
                "\\begin{mdframed}[backgroundcolor=black!4,linewidth=0.6pt,"
                "linecolor=black!25,innerleftmargin=6pt,innerrightmargin=6pt,"
                "innertopmargin=4pt,innerbottommargin=4pt]\n"
                "{\\ttfamily\\small\\setlength{\\baselineskip}{14pt}\n" +
                "\\\\\n".join(tex_verbatim(l) if l.strip() else "~"
                               for l in body.rstrip("\n").split("\n")) +
                "}\n\\end{mdframed}\n\\end{minipage}")
    if outp:
        return (box("Input", inp) + "\\hfill\n" + box("Output", outp) + "\n\n\\medskip\n")
    return box("Input", inp) + "\n\n\\medskip\n"


PREAMBLE = """\\documentclass[a4paper,12pt]{article}
\\usepackage{fontspec}
\\usepackage{xltxtra}
\\usepackage{geometry}
\\usepackage{xcolor}
\\usepackage{amsmath}
\\usepackage{mdframed}
\\usepackage{fancyhdr}
\\geometry{top=2.2cm,bottom=2.2cm,left=2.2cm,right=2.2cm}
\\definecolor{accent}{HTML}{ACCENT}
\\setmainfont[
  Path=FONTPATH,
  Extension=.ttf,
  UprightFont=sarabun,
  BoldFont=sarabun-bold,
  ItalicFont=sarabun-italic,
  BoldItalicFont=sarabun-bolditalic
]{sarabun}
\\renewcommand{\\normalsize}{\\fontsize{14}{22}\\selectfont}
\\setlength{\\parskip}{6pt}
\\setlength{\\parindent}{0pt}
\\pagestyle{fancy}
\\fancyhf{}
\\fancyfoot[C]{\\small\\color{black!45} Newbiegrader \\quad\\textbar\\quad \\thepage}
\\renewcommand{\\headrulewidth}{0pt}
\\begin{document}
\\normalsize
""".replace("ACCENT", ACCENT).replace("FONTPATH", str(FONTDIR) + "/")


def build(pid: str, title: str, tl: float, mem: int, md: str) -> str:
    blocks = [b for b in md.split("\n") if b.strip()]
    _ = blocks
    parts = [PREAMBLE]
    parts.append("{\\small\\ttfamily\\color{black!50} " + esc_plain(pid) + "}\n\n")
    parts.append("{\\LARGE\\bfseries " + tex_inline(title) + "}\n\n")
    parts.append("\\textcolor{accent}{\\rule{\\linewidth}{1.2pt}}\n\n")
    parts.append("\\begin{mdframed}[backgroundcolor=black!4,linewidth=0pt,"
                 "innerleftmargin=8pt,innerrightmargin=8pt,"
                 "innertopmargin=5pt,innerbottommargin=5pt]\n"
                 "{\\small\\textsf{Time limit: " + str(tl).rstrip("0").rstrip(".")
                 + " s \\quad\\textbar\\quad Memory limit: " + str(mem) + " MB}}\n"
                 "\\end{mdframed}\n\n\\bigskip\n")
    story_done = False
    for kind, text in md_blocks(md):
        if kind == "h1":
            continue  # title already in header
        if kind == "h2":
            story_done = True
            parts.append("{\\large\\bfseries\\color{accent} " + tex_inline(text) + "}\n\n")
        elif kind == "code":
            story_done = True
            inp, outp = split_sample(text)
            # drop a leading 'input:' marker line if present
            inp_lines = inp.split("\n")
            if inp_lines and inp_lines[0].strip().lower().rstrip(":") == "input":
                inp = "\n".join(inp_lines[1:])
            parts.append(render_sample(inp, outp))
        elif kind == "li":
            story_done = True
            parts.append("\\textbullet\\ " + tex_inline(text) + "\\\\\n")
        else:
            for para in text.split("\n"):
                para = para.strip()
                if not para:
                    continue
                parts.append(tex_inline(para) + "\n\n")
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
