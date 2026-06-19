"""Locate the ffmpeg executable robustly on Windows.

winget installs ffmpeg but the updated PATH only applies to *new* shells, so a
freshly-installed ffmpeg may not be visible via PATH yet. We therefore search,
in order:

1. An explicit AIRPLAY_FFMPEG environment override.
2. ffmpeg on the current PATH.
3. The winget "Links" shim (%LOCALAPPDATA%\\Microsoft\\WinGet\\Links).
4. The winget package install dir (Gyan.FFmpeg ... \\bin\\ffmpeg.exe).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional


class FFmpegNotFound(RuntimeError):
    pass


def _bundled_ffmpeg() -> Optional[str]:
    """Return a bundled ffmpeg.exe if running as a packaged app, else None.

    PyInstaller unpacks data into sys._MEIPASS; we also check a `bundle/` folder
    next to the executable (onedir builds) and next to this source file (dev).
    """
    import sys

    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "ffmpeg.exe")
        candidates.append(Path(meipass) / "bundle" / "ffmpeg.exe")
    # Next to the frozen exe.
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / "ffmpeg.exe")
        candidates.append(exe_dir / "bundle" / "ffmpeg.exe")
    # Dev: project bundle folder.
    candidates.append(
        Path(__file__).resolve().parent.parent / "bundle" / "ffmpeg.exe"
    )
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def find_ffmpeg() -> str:
    # 0. Bundled with the app (packaged build) — preferred so it works on any PC.
    bundled = _bundled_ffmpeg()
    if bundled:
        return bundled

    # 1. Explicit override.
    override = os.environ.get("AIRPLAY_FFMPEG")
    if override and Path(override).exists():
        return override

    # 2. On PATH.
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path

    local = os.environ.get("LOCALAPPDATA")
    if local:
        local_path = Path(local)
        # 3. winget Links shim.
        shim = local_path / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
        if shim.exists():
            return str(shim)

        # 4. winget package dir (version-agnostic glob).
        pkg_root = local_path / "Microsoft" / "WinGet" / "Packages"
        if pkg_root.exists():
            matches = list(pkg_root.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"))
            if matches:
                return str(matches[0])

    raise FFmpegNotFound(
        "找不到 ffmpeg。请安装后重试：winget install Gyan.FFmpeg "
        "（或设置环境变量 AIRPLAY_FFMPEG 指向 ffmpeg.exe）。"
    )


def ffmpeg_available() -> Optional[str]:
    """Return the ffmpeg path if found, else None (non-raising)."""
    try:
        return find_ffmpeg()
    except FFmpegNotFound:
        return None
