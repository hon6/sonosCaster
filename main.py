"""Entry point for Sonos Caster — floating capsule UI.

Forward Windows system audio to a Sonos speaker over its native protocol.
A small macOS-style floating pill: click the toggle to start/stop forwarding;
hover to expand for device / format / volume / settings.

Run:  python main.py   (or double-click run.bat)

Writes a session log to sonos_caster.log (pythonw / the PyInstaller exe have
no stdout, so this file is the only window into what's happening).
"""

import logging
import os
import sys


def _log_path() -> str:
    """Where to write `sonos_caster.log`.

    For the PyInstaller --onefile build, __file__ points into the temp
    _MEIxxxxx extraction dir which gets DELETED when the exe exits — so a
    log written there is gone before the user can find it. Frozen builds
    therefore log next to the settings file in %APPDATA%\\SonosCaster\\, which
    is always user-writable (unlike, say, D:\\Program Files\\sonosCaster\\).
    Dev runs (python main.py) log next to the project root for convenience.
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "SonosCaster")
    else:
        d = os.path.dirname(os.path.abspath(__file__))
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        d = os.path.expanduser("~")
    return os.path.join(d, "sonos_caster.log")


LOG = _log_path()

# `filemode="w"` truncates the file at startup so each launch's log is
# self-contained — exactly what you want when asked to share it for diagnosis.
logging.basicConfig(
    filename=LOG,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    filemode="w",
)

logger = logging.getLogger("sonos_caster.main")


def main() -> None:
    logger.info("=== launch (capsule) ===")
    logger.info("log file path: %s", LOG)
    logger.info("frozen=%s, executable=%s", getattr(sys, "frozen", False),
                getattr(sys, "executable", ""))
    try:
        from sonos_caster.capsule import main as ui_main
        logger.info("starting capsule UI")
        ui_main()
        logger.info("UI closed")
    except Exception:
        logger.exception("FATAL")
        try:
            print("Fatal error — see sonos_caster.log", file=sys.stderr)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
