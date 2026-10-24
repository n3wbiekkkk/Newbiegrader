#!/usr/bin/env python3
"""Build a private solution PDF with the shared statement typography and branding."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import make_statement_tex as house

REQUIRED_SECTIONS = ('แนวคิด', 'วิธีทำ', 'เหตุผลความถูกต้อง', 'ความซับซ้อน', 'จุดที่ควรระวัง')


def escape_code(text):
    mapping = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}', '#': r'\#',
               '$': r'\$', '%': r'\%', '&': r'\&', '_': r'\_',
               '^': r'\textasciicircum{}', '~': r'\textasciitilde{}'}
    return ''.join(mapping.get(ch, ch) for ch in text)


def source_hash(folder):
    names = ['config.json', 'statement.md', 'solution.md', 'solution.py', 'solution.cpp']
    config = json.loads((folder/'config.json').read_text())
    for sample in config.get('samples', []):
        for suffix in ('in', 'out'):
            names.append(f'tests/{sample}.{suffix}')
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode() + b'\0' + (folder/name).read_bytes() + b'\0')
    for path in [Path(__file__), Path(house.__file__), house.BRAND_LOGO, *sorted(house.FONTDIR.iterdir())]:
        if path.is_file():
            digest.update(path.name.encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def validate_source(folder):
    md = (folder/'solution.md').read_text()
    for section in REQUIRED_SECTIONS:
        if f'## {section}\n' not in md:
            raise ValueError(f'missing solution section: {section}')
    if any(marker in md for marker in ('TODO', 'TBD', 'REPLACE_ME')):
        raise ValueError('unfinished solution template')
    if '```' in md:
        raise ValueError('code belongs in solution.py and solution.cpp, not Markdown fences')
    compile((folder/'solution.py').read_text(), str(folder/'solution.py'), 'exec')
    cpp = (folder/'solution.cpp').read_text()
    if any(marker in cpp for marker in ('TODO', 'TBD', 'REPLACE_ME')) or not cpp.strip():
        raise ValueError('unfinished C++ solution code')
    return md


def code_pages(source, language="Python 3"):
    """Bound displayed widths and page heights without modifying executable source."""
    rows = []
    for number, line in enumerate(source.expandtabs(4).splitlines(), 1):
        # 78 mono columns fit the statement's text width at 9.8 pt.
        chunks = textwrap.wrap(line, width=78, replace_whitespace=False,
                               drop_whitespace=False, break_long_words=True,
                               break_on_hyphens=False) or ['']
        for part, chunk in enumerate(chunks):
            indent = len(chunk) - len(chunk.lstrip(' '))
            label = str(number) if part == 0 else ''
            rows.append(r'\makebox[18pt][r]{\color{brandmuted}' + label + r'}\hspace{9pt}'
                        + r'\hspace*{' + str(indent * 4.9) + r'pt}\texttt{'
                        + escape_code(chunk.lstrip(' ')) + r'}\par')
    pages = []
    for start in range(0, len(rows), 53):
        title = 'โค้ดตัวอย่าง ' + language + (' (ต่อ)' if start else '')
        pages.append(r'\newpage' + '\n' + house.brand_header()
                     + r'{\fontsize{22}{26}\selectfont\bfseries ' + house.tex_inline(title)
                     + r'}\par\vspace{8pt}' + '\n'
                     + r'{\fontsize{9.8}{11.5}\selectfont\setlength{\parskip}{0pt}' + '\n'
                     + '\n'.join(rows[start:start+53]) + '\n}\n')
    return ''.join(pages)


def build(folder, output_dir=None, engine='tectonic'):
    folder = Path(folder)
    md = validate_source(folder)
    cfg = json.loads((folder/'config.json').read_text())
    pdf = (Path(output_dir)/f'{folder.name}-solution.pdf') if output_dir else folder/'solution.pdf'
    pdf.parent.mkdir(parents=True, exist_ok=True)
    samples = []
    for name in cfg.get('samples', [])[:3]:
        inp = (folder/'tests'/f'{name}.in').read_text().rstrip('\n')
        out = (folder/'tests'/f'{name}.out').read_text().rstrip('\n')
        if max(map(len, (inp+'\n'+out).splitlines()), default=0) <= 65 and max(len(inp.splitlines()), len(out.splitlines())) <= 8:
            samples.append((inp, out))
    if samples:
        # Let the canonical statement renderer measure and keep the complete
        # sample table together; never guess Thai line heights here.
        md += '\n## ตัวอย่าง\n\n'
        for inp, out in samples:
            md += '```\ninput:\n' + inp + '\n\noutput:\n' + out + '\n```\n\n'
    tex = house.build(folder.name, 'เฉลย: ' + cfg['title'], cfg['time_limit'], cfg['memory_limit'], md)
    tex = tex.replace(house._limits_line(cfg['time_limit'], cfg['memory_limit']),
                      r'{\eng{}Solution}\par' + '\n', 1)
    tex = tex.rsplit(r'\end{document}', 1)[0]
    tex += code_pages((folder/'solution.cpp').read_text(), 'C++17')
    tex += code_pages((folder/'solution.py').read_text()) + r'\end{document}' + '\n'
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp)/'solution.tex'
        src.write_text(tex)
        result = subprocess.run([engine, '-o', tmp, str(src)], capture_output=True, text=True, timeout=300)
        if result.returncode:
            raise RuntimeError((result.stdout+result.stderr)[-4000:])
        data = house.normalize_pdf((Path(tmp)/'solution.pdf').read_bytes())
    pdf.write_bytes(data)
    pdf.with_suffix('.tex').write_text(tex)
    record = {'version': 1, 'kind': 'solution', 'source_sha256': source_hash(folder),
              'pdf_sha256': hashlib.sha256(data).hexdigest()}
    pdf.with_suffix('.build.json').write_text(json.dumps(record, indent=2)+'\n')
    return pdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('problem')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--engine', default='tectonic')
    args = parser.parse_args()
    if not args.problem or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_' for c in args.problem):
        parser.error('invalid problem ID')
    print(build(ROOT/'problems'/args.problem, args.output_dir, args.engine))


if __name__ == '__main__':
    main()
