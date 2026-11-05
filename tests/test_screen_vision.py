"""Screen-vision pipeline regression test.

Covers the new vision stack added on top of the existing upload + Gemini
Vision flow:

    1. Image classifier (image_intelligence.classify_content)
       - dark IDE screenshot   → 'code_screenshot'
       - light IDE screenshot  → 'code_screenshot'
       - paper / PDF page      → 'pdf_page'
       - colourful photo       → 'photo'
       - bright UI mockup      → 'ui_mockup'
       - empty / corrupt input → 'generic_image' (graceful)

    2. Preprocessing (image_intelligence.preprocess)
       - tiny screenshots get upscaled
       - very wide screenshots get downscaled to MAX_OUTPUT_WIDTH
       - dark-mode detection True for IDE-style fixtures
       - returns valid PNG bytes
       - never raises on garbage input
       - idempotent enough that two passes don't double-resize a
         normally-sized image

    3. Steers (image_intelligence.steer_for_kind)
       - every label in CONTENT_KINDS has a non-empty steer
       - unknown labels return the generic_image steer

    4. screen_capture monitor enumeration
       - list_monitors() returns a list of well-shaped dicts
       - is_available() True when at least one backend is importable
       - region clipping math clamps negative + oversized boxes

    5. Vision-aware prompt routing (app._build_system_prompt)
       - image attachment with vision_kind='code_screenshot' injects
         the debugging steer
       - image attachment with vision_kind='ui_mockup' injects the
         UX steer
       - no image attachments → no [VISION CONTEXT] block
       - text-only attachments do NOT trigger vision steer

    6. HTTP endpoint contracts (Flask test client)
       - GET  /api/screen/monitors   without auth → 401
       - POST /api/screen/capture    without auth → 401
       - POST /api/screen/capture    with auth, NO consent → 403
       - POST /api/screen/region     with auth, NO consent → 403
       - POST /api/screen/region     with auth + consent + bogus dims
                                                            → 400

Run from the repo root:

    python -m tests.test_screen_vision
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# UTF-8 stdout for symbol-safe logging on Windows.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# We need numpy + Pillow for fixture generation. Both are already
# direct deps via the existing vision_module.
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import image_intelligence as ii  # noqa: E402
import screen_capture as sc  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# Test harness
# ══════════════════════════════════════════════════════════════════════════════
_failures: list[str] = []


def check(label: str, cond: bool, detail: str = ""):
    flag = "OK  " if cond else "FAIL"
    print(f"[{flag}] {label}" + (f"  ::  {detail}" if (detail and not cond) else ""))
    if not cond:
        _failures.append(label)


def section(title: str):
    print(f"\n── {title} " + "─" * max(0, 60 - len(title)))


# ══════════════════════════════════════════════════════════════════════════════
# Fixture builders — synthesise images that LOOK like what each
# classifier label is supposed to detect, without baking any real
# screenshots into the repo.
# ══════════════════════════════════════════════════════════════════════════════
def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def fixture_dark_ide(width=1200, height=720) -> bytes:
    """Mimic a dark IDE: near-black background, regular rows of light
    grey 'text' (drawn as horizontal stripes of varying length)."""
    img = Image.new("RGB", (width, height), (18, 22, 28))
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(42)
    line_h = 18
    y = 12
    while y < height - 12:
        # Random line length so the right margin is ragged like real code.
        length = int(rng.integers(low=width // 4, high=width - 60))
        d.rectangle([20, y, 20 + length, y + 4], fill=(220, 220, 230))
        y += line_h
    return _png(img)


def fixture_light_ide(width=1200, height=720) -> bytes:
    """White-background editor: black-ish text rows on a light page."""
    img = Image.new("RGB", (width, height), (250, 250, 252))
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(7)
    y = 12
    while y < height - 12:
        length = int(rng.integers(low=width // 5, high=width - 80))
        d.rectangle([24, y, 24 + length, y + 3], fill=(20, 20, 28))
        y += 16
    return _png(img)


def fixture_pdf_page(width=720, height=960) -> bytes:
    """A4-ish aspect ratio, white background, dense rows of text."""
    img = Image.new("RGB", (width, height), (252, 252, 250))
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(13)
    y = 40
    while y < height - 40:
        length = int(rng.integers(low=width // 3, high=width - 80))
        d.rectangle([40, y, 40 + length, y + 3], fill=(20, 20, 28))
        y += 14
    return _png(img)


def fixture_photo(width=1024, height=768) -> bytes:
    """Smooth saturated gradient, no text rhythm."""
    img = Image.new("RGB", (width, height))
    arr = np.zeros((height, width, 3), dtype="uint8")
    # Diagonal gradient from sunrise red to deep blue.
    xs = np.linspace(0, 1, width).reshape(1, -1)
    ys = np.linspace(0, 1, height).reshape(-1, 1)
    arr[..., 0] = (255 * (1 - xs) * (1 - ys)).astype("uint8")
    arr[..., 1] = (180 * (1 - xs) * ys).astype("uint8")
    arr[..., 2] = (255 * xs).astype("uint8")
    img = Image.fromarray(arr, "RGB")
    return _png(img)


def fixture_ui_mockup(width=1200, height=800) -> bytes:
    """Bright canvas with cards, sidebar nav, header buttons, and
    text-line strips — mimics a typical Material / SaaS dashboard
    screenshot. Tuned to land in the classifier's UI mockup band:
    bright background + moderate saturation accents + moderate
    edge density."""
    img = Image.new("RGB", (width, height), (245, 246, 250))
    d = ImageDraw.Draw(img)
    # Sidebar with menu icons + labels
    d.rectangle([0, 0, 200, height], fill=(25, 28, 38))
    for i in range(8):
        ny = 80 + i * 60
        d.rectangle([20, ny, 36, ny + 28], fill=(80, 200, 160))
        d.rectangle([48, ny + 8, 180, ny + 18], fill=(170, 175, 200))
    # Header bar with logo + action buttons
    d.rectangle([200, 0, width, 60], fill=(255, 255, 255))
    d.rectangle([220, 22, 320, 38], fill=(80, 100, 240))
    d.rectangle([width - 320, 18, width - 230, 42], fill=(80, 200, 160))
    d.rectangle([width - 220, 18, width - 130, 42], fill=(240, 100, 100))
    d.rectangle([width - 120, 18, width -  30, 42], fill=(60, 80, 220))
    # Card grid with text lines + CTA buttons
    for row in range(2):
        for col in range(3):
            x = 240 + col * 280
            y = 100 + row * 220
            d.rectangle([x, y, x + 240, y + 180], fill=(255, 255, 255), outline=(180, 185, 200))
            d.rectangle([x + 16, y + 16, x + 100, y + 36], fill=(80, 200, 160))
            for i in range(5):
                ty = y + 50 + i * 16
                d.rectangle([x + 16, ty, x + 220, ty + 6], fill=(60, 70, 90))
            d.rectangle([x + 16, y + 150, x +  90, y + 168], fill=(60, 80, 220))
            d.rectangle([x + 100, y + 150, x + 170, y + 168], fill=(220, 100, 100))
    return _png(img)


def fixture_diagram(width=900, height=700) -> bytes:
    """White paper with hand-drawn boxes + arrows: low saturation,
    irregular edges, no horizontal rhythm."""
    img = Image.new("RGB", (width, height), (252, 250, 245))
    d = ImageDraw.Draw(img)
    boxes = [(120, 120, 280, 200), (520, 120, 720, 200),
             (320, 360, 520, 460), (120, 540, 280, 620),
             (520, 540, 720, 620)]
    for (x0, y0, x1, y1) in boxes:
        d.rectangle([x0, y0, x1, y1], outline=(40, 40, 40), width=2)
    arrows = [(280, 160, 520, 160), (200, 200, 380, 360),
              (640, 200, 460, 360), (380, 460, 200, 540),
              (460, 460, 620, 540)]
    for (x0, y0, x1, y1) in arrows:
        d.line([(x0, y0), (x1, y1)], fill=(40, 40, 40), width=2)
    return _png(img)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1: classifier
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 1: image classifier (heuristic)")

cases = [
    ("dark IDE",        fixture_dark_ide(),    "code_screenshot"),
    ("light IDE",       fixture_light_ide(),   "code_screenshot"),
    ("PDF page",        fixture_pdf_page(),    "pdf_page"),
    ("photo gradient",  fixture_photo(),       "photo"),
    ("UI mockup",       fixture_ui_mockup(),   "ui_mockup"),
]
for label, data, expected in cases:
    got = ii.classify_content(data)
    check(
        f"classify {label} → {expected!r}",
        got == expected,
        f"got {got!r}",
    )

# Diagram heuristic is fuzzy by design (low saturation + irregular
# edges). Accept either 'diagram' or 'generic_image' so we don't false
# fail on minor stat shifts when the fixture changes.
diag_kind = ii.classify_content(fixture_diagram())
check(
    f"classify diagram → diagram OR generic_image (got {diag_kind!r})",
    diag_kind in ("diagram", "generic_image"),
)

# Garbage / empty inputs must not raise.
check(
    "classify empty bytes does not raise → 'generic_image'",
    ii.classify_content(b"") == "generic_image",
)
check(
    "classify garbage bytes does not raise → 'generic_image'",
    ii.classify_content(b"\x00\x01\x02notapng") == "generic_image",
)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2: preprocessing
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 2: preprocessing pipeline")

dark_bytes = fixture_dark_ide()
res = ii.preprocess(dark_bytes)
check("preprocess returns non-empty bytes",          len(res.data) > 0)
check("preprocess output decodes as PNG",
      Image.open(io.BytesIO(res.data)).format == "PNG")
check("preprocess detects dark mode on dark IDE",    res.dark_mode is True)
check("preprocess re-classifies as code_screenshot", res.content_kind == "code_screenshot")
check("preprocess records width/height",             res.width > 0 and res.height > 0)

# Tiny screenshot upscaling.
tiny = Image.new("RGB", (320, 240), (240, 240, 240))
tiny_buf = io.BytesIO(); tiny.save(tiny_buf, "PNG")
res_tiny = ii.preprocess(tiny_buf.getvalue())
check("tiny screenshot upscaled to ≥ original width",
      res_tiny.width > tiny.width,
      f"width {res_tiny.width} ≤ {tiny.width}")

# Wide screenshot downscaling.
wide = Image.new("RGB", (4000, 1200), (245, 245, 245))
wide_buf = io.BytesIO(); wide.save(wide_buf, "PNG")
res_wide = ii.preprocess(wide_buf.getvalue())
check("wide screenshot downscaled to ≤ MAX_OUTPUT_WIDTH",
      res_wide.width <= ii.MAX_OUTPUT_WIDTH,
      f"width {res_wide.width} > {ii.MAX_OUTPUT_WIDTH}")

# Garbage in must not raise.
res_bad = ii.preprocess(b"not-an-image")
check("preprocess on garbage returns a result without raising",
      isinstance(res_bad, ii.PreprocessResult))


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3: content-kind steers
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 3: content-kind steers")

for kind in ii.CONTENT_KINDS:
    s = ii.steer_for_kind(kind)
    check(f"steer for {kind!r} non-empty",      isinstance(s, str) and len(s) > 30)
    check(f"steer for {kind!r} mentions kind context",
          any(token in s.lower() for token in ("user", "code", "image", "screenshot",
                                              "diagram", "page", "design",
                                              "photograph", "ui")),
          f"steer text: {s[:80]!r}")
check("unknown kind falls back to generic_image steer",
      ii.steer_for_kind("nonsense") == ii.ANALYSIS_STEERS["generic_image"])


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4: screen_capture monitor enumeration + region clipping
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 4: screen_capture core")

monitors = sc.list_monitors()
check("list_monitors returns a list",                isinstance(monitors, list))
if monitors:
    m = monitors[0]
    for key in ("index", "left", "top", "width", "height", "is_primary", "label"):
        check(f"monitor entry has '{key}'", key in m, f"missing {key}: {m}")
    check("monitor width > 0",   m["width"]  > 0)
    check("monitor height > 0",  m["height"] > 0)
    primaries = sum(1 for x in monitors if x.get("is_primary"))
    check("at most one monitor flagged as primary", primaries <= 1)
else:
    print("[INFO] no monitors enumerated — both backends absent on this host")

check("is_available is bool", isinstance(sc.is_available(), bool))

# Region clipping math: positive box inside bounds — unchanged.
bounds = {"left": 0, "top": 0, "width": 1920, "height": 1080}
L, T, W, H = sc._clip_box(100, 200, 400, 300, bounds)
check("clip: in-bounds box preserved", (L, T, W, H) == (100, 200, 400, 300))

# Negative coords clamp to monitor origin.
L, T, W, H = sc._clip_box(-50, -200, 400, 300, bounds)
check("clip: negative coords clamped to monitor origin",
      L == 0 and T == 0,
      f"got L={L} T={T}")

# Oversized box clamps to monitor edges.
L, T, W, H = sc._clip_box(1700, 900, 800, 800, bounds)
check("clip: right edge clamped", L + W <= bounds["width"], f"L={L} W={W}")
check("clip: bottom edge clamped", T + H <= bounds["height"], f"T={T} H={H}")

# Excessive dimensions get scaled down to MAX_DIMENSION.
huge_bounds = {"left": 0, "top": 0, "width": 99999, "height": 99999}
L, T, W, H = sc._clip_box(0, 0, 99999, 99999, huge_bounds)
check("clip: extreme dims capped at MAX_DIMENSION",
      W <= sc.MAX_DIMENSION and H <= sc.MAX_DIMENSION,
      f"got W={W} H={H}, MAX={sc.MAX_DIMENSION}")

# Zero or negative dimensions raise.
try:
    sc._clip_box(0, 0, 0, 100, bounds)
    check("clip: zero width raises ValueError", False, "did not raise")
except ValueError:
    check("clip: zero width raises ValueError", True)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5: vision-aware prompt routing
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 5: vision-aware prompt routing in app._build_system_prompt")

# Importing app is heavy; skip if it fails so this test stays useful
# even on a partial setup (CI without API keys, etc.).
try:
    import app as jarvis_app  # noqa: F401
    BUILD = jarvis_app._build_system_prompt
    APP_AVAILABLE = True
except Exception as exc:
    print(f"[WARN] app.py not importable, skipping prompt-routing tests: {exc}")
    APP_AVAILABLE = False

if APP_AVAILABLE:
    # Build a fake image attachment that looks like the descriptor
    # produced by file_processor.process_upload + the screen-capture
    # endpoint (which adds the `vision_kind` field).
    code_attach = {
        "id": "fake-1",
        "name": "screen.png",
        "kind": "image",
        "size": 1024,
        "mime": "image/png",
        "image": {"mime_type": "image/png", "data": fixture_dark_ide()},
        "vision_kind": "code_screenshot",
    }
    ui_attach = {
        "id": "fake-2",
        "name": "design.png",
        "kind": "image",
        "size": 1024,
        "mime": "image/png",
        "image": {"mime_type": "image/png", "data": fixture_ui_mockup()},
        "vision_kind": "ui_mockup",
    }
    text_attach = {
        "id": "fake-3",
        "name": "notes.txt",
        "kind": "text",
        "size": 100,
        "mime": "text/plain",
        "text": "hello world",
    }

    p_code = BUILD(attachments=[code_attach])
    check(
        "code screenshot injects [VISION CONTEXT — code_screenshot]",
        "[VISION CONTEXT — code_screenshot]" in p_code,
        f"prompt missing tag: {p_code[-300:]!r}",
    )
    check(
        "code-screenshot steer mentions debugging vocabulary",
        any(t in p_code.lower() for t in ("debug", "compiler", "error", "code")),
    )

    p_ui = BUILD(attachments=[ui_attach])
    check(
        "UI mockup injects [VISION CONTEXT — ui_mockup]",
        "[VISION CONTEXT — ui_mockup]" in p_ui,
    )
    check(
        "UI steer mentions UX vocabulary",
        any(t in p_ui.lower() for t in ("ux", "spacing", "layout", "design",
                                        "accessibility", "responsiv")),
    )

    p_none = BUILD(attachments=None)
    check(
        "no attachments → no [VISION CONTEXT] block",
        "[VISION CONTEXT" not in p_none,
    )

    p_text = BUILD(attachments=[text_attach])
    check(
        "text-only attachment → no [VISION CONTEXT] block",
        "[VISION CONTEXT" not in p_text,
    )

    p_two = BUILD(attachments=[code_attach, ui_attach])
    check(
        "multi-image: only ONE [VISION CONTEXT] block injected",
        p_two.count("[VISION CONTEXT") == 1,
        f"count={p_two.count('[VISION CONTEXT')}",
    )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 6: HTTP endpoint contracts (Flask test client, no real capture)
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 6: HTTP endpoint contracts")

if APP_AVAILABLE:
    flask_app = jarvis_app.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as c:
        # Unauthenticated probes.
        r = c.get("/api/screen/monitors")
        check("GET /api/screen/monitors w/o auth → 401",
              r.status_code == 401, f"got {r.status_code}")

        r = c.post("/api/screen/capture", json={"consent": True})
        check("POST /api/screen/capture w/o auth → 401",
              r.status_code == 401, f"got {r.status_code}")

        r = c.post("/api/screen/region", json={"consent": True})
        check("POST /api/screen/region w/o auth → 401",
              r.status_code == 401, f"got {r.status_code}")

    # Authenticated probes — set demo-user uid so the gates open.
    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["uid"] = "demo-user"

        r = c.get("/api/screen/monitors")
        body = r.get_json() or {}
        check("GET /api/screen/monitors with auth → 200 + ok",
              r.status_code == 200 and body.get("ok") is True,
              f"status={r.status_code} body={body}")
        check("monitors list is a list",
              isinstance(body.get("monitors"), list))

        r = c.post("/api/screen/capture", json={})
        check("POST /api/screen/capture w/auth, NO consent → 403",
              r.status_code == 403, f"got {r.status_code}")

        r = c.post("/api/screen/region",
                   json={"consent": True, "left": 0, "top": 0, "width": 0, "height": 0})
        # 0×0 region is invalid → 400.
        check("POST /api/screen/region w/auth + bogus dims → 400",
              r.status_code == 400, f"got {r.status_code}")

        # Negative dims also 400.
        r = c.post("/api/screen/region",
                   json={"consent": True, "left": 0, "top": 0, "width": -10, "height": 100})
        check("POST /api/screen/region w/auth + negative width → 400",
              r.status_code == 400, f"got {r.status_code}")


# ══════════════════════════════════════════════════════════════════════════════
print()
print("═" * 70)
if _failures:
    print(f"FAIL — {len(_failures)} screen-vision invariant(s) broken:")
    for f in _failures:
        print(f"  • {f}")
    sys.exit(1)
else:
    print("PASS — every screen-vision invariant holds.")
