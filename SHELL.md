# Dev OS Shell: taskbar, เมนูแอป และนาฬิกา

`tools/dev_shell.py` (ติดตั้งเป็น `/usr/bin/dev-shell`) คือ desktop shell ตัวแรกของ Dev OS:
taskbar สูง 24 พิกเซลด้านล่างจอ เขียนด้วย X11 ล้วนผ่าน ctypes/libX11 เหมือน DPK window runtime
ไม่เพิ่ม toolkit หรือ dependency ใหม่ ทดสอบจริงบน X11 display (WSLg) พร้อมจับภาพหลักฐาน

## ดีไซน์

Taskbar (สูง 24px เต็มความกว้างจอ, พื้น `0x142034`):

```
+----------+---+----------------------------------------------------+---------------------+
| MENU     | | | Dev Counter                                       | 2026-09-21 19:40:12 |
+----------+---+----------------------------------------------------+---------------------+
  ^ ปุ่มเมนู    ^ ปุ่มหน้าต่างที่เปิด (ถ้า WM มี _NET_CLIENT_LIST)        ^ วันที่+เวลา ชิดขวา
  กว้าง 64px    กว้าง 160px/ปุ่ม คลิกเพื่อยกหน้าต่างขึ้นมา                อัปเดตทุกวินาที
```

- ปุ่ม MENU ซ้ายสุด มีแถบ accent (`0x65e0bf`) 2px ใต้ปุ่ม
- ปุ่มหน้าต่างรันอยู่แสดงชื่อหน้าต่าง (ตัดด้วย `...` เมื่อยาว) — ต้องมี window manager
  ที่เผยแพร่ `_NET_CLIENT_LIST`; ถ้าไม่มี (เช่น XWayland เปล่า ๆ) ส่วนนี้ซ่อนได้
- วันที่-เวลารูปแบบ `YYYY-MM-DD HH:MM:SS` ชิดขวา ตาม timezone ของเครื่อง
- จองพื้นที่แถบล่างผ่าน EWMH (`_NET_WM_STRUT`/`_NET_WM_STRUT_PARTIAL` 24px,
  window type `DOCK`, sticky, skip taskbar/pager) หน้าต่าง maximize จึงไม่ทับ taskbar

เมนูแอป (popup กว้าง 320px ลอยเหนือปุ่ม MENU ชิดซ้ายจอ, พื้น `0x101b2c`):

```
+--------------------------------+
| DEV OS                         |  header 22px (accent)
|--------------------------------|
| Dev Counter                    |  รายการ 34px/แอป
| Utility · window,storage       |  บรรทัดรอง (categories · permissions)
|--------------------------------|
| Open Dev Counter?              |  แถวยินยอม 44px (แสดงหลังคลิกรายการ)
| window,storage   [ ALLOW ] [ cancel ] |
+--------------------------------+
```

- รายการมาจากฐานข้อมูลแพ็กเกจที่ติดตั้ง (อ่านอย่างเดียว) กรองเฉพาะแพ็กเกจที่มี `window`
  เรียงตามชื่อ label (ใช้ launcher.name → display_name → name เหมือน desktop entry)
- คลิกรายการ → แสดงแถวยินยอม: ชื่อแอป, ชุด permissions ที่แอปประกาศ, `[ ALLOW ]` `[ cancel ]`
- กด ALLOW แล้วเรียก `dev launch <name> --allow <permissions ตามที่ประกาศ>` เป็นโปรเซสแยก
  — shell ไม่เพิ่มสิทธิ์เกินที่ประกาศ ไม่จำ grants ถามทุกครั้งเหมือน `dev launch`
- คลิกนอกเมนู (pointer grab) หรือกดปุ่ม MENU ซ้ำเพื่อปิด

## ใช้งาน

ต้องอยู่ใน X11 session แล้วเท่านั้น (ยังไม่มี session เริ่มอัตโนมัติใน ISO):

```sh
dev-shell                      # บน Dev OS ที่ติดตั้ง shell แล้ว
python3 tools/dev_shell.py --root out/desktop-demo-root \
  --dev tools/dev.py           # ทดลองจาก checkout บน Linux desktop/WSLg
```

ตรวจผ่าน `python3 scripts/test-shell.py` บน display จริง: ติดตั้ง desktop-counter ลง root
จำลอง เปิด shell จับภาพ PNG แล้วตรวจพิกเซล (ความสูง 24px, MENU ซ้าย, นาฬิกาขวา,
หัวเมนู/รายการ/แถวยินยอม) ผลและภาพอยู่ที่ `out/shell-tests/`

## ขอบเขตและข้อจำกัด

- เป็นโปรเซสผู้ใช้ปกติ ไม่ใช่ส่วนของ installer หรือ boot; ISO ที่ส่งมอบยังเป็น CLI
  และยังไม่มี display manager/session ที่เริ่ม shell ให้อัตโนมัติ
- ปุ่มหน้าต่างและการยกหน้าต่างต้องมี WM ที่รองรับ EWMH; บน X server เปล่าจะเหลือ
  MENU + นาฬิกาซึ่งยังใช้งานได้
- การยินยอมของ shell เทียบเท่า `dev launch` แบบพิมพ์ yes ใน terminal: เป็น explicit
  consent ต่อการเปิดครั้งนั้น ไม่ใช่การขยายสิทธิ์; ผู้ที่อยู่หน้าจอเห็นข้อความเดียวกัน
- ภาพหลักฐานจาก WSLg: การจับภาพ override-redirect window ไม่ได้บน XWayland
  โหมดจับภาพจึงใช้หน้าต่างปกติชั่วคราว และต้องวาดซ้ำหลังรอ compositor
  ก่อน `XGetImage` — เป็นพฤติกรรมของสภาพแวดล้อมทดสอบ ไม่ใช่ของเวลาใช้งานจริง
- ยังไม่มี systray, notification center, คีย์ลัด, multi-monitor แยก
  (taskbar วาดเต็มความกว้างรวมทุกจอ), หรือการตั้ง timezone จาก shell
