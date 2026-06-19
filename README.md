# Sonos Caster

**English** | [简体中文](README.zh.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Forward Windows system audio to a Sonos speaker in real time.
Whatever your PC is playing (browser, video, music, games) comes out of the
Sonos. Low-latency mode measures **~0.2 s** end-to-end.

A floating macOS-style capsule HUD sits in the corner of the screen —
toggle on/off, hover to expand for device picker / volume / settings.

> Originally targeted AirPlay; modern Sonos units use AirPlay 2 with mandatory
> encryption that open-source projects can't transmit to. Pivoted to Sonos's
> native UPnP path: dodges encryption, ends up lower-latency anyway.

---

## How it works

```
PC system audio (WASAPI loopback)
   → ffmpeg-less raw PCM with a 4 GB WAV header (low-latency)  *or*  ffmpeg MP3
   → local HTTP audio stream at http://<lan-ip>:8009/stream.wav
   → SoCo tells Sonos to play that URL (auto-resolves current group coordinator)
```

- **Discovery**: `soco` (zeroconf), remembered by stable **UID** — survives router restarts.
- **Capture**: `soundcard` (WASAPI loopback — what the PC is actually playing).
- **Streaming**: raw PCM with a 4 GB-length WAV header trick = no encoder buffering. MP3 path available via ffmpeg for low-bandwidth use.
- **Control**: `soco.play_uri` with dynamic coordinator resolution + retry, so surround groups (e.g. Playbase + 2× Play:One) keep working when the coordinator switches.

---

## Latency

| Mode | Measured | Good for |
|------|----------|----------|
| **Low-latency (WAV / raw PCM)** | **~0.2 s** | Video, music, casual games |
| MP3 | ~4 s | Music / podcasts only (lower bandwidth) |

The default is the low-latency path. The 0.2 s floor is Sonos's own multi-room
sync buffer — already at the firmware limit. WAV mode is ~1.4 Mbps, fine on
any home WiFi.

---

## Install (dev / running from source)

Requires **Python 3.9+** and **ffmpeg** on PATH.

```powershell
# 1. ffmpeg (one-time)
winget install Gyan.FFmpeg

# 2. Clone + enter
git clone git@github.com:hon6/sonosCaster.git
cd sonosCaster

# 3. Virtualenv + deps
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 4. Run
.venv\Scripts\python.exe main.py
```

Or double-click `run.bat`.

---

## Build a standalone .exe

PyInstaller bundles Python + ffmpeg into a single 60 MB executable that runs
on any Windows PC without installing anything.

```powershell
# Drop ffmpeg.exe into bundle/ first (not tracked in git — too large):
#   download from https://www.gyan.dev/ffmpeg/builds/  ->  bundle/ffmpeg.exe

.venv\Scripts\python.exe build.py
# -> dist/SonosCaster.exe
```

---

## Usage

1. The pill shows up in the corner. Click the toggle — discovery + forwarding starts.
2. Hover the pill to expand: device picker, volume, settings, close.
3. Pill remembers its position; drags by clicking and dragging. Near the right
   edge of the screen it expands to the **left** instead.
4. First run may prompt for admin to add a firewall rule for port 8009
   (so Sonos can pull the stream). Allow it once.

---

## Troubleshooting

**No Sonos found** — PC and Sonos must be on the same LAN / WiFi, no AP isolation.

**Connected but silent** — make sure (a) your PC is actually playing something
right now (loopback only captures live audio), (b) the default output device
matches what's playing (settings → audio source), (c) firewall allows port 8009.

**Surround group / "must be called on the coordinator" errors** — built-in
retry handles this; if it doesn't recover, toggle off and on once.

**Sonos rebooted, IP changed** — works automatically; devices are tracked by
stable UID, not IP.

**Want even lower latency** — 0.2 s is Sonos's own buffer. To go lower you
need a different transport (low-latency BT transmitter, wired output).

---

## Project layout

```
.
├── main.py                  # Entry point
├── run.bat                  # One-click launcher
├── build.py                 # PyInstaller .exe builder
├── requirements.txt
├── LICENSE
├── README.md
├── bundle/
│   └── ffmpeg.exe           # (you download — not in git)
└── sonos_caster/
    ├── capsule.py           # Floating pill UI (Tkinter + PIL-rendered)
    ├── sonos_caster.py      # Discovery, coordinator resolve, play_uri, watchdog
    ├── http_stream.py       # Local HTTP audio stream + WAV/MP3 paths
    ├── capture.py           # WASAPI loopback
    ├── render.py            # PIL anti-aliased UI primitives
    ├── icon.py              # App icon (Sonos-style "S")
    ├── ffmpeg_util.py       # ffmpeg locator (PATH / PyInstaller bundle)
    ├── firewall.py          # Port 8009 inbound rule helper
    ├── sysvolume.py         # Master volume get/set for dim-while-forwarding
    ├── config.py            # Settings persistence
    ├── autostart.py         # Start-with-Windows registry helper
    └── diagnostics.py       # Bundled diagnostic report (in-app)
```

---

## License

MIT — see [LICENSE](LICENSE).

Copyright © 2026 MRHong.
