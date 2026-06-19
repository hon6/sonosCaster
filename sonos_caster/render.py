"""High-quality iOS-style rendering via Pillow (anti-aliased, smooth).

Tk's Canvas has no anti-aliasing, so hand-drawn rounded rects / circles look
jagged. Here we render at 3x scale with PIL and downsample with LANCZOS, giving
crisp rounded capsules, switches and shadows. Results are returned as
PhotoImage-ready PIL images the GUI blits onto its Canvas.
"""

from __future__ import annotations

import math
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_SS = 3  # supersample factor for anti-aliasing


def _hex(c: str):
    c = c.lstrip("#")
    if len(c) == 6:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    if len(c) == 8:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4, 6))
    raise ValueError(c)


def capsule(w: int, h: int, fill: str, border: str = None,
            border_w: int = 1, key: str = None) -> Image.Image:
    """A smooth rounded capsule (radius = h/2), anti-aliased.

    When `key` is given (e.g. "#ff00ff" for Tk -transparentcolor), the AA
    edge gradient is preserved by FEATHERING the pill onto a near-black
    backdrop rather than hard-thresholding alpha. Hard threshold made the
    rounded corners look like a binary stair-step; soft feather keeps the
    LANCZOS gradient so the curve glides. The dark feather blends into the
    desktop wallpaper / taskbar (typically dark) almost invisibly; only on
    bright wallpapers does it read as a subtle drop shadow.

    Supersamples at 5x for the pill specifically — finer than the module
    default _SS so the rounded corners read perfectly smooth.
    """
    SS = 5
    W, H = w * SS, h * SS
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = H // 2
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=r, fill=_hex(fill),
                        outline=_hex(border) if border else None,
                        width=border_w * SS if border else 0)
    small = img.resize((w, h), Image.LANCZOS)
    if key is None:
        return small
    # Soft-feather edges: composite onto a near-black backdrop so AA edges
    # fade toward dark (approximating wallpaper behind a HUD). Only pixels
    # that are essentially fully outside the pill (alpha < 16) become the
    # magenta key — the rest keep the smooth gradient.
    backdrop = Image.new("RGBA", (w, h), (10, 10, 13, 255))
    composed = Image.alpha_composite(backdrop, small)
    _, _, _, a = small.split()
    mask = a.point(lambda v: 255 if v >= 16 else 0)
    out = Image.new("RGB", (w, h), _hex(key)[:3])
    out.paste(composed.convert("RGB"), (0, 0), mask)
    return out


def ios_switch(w: int, h: int, pos: float, on_color: str, off_color: str,
               knob: str = "#ffffff", bg: str = None) -> Image.Image:
    """An iOS toggle. pos 0..1 slides the knob; color blends off->on.

    Includes a soft drop shadow under the knob for depth. If `bg` is given, the
    switch is flattened onto that background (RGB) so it sits cleanly on the
    pill with no transparent-edge halo.
    """
    W, H = w * _SS, h * _SS
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = H // 2
    # Blend track color by pos.
    on = _hex(on_color)
    off = _hex(off_color)
    track = tuple(int(off[i] + (on[i] - off[i]) * pos) for i in range(4))
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=r, fill=track)

    # Knob geometry.
    margin = int(H * 0.10)
    kr = (H - 2 * margin) // 2
    left_cx = margin + kr
    right_cx = W - margin - kr
    kcx = int(left_cx + (right_cx - left_cx) * pos)
    kcy = H // 2

    # Soft shadow: draw a dark blurred circle on its own layer.
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse([kcx - kr, kcy - kr + int(H * 0.04),
                kcx + kr, kcy + kr + int(H * 0.04)], fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(_SS * 2))
    img = Image.alpha_composite(img, shadow)

    d = ImageDraw.Draw(img)
    d.ellipse([kcx - kr, kcy - kr, kcx + kr, kcy + kr], fill=_hex(knob))
    small = img.resize((w, h), Image.LANCZOS)
    if bg is None:
        return small
    base = Image.new("RGBA", (w, h), _hex(bg))
    return Image.alpha_composite(base, small).convert("RGB")


def pill_with_shadow(w: int, h: int, fill: str, shadow_blur: int = 6,
                     shadow_alpha: int = 70) -> Image.Image:
    """A capsule with a soft drop shadow, sized to include shadow padding.

    Returns an image of size (w, h); the capsule is inset to leave room for the
    shadow so nothing clips.
    """
    pad = shadow_blur + 2
    W, H = w * _SS, h * _SS
    cap_w = W - pad * 2 * _SS
    cap_h = H - pad * 2 * _SS
    r = cap_h // 2

    # Shadow layer.
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    sd.rounded_rectangle(
        [pad * _SS, pad * _SS + int(H * 0.02),
         pad * _SS + cap_w, pad * _SS + cap_h + int(H * 0.02)],
        radius=r, fill=(0, 0, 0, shadow_alpha))
    sh = sh.filter(ImageFilter.GaussianBlur(shadow_blur * _SS))
    img = Image.alpha_composite(img, sh)

    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        [pad * _SS, pad * _SS, pad * _SS + cap_w, pad * _SS + cap_h],
        radius=r, fill=_hex(fill))
    return img.resize((w, h), Image.LANCZOS)


def level_meter(w: int, h: int, hist: List[float], color: str,
                color_hot: str, dim: str, bg: str) -> Image.Image:
    """An anti-aliased mirrored waveform centered vertically.

    Drawn as a FILLED polygon between top and bottom polylines rather than
    two stroked lines, so at low amplitudes the wave still reads as a single
    solid band instead of two thin separated lines (which look "dashed" /
    interrupted when the amplitude collapses to ~1 pixel either side of mid).
    """
    W, H = w * _SS, h * _SS
    img = Image.new("RGB", (W, H), _hex(bg)[:3])
    d = ImageDraw.Draw(img)
    mid = H / 2
    max_amp = H / 2 - 8 * _SS
    # Faint baseline so the strip never looks empty.
    d.line([(0, mid), (W - 1, mid)], fill=_hex(dim)[:3], width=_SS)
    n = len(hist)
    if n >= 2:
        peak = max(hist[-min(n, 8):])
        col = _hex(color_hot)[:3] if peak >= 0.85 else _hex(color)[:3]
        step = W / max(1, n - 1)
        top, bot = [], []
        for i, lvl in enumerate(hist):
            # Perceptual / compressive scaling — raw int16 peaks rarely sit
            # near 1.0, and when dim_local is on (PC volume dropped to ~2%
            # so you only hear Sonos) the captured loopback amplitude is
            # ~50x quieter than normal. sqrt expands the low range so the
            # wave is clearly visible in both modes without clipping loud
            # passages.
            scaled = math.sqrt(max(0.0, min(1.0, lvl)))
            amp = max(1.5 * _SS, scaled * max_amp)
            x = i * step
            top.append((x, mid - amp))
            bot.append((x, mid + amp))
        # Filled mirrored polygon — always a continuous band.
        poly = top + list(reversed(bot))
        d.polygon(poly, fill=col)
    return img.resize((w, h), Image.LANCZOS)


def volume_slider(w: int, h: int, vol_0_to_1: float, fill_color: str,
                  trough_color: str, knob_color: str = "#ffffff",
                  dragging: bool = False, bg: str = "#23262d") -> Image.Image:
    """Slim track + soft circular knob with subtle drop shadow."""
    W, H = w * _SS, h * _SS
    img = Image.new("RGBA", (W, H), _hex(bg))
    d = ImageDraw.Draw(img)
    mid = H / 2
    pad = 6 * _SS
    track_h = 4 * _SS
    x0, x1 = pad, W - pad
    d.rounded_rectangle([x0, mid - track_h / 2, x1, mid + track_h / 2],
                        radius=track_h / 2, fill=_hex(trough_color))
    fx = x0 + (x1 - x0) * max(0.0, min(1.0, vol_0_to_1))
    if fx > x0 + 1:
        d.rounded_rectangle([x0, mid - track_h / 2, fx, mid + track_h / 2],
                            radius=track_h / 2, fill=_hex(fill_color))
    r = (7 if dragging else 6) * _SS
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse([fx - r, mid - r + int(H * 0.025),
                fx + r, mid + r + int(H * 0.025)], fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(_SS * 2))
    img = Image.alpha_composite(img, shadow)
    d = ImageDraw.Draw(img)
    d.ellipse([fx - r, mid - r, fx + r, mid + r], fill=_hex(knob_color))
    return img.resize((w, h), Image.LANCZOS).convert("RGB")


def icon_close(size: int, x_color: str, circle_bg: str,
               bg: str = "#23262d") -> Image.Image:
    """A round close button: filled circle with an X stroke."""
    W = H = size * _SS
    img = Image.new("RGB", (W, H), _hex(bg)[:3])
    d = ImageDraw.Draw(img)
    margin = 2 * _SS
    d.ellipse([margin, margin, W - margin, H - margin],
              fill=_hex(circle_bg)[:3])
    pad = int(W * 0.34)
    width = max(2, int(2.4 * _SS))
    d.line([(pad, pad), (W - pad - 1, H - pad - 1)],
           fill=_hex(x_color)[:3], width=width)
    d.line([(W - pad - 1, pad), (pad, H - pad - 1)],
           fill=_hex(x_color)[:3], width=width)
    return img.resize((size, size), Image.LANCZOS)


def chip(w: int, h: int, label: str, fg: str, bg_chip: str, bg_outer: str,
         chevron_color: str, font_size: int = 10) -> Image.Image:
    """A rounded 'pill segment' chip: dark inset background with label + caret.

    Drawn at 3x and downsampled so its rounded ends and text both AA cleanly
    against `bg_outer` (which should match the parent capsule's fill, so the
    chip edges blend without a halo).
    """
    W, H = w * _SS, h * _SS
    img = Image.new("RGB", (W, H), _hex(bg_outer)[:3])
    d = ImageDraw.Draw(img)
    pad = 2 * _SS
    r = (H - 2 * pad) // 2
    d.rounded_rectangle([pad, pad, W - pad - 1, H - pad - 1],
                        radius=r, fill=_hex(bg_chip)[:3])

    # CJK-capable font with progressive fallback (Sonos zones often have
    # Chinese names like "卧室"). msyh.ttc ships with Windows.
    font = None
    for name in ("msyh.ttc", "msyhl.ttc", "simhei.ttf", "segoeui.ttf",
                 "arial.ttf"):
        try:
            font = ImageFont.truetype(name, int(font_size * _SS))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    # Reserve a chevron zone on the right; ellipsize the label if needed.
    text_x = int(12 * _SS)
    chevron_zone = int(20 * _SS)
    avail = W - text_x - chevron_zone
    text = label or ""
    while text and d.textlength(text, font=font) > avail:
        text = text[:-1]
    if text != (label or "") and text:
        # Trim one more char and append ellipsis.
        while text and d.textlength(text + "…", font=font) > avail:
            text = text[:-1]
        text = text + "…"
    if text:
        bbox = d.textbbox((0, 0), text, font=font)
        th = bbox[3] - bbox[1]
        y = (H - th) // 2 - bbox[1]
        d.text((text_x, y), text, fill=_hex(fg)[:3], font=font)

    # Down chevron — three-point line stroke, smooth after LANCZOS.
    cx = W - chevron_zone // 2 - pad
    cy = H // 2
    arr_w = int(4 * _SS)
    arr_h = int(2.5 * _SS)
    d.line([(cx - arr_w, cy - arr_h),
            (cx, cy + arr_h),
            (cx + arr_w, cy - arr_h)],
           fill=_hex(chevron_color)[:3], width=int(2 * _SS))
    return img.resize((w, h), Image.LANCZOS)


def chip_row(w: int, h: int, label: str, fg: str, bg: str,
             font_size: int = 10) -> Image.Image:
    """A flat rectangular dropdown row using the SAME font + supersampling
    as `chip()`, so the popup text is pixel-for-pixel consistent with the
    chip's text — no jarring size jump between the trigger and the menu.
    """
    W, H = w * _SS, h * _SS
    img = Image.new("RGB", (W, H), _hex(bg)[:3])
    d = ImageDraw.Draw(img)
    font = None
    for name in ("msyh.ttc", "msyhl.ttc", "simhei.ttf", "segoeui.ttf",
                 "arial.ttf"):
        try:
            font = ImageFont.truetype(name, int(font_size * _SS))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    text_x = int(12 * _SS)
    text = label or ""
    if text:
        bbox = d.textbbox((0, 0), text, font=font)
        th = bbox[3] - bbox[1]
        y = (H - th) // 2 - bbox[1]
        d.text((text_x, y), text, fill=_hex(fg)[:3], font=font)
    return img.resize((w, h), Image.LANCZOS)


def icon_glyph(size: int, glyph: str, color: str, bg: str = "#23262d",
               font_name: Optional[str] = None,
               scale: float = 0.78) -> Image.Image:
    """A single glyph (e.g. a gear ⚙) drawn at 3x and downsampled."""
    W = H = size * _SS
    img = Image.new("RGB", (W, H), _hex(bg)[:3])
    d = ImageDraw.Draw(img)
    font = None
    tries = []
    if font_name:
        tries.append(font_name)
    tries.extend(["seguisym.ttf", "segoeui.ttf", "arial.ttf"])
    for name in tries:
        try:
            font = ImageFont.truetype(name, int(size * _SS * scale))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), glyph, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (W - tw) // 2 - bbox[0]
    y = (H - th) // 2 - bbox[1]
    d.text((x, y), glyph, fill=_hex(color)[:3], font=font)
    return img.resize((size, size), Image.LANCZOS)
