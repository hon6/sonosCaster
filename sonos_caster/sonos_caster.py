"""Forward Windows system audio to a Sonos speaker via its native protocol.

This sidesteps AirPlay 2 entirely: we serve system audio as an HTTP MP3 stream
on the LAN and ask Sonos (over UPnP, via SoCo) to play that URL. Latency is
~1-2s (Sonos buffers for multi-room sync) — fine for music, not for video.
"""

from __future__ import annotations

import logging
import threading
import time as _time
from enum import Enum
from typing import Callable, List, Optional

import soco

from .capture import CaptureConfig
from .http_stream import AudioHTTPServer

log = logging.getLogger("sonos_caster.cast")


class CastState(Enum):
    IDLE = "idle"
    STARTING = "starting"
    PLAYING = "playing"
    STOPPING = "stopping"
    ERROR = "error"


StatusCallback = Callable[[CastState, str], None]


class SonosDevice:
    """Lightweight UI-facing wrapper around a discovered SoCo zone.

    Stores the speaker's STABLE uid (which never changes) alongside the current
    ip (which can change on reboot / DHCP lease change). All later operations
    re-resolve the live IP via the uid, so the app keeps working after the
    Sonos or router restarts.
    """

    def __init__(self, zone):
        self.zone = zone
        self.name = zone.player_name
        self.ip = zone.ip_address
        self.uid = zone.uid  # e.g. "RINCON_B8E93749876101400" — stable forever

    @property
    def model(self) -> str:
        try:
            return self.zone.get_speaker_info().get("model_name", "Sonos")
        except Exception:
            return "Sonos"


def discover_sonos(timeout: float = 5.0) -> List[SonosDevice]:
    """Discover Sonos *rooms* (one entry per group, deduped by room name).

    A surround set (e.g. Playbase + 2x Play:One) shares one room name; we show a
    single entry so the user picks the room, not three speakers.
    """
    zones = soco.discover(timeout=int(timeout)) or set()
    by_name = {}
    for z in zones:
        # Prefer the group coordinator as the representative of the room.
        try:
            rep = z.group.coordinator or z
        except Exception:
            rep = z
        by_name.setdefault(rep.player_name, SonosDevice(rep))
    devices = list(by_name.values())
    devices.sort(key=lambda d: d.name.lower())
    return devices


class SonosCaster:
    """Manages one forwarding session: HTTP stream + Sonos play_uri."""

    def __init__(
        self,
        status_cb: Optional[StatusCallback] = None,
        capture_config: Optional[CaptureConfig] = None,
        port: int = 8009,
        codec: str = "mp3",
        dim_local: bool = True,
        dim_level: float = 0.02,  # near-silent but non-zero so loopback works
        lan_ip_override: Optional[str] = None,
    ):
        self._status_cb = status_cb or (lambda s, m: None)
        self._capture_config = capture_config or CaptureConfig()
        self._port = port
        self._codec = codec
        self._dim_local = dim_local
        self._dim_level = dim_level
        self._lan_ip_override = lan_ip_override
        self._saved_volume: Optional[float] = None
        self._level_cb = None  # callback(float peak 0..1) for the GUI VU meter
        self._server: Optional[AudioHTTPServer] = None
        self._zone = None
        self._state = CastState.IDLE
        self._last_device = None       # for watchdog re-resolution
        self._replay = None            # closure to re-issue Play
        self._watchdog_stop = None

    @property
    def state(self) -> CastState:
        return self._state

    def set_level_callback(self, cb) -> None:
        """Register a callback(peak: float 0..1) fired per captured audio block."""
        self._level_cb = cb
        if self._server is not None:
            self._server.set_level_callback(cb)

    def _set_state(self, state: CastState, msg: str = "") -> None:
        self._state = state
        try:
            self._status_cb(state, msg)
        except Exception:
            pass

    @staticmethod
    def _locate_zone(device: "SonosDevice"):
        """Find the live SoCo zone for `device`, resolving its CURRENT ip.

        IPs change on reboot, so we re-discover and match by the stable uid.
        Falls back to the last-known ip if discovery misses it. Read-only;
        never modifies grouping.
        """
        import soco

        # 1. Try the cached ip first (fast path when nothing changed).
        try:
            z = soco.SoCo(device.ip)
            if z.uid == device.uid:
                return z
        except Exception:
            pass
        # 2. IP changed — re-discover and match by uid.
        try:
            for z in (soco.discover(timeout=5) or set()):
                if z.uid == device.uid:
                    device.ip = z.ip_address  # remember the new ip
                    return z
                # Also scan group members (surround slaves share the room).
                try:
                    for m in z.group.members:
                        if m.uid == device.uid:
                            device.ip = m.ip_address
                            return m
                except Exception:
                    pass
        except Exception:
            pass
        # 3. Last resort: cached ip even if uid check failed.
        return soco.SoCo(device.ip)

    @classmethod
    def _fresh_coordinator(cls, device: "SonosDevice", patience: float = 8.0):
        """Resolve the CURRENT group coordinator for `device`'s room.

        Only the coordinator accepts play_uri. The hard-won lesson: in a
        surround group the SoCo group topology takes a few seconds to warm up
        after a fresh SoCo() / discover(); during that window `group.coordinator`
        is None. That intermittent None — NOT a real coordinator change — was
        causing "can only be called on the coordinator" failures. So here we
        build a persistent SoCo from the device IP and PATIENTLY poll until the
        coordinator resolves, instead of giving up after one shot.

        Read-only; never modifies grouping.
        """
        import soco
        import time as _t

        z = cls._locate_zone(device)
        deadline = patience
        waited = 0.0
        while True:
            try:
                coord = z.group.coordinator
                if coord is not None and getattr(coord, "ip_address", None):
                    # Reuse the same object if it's already the coordinator to
                    # avoid rebuilding topology from scratch.
                    if coord.ip_address == z.ip_address:
                        return z
                    return soco.SoCo(coord.ip_address)
            except Exception:
                pass
            if waited >= deadline:
                # Give up waiting — fall back to the zone itself (often correct,
                # since the Playbase is usually the coordinator).
                return z
            _t.sleep(0.5)
            waited += 0.5

    def _play_on(self, zone, url, meta, title):
        # Use the low-level AVTransport SetAVTransportURI directly instead of
        # SoCo's play_uri. Research (SoCo issue #434, Sonos community) found that
        # play_uri fails on some streams (esp. WAV — title flips, position jumps
        # 0-3s, no playback) while a direct SetAVTransportURI + Play works. This
        # gives us full control over the DIDL metadata and avoids play_uri's
        # x-rincon-mp3radio rewriting (which caused crackle on live streams).
        if not meta:
            meta = (
                '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
                'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
                'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
                '<item id="0" parentID="-1" restricted="true">'
                f'<dc:title>{title}</dc:title>'
                '<upnp:class>object.item.audioItem.audioBroadcast'
                '</upnp:class></item></DIDL-Lite>'
            )
        try:
            zone.avTransport.SetAVTransportURI([
                ("InstanceID", 0),
                ("CurrentURI", url),
                ("CurrentURIMetaData", meta),
            ])
            zone.avTransport.Play([("InstanceID", 0), ("Speed", "1")])
        except Exception:
            # Fall back to play_uri if the low-level call isn't available.
            zone.play_uri(url, meta=meta, title=title)

    def start(self, device: SonosDevice) -> None:
        if self._state in (CastState.STARTING, CastState.PLAYING):
            return
        self._last_device = device
        try:
            self._set_state(CastState.STARTING, "正在定位设备…")
            # Resolve the live coordinator first (updates device.ip if the
            # speaker's address changed since discovery).
            coordinator = self._fresh_coordinator(device)
            sonos_ip = getattr(coordinator, "ip_address", device.ip)

            self._set_state(CastState.STARTING, "正在启动音频流…")
            self._server = AudioHTTPServer(
                sonos_ip=sonos_ip,
                port=self._port,
                capture_config=self._capture_config,
                codec=self._codec,
                lan_ip_override=self._lan_ip_override,
            )
            if self._level_cb is not None:
                self._server.set_level_callback(self._level_cb)
            self._server.start()

            url = self._server.stream_url
            self._set_state(CastState.STARTING, f"通知 Sonos 播放：{url}")

            # DIDL metadata so Sonos shows a title instead of nothing.
            meta = (
                '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
                'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
                'xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/" '
                'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
                '<item id="0" parentID="-1" restricted="true">'
                '<dc:title>电脑音频 (PC Audio)</dc:title>'
                '<upnp:class>object.item.audioItem.audioBroadcast</upnp:class>'
                '<desc id="cdudn" '
                'nameSpace="urn:schemas-rinconnetworks-com:metadata-1-0/">'
                'RINCON_AssociatedZPUDN</desc>'
                '</item></DIDL-Lite>'
            )
            title = "电脑音频 (PC Audio)"

            # In a surround group (Playbase + 2x Play:One + Boost) only the
            # current coordinator accepts play_uri. _fresh_coordinator now waits
            # patiently for the topology to warm up, but as a final safety net we
            # also try every group member if the chosen target is rejected.
            last_exc = None
            played = False
            for attempt in range(3):
                self._set_state(
                    CastState.STARTING, f"定位协调器… ({attempt + 1}/3)"
                )
                target = self._fresh_coordinator(device)
                # Build a candidate list: the resolved coordinator first, then
                # all group members (in case the topology mislabeled it).
                candidates = [target]
                try:
                    for m in target.group.members:
                        if m not in candidates:
                            candidates.append(m)
                except Exception:
                    pass
                for cand in candidates:
                    try:
                        self._play_on(cand, url, meta, title)
                        self._zone = cand
                        played = True
                        break
                    except Exception as exc:
                        last_exc = exc
                        if "coordinator" not in str(exc).lower():
                            raise
                if played:
                    break
                _time.sleep(1.0)
            if not played:
                raise last_exc or RuntimeError("无法在协调器上启动播放")

            # Dip the local PC volume so you don't hear both at once. We lower
            # rather than mute, so WASAPI loopback keeps capturing audio for
            # Sonos. Saved level is restored on stop().
            if self._dim_local:
                self._dim_local_volume()

            self._set_state(CastState.PLAYING, "正在转发到 Sonos…")
            # Remember how to re-issue Play, and start the reconnect watchdog.
            self._replay = lambda: self._play_on(self._zone, url, meta, title)
            self._start_watchdog()
        except Exception as exc:
            self._set_state(CastState.ERROR, f"出错：{exc}")
            self.stop()

    def _start_watchdog(self):
        """Auto-recover if the Sonos stops pulling the stream.

        Sonos sometimes drops the HTTP connection after a while (re-buffer,
        transient) and doesn't reconnect on its own -> silence until the user
        toggles off/on. The watchdog detects 'no client connected for a few
        seconds while we're supposed to be playing' and re-issues Play so Sonos
        reconnects automatically.
        """
        self._watchdog_stop = threading.Event()

        def run():
            grace = 0
            # Give Sonos a moment to make the first connection after Play.
            _time.sleep(6)
            while not self._watchdog_stop.is_set():
                if self._state != CastState.PLAYING or self._server is None:
                    break
                try:
                    n = self._server.client_count()
                except Exception:
                    n = 1
                if n == 0:
                    grace += 1
                    # Wait ~10s of no-connection before re-Playing. A re-Play
                    # produces a brief audible gap, so we want to be sure the
                    # connection really is dead — Sonos occasionally re-buffers
                    # mid-stream for a couple seconds and would otherwise look
                    # like a disconnect.
                    if grace >= 5:
                        log.warning(
                            "watchdog: no client for ~10s, re-issuing Play "
                            "(this is the 'restart' the user sees)"
                        )
                        try:
                            self._set_state(CastState.PLAYING, "重新连接 Sonos…")
                            target = self._fresh_coordinator_safe()
                            if target is not None and self._replay:
                                # Re-resolve coordinator and replay.
                                self._zone = target
                                self._replay_now()
                        except Exception:
                            log.exception("watchdog re-Play failed")
                        grace = 0
                else:
                    grace = 0
                self._watchdog_stop.wait(2.0)

        threading.Thread(target=run, name="SonosWatchdog", daemon=True).start()

    def _fresh_coordinator_safe(self):
        try:
            if self._last_device is not None:
                return self._fresh_coordinator(self._last_device)
        except Exception:
            pass
        return self._zone

    def _replay_now(self):
        try:
            self._replay()
        except Exception:
            pass

    def _dim_local_volume(self) -> None:
        try:
            from . import sysvolume
            cur = sysvolume.get_volume()
            if cur is not None:
                self._saved_volume = cur
                sysvolume.set_volume(self._dim_level)
        except Exception:
            pass

    def _restore_local_volume(self) -> None:
        if self._saved_volume is None:
            return
        try:
            from . import sysvolume
            sysvolume.set_volume(self._saved_volume)
        except Exception:
            pass
        finally:
            self._saved_volume = None

    def stop(self) -> None:
        if self._state in (CastState.IDLE, CastState.STOPPING):
            # still attempt cleanup
            pass
        self._set_state(CastState.STOPPING, "正在停止…")
        # Stop the reconnect watchdog so it doesn't re-Play after we stop.
        if self._watchdog_stop is not None:
            self._watchdog_stop.set()
        # Restore the local volume first so the user always gets sound back even
        # if Sonos teardown is slow.
        self._restore_local_volume()
        if self._zone is not None:
            try:
                self._zone.stop()
            except Exception:
                pass
        if self._server is not None:
            self._server.stop()
            self._server = None
        self._zone = None
        self._set_state(CastState.IDLE, "已停止")

    def set_volume(self, level_0_to_100: float) -> None:
        if self._zone is not None:
            try:
                self._zone.volume = int(max(0, min(100, level_0_to_100)))
            except Exception:
                pass
