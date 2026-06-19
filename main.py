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

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sonos_caster.log")

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
