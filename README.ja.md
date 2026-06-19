# Sonos Caster

[English](README.md) | [简体中文](README.zh.md) | [繁體中文](README.zh-Hant.md) | **日本語** | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português](README.pt.md) | [Русский](README.ru.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Windowsのシステムオーディオをリアルタイムで Sonos スピーカーに転送します。
PCで再生しているもの（ブラウザ、動画、音楽、ゲーム）が、そのまま Sonos から
流れます。低遅延モードでは実測 **約0.2秒** のエンドツーエンド遅延です。

画面の隅にはmacOS風のフローティングカプセルHUDが常駐 —
オン/オフを切り替え、ホバーで展開してデバイス選択 / 音量 / 設定にアクセスできます。

> 当初は AirPlay を想定していましたが、最近の Sonos は AirPlay 2 を使っており、
> オープンソースでは送出不可能な暗号化が必須になっています。そこで Sonos
> ネイティブの UPnP 経路に切り替えました — 暗号化を回避できる上、結果的に
> 遅延も低くなりました。

---

## 仕組み

```
PC system audio (WASAPI loopback)
   → ffmpeg-less raw PCM with a 4 GB WAV header (low-latency)  *or*  ffmpeg MP3
   → local HTTP audio stream at http://<lan-ip>:8009/stream.wav
   → SoCo tells Sonos to play that URL (auto-resolves current group coordinator)
```

- **検出**: `soco` (zeroconf)、安定した **UID** で記憶 — ルーター再起動後も維持されます。
- **キャプチャ**: `soundcard`（WASAPI loopback — PCが実際に再生している音）。
- **ストリーミング**: 4 GB 長の WAV ヘッダーを偽装した raw PCM = エンコーダのバッファリングなし。低帯域用には ffmpeg 経由の MP3 経路も利用可能。
- **制御**: `soco.play_uri` に動的なコーディネーター解決とリトライを組み合わせており、サラウンドグループ（例: Playbase + Play:One × 2）でコーディネーターが切り替わっても動作し続けます。

---

## 遅延

| モード | 実測値 | 適した用途 |
|------|----------|----------|
| **低遅延 (WAV / raw PCM)** | **約0.2秒** | 動画、音楽、カジュアルゲーム |
| MP3 | 約4秒 | 音楽 / ポッドキャストのみ（低帯域向け） |

デフォルトは低遅延経路です。0.2秒の下限は Sonos 自身のマルチルーム同期
バッファによるもので — すでにファームウェアの限界に達しています。WAV モード
は約 1.4 Mbps なので、家庭の WiFi なら問題ありません。

---

## インストール（開発 / ソースから実行）

**Python 3.9+** と PATH に通った **ffmpeg** が必要です。

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

または `run.bat` をダブルクリックします。

---

## スタンドアロン .exe をビルドする

PyInstaller が Python と ffmpeg を 60 MB のシングル実行ファイルにまとめ、
何もインストールせずに任意の Windows PC で動作するようにします。

```powershell
# Drop ffmpeg.exe into bundle/ first (not tracked in git — too large):
#   download from https://www.gyan.dev/ffmpeg/builds/  ->  bundle/ffmpeg.exe

.venv\Scripts\python.exe build.py
# -> dist/SonosCaster.exe
```

---

## 使い方

1. 画面の隅にピル（カプセル）が表示されます。トグルをクリックすると、検出と転送が始まります。
2. ピルにホバーすると展開: デバイス選択、音量、設定、閉じる。
3. ピルは位置を記憶します。クリック＆ドラッグで移動可能。画面の右端付近では、
   **左** 方向に展開します。
4. 初回起動時、ポート 8009 のファイアウォール規則を追加するため管理者権限を
   要求されることがあります（Sonos がストリームを取りに来られるように）。
   一度だけ許可してください。

---

## トラブルシューティング

**Sonos が見つからない** — PC と Sonos が同じ LAN / WiFi 上にあり、AP分離が無効である必要があります。

**接続できているのに無音** — 確認してください: (a) PC で今まさに何かが再生されているか
（loopback はライブ音声しか取れません）、(b) 既定の出力デバイスが実際に再生しているものと
一致しているか（設定 → オーディオソース）、(c) ファイアウォールでポート 8009 が許可されているか。

**サラウンドグループ / 「must be called on the coordinator」エラー** — 組み込みの
リトライが処理します。それでも復帰しない場合は、一度オフにしてからオンに切り替えてください。

**Sonos を再起動して IP が変わった** — 自動で対応します。デバイスは IP ではなく
安定した UID で追跡されています。

**さらに低遅延にしたい** — 0.2秒は Sonos 自身のバッファによる下限です。それより低くするには、
別の伝送方式（低遅延BTトランスミッター、有線出力など）が必要になります。

---

## プロジェクト構成

```
.
├── main.py                  # エントリーポイント
├── run.bat                  # ワンクリック起動スクリプト
├── build.py                 # PyInstaller .exe ビルダー
├── requirements.txt
├── LICENSE
├── README.md
├── bundle/
│   └── ffmpeg.exe           # （自分でダウンロード — git には含まれません）
└── sonos_caster/
    ├── capsule.py           # フローティングピル UI (Tkinter + PIL 描画)
    ├── sonos_caster.py      # 検出、コーディネーター解決、play_uri、ウォッチドッグ
    ├── http_stream.py       # ローカル HTTP オーディオストリーム + WAV/MP3 経路
    ├── capture.py           # WASAPI loopback
    ├── render.py            # PIL によるアンチエイリアス UI プリミティブ
    ├── icon.py              # アプリアイコン (Sonos 風の "S")
    ├── ffmpeg_util.py       # ffmpeg ロケーター (PATH / PyInstaller バンドル)
    ├── firewall.py          # ポート 8009 受信規則のヘルパー
    ├── sysvolume.py         # 転送中に音量を下げるためのマスター音量 get/set
    ├── config.py            # 設定の永続化
    ├── autostart.py         # Windows 起動時自動実行のレジストリヘルパー
    └── diagnostics.py       # 同梱の診断レポート (アプリ内)
```

---

## ライセンス

MIT — [LICENSE](LICENSE) を参照してください。

Copyright © 2026 MRHong.
