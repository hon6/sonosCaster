# Sonos Caster

[English](README.md) | [简体中文](README.zh.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português](README.pt.md) | [Русский](README.ru.md) | [العربية](README.ar.md) | **हिन्दी**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Windows के सिस्टम ऑडियो को रियल-टाइम में किसी Sonos स्पीकर पर भेजिए।
आपका PC जो भी चला रहा हो (ब्राउज़र, वीडियो, संगीत, गेम) — वह सब Sonos से बाहर
आता है। लो-लेटेंसी मोड में एंड-टू-एंड देरी **~0.2 सेकंड** मापी गई है।

स्क्रीन के कोने में एक फ़्लोटिंग macOS-स्टाइल कैप्सूल HUD बैठा रहता है —
चालू/बंद टॉगल करें, होवर करने पर वह फैलकर डिवाइस पिकर / वॉल्यूम / सेटिंग्स दिखाता है।

> शुरुआत में लक्ष्य AirPlay था; आधुनिक Sonos यूनिट्स AirPlay 2 का इस्तेमाल करती हैं
> जिसमें अनिवार्य एन्क्रिप्शन है — ओपन-सोर्स प्रोजेक्ट्स उसमें ट्रांसमिट नहीं कर सकते।
> इसलिए Sonos के अपने नेटिव UPnP रास्ते पर शिफ्ट हो गए: एन्क्रिप्शन से बच गए, और
> लेटेंसी भी कम मिल गई।

---

## यह काम कैसे करता है

```
PC system audio (WASAPI loopback)
   → ffmpeg-less raw PCM with a 4 GB WAV header (low-latency)  *or*  ffmpeg MP3
   → local HTTP audio stream at http://<lan-ip>:8009/stream.wav
   → SoCo tells Sonos to play that URL (auto-resolves current group coordinator)
```

- **डिस्कवरी**: `soco` (zeroconf), स्थिर **UID** से याद रखा जाता है — राउटर रीस्टार्ट के बाद भी टिकता है।
- **कैप्चर**: `soundcard` (WASAPI loopback — PC असल में जो बजा रहा है)।
- **स्ट्रीमिंग**: 4 GB-लंबाई वाले WAV हेडर ट्रिक के साथ raw PCM = कोई एनकोडर बफरिंग नहीं। कम बैंडविड्थ के लिए ffmpeg के ज़रिये MP3 रास्ता भी उपलब्ध है।
- **कंट्रोल**: डायनेमिक कोऑर्डिनेटर रिज़ॉल्यूशन + रिट्राय के साथ `soco.play_uri`, ताकि सराउंड ग्रुप (जैसे Playbase + 2× Play:One) तब भी चलते रहें जब कोऑर्डिनेटर बदल जाए।

---

## लेटेंसी

| मोड | मापा गया | किसके लिए ठीक |
|------|----------|----------|
| **लो-लेटेंसी (WAV / raw PCM)** | **~0.2 सेकंड** | वीडियो, संगीत, साधारण गेम |
| MP3 | ~4 सेकंड | केवल संगीत / पॉडकास्ट (कम बैंडविड्थ) |

डिफ़ॉल्ट लो-लेटेंसी रास्ता है। 0.2 सेकंड की निचली सीमा खुद Sonos का मल्टी-रूम
सिंक बफर है — फर्मवेयर की सीमा पर पहले से ही है। WAV मोड लगभग 1.4 Mbps का है, जो
किसी भी घरेलू WiFi पर ठीक चलता है।

---

## इंस्टॉल (डेव / सोर्स से चलाना)

**Python 3.9+** और PATH पर **ffmpeg** चाहिए।

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

या फिर `run.bat` पर डबल-क्लिक कर दें।

---

## स्टैंडअलोन .exe बनाना

PyInstaller, Python + ffmpeg को एक ही 60 MB एक्ज़ीक्यूटेबल में पैक कर देता है
जो बिना कुछ इंस्टॉल किए किसी भी Windows PC पर चलता है।

```powershell
# Drop ffmpeg.exe into bundle/ first (not tracked in git — too large):
#   download from https://www.gyan.dev/ffmpeg/builds/  ->  bundle/ffmpeg.exe

.venv\Scripts\python.exe build.py
# -> dist/SonosCaster.exe
```

---

## इस्तेमाल

1. कोने में पिल (कैप्सूल) दिखती है। टॉगल पर क्लिक करें — डिस्कवरी और फ़ॉरवर्डिंग शुरू हो जाती है।
2. पिल पर होवर करने से वह फैलती है: डिवाइस पिकर, वॉल्यूम, सेटिंग्स, बंद करने का बटन।
3. पिल अपनी जगह याद रखती है; क्लिक करके खींचने से हिलती है। स्क्रीन के दाहिने
   किनारे के पास होने पर वह दाएँ की बजाय **बाएँ** की ओर फैलती है।
4. पहली बार चलाने पर पोर्ट 8009 के लिए फ़ायरवॉल रूल जोड़ने हेतु admin अनुमति माँगी
   जा सकती है (ताकि Sonos स्ट्रीम खींच सके)। एक बार अनुमति दे दें।

---

## ट्रबलशूटिंग

**कोई Sonos नहीं मिला** — PC और Sonos एक ही LAN / WiFi पर होने चाहिए, AP आइसोलेशन बंद हो।

**कनेक्ट तो है पर आवाज़ नहीं** — सुनिश्चित करें कि (a) आपका PC अभी सचमुच कुछ
बजा रहा है (loopback केवल लाइव ऑडियो पकड़ता है), (b) डिफ़ॉल्ट आउटपुट डिवाइस वही है
जो बज रहा है (settings → audio source), (c) फ़ायरवॉल पोर्ट 8009 को अनुमति दे रहा है।

**सराउंड ग्रुप / "must be called on the coordinator" वाली एरर** — बिल्ट-इन रिट्राय
इसे संभाल लेती है; अगर ख़ुद नहीं संभले, तो एक बार टॉगल बंद-चालू कर दें।

**Sonos रीबूट हुआ, IP बदल गया** — अपने आप काम करता रहेगा; डिवाइस स्थिर UID से
ट्रैक होते हैं, IP से नहीं।

**और भी कम लेटेंसी चाहिए** — 0.2 सेकंड खुद Sonos का बफर है। इससे कम के लिए आपको
अलग ट्रांसपोर्ट चाहिए (लो-लेटेंसी BT ट्रांसमीटर, वायर्ड आउटपुट)।

---

## प्रोजेक्ट का ढाँचा

```
.
├── main.py                  # एंट्री पॉइंट
├── run.bat                  # वन-क्लिक लॉन्चर
├── build.py                 # PyInstaller .exe बिल्डर
├── requirements.txt
├── LICENSE
├── README.md
├── bundle/
│   └── ffmpeg.exe           # (आप डाउनलोड करते हैं — git में नहीं है)
└── sonos_caster/
    ├── capsule.py           # फ़्लोटिंग पिल UI (Tkinter + PIL से रेंडर)
    ├── sonos_caster.py      # डिस्कवरी, कोऑर्डिनेटर रिज़ॉल्व, play_uri, वॉचडॉग
    ├── http_stream.py       # लोकल HTTP ऑडियो स्ट्रीम + WAV/MP3 रास्ते
    ├── capture.py           # WASAPI loopback
    ├── render.py            # PIL एंटी-एलियास्ड UI प्रिमिटिव्स
    ├── icon.py              # ऐप आइकन (Sonos-स्टाइल "S")
    ├── ffmpeg_util.py       # ffmpeg लोकेटर (PATH / PyInstaller बंडल)
    ├── firewall.py          # पोर्ट 8009 इनबाउंड रूल हेल्पर
    ├── sysvolume.py         # फ़ॉरवर्डिंग के दौरान डिम करने के लिए मास्टर वॉल्यूम get/set
    ├── config.py            # सेटिंग्स को सहेजना
    ├── autostart.py         # Windows के साथ शुरू होने का रजिस्ट्री हेल्पर
    └── diagnostics.py       # बंडल किया गया डायग्नॉस्टिक रिपोर्ट (ऐप के अंदर)
```

---

## लाइसेंस

MIT — देखें [LICENSE](LICENSE)।

Copyright © 2026 MRHong.
