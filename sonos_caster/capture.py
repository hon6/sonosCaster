"""Capture Windows system audio via WASAPI loopback.

`soundcard` exposes the default speaker as a loopback "microphone", letting us
record exactly what the PC is playing. We grab float32 frames, downmix/resample
expectations are handled downstream by ffmpeg, so here we only deal with raw
interleaved PCM.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import soundcard as sc

log = logging.getLogger("sonos_caster.capture")


@dataclass
class CaptureConfig:
    samplerate: int = 44100  # RAOP/ALAC classic rate
    channels: int = 2
    # Block size (frames per read). 64 is ultra-low latency but on REAL sound
    # cards (not the VM's virtual card) it causes constant under-runs ->
    # "data discontinuity" -> crackle/dropouts on the Sonos. 512 (~12ms) is the
    # robust default that stays low-latency while feeding a continuous stream.
    # The GUI lets advanced users drop it to 64/128 if their hardware allows.
    blocksize: int = 512  # frames per read
    # Output device NAME to capture (WASAPI loopback). None = system default.
    # Lets the user pick the right device (e.g. headphones) when the default
    # isn't where their audio actually plays.
    device_name: Optional[str] = None


class LoopbackCapture:
    """Streams system-audio PCM from the default output device.

    Usage:
        cap = LoopbackCapture()
        cap.start(on_pcm=lambda data: ...)   # data: bytes of int16 LE interleaved
        ...
        cap.stop()
    """

    def __init__(self, config: Optional[CaptureConfig] = None):
        self.config = config or CaptureConfig()
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._on_pcm: Optional[Callable[[bytes], None]] = None
        self._error: Optional[Exception] = None

    @staticmethod
    def default_speaker_name() -> str:
        try:
            return sc.default_speaker().name
        except Exception:  # pragma: no cover - hardware dependent
            return "(unknown output device)"

    def start(self, on_pcm: Callable[[bytes], None]) -> None:
        if self._running.is_set():
            return
        self._on_pcm = on_pcm
        self._error = None
        self._running.set()
        self._thread = threading.Thread(
            target=self._run, name="LoopbackCapture", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        """Capture loop with auto-reconnect.

        Closing a browser tab (or any app ending its audio session) can reset
        the WASAPI audio engine, which makes the active loopback recorder throw.
        Instead of giving up, we rebuild the recorder and keep going, so the
        forward survives tab switches without the user restarting it.

        While the recorder is briefly unavailable we emit digital silence so the
        downstream ffmpeg/HTTP stream never hits EOF (which would stop Sonos).
        """
        cfg = self.config
        silence = self._silence_block()
        consecutive_failures = 0
        # Current effective blocksize — we'll halve it on repeated open-failures
        # so a too-large request (e.g. 1024 on a card that only accepts 512)
        # downgrades automatically instead of going completely silent.
        active_bs = cfg.blocksize
        log.info("capture loop starting (samplerate=%d, ch=%d, blocksize=%d, device=%r)",
                 cfg.samplerate, cfg.channels, active_bs, cfg.device_name)

        # soundcard emits a noisy "data discontinuity in recording" warning on
        # any tiny timing hiccup; it is harmless and would otherwise flood the
        # console. Silence just that warning class.
        import warnings
        try:
            from soundcard import SoundcardRuntimeWarning
            warnings.filterwarnings("ignore", category=SoundcardRuntimeWarning)
        except Exception:
            warnings.filterwarnings("ignore", message=".*data discontinuity.*")

        while self._running.is_set():
            try:
                dev_name = cfg.device_name
                if dev_name:
                    # Match a chosen output device by (partial) name.
                    match = None
                    for sp in sc.all_speakers():
                        if sp.name == dev_name:
                            match = sp.name
                            break
                    if match is None:
                        for sp in sc.all_speakers():
                            if dev_name in sp.name or sp.name in dev_name:
                                match = sp.name
                                break
                    speaker_name = match or sc.default_speaker().name
                else:
                    speaker_name = sc.default_speaker().name
                loopback = sc.get_microphone(
                    id=speaker_name, include_loopback=True
                )
                # Record at the device's NATIVE channel layout (channels=None),
                # then force to exactly cfg.channels below. On some hosts the
                # device isn't plain stereo; asking soundcard for 2ch directly
                # can yield mismatched/empty frames -> no level + a WAV header
                # whose channel count doesn't match the bytes (Sonos rejects it,
                # but MP3 re-encode hides it). Recording native + normalising
                # ourselves fixes both the missing meter and WAV playback.
                with loopback.recorder(
                    samplerate=cfg.samplerate,
                    channels=None,
                    blocksize=active_bs,
                ) as rec:
                    consecutive_failures = 0
                    log.info("recorder opened on %r with blocksize=%d",
                             speaker_name, active_bs)
                    while self._running.is_set():
                        frames = rec.record(numframes=active_bs)
                        pcm16 = self._float_to_int16(frames, cfg.channels)
                        if self._on_pcm is not None:
                            self._on_pcm(pcm16)
            except Exception as exc:
                # Recorder died (likely an audio-session change OR the
                # requested blocksize is unsupported by this device).
                self._error = exc
                consecutive_failures += 1
                if not self._running.is_set():
                    break
                # If failures pile up fast, the blocksize is probably the
                # problem (audio-session changes are sporadic, not 5+ in a
                # row). Halve it on every 5 consecutive failures down to a
                # floor of 128.
                if consecutive_failures % 5 == 0 and active_bs > 128:
                    new_bs = max(128, active_bs // 2)
                    log.warning(
                        "%d consecutive recorder failures at blocksize=%d "
                        "(%s); downgrading to %d",
                        consecutive_failures, active_bs, exc, new_bs,
                    )
                    active_bs = new_bs
                    silence = (b"\x00\x00" * cfg.channels) * active_bs
                else:
                    log.debug("recorder failure %d: %s",
                              consecutive_failures, exc)
                if self._on_pcm is not None:
                    # ~50ms of silence to bridge the gap.
                    for _ in range(8):
                        if not self._running.is_set():
                            break
                        self._on_pcm(silence)
                # Brief backoff; give up only after many rapid failures.
                if consecutive_failures > 200:
                    log.error("capture giving up after 200 failures (last error: %s)", exc)
                    self._running.clear()
                    break
                self._sleep(0.05)

    def _silence_block(self) -> bytes:
        return (b"\x00\x00" * self.config.channels) * self.config.blocksize

    @staticmethod
    def _sleep(seconds: float) -> None:
        import time
        time.sleep(seconds)

    @staticmethod
    def _float_to_int16(frames: np.ndarray, out_channels: int = 2) -> bytes:
        # frames: (numframes, native_channels) float32 in [-1,1]. Normalise to
        # exactly out_channels so the downstream WAV/MP3 format is always right.
        if frames.ndim == 1:
            frames = frames.reshape(-1, 1)
        nch = frames.shape[1]
        if nch != out_channels:
            if nch == 1:
                # Mono -> duplicate to all output channels.
                frames = np.repeat(frames, out_channels, axis=1)
            elif nch > out_channels:
                # More channels (e.g. 6/8) -> take/mix down to the first N.
                frames = frames[:, :out_channels]
            else:
                # Fewer (but >1) -> pad by repeating the last channel.
                pad = np.repeat(frames[:, -1:], out_channels - nch, axis=1)
                frames = np.concatenate([frames, pad], axis=1)
        clipped = np.clip(frames, -1.0, 1.0)
        as_int16 = (clipped * 32767.0).astype("<i2")  # little-endian int16
        return as_int16.tobytes()

    def stop(self) -> None:
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._running.is_set()

    @property
    def last_error(self) -> Optional[Exception]:
        return self._error


def list_output_devices() -> list[str]:
    """Return names of available output devices (for diagnostics/UI)."""
    try:
        return [s.name for s in sc.all_speakers()]
    except Exception:
        return []
