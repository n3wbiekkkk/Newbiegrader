#!/usr/bin/env python3
"""Generate a Thai statement.pdf from problems/<id>/statement.md
using LaTeX (tectonic + TH Sarabun New).

House style (matches the TOI reference statements, e.g. monsters.TH.pdf):
- header: centered website icon + newbiegrader wordmark and a thin rule,
  followed by a 26pt Thai title, smaller English name and 12pt limits line
- story paragraphs in full at 17pt — do NOT shorten
- math stays at 12pt (as in the reference: $n$ renders smaller than
  the surrounding 17pt Thai), Latin runs in Latin Modern Roman,
  code/sample cells in Inconsolata
- sample input/output pairs share a plain bordered two-column table, with
  12pt Inconsolata cells (smaller only for wide output) and repeated headers
- indented bullets and numbered rules, with headings kept with their content
- page number at the bottom right; no decorative banner or invented subtasks

Requires: tectonic (brew install tectonic). Fonts in tools/fonts/.

Usage: python3 tools/make_statement_tex.py <problem_id>
"""
import hashlib
import argparse
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FONTDIR = (Path(__file__).parent / "fonts").resolve()
BRAND_LOGO = (ROOT / "static" / "logo-icon.png").resolve()

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
            code = "\\texttt{" + esc_plain(m) + "}" if m else ""
            out.append("{\\normalsize " + code + "}" if msmall and code else code)
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
    Raw math segments (\\(...\\), \\[...\\], $$...$$) pass through untouched so
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
            blocks.append(("li", line))
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


def sample_font_size(samples: list) -> int:
    maxlen = max((len(line) for pair in samples for body in pair
                  for line in body.splitlines()), default=0)
    # A 12pt Inconsolata line fits 37 characters inside the column borders.
    return 12 if maxlen <= 37 else max(7, int(37 * 12 / maxlen))


def render_samples_table(samples: list, multipage: bool = True) -> str:
    """All fenced samples as ONE bordered table (house style): a header row
    plus one row per sample. Pages can break between sample rows, with the
    header repeated. Cells are small monospace; source lines are
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

    size = sample_font_size(samples)
    lineskip = round(size * 1.2, 1)
    font = "{\\fontsize{%d}{%s}\\selectfont\\ttfamily " % (size, lineskip)

    head = ("{\\centering\\fontsize{16}{19}\\selectfont\\bfseries ตัวอย่างข้อมูลนำเข้า\\par} &\n"
            "{\\centering\\fontsize{16}{19}\\selectfont\\bfseries ตัวอย่างข้อมูลส่งออก\\par} \\\\\n"
            "\\hline\n")
    col = "p{\\dimexpr0.5\\linewidth-2\\tabcolsep-1.5\\arrayrulewidth\\relax}"
    environment = "longtable" if multipage else "tabular"
    parts = ["{\\fontsize{12}{14.4}\\selectfont\\setlength{\\parskip}{0pt}"
             "\\setlength{\\tabcolsep}{6pt}\\renewcommand{\\arraystretch}{1.15}"
             "\\arrayrulecolor[gray]{0.5}\\setlength{\\LTpre}{0pt}\\setlength{\\LTpost}{6pt}\n",
             "\\begin{" + environment + "}{|" + col + "|" + col + "|}\n",
             "\\hline\n", head]
    if multipage:
        parts.extend(["\\endfirsthead\n", "\\hline\n", head, "\\endhead\n"])
    for inp, outp in samples:
        parts.append(font + cell(inp) + "\\par} &\n"
                     + font + cell(outp) + "\\par} \\\\\n"
                     "\\hline\n")
    parts.append("\\end{" + environment + "}}\\par\n\n")
    return "".join(parts)


PREAMBLE = """\\documentclass[a4paper,12pt]{article}
\\usepackage{fontspec}
\\usepackage{graphicx}
\\usepackage{xltxtra}
\\usepackage{geometry}
\\usepackage[table]{xcolor}
\\usepackage{amsmath}
\\usepackage{longtable}
\\usepackage{array}
\\usepackage{needspace}
\\usepackage{fancyhdr}
\\geometry{top=1.2cm,bottom=2.2cm,left=2.2cm,right=2.2cm}
\\definecolor{accent}{HTML}{ACCENT}
\\definecolor{brandink}{HTML}{232522}
\\definecolor{brandmuted}{HTML}{656961}
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
\\newfontfamily\\wordmarkfont[
  Path=FONTPATH,
  Extension=.ttf,
  UprightFont=anuphan-regular,
  BoldFont=anuphan-semibold
]{anuphan-regular}
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
\\fancyfoot[R]{{\\eng{}\\fontsize{10}{12}\\selectfont\\thepage}}
\\renewcommand{\\headrulewidth}{0pt}
% Body Thai is 17.3pt but math/Latin stay at 12pt (exactly like the
% reference): mth/dmth typeset math back at normalsize.
\\newcommand{\\mth}[1]{{\\normalsize $#1$}}
\\newcommand{\\dmth}[1]{{\\normalsize \\[#1\\]}}
\\newbox\\statementtailbox
\\newdimen\\statementtailheight
\\begin{document}
\\XeTeXlinebreaklocale "th"
\\XeTeXlinebreakskip = 0pt plus 1pt
\\normalsize
\\raggedright
""".replace("ACCENT", ACCENT).replace("FONTPATH", str(FONTDIR) + "/")


def _limits_line(tl: float, mem: int) -> str:
    t = format(tl, "g")
    unit = "second" if float(t) == 1 else "seconds"
    return "{\\fontsize{12}{16}\\selectfont{\\eng{}" + t + " " + unit + ", " + str(mem) + " megabytes}}\n\n"


def brand_header() -> str:
    """Match the light website wordmark above the problem title, once per PDF."""
    return (
        "{\\centering\n"
        "\\raisebox{-5pt}{\\includegraphics[height=24pt]{\\detokenize{" + str(BRAND_LOGO) + "}}}"
        "\\hspace{7pt}"
        "{\\wordmarkfont\\fontsize{22}{28}\\selectfont\\color{brandink}\\bfseries "
        "newbie{\\mdseries\\color{brandmuted}grader}}\\par}\n"
        "\\vspace{6pt}\\hrule height 0.4pt\\vspace{10pt}\n"
    )


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
    parts = [PREAMBLE, brand_header()]
    # One big bold title line, Thai + English alike (Latin runs fall
    # through to Latin Modern via tex_inline, as in the reference).
    match = re.fullmatch(r"(.+?)\s+(\([^()]+\))", title)
    heading = tex_inline(title)
    if match:
        heading = (tex_inline(match[1]) + " {\\fontsize{16}{22}\\selectfont "
                   + tex_inline(match[2]) + "}")
    parts.append("{\\fontsize{26}{31}\\selectfont\\bfseries " + heading + "}\\par\n")
    parts.append(_limits_line(tl, mem))
    blocks = md_blocks(md)
    # Resource limits already appear under the title. Keep other constraints
    # in a Limits section, but suppress a section containing only that repeat.
    cleaned = []
    for kind, text in blocks:
        if kind == "li" and re.fullmatch(
                r"\s*[-*]\s*เวลา\s+[\d.]+\s+วินาที,?\s*หน่วยความจำ\s+\d+\s+MB\s*", text):
            continue
        cleaned.append((kind, text))
    blocks = [block for i, block in enumerate(cleaned)
              if not (block[0] == "h2" and block[1].lower() == "limits"
                      and (i + 1 == len(cleaned) or cleaned[i + 1][0] == "h2"))]
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
    tail_start = None
    for kind, text in blocks:
        if kind == "h1":
            continue  # title already in header
        if kind == "h2":
            reserve = 80
            if text == "ตัวอย่าง" and samples:
                tail_start = len(parts)
                height = max(len(body.rstrip("\n").split("\n")) for body in samples[0])
                size = sample_font_size(samples)
                reserve = min(620, 65 + height * size * 1.2)
            parts.append("\\Needspace{" + str(reserve) + "pt}\\vspace{12pt}\n"
                         "{\\fontsize{22}{26}\\selectfont\\bfseries "
                         + tex_inline(H2_TH.get(text.lower(), text))
                         + "}\\par\\nobreak\\vspace{4pt}\n")
        elif kind == "code":
            if not table_done:
                parts.append(render_samples_table(samples))
                table_done = True
        elif kind == "li":
            item = re.match(r"^(\s*)([-*]|\d+[.)])\s+(.*)", text)
            indent = 12 * (1 + len(item[1].expandtabs(2)) // 2)
            marker = "\\textbullet" if item[2] in ("-", "*") else tex_inline(item[2])
            parts.append("{\\fontsize{17.3}{20}\\selectfont\\setlength{\\leftskip}{"
                         + str(indent) + "pt}\\setlength{\\parskip}{2pt}"
                         "\\hangindent=12pt\\noindent " + marker + "\\enspace "
                         + tex_inline(item[3], msmall=True) + "\\par}\n")
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
    if tail_start is not None:
        # Measure the actual typeset examples + explanation + existing scoring
        # as one block. If it fits a fresh page, reserve exactly that height;
        # otherwise retain longtable's normal multipage behavior. This avoids
        # almost-empty final pages without guessing Thai line lengths.
        tail = "".join(parts[tail_start:])
        boxed = tail.replace(render_samples_table(samples),
                             render_samples_table(samples, multipage=False))
        parts[tail_start:] = [
            "\\par\\begingroup\n\\setbox\\statementtailbox=\\vbox{\\hsize=\\linewidth\n"
            "\\renewcommand{\\Needspace}[1]{}\n" + boxed + "}\n"
            "\\statementtailheight=\\ht\\statementtailbox\n"
            "\\advance\\statementtailheight by\\dp\\statementtailbox\n"
            "\\ifdim\\statementtailheight<.92\\textheight\n"
            # Account for the paragraph/baseline glue at the insertion point.
            "\\advance\\statementtailheight by2\\baselineskip\n"
            "\\Needspace{\\statementtailheight}\\unvbox\\statementtailbox\n"
            "\\else\n" + tail + "\\fi\\endgroup\n"]
    parts.append("\\end{document}\n")
    return "".join(parts)


def main(pid: str, output_dir: Path | None = None) -> None:
    import grader
    from tools.statement_build import build_record
    from tools.validate_problem import public_sample_errors

    pdir = ROOT / "problems" / pid
    cfg = json.loads((pdir / "config.json").read_text(encoding="utf-8"))
    md = (pdir / "statement.md").read_text(encoding="utf-8")
    errors = public_sample_errors(cfg, md, grader.load_problem(pid).tests)
    if errors:
        raise SystemExit("PDF preflight failed: " + "; ".join(errors))
    tex = build(pid, cfg["title"], float(cfg.get("time_limit", 1.0)),
                int(cfg.get("memory_limit", 256)), md)
    # Byte-deterministic builds: same .tex always yields identical bytes
    # (fixes xdvipdfmx subset tags/checksums/IDs). normalize_pdf pins dates.
    os.environ.setdefault("SOURCE_DATE_EPOCH", "0")
    out = (output_dir / f"{pid}.pdf") if output_dir else pdir / "statement.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "statement.tex"
        src.write_text(tex, encoding="utf-8")
        r = subprocess.run(["tectonic", "-o", tmp, str(src)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(r.stdout[-3000:])
            print(r.stderr[-3000:])
            raise SystemExit(f"tectonic failed for {pid}")
        shutil.move(str(Path(tmp) / "statement.pdf"), str(out))
    out.write_bytes(normalize_pdf(out.read_bytes()))
    record_path = out.with_suffix(".build.json")
    record_path.write_text(json.dumps(build_record(cfg, md, out.read_bytes()), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("problems", nargs="*", help="problem IDs to render")
    parser.add_argument("--all", action="store_true", help="render all local problems")
    parser.add_argument("--output-dir", type=Path, help="preview directory; leaves installed PDFs unchanged")
    args = parser.parse_args()
    if args.all and args.problems:
        parser.error("use either problem IDs or --all")
    ids = sorted(p.name for p in (ROOT / "problems").iterdir()
                 if (p / "config.json").is_file()) if args.all else args.problems
    if not ids:
        parser.error("provide problem IDs or --all")
    for pid in ids:
        main(pid, args.output_dir)
