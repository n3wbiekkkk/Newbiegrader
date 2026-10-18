# เตรียมอีเมลยืนยันสำหรับ Newbiegrader

สถานะ 2026-10-18: **เตรียมการเท่านั้น — S05 ยัง OPEN**

ตรวจพบบัญชีรหัสผ่านเดิม 3 บัญชี โดยตรวจเฉพาะจำนวน/โครงสร้างตาราง ไม่อ่าน
อีเมลหรือ hash ออกมา ผู้ดูแลยืนยันว่ายังไม่มีบริการส่งอีเมล การตั้ง SMTP
อย่างเดียวไม่ปิดช่องโหว่: `/api/auth/register` และ `/api/auth/password` ปัจจุบัน
ตรวจรหัสผ่านเอง ยังไม่ได้เรียก Supabase Auth เพื่อยืนยันอีเมล

## วิธีที่แนะนำ

ใช้ Resend SMTP เป็นช่องทางส่งของ Supabase Auth และใช้ email OTP เป็นหลักฐาน
เจ้าของอีเมลใน backend เดิม ไม่ต้องเปลี่ยน SPA, judge หรือฐานข้อมูลทั้งระบบ
ขั้นเชื่อม OTP และย้ายบัญชียังต้องทำและทดสอบก่อนเปิดใช้จริง

Resend Free ระบุ 3,000 อีเมล/เดือน และ 100/วัน ณ วันที่ตรวจ ต้องประเมินทั้ง
การสมัคร ส่งซ้ำ และกู้บัญชี รวมถึงค่าโดเมนแยกต่างหาก ไม่ได้สมัครแผนเสียเงิน
หรือเปิด overage ให้ในรอบนี้ ดู [ราคาปัจจุบัน](https://resend.com/pricing)

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

เลือกโครงการ **qblnlfzjublfnnsasgpe** แล้วเปิด Authentication → Emails → SMTP
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

### 3. เตรียม OTP โดยยังไม่เปลี่ยนเส้นทางล็อกอินจริง

- เปิดการยืนยันอีเมลสำหรับ password provider; ไม่ใช้การยืนยันอัตโนมัติ
- เมื่อนำ flow เข้า staging ใช้ `tools/templates/auth/email_otp.html` ใน Magic Link
  template เพื่อส่งรหัส OTP; ตั้งอายุ 600 วินาทีและช่วงขอซ้ำอย่างน้อย 60 วินาที
- ใช้ POST ส่งรหัสกลับ backend ไม่ใส่ OTP/access token ใน URL หรือ log
- ทดสอบส่งเฉพาะอีเมลที่ผู้ดูแลเป็นเจ้าของหลังได้รับอนุญาต ไม่ส่งไปยังบัญชีเดิม
  ทั้งสามโดยอัตโนมัติ ตั้ง rate limit ไม่ให้เกินโควตาผู้ให้บริการ
- ถ้าใช้ redirect ให้ allowlist เฉพาะ origin/callback ที่มีจริง แยก staging
  จาก production ไม่ตั้ง wildcard เพื่อให้ลิงก์ผ่าน

ดู [การตั้ง email OTP](https://supabase.com/docs/guides/auth/auth-email-passwordless)

## แผนแก้ S05 ที่ต้องผ่านก่อน rollout

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

ยังไม่ได้ตั้ง DNS, ออก API key, ส่งอีเมลจริง, แก้ Supabase Auth settings,
เปลี่ยนตาราง production หรือย้ายบัญชีในรอบนี้
