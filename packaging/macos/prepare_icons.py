"""Compile authored light/dark icons, with a legacy macOS 15 fallback."""
import json
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[2]
build = root / 'build' / 'icons'
build.mkdir(parents=True, exist_ok=True)
composer = build / 'AppIcon.icon'
(composer / 'Assets').mkdir(parents=True, exist_ok=True)
for appearance in ['light', 'dark']:
    source = root / 'packaging' / 'macos' / 'icons' / (appearance + '.png')
    shutil.copyfile(source, composer / 'Assets' / (appearance + '.png'))
    iconset = build / (appearance + '.iconset')
    iconset.mkdir(exist_ok=True)
    for size in [16, 32, 128, 256, 512]:
        for scale in [1, 2]:
            filename = f'icon_{size}x{size}' + ('@2x' if scale == 2 else '') + '.png'
            subprocess.run(['sips', '-z', str(size * scale), str(size * scale), str(source), '--out', str(iconset / filename)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['iconutil', '--convert', 'icns', '--output', str(build / ('LegacyAppIcon.icns' if appearance == 'light' else 'AppIconDark.icns')), str(iconset)], check=True)
    subprocess.run(['sips', '-z', '128', '128', str(source), '--out', str(root / 'src' / 'static' / 'icons' / ('app-' + appearance + '.png'))], check=True, stdout=subprocess.DEVNULL)
# Legacy .appiconset does not support macOS dark appearance entries. Use the
# Icon Composer format (Xcode 26+) for systems supporting adaptive app icons.
(composer / 'icon.json').write_text(json.dumps({
    'fill-specializations': [
        {'value': {'solid': 'srgb:0.95,0.95,0.94,1'}},
        {'appearance': 'dark', 'value': {'solid': 'srgb:0.12,0.13,0.14,1'}},
    ],
    'groups': [{
        'lighting': 'individual', 'specular': False,
        'translucency': {'enabled': False, 'value': 0},
        'shadow': {'kind': 'none', 'opacity': 0},
        'layers': [{'name': 'GeoPort', 'glass': False,
                    'image-name-specializations': [
                        {'value': 'light.png'},
                        {'appearance': 'dark', 'value': 'dark.png'},
                    ]}],
    }],
    'supported-platforms': {'squares': 'shared'},
}, indent=2))
subprocess.run(['xcrun', 'actool', str(composer), '--compile', str(build), '--app-icon', 'AppIcon', '--platform', 'macosx', '--target-device', 'mac', '--minimum-deployment-target', '26.0', '--output-partial-info-plist', str(build / 'IconInfo.plist'), '--warnings', '--errors'], check=True)
assert (build / 'Assets.car').exists(), 'Missing compiled appearance catalog'
# Preserve the full-resolution classic icon; actool emits a smaller fallback.
shutil.copyfile(build / 'LegacyAppIcon.icns', build / 'AppIcon.icns')
inspection = subprocess.run(['xcrun', 'assetutil', '--info', str(build / 'Assets.car')], check=True, capture_output=True, text=True).stdout
(build / 'IconAssets.json').write_text(inspection)
assert 'dark' in inspection.lower(), 'Compiled catalog is missing dark appearance'
print('Prepared adaptive native icon, macOS 15 fallback and local favicons')
