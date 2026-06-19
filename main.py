"""Entry point for Sonos Caster — floating capsule UI.

Forward Windows system audio to a Sonos speaker over its native protocol.
A small macOS-style floating pill: click the toggle to start/stop forwarding;
hover to expand for device / format / volume / settings.

Run:  python main.py   (or double-click run.bat)

Writes a startup log to sonos_caster.log for diagnosis (pythonw has no stdout).
"""

import os
import sys
import traceback

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sonos_caster.log")


def _log(msg: str) -> None:
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def main() -> None:
    _log("=== launch (capsule) ===")
    try:
        from sonos_caster.capsule import main as ui_main
        _log("starting capsule UI")
        ui_main()
        _log("UI closed")
    except Exception:
        _log("FATAL:\n" + traceback.format_exc())
        try:
            print("Fatal error — see sonos_caster.log", file=sys.stderr)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    try:
        open(LOG, "w", encoding="utf-8").close()
    except Exception:
        pass
    main()
