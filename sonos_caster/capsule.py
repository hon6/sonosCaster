"""Floating capsule UI — macOS-style pill that forwards PC audio to Sonos.

States (driven by forwarding on/off and mouse hover):

  collapsed + idle      -> small circle with a grey toggle
  collapsed + forwarding -> pill: green toggle + live level line
  hovered (any)         -> expands right: toggle, level line, device dropdown,
                           format (WAV/MP3), volume, settings

The window is borderless, always-on-top, semi-transparent, draggable, and
remembers its position. Rounded corners are drawn on a Canvas; the window uses a
transparent color key so only the pill shows (Windows).
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import List, Optional

from PIL import ImageTk

from . import config as cfg_store
from . import render
from .autostart import is_enabled as is_autostart_enabled
from .autostart import set_enabled as set_autostart_enabled
from .capture import CaptureConfig
from .ffmpeg_util import ffmpeg_available
from .firewall import ensure_firewall_rule
from .sonos_caster import CastState, SonosCaster, SonosDevice, discover_sonos

# iOS-style slider switch geometry.
_SW_W = 50                 # switch track width
_SW_H = 30                 # switch track height
_SW_KNOB = 24              # sliding knob diameter
_SW_PAD = 11               # margin between switch and pill edge (all sides)

# Geometry. The pill HUGS its contents: collapsed it is just the switch + a
# uniform margin (so it reads as "a switch on a small rounded chip", not a
# switch floating in a big box). Height is uniform across states.
_H = _SW_H + _SW_PAD * 2          # pill height (hugs the switch: ~52px)
_COLLAPSED_W = _SW_W + _SW_PAD * 2  # ~72px — snug around the switch
_FORWARD_W = 176                  # pill width when forwarding+unhovered
_EXPANDED_W = 480                 # width when hovered (full controls)
_PAD = 12                         # outer transparent margin

_KNOB_GAP = 12             # gap between switch and the level line
_LEVEL_W_COLLAPSED = 78    # level line width in the forwarding pill state

# Colors (flat, macOS-ish dark).
_TRANSPARENT_KEY = "#ff00ff"   # magenta — made fully transparent on Windows
_BG = "#23262d"                # pill background
_BG_LIGHT = "#31353d"          # control background
_BG_LIGHTER = "#3a3f48"
_TOGGLE_OFF = "#5b616b"        # grey
_TOGGLE_ON = "#34c759"         # macOS green
_TOGGLE_ON_RING = "#7fe0a0"
_LEVEL = "#34c759"
_LEVEL_HOT = "#ff453a"
_LEVEL_DIM = "#3a4a40"         # baseline when quiet
_TEXT = "#f0f0f2"
_MUTED = "#9aa0aa"
_BORDER = "#3d424b"


def _rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    """Draw a filled rounded rectangle (capsule when r = height/2)."""
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


class CapsuleApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = cfg_store.load()

        self.devices: List[SonosDevice] = []
        self.caster: Optional[SonosCaster] = None
        self._forwarding = False
        self._hovered = False
        self._latest_level = 0.0
        self._level_history = [0.0] * 80
        self._cur_w = _COLLAPSED_W
        self._target_w = _COLLAPSED_W
        self._sw_pos = 0.0      # iOS switch knob position (0=off, 1=on)
        self._drag = None
        # `_anchor_x` is the SCREEN x of the collapsed pill's left edge — the
        # one position the user perceives as "where the pill lives". The
        # actual window x is derived from it via `_compute_win_x` and depends
        # on `_expand_left`. When the pill is too close to the right screen
        # edge to expand rightward without clipping, _expand_left flips True
        # and the pill expands toward the left instead (switch stays at the
        # right side of the pill, all other components mirror to its left).
        self._anchor_x = 0
        self._expand_left = False

        self._setup_window()
        self._build()
        self._ensure_prereqs()
        # Discover devices in the background.
        threading.Thread(target=self._scan_worker, daemon=True).start()
        self._animate()
        self._tick_level()

    # ----- window -------------------------------------------------------

    def _setup_window(self):
        self.root.configure(bg=_TRANSPARENT_KEY)
        # Taskbar icon. iconbitmap(default=...) with a real .ico file is what
        # Windows actually shows in the taskbar; iconphoto alone is ignored on
        # Windows when the AppUserModelID is set elsewhere (see main()).
        try:
            from .icon import app_icon_photo, bundled_ico_path
            ico = bundled_ico_path()
            if ico is not None:
                self.root.iconbitmap(default=ico)
            self._icon_photo = app_icon_photo(self.root)
            self.root.iconphoto(True, self._icon_photo)
        except Exception:
            pass

        # Initial position: remembered, else bottom-right. The saved x/y is
        # treated as the COLLAPSED pill's screen anchor (its top-left corner),
        # so the visible pill always lives where the user last left it
        # regardless of expand direction.
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        saved_x = self.cfg.get("x")
        saved_y = self.cfg.get("y")
        if saved_x is None or saved_y is None:
            saved_x = sw - _COLLAPSED_W - 40
            saved_y = sh - _H - 80
        # Clamp to current screen so a monitor change / DPI change since the
        # position was saved doesn't park the pill off-screen.
        self._anchor_x = max(0, min(int(saved_x), sw - _COLLAPSED_W))
        self._win_y = max(0, min(int(saved_y), sh - _H - _PAD * 2))
        self._decide_expand_direction()
        self._win_x = self._compute_win_x()
        self._apply_geometry(_COLLAPSED_W)

        # IMPORTANT ordering — works on both Win10 AND Win11:
        # `-transparentcolor` requires WS_EX_LAYERED, which Tk sets when you
        # apply `-alpha`. On Win11, calling overrideredirect(True) BEFORE
        # -alpha can clear that style and the window paints fully transparent
        # (i.e. invisible) until the user finds it by accident. So: map the
        # window first, set alpha + transparentcolor (now WS_EX_LAYERED is
        # locked in), THEN strip the border, THEN topmost.
        try:
            self.root.attributes("-alpha", 0.82)
            self.root.attributes("-transparentcolor", _TRANSPARENT_KEY)
        except Exception:
            pass
        self.root.update_idletasks()
        self.root.deiconify()
        self.root.lift()
        self.root.update()
        self.root.overrideredirect(True)          # borderless (after mapping)
        self.root.attributes("-topmost", True)     # float above
        # Win11 sometimes still needs several deferred kicks — mapping, layered
        # style and topmost can race during the first frames. Re-assert.
        for ms in (50, 200, 500, 1000):
            self.root.after(ms, self._force_show)

    def _decide_expand_direction(self):
        """Pick left- vs right-expansion based on room on the right of anchor.

        If expanding rightward would push the pill past the screen edge, we
        flip to left-expansion: the switch then stays on the RIGHT side of the
        pill and all other components mirror to its left. A small margin
        avoids flip-flop right at the boundary.
        """
        sw = self.root.winfo_screenwidth()
        margin = 8
        self._expand_left = (
            self._anchor_x + _EXPANDED_W + _PAD > sw - margin)

    def _compute_win_x(self) -> int:
        """Screen x of the WINDOW. Differs from `_anchor_x` because the canvas
        is always full _EXPANDED_W wide and the pill is drawn flush-left
        (right-expand) or flush-right (left-expand) inside it.
        """
        if self._expand_left:
            return self._anchor_x - _PAD - _EXPANDED_W + _COLLAPSED_W
        return self._anchor_x - _PAD

    def _force_show(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
        except Exception:
            pass

    def _apply_geometry(self, w: int):
        total_w = _EXPANDED_W + _PAD * 2      # canvas always full size; pill grows
        total_h = _H + _PAD * 2
        self.root.geometry(
            f"{total_w}x{total_h}+{self._win_x}+{self._win_y}"
        )

    def _build(self):
        # Canvas background = the transparent key so the window's corners (and
        # the area to the right of a collapsed pill) are fully see-through.
        self.canvas = tk.Canvas(
            self.root, highlightthickness=0, bg=_TRANSPARENT_KEY,
            width=_EXPANDED_W + _PAD * 2, height=_H + _PAD * 2,
        )
        self.canvas.pack(fill="both", expand=True)

        # Drag on the canvas; hover is handled by polling the pointer position
        # globally (Enter/Leave on a transparent-key canvas is unreliable and
        # caused expand/collapse flicker).
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        self._redraw()
        self._poll_hover()

    # ----- hover / drag -------------------------------------------------

    def _poll_hover(self):
        """Decide hover by the real pointer position vs the whole window rect.

        Once expanded, we treat the ENTIRE window area (not just the drawn pill)
        as the hover zone, with a small margin, so moving onto the dropdowns
        never counts as 'leaving'. A short collapse delay debounces jitter.
        """
        try:
            px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()
            wx, wy = self._win_x, self._win_y
            total_w = _EXPANDED_W + _PAD * 2
            total_h = _H + _PAD * 2
            margin = 6
            inside = (wx - margin <= px <= wx + total_w + margin and
                      wy - margin <= py <= wy + total_h + margin)
        except Exception:
            inside = False

        # If the device dropdown popup is open, keep the pill expanded — the
        # cursor will be over the popup, OUTSIDE the pill's hover zone, but
        # collapsing would orphan/dismiss the menu the user just opened.
        popup = getattr(self, "_dev_popup", None)
        popup_open = False
        try:
            popup_open = popup is not None and popup.winfo_exists()
        except Exception:
            pass
        if inside or popup_open:
            self._hover_leave_ticks = 0
            if not self._hovered:
                self._hovered = True
                self._update_target_width()
        else:
            # Debounce: require several consecutive 'outside' polls before
            # collapsing, so brief pointer jumps don't cause flicker.
            self._hover_leave_ticks = getattr(self, "_hover_leave_ticks", 0) + 1
            if self._hovered and self._hover_leave_ticks >= 4:
                self._hovered = False
                self._update_target_width()
        self.root.after(60, self._poll_hover)

    def _update_target_width(self):
        if self._hovered:
            self._target_w = _EXPANDED_W
        elif self._forwarding:
            self._target_w = _FORWARD_W
        else:
            self._target_w = _COLLAPSED_W

    def _on_press(self, e):
        # Take focus so embedded comboboxes can open their dropdowns (an
        # overrideredirect window does not auto-focus on click).
        try:
            self.root.focus_force()
        except Exception:
            pass
        # Record start for drag vs click discrimination.
        self._drag = {"x": e.x_root, "y": e.y_root,
                      "wx": self._win_x, "wy": self._win_y, "moved": False}

    def _on_drag(self, e):
        if not self._drag:
            return
        dx = e.x_root - self._drag["x"]
        dy = e.y_root - self._drag["y"]
        if abs(dx) > 3 or abs(dy) > 3:
            self._drag["moved"] = True
        self._win_x = self._drag["wx"] + dx
        self._win_y = self._drag["wy"] + dy
        self._apply_geometry(self._cur_w)

    def _on_release(self, e):
        if self._drag and not self._drag["moved"]:
            # A click (not a drag): hit-test the toggle.
            self._handle_click(e.x, e.y)
        if self._drag and self._drag["moved"]:
            # Convert dragged window position back to anchor (where the visible
            # pill ended up), then re-decide expand direction. If the user
            # dragged the pill across the right-edge threshold, the canvas
            # layout flips — but the math keeps the VISIBLE pill in place
            # (anchor unchanged, canvas absorbs the new direction).
            if self._expand_left:
                self._anchor_x = (
                    self._win_x + _PAD + _EXPANDED_W - _COLLAPSED_W)
            else:
                self._anchor_x = self._win_x + _PAD
            sw = self.root.winfo_screenwidth()
            self._anchor_x = max(0, min(self._anchor_x, sw - _COLLAPSED_W))
            prev_dir = self._expand_left
            self._decide_expand_direction()
            self._win_x = self._compute_win_x()
            self._apply_geometry(self._cur_w)
            if prev_dir != self._expand_left:
                # Force a full re-render so the mirror layout takes effect now.
                self._pill_w_cached = None
                self._redraw()
            self.cfg["x"] = self._anchor_x
            self.cfg["y"] = self._win_y
            cfg_store.save(self.cfg)
        self._drag = None

    # ----- click handling ----------------------------------------------

    def _toggle_center(self):
        # Center of the iOS-style switch (used for layout reference).
        cx = _PAD + _SW_PAD + _SW_W / 2
        cy = _PAD + _H / 2
        return cx, cy

    def _toggle_rect(self):
        """Bounding box of the iOS switch track.

        In left-expand mode the switch lives at the RIGHT side of the pill so
        the rest of the controls can grow leftward from it.
        """
        if self._expand_left:
            x0 = _PAD + _EXPANDED_W - _SW_PAD - _SW_W
        else:
            x0 = _PAD + _SW_PAD
        y0 = _PAD + (_H - _SW_H) / 2
        return x0, y0, x0 + _SW_W, y0 + _SW_H

    def _handle_click(self, x, y):
        # Toggle hit area = the switch track (a bit padded for easy tapping).
        x0, y0, x1, y1 = self._toggle_rect()
        if x0 - 6 <= x <= x1 + 6 and y0 - 6 <= y <= y1 + 6:
            self._toggle_forwarding()
            return
        # Clicks in the expanded area: device dropdown / format handled by
        # embedded ttk widgets (see _layout_expanded_widgets).

    # ----- forwarding ---------------------------------------------------

    def _toggle_forwarding(self):
        # Debounce rapid clicks: ignore a new toggle until the last one settled.
        import time as _t
        now = _t.monotonic() if hasattr(_t, "monotonic") else 0
        if now and now - getattr(self, "_last_toggle", 0) < 0.6:
            return
        self._last_toggle = now
        # Decide by the real caster state, not just the optimistic flag.
        active = self.caster is not None and self.caster.state in (
            CastState.STARTING, CastState.PLAYING)
        if active or self._forwarding:
            self._stop_forwarding()
        else:
            self._start_forwarding()

    def _start_forwarding(self):
        device = self._current_device()
        if device is None:
            self._flash("未找到设备")
            return
        if ffmpeg_available() is None:
            self._flash("缺少 ffmpeg")
            return
        self.caster = SonosCaster(
            status_cb=self._on_status,
            codec=self.cfg.get("codec", "wav"),
            dim_local=self.cfg.get("dim_local", True),
            capture_config=CaptureConfig(
                blocksize=int(self.cfg.get("blocksize", 512)),
                device_name=self.cfg.get("audio_device"),
            ),
            lan_ip_override=self.cfg.get("lan_ip"),
        )
        self.caster.set_level_callback(self._on_level)
        self._forwarding = True
        self._update_target_width()
        threading.Thread(
            target=lambda: self.caster.start(device), daemon=True
        ).start()

    def _stop_forwarding(self):
        if self.caster is not None:
            c = self.caster
            threading.Thread(target=c.stop, daemon=True).start()
        self._forwarding = False
        self._latest_level = 0.0
        self._update_target_width()

    def _on_status(self, state: CastState, message: str):
        def apply():
            # Drive the switch from the ACTUAL forwarding state so a fast click
            # can't leave the switch showing "off" while it's really playing.
            if state in (CastState.STARTING, CastState.PLAYING):
                self._forwarding = True
            elif state in (CastState.IDLE, CastState.ERROR, CastState.STOPPING):
                self._forwarding = False
            self._update_target_width()  # also re-renders the switch position
            if state == CastState.PLAYING and self.caster is not None:
                self.caster.set_volume(self.cfg.get("volume", 30))
            if state == CastState.ERROR:
                self._flash(message)
        self.root.after(0, apply)

    def _on_level(self, peak: float):
        # VU-meter style smoothing: fast attack catches transients so beats
        # still pop; slow release keeps the wave undulating between hits
        # instead of snapping back to baseline (which made the meter look
        # like sparse spiky needles). The audio path is unaffected — this
        # only smooths what the meter DISPLAYS.
        prev = self._latest_level
        if peak > prev:
            self._latest_level = prev + (peak - prev) * 0.55
        else:
            self._latest_level = prev + (peak - prev) * 0.10

    # ----- device / settings -------------------------------------------

    def _scan_worker(self):
        try:
            found = discover_sonos(timeout=5.0)
        except Exception:
            found = []
        self.root.after(0, lambda: self._set_devices(found))

    def _set_devices(self, found: List[SonosDevice]):
        self.devices = found
        # Restore last device by uid if present.
        if found and self.cfg.get("device_uid"):
            for d in found:
                if d.uid == self.cfg["device_uid"]:
                    self._selected_uid = d.uid
                    break
        self._redraw()

    def _current_device(self) -> Optional[SonosDevice]:
        if not self.devices:
            return None
        uid = self.cfg.get("device_uid")
        for d in self.devices:
            if d.uid == uid:
                return d
        return self.devices[0]

    def _ensure_prereqs(self):
        def work():
            ok, msg = ensure_firewall_rule(8009)
            if not ok:
                # Surface the failure so the user knows to allow it / run as
                # admin, instead of silently having no sound.
                self.root.after(0, lambda: self._flash("防火墙未放行,可能没声"))
        threading.Thread(target=work, daemon=True).start()

    # ----- drawing ------------------------------------------------------

    def _flash(self, msg: str):
        self._flash_msg = msg
        self._flash_until = 60  # frames
        self._redraw()

    def _redraw(self):
        c = self.canvas
        c.delete("all")
        w = int(self._cur_w)

        # --- smooth PIL-rendered pill background (anti-aliased) ---
        if getattr(self, "_pill_w_cached", None) != w:
            self._pill_w_cached = w
            img = render.capsule(w, _H, _BG, border=_BORDER, border_w=1,
                                 key=_TRANSPARENT_KEY)
            self._pill_img = ImageTk.PhotoImage(img)
        # Pill is drawn flush-left for right-expand and flush-right for
        # left-expand so the COLLAPSED pill stays at its anchor position while
        # expansion grows in the chosen direction.
        pill_x = (_PAD + _EXPANDED_W - w) if self._expand_left else _PAD
        c.create_image(pill_x, _PAD, anchor="nw", image=self._pill_img)

        # --- iOS-style slider switch (PIL, anti-aliased) ---
        self._draw_ios_switch(c)

        # --- level line (forwarding pill, or expanded) ---
        sw_x0, _, sw_x1, _ = self._toggle_rect()
        show_level = self._forwarding or w > _FORWARD_W - 12
        if show_level:
            if self._expand_left:
                lvl_x1 = sw_x0 - _KNOB_GAP
                if w >= _EXPANDED_W - 8:
                    lvl_x0 = lvl_x1 - 86
                else:
                    lvl_x0 = (_PAD + _EXPANDED_W - w) + 16
            else:
                lvl_x0 = sw_x1 + _KNOB_GAP
                if w >= _EXPANDED_W - 8:
                    lvl_x1 = lvl_x0 + 86
                else:
                    lvl_x1 = _PAD + w - 16
            self._draw_level(c, lvl_x0, lvl_x1)

        # --- expanded controls ---
        if w >= _EXPANDED_W - 8:
            self._layout_expanded_widgets()
        else:
            self._hide_expanded_widgets()

    def _draw_ios_switch(self, c):
        """iOS toggle rendered with PIL (smooth track, knob, soft shadow)."""
        x0, y0, x1, y1 = self._toggle_rect()
        # Animate knob position toward target.
        target = 1.0 if self._forwarding else 0.0
        self._sw_pos = self._sw_pos + (target - self._sw_pos) * 0.35
        if abs(self._sw_pos - target) < 0.02:
            self._sw_pos = target

        # Cache switch images at a few discrete positions to avoid re-rendering
        # every frame (round pos to 0.05 steps).
        key = round(self._sw_pos, 2)
        cache = getattr(self, "_sw_cache", None)
        if cache is None:
            cache = self._sw_cache = {}
        if key not in cache:
            img = render.ios_switch(_SW_W, _SW_H, key, _TOGGLE_ON, _TOGGLE_OFF,
                                    bg=_BG)
            cache[key] = ImageTk.PhotoImage(img)
            # Bound cache size.
            if len(cache) > 40:
                cache.clear()
                cache[key] = ImageTk.PhotoImage(render.ios_switch(
                    _SW_W, _SW_H, key, _TOGGLE_ON, _TOGGLE_OFF, bg=_BG))
        self._sw_img = cache[key]
        c.create_image(int(x0), int(y0), anchor="nw", image=self._sw_img)

    def _draw_level(self, c, x0, x1):
        """Anti-aliased mirrored waveform — rendered in PIL and blitted.

        Tk's create_line(smooth=True) gives a smooth path but each pixel still
        snaps to the grid (no AA). Rendering with PIL at 3x then LANCZOSing
        down gives true sub-pixel smoothing so the wave glides cleanly along
        the pill instead of crawling pixel-by-pixel.
        """
        span = int(x1 - x0)
        if span < 12:
            return
        self._level_history.append(self._latest_level)
        if len(self._level_history) > span:
            self._level_history = self._level_history[-span:]
        # Inset by 1px top + bottom so the pill's lighter rim border keeps
        # going through this zone instead of getting overpainted (which
        # made the border look "dashed" where the level meter ran).
        inner_h = _H - 2
        img = render.level_meter(
            span, inner_h, self._level_history,
            _LEVEL, _LEVEL_HOT, _LEVEL_DIM, _BG,
        )
        # Reuse a single PhotoImage per (width, height) — `paste` updates the
        # pixels of an existing Tk image without creating a new C-side image
        # object. Avoids a slow PhotoImage allocate-then-GC churn that, over
        # many minutes of 20 fps redraws, was holding the GIL longer than
        # necessary and starving the audio thread (= one suspect for the
        # gradually-worsening stutter).
        cache = getattr(self, "_level_img_cache", None)
        if cache is None:
            cache = self._level_img_cache = {}
        key = (span, inner_h)
        if key not in cache:
            cache[key] = ImageTk.PhotoImage(img)
            # Bound cache so a rapidly-resizing pill (rare) can't grow it
            # forever; current width gets re-created on next frame.
            if len(cache) > 6:
                cache.clear()
                cache[key] = ImageTk.PhotoImage(img)
        else:
            cache[key].paste(img)
        self._level_img = cache[key]
        c.create_image(int(x0), _PAD + 1, anchor="nw", image=self._level_img)

    # --- embedded ttk widgets for the expanded state -------------------

    def _ensure_expanded_widgets(self):
        if getattr(self, "_exp_built", False):
            return
        self._exp_built = True

        # Dark dropdown list styling for SettingsDialog's still-ttk comboboxes
        # (audio device, LAN IP, blocksize). Set here so the option DB has them
        # before any ttk.Combobox listbox materialises.
        self.root.option_add("*TCombobox*Listbox.background", _BG_LIGHT)
        self.root.option_add("*TCombobox*Listbox.foreground", _TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", _TOGGLE_ON)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)

        # Device chip — a fully PIL-rendered "pill segment" with the current
        # device name + a down chevron. Replaces ttk.Combobox so the control
        # blends with the capsule instead of looking like a Windows widget.
        self._dev_chip_w = 130
        self._dev_chip_h = 28
        self.device_canvas = tk.Canvas(
            self.root, width=self._dev_chip_w, height=self._dev_chip_h,
            bg=_BG, highlightthickness=0, cursor="hand2",
        )
        self.device_canvas.bind("<Button-1>",
                                lambda e: self._open_device_menu())
        self.device_canvas.bind("<Enter>",
                                lambda e: self._draw_device_chip(hover=True))
        self.device_canvas.bind("<Leave>",
                                lambda e: self._draw_device_chip(hover=False))
        self._dev_chip_hover = False

        # Custom slim volume slider: a thin track with a small draggable dot,
        # plus a number to its right that appears while dragging.
        self.vol_var = tk.IntVar(value=int(self.cfg.get("volume", 30)))
        self._vol_w = 96
        # Inset 1px top + bottom so the pill's lighter rim border keeps going
        # through the slider zone (same reason as the level meter inset).
        self.vol_canvas = tk.Canvas(
            self.root, width=self._vol_w, height=_H - 2, bg=_BG,
            highlightthickness=0, cursor="hand2",
        )
        self.vol_canvas.bind("<Button-1>", self._on_vol_drag)
        self.vol_canvas.bind("<B1-Motion>", self._on_vol_drag)
        self.vol_num = tk.Label(self.root, text="", bg=_BG, fg=_TEXT,
                                font=("Segoe UI", 9))

        # Gear button — PIL-rendered glyph on a Canvas to match the smooth
        # AA look of the rest of the capsule (a tk.Label with a Segoe UI
        # Symbol glyph looked pixelated next to the AA pill).
        self.settings_btn = tk.Canvas(
            self.root, width=24, height=24, bg=_BG, highlightthickness=0,
            cursor="hand2",
        )
        self.settings_btn.bind("<Button-1>", lambda e: self._open_settings())
        self.settings_btn.bind("<Enter>", lambda e: self._draw_gear(hover=True))
        self.settings_btn.bind("<Leave>",
                               lambda e: self._draw_gear(hover=False))

        # Round close button — fully exits the app (stops forwarding, saves
        # position, destroys the root). The old behavior was hide-to-tray
        # (drop overrideredirect, iconify), but on Win11 that combination is
        # unreliable: the layered/transparent window often doesn't get a real
        # taskbar entry, so X "did nothing" from the user's perspective.
        # Exiting is unambiguous: click X -> pill is gone.
        self.close_btn = tk.Canvas(
            self.root, width=24, height=24, bg=_BG, highlightthickness=0,
            cursor="hand2",
        )
        self.close_btn.bind("<Button-1>", lambda e: self.on_close())
        self.close_btn.bind("<Enter>", lambda e: self._draw_close(hover=True))
        self.close_btn.bind("<Leave>", lambda e: self._draw_close(hover=False))

    def _layout_expanded_widgets(self):
        self._ensure_expanded_widgets()
        y = _PAD + _H // 2

        if self._expand_left:
            # Mirror layout, reading left→right INSIDE the pill:
            # [close][gear][num][vol][chip][level meter][switch]
            close_x = _PAD + 6
            gear_x = close_x + 32
            vol_x = 93
            chip_x = 195
            self.device_canvas.place(x=chip_x, y=y - self._dev_chip_h // 2,
                                     anchor="nw")
            self.vol_canvas.place(x=vol_x, y=_PAD + 1, anchor="nw")
            self.vol_num.place(x=vol_x - 4, y=y, anchor="e")
            self.settings_btn.place(x=gear_x, y=y - 12, anchor="nw")
            self.close_btn.place(x=close_x, y=y - 12, anchor="nw")
        else:
            # Right-expand layout, switch on the LEFT side of the pill:
            # [switch][level 86][chip][vol][num][gear][close]
            base_x = _PAD + _H + _KNOB_GAP + 86 + 14
            self.device_canvas.place(x=base_x, y=y - self._dev_chip_h // 2,
                                     anchor="nw")
            vol_x = base_x + self._dev_chip_w + 6
            self.vol_canvas.place(x=vol_x, y=_PAD + 1, anchor="nw")
            self.vol_num.place(x=vol_x + self._vol_w + 4, y=y, anchor="w")
            close_x = _PAD + _EXPANDED_W - 30
            gear_x = close_x - 32
            self.settings_btn.place(x=gear_x, y=y - 12, anchor="nw")
            self.close_btn.place(x=close_x, y=y - 12, anchor="nw")

        self._draw_device_chip()
        self._draw_volume()
        self._draw_gear(hover=False)
        self._draw_close(hover=False)
        for wdg in (self.device_canvas, self.vol_canvas, self.vol_num,
                    self.settings_btn, self.close_btn):
            try:
                wdg.lift()
            except Exception:
                pass

    def _hide_expanded_widgets(self):
        for name in ("device_canvas", "vol_canvas", "vol_num", "settings_btn",
                     "close_btn"):
            w = getattr(self, name, None)
            if w is not None:
                w.place_forget()

    def _draw_device_chip(self, hover=None):
        c = getattr(self, "device_canvas", None)
        if c is None:
            return
        if hover is not None:
            self._dev_chip_hover = bool(hover)
        cur = self._current_device()
        label = cur.name if cur else ("(搜索中…)" if not self.devices else "(选择设备)")
        bg_chip = _BG_LIGHTER if self._dev_chip_hover else _BG_LIGHT
        img = render.chip(self._dev_chip_w, self._dev_chip_h, label,
                          _TEXT, bg_chip, _BG, _MUTED, font_size=10)
        self._chip_img = ImageTk.PhotoImage(img)
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=self._chip_img)

    def _open_device_menu(self):
        if not self.devices:
            return
        existing = getattr(self, "_dev_popup", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.destroy()
            except Exception:
                pass
        self._dev_popup = _DeviceMenu(
            self.root, self.devices, self._on_device_pick,
            self.device_canvas, current_uid=self.cfg.get("device_uid"),
        )

    def _on_device_pick(self, device):
        self.cfg["device_uid"] = device.uid
        self.cfg["device_name"] = device.name
        cfg_store.save(self.cfg)
        self._draw_device_chip()

    # ----- custom volume slider (thin track + small dot + number) -------

    def _draw_volume(self, dragging=False):
        c = getattr(self, "vol_canvas", None)
        if c is None:
            return
        c.delete("all")
        vol = int(self.vol_var.get())
        img = render.volume_slider(
            self._vol_w, _H - 2, vol / 100.0,
            _TOGGLE_ON, _BG_LIGHTER, "#ffffff", dragging, _BG,
        )
        self._vol_img = ImageTk.PhotoImage(img)
        c.create_image(0, 0, anchor="nw", image=self._vol_img)

    def _on_vol_drag(self, e):
        w = self._vol_w
        pad = 6
        x = max(pad, min(w - pad, e.x))
        vol = int(round((x - pad) / (w - 2 * pad) * 100))
        self.vol_var.set(vol)
        self.vol_num.configure(text=str(vol))
        self._draw_volume(dragging=True)
        self._on_vol()
        # Hide the number a moment after dragging stops.
        if getattr(self, "_volnum_after", None):
            try:
                self.root.after_cancel(self._volnum_after)
            except Exception:
                pass
        self._volnum_after = self.root.after(
            1200, lambda: self.vol_num.configure(text=""))

    def _on_vol(self):
        # Update the value instantly (keeps the slider snappy) but DEBOUNCE the
        # network volume call + disk save so dragging doesn't block on every
        # pixel — that was what made it feel sluggish.
        self.cfg["volume"] = int(self.vol_var.get())
        if getattr(self, "_vol_after", None) is not None:
            try:
                self.root.after_cancel(self._vol_after)
            except Exception:
                pass
        self._vol_after = self.root.after(120, self._commit_vol)

    # ----- round close button -> hide to tray --------------------------

    def _draw_close(self, hover=False):
        c = getattr(self, "close_btn", None)
        if c is None:
            return
        c.delete("all")
        cache = getattr(self, "_btn_cache", None)
        if cache is None:
            cache = self._btn_cache = {}
        key = ("close", bool(hover))
        if key not in cache:
            bg_circle = _BG_LIGHTER if hover else _BG_LIGHT
            x_col = _TEXT if hover else _MUTED
            img = render.icon_close(24, x_col, bg_circle, _BG)
            cache[key] = ImageTk.PhotoImage(img)
        self._close_img = cache[key]
        c.create_image(0, 0, anchor="nw", image=self._close_img)

    def _draw_gear(self, hover=False):
        c = getattr(self, "settings_btn", None)
        if c is None:
            return
        c.delete("all")
        cache = getattr(self, "_btn_cache", None)
        if cache is None:
            cache = self._btn_cache = {}
        key = ("gear", bool(hover))
        if key not in cache:
            col = _TEXT if hover else _MUTED
            img = render.icon_glyph(24, "\u2699", col, _BG,
                                    "seguisym.ttf", 0.78)
            cache[key] = ImageTk.PhotoImage(img)
        self._gear_img = cache[key]
        c.create_image(0, 0, anchor="nw", image=self._gear_img)

    def _commit_vol(self):
        self._vol_after = None
        vol = int(self.cfg.get("volume", 30))
        if self.caster is not None:
            # Run the SOAP call off the UI thread.
            threading.Thread(
                target=lambda: self.caster.set_volume(vol), daemon=True
            ).start()
        cfg_store.save(self.cfg)

    def _open_settings(self):
        SettingsDialog(self.root, self.cfg, self._on_settings_changed)

    def _on_settings_changed(self):
        cfg_store.save(self.cfg)

    # ----- animation loops ---------------------------------------------

    def _animate(self):
        # Smoothly approach target width AND animate the switch knob slide.
        moving_w = abs(self._cur_w - self._target_w) > 1
        sw_target = 1.0 if self._forwarding else 0.0
        moving_sw = abs(self._sw_pos - sw_target) > 0.02
        if moving_w:
            self._cur_w += (self._target_w - self._cur_w) * 0.3
            if abs(self._cur_w - self._target_w) <= 1:
                self._cur_w = self._target_w
        if moving_w or moving_sw:
            self._redraw()
        self.root.after(16, self._animate)

    def _tick_level(self):
        # Redraw the level line while forwarding/expanded.
        if self._forwarding or self._cur_w >= _EXPANDED_W - 8:
            self._redraw()
        # 100 ms (10 fps) — was 50 ms but at 20 fps the Tk Canvas redraw +
        # PIL render combo measurably steals CPU from the audio capture
        # thread, contributing to the under-a-minute stutter cascade.
        self.root.after(100, self._tick_level)

    # ----- minimize to taskbar (reliable; no tray dependency) ----------

    def _hide_to_tray(self):
        """Minimize to the taskbar (does NOT stop forwarding / quit).

        An overrideredirect (borderless) window can't iconify and has no taskbar
        button. So we briefly drop overrideredirect, iconify (now it minimizes
        to the taskbar like a normal app), and restore overrideredirect when the
        user clicks the taskbar button to bring it back.
        """
        self.cfg["x"], self.cfg["y"] = self._anchor_x, self._win_y
        cfg_store.save(self.cfg)
        try:
            self.root.overrideredirect(False)
            self.root.update_idletasks()
            self.root.iconify()
            # When restored from the taskbar, re-apply the borderless look.
            self.root.bind("<Map>", self._on_restore)
        except Exception:
            # Fallback: just withdraw (last resort).
            self.root.withdraw()
            self.root.after(100, self._on_restore)

    def _on_restore(self, event=None):
        try:
            self.root.unbind("<Map>")
        except Exception:
            pass
        try:
            self.root.deiconify()
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self._apply_geometry(int(self._cur_w))
            self.root.lift()
        except Exception:
            pass

    def on_close(self):
        if self.caster is not None:
            try:
                self.caster.stop()
            except Exception:
                pass
        self.cfg["x"], self.cfg["y"] = self._anchor_x, self._win_y
        cfg_store.save(self.cfg)
        self.root.after(200, self.root.destroy)


class _DeviceMenu(tk.Toplevel):
    """A borderless dark dropdown anchored flush against the device chip.

    Visually reads as a "drawer" pulled out of the chip:
      - Same width as the chip (left/right edges line up)
      - Zero gap below the chip (top edge of menu = bottom edge of chip)
      - Rows rendered through the SAME PIL pipeline / font / size as the
        chip itself, so the dropdown text has identical glyph metrics —
        no jump in size or weight between trigger and menu.
      - Hover swaps PIL images via Canvas.itemconfig (cheap, snappy).

    Auto-dismisses ~1 s after the cursor leaves (overrideredirect windows
    don't reliably receive FocusOut on Win11).
    """

    _ROW_H = 28
    _FONT_SIZE = 10

    def __init__(self, parent, devices, on_select, anchor_widget,
                 current_uid=None):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        # No border / no inner Frame — the popup IS the chip's background
        # color, so it reads as a vertical extension instead of a separate
        # floating panel.
        self.configure(bg=_BG_LIGHT)

        self._on_select = on_select
        anchor_w = anchor_widget.winfo_width()
        self._row_imgs = {}       # uid -> (idle_photo, hover_photo)
        self._row_canvases = {}   # uid -> Canvas

        for i, dev in enumerate(devices):
            is_cur = dev.uid == current_uid
            base = _BG_LIGHTER if is_cur else _BG_LIGHT
            idle_pil = render.chip_row(
                anchor_w, self._ROW_H, dev.name, _TEXT, base,
                font_size=self._FONT_SIZE,
            )
            hover_pil = render.chip_row(
                anchor_w, self._ROW_H, dev.name, _TEXT, _BG_LIGHTER,
                font_size=self._FONT_SIZE,
            )
            idle_photo = ImageTk.PhotoImage(idle_pil)
            hover_photo = ImageTk.PhotoImage(hover_pil)
            self._row_imgs[dev.uid] = (idle_photo, hover_photo)

            cv = tk.Canvas(self, width=anchor_w, height=self._ROW_H,
                           bg=base, highlightthickness=0, cursor="hand2")
            cv._img_id = cv.create_image(0, 0, anchor="nw",
                                         image=idle_photo)
            cv.place(x=0, y=i * self._ROW_H,
                     width=anchor_w, height=self._ROW_H)
            self._row_canvases[dev.uid] = cv

            cv.bind("<Enter>",
                    lambda e, u=dev.uid: self._set_row(u, hover=True))
            cv.bind("<Leave>",
                    lambda e, u=dev.uid: self._set_row(u, hover=False))
            cv.bind("<Button-1>", lambda e, d=dev: self._pick(d))

        # Flush against the chip: no gap, same width, same x.
        x = anchor_widget.winfo_rootx()
        y = anchor_widget.winfo_rooty() + anchor_widget.winfo_height()
        h = len(devices) * self._ROW_H
        self.geometry(f"{anchor_w}x{h}+{x}+{y}")

        self._outside_ticks = 0
        self.after(180, self._poll_dismiss)

    def _set_row(self, uid, hover):
        cv = self._row_canvases.get(uid)
        if cv is None:
            return
        idle, hov = self._row_imgs[uid]
        cv.itemconfig(cv._img_id, image=(hov if hover else idle))

    def _poll_dismiss(self):
        if not self.winfo_exists():
            return
        try:
            px, py = self.winfo_pointerx(), self.winfo_pointery()
            x = self.winfo_rootx()
            y = self.winfo_rooty()
            ww = self.winfo_width()
            hh = self.winfo_height()
            margin = 8
            inside = (x - margin <= px <= x + ww + margin and
                      y - margin <= py <= y + hh + margin)
        except Exception:
            inside = False
        if inside:
            self._outside_ticks = 0
        else:
            self._outside_ticks += 1
            if self._outside_ticks >= 6:  # ~1s outside -> dismiss
                try:
                    self.destroy()
                except Exception:
                    pass
                return
        self.after(180, self._poll_dismiss)

    def _pick(self, device):
        try:
            self._on_select(device)
        finally:
            try:
                self.destroy()
            except Exception:
                pass


class SettingsDialog(tk.Toplevel):
    """Small settings popup: blocksize, dim-local, autostart."""

    def __init__(self, parent, cfg, on_change):
        super().__init__(parent)
        self.cfg = cfg
        self.on_change = on_change
        self.title("设置")
        self.configure(bg=_BG)
        self.attributes("-topmost", True)
        self.resizable(False, False)

        pad = {"padx": 10, "pady": 6}
        frm = tk.Frame(self, bg=_BG)
        frm.pack(**pad)

        # Audio source device — the key control for capturing the RIGHT output
        # (e.g. headphones) when the system default isn't where audio plays.
        tk.Label(frm, text="音频来源 (抓哪个设备的声音)", bg=_BG, fg=_TEXT).grid(
            row=0, column=0, sticky="w")
        from .capture import list_output_devices, LoopbackCapture
        devs = ["(系统默认)"] + list_output_devices()
        cur_dev = cfg.get("audio_device") or "(系统默认)"
        if cur_dev not in devs:
            devs.append(cur_dev)
        self.dev_var = tk.StringVar(value=cur_dev)
        ttk.Combobox(
            frm, textvariable=self.dev_var, state="readonly", width=30,
            values=devs,
        ).grid(row=0, column=1, padx=6, sticky="w")
        default_name = LoopbackCapture.default_speaker_name()
        tk.Label(frm, text=f"当前默认: {default_name}", bg=_BG, fg=_MUTED,
                 font=("", 8)).grid(row=1, column=0, columnspan=2, sticky="w")

        # Local IP that Sonos connects back to. On multi-NIC hosts (VMware/WSL/
        # Tailscale) auto-pick can choose an unreachable address; let the user
        # pick the one on the Sonos's subnet.
        tk.Label(frm, text="本机IP (Sonos回连用, 选和音箱同网段)", bg=_BG,
                 fg=_TEXT).grid(row=2, column=0, sticky="w", pady=(8, 0))
        from .http_stream import _all_ipv4
        ips = ["(自动)"] + _all_ipv4()
        cur_ip = cfg.get("lan_ip") or "(自动)"
        if cur_ip not in ips:
            ips.append(cur_ip)
        self.ip_var = tk.StringVar(value=cur_ip)
        ttk.Combobox(
            frm, textvariable=self.ip_var, state="readonly", width=30,
            values=ips,
        ).grid(row=2, column=1, padx=6, sticky="w", pady=(8, 0))

        tk.Label(frm, text="采集帧数 (越小越低延迟)", bg=_BG, fg=_TEXT).grid(
            row=3, column=0, sticky="w", pady=(8, 0))
        self.bs_var = tk.IntVar(value=int(cfg.get("blocksize", 512)))
        ttk.Combobox(
            frm, textvariable=self.bs_var, state="readonly", width=6,
            values=[64, 128, 256, 512, 1024],
        ).grid(row=3, column=1, padx=6, sticky="w", pady=(8, 0))

        self.dim_var = tk.BooleanVar(value=bool(cfg.get("dim_local", True)))
        tk.Checkbutton(
            frm, text="转发时电脑几乎静音", variable=self.dim_var, bg=_BG,
            fg=_TEXT, selectcolor=_BG_LIGHT, activebackground=_BG,
            activeforeground=_TEXT,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=4)

        self.auto_var = tk.BooleanVar(value=is_autostart_enabled())
        tk.Checkbutton(
            frm, text="开机自动启动", variable=self.auto_var, bg=_BG, fg=_TEXT,
            selectcolor=_BG_LIGHT, activebackground=_BG, activeforeground=_TEXT,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=4)

        btns = tk.Frame(frm, bg=_BG)
        btns.grid(row=6, column=0, columnspan=2, pady=8)
        tk.Button(btns, text="保存", command=self._save, bg=_TOGGLE_ON,
                  fg="white", bd=0, padx=16).pack(side="left", padx=4)
        tk.Button(btns, text="诊断", command=self._diagnose, bg=_BG_LIGHTER,
                  fg=_TEXT, bd=0, padx=16).pack(side="left", padx=4)
        self.diag_label = tk.Label(frm, text="", bg=_BG, fg=_MUTED,
                                   font=("", 8), wraplength=320, justify="left")
        self.diag_label.grid(row=7, column=0, columnspan=2, sticky="w")

        # Center over parent.
        self.update_idletasks()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        self.geometry(f"+{px}+{max(0, py - 200)}")

    def _diagnose(self):
        self.diag_label.configure(text="诊断中…（保持音乐播放，约10秒）")
        self.update_idletasks()
        import threading

        def work():
            try:
                from .diagnostics import run_diagnostics
                # Persist current selections first so the report reflects them.
                self.cfg["audio_device"] = (
                    None if self.dev_var.get() == "(系统默认)"
                    else self.dev_var.get())
                self.cfg["lan_ip"] = (
                    None if self.ip_var.get() == "(自动)" else self.ip_var.get())
                path = run_diagnostics(self.cfg)
                msg = f"诊断报告已保存到桌面:\n{path}\n请把这个 txt 发给开发者。"
            except Exception as e:
                msg = f"诊断出错: {e}"
            self.after(0, lambda: self.diag_label.configure(text=msg))

        threading.Thread(target=work, daemon=True).start()

    def _save(self):
        dev = self.dev_var.get()
        self.cfg["audio_device"] = None if dev == "(系统默认)" else dev
        ip = self.ip_var.get()
        self.cfg["lan_ip"] = None if ip == "(自动)" else ip
        self.cfg["blocksize"] = int(self.bs_var.get())
        self.cfg["dim_local"] = bool(self.dim_var.get())
        self.cfg["autostart"] = bool(self.auto_var.get())
        set_autostart_enabled(self.cfg["autostart"])
        self.on_change()
        self.destroy()


def _single_instance_lock():
    """Prevent a second instance — multiple instances fight over the Sonos and
    cause 'no sound / no level / only one format works / still streaming when
    off'. Returns the lock socket (keep it alive) or None if already running.
    """
    import socket as _s
    try:
        srv = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
        srv.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 0)
        # Bind a fixed loopback port as a mutex. If it's taken, another instance
        # owns it.
        srv.bind(("127.0.0.1", 50917))
        srv.listen(1)
        return srv
    except OSError:
        return None


def main():
    # Tell Windows we are a DISTINCT app, not pythonw.exe — otherwise the
    # taskbar groups our window under the Python launcher and shows its yellow
    # icon. Must be called BEFORE the first Tk window is created.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "SonosCaster.Capsule.1")
    except Exception:
        pass

    lock = _single_instance_lock()
    if lock is None:
        # Another SonosCaster is already running — refuse to start a second.
        try:
            import tkinter.messagebox as mb
            r = tk.Tk(); r.withdraw()
            mb.showinfo("SonosCaster",
                        "SonosCaster 已经在运行了。\n"
                        "（多开会互相抢 Sonos 导致没声音）\n"
                        "请看屏幕上已有的悬浮胶囊。")
            r.destroy()
        except Exception:
            pass
        return

    root = tk.Tk()
    app = CapsuleApp(root)
    app._instance_lock = lock  # keep the lock socket alive for the app lifetime
    # Closing the window hides to tray (the X button does the same). Right-click
    # no longer quits — that was too easy to trigger by accident.
    root.protocol("WM_DELETE_WINDOW", app._hide_to_tray)
    root.mainloop()


if __name__ == "__main__":
    main()
