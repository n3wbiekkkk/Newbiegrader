# Newbiegrader (โหดจริง ไม่ติงนัง)

Grader แบบ stdlib-only (ไม่ต้องลง lib) รองรับ `.py .cpp .c .java .js .go .rs`
ตรวจแบบโหด: Time Limit / Memory Limit (RLIMIT บน macOS/Linux), diff แสดง whitespace,
กับดัก hidden tests (ค่าใหญ่, case-sensitive, trailing space, O(n²) โดน TLE)

## เว็บ (ส่งโค้ดผ่านเบราว์เซอร์)

Stack: FastAPI + Uvicorn (backend) + HTML/CSS/JS ไม่ต้อง build (frontend).
รองรับ Python / C / C++ ส่งได้ 2 แบบ: วางโค้ดใน editor หรือแนบไฟล์ (คลิก/ลากไฟล์ลง dropzone)
หน้าเว็บมี 4 วิว: Home (สถิติ) / Tasks (ตารางโจทย์ + ค้นหา/กรองระดับ/tag) / Task (โจทย์ + ส่ง + ผล) / History

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

## Google Login + รหัสผ่าน (บังคับ login ก่อนส่ง)

1. Google Auth Platform → Create OAuth client (Web application)
   - Authorised redirect URIs (ใส่ทั้งสองบรรทัด):
     `https://gradernew-static.vercel.app/api/auth/callback`
     `https://grader.n.onjrnm.vip/api/auth/callback`
   - JavaScript origins: ปล่อยว่างได้
2. รัน migration คอลัมน์ email:
```sql
alter table submissions add column if not exists user_email text not null default '';
```
3. ตั้ง env ที่ backend + restart:
```
GOOGLE_CLIENT_ID=....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
GOOGLE_REDIRECT_URI=https://gradernew-static.vercel.app/api/auth/callback
FRONTEND_URL=https://<vercel-app>
SESSION_SECRET=<สุ่ม 64 hex>
SESSION_SAMESITE=none
SESSION_SECURE=true
```
(local: `SESSION_SAMESITE=lax SESSION_SECURE=false`)
4. หน้าเว็บมีหน้า Login: สมัครด้วยอีเมล+รหัสผ่าน (scrypt, rate-limit กัน brute force) หรือ Sign in with Google ก็ได้ — login แล้วส่งได้เลย ไม่ต้องกรอกชื่อ (ใช้ชื่อโปรไฟล์อัตโนมัติ) ประวัติดูของตัวเองได้ด้วยติ๊ก "ของฉัน"
5. หน้า Settings (ต้อง login): เปลี่ยน display name (ชื่อที่โชว์ใน history) + เลือกภาษา default — เก็บในตาราง `profiles` (ดู `supabase/schema.sql`)

Migration ตาราง `users` (รันใน SQL Editor):
```sql
create table if not exists users (
  email text primary key,
  name text not null default '',
  password_hash text not null default '',
  created_at timestamptz not null default now()
);
alter table users enable row level security;
create index if not exists submissions_user_time
  on submissions (user_email, created_at desc);
```

## Report / Leaderboard / Dark mode

- หน้า task มีแท็บ Submissions (ของทุกคน) + ปุ่ม Report แจ้งโจทย์พัง (statement/test/อื่น ๆ)
- หน้า Archive: browse ตาม tag + กลุ่มตามระดับ | หน้า Leaderboard: คะแนนรวมรายคน
- ปุ่ม dark/light มุมขวาบน (จำค่าที่เลือกไว้)
- Migration ตาราง `reports`:
```sql
create table if not exists reports (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  problem text not null,
  kind text not null default 'other',
  message text not null default '',
  user_email text not null default '',
  name text not null default '',
  status text not null default 'open'
);
create index if not exists reports_problem_time
  on reports (problem, created_at desc);
alter table reports enable row level security;
```
- env เพิ่มที่ backend: `ADMIN_EMAILS=a@x.com,b@y.com` (ดู + ปิดรีพอร์ตได้ในหน้า Settings)

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

Migration (ถ้าสร้างตารางก่อนคอลัมน์ `name`): รันใน SQL Editor
```sql
alter table submissions add column if not exists name text not null default '';
```
- `GET /api/health` — สถานะ + รายชื่อโจทย์
- `GET /api/languages` — ภาษาที่รองรับ (python/c/cpp)
- `GET /api/problems` — รายการโจทย์
- `GET /api/problems/{id}` — โจทย์ + statement
- `POST /api/submit` (multipart: `problem`, `language`, `name` (บังคับ), `code` หรือ `file`) — ตรวจแล้วตอบ JSON ทันที

```bash
curl -F problem=aplusb -F language=python -F code='import sys
print(sum(map(int, sys.stdin.read().split())))' http://127.0.0.1:8000/api/submit
```

## โครง
```
grader.py
problems/<id>/config.json      # time_limit, memory_limit, checker (token|exact|float)
problems/<id>/statement.pdf      # โจทย์ต้นฉบับ (ถ้ามี)
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

## โจทย์ (PDF workflow)

โจทย์มาจากไฟล์ PDF: ส่ง PDF มา จะสร้าง `problems/<id>/` ให้ ประกอบด้วย
`statement.pdf` (ต้นฉบับ) + `statement.md` + `config.json` + `tests/` (~10 testcases)
หน้าเว็บมีปุ่ม open PDF statement + ระบบ filter (ค้นหา/ระดับ/tag)

| id | ชื่อ | ระดับ | tests |
|----|------|--------|-------|
| `mana_crystal` | ย่อภาพผลึกมานา | medium | 10 |
| `posn_server_passcode` | รหัสผ่านเซิร์ฟเวอร์ สอวน. | medium | 10 |
| `warpz` | วาร์ปอวกาศ | easy | 10 |
| `napprime` | Napprime นับจำนวนเฉพาะ (TL 0.5s / MEM 32MB) | easy | 10 |
| `bake_a_cake` | อบเค้ก (TL 0.5s / MEM 32MB) | easy | 10 |
| `min_distance` | ระยะทางรวมน้อยสุด (TL 1s / MEM 64MB) | medium | 10 |

## Verdicts
`AC` ผ่าน / `WA` + diff (·=space) / `TLE` เกินเวลา / `MLE` หน่วยความจำ /
`RE` traceback บรรทัดสุดท้าย / `CE` compile ไม่ผ่าน

คะแนน OI: `100 * passed/total`, exit code 0 = เต็ม 100 เท่านั้น

## เพิ่มโจทย์เอง
```bash
mkdir -p problems/myprob/tests
# config.json: {"title":"...","time_limit":1.0,"memory_limit":256,"checker":"token",
#               "difficulty":"easy|medium|hard","tags":["math","impl"]}
# ใส่ 01.in / 01.out, 02.in / 02.out ... (+ statement.pdf ได้) แล้ว run ได้เลย
```

## หมายเหตุความโหด
- Memory limit ใช้ `RLIMIT_AS` (ประมาณ, บน macOS วัด peak ด้วย `getrusage`)
- Time limit คือ wall-time (`communicate(timeout=...)`) + `RLIMIT_CPU` กัน loop อนันต์
- `--strict` = byte-exact (whitespace nazi mode), default ใช้ checker ตาม config
