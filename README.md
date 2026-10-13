# Brutal CP Grader (โหดจริง ไม่ติงนัง)

Grader แบบ stdlib-only (ไม่ต้องลง lib) รองรับ `.py .cpp .c .java .js .go .rs`
ตรวจแบบโหด: Time Limit / Memory Limit (RLIMIT บน macOS/Linux), diff แสดง whitespace,
กับดัก hidden tests (ค่าใหญ่, case-sensitive, trailing space, O(n²) โดน TLE)

## เว็บ (ส่งโค้ดผ่านเบราว์เซอร์)

Stack: FastAPI + Uvicorn (backend) + HTML/CSS/JS ไม่ต้อง build (frontend).
รองรับ Python / C / C++ ส่งได้ 2 แบบ: วางโค้ดใน editor หรือแนบไฟล์ (คลิก/ลากไฟล์ลง dropzone)

```bash
pip3 install --user -r requirements.txt
python3 server.py                  # http://127.0.0.1:8000
python3 server.py --port 8080
```

## Deploy (Vercel + backend แยกกัน)

อย่า deploy ทั้ง repo ด้วย preset FastAPI บน Vercel — serverless ไม่มี compiler (C/C++ คอมไพล์ไม่ได้),
filesystem เขียนไม่ได้นอกจาก `/tmp`, โดนตัด timeout กลางคัน แผนที่ถูก:

**1. Backend (judge) ขึ้น host ที่มี Docker** — Render / Fly.io / Railway / VPS
```bash
# Render: New -> Blueprint -> เลือก repo นี้ (ใช้ render.yaml)
# แล้วตั้ง env: GRADER_CORS_ORIGINS=https://<ชื่อโปรเจกต์>.vercel.app
```
หรือ Docker เอง:
```bash
docker build -t brutal-grader .
docker run -e GRADER_CORS_ORIGINS=https://<ชื่อโปรเจกต์>.vercel.app -p 8000:8000 brutal-grader
```

**2. Frontend ขึ้น Vercel** — ในหน้า Import ตั้ง:
- Framework Preset: **Other** (ไม่ใช่ FastAPI)
- Root Directory: **`static`**
- Build/Output: ไม่ต้องตั้ง (static ล้วน)

แล้วแก้ `static/config.js` ชี้ไป backend:
```js
window.GRADER_API_BASE = "https://brutal-grader-api.onrender.com";
```
commit + push — Vercel redeploy อัตโนมัติ

รัน local ทั้งก้อนแบบเดิมได้อยู่ (`python3 server.py` — same origin, ไม่ต้องมี CORS)

## Supabase (ประวัติส่ง + สถิติ, optional)

ไม่ตั้ง = เว็บทำงานปกติแค่ไม่มี history ตั้งแล้วทุก submission จะถูกบันทึกพร้อมดูย้อนหลังได้

1. สร้างโปรเจกต์ที่ supabase.com → SQL Editor → รันไฟล์ `supabase/schema.sql`
2. เอา Project URL + **service_role key** (Settings → API — อันนี้อยู่ฝั่ง server เท่านั้น ห้ามโผล่ frontend)
3. ตั้ง env ที่ backend:
```bash
# local
export SUPABASE_URL=https://xyzcompany.supabase.co
export SUPABASE_KEY=eyJ...   # service_role
python3 server.py
# Render/host: เพิ่ม 2 env นี้ใน dashboard แล้ว redeploy
```
4. หน้าเว็บจะมี section History (filter ตามข้อได้) + สถิติ best/avg ต่อข้อ — API: `GET /api/history`, `GET /api/history/{id}`, `GET /api/stats`
- `GET /api/health` — สถานะ + รายชื่อโจทย์
- `GET /api/languages` — ภาษาที่รองรับ (python/c/cpp)
- `GET /api/problems` — รายการโจทย์
- `GET /api/problems/{id}` — โจทย์ + statement
- `POST /api/submit` (multipart: `problem`, `language`, `code` หรือ `file`) — ตรวจแล้วตอบ JSON ทันที

```bash
curl -F problem=aplusb -F language=python -F code='import sys
print(sum(map(int, sys.stdin.read().split())))' http://127.0.0.1:8000/api/submit
```

## โครง
```
grader.py
problems/<id>/config.json      # time_limit, memory_limit, checker (token|exact|float)
problems/<id>/statement.md
problems/<id>/tests/*.in|*.out
examples/                      # โค้ดถูก/ผิด/TLE ไว้ลอง
server.py                      # FastAPI backend (reuse grader.py)
static/                        # frontend: index.html, styles.css, app.js
requirements.txt               # fastapi, uvicorn, python-multipart
```

## ใช้ยังไง
```bash
python3 grader.py list
python3 grader.py info aplusb
python3 grader.py run aplusb examples/aplusb_correct.py
python3 grader.py run fizzbuzz examples/fizzbuzz_correct.py -v
python3 grader.py run palindrome examples/palindrome_correct.py --strict --stop-on-fail
python3 grader.py run aplusb examples/aplusb_correct.cpp   # C++ ก็ได้ (auto compile -O2)
```

## โจทย์ที่มี (ง่าย 3 ข้อ แต่ test โหด)
| id | ชื่อ | กับดัก |
|----|------|--------|
| `aplusb` | A+B (`-1e18..1e18`) | `int` แตก, whitespace, 7 tests |
| `fizzbuzz` | FizzBuzz ถึง N=100000 | `Fizz` ตัวพิมพ์, trailing space (checker=exact), TLE trap, 5 tests |
| `palindrome` | Palindrome ยาวถึง 1e6 | `Aa`→NO, ว่าง→YES, space นับด้วย, 8 tests |

## Verdicts
`AC` ผ่าน / `WA` + diff (·=space) / `TLE` เกินเวลา / `MLE` หน่วยความจำ /
`RE` traceback บรรทัดสุดท้าย / `CE` compile ไม่ผ่าน

คะแนน OI: `100 * passed/total`, exit code 0 = เต็ม 100 เท่านั้น

## เพิ่มโจทย์เอง
```bash
mkdir -p problems/myprob/tests
# config.json: {"title":"...","time_limit":1.0,"memory_limit":256,"checker":"token"}
# ใส่ 01.in / 01.out, 02.in / 02.out ... แล้ว run ได้เลย
```

## หมายเหตุความโหด
- Memory limit ใช้ `RLIMIT_AS` (ประมาณ, บน macOS วัด peak ด้วย `getrusage`)
- Time limit คือ wall-time (`communicate(timeout=...)`) + `RLIMIT_CPU` กัน loop อนันต์
- `--strict` = byte-exact (whitespace nazi mode), default ใช้ checker ตาม config
