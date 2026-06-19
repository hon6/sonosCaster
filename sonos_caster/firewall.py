"""Ensure Windows lets Sonos reach this app's audio stream.

Sonos *pulls* the HTTP stream from this PC, so inbound connections must be
allowed. We add a PROGRAM-based firewall rule (allow this executable) rather
than a fixed-port rule — that way it keeps working no matter which port the app
picks (the port is chosen dynamically to avoid "port already in use").

Adding a rule needs admin rights. If we're not elevated, we relaunch just the
netsh command elevated via ShellExecute "runas" (a single UAC prompt), so it
works even when the app itself didn't start elevated.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from typing import Tuple

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
RULE_NAME = "SonosCaster"


def _run(args) -> Tuple[int, str]:
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, creationflags=_NO_WINDOW,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except Exception as e:
        return 1, str(e)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _app_path() -> str:
    """The executable to authorize. Frozen -> the exe; dev -> python.exe."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return sys.executable  # the venv python running this


def rule_exists() -> bool:
    code, out = _run([
        "netsh", "advfirewall", "firewall", "show", "rule", f"name={RULE_NAME}",
    ])
    if code != 0:
        return False
    # The rule's presence is shown by netsh echoing details. On English systems
    # that includes "Program"/"LocalPort"; on Chinese systems it's "程序"/"规则
    # 名称". The reliable cross-locale signal: a "No rules match"/"没有与..."
    # message is ABSENT and the rule name appears in the output.
    low = out.lower()
    not_found = ("no rules match" in low or "没有" in out or
                 "不存在" in out or len(out.strip()) < 20)
    return (not not_found) and (RULE_NAME.lower() in low)


def _netsh_add_args(program: str):
    # Allow this program inbound on all profiles, any local port.
    return [
        "advfirewall", "firewall", "add", "rule",
        f"name={RULE_NAME}", "dir=in", "action=allow",
        f"program={program}", "enable=yes", "profile=any",
    ]


def _elevated_netsh(args) -> bool:
    """Run `netsh <args>` elevated via a single UAC prompt. Returns True if the
    UAC prompt was accepted (we can't easily read the child's exit code)."""
    try:
        params = " ".join(f'"{a}"' if " " in a else a for a in args)
        # ShellExecuteW returns >32 on success (UAC accepted & launched).
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "netsh", params, None, 0  # SW_HIDE
        )
        return int(rc) > 32
    except Exception:
        return False


def ensure_firewall_rule(port: int = 0) -> Tuple[bool, str]:
    """Ensure a program-based inbound allow rule exists. `port` is ignored
    (kept for call-site compatibility) — we authorize the program, not a port.
    """
    if sys.platform != "win32":
        return True, "non-Windows: no firewall rule needed"
    if rule_exists():
        return True, "firewall rule already present"

    program = _app_path()
    add_args = _netsh_add_args(program)

    if is_admin():
        code, out = _run(["netsh"] + add_args)
        if code == 0:
            return True, "firewall rule added"
        return False, f"添加防火墙规则失败：{out[:200]}"

    # Not elevated — ask for elevation just for this netsh call (one UAC prompt).
    if _elevated_netsh(add_args):
        # Give Windows a moment, then verify.
        import time
        time.sleep(1.0)
        if rule_exists():
            return True, "firewall rule added (elevated)"
        return True, "已请求添加防火墙规则"
    return False, (
        "需要管理员权限放行防火墙。请右键以管理员身份运行，或手动放行本程序。"
    )
