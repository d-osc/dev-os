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

## API (รุ่น 1)

โค้ด extension เขียน `activate(api)` รับออบเจกต์ API (และ `deactivate()`
ซึ่ง shell เรียกตอนออก):

```python
def activate(api):
    api.register_command('devos.battery.status', 'Battery status',
                         lambda: api.notify('Battery', summary()),
                         'Power supply summary')
    api.register_tray('battery', BOLT, command_id='devos.battery.status',
                      color='accent')
```

| เมธอด | ความหมาย |
|---|---|
| `register_command(id, title, handler, detail='')` | เพิ่มคำสั่งในเมนูแอป คลิกแล้วเรียก `handler()` |
| `register_tray(id, icon, command_id=None, color='accent')` | ไอคอนในถาด taskbar (คลิกได้) — `icon` เป็นชื่อไอคอนของธีม หรือ dict ไอคอนตามรูปแบบ [THEMES.md](THEMES.md); `color` เป็นชื่อ token สี |
| `notify(title, body='')` | แจ้งเตือนบน desktop (ผ่านระบบ notification ของ OS) |
| `set_theme(path)` | สลับธีมทั้ง desktop แบบสด ๆ |
| `api.settings` / `api.theme` / `api.screen` | ข้อมูลอ่านอย่างเดียวของสภาพแวดล้อม |

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
การรันคำสั่ง, และกรณี extension พัง (261 unit tests ผ่านทั้ง Windows/Linux)
`scripts/test-extensions.py` พิสูจน์บน display จริง: extension ถูกโหลด
`activate()` รันจริง (เขียนไฟล์หลักฐาน) คำสั่งลงเมนู และไอคอนถาดวาดจริงบนจอ
