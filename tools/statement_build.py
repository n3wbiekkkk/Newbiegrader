"""Offline PDF provenance: detect stale source/layout/fonts without reading PDF text.

Hashes detect accidental drift, not a malicious author or rendering defects.
Visual review of every final page is still required.
"""
import hashlib
import io
import json
import tokenize
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
BRAND_ASSETS = (TOOLS.parent / "static" / "logo-icon.png",)

# Whitespace and comment tokens carry no rendering decision, so they are left
# out of the layout fingerprint.
_IGNORED_TOKENS = frozenset({
    tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.ENCODING,
})


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def renderer_source(path: Path) -> bytes:
    """The renderer's token stream, with comments and line breaks removed.

    A licence header or a code comment cannot change a rendered page, so it
    must not invalidate the provenance record of every statement in the
    catalog. The tokenizer decides what a comment is, so a `#` inside a string
    literal is left alone, and the remaining tokens keep their types and text,
    which is what the renderer actually acts on.
    """
    raw = path.read_bytes()
    try:
        tokens = list(tokenize.tokenize(io.BytesIO(raw).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return raw
    # Python 3.12 split f-strings into multiple tokens; 3.13 also changed OP's
    # numeric ID. Preserve the original 3.11 provenance for identical source.
    # Slice complete f-strings from source so nested expressions, escaped braces
    # and multiline strings retain every byte relevant to rendering.
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    lines = raw.decode(encoding).splitlines(keepends=True)
    legacy = {'ENDMARKER': 0, 'NAME': 1, 'NUMBER': 2, 'STRING': 3,
              'INDENT': 5, 'DEDENT': 6, 'OP': 54, 'ERRORTOKEN': 60}
    result = []
    depth = 0
    for tok in tokens:
        kind = tokenize.tok_name[tok.type]
        if kind == 'FSTRING_START':
            if depth == 0:
                start = tok.start
            depth += 1
        elif kind == 'FSTRING_END':
            depth -= 1
            if depth == 0:
                first, col = start
                last, end = tok.end
                text = ''.join(lines[first - 1:last])
                text = text[col:len(text) - len(lines[last - 1]) + end]
                result.append(f'3:{text}\n'.encode())
        elif depth == 0 and tok.type not in _IGNORED_TOKENS:
            result.append(f'{legacy.get(kind, kind)}:{tok.string}\n'.encode())
    return b''.join(result)


def build_record(cfg: dict, md: str, pdf: bytes) -> dict:
    layout = renderer_source(TOOLS / "make_statement_tex.py")
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
