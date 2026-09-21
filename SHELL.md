# Dev OS Shell: taskbar, เมนูแอป และนาฬิกา

`tools/dev_shell.py` (ติดตั้งเป็น `/usr/bin/dev-shell`) คือ desktop shell ตัวแรกของ Dev OS:
taskbar สูง 24 พิกเซลด้านล่างจอ เรนเดอร์ด้วย **Cairo** ผ่าน ctypes บน X11 — ฟอนต์ TrueType
แบบ anti-alias (ผ่าน fontconfig), ไล่เฉดสี, มุมโค้งและความโปร่งใสจริงบน visual 32-bit ARGB
เมื่อ display รองรับ ต้องมี `libcairo`, `fontconfig` และฟอนต์ TTF (เช่น DejaVu Sans) ใน image

## ดีไซน์

Taskbar (สูง 24px เต็มความกว้างจอ):

```
+----------+---+----------------------------------------------------+---------------------+
| MENU     | | | Dev Counter                                       | 2026-09-21 19:40:12 |
+----------+---+----------------------------------------------------+---------------------+
  ^ ปุ่มเมนู    ^ ปุ่มหน้าต่างที่เปิด (ถ้า WM มี _NET_CLIENT_LIST)        ^ วันที่+เวลา ชิดขวา
  แคปซูลโค้ง    แคปซูลโค้งขอบบาง คลิกเพื่อยกหน้าต่างขึ้น                 AA ตลอดตัวอักษร
```

- พื้น taskbar เป็น gradient แนวตั้ง (เข้ม→อ่อนเล็กน้อย) มีเส้น hairline สีมิ้นต์โปร่งแสง
  คั่นกับพื้นที่ทำงานด้านบน
- ปุ่ม MENU เป็นแคปซูลมุมโค้งพื้นมิ้นต์โปร่งแสง ตัวอักษรหนาสีมิ้นต์
- ปุ่มหน้าต่างรันอยู่เป็นแคปซูลโค้งขอบบาง แสดงชื่อหน้าต่าง (ตัดด้วย `...`) — ต้องมี
  window manager ที่เผยแพร่ `_NET_CLIENT_LIST`; ถ้าไม่มี ส่วนนี้ซ่อนได้
- วันที่-เวลารูปแบบ `YYYY-MM-DD HH:MM:SS` ชิดขวา อัปเดตทุกวินาที ตาม timezone ของเครื่อง
- จองพื้นที่แถบล่างผ่าน EWMH (`_NET_WM_STRUT`/`_STRUT_PARTIAL` 24px, window type `DOCK`,
  sticky, skip taskbar/pager) หน้าต่าง maximize จึงไม่ทับ taskbar

เมนูแอป (popup กว้าง 320px ลอยเหนือปุ่ม MENU ชิดซ้ายจอ):

```
╭─────────────────────────────╮
│ ● DEV OS                    │  header 26px: จุดมิ้นต์ + ชื่อหนา + เส้นคั่นโปร่งแสง
│                             │
│ Dev Counter                 │  รายการ 36px/แอป: ชื่อหนา AA
│ Utility · window,storage    │  บรรทัดรองสีจาง (categories · permissions)
│ ╭─────────────────────────╮ │
│ │ Open Dev Counter?        │ │  แถวยินยอม 52px พื้นมิ้นต์โปร่งแสงมุมโค้ง
│ │ window,storage  (ALLOW)  │ │  ชิป ALLOW มุมโค้งพื้นมิ้นต์ ตัวอักษรเข้ม
│ ╰─────────────────────────╯ │
╰─────────────────────────────╯
```

- แผงเมนูมุมโค้ง 12px พร้อมเงาโปร่งแสงเมื่อใช้ visual 32-bit ARGB (โปร่งใสจริงเห็น
  desktop ตอนลอย) — ถ้า display ไม่มี visual 32-bit จะเป็นพื้นทึดแทน
- รายการมาจากฐานข้อมูลแพ็กเกจที่ติดตั้ง (อ่านอย่างเดียว) กรองเฉพาะแพ็กเกจที่มี `window`
  เรียงตาม label (launcher.name → display_name → name เหมือน desktop entry)
- คลิกรายการ → แถวยินยอม; กด `ALLOW` แล้วเรียก `dev launch <name> --allow
  <permissions ตามที่ประกาศ>` เป็นโปรเซสแยก — shell ไม่เพิ่มสิทธิ์เกินที่ประกาศ
  ไม่จำ grants ถามทุกครั้งเหมือน `dev launch`
- คลิกนอกเมนู (pointer grab) หรือกดปุ่ม MENU ซ้ำเพื่อปิด

## ใช้งาน

ต้องอยู่ใน X11 session แล้วเท่านั้น (ยังไม่มี session เริ่มอัตโนมัติใน ISO) และระบบต้องมี
`libcairo.so.2`, `fontconfig` กับฟอนต์ TTF (Buildroot: `libcairo`, `fontconfig`,
`dejavu-fonts`) — WSLg ของตัวทดสอบมีครบโดยไม่ต้องติดตั้งเพิ่ม:

```sh
dev-shell                      # บน Dev OS ที่ติดตั้ง shell แล้ว
python3 tools/dev_shell.py --root out/desktop-demo-root \
  --dev tools/dev.py           # ทดลองจาก checkout บน Linux desktop/WSLg
```

ตรวจผ่าน `python3 scripts/test-shell.py` บน display จริง: ติดตั้ง desktop-counter ลง root
จำลอง เปิด shell จับภาพ PNG แล้วตรวจพิกเซลระดับความละเอียด (จำนวนเฉดสีจาก AA/gradient
ของ bar และเมนู, ตำแหน่ง MENU/นาฬิกา, มุมโค้งและชิป ALLOW) ผลและภาพอยู่ที่ `out/shell-tests/`

## ขอบเขตและข้อจำกัด

- เป็นโปรเซสผู้ใช้ปกติ ไม่ใช่ส่วนของ installer หรือ boot; ISO ที่ส่งมอบยังเป็น CLI
  และยังไม่มี display manager/session ที่เริ่ม shell ให้อัตโนมัติ และ image ปัจจุบัน
  ยังไม่รวม libcairo/fontconfig — ต้องเพิ่มในการ rebuild ครั้งหน้า
- ปุ่มหน้าต่างและการยกหน้าต่างต้องมี WM ที่รองรับ EWMH; บน X server เปล่าจะเหลือ
  MENU + นาฬิกาซึ่งยังใช้งานได้
- การยินยอมของ shell เทียบเท่า `dev launch` แบบพิมพ์ yes ใน terminal: เป็น explicit
  consent ต่อการเปิดครั้งนั้น ไม่ใช่การขยายสิทธิ์
- ข้อจำกัดของสภาพแวดล้อมทดสอบ (XWayland บน WSLg): จับภาพหน้าต่าง ARGB หรือ
  override-redirect ไม่ได้ โหมดจับภาพหลักฐานจึงใช้ visual ปกติและวาดพื้น "desktop"
  จำลองให้เห็นมุมโค้ง ส่วนตอนใช้งานจริงได้โปร่งใสเต็มรูปแบบ; การจับภาพยังต้องวาดซ้ำ
  หลังรอ compositor หนึ่งรอบ
- ฟอนต์ตามที่ fontconfig ให้ (ค่าเริ่มต้น DejaVu Sans) — การแสดงภาษาอื่นนอกจาก
  Latin/Cyrillic/Greek ต้องมีฟอนต์ครอบคลุมติดตั้งเพิ่ม
- ยังไม่มี systray, notification center, คีย์ลัด, multi-monitor แยก, hover highlight
  แบบตอบสนอง หรือการตั้ง timezone จาก shell

