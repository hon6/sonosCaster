# Sonos Caster

[English](README.md) | [简体中文](README.zh.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | **한국어** | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português](README.pt.md) | [Русский](README.ru.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Windows 시스템 오디오를 Sonos 스피커로 실시간 전송합니다.
PC에서 재생 중인 모든 소리(브라우저, 동영상, 음악, 게임)가 그대로 Sonos에서
흘러나옵니다. 저지연 모드의 종단 간 지연은 측정값 **약 0.2초**.

화면 한쪽 구석에 macOS 스타일의 떠 있는 캡슐형 HUD가 자리잡고 —
클릭으로 켜고 끄거나, 마우스를 올리면 펼쳐져서 기기 선택 / 볼륨 / 설정에 접근할 수 있습니다.

> 처음에는 AirPlay를 목표로 했지만, 최신 Sonos 기기는 필수 암호화가 적용된
> AirPlay 2를 사용하기 때문에 오픈소스 프로젝트가 송신하기는 어렵습니다. 그래서
> Sonos의 네이티브 UPnP 경로로 방향을 틀었는데, 암호화를 우회하면서 결과적으로
> 지연도 더 낮아졌습니다.

---

## 작동 방식

```
PC system audio (WASAPI loopback)
   → ffmpeg-less raw PCM with a 4 GB WAV header (low-latency)  *or*  ffmpeg MP3
   → local HTTP audio stream at http://<lan-ip>:8009/stream.wav
   → SoCo tells Sonos to play that URL (auto-resolves current group coordinator)
```

- **검색**: `soco` (zeroconf), 안정적인 **UID**로 기억 — 공유기를 재시작해도 유지됩니다.
- **캡처**: `soundcard` (WASAPI loopback — PC가 실제로 재생하고 있는 소리).
- **스트리밍**: 4 GB 길이 WAV 헤더 트릭을 쓴 raw PCM = 인코더 버퍼링 없음. 저대역폭이 필요할 때를 위해 ffmpeg를 통한 MP3 경로도 제공.
- **제어**: 동적 coordinator 해석 + 재시도 로직이 포함된 `soco.play_uri`. 덕분에 서라운드 그룹(예: Playbase + Play:One 2대)에서 coordinator가 바뀌어도 계속 작동합니다.

---

## 지연 시간

| 모드 | 측정값 | 적합한 용도 |
|------|--------|-------------|
| **저지연 (WAV / raw PCM)** | **약 0.2초** | 동영상, 음악, 캐주얼 게임 |
| MP3 | 약 4초 | 음악 / 팟캐스트 전용 (낮은 대역폭) |

기본값은 저지연 경로입니다. 0.2초라는 하한은 Sonos 자체의 멀티룸 동기화
버퍼이며 — 이미 펌웨어 한계까지 도달한 값입니다. WAV 모드는 약 1.4 Mbps로,
어떤 가정용 WiFi에서도 부담 없는 수준입니다.

---

## 설치 (개발 / 소스에서 실행)

**Python 3.9+** 및 PATH에 등록된 **ffmpeg**가 필요합니다.

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

또는 `run.bat`를 더블클릭하세요.

---

## 독립 실행형 .exe 빌드

PyInstaller가 Python과 ffmpeg를 하나의 60 MB짜리 실행 파일로 묶어주며,
별도 설치 없이 어느 Windows PC에서나 바로 실행할 수 있습니다.

```powershell
# Drop ffmpeg.exe into bundle/ first (not tracked in git — too large):
#   download from https://www.gyan.dev/ffmpeg/builds/  ->  bundle/ffmpeg.exe

.venv\Scripts\python.exe build.py
# -> dist/SonosCaster.exe
```

---

## 사용법

1. 화면 구석에 캡슐(pill)이 나타납니다. 토글을 클릭하면 — 기기 검색과 전송이 시작됩니다.
2. 캡슐에 마우스를 올리면 펼쳐집니다: 기기 선택, 볼륨, 설정, 닫기.
3. 캡슐은 위치를 기억하며, 클릭한 채로 드래그해서 옮길 수 있습니다. 화면 오른쪽
   가장자리에 가까우면 펼쳐지는 방향이 **왼쪽**으로 바뀝니다.
4. 첫 실행 시 포트 8009에 대한 방화벽 규칙 추가를 위해 관리자 권한을 요청할
   수 있습니다(Sonos가 스트림을 가져갈 수 있도록). 한 번만 허용해 주세요.

---

## 문제 해결

**Sonos가 발견되지 않을 때** — PC와 Sonos가 같은 LAN / WiFi에 있어야 하며, AP isolation이 꺼져 있어야 합니다.

**연결됐는데 소리가 안 날 때** — 다음을 확인하세요. (a) 지금 PC에서 실제로
뭔가 재생되고 있는지(loopback은 라이브 오디오만 캡처합니다), (b) 기본 출력
장치가 재생 중인 것과 일치하는지(설정 → 오디오 소스), (c) 방화벽이 포트
8009를 허용하는지.

**서라운드 그룹 / "must be called on the coordinator" 오류** — 내장 재시도
로직이 처리합니다. 만약 복구되지 않으면 토글을 한 번 껐다 켜 보세요.

**Sonos가 재부팅돼서 IP가 바뀌었을 때** — 자동으로 처리됩니다. 기기는 IP가
아니라 안정적인 UID로 추적됩니다.

**더 낮은 지연이 필요하다면** — 0.2초는 Sonos 자체 버퍼입니다. 그 이하로
가려면 다른 전송 방식(저지연 BT 송신기, 유선 출력)이 필요합니다.

---

## 프로젝트 구조

```
.
├── main.py                  # 진입점
├── run.bat                  # 원클릭 실행 스크립트
├── build.py                 # PyInstaller .exe 빌더
├── requirements.txt
├── LICENSE
├── README.md
├── bundle/
│   └── ffmpeg.exe           # (직접 다운로드 — git에 포함되지 않음)
└── sonos_caster/
    ├── capsule.py           # 떠 있는 캡슐 UI (Tkinter + PIL로 렌더링)
    ├── sonos_caster.py      # 검색, coordinator 해석, play_uri, watchdog
    ├── http_stream.py       # 로컬 HTTP 오디오 스트림 + WAV/MP3 경로
    ├── capture.py           # WASAPI loopback
    ├── render.py            # PIL 안티앨리어싱 UI 프리미티브
    ├── icon.py              # 앱 아이콘 (Sonos 스타일의 "S")
    ├── ffmpeg_util.py       # ffmpeg 탐색 (PATH / PyInstaller 번들)
    ├── firewall.py          # 포트 8009 인바운드 규칙 헬퍼
    ├── sysvolume.py         # 전송 중 볼륨 낮추기를 위한 마스터 볼륨 가져오기/설정
    ├── config.py            # 설정 영속화
    ├── autostart.py         # Windows 시작 시 자동 실행 레지스트리 헬퍼
    └── diagnostics.py       # 번들 진단 리포트 (앱 내장)
```

---

## 라이선스

MIT — [LICENSE](LICENSE) 참조.

Copyright © 2026 MRHong.
