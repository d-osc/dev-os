"""Inspect base-system archives without extracting or executing their contents."""
import gzip
import hashlib
import json
import os
from pathlib import PurePosixPath
import tarfile
import tempfile

MAX_FILES = 100000
MAX_FILE = 512 * 1024**2
MAX_PAYLOAD = 2 * 1024**3
MAX_STREAM = MAX_PAYLOAD + 128 * 1024**2
REQUIRED = {'etc/passwd', 'etc/shadow', 'etc/fstab', 'bin/sh', 'sbin/init',
            'usr/bin/dev', 'usr/lib/devos/platform.json'}


class Header(tarfile.TarInfo):
    def _proc_member(self, archive):
        # Reject giant PAX/GNU extension records before stdlib allocates them.
        metadata = self.type in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE,
                                tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK)
        if self.size < 0 or self.size > (65536 if metadata else MAX_FILE):
            raise ValueError('Oversized rootfs tar member')
        if self.type == tarfile.GNUTYPE_SPARSE:
            raise ValueError('Sparse rootfs members are unsupported')
        return super()._proc_member(archive)


class Bounded:
    def __init__(self, stream):
        self.stream, self.total = stream, 0

    def read(self, size):
        if size < 0 or size > 1024**2:
            raise ValueError('Unbounded rootfs stream read')
        data = self.stream.read(size)
        self.total += len(data)
        if self.total > MAX_STREAM:
            raise ValueError('Expanded rootfs stream exceeds limit')
        return data


def name(value, *, root=False):
    if not isinstance(value, str) or '\x00' in value or '\\' in value or value.startswith('/'):
        raise ValueError('Invalid rootfs path')
    parts = PurePosixPath(value).parts
    if '..' in parts:
        raise ValueError('Rootfs path traversal')
    result = '/'.join(part for part in parts if part != '.')
    if not result and not root:
        raise ValueError('Empty rootfs path')
    if len(result) > 4096:
        raise ValueError('Rootfs path too long')
    return result


def link_target(path, link):
    if '\x00' in link or '\\' in link or len(link) > 4096 or not link:
        raise ValueError('Invalid rootfs link')
    parts = [] if link.startswith('/') else path.split('/')[:-1]
    for part in PurePosixPath(link).parts:
        if part in ('/', '.', ''):
            continue
        if part == '..':
            if not parts:
                raise ValueError('Rootfs link escapes target')
            parts.pop()
        else:
            parts.append(part)
    return '/'.join(parts)


def inspect(path, *, require_sanitized=True):
    inventory, contents = {}, {}
    total = 0
    with gzip.open(path, 'rb') as compressed:
        with tarfile.open(fileobj=Bounded(compressed), mode='r|', tarinfo=Header) as archive:
            for member in archive:
                relative = name(member.name, root=member.isdir())
                if not relative:
                    continue
                if relative in inventory or len(inventory) >= MAX_FILES:
                    raise ValueError('Duplicate or excessive rootfs members')
                if member.sparse is not None or any(key.startswith('GNU.sparse') for key in member.pax_headers):
                    raise ValueError('Sparse rootfs members are unsupported')
                if set(member.pax_headers) - {'path', 'linkpath', 'size', 'uid', 'gid',
                                              'uname', 'gname', 'mtime', 'atime', 'ctime'}:
                    raise ValueError('Unsupported rootfs extended metadata')
                if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise ValueError('Rootfs devices, sockets and FIFOs are not permitted')
                if not 0 <= member.mode <= 0o7777 or min(member.uid, member.gid) < 0:
                    raise ValueError('Invalid rootfs ownership or mode')
                if relative.split('/')[0] in ('bin', 'sbin', 'usr', 'lib', 'lib64', 'etc'):
                    if member.uid != 0 or (not member.issym() and member.mode & 0o022):
                        raise ValueError('System paths must be root-owned and not group/world writable')
                item = {'mode': member.mode, 'uid': member.uid, 'gid': member.gid,
                        'type': 'file' if member.isfile() else 'directory' if member.isdir() else
                                'symlink' if member.issym() else 'hardlink'}
                if member.issym():
                    item.update(link=member.linkname, target=link_target(relative, member.linkname))
                elif member.islnk():
                    item.update(link=member.linkname, target=name(member.linkname))
                elif member.isfile():
                    total += member.size
                    if not 0 <= member.size <= MAX_FILE or total > MAX_PAYLOAD:
                        raise ValueError('Expanded rootfs payload exceeds limit')
                    digest, length = hashlib.sha256(), 0
                    saved = bytearray() if relative in ('etc/passwd', 'etc/shadow', 'usr/lib/devos/platform.json') else None
                    stream = archive.extractfile(member)
                    while chunk := stream.read(65536):
                        digest.update(chunk); length += len(chunk)
                        if saved is not None:
                            if length > 65536: raise ValueError('Oversized rootfs identity metadata')
                            saved.extend(chunk)
                    if length != member.size: raise ValueError('Truncated rootfs file')
                    item.update(length=length, sha256=digest.hexdigest())
                    if saved is not None: contents[relative] = saved.decode('utf-8')
                inventory[relative] = item
    for path, item in inventory.items():
        for parent in PurePosixPath(path).parents:
            if parent.as_posix() == '.': continue
            if parent.as_posix() not in inventory or inventory[parent.as_posix()]['type'] != 'directory':
                raise ValueError('Rootfs member has a missing or non-directory parent: ' + path)
        if item['type'] == 'hardlink' and inventory.get(item['target'], {}).get('type') != 'file':
            raise ValueError('Rootfs hardlink must target a regular archive file')
        if item['type'] == 'hardlink' and any(item[key] != inventory[item['target']][key]
                                             for key in ('mode', 'uid', 'gid')):
            raise ValueError('Conflicting rootfs hardlink metadata')
    if not REQUIRED <= inventory.keys():
        raise ValueError('Rootfs is missing required system files')
    for metadata in ('etc/passwd', 'etc/shadow', 'etc/fstab', 'usr/lib/devos/platform.json'):
        if inventory[metadata]['type'] != 'file':
            raise ValueError('Rootfs identity/configuration metadata must be regular files')
    for executable in ('bin/sh', 'sbin/init', 'usr/bin/dev'):
        current, visited = executable, set()
        while inventory.get(current, {}).get('type') in ('symlink', 'hardlink'):
            if current in visited or len(visited) >= 40:
                raise ValueError('Rootfs executable link cycle')
            visited.add(current)
            current = inventory[current]['target']
        item = inventory.get(current, {})
        if item.get('type') != 'file' or not item['mode'] & 0o111:
            raise ValueError('Rootfs system executable is missing or not executable')
    if json.loads(contents.get('usr/lib/devos/platform.json', '{}')).get('arch') != 'x86_64':
        raise ValueError('Rootfs platform does not match x86_64')
    if require_sanitized:
        if any(path.startswith('home/') or path.startswith('var/lib/dev/') or path in (
                'etc/devos-install.json', 'etc/devos-system.json', 'etc/devos-live') for path in inventory):
            raise ValueError('Rootfs contains installation or user state')
        for line in contents.get('etc/passwd', '').splitlines():
            fields = line.split(':')
            if len(fields) != 7 or not fields[2].isdigit() or 1000 <= int(fields[2]) < 65534:
                raise ValueError('Rootfs contains invalid or personal accounts')
        shadow = contents.get('etc/shadow', '').splitlines()
        if not shadow or not any(line.startswith('root:') for line in shadow):
            raise ValueError('Rootfs is missing locked root account')
        for line in shadow:
            fields = line.split(':')
            if len(fields) != 9 or not fields[1].startswith(('!', '*')):
                raise ValueError('Release rootfs accounts must have locked passwords')
    return {'arch': 'x86_64', 'bytes': total, 'files': inventory}


def extract(path, destination, *, length, sha256):
    """Extract authenticated bytes to an empty, caller-isolated Linux directory.

    This is a staging primitive, not a device/slot authorization mechanism.
    A failed staging directory must never be booted or published. The caller
    must exclude concurrent writers and validate the inactive mount separately.
    """
    if os.name != 'posix' or os.geteuid() != 0:
        raise ValueError('Rootfs extraction requires Linux root')
    if type(length) is not int or not 0 < length <= 1024**3:
        raise ValueError('Invalid compressed rootfs length')
    if not isinstance(sha256, str) or len(sha256) != 64 or any(c not in '0123456789abcdef' for c in sha256):
        raise ValueError('Invalid rootfs digest')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root = os.open(destination, flags)
    try:
        status = os.fstat(root)
        if status.st_uid != 0 or status.st_mode & 0o022 or os.listdir(root):
            raise ValueError('Rootfs destination must be empty, root-owned and protected')

        def parent(relative):
            descriptor = os.dup(root)
            try:
                for part in relative.split('/')[:-1]:
                    child = os.open(part, flags, dir_fd=descriptor)
                    os.close(descriptor)
                    descriptor = child
                return descriptor
            except BaseException:
                os.close(descriptor)
                raise

        # A private, bounded snapshot binds inspection and extraction to the
        # exact same authenticated bytes even if the download path is replaced.
        with tempfile.TemporaryFile() as snapshot:
            digest, copied = hashlib.sha256(), 0
            with open(path, 'rb') as source:
                while chunk := source.read(min(65536, length - copied + 1)):
                    copied += len(chunk)
                    if copied > length: raise ValueError('Rootfs length mismatch')
                    digest.update(chunk)
                    snapshot.write(chunk)
            if copied != length or digest.hexdigest() != sha256:
                raise ValueError('Rootfs authentication mismatch')
            snapshot.seek(0)
            result = inspect(snapshot)
            inventory = result['files']
            for relative, item in sorted(inventory.items(), key=lambda pair: pair[0].count('/')):
                if item['type'] != 'directory': continue
                fd = parent(relative)
                try: os.mkdir(relative.split('/')[-1], 0o700, dir_fd=fd)
                finally: os.close(fd)
            snapshot.seek(0)
            with gzip.GzipFile(fileobj=snapshot) as compressed:
                with tarfile.open(fileobj=Bounded(compressed), mode='r|', tarinfo=Header) as archive:
                    for member in archive:
                        if not member.isfile(): continue
                        relative = name(member.name)
                        item = inventory[relative]
                        fd = parent(relative)
                        try:
                            output = os.open(relative.split('/')[-1], os.O_WRONLY | os.O_CREAT |
                                             os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                            with os.fdopen(output, 'wb') as stream:
                                source = archive.extractfile(member)
                                digest = hashlib.sha256()
                                while chunk := source.read(65536):
                                    stream.write(chunk); digest.update(chunk)
                                if stream.tell() != item['length'] or digest.hexdigest() != item['sha256']:
                                    raise ValueError('Rootfs extraction integrity mismatch')
                                stream.flush()
                                os.fchown(stream.fileno(), item['uid'], item['gid'])
                                os.fchmod(stream.fileno(), item['mode'])
                                os.fsync(stream.fileno())
                        finally: os.close(fd)
            # Never traverse archive symlinks: links are created after all data.
            for relative, item in inventory.items():
                if item['type'] not in ('symlink', 'hardlink'): continue
                fd = parent(relative)
                try:
                    leaf = relative.split('/')[-1]
                    if item['type'] == 'symlink':
                        os.symlink(item['link'], leaf, dir_fd=fd)
                        os.chown(leaf, item['uid'], item['gid'], dir_fd=fd, follow_symlinks=False)
                    else:
                        source_fd = parent(item['target'])
                        try:
                            os.link(item['target'].split('/')[-1], leaf, src_dir_fd=source_fd,
                                    dst_dir_fd=fd, follow_symlinks=False)
                        finally: os.close(source_fd)
                finally: os.close(fd)
            for relative, item in sorted(inventory.items(), key=lambda pair: -pair[0].count('/')):
                if item['type'] != 'directory': continue
                fd = parent(relative)
                try:
                    child = os.open(relative.split('/')[-1], flags, dir_fd=fd)
                    try:
                        os.fchown(child, item['uid'], item['gid'])
                        os.fchmod(child, item['mode'])
                        os.fsync(child)
                    finally: os.close(child)
                finally: os.close(fd)
            os.fsync(root)
            return result
    finally:
        os.close(root)
