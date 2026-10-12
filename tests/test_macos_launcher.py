from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import macos_launcher as launcher


class MacLauncherTests(unittest.TestCase):
    def test_only_unprivileged_finder_launch_requests_authorization(self):
        self.assertTrue(launcher.needs_authorization('darwin', True, False, 501))
        for values in [('darwin', True, False, 0), ('darwin', True, True, 501),
                       ('darwin', False, False, 501), ('win32', True, False, 501)]:
            self.assertFalse(launcher.needs_authorization(*values))

    def test_system_authorization_cancel_has_no_password_handling(self):
        result = MagicMock(returncode=1, stderr='execution error: User canceled. (-128)')
        with patch.object(launcher.subprocess, 'run', return_value=result) as run:
            with self.assertRaises(launcher.AuthorizationCancelled):
                launcher.authorize('/path/GeoPortLite')
        self.assertIn('with administrator privileges', run.call_args.kwargs['input'])
        self.assertNotIn('password', run.call_args.kwargs['input'])

    def test_authorization_failure_is_distinct_from_cancel(self):
        with patch.object(launcher.subprocess, 'run', return_value=MagicMock(returncode=1, stderr='error')):
            with self.assertRaisesRegex(RuntimeError, 'authorization failed'):
                launcher.authorize('/path/GeoPortLite')

    def test_cancel_does_not_open_browser_or_wait_for_server(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(launcher.Path, 'home', return_value=Path(directory)), \
             patch.object(launcher, 'health', return_value={}) as health, \
             patch.object(launcher, 'available_port', return_value=54321), \
             patch.object(launcher, 'authorize', side_effect=launcher.AuthorizationCancelled()), \
             patch.object(launcher.webbrowser, 'open') as browser:
            with self.assertRaises(launcher.AuthorizationCancelled):
                launcher.launch('/App/GeoPortLite', [], Path(directory) / 'config')
        health.assert_called_once()
        browser.assert_not_called()

    def test_browser_waits_for_matching_privileged_instance_and_preserves_user_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config ' with spaces"
            executable = Path(directory) / "App ' with spaces/GeoPortLite"
            with patch.object(launcher.Path, 'home', return_value=Path(directory)), \
                 patch.object(launcher, 'available_port', return_value=54322), \
                 patch.object(launcher.uuid, 'uuid4', return_value=MagicMock(hex='unique')), \
                 patch.object(launcher, 'health', side_effect=[{},
                     {'launch_id': 'other', 'administrator': True},
                     {'launch_id': 'unique', 'administrator': False},
                     {'launch_id': 'unique', 'administrator': True}]), \
                 patch.object(launcher, 'authorize') as authorize, \
                 patch.object(launcher.time, 'sleep'), \
                 patch.object(launcher.webbrowser, 'open') as browser:
                launcher.launch(executable, ['--ui-mode', 'lite'], config)
            command = shlex.split(authorize.call_args.args[0])
            self.assertIn(str(executable.resolve()), command)
            self.assertIn(f'GEOPORT_CONFIG_DIR={config.resolve()}', command)
            self.assertIn(f'SUDO_UID={launcher.os.getuid()}', command)
            self.assertIn('--no-browser', command)
            browser.assert_called_once_with('http://127.0.0.1:54322/')

    def test_existing_privileged_geoport_reuses_browser_without_authorization(self):
        with patch.object(launcher, 'health', return_value={'app': 'GeoPort', 'administrator': True}), \
             patch.object(launcher, 'authorize') as authorize, \
             patch.object(launcher.webbrowser, 'open') as browser:
            launcher.launch('/App/GeoPortLite', [], '/unused/config')
        authorize.assert_not_called()
        browser.assert_called_once_with('http://127.0.0.1:54321/')

    def test_startup_failure_does_not_open_browser(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(launcher.Path, 'home', return_value=Path(directory)), \
             patch.object(launcher, 'health', return_value={}), \
             patch.object(launcher, 'available_port', return_value=54321), \
             patch.object(launcher, 'authorize'), \
             patch.object(launcher.time, 'monotonic', side_effect=[0, 31]), \
             patch.object(launcher.webbrowser, 'open') as browser:
            with self.assertRaisesRegex(RuntimeError, 'did not become ready'):
                launcher.launch('/App/GeoPortLite', [], Path(directory) / 'config')
        browser.assert_not_called()


if __name__ == '__main__':
    unittest.main()
