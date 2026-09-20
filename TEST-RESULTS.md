# ผลทดสอบ Dev OS 0.1

รายงานนี้เป็นผลของ base image ก่อนเพิ่มตัวติดตั้ง ค่าเวลาและ RAM ด้านล่างไม่ได้วัดจาก installer ISO รุ่นใหม่ ดูผลชุดติดตั้งแยกใน [INSTALLER-TEST-RESULTS.md](INSTALLER-TEST-RESULTS.md)

ทดสอบวันที่ 17 กันยายน 2026 บนเครื่องพัฒนานี้ สร้างระบบจาก Buildroot 2026.08, Linux 6.18.7 และ Python 3.14.7

## บูตและใช้งานจริงใน QEMU

QEMU/KVM ภายใน Ubuntu WSL ใช้ 2 vCPU และ disk snapshot ทดสอบตามลำดับทีละ VM:

| RAM ที่ให้ VM | บูตถึง login | MemAvailable ตอน idle | ผล |
| --- | ---: | ---: | --- |
| 256 MiB | 1.549 วินาที | 215.36 MiB | ผ่าน |
| 512 MiB | 1.538 วินาที | 463.85 MiB | ผ่าน |
| 1024 MiB | 1.530 วินาที | 961.63 MiB | ผ่าน |

MemAvailable อ่านจาก `/proc/meminfo` หลัง login ก่อนเรียกตัวจัดการแพ็กเกจ เป็นค่าประมาณ RAM ที่ kernel ประเมินว่ายังให้โปรแกรมใช้ได้ ไม่ใช่แค่ช่อง MemFree และรวมหน่วยความจำที่ reclaim ได้ ค่าต่างระหว่าง RAM ที่กำหนดกับ MemAvailable จึงไม่ใช่หน่วยความจำของโปรเซสอย่างเดียว

ในทั้งสาม VM ทดสอบผ่าน:

- Login ผู้ใช้ `dev` และตรวจ UID 1000
- ปฏิเสธการติดตั้ง `.dpk` เมื่อไม่มีสิทธิ์ root
- ยืนยันรหัสผ่านผ่าน `sudo` และ `su` แล้วตรวจ UID 0
- ติดตั้งแพ็กเกจตัวอย่าง เรียก `dev-hello`, อ่าน `dev list` จากผู้ใช้ปกติ และลบแพ็กเกจ
- รับ IPv4 ผ่าน DHCP
- โปรแกรมทดสอบแตะหน่วยความจำครึ่งหนึ่งของ MemAvailable แล้วถือไว้ 12 วินาที ขณะนั้น shell ยังตอบสนอง หลังโปรแกรมจบตรวจไม่พบ OOM/killed-process ใน `dmesg`

การทดสอบจัดสรรหน่วยความจำไม่ได้ทำให้ RAM หมด และยังไม่ใช่การทดสอบโหลดต่อเนื่องหรือรับรองว่าจะไม่ค้างทุกกรณี เวลาโต้ตอบ shell ใน JSON รวม delay ของ pexpect และ scheduling ของ host จึงไม่ควรใช้เป็นตัวเลข latency ของ OS โดยตรง

## เปิด exported image บน Windows

QEMU/TCG, RAM 512 MiB, 2 vCPU: **ผ่าน** บูตถึง login ใน **4.869 วินาที** โดยใช้ kernel และ disk image ที่ส่งออกกลับมายัง Windows จริง การทดสอบนี้ตรวจถึงหน้า login ส่วนการยืนยันรหัสผ่านและแพ็กเกจทดสอบเต็มใน WSL/KVM ตามด้านบน

เวลา boot เป็นการวัดครั้งเดียวต่อการตั้งค่า บน VM และ host นี้ ไม่ใช่ค่าเฉลี่ยหรือการรับรองผลบนเครื่องอื่น

## Unit/regression tests

`python3 -m unittest discover -s tests -q` บน Ubuntu WSL: **12 tests ผ่าน ไม่มี skip**

ครอบคลุม install/remove, ไฟล์ชนกัน, checksum ผิด, path traversal, symlink ใน archive และ target, database lock, rollback เมื่อเขียนฐานข้อมูลล้มเหลว, ไฟล์ที่ถูกแก้ไขหลังติดตั้ง, สิทธิ์อ่าน metadata ของผู้ใช้ปกติ และการสร้าง password hash ที่ใช้กับ Buildroot ได้

การทดสอบ guest ช่วยพบและแก้ปัญหา `installed.json` ที่เดิมใช้ mode 0600 หลัง `sudo dev install` ทำให้ `dev list` ของผู้ใช้ปกติอ่านไม่ได้ ปัจจุบัน metadata ใช้ 0644 และมี regression test แล้ว

## ไฟล์ผลลัพธ์

- `out/images/bzImage`: kernel, 6,644,736 bytes
- `out/images/rootfs.ext4`: disk/root filesystem ขนาด 512 MiB
- `out/images/SHA256SUMS`: checksum ของ image ที่ส่งออก
- `out/test-results/vm-256.json`, `vm-512.json`, `vm-1024.json`: ผลตรวจ guest และค่าหน่วยความจำ
- `out/test-results/windows-tcg.json`: ผลบูตด้วย Windows QEMU
- ไฟล์ `.log` ใน directory เดียวกัน: serial console ของการทดสอบ

ไฟล์ build, credentials และ logs อยู่ใน `out/` ซึ่งถูก exclude จาก version control ต้องรัน build/test เพื่อสร้างใหม่บนเครื่องอื่น ขั้นตอนอยู่ใน [BUILDING.md](BUILDING.md)

ยังไม่ได้ทดสอบ bare metal, ISO/installer, power-loss recovery, repository signatures หรือการ upgrade ระบบฐาน ผลนี้ยืนยันต้นแบบ CLI ที่บูตและจัดการแพ็กเกจ local ได้เท่านั้น
