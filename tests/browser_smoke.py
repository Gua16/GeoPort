"""Optional offline browser acceptance. Requires Playwright and a local Chromium.

GEOPORT_TEST_PYTHON=/path/to/venv/bin/python python tests/browser_smoke.py
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen, Request

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
PYTHON = os.environ.get('GEOPORT_TEST_PYTHON', sys.executable)
CHROMIUM = os.environ.get('GEOPORT_TEST_CHROMIUM', '/usr/bin/chromium')


def start(directory, port):
    environment = {**os.environ, 'GEOPORT_CONFIG_DIR': directory}
    server = subprocess.Popen([PYTHON, str(ROOT/'tests/browser_server.py'), str(port)],
                              cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic()+15
    while time.monotonic()<deadline:
        try:
            with urlopen(f'http://127.0.0.1:{port}/health',timeout=.3) as response:
                if response.status == 200: return server
        except OSError: time.sleep(.05)
        if server.poll() is not None: raise RuntimeError('Test server exited during startup')
    server.terminate()
    server.wait(5)
    raise RuntimeError('Test server was not ready')


def stop(server):
    server.terminate()
    try: server.wait(5)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(5)


with tempfile.TemporaryDirectory() as directory, socket.socket() as sock:
    sock.bind(('127.0.0.1',0))
    port = sock.getsockname()[1]
    sock.close()
    base = f'http://127.0.0.1:{port}'
    server = start(directory,port)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROMIUM,headless=True)
            page = browser.new_page(viewport={'width':390,'height':844})
            external = []
            errors = []
            page.on('pageerror',lambda error: errors.append(str(error)))
            def local_only(route):
                if urlparse(route.request.url).hostname == '127.0.0.1': route.continue_()
                else:
                    external.append(route.request.url)
                    route.abort()
            page.route('**/*',local_only)
            page.goto(base)
            expect(page.locator('#device option')).to_have_count(2)
            expect(page.locator('#random')).to_be_disabled()
            page.locator('#latitude').fill('23.1291')
            page.locator('#longitude').fill('113.2644')
            page.locator('#save-base').click()
            expect(page.locator('#notice')).to_contain_text('基准坐标已保存')
            expect(page.locator('#base-display')).to_have_text('23.129100, 113.264400')
            page.locator('#radius').fill('600')
            page.locator('#radius').press('Tab')
            expect(page.locator('#notice')).to_have_text('偏移半径已保存。')
            page.locator('#connect').click()
            expect(page.locator('#notice')).to_contain_text('设备连接成功')
            expect(page.locator('#random')).to_be_enabled()
            for _ in range(2):
                page.locator('#random').click()
                expect(page.locator('#notice')).to_contain_text('已应用一次随机偏移')
                expect(page.locator('#random')).to_be_enabled()
            with urlopen(base+'/test/calls') as response: calls=json.load(response)
            assert len(calls['sets'])==2 and calls['opens']==1,calls
            page.locator('#apply-base').click()
            expect(page.locator('#notice')).to_contain_text('已恢复至基准坐标')
            expect(page.locator('#current-display')).to_have_text('23.129100, 113.264400')
            if os.environ.get('GEOPORT_TEST_SCREENSHOT'):
                page.screenshot(path=os.environ['GEOPORT_TEST_SCREENSHOT'],full_page=True)
            page.locator('#stop').click()
            expect(page.locator('#location-status')).to_have_text('未启动')
            expect(page.locator('#base-display')).to_have_text('23.129100, 113.264400')
            with urlopen(base+'/test/calls') as response: assert len(json.load(response)['sets'])==3
            # Reloading must not submit any new location updates.
            page.reload()
            expect(page.locator('#radius')).to_have_value('600')
            expect(page.locator('#latitude')).to_have_value('23.1291')
            page.locator('#disconnect').click()
            expect(page.locator('#random')).to_be_disabled()
            stop(server)
            server=start(directory,port)
            page.reload()
            expect(page.locator('#latitude')).to_have_value('23.1291')
            expect(page.locator('#radius')).to_have_value('600')
            expect(page.locator('#location-status')).to_have_text('未启动')
            expect(page.locator('#random')).to_be_disabled()
            with urlopen(base+'/test/calls') as response: assert json.load(response)['sets']==[]
            expect(page.locator('#connect')).to_be_enabled()
            page.locator('#connect').click()
            expect(page.locator('#random')).to_be_enabled()
            with urlopen(Request(base+'/test/fail',data=b'{}',method='POST')) as response: assert response.status==200
            page.locator('#random').click()
            expect(page.locator('#notice')).to_contain_text('device disconnected')
            expect(page.locator('#location-status')).to_have_text('失败')
            expect(page.locator('#random')).to_be_disabled()
            assert not external,external
            assert not errors,errors
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile layout overflow'
            page.screenshot(path=str(Path(directory)/'lite.png'),full_page=True)
            page.locator('#quit').click()
            expect(page.locator('#notice')).to_have_text('GeoPort 已退出，可以关闭此页面。')
            server.wait(timeout=5)
            assert server.returncode == 0
            browser.close()
        print('PASS: offline mobile UI, explicit save, radius persistence, two single updates, one retained session, restore, stop, process restart and device failure; no external requests or page errors')
    finally: stop(server)
