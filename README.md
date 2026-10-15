# Newbiegrader (โหดจริง ไม่ติงนัง)

Grader แบบ stdlib-only (ไม่ต้องลง lib) รองรับ `.py .cpp .c .java .js .go .rs`
ตรวจแบบโหด: Time Limit / Memory Limit (RLIMIT บน macOS/Linux), diff แสดง whitespace,
กับดัก hidden tests (ค่าใหญ่, case-sensitive, trailing space, O(n²) โดน TLE)

## เว็บ (ส่งโค้ดผ่านเบราว์เซอร์)

Stack: FastAPI + Uvicorn (backend) + HTML/CSS/JS ไม่ต้อง build (frontend).
รองรับ Python / C / C++ ส่งได้ 2 แบบ: วางโค้ดใน editor หรือแนบไฟล์ (คลิก/ลากไฟล์ลง dropzone)
หน้าเว็บมีวิว: Home (สถิติ) / Tasks (การ์ดโจทย์ + sidebar All/Tried/Solved/Tag Filter) / Task (Statement/Submit/Submissions/My/Run + Your Score) / Contests (+ scoreboard) / Archive / Leaderboard / History (ของตัวเอง) / Settings (รวมเครื่องมือ admin) / Login

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
4. หน้าเว็บมีหน้า Login: สมัครด้วยอีเมล+รหัสผ่าน (PBKDF2 210k iterations) หรือ Sign in with Google ก็ได้ — login แล้วส่งได้เลย ไม่ต้องกรอกชื่อ (ใช้ชื่อโปรไฟล์อัตโนมัติ) ประวัติดูของตัวเองได้ด้วยติ๊ก "ของฉัน"
   - **rate limit เป็นรายบัญชี ไม่ใช่ราย IP**: ทุกคนที่เข้าเว็บผ่าน Pages proxy จะถูกมองเป็น IP เดียวกัน (Cloudflare เขียนทับ IP ต้นทาง) ถ้าจำกัดต่อ IP ทั้งเว็บจะติด "too many attempts" พร้อมกันหลัง 20 ครั้ง — ตอนนี้ผิดรหัสได้ 8 ครั้ง/15 นาทีต่อบัญชี (ล็อกอินถูก = รีเซ็ต) และมีเพดาน 200 ครั้ง/5 นาทีต่อ IP ไว้กัน flood เท่านั้น
   - ถ้าผู้ใช้ "หลุด login ทุกครั้งที่ deploy" ให้เช็คว่าตั้ง `SESSION_SECRET` ใน panel แล้ว (ไม่ตั้ง = สุ่มใหม่ทุก boot → session ตายทั้งหมด)
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

## คอนเทสต์ / ตรวจซ้ำ / ตรวจการก็อป (admin)

- **Contest mode**: `GET /api/contests`, `GET /api/contests/{id}` (มี scoreboard), `POST /api/contests`
  (admin, upsert), `DELETE /api/contests/{id}` — ตาราง `contests` เก็บ `starts_at/ends_at`,
  `problems` (jsonb), `freeze_minutes`, `show_samples`, `hide_from_tasks`
  - ส่งงานเข้าคอนเทสต์: เพิ่มฟิลด์ `contest=<id>` ใน `/api/submit` (โจทย์ต้องอยู่ในคอนเทสต์ และ
    ต้องอยู่ในช่วงเวลา ไม่ใช่ admin)
  - scoreboard แช่แข็ง: คนทั่วไปเห็นเฉพาะผลก่อน `ends_at - freeze_minutes` ระหว่างแข่ง (admin เห็นสด)
  - `show_samples=false` → ระหว่างแข่งแม้แต่ตัวอย่างสาธารณะก็ไม่โชว์ input/expected

### โจทย์ชุดคอนเทสต์ (ไม่โชว์ในหน้า Task)

ผู้ใช้ทั่วไปจะเห็นโจทย์เฉพาะข้อที่ "เปิด" — ข้อที่ซ่อนจะเข้าถึงได้ทางหน้าคอนเทสต์ที่ระบุไว้ และทางหน้า admin เท่านั้น
(`/api/problems`, `/api/health`, `/api/version`, `/api/history` สาธารณะ และ `POST /api/submit` ถูกกรองทั้งหมด;
admin เห็นครบพร้อมป้าย `hidden`)

วิธีทำเครื่องหมายมี 2 ทาง เลือกอย่างใดอย่างหนึ่ง:

| วิธี | ใช้เมื่อ | คำสั่ง |
|---|---|---|
| ธงในไฟล์โจทย์ `"hidden": true` | ชุดคอนเทสต์ถาวร (ข้อสอบจริง) — ซ่อนตลอดไม่ว่าคอนเทสต์จะจบหรือถูกลบ | `python3 tools/problem_visibility.py --id <pid> --hidden` (ดูทั้งหมด: `--list`, กลับเป็นสาธารณะ: `--public`) |
| ติ๊ก "ซ่อนโจทย์ชุดนี้จากหน้า Task" ตอนสร้างคอนเทสต์ (`contests.hide_from_tasks`, ค่าเริ่มต้นเปิด) | คอนเทสต์ที่หยิบโจทย์สาธารณะมาใช้ชั่วคราว — ลบคอนเทสต์หรือปิดติ๊กแล้วโจทย์กลับขึ้นใน Task เอง | หน้า Settings → admin → ฟอร์มคอนเทสต์ |

ขั้นตอน "โยนไฟล์ให้" (โจทย์ชุดคอนเทสต์): สร้าง `problems/<id>/` ตามปกติ (statement.md/pdf + tests + ref)
→ ตั้ง `hidden` → `python3 tools/validate_problem.py <id>` (ต้อง 0 FAIL; บรรทัด OK จะขึ้น
`[contest-only: ไม่โชว์ในหน้า Task]`) → สร้างคอนเทสต์ในหน้า admin แล้วเลือกโจทย์ (ข้อที่ซ่อนจะถูกจัดไว้บนสุด
พร้อมป้าย `[ซ่อนจาก Task]`) → restart backend เพื่อโหลดโจทย์ใหม่

หมายเหตุ: คอลัมน์ `contests.hide_from_tasks` ต้องรัน `supabase/schema.sql` ใหม่ (ถ้าไม่รัน การสร้างคอนเทสต์จะได้
ข้อความบอกให้รัน ไม่ใช่ 500)
- **ตรวจซ้ำ (rejudge)**: `POST /api/admin/rejudge` body `{"ids":[...]}` หรือ `{"problem":"x","limit":50}`
  → คืน `job_id` ให้ poll เหมือน submit (อัปเดตแถวเดิม ไม่สร้างใหม่) — ใช้หลังแก้เทสต์
- **ตรวจการก็อป**: `GET /api/admin/plagiarism?problem=<id>&threshold=0.6&limit=300` (admin)
  ใช้ `tools/plagiarism.py` (winnowing, stdlib ล้วน) เทียบโค้ดที่ส่งล่าสุดของข้อนั้น
- ทุก submission เก็บ `tests_hash` + `grader_version` → รู้ว่าตัดสินด้วยเทสต์ชุดไหน/engine เวอร์ชันใด

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

อัปเดตล่าสุด (ต้องรัน `supabase/schema.sql` ใหม่ถ้ารันเวอร์ชันเก่าไปแล้ว): เพิ่มคอลัมน์
`tests_hash/grader_version/kind/contest_id/job_id` ใน `submissions`, ตาราง `judge_jobs`
(คิวตรวจงาน + `reveal`) และ `contests`, view `leaderboard_scores` + `problem_stats`
— **ถ้าไม่รัน**: ระบบยังทำงานได้ (insert จะตัดคอลัมน์ใหม่ทิ้ง แล้ว log เตือน) แต่
leaderboard/สถิติจะ fallback ไปสแกนแค่ 2000/500 แถวล่าสุด (คะแนนเก่าจะหลุดจากบอร์ด)
และคิวงานจะเป็น in-memory (หายเมื่อ restart)

env ปรับสมรรถนะ/ความยุติธรรม — **ทุกตัวมี auto** จาก cgroup ของ container (ดู `GET /api/version` → `system`)

| env | auto (host 0.5 vCPU / 0.5 GB) | ความหมาย |
|---|---|---|
| `GRADER_JUDGE_WORKERS` | `1` (`2` ถ้า cpu ≥ 2) | งานที่ตรวจพร้อมกัน — 0.5 CPU ตั้ง 1 เพื่อไม่ให้ TLE ปลอมจากการแย่ง CPU |
| `GRADER_JUDGE_JOBS` | `1` (`4` ถ้า cpu ≥ 2) | เทสต์ที่รันพร้อมกันในหนึ่งงาน |
| `GRADER_MEMORY_CAP_MB` | `ram × 0.5` = **256** | เพดานหน่วยความจำจริงต่อเทสต์ (โจทย์ที่ประกาศ 512MB จะถูกตัดเหลือ 256MB และรายงาน `limits.capped` ให้ผู้ใช้เห็น) — กันโจทย์อัดแรมจน OOM killer ฆ่า server |
| `GRADER_QUEUE_MAX` | `25` | คิวเต็ม = ตอบ 503 + `Retry-After` (shed load) แทนที่จะให้คิวบวมเป็นชั่วโมง |
| `GRADER_OVERALL_TIMEOUT` | `240`s (90 ถ้า cpu ≥ 2) | เวลาสูงสุดต่องาน (compile + ทุกเทสต์แบบ serial) |
| `GRADER_COMPILE_TIMEOUT` | `90`s (60 ถ้า cpu ≥ 2) | timeout ตอน compile (C++ -O2 บน 0.5 CPU กินเวลาหลายสิบวิ) |
| `GRADER_SAMPLE_INTERVAL` | `0.02`s (0.005 ถ้า cpu ≥ 2) | ความถี่ poll peak RSS |
| `GRADER_SUBMIT_QUOTA` | `60/600` | โควตาส่งงานต่อคน (`N/วินาที`, `0` = ปิด) |
| `GRADER_RUN_QUOTA` | `120/600` | โควตา playground `/api/run` |

`python3 server.py` จะ print ค่าที่ใช้จริงตอน boot หนึ่งบรรทัด เช่น
`[web] host: cpu=0.5 core(s), ram=512MB -> workers=1, tests/submission=1, memory_cap=256MB, ...`
ถ้าย้ายไป host ใหญ่ขึ้นไม่ต้องแก้อะไร (auto ตาม cgroup) หรือ override รายตัวผ่าน env

Migration (ถ้าสร้างตารางก่อนคอลัมน์ `name`): รันใน SQL Editor
```sql
alter table submissions add column if not exists name text not null default '';
```
- `GET /api/health` — สถานะ + รายชื่อโจทย์
- `GET /api/languages` — ภาษาที่รองรับ (python/c/cpp)
- `GET /api/version` — เวอร์ชัน engine + hash ของชุดเทสต์ทุกข้อ (`grader.GRADER_VERSION`)
- `GET /api/problems` — รายการโจทย์
- `GET /api/problems/{id}` — โจทย์ + statement (+ `samples`, `hidden_tests`, `tests_hash`)
- `GET /api/problems/{id}/sample/{name}` — ตัวอย่างสาธารณะ (เทสต์ลับตอบ 404)
- `POST /api/submit` (multipart: `problem`, `language`, `code` หรือ `file`, `contest`; ต้อง login)
  — **ตอบ 202 + `job_id` ทันที** แล้วตรวจเบื้องหลัง (คิว) ต้อง poll ต่อ:
- `GET /api/jobs/{id}` — สถานะงาน (`queued|running|done|error`) + ผลเมื่อ `done`
- `POST /api/run` (multipart: `language`, `code`/`file`, `input`, `problem?`, `time_limit?`)
  — playground รันครั้งเดียวกับ input ที่ผู้ใช้พิมพ์ ไม่บันทึกประวัติ

```bash
# ส่งแล้วรอผล (submission เป็น async job)
JOB=$(curl -s -F problem=warpz -F language=python -F code='print("YES")' \
      -b cookies.txt http://127.0.0.1:8000/api/submit | python3 -c 'import json,sys;print(json.load(sys.stdin)["job_id"])')
curl -s -b cookies.txt http://127.0.0.1:8000/api/jobs/$JOB | python3 -m json.tool
```

**นโยบายเฉลย (สำคัญ)**: ผู้ใช้ทั่วไปเห็น input/expected ของเฉพาะ test ที่อยู่ใน `samples`
ใน `config.json` (ตัวอย่างใน statement) เท่านั้น — test ที่เหลือ ("เทสต์ลับ") คืนแค่ verdict +
เวลา/หน่วยความจำ และข้อมูลนี้ถูกตัดออกก่อนบันทึกลง DB ด้วย (admin เห็นครบ) `samples` เป็น
รายชื่อ test เช่น `"samples": ["03"]` (สคริปต์ตรวจ: `python3 tools/validate_problem.py`)

## โครง
```
grader.py
problems/<id>/config.json      # time_limit, memory_limit, checker, difficulty, tags (ดู KNOWN_TAGS), samples
problems/<id>/statement.pdf      # โจทย์ต้นฉบับ (ถ้ามี)
problems/<id>/statement.md
problems/<id>/tests/*.in|*.out
examples/                      # reference solution ประจำข้อ (*_ref.py)
server.py                      # FastAPI backend (reuse grader.py) + คิวตรวจงาน (judge_jobs)
static/                        # frontend: index.html, styles.css, app.js (?v=N กัน cache)
functions/api/[[proxy]].js     # Cloudflare Pages Function proxy /api
supabase/schema.sql            # schema + migration ทั้งหมด
tests/                         # E2E API test (fake Supabase, ไม่แตะข้อมูลจริง)
tools/validate_problem.py      # ตรวจโจทย์ทั้งชุด (config/tests/ตัวอย่าง/ref ต้อง AC)
tools/plagiarism.py            # ตรวจการก็อปโค้ด (winnowing)
tools/check_frontend.js        # เช็ค id ที่ app.js อ้างถึงว่ามีจริง
tools/make_statement_tex.py    # สร้าง statement.pdf (LaTeX)
.github/workflows/ci.yml       # CI: compile + syntax + id check + validate โจทย์ + E2E test
agent.md                       # คู่มือ AI
requirements.txt               # fastapi, uvicorn, python-multipart, supabase, itsdangerous
```

## ตรวจคุณภาพ (รันก่อน commit ทุกครั้ง)
```bash
python3 tools/validate_problem.py          # 47 ข้อ: config/tests/ตัวอย่าง/ref ต้อง AC ครบ
python3 tools/plagiarism.py                # self-test ของตัวตรวจการก็อป
python3 -m unittest discover -s tests -v    # E2E API (คิวงาน/สิทธิ์/คอนเทสต์/quota/redact)
node --check static/app.js && node tools/check_frontend.js
```
CI (`.github/workflows/ci.yml`) รันทั้งชุดนี้อัตโนมัติทุก push/PR เข้า `main`
(validator รันแบบ jobs=1 ตั้งใจ — รัน ref หลายข้อพร้อมกันจะได้ TLE ปลอมจากการแย่ง CPU)

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

**ทุกข้อมีเลขโจทย์ถาวร** (`config.json → "no"`) ใช้เรียงและค้นหา: พิมพ์ `19` หรือ `#19` ในช่องค้นหา,
เปิดตรงด้วย `#/task/19`, และเรียงได้ 3 แบบ (เลข / ระดับ / ชื่อ) ผ่าน dropdown ในหน้า Tasks
เลขเก็บในโฟลเดอร์โจทย์ (ไม่ใช่ลำดับที่คำนวณ) → ไม่เปลี่ยนเมื่อเพิ่มข้อใหม่ และใช้ได้ทั้ง CLI/validator
จัดการด้วย:

```bash
python3 tools/number_problems.py --list                    # ตารางเลขโจทย์ทั้งหมด
python3 tools/number_problems.py --assign                  # ให้เลขข้อที่ยังไม่มี (ต่อท้าย)
python3 tools/number_problems.py --renumber                # ล้างแล้วให้ใหม่ (public easy→medium→hard, คอนเทสต์ท้าย)
python3 tools/number_problems.py --set --id hanoi --no 12  # ย้ายข้อไปเลขที่ต้องการ
python3 tools/number_problems.py --check                   # ตรวจเลขซ้ำ/ขาด
```
เลขต้องไม่ซ้ำ — `python3 tools/validate_problem.py` จะ FAIL ถ้าซ้ำหรือหาย (ข้อที่ตั้ง `"hidden": true` จะขึ้น `[contest-only: ไม่โชว์ในหน้า Task]` และไม่ปรากฏในตารางนี้ให้ผู้ใช้ทั่วไป)

| # | id | ชื่อ | ระดับ | tests | limits |
|---|----|------|--------|-------|--------|
| `1` | `array_min_sum` | ค่าต่ำสุดและผลรวมของอาร์เรย์ (Array Min Sum) | easy | 14 | TL 1s / MEM 64MB |
| `2` | `bake_a_cake` | อบเค้ก (Bake a Cake) | easy | 16 | TL 0.5s / MEM 32MB |
| `3` | `binary_strings` | สายไบนารีที่ไม่มีเลข 1 ติดกัน (Binary Strings) | easy | 15 | TL 1s / MEM 64MB |
| `4` | `blood_moon` | คืนพระจันทร์สีเลือด (Blood Moon) | easy | 15 | TL 1s / MEM 256MB |
| `5` | `boat_crossing` | เรือพายข้ามคลอง (Boat Rescue) | easy | 14 | TL 1s / MEM 256MB |
| `6` | `candy_sales` | ยอดขายสายไหมรายวัน (Daily Candy Sales) | easy | 15 | TL 1s / MEM 256MB |
| `7` | `club_vote` | เลือกตั้งประธานชมรมดนตรี (Club Election) | easy | 15 | TL 1s / MEM 64MB |
| `8` | `collatz_max` | ลำดับคอลลาตซ์ที่ยาวที่สุด (Collatz Max) | easy | 14 | TL 1s / MEM 64MB |
| `9` | `cookie_share` | แบ่งคุกกี้ ห.ร.ม. ค.ร.น. (Cookie Sharing) | easy | 14 | TL 1s / MEM 64MB |
| `10` | `count_even_odd` | นับเลขคู่และเลขคี่ (Even Odd Count) | easy | 14 | TL 1s / MEM 64MB |
| `11` | `dec_to_bin` | แปลงเลขฐานสิบเป็นฐานสอง (Decimal to Binary) | easy | 14 | TL 1s / MEM 64MB |
| `12` | `dec_to_hex` | แปลงเลขฐานสิบเป็นฐานสิบหก (Decimal to Hex) | easy | 14 | TL 1s / MEM 64MB |
| `13` | `digit_sum` | ผลรวมเลขโดด (Digit Sum) | easy | 14 | TL 1s / MEM 64MB |
| `14` | `digital_root` | รากดิจิทัล (Digital Root) | easy | 14 | TL 1s / MEM 64MB |
| `15` | `dna` | จำลอง DNA (DNA Replication) | easy | 15 | TL 1s / MEM 256MB |
| `16` | `fib_sum` | ผลรวมลำดับฟีโบนัชชี (Fibonacci Sum) | easy | 14 | TL 1s / MEM 64MB |
| `17` | `find_max` | หาค่ามากที่สุดด้วยฟังก์ชัน (Find Max) | easy | 14 | TL 1s / MEM 64MB |
| `18` | `fraction_add` | บวกเศษส่วนให้เป็นเศษส่วนอย่างต่ำ (Fraction Add) | easy | 14 | TL 1s / MEM 64MB |
| `19` | `hanoi` | หอคอยฮานอย (Hanoi Tower) | easy | 10 | TL 1s / MEM 64MB |
| `20` | `hidden_digit_sum` | ผลรวมตัวเลขที่ซ่อนในข้อความ (Hidden Digits) | easy | 14 | TL 1s / MEM 64MB |
| `21` | `library_code` | ซ่อมรหัสสมาชิกห้องสมุด (Library Code) | easy | 14 | TL 1s / MEM 64MB |
| `22` | `mirror_pair` | เลขสะท้อนคู่ (Mirror Pair) | easy | 14 | TL 1s / MEM 64MB |
| `23` | `napprime` | นับจำนวนเฉพาะ (Napprime) | easy | 16 | TL 0.5s / MEM 32MB |
| `24` | `power_recur` | ยกกำลังด้วยการเรียกตัวเอง (Power) | easy | 14 | TL 1s / MEM 64MB |
| `25` | `prime_check` | ตรวจจำนวนเฉพาะ (Prime Check) | easy | 14 | TL 1s / MEM 64MB |
| `26` | `rotation` | เธอหมุนรอบฉัน ฉันหมุนรอบเธอ (Rotation) | easy | 15 | TL 1s / MEM 256MB |
| `27` | `shadow` | เงาปะทะมังกร (Shadow) | easy | 15 | TL 1s / MEM 64MB |
| `28` | `sing_contest` | อันดับประกวดร้องเพลง (Singing Contest) | easy | 15 | TL 1s / MEM 256MB |
| `29` | `snack_budget` | งบจำกัดแต่อยากกินเยอะ (Snack Budget) | easy | 14 | TL 1s / MEM 256MB |
| `30` | `stage_lights` | จุดไฟประดับใกล้เวทีที่สุด (Stage Lights) | easy | 15 | TL 1s / MEM 256MB |
| `31` | `stage_show` | ตารางการแสดงบนเวที (Stage Schedule) | easy | 15 | TL 1s / MEM 256MB |
| `32` | `sum_even` | ผลรวมของเลขคู่ (Sum Even) | easy | 14 | TL 1s / MEM 64MB |
| `33` | `swordsmith` | ช่างตีดาบแห่งวังหลวง (Swordsmith) | easy | 14 | TL 1s / MEM 64MB |
| `34` | `thai_time` | ระบบบอกเวลาภาษาไทย (Thai Time) | easy | 15 | TL 1s / MEM 256MB |
| `35` | `ticket_queue` | คิวซื้อตั๋วคอนเสิร์ต (Ticket Queue) | easy | 15 | TL 1s / MEM 256MB |
| `36` | `warpz` | วาร์ปอวกาศ (Warpz) | easy | 15 | TL 1s / MEM 256MB |
| `37` | `broken_stairs` | บันไดขั้นพัง (Broken Stairs) | medium | 14 | TL 1s / MEM 64MB |
| `38` | `count_islands` | นับเกาะ (Count Islands) | medium | 18 | TL 1s / MEM 64MB |
| `39` | `exact_budget` | ซื้อของให้พอดีงบ (Exact Budget) | medium | 14 | TL 1s / MEM 64MB |
| `40` | `flashback` | ไม่ได้ลืมแค่ไม่ได้เจอ (Flashback) | medium | 15 | TL 1s / MEM 256MB |
| `41` | `largest_rectangle` | สี่เหลี่ยมใหญ่สุดในฮิสโตแกรม (Largest Rectangle) | medium | 15 | TL 1s / MEM 64MB |
| `42` | `mana_crystal` | ย่อภาพผลึกมานา (Mana Crystal) | medium | 15 | TL 1s / MEM 256MB |
| `43` | `maze_score` | เขาวงกตเก็บคะแนน (Maze Score) | medium | 14 | TL 1s / MEM 64MB |
| `44` | `min_distance` | ระยะทางรวมน้อยสุด (Min Distance) | medium | 14 | TL 1s / MEM 64MB |
| `45` | `panda` | แพนด้าหาส้มโอ (Panda50O) | medium | 15 | TL 1s / MEM 512MB |
| `46` | `posn_server_passcode` | รหัสผ่านเซิร์ฟเวอร์ สอวน. (POSN Passcode) | medium | 16 | TL 1s / MEM 256MB |
| `47` | `queens_holes` | ราชินีบนกระดานมีหลุม (Queens Holes) | medium | 14 | TL 1s / MEM 64MB |

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
