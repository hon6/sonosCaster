"""Serve live system audio as an endless HTTP MP3 stream for Sonos.

Sonos plays audio by *pulling* an HTTP URL (like an internet radio station).
So we:

  1. Capture system audio (WASAPI loopback) -> int16 PCM.
  2. Pipe PCM through ffmpeg -> continuous MP3.
  3. Expose that MP3 as http://<lan-ip>:<port>/stream.mp3
  4. Tell Sonos (via SoCo) to play that URL.

The server fans out the single ffmpeg MP3 output to any connected client via
per-client queues, so reconnects / multiple Sonos zones all work.
"""

from __future__ import annotations

import logging
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Queue
from typing import List, Optional

log = logging.getLogger("sonos_caster.http_stream")

from .capture import CaptureConfig, LoopbackCapture
from .ffmpeg_util import find_ffmpeg

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _wav_header(samplerate: int, channels: int, bits: int = 16) -> bytes:
    """Build a streaming WAV header with a ~4GB data size.

    For a live (non-seekable) stream we can't know the final length, so we
    declare the maximum (the swyh-rs trick): RIFF size 0xFFFFFFFF and data size
    0xFFFFFFFF. Sonos accepts this as a continuous stream and plays it, whereas
    ffmpeg's pipe WAV (length 0) is rejected (stays STOPPED).
    """
    import struct

    byte_rate = samplerate * channels * bits // 8
    block_align = channels * bits // 8
    big = 0xFFFFFFFF
    return (
        b"RIFF" + struct.pack("<I", big) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH",
                                16,            # fmt chunk size
                                1,             # PCM
                                channels,
                                samplerate,
                                byte_rate,
                                block_align,
                                bits)
        + b"data" + struct.pack("<I", big)
    )


def _all_ipv4() -> list:
    """All local IPv4 addresses (best-effort)."""
    addrs = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       family=socket.AF_INET):
            addrs.add(info[4][0])
    except Exception:
        pass
    return [a for a in addrs if not a.startswith("127.")]


def get_lan_ip(target_ip: str = "10.168.1.166", override: str = None) -> str:
    """Return the local IP Sonos should connect back to.

    Order of preference:
      1. An explicit user override (set in settings) — wins always.
      2. An address on the SAME /24 subnet as the Sonos. Hosts that run
         VMware/WSL/Tailscale have many NICs (169.254.x, 172.x, 100.x) and the
         naive routing trick can pick an unreachable one; matching the Sonos's
         subnet is far more reliable.
      3. The UDP-connect routing trick.
      4. Hostname resolution.
    """
    if override:
        return override

    # 2. Same-subnet match.
    try:
        sonos_prefix = ".".join(target_ip.split(".")[:3]) + "."
        for ip in _all_ipv4():
            if ip.startswith(sonos_prefix):
                return ip
    except Exception:
        pass

    # 3. Routing trick.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target_ip, 9))
        cand = s.getsockname()[0]
        if not cand.startswith("127."):
            return cand
    except Exception:
        pass
    finally:
        s.close()

    # 4. Fallback.
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


class _Broadcaster:
    """Fans the live audio stream out to HTTP clients — CONTINUOUS, not choppy.

    Design: feed Sonos a smooth, uninterrupted stream and let Sonos manage its
    own playback buffer (it reads ahead ~1-2s, then plays at realtime; TCP
    backpressure paces us). Our producer (ffmpeg fed by realtime loopback) is
    inherently realtime, so a modest bounded queue self-paces without unbounded
    latency growth.

    We do NOT proactively drop mid-stream — that was the cause of "silence, then
    a burst of fast audio, then silence" (buffer underrun + catch-up). We only
    drop the single oldest chunk if a client's queue is genuinely full, which is
    rare and inaudible.
    """

    # Broadcast buffer headroom. ~750 ms at blocksize=512 — small enough that
    # if Sonos's pull stalls we drop ONE chunk per arrival (audible but
    # recovers) instead of accumulating seconds of stale audio that then
    # cascades into many drops in a row (which sounds like "escalating
    # stutter"). The original code used this size; making it larger to
    # tolerate jitter ended up MAKING the cascade worse.
    _MAX_QUEUE = 64

    def __init__(self):
        self._clients: List[Queue] = []
        self._lock = threading.Lock()
        self._drop_count = 0

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def add_client(self) -> Queue:
        q: Queue = Queue(maxsize=self._MAX_QUEUE)
        with self._lock:
            self._clients.append(q)
        return q

    def remove_client(self, q: Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def publish(self, data: bytes) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(data)
            except Exception:
                # Queue full: drop exactly one oldest chunk to make room.
                try:
                    q.get_nowait()
                    q.put_nowait(data)
                    self._drop_count = getattr(self, "_drop_count", 0) + 1
                except Exception:
                    pass


class AudioHTTPServer:
    """Runs ffmpeg + an HTTP server that streams live system audio as MP3."""

    def __init__(
        self,
        sonos_ip: str,
        port: int = 8009,
        capture_config: Optional[CaptureConfig] = None,
        bitrate: str = "256k",
        codec: str = "mp3",  # "mp3" or "wav" (wav = uncompressed PCM, lower
                              # encode latency but ~5x bandwidth)
        lan_ip_override: Optional[str] = None,
    ):
        self.sonos_ip = sonos_ip
        self.port = port
        self.capture_config = capture_config or CaptureConfig()
        self.bitrate = bitrate
        self.codec = codec

        self._broadcaster = _Broadcaster()
        self._capture: Optional[LoopbackCapture] = None
        self._ffmpeg: Optional[subprocess.Popen] = None
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._http_thread: Optional[threading.Thread] = None
        self._pump_thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._level_cb = None  # optional callback(float peak 0..1) for a VU meter
        self._connections = []  # remote IPs that GET'd the stream (diagnostics)
        self.lan_ip = get_lan_ip(sonos_ip, override=lan_ip_override)

    def client_count(self) -> int:
        """How many clients (Sonos) are currently pulling the stream."""
        return self._broadcaster.client_count()

    @property
    def _ext(self) -> str:
        return {"wav": "wav", "flac": "flac"}.get(self.codec, "mp3")

    @property
    def _content_type(self) -> str:
        return {"wav": "audio/wav",
                "flac": "audio/flac"}.get(self.codec, "audio/mpeg")

    @property
    def stream_url(self) -> str:
        return f"http://{self.lan_ip}:{self.port}/stream.{self._ext}"

    # ----- lifecycle -----------------------------------------------------

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()

        cfg = self.capture_config

        # WAV mode: raw int16 PCM straight to clients after a 4GB-length WAV
        # header (swyh-rs trick). Two previous attempts to insert an ffmpeg
        # drift-absorbing pass didn't actually help — the raw s16le demuxer
        # ignores -use_wallclock_as_timestamps, so the aresample async filter
        # saw zero drift to correct. Better to keep the pipeline simple and
        # add diagnostic logging so we can see WHAT is actually causing the
        # stutter the user reports.
        if self.codec == "wav":
            self._wav_header = _wav_header(cfg.samplerate, cfg.channels, 16)
            self._capture = LoopbackCapture(cfg)
            self._capture.start(on_pcm=self._feed_raw)
            self._start_http()
            self._start_diagnostics()
            return

        # 1. ffmpeg: raw PCM in -> MP3/FLAC out (continuous).
        ffmpeg_path = find_ffmpeg()
        common_in = [
            ffmpeg_path, "-hide_banner", "-loglevel", "error",
            # Minimise input-side buffering/probing latency.
            "-fflags", "nobuffer", "-flags", "low_delay",
            "-avioflags", "direct", "-max_delay", "0",
            "-f", "s16le", "-ar", str(cfg.samplerate),
            "-ac", str(cfg.channels), "-i", "pipe:0",
        ]
        if self.codec == "wav":
            # Raw PCM WAV: no encoder latency. Use a fixed huge RIFF size so the
            # streamed (non-seekable) header is still valid and Sonos accepts it
            # as a continuous stream instead of a zero-length file.
            out_args = [
                "-f", "wav", "-codec:a", "pcm_s16le",
                "-flush_packets", "1", "-avioflags", "direct",
                "pipe:1",
            ]
        elif self.codec == "flac":
            # FLAC: lossless, low encode latency, proper streaming container.
            # Low-latency tuning: smaller frames flush sooner; fastest compress
            # level (0) minimises encode time; no padding/seektable overhead.
            out_args = [
                "-f", "flac", "-codec:a", "flac",
                "-frame_size", "512",          # smaller frame -> lower latency
                "-compression_level", "0",     # fastest encode (lossless still)
                "-flush_packets", "1",
                "-avioflags", "direct", "pipe:1",
            ]
        else:
            bitrate = {
                "mp3_128": "128k",
                "mp3_320": "320k",
            }.get(self.codec, self.bitrate)  # default "mp3" -> 256k
            out_args = [
                "-f", "mp3", "-codec:a", "libmp3lame", "-b:a", bitrate,
                "-reservoir", "0", "-flush_packets", "1",
                "-avioflags", "direct", "-fflags", "flush_packets",
                "pipe:1",
            ]
        self._ffmpeg = subprocess.Popen(
            common_in + out_args,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=0, creationflags=_NO_WINDOW,
        )

        # 2. Capture -> ffmpeg stdin.
        self._capture = LoopbackCapture(cfg)
        self._capture.start(on_pcm=self._feed_ffmpeg)

        # 3. ffmpeg stdout -> broadcaster.
        self._pump_thread = threading.Thread(
            target=self._pump_mp3, name="MP3Pump", daemon=True
        )
        self._pump_thread.start()

        # 4. HTTP server.
        self._start_http()

    def _feed_raw(self, pcm: bytes) -> None:
        """Raw-WAV path: int16 PCM straight to the broadcaster (no ffmpeg)."""
        if self._level_cb is not None:
            try:
                self._level_cb(self._peak_level(pcm))
            except Exception:
                pass
        self._broadcaster.publish(pcm)

    def _start_http(self):
        broadcaster = self._broadcaster
        running = self._running
        content_type = self._content_type
        # In raw-WAV mode each new client must receive the WAV header first.
        wav_header = getattr(self, "_wav_header", None)

        server_self = self

        class Handler(BaseHTTPRequestHandler):
            # HTTP/1.0 + Connection: close = classic endless-radio-stream
            # semantics (client reads until the socket closes). Avoids the
            # HTTP/1.1 requirement for Content-Length or chunked encoding, which
            # we can't provide for an infinite stream.
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):  # silence console logging
                pass

            def _stream_headers(self):
                # Headers a Sonos streaming/radio source is expected to send for
                # an endless live stream: correct content-type, no caching, and
                # crucially NO Content-Length (the stream never ends). We also
                # advertise that ranges are not supported so Sonos doesn't try a
                # ranged GET and fail.
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-cache, no-store")
                self.send_header("Accept-Ranges", "none")
                self.send_header("Connection", "close")

            def do_HEAD(self):
                # Sonos often sends a HEAD probe BEFORE streaming. The old server
                # didn't answer HEAD -> Sonos could reject the stream (esp. WAV),
                # which looked like "WAV doesn't play". Answer it properly.
                if not self.path.startswith("/stream"):
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self._stream_headers()
                self.end_headers()

            def do_GET(self):
                if not self.path.startswith("/stream"):
                    self.send_response(404)
                    self.end_headers()
                    return
                # Log who connected (so diagnostics can tell if the SONOS
                # actually reached us vs. only localhost self-fetch). Bound the
                # history so long-running sessions don't slowly leak memory via
                # this list growing on every Sonos reconnect.
                peer = self.client_address[0] if self.client_address else "?"
                server_self._connections.append(peer)
                if len(server_self._connections) > 16:
                    del server_self._connections[:-16]
                self.send_response(200)
                self._stream_headers()
                self.end_headers()
                # Disable Nagle so small chunks are sent immediately (latency).
                # Also enable TCP keepalive so a dead Sonos connection is
                # detected in minutes, not the OS default of ~2 hours — without
                # this, a stale TCP from a power-cycled Sonos can keep
                # client_count > 0 forever, hiding it from the watchdog.
                try:
                    import socket as _sock
                    self.connection.setsockopt(
                        _sock.IPPROTO_TCP, _sock.TCP_NODELAY, 1
                    )
                    self.connection.setsockopt(
                        _sock.SOL_SOCKET, _sock.SO_KEEPALIVE, 1
                    )
                except Exception:
                    pass
                q = broadcaster.add_client()
                try:
                    # Raw-WAV: send the WAV header once, then the PCM stream.
                    if wav_header is not None:
                        self.wfile.write(wav_header)
                        self.wfile.flush()
                    while running.is_set():
                        try:
                            chunk = q.get(timeout=1.0)
                        except Empty:
                            continue
                        # Send continuously. Do NOT skip ahead — let Sonos pace
                        # via its own buffer + TCP backpressure. Skipping caused
                        # underruns (silence then fast catch-up).
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    broadcaster.remove_client(q)

        # Bind to the requested port; if it's taken, fall back to an OS-chosen
        # free port (port=0) so a busy 8009 never breaks playback.
        try:
            self._httpd = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        except OSError:
            self._httpd = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        # Record the ACTUAL bound port (matters when we fell back to 0, and the
        # stream URL must use it).
        self.port = self._httpd.server_address[1]
        self._http_thread = threading.Thread(
            target=self._httpd.serve_forever, name="AudioHTTP", daemon=True
        )
        self._http_thread.start()

    def _feed_ffmpeg(self, pcm: bytes) -> None:
        # Tap the PCM for a level meter before sending it onward.
        if self._level_cb is not None:
            try:
                self._level_cb(self._peak_level(pcm))
            except Exception:
                pass
        proc = self._ffmpeg
        if proc is None or proc.stdin is None:
            return
        try:
            proc.stdin.write(pcm)
        except (BrokenPipeError, ValueError, OSError):
            if self._capture is not None:
                self._capture.stop()

    @staticmethod
    def _peak_level(pcm: bytes) -> float:
        """Return a 0.0–1.0 peak amplitude for a block of int16 PCM."""
        if not pcm:
            return 0.0
        import numpy as np
        a = np.frombuffer(pcm, dtype="<i2")
        if a.size == 0:
            return 0.0
        return float(np.max(np.abs(a))) / 32768.0

    def set_level_callback(self, cb) -> None:
        self._level_cb = cb

    def _start_diagnostics(self) -> None:
        """Log queue depth + drop count every 5s. Lets us see, from a real
        user's session log, whether stutter comes from (a) drops because the
        producer outpaces Sonos (depth=64, drops climbing), (b) Sonos
        stalling and reconnecting (depth bounces 0..64), or (c) something
        upstream of the broadcaster entirely (depth stays low, drops=0).
        """
        threading.Thread(
            target=self._monitor_loop, name="Monitor", daemon=True,
        ).start()

    def _monitor_loop(self) -> None:
        last_drops = 0
        log.info("monitor: streaming started (queue_max=%d)", self._broadcaster._MAX_QUEUE)
        while self._running.is_set():
            time.sleep(5)
            if not self._running.is_set():
                break
            try:
                with self._broadcaster._lock:
                    depths = [q.qsize() for q in self._broadcaster._clients]
                drops = getattr(self._broadcaster, "_drop_count", 0)
                delta = drops - last_drops
                last_drops = drops
                clients = self.client_count()
                log.info(
                    "depths=%s drops_5s=%d total_drops=%d clients=%d",
                    depths, delta, drops, clients,
                )
            except Exception as e:
                log.warning("monitor error: %s", e)

    def _pump_mp3(self) -> None:
        proc = self._ffmpeg
        if proc is None or proc.stdout is None:
            return
        # Read in frame-aligned chunks. For WAV/PCM each stereo int16 frame is
        # channels*2 bytes; reading a multiple keeps L/R alignment intact even
        # when the broadcaster drops chunks to stay real-time. ~256 frames is
        # ~6ms — low latency without per-byte syscall overhead.
        # Frame-aligned for WAV so dropped chunks never desync L/R; small for
        # low latency.
        read_size = (self.capture_config.channels * 2 * 128) \
            if self.codec == "wav" else 512
        try:
            while self._running.is_set():
                chunk = proc.stdout.read(read_size)
                if not chunk:
                    break
                self._broadcaster.publish(chunk)
        except Exception:
            pass

    def stop(self) -> None:
        if not self._running.is_set():
            return
        self._running.clear()

        if self._capture is not None:
            self._capture.stop()
            self._capture = None

        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

        if self._ffmpeg is not None:
            try:
                if self._ffmpeg.stdin and not self._ffmpeg.stdin.closed:
                    self._ffmpeg.stdin.close()
            except Exception:
                pass
            try:
                self._ffmpeg.terminate()
            except Exception:
                pass
            self._ffmpeg = None

    @property
    def running(self) -> bool:
        return self._running.is_set()
