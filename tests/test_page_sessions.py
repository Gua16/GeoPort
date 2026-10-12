from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from page_sessions import PageSessions


class PageTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.exit = Mock()
        self.pages = PageSessions(self.exit, clock=lambda: self.now)

    def test_headless_server_never_arms_automatic_exit(self):
        self.now = 999
        self.assertFalse(self.pages.poll())
        self.exit.assert_not_called()

    def test_last_page_closes_after_120_seconds_and_only_once(self):
        self.pages.opened('a'); self.pages.opened('b')
        self.pages.closed('a'); self.now = 200
        self.assertFalse(self.pages.poll())
        self.pages.closed('b'); self.now = 319
        self.assertFalse(self.pages.poll())
        self.now = 320
        self.assertTrue(self.pages.poll())
        self.assertFalse(self.pages.poll())
        self.exit.assert_called_once()
        self.assertFalse(self.pages.opened('c'))

    def test_reload_or_reopen_cancels_old_countdown(self):
        self.pages.opened('a'); self.pages.closed('a')
        self.now = 119; self.pages.opened('b')
        self.now = 500; self.assertFalse(self.pages.poll())
        self.pages.closed('b'); self.now = 619
        self.assertFalse(self.pages.poll())
        self.now = 620; self.assertTrue(self.pages.poll())

    def test_cleanup_failure_retries_and_accepts_reopened_page(self):
        self.pages.opened('a'); self.pages.closed('a')
        self.now = 120; self.exit.side_effect = OSError('device clear failed')
        with self.assertRaises(OSError): self.pages.poll()
        self.assertTrue(self.pages.opened('b'))
        self.now = 999; self.assertFalse(self.pages.poll())

    def test_duplicate_close_does_not_extend_grace(self):
        self.pages.opened('a'); self.pages.closed('a')
        self.now = 119; self.pages.closed('a')
        self.now = 120; self.assertTrue(self.pages.poll())
