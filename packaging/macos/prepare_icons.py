"""Convert authored masters using native Apple tools; include both appearances."""
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
build = root / 'build' / 'icons'
build.mkdir(parents=True, exist_ok=True)
assets = build / 'GeoPort.xcassets'
assets.mkdir(exist_ok=True)
(assets / 'Contents.json').write_text(json.dumps({'info': {'author': 'xcode', 'version': 1}}))
appicon = assets / 'AppIcon.appiconset'
appicon.mkdir(exist_ok=True)
entries = []
for appearance in ['light', 'dark']:
    source = root / 'packaging' / 'macos' / 'icons' / (appearance + '.png')
    iconset = build / (appearance + '.iconset')
    iconset.mkdir(exist_ok=True)
    for size in [16, 32, 128, 256, 512]:
        for scale in [1, 2]:
            filename = f'icon_{size}x{size}' + ('@2x' if scale == 2 else '') + '.png'
            output = iconset / filename
            subprocess.run(['sips', '-z', str(size * scale), str(size * scale), str(source), '--out', str(output)], check=True, stdout=subprocess.DEVNULL)
            catalog_file = appearance + '-' + filename
            subprocess.run(['cp', str(output), str(appicon / catalog_file)], check=True)
            entry = {'idiom': 'mac', 'size': f'{size}x{size}', 'scale': f'{scale}x', 'filename': catalog_file}
            if appearance == 'dark':
                entry['appearances'] = [{'appearance': 'luminosity', 'value': 'dark'}]
            entries.append(entry)
    subprocess.run(['iconutil', '--convert', 'icns', '--output', str(build / ('AppIcon.icns' if appearance == 'light' else 'AppIconDark.icns')), str(iconset)], check=True)
    # Browser favicons are intentionally small; never bundle 1280px artwork twice.
    subprocess.run(['sips', '-z', '128', '128', str(source), '--out', str(root / 'src' / 'static' / 'icons' / ('app-' + appearance + '.png'))], check=True, stdout=subprocess.DEVNULL)
(appicon / 'Contents.json').write_text(json.dumps({'images': entries, 'info': {'author': 'xcode', 'version': 1}}, indent=2))
subprocess.run(['xcrun', 'actool', str(assets), '--compile', str(build), '--app-icon', 'AppIcon', '--platform', 'macosx', '--minimum-deployment-target', '15.0', '--output-partial-info-plist', str(build / 'IconInfo.plist'), '--warnings', '--errors'], check=True)
assert (build / 'Assets.car').exists(), 'Missing compiled appearance catalog'
print('Prepared light/dark native icons, appearance catalog and local favicons')
