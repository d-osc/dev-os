import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('notifications_test', Path(__file__).parents[1] / 'tools/dev_notifications.py')
notifications = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notifications)


class Notifications(unittest.TestCase):
    def test_unicode_text(self):
        self.assertEqual(notifications.validate({'title': 'เสร็จแล้ว', 'body': 'งานเสร็จแล้ว'}),
                         ('เสร็จแล้ว', 'งานเสร็จแล้ว', 'normal'))

    def test_invalid_requests_are_rejected(self):
        for request in ([], {}, {'title': 'x' * 81}, {'title': 'x', 'body': 'x' * 513},
                        {'title': 'x', 'actions': ['shell']}, {'title': 'x', 'urgency': 'root'},
                        {'title': 'x\0'}, {'title': '\ud800'}):
            with self.subTest(request=request), self.assertRaises((ValueError, UnicodeError)):
                notifications.validate(request)

    @unittest.skipIf(os.name == 'nt', 'POSIX file locks')
    def test_rate_limit_survives_broker_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rate'
            with mock.patch.object(notifications.time, 'monotonic', return_value=100):
                notifications.reserve(path)
                with self.assertRaisesRegex(ValueError, 'rate limit'):
                    notifications.reserve(path)
            with mock.patch.object(notifications.time, 'monotonic', return_value=106):
                notifications.reserve(path)

    def test_client_requires_permission_endpoint(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'permission'):
                notifications.send('Test')

    def test_body_markup_is_escaped_and_no_actions_are_forwarded(self):
        backend = object.__new__(notifications.DesktopBackend)
        backend.markup = True
        with mock.patch.object(backend, 'call', return_value='(uint32 42,)\n') as call:
            result = backend.notify('package-id', {'title': 'Title', 'body': '<a href="file:///x">hello</a>'})
        self.assertEqual(result, {'ok': True, 'id': 42})
        args = call.call_args.args
        self.assertIn('&lt;a', args[5])
        self.assertEqual(args[6], '[]')
        self.assertEqual(args[-1], '5000')

    def test_backend_failure_is_not_reported_as_success(self):
        backend = object.__new__(notifications.DesktopBackend)
        backend.markup = False
        with mock.patch.object(backend, 'call', return_value='invalid reply'):
            with self.assertRaisesRegex(ValueError, 'Unexpected'):
                backend.notify('app', {'title': 'Hello'})


if __name__ == '__main__':
    unittest.main()
