#!/bin/bash
set -euo pipefail
app='/Applications/GeoPort Lite.app'
if [ ! -x "$app/Contents/MacOS/GeoPortLite" ]; then
  echo 'First drag GeoPort Lite.app into Applications.'
  read -r -p 'Press Return to close this window.'
  exit 1
fi
config_dir="$HOME/Library/Application Support/GeoPort"
mkdir -p "$config_dir"
echo 'Exit any existing GeoPort instance before starting with administrator privileges.'
echo 'Your password is entered only into the local sudo prompt.'
echo 'Use the browser Exit GeoPort button or Control-C here to stop this instance.'
sudo -v
port=54321
if /usr/sbin/lsof -nP -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
  echo 'Port 54321 is occupied. Exit the existing GeoPort instance first.'
  read -r -p 'Press Return to close this window.'
  exit 1
fi
# Open the browser as the normal user only after the administrator server is ready.
(
  for attempt in {1..200}; do
    if /usr/bin/curl --silent --fail --max-time 1 "http://127.0.0.1:$port/health" >/dev/null; then
      /usr/bin/open "http://127.0.0.1:$port/"
      exit 0
    fi
    /bin/sleep 0.1
  done
  echo 'GeoPort did not become ready. Inspect the error above.' >&2
) &
browser_wait=$!
trap 'kill "$browser_wait" 2>/dev/null || true' EXIT
sudo GEOPORT_CONFIG_DIR="$config_dir" "$app/Contents/MacOS/GeoPortLite" --no-browser --ui-mode lite --port "$port"
