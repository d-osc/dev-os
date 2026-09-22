# Dev OS Settings: ปรับ desktop ด้วย `settings.json` แบบ VS Code

การตั้งค่าของ desktop เก็บในไฟล์ `settings.json` รูปแบบ flat key
(`section.name`) เหมือน VS Code — แก้ไฟล์เดียว เปิด shell ใหม่ ได้ผลทันที

## ไฟล์อยู่ที่ไหน

โหลด 3 ชั้น ชั้นหลังชนะชั้นหน้า (คีย์ที่ไม่ระบุสืบค่าจากชั้นก่อนหน้า):

1. `/etc/devos/settings.json` — ค่าเริ่มต้นของระบบ (ติดตั้งมาพร้อม image)
2. `~/.config/devos/settings.json` — ของผู้ใช้ (สร้างเองได้ เขียนเฉพาะที่ต้องการแก้)
3. ไฟล์ override — ธง `--settings <path>` หรือตัวแปร `DEVOS_SETTINGS`

## คีย์ทั้งหมด

```json
{
  "theme": "terminal-amber",
  "clock.hour12": false,
  "clock.showSeconds": true,
  "clock.dateFormat": "%b %d, %Y",
  "font.family": "DejaVu Sans",
  "desktop.background": "/usr/share/backgrounds/dev.jpg"
}
```

| คีย์ | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `theme` | `dev-dark` | ธีมที่ใช้: ชื่อธีม (หาจาก `themes/` ข้างไฟล์ settings, `./themes/` และ `/usr/share/devos/themes/`) หรือพาธไฟล์ `.json` ตรง ๆ หรือ `default` (ลุค built-in) |
| `clock.hour12` | `false` | `true` = นาฬิกา 12 ชั่วโมงพร้อม AM/PM |
| `clock.showSeconds` | `true` | `false` = แสดงแค่ ชั่วโมง:นาที |
| `clock.dateFormat` | `%b %d, %Y` | รูปแบบบรรทัดวันที่ (strftime, แสดงตัวพิมพ์ใหญ่) |
| `font.family` | `DejaVu Sans` | ฟอนต์ของ shell และแอป (ต้องเป็นฟอนต์ที่ fontconfig เห็น) |
| `desktop.background` | `none` | พื้นหลัง desktop + หน้า login: `none` (สีธีม), `#RRGGBB`, หรือพาธไฟล์ `.png` `.jpg/.jpeg` `.svg` `.html` |

ลำดับการเลือกธีมเมื่อรัน: ธง `--theme` > ตัวแปร `DEVOS_THEME` >
คีย์ `theme` ใน settings > built-in

## พื้นหลัง desktop (desktop.background)

เป็น**ภาพพื้นหลังของหน้าจอ desktop เท่านั้น** — shell วาดลงหน้าต่าง desktop
ของตัวเอง (แผนหลังสุดใต้ทุกหน้าต่าง) ไม่เกี่ยวกับหน้า login ซึ่งใช้สีธีม
และปรับแต่งผ่าน greeter extension (`paint_background`) แทน วาดแบบ **cover**
(เต็มจอ คงสัดส่วน ตัดขอบเกิน):

- **`.png`** — ถอดรหัสด้วย cairo โดยตรง
- **`.jpg` / `.jpeg`** — ถอดรหัสผ่าน TurboJPEG (libturbojpeg มาพร้อม image)
- **`.svg`** — parser ชุดย่อยของเราเอง: `rect` `circle` `ellipse` `line`
  `polyline` `polygon` `path` (แกน M/L/H/V + ข้ามช่วงโค้งอย่างปลอดภัย), สี
  hex/ชื่อพื้นฐาน, `fill`/`stroke`/`stroke-width`, `viewBox` และ `<g>`
- **`.html`** — ชุดย่อยเชิงประกาศ: `background-color` /
  `background:linear-gradient(c1,c2)` บน body/div, ข้อความ
  (`<h1..h3>/<p>` + style `left/top/font-size/font-weight/color`) และ
  `<img src="...png">` แบบพาธสัมพัทธ์

ไฟล์ทุกชนิดจำกัด 256 KiB (รูป ≤16 MiB) ตรวจอย่างเคร่งครัด — **พังเมื่อไหร่
fallback เป็นสีธีมทันที** พื้นหลังไม่มีสิทธิทำให้ desktop ล้ม

## การสืบทอดไปยังแอป

แอปที่ shell เปิดให้ (กด ALLOW) จะได้ตัวแปร `DEVOS_THEME` (พาธไฟล์ธีม)
และ `DEVOS_FONT` อัตโนมัติ — ฟอนต์และธีมจึงตรงกันทั้ง desktop โดยผู้ใช้ไม่ต้อง
ตั้งอะไรเพิ่มในแอป

## ความปลอดภัย

เหมือนไฟล์ธีม: จำกัด 16 KiB, ตรวจ schema เคร่งครัด (คีย์/ชนิดค่าที่ไม่รู้จัก
ปฏิเสธทันที) โค้ดอยู่ที่ `tools/dev_settings.py` มี unit test ครบ และ
`scripts/test-settings.py` พิสูจน์บน display จริงว่า settings เลือกธีมและ
จูนนาฬิกาได้จริง ดูธีม (สี/มุม/ไอคอน) ต่อที่ [THEMES.md](THEMES.md)
