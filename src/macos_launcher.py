"""System authorization for a Finder-launched app; never handles passwords."""
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import time
from urllib.request import urlopen
import uuid
import webbrowser


class AuthorizationCancelled(Exception):
    pass


def needs_authorization(platform, frozen, no_browser, uid):
    # CLI/headless and already-elevated launches keep their existing behavior.
    return platform == 'darwin' and frozen and not no_browser and uid != 0


def health(port):
    try:
        with urlopen(f'http://127.0.0.1:{port}/health', timeout=.3) as response:
            return json.load(response)
    except (OSError, ValueError):
        return {}


def available_port(preferred):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', preferred))
        except OSError:
            sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def apple_string(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def authorize(command):
    # AppleScript requests credentials directly from macOS SecurityAgent.
    script = 'do shell script ' + apple_string(command) + ' with administrator privileges\n'
    result = subprocess.run(['/usr/bin/osascript', '-'], input=script, text=True,
                            capture_output=True)
    if result.returncode:
        if '(-128)' in result.stderr:
            raise AuthorizationCancelled()
        raise RuntimeError('macOS administrator authorization failed')


def launch(executable, arguments, config_directory, preferred_port=54321):
    existing = health(preferred_port)
    if existing.get('app') == 'GeoPort' and existing.get('administrator'):
        webbrowser.open(f'http://127.0.0.1:{preferred_port}/')
        return

    config_directory = Path(config_directory).resolve()
    config_directory.mkdir(parents=True, exist_ok=True)
    log_directory = Path.home() / 'Library' / 'Logs' / 'GeoPort'
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / 'startup.log'
    # Create the log as the normal user before the administrator writes to it.
    log_path.touch(exist_ok=True)
    port = available_port(preferred_port)
    launch_id = uuid.uuid4().hex
    argv = ['/usr/bin/env',
            'PYINSTALLER_RESET_ENVIRONMENT=1',
            f'GEOPORT_CONFIG_DIR={config_directory}',
            f'SUDO_UID={os.getuid()}', f'SUDO_GID={os.getgid()}',
            str(Path(executable).resolve()), *arguments,
            '--no-browser', '--port', str(port), '--launch-id', launch_id]
    # SecurityAgent has no controlling terminal. Ignore HUP in the shell rather
    # than using macOS nohup, which can fail while detaching from that console.
    command = ('trap "" HUP; ' + shlex.join(argv) + ' >> ' + shlex.quote(str(log_path)) +
               ' 2>&1 < /dev/null & echo $!')
    authorize(command)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        ready = health(port)
        if ready.get('launch_id') == launch_id and ready.get('administrator'):
            webbrowser.open(f'http://127.0.0.1:{port}/')
            return
        time.sleep(.1)
    raise RuntimeError(f'GeoPort did not become ready. Startup log: {log_path}')


def show_error(message):
    subprocess.run(['/usr/bin/osascript', '-'], input=(
        'display alert "GeoPort 启动失败" message ' + apple_string(message) +
        ' as critical\n'), text=True, capture_output=True)
