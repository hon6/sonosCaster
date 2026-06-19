# Sonos Caster

[English](README.md) | [简体中文](README.zh.md) | **繁體中文** | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português](README.pt.md) | [Русский](README.ru.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

把 Windows 系統音訊即時轉送到 Sonos 喇叭。
不論電腦正在播什麼(瀏覽器、影片、音樂、遊戲),全都會從 Sonos 放出來。
低延遲模式實測端到端約 **0.2 秒**。

螢幕角落會浮著一顆 macOS 風格的膠囊 HUD —— 點一下開關啟動,游標移過去會展開,裡面有裝置選單、音量、設定。

> 一開始是衝著 AirPlay 來做的;不過新款 Sonos 用的是 AirPlay 2,強制加密,開源專案沒辦法傳。後來改走 Sonos 原生的 UPnP 路徑:閃過了加密,延遲反而還更低。

---

## 運作原理

```
PC system audio (WASAPI loopback)
   → ffmpeg-less raw PCM with a 4 GB WAV header (low-latency)  *or*  ffmpeg MP3
   → local HTTP audio stream at http://<lan-ip>:8009/stream.wav
   → SoCo tells Sonos to play that URL (auto-resolves current group coordinator)
```

- **裝置發現**:使用 `soco`(zeroconf),靠穩定的 **UID** 記住裝置 —— 路由器重開也不會跑掉。
- **音訊擷取**:使用 `soundcard`(WASAPI loopback —— 抓的就是 PC 當下實際播出的聲音)。
- **串流**:raw PCM 搭配一個 4 GB 長度的 WAV 表頭小技巧,完全不經過編碼器緩衝。如果想省頻寬,也有走 ffmpeg 的 MP3 路徑可選。
- **控制**:`soco.play_uri` 搭配動態解析 coordinator 與自動重試,所以家庭劇院群組(例如 Playbase + 2× Play:One)在 coordinator 切換時依然正常運作。

---

## 延遲

| 模式 | 實測 | 適用情境 |
|------|----------|----------|
| **低延遲(WAV / raw PCM)** | **約 0.2 秒** | 影片、音樂、輕度遊戲 |
| MP3 | 約 4 秒 | 純音樂 / Podcast(頻寬較低) |

預設走低延遲路徑。這 0.2 秒的底線是 Sonos 自己多房同步用的緩衝區造成的 —— 已經是韌體層級的極限。WAV 模式大約 1.4 Mbps,一般家用 WiFi 完全吃得下。

---

## 安裝(開發 / 從原始碼執行)

需要 **Python 3.9 以上** 以及 PATH 內可呼叫到的 **ffmpeg**。

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

或者直接雙擊 `run.bat`。

---

## 打包成獨立 .exe

PyInstaller 會把 Python 跟 ffmpeg 包進一個約 60 MB 的單一執行檔,丟到任何 Windows PC 上不用安裝就能跑。

```powershell
# Drop ffmpeg.exe into bundle/ first (not tracked in git — too large):
#   download from https://www.gyan.dev/ffmpeg/builds/  ->  bundle/ffmpeg.exe

.venv\Scripts\python.exe build.py
# -> dist/SonosCaster.exe
```

---

## 使用方式

1. 膠囊會出現在螢幕角落。點一下開關 —— 就開始搜尋裝置並轉送音訊。
2. 游標移到膠囊上會展開:裝置選單、音量、設定、關閉。
3. 膠囊會記住自己的位置;用滑鼠拖曳即可移動。靠近螢幕右側時會改成往**左**展開。
4. 第一次執行可能會跳出 UAC,要求加入 port 8009 的防火牆規則(這樣 Sonos 才拉得到串流)。允許一次就好。

---

## 疑難排解

**找不到 Sonos** —— PC 跟 Sonos 必須在同一個 LAN / WiFi 上,而且 AP 不能開啟用戶端隔離。

**連上了卻沒聲音** —— 請確認:(a) PC 現在真的有在播東西(loopback 只抓即時音訊);(b) 預設輸出裝置就是現在播放音訊的那個(設定 → 音訊來源);(c) 防火牆有放行 port 8009。

**家庭劇院群組 / 「must be called on the coordinator」錯誤** —— 內建的重試機制會自動處理;萬一沒回復,就把開關關掉再打開一次。

**Sonos 重開、IP 變了** —— 完全自動,因為裝置是用穩定的 UID 追蹤,而不是用 IP。

**想要更低的延遲** —— 0.2 秒是 Sonos 自家的緩衝下限。要再壓低,得換別的傳輸方式(低延遲 BT 發射器、有線輸出)。

---

## 專案結構

```
.
├── main.py                  # 程式進入點
├── run.bat                  # 一鍵啟動
├── build.py                 # PyInstaller .exe 打包腳本
├── requirements.txt
├── LICENSE
├── README.md
├── bundle/
│   └── ffmpeg.exe           # (自行下載,未納入 git)
└── sonos_caster/
    ├── capsule.py           # 浮動膠囊 UI(Tkinter + PIL 繪製)
    ├── sonos_caster.py      # 裝置發現、coordinator 解析、play_uri、watchdog
    ├── http_stream.py       # 本地 HTTP 音訊串流 + WAV/MP3 路徑
    ├── capture.py           # WASAPI loopback
    ├── render.py            # PIL 抗鋸齒 UI 元件
    ├── icon.py              # 應用程式圖示(Sonos 風格的「S」)
    ├── ffmpeg_util.py       # ffmpeg 定位器(PATH / PyInstaller bundle)
    ├── firewall.py          # Port 8009 入站規則輔助工具
    ├── sysvolume.py         # 主音量讀寫,用於轉送時自動降低系統音量
    ├── config.py            # 設定儲存
    ├── autostart.py         # 開機自動啟動的登錄檔輔助工具
    └── diagnostics.py       # 內建診斷報告(可在 app 內查看)
```

---

## 授權

MIT —— 請見 [LICENSE](LICENSE)。

Copyright © 2026 MRHong.
