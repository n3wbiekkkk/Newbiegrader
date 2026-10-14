# agent.md — คู่มือสำหรับ AI session ใหม่ (อ่านไฟล์นี้ก่อนเสมอ)

> ภาษาตอบผู้ใช้: ไทย สั้น กระชับ ห้ามใช้อีโมจิ
> หลัก: verify ด้วยการรันจริงทุกครั้งก่อนสรุป ห้ามเดา

## 1. ภาพรวมโปรเจกต์

Newbiegrader = เว็บสนามสอบเขียนโปรแกรม (Python / C / C++) ตรวจอัตโนมัติแบบโหด
- โจทย์มาจากไฟล์ PDF → `problems/<id>/` (statement.pdf + statement.md + config.json + tests 10 ข้อ)
- Frontend: `static/` HTML/CSS/JS ล้วน **ไม่มี build step** (Home/Tasks/Task/Contests/Archive/Leaderboard/History/Settings)
- Backend: `server.py` (FastAPI) reuse logic จาก `grader.py` ตรงๆ (ห้ามเขียน judge ซ้ำ)
- **ส่งงานเป็น async job**: `/api/submit` ตอบ 202 + `job_id` → worker (ในprocess, `GRADER_JUDGE_WORKERS`)
  ตรวจเบื้องหลัง → client poll `/api/jobs/{id}`; คิว durable ในตาราง `judge_jobs` (ถ้ามี DB)
- **นโยบายเฉลย**: test ที่อยู่ใน `config.json → samples` เท่านั้นที่โชว์ input/expected ให้ผู้ใช้ทั่วไป
  (ที่เหลือ = เทสต์ลับ, คืนแค่ verdict+เวลา และถูกตัดออกก่อนบันทึกลง DB); admin เห็นครบ
- **คอนเทสต์**: ตาราง `contests` (ช่วงเวลา + freeze scoreboard + `show_samples`), ส่งเข้าคอนเทสต์ด้วยฟิลด์ `contest`
- DB: Supabase Postgres (ตาราง `submissions`, `profiles`, `reports`, `users`, `judge_jobs`, `contests`) — ดู `supabase/schema.sql`
- Login: Google OAuth + รหัสผ่าน (บังคับก่อนส่ง) + session cookie
- Deploy แยก 2 ที่:
  - Frontend → Cloudflare Pages (output = `static/`, auto-deploy ทุก push `main`)
  - Backend → justrunmy (Docker, push `HEAD:deploy` ไป remote พิเศษ แล้วมัน restart เอง)

## 2. URLs / ports

| อะไร | ค่า |
|---|---|
| Production frontend | `https://gradernew.pages.dev` |
| Production backend | `https://grader.n.onjrnm.vip` |
| Local dev | `http://127.0.0.1:8000` (`python3 server.py --port 8000`) |
| GitHub | `sphetpitak-sudo/gradernew` branch `main` |
| Supabase project | `synyixryyoytbdaxnmph.supabase.co` (region Tokyo) |

## 3. โครง repo

```
grader.py            # engine: run_one/judge_test/checkers/CLI (stdlib ล้วน) + tests_hash/GRADER_VERSION
server.py            # FastAPI: /api/* + คิวงาน (judge_jobs) + serve static/ (โหลด .env local ถ้ามี)
static/              # index.html styles.css app.js (?v=N กัน cache) config.js (+ vercel.json legacy ไม่ใช้แล้ว)
functions/api/[[proxy]].js  # Cloudflare Pages Function: proxy /api ไป backend
problems/<id>/       # statement.pdf statement.md config.json (มี samples) tests/*.in|*.out
examples/*_ref.py    # reference solution ประจำข้อ (single source of truth ตอน gen test)
tests/               # E2E API test (unittest + fake_supabase) — ไม่แตะ production
tools/validate_problem.py   # ตรวจโจทย์ทั้งชุดก่อน commit
tools/plagiarism.py  # ตรวจการก็อปโค้ด (winnowing; มี self-test ใน __main__)
tools/check_frontend.js     # เช็ค $("id") ใน app.js ว่ามีจริงใน index.html/template
tools/make_statement_tex.py # สร้าง statement.pdf (LaTeX)
.github/workflows/ci.yml    # CI ทั้งชุด (compile, syntax, id check, validate โจทย์, E2E)
supabase/schema.sql  # schema + migration ทั้งหมด (append-only, อย่าลบของเก่า)
.env.example         # template env (ห้าม commit .env จริง)
requirements.txt     # fastapi uvicorn python-multipart supabase itsdangerous
Dockerfile           # backend image (python:3.11-slim + gcc/g++)
agent.md             # ไฟล์นี้
```

## 4. Workflow: เพิ่มโจทย์จาก PDF

1. ผู้ใช้วาง PDF ใน `problems/` → ย้ายเป็น `problems/<id>/statement.pdf` (id ตัวเล็ก, `git mv`)
   - ถ้าโจทย์มาเป็น **ภาษาอังกฤษหรือ text (ไม่มี PDF ไทย)**: แปล/เขียน `statement.md` ไทยเอง
     (เก็บเรื่องราวครบ ห้ามย่อ) แล้วทำ `statement.pdf` ด้วย LaTeX เท่านั้น:
     `python3 tools/make_statement_tex.py <id>` (tectonic + TH Sarabun, คณิตสวย, ตัวอย่างเป็นกล่องคู่ —
     build นิ่งแบบ byte-identical ทุกรอบ (SOURCE_DATE_EPOCH คงที่ในสคริปต์) + footer `Newbiegrader | หน้า`
     ติดทุกไฟล์ — verify ด้วย pdftotext + เปิดภาพดูทุกข้อก่อน commit)
   - โจทย์ค่ายที่มี PDF ต้นฉบับแล้วแต่อยากได้เวอร์ชัน LaTeX ดำ (style เดียวกัน): เขียน `statement.md`
     เองแล้วรันสคริปต์เดียวกันทับ `statement.pdf` ได้เลย
2. อ่าน PDF (tool `read` อ่าน PDF ได้) แล้วสร้าง:
   - `config.json`: `{"title","time_limit":1.0,"memory_limit":256,"checker":"token|exact|float|decimal2","difficulty":"easy|medium|hard","tags":[...],"notice":"...","samples":["02"]}` (tags ต้องอยู่ใน KNOWN_TAGS ใน `grader.py`; `notice` โชว์แบนเนอร์บนหน้า task)
     - **`samples`** = รายชื่อ test ที่เป็นตัวอย่างใน statement (เช่น `["03"]`) — เฉพาะเทสต์เหล่านี้ที่ผู้ใช้ทั่วไปเห็น input/expected; ต้องมีชื่อไฟล์จริงใน `tests/` ไม่งั้น validator ฟ้อง (ทำให้อัตโนมัติ: จับคู่ fenced block `input:`/`output:` ใน statement.md กับ test ที่เหมือนกันแบบ token)
   - `statement.md`: spec ภาษาไทย (input/output/constraints/subtasks/ตัวอย่าง) — **ห้ามใส่ section กับดัก** (นโยบาย: ไม่บอกใบ้)
   - `tests/01..10.in/.out`: ข้อ 01+ = ตัวอย่างใน PDF (ต้องตรงเป๊ะ), ที่เหลือ edge + random (seeded) + max constraint
   - `examples/<id>_ref.py`: reference solution ที่ถูกต้อง
3. Verify 3 ชั้น (บังคับ): (a) ตัวอย่างตรง PDF (b) gen logic กับ ref ตรงกัน byte-for-byte (c) cross-check อิสระ (เช่น greedy vs DP, Miller-Rabin + Pollard-Rho สำหรับ prime)
4. Judge ref ผ่าน CLI ต้อง `ACCEPTED 10/10` + ลอง solution ผิดต้องได้ WA (กัน test หลวม)
5. **รันตัวตรวจทั้งชุด**: `python3 tools/validate_problem.py [id]` ต้อง 0 FAIL (config/tags/tests ต่อเนื่อง/ตัวอย่างตรง test/ref AC ครบทุกข้อ) — CI รันตัวนี้อยู่แล้ว อย่ารันด้วย `--jobs >1` (จะได้ TLE ปลอมจากการแย่ง CPU)
6. Restart local server (problems โหลดตอน boot) → เทสเว็บ → commit + push GitHub + push justrunmy (ข้อ 7)

checker ที่มี: `token` (default), `exact` (byte, ผ่อน newline ท้ายไฟล์), `float` (tolerance 1e-6),
`decimal2` (เฉพาะ mana: ทศนิยม 2 ตำแหน่งเท่านั้น แต่ไม่หัก space เกิน) — ดู `check_decimal2` ใน `grader.py`

## 5. Workflow: แก้ frontend (`static/`)

- ไม่ต้อง build/restart (StaticFiles อ่านจาก disk ทุก request) — แต่ Pages ต้อง redeploy (auto จาก push `main`)
- **ทุกครั้งที่แก้ `app.js`/`styles.css` ให้ bump `?v=N` ใน `index.html`** (กัน browser cache ค้าง) — เลขปัจจุบันดูในไฟล์
- ห้ามใช้ emoji ใน UI — icon ใช้ SVG sprite (`<symbol id="i-*">` ใน `index.html` + helper `icon()` ใน `app.js`)
- หลังแก้: `node --check static/app.js` + `node tools/check_frontend.js` (เช็คว่า `$("...")` ทุกตัวมี id จริงใน `index.html` หรือใน template literal ของ `app.js`) — ตัวนี้อยู่ใน CI แล้ว
- ส่งงานเป็น async: หน้า Submit ต้อง poll `/api/jobs/{id}` (~700ms) — อย่ากลับไปอ่านผลจาก response ของ `/api/submit` (ได้แค่ 202 + job_id)
- ทดสอบ UI จริง: รัน `SUPABASE_URL= SUPABASE_KEY= SESSION_SECURE=false python3 server.py --port 8090` แล้วเปิดเบราว์เซอร์ (หน้าเว็บที่ต้อง login จะทดสอบได้ต้องมี session — ใช้ password API ถ้ามี DB หรือให้ user ช่วยล็อกอิน)
- Dark mode ผ่าน `[data-theme="dark"]` + CSS vars — สี hardcode ต้องใช้ var (`--field`, `--on-acc`)

## 6. Workflow: แก้ backend (`server.py`)

- เพิ่ม endpoint → เทส local ก่อนเสมอ (server local: `GRADER_CORS_ORIGINS=https://gradernew.pages.dev python3 server.py --port 8000`)
- **เทสได้โดยไม่แตะ production DB**: `python3 -m unittest discover -s tests -v` รัน FastAPI จริง
  แค่สลับ Supabase เป็น `tests/fake_supabase.py` (จำลองตาราง+view พอใช้) — เพิ่มเทสใน `tests/test_api_e2e.py`
  ทุกครั้งที่แตะ submit/jobs/history/contests/admin (โจทย์ใหม่ไม่ต้อง)
- **Login จำลองโดยไม่ต้องผ่าน Google**: สมัคร/ล็อกอินผ่าน password API แล้วเก็บ cookie เอง:
```python
from httpx import Client
c = Client(base_url="http://127.0.0.1:8000", timeout=90)
c.post("/api/auth/register", json={"email": "test@example.com", "password": "testpass123", "name": "t"})
# login ซ้ำใช้ c.post("/api/auth/password", json={...}) — cookie ng_session ติดมาเอง
```
(ห้าม forge cookie เอง: session ใช้ Starlette SessionMiddleware + one-time token ผ่าน `/api/auth/finish`)
- Supabase local test: ตั้ง `SUPABASE_URL` + `SUPABASE_KEY` (service_role) ใน env แล้วเทส **ห้ามลืมลบข้อมูลเทส** (delete by id/email ทันทีหลังเทส, เช็ค count กลับเท่าเดิม)
- **คิวตรวจงาน**: `/api/submit` ห้ามตรวจ inline — สร้าง job (`_create_job`) แล้วให้ worker (`_judge_worker`/`_run_job`)
  ตรวจในเทรด; ผลเก็บใน `judge_jobs.result` + `submissions`; ค้างหลัง restart จะถูก requeue ตอน boot (`_recover_jobs`)
  — อย่าเรียก `run_submission` จาก request handler ตรง ๆ (`/api/run` เป็นข้อยกเว้น: รันครั้งเดียวสั้น ๆ)
- **อย่าให้ test ลับหลุดออกไป**: `run_submission` คืนผลโดยผ่าน `_redact_results(..., reveal)`; เก็บลง DB ด้วย
  `REVEAL_SAMPLES` เสมอ (admin เห็นครบแค่ตอน response) — เพิ่มฟิลด์ใหม่ที่มีข้อมูลเทสต์ต้องคิดเรื่องนี้ทุกครั้ง
- โควตา: `_quota_check(kind, email, SUBMIT_QUOTA/RUN_QUOTA)` — env `GRADER_SUBMIT_QUOTA`, `GRADER_RUN_QUOTA` (`N/วินาที`, `0`=ปิด), worker: `GRADER_JUDGE_WORKERS`
- Session ใช้ `ng_session` (HttpOnly, SameSite=lax + Secure ใน prod — same-origin ผ่าน Pages proxy เลยไม่ต้องใช้ None) — flow เต็ม: `/api/auth/login` → Google → `/api/auth/callback` (ผ่าน Pages Function proxy เพื่อให้ session อยู่ origin เดียวกัน) → mint one-time token → `/api/auth/finish` ตั้ง cookie first-party → redirect หน้าเว็บ
- CORS: `allow_methods` ต้องครอบคลุม method ที่ frontend ใช้ (เคยลืม PUT จนปุ่ม settings พัง) + `allow_credentials=True`
- `ADMIN_EMAILS` default = เมลเจ้าของในโค้ด (override ผ่าน env ได้) — endpoint ใต้ `/api/admin/*` และการดู submission ของคนอื่นต้องเป็น admin เท่านั้น
- ปุ่ม/ฟีเจอร์ใหม่ของ admin: rejudge (`POST /api/admin/rejudge`), ตรวจการก็อป (`GET /api/admin/plagiarism`), จัดการคอนเทสต์ (`POST/DELETE /api/contests`)

## 7. Workflow: deploy

```bash
# 1) GitHub (frontend auto-redeploy)
git add -A && git commit -m "..." && git push origin main
# 2) Backend (เฉพาะเมื่อแก้ server.py/grader.py/requirements/Dockerfile/problems/)
#    ใช้ remote ชื่อ deploy (ตั้งครั้งเดียวในเครื่องนี้ ไม่ถูก commit):
#    git remote add deploy <git-url จาก justrunmy panel>
git push deploy HEAD:deploy
```
- หลัง push backend รอ ~2-5 นาที แล้ว verify: `curl https://grader.n.onjrnm.vip/api/health`
  (build รอบใหญ่ใช้เวลานาน ถ้านานเกินให้ user ดู build status ที่ panel)
- Pages: ถ้าหน้าเว็บไม่อัปเดต ให้ user hard refresh (Ctrl+Shift+R)

## 8. Secrets (ชื่อเท่านั้น — ห้ามเขียนค่าลงไฟล์/chat/repo)

`SUPABASE_URL`, `SUPABASE_KEY` (service_role), `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
`GOOGLE_REDIRECT_URI`, `FRONTEND_URL`, `SESSION_SECRET`, `ADMIN_EMAILS`, `GRADER_CORS_ORIGINS`
→ อยู่บน justrunmy panel (env) เท่านั้น + local shell env ตอนเทส
- ค่า local dev: ก็อป `.env.example` เป็น `.env` แล้วขอค่าจาก user (ดูจาก justrunmy panel) —
  `server.py` โหลด `.env` เองตอน start (env จริงชนะเสมอ), `.env` อยู่ใน `.gitignore` แล้ว
  (เครื่อง dev นี้มี `.env` พร้อมค่าแล้ว — session ใหม่ใช้ได้เลยไม่ต้องขอซ้ำ)
- ถ้า token/secret หลุดลง chat หรือ commit: ให้ user rotate ที่ต้นทางทันที (เช่น reset git
  credentials / สร้าง key ใหม่) เพราะลบออกจากประวัติไม่ได้ง่ายๆ

## 9. Database

- เปลี่ยน schema → append ลง `supabase/schema.sql` (ใช้ `if not exists` เสมอ) + ให้ user รันใน SQL Editor (agent รัน DDL เองไม่ได้)
- migration ล่าสุด (2026-10): คอลัมน์ `tests_hash/grader_version/kind/contest_id/job_id` ใน `submissions`,
  ตาราง `judge_jobs` (คิวงาน + คอลัมน์ `reveal`) และ `contests`, view `leaderboard_scores` + `problem_stats`
  — โค้ด fallback ไว้ถ้า user ยังไม่รัน (insert ตัดคอลัมน์ใหม่ทิ้ง, aggregate สแกนแค่ 2000/500 แถวล่าสุด,
  คิวเป็น in-memory) **แต่ต้องเตือน user ให้รันถ้าอยากได้คะแนนถูกต้อง + คิว durable**
- RLS เปิดทุกตารางแบบไม่มี public policy (backend ใช้ service_role อย่างเดียว)
- Production มีข้อมูลจริง — เทสแล้วลบทุกครั้ง, ห้าม reset/drop โดยไม่ได้รับคำสั่งชัดๆ

## 10. กับดักที่เจอมาแล้ว (อย่าทำซ้ำ)

1. `difflib` กับ output แสนบรรทัดช้า 100วิ+ → `show_diff` ใช้ linear first-mismatch เมื่อไฟล์ใหญ่ (ดู `_show_diff_head`)
2. `threading.Thread._stop` ห้ามตั้งชื่อ attr ชน (ใช้ `_stop_event`)
3. ไฟล์ `/tmp/*.py` ชื่อชน stdlib (เช่น `re.py`) ทำ interpreter พัง — ใช้โฟลเดอร์ที่ env แนะนำ
4. `problems/` โหลดตอน boot — แก้ test/config ต้อง restart server (local + production)
5. Expected output ของ mana ต้องตรง format เป๊ะทั้ง 2 ภาษา (เคย cross-check Python `.2f` vs C++ `setprecision(2)` ครบ 10 ข้อ)
6. Free-tier CPU (0.25) ทำให้ Python TLE ข้อใหญ่ที่เครื่องแรงผ่าน — C++ คือเกณฑ์ยุติธรรม (ยึด TL ตาม PDF)
7. Browser cache JS เก่า → user บ่นช้า/เพี้ยนทั้งที่ deploy แล้ว — bump `?v=` + ให้ hard refresh
8. Third-party cookie โดนบล็อกในเบราว์เซอร์ใหม่ → login ต้องผ่าน Pages Function `/api` proxy + one-time token (ห้ามกลับไปใช้ cookie ข้าม origin)
9. Google OAuth: redirect URI ต้องตรงตัวเป๊ะ + เพิ่มทุก origin ที่ใช้ (backend ตรง + ผ่าน proxy), consent screen ต้องมี test user หรือ publish ก่อน
10. `static/vercel.json` คือ legacy สมัย Vercel (ไม่ใช้แล้ว) — ปัจจุบัน proxy `/api:path*` → backend คือ `functions/api/[[proxy]].js` บน Pages
11. Push justrunmy ใช้ `HEAD:deploy` (branch แยกจาก `main`, ไม่มีผลกับ GitHub)
12. `/api/history/{sid}` เคยให้ใครก็ได้ที่ login อ่านโค้ด+เทสต์ของคนอื่น → ตอนนี้เจ้าของ/admin เท่านั้น (อย่าเผลอถอดเช็ค)
13. เคยคืน input/expected ของเทสต์ลับในผลตรวจ (ทั้ง response และ row ใน DB) → ตอนนี้ผ่าน `_redact_results` เท่านั้น
    และเก็บลง DB ที่ระดับ `REVEAL_SAMPLES` เสมอ
14. validator โจทย์รันหลาย job พร้อมกัน (`--jobs >1`) จะได้ TLE ปลอมจากการแย่ง CPU — รัน default (jobs=1)
15. `POST /api/submit` ไม่คืนผลแล้ว (202 + job_id) — frontend/สคริปต์เก่าที่อ่าน `result` จาก response ตรง ๆ จะพัง ต้อง poll `/api/jobs/{id}`
16. ตรวจ override env กับ `.env`: `server.py` โหลด `.env` เฉพาะ key ที่ยังไม่มีใน env — ตั้ง `SUPABASE_URL=` (ว่าง) เพื่อปิด DB ตอนเทส local ได้
17. **asyncio primitive ผูกกับ event loop**: `asyncio.Queue()` ที่สร้างตอน import (หรือใช้ข้าม TestClient ที่มี loop คนละตัว)
   จะค้างเงียบ ๆ — งานไม่ถูกกินเลยดูเหมือน "queued" ตลอด ใช้ `_queue()` ใน `server.py` (สร้างใหม่เมื่อ loop เปลี่ยน
   แล้วยก job ที่ค้างไปด้วย) ทุกครั้งที่ต้องแตะคิว
18. **host เป็น container เศษเสี้ยว** (prod: 0.5 vCPU / 0.5 GB) → ห้าม hardcode concurrency/limit:
   `grader.cpu_quota()` / `grader.ram_limit_mb()` อ่าน cgroup ให้, `server.py` แปลงเป็น `JUDGE_WORKERS/JUDGE_JOBS/
   MEMORY_CAP_MB/QUEUE_MAX/OVERALL_TIMEOUT/COMPILE_TIMEOUT/SAMPLE_INTERVAL` (env override ได้, 0 = auto)
   ดูค่าจริงได้ที่ `GET /api/version` → `system` และบรรทัด `[web] host: ...` ตอน boot
   - memory cap ต่อเทสต์ = ram/2: โจทย์ที่ประกาศ 512MB (panda) จะรันจริงที่ 256MB และรายงาน `limits.capped: true`
     (frontend โชว์ "(เครื่องตัดที่ X MB จาก Y MB)") — จำเป็น เพราะปล่อย 512MB ใน container 512MB = OOM killer ฆ่า server
   - endpoint ที่เป็น `def` (sync) รันใน threadpool: **ห้ามเรียก `_queue()`** ที่นั่น (ไม่มี running loop) ใช้ `_queue_depth()`
19. **Cloudflare Pages proxy ทำให้ backend เห็น IP เดียวกันทุกคน** (วัดแล้ว: ยิงผ่าน proxy 19 ครั้ง + ยิงตรง 1 ครั้ง = คนละ bucket,
   ครั้งที่ 20 ผ่าน proxy = 429) → ห้ามทำ rate limit ที่สำคัญ "ต่อ IP" อย่างเดียว ให้ล็อกต่อ **บัญชี/อีเมล** เป็นหลัก
   (ดู `_check_rate_limit(request, email)` + `ACCOUNT_MAX_TRIES`) ส่วน per-IP เหลือเป็น flood guard
   — และเพดานนี้แชร์กันทั้งเว็บ อย่าตั้งต่ำ (เดิม 20/5 นาที = ทั้งโรงเรียนล็อกอินไม่ได้)
20. leaderboard ใช้ view `leaderboard_scores` ที่รวมทุกช่วงเวลา — **อย่าลืมคอลัมน์ `name`** ใน view (โค้ดลอง select
   แบบมี/ไม่มี name แล้ว fallback เองได้ แต่จะได้ชื่อจาก 2000 แถวล่าสุดเท่านั้น) และ Settings display_name ทับชื่อใน submissions เสมอ

## 11. Definition of done (ทุกงาน)

- [ ] รัน/เทสจริงผ่าน (ไม่ใช่แค่อ่านโค้ด): CLI judge / curl endpoint / สคริปต์ verify
- [ ] รันชุดตรวจก่อน commit: `python3 tools/validate_problem.py` (ถ้าแตะโจทย์), `python3 -m unittest discover -s tests -v`
      (ถ้าแตะ backend), `node --check static/app.js && node tools/check_frontend.js` (ถ้าแตะ frontend)
- [ ] ข้อมูลเทสใน production ลบเกลี้ยง (เช็ค count)
- [ ] commit + push GitHub (และ justrunmy ถ้าแตะ backend/problems)
- [ ] verify บน production หลัง deploy (health + ฟีเจอร์ที่แก้)
- [ ] แจ้ง user ถ้ามี migration SQL ใหม่ต้องรันใน Supabase SQL Editor
- [ ] สรุปสั้นๆ ภาษาไทย ไม่มีอีโมจิ
