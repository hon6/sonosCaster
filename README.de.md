# Sonos Caster

[English](README.md) | [简体中文](README.zh.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | **Deutsch** | [Português](README.pt.md) | [Русский](README.ru.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Den Systemton von Windows in Echtzeit an einen Sonos-Lautsprecher weiterleiten.
Was auch immer dein PC gerade abspielt (Browser, Video, Musik, Spiele), kommt
aus dem Sonos. Im Low-Latency-Modus liegt die gemessene End-to-End-Verzögerung
bei **~0,2 s**.

Ein schwebendes HUD im macOS-Kapsel-Stil sitzt in der Bildschirmecke –
ein Klick schaltet die Übertragung ein und aus, beim Überfahren mit der Maus
klappt es auf und zeigt Geräteauswahl, Lautstärke und Einstellungen.

> Ursprünglich war AirPlay das Ziel; moderne Sonos-Geräte nutzen AirPlay 2 mit
> obligatorischer Verschlüsselung, die Open-Source-Projekte nicht senden können.
> Daher der Wechsel zum nativen UPnP-Pfad von Sonos: Verschlüsselung umgangen,
> Latenz am Ende sogar niedriger.

---

## Funktionsweise

```
PC system audio (WASAPI loopback)
   → ffmpeg-less raw PCM with a 4 GB WAV header (low-latency)  *or*  ffmpeg MP3
   → local HTTP audio stream at http://<lan-ip>:8009/stream.wav
   → SoCo tells Sonos to play that URL (auto-resolves current group coordinator)
```

- **Erkennung**: `soco` (zeroconf), gespeichert über stabile **UID** – übersteht Router-Neustarts.
- **Aufnahme**: `soundcard` (WASAPI-Loopback – das, was der PC tatsächlich abspielt).
- **Streaming**: rohes PCM mit einem WAV-Header-Trick (4 GB Länge) = keine Encoder-Pufferung. Über ffmpeg steht zusätzlich ein MP3-Pfad für bandbreitenarme Szenarien zur Verfügung.
- **Steuerung**: `soco.play_uri` mit dynamischer Coordinator-Auflösung und Retry, damit Surround-Gruppen (z. B. Playbase + 2× Play:One) weiterlaufen, wenn der Coordinator wechselt.

---

## Latenz

| Modus | Gemessen | Geeignet für |
|------|----------|----------|
| **Low-Latency (WAV / rohes PCM)** | **~0,2 s** | Video, Musik, gelegentliche Spiele |
| MP3 | ~4 s | Nur Musik / Podcasts (geringere Bandbreite) |

Standard ist der Low-Latency-Pfad. Die Untergrenze von 0,2 s ist Sonos' eigener
Multiroom-Sync-Puffer – also das Firmware-Limit. Der WAV-Modus liegt bei ~1,4 Mbps
und läuft problemlos über jedes Heim-WiFi.

---

## Installation (Entwicklung / aus dem Quellcode starten)

Voraussetzungen: **Python 3.9+** und **ffmpeg** im PATH.

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

Oder einfach per Doppelklick auf `run.bat`.

---

## Eigenständige .exe bauen

PyInstaller bündelt Python und ffmpeg in eine einzige 60-MB-Executable, die
auf jedem Windows-PC ohne Installation läuft.

```powershell
# Drop ffmpeg.exe into bundle/ first (not tracked in git — too large):
#   download from https://www.gyan.dev/ffmpeg/builds/  ->  bundle/ffmpeg.exe

.venv\Scripts\python.exe build.py
# -> dist/SonosCaster.exe
```

---

## Verwendung

1. Die Kapsel erscheint in der Bildschirmecke. Klick auf den Schalter – Erkennung und Weiterleitung starten.
2. Mit der Maus über die Kapsel fahren, um sie aufzuklappen: Geräteauswahl, Lautstärke, Einstellungen, Schließen.
3. Die Kapsel merkt sich ihre Position; ziehen geht per Klicken und Halten. Nahe am rechten Bildschirmrand klappt sie nach **links** auf statt nach rechts.
4. Beim ersten Start wird ggf. nach Admin-Rechten gefragt, um eine Firewall-Regel für Port 8009 anzulegen (damit Sonos den Stream abholen kann). Einmal zustimmen reicht.

---

## Fehlerbehebung

**Kein Sonos gefunden** – PC und Sonos müssen im selben LAN / WiFi sein, ohne AP-Isolation.

**Verbunden, aber kein Ton** – sicherstellen, dass (a) am PC gerade wirklich etwas läuft (Loopback nimmt nur aktiven Ton auf), (b) das Standard-Wiedergabegerät zu dem passt, was läuft (Einstellungen → Audioquelle), (c) die Firewall Port 8009 freigibt.

**Surround-Gruppe / "must be called on the coordinator"-Fehler** – der eingebaute Retry fängt das ab; falls sich der Stream nicht erholt, einmal aus- und wieder einschalten.

**Sonos neu gestartet, IP geändert** – läuft automatisch weiter; Geräte werden über die stabile UID identifiziert, nicht über die IP.

**Noch weniger Latenz** – 0,2 s sind Sonos' eigener Puffer. Wer darunter will, braucht eine andere Übertragung (Low-Latency-BT-Transmitter, kabelgebundener Ausgang).

---

## Projektstruktur

```
.
├── main.py                  # Einstiegspunkt
├── run.bat                  # Ein-Klick-Starter
├── build.py                 # PyInstaller-Builder für die .exe
├── requirements.txt
├── LICENSE
├── README.md
├── bundle/
│   └── ffmpeg.exe           # (selbst herunterladen — nicht im git)
└── sonos_caster/
    ├── capsule.py           # Schwebende Kapsel-UI (Tkinter + PIL-gerendert)
    ├── sonos_caster.py      # Erkennung, Coordinator-Auflösung, play_uri, Watchdog
    ├── http_stream.py       # Lokaler HTTP-Audiostream + WAV/MP3-Pfade
    ├── capture.py           # WASAPI-Loopback
    ├── render.py            # Anti-aliasing-UI-Primitiven via PIL
    ├── icon.py              # App-Icon (Sonos-typisches „S")
    ├── ffmpeg_util.py       # ffmpeg-Locator (PATH / PyInstaller-Bundle)
    ├── firewall.py          # Helfer für Inbound-Regel auf Port 8009
    ├── sysvolume.py         # Master-Lautstärke lesen/setzen (zum Absenken beim Forwarden)
    ├── config.py            # Persistenz der Einstellungen
    ├── autostart.py         # Registry-Helfer für Autostart mit Windows
    └── diagnostics.py       # Mitgelieferter Diagnosebericht (in-App)
```

---

## Lizenz

MIT – siehe [LICENSE](LICENSE).

Copyright © 2026 MRHong.
