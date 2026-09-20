"""Read-only identity checks for the installed A/B layout; no disk writes."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid


def canonical(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Invalid slot UUID')
    return value


def mountinfo(text):
    def unescape(value):
        return re.sub(r'\\(040|011|012|134)', lambda match: chr(int(match[1], 8)), value)
    result = []
    for line in text.splitlines():
        fields = line.split()
        try:
            split = fields.index('-')
            if split < 6 or len(fields) < split + 4 or not re.fullmatch(r'\d+:\d+', fields[2]):
                raise ValueError()
            result.append({'device': fields[2], 'root': unescape(fields[3]),
                           'target': unescape(fields[4]), 'options': fields[5].split(','),
                           'fstype': fields[split + 1], 'super_options': fields[split + 3].split(',')})
        except (ValueError, IndexError):
            raise ValueError('Malformed Linux mountinfo') from None
    return result


def validate(metadata, commandline, mounts, devices, swaps):
    """Validate one observation; caller must revalidate under deployment exclusion."""
    if metadata.get('version') != 1 or metadata.get('layout') != 'ab':
        raise ValueError('Unsupported system layout')
    active = metadata.get('slot')
    if active not in ('A', 'B') or metadata.get('shared_mounts') != ['/home']:
        raise ValueError('Unsupported slot/shared mount configuration')
    slots = [arg.split('=', 1)[1] for arg in commandline.split() if arg.startswith('devos.slot=')]
    roots = [arg.split('=', 1)[1] for arg in commandline.split() if arg.startswith('root=')]
    parts = metadata.get('partitions', {})
    names = ('efi', 'boot', 'A', 'B', 'home')
    if set(parts) != set(names) or slots != [active]:
        raise ValueError('Boot slot does not match installed layout')
    part_ids, fs_ids, selected = set(), set(), {}
    for number, name in enumerate(names, 1):
        part = parts[name]
        partuuid = canonical(part.get('partuuid'))
        if part.get('number') != number or partuuid in part_ids:
            raise ValueError('Duplicate or incorrect partition identity')
        part_ids.add(partuuid)
        matches = [entry for entry in devices if entry.get('partuuid') == partuuid]
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous partition: ' + name)
        entry = matches[0]
        expected_type = 'vfat' if name == 'efi' else 'ext4'
        if (entry.get('number') != number or entry.get('fstype') != expected_type or
                entry.get('read_only') or entry.get('holders') or not entry.get('parent')):
            raise ValueError('Partition is unsuitable for A/B servicing: ' + name)
        if name != 'efi':
            fsuuid = canonical(part.get('uuid'))
            if fsuuid in fs_ids or entry.get('uuid') != fsuuid:
                raise ValueError('Filesystem identity mismatch: ' + name)
            if sum(device.get('uuid') == fsuuid for device in devices) != 1:
                raise ValueError('Ambiguous filesystem UUID: ' + name)
            fs_ids.add(fsuuid)
        selected[name] = entry
    if len({entry['device'] for entry in selected.values()}) != 5 or len({entry['parent'] for entry in selected.values()}) != 1:
        raise ValueError('Slots must be distinct partitions of one disk')
    if roots != ['PARTUUID=' + parts[active]['partuuid']]:
        raise ValueError('Kernel root argument does not match active slot')
    for target, name in (('/', active), ('/boot', 'boot'), ('/boot/efi', 'efi'), ('/home', 'home')):
        found = [mount for mount in mounts if mount['target'] == target]
        if len(found) != 1:
            raise ValueError('Missing or overmounted system mount: ' + target)
        mount = found[0]
        if (mount['device'] != selected[name]['device'] or mount['root'] != '/' or
                mount['fstype'] != selected[name]['fstype'] or
                'rw' not in mount['options'] or 'rw' not in mount['super_options']):
            raise ValueError('Unexpected system mount: ' + target)
    inactive = 'B' if active == 'A' else 'A'
    device = selected[inactive]['device']
    if any(mount['device'] == device for mount in mounts) or device in swaps:
        raise ValueError('Inactive slot is already mounted or used as swap')
    return {'active': active, 'inactive': inactive, 'disk': selected[inactive]['parent'],
            'target': selected[inactive]['path'], 'device': device,
            'partuuid': parts[inactive]['partuuid'], 'uuid': parts[inactive]['uuid']}


def observe():
    """Read authoritative kernel/device state in the current mount namespace."""
    if os.name != 'posix' or os.geteuid() != 0:
        raise ValueError('Slot inspection requires Linux root')
    descriptor = os.open('/etc/devos-system.json', os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 65536:
            raise ValueError('Untrusted installed system metadata')
        metadata = json.loads(stream.read(65537))
    devices = []
    for path in Path('/sys/class/block').iterdir():
        if not (path / 'partition').exists(): continue
        properties = dict(line.split('=', 1) for line in (path / 'uevent').read_text().splitlines() if '=' in line)
        node = Path('/dev') / properties['DEVNAME']
        info = node.stat()
        device = (path / 'dev').read_text().strip()
        if not stat.S_ISBLK(info.st_mode) or device != f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}':
            raise ValueError('Device node does not match sysfs')
        probe = subprocess.run(['blkid', '-p', '-o', 'export', str(node)], capture_output=True, text=True, timeout=10)
        if probe.returncode not in (0, 2):
            raise ValueError('Ambiguous or failed block-device probe')
        values = dict(line.split('=', 1) for line in probe.stdout.splitlines() if '=' in line)
        devices.append({'path': str(node), 'device': device, 'parent': str(path.resolve().parent),
                        'number': int((path / 'partition').read_text()),
                        'partuuid': values.get('PART_ENTRY_UUID'), 'uuid': values.get('UUID'),
                        'fstype': values.get('TYPE'), 'read_only': (path / 'ro').read_text().strip() != '0',
                        'holders': bool(list((path / 'holders').iterdir()))})
    swaps = set()
    for line in Path('/proc/swaps').read_text().splitlines()[1:]:
        swap = Path(line.split()[0]).stat()
        number = swap.st_rdev if stat.S_ISBLK(swap.st_mode) else swap.st_dev
        swaps.add(f'{os.major(number)}:{os.minor(number)}')
    return validate(metadata, Path('/proc/cmdline').read_text(),
                    mountinfo(Path('/proc/self/mountinfo').read_text()), devices, swaps)


if __name__ == '__main__':
    print(json.dumps(observe(), indent=2))
