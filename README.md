# Newbiegrader (โหดจริง ไม่ติงนัง)

Grader แบบ stdlib-only (ไม่ต้องลง lib) รองรับ `.py .cpp .c .java .js .go .rs`
ตรวจแบบโหด: Time Limit / Memory Limit (RLIMIT บน macOS/Linux), diff แสดง whitespace,
กับดัก hidden tests (ค่าใหญ่, case-sensitive, trailing space, O(n²) โดน TLE)

## เว็บ (ส่งโค้ดผ่านเบราว์เซอร์)

Stack: FastAPI + Uvicorn (backend) + HTML/CSS/JS ไม่ต้อง build (frontend).
รองรับ Python / C / C++ ส่งได้ 2 แบบ: วางโค้ดใน editor หรือแนบไฟล์ (คลิก/ลากไฟล์ลง dropzone)
หน้าเว็บมี 7 วิว: Home (สถิติ) / Tasks (การ์ดโจทย์ + sidebar All/Tried/Solved/Tag Filter) / Task (Statement/Submit/Submissions/My + Your Score) / Archive / Leaderboard / History (ของตัวเอง) / Settings / Login

```bash
pip3 install --user -r requirements.txt
python3 server.py                  # http://127.0.0.1:8000
python3 server.py --port 8080
```

## Deploy (frontend + backend แยกกัน)

อย่า deploy ทั้ง repo ด้วย preset FastAPI บน serverless — ไม่มี compiler (C/C++ คอมไพล์ไม่ได้),
filesystem เขียนไม่ได้นอกจาก `/tmp`, โดนตัด timeout กลางคัน แผนที่ถูก:

**1. Backend (judge) ขึ้น host ที่มี Docker** — ปัจจุบันใช้ justrunmy (push `HEAD:deploy` ไป git remote ของมัน)
```bash
git push <justrunmy-git-url> HEAD:deploy
```
สำรอง: Render (Blueprint + `render.yaml`) / Fly.io / VPS แล้วตั้ง env ตามต้องการ

**2. Frontend** — ปัจจุบันใช้ Cloudflare Pages:
- Connect Git → repo นี้, Framework None, build ว่าง, output = `static`
  (proxy `/api` ผ่าน `functions/api/[[proxy]].js` อัตโนมัติ ไม่ต้องตั้งเพิ่ม)
- เหลือ `static/vercel.json` ไว้เผื่อย้อนกลับ (legacy)

config.js ปล่อย `""` ไว้ (same-origin ผ่าน proxy) — ถ้าโฮสต์ frontend ที่ไม่มี proxy ค่อยชี้ URL backend + ตั้ง `GRADER_CORS_ORIGINS`

รัน local ทั้งก้อนแบบเดิมได้อยู่ (`python3 server.py` — same origin, ไม่ต้องมี CORS)

## Google Login + รหัสผ่าน (บังคับ login ก่อนส่ง)

1. Google Auth Platform → Create OAuth client (Web application)
   - Authorised redirect URIs (ใส่ทั้งสองบรรทัด):
     `https://gradernew.pages.dev/api/auth/callback`
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
GOOGLE_REDIRECT_URI=https://gradernew.pages.dev/api/auth/callback
FRONTEND_URL=https://gradernew.pages.dev
SESSION_SECRET=<สุ่ม 64 hex>
SESSION_SAMESITE=lax
SESSION_SECURE=true
```
(local: `SESSION_SAMESITE=lax SESSION_SECURE=false`)
4. หน้าเว็บมีหน้า Login: สมัครด้วยอีเมล+รหัสผ่าน (PBKDF2 210k iterations, rate-limit กัน brute force) หรือ Sign in with Google ก็ได้ — login แล้วส่งได้เลย ไม่ต้องกรอกชื่อ (ใช้ชื่อโปรไฟล์อัตโนมัติ) ประวัติดูของตัวเองได้ด้วยติ๊ก "ของฉัน"
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
- `POST /api/submit` (multipart: `problem`, `language`, `code` หรือ `file`; ต้อง login) — ตรวจแล้วตอบ JSON ทันที

```bash
curl -F problem=warpz -F language=python -F code='print("YES")' http://127.0.0.1:8000/api/submit
```

## โครง
```
grader.py
problems/<id>/config.json      # time_limit, memory_limit, checker, difficulty, tags (ดู KNOWN_TAGS)
problems/<id>/statement.pdf      # โจทย์ต้นฉบับ (ถ้ามี)
problems/<id>/statement.md
problems/<id>/tests/*.in|*.out
examples/                      # reference solution ประจำข้อ (*_ref.py)
server.py                      # FastAPI backend (reuse grader.py)
static/                        # frontend: index.html, styles.css, app.js (?v=N กัน cache)
functions/api/[[proxy]].js     # Cloudflare Pages Function proxy /api
supabase/schema.sql            # schema + migration ทั้งหมด
agent.md                       # คู่มือ AI
requirements.txt               # fastapi, uvicorn, python-multipart, supabase, itsdangerous
```

## ใช้ยังไง
```bash
python3 grader.py list
python3 grader.py info warpz
python3 grader.py run warpz examples/warpz_ref.py
python3 grader.py run mana_crystal examples/mana_crystal_ref.py --strict --stop-on-fail
python3 grader.py run napprime examples/napprime_ref.cpp   # C++ ก็ได้ (auto compile -O2)
```

## โจทย์ (PDF workflow)

โจทย์มาจากไฟล์ PDF: ส่ง PDF มา จะสร้าง `problems/<id>/` ให้ ประกอบด้วย
`statement.pdf` (ต้นฉบับ) + `statement.md` + `config.json` + `tests/` (~10 testcases)
หน้าเว็บมีปุ่ม open PDF statement + ระบบ filter (ค้นหา/ระดับ/tag)

| id | ชื่อ | ระดับ | tests |
|----|------|--------|-------|
| `mana_crystal` | ย่อภาพผลึกมานา | medium | 15 |
| `posn_server_passcode` | รหัสผ่านเซิร์ฟเวอร์ สอวน. | medium | 16 |
| `warpz` | วาร์ปอวกาศ | easy | 15 |
| `napprime` | Napprime นับจำนวนเฉพาะ (TL 0.5s / MEM 32MB) | easy | 16 |
| `bake_a_cake` | อบเค้ก (TL 0.5s / MEM 32MB) | easy | 16 |
| `min_distance` | ระยะทางรวมน้อยสุด (TL 1s / MEM 64MB) | medium | 14 |
| `largest_rectangle` | สี่เหลี่ยมใหญ่สุดในฮิสโตแกรม (TL 1s / MEM 64MB) | medium | 15 |
| `blood_moon` | คืนพระจันทร์สีเลือด (ใช้อะไรก็ได้ ไม่บังคับ pointer) | easy | 15 |
| `dna` | จำลอง DNA (ใช้อะไรก็ได้ ไม่บังคับ pointer) | easy | 15 |
| `flashback` | ไม่ได้ลืมแค่ไม่ได้เจอ | medium | 15 |
| `rotation` | เธอหมุนรอบฉัน ฉันหมุนรอบเธอ | easy | 15 |
| `shadow` | Shadow เงาปะทะมังกร (TL 1s / MEM 64MB) | easy | 15 |
| `panda` | แพนด้าหาส้มโอ (TL 1s / MEM 512MB) | medium | 15 |
| `sing_contest` | อันดับประกวดร้องเพลง | easy | 15 |
| `candy_sales` | ยอดขายสายไหมรายวัน | easy | 15 |
| `snack_budget` | งบจำกัดแต่อยากกินเยอะ | easy | 14 |
| `stage_show` | ตารางการแสดงบนเวที | easy | 15 |
| `ticket_queue` | คิวซื้อตั๋วคอนเสิร์ต | easy | 15 |
| `club_vote` | เลือกตั้งประธานชมรมดนตรี | easy | 15 |
| `stage_lights` | จุดไฟประดับใกล้เวทีที่สุด | easy | 15 |
| `boat_crossing` | เรือพายข้ามคลอง | easy | 14 |
| `find_max` | หาค่ามากที่สุดด้วยฟังก์ชัน (ใช้อะไรก็ได้) | easy | 14 |
| `sum_even` | ผลรวมของเลขคู่ (ใช้อะไรก็ได้) | easy | 14 |
| `prime_check` | ตรวจจำนวนเฉพาะ (ใช้อะไรก็ได้) | easy | 14 |
| `count_even_odd` | นับเลขคู่และเลขคี่ (ใช้อะไรก็ได้) | easy | 14 |
| `digit_sum` | ผลรวมเลขโดด (ใช้อะไรก็ได้) | easy | 14 |
| `digital_root` | รากดิจิทัล (ใช้อะไรก็ได้) | easy | 14 |
| `dec_to_bin` | แปลงเลขฐานสิบเป็นฐานสอง (ใช้อะไรก็ได้) | easy | 14 |
| `dec_to_hex` | แปลงเลขฐานสิบเป็นฐานสิบหก (ใช้อะไรก็ได้) | easy | 14 |
| `hidden_digit_sum` | ผลรวมตัวเลขที่ซ่อนในข้อความ (ใช้อะไรก็ได้) | easy | 14 |
| `hanoi` | หอคอยฮานอย (ใช้อะไรก็ได้) | easy | 10 |
| `power_recur` | ยกกำลังด้วยการเรียกตัวเอง (ใช้อะไรก็ได้) | easy | 14 |
| `fib_sum` | ผลรวมลำดับฟีโบนัชชี (ใช้อะไรก็ได้) | easy | 14 |
| `array_min_sum` | ค่าต่ำสุดและผลรวมของอาร์เรย์ (ใช้อะไรก็ได้) | easy | 14 |
| `maze_score` | เขาวงกตเก็บคะแนน (ใช้อะไรก็ได้) | medium | 14 |
| `swordsmith` | ช่างตีดาบแห่งวังหลวง (ใช้อะไรก็ได้) | easy | 14 |
| `cookie_share` | แบ่งคุกกี้ ห.ร.ม. ค.ร.น. (ใช้อะไรก็ได้) | easy | 14 |
| `mirror_pair` | เลขสะท้อนคู่ (ใช้อะไรก็ได้) | easy | 14 |
| `collatz_max` | ลำดับคอลลาตซ์ที่ยาวที่สุด (ใช้อะไรก็ได้) | easy | 14 |
| `library_code` | ซ่อมรหัสสมาชิกห้องสมุด (ใช้อะไรก็ได้) | easy | 14 |
| `fraction_add` | บวกเศษส่วนให้เป็นเศษส่วนอย่างต่ำ (ใช้อะไรก็ได้) | easy | 14 |
| `binary_strings` | สายไบนารีที่ไม่มีเลข 1 ติดกัน (ใช้อะไรก็ได้) | easy | 15 |
| `broken_stairs` | บันไดขั้นพัง (ใช้อะไรก็ได้) | medium | 14 |
| `exact_budget` | ซื้อของให้พอดีงบ (ใช้อะไรก็ได้) | medium | 14 |
| `count_islands` | นับเกาะ (ใช้อะไรก็ได้) | medium | 18 |
| `queens_holes` | ราชินีบนกระดานมีหลุม (ใช้อะไรก็ได้) | medium | 14 |
| `thai_time` | ระบบบอกเวลาภาษาไทย | easy | 15 |

## Verdicts
`AC` ผ่าน / `WA` + diff (·=space) / `TLE` เกินเวลา / `MLE` หน่วยความจำ /
`RE` traceback บรรทัดสุดท้าย / `CE` compile ไม่ผ่าน

คะแนน OI: `100 * passed/total`, exit code 0 = เต็ม 100 เท่านั้น

## เพิ่มโจทย์เอง
```bash
mkdir -p problems/myprob/tests
# config.json: {"title":"...","time_limit":1.0,"memory_limit":256,"checker":"token",
#               "difficulty":"easy|medium|hard","tags":["Math","Greedy"]}  (tags ดู KNOWN_TAGS ใน grader.py)
# ใส่ 01.in / 01.out, 02.in / 02.out ... (+ statement.pdf ได้) แล้ว run ได้เลย
```

## หมายเหตุความโหด
- Memory limit ใช้ `RLIMIT_AS` (ประมาณ, บน macOS วัด peak ด้วย `getrusage`)
- Time limit คือ wall-time (`communicate(timeout=...)`) + `RLIMIT_CPU` กัน loop อนันต์
- `--strict` = byte-exact (whitespace nazi mode), default ใช้ checker ตาม config
