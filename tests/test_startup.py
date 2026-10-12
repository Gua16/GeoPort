from pathlib import Path
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import main


class StartupTests(unittest.TestCase):
    def test_browser_opens_only_after_health_is_ready(self):
        response=MagicMock()
        response.__enter__.return_value.status=200
        with patch.object(main,'urlopen',side_effect=[OSError('not listening yet'),response]) as health, \
             patch.object(main.webbrowser,'open') as browser, \
             patch.object(main.threading,'Event') as event:
            main.open_browser(54321)
        self.assertEqual(health.call_count,2)
        event.return_value.wait.assert_called_once_with(.05)
        browser.assert_called_once_with('http://127.0.0.1:54321/')

    def test_browser_timeout_does_not_open_a_dead_server(self):
        with patch.object(main.time,'monotonic',side_effect=[0,16]), \
             patch.object(main.webbrowser,'open') as browser:
            main.open_browser(54321)
        browser.assert_not_called()
