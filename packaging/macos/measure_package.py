"""Comparable native size and startup measurements; symlinks counted once."""
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
profile = os.environ.get('GEOPORT_BUNDLE_PROFILE', 'compact')
app = root/'dist'/'GeoPort Lite.app'
files = [p for p in app.rglob('*') if p.is_file() and not p.is_symlink()]
top = sorted(((p.stat().st_size,str(p.relative_to(app))) for p in files),reverse=True)[:20]
dmg = root/'dist'/'GeoPort-Lite-macOS-15-arm64-test.dmg'
report = {'profile':profile,'app_bytes':sum(p.stat().st_size for p in files),
          'dmg_bytes':dmg.stat().st_size,'largest_files':top}
timing=root/'dist'/'startup-times.json'
if timing.exists(): report.update(json.loads(timing.read_text()))
(root/'dist'/'package-metrics.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='largest_files'},indent=2))
