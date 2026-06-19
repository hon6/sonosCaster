"""Persistent settings for the floating capsule UI.

Stores window position, last-used device, format, blocksize, volume and the
dim-local / autostart toggles in a small JSON file next to the project so the
capsule reappears where the user left it.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict


def _config_dir() -> str:
    """Where to store settings.

    Packaged (frozen) builds may live in a read-only folder, so use a per-user
    AppData dir. In dev, keep it next to the project for convenience.
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "SonosCaster")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            d = os.path.dirname(sys.executable)
        return d
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


_CONFIG_PATH = os.path.join(_config_dir(), "sonos_caster_settings.json")

_DEFAULTS: Dict[str, Any] = {
    "x": None,            # window left (None -> center bottom-right on first run)
    "y": None,
    "device_uid": None,   # last selected Sonos room (stable id)
    "device_name": None,  # last selected Sonos room display name
    "audio_device": None,  # output device to CAPTURE (None = system default)
    "lan_ip": None,        # local IP Sonos connects back to (None = auto-pick)
    "codec": "wav",       # WAV = low latency, works fine. MP3 = stable fallback.
    "blocksize": 512,     # robust on real hardware; 64 crackles on real cards
    "volume": 30,
    "dim_local": True,
    "autostart": False,
}


def load() -> Dict[str, Any]:
    cfg = dict(_DEFAULTS)
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update({k: data[k] for k in data if k in _DEFAULTS})
    except Exception:
        pass
    # Migrate the known-bad ultra-small blocksize: 64 crackles on real sound
    # cards. Bump anything below 256 up to the robust default so existing
    # settings files don't keep producing dropouts.
    try:
        if int(cfg.get("blocksize", 512)) < 256:
            cfg["blocksize"] = 512
    except Exception:
        cfg["blocksize"] = 512
    return cfg


def save(cfg: Dict[str, Any]) -> None:
    try:
        # Only persist known keys.
        out = {k: cfg.get(k, _DEFAULTS[k]) for k in _DEFAULTS}
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
