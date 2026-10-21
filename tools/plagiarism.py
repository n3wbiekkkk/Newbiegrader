#!/usr/bin/env python3
"""ตรวจการคัดลอกโค้ด (plagiarism / similarity) ของ submission — stdlib ล้วน
ไม่มีผลข้างเคียงตอน import (ใช้เป็น module ได้ทันที)

วิธีทำงาน (winnowing / k-gram fingerprinting) — ทนการเปลี่ยนชื่อตัวแปร, ย้าย indent,
แปะคอมเมนต์ แต่ยังแยก "โจทย์เดียวกันแต่คิดคนละวิธี" ออกจากกันได้:
  1) normalize  — ตัดคอมเมนต์ตามภาษา ยุบ whitespace ทิ้งบรรทัดว่าง (คง case ไว้)
  2) tokenize   — แยกเป็น token (คำ / เครื่องหมายตัวอักษรเดี่ยว)
  3) abstract   — คำสงวน + builtin ที่รู้จักคงเดิม, identifier อื่นแทนด้วยลำดับที่เจอครั้งแรก
                  (rename ตัวแปรทั้งไฟล์จึงไม่ทำให้ fingerprint ขยับ)
  4) k-gram     — hash token ติดกัน k ตัว ด้วย blake2b (8 ไบต์ -> int, คงที่ข้าม process
                  ต่างจาก built-in hash(str) ที่สุ่มทุก process)
  5) winnowing  — เลือก min hash ของทุกหน้าต่าง w ตัวอักษร -> ได้ fingerprint ~2n/(w+1) ตัว
                  (คำนวณครั้งเดียวต่อ submission แล้ว intersect แบบ set[int] ในลูป n^2)

API:
    normalize(code, language="") -> str
    fingerprints(code, k=12, w=6, language="") -> set[int]
    similarity(a, b, language_a="", language_b="") -> float        # 0..1 (Jaccard)
    similar_pairs(rows, threshold=0.5, k=12, w=6, same_language_only=False) -> list[dict]

self-test: python3 tools/plagiarism.py   (exit 1 ถ้ามี FAIL)
"""
from __future__ import annotations

import hashlib
import sys
from collections import deque

K_DEFAULT = 12                  # ความยาว k-gram (จำนวน token)
W_DEFAULT = 6                   # ขนาดหน้าต่างของ winnowing
MIN_NORMALIZED_LEN = 50         # โค้ดสั้นกว่านี้ (หลัง normalize) = ข้าม ไม่เอามาจับคู่
MAX_ROWS = 2000                 # กัน O(n^2) ระเบิด: เกินนี้ raise ValueError

# ---------------------------------------------------------------- keywords / builtins
# คงไว้เป็น token จริง (ไม่ abstract) เพื่อให้แยก "คนละวิธีคิด" ได้ดีขึ้น
# ส่วน identifier ที่ไม่อยู่ในนี้จะถูกแทนด้วย placeholder ตามลำดับที่เจอครั้งแรก
_PY_KEYWORDS = frozenset("""
and as assert async await break class continue def del elif else except finally for from
global if import in is lambda nonlocal not or pass raise return try while with yield
None True False self
""".split())

_PY_BUILTINS = frozenset("""
abs all any append bin bool bytes callable chr clear copy count dict divmod enumerate eval
exec extend filter float format frozenset get getattr hasattr hash hex index input insert
int isinstance issubclass iter items join keys len list lower lstrip map max min next object
open ord pop pow print range read readline remove replace repr reverse reversed round rstrip
set setattr slice sorted split startswith str strip sum super tuple type upper values write
zip sys math collections heapq bisect itertools functools operator stdin stdout stderr argv
deque defaultdict inf gcd sqrt comb permutations Counter
""".split())

_C_KEYWORDS = frozenset("""
auto break case char const continue default do double else enum extern float for goto if
inline int long register restrict return short signed sizeof static struct switch typedef
union unsigned void volatile while bool true false nullptr class public private protected
template namespace using new delete this operator virtual constexpr try catch throw friend
explicit mutable typename
""".split())

_C_BUILTINS = frozenset("""
cin cout cerr endl printf scanf getline puts malloc calloc realloc free memset memcpy sort
swap min max push_back pop_back push pop size empty begin end clear resize insert erase front
back first second make_pair find count accumulate substr length abs sqrt pow log floor ceil
gcd vector map set pair string queue stack priority_queue deque array list unordered_map
unordered_set bitset iostream algorithm cstdio cstring cmath climits cstdlib utility numeric
cctype sstream fstream std main size_t ios sync_with_stdio tie fopen fclose fprintf
""".split())

_C_FAMILY = frozenset({"c", "cpp", "c++", "cc", "cxx", "h", "hpp", "c/cpp", "cxx/clang"})


def _is_c_family(language: str) -> bool:
    """เดาว่าเป็นภาษา C/C++ ไหม (ไม่งั้นถือว่า python-like: คอมเมนต์คือ #)"""
    lang = (language or "").strip().lower()
    if not lang:
        return False
    if lang in _C_FAMILY:
        return True
    return "c++" in lang or "++" in lang or lang.startswith(("cpp", "clang", "gcc", "g++"))


def _keywords(language: str) -> frozenset:
    return _C_KEYWORDS | _C_BUILTINS if _is_c_family(language) else _PY_KEYWORDS | _PY_BUILTINS


# ---------------------------------------------------------------- normalize
def _escaped(text: str, idx: int) -> bool:
    """ตัวอักษรที่ idx ถูก backslash หนีมาไหม (นับจำนวน \\ ด้านหน้าว่าคี่)"""
    bs = 0
    j = idx - 1
    while j >= 0 and text[j] == "\\":
        bs += 1
        j -= 1
    return bs % 2 == 1


def _strip_comments(code: str, language: str) -> str:
    """ตัดคอมเมนต์แบบไม่แตะ string literal (สำคัญ: ข้อความ output ต้องคงอยู่)"""
    c_family = _is_c_family(language)
    out: list[str] = []
    i, n = 0, len(code)
    while i < n:
        ch = code[i]
        if ch in "\"'":
            quote = ch * 3 if code[i:i + 3] == ch * 3 else ch
            j = code.find(quote, i + len(quote))
            while j != -1 and len(quote) == 1 and _escaped(code, j):
                j = code.find(quote, j + 1)
            if j == -1:                      # string ไม่ปิด -> เก็บที่เหลือทั้งก้อน
                out.append(code[i:])
                break
            out.append(code[i:j + len(quote)])
            i = j + len(quote)
            continue
        if c_family and code[i:i + 2] == "//":
            nl = code.find("\n", i)
            if nl == -1:
                break
            out.append(" ")                  # กัน token สองฝั่งมาติดกัน
            i = nl + 1
            continue
        if c_family and code[i:i + 2] == "/*":
            end = code.find("*/", i + 2)
            out.append(" ")
            i = n if end == -1 else end + 2
            continue
        if not c_family and ch == "#":
            nl = code.find("\n", i)
            if nl == -1:
                break
            out.append(" ")
            i = nl + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def normalize(code: str, language: str = "") -> str:
    """ตัดคอมเมนต์ -> ยุบ whitespace ทุกชนิดเป็นช่องเดียว -> ทิ้งบรรทัดว่าง
    คง case และ token ไว้ครบ (ไม่มีการ lowercase / ไม่ลบตัวเลข)"""
    body = _strip_comments(code or "", language)
    return " ".join(body.split())


# ---------------------------------------------------------------- tokens / hashing
def _tokenize(norm: str) -> list[str]:
    """แยก token: ชุด [A-Za-z0-9_] ติดกัน = 1 token, ที่เหลือ = ตัวอักษรเดี่ยว ๆ"""
    toks: list[str] = []
    i, n = 0, len(norm)
    while i < n:
        ch = norm[i]
        if ch == " ":
            i += 1
            continue
        if ch.isalnum() or ch == "_":
            j = i + 1
            while j < n and (norm[j].isalnum() or norm[j] == "_"):
                j += 1
            toks.append(norm[i:j])
            i = j
            continue
        toks.append(ch)
        i += 1
    return toks


def _abstract(tokens: list[str], language: str) -> list[str]:
    """คำสงวน/builtin คงเดิม, identifier อื่น -> "\\x00<ลำดับ>" (ทน rename)"""
    kws = _keywords(language)
    seen: dict[str, int] = {}
    out: list[str] = []
    for tok in tokens:
        head = tok[0]
        if (head.isalpha() or head == "_") and tok not in kws:
            idx = seen.get(tok)
            if idx is None:
                idx = len(seen)
                seen[tok] = idx
            out.append("\x00" + str(idx))
        else:
            out.append(tok)
    return out


def _gram_hash(gram: str) -> int:
    return int.from_bytes(hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest(), "big")


def _winnow(hashes: list[int], w: int) -> set[int]:
    """เลือก min hash ของทุกหน้าต่าง w ตัวติดกัน (เสมอตัว / deterministic: ยึดตัวซ้ายสุด)"""
    n = len(hashes)
    if n == 0 or w <= 1:
        return set(hashes)
    if n <= w:
        return set(hashes)          # สั้นกว่าหนึ่งหน้าต่าง -> เอาทั้งหมด
    picked: set[int] = set()
    window: deque[tuple[int, int]] = deque()      # (index, hash) เรียง hash ขึ้น
    for idx in range(n):
        h = hashes[idx]
        while window and window[-1][1] > h:
            window.pop()
        window.append((idx, h))
        left = idx - w + 1
        while window[0][0] < left:
            window.popleft()
        picked.add(window[0][1])
    return picked


def _fingerprints_from_normalized(norm: str, k: int, w: int, language: str) -> set[int]:
    k = max(1, int(k))
    w = max(1, int(w))
    toks = _abstract(_tokenize(norm), language)
    n = len(toks)
    if n < k:
        return set()
    grams = ["\x1f".join(toks[i:i + k]) for i in range(n - k + 1)]
    return _winnow([_gram_hash(g) for g in grams], w)


def fingerprints(code: str, k: int = K_DEFAULT, w: int = W_DEFAULT,
                 language: str = "") -> set[int]:
    """ชุด fingerprint (int) ของโค้ด — normalize ให้เองในตัว (เรียกซ้ำได้ ไม่เปลี่ยนผล)"""
    return _fingerprints_from_normalized(normalize(code, language), k, w, language)


# ---------------------------------------------------------------- similarity
def similarity(a_code: str, b_code: str, language_a: str = "", language_b: str = "") -> float:
    """ความคล้าย 0..1 = Jaccard ของชุด fingerprint (1.0 = fingerprint เหมือนกันเป๊ะ)
    ถ้าโค้ดสั้นจนไม่มี fingerprint เลย ใช้ "ข้อความหลัง normalize เท่ากันไหม" แทน"""
    norm_a = normalize(a_code, language_a)
    norm_b = normalize(b_code, language_b)
    fa = _fingerprints_from_normalized(norm_a, K_DEFAULT, W_DEFAULT, language_a)
    fb = _fingerprints_from_normalized(norm_b, K_DEFAULT, W_DEFAULT, language_b)
    if not fa and not fb:
        return 1.0 if norm_a == norm_b else 0.0
    inter = len(fa & fb)
    union = len(fa) + len(fb) - inter
    return inter / union if union else 0.0


# ---------------------------------------------------------------- pairwise
def _row_field(row: dict, key: str) -> str:
    val = row.get(key)
    return "" if val is None else str(val)


def similar_pairs(rows: list[dict], threshold: float = 0.5, k: int = K_DEFAULT,
                  w: int = W_DEFAULT, same_language_only: bool = False) -> list[dict]:
    """หาคู่ที่คล้ายกันจาก rows (n^2 แต่ cache fingerprint ต่อแถวแล้ว intersect set[int])

    rows item: {"id","name","problem","language","code"} (key อื่นไม่สนใจ)
    แถวที่โค้ดหลัง normalize สั้นกว่า MIN_NORMALIZED_LEN = ข้าม
    คืน list เรียงจาก similarity มากไปน้อย (เสมอด้วย (a_id, b_id)) — ห้าม dedupe ด้วย name
    ค่า "language" ในผลลัพธ์ = ภาษาเดียวกัน -> ตัวนั้น, คนละภาษา -> "a/b"
    """
    if len(rows) > MAX_ROWS:
        raise ValueError(f"rows มากเกินไป ({len(rows)} > {MAX_ROWS}) — O(n^2) จะช้าเกิน")

    prepped: list[tuple[str, str, str, str, int, set[int]]] = []
    for row in rows:
        lang = _row_field(row, "language")
        norm = normalize(_row_field(row, "code"), lang)
        if len(norm) < MIN_NORMALIZED_LEN:
            continue
        prepped.append((
            _row_field(row, "id"),
            _row_field(row, "name"),
            lang,
            lang.strip().lower(),
            len(norm),
            _fingerprints_from_normalized(norm, k, w, lang),
        ))

    n = len(prepped)
    out: list[dict] = []
    for i in range(n):
        id_a, name_a, lang_a, key_a, len_a, fp_a = prepped[i]
        for j in range(i + 1, n):
            id_b, name_b, lang_b, key_b, len_b, fp_b = prepped[j]
            if same_language_only and key_a != key_b:
                continue
            if not fp_a or not fp_b:
                if not fp_a and not fp_b and len_a == 0 and len_b == 0:
                    # both truly empty: identical normalized text => perfect match
                    out.append({
                        "a_id": id_a,
                        "a_name": name_a,
                        "b_id": id_b,
                        "b_name": name_b,
                        "language": lang_a if key_a == key_b else f"{lang_a}/{lang_b}",
                        "similarity": 1.0,
                        "normalized_len_a": 0,
                        "normalized_len_b": 0,
                        "matches": 0,
                    })
                continue
            inter = len(fp_a & fp_b)
            union = len(fp_a) + len(fp_b) - inter
            sim = inter / union if union else 0.0
            if sim >= threshold:
                out.append({
                    "a_id": id_a,
                    "a_name": name_a,
                    "b_id": id_b,
                    "b_name": name_b,
                    "language": lang_a if key_a == key_b else f"{lang_a}/{lang_b}",
                    "similarity": sim,
                    "normalized_len_a": len_a,
                    "normalized_len_b": len_b,
                    "matches": inter,
                })
    out.sort(key=lambda p: (-p["similarity"], p["a_id"], p["b_id"]))
    return out


# ---------------------------------------------------------------- self-test
_SAMPLE_GRID = '''\
import sys


def count_islands(grid, rows, cols):
    seen = [[False] * cols for _ in range(rows)]
    total = 0
    best = 0
    for i in range(rows):
        for j in range(cols):
            if grid[i][j] == "#" and not seen[i][j]:
                total += 1
                area = 0
                stack = [(i, j)]
                seen[i][j] = True
                while stack:
                    x, y = stack.pop()
                    area += 1
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < rows and 0 <= ny < cols:
                            if grid[nx][ny] == "#" and not seen[nx][ny]:
                                seen[nx][ny] = True
                                stack.append((nx, ny))
                if area > best:
                    best = area
    return total, best


def main():
    data = sys.stdin.read().split()
    rows, cols = int(data[0]), int(data[1])
    grid = data[2:2 + rows]
    total, best = count_islands(grid, rows, cols)
    sys.stdout.write(str(total) + " " + str(best) + "\\n")


main()
'''

# สำเนาที่ "โกงแบบเนียน": เปลี่ยนชื่อตัวแปร/ฟังก์ชันทั้งหมด + แปะคอมเมนต์ + จัด indent ใหม่
_SAMPLE_GRID_RENAMED = '''\
# นาย ก. ส่งงาน (แต่จริง ๆ ก็อปมา)
import sys


def count_islands(g, r, c):          # นับเกาะ + เกาะใหญ่สุด
    vis = [[False] * c for _ in range(r)]
    cnt = 0
    mx = 0
    for a in range(r):
        for b in range(c):           # ไล่ทุกช่อง
            if g[a][b] == "#" and not vis[a][b]:
                cnt += 1
                sz = 0
                st = [(a, b)]
                vis[a][b] = True
                while st:
                    u, v = st.pop()
                    sz += 1
                    for p, q in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        mu, nv = u + p, v + q
                        if 0 <= mu < r and 0 <= nv < c:
                            if g[mu][nv] == "#" and not vis[mu][nv]:
                                vis[mu][nv] = True
                                st.append((mu, nv))
                if sz > mx:
                    mx = sz
    return cnt, mx


def main():
    tok = sys.stdin.read().split()
    r, c = int(tok[0]), int(tok[1])
    g = tok[2:2 + r]
    cnt, mx = count_islands(g, r, c)
    sys.stdout.write(str(cnt) + " " + str(mx) + "\\n")


main()
'''

# คนละโจทย์/คนละวิธีคิดจริง ๆ (ข้อความล้วน ๆ ไม่มี grid)
_SAMPLE_TEXT = '''\
import sys


def longest_word(text):
    best = ""
    for word in text.split():
        word = word.strip(".,!?")
        if len(word) > len(best):
            best = word
    return best


def main():
    text = sys.stdin.read()
    answer = longest_word(text)
    print(answer)
    print(len(answer))


main()
'''


def _case(results: list[tuple[str, bool, str]], name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{len(results)}] {name:<34} {detail:<46} {mark}")


def selftest() -> int:
    """รัน self-test 4 เคส -> exit code (0 = ผ่านหมด)"""
    print(f"self-test tools/plagiarism.py  (k={K_DEFAULT}, w={W_DEFAULT})")
    results: list[tuple[str, bool, str]] = []

    # (1) ไฟล์เดิม vs ตัวเอง = 1.0
    same = similarity(_SAMPLE_GRID, _SAMPLE_GRID, "python", "python")
    _case(results, "ไฟล์เดิม vs ตัวเอง", same == 1.0, f"similarity={same:.4f} (ต้อง = 1.0)")

    # (2) ก็อป + rename ตัวแปร + คอมเมนต์ + indent ใหม่ -> >= 0.8
    copy = similarity(_SAMPLE_GRID, _SAMPLE_GRID_RENAMED, "python", "python")
    _case(results, "rename+คอมเมนต์+indent ใหม่", copy >= 0.8,
          f"similarity={copy:.4f} (ต้อง >= 0.8)")

    # (3) คนละวิธีคิดจริง ๆ -> < 0.3
    diff = similarity(_SAMPLE_GRID, _SAMPLE_TEXT, "python", "python")
    _case(results, "คนละโจทย์/คนละวิธี", diff < 0.3, f"similarity={diff:.4f} (ต้อง < 0.3)")

    # (4) similar_pairs บน 4 แถว -> คู่ที่ก็อปกันต้องมาก่อน
    rows = [
        {"id": "s1", "name": "Alice", "problem": "count_islands",
         "language": "python", "code": _SAMPLE_GRID},
        {"id": "s2", "name": "Alice", "problem": "count_islands",   # ชื่อซ้ำ = ต้องยังรายงาน
         "language": "python", "code": _SAMPLE_GRID_RENAMED},
        {"id": "s3", "name": "Bob", "problem": "count_islands",
         "language": "python", "code": _SAMPLE_TEXT},
        {"id": "s4", "name": "Carol", "problem": "count_islands",
         "language": "python", "code": _SAMPLE_TEXT + "\n# sentinel\n"},
    ]
    pairs = similar_pairs(rows, threshold=0.5)
    first = pairs[0] if pairs else {}
    ok = (bool(pairs)
          and first.get("a_id") == "s1" and first.get("b_id") == "s2"
          and first.get("similarity", 0.0) >= 0.5
          and first.get("a_name") == "Alice" and first.get("b_name") == "Alice"
          and similar_pairs(rows, threshold=0.5) == pairs)      # เสมอเดิมทุกครั้ง
    detail = (f"pairs={len(pairs)} first=({first.get('a_id')},{first.get('b_id')})"
              f" sim={first.get('similarity', 0.0):.4f} matches={first.get('matches')}")
    _case(results, "similar_pairs 4 แถว (คู่แรกถูก)", ok, detail)

    failed = [name for name, ok, _ in results if not ok]
    if failed:
        print(f"FAIL {len(failed)}/{len(results)}: " + ", ".join(failed))
        return 1
    print(f"PASS ทั้งหมด {len(results)}/{len(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(selftest())
