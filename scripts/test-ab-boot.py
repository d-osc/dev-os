#!/usr/bin/env python3
"""Exercise the A/B boot policy through real UEFI GRUB on a disposable GPT disk."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

import pexpect

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'tools'))
import dev_boot


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=PROJECT / 'out/test-results/ab-boot.json')
    args = parser.parse_args()
    report = {'passed': False, 'checks': [], 'base_image_sha256': digest(args.images / 'rootfs.ext4'),
              'boot_policy_sha256': digest(PROJECT / 'tools/dev_boot.py'),
              'method': 'UEFI/GRUB ISO bootstrap; separate writable GPT boot and two root partitions'}
    vm = None
    stage = 'prepare'
    try:
        accounts = json.loads(args.credentials.read_text())
        with tempfile.TemporaryDirectory(prefix='devos-ab-boot-') as directory:
            temporary = Path(directory)
            boot_uuid = str(uuid.uuid4())
            roots = {slot: str(uuid.uuid4()) for slot in ('A', 'B')}
            tree = temporary / 'boot-tree'; tree.mkdir()
            for slot in roots:
                (tree / 'devos' / slot).mkdir(parents=True)
                shutil.copyfile(args.images / 'bzImage', tree / 'devos' / slot / 'vmlinuz')
            dev_boot.publish_config(tree, boot_uuid, roots, 'A', serial=True)
            dev_boot.environment(tree, initialize=True)
            (tree / 'grub/confirmed-B.cfg').write_text(dev_boot.render(boot_uuid, roots, 'B', serial=True))
            boot_image = temporary / 'boot.ext4'
            with boot_image.open('wb') as stream: stream.truncate(128 * 1024**2)
            run('mkfs.ext4', '-q', '-F', '-U', boot_uuid, '-d', str(tree), str(boot_image))
            size = (args.images / 'rootfs.ext4').stat().st_size
            assert size % 1024**2 == 0
            root_mib = size // 1024**2
            disk = temporary / 'ab.raw'
            with disk.open('wb') as stream: stream.truncate((131 + 2 * root_mib) * 1024**2)
            layout = ('label: gpt\nstart=1MiB,size=128MiB,type=L\n'
                      f'start=129MiB,size={root_mib}MiB,type=L,uuid={roots["A"]}\n'
                      f'start={129 + root_mib}MiB,size={root_mib}MiB,type=L,uuid={roots["B"]}\n')
            run('sfdisk', str(disk), input=layout.encode())
            for source, offset in ((boot_image, 1), (args.images / 'rootfs.ext4', 129),
                                   (args.images / 'rootfs.ext4', 129 + root_mib)):
                run('dd', 'if=' + str(source), 'of=' + str(disk), 'bs=1M', 'seek=' + str(offset),
                    'conv=notrunc,sparse', 'status=none')
            iso_tree = temporary / 'iso/boot/grub'; iso_tree.mkdir(parents=True)
            (iso_tree / 'grub.cfg').write_text('serial --unit=0 --speed=115200\n'
                'terminal_input console serial\nterminal_output console serial\n'
                f'search --no-floppy --fs-uuid --set=bootdisk {boot_uuid}\n'
                'configfile ($bootdisk)/grub/grub.cfg\n')
            iso = temporary / 'bootstrap.iso'
            run('grub-mkrescue', '-o', str(iso), str(temporary / 'iso'))
            firmware = temporary / 'OVMF_VARS.fd'
            shutil.copyfile('/usr/share/OVMF/OVMF_VARS_4M.fd', firmware)

            def launch(expected):
                nonlocal vm, stage
                stage = 'boot slot ' + expected
                vm = pexpect.spawn('qemu-system-x86_64', [
                    '-accel', 'kvm', '-machine', 'q35', '-m', '512', '-smp', '2', '-nographic', '-no-reboot',
                    '-drive', 'if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd',
                    '-drive', f'if=pflash,format=raw,file={firmware}',
                    '-drive', f'file={disk},format=raw,if=virtio', '-cdrom', str(iso),
                    '-boot', 'order=d', '-nic', 'none'], encoding='utf-8', timeout=120, dimensions=(30, 160))
                try:
                    vm.expect_exact('dev-os login:')
                except Exception:
                    # This buffer precedes all authentication; safe for boot diagnostics.
                    report['boot_diagnostic'] = vm.before[-4000:]
                    raise
                vm.sendline('dev')
                vm.expect_exact('Password:'); vm.sendline(accounts['dev'])
                vm.expect_exact('dev@dev-os:~$ ')
                vm.sendline('su -'); vm.expect_exact('Password:'); vm.sendline(accounts['root'])
                vm.expect_exact('root@dev-os:~# ')
                command("grep -q 'devos.slot=" + expected + "' /proc/cmdline")
                command('test -d /sys/firmware/efi; mkdir -p /mnt/boot; mount /dev/vda1 /mnt/boot')

            def command(value):
                vm.sendline(value + "; printf '\\nAB_RC=%s\\n' \"$?\"")
                vm.expect(r'\r+\nAB_RC=(\d+)\r+\n')
                result = vm.before
                assert int(vm.match.group(1)) == 0, value + ': ' + result
                vm.expect_exact('root@dev-os:~# ')

            def shutdown():
                nonlocal vm
                command('sync')
                vm.sendline('reboot')
                vm.expect(pexpect.EOF)
                vm.close(); vm = None

            def passed(label):
                report['checks'].append(label)
                print('PASS ' + label, flush=True)

            launch('A'); passed('confirmed slot A boots via UEFI GRUB')
            command('grub-editenv /mnt/boot/grub/devos.env set next_entry=devos-B')
            shutdown()
            launch('B')
            command("test -z \"$(grub-editenv /mnt/boot/grub/devos.env list | grep '^next_entry=devos-')\"")
            passed('trial B boots and its marker is consumed before Linux')
            shutdown()
            launch('A'); passed('unconfirmed B returns to A on next boot')
            command('mv /mnt/boot/devos/B/vmlinuz /mnt/boot/devos/B/saved-kernel')
            command('grub-editenv /mnt/boot/grub/devos.env set next_entry=devos-B')
            shutdown()
            launch('A'); passed('missing trial kernel falls back to confirmed A')
            command('mv /mnt/boot/devos/B/saved-kernel /mnt/boot/devos/B/vmlinuz')
            command('grub-editenv /mnt/boot/grub/devos.env set next_entry=devos-B')
            shutdown()
            launch('B')
            command('cp /mnt/boot/grub/confirmed-B.cfg /mnt/boot/grub/confirm.tmp; sync; '
                    'mv /mnt/boot/grub/confirm.tmp /mnt/boot/grub/grub.cfg; sync')
            shutdown()
            launch('B'); passed('explicitly confirmed B remains the default')
            command("printf 'corrupt-environment' > /mnt/boot/grub/devos.env")
            shutdown()
            launch('B'); passed('corrupt environment retains confirmed B')
            shutdown()
            report['passed'] = True
    except Exception as exc:
        report['failure'] = {'stage': stage, 'type': type(exc).__name__}
    finally:
        if vm is not None: vm.close(force=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
