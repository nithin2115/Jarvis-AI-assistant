"""Fast desktop screen capture for JARVIS Vision.

Primary backend: `mss` — a small, BSD-licensed native screen-grabber
that produces a raw BGRA buffer in roughly 5-15ms per frame on a
typical laptop. We convert that buffer to a PNG byte string so it
plugs straight into the existing `file_processor.process_upload()`
pipeline (which already knows how to feed image bytes to Gemini
Vision).

Fallback backend: `pyautogui.screenshot()` — slower but pure-Python
adjacent and usually present on dev machines. Used only if mss is
not importable, so the user always gets *some* capture path even
without installing extra packages.

Public API:
    list_monitors() -> list[dict]
        [{index, left, top, width, height, is_primary, label}, ...]

    capture_full(monitor_index=None) -> CapturedImage
        Capture an entire monitor (or the virtual screen if -1).

    capture_region(left, top, width, height,
                   monitor_index=None) -> CapturedImage
        Capture a rectangle. Coordinates are interpreted as monitor-
        relative when monitor_index is set, virtual-screen-absolute
        when monitor_index is None.

    is_available() -> bool
        Quick liveness probe so the API layer can advertise capture
        support to the UI without throwing.

Privacy invariants enforced here:
    * NO state, NO timers, NO background threads — every capture is
      a single explicit call.
    * Captures NEVER write to disk. The caller decides whether to
      hand the bytes to file_processor.remember() (which keeps them
      in the same in-memory store as user-uploaded files).
    * Width/height clamped to MAX_DIMENSION to defend against insane
      virtual-screen geometries.

This module is import-safe even if neither backend is installed; the
top-level functions raise `RuntimeError` only when actually called
without a working backend.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("jarvis.screen")

# Conservative caps so a 4K x 3 monitor virtual screen does not pin
# the upload pipeline at 100MB+.
MAX_DIMENSION = 6000          # px on either axis after clipping
MAX_OUTPUT_BYTES = 12 * 1024 * 1024  # 12 MB encoded PNG ceiling


@dataclass
class CapturedImage:
    """Result of a screen capture.

    `data` is PNG-encoded bytes ready for `file_processor.process_upload()`.
    `width`/`height` are the actual pixel dimensions of the capture
    AFTER any clipping. `monitor_index` is the source monitor (or -1
    for the virtual-screen capture). `backend` reports which engine
    produced the bytes ("mss" or "pyautogui") for diagnostics.
    """
    data: bytes
    width: int
    height: int
    monitor_index: int
    backend: str
    mime_type: str = "image/png"


# ───────────────────────────────────────────────────────────────────
# Backend probing (lazy)
# ───────────────────────────────────────────────────────────────────
_MSS_AVAILABLE: Optional[bool] = None
_PYAUTOGUI_AVAILABLE: Optional[bool] = None


def _try_mss() -> bool:
    global _MSS_AVAILABLE
    if _MSS_AVAILABLE is None:
        try:
            import mss  # noqa: F401
            _MSS_AVAILABLE = True
        except Exception as exc:
            logger.info("[SCREEN] mss not available: %s", exc)
            _MSS_AVAILABLE = False
    return _MSS_AVAILABLE


def _try_pyautogui() -> bool:
    global _PYAUTOGUI_AVAILABLE
    if _PYAUTOGUI_AVAILABLE is None:
        try:
            import pyautogui  # noqa: F401
            from PIL import Image  # noqa: F401  pyautogui returns a PIL image
            _PYAUTOGUI_AVAILABLE = True
        except Exception as exc:
            logger.info("[SCREEN] pyautogui not available: %s", exc)
            _PYAUTOGUI_AVAILABLE = False
    return _PYAUTOGUI_AVAILABLE


def is_available() -> bool:
    """True if at least one capture backend is importable on this system."""
    return _try_mss() or _try_pyautogui()


# ───────────────────────────────────────────────────────────────────
# Monitor enumeration
# ───────────────────────────────────────────────────────────────────
def list_monitors() -> list[dict]:
    """Return one dict per monitor.

    Index 0 is reserved for the virtual screen (every monitor merged).
    Indices 1..N are the physical monitors in the order the OS reports
    them. Caller-friendly fields:

        index       int   monitor number (0 = virtual, 1..N = physical)
        left, top   int   top-left corner in virtual-screen coords
        width       int
        height      int
        is_primary  bool  True for the OS's primary display
        label       str   "Primary 1920×1080" / "Monitor 2 2560×1440"
    """
    if not _try_mss():
        if _try_pyautogui():
            # pyautogui can only see the primary display; expose just it.
            try:
                import pyautogui
                size = pyautogui.size()
                return [{
                    "index": 1, "left": 0, "top": 0,
                    "width": int(size.width), "height": int(size.height),
                    "is_primary": True,
                    "label": f"Primary {size.width}×{size.height}",
                }]
            except Exception:
                return []
        return []

    import mss
    out: list[dict] = []
    with mss.mss() as sct:
        # mss's index 0 is the virtual screen (the bounding box of all
        # physical monitors). Indices ≥1 are physical displays. We
        # surface both so a multi-monitor user can pick which to grab.
        for idx, mon in enumerate(sct.monitors):
            label = (
                f"Virtual {mon['width']}×{mon['height']}"
                if idx == 0
                else f"Monitor {idx} {mon['width']}×{mon['height']}"
            )
            out.append({
                "index": idx,
                "left": int(mon.get("left", 0)),
                "top": int(mon.get("top", 0)),
                "width": int(mon["width"]),
                "height": int(mon["height"]),
                # mss does not flag primary directly; index 1 is always
                # the OS primary on every platform we support.
                "is_primary": idx == 1,
                "label": label,
            })
    return out


# ───────────────────────────────────────────────────────────────────
# Encoding helpers
# ───────────────────────────────────────────────────────────────────
def _encode_png_from_bgra(buffer: bytes, width: int, height: int) -> bytes:
    """Convert an mss BGRA buffer to PNG bytes via Pillow."""
    from PIL import Image
    img = Image.frombytes("RGB", (width, height), buffer, "raw", "BGRX")
    return _encode_png_from_pil(img)


def _encode_png_from_pil(img) -> bytes:
    """Encode a Pillow image to PNG, applying a defensive size cap.

    If the encoded payload exceeds MAX_OUTPUT_BYTES we down-sample by
    a factor of 2 and try once more. This trips only on very-high-res
    multi-monitor captures and avoids blowing up the upload store.
    """
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    out = buf.getvalue()
    if len(out) <= MAX_OUTPUT_BYTES:
        return out

    logger.info(
        "[SCREEN] PNG %d bytes exceeds cap %d, halving resolution",
        len(out), MAX_OUTPUT_BYTES,
    )
    new_size = (max(1, img.width // 2), max(1, img.height // 2))
    img = img.resize(new_size)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ───────────────────────────────────────────────────────────────────
# Capture helpers
# ───────────────────────────────────────────────────────────────────
def _resolve_mss_monitor(sct, monitor_index: Optional[int]) -> tuple[int, dict]:
    """Pick the mss monitor dict for the requested index. None or -1
    means 'virtual screen' which is mss index 0."""
    monitors = sct.monitors
    if monitor_index is None or monitor_index < 0:
        return 0, monitors[0]
    if monitor_index >= len(monitors):
        raise ValueError(
            f"monitor_index {monitor_index} out of range (have {len(monitors)})"
        )
    return monitor_index, monitors[monitor_index]


def _clip_box(left: int, top: int, width: int, height: int,
              bounds: dict) -> tuple[int, int, int, int]:
    """Clamp a region rectangle so it stays inside the source monitor.
    Coordinates are virtual-screen-absolute on the way in and on the
    way out. Width/height are forced positive."""
    bx, by = bounds["left"], bounds["top"]
    bw, bh = bounds["width"], bounds["height"]
    # Translate negative offsets to start at the monitor's origin.
    if width <= 0 or height <= 0:
        raise ValueError("region width/height must be positive")
    L = max(bx, int(left))
    T = max(by, int(top))
    R = min(bx + bw, L + int(width))
    B = min(by + bh, T + int(height))
    new_w = max(1, R - L)
    new_h = max(1, B - T)
    if new_w > MAX_DIMENSION or new_h > MAX_DIMENSION:
        # Scale-preserving clamp, never silently distort.
        scale = min(MAX_DIMENSION / new_w, MAX_DIMENSION / new_h)
        new_w = max(1, int(new_w * scale))
        new_h = max(1, int(new_h * scale))
    return L, T, new_w, new_h


def capture_full(monitor_index: Optional[int] = None) -> CapturedImage:
    """Capture a whole monitor (or the virtual screen if monitor_index
    is None or -1)."""
    if _try_mss():
        import mss
        with mss.mss() as sct:
            idx, mon = _resolve_mss_monitor(sct, monitor_index)
            shot = sct.grab(mon)
            data = _encode_png_from_bgra(shot.bgra, shot.width, shot.height)
            return CapturedImage(
                data=data,
                width=shot.width,
                height=shot.height,
                monitor_index=idx,
                backend="mss",
            )

    if _try_pyautogui():
        import pyautogui
        img = pyautogui.screenshot()
        data = _encode_png_from_pil(img)
        return CapturedImage(
            data=data,
            width=img.width,
            height=img.height,
            monitor_index=1,
            backend="pyautogui",
        )

    raise RuntimeError(
        "No screen-capture backend available. Install 'mss' "
        "(`pip install mss`) or 'pyautogui'."
    )


def capture_region(left: int, top: int, width: int, height: int,
                   monitor_index: Optional[int] = None) -> CapturedImage:
    """Capture a rectangle from a specific monitor (or the virtual
    screen). Coordinates are virtual-screen-absolute when
    monitor_index is None, else monitor-relative."""
    if _try_mss():
        import mss
        with mss.mss() as sct:
            idx, mon = _resolve_mss_monitor(sct, monitor_index)
            # If the user passed monitor-relative coords, translate.
            if monitor_index is not None and monitor_index >= 1:
                abs_left = mon["left"] + int(left)
                abs_top = mon["top"] + int(top)
            else:
                abs_left = int(left)
                abs_top = int(top)
            L, T, W, H = _clip_box(abs_left, abs_top, width, height, mon)
            region = {"left": L, "top": T, "width": W, "height": H}
            shot = sct.grab(region)
            data = _encode_png_from_bgra(shot.bgra, shot.width, shot.height)
            return CapturedImage(
                data=data,
                width=shot.width,
                height=shot.height,
                monitor_index=idx,
                backend="mss",
            )

    if _try_pyautogui():
        import pyautogui
        # pyautogui supports region kwarg (left, top, width, height).
        img = pyautogui.screenshot(
            region=(int(left), int(top), max(1, int(width)), max(1, int(height)))
        )
        data = _encode_png_from_pil(img)
        return CapturedImage(
            data=data,
            width=img.width,
            height=img.height,
            monitor_index=1,
            backend="pyautogui",
        )

    raise RuntimeError(
        "No screen-capture backend available. Install 'mss' "
        "(`pip install mss`) or 'pyautogui'."
    )
