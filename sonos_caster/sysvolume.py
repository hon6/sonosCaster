"""Get/set the Windows master output volume.

Used to dip the PC's local volume to near-zero while forwarding to Sonos (so
you don't hear both at once) and restore it afterwards. Loopback keeps
capturing, so Sonos still receives audio even though the local speaker is nearly
silent.

Implementation: a tiny inline-C# helper run via PowerShell, calling the Core
Audio IAudioEndpointVolume API. This needs no Python packages (pycaw/comtypes
are not installed). Only called on start/stop, so the PowerShell startup cost is
irrelevant.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Optional

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_CS = r"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
  int f(); int g(); int h(); int i();
  int SetMasterVolumeLevelScalar(float level, Guid ctx);
  int j();
  int GetMasterVolumeLevelScalar(out float level);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { int Activate(ref Guid id, int clsCtx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object ep); }
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int f(); int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ep); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject { }
public class Vol {
  static IAudioEndpointVolume Endpoint() {
    var e = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
    IMMDevice dev; e.GetDefaultAudioEndpoint(0,1,out dev);
    Guid iid = typeof(IAudioEndpointVolume).GUID; object o;
    dev.Activate(ref iid,1,IntPtr.Zero,out o);
    return (IAudioEndpointVolume)o;
  }
  public static float Get(){ float v; Endpoint().GetMasterVolumeLevelScalar(out v); return v; }
  public static void Set(float v){ Endpoint().SetMasterVolumeLevelScalar(v, Guid.Empty); }
}
'@
"""


def _run_ps(action: str) -> Optional[str]:
    script = _CS + action
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=15,
        )
        if proc.returncode != 0:
            return None
        return (proc.stdout or "").strip()
    except Exception:
        return None


def get_volume() -> Optional[float]:
    """Return master volume as 0.0–1.0, or None on failure."""
    out = _run_ps("[Vol]::Get()")
    if out is None:
        return None
    try:
        return float(out)
    except ValueError:
        return None


def set_volume(level_0_to_1: float) -> bool:
    """Set master volume (0.0–1.0). Returns True on success."""
    level = max(0.0, min(1.0, float(level_0_to_1)))
    out = _run_ps(f"[Vol]::Set({level:.4f})")
    return out is not None
