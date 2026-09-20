# ติดตั้ง Dev OS ลงเครื่องจริง

ตัวติดตั้งรุ่นแรกเป็น **CLI สำหรับ x86_64 / UEFI 64-bit** ใช้ GPT, EFI System Partition และ ext4 ติดตั้งแบบ offline จาก ISO ได้ โดยตั้งบัญชีและรหัสผ่านใหม่ระหว่าง setup

ซอร์ส installer A/B ที่กำลังทดสอบใช้ดิสก์ขั้นต่ำ **16 GiB**: EFI 512 MiB,
boot 256 MiB, root A/B ชุดละ 4 GiB และพื้นที่ที่เหลือสำหรับ `/home` แยก
เริ่มติดตั้งใน A ส่วน B ยังว่างสำหรับอัปเดตที่ตรวจลายเซ็นภายหลัง ซึ่งเส้นทางอัปเดต
ยังไม่เสร็จ ISO ที่ส่งออกเดิมยังเป็น layout root เดียวตามข้อกำหนดด้านล่าง
อย่าใช้ผลทดสอบ ISO เดิมยืนยัน installer A/B รุ่นใหม่

**ตัวติดตั้งลบข้อมูลทั้งหมดบนดิสก์ที่เลือก** เตรียมข้อมูลสำรองก่อนเริ่ม และตรวจชื่อดิสก์ รุ่น ความจุ และ serial ให้ตรงกัน รุ่นนี้ยังไม่รองรับ dual boot, การย่อพาร์ติชัน, disk encryption หรือ Legacy BIOS

## ไฟล์และความต้องการ

- ISO: `out/installer/dev-os-0.1-installer.iso`
- SHA-256: `out/installer/SHA256SUMS`
- CPU: x86_64, firmware: UEFI 64-bit
- ปิด Secure Boot สำหรับ ISO รุ่นนี้ ซึ่งยังไม่ได้ลงลายเซ็น Secure Boot
- RAM สำหรับ setup: แนะนำอย่างน้อย 2 GiB ตามการตั้งค่าที่ใช้ทดสอบ
- ดิสก์ปลายทาง: อย่างน้อย 8 GiB ตัวติดตั้งใช้ทั้งดิสก์ แนะนำ 16 GB ขึ้นไปสำหรับเพิ่มโปรแกรม
- USB สำหรับบูต installer: 1 GB ขึ้นไป ข้อมูลบน USB จะถูกแทนที่เมื่อเขียน image

kernel มีไดรเวอร์ NVMe, SATA/AHCI, USB storage และ USB keyboard แต่ยังไม่ได้ทดสอบกับเครื่องจริงทุกแบบ Wi-Fi, RAID/RST, GPU และอุปกรณ์เฉพาะรุ่นอาจต้องเพิ่ม driver/firmware ภายหลัง ผลทดสอบ VM อยู่ใน `INSTALLER-TEST-RESULTS.md`

## 1. เตรียม USB บน Windows

ตรวจ checksum จาก PowerShell โดยเทียบค่ากับไฟล์ SHA256SUMS:

```powershell
Get-FileHash .\out\installer\dev-os-0.1-installer.iso -Algorithm SHA256
Get-Content .\out\installer\SHA256SUMS
```

ใช้ [Rufus จากเว็บไซต์ทางการ](https://rufus.ie/en/) ซึ่งรองรับการสร้าง USB ที่บูตได้จาก ISO:

1. เสียบ USB สำหรับ installer
2. เลือก USB ให้ถูกต้องใน Device
3. เลือกไฟล์ `dev-os-0.1-installer.iso`
4. เริ่มเขียน image และหากโปรแกรมถามโหมด ให้เลือก **DD Image mode** เพื่อคงรูปแบบ image ที่สร้างไว้
5. รอจนเขียนเสร็จแล้วนำ USB ไปบูตเครื่องปลายทาง

ยังไม่มีการเขียน USB หรือดิสก์จริงของผู้ใช้โดยอัตโนมัติในโปรเจกต์นี้

## 2. บูตเข้า setup

เปิด boot menu ของเครื่อง เลือกรายการ USB แบบ **UEFI** และเลือกเมนู **Dev OS setup (screen and keyboard)** ใช้เมนู serial console เฉพาะกรณีที่ควบคุมเครื่องผ่าน serial

เมื่อเห็น `DEVOS-LIVE#` ให้รัน:

```sh
dev install-system
```

Live environment ให้ root shell สำหรับ setup โดยตรง ไม่มีบัญชีหรือรหัสผ่านร่วมกันที่จะถูกส่งต่อไปยังระบบที่ติดตั้ง

## 3. เลือกดิสก์และตั้งบัญชี

ตัวติดตั้งจะตรวจไฟล์ระบบและเครื่องมือที่ต้องใช้ แล้วแสดงดิสก์พร้อมความจุ รุ่น และ serial ตัวอย่างชื่อดิสก์:

- SATA: `/dev/sda`
- NVMe: `/dev/nvme0n1`
- VirtIO ใน VM: `/dev/vda`

ชื่อข้างต้นเป็นตัวอย่าง ต้องใช้ชื่อที่ setup แสดงบนเครื่องของคุณจริง ตัวติดตั้งปฏิเสธดิสก์ที่กำลัง mount, ใช้เป็น swap, มี mapped/RAID device ที่กำลังใช้งาน, เป็น read-only, มีขนาดเล็กเกินไป หรือมีลักษณะเป็นสื่อ installer

กรอกตามลำดับ:

1. **Target disk**: พาธของดิสก์ทั้งลูก กด Enter เปล่าเพื่อยกเลิก
2. **Username**: ชื่อผู้ใช้ ค่าเริ่มต้น `dev` ใช้อักษรอังกฤษตัวเล็ก ตัวเลข `_` หรือ `-`
3. **Hostname**: ชื่อเครื่อง ค่าเริ่มต้น `dev-os`
4. **User password** และยืนยัน: อย่างน้อย 12 ตัวอักษร ใช้กับ login และ `sudo`
5. **Root password** และยืนยัน: อย่างน้อย 12 ตัวอักษร ใช้กับ `su -`

รหัสผ่านไม่แสดงบนหน้าจอและถูกเก็บเป็น salted SHA-512 crypt hash ในระบบที่ติดตั้ง

หน้าสรุปจะแสดงดิสก์ที่จะลบ ชื่อบัญชี และรูปแบบพาร์ติชัน ต้องพิมพ์ `ERASE` ตามด้วยพาธดิสก์ตรงตามที่แสดงจึงจะเริ่มติดตั้ง เช่น `ERASE /dev/nvme0n1` การพิมพ์ข้อความอื่นจะยกเลิกโดยไม่เริ่มเขียนดิสก์

หลังยืนยัน setup จะสร้าง:

- ตารางพาร์ติชัน GPT
- EFI System Partition แบบ FAT32 ขนาด 512 MiB
- พาร์ติชัน ext4 สำหรับ Dev OS ใช้พื้นที่ที่เหลือ
- บัญชีผู้ใช้ UID 1000 พร้อมสิทธิ์ sudo ผ่านกลุ่ม wheel
- GRUB UEFI bootloader ที่อ้างอิง filesystem ด้วย UUID และ kernel root ด้วย PARTUUID

การติดตั้งไม่มี rollback สำหรับข้อมูลเดิมหลังเริ่มแบ่งพาร์ติชัน หากถูกขัดจังหวะก่อนเสร็จ ดิสก์ปลายทางอาจมีระบบไม่ครบ

## 4. บูตระบบที่ติดตั้งแล้ว

รอข้อความ **INSTALLATION COMPLETE** ถอด USB installer แล้วรีบูตและเลือกดิสก์ปลายทางจาก UEFI boot menu

ตัวติดตั้งเขียน loader ไว้ที่ `EFI/BOOT/BOOTX64.EFI` และไม่แก้รายการ NVRAM boot ของ firmware หากเครื่องไม่เลือกดิสก์นี้อัตโนมัติ ให้เลือกดิสก์เอง หรือใช้เมนู Boot from EFI file ของ firmware เปิดไฟล์ดังกล่าว

Login ด้วยชื่อและรหัสผ่านที่ตั้งไว้ แล้วทดลอง:

```sh
sudo dev install /opt/hello-0.1.0.dpk
dev-hello
dev list
su -
```

การติดตั้งลงดิสก์จริงเก็บข้อมูลถาวร รวมถึงแพ็กเกจที่ติดตั้งและไฟล์ผู้ใช้หลัง reboot

## สร้าง ISO ใหม่จากซอร์ส

ใช้ Linux/WSL build ตาม `BUILDING.md` และติดตั้ง host tools สำหรับ ISO:

```sh
sudo apt-get install grub-pc-bin grub-efi-amd64-bin grub-common xorriso mtools fakeroot cpio ovmf
```

ใน Linux copy ของโปรเจกต์:

```sh
DEVOS_TEST_VM=1 sh scripts/configure.sh ~/src/dev-os-build/buildroot-2026.08
sh scripts/build.sh
fakeroot -- python3 scripts/build-installer.py
```

สำหรับ build tree เก่าที่เคยสร้างรุ่นก่อนมี installer ให้รัน `sh scripts/build.sh linux-reconfigure busybox-reconfigure util-linux-reconfigure dosfstools-reconfigure` หลัง configure แล้วค่อย build ทั้งระบบ เพื่อให้ตัวเลือกใหม่มีผล

แม้ build base image ด้วย test accounts ตัวสร้าง ISO จะนำบัญชีทดสอบออกและล็อก root ใน payload ก่อนบรรจุ บัญชีใช้งานจริงถูกสร้างใหม่ตอน setup

ทดสอบ end-to-end ด้วย `python3 scripts/test-installer.py --disk-type virtio` หรือ `nvme` หรือ `sata` สคริปต์ใช้ไฟล์ดิสก์ใหม่ภายใต้ `out/installer-tests/` และปฏิเสธการเขียนทับไฟล์ทดสอบที่มีอยู่แล้ว ไม่ส่ง physical disk ของ host เข้า VM

ทดสอบ USB เสมือนด้วย `python3 scripts/test-installer-usb.py` เมื่อทดสอบแล้ว ส่งออก ISO, checksum และผลทดสอบกลับ Windows ด้วย:

```sh
sh scripts/export-installer.sh /mnt/c/Users/ondev/Projects/dev-os
```
