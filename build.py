"""Build a standalone Windows executable with PyInstaller.

Produces dist/SonosCaster/SonosCaster.exe (onedir) with ffmpeg.exe bundled, so
it runs on any Windows PC without installing Python or ffmpeg.

Run:  .venv\\Scripts\\python.exe build.py
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
FFMPEG = os.path.join(ROOT, "bundle", "ffmpeg.exe")
ICON = os.path.join(ROOT, "bundle", "SonosCaster.ico")


def main():
    if not os.path.exists(FFMPEG):
        print("ERROR: bundle/ffmpeg.exe not found. Copy it there first.")
        sys.exit(1)
    # Regenerate the icon each build so the exe always reflects the latest
    # icon.py output (no stale bundle/SonosCaster.ico after a tweak).
    from sonos_caster.icon import save_ico
    save_ico(ICON)

    onefile = "--onedir" not in sys.argv  # default: single-file exe
    mode = "--onefile" if onefile else "--onedir"

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", "SonosCaster",
        "--windowed",                 # no console window (GUI app)
        "--icon", ICON,
        # No --uac-admin: the app runs normally; the firewall step self-elevates
        # just the netsh call via ShellExecute "runas" (one UAC prompt) when
        # needed. This is more reliable than the manifest on the 32-bit loader.
        mode,
        # Bundle ffmpeg INTO the exe so find_ffmpeg() (sys._MEIPASS) picks it up.
        "--add-binary", f"{FFMPEG}{os.pathsep}.",
        # Bundle the .ico too so iconbitmap(default=...) can find it at runtime
        # (taskbar icon while the window is open).
        "--add-data", f"{ICON}{os.pathsep}.",
        # soundcard loads its backend dynamically; make sure it's included.
        "--collect-all", "soundcard",
        "--collect-submodules", "soco",
        "--collect-submodules", "zeroconf",
        "--collect-submodules", "PIL",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "comtypes",
        "main.py",
    ]
    print("Running:", " ".join(args))
    rc = subprocess.call(args, cwd=ROOT)
    if rc == 0:
        if onefile:
            out = os.path.join(ROOT, "dist", "SonosCaster.exe")
            print("\nBUILD OK ->", out)
            print("Single-file build. Copy SonosCaster.exe to the other PC and "
                  "run it (first launch is a few seconds slower as it unpacks).")
        else:
            out = os.path.join(ROOT, "dist", "SonosCaster", "SonosCaster.exe")
            print("\nBUILD OK ->", out)
            print("Copy the whole dist\\SonosCaster folder and run "
                  "SonosCaster.exe.")
    else:
        print("\nBUILD FAILED (exit %d)" % rc)
    sys.exit(rc)


if __name__ == "__main__":
    main()
