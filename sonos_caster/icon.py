"""Sonos-style app icon. Renders a bold white 'S' on a dark rounded square.

Used as both the window/taskbar icon (via Tk iconphoto) and the .exe icon
(via PyInstaller --icon, see build.py / scripts/gen_icon.py).
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont


_BG = (15, 15, 15, 255)         # near-black, like Sonos branding
_FG = (255, 255, 255, 255)


def _font(px: int) -> ImageFont.ImageFont:
    # Try a few common Windows bold sans-serif faces; fall back to the default.
    for name in ("arialbd.ttf", "seguibd.ttf", "calibrib.ttf", "verdanab.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def make_icon(size: int) -> Image.Image:
    """A square Sonos-style app icon: white 'S' on a dark rounded square."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=_BG)

    font = _font(int(size * 0.72))
    text = "S"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    # Optical-center slightly above geometric center; descender-less glyphs read
    # high otherwise.
    y = (size - th) // 2 - bbox[1] - int(size * 0.02)
    d.text((x, y), text, fill=_FG, font=font)
    return img


def app_icon_photo(root):
    """A PhotoImage suitable for Tk's iconphoto (taskbar icon when minimized)."""
    from PIL import ImageTk
    return ImageTk.PhotoImage(make_icon(64), master=root)


def bundled_ico_path():
    """Locate SonosCaster.ico at runtime: PyInstaller bundle dir OR source tree.

    Returns the absolute path, or None if not found (e.g. running before the
    icon has been generated). Tk's iconbitmap(default=...) needs a real file.
    """
    import os
    import sys
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "SonosCaster.ico"))
    candidates.append(os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "bundle",
                     "SonosCaster.ico")))
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def save_ico(path: str) -> None:
    """Write a multi-resolution .ico (PIL downsamples from the 256px master)."""
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
             (128, 128), (256, 256)]
    make_icon(256).save(path, format="ICO", sizes=sizes)


if __name__ == "__main__":
    import os
    out = os.path.join(os.path.dirname(__file__), "..", "bundle",
                       "SonosCaster.ico")
    out = os.path.abspath(out)
    save_ico(out)
    print("wrote", out)
