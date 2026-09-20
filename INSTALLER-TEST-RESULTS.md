# ผลทดสอบ Dev OS installer 0.1

ทดสอบวันที่ 17 กันยายน 2026 บน QEMU/KVM ภายใน Ubuntu WSL โดยใช้ UEFI OVMF, 2 vCPU, RAM 2 GiB และไฟล์ดิสก์เปล่าขนาด 8 GiB ทุกกรณี ไม่มีการส่ง physical disk ของ host เข้า VM

## อัปเดต prompt ใน ISO ล่าสุด

ISO ที่ส่งมอบปัจจุบันเพิ่ม prompt `username@hostname:directory$` และ `#` สำหรับ root โดยคง kernel และ userspace ของ baseline เดิมไว้

SHA-256 ปัจจุบัน: `875fa3c75ca7dc58af8e4fc9a37bb41ff2f6c5be6e5f4f0a92d4905d79c9badb`

ทดสอบ ISO ใหม่นี้บน QEMU/KVM + UEFI + VirtIO: ติดตั้งลงดิสก์จำลอง, บูตโดยถอด ISO, login ได้ `tester@dev-os-test:~$`, `su -` ได้ `root@dev-os-test:~#`, sudo และ .dpk ผ่าน รวมทั้งบูตซ้ำและตรวจแพ็กเกจที่ติดตั้งไว้ ผลอยู่ใน `out/test-results/prompt-installer.json` รอบอัปเดต prompt ไม่ได้ทดสอบ NVMe/SATA/USB ซ้ำ

Image แบบ direct boot ผ่านการทดสอบ prompt 12 รายการใน `out/test-results/prompt.json` และ checksum ของไฟล์ส่งมอบอยู่ใน `out/test-results/prompt-update.json`

## ผล ISO baseline ก่อนอัปเดต prompt

| อุปกรณ์เสมือน | ผล |
| --- | --- |
| NVMe | ผ่านการติดตั้ง, login, sudo/su, .dpk และบูตซ้ำ |
| SATA/AHCI | ผ่านการติดตั้ง, login, sudo/su, .dpk และบูตซ้ำ |
| VirtIO block | ผ่านการติดตั้ง, login, sudo/su, .dpk และบูตซ้ำ |
| USB storage ผ่าน xHCI | บูต raw-written ISO ได้ และปฏิเสธการใช้ USB ต้นทางเป็นเป้าหมาย |

ISO: `out/installer/dev-os-0.1-installer.iso`

SHA-256: `6156f61337e331818b1ff19d9cd7543168d5e22e2c04c35370c6ec1ca5a8b4c8`

ระหว่างทดสอบพบว่า kernel เดิมปิด PCI MSI ทำให้ NVMe I/O ค้าง แก้โดยเปิด `CONFIG_PCI_MSI=y` แล้วสร้างและทดสอบ ISO ใหม่ครบทั้งสี่ชุดข้างต้น

## ขอบเขตการทดสอบ

สคริปต์ `scripts/test-installer.py` บูต ISO และทำ setup แบบโต้ตอบ จากนั้นปิด VM แล้วบูตจากดิสก์ที่ติดตั้งโดยถอด ISO และไม่ใช้ `-kernel` หรือ `-initrd` ตรวจสิ่งต่อไปนี้:

- ยกเลิกตอนเลือกดิสก์ และปฏิเสธคำยืนยันล้างดิสก์: SHA-256 ของพื้นที่ 1 MiB แรกบนดิสก์ไม่เปลี่ยน
- สร้าง GPT, FAT32 ESP, ext4, บัญชีผู้ใช้ และ GRUB UEFI
- บูตจาก EFI loader บนดิสก์แล้ว login ด้วยบัญชีใหม่ UID 1000
- ยืนยันรหัสผ่าน `sudo` และ `su` ได้สิทธิ์ root และ ESP ถูก mount
- ติดตั้ง `.dpk`, เรียกโปรแกรม และอ่านรายการแพ็กเกจจากบัญชีผู้ใช้ปกติ
- บูตซ้ำอีกครั้งโดยไม่มี ISO: แพ็กเกจและโปรแกรมยังอยู่
- ระบบที่ติดตั้งไม่มี live marker และไม่ใช้ automatic root shell ของ installer

`scripts/test-installer-usb.py` เขียน ISO ลงไฟล์ USB เสมือนที่เขียนได้ขนาด 16 GiB แล้วบูตผ่าน QEMU xHCI/USB storage โดยไม่มี CD-ROM image ตรวจหน้า console และตรวจว่าตัวติดตั้งปฏิเสธ USB ต้นทางของตัวเอง

ผลที่อ่านด้วยโปรแกรมได้และ serial logs อยู่ใน `out/installer-tests/<ชนิด>/` แต่ละ `result.json` ของชุดล่าสุดบันทึก SHA-256 ของ ISO ที่ใช้ทดสอบ ส่วน screenshot อยู่ที่ `out/installer-tests/usb/setup-screen.png`

## การตรวจโค้ด

`python3 -m unittest discover -s tests -q` ผ่าน **23 รายการ** บน Linux ครอบคลุมตัวจัดการ `.dpk` และเงื่อนไขป้องกันของ installer: mounted disk, swap, read-only, ขนาดไม่พอ, mapped device, source media, identity ของดิสก์เปลี่ยน, payload checksum และ password hashing

## ข้อจำกัด

- ผลชุดนี้มาจาก VM ทั้งหมด **ยังไม่ได้ติดตั้งบนเครื่องจริง** จึงไม่รับรอง firmware และอุปกรณ์ทุกรุ่น
- รองรับ setup แบบล้างทั้งดิสก์สำหรับ x86_64 / UEFI 64-bit และต้องปิด Secure Boot
- ยังไม่รองรับ dual boot, ย่อพาร์ติชัน, disk encryption หรือ Legacy BIOS installation
- ไม่มีการทดสอบไฟดับระหว่างเขียนดิสก์ และไม่สามารถกู้ข้อมูลเดิมหลังเริ่ม partitioning ได้
- ค่าเวลาและ RAM ใน `TEST-RESULTS.md` เป็นผล base image ก่อนเพิ่ม installer ไม่ใช่ค่าประสิทธิภาพของ ISO ชุดนี้
- SHA-256 ใช้ตรวจความครบถ้วนของไฟล์ ไม่ใช่ลายเซ็นรับรองผู้เผยแพร่

วิธีสร้าง USB และติดตั้งอยู่ใน [INSTALL.md](INSTALL.md)
