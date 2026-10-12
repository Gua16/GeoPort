"""Verify the frozen executable, resources and persistence on the native runner."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

executable = str(Path(sys.argv[1]).resolve())
startup_times=[]
subprocess.run([executable, '--help'], check=True, timeout=60)


def request(base, path, method='GET', data=None, binary=False):
    payload = None if data is None else json.dumps(data).encode()
    with urlopen(Request(base + path, data=payload, method=method,
                         headers={'Content-Type': 'application/json'}), timeout=10) as response:
        data=response.read()
        return data if binary else data.decode()


with tempfile.TemporaryDirectory() as directory:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'GEOPORT_CONFIG_DIR': directory}
    for iteration in range(2):
        started = time.monotonic()
        process = subprocess.Popen([executable, '--no-browser', '--ui-mode', 'lite', '--port', str(port)], env=env)
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    if json.loads(request(base, '/health'))['status'] == 'ok':
                        break
                except OSError:
                    time.sleep(.1)
                if process.poll() is not None:
                    raise RuntimeError('Frozen executable exited before readiness')
            else:
                raise RuntimeError('Frozen executable startup timed out')
            startup_times.append(round(time.monotonic()-started,3))
            html = request(base, '/')
            assert '/static/lite.js' in html and '/static/lite.css' in html
            assert 'GEOPORT / LOCATION' in html
            for asset in ['app-light.png','app-dark.png','device-mobile.svg']:
                assert request(base,'/static/icons/'+asset, binary=True)
            assert 'prefers-color-scheme:dark' in request(base,'/static/lite.css')
            assert 'https://' not in html
            assert '随机偏移' in html
            assert '/api/location/apply' in request(base, '/static/lite.js')
            assert 'font-family' in request(base, '/static/lite.css')
            settings = json.loads(request(base, '/api/settings'))
            assert settings['current_location'] is None and settings['device_connection'] is None
            if iteration == 0:
                request(base, '/api/base-location', 'PUT', {'lat': 23.1291, 'lng': 113.2644})
                request(base, '/api/settings', 'PUT', {'random_radius_m': 600})
            else:
                assert settings['base_location'] == {'lat': 23.1291, 'lng': 113.2644}
                assert settings['random_radius_m'] == 600
            try:
                request(base, '/api/location/apply', 'POST', {'mode': 'random'})
            except HTTPError as error:
                assert error.code == 409
            else:
                raise AssertionError('Unconnected device application falsely succeeded')
            if iteration == 1:
                assert json.loads(request(base, '/exit', 'POST', {}))['success']
                process.wait(timeout=10)
                assert process.returncode == 0
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
Path('dist/startup-times.json').write_text(json.dumps({'startup_seconds':startup_times}))
print('PASS: frozen app CLI, health, lite resources, save, restart persistence, unconnected rejection and clean exit')
