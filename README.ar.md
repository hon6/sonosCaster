# Sonos Caster

[English](README.md) | [简体中文](README.zh.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português](README.pt.md) | [Русский](README.ru.md) | **العربية** | [हिन्दी](README.hi.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

أعِد توجيه صوت نظام Windows إلى مكبّر صوت Sonos في الوقت الفعلي.
أيًّا كان ما يشغّله حاسوبك (متصفّح، فيديو، موسيقى، ألعاب) فإنه يخرج من
مكبّر Sonos. يبلغ زمن الاستجابة في الوضع منخفض الكمون **نحو 0.2 ثانية** من الطرف إلى الطرف.

تظهر كبسولة عائمة على طراز macOS في زاوية الشاشة —
اضغطها للتشغيل/الإيقاف، ومرّر المؤشّر فوقها لتتوسّع وتُظهر منتقي الأجهزة ومستوى الصوت والإعدادات.

> كان الاستهداف الأصلي AirPlay؛ غير أن أجهزة Sonos الحديثة تستخدم AirPlay 2 مع تشفير إلزامي
> لا تستطيع المشاريع مفتوحة المصدر البثّ إليه. فتمّ التحوّل إلى مسار UPnP الأصلي من Sonos:
> يتفادى التشفير، ويُحقّق في النهاية كمونًا أدنى أيضًا.

---

## آلية العمل

```
PC system audio (WASAPI loopback)
   → ffmpeg-less raw PCM with a 4 GB WAV header (low-latency)  *or*  ffmpeg MP3
   → local HTTP audio stream at http://<lan-ip>:8009/stream.wav
   → SoCo tells Sonos to play that URL (auto-resolves current group coordinator)
```

- **الاكتشاف**: عبر `soco` (zeroconf)، ويُحفظ الجهاز بمعرّف **UID** ثابت — يصمد أمام إعادة تشغيل الموجّه.
- **الالتقاط**: عبر `soundcard` (وضع WASAPI loopback — أي ما يشغّله الحاسوب فعليًا).
- **البثّ**: PCM خام مع حيلة ترويسة WAV بطول 4 جيجابايت = لا تخزين مؤقّت لدى المُرمِّز. ويتوفّر مسار MP3 عبر ffmpeg للاستخدام منخفض النطاق الترددي.
- **التحكّم**: `soco.play_uri` مع تحديد ديناميكي للمنسّق وإعادة محاولة، بحيث تستمرّ مجموعات الصوت المحيطي (مثل Playbase + قطعتَي Play:One) في العمل عند تبديل المنسّق.

---

## زمن الاستجابة

| الوضع | المقيس | يصلح لـ |
|------|----------|----------|
| **منخفض الكمون (WAV / PCM خام)** | **~0.2 ثانية** | الفيديو والموسيقى والألعاب العادية |
| MP3 | ~4 ثوانٍ | الموسيقى والبودكاست فقط (نطاق ترددي أقل) |

المسار الافتراضي هو المسار منخفض الكمون. حدّ الـ 0.2 ثانية هو ذاته مخزن التزامن
متعدد الغرف الخاص بـ Sonos — أي إنّنا بالفعل عند الحدّ الأقصى للبرامج الثابتة. يبلغ معدّل وضع WAV نحو 1.4 ميجابت/ث،
وهو مقبول على أي شبكة WiFi منزلية.

---

## التثبيت (للتطوير / التشغيل من المصدر)

يتطلّب **Python 3.9+** وتوفّر **ffmpeg** في متغيّر PATH.

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

أو انقر نقرًا مزدوجًا على `run.bat`.

---

## بناء ملفّ ‎.exe مستقل

تُجمّع أداة PyInstaller كلًّا من Python وffmpeg في ملفّ تنفيذي واحد بحجم 60 ميجابايت يعمل
على أي جهاز Windows دون الحاجة إلى تثبيت أيّ شيء.

```powershell
# Drop ffmpeg.exe into bundle/ first (not tracked in git — too large):
#   download from https://www.gyan.dev/ffmpeg/builds/  ->  bundle/ffmpeg.exe

.venv\Scripts\python.exe build.py
# -> dist/SonosCaster.exe
```

---

## الاستخدام

1. تظهر الكبسولة في الزاوية. انقر على المفتاح — يبدأ الاكتشاف وإعادة التوجيه.
2. مرّر المؤشّر فوق الكبسولة لتتوسّع: منتقي الأجهزة، مستوى الصوت، الإعدادات، الإغلاق.
3. تتذكّر الكبسولة موضعها؛ ويمكن سحبها بالنقر والسحب. وعندما تقترب من
   الحافة اليمنى للشاشة فإنها تتوسّع **يسارًا** بدلًا من اليمين.
4. قد يطلب التشغيل الأوّل صلاحيات المدير لإضافة قاعدة جدار حماية للمنفذ 8009
   (حتى يتمكّن Sonos من جلب البثّ). اسمح بذلك مرّة واحدة.

---

## استكشاف الأخطاء وإصلاحها

**لم يُعثر على أي جهاز Sonos** — يجب أن يكون الحاسوب وأجهزة Sonos على شبكة LAN / WiFi نفسها، ودون عزل لنقاط الوصول.

**متّصل لكن دون صوت** — تأكّد من (أ) أنّ حاسوبك يشغّل شيئًا فعلًا
في هذه اللحظة (لأنّ وضع loopback لا يلتقط سوى الصوت الحيّ)، (ب) أنّ جهاز الإخراج الافتراضي
يطابق ما يجري تشغيله (الإعدادات → مصدر الصوت)، (ج) أنّ جدار الحماية يسمح بالمنفذ 8009.

**أخطاء مجموعة الصوت المحيطي / "must be called on the coordinator"** — يتكفّل بذلك
نظام إعادة المحاولة المضمّن؛ وإن لم يتعافَ، فأوقف التشغيل ثم أعد تشغيله مرّة واحدة.

**أُعيد تشغيل Sonos وتغيّر عنوان IP** — يعمل تلقائيًا؛ إذ تُتعقّب الأجهزة عبر
UID ثابت لا عبر عنوان IP.

**أريد كمونًا أدنى** — حدّ الـ 0.2 ثانية هو مخزن Sonos ذاته. وللنزول دون ذلك
تحتاج إلى وسط نقل مختلف (مرسِل BT منخفض الكمون، أو خرج سلكي).

---

## بنية المشروع

```
.
├── main.py                  # نقطة الدخول
├── run.bat                  # مُشغِّل بنقرة واحدة
├── build.py                 # أداة بناء ملف .exe عبر PyInstaller
├── requirements.txt
├── LICENSE
├── README.md
├── bundle/
│   └── ffmpeg.exe           # (تنزّله بنفسك — غير مُضمَّن في git)
└── sonos_caster/
    ├── capsule.py           # واجهة الكبسولة العائمة (Tkinter + رسم عبر PIL)
    ├── sonos_caster.py      # الاكتشاف، تحديد المنسّق، play_uri، مراقب التشغيل
    ├── http_stream.py       # بثّ HTTP صوتي محلي + مسارا WAV/MP3
    ├── capture.py           # WASAPI loopback
    ├── render.py            # عناصر واجهة أوّلية مضادة للتسنّن عبر PIL
    ├── icon.py              # أيقونة التطبيق (حرف "S" بطراز Sonos)
    ├── ffmpeg_util.py       # محدِّد موقع ffmpeg (PATH / حزمة PyInstaller)
    ├── firewall.py          # مساعد قاعدة وارد للمنفذ 8009
    ├── sysvolume.py         # قراءة/ضبط مستوى الصوت الرئيسي للخفت أثناء التوجيه
    ├── config.py            # حفظ الإعدادات
    ├── autostart.py         # مساعد سجلّ التشغيل مع Windows
    └── diagnostics.py       # تقرير تشخيصي مُضمَّن (داخل التطبيق)
```

---

## الترخيص

MIT — انظر [LICENSE](LICENSE).

Copyright © 2026 MRHong.
