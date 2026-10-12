"""Regressions for errors and cleanup crossing the tunnel thread boundary."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import main


class TunnelTests(unittest.TestCase):
    def setUp(self):
        main._stop_tunnels()

    def tearDown(self):
        main._stop_tunnels()

    def test_permission_error_reaches_connection_request_without_timeout(self):
        client = main.app.test_client()
        started = time.monotonic()
        with patch.object(main, 'check_developer_mode', return_value=True), \
             patch.object(main, 'create_using_usbmux', return_value=MagicMock()), \
             patch.object(main, 'stop_remoted_if_required', side_effect=main.AccessDeniedError()), \
             patch.object(main, 'resume_remoted_if_required') as resume, \
             self.assertLogs('GeoPort', level='ERROR') as logs:
            response = client.post('/connect_device', json={
                'udid': 'fake', 'connType': 'USB', 'ios_version': '27.0.1'})
        self.assertEqual(response.status_code, 502)
        self.assertIn('AccessDeniedError', response.json['error'])
        self.assertIn('sudo', response.json['error'])
        self.assertNotIn('30 seconds', response.json['error'])
        self.assertLess(time.monotonic() - started, 2)
        self.assertIsNone(response.json['state']['device_connection'])
        self.assertIn('Traceback', '\n'.join(logs.output))
        resume.assert_not_called()  # Suspend failed before changing remoted.

    def test_original_exception_type_and_cause_are_preserved(self):
        failure = OSError('tunnel handshake rejected')
        def fail():
            raise failure
        with self.assertLogs('GeoPort', level='ERROR'):
            thread = main._start_tunnel(fail)
            with self.assertRaisesRegex(RuntimeError, 'OSError: tunnel handshake rejected') as caught:
                main.check_rsd_data()
            thread.join()
        self.assertIs(caught.exception.__cause__, failure)

    def test_remoted_resumes_and_service_closes_when_enter_fails(self):
        class Service:
            @asynccontextmanager
            async def start_tcp_tunnel(self):
                raise OSError('handshake failed')
                yield
            async def close(self):
                closed.append(True)
        closed = []
        async def run():
            async with main._managed_tunnel(Service, 'start_tcp_tunnel'):
                self.fail('must not become ready')
        with patch.object(main, 'stop_remoted_if_required') as stop, \
             patch.object(main, 'resume_remoted_if_required') as resume:
            with self.assertRaisesRegex(OSError, 'handshake failed'):
                asyncio.run(run())
        stop.assert_called_once()
        resume.assert_called_once()
        self.assertEqual(closed, [True])

    def test_service_constructor_failure_also_resumes_remoted(self):
        async def run():
            async with main._managed_tunnel(MagicMock(side_effect=OSError('create failed')), 'start_tcp_tunnel'):
                self.fail('must not become ready')
        with patch.object(main, 'stop_remoted_if_required'), \
             patch.object(main, 'resume_remoted_if_required') as resume:
            with self.assertRaisesRegex(OSError, 'create failed'):
                asyncio.run(run())
        resume.assert_called_once()

    def test_cleanup_errors_do_not_hide_handshake_exception(self):
        class Service:
            @asynccontextmanager
            async def start_tcp_tunnel(self):
                raise OSError('original handshake failure')
                yield
            async def close(self):
                raise ValueError('secondary close failure')
        async def run():
            async with main._managed_tunnel(Service, 'start_tcp_tunnel'):
                self.fail('must not become ready')
        with patch.object(main, 'stop_remoted_if_required'), \
             patch.object(main, 'resume_remoted_if_required', side_effect=PermissionError('resume failed')), \
             self.assertLogs('GeoPort', level='ERROR') as logs:
            with self.assertRaisesRegex(OSError, 'original handshake failure'):
                asyncio.run(run())
        self.assertIn('resume failed', '\n'.join(logs.output))
        self.assertIn('secondary close failure', '\n'.join(logs.output))

    def test_async_service_factory_failure_resumes_without_closing_coroutine(self):
        async def create():
            raise OSError('async create failed')
        async def run():
            async with main._managed_tunnel(create, 'start_quic_tunnel'):
                self.fail('must not become ready')
        with patch.object(main, 'stop_remoted_if_required'), \
             patch.object(main, 'resume_remoted_if_required') as resume, \
             patch.object(main.logger, 'exception') as log:
            with self.assertRaisesRegex(OSError, 'async create failed'):
                asyncio.run(run())
        resume.assert_called_once()
        log.assert_not_called()

    def test_success_restores_remoted_before_ready_and_reuses_lockdown(self):
        entered, exited, closed = threading.Event(), threading.Event(), threading.Event()
        resumed = threading.Event()
        provider = object()
        class Service:
            @asynccontextmanager
            async def start_tcp_tunnel(self):
                entered.set()
                try:
                    yield SimpleNamespace(address='::1', port=1234)
                finally:
                    exited.set()
            async def close(self):
                closed.set()
        with patch.object(main, 'stop_remoted_if_required') as stop, \
             patch.object(main, 'resume_remoted_if_required', side_effect=resumed.set) as resume, \
             patch.object(main, 'CoreDeviceTunnelProxy', return_value=Service()) as factory, \
             patch.object(main, 'create_using_usbmux') as create:
            main.start_tcp_tunnel_thread(provider)
            self.assertTrue(main.check_rsd_data())
            self.assertTrue(entered.is_set())
            self.assertTrue(resumed.is_set())
            self.assertEqual((main.rsd_host, main.rsd_port), ('::1', '1234'))
            main._stop_tunnels()
        factory.assert_called_once_with(provider)
        create.assert_not_called()
        stop.assert_called_once()
        resume.assert_called_once()
        self.assertTrue(exited.is_set())
        self.assertTrue(closed.is_set())
        self.assertIsNone(main.rsd_host)

    def test_cancelled_startup_cannot_publish_stale_rsd(self):
        release = threading.Event()
        def late_start():
            release.wait(2)
            main._publish_tunnel(SimpleNamespace(address='::1', port=1234))
        with self.assertLogs('GeoPort', level='ERROR'):
            thread = main._start_tunnel(late_start)
            thread.geoport_stop_event.set()
            release.set()
            thread.join(2)
        self.assertIsNone(main.rsd_host)
        self.assertIsNone(main.rsd_port)
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            main.check_rsd_data()


if __name__ == '__main__':
    unittest.main()
