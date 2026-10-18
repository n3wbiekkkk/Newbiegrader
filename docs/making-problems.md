# มาตรฐานสร้างโจทย์สำหรับทุก AI / ผู้เขียน

ใช้เอกสารนี้กับ `AGENTS.md` ทุกครั้งที่สร้างหรือแก้โจทย์ มาตรฐานและ template อยู่ใน
Git เพื่อให้ AI คนละตัวหรือคนละ session ใช้โครงสร้าง รูปแบบ PDF และขั้นตรวจเดียวกัน
เนื้อเรื่องยังต้องผ่านการอ่านทวน เครื่องมือตรวจไม่ได้รับรองความถูกต้องเชิงความหมาย

## 1. แหล่งข้อมูลและสิ่งที่ต้องตกลงก่อนเขียน

- `config.json`: ชื่อ `ชื่อไทย (English Name)`, เลขถาวร, เวลา, หน่วยความจำ,
  checker, difficulty, tags และรายชื่อ public samples
- `statement.md`: เรื่องที่สัมพันธ์กับชื่อ กติกาครบ และ Input/Output ที่ไม่กำกวม
- `tests/*.in|out`: แหล่งข้อมูลตัวอย่างจริง ห้ามคัดลอกแล้วแก้ซ้ำใน statement ด้วยมือ
- `input_validator.py`: grammar/constraints ของ input ทั้ง public และ hidden
- `examples/<id>_ref.py` หรือ `.cpp`: reference ตามกติกาเดียวกัน ใช้ engine เดิมตัดสิน
- `tools/make_statement_tex.py` + `tools/fonts/`: รูปแบบ PDF กลาง ห้ามสร้าง renderer
  หรือแต่งฟอนต์ ระยะขอบ และ template ใหม่แยกตาม AI
- `problems/`, `examples/` และไฟล์ build ภายในนั้นเป็นข้อมูลส่วนตัวที่ Git ignore
  source of truth ที่เผยแพร่คือ Supabase ห้าม force-add tests/เฉลยเข้า public repo

ก่อนสร้าง ให้สรุป I/O contract: ทุกบรรทัดมีกี่ค่า ชนิดและช่วงค่า ตัวคั่น ขนาดตาราง
ลำดับคำตอบ EOF และกรณีพิเศษ ตารางจำนวนเต็มคั่นช่องว่าง (`0 1 0`) กับสตริงติดกัน
(`010`) เป็นคนละรูปแบบ ต้องเลือกตามโจทย์และใช้ให้ตรงในทุกไฟล์ ส่วน output อาจใช้
ตัวคั่นต่างจาก input ได้ แต่ต้องเขียนให้ชัด ห้ามอนุมานว่าเหมือนกันเอง

เรื่องเล่าต้องใช้คำเรียกคงที่ อธิบายว่าต้องหาค่าอะไร ระบุการเปลี่ยนสถานะพร้อมกันหรือ
ตามลำดับให้ครบ และไม่เพิ่มกติกาแฝงจากเรื่อง ห้ามมีหัวข้อคำใบ้/วิธีทำ/เฉลย
อย่าแต่ง subtasks หรือเกณฑ์คะแนนเพิ่ม ถ้าโจทย์เดิมไม่ได้ระบุไว้

## 2. สร้างจาก template เดียว

ตรวจ working tree และเลขที่ใช้แล้วก่อน ห้ามแตะไฟล์งานอื่นหรือเปลี่ยนเลขโจทย์เดิม:

```sh
git status --short
python tools/number_problems.py --list
python tools/number_problems.py --check
python tools/problem_authoring.py new new_problem \
  --thai 'ชื่อภาษาไทย' --english 'English Name' --no 69
```

`69` เป็นเพียงตัวอย่าง ต้องเลือกเลขที่ยังไม่ใช้จริง โจทย์ contest ใช้ `--hidden`
และเลขตั้งแต่ `1001` เครื่องมือไม่เขียนทับโฟลเดอร์/reference เดิม ไม่ใช้เลขซ้ำ
และไม่ติดต่อฐานข้อมูล สร้างไฟล์จาก `tools/templates/problem/`:

- `config.json` เริ่มที่ 1 วินาที / 256 MB / token / easy / Implementation
  ปรับตามข้อกำหนดจริง โดย tags ต้องอยู่ใน `grader.KNOWN_TAGS`
- `statement.md` ใช้ลำดับ Input → Output → ตัวอย่าง → คำอธิบายตัวอย่าง → Limits
- `input_validator.py` และ reference เป็นร่างที่ **ยังไม่ผ่าน** จนกว่าจะเขียนจริง

กรอก TODO ทั้งหมด ไม่ใช้ default แทนการตัดสินใจเรื่อง limits หรือ difficulty
ถ้ายอมหลายคำตอบ ต้องกำหนดคำตอบที่เป็นเอกลักษณ์หรือใช้ checker ที่รองรับจริง
checker `token` ไม่ยอมรับคำตอบคนละค่าแม้ว่าจะเป็นคำตอบที่โจทย์เปิดให้เลือกได้

## 3. สร้าง tests และ input validator

- อย่างน้อย 10 ชุด: public `01`, `02`, `03` และ hidden `1001..` ต่อเนื่อง
- ประกาศ public samples ใน `config.samples` ตามลำดับตัวอย่าง ใช้ชื่อเลขสองหลัก
- UTF-8, LF, มี newline ปิดไฟล์ ทุก `.in` ต้องมี `.out` คู่กัน
- ตัวอย่างสั้น อ่านได้ (ไม่เกิน 40 input tokens); มีคำอธิบายที่ตรงข้อมูลทุกชุด
- ครอบคลุม min/max, edge cases, กรณีเฉพาะ, random แบบระบุ seed และ stress
- สร้าง expected ด้วย reference ที่ตรวจแล้ว ใช้ `check=True` และ timeout เมื่อรัน
  ห้ามเขียน `.out` ต่อเมื่อ reference crash/timeout และอย่าใช้ reference เพียงตัวเดียว
  เป็นหลักฐานความถูกต้อง: เทียบกับ brute force/วิธีอิสระบนเคสเล็กด้วย

`input_validator.py` เป็น **trusted author tool** ไม่ใช่โค้ดผู้ส่ง ไม่ถูกรันใน production
และไม่ถูกอัปโหลดโดย importer ต้องอ่านหนึ่ง input จาก stdin, exit 0 เมื่อถูกต้อง,
exit nonzero เมื่อผิด ตรวจชนิด/ช่วงค่า จำนวนแถว ความยาวแถว ตัวคั่น เงื่อนไขข้ามฟิลด์
และไม่มีข้อมูลเกิน EOF อย่าพิมพ์ input หรือ expected ลง log และอย่าเขียน validator
ที่รับทุกอย่าง การใช้ `split()` อย่างเดียวอาจจับตารางผิดรูปแบบไม่ได้

`validate_problem.py` เรียก validator กับ **ทุก** `.in` ที่จับคู่แล้ว มี deadline 2 วินาที
ต่อไฟล์และทิ้ง stdout/stderr รายงานเฉพาะชื่อเคสและ exit code/timeout
ผู้เขียนต้องทดสอบ negative inputs ด้วย เช่น แถวติดกัน จำนวนคอลัมน์ผิด ค่านอกช่วง
และข้อมูลเกินท้ายไฟล์ กรณี `forest_fire_spread` ต้องปฏิเสธ `010` เมื่อ C = 3

## 4. ดึงตัวอย่างจากไฟล์เทสต์ ไม่พิมพ์ซ้ำ

```sh
python tools/problem_authoring.py sync-samples new_problem --write
python tools/problem_authoring.py sync-samples new_problem
```

คำสั่งแรกแทนที่เฉพาะส่วน `## ตัวอย่าง` ด้วย public fixtures ตาม config ไม่แก้เรื่อง
Input/Output คำอธิบาย หรือเทสต์ และไม่ดึง hidden cases มาใส่ คำสั่งที่สองตรวจอย่างเดียว
ถ้าไม่ตรงจะ exit 1 ตัวอย่างแต่ละชุดมี fenced block พร้อม `input:` / `output:`

Validator บังคับให้ตัวอย่างตรง public fixtures ตามลำดับ **รวมช่องว่างและการขึ้นบรรทัด**
ยกเว้น newline ปิดไฟล์หนึ่งตัว mismatch เป็น FAIL ไม่ใช่ WARN
ถ้าแก้ input ต้องแก้ contract/parser/validator และชุดทดสอบให้สอดคล้อง แล้ว sync ใหม่
ห้าม sync ทับเพื่อซ่อนข้อผิดพลาดในข้อกำหนด

## 5. สร้างและตรวจ PDF

```sh
python tools/make_statement_tex.py new_problem --output-dir output/pdf/previews
python tools/make_statement_tex.py new_problem
mkdir -p tmp/pdfs/new_problem
pdftotext problems/new_problem/statement.pdf -
pdftoppm -png -r 100 problems/new_problem/statement.pdf tmp/pdfs/new_problem/page
```

เปิดดูภาพ **ทุกหน้า**: ไม่มีข้อความหาย/ล้น/ทับกัน ตัวอย่างอ่านได้ ภาษาไทยไม่เป็นสี่เหลี่ยม
ใช้ A4 ขอบบน 1.2 ซม. ขอบล่าง/ซ้าย/ขวา 2.2 ซม., ชื่อไทย 26pt + อังกฤษขนาดเล็กกว่า, limits 12pt,
เนื้อไทย 17.3pt, หัวข้อ 22pt, ตาราง input/output สองคอลัมน์ไม่มีแถบสี
และเลขหน้าล่างขวา ไม่บังคับจำนวนหน้าให้เท่ากัน

หัวหน้าแรกใช้ไอคอน `static/logo-icon.png` คู่กับชื่อ `newbiegrader` ไม่มีจุดท้าย
ใช้ Anuphan เช่นหัวเว็บ วางกึ่งกลางเหนือชื่อโจทย์ พร้อมเส้นคั่นบาง
ทุกข้อใช้ `brand_header()` จาก renderer กลาง ห้ามแทรกโลโก้ซ้ำใน statement.md

เครื่องมือหยุดก่อนเรียก tectonic หาก sample ไม่ตรง สร้าง `statement.build.json`
คู่กับ PDF เก็บ hash ของ statement/metadata ที่ใช้ render, renderer, ฟอนต์, โลโก้ และ PDF
เมื่อแก้แหล่งข้อมูลแล้วไม่ rebuild ตัวตรวจจะ FAIL ว่า PDF เก่า preview มี build record
ของตัวเองและไม่เขียนทับไฟล์ติดตั้ง hash นี้ตรวจความเก่า ไม่แทนการตรวจภาพหรือยืนยันว่า
PDF ถูกต้องเมื่อผู้เขียนจงใจปลอม record

ก่อนแก้โจทย์เดิม สำรอง config, statement/PDF, tests และ reference ไว้ในพื้นที่ส่วนตัว
โจทย์ไม่ได้อยู่ใน Git จึงห้ามพึ่ง `git checkout -- problems/...` สำหรับกู้คืน
ถ้าแค่แต่งเรื่อง ห้ามเปลี่ยน rules/limits/เลข/sample/outputs เพื่อให้เรื่องเข้ากัน

## 6. ประตูตรวจบังคับสำหรับโจทย์ใหม่

```sh
python tools/validate_problem.py new_problem --strict
python tools/number_problems.py --check
python tools/validate_problem.py
python -m unittest discover -s tests -v
python tools/plagiarism.py
python -m compileall -q grader.py server.py judge_runner.py tools
node --check static/app.js
node tools/check_frontend.js
node tools/check_styles.js
node --test tests/test_*.js
```

โหมด `--strict` ต้องมี validator, PDF/build record ปัจจุบัน, หัวข้อและชื่อถูกแบบ,
ไม่มี TODO/TBD และไม่มี WARN; ไม่มี `problems/` หรือไม่มีข้อให้ตรวจถือว่าล้มเหลว
reference ต้อง AC ทุกเคสผ่าน `grader.prepare_command` / `grader.judge_test` เดิม

เขียน solution ผิดโดยตั้งใจหลายแบบแล้วตรวจให้ตกที่เคสที่คาดไว้ อย่าลดความเข้ม checker
เพื่อให้ reference หรือโค้ดผิดผ่าน เก็บผลการรันจริงและข้อจำกัดของเครื่องทดสอบในรายงาน

โจทย์เดิมยังใช้ compatibility mode ได้ระหว่างทยอยเพิ่ม validator/build record
แต่ sample mismatch เป็น FAIL ทุกโหมด หากมี build record จะตรวจความเก่าทุกโหมด
ห้ามแก้ tests/rules ของโจทย์เดิมเพียงเพื่อให้ผ่าน strict
CI มี synthetic authoring tests ใน Git จึงตรวจเครื่องมือได้แม้ไม่มีโจทย์ส่วนตัว

## 7. เผยแพร่และตรวจของจริง

เก็บ credentials ใน environment ของเครื่องมือฝั่ง server ไม่พิมพ์ค่าลงคำสั่งหรือ log
สำหรับโจทย์ใหม่ที่ได้รับอนุญาตให้เผยแพร่:

```sh
python tools/import_problems_supabase.py --problem new_problem --strict --dry-run
python tools/import_problems_supabase.py --problem new_problem --strict
```

`--strict` ตรวจ local ทั้งหมดก่อนติดต่อ Supabase; ถ้าไม่ผ่าน ไม่มี remote writes
ทุกโหมดของ CLI มี sample/build preflight แม้ไม่ได้ใช้ strict ส่วน `--dry-run`
ตรวจความพร้อมเท่านั้น **ไม่ได้** อัปโหลดหรือพิสูจน์ว่า publish สำเร็จ
ตรวจ metadata, samples, tests hash, PDF และสิทธิ์เข้าถึงบนเว็บหลัง publish จริง

สำหรับแก้เฉพาะเรื่อง/PDF ของข้อเดิม ใช้ `--statements-only --problem <id>`
พร้อม dry-run ก่อน โหมดนี้ไม่แก้เทสต์/เลข/visibility และห้ามใช้เพื่อเผยแพร่การเปลี่ยน input
สำรองแถวเดิมและ assets ก่อนอัปเดตเสมอ importer ปกติไม่ใช่ transaction ข้าม Storage/DB
ถ้าแก้ชุดเทสต์ของโจทย์เดิม ต้องตรวจ active jobs และวางแผน rollback ของไฟล์กับ row

local source ต้อง restart หลังเปลี่ยนโจทย์; Supabase source มี metadata TTL refresh
ให้ตรวจว่า `/api/version` และ problem detail เห็น hash รุ่นใหม่ก่อนสรุปว่างานเสร็จ
commit/push เฉพาะ code/docs/tools ที่เปลี่ยน ห้าม `git add -A` หรือ force-add ข้อมูลส่วนตัว

## Prompt ย่อสำหรับ AI ตัวอื่น

> อ่าน AGENTS.md และ docs/making-problems.md ใช้ tools/problem_authoring.py กับ
> template กลาง ระบุ I/O contract ก่อนเขียน ใช้ input_validator.py ตรวจทุกเคส
> ดึง samples จาก fixtures ด้วย sync-samples และสร้าง PDF ด้วย make_statement_tex.py
> เท่านั้น ตรวจภาพทุกหน้า ต้องผ่าน validate_problem.py <id> --strict พร้อม reference
> และ negative tests จริงก่อน import --strict รายงานผลการรันและข้อจำกัดตามจริง
> ห้ามเปลี่ยนเลข/rules/tests ของโจทย์เดิมนอกงาน ห้ามเผย hidden tests/เฉลย/credentials
