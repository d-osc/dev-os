# Dev OS Extensions: ขยาย desktop แบบ VS Code

Extension คือโฟลเดอร์ที่มี `manifest.json` + `extension.py` วางไว้ที่
`~/.config/devos/extensions/` (ผู้ใช้) หรือ `/usr/share/devos/extensions/`
(ระบบ) — shell โหลดเข้ามาตอนเปิด สิ่งที่ extension ลงทะเบียนจะปรากฏในเมนูแอป
และถาด (tray) ของ taskbar ทันที ตัวอย่างจริงอยู่ที่ `examples/extensions/`
(`devos.battery`, `devos.theme-switch`)

## โครงสร้าง

```
extensions/devos.battery/
├── manifest.json
└── extension.py
```

```json
{
  "id": "devos.battery",
  "name": "Battery",
  "version": "1.0.0",
  "description": "Battery tray icon with a status command",
  "engine": 1,
  "main": "extension.py"
}
```

- `id` รูปแบบ `devos.<name>` (ตัวเล็ก ตัวเลข ขีด) · `version` แบบ MAJOR.MINOR.PATCH
- `engine: 1` คือ API รุ่นปัจจุบัน · `main` ต้องเป็น `extension.py`
- manifest จำกัด 4 KiB โค้ดจำกัด 64 KiB ตรวจอย่างเคร่งครัด — extension ที่พัง
  จะถูกรายงานและข้าม ไม่ทำให้ shell ตาย

## API (รุ่น 2 — custom GUI ได้ทุกระดับ)

โค้ด extension เขียน `activate(api)` รับออบเจกต์ API (และ `deactivate()`
ซึ่ง shell เรียกตอนออก) draw callback ทุกตัวรับ **Painter**: พิกัด (0,0)
คือมุมซ้ายบนของพื้นที่ตัวเอง มี `text/rect/line/circle/icon`, `text_width`,
`width/height`, `colors` (พาเลตต์ธีมปัจจุบัน) และ `raw` (cairo, cr) สำหรับ
เรียก Cairo ตรง ๆ ไม่จำกัด — callback ที่พังถูกจับไว้ วาดกรอบแดงแทน ไม่ทำให้
shell ตาย

```python
def activate(api):
    panel = api.create_panel('devos.dashboard.panel', 260, 110, draw_panel, x=8)
    api.register_widget('right', 100, draw_widget, on_click=panel.toggle)
    api.override_clock(120, lambda p: p.text('OVERRIDE', 4, 25, 'red', 13, True))
    api.hide('tray')
```

| เมธอด | ความหมาย |
|---|---|
| `register_widget(zone, width, draw, on_click=None)` | แถบของตัวเองบน taskbar — `zone` เป็น `'left'` (ถัดไอคอนแอป) หรือ `'right'` (ก่อนถาด) กว้าง 8–320px คลิกได้ |
| `create_panel(id, width, height, draw, on_event=None, x=8)` | แผงลอยเหนือ taskbar ที่ extension วาดเองทั้งหมด (webview ของเรา) — คืน handle ที่มี `show()/hide()/toggle()`; `on_event('click'/'hover', x, y)` รับเหตุการณ์เมาส์; คลิกนอกแผงปิดอัตโนมัติ |
| `override_clock(width, draw)` | ทับการวาดนาฬิกาในตัวทั้งหมด (กว้าง 40–400px) |
| `hide(section)` / `show(section)` | ซ่อน/คืนส่วน built-in: `'tray'` (ไอคอน wifi/ลำโพง/กระดิ่ง), `'clock'`, `'pinned'` — ผสมกับ widget เพื่อประกอบ taskbar แบบของตัวเองได้ |
| `register_command(id, title, handler, detail='')` | คำสั่งในเมนูแอป |
| `register_tray(id, icon, command_id=None, color='accent')` | ไอคอนถาดคลิกได้ (ชื่อไอคอนธีม หรือ dict ตาม [THEMES.md](THEMES.md)) |
| `notify(title, body='')` | แจ้งเตือนบน desktop |
| `set_theme(path)` | สลับธีมทั้ง desktop สด ๆ |
| `api.settings` / `api.theme` / `api.screen` | ข้อมูลอ่านอย่างเดียว |

ตัวอย่างครบทุกระดับอยู่ที่ `examples/extensions/dashboard` (widget RAM บน
taskbar + แผงลอยรายละเอียด กด widget เพื่อเปิด/ปิด)

## API รุ่น 1 (ยังรองรับ)

`register_command`, `register_tray`, `notify`, `set_theme`, `settings/theme/screen`
— ดูตัวอย่าง `examples/extensions/battery` และ `examples/extensions/theme-switch`

## เรื่อง JS/TS (สำคัญ)

Desktop ปัจจุบันไม่มี JavaScript engine ใน image (ไม่มี Node/QuickJS) API จึง
ให้เขียนด้วย **Python** ซึ่ง runtime มีอยู่แล้ว — แต่ manifest (`engine`) และ
API surface ออกแบบให้ language-agnostic: เมื่อ Buildroot เพิ่ม engine
(เช่น QuickJS) ใน image รุ่นหน้า host สำหรับ JS จะโหลด manifest เดียวกันนี้ได้
ทันทีโดยไม่ต้องเปลี่ยนรูปแบบ

## ความปลอดภัย (โมเดลความเชื่อใจ)

Extension รัน **ในโปรเซสของ shell** เหมือน VS Code extension รันใน extension
host — การติดตั้ง extension คือความยินยอมของผู้ใช้เอง ติดตั้งเฉพาะจากแหล่งที่
เชื่อถือได้เท่านั้น (ต่างจากแอป DPK ที่ถูกจำกัดสิทธิ์และถามยินยอมทุกครั้ง)
ของที่โหลดจากไฟล์ถูกจำกัดขนาด + validate; ไอคอนที่ extension ลงทะเบียนผ่าน
`dev_theme.validate_icon` เหมือนไฟล์ธีม

## การตรวจสอบ

`tests/test_extensions.py` ครอบ manifest validation, วงจร activate/deactivate,
การรันคำสั่ง, Painter, widget/panel/override validation และกรณี extension พัง
(263 unit tests ผ่านทั้ง Windows/Linux) สองสคริปต์พิสูจน์บน display จริง:
`scripts/test-extensions.py` (โหลด + คำสั่ง + ไอคอนถาด) และ
`scripts/test-gui-extensions.py` (custom widget + clock override + hide + แผงลอย
ตรวจด้วยพิกเซล)
