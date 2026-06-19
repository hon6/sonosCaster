"""Enable/disable launching Sonos Caster at Windows login.

Uses the per-user Run registry key (HKCU\\...\\Run), which needs no admin
rights and only affects the current user. The command points at run.bat so the
venv is used. Toggle is fully reversible.
"""

from __future__ import annotations

import os
import sys

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "SonosCaster"


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _launch_command() -> str:
    """Command Windows runs at login. Quote the path."""
    # Packaged build: point at the frozen .exe itself.
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # Dev: prefer run.bat.
    bat = os.path.join(_project_root(), "run.bat")
    if os.path.exists(bat):
        return f'"{bat}"'
    pyw = os.path.join(_project_root(), ".venv", "Scripts", "pythonw.exe")
    main = os.path.join(_project_root(), "main.py")
    return f'"{pyw}" "{main}"'


def is_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, _VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_enabled(enabled: bool) -> bool:
    """Add or remove the autostart entry. Returns True on success."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            if enabled:
                winreg.SetValueEx(
                    k, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command()
                )
            else:
                try:
                    winreg.DeleteValue(k, _VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
