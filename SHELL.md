# Dev OS Shell: taskbar, เมนูแอป และนาฬิกา

`tools/dev_shell.py` (ติดตั้งเป็น `/usr/bin/dev-shell`) คือ desktop shell ตัวแรกของ Dev OS:
taskbar สูง 40 พิกเซลด้านล่างจอตามดีไซน์อ้างอิง (flat พื้นเกือบดำ `#0b0f16`) เรนเดอร์ด้วย
**Cairo** ผ่าน ctypes บน X11 — ฟอนต์ TrueType แบบ anti-alias (ผ่าน fontconfig), มุมโค้ง,
hairline และความโปร่งใสจริงบน visual 32-bit ARGB เมื่อ display รองรับ ต้องมี `libcairo`,
`fontconfig` และฟอนต์ TTF (เช่น DejaVu Sans / DejaVu Sans Mono) ใน image

## Toolkit กลาง dev_gui

`tools/dev_gui.py` (ติดตั้งที่ `/usr/lib/devos/dev_gui.py`) คือ widget toolkit ขนาดเล็กที่
shell และแอป DPK ใช้ร่วมกัน: การเชื่อมต่อ X11+Cairo, `Window` แบบมี title bar (ลากย้ายได้
ปุ่มปิด มุมโค้ง), popup โปร่งใส, `Button` พร้อม hover/press และ callback, `Label`,
การจับภาพหน้าต่างสำหรับทดสอบ และตัวช่วยเขียน PNG — ไม่เพิ่ม dependency นอกเหนือจาก
libX11, libcairo และ fontconfig ที่ shell ต้องใช้อยู่แล้ว

แอปตัวอย่างที่ใช้ toolkit นี้: `examples/desktop-info` (System Info) — หน้าต่าง 380×230
แสดง Version/Kernel/Memory/Uptime พร้อมปุ่ม Close แบบหลัก แพ็กเป็น `.dpk` รูปแบบ 2 ได้
ปกติ และเปิดผ่าน `dev launch desktop-info --allow window` ใน sandbox เดียวกับแอปอื่น
ตรวจผ่าน `python3 scripts/test-gui.py` บน display จริง ภาพหลักฐานอยู่ที่ `out/gui-tests/`

## ดีไซน์

Taskbar (สูง 40px เต็มความกว้างจอ พื้นเรียบสีเกือบดำอมน้ำเงิน แยกจากพื้นที่ทำงานด้วย
เส้น hairline บาง ๆ ด้านบน):

```
+------------+------+----------------------------------+--------+----------+----------------+
| >_ DEVOS   | [D]  |                                  | ))) (S | 21:40:12 |  <- ปุ่ม start  pill ขอบเขียว
+------------+------+----------------------------------+---+----+-----+----+----------------+
   ^ pill โค้งขอบเขียว   ^ ไอคอนแอปชิดซ้ายถัดจาก pill        ^ tray  ^ เส้นคั่น + นาฬิกา 2 บรรทัด
     ตัวอักษร mono หา      (จุด=กำลังรัน, เส้นใต้น้ำเงิน=active)  (wifi เขียว,  (เวลา 13px ขาว / วันที่
     เขียว คลิกเปิดเมนู                                      ลำโพง, กระดิ่ง+ 8.5px เทา ตัวพิมพ์ใหญ่)
                                                           จุดแดง)
```

- ปุ่ม start เป็น pill มุมโค้งเต็มขอบเขียว (`#2eff8f`) พื้นเขียวโปร่งบาง ตัวอักษร
  `>_ DEVOS` ฟอนต์ mono หนาสีเขียว — hover แล้วขอบ/พื้นสว่างขึ้น คลิกเพื่อเปิด/ปิดเมนูแอป
- ไอคอนแอปที่ติดตั้ง (สี่เหลี่ยมมุมโค้ง 28px พร้อม monogram ตัวแรกของชื่อ) เรียงชิดซ้าย
  ถัดจาก pill (เว้น 16px) สูงสุด 9 ตัว: แอปที่มีหน้าต่างเปิดอยู่มีจุดสีขาวใต้ไอคอน ตัวแรก
  ที่เปิดได้เส้นใต้สีน้ำเงิน (`#00aaff`) และ monogram สีขาวสว่าง; คลิกไอคอน = ยกหน้าต่าง
  นั้นขึ้น หรือถ้ายังไม่เปิด จะเด้งไปแถวยินยอมของแอปนั้นในเมนูทันที (การจับคู่หน้าต่าง
  ใช้ชื่อ title ผ่าน `_NET_CLIENT_LIST` แบบ best-effort)
- ฝั่งขวาเป็น tray ประกอบ (wifi สีเขียว, ลำโพง, กระดิ่งพร้อมจุดแดง `#ff4444`) —
  วาดด้วยเส้น Cairo ล้วน **เป็นภาพประกอบยังไม่มีฟังก์ชัน** ตามด้วยเส้นคั่นแนวตั้ง
- นาฬิกาสองบรรทัดชิดขวา: เวลา `HH:MM:SS` ตัวขาวหนา 13px บน วันที่ `SEP 21, 2026`
  ตัวพิมพ์ใหญ่สีเทา 8.5px ล่าง อัปเดตทุกวินาทีตาม timezone เครื่อง
- จองพื้นที่แถบล่างผ่าน EWMH (`_NET_WM_STRUT`/`_STRUT_PARTIAL` 40px, window type `DOCK`,
  sticky, skip taskbar/pager) หน้าต่าง maximize จึงไม่ทับ taskbar

เมนูแอป (popup กว้าง 320px ลอยเหนือปุ่ม MENU ชิดซ้ายจอ):

```
╭─────────────────────────────╮
│ ● DEV OS                    │  header 26px: จุดเขียว + ชื่อหนา + เส้นคั่นโปร่งแสง
│                             │
│ Dev Counter                 │  รายการ 36px/แอป: ชื่อหนา AA
│ Utility · window,storage    │  บรรทัดรองสีจาง (categories · permissions)
│ ╭─────────────────────────╮ │
│ │ Open Dev Counter?        │ │  แถวยินยอม 52px พื้นเขียวโปร่งแสงมุมโค้ง
│ │ window,storage  (ALLOW)  │ │  ชิป ALLOW มุมโค้งพื้นเขียว ตัวอักษรเข้ม
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
จำลอง เปิด shell จับภาพ PNG แล้วตรวจพิกเซลระดับความละเอียด (ความสูง 40px, จำนวนเฉดสีจาก
anti-alias, pill เขียว/monogram กลางจอ/tray + จุดแดง/นาฬิกา 2 บรรทัด, มุมโค้งและชิป ALLOW
ของเมนู) ผลและภาพอยู่ที่ `out/shell-tests/`

## ขอบเขตและข้อจำกัด

- เป็นโปรเซสผู้ใช้ปกติ ไม่ใช่ส่วนของ installer หรือ boot; ISO ที่ส่งมอบยังเป็น CLI
  และยังไม่มี display manager/session ที่เริ่ม shell ให้อัตโนมัติ และ image ปัจจุบัน
  ยังไม่รวม libcairo/fontconfig — ต้องเพิ่มในการ rebuild ครั้งหน้า
- การจับคู่หน้าต่างของไอคอน pinned และการยกหน้าต่างต้องมี WM ที่รองรับ EWMH; บน X
  server เปล่าจะเหลือ pill + ไอคอน (ไม่มีจุด/เส้นใต้) + tray + นาฬิกา ซึ่งยังใช้งานได้
- การยินยอมของ shell เทียบเท่า `dev launch` แบบพิมพ์ yes ใน terminal: เป็น explicit
  consent ต่อการเปิดครั้งนั้น ไม่ใช่การขยายสิทธิ์
- ข้อจำกัดของสภาพแวดล้อมทดสอบ (XWayland บน WSLg): จับภาพหน้าต่าง ARGB หรือ
  override-redirect ไม่ได้ โหมดจับภาพหลักฐานจึงใช้ visual ปกติและวาดพื้น "desktop"
  จำลองให้เห็นมุมโค้ง ส่วนตอนใช้งานจริงได้โปร่งใสเต็มรูปแบบ; การจับภาพยังต้องวาดซ้ำ
  หลังรอ compositor หนึ่งรอบ
- ฟอนต์ตามที่ fontconfig ให้ (ค่าเริ่มต้น DejaVu Sans และ DejaVu Sans Mono สำหรับ
  pill) — การแสดงภาษาอื่นนอกจาก Latin/Cyrillic/Greek ต้องมีฟอนต์ครอบคลุมติดตั้งเพิ่ม
- tray ฝั่งขวา (wifi/ลำโพง/กระดิ่ง+จุดแดง) เป็น glyph ประกอบตามดีไซน์ ยังไม่มีสถานะจริง
  หรือ notification center; ยังไม่มี systray มาตรฐาน, คีย์ลัด, multi-monitor แยก หรือ
  การตั้ง timezone จาก shell

