# Sonos Caster

[English](README.md) | [简体中文](README.zh.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | **Español** | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português](README.pt.md) | [Русский](README.ru.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Reenvía el audio del sistema de Windows a un altavoz Sonos en tiempo real.
Todo lo que reproduzca tu PC (navegador, video, música, juegos) sale por el
Sonos. En modo de baja latencia se miden **~0,2 s** de extremo a extremo.

Un HUD flotante con forma de cápsula al estilo de macOS se ubica en una esquina
de la pantalla: actívalo o desactívalo, o pasa el cursor por encima para
expandirlo y acceder al selector de dispositivos, volumen y ajustes.

> Originalmente apuntaba a AirPlay; las unidades Sonos modernas usan AirPlay 2
> con cifrado obligatorio que los proyectos open-source no pueden transmitir.
> Se cambió al camino nativo UPnP de Sonos: esquiva el cifrado y, de paso,
> termina ofreciendo menos latencia.

---

## Cómo funciona

```
PC system audio (WASAPI loopback)
   → ffmpeg-less raw PCM with a 4 GB WAV header (low-latency)  *or*  ffmpeg MP3
   → local HTTP audio stream at http://<lan-ip>:8009/stream.wav
   → SoCo tells Sonos to play that URL (auto-resolves current group coordinator)
```

- **Descubrimiento**: `soco` (zeroconf), recordado por un **UID** estable — sobrevive a reinicios del router.
- **Captura**: `soundcard` (WASAPI loopback — lo que el PC está reproduciendo realmente).
- **Streaming**: PCM crudo con el truco de cabecera WAV de 4 GB = sin buffering del codificador. También hay un camino MP3 vía ffmpeg para escenarios de bajo ancho de banda.
- **Control**: `soco.play_uri` con resolución dinámica del coordinador y reintentos, para que los grupos surround (por ejemplo, Playbase + 2× Play:One) sigan funcionando cuando cambia el coordinador.

---

## Latencia

| Modo | Medida | Ideal para |
|------|--------|------------|
| **Baja latencia (WAV / PCM crudo)** | **~0,2 s** | Video, música, juegos casuales |
| MP3 | ~4 s | Solo música y podcasts (menor ancho de banda) |

Por defecto se usa el camino de baja latencia. El piso de 0,2 s es el propio
búfer de sincronización multisala de Sonos — ya estamos en el límite del
firmware. El modo WAV ronda los 1,4 Mbps, sin problemas en cualquier WiFi
doméstica.

---

## Instalación (modo desarrollo / ejecutar desde el código fuente)

Requiere **Python 3.9+** y **ffmpeg** disponible en el PATH.

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

O haz doble clic en `run.bat`.

---

## Compilar un .exe independiente

PyInstaller empaqueta Python + ffmpeg en un único ejecutable de 60 MB que
corre en cualquier PC con Windows sin necesidad de instalar nada.

```powershell
# Drop ffmpeg.exe into bundle/ first (not tracked in git — too large):
#   download from https://www.gyan.dev/ffmpeg/builds/  ->  bundle/ffmpeg.exe

.venv\Scripts\python.exe build.py
# -> dist/SonosCaster.exe
```

---

## Uso

1. La cápsula aparece en la esquina. Haz clic en el interruptor — comienzan el descubrimiento y el reenvío.
2. Pasa el cursor sobre la cápsula para expandirla: selector de dispositivos, volumen, ajustes, cerrar.
3. La cápsula recuerda su posición; se arrastra haciendo clic y moviendo. Si está cerca del borde derecho de la pantalla, se expande hacia la **izquierda**.
4. La primera vez puede pedir permisos de administrador para agregar una regla de firewall en el puerto 8009 (para que Sonos pueda consumir el stream). Acéptalo una vez.

---

## Solución de problemas

**No se encuentra ningún Sonos** — el PC y el Sonos deben estar en la misma LAN / WiFi, sin aislamiento de AP.

**Se conecta pero no hay sonido** — verifica que (a) tu PC esté reproduciendo
algo en ese momento (el loopback solo captura audio en vivo), (b) el dispositivo
de salida predeterminado coincida con lo que se está reproduciendo (ajustes →
fuente de audio), (c) el firewall permita el puerto 8009.

**Errores de grupo surround / "must be called on the coordinator"** — el
reintento incorporado se encarga de esto; si no se recupera, apaga y vuelve a
encender una vez.

**Sonos se reinició y cambió de IP** — funciona automáticamente; los
dispositivos se rastrean por su UID estable, no por IP.

**Quiero aún menos latencia** — los 0,2 s son el propio búfer de Sonos. Para
bajar de ahí necesitas otro transporte (transmisor BT de baja latencia, salida
por cable).

---

## Estructura del proyecto

```
.
├── main.py                  # Punto de entrada
├── run.bat                  # Lanzador de un clic
├── build.py                 # Generador de .exe con PyInstaller
├── requirements.txt
├── LICENSE
├── README.md
├── bundle/
│   └── ffmpeg.exe           # (lo descargas tú — no está en git)
└── sonos_caster/
    ├── capsule.py           # UI de la cápsula flotante (Tkinter + renderizado con PIL)
    ├── sonos_caster.py      # Descubrimiento, resolución del coordinador, play_uri, watchdog
    ├── http_stream.py       # Stream de audio HTTP local + caminos WAV/MP3
    ├── capture.py           # WASAPI loopback
    ├── render.py            # Primitivas de UI con antialiasing vía PIL
    ├── icon.py              # Icono de la app (una "S" estilo Sonos)
    ├── ffmpeg_util.py       # Localizador de ffmpeg (PATH / bundle de PyInstaller)
    ├── firewall.py          # Helper para la regla de entrada en el puerto 8009
    ├── sysvolume.py         # Lectura/escritura del volumen maestro para atenuar al reenviar
    ├── config.py            # Persistencia de la configuración
    ├── autostart.py         # Helper de registro para iniciar con Windows
    └── diagnostics.py       # Reporte de diagnóstico integrado (dentro de la app)
```

---

## Licencia

MIT — ver [LICENSE](LICENSE).

Copyright © 2026 MRHong.
