# DPK 2: Permissions, Background และ Desktop UI

เพิ่ม runtime ในซอร์ส Dev OS แล้ว ทดสอบจริงบน Linux/WSLg วันที่ 18 กันยายน 2026 ด้วย bubblewrap และหน้าต่าง X11 แบบ native **ISO ที่ส่งก่อนหน้านี้ยังเป็น CLI รุ่นเดิมและยังไม่ได้ rebuild เพื่อรวม runtime นี้** ต้องมี display server/session จึงจะเปิดหน้าต่างได้ การเพิ่ม libX11 เพียงอย่างเดียวไม่ได้สร้าง Desktop session

## Manifest ของแอป

```json
{
  "manifest_version": 2,
  "name": "desktop-counter",
  "display_name": "Dev Counter",
  "version": "0.1.0",
  "arch": "all",
  "permissions": ["background", "window", "storage"],
  "background": {
    "runtime": "python",
    "entry_point": "opt/apps/desktop-counter/background.py"
  },
  "window": {
    "type": "desktop",
    "runtime": "python",
    "entry_point": "opt/apps/desktop-counter/window.py"
  },
  "executables": [
    "opt/apps/desktop-counter/background.py",
    "opt/apps/desktop-counter/window.py"
  ]
}
```

- Builder สร้าง archive `format: 2` เพื่อให้ reader เก่าปฏิเสธ ไม่มองข้ามเงื่อนไข runtime
- payload ทั้งหมดต้องอยู่ใต้ `opt/apps/<name>/` ส่วนชื่อไฟล์ metadata ยังคง `manifest.json`
- entry point ต้องเป็นไฟล์ในแพ็กเกจ หากใช้ `native` ต้องมีชื่อใน `executables`; runtime แบบ interpreter อ่าน script mode 0644 ได้ ใช้ `args` เป็น array ของ strings ไม่มี shell interpolation จาก launcher
- background และ UI เป็นคนละโปรเซส ไม่ใช่ JavaScript service worker ของ browser
- `window.type: desktop` รุ่นแรกใช้ local X11; แอปตัวอย่างใช้ Python + libX11 ผ่าน ctypes ไม่ใช้หน้าเว็บ
- ต้องเตรียม runtime/library ที่โปรแกรมใช้เอง รุ่นนี้ยังไม่มี dependency resolver

## Launcher สำหรับ Application Menu

เพิ่มใน manifest format 2 ที่มี `window`:

```json
"launcher": {
  "name": "Dev Counter",
  "comment": "Open the counter window",
  "icon": "opt/apps/desktop-counter/icon.svg",
  "categories": ["Utility"]
}
```

ทุก field เป็น optional: name ใช้ display_name/name ของแพ็กเกจเป็นค่าเริ่มต้น, categories ใช้ `["Utility"]`, ส่วน icon/comment ไม่แสดงเมื่อไม่กำหนด `icon` ต้องเป็นไฟล์ที่บรรจุใน payload ไม่ใช่ URL หรือไฟล์ภายนอก

`launcher` เป็น metadata ของไอคอน/เมนูเท่านั้น ทั้งการกดไอคอน, `dev launch` และ `dev open` ใช้ `window.runtime`, `window.entry_point` และ `window.args` ชุดเดียวกัน สำหรับ native ต้องระบุไฟล์ใน `executables` เช่นเดิม

นำ `runtime`, `entry_point` และ `args` ที่เคยอยู่ใน launcher ย้ายไป window แล้วลบออกจาก launcher ตัวตรวจ manifest จะปฏิเสธ fields เหล่านี้พร้อมข้อความให้ย้ายไป window เพื่อไม่ให้เกิดค่าที่ซ้ำกัน

ตัวติดตั้งสร้าง `/usr/share/applications/devos-<name>.desktop` พร้อมติดตาม hash ในฐานข้อมูล ถอนออกพร้อมแพ็กเกจ และไม่เขียนทับ desktop entry ที่มีอยู่ ผู้ใช้เลือก pin หรือสร้าง shortcut บน Desktop ผ่าน desktop environment ของตนได้; ตัวติดตั้งไม่เขียนเข้า Desktop ของทุกบัญชี

กดไอคอนแล้วเรียก `dev launch <name>` รุ่นนี้กำหนด `Terminal=true` เพื่อแสดงรายชื่อ permissions และให้พิมพ์ `yes` ก่อนเปิด `window` ผ่าน sandbox เดิม ไม่เริ่ม background อัตโนมัติ ไม่บันทึก grants ถาวร และปฏิเสธ implicit grants หากไม่มี interactive terminal ผู้ใช้ CLI ที่ต้องการระบุ grants เองใช้ `dev launch <name> --allow window,storage` โดยรายการต้องตรงกับ permissions ของแอป

รองรับเฉพาะ fields ข้างต้น ไม่รับ `exec` หรือ shell command ใน launcher; args ยังคงกำหนดที่ `window` ระบบ Desktop ต้องมี terminal emulator และ runtime/display ที่จำเป็นก่อนใช้ไอคอนนี้ ISO ปัจจุบันยังเป็น CLI และไม่ได้รวมฟีเจอร์ launcher ใหม่

ตัวอย่าง: `examples/desktop-counter/manifest.json` พร้อม SVG icon อ้างอิง [Desktop Entry keys](https://specifications.freedesktop.org/desktop-entry/latest/recognized-keys.html) และ [Exec syntax](https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html)

## เลือก runtime แยกกัน (ตัวอย่าง)

```json
{
  "background": {
    "runtime": "node",
    "entry_point": "opt/apps/desktop-counter/background.cjs",
    "args": []
  },
  "window": {
    "type": "desktop",
    "runtime": "bash",
    "entry_point": "opt/apps/desktop-counter/window.sh"
  }
}
```

| runtime | วิธีเรียก |
| --- | --- |
| `native` | รัน entry point โดยตรง ใช้กับ binary หรือ script ที่มี shebang; เป็นค่าเริ่มต้นเมื่อไม่ระบุ |
| `node` | Node.js เรียกไฟล์ JavaScript เช่น `.js`, `.cjs`, `.mjs` |
| `bash` | GNU Bash เรียกไฟล์ shell script โดยไม่อ่าน profile/rc |
| `sh` | `/bin/sh` เรียก POSIX shell script |
| `python` | Python 3 เรียกไฟล์ script โดยไม่อ่าน Python environment settings และ user site packages |

ทั้ง `window` และ `background` เลือกได้ทุกค่าด้านบนอย่างอิสระ ไม่รับ `runtime: "bash -c"` หรือ path ที่แพ็กเกจกำหนดเอง `args` อยู่หลังชื่อ script จึงเป็น argument ของแอป ไม่ใช่ interpreter flags การใช้ Bash ยังรันคำสั่งภายใน script ตามปกติ

Node และ Bash ไม่ได้สร้างหน้าต่างให้อัตโนมัติ entry point ของ `window` ต้องเรียก GUI library หรือโปรแกรมที่เปิดหน้าต่างจริง ตัวอย่าง `window.sh` ใช้ Bash เรียก Python/libX11 ที่มีในระบบ และ Node ทำหน้าที่ background นับตัวเลข

ตัวอย่างพร้อมใช้: `examples/desktop-counter/manifest.node-bash.json` ให้คัดลอกเป็น `manifest.json` ในสำเนา source ก่อน `dev build` ส่วนตัวอย่างหลักใช้ Python ทั้งสองส่วน แพ็กเกจปกติที่สร้างแล้วอยู่ที่ `out/desktop-counter-node-bash-0.1.0-all.dpk` ส่วน `out/runtime-tests-node-bash/desktop-counter.dpk` เป็นแพ็กเกจทดสอบที่ใส่ `--test` ให้หน้าต่างปิดเองหลัง 4 วินาที

Launcher ตรวจ executable ของ runtime ก่อนเริ่ม ไม่มีการดาวน์โหลด interpreter/npm packages อัตโนมัติ ถ้าเครื่องพัฒนาเก็บ runtime นอก path มาตรฐาน กำหนด `DEVOS_RUNTIME_NODE`, `DEVOS_RUNTIME_BASH`, `DEVOS_RUNTIME_SH` หรือ `DEVOS_RUNTIME_PYTHON` เป็น absolute path ได้ ค่านี้เป็นการตั้งค่าของผู้เรียก ไม่รับมาจาก manifest; binary ที่เลือกถูก mount แบบ read-only ใน sandbox แต่ shared libraries ยังต้องมีใน system runtime

สำหรับ build OS: config เพิ่ม Bash แล้ว ส่วน Node เป็นตัวเลือกเพื่อคง base CLI ให้เล็ก ใช้ `DEVOS_WITH_NODE=1` ตอนเรียก `scripts/configure.sh` เพื่อเปิด C++ toolchain และ Node.js ต้องใช้ build tree ใหม่เมื่อเปลี่ยน toolchain ตามแนวทาง Buildroot ยังไม่ได้ rebuild/export ISO ที่มี runtime เหล่านี้

## สิทธิ์ที่บังคับใช้

### Linux binary (ELF)

ใช้ `runtime: "native"` ได้ทั้ง `background` และ `window` สำหรับ binary Linux x86_64 โดยไม่ต้องมี Node/Python/Bash เป็น interpreter ของแอป ชื่อไฟล์จะมี `.bin` หรือไม่มีนามสกุลก็ได้ ต้องเป็น ELF จริง ไม่ใช่เปลี่ยนนามสกุล `.exe` ของ Windows

```json
{
  "arch": "x86_64",
  "background": {
    "runtime": "native",
    "entry_point": "opt/apps/native-counter/bin/counterd"
  },
  "window": {
    "type": "desktop",
    "runtime": "native",
    "entry_point": "opt/apps/native-counter/bin/counter-window.bin"
  },
  "executables": [
    "opt/apps/native-counter/bin/counterd",
    "opt/apps/native-counter/bin/counter-window.bin"
  ]
}
```

ตัวอย่างด้านบนเป็นส่วนหนึ่งของ manifest; ฉบับเต็มอยู่ที่ `examples/native-counter/manifest.json` ให้ใช้ `arch: x86_64` และระบุ binary ใน `executables` เพื่อให้ builder ตั้ง mode 0755

ก่อนรัน launcher ตรวจ ELF 64-bit little-endian, x86_64, arch ใน manifest, ขอบเขต program headers และ dynamic loader (`PT_INTERP`) ที่ต้องมีใน system runtime โดยอ่านไฟล์ ไม่เรียก `ldd` หรือรัน binary นอก sandbox เป็นการตรวจเบื้องต้น ไม่ใช่ตัวตรวจ ELF ทุกส่วน kernel และ loader ยังเป็นผู้ตัดสินขั้นสุดท้าย

รองรับ static ELF และ dynamic ELF ที่เข้ากับ libc/ABI/library ของระบบ ไม่ได้หมายความว่า binary จาก Linux ทุก distro จะใช้ได้ โปรแกรม ARM, Windows PE, kernel modules, AppImage และตัวติดตั้ง `.deb`/`.rpm` ไม่อยู่ในขอบเขตรุ่นนี้ หากต้องใช้ library ของแอป ให้บรรจุ regular `.so` ใต้ `opt/apps/<name>/lib/` และ compile ด้วย RUNPATH เช่น `$ORIGIN/../lib` ([GNU linker reference](https://sourceware.org/binutils/docs/ld.pdf)) ส่วน libc, loader, libX11 และ library อื่นที่ไม่บรรจุต้องมีใน OS ไม่มี dependency resolver หรือการดาวน์โหลดอัตโนมัติ

ตัวอย่างนี้มี background ที่ compile แบบ static และ window ที่ link กับ libX11 ของระบบและ `libcounter-label.so` ในแพ็กเกจ ต้องมี C compiler, static libc development files, X11 development headers และ libX11 สำหรับ build:

```sh
python3 scripts/build-native-example.py
python3 tools/dev.py info out/native-counter-0.1.0-x86_64.dpk
```

ใช้ `CC` เลือก compiler executable และ `DEVOS_X11_INCLUDE` เลือก directory ของ X11 headers ได้ เมื่อทำแพ็กเกจสำหรับ Dev OS จริงควร compile ด้วย toolchain/sysroot ที่ตรงกับ target แทนการสมมติว่า host ABI ตรงกัน `dev build` เองยังทำหน้าที่ pack เท่านั้น

แพ็กเกจพร้อมทดลอง: `out/native-counter-0.1.0-x86_64.dpk` ทดสอบ `dev start`, `dev open`, `dev stop`, การปิดหน้าต่างโดย background ยังทำงาน และข้อมูลหลัง restart ผ่านบน Linux/WSLg ด้วย `python3 scripts/test-app-runtime.py --variant native` ผลอยู่ที่ `out/runtime-tests-native/result.json` **ยังไม่ได้ทดสอบ binary ชุดนี้ใน Dev OS ISO หรือเครื่องจริง**

## ตาราง permissions

| Permission | พฤติกรรม |
| --- | --- |
| `background` | อนุญาตให้ launcher เริ่ม background entry point ด้วย `dev start` |
| `window` | อนุญาตให้ `dev open` เปิด UI และส่ง local X11 socket/authorization ให้ UI เท่านั้น |
| `storage` | mount พื้นที่ข้อมูลของแอปเป็น `/data` แบบถาวรและเขียนได้; หากไม่มีใช้พื้นที่ชั่วคราวของแต่ละโปรเซส |
| `network` | แชร์ network namespace ของ host ให้โปรเซสแอป; ถ้าไม่มีใช้ network namespace แยก |
| `notifications` | ส่ง Desktop notification ผ่าน broker เฉพาะแอป โดยไม่เปิด session bus หรือ display ให้ background |

ทุกครั้งที่ start/open ต้องให้ `--allow` ตรงกับชุด permissions ที่ประกาศทั้งหมด ไม่มี wildcard และไม่มีการจำสิทธิ์อัตโนมัติ การ install ไม่เริ่ม background และไม่เปิด UI ไม่รองรับ autostart หลัง boot ในรุ่นนี้

## Desktop notifications

เพิ่ม `"notifications"` ใน `permissions` แล้วอนุญาตเมื่อ launch เช่น:

```json
{
  "permissions": ["background", "notifications"],
  "background": {
    "runtime": "python",
    "entry_point": "opt/apps/notification-demo/background.py"
  }
}
```

ตัวอย่างฉบับเต็มอยู่ที่ `examples/notification-demo/manifest.json` และแพ็กเกจอยู่ที่ `out/notification-demo-0.1.0-all.dpk`

```sh
sudo dev install ./notification-demo-0.1.0-all.dpk
dev start notification-demo --allow background,notifications
dev stop notification-demo
```

จากโค้ดแอปที่รันใน sandbox ให้ใช้:

```sh
dev-notify "ดาวน์โหลดเสร็จแล้ว" "ไฟล์พร้อมใช้งาน" --urgency normal
```

Node.js เรียกได้โดยไม่ใช้ shell:

```js
const { spawnSync } = require('node:child_process');
const result = spawnSync('dev-notify', ['เสร็จแล้ว', 'บันทึกข้อมูลเรียบร้อย'], { encoding: 'utf8' });
if (result.status !== 0) console.error(result.stderr);
```

Python ใช้ `subprocess.run(['dev-notify', title, body], check=True)` ส่วน Linux binary ใช้ exec/spawn เรียกคำสั่งเดียวกัน หรือเชื่อม Unix socket จาก `DEVOS_NOTIFICATION_SOCKET` แล้วส่ง UTF-8 JSON หนึ่งบรรทัด:

```json
{"title":"เสร็จแล้ว","body":"บันทึกข้อมูลเรียบร้อย","urgency":"normal"}
```

ผลสำเร็จเป็น `{"ok":true,"id":123}` โดย ID มาจาก Desktop notification service ผลผิดพลาดเป็น `{"ok":false,"error":"..."}` และ CLI คืน exit code 1 ต้องอ่าน response ไม่ควรถือว่าส่งสำเร็จเพียงเพราะเขียนลง socket ได้

- รองรับ `low`, `normal`, `critical`; title ไม่เกิน 80 ตัวและ body ไม่เกิน 512 ตัว รับ Unicode แต่การแสดง glyph ขึ้นกับ font ของ Desktop
- จำกัด 1 คำขอต่อ 5 วินาทีต่อ app/root/user ร่วมกันทั้ง background และ window และยังจำช่วงจำกัดเมื่อ restart แอป
- ขอให้ notification daemon ปิดหลัง 5 วินาที แต่ daemon/การตั้งค่า Desktop อาจมีนโยบายต่างออกไป โดยเฉพาะ critical
- ไม่รองรับปุ่ม action, เปิด URL, เรียกคำสั่ง หรือ icon path จากแอป และ escape markup เมื่อ backend รองรับ markup
- helper กับ socket ถูก mount เฉพาะโปรเซสที่มี permission แอปส่งชื่อ package อื่นแทนตัวเองไม่ได้ผ่าน protocol นี้ ไม่มีการ mount D-Bus session socket ให้แอป
- permission นี้ใช้ได้ใน background โดยไม่ต้องมี `window`, `network` หรือ `storage`
- ใช้ [Freedesktop Desktop Notifications protocol](https://specifications.freedesktop.org/notification/latest/protocol.html) ผ่าน `gdbus` บน host ต้องมี D-Bus **session bus** และ notification daemon ของ Desktop เช่น Dunst การมี system bus อย่างเดียวไม่พอ หากไม่มี service จะปฏิเสธการเริ่มโปรเซสที่ขอ notifications
- ยังไม่มี Dev OS notification center/history ของตัวเอง, scheduling, persistent delivery, หรือการยืนยันว่าผู้ใช้เห็นข้อความแล้ว Desktop อาจใช้ Do Not Disturb

ทดสอบกับ Dunst จริงบน X11/WSLg ใน session bus แยก โดยสคริปต์เริ่มและหยุด daemon ของชุดทดสอบเอง:

```sh
DEVOS_TEST_DUNST=/absolute/path/to/dunst dbus-run-session -- python3 scripts/test-notifications.py
```

ผลอยู่ที่ `out/notification-tests/result.json` ครอบคลุม service หาย, grant ไม่ครบ, Unicode, daemon วาดหน้าต่าง, rate limit, ไม่มี endpoint เมื่อไม่ได้รับ permission และการเรียกจาก window ส่วน config Buildroot เพิ่ม GLib (`gdbus`) และ D-Bus แล้ว แต่ **ยังไม่ได้ rebuild ISO และยังไม่ได้รวม Desktop session/notification daemon ลง ISO เดิม**

ตัวแปรใน sandbox:

- `DEVOS_APP_DIR`: โฟลเดอร์ไฟล์แอปที่อ่านอย่างเดียว
- `DEVOS_DATA_DIR` และ `HOME`: `/data`
- `PATH`: `/usr/bin:/bin`
- UI ได้ `DISPLAY` และ `XAUTHORITY` เมื่อ session ต้องใช้ cookie

Launcher ล้าง environment เดิม ไม่ mount home ของ host ให้แอป ใช้ snapshot ที่ตรวจ SHA-256 ของไฟล์ติดตั้งอีกครั้งก่อนรัน แยก user/PID/IPC/network namespaces, ลด Linux capabilities และให้ filesystem runtime เป็น read-only หากไม่มี bubblewrap หรือ namespace ใช้งานไม่ได้ จะไม่ fallback ไปรันนอก sandbox

## ใช้งาน

บน Dev OS รุ่นที่รวม runtime และมี X11 desktop session แล้ว:

```sh
dev build examples/desktop-counter out/desktop-counter-0.1.0-all.dpk
dev info out/desktop-counter-0.1.0-all.dpk
sudo dev install out/desktop-counter-0.1.0-all.dpk

dev start desktop-counter --allow background,window,storage
dev open desktop-counter --allow background,window,storage
dev status desktop-counter
dev stop desktop-counter
```

ใช้ `sudo` เฉพาะติดตั้ง/ถอนแพ็กเกจ คำสั่ง runtime ปฏิเสธการรันด้วย root `dev open` รอจนหน้าต่างปิด แต่ background ที่เริ่มแยกไว้ยังทำงานต่อ `dev stop` หยุด background ของผู้ใช้ปัจจุบัน ไม่ปิด UI ที่เปิดอยู่

บน Linux desktop/WSLg ทดลองจาก checkout ได้ด้วยการแทน `dev` เป็น `python3 tools/dev.py` และใช้ `--root out/desktop-demo-root` ก่อน subcommand ทุกครั้งเพื่อไม่ติดตั้งลงระบบ host ต้องมี bubblewrap, Python 3.11+, libX11 และ local X11 display (`DISPLAY=:N`) ตั้ง `DEVOS_BWRAP` เป็นพาธ bubblewrap ได้เมื่อต้องการใช้ dependency ที่แตกไว้ใน workspace

ข้อมูลถาวรอยู่ใต้ `~/.local/share/devos/<hash-of-root-and-name>/` และ socket/log อยู่ใต้ `/tmp/devos-runtime-<uid>/` ทุกโฟลเดอร์เฉพาะแอป/ผู้ใช้เป็น mode 0700 ข้อมูลถาวรไม่ถูกลบเมื่อถอนแพ็กเกจ ใช้ package ID เดิมจะกลับมาเห็นข้อมูลเดิม ก่อนถอนหรือเปลี่ยนรุ่นต้องหยุด background และปิดหน้าต่างของผู้ใช้ที่กำลังใช้งาน เพราะ runtime ใช้ snapshot และอาจทำงานต่อได้แม้ลบไฟล์ติดตั้งแล้ว

## ขอบเขตของต้นแบบ

- สิทธิ์นี้บังคับเมื่อรันผ่าน launcher `dev` ไม่ใช่ mandatory policy สำหรับทุก executable ใน Linux ผู้ใช้ที่นำไฟล์ออกมารันเองจะไม่ได้รับ sandbox นี้
- X11 ให้สิทธิ์เข้าถึง session กว้าง แอป UI ที่ได้รับสิทธิ์อาจเข้าถึงหน้าต่างหรือ input ของแอปอื่นได้ **ยังไม่มีการแยก clipboard/screenshot/input เป็นรายสิทธิ์** ใช้กับแอปที่ไว้ใจได้ ส่วนการแยก desktop ที่ละเอียดกว่านี้ต้องเพิ่ม Wayland/portal runtime
- `network` เป็นสิทธิ์เครือข่ายทั้ง namespace ไม่ใช่ allowlist ของ domain และครอบคลุมทั้ง background/UI เมื่อให้สิทธิ์นี้
- `/usr`, `/bin`, `/sbin` และ library directories ที่มีอยู่เปิดให้อ่านเป็น system runtime; นี่ไม่ใช่การซ่อนทุกไฟล์ของ host หรือ sandbox ที่ผ่าน security audit
- กำหนด address space 256 MiB ต่อโปรเซสสำหรับ runtime อื่น ส่วน Node ใช้ 8 GiB ของ **virtual address space** เพื่อรองรับ V8 และตั้ง `--max-old-space-size=128` ซึ่งจำกัดเฉพาะ old-generation heap ไม่ใช่ RAM ทั้งโปรเซส ([Node CLI reference](https://nodejs.org/api/cli.html#--max-old-space-sizesize-in-mib)) ทั้งสองแบบกำหนด file size 4 MiB ต่อไฟล์, open descriptors 128 และ NPROC 256 ซึ่งมีขอบเขตตาม real UID ไม่ใช่โควตาเฉพาะแอป ยังไม่มี cgroup aggregate memory/CPU/disk quota หรือ syscall allowlist
- log ของ background เขียนทับเมื่อ start รอบใหม่ ยังไม่มี log rotation, restart-on-crash หรือ autostart
- ไม่รองรับการใช้ package directories/state ที่ผู้ใช้เดียวกันแก้ไขอย่างประสงค์ร้ายพร้อมกัน Runtime รุ่นนี้ไม่ใช่ขอบเขตความปลอดภัยระหว่างโปรเซสที่อยู่นอก sandbox และใช้ UID เดียวกัน
- การอัปเดต config Buildroot เพิ่ม bubblewrap, libX11 และ `CONFIG_USER_NS=y` แล้ว แต่ **ยังไม่ได้สร้างหรือทดสอบ ISO ใหม่ และยังไม่ได้เพิ่ม Desktop session ให้ ISO เดิม**

## ผลทดสอบ

รัน `python3 scripts/test-app-runtime.py` บน Linux ที่มี local X11 display และ bubblewrap ทดสอบ:

1. ปฏิเสธการเริ่มเมื่อไม่มี grants และเมื่อ sandbox หายไป
2. เริ่ม background และปฏิเสธการ start ซ้ำ
3. เปิดหน้าต่าง X11 จริง เก็บภาพจากหน้าต่าง แล้วปิด UI โดย background ยังนับต่อ
4. stop หยุดการเขียนข้อมูล และ restart อ่านข้อมูลถาวรเดิมได้
5. เมื่อไม่มี `network` ต่อ listener ของ host ไม่ได้ แต่เมื่อได้รับสิทธิ์ต่อได้
6. เมื่อไม่มี `storage` ไฟล์ไม่ถูกเก็บบน host แต่เมื่อได้รับสิทธิ์ถูกเก็บ
7. ทั้งสองกรณีไม่เห็น private file ของ host นอก mount ที่อนุญาต
8. มองไม่เห็น PID ของ process ทดสอบบน host และไม่ได้รับ environment ทดสอบจาก host
9. `NoNewPrivs` เปิดใช้งาน และ effective Linux capabilities เป็นศูนย์
10. เขียนเพิ่มไฟล์ใน snapshot `/app` ไม่ได้
11. หลัง `dev stop` process ลูกของแอปหยุดเขียนข้อมูลด้วย

ข้อจำกัดทรัพยากรปัจจุบันยังเป็น rlimit ราย process และข้อจำกัด Node heap ไม่ใช่
งบ memory/CPU รวมของทั้งแอป การแยกด้วย cgroup และทดสอบ OOM ของทั้ง process tree
ยังต้องทำก่อนผ่านเกณฑ์ production การผ่านชุด sandbox นี้ไม่ยืนยันว่าจัดสรร memory
ภายใต้โหลดสูงได้ตามเกณฑ์แล้ว

ผลที่อ่านด้วยโปรแกรมได้: `out/runtime-tests/result.json` ภาพ native window: `out/runtime-tests/native-window.png` ผลนี้เป็น Linux/WSLg ไม่ใช่การทดสอบ runtime ใน Dev OS ISO หรือเครื่องจริง

ทดสอบ Node+Bash ด้วย `python3 scripts/test-app-runtime.py --variant node-bash` ผลแยกอยู่ที่ `out/runtime-tests-node-bash/result.json` ชุดนี้ทดสอบด้วย Node.js 22.23.2 และ Bash บน Linux/WSLg พร้อมตรวจ runtime ที่ไม่มีอยู่แล้วต้องปฏิเสธการเริ่ม

อ้างอิงกลไก sandbox: [Bubblewrap README](https://github.com/containers/bubblewrap) และ [ตัวเลือกของ bubblewrap](https://github.com/containers/bubblewrap/blob/main/bubblewrap.c)
