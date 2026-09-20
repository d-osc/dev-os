import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('dev_config', Path(__file__).parents[1] / 'tools/dev_config.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


def file(value, mode=0o644):
    return {'type': 'file', 'mode': mode, 'uid': 0, 'gid': 0,
            'length': len(value), 'sha256': hashlib.sha256(value.encode()).hexdigest()}


class Config(unittest.TestCase):
    def setUp(self):
        self.base = {'etc': {'type': 'directory', 'mode': 0o755, 'uid': 0, 'gid': 0},
                     'etc/config': file('original')}

    def test_upstream_change_applies_only_to_unmodified_local_file(self):
        new = dict(self.base, **{'etc/config': file('updated')})
        result = config.plan(self.base, self.base, new)
        self.assertTrue(result['ready'])
        self.assertEqual(result['entries']['etc/config']['source'], 'incoming')

    def test_local_change_mode_and_deletion_survive_unchanged_upstream(self):
        for item in (file('local'), file('original', 0o600), None):
            local = dict(self.base)
            if item is None: del local['etc/config']
            else: local['etc/config'] = item
            result = config.plan(self.base, local, self.base)
            self.assertTrue(result['ready'])
            self.assertEqual(result['entries']['etc/config']['item'], item)

    def test_both_changed_or_upstream_deleted_local_edit_are_conflicts(self):
        local = dict(self.base, **{'etc/config': file('local')})
        for new in (dict(self.base, **{'etc/config': file('upstream')}), {'etc': self.base['etc']}):
            result = config.plan(self.base, local, new)
            self.assertFalse(result['ready'])
            self.assertEqual(result['entries'], {})
            self.assertEqual(result['conflicts'][0]['path'], 'etc/config')

    def test_same_edits_and_local_additions_are_preserved(self):
        local = dict(self.base, **{'etc/config': file('same'), 'etc/local': file('private')})
        new = dict(self.base, **{'etc/config': file('same')})
        result = config.plan(self.base, local, new)
        self.assertTrue(result['ready'])
        self.assertEqual(result['entries']['etc/local']['source'], 'current')

    def test_parent_removal_cannot_discard_local_children(self):
        base = dict(self.base, **{'etc/sub': self.base['etc']})
        local = dict(base, **{'etc/sub/local': file('keep')})
        result = config.plan(base, local, self.base)
        self.assertFalse(result['ready'])
        self.assertEqual(result['entries'], {})

    def test_no_baseline_or_invalid_parent_is_rejected(self):
        with self.assertRaises(ValueError): config.plan({}, self.base, self.base)
        local = dict(self.base, **{'etc/config/child': file('x')})
        with self.assertRaises(ValueError): config.plan(self.base, local, self.base)

    @unittest.skipUnless(os.name == 'posix', 'Linux filesystem semantics')
    def test_snapshot_does_not_follow_symlinks_and_preserves_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'etc').mkdir()
            (root / 'etc/config').write_text('local'); (root / 'etc/config').chmod(0o600)
            (root / 'etc/link').symlink_to('/outside/private')
            result = config.snapshot(root)
            self.assertEqual(result['etc/link']['link'], '/outside/private')
            self.assertEqual(result['etc/config']['sha256'], file('local')['sha256'])
            self.assertEqual(result['etc/config']['mode'], 0o600)
            os.link(root / 'etc/config', root / 'etc/alias')
            with self.assertRaisesRegex(ValueError, 'Hardlinked'): config.snapshot(root)


def build_world(directory):
    """Three real /etc trees: unchanged base, locally edited current, new incoming."""
    base, current, incoming = directory / 'base', directory / 'current', directory / 'incoming'
    for root in (base, current, incoming):
        (root / 'etc/sub').mkdir(parents=True)
        (root / 'etc/sub/file').write_text('sub-content')
    for root, text in ((base, 'original'), (current, 'original'), (incoming, 'updated')):
        (root / 'etc/config').write_text(text)
    for root in (base, incoming):
        (root / 'etc/link').symlink_to('/old-target')
        (root / 'etc/keep').write_text('same')
    (current / 'etc/link').symlink_to('/new-target')
    (current / 'etc/keep').write_text('same'); (current / 'etc/keep').chmod(0o600)
    (current / 'etc/local').write_text('private')
    (base / 'etc/upstream-deleted').write_text('old')
    (incoming / 'etc/new-upstream').write_text('fresh')
    return base, current, incoming


class Apply(unittest.TestCase):
    def setUp(self):
        self.base = {'etc': {'type': 'directory', 'mode': 0o755, 'uid': 0, 'gid': 0},
                     'etc/config': file('original')}

    def test_apply_rejects_conflicting_plan_before_touching_staged(self):
        local = dict(self.base, **{'etc/config': file('local')})
        incoming = dict(self.base, **{'etc/config': file('upstream')})
        with tempfile.TemporaryDirectory() as directory:
            staged = Path(directory) / 'staged'; staged.mkdir()
            with self.assertRaisesRegex(ValueError, 'Configuration conflicts'):
                config.apply(Path(directory), staged, self.base, local, incoming)
            self.assertEqual(list(staged.iterdir()), [])

    @unittest.skipUnless(os.name == 'posix', 'Linux filesystem semantics')
    def test_apply_preserves_local_edits_and_upstream_updates(self):
        import shutil
        import stat
        with tempfile.TemporaryDirectory() as directory:
            base, current, incoming = build_world(Path(directory))
            staged = Path(directory) / 'staged'
            shutil.copytree(incoming, staged, symlinks=True)
            merged = config.apply(current, staged, config.snapshot(base),
                                  config.snapshot(current), config.snapshot(incoming))
            self.assertEqual((staged / 'etc/config').read_text(), 'updated')
            self.assertEqual((staged / 'etc/keep').read_text(), 'same')
            self.assertEqual(stat.S_IMODE((staged / 'etc/keep').stat().st_mode), 0o600)
            self.assertEqual(os.readlink(staged / 'etc/link'), '/new-target')
            self.assertEqual((staged / 'etc/local').read_text(), 'private')
            self.assertEqual((staged / 'etc/sub/file').read_text(), 'sub-content')
            self.assertEqual((staged / 'etc/new-upstream').read_text(), 'fresh')
            self.assertFalse((staged / 'etc/upstream-deleted').exists())
            self.assertEqual(config.snapshot(staged), merged)

    @unittest.skipUnless(os.name == 'posix', 'Linux filesystem semantics')
    def test_apply_refuses_when_staged_tree_differs_from_incoming(self):
        import shutil
        import stat
        with tempfile.TemporaryDirectory() as directory:
            base, current, incoming = build_world(Path(directory))
            staged = Path(directory) / 'staged'
            shutil.copytree(incoming, staged, symlinks=True)
            (staged / 'etc/config').write_text('tampered')
            with self.assertRaisesRegex(ValueError, 'does not match the incoming'):
                config.apply(current, staged, config.snapshot(base),
                             config.snapshot(current), config.snapshot(incoming))
            self.assertEqual((staged / 'etc/config').read_text(), 'tampered')
            self.assertEqual(stat.S_IMODE((staged / 'etc/keep').stat().st_mode), 0o644)
            self.assertFalse((staged / 'etc/local').exists())

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'Linux root')
    def test_apply_restores_planned_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, current, staged = root / 'base', root / 'current', root / 'staged'
            for tree in (base, current, staged): (tree / 'etc').mkdir(parents=True)
            (base / 'etc/file').write_text('original')
            (current / 'etc/file').write_text('local')
            (staged / 'etc/file').write_text('original')
            os.chown(current / 'etc/file', 0, 0, follow_symlinks=False)
            config.apply(current, staged, config.snapshot(base),
                         config.snapshot(current), config.snapshot(staged))
            status = (staged / 'etc/file').stat()
            self.assertEqual((status.st_uid, status.st_gid), (0, 0))
