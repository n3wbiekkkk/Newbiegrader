# agent.md — คู่มือสำหรับ AI session ใหม่ (อ่านไฟล์นี้ก่อนเสมอ)

> ภาษาตอบผู้ใช้: ไทย สั้น กระชับ ห้ามใช้อีโมจิ
> หลัก: verify ด้วยการรันจริงทุกครั้งก่อนสรุป ห้ามเดา

## 1. ภาพรวมโปรเจกต์

Newbiegrader = เว็บสนามสอบเขียนโปรแกรม (Python / C / C++) ตรวจอัตโนมัติแบบโหด
- โจทย์มาจากไฟล์ PDF → `problems/<id>/` (statement.pdf + statement.md + config.json + tests 10 ข้อ)
- Frontend: `static/` HTML/CSS/JS ล้วน **ไม่มี build step** (Home/Tasks/Archive/Leaderboard/History/Settings)
- Backend: `server.py` (FastAPI) reuse logic จาก `grader.py` ตรงๆ (ห้ามเขียน judge ซ้ำ)
- DB: Supabase Postgres (ตาราง `submissions`, `profiles`, `reports`) — ดู `supabase/schema.sql`
- Login: Google OAuth (บังคับก่อนส่ง) + session cookie
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
grader.py            # engine: run_one/judge_test/checkers/CLI (stdlib ล้วน)
server.py            # FastAPI: /api/* + serve static/ (โหลด .env local ถ้ามี)
static/              # index.html styles.css app.js (?v=N กัน cache) config.js (+ vercel.json legacy ไม่ใช้แล้ว)
functions/api/[[proxy]].js  # Cloudflare Pages Function: proxy /api ไป backend
problems/<id>/       # statement.pdf statement.md config.json tests/*.in|*.out
examples/*_ref.py    # reference solution ประจำข้อ (single source of truth ตอน gen test)
supabase/schema.sql  # schema + migration ทั้งหมด (append-only, อย่าลบของเก่า)
.env.example         # template env (ห้าม commit .env จริง)
requirements.txt     # fastapi uvicorn python-multipart supabase itsdangerous
Dockerfile           # backend image (python:3.11-slim + gcc/g++)
render.yaml          # (เลิกใช้ Render แล้ว เก็บไว้เฉยๆ)
agent.md             # ไฟล์นี้
```

## 4. Workflow: เพิ่มโจทย์จาก PDF

1. ผู้ใช้วาง PDF ใน `problems/` → ย้ายเป็น `problems/<id>/statement.pdf` (id ตัวเล็ก, `git mv`)
   - ถ้าโจทย์มาเป็น **ภาษาอังกฤษหรือ text (ไม่มี PDF ไทย)**: แปล/เขียน `statement.md` ไทยเอง
     (เก็บเรื่องราวครบ ห้ามย่อ) แล้วทำ `statement.pdf` ด้วย LaTeX เท่านั้น:
     `python3 tools/make_statement_tex.py <id>` (tectonic + TH Sarabun, คณิตสวย, ตัวอย่างเป็นกล่องคู่ —
     verify ด้วย pdftotext + เปิดภาพดูทุกข้อก่อน commit)
2. อ่าน PDF (tool `read` อ่าน PDF ได้) แล้วสร้าง:
   - `config.json`: `{"title","time_limit":1.0,"memory_limit":256,"checker":"token|exact|float|decimal2","difficulty":"easy|medium|hard","tags":[...],"notice":"..."}` (tags ต้องอยู่ใน KNOWN_TAGS ใน `grader.py`; `notice` โชว์แบนเนอร์บนหน้า task)
   - `statement.md`: spec ภาษาไทย (input/output/constraints/subtasks/ตัวอย่าง) — **ห้ามใส่ section กับดัก** (นโยบาย: ไม่บอกใบ้)
   - `tests/01..10.in/.out`: ข้อ 01+ = ตัวอย่างใน PDF (ต้องตรงเป๊ะ), ที่เหลือ edge + random (seeded) + max constraint
   - `examples/<id>_ref.py`: reference solution ที่ถูกต้อง
3. Verify 3 ชั้น (บังคับ): (a) ตัวอย่างตรง PDF (b) gen logic กับ ref ตรงกัน byte-for-byte (c) cross-check อิสระ (เช่น greedy vs DP, Miller-Rabin + Pollard-Rho สำหรับ prime)
4. Judge ref ผ่าน CLI ต้อง `ACCEPTED 10/10` + ลอง solution ผิดต้องได้ WA (กัน test หลวม)
5. Restart local server (problems โหลดตอน boot) → เทสเว็บ → commit + push GitHub + push justrunmy (ข้อ 7)

checker ที่มี: `token` (default), `exact` (byte, ผ่อน newline ท้ายไฟล์), `float` (tolerance 1e-6),
`decimal2` (เฉพาะ mana: ทศนิยม 2 ตำแหน่งเท่านั้น แต่ไม่หัก space เกิน) — ดู `check_decimal2` ใน `grader.py`

## 5. Workflow: แก้ frontend (`static/`)

- ไม่ต้อง build/restart (StaticFiles อ่านจาก disk ทุก request) — แต่ Pages ต้อง redeploy (auto จาก push `main`)
- **ทุกครั้งที่แก้ `app.js`/`styles.css` ให้ bump `?v=N` ใน `index.html`** (กัน browser cache ค้าง) — เลขปัจจุบันดูในไฟล์
- ห้ามใช้ emoji ใน UI — icon ใช้ SVG sprite (`<symbol id="i-*">` ใน `index.html` + helper `icon()` ใน `app.js`)
- หลังแก้: `node --check static/app.js` + สคริปต์เช็คว่า `$("...")` ทุกตัวมี id ใน HTML (ดูตัวอย่างในประวัติ commit "UI/UX polish")
- Dark mode ผ่าน `[data-theme="dark"]` + CSS vars — สี hardcode ต้องใช้ var (`--field`, `--on-acc`)

## 6. Workflow: แก้ backend (`server.py`)

- เพิ่ม endpoint → เทส local ก่อนเสมอ (server local: `GRADER_CORS_ORIGINS=https://gradernew.pages.dev python3 server.py --port 8000`)
- **Login จำลองโดยไม่ต้องผ่าน Google**: สมัคร/ล็อกอินผ่าน password API แล้วเก็บ cookie เอง:
```python
from httpx import Client
c = Client(base_url="http://127.0.0.1:8000", timeout=90)
c.post("/api/auth/register", json={"email": "test@example.com", "password": "testpass123", "name": "t"})
# login ซ้ำใช้ c.post("/api/auth/password", json={...}) — cookie ng_session ติดมาเอง
```
(ห้าม forge cookie เอง: session ใช้ Starlette SessionMiddleware + one-time token ผ่าน `/api/auth/finish`)
- Supabase local test: ตั้ง `SUPABASE_URL` + `SUPABASE_KEY` (service_role) ใน env แล้วเทส **ห้ามลืมลบข้อมูลเทส** (delete by id/email ทันทีหลังเทส, เช็ค count กลับเท่าเดิม)
- Session ใช้ `ng_session` (HttpOnly, SameSite=lax + Secure ใน prod — same-origin ผ่าน Pages proxy เลยไม่ต้องใช้ None) — flow เต็ม: `/api/auth/login` → Google → `/api/auth/callback` (ผ่าน Pages Function proxy เพื่อให้ session อยู่ origin เดียวกัน) → mint one-time token → `/api/auth/finish` ตั้ง cookie first-party → redirect หน้าเว็บ
- CORS: `allow_methods` ต้องครอบคลุม method ที่ frontend ใช้ (เคยลืม PUT จนปุ่ม settings พัง) + `allow_credentials=True`
- `ADMIN_EMAILS` default = เมลเจ้าของในโค้ด (override ผ่าน env ได้)

## 7. Workflow: deploy

```bash
# 1) GitHub (frontend auto-redeploy)
git add -A && git commit -m "..." && git push origin main
# 2) Backend (เฉพาะเมื่อแก้ server.py/grader.py/requirements/Dockerfile/problems/)
#    ใช้ remote ชื่อ deploy (ตั้งครั้งเดียวในเครื่องนี้ ไม่ถูก commit):
#    git remote add deploy <git-url จาก justrunmy panel>
git push deploy HEAD:deploy
```
- หลัง push backend รอ ~45วิ แล้ว verify: `curl https://grader.n.onjrnm.vip/api/health`
- ถ้า push แล้ว error "image built on different server": รอ 1 นาที push ซ้ำ (empty commit ได้) ถ้ายังพังให้ user กด recreate ที่ panel
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
- ด่วน: git credentials ของ justrunmy เคยหลุดในประวัติ (`9b66670..c7361bd`, ลบออกแล้วแต่ยังอยู่ใน history)
  → ให้ user reset ที่ justrunmy panel แล้ว `git remote set-url deploy <url ใหม่>` ในเครื่องนี้

## 9. Database

- เปลี่ยน schema → append ลง `supabase/schema.sql` (ใช้ `if not exists` เสมอ) + ให้ user รันใน SQL Editor (agent รัน DDL เองไม่ได้)
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
10. `static/vercel.json` คือ legacy สมัย Vercel (ไม่ใช้แล้ว) — ปัจจุบัน proxy `/api/:path*` → backend คือ `functions/api/[[proxy]].js` บน Pages
11. Push justrunmy ใช้ `HEAD:deploy` (branch แยกจาก `main`, ไม่มีผลกับ GitHub)

## 11. Definition of done (ทุกงาน)

- [ ] รัน/เทสจริงผ่าน (ไม่ใช่แค่อ่านโค้ด): CLI judge / curl endpoint / สคริปต์ verify
- [ ] ข้อมูลเทสใน production ลบเกลี้ยง (เช็ค count)
- [ ] commit + push GitHub (และ justrunmy ถ้าแตะ backend/problems)
- [ ] verify บน production หลัง deploy (health + ฟีเจอร์ที่แก้)
- [ ] สรุปสั้นๆ ภาษาไทย ไม่มีอีโมจิ
