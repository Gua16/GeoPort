"""Real browser QA for layout, themes, keyboard navigation and form state."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[1]
python = os.environ.get('GEOPORT_TEST_PYTHON', '/workspace/geoport-env/venv/bin/python')
output = Path(os.environ.get('GEOPORT_DESIGN_OUTPUT', '/workspace/geoport-env/design'))
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as directory:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    server = subprocess.Popen([python, str(root/'tests/browser_server.py'), str(port)],
        cwd=root, env={**os.environ, 'GEOPORT_CONFIG_DIR': directory}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with urlopen(base+'/health', timeout=.3) as response:
                    if response.status == 200: break
            except OSError: time.sleep(.05)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
            page = browser.new_page(viewport={'width':1440,'height':1000}, color_scheme='light')
            errors=[]; external=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            def intercept(route):
                if urlparse(route.request.url).hostname=='127.0.0.1':route.continue_()
                else:external.append(route.request.url);route.abort()
            page.route('**/*',intercept)
            page.goto(base)
            expect(page.locator('#device option')).to_have_count(2)
            expect(page.locator('#random')).to_be_disabled()
            assert page.locator('.app-header p').count()==1, 'No subtitle under GeoPort'
            page.screenshot(path=str(output/'empty-light.png'),full_page=True)
            page.locator('#latitude').fill('23.129100');page.locator('#longitude').fill('113.264400')
            expect(page.locator('#draft-indicator')).to_have_text('尚未保存')
            page.locator('#save-base').click()
            expect(page.locator('#notice')).to_contain_text('基准坐标已保存')
            expect(page.locator('#draft-indicator')).to_have_text('')
            page.locator('#connect').click()
            expect(page.locator('#device-summary')).to_have_text('已连接')
            expect(page.locator('#disconnect')).to_be_visible()
            expect(page.locator('#connect')).to_be_hidden()
            page.locator('#random').click()
            expect(page.locator('#notice')).to_contain_text('已应用一次随机偏移')
            expect(page.locator('#location-status')).to_have_text('模拟中')
            page.screenshot(path=str(output/'connected-light.png'),full_page=True)
            # Tabs follow the ARIA keyboard pattern and reveal real preferences.
            page.locator('#workspace-tab').focus();page.keyboard.press('ArrowRight')
            expect(page.locator('#preferences-tab')).to_be_focused()
            expect(page.locator('#preferences-panel')).to_be_visible()
            page.locator('#startup-mode').select_option('map')
            expect(page.locator('#notice')).to_have_text('下次启动界面已保存。')
            page.locator('#startup-mode').select_option('lite')
            expect(page.locator('#notice')).to_have_text('下次启动界面已保存。')
            page.screenshot(path=str(output/'settings-light.png'),full_page=True)
            page.locator('#preferences-tab').focus();page.keyboard.press('Home')
            expect(page.locator('#workspace-panel')).to_be_visible()
            page.emulate_media(color_scheme='dark')
            assert page.evaluate("matchMedia('(prefers-color-scheme: dark)').matches")
            dark=page.locator('body').evaluate("el=>getComputedStyle(el).getPropertyValue('--background').trim()")
            assert dark=='#1c1c1b',dark
            assert page.locator('link[rel=icon][media="(prefers-color-scheme: dark)"]').count()==1
            page.screenshot(path=str(output/'connected-dark.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Narrow viewport overflow'
            page.screenshot(path=str(output/'mobile-dark.png'),full_page=True)
            page.emulate_media(color_scheme='light')
            page.screenshot(path=str(output/'mobile-light.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1000})
            # System-style contrast check for normal secondary text, both appearances.
            for appearance in ['light','dark']:
                page.emulate_media(color_scheme=appearance)
                colors=page.locator(':root').evaluate("el=>{const s=getComputedStyle(el);return [s.getPropertyValue('--muted').trim(),s.getPropertyValue('--surface').trim()]}")
                def luminance(color):
                    rgb=[int(color[i:i+2],16)/255 for i in (1,3,5)]
                    v=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in rgb]
                    return sum(a*b for a,b in zip(v,[.2126,.7152,.0722]))
                a,b=map(luminance,colors);ratio=(max(a,b)+.05)/(min(a,b)+.05)
                assert ratio>=4.5,(appearance,ratio)
            assert not external,external
            assert not errors,errors
            browser.close()
        print('PASS: desktop/mobile, light/dark, keyboard tabs, preferences, dirty state, primary flow, 4.5:1 secondary contrast, no external requests or page errors')
    finally:
        server.terminate()
        try:server.wait(5)
        except subprocess.TimeoutExpired:server.kill();server.wait(5)
