# Native macOS arm64 PyInstaller bundle. Execute from the repository root.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).resolve().parents[1]
datas = [(str(root / 'src' / 'templates'), 'templates'),
         (str(root / 'src' / 'static'), 'static'),
         (str(root / 'LICENSE'), '.'),
         (str(root / 'docs' / 'MACOS_TEST.md'), '.')]
binaries = []
hiddenimports = ['asgiref.sync', 'pymobiledevice3.osu.posix_util', 'pymobiledevice3.cli.remote']
for package in ['pymobiledevice3', 'pycountry']:
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports
datas += copy_metadata('pymobiledevice3', recursive=True)

a = Analysis([str(root / 'src' / 'main.py')], pathex=[str(root / 'src')],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=['pytest', 'tkinter', 'matplotlib'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='GeoPortLite',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, target_arch='arm64', codesign_identity=None)
collect = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='GeoPortLite')
app = BUNDLE(collect, name='GeoPort Lite.app', bundle_identifier='app.geoport.lite.test',
             info_plist={'CFBundleDisplayName': 'GeoPort Lite',
                         'CFBundleShortVersionString': '0.1.2',
                         'CFBundleVersion': '3',
                         'LSMinimumSystemVersion': '15.0',
                         'NSHighResolutionCapable': True})
