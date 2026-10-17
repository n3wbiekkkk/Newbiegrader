# วิธีทำโจทย์ (Making a Problem) — สูตรให้ AI ทำเหมือนกันทุกครั้ง

เอกสารนี้คือ "สูตร" สำหรับสร้างโจทย์ใหม่ 1 ข้อใน Newbiegrader ให้ได้ผลเหมือนกัน
ทุกครั้งไม่ว่า AI session ไหนจะทำ อ่านคู่กับ `agent.md` §7 (workflow เพิ่มโจทย์)

> เป้าหมาย: ทำตามลำดับในไฟล์นี้แล้วได้โจทย์ที่ `validate_problem.py` ผ่าน 0 FAIL,
> reference solution AC ทุกเทสต์, PDF ตรงสไตล์ reference และเทสต์แน่นพอที่โค้ดผิดจะตก

---

## 0. หลักการ (อย่าละเมิด)

- 1 โจทย์ = 1 โฟลเดอร์ `problems/<id>/` + reference solution `examples/<id>_ref.py`
- `<id>` = ตัวเล็ก snake_case อังกฤษ (`distinct_groups`, `kai_gai_codex`) — ห้ามเว้นวรรค/ตัวใหญ่
- **อย่าแก้ `grader.py` / `server.py` / `static/app.js` พร้อมกับงานอื่น** (คู่มือ agent.md §14 ข้อ 13)
- ตัวอย่างใน statement **ต้องตรงกับเทสต์ทุก byte** (canonical) — ไม่ใช่แค่ค่าตรง
- เทสต์ต้องแน่น: ถ้าโค้ดผิด (off-by-one ฯลฯ) ยัง AC = เทสต์หลวม ต้องเติมเทสต์ ไม่ใช่ลดเกณฑ์
- **`problems/` และ `examples/` ไม่ถูก versioned** (อยู่ใน `.gitignore`) — repo เป็น public
  และ source of truth คือ Supabase ไฟล์โจทย์/เฉลยอยู่บนดิสก์เพื่อทำงานและรันเทสต์เท่านั้น
  การเผยแพร่โจทย์ทำผ่าน import ขึ้น Supabase (ข้อ 9) ไม่ใช่ commit
- เริ่มงานให้ working tree สะอาดก่อน (`git status --short`)

---

## 1. หาเลขโจทย์ + สร้างโฟลเดอร์

```sh
cd <repo root>
git status --short                            # ต้องสะอาด (หรือรู้ว่าอะไร dirty อยู่และห้ามแตะ)
python3 tools/number_problems.py --list       # ดูเลขที่ใช้ไปแล้ว
python3 tools/number_problems.py --check      # ต้อง "ต่อเนื่องครบ" ไม่มีซ้ำ
mkdir -p problems/<id>/tests
```

- โจทย์สาธารณะ: เลขอยู่ในช่วง `1..` ต่อเนื่อง (ข้อใหม่ = สูงสุด + 1)
- โจทย์ชุดคอนเทสต์: ใส่ `"hidden": true` ใน config แล้วเลขจะไปอยู่ช่วง `1001..` ต่อเนื่อง
- ให้ `--assign` เป็นตัวกำหนดเลข (มันต่อท้ายให้ถูกช่วง) หรือเขียน `"no"` เองแล้ว `--check`

```sh
python3 tools/number_problems.py --assign     # ให้เลขกับข้อที่ยังไม่มี "no" (ต่อท้าย)
python3 tools/number_problems.py --check      # ยืนยัน ต่อเนื่องครบ
```

---

## 2. `config.json`

ไฟล์เดียวจบ ทุกฟิลด์มีความหมายตรงกับ `agent.md` §7.3:

```json
{
  "title": "ชื่อไทย (English Name)",
  "time_limit": 1.0,
  "memory_limit": 256,
  "checker": "token",
  "tolerance": 1e-6,
  "difficulty": "easy",
  "tags": ["Implementation", "Ad-hoc"],
  "samples": ["01", "02", "03"],
  "no": 63
}
```

| ฟิลด์ | กติกา |
|---|---|
| `title` | `ชื่อไทย (English)` — ใช้เป็นหัวเรื่องบน PDF (จาก config ไม่ใช่ `# ` ใน md) |
| `time_limit` | วินาที, validator บังคับ `0 < x <= 60` |
| `memory_limit` | MB, validator บังคับ `16..4096` (ถูก cap ที่ `MEMORY_CAP_MB` อีกชั้น) |
| `checker` | `token` = เทียบทีละโทเคน (ตัด whitespace) · `exact` = byte ต่อบรรทัด · `float` = ตาม `tolerance` · `decimal2` = ทศนิยม 2 ตำแหน่ง |
| `difficulty` | `easy` \| `medium` \| `hard` |
| `tags` | ต้องอยู่ใน KNOWN_TAGS ของ `grader.py` (Implementation, Math, Ad-hoc, String, Data Structure, DP, Sweepline, Greedy, DFS, Bitmasks, Binary Search, Graph, DSU, Sorting, Sliding Window, Divide and Conquer, Matrix Exponential, Tree, Fixed Parameter, Hashing, Geometry, NP, Recursive, Linear Algebra, Matching) |
| `samples` | ลิสต์ชื่อเทสต์ตัวอย่างสาธารณะ — **นโยบาย repo: 3 ชุดต่อข้อ** (`["01","02","03"]`) ต้องมีไฟล์จริง |
| `hidden` | ใส่ `true` เฉพาะโจทย์ชุดคอนเทสต์ (ไม่โชว์หน้า Task) |
| `no` | เลขโจทย์ บังคับ, ไม่ซ้ำ, `>= 1` |

> `checker` เป็น `token` แล้ว ต้องมั่นใจว่า **คำตอบมีแบบเดียว** ถ้าโจทย์ยอมหลายคำตอบ
> ต้องเขียนกติกาให้คำตอบเดียว (เช่นกำหนดลำดับ) มิฉะนั้นนักเรียนที่ตอบถูกแบบอื่นจะโดน WA

---

## 3. `statement.md`

### โครงบังคับ

````markdown
# ชื่อไทย (English Name)

<เนื้อเรื่องภาษาไทย มีตัวละคร/บริบท เหมือนโจทย์ข้ออื่น ไม่ย่อทิ้ง>

## Input
- บรรทัดแรก: ...
- ...

## Output
- ...

## ตัวอย่าง
```
input:
6
1 2 1 3 2 1

output:
3
1 2 3
1 2
1
```

## คำอธิบายตัวอย่าง
<อธิบายว่าทำไมตัวอย่างได้คำตอบนี้>

## Limits
- เวลา 1 วินาที, หน่วยความจำ 256 MB
````

### กติกา

- `# ...` บรรทัดแรกใช้แค่ความสวย — **หัวเรื่องจริงมาจาก `config.json` → `title`**
- **section เขียนเป็นภาษาอังกฤษ** (`## Input` / `## Output` / `## ตัวอย่าง` / `## Limits`
  / `## Subtasks`) เพราะ tool แปลหัวข้อเป็นไทยให้:
  - `Input` → "ข้อมูลนำเข้า"
  - `Output` → "ข้อมูลส่งออก"
  - `ตัวอย่าง` → "ตัวอย่างข้อมูลนำเข้าและข้อมูลส่งออก"
  - `Limits` → "ข้อจำกัด"
  - `Subtasks` → "การให้คะแนน"
- ตัวอย่าง **ต้องอยู่ใน fenced block** และมีป้าย `input:` และ `output:` — ถ้าไม่มีป้ายนี้
  validator จะ WARN "no fenced `input:`/`output:` sample block"
- **แต่ละข้อให้มีตัวอย่าง 3 ชุด** (แต่ละชุด = fenced block หนึ่งอัน ป้าย `input:`/`output:`)
  ตั้งชื่อเทสต์ `01`,`02`,`03` และประกาศใน `config.samples` — วิธีที่แนะนำคือดึงเทสต์ hidden
  ที่เล็ก/หลากหลายขึ้นมาเป็นตัวอย่าง แล้ว renumber hidden ที่เหลือให้ต่อเนื่อง `1001..`
  - **validator บังคับแล้ว (FAIL ไม่ใช่ WARN):** `config.samples` ต้องมี ≥ 3 ชุด
    (`MIN_SAMPLES`) และจำนวน fenced block ใน `statement.md` ต้องตรงกับจำนวนใน
    `config.samples` พร้อมทุกชื่อมี block ที่ match `tests/*.in|out` จริง
  - **ตัวอย่างต้องสั้น อ่านเข้าใจง่าย** — อย่าดึงเทสต์ยาว/stress test มาเป็นตัวอย่าง
    (validator จะ WARN "examples must be short" ถ้า sample มีเกิน 40 token)
    ให้เลือกเทสต์ hidden ที่เล็กที่สุดที่ยังมี output ต่างจากตัวอย่างเดิม
- **ห้ามมี section ใบ้วิธีทำ** (เช่น "แนวคิด", "复杂度") — ผิดกติกาโจทย์
- เขียนข้อความให้เหมือนเว็บ/tool render: ดูข้อ "การเขียน markdown ให้ PDF สวย" ด้านล่าง

### การเขียน markdown ให้ PDF สวย (ตัวแปลงของ `make_statement_tex.py`)

| เขียนใน md | ได้เป็น |
|---|---|
| `<=`, `>=`, `!=` | $\le$, $\ge$, $\ne$ |
| `n^2`, `10^9` | ยกกำลัง (math) |
| ตัวอักษรเดี่ยว `n`, `a_i` | อิทัลิกแบบ math (`$n$`) |
| `` `code` `` | Inconsolata (โค้ด) |
| `**หนา**` | ตัวหนา |
| `` `n` `` ที่เป็นตัวแปรเดี่ยว | math อิทัลิก (เหมือน `$n$`) |

- เนื้อเรื่อง/`## Input`/`## Output` ตั้งใจเป็น 17.3pt ส่วน math/latin ตั้งใจเล็ก (12pt)
  ตาม reference — **อย่าแก้**
- ตัวอักษรพิเศษ `\ { } $ & % # _` พิมพ์ตรง ๆ ได้ (tool escape ให้)

---

## 4. สร้าง PDF + verify ด้วยตาจริงทุกครั้ง

```sh
python3 tools/make_statement_tex.py <id> 2>&1 | grep -v "absolute path"
pdftotext problems/<id>/statement.pdf - | head -40
pdftoppm -png -r 60 problems/<id>/statement.pdf /tmp/pdfcheck/<id>
# แล้วเปิดดูภาพทุกหน้า (มีหัวเรื่อง + ตารางตัวอย่าง + footer "Newbiegrader | n")
```

- build ต้องขึ้น `wrote problems/<id>/statement.pdf (NN KB)`
- ถ้า build พัง: มักเป็น backslash หลุด (เช่น `\n`, `\mth` ใน comment ของ preamble)
  — เปิด log ของ tectonic ที่ tool พ่นออกมา
- **กับดักโจทย์เดิม**: ถ้าโจทย์นี้เคยมี `statement.pdf` อยู่แล้ว และ `statement.md`
  สั้นกว่าเนื้อหา PDF ตัวเต็ม การ regen จะทำให้เนื้อหาหาย ให้กันไว้ก่อน:

```sh
git show HEAD:problems/<id>/statement.pdf > /tmp/old.pdf 2>/dev/null || true
old=$(pdftotext /tmp/old.pdf - 2>/dev/null | wc -c)
python3 tools/make_statement_tex.py <id>
new=$(pdftotext problems/<id>/statement.pdf - 2>/dev/null | wc -c)
# ถ้า new < 0.8*old ให้ย้อนกลับ อย่าใช้ PDF ใหม่
git checkout -- problems/<id>/statement.pdf
```

---

## 5. `tests/` — อย่างน้อย 10 เคส

```sh
ls problems/<id>/tests
```

- **ตัวอย่างสาธารณะ**: ชื่อเลขเล็ก `01`, `02`, … และต้องถูกประกาศใน `config.samples`
- **เทสต์ลับ**: เริ่ม `1001` ขึ้นไป **ต่อเนื่อง** ไม่มี gap
- เลขเล็กที่ **ไม่ได้** ประกาศใน `samples` = **FAIL** (validator บังคับ)
- ต้องมีเทสต์ลับ ≥ 1 เคสเสมอ
- ทุกไฟล์ `.in` ต้องไม่ว่าง, UTF-8, ไม่มี `\r`

### ครอบคลุมอะไรบ้าง

1. ตัวอย่างใน statement (ชื่อตรงกัน เนื้อหา **byte-identical**)
2. edge: `n = 1`, ค่าต่ำสุด/สูงสุด, เคสว่าง (ถ้ามี)
3. ค่าสุดขีดตาม constraint (max `n`, max ค่า)
4. random แบบ seeded (ให้ reproducible)
5. กับดักโค้ดผิดยอดฮิต: off-by-one, ไม่ขยาย shorthand, ลืมเคสว่าง/สุดขีด, O(N²) กับ max input

### gen output ด้วย ref solution เสมอ (อย่าพิมพ์มือ)

```sh
python3 - <<'PY'
import subprocess
from pathlib import Path
tests = Path('problems/<id>/tests')
ref = Path('examples/<id>_ref.py')
cases = {
    "01": "6\n1 2 1 3 2 1\n",
    "1001": "5\n1 2 3 4 5\n",
    # ... อย่างน้อย 10 เคส
}
for name, data in cases.items():
    (tests / f"{name}.in").write_text(data, encoding="utf-8")
    out = subprocess.run(["python3", str(ref)], input=data,
                         capture_output=True, text=True).stdout
    (tests / f"{name}.out").write_text(out, encoding="utf-8")
    print(name, "ok")
PY
```

> ตัวอย่างใน `01.in`/`01.out` ต้องตรงกับ fenced block ใน statement ทุก byte
> (validator เทียบ token ก่อน แล้วเตือนถ้า canonical ไม่ตรง — ถ้าเตือน = ยังไม่ผ่าน)

---

## 6. Reference solution

- วางที่ `examples/<id>_ref.py`
- Python stdlib ล้วน อ่าน `sys.stdin` เขียน `sys.stdout`
- ต้อง **AC ทุกเทสต์**

```python
import sys

def solve():
    data = sys.stdin.read().split()
    if not data:
        return
    # ... อ่าน input และเขียนคำตอบ
    sys.stdout.write("...\n")

solve()
```

---

## 7. ตรวจ 3 ชั้น

```sh
python3 grader.py run <id> examples/<id>_ref.py   # ต้อง ACCEPTED N/N
python3 tools/validate_problem.py <id>            # ต้อง OK #<no> ... 0 FAIL
```

- **ทดสอบว่าเทสต์แน่น**: เขียน solution ผิด **ตั้งใจ** (เช่น off-by-one) ลง `/tmp/bad.py`
  แล้ว `python3 grader.py run <id> /tmp/bad.py` ต้อง **ไม่ AC** (ได้ WA ที่เคสที่ควรตก)
  ถ้า AC = เทสต์หลวม ให้เติมเทสต์
- `validate_problem.py` จะรัน ref กับทุกเทสต์ด้วย `grader.judge_test` ให้เอง
  และ **FAIL** ถ้า sample ไม่ครบ 3 ชุด หรือจำนวน sample ใน statement ไม่ตรงกับ `config.samples`

---

## 8. ชุดตรวจก่อน commit (บังคับ)

```sh
python3 tools/number_problems.py --check
python3 tools/validate_problem.py            # ทั้งชุด
python3 -m unittest discover -s tests -v     # ต้องเขียว (ยกเว้น fail ที่เป็นข้อจำกัดเครื่องนี้)
python3 -m compileall -q grader.py server.py judge_runner.py tools
```

- ถ้าแก้ frontend เพิ่ม: `node --check static/app.js && node tools/check_frontend.js && node tools/check_styles.js`
- restart server แล้วเทสบนเว็บ (ค้นหาด้วยเลขโจทย์ได้)

---

## 9. เผยแพร่ + commit

`problems/` และ `examples/` **ไม่ถูก versioned** (อยู่ใน `.gitignore`) — `git add` ไฟล์
เหล่านี้จะไม่ติด ดังนั้นการ "ส่งโจทย์" คือ **import ขึ้น Supabase** ไม่ใช่ commit

```sh
# 1) ตรวจก่อน import (ไม่เขียนอะไร) — ต้องมี service_role key (server-side เท่านั้น)
SUPABASE_URL=... SUPABASE_KEY=<service_role> \
  python3 tools/import_problems_supabase.py --problem <id> --dry-run

# 2) import จริง (idempotent): metadata + public samples/statement ขึ้น Postgres,
#    hidden tests + statement.pdf ขึ้น Storage bucket judge-assets (private)
SUPABASE_URL=... SUPABASE_KEY=<service_role> \
  python3 tools/import_problems_supabase.py --problem <id>
```

- commit (git) ใช้เฉพาะเวลาที่แก้ **code/docs/tools** เท่านั้น — รูป `Area: subject`
  ```sh
  git add docs/making-problems.md tools/...    # เฉพาะไฟล์ที่ track ได้
  git commit -m "Docs: ..."                     # เช่น "Frontend: ...", "Statements: ..."
  ```
- **อย่า `git add -A`** — `problems/`/`examples/` ถูก ignore อยู่แล้ว และอาจมีไฟล์ dirty ของงานอื่นค้าง
- หลัง import แล้ว restart server + เทสบนเว็บ (ค้นด้วยเลขโจทย์ได้)

---

## 10. กับดักที่เจอจริง (อ่านก่อนทุกครั้ง)

1. **statement.md ไม่มี fenced `input:`/`output:`** → validator WARN
   "no fenced sample block" และ `config.samples` จะอ้างเทสต์ไม่ได้
2. **เทสต์เลขเล็กที่ไม่อยู่ใน `samples`** → FAIL (`small numbers are public samples only`)
3. **ไม่มีเทสต์ลับ** → FAIL (`at least one hidden test (1001+) is required`)
4. **ตัวอย่าง statement ไม่ตรงเทสต์** → WARN (whitespace ต่างก็เตือน) = ยังไม่ผ่าน
5. **regen PDF จาก md ที่สั้นกว่าเนื้อหาเต็ม** → เนื้อหาหาย ให้ใช้ตัวกันในข้อ 4
6. **แก้โจทย์แล้วเว็บยังเก่า** → ลืม restart server (problems โหลดตอน boot)
7. **คู่มือ agent.md §7.4 ข้อ 4 เขียนว่า validator สร้าง solution ผิดเอง** — จริง ๆ
   `validate_problem.py` **ไม่ได้** ทำขั้นนี้ ให้ทำมือด้วย `grader.py run /tmp/bad.py` (ข้อ 7)
8. **โจทย์หลายคำตอบ + checker `token`** → คำตอบที่ไม่ตรง expected จะโดน WA
   ต้องเขียนกติกาให้คำตอบเดียว หรือใช้ checker เฉพาะ (ถ้ามี)

---

## 11. เช็คลิสต์ย่อ (ทำเครื่องหมายก่อน commit)

- [ ] `git status` รู้ว่าอะไรแตะ/ห้ามแตะ
- [ ] `problems/<id>/config.json` ครบทุกฟิลด์ + `no` ไม่ซ้ำ (`number_problems.py --check`)
- [ ] `statement.md`: เรื่องครบ + `## Input`/`## Output`/`## ตัวอย่าง` (3 fenced blocks)/`## Limits` + ไม่มี section ใบ้
- [ ] build PDF แล้ว + `pdftotext` + เปิดดูภาพทุกหน้า
- [ ] `tests/` ≥ 10: ตัวอย่าง `01`,`02`,`03` (ตรง statement byte-identical) + `1001..` ต่อเนื่อง
- [ ] `examples/<id>_ref.py` AC ทุกเทสต์
- [ ] `grader.py run` = ACCEPTED N/N, solution ผิด = WA
- [ ] `validate_problem.py <id>` = 0 FAIL (เคลียร์ WARN ที่เกี่ยวกับ sample ด้วย เพราะ WARN ไม่ทำให้ exit != 0)
- [ ] `unittest` + `number_problems.py --check` + `compileall` ผ่าน
- [ ] `import_problems_supabase.py --problem <id> --dry-run` ผ่าน (เมื่อจะเผยแพร่)
- [ ] commit เฉพาะ code/docs/tools ที่แก้ (`problems/`/`examples/` ไม่ถูก versioned)
