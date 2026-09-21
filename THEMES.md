# Dev OS Themes: เปลี่ยนสีและไอคอนทั้ง desktop ด้วยไฟล์ JSON ไฟล์เดียว

ธีมของ Dev OS ทำงานแบบเดียวกับ color theme ของ VS Code: ไฟล์ JSON หนึ่งไฟล์
ระบุ **token สี** (แก้บางตัวก็ได้ ที่เหลือได้ค่า default) และ/หรือ **ไอคอน vector**
(ถ้าไม่แตะก็ใช้ไอคอนของธีมมาตรฐาน) แล้ว taskbar, เมนูแอป, หน้าต่างแอปและปุ่ม
ทั้งหมดเปลี่ยนตามพร้อมกัน

## ใช้งาน

```sh
dev-shell --theme themes/terminal-amber.json    # ระบุไฟล์ตรง ๆ
DEVOS_THEME=themes/terminal-amber.json dev-shell   # หรือผ่านตัวแปรสภาพแวดล้อม
```

วิธีถาวรกว่านั้นคือตั้ง `"theme": "terminal-amber"` ใน `settings.json`
(ดู [SETTINGS.md](SETTINGS.md)) — ธีมที่ใช้กับทั้ง desktop โหลดอัตโนมัติทุกครั้งที่เปิด

ลำดับการหาธีม: ธง `--theme` > ตัวแปร `DEVOS_THEME` > คีย์ `theme` ใน
settings.json > built-in

แอปที่ shell เปิดผ่านเมนู (กด ALLOW) จะได้ตัวแปร `DEVOS_THEME` ชี้ไปที่ไฟล์ธีม
เดียวกันโดยอัตโนมัติ — ธีมจึงต่อเนื่องจาก taskbar ไปถึงหน้าต่างแอป; แอปก็รับธีมเอง
ได้จาก `DEVOS_THEME` หรือธง `--theme` เช่นเดียวกัน ไฟล์ธีมที่มาพร้อมระบบ:
`themes/dev-dark.json` (ลุคมาตรฐาน) และ `themes/terminal-amber.json` (ตัวอย่าง
สลับ accent เป็นส้ม + ไอคอน wifi แบบขีด)

## โครงสร้างไฟล์

```json
{
  "name": "Terminal Amber",
  "colors": {
    "bg": "#12100C",        "chrome": "#1C1914",  "line": "#3A3226",
    "text": "#F5EFE3",      "dim": "#8A7D64",     "accent": "#FFB000",
    "accentText": "#201600", "blue": "#59C2FF",    "red": "#FF6363"
  },
  "corners": {
    "window": 4, "menu": 6, "chip": 3
  },
  "icons": { "wifi": { "...": "ดูด้านล่าง" } }
}
```

ทุก section ใส่หรือไม่ใส่ก็ได้ ค่าที่ไม่ระบุใช้ของธีมมาตรฐานต่อ

### Token สี

| Token | ควบคุม | ค่าเริ่มต้น |
|---|---|---|
| `bg` | พื้น taskbar / พื้นหน้าต่างแอป | `#0b0f16` |
| `chrome` | ปุ่ม start, title bar, แผงเมนู | `#111827` |
| `line` | เส้นคั่น/hairline/ขอบหน้าต่าง | `#222D3D` |
| `text` | ตัวอักษรหลัก (DEVOS, ค่าในหน้าต่าง, นาฬิกา) | `#F1F5F9` |
| `dim` | ตัวอักษรรอง, ไอคอน tray, ปุ่มควบคุมเวลาพัก | `#6F8098` |
| `accent` | ขอบ+`>_` ปุ่ม start, ชิป ALLOW, ปุ่มหลัก, wifi | `#00FF9C` |
| `accentText` | ตัวอักษรบนพื้น accent | `#0b0f16` |
| `blue` | เส้นใต้แอป active บน taskbar | `#00AAFF` |
| `red` | จุดแจ้งเตือน, ปุ่มปิดเวลา hover | `#FF4444` |

รูปแบบสี: `#RGB` หรือ `#RRGGBB` เท่านั้น — token นอกตารางถูกปฏิเสธตั้งแต่โหลด

### มุม (corners)

ปรับรัศมีมุมเป็นพิกเซล ย่าน 0–24 — **`0` คือมุมเหลี่ยม (square) เต็ม** ค่าจะถูก
บีบไม่ให้เกินครึ่งด้านสั้นของกล่องโดยอัตโนมัติ:

| Token | ควบคุม | ค่าเริ่มต้น |
|---|---|---|
| `window` | มุมหน้าต่างแอป + title plate | `10` |
| `button` | ปุ่มในหน้าต่าง (ปุ่มหลัก/รอง) | `8` |
| `menu` | แผงเมนูแอป (รวมเงา) | `12` |
| `row` | แถวรายการในเมนู + แถวยินยอม | `8` |
| `chip` | ชิป ALLOW | `11` |
| `start` | ปุ่ม start | `6` |
| `icon` | ไอคอนแอปบน taskbar + พื้น hover ปุ่มควบคุม | `6` |

ตัวอย่างธีมมุมเหลี่ยมทั้งหมด:

```json
{ "name": "Brutalist", "corners": { "window": 0, "button": 0, "menu": 0,
                                    "row": 0, "chip": 0, "start": 0, "icon": 0 } }
```

### ไอคอน

ไอคอนคือ vector จิ๊กซอว์ในกรอบ `view: [กว้าง, สูง]` ของตัวเอง ประกอบจาก element
1–32 ตัว วาดตามลำดับ แต่ละตัวได้ `color` (ชื่อ token), `fill` (boolean) และ `width`
(ความหนาเส้น) โดยค่าเริ่มต้นสืบจากที่เรียกใช้:

```json
"wifi": {
  "view": [16, 16],
  "elements": [
    {"kind": "line",    "x1": 3, "y1": 6, "x2": 8, "y2": 11, "width": 1.8},
    {"kind": "line",    "x1": 13, "y1": 6, "x2": 8, "y2": 11, "width": 1.8},
    {"kind": "circle",  "cx": 8, "cy": 12.5, "r": 1.1, "fill": true}
  ]
}
```

ชนิด element: `line` (x1,y1,x2,y2) · `poly` (points 2–16 จุด) ·
`rect` (x,y,w,h + `r` มุมโค้ง) · `circle` (cx,cy,r) ·
`arc` (cx,cy,r,from,to องศา + `lines` ต่อปลาย + `closed`)

ชื่อไอคอนที่แทนที่ได้: `start` (`>_` ในปุ่ม start), `mark` (`>_` หน้าชื่อหน้าต่าง),
`wifi`, `volume`, `bell` (รวมจุดแดงที่ผูก `color: red`), `minimize`, `maximize`,
`restore`, `close`

## ความปลอดภัย

ไฟล์ธีมเป็น untrusted input: จำกัดขนาด 64 KiB, ตรวจโครงสร้างอย่างเคร่งครัด
(token/ชนิด element/ชื่อไอคอนที่ไม่รู้จักถูกปฏิเสธทันที) และสิ่งเดียวที่ออกมาจาก
ไฟล์ได้คือสีกับเรขาคณิตของไอคอนเท่านั้น — โค้ดทำงานใน `tools/dev_theme.py`
(validate/resolve/load) มี unit test ครบทั้งกรณีถูกและผิด และ `scripts/test-theme.py`
พิสูจน์บน display จริงว่าสลับธีมแล้วพิกเซลเปลี่ยนจริงทั้ง bar และหน้าต่างแอป
