# Dev OS DPK SDK 0.4

รองรับ `launcher` สำหรับ Application Menu ของแอปที่มี window แล้ว ดู [DPK-RUNTIME.md](../DPK-RUNTIME.md) รวม schema, icon และ permission confirmation ที่ตัวติดตั้ง/runtime ใช้

`launcher` กำหนด metadata ของไอคอนเท่านั้น โดยใช้ runtime, entry_point และ args จาก window เสมอ ต้องย้าย fields เหล่านี้จาก launcher ไป window ก่อน pack ด้วยรุ่นนี้

รองรับ `cli.commands` ใน manifest แล้ว ดู schema และ semantics ใน [DPK-FORMAT.md](../DPK-FORMAT.md) และตัวอย่าง `examples/cli-hello` ตัว SDK ตรวจและ pack declarations; ตัวติดตั้ง Dev OS รุ่นใหม่สร้าง launcher ตอน install

SDK สำหรับสร้าง source project, ตรวจ manifest และ pack `.dpk` ใช้ Python 3.11 ขึ้นไปบน Windows/Linux ไม่ต้องติดตั้ง Dev OS และไม่ต้องใช้ sudo สำหรับ pack ไม่มี third-party Python runtime dependencies

## ติดตั้งหรือใช้ portable

จาก root ของ checkout หลังสร้าง SDK release แล้ว:

```sh
python -m pip install out/sdk/devos_dpk_sdk-0.4.0-py3-none-any.whl
dpk --help
```

แนะนำติดตั้งใน virtual environment ของคุณ คำสั่ง `dpk-sdk` เป็น alias ของ `dpk` หรือใช้ `python -m dpk_sdk` หลังติดตั้ง หากไม่ต้องการติดตั้ง ให้ใช้ไฟล์ portable โดยตรง:

```sh
python out/sdk/dpk-sdk.pyz --help
python out/sdk/dpk-sdk.pyz init my-app --background-runtime node --window-runtime bash
python out/sdk/dpk-sdk.pyz validate my-app
python out/sdk/dpk-sdk.pyz pack my-app
python out/sdk/dpk-sdk.pyz verify my-app/dist/my-app-0.1.0-all.dpk
```

ไฟล์ `.pyz` ใช้ร่วมกับ Python ไม่ใช่ Windows `.exe` และไม่รวม Node/Bash/compiler ไว้ในตัว สำหรับคำสั่งตัวอย่างที่ใช้ `dpk` ด้านล่าง แทนด้วย `python /absolute/path/to/dpk-sdk.pyz` ได้ทั้งหมด

## สร้างแอป

```sh
dpk init my-app --background-runtime node --window-runtime bash
```

```text
my-app/
├── manifest.json
├── README.md
├── .gitignore
└── payload/opt/apps/my-app/
    ├── background.cjs
    ├── window.sh
    └── window.py
```

ตัวอย่างเริ่มต้นเป็น counter app มี background และหน้าต่างแยกกัน พร้อม `storage` เพื่อเก็บตัวเลข แอปที่ใช้ Node/Bash/sh ใน window template จะเรียก Python/libX11 เพื่อสร้างหน้าต่างจริง คุณเปลี่ยน payload เป็นโปรแกรมของคุณเองได้

ตัวเลือก:

- `--kind background`, `--kind window`, `--kind both` (ค่าเริ่มต้น)
- `--runtime python|node|bash|sh|native` ตั้งค่าเริ่มต้นให้ทั้งสองส่วน
- `--background-runtime` และ `--window-runtime` เลือกแยกกัน
- `--name my-package` กำหนด package ID ต่างจากชื่อ directory
- `--permissions notifications,network` เพิ่มสิทธิ์ที่แอปต้องการ ไม่ได้ให้สิทธิ์ launch อัตโนมัติ

`init` ปฏิเสธ directory ที่มีอยู่แล้ว ไม่เขียนทับงานเดิม ค่าเริ่มต้นไม่ขอ network หรือ notifications ส่วน format 1 ที่มีอยู่แล้วสามารถ validate/pack ได้โดยไม่ต้องสร้างโปรเจกต์ใหม่

## Linux binary

```sh
dpk init native-app --runtime native
cd native-app
python3 build.py
dpk validate .
dpk pack .
```

Native template มี C source และ `build.py` ให้ compile บน Linux ก่อน pack ต้องมี C compiler/static libc development files และ X11 headers/library เมื่อสร้างหน้าต่าง ใช้ `CC` เลือก compiler executable และ `DEVOS_X11_INCLUDE` เลือก include directory ได้ SDK ไม่ compile code โดยอัตโนมัติ และไม่เปลี่ยน Windows executable เป็น Linux binary

หากมี ELF binary อยู่แล้ว ให้วางใต้ `payload/opt/apps/<name>/`, ตั้ง `arch: x86_64`, `runtime: native`, `entry_point` และ `executables` ให้ตรงไฟล์ ใช้ toolchain/sysroot ที่ตรงกับ Dev OS เป้าหมาย ไม่ควรสมมติว่า binary จากทุก Linux distro จะรันได้

## ตรวจและ pack

```sh
dpk validate my-app
dpk validate my-app --json
dpk pack my-app
dpk pack my-app -o release/my-app.dpk
dpk inspect release/my-app.dpk
dpk verify release/my-app.dpk
```

- `validate` ตรวจ source manifest, entry points, permissions, path, file modes, inventory และขนาด พร้อมคำนวณ SHA-256 ไม่รันแอปและไม่ตรวจ ABI/library ของระบบปลายทาง
- `pack` ใช้ validation core เดียวกับ `dev` และเขียน archive ที่ตัวติดตั้งอ่านได้ มี `manifest.json` เป็นสมาชิกแรก
- ค่าเริ่มต้นออกไฟล์ `SOURCE/dist/<name>-<version>-<arch>.dpk` ถ้าระบุ `-o` พาธจะอิง working directory ปัจจุบัน
- ไม่เขียนทับไฟล์ output เดิม เว้นแต่ระบุ `--force`; ปฏิเสธ output ที่เป็น symlink หรืออยู่ใต้ payload
- ตรวจ archive ทั้งไฟล์ก่อน publish ผลลัพธ์แบบ atomic สำหรับโหมดไม่เขียนทับ filesystem ต้องรองรับ hard links (ทดสอบ NTFS และ Linux filesystem แล้ว); ไม่มี fallback ที่เสี่ยงเขียนทับไฟล์เดิม
- ตัด gzip timestamp/filename และใช้ลำดับสมาชิกคงที่ จึงสร้าง byte-identical `.dpk` ได้เมื่อ inputs และ SDK/Python/zlib environment เหมือนกัน
- `inspect` และ `verify` อ่าน payload และตรวจ hash ทั้งหมด โดยแตกลง temporary directory ไม่ใช่แค่ดู metadata; SHA-256 ไม่ใช่ signature ยืนยันผู้เผยแพร่
- ใช้พื้นที่ชั่วคราวสำหรับ archive ระหว่างสร้าง/ตรวจและ payload ที่แตกแล้ว ต้องเผื่อพื้นที่ดิสก์; จำกัด payload 256 MiB, 10,000 ไฟล์ และ manifest 2 MiB ตาม format ปัจจุบัน

SDK ไม่ติดตั้งแพ็กเกจลง OS, ไม่ให้ permission เอง, ไม่เริ่ม background/window และไม่ดาวน์โหลด runtime/dependencies เมื่อพร้อม ให้ใช้ `sudo dev install <file.dpk>` บน Dev OS ที่รองรับ format นั้น

## Python API

```python
from dpk_sdk import init_project, validate, pack, inspect_package, verify

init_project('my-app', background_runtime='node', window_runtime='bash')
metadata = validate('my-app')
archive = pack('my-app')
verified = verify(archive)
print(inspect_package(archive)['name'])
```

API คืนค่า `Path` สำหรับ init/pack และ manifest dictionary สำหรับ validate/inspect/verify; ข้อผิดพลาดยก exception ส่วน CLI แสดงข้อความและคืน exit code 1 (`argparse` คืน 2 เมื่อใช้คำสั่งผิด)

## สร้าง SDK release จาก source

```sh
python scripts/build-sdk.py
```

ต้องมี setuptools และ wheel ในเครื่องที่ build SDK release (ตัว SDK ที่ส่งมอบใช้เพียง Python standard library) สคริปต์รวม core รุ่นปัจจุบันจาก `tools/dev.py` และ template assets ลงใน release โดยไม่พึ่ง checkout ตอนใช้งาน ได้ `.whl`, `.pyz` และ `SHA256SUMS` ใต้ `out/sdk/`

ทดลองซอร์ส SDK ก่อนสร้าง release ด้วย `PYTHONPATH=sdk python -m dpk_sdk --help` บน Linux หรือ `$env:PYTHONPATH='sdk'; python -m dpk_sdk --help` ใน PowerShell

SDK รุ่นนี้รองรับ DPK format 1 และ 2 ส่วน ISO CLI เดิมยังไม่รวม runtime format 2/Desktop/notifications การ pack สำเร็จไม่ได้แปลว่า ISO เดิมจะรันความสามารถเหล่านั้นได้
