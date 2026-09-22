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

## Python กับ JavaScript (Node.js)

manifest เลือกภาษาด้วย `"main"`: `"extension.py"` หรือ `"extension.js"` —
extension ภาษา JS รันบน **Node.js runtime** ผ่าน runner (`ext-runner.js`) คุยกับ
shell ด้วย JSON บรรทัดต่อบรรทัด คำสั่ง/ไอคอนถาด/notif/ธีมใช้เหมือน Python เป๊ะ
ต่างกันแค่การวาด: callback ข้าม process ไม่ได้ JS จึงส่ง **draw ops** (ลิสต์
`{op:'text'|'rect'|'line'|'circle'|'icon', ...}`) แล้ว shell เป็นคน replay ผ่าน
Painter — จะอัปเดตภาพเมื่อไหร่ก็ `api.updateWidget(id, ops)` /
`api.updatePanel(id, ops)` ตัวอย่าง: `examples/extensions/hello-js`

```js
module.exports.activate = function activate(api) {
  api.registerWidget('clock', 'left', 76, [
    { op: 'rect', x: 0, y: 3, w: 72, h: 34, color: 'chrome', r: 4 },
    { op: 'text', value: '12:34', x: 8, y: 25, color: 'accent', size: 13, bold: true },
  ]);
  api.registerCommand('devos.hello-js.ping', 'Ping from JavaScript',
                      () => api.notify('Hello from JS', 'Node ' + process.version));
};
```

API ฝั่ง JS: `registerCommand`, `registerTray`, `registerWidget(id, zone, width,
ops, onClick?)`, `updateWidget`, `createPanel(id, w, h, ops, onEvent?, x?)` (คืน
handle `show/hide/toggle`), `updatePanel`, `overrideClock(width, ops)` /
`restoreClock()`, `hide`/`show`, `notify`, `setTheme`, และ `settings/theme/screen`
— **TypeScript ใช้ได้** เพราะเป้าหมายคือ CommonJS ธรรมดา คอมไพล์ด้วย `tsc` แล้วส่ง
`extension.js` ที่ได้มาได้เลย

Node ต้องมีใน image: สร้างด้วย `DEVOS_WITH_NODE=1 sh scripts/configure.sh …`
(สำหรับ dev บนเครื่องปกติ แค่มี `node` ใน PATH ก็พอ)

## Rust

`DEVOS_WITH_RUST=1` ตอน configure เพิ่ม rustc + cargo ลงใน image — เป็นเครื่องมือ
สำหรับคอมไพล์โปรแกรม/แอป native บนเครื่อง Dev OS เอง extension แบบ Rust
(binary คุย JSON ตามโปรโตคอลเดียวกับ ext-runner.js) เป็นแนวทางอนาคตเมื่อมี
ตัวอย่างใช้งานจริง

## ความปลอดภัย (โมเดลความเชื่อใจ)

Extension รัน **ในโปรเซสของ shell** เหมือน VS Code extension รันใน extension
host — การติดตั้ง extension คือความยินยอมของผู้ใช้เอง ติดตั้งเฉพาะจากแหล่งที่
เชื่อถือได้เท่านั้น (ต่างจากแอป DPK ที่ถูกจำกัดสิทธิ์และถามยินยอมทุกครั้ง)
ของที่โหลดจากไฟล์ถูกจำกัดขนาด + validate; ไอคอนที่ extension ลงทะเบียนผ่าน
`dev_theme.validate_icon` เหมือนไฟล์ธีม

## การตรวจสอบ

`tests/test_extensions.py` ครอบ manifest validation, วงจร activate/deactivate,
การรันคำสั่ง, Painter, widget/panel/override validation, draw-ops และ
โปรโตคอล JS ทั้งฝั่ง dispatch (267 unit tests ผ่านทั้ง Windows/Linux) สามสคริปต์
พิสูจน์บน display จริง: `scripts/test-extensions.py` (โหลด + คำสั่ง + ถาด),
`scripts/test-gui-extensions.py` (widget + clock override + hide + แผงลอย) และ
`scripts/test-js-extensions.py` (extension ภาษา JavaScript รันบน Node จริง)
