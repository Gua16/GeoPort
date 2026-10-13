#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
  echo 'This build requires a native Apple Silicon macOS machine.' >&2
  exit 1
fi
python packaging/macos/prepare_icons.py
python -m PyInstaller --noconfirm --clean packaging/macos/GeoPortLite.spec
app='dist/GeoPort Lite.app'
cp build/icons/Assets.car "$app/Contents/Resources/Assets.car"
cp build/icons/AppIconDark.icns "$app/Contents/Resources/AppIconDark.icns"
codesign --force --deep --sign - "$app"
codesign --verify --deep --strict --verbose=2 "$app"
file "$app/Contents/MacOS/GeoPortLite"
python packaging/macos/verify_bundle.py "$app/Contents/MacOS/GeoPortLite"
stage=$(mktemp -d "${TMPDIR:-/tmp}/geoport-dmg.XXXXXX")
trap 'rm -rf "$stage"' EXIT
ditto "$app" "$stage/GeoPort Lite.app"
ln -s /Applications "$stage/Applications"
cp packaging/macos/Start-with-Admin.command "$stage/Start with Admin.command"
chmod +x "$stage/Start with Admin.command"
cp docs/MACOS_TEST.md "$stage/Read me first.txt"
cp LICENSE "$stage/LICENSE.txt"
git rev-parse HEAD > "$stage/SOURCE_COMMIT.txt"
python --version > "$stage/BUILD_PYTHON.txt"
dmg='GeoPort-Lite-macOS-15-arm64-test.dmg'
hdiutil create -volname 'GeoPort Lite Test' -srcfolder "$stage" -ov -format UDZO "dist/$dmg"
hdiutil verify "dist/$dmg"
(cd dist && shasum -a 256 "$dmg" > "$dmg.sha256")
echo "Built dist/$dmg (ad-hoc signed, not notarized)"
