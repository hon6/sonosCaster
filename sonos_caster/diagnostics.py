"""Self-diagnostics — writes a report so we can see WHY there's no sound on a
machine where we can't run scripts (e.g. the user's host PC).

Checks: ffmpeg, audio devices + live capture level, local IPs, chosen stream IP,
firewall rule presence, Sonos discovery + coordinator, and whether the served
stream is self-reachable. Saves to the Desktop as SonosCaster_诊断.txt.
"""

from __future__ import annotations

import os
import socket
import sys
import time
import traceback


def _line(f, msg=""):
    f.write(msg + "\n")


def run_diagnostics(cfg) -> str:
    """Run all checks, write a report file, return its path."""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        desktop = os.path.expanduser("~")
    path = os.path.join(desktop, "SonosCaster_诊断.txt")

    with open(path, "w", encoding="utf-8") as f:
        _line(f, "===== SonosCaster 诊断报告 =====")
        _line(f, f"frozen(打包运行): {getattr(sys, 'frozen', False)}")
        _line(f, f"exe/py: {sys.executable}")
        _line(f)

        # 1. ffmpeg
        _line(f, "--- 1. ffmpeg ---")
        try:
            from .ffmpeg_util import find_ffmpeg
            ff = find_ffmpeg()
            _line(f, f"ffmpeg: {ff}  存在={os.path.exists(ff)}")
        except Exception as e:
            _line(f, f"ffmpeg 未找到: {e}")
        _line(f)

        # 2. 管理员 + 防火墙
        _line(f, "--- 2. 权限 / 防火墙 ---")
        try:
            from . import firewall
            _line(f, f"是否管理员: {firewall.is_admin()}")
            _line(f, f"防火墙规则存在: {firewall.rule_exists()}")
        except Exception as e:
            _line(f, f"防火墙检查出错: {e}")
        _line(f)

        # 3. 音频设备 + 实时电平
        _line(f, "--- 3. 音频设备 (保持在播放声音) ---")
        try:
            import numpy as np
            import soundcard as sc
            _line(f, f"默认扬声器: {sc.default_speaker().name}")
            chosen = cfg.get("audio_device")
            _line(f, f"配置选择的音频来源: {chosen or '(系统默认)'}")
            _line(f, "各输出设备 loopback 电平 (含真实声道数检测):")
            for sp in sc.all_speakers():
                ch_info = ""
                try:
                    # Probe how many channels the device really delivers — a
                    # mismatch with our assumed stereo can break the WAV header.
                    mic = sc.get_microphone(id=sp.name, include_loopback=True)
                    with mic.recorder(samplerate=44100, channels=None,
                                      blocksize=1024) as rec:
                        fr = rec.record(numframes=4096)
                    real_ch = fr.shape[1] if fr.ndim == 2 else 1
                    ch_info = f" 实际声道={real_ch}"
                except Exception:
                    real_ch = "?"
                try:
                    mic = sc.get_microphone(id=sp.name, include_loopback=True)
                    with mic.recorder(samplerate=44100, channels=2,
                                      blocksize=1024) as rec:
                        frames = rec.record(numframes=22050)
                    peak = float(np.max(np.abs(frames))) if frames.size else 0.0
                except Exception as e:
                    peak = -1.0
                flag = "  <== 有声音!" if peak > 0.001 else ""
                _line(f, f"    peak={peak:.4f}{ch_info}  {sp.name}{flag}")
        except Exception as e:
            _line(f, f"音频设备检查出错: {e}\n{traceback.format_exc()}")
        _line(f)

        # 3b. 是否有多个实例在跑（抢流/抢端口的常见原因）
        _line(f, "--- 3b. SonosCaster 进程数 ---")
        try:
            import subprocess as _sp
            out = _sp.run(["tasklist", "/fi", "imagename eq SonosCaster.exe"],
                          capture_output=True, text=True,
                          creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)).stdout
            n = out.count("SonosCaster.exe")
            _line(f, f"正在运行的 SonosCaster.exe 实例数: {n}")
            if n > 1:
                _line(f, "  ⚠ 多个实例会抢同一个 Sonos/端口 -> 没声/没电平/只能一种格式!")
        except Exception as e:
            _line(f, f"进程检查出错: {e}")
        _line(f)

        # 4. 本机 IP + 选中的流 IP
        _line(f, "--- 4. 网络 IP ---")
        try:
            from .http_stream import _all_ipv4, get_lan_ip
            _line(f, f"本机所有 IPv4: {_all_ipv4()}")
            _line(f, f"配置手动IP: {cfg.get('lan_ip') or '(自动)'}")
        except Exception as e:
            _line(f, f"IP 检查出错: {e}")
        _line(f)

        # 5. Sonos 发现 + 协调器 + 流可达性
        _line(f, "--- 5. Sonos ---")
        try:
            from .sonos_caster import discover_sonos, SonosCaster
            from .http_stream import get_lan_ip
            devs = discover_sonos(timeout=6)
            _line(f, f"发现 Sonos 房间数: {len(devs)}")
            for d in devs:
                _line(f, f"    {d.name} @ {d.ip} (uid={d.uid})")
            if devs:
                d = devs[0]
                lan = get_lan_ip(d.ip, override=cfg.get("lan_ip"))
                _line(f, f"将用于回连的本机IP: {lan}")
                _line(f, f"(Sonos {d.ip} 与本机 {lan} 同网段: "
                         f"{lan.rsplit('.',1)[0] == d.ip.rsplit('.',1)[0]})")
                coord = SonosCaster._fresh_coordinator(d)
                _line(f, f"当前协调器IP: {getattr(coord,'ip_address','?')}")
        except Exception as e:
            _line(f, f"Sonos 检查出错: {e}\n{traceback.format_exc()}")
        _line(f)

        # 6. NON-INTRUSIVE reachability check. Does NOT command the Sonos and
        # does NOT touch its grouping — it only starts the local HTTP audio
        # server and checks the stream is reachable via the chosen LAN IP (what
        # Sonos would do). This never disturbs playback / surround grouping.
        _line(f, "--- 6. 流可达性检查 (不命令Sonos, 不影响环绕声) ---")
        try:
            import urllib.request
            from .capture import CaptureConfig
            from .http_stream import AudioHTTPServer, get_lan_ip
            from .sonos_caster import discover_sonos
            devs = discover_sonos(timeout=4)
            lan = (get_lan_ip(devs[0].ip, override=cfg.get("lan_ip"))
                   if devs else cfg.get("lan_ip") or "127.0.0.1")
            srv = AudioHTTPServer(
                sonos_ip=devs[0].ip if devs else "127.0.0.1",
                capture_config=CaptureConfig(
                    blocksize=int(cfg.get("blocksize", 64)),
                    device_name=cfg.get("audio_device")),
                codec=cfg.get("codec", "wav"),
                lan_ip_override=cfg.get("lan_ip"),
            )
            srv.start()
            time.sleep(1.5)
            url = srv.stream_url
            _line(f, f"流地址: {url}")
            # Fetch via the actual LAN IP (not localhost) — this is the path the
            # Sonos uses. If THIS works, the port is reachable on the LAN.
            for label, test_url in [("本机localhost", url.replace(lan, "127.0.0.1")),
                                    ("经局域网IP", url)]:
                try:
                    t0 = time.time()
                    data = urllib.request.urlopen(test_url, timeout=5).read(65536)
                    dt = time.time() - t0
                    _line(f, f"  {label} {test_url}: 收到 {len(data)} 字节, "
                             f"{len(data)/1024/dt:.0f} KB/s")
                except Exception as e:
                    _line(f, f"  {label} {test_url}: 失败 -> {e}")
            srv.stop()
            _line(f, ">>> 两个都成功=端口在局域网可达; '经局域网IP'失败=防火墙/网卡拦截入站")
        except Exception as e:
            _line(f, f"可达性检查出错: {e}\n{traceback.format_exc()}")
        _line(f)

        _line(f, "===== 报告结束 =====")
    return path
