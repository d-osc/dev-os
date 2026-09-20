# การออกแบบ Developer Package Kit (.dpk)

**เพิ่ม DPK format 2 แล้ว:** แอปที่ต้องการ `permissions`, `background` และหน้าต่าง Desktop ใช้ [DPK-RUNTIME.md](DPK-RUNTIME.md) ส่วนเอกสารด้านล่างอธิบาย format 1 ซึ่งยังใช้กับแพ็กเกจ CLI เดิมได้

สถานะ: แนวทาง pack สำหรับ **DPK format 1** คำสั่ง pack ชื่อ `dev build` ในซอร์สรุ่นปัจจุบันต้องมี `manifest.json` ในโฟลเดอร์ source แพ็กเกจที่สร้างยังติดตั้งด้วย reader ใน ISO เดิมได้ แต่คำสั่ง build ภายใน ISO ที่สร้างก่อนการเปลี่ยนนี้ยังใช้ชื่อเก่า ให้ใช้ `python tools/dev.py build` จาก checkout ปัจจุบัน หรือ rebuild image เพื่ออัปเดตคำสั่งใน OS

## 1. ประสบการณ์ของผู้พัฒนา

### คำสั่ง CLI จาก manifest

กำหนด `cli.commands` ได้ทั้ง format 1 และ 2 เช่น:

```json
{
  "manifest_version": 2,
  "name": "my-app",
  "version": "1.0.0",
  "arch": "all",
  "permissions": [],
  "cli": {
    "commands": {
      "my-app": {
        "runtime": "node",
        "entry_point": "opt/apps/my-app/cli.js",
        "args": ["--color=auto"]
      }
    }
  }
}
```

วางไฟล์จริงที่ `payload/opt/apps/my-app/cli.js` แล้ว pack/install ตามปกติ หลังติดตั้งเรียก `my-app --help` ได้ ตัว launcher ส่ง `args` ที่กำหนดไว้ก่อน arguments จากผู้ใช้ พร้อมรักษาช่องว่างและการ quote

- Runtime: `native` (ค่าเริ่มต้น), `node`, `bash`, `sh`, `python` โดย runtime ต้องมีในเครื่องปลายทาง
- Native entry ต้องระบุใน `executables`; script ที่เรียกผ่าน interpreter ไม่ต้องมี executable bit
- สร้าง `/usr/bin/<command>` ตอน install และบันทึก hash ใน `installed_commands` ของฐานข้อมูล; ถอน launcher พร้อมแพ็กเกจ ตรวจ conflicts และ rollback เช่นเดียวกับไฟล์ payload
- ไม่อนุญาตชื่อ `dev`, พาธในชื่อ command, คำสั่งชนกับ payload/ไฟล์เดิม หรือการส่ง `installed_commands` มาใน archive
- CLI-only format 2 ใช้ `permissions: []` ได้; ไม่ต้องมี background/window
- **CLI ทำงานเป็นคำสั่ง Unix ปกติด้วยสิทธิ์ผู้เรียก, cwd, stdin/stdout และ environment ปัจจุบัน ไม่อยู่ใน sandbox ของแอป** `permissions` ใช้กับ `dev start`/`dev open` ไม่จำกัด CLI และไม่เปิด background/window อัตโนมัติ
- ตัวอย่างพร้อม pack: `examples/cli-hello` สร้างคำสั่ง `dev-greet`

ต้องใช้ตัวจัดการ `dev` รุ่นที่รองรับ CLI นี้; SDK รุ่นใหม่สร้างแพ็กเกจได้ แต่ image/ISO รุ่นอัปเดต prompt ยังไม่ได้รวมตัวติดตั้งใหม่นี้

คำสั่ง `dev` ในซอร์สปัจจุบันรองรับ `.tar.gz` เป็นนามสกุลอีกแบบของแพ็กเกจ DPK:

```sh
dev build ./dev-tool ./dev-tool-0.1.0.tar.gz
dev info ./dev-tool-0.1.0.tar.gz
sudo dev install ./dev-tool-0.1.0.tar.gz
sudo dev remove dev-tool
```

สำหรับ `.tar.gz` ที่มี manifest: โครงสร้างภายในและการตรวจสอบเหมือน `.dpk` ทุกอย่าง โดย `manifest.json` เป็นสมาชิกแรก พร้อม inventory/hash แล้วตามด้วย regular files ใต้ `payload/` จึงสามารถเปลี่ยนนามสกุลแพ็กเกจ `.dpk` เป็น `.tar.gz` ได้

### นำเข้า tarball ที่ไม่มี manifest อัตโนมัติ

```sh
dev info ./my-app-1.2.3.tar.gz
sudo dev install ./my-app-1.2.3.tar.gz
my-app
sudo dev remove my-app
```

- ใช้ชื่อ archive เพื่อแยกชื่อ/เวอร์ชัน (`my-app-1.2.3` → `my-app`, `1.2.3`); ถ้าไม่พบเวอร์ชัน ใช้ `0.0.0` ชื่อไม่ถูกต้องต้องเปลี่ยนชื่อ archive ก่อน
- ตัดโฟลเดอร์ครอบชั้นเดียวเมื่อไฟล์ทั้งหมดอยู่ใต้โฟลเดอร์เดียวกัน แล้วติดตั้งใต้ `/opt/<name>/`
- สร้าง manifest/hash และบันทึกในฐานข้อมูลแพ็กเกจ เพื่อให้ `dev list` และ `dev remove` ใช้ได้ ไม่แก้ archive ต้นฉบับ
- เลือกไฟล์ชื่อ `<name>` หรือ `bin/<name>` ก่อน หรือ executable เดียวที่พบ โดยต้องมี executable bit และเป็น ELF/shebang script จากนั้นสร้าง launcher `/usr/bin/<name>` ถ้ากำกวมหรือเป็น source distribution ที่ตรวจพบ จะติดตั้งไฟล์อย่างเดียวและแจ้งว่าไม่มีคำสั่งที่เลือกได้
- ไม่รันโปรแกรม ไม่ compile ไม่เรียก `configure`, `make` หรือ install scripts; source tarball ไม่ได้กลายเป็นแอปที่พร้อมรันโดยอัตโนมัติ
- รับเฉพาะ regular files/directories ปฏิเสธ links, devices, traversal, ไฟล์ซ้ำ, ELF ที่ไม่ใช่ x86_64 และไฟล์ที่ชนกับของเดิม; ไม่เก็บ setuid/setgid bits
- ไม่มีการรับรองความเข้ากันได้ของไลบรารีที่ binary ต้องใช้ ไม่มี dependency installation หรือ signature verification
- `.dpk` และ SDK archive verification ยังคงต้องมี manifest; DPK ที่มี manifest เสียหรือ checksum ผิดจะไม่ถูก fallback ไปเป็น plain tarball

ติดตั้งทีละ archive; `*.tar.gz` ไม่ได้เพิ่มโหมดติดตั้งหลายไฟล์ในคำสั่งเดียว

ต้องใช้ `tools/dev.py` รุ่นใหม่นี้หรืออัปเดต `/usr/bin/dev` ใน OS ก่อน; ISO รุ่นอัปเดต prompt เดิมยังไม่ได้รวมความสามารถนี้

```text
เขียนโปรแกรม → compile ถ้าจำเป็น → จัด payload → dev build → ตรวจและทดลองติดตั้ง → แจกไฟล์ .dpk
```

`dev build` บรรจุไฟล์ที่เตรียมไว้ ไม่ compile source และไม่รันสคริปต์ในแพ็กเกจ ใช้สิทธิ์ผู้ใช้ปกติในการ pack ส่วนติดตั้งเข้า OS ต้องใช้ `sudo`

แนะนำชื่อไฟล์ `<name>-<version>-<arch>.dpk` เช่น `dev-tool-0.1.0-all.dpk` ชื่อไฟล์เป็นเพียงธรรมเนียม ตัวติดตั้งอ่านตัวตนแพ็กเกจจาก manifest ภายใน

## 2. โฟลเดอร์ก่อน pack

```text
dev-tool/
├── manifest.json
└── payload/
    └── usr/
        ├── bin/
        │   └── dev-tool
        └── share/
            └── doc/
                └── dev-tool/
                    └── README.txt
```

พาธใต้ `payload/` ตรงกับพาธติดตั้ง เช่น `payload/usr/bin/dev-tool` จะติดตั้งเป็น `/usr/bin/dev-tool` ไม่มีการเดาตำแหน่งจากนามสกุลไฟล์

| ชนิดไฟล์ | ตำแหน่งแนะนำ |
| --- | --- |
| คำสั่งที่ผู้ใช้เรียก | `/usr/bin/<command>` |
| ไฟล์ภายในของโปรแกรม | `/usr/lib/<package>/` |
| ข้อมูลคงที่ รูป และ template | `/usr/share/<package>/` |
| คู่มือและ license notices | `/usr/share/doc/<package>/` |
| แอปที่รวมไฟล์ไว้ในโฟลเดอร์เดียว | `/opt/<package>/` |

รุ่นนี้รับเฉพาะ regular files ใต้ `/usr` และ `/opt` ไม่บรรจุ directory เปล่า, symlink, device node, setuid หรือไฟล์ตั้งค่าใต้ `/etc` ให้โปรแกรมสร้างการตั้งค่าส่วนบุคคลใน home เมื่อผู้ใช้เรียกใช้งาน ไม่เขียนข้อมูลที่เปลี่ยนแปลงลงไฟล์ที่ package manager เป็นเจ้าของ

## 3. manifest.json ที่ผู้พัฒนาเขียน

```json
{
  "manifest_version": 1,
  "name": "dev-tool",
  "display_name": "Dev Tool",
  "short_name": "Dev Tool",
  "version": "0.1.0",
  "arch": "all",
  "description": "A small command-line tool for Dev OS",
  "icons": {"128": "usr/share/dev-tool/icon.svg"},
  "executables": ["usr/bin/dev-tool"]
}
```

| Field | ความหมายและข้อกำหนดปัจจุบัน |
| --- | --- |
| `manifest_version` | เวอร์ชัน schema ของ DPK ใช้ `1`; manifest เก่าที่ไม่มี field นี้ถือเป็นรุ่น 1 และ builder เติมให้ |
| `name` | ตัวตนสำหรับ install/list/remove แนะนำ lowercase และขีดกลาง เช่น `dev-tool` |
| `display_name`, `short_name` | ชื่อแสดงผลและชื่อย่อ เป็น metadata; `dev list` ปัจจุบันยังแสดง `name` |
| `version` | แนะนำ `MAJOR.MINOR.PATCH` เช่น `0.1.0`; ยังไม่มีการเปรียบเทียบเวอร์ชันหรือ upgrade |
| `arch` | `all` สำหรับไฟล์ที่ไม่ผูกกับ CPU หรือ `x86_64` สำหรับ binary ของสถาปัตยกรรมนี้ |
| `description` | คำอธิบายสำหรับมนุษย์ แสดงผ่าน `dev info` |
| `author`, `homepage_url` | ข้อมูลผู้พัฒนาและหน้าเว็บ เป็นข้อความ ไม่ใช่การยืนยันตัวตน และไม่เปิด URL อัตโนมัติ |
| `icons` | map ขนาดเป็นพาธใต้ payload เช่น `"128": "usr/share/dev-tool/icon.svg"`; ตรวจว่ามีไฟล์ใน inventory จริง |
| `executables` | พาธสัมพัทธ์ที่ต้องได้ mode `0755`; ไฟล์อื่นเป็น `0644` |

ชื่อและเวอร์ชันที่โค้ดยอมรับมีความยาว 1–80 ตัว เริ่มด้วยตัวอักษรอังกฤษหรือตัวเลข ที่เหลือใช้ตัวอักษรอังกฤษ ตัวเลข `.`, `_`, `+`, `-` ได้ ผู้พัฒนาไม่ต้องเขียน `format` หรือ `files` เพราะ builder สร้างให้ใหม่

ใช้ slash `/` และไม่มี `/` นำหน้าใน `executables` แม้ pack บน Windows รายการนี้กำหนด executable bit แทนการพึ่ง permission ของเครื่องที่ใช้ pack ถ้าอ้างไฟล์ที่ไม่มีอยู่ builder จะปฏิเสธ

### ความคล้ายกับ Chrome Extension

อ้างอิงแนวทาง JSON จาก [Chrome manifest reference](https://developer.chrome.com/docs/extensions/reference/manifest): มี `manifest_version`, `name`, `version`, `description` และ `icons` แต่เลขเวอร์ชันของ DPK เป็นของ Dev OS เอง จึงใช้ `1` ไม่ใช่ Chrome Manifest V3

DPK คง `name` เป็น package ID สำหรับคำสั่งเดิม และใช้ `display_name` สำหรับชื่อที่มีช่องว่าง ส่วน `arch`, `executables` และ inventory เป็นข้อมูลเฉพาะ OS ไม่ใช่ Chrome Extension API

ฟิลด์ข้อความเสริมต้องเป็น string ที่ไม่ว่างและยาวไม่เกิน 2,048 ตัว ไอคอนใช้ key ขนาดเป็นตัวเลข 1–9999 และพาธสัมพัทธ์จาก `payload/` ระบบตรวจพาธและ checksum ของไฟล์ แต่ยังไม่ decode รูปเพื่อตรวจชนิดหรือขนาด และ CLI ยังไม่แสดงไอคอน ตัวอย่าง SVG นี้ใช้กับ DPK ไม่ใช่การรับรองว่าโหลดเป็นไอคอน Chrome Extension ได้

ยังไม่มี browser runtime หรือ sandbox permissions ใน Dev OS ตัวตรวจรุ่นนี้ปฏิเสธ `permissions`, `optional_permissions`, `host_permissions`, `optional_host_permissions`, `background`, `content_scripts` และ `action` เพื่อไม่ให้เข้าใจว่าความสามารถเหล่านี้ถูกใช้งานจริง การรันโปรแกรมใช้สิทธิ์ Linux ของผู้เรียกตามปกติ ไม่ใช่ permission model ของ Chrome

reader ใน ISO เดิมยังติดตั้งไฟล์ format 1 ได้ แต่จะยังไม่ตรวจ metadata ใหม่ดังกล่าว ต้อง rebuild image เพื่อให้ตัวตรวจรุ่นใหม่นี้ทำงานใน guest

`arch: all` ไม่ได้แปลว่ารันได้โดยไม่มี runtime เช่น Python script ยังต้องมี Python ส่วน binary `x86_64` ต้อง compile ให้ตรง Linux และ ABI ของ Dev OS รุ่นเป้าหมาย ตัวติดตั้งปัจจุบันตรวจเพียงค่าของ `arch` ยังไม่ตรวจ ELF/ABI หรือแก้ dependencies ให้

## 4. ภายในไฟล์ .dpk

```text
dev-tool-0.1.0-all.dpk         ← gzip-compressed tar
├── manifest.json             ← ต้องเป็นสมาชิกแรก
└── payload/
    └── usr/...
```

ภาพโครงสร้างนี้แสดงพาธเชิงตรรกะ ใน archive จริง builder ใส่เฉพาะ manifest และสมาชิกที่เป็นไฟล์ ไม่ใส่สมาชิก directory

manifest ภายใน archive เก็บ metadata จาก `manifest.json` ของ source พร้อมข้อมูลที่ builder คำนวณ โดยไม่แก้ไขไฟล์ source เช่น:

```json
{
  "format": 1,
  "name": "dev-tool",
  "version": "0.1.0",
  "arch": "all",
  "description": "A small command-line tool for Dev OS",
  "executables": ["usr/bin/dev-tool"],
  "files": {
    "usr/bin/dev-tool": {
      "sha256": "<SHA-256 จริงจำนวน 64 ตัวที่ builder คำนวณ>",
      "mode": 493
    }
  }
}
```

ตัวอย่างด้านบนย่อ inventory เพื่อแสดงรูปแบบ ไม่ใช่ manifest พร้อมใช้ ค่า `493` ใน JSON เท่ากับ `0755` ในเลขฐานแปด และ `420` เท่ากับ `0644` ตัวติดตั้งใช้ mode ใน manifest เป็นหลัก

เลือก gzip ในรุ่นแรกเพื่อให้ตรงกับ reader ที่มีอยู่ ไม่เปลี่ยน compression โดยคง `format: 1` เพราะตัวอ่านปัจจุบันเปิดด้วย gzip โดยตรง ไม่ซ้อน `payload.tar` อีกชั้น เพื่อลดขั้นตอน unpack

## 5. คำสั่ง pack และตรวจ

บน Dev OS หรือ Linux ที่ติดตั้งคำสั่ง `dev` แล้ว:

```sh
dev build examples/dev-tool out/dev-tool-0.1.0-all.dpk
dev info out/dev-tool-0.1.0-all.dpk
sudo dev install out/dev-tool-0.1.0-all.dpk
dev-tool --version
dev list
sudo dev remove dev-tool
```

บนเครื่องพัฒนา Windows เรียกตัวเดียวกันผ่าน Python 3.11 ขึ้นไป:

```powershell
python tools/dev.py build examples/dev-tool out/dev-tool-0.1.0-all.dpk
python tools/dev.py info out/dev-tool-0.1.0-all.dpk
python tools/dev.py --root out/dpk-sandbox install out/dev-tool-0.1.0-all.dpk
python tools/dev.py --root out/dpk-sandbox list
python tools/dev.py --root out/dpk-sandbox remove dev-tool
```

`--root` ต้องอยู่ก่อน subcommand ใช้ทดสอบลง directory แยก; shell script ตัวอย่างต้องทดลองเรียกใน Linux การ pack บน Windows ไม่แปลง `.exe` เป็น Linux binary สำหรับ shell script ให้บันทึก UTF-8 แบบไม่มี BOM และใช้ LF

`dev info` ปัจจุบันตรวจ payload และ checksum ด้วย จึงใช้พื้นที่ชั่วคราวสำหรับแตกไฟล์ ไม่ได้อ่านเฉพาะ metadata ส่วน builder ปัจจุบันเขียนทับ output ที่มีอยู่ได้ ควรใช้ชื่อเวอร์ชันใหม่เมื่อสร้าง release

## 6. สัญญาการติดตั้งและขอบเขตทรัพยากร

1. อ่าน manifest แล้วตรวจรูปแบบและพาธ
2. แตกไฟล์ลง staging ตรวจชนิดไฟล์ จำนวน ขนาด และ SHA-256 ให้ครบ
3. ตรวจชื่อแพ็กเกจซ้ำและ file conflict ก่อนคัดลอกเข้าระบบ
4. คัดลอกไฟล์และบันทึก inventory ใน `/var/lib/dev/installed.json`
5. ถ้าเกิดข้อผิดพลาดที่โปรแกรมจับได้ระหว่างเขียน ให้ย้อนการเปลี่ยนแปลงที่ติดตามไว้

รุ่นนี้ไม่รัน pre/post-install hooks และไม่เขียนทับไฟล์เดิม ป้องกัน `/usr/bin/dev` โดยเฉพาะ การ remove จะปฏิเสธเมื่อไฟล์แพ็กเกจถูกแก้ไข ไม่ลบข้อมูลที่เปลี่ยนไปโดยอัตโนมัติ

- payload ไม่เกิน 256 MiB และไม่เกิน 10,000 ไฟล์
- reader รับ manifest ไม่เกิน 2 MiB; builder ยังไม่ได้ตรวจขนาด manifest ก่อนเขียน จึงต้องรัน `dev info` เป็น release check
- copy ใช้ buffer 1 MiB แต่ยังมี memory overhead ของ Python และ metadata ไม่ได้จำกัด RAM ทั้งโปรเซสไว้ที่ 1 MiB
- ต้องเผื่อพื้นที่ให้ทั้ง staging และไฟล์ปลายทาง ประมาณสองเท่าของ payload ที่ไม่บีบอัด บวก archive, metadata และ filesystem overhead; ยังไม่มี disk-space preflight
- checksum ตรวจความครบถ้วน ไม่ยืนยันผู้เผยแพร่ จึงติดตั้งเฉพาะไฟล์ที่เชื่อถือแหล่งที่มา
- ซอร์สล่าสุดมี [recovery journal](TRANSACTION-RECOVERY.md) สำหรับ install/remove และทดสอบ process/QEMU ถูกหยุดกะทันหัน; ยังไม่รับรอง hostile concurrent changes ใน target directories หรือ physical storage ทุกชนิด

## 7. ทิศทางรุ่นถัดไป — ยังไม่ implement

ลำดับที่แนะนำ:

1. ทำ builder ให้ตรวจ metadata, executable paths และขนาด manifest อย่างเข้มงวด พร้อมสร้าง output แบบ atomic และ reproducible
2. เพิ่ม inventory ขนาดไฟล์, target OS/ABI และ metadata ของ license/source พร้อม schema ที่ชัดเจน
3. ออกแบบ signed manifest และ trust store โดยให้ลายเซ็นครอบคลุม metadata กับ hash ของทุกไฟล์ กำหนดวิธีเพิ่ม ถอน และหมุนเวียน signing keys
4. เพิ่ม dependencies และกติกาเปรียบเทียบเวอร์ชัน พร้อม resolver และการตรวจเงื่อนไขก่อนติดตั้ง
5. ทดสอบ transaction journal บนฮาร์ดแวร์เป้าหมาย และเพิ่ม upgrade/config-file policy ก่อนเปิด repository ให้ใช้งานทั่วไป

field ที่มีผลต่อความถูกต้อง เช่น dependencies, ABI และ signature ต้องเพิ่มพร้อมตัวตรวจที่บังคับใช้จริง และใช้ format รุ่นใหม่เมื่อเปลี่ยนสัญญาการติดตั้ง เพื่อให้ reader เก่าปฏิเสธ แทนการมองข้ามเงื่อนไขที่ไม่เข้าใจ ปัจจุบัน field เพิ่มเติมอาจถูกเก็บไว้แต่ไม่ได้บังคับใช้ จึงไม่ควรใส่ `depends` แล้วเข้าใจว่าระบบติดตั้ง dependency ให้แล้ว

ตัวอย่างพร้อม pack อยู่ใน `examples/dev-tool/` และโค้ดอ้างอิงอยู่ใน `tools/dev.py`
