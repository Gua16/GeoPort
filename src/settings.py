"""User-owned settings, with validated reads and atomic writes."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

from location_math import coordinates, radius_m

DEFAULTS = {"schema_version": 1, "base_location": None, "random_radius_m": 300, "ui_mode": "lite"}


def config_path():
    if os.environ.get("GEOPORT_CONFIG_DIR"):
        return Path(os.environ["GEOPORT_CONFIG_DIR"]) / "config.json"
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "GeoPort" / "config.json"


def validated(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported or invalid configuration schema")
    result = copy.deepcopy(DEFAULTS)
    base = data.get("base_location")
    if base is not None:
        if not isinstance(base, dict):
            raise ValueError("Invalid base location")
        result["base_location"] = coordinates(base.get("lat"), base.get("lng"))
    result["random_radius_m"] = radius_m(data.get("random_radius_m", 300))
    if data.get("ui_mode", "lite") not in ("lite", "map"):
        raise ValueError("UI mode must be lite or map")
    result["ui_mode"] = data.get("ui_mode", "lite")
    return result


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else config_path()
        self._lock = threading.RLock()
        self.warning = None
        self._data = copy.deepcopy(DEFAULTS)
        try:
            self._data = validated(json.loads(self.path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Preserve the original file until the user explicitly saves again.
            self.warning = f"Could not read saved settings; using defaults: {exc}"

    def read(self):
        with self._lock:
            return copy.deepcopy(self._data)

    def update(self, **changes):
        with self._lock:
            data = validated({**self._data, **changes})
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                                 prefix=".config-", suffix=".json", delete=False) as handle:
                    temporary = handle.name
                    json.dump(data, handle, ensure_ascii=False, allow_nan=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                # Keep the normal user's configuration readable after sudo use.
                owner = self.path.parent.stat()
                sudo_uid = os.environ.get('SUDO_UID', '')
                if hasattr(os, 'geteuid') and os.geteuid() == 0 and sudo_uid.isdecimal():
                    if owner.st_uid == int(sudo_uid) and owner.st_uid != 0:
                        os.chown(temporary, owner.st_uid, owner.st_gid)
                os.replace(temporary, self.path)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
            self._data = data
            self.warning = None
            return copy.deepcopy(data)
