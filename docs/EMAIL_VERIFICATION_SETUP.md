# เตรียมอีเมลยืนยันสำหรับ Newbiegrader

สถานะ 2026-10-18: **deploy โค้ด OTP และ migration แล้ว; ผู้ดูแลสมัครด้วย OTP
จริงสำเร็จ และตรวจพบ identity ที่ verified พร้อมผูก provider ตรงกันในฐานข้อมูลแล้ว**

SQL และ env ที่ใช้ตั้งค่าอยู่ในคู่มือนี้ ส่วนผลทดสอบและบันทึก rollout
เก็บไว้เป็นเอกสารภายใน การทดสอบอีเมลสำเร็จเพียงอย่างเดียวไม่ใช่หลักฐานว่า
flow OTP ใหม่ทำงานบน production แล้ว

ตรวจพบบัญชีรหัสผ่านเดิม 3 บัญชี โดยตรวจเฉพาะจำนวน/โครงสร้างตาราง ไม่อ่าน
อีเมลหรือ hash ออกมา ตอนเริ่มเตรียมยังไม่มีบริการส่งอีเมล ภายหลังผู้ดูแลตั้ง Gmail SMTP ใน Supabase
และยืนยันว่าได้รับอีเมลทดสอบแล้ว การตั้ง SMTP อย่างเดียวไม่ปิดช่องโหว่: `/api/auth/register` และ `/api/auth/password` บน release เดิม
ตรวจรหัสผ่านเอง release ใหม่ใช้ Supabase Auth ยืนยันอีเมลก่อนออกสิทธิ์แล้ว

## สถานะหลังย้าย PC — 2026-10-22

ย้าย configuration เดิมและรักษา `SESSION_SECRET` / รุ่น identity ไว้ ทดสอบ session
ของผู้ดูแลที่ verified อยู่แล้วผ่านเว็บจริง พร้อมส่งงานและเปิดประวัติสำเร็จ
รอบย้ายเครื่องไม่ได้ส่ง OTP หรือทำ Google/password login ใหม่ จึงไม่ใช้ผลนี้
รับรองความพร้อมของผู้ให้บริการอีเมลหรือทุก flow การสมัครในปัจจุบัน
ดู [สถาปัตยกรรมปัจจุบัน](PRODUCTION_ARCHITECTURE.md)

## ตัวอย่างการตั้ง Custom SMTP

ตัวอย่างด้านล่างใช้ Resend SMTP เป็นช่องทางส่งของ Supabase Auth และใช้ email OTP เป็นหลักฐาน
เจ้าของอีเมลใน backend เดิม ไม่ต้องเปลี่ยน SPA, judge หรือฐานข้อมูลทั้งระบบ
โค้ดเชื่อม OTP ติดตั้งแล้ว ส่วนโดเมนผู้ส่งและการส่งถึงผู้รับหลากหลายยังต้องเตรียม

ตรวจโควตา ราคา และโดเมนผู้ส่งกับผู้ให้บริการในวันที่จะเปลี่ยนจริง โดยนับทั้ง
การสมัคร ส่งซ้ำ และกู้บัญชี การย้าย PC ไม่ได้เปลี่ยนผู้ให้บริการ SMTP หรือสมัคร
แพ็กเกจใหม่ ดู [ข้อมูลผู้ให้บริการ](https://resend.com/pricing)

### 1. เตรียมโดเมนผู้ส่ง

1. ใช้โดเมนที่ผู้ดูแลควบคุม DNS ได้ เช่น `auth.example.com` เป็นเพียงตัวอย่าง
   ไม่ใช่โดเมนที่ตั้งไว้แล้ว โดเมนผู้ส่งไม่จำเป็นต้องเป็นโดเมนหน้าเว็บ
2. เพิ่มโดเมนใน Resend และเพิ่ม DNS ตามค่าที่ dashboard ออกให้จนขึ้น verified
   อย่าเดาค่า SPF/DKIM หรือทับ MX เดิมถ้าใช้รับเมลอยู่
3. ตั้งผู้ส่ง เช่น `no-reply@auth.example.com` และปิด open/click tracking
   สำหรับอีเมลยืนยัน `newbiegrader.pages.dev` อย่างเดียวไม่ได้แปลว่ามีสิทธิ์
   จัดการ DNS ของโดเมนผู้ส่งที่ Resend ต้องการ

ดู [ข้อกำหนดโดเมน](https://resend.com/docs/dashboard/domains/introduction)

### 2. ตั้ง Custom SMTP ใน Supabase

เลือกโครงการที่ตรงกับ `SUPABASE_URL` ใน configuration ของ production
อย่าใช้ project ref ของ MCP/local development เป็นตัวตัดสิน แล้วเปิด Authentication → Emails → SMTP
Settings (ชื่อเมนูอาจเปลี่ยน) ตั้งค่าตามนี้ใน dashboard:

| ช่อง | ค่า |
| --- | --- |
| Sender name | Newbiegrader |
| Sender email | ที่อยู่บนโดเมนที่ verified แล้ว |
| Host | `smtp.resend.com` |
| Port | `465` พร้อม TLS หรือ `587` พร้อม STARTTLS |
| Username | `resend` |
| Password | API key ของ Resend — ใส่ใน dashboard เท่านั้น |

สร้าง key จำกัดการส่งให้โดเมนที่เลือกตามสิทธิ์ที่ผู้ให้บริการรองรับ ห้ามใส่
key ใน Git, frontend, URL, screenshot, คำสั่ง shell หรือส่งกลับในแชต
ไม่ต้องเพิ่ม SMTP credential ลง container ที่รัน judge ถ้า Supabase เป็นผู้ส่ง
ดู [SMTP ของ Resend](https://resend.com/docs/send-with-smtp)

SMTP เริ่มต้นของ Supabase ใช้ทดสอบกับอีเมลสมาชิกทีมและมีเพดานต่ำ จึงไม่ใช้เป็น
ช่องทางยืนยันสำหรับผู้ใช้สาธารณะ ดู [Custom SMTP](https://supabase.com/docs/guides/auth/auth-smtp)

### 3. การตั้ง OTP ที่ติดตั้งแล้ว

- เปิดการยืนยันอีเมลสำหรับ password provider; ไม่ใช้การยืนยันอัตโนมัติ
- ใช้ `tools/templates/auth/email_otp.html` ทั้ง Magic Link และ Confirm Sign Up
  template เพื่อให้บัญชีใหม่ได้รับรหัสด้วย ตรวจหลัง reload แล้วว่า OTP 8 หลัก
  อายุ 600 วินาที ช่วงขอซ้ำอย่างน้อย 60 วินาที และ provider ส่งได้ 30 อีเมล/ชั่วโมง
- ใช้ POST ส่งรหัสกลับ backend ไม่ใส่ OTP/access token ใน URL หรือ log
- ทดสอบส่งเฉพาะอีเมลที่ผู้ดูแลเป็นเจ้าของหลังได้รับอนุญาต ไม่ส่งไปยังบัญชีเดิม
  ทั้งสามโดยอัตโนมัติ ตั้ง rate limit ไม่ให้เกินโควตาผู้ให้บริการ
- ถ้าใช้ redirect ให้ allowlist เฉพาะ origin/callback ที่มีจริง แยก staging
  จาก production ไม่ตั้ง wildcard เพื่อให้ลิงก์ผ่าน

ดู [การตั้ง email OTP](https://supabase.com/docs/guides/auth/auth-email-passwordless)

## นโยบาย S05 ใน release ใหม่และเกณฑ์ตรวจ

1. สมัครได้เป็นสถานะ pending เท่านั้น ยังไม่ออก session ที่ส่งงาน/อ่านประวัติได้
   พิสูจน์ email OTP และ provider subject ฝั่ง server ก่อนเปิดสิทธิ์
2. เก็บหลักฐาน verified/subject และรุ่น session ด้วย migration แบบเพิ่มข้อมูล
   ไม่ย้ายหมายเลขโจทย์ ไม่เปลี่ยนเจ้าของประวัติ และไม่ลบบัญชีเดิม
3. บัญชีเดิมห้ามตั้ง verified อัตโนมัติจากแค่มี row หรือรู้รหัสผ่าน ต้องพิสูจน์
   กล่องอีเมลจริง แล้วให้เจ้าของตั้งรหัสผ่านใหม่และเพิกถอน session/remember
   เดิม เพื่อไม่ให้รหัสผ่านที่ผู้โจมตีเคยตั้งกลับมาใช้ได้
4. ผูก Google/password เฉพาะเมื่อมีหลักฐานความเป็นเจ้าของ อย่า auto-link
   จากอีเมลตรงกันอย่างเดียว สำรองก่อน migration และให้ผู้ดูแลตรวจ SQL/rollback
5. ใช้ Auth client แยกจาก Supabase service-role database client ป้องกันการล็อกอิน
   ไปเปลี่ยนสถานะ authentication ของ client ที่แชร์ข้าม request
6. Rate limit การขอ/ลอง OTP กลางทุก replica, ข้อความตอบไม่เปิดเผยว่ามีบัญชีหรือไม่
   และ mail/provider ล่มต้องไม่ให้สิทธิ์สำเร็จ

### Acceptance criteria

- attacker สมัครอีเมลเหยื่อ → ยังอ่าน/ส่งงานไม่ได้จนยืนยันอีเมลสำเร็จ
- เหยื่อยืนยัน/ผูก Google → รหัสผ่านและ session เดิมของ attacker ใช้ไม่ได้
- OTP ผิด หมดอายุ ใช้ซ้ำ หรือส่งพร้อมกัน → ไม่ได้สิทธิ์เพิ่ม
- บัญชีเดิมทั้งสามยืนยันใหม่ได้โดยประวัติและเจ้าของเดิมไม่เปลี่ยน
- signup/login/restore/history/job ทั้ง API และ proxy ใช้นโยบายเดียวกัน
- ไม่มี credential ใน response/log; outage และการย้ายหลาย replica ผ่าน canary

## Gmail สำหรับทดสอบเมื่อยังไม่มีโดเมน

ผู้ดูแลสร้างบัญชี Gmail แยก เปิด 2-Step Verification สร้าง App Password และ
บันทึกใน Supabase โดยตรงแล้ว ไม่ส่งรหัสผ่านแชต ไม่เก็บใน Git หรือ container:

| ช่อง | ค่า |
| --- | --- |
| Sender / Username | Gmail เต็มเดียวกับบัญชีที่สร้าง App Password |
| Host / Port | `smtp.gmail.com` / `465` (TLS) |
| Sender name | Newbiegrader |
| Password | App Password ของบัญชีนั้น ไม่ใช่ Google password ปกติ |

คำขอทดสอบครั้งแรกถูก Gmail ปฏิเสธ 535 เพราะ App Password คนละบัญชี หลังผู้ดูแล
แก้แล้ว Supabase ตอบ 200 และผู้ดูแลยืนยัน receipt แล้ว ไม่ได้อ่าน OTP/link
SMTP ที่ส่งถึงจริงยังไม่รับรองปริมาณการส่ง การเข้า inbox ของผู้รับอื่น หรือ flow
ยืนยันตัวตนใหม่ ใช้เป็นทางเริ่มทดสอบและเตรียม provider ที่มีโดเมนสำหรับ public

ติดตั้ง template/expiration, `SUPABASE_AUTH_KEY`, migration และ backend/frontend
ใหม่แล้ว บัญชีเดิมทั้งสามยังไม่ถูกตั้ง verified อัตโนมัติ ตรวจยืนยันว่า field เดิม
ไม่เปลี่ยนหลัง migration และสำรองตารางที่ได้รับผลกระทบแบบเข้ารหัสแล้ว
ผู้ดูแลกรอก OTP และรหัสผ่านใหม่เองในเว็บและยืนยันว่าสมัครสำเร็จแล้ว ตรวจ SQL
เฉพาะจำนวน/boolean พบ identity ครบและผูก Auth user ที่ยืนยันอีเมลตรงกัน
ไม่อ่านหรือพิมพ์ OTP/รหัสผ่าน/hash/provider subject ส่วน OTP หมดอายุหรือใช้ซ้ำ
กับ provider จริงยังไม่ได้ตรวจ มีผลผ่านเฉพาะ synthetic regression
ดู build/CI และการตรวจปัจจุบันใน [security readiness](SECURITY_READINESS.md)
และขอบเขตการกู้คืนใน [คู่มือ backup](HOST_BACKUP_RESTORE.md)
