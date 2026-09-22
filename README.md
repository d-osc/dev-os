# Dev OS

ต้นแบบ Linux distribution ของเราเอง เริ่มจากโปรเจกต์ว่าง โดยใช้ Linux kernel และสร้าง userspace จากซอร์สผ่าน Buildroot ไม่ได้ดัดแปลง Ubuntu image

รุ่นแรก: **x86_64, command line, BusyBox init, แพ็กเกจ `.dpk` และคำสั่ง `dev`**

ขั้นตอน build/test บน Windows + WSL พร้อมบัญชี VM แบบสุ่มรหัสผ่าน อยู่ใน [BUILDING.md](BUILDING.md)

## สถานะจริง

- **ยังไม่พร้อม production**: สถานะและเงื่อนไขออก release อยู่ใน [PRODUCTION-READINESS.md](PRODUCTION-READINESS.md)
- ซอร์สล่าสุดเพิ่ม `sudo dev verify [ชื่อแพ็กเกจ]`, OS lock และ [transaction recovery](TRANSACTION-RECOVERY.md) ด้วย `sudo dev recover`; ยังไม่ได้รวมใน ISO/SDK release

- ตัวจัดการแพ็กเกจ local ใช้งานและทดสอบบนเครื่องพัฒนาได้
- ซอร์ส `dev install` / `dev info` รับ `.dpk` และ `.tar.gz`; tarball ที่ไม่มี manifest จะสร้าง metadata อัตโนมัติและติดตั้งใต้ `/opt/<name>` พร้อมคำสั่งเรียกใช้เมื่อเลือก executable ได้ชัดเจน ไม่ compile หรือรัน install scripts
- **Build และบูตจริงสำเร็จ**: Linux 6.18.7, Python 3.14.7 และ root filesystem แบบ ext4
- ทดสอบ login, `sudo`, `su`, เครือข่าย และติดตั้ง/เรียกใช้/ลบ `.dpk` ผ่านใน QEMU/KVM ที่ RAM 256, 512 และ 1024 MiB
- ทดสอบ exported image บน Windows QEMU/TCG ถึงหน้า login ผ่านแล้ว
- มี [DPK SDK](sdk/README.md) สำหรับ init/validate/pack/inspect/verify บน Windows และ Linux พร้อม Python API
- มี [TypeScript SDK 0.5](sdk/typescript/README.md) พร้อม typed manifest, `cli.commands`, `launcher` และ async API ตรวจ/pack ด้วย Node.js โดยตรง ไม่ต้องมี Python
- รอบ regression ล่าสุดบน Linux พร้อม dependencies ของ TUF ผ่าน 131 รายการ และชุด publisher/provisioning เพิ่มเติมผ่าน ดู [สถานะ hardening](PRODUCTION-READINESS.md); ผล release SDK แยกอยู่ใน [ผลทดสอบ SDK](SDK-TEST-RESULTS.md)
- มี **ISO installer แบบ CLI สำหรับ x86_64 / UEFI** แล้ว ตั้งบัญชีใหม่และติดตั้งลงดิสก์ได้ ดู [คู่มือติดตั้ง](INSTALL.md) และ [ผลทดสอบตัวติดตั้ง](INSTALLER-TEST-RESULTS.md) ยังไม่ได้ทดสอบบนเครื่องจริง
- ซอร์สมี [TUF repository และ publisher](PUBLISHING.md), `dev trust`, signed install, `dev update`/`dev fetch`, `dev upgrade ชื่อแพ็กเกจ`, `dev rollback ชื่อแพ็กเกจ` และ `dev system-deploy` ที่ stage ระบบรุ่นใหม่ลง inactive slot พร้อม trial boot หนึ่งครั้ง (ทดสอบระดับ host fixture แล้ว) — repository ฝากบน GitHub Releases ได้ด้วย `github-upload` และ client ดึงจาก `releases/latest/download` ได้ (ทดสอบสดผ่านครบ ดู [PUBLISHING.md](PUBLISHING.md)) ยังไม่มี dependency resolver, health confirmation หรือ kernel/base-system rollback

## เปิด Dev OS ที่ build แล้ว

จาก PowerShell ในโฟลเดอร์โปรเจกต์:

```powershell
.\scripts\run-qemu.ps1
```

Login ด้วยบัญชี `dev` ดูรหัสผ่านเฉพาะเครื่องได้ใน `out/vm-credentials.json` ใช้รหัสผ่านของ `dev` กับ `sudo` และรหัสผ่านของ `root` กับ `su -` ไฟล์นี้ไม่ควรเผยแพร่

Image อยู่ใน `out/images/` และผลทดสอบอยู่ใน `out/test-results/` การรันแบบ snapshot จะไม่เก็บการแก้ไข disk หลังปิด VM

## ลอง `.dpk` ทันทีบน Windows

ใช้ Python 3.11 ขึ้นไป จากโฟลเดอร์โปรเจกต์:

```powershell
python tools/dev.py build examples/hello out/hello-0.1.0.dpk
python tools/dev.py info out/hello-0.1.0.dpk
python tools/dev.py --root out/demo-root install out/hello-0.1.0.dpk
python tools/dev.py --root out/demo-root list
python tools/dev.py --root out/demo-root remove hello
python -m unittest discover -s tests -v
```

`--root` ใช้ทดสอบใน directory แยก ตัวโปรแกรมไม่ได้เปลี่ยน Windows ให้เป็น Linux และ shell script ในแพ็กเกจตัวอย่างต้องรันใน Linux

เมื่อ build Dev OS แล้ว คำสั่งใน guest เป็น:

```sh
sudo dev install ./hello-0.1.0.dpk
dev list
dev info ./hello-0.1.0.dpk
sudo dev remove hello
su -
```

`dev install` คล้าย `apt install` แต่รุ่นนี้รับไฟล์ local เท่านั้น ส่วน `su` และ `sudo` ใช้กลไก Linux ตามปกติ ไม่ใช่คำสั่งจำลองของตัวจัดการแพ็กเกจ `.dpk` เป็นนามสกุลแพ็กเกจ ไม่ได้บังคับให้ไฟล์เอกสารหรือโปรแกรมทั้งหมดใน OS ใช้นามสกุลนี้

## Build บน Linux / WSL2

ใช้ Buildroot **2026.08** จาก [เว็บไซต์ทางการ](https://buildroot.org/download.html) และตรวจ checksum/signature ของ source ก่อนใช้ ต้องเตรียม dependencies ตาม [Buildroot manual](https://buildroot.org/downloads/manual/manual.html#requirement-mandatory)

ควรวางทั้งโปรเจกต์และ Buildroot ใน filesystem ของ Linux เช่น `~/src/` แทน `/mnt/c/` เพื่อประสิทธิภาพและ permission ของไฟล์ พาธต้องไม่มีช่องว่าง

```sh
cd ~/src/dev-os
chmod +x scripts/*.sh
sh scripts/configure.sh ~/src/buildroot-2026.08
make -C out/buildroot menuconfig
```

ธงตัวเลือกตอน configure (ใช้ tree ใหม่ทุกครั้งที่เปลี่ยน): `DEVOS_WITH_NODE=1`
เพิ่ม **Node.js runtime** (extension ภาษา JS และเครื่องมือ Node บนเครื่อง),
`DEVOS_WITH_RUST=1` เพิ่ม **rustc + cargo** — ทั้งคู่เป็น build ยาวจึงเป็น opt-in
และ configure จะตรวจว่า Buildroot เลือกแพ็กเกจจริงก่อนปล่อยผ่าน

ก่อน build ให้ตั้งค่าบัญชีที่ **System configuration**:

1. เปิด root login และตั้ง root password ของคุณเองสำหรับทดสอบผ่าน console
2. หากต้องการใช้ `sudo` จากผู้ใช้ปกติ ให้เพิ่มผู้ใช้ผ่าน `BR2_ROOTFS_USERS_TABLES` ตามหัวข้อ *Adding custom user accounts* ในคู่มือ Buildroot โดยใส่กลุ่ม `wheel` และตั้ง password hash ของผู้ใช้นั้น
3. อย่า commit password หรือ password hash ลง repository

ค่าเริ่มต้นปิด root login และยังไม่มีผู้ใช้ เพื่อไม่แจก image ที่ใช้รหัสผ่านร่วมกัน หากข้ามขั้นตอนนี้จะ login ไม่ได้

```sh
DEVOS_BUILD_JOBS=2 sh scripts/build.sh
sh scripts/run-qemu.sh
```

สคริปต์ configure เริ่มจาก QEMU x86_64 defconfig ของ Buildroot 2026.08 แล้วเพิ่ม Python, zlib, sudo, su และ `dev` ขนาด filesystem เริ่มต้น 512 MiB ใช้ ext4 และ RAM ของ VM 512 MiB ทดสอบงานพื้นฐานผ่านถึง RAM 256 MiB แล้ว แต่ยังไม่ใช่ข้อกำหนดขั้นต่ำสำหรับทุก workload

QEMU ต้องอยู่ใน PATH สคริปต์ใช้ `-snapshot` จึงทิ้งการแก้ไข disk เมื่อออก ถ้าต้องการเก็บแพ็กเกจที่ติดตั้งระหว่างทดสอบ ให้ลบ flag นี้และใช้สำเนา image ของตัวเอง ออกจาก serial console ด้วย `Ctrl+A` แล้ว `X`

การ compile ครั้งแรกใช้เวลานานและพื้นที่หลาย GB เริ่มด้วย `-j2` เพื่อจำกัดจำนวน compiler ที่ใช้ RAM พร้อมกัน ไม่จำเป็นต้อง build ด้วย root

## รูปแบบ Developer Package Kit v1

แอปที่มี permissions, background และหน้าต่าง native Desktop มี [DPK runtime รุ่น 2](DPK-RUNTIME.md) ในซอร์สแล้ว ทดสอบบน Linux/WSLg; ยังไม่รวมใน ISO CLI ที่ส่งมอบก่อนหน้านี้ มี [desktop shell: taskbar 40px ตามดีไซน์ (pill >_ DEVOS, ไอคอนแอปกลางจอ, tray, นาฬิกา 2 บรรทัด) พร้อมเมนูแอปแบบขออยินยอม](SHELL.md) แบบ X11 ล้วน ทดสอบบน display จริงด้วยภาพหลักฐานแล้ว ปรับแต่งได้ด้วย[ธีมสี/มุม/ไอคอนแบบ JSON](THEMES.md) กับ[`settings.json` แบบ VS Code](SETTINGS.md) และขยายได้ด้วย[extension (คำสั่งเมนู + ไอคอนถาด)](EXTENSIONS.md)

ดู [คู่มือออกแบบและ pack .dpk](DPK-FORMAT.md) สำหรับโครงสร้าง source, metadata, รูปแบบ archive, ขั้นตอนตรวจ และตัวอย่างพร้อมใช้งานใน `examples/dev-tool/`

`.dpk` เป็น gzip-compressed tar ที่มี `manifest.json` เป็นสมาชิกแรก ตามด้วย `payload/<path>` โฟลเดอร์ source ต้องมี `manifest.json` เช่นกัน builder เติม inventory และ SHA-256 ลงใน manifest ภายใน archive โดยไม่แก้ไฟล์ต้นฉบับ ตัวอย่าง source อยู่ใน `examples/hello`

Manifest มี `format`, `name`, `version`, `arch`, `files` โดยแต่ละไฟล์มี SHA-256 และ mode 0644 หรือ 0755 รุ่นแรกยอมรับเฉพาะ regular files ใต้ `/usr` และ `/opt` ไม่อนุญาต symlink, hardlink, device node, setuid file, install hook หรือการเขียนทับไฟล์เดิม รวมถึงป้องกัน `/usr/bin/dev`

ฐานข้อมูลอยู่ที่ `/var/lib/dev/installed.json` มี OS lock ป้องกันการติดตั้งพร้อมกันและ journal สำหรับกู้คืน install/remove ตาม commit ของฐานข้อมูล หากไฟล์ถูกแก้ไขหลังติดตั้งจะปฏิเสธการลบ

ข้อจำกัดของต้นแบบ:

- SHA-256 ตรวจความสอดคล้องกับ manifest **ไม่ใช่ลายเซ็นยืนยันผู้เผยแพร่** จึงใช้เฉพาะแพ็กเกจทดสอบที่เชื่อถือได้
- จำกัด payload รวม 256 MiB และไม่เกิน 10,000 ไฟล์ ใช้ buffer 1 MiB ระหว่าง copy แต่ยังมี overhead ของ Python และ metadata
- ยังไม่รับรองความปลอดภัยเมื่อผู้ใช้คนอื่นแก้ไข target directories พร้อมกัน ต้องใช้ root directory ที่ผู้ดูแลควบคุม
- มี journal ในซอร์สแล้วและทดสอบ abrupt process exit/QEMU power cut; ยังไม่รับรอง physical controller power loss และเมื่อพบไฟล์เปลี่ยนหรือ backup เสียจะเก็บ journal ให้ผู้ดูแลตรวจแทนการเขียนทับ
- ยังไม่จัดการ dependencies, ABI, base-system upgrade หรือการอัปเดต kernel ควร rebuild image สำหรับส่วนฐานระบบในระยะนี้
- `arch` เป็น metadata ที่ตรวจรูปแบบเท่านั้น ยังไม่มีการตรวจ ELF/ABI ของ payload

## เป้าหมายความเร็วและหน่วยความจำ

เริ่มจาก CLI และบริการพื้นหลังน้อย ใช้ BusyBox init และไม่เปิด daemon สำหรับตัวจัดการแพ็กเกจ Python ทำงานเฉพาะตอนเรียก `dev` จึงไม่กิน RAM ค้างหลังคำสั่งจบ

ไม่มี OS ที่รับประกันว่าจะไม่ค้างทุกกรณี ตอนนี้เก็บเวลา boot ถึง login, idle MemAvailable และการตอบสนองขณะโปรแกรมแตะหน่วยความจำครึ่งหนึ่งของ MemAvailable แล้วที่ RAM 256/512/1024 MiB ดู [ผลทดสอบ](TEST-RESULTS.md) งานที่ยังต้องวัดคือ peak RAM ระหว่างติดตั้งแพ็กเกจขนาดใหญ่, workload จริง, sustained load และการกู้คืนเมื่อหน่วยความจำหมด

เครื่องมือเริ่มต้น: `free -m`, `top`, `vmstat 1`, `cat /proc/meminfo` และ `dmesg` ตรวจเหตุการณ์ OOM ทดลอง workload ใน VM ที่ทิ้งข้อมูลได้เท่านั้น

ขั้นต่อไปคือทดลอง zram แบบจำกัดขนาดและเปรียบเทียบ latency/CPU ก่อนเปิดเป็นค่าเริ่มต้น zram บีบอัดข้อมูลใน RAM จึงช่วยได้ตามชนิดข้อมูลและมีต้นทุน CPU ดู [Linux zram documentation](https://www.kernel.org/doc/html/latest/admin-guide/blockdev/zram.html) ตอนนี้ยังไม่ได้เปิด zram หรือปรับ swappiness โดยไม่มีผลวัด

## ลำดับงานต่อไป

1. รวม verifier dependencies ลง Buildroot เพิ่ม dependency/ABI checks และทดสอบ image ที่รวม transaction recovery
2. วัด workload จริงและกรณี RAM ใกล้เต็ม แล้วทดลอง zram/การจำกัดบริการตามผลที่วัด
3. เพิ่มการอัปเดต kernel/ระบบฐานพร้อม rollback และทดสอบ installer กับ hardware จริง

การเผยแพร่ image ต้องเก็บ license notices และจัดเตรียม corresponding source ตาม license ของ kernel และแพ็กเกจที่รวมมา ใช้เป้าหมาย `make legal-info` ของ Buildroot ช่วยรวบรวมข้อมูลก่อนเผยแพร่
