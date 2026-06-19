# Sonos Caster

[English](README.md) | **简体中文** | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português](README.pt.md) | [Русский](README.ru.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

把 Windows 系统声音实时转发到 Sonos 音箱。
不管 PC 在放什么（浏览器、视频、音乐、游戏），都能从 Sonos 里出来。低延迟模式下端到端实测约 **0.2 秒**。

屏幕角落有一颗 macOS 风格的悬浮胶囊 HUD —— 点一下开关，鼠标悬停就会展开出设备选择 / 音量 / 设置。

> 最初是冲着 AirPlay 做的；但现在的 Sonos 用的是带强制加密的 AirPlay 2，开源项目无法发送过去。于是转向 Sonos 原生的 UPnP 通道：绕开了加密，延迟反而更低。

---

## 工作原理

```
PC system audio (WASAPI loopback)
   → ffmpeg-less raw PCM with a 4 GB WAV header (low-latency)  *or*  ffmpeg MP3
   → local HTTP audio stream at http://<lan-ip>:8009/stream.wav
   → SoCo tells Sonos to play that URL (auto-resolves current group coordinator)
```

- **发现**：`soco`（zeroconf），按稳定的 **UID** 记住设备 —— 路由器重启也认得出。
- **采集**：`soundcard`（WASAPI loopback —— 也就是 PC 当前正在播放的声音）。
- **流传输**：raw PCM 加上一个 4 GB 长度的 WAV 头小把戏 = 不走编码器、不缓冲。也提供 ffmpeg MP3 通道，用于低带宽场景。
- **控制**：`soco.play_uri` 配合动态协调者解析 + 重试，因此环绕音组（比如 Playbase + 两只 Play:One）在协调者切换时依然能用。

---

## 延迟

| 模式 | 实测 | 适用场景 |
|------|----------|----------|
| **低延迟（WAV / 原始 PCM）** | **约 0.2 秒** | 视频、音乐、休闲游戏 |
| MP3 | 约 4 秒 | 仅音乐 / 播客（带宽更低） |

默认走低延迟通道。0.2 秒这个下限是 Sonos 自家多房间同步缓冲造成的 —— 已经顶到固件极限了。WAV 模式约 1.4 Mbps，任何家用 WiFi 都扛得住。

---

## 安装（开发 / 从源码运行）

需要 **Python 3.9+** 以及 PATH 上的 **ffmpeg**。

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

或者直接双击 `run.bat`。

---

## 打包独立 .exe

PyInstaller 会把 Python + ffmpeg 一起塞进一个 60 MB 左右的单文件可执行程序，在任何 Windows PC 上免安装即可运行。

```powershell
# Drop ffmpeg.exe into bundle/ first (not tracked in git — too large):
#   download from https://www.gyan.dev/ffmpeg/builds/  ->  bundle/ffmpeg.exe

.venv\Scripts\python.exe build.py
# -> dist/SonosCaster.exe
```

---

## 使用方法

1. 胶囊会出现在屏幕角落。点开关 —— 设备发现 + 转发就启动了。
2. 鼠标悬停在胶囊上会展开：设备选择、音量、设置、关闭。
3. 胶囊会记住位置；按住拖动即可移动。如果靠近屏幕右边缘，会改为向**左**展开。
4. 首次运行可能会请求管理员权限，用来给 8009 端口加一条防火墙规则（让 Sonos 能拉到流）。同意一次即可。

---

## 疑难排查

**找不到 Sonos** —— PC 和 Sonos 必须在同一个 LAN / WiFi 里，且未开启 AP 隔离。

**已连接但没声音** —— 确认（a）PC 此刻确实在放东西（loopback 只能抓到正在播放的音频），（b）默认输出设备和正在发声的设备一致（设置 → 音频来源），（c）防火墙允许 8009 端口。

**环绕音组 / "must be called on the coordinator" 报错** —— 内置重试会处理；如果还是恢复不了，把开关关掉再打开一次就行。

**Sonos 重启后 IP 变了** —— 自动适配；设备按稳定的 UID 跟踪，而不是 IP。

**想再低一点延迟** —— 0.2 秒就是 Sonos 自家的缓冲。要再低就得换传输方式（低延迟 BT 发射器、有线输出）。

---

## 项目结构

```
.
├── main.py                  # 程序入口
├── run.bat                  # 一键启动脚本
├── build.py                 # PyInstaller .exe 打包脚本
├── requirements.txt
├── LICENSE
├── README.md
├── bundle/
│   └── ffmpeg.exe           # （需自行下载 —— 不在 git 中）
└── sonos_caster/
    ├── capsule.py           # 悬浮胶囊 UI（Tkinter + PIL 渲染）
    ├── sonos_caster.py      # 发现、协调者解析、play_uri、看门狗
    ├── http_stream.py       # 本地 HTTP 音频流 + WAV/MP3 通道
    ├── capture.py           # WASAPI loopback 采集
    ├── render.py            # PIL 抗锯齿 UI 元件
    ├── icon.py              # 应用图标（Sonos 风格的 "S"）
    ├── ffmpeg_util.py       # ffmpeg 定位（PATH / PyInstaller 打包内）
    ├── firewall.py          # 8009 端口入站规则辅助
    ├── sysvolume.py         # 主音量读写（转发时压低本机音量）
    ├── config.py            # 设置持久化
    ├── autostart.py         # 开机自启注册表辅助
    └── diagnostics.py       # 内置诊断报告（应用内）
```

---

## 许可证

MIT —— 详见 [LICENSE](LICENSE)。

Copyright © 2026 MRHong.
