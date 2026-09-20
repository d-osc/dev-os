"""Three-way /etc preservation planning. No writes or implicit conflict resolution."""
import hashlib
import os
from pathlib import PurePosixPath
import stat


def snapshot(root):
    """Read /etc through no-follow directory descriptors in a quiesced root.

    The caller must exclude concurrent configuration writers. A detected race
    aborts, but this is not a filesystem snapshot or service freeze.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(root, flags)
    result = {}
    total = 0

    def visit(parent, leaf, relative):
        nonlocal total
        before = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        item = {'mode': stat.S_IMODE(before.st_mode), 'uid': before.st_uid, 'gid': before.st_gid}
        if stat.S_ISLNK(before.st_mode):
            item.update(type='symlink', link=os.readlink(leaf, dir_fd=parent))
        elif stat.S_ISDIR(before.st_mode):
            item['type'] = 'directory'
            child = os.open(leaf, flags, dir_fd=parent)
            try:
                if os.fstat(child).st_ino != before.st_ino or os.fstat(child).st_dev != before.st_dev:
                    raise ValueError('Configuration changed during snapshot')
                for name in sorted(os.listdir(child)):
                    visit(child, name, relative + '/' + name)
            finally: os.close(child)
        elif stat.S_ISREG(before.st_mode):
            if before.st_nlink != 1:
                raise ValueError('Hardlinked configuration needs explicit migration')
            if before.st_size > 16 * 1024**2:
                raise ValueError('Configuration file exceeds snapshot limit')
            child = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(child, 'rb') as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise ValueError('Configuration changed during snapshot')
                digest, length = hashlib.sha256(), 0
                while chunk := stream.read(65536):
                    length += len(chunk); total += len(chunk)
                    if length > 16 * 1024**2 or total > 128 * 1024**2:
                        raise ValueError('Configuration snapshot exceeds limit')
                    digest.update(chunk)
                item.update(type='file', length=length, sha256=digest.hexdigest())
        else:
            raise ValueError('Unsupported special configuration file')
        after = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        if any(getattr(before, key) != getattr(after, key) for key in
               ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_size', 'st_mtime_ns', 'st_ctime_ns')):
            raise ValueError('Configuration changed during snapshot')
        result[relative] = item
        if len(result) > 10000: raise ValueError('Too many configuration entries')
    try: visit(descriptor, 'etc', 'etc')
    finally: os.close(descriptor)
    return result


def config_inventory(inventory):
    """Convert an inspected release inventory to the comparable /etc subset."""
    result = {}
    for path, value in inventory.items():
        if path != 'etc' and not path.startswith('etc/'): continue
        item = {key: value[key] for key in ('type', 'mode', 'uid', 'gid')}
        if item['type'] == 'file':
            item.update(length=value['length'], sha256=value['sha256'])
        elif item['type'] == 'symlink':
            item['link'] = value['link']
        elif item['type'] != 'directory':
            raise ValueError('Hardlinked configuration needs explicit migration')
        result[path] = item
    return result


def plan(base, current, incoming):
    """Select unchanged upstream defaults and retain local edits/deletions.

    Inputs must derive from authenticated base/new images and a stable current
    snapshot. Missing baseline is an error, never an invitation to overwrite.
    Results contain hashes, not config contents; do not expose shadow hashes.
    """
    for inventory in (base, current, incoming):
        if not isinstance(inventory, dict) or inventory.get('etc', {}).get('type') != 'directory':
            raise ValueError('A complete baseline/current/incoming /etc inventory is required')
        for path, item in inventory.items():
            parts = PurePosixPath(path).parts
            if not parts or parts[0] != 'etc' or '..' in parts or '\\' in path or '\x00' in path or str(PurePosixPath(path)) != path:
                raise ValueError('Invalid configuration path')
            if item.get('type') not in ('file', 'directory', 'symlink'):
                raise ValueError('Unsupported configuration type')
            for parent in PurePosixPath(path).parents:
                if str(parent) == '.': continue
                if inventory.get(str(parent), {}).get('type') != 'directory':
                    raise ValueError('Missing or non-directory configuration parent')
    selected, conflicts = {}, []
    for path in sorted(base.keys() | current.keys() | incoming.keys()):
        old, local, new = base.get(path), current.get(path), incoming.get(path)
        if local == old:
            source, item = 'incoming', new
        elif new == old or local == new:
            source, item = 'current', local
        else:
            conflicts.append({'path': path, 'reason': 'Both local configuration and upstream changed'})
            continue
        selected[path] = {'source': source if item is not None else 'delete', 'item': item}
    for path, choice in selected.items():
        if choice['item'] is None: continue
        for parent in PurePosixPath(path).parents:
            if str(parent) == '.': continue
            parent_item = selected.get(str(parent), {}).get('item')
            if not parent_item or parent_item['type'] != 'directory':
                conflicts.append({'path': path, 'reason': 'Merged parent is absent, conflicting or not a directory'})
                break
    # No partial plan may be applied when any conflict exists.
    return {'ready': not conflicts, 'entries': selected if not conflicts else {}, 'conflicts': conflicts}


def _directory_flags():
    # POSIX-only flags, resolved lazily so importing on other hosts stays safe.
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


_FORMATS = {'file': stat.S_IFREG, 'directory': stat.S_IFDIR, 'symlink': stat.S_IFLNK}


def _directory(descriptor, relative):
    """Open a no-follow chain of existing directories below a root descriptor."""
    current = os.dup(descriptor)
    try:
        for part in PurePosixPath(relative).parts:
            if part in ('.', ''): continue
            nxt = os.open(part, _directory_flags(), dir_fd=current)
            os.close(current)
            current = nxt
        return current
    except Exception:
        os.close(current)
        raise


def _identity(leaf, parent, item):
    """Stat one entry without following it and compare it with a planned item."""
    status = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
    if (stat.S_IFMT(status.st_mode) != _FORMATS[item['type']] or
            stat.S_IMODE(status.st_mode) != item['mode'] or
            (status.st_uid, status.st_gid) != (item['uid'], item['gid'])):
        raise ValueError('Configuration changed after snapshot')
    return status


def _read_current(root, relative, item):
    """Read the retained local bytes for one planned entry, re-verifying them.

    Directories and symlinks carry no payload; their link text is checked here
    and written from the plan item itself.
    """
    parent = _directory(root, PurePosixPath(relative).parent)
    try:
        leaf = PurePosixPath(relative).name
        _identity(leaf, parent, item)
        if item['type'] == 'symlink':
            if os.readlink(leaf, dir_fd=parent) != item['link']:
                raise ValueError('Configuration changed after snapshot')
            return None
        if item['type'] == 'directory': return None
        child = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(child, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            before = _identity(leaf, parent, item)
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError('Configuration changed during apply')
            payload = stream.read(16 * 1024**2 + 1)
        if len(payload) != item['length'] or hashlib.sha256(payload).hexdigest() != item['sha256']:
            raise ValueError('Configuration changed after snapshot')
        _identity(leaf, parent, item)
        return payload
    finally:
        os.close(parent)


def _clear_directory_leaf(leaf, parent):
    """Remove only a directory occupying a non-directory destination, if any."""
    try:
        status = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISDIR(status.st_mode): os.rmdir(leaf, dir_fd=parent)


def _write_staged(root, relative, item, payload):
    """Publish one planned entry into the staged tree through a temporary name."""
    parent = _directory(root, PurePosixPath(relative).parent)
    try:
        leaf = PurePosixPath(relative).name
        temporary = '.' + leaf + '.devos-apply'
        if item['type'] == 'directory':
            try:
                os.mkdir(leaf, item['mode'], dir_fd=parent)
            except FileExistsError:
                # A kept staged directory survives with its children; anything
                # else at the path is replaced by the planned directory.
                if not stat.S_ISDIR(os.stat(leaf, dir_fd=parent, follow_symlinks=False).st_mode):
                    os.unlink(leaf, dir_fd=parent)
                    os.mkdir(leaf, item['mode'], dir_fd=parent)
        elif item['type'] == 'symlink':
            os.symlink(item['link'], temporary, dir_fd=parent)
            os.chown(temporary, item['uid'], item['gid'], dir_fd=parent, follow_symlinks=False)
            _clear_directory_leaf(leaf, parent)
            os.rename(temporary, leaf, src_dir_fd=parent, dst_dir_fd=parent)
        else:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), item['mode'])
                os.fchown(stream.fileno(), item['uid'], item['gid'])
            _clear_directory_leaf(leaf, parent)
            os.rename(temporary, leaf, src_dir_fd=parent, dst_dir_fd=parent)
        if item['type'] != 'symlink':
            os.chmod(leaf, item['mode'], dir_fd=parent)
        os.chown(leaf, item['uid'], item['gid'], dir_fd=parent, follow_symlinks=False)
        os.fsync(parent)
    finally:
        os.close(parent)


def _remove_staged(root, relative):
    parent = _directory(root, PurePosixPath(relative).parent)
    try:
        leaf = PurePosixPath(relative).name
        if stat.S_ISDIR(os.stat(leaf, dir_fd=parent, follow_symlinks=False).st_mode):
            os.rmdir(leaf, dir_fd=parent)
        else:
            os.unlink(leaf, dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(parent)


def apply(current_root, staged_root, base, current, incoming):
    """Write a ready preservation plan into a freshly extracted staged root.

    current_root supplies the retained local bytes and is re-verified per entry,
    so a stale snapshot is refused instead of copied. staged_root must exactly
    equal the incoming inventory before anything is modified, and the applied
    result is re-snapshotted against the merged plan before returning. The
    caller must quiesce both trees and discard, never publish or boot, a staged
    root left behind by a failure: this is a staging step, not a transaction.
    """
    result = plan(base, current, incoming)
    if not result['ready']:
        raise ValueError('Configuration conflicts: ' +
                         ', '.join(conflict['path'] for conflict in result['conflicts']))
    current_fd = os.open(current_root, _directory_flags())
    try:
        staged_fd = os.open(staged_root, _directory_flags())
        try:
            if snapshot(staged_root) != incoming:
                raise ValueError('Staged configuration does not match the incoming release inventory')
            copied = 0
            # Deletions run first, children before parents, so a changed entry
            # type never renames over a populated directory. Entries absent
            # from the incoming release need no staged removal.
            for path in sorted(result['entries'], reverse=True):
                if result['entries'][path]['item'] is None and incoming.get(path) is not None:
                    _remove_staged(staged_fd, path)
            for path, choice in sorted(result['entries'].items()):
                item = choice['item']
                if item is None or choice['source'] == 'incoming': continue
                payload = _read_current(current_fd, path, item)
                if item['type'] == 'file':
                    copied += item['length']
                    if copied > 128 * 1024**2: raise ValueError('Configuration apply exceeds copy limit')
                _write_staged(staged_fd, path, item, payload)
            merged = {path: choice['item'] for path, choice in result['entries'].items()
                      if choice['item'] is not None}
            if snapshot(staged_root) != merged:
                raise ValueError('Applied configuration does not match the merged plan')
            return merged
        finally:
            os.close(staged_fd)
    finally:
        os.close(current_fd)
