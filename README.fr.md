# Sonos Caster

[English](README.md) | [简体中文](README.zh.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | **Français** | [Deutsch](README.de.md) | [Português](README.pt.md) | [Русский](README.ru.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Renvoyez l'audio système de Windows vers une enceinte Sonos en temps réel.
Tout ce que joue votre PC (navigateur, vidéo, musique, jeux) sort de la
Sonos. Le mode faible latence mesure **~0,2 s** de bout en bout.

Un HUD flottant en forme de capsule, à la macOS, se loge dans un coin de
l'écran — un clic pour activer/désactiver, un survol pour le déplier et
accéder au sélecteur d'appareil, au volume et aux réglages.

> À l'origine, le projet visait AirPlay ; mais les Sonos récentes utilisent
> AirPlay 2 avec un chiffrement obligatoire que les projets open source ne
> peuvent pas émettre. Pivot vers la voie native de Sonos en UPnP : on
> contourne le chiffrement et, au passage, la latence est encore meilleure.

---

## Fonctionnement

```
PC system audio (WASAPI loopback)
   → ffmpeg-less raw PCM with a 4 GB WAV header (low-latency)  *or*  ffmpeg MP3
   → local HTTP audio stream at http://<lan-ip>:8009/stream.wav
   → SoCo tells Sonos to play that URL (auto-resolves current group coordinator)
```

- **Découverte** : `soco` (zeroconf), mémorisée par un **UID** stable — survit aux redémarrages du routeur.
- **Capture** : `soundcard` (WASAPI loopback — ce que le PC est réellement en train de jouer).
- **Streaming** : PCM brut avec une astuce d'en-tête WAV de 4 Go = aucun tamponnage côté encodeur. Une voie MP3 reste disponible via ffmpeg pour les usages à faible bande passante.
- **Pilotage** : `soco.play_uri` avec résolution dynamique du coordinateur et réessais, pour que les groupes surround (par ex. Playbase + 2× Play:One) continuent de fonctionner quand le coordinateur change.

---

## Latence

| Mode | Mesurée | Idéal pour |
|------|---------|------------|
| **Faible latence (WAV / PCM brut)** | **~0,2 s** | Vidéo, musique, jeux occasionnels |
| MP3 | ~4 s | Musique / podcasts uniquement (bande passante réduite) |

La voie faible latence est utilisée par défaut. Le plancher de 0,2 s correspond
au propre tampon de synchronisation multi-pièces de Sonos — on est déjà à la
limite du firmware. Le mode WAV tourne autour de 1,4 Mb/s, ce qui passe sans
souci sur n'importe quel WiFi domestique.

---

## Installation (dév / exécution depuis les sources)

Nécessite **Python 3.9+** et **ffmpeg** dans le PATH.

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

Ou double-cliquez sur `run.bat`.

---

## Construire un .exe autonome

PyInstaller regroupe Python et ffmpeg dans un seul exécutable de 60 Mo qui
s'exécute sur n'importe quel PC Windows, sans aucune installation.

```powershell
# Drop ffmpeg.exe into bundle/ first (not tracked in git — too large):
#   download from https://www.gyan.dev/ffmpeg/builds/  ->  bundle/ffmpeg.exe

.venv\Scripts\python.exe build.py
# -> dist/SonosCaster.exe
```

---

## Utilisation

1. La pastille apparaît dans un coin. Cliquez sur l'interrupteur — la
   découverte et le renvoi démarrent.
2. Survolez la pastille pour la déplier : sélecteur d'appareil, volume,
   réglages, fermeture.
3. La pastille mémorise sa position ; on la déplace par cliquer-glisser. Près
   du bord droit de l'écran, elle se déplie vers la **gauche** au lieu de la
   droite.
4. Au premier lancement, une invite d'administrateur peut apparaître pour
   ajouter une règle de pare-feu sur le port 8009 (afin que Sonos puisse
   récupérer le flux). Acceptez-la une bonne fois.

---

## Dépannage

**Aucune Sonos détectée** — le PC et la Sonos doivent être sur le même
LAN / WiFi, sans isolation des points d'accès.

**Connecté mais silence total** — vérifiez que (a) votre PC est bien en train
de jouer quelque chose à l'instant (le loopback ne capte que de l'audio en
direct), (b) le périphérique de sortie par défaut correspond à ce qui joue
(réglages → source audio), (c) le pare-feu autorise bien le port 8009.

**Erreurs « must be called on the coordinator » / groupe surround** — un
mécanisme de réessais intégré gère ce cas ; s'il ne se rétablit pas, désactivez
puis réactivez une fois.

**Sonos a redémarré, l'IP a changé** — c'est géré automatiquement ; les
appareils sont suivis par un UID stable, pas par leur IP.

**Vous voulez encore moins de latence** — les 0,2 s correspondent au tampon
propre à Sonos. Pour descendre plus bas, il faut un autre transport
(émetteur BT faible latence, sortie filaire).

---

## Arborescence du projet

```
.
├── main.py                  # Point d'entrée
├── run.bat                  # Lanceur en un clic
├── build.py                 # Constructeur de .exe via PyInstaller
├── requirements.txt
├── LICENSE
├── README.md
├── bundle/
│   └── ffmpeg.exe           # (à télécharger — absent du dépôt)
└── sonos_caster/
    ├── capsule.py           # UI de la pastille flottante (Tkinter + rendu PIL)
    ├── sonos_caster.py      # Découverte, résolution du coordinateur, play_uri, watchdog
    ├── http_stream.py       # Flux audio HTTP local + voies WAV/MP3
    ├── capture.py           # WASAPI loopback
    ├── render.py            # Primitives d'UI anti-crénelées en PIL
    ├── icon.py              # Icône de l'app (un « S » façon Sonos)
    ├── ffmpeg_util.py       # Localisateur ffmpeg (PATH / bundle PyInstaller)
    ├── firewall.py          # Utilitaire pour la règle entrante du port 8009
    ├── sysvolume.py         # Lecture/écriture du volume principal pour l'atténuation pendant le renvoi
    ├── config.py            # Persistance des réglages
    ├── autostart.py         # Utilitaire registre pour le démarrage avec Windows
    └── diagnostics.py       # Rapport de diagnostic intégré (dans l'app)
```

---

## Licence

MIT — voir [LICENSE](LICENSE).

Copyright © 2026 MRHong.
