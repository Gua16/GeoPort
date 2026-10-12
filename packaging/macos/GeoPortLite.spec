# Native Apple Silicon bundle. The default profile avoids broad CLI/resource collection.
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

root = Path(SPECPATH).resolve().parents[1]
profile = os.environ.get('GEOPORT_BUNDLE_PROFILE', 'compact')
datas = [(str(root / 'src' / 'templates'), 'templates'),
         (str(root / 'src' / 'static'), 'static'),
         (str(root / 'LICENSE'), '.'),
         (str(root / 'docs' / 'MACOS_TEST.md'), '.'),
         (str(root / 'build' / 'icons' / 'Assets.car'), '.'),
         (str(root / 'build' / 'icons' / 'AppIconDark.icns'), 'icons')]
binaries = []
hiddenimports = ['asgiref.sync', 'pymobiledevice3.osu.posix_util']
excludes = ['pytest', 'tkinter', 'matplotlib']
if profile == 'baseline':
    for package in ['pymobiledevice3', 'pycountry']:
        data, binary, imports = collect_all(package)
        datas += data
        binaries += binary
        hiddenimports += imports
    datas += copy_metadata('pymobiledevice3', recursive=True)
else:
    datas += collect_data_files('pymobiledevice3')
    datas += copy_metadata('pymobiledevice3', recursive=True)
    # GeoPort directly imports device service APIs; no interactive CLI is offered.
    excludes += ['pymobiledevice3.cli', 'pymobiledevice3.tunneld', 'fastapi',
                 'fastapi_cli', 'fastapi_cloud_cli', 'uvicorn', 'sentry_sdk',
                 'opentelemetry', 'jedi', 'PIL']
a = Analysis([str(root / 'src' / 'main.py')], pathex=[str(root / 'src')],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[] if profile == 'baseline' else [str(root / 'packaging' / 'macos' / 'hooks')],
             excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)
common = dict(name='GeoPortLite', debug=False, bootloader_ignore_signals=False,
              strip=profile != 'baseline', upx=False, console=True,
              target_arch='arm64', codesign_identity=None)
if profile == 'onefile':
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **common)
    contents = exe
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    contents = COLLECT(exe, a.binaries, a.datas, strip=profile != 'baseline', upx=False, name='GeoPortLite')
app = BUNDLE(contents, name='GeoPort Lite.app', icon=str(root / 'build' / 'icons' / 'AppIcon.icns'),
             bundle_identifier='app.geoport.lite.test',
             info_plist={'CFBundleDisplayName': 'GeoPort Lite',
                         'CFBundleShortVersionString': '0.1.4',
                         'CFBundleVersion': '5',
                         'CFBundleIconName': 'AppIcon',
                         'LSMinimumSystemVersion': '15.0',
                         'NSHighResolutionCapable': True})
