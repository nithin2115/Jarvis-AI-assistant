"""Image preprocessing + lightweight content classification for JARVIS Vision.

Why this module exists:
    Gemini Vision (and any other multimodal LLM) is *much* better when
    we (a) pre-clean the image and (b) tell the model what kind of
    artefact it is looking at. Both jobs are done here, locally, with
    cheap heuristics — no extra ML weights required.

Two responsibilities:

    1. PREPROCESS — sharpen contrast, normalise brightness, detect
       dark-mode editors, optionally upscale tiny screenshots so OCR
       and the LLM can both see fine glyphs. Returns a Pillow image.

    2. CLASSIFY — guess the content kind from a small set:
           code_screenshot   IDE / terminal / compiler output
           ui_mockup         a website, app, or design surface
           pdf_page          rendered PDF page
           diagram           a chart, flowchart, or whiteboard sketch
           photo             a real-world photograph
           generic_image     anything else
       The classifier uses pixel-statistics heuristics (saturation,
       edge density, monospace-ness) — fast and zero-dependency
       beyond Pillow.

    3. OCR (optional) — if `pytesseract` is installed AND the system
       has the `tesseract` binary, we expose `extract_text(img)` for
       a local OCR pre-pass. Used to inject extracted text into the
       LLM context so even degraded captures still deliver useful
       structured output.

Public API:
    preprocess(image_bytes)               -> PreprocessResult
    classify_content(pil_image | bytes)   -> str   (one of the labels above)
    extract_text(pil_image | bytes)       -> str
    is_ocr_available()                    -> bool

PreprocessResult:
    .data        bytes   the cleaned PNG bytes
    .width/height int    final pixel dimensions
    .dark_mode   bool    True if the source looks like a dark IDE
    .content_kind str    one of the classifier labels above
    .text_density float  0..1, how text-dense the image looks
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Optional, Union

logger = logging.getLogger("jarvis.vision")

# Upscale tiny screenshots so OCR + Gemini can read small fonts.
# Anything narrower than this gets nearest-neighbour 2x upscaled.
MIN_USEFUL_WIDTH = 800

# Cap output dimensions — Gemini accepts up to ~4096 but we don't
# need that, and smaller images = faster tokens + cheaper inference.
MAX_OUTPUT_WIDTH = 2400

CONTENT_KINDS = (
    "code_screenshot",
    "ui_mockup",
    "pdf_page",
    "diagram",
    "photo",
    "generic_image",
)


@dataclass
class PreprocessResult:
    data: bytes
    width: int
    height: int
    dark_mode: bool = False
    content_kind: str = "generic_image"
    text_density: float = 0.0
    notes: list[str] = field(default_factory=list)


# ───────────────────────────────────────────────────────────────────
# Pillow loading
# ───────────────────────────────────────────────────────────────────
def _load(image: Union[bytes, "object"]):
    """Accept raw bytes or a Pillow Image; return a Pillow Image in
    RGB mode. Raises ValueError if neither path works."""
    from PIL import Image
    if isinstance(image, (bytes, bytearray)):
        try:
            img = Image.open(io.BytesIO(image))
        except Exception as exc:
            raise ValueError(f"could not decode image bytes: {exc}") from exc
    else:
        img = image
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


# ───────────────────────────────────────────────────────────────────
# Heuristic classifier
# ───────────────────────────────────────────────────────────────────
def _stats(img) -> dict:
    """Compute the cheap pixel statistics our classifier consumes.

    All values are in 0..255 except `aspect_ratio` and `near_*` which
    are 0..1 fractions.
    """
    import numpy as np
    arr = _to_array(img)
    if arr.size == 0:
        return {}
    h, w, _ = arr.shape

    # Mean RGB → grey: cheap luminance.
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    grey = (0.299 * r + 0.587 * g + 0.114 * b).astype("float32")
    mean_brightness = float(grey.mean())

    # Saturation = max-min over RGB.
    max_c = arr.max(axis=2).astype("float32")
    min_c = arr.min(axis=2).astype("float32")
    saturation = float((max_c - min_c).mean())

    # Histograms: count near-black + near-white pixels. A code editor
    # is overwhelmingly two-tone (background + foreground), whereas a
    # photo has a smooth distribution.
    near_black = float(((grey < 40)).mean())
    near_white = float(((grey > 215)).mean())

    # Edge density = mean abs Laplacian. High in text-heavy images,
    # moderate in UI mockups, low in photos with smooth gradients.
    edges = _laplacian_strength(grey)

    # Horizontal-stripe-ness: code screenshots have very regular
    # left-aligned text rows, so the column-wise variance of the
    # row-mean is high. Sample at most 200 rows for speed.
    row_means = grey[:: max(1, h // 200)].mean(axis=1)
    horizontal_rhythm = float(row_means.std())

    return {
        "width": w,
        "height": h,
        "aspect": w / max(1, h),
        "mean_brightness": mean_brightness,
        "saturation": saturation,
        "near_black": near_black,
        "near_white": near_white,
        "edge_density": edges,
        "horizontal_rhythm": horizontal_rhythm,
    }


def _to_array(img):
    import numpy as np
    return np.asarray(img, dtype="uint8")


def _laplacian_strength(grey) -> float:
    """Mean absolute Laplacian — proxy for sharp-edge density."""
    import numpy as np
    # Simple 3x3 Laplacian without scipy. Pad with edge replication.
    if grey.shape[0] < 3 or grey.shape[1] < 3:
        return 0.0
    g = grey
    # Centre - neighbours: a fast approximation of |∇²I|.
    centre = g[1:-1, 1:-1]
    up = g[:-2, 1:-1]
    down = g[2:, 1:-1]
    left = g[1:-1, :-2]
    right = g[1:-1, 2:]
    lap = np.abs(4.0 * centre - up - down - left - right)
    return float(lap.mean())


def classify_content(image: Union[bytes, "object"]) -> str:
    """Return one of CONTENT_KINDS based on cheap pixel heuristics.

    Decision rules (thresholds tuned on a small validation set of
    screenshots — documented inline so they're easy to retune):

        * very dark + low saturation + strong horizontal rhythm
                                           → code_screenshot (dark IDE)
        * very bright + monochrome + strong horizontal rhythm
                                           → code_screenshot (light IDE)
        * page-like aspect (0.65..0.85) + bright + strong rhythm
                                           → pdf_page
        * low edge density + high saturation + smooth gradient
                                           → photo
        * moderate edges + moderate saturation, lots of near-white,
          some bright accents              → ui_mockup
        * very low saturation + scattered edges (pen-on-paper feel)
                                           → diagram
        * everything else                  → generic_image
    """
    try:
        img = _load(image)
    except Exception:
        return "generic_image"
    s = _stats(img)
    if not s:
        return "generic_image"

    bright = s["mean_brightness"]
    sat = s["saturation"]
    edges = s["edge_density"]
    rhythm = s["horizontal_rhythm"]
    nb, nw = s["near_black"], s["near_white"]
    aspect = s["aspect"]

    # Code editors: very two-tone (mostly background + foreground)
    # AND nearly monochrome — real IDEs only colour-code keywords
    # so the AVERAGE saturation across the whole frame stays under
    # ~10. UI dashboards with white backgrounds and accent buttons
    # typically sit at sat 10-25 and must NOT match this branch.
    two_tone = (nb + nw) > 0.55 and sat < 10
    has_text_rhythm = rhythm > 22 and edges > 5
    if two_tone and has_text_rhythm:
        # Page-shaped → likely a PDF page rather than IDE.
        if 0.6 < aspect < 0.85 and bright > 200:
            return "pdf_page"
        return "code_screenshot"

    # Photos: smooth, saturated, fewer hard edges.
    if sat > 55 and edges < 9 and nb < 0.3 and nw < 0.3:
        return "photo"

    # UI mockups: bright background with some saturated accents and
    # moderate edge density (cards, buttons, icons). Lower-sat bound
    # is intentionally low (8) because clean Material/iOS designs are
    # mostly white with sparse colour accents — real screenshots
    # rarely cross 25% mean saturation.
    if bright > 175 and 8 < sat < 70 and 4 < edges < 30 and nw > 0.25:
        return "ui_mockup"

    # Sketch / diagram: low saturation but irregular edges, no rhythm.
    if sat < 30 and edges > 4 and rhythm < 18:
        return "diagram"

    return "generic_image"


def estimate_dark_mode(image: Union[bytes, "object"]) -> bool:
    """True if the dominant background appears to be dark (<70 luma)."""
    try:
        img = _load(image)
    except Exception:
        return False
    s = _stats(img)
    if not s:
        return False
    return s["mean_brightness"] < 70 and s["near_black"] > 0.45


# ───────────────────────────────────────────────────────────────────
# Preprocessing
# ───────────────────────────────────────────────────────────────────
def preprocess(image_bytes: bytes) -> PreprocessResult:
    """Clean a screenshot before sending it to the LLM.

    Pipeline:
        1. Load + force RGB.
        2. Detect dark-mode early (informs invert decision below).
        3. Upscale anything below MIN_USEFUL_WIDTH so fine glyphs
           survive JPEG-style compression downstream.
        4. Auto-contrast + a touch of sharpen for text legibility.
        5. Downscale anything wider than MAX_OUTPUT_WIDTH to keep
           upload size bounded.
        6. Re-encode as PNG.

    Returns a `PreprocessResult` with the cleaned bytes and the
    classifier's verdict baked in so downstream callers don't need
    to re-classify.
    """
    notes: list[str] = []
    try:
        img = _load(image_bytes)
    except Exception as exc:
        # Never break the upload pipeline because of a preprocess error
        # — return the original bytes verbatim.
        logger.warning("[VISION] preprocess load failed: %s", exc)
        return PreprocessResult(
            data=image_bytes if isinstance(image_bytes, bytes) else b"",
            width=0, height=0, content_kind="generic_image",
            notes=[f"load_failed: {exc}"],
        )

    s = _stats(img)
    dark = bool(s and s["mean_brightness"] < 70 and s["near_black"] > 0.45)

    # Step 3: upscale tiny captures so the LLM can read fine text.
    if img.width < MIN_USEFUL_WIDTH:
        from PIL import Image
        scale = min(2.0, MAX_OUTPUT_WIDTH / max(1, img.width))
        new_size = (int(img.width * scale), int(img.height * scale))
        img = img.resize(new_size, Image.LANCZOS)
        notes.append(f"upscaled_{scale:.2f}x")

    # Step 4: contrast + sharpen. ImageOps.autocontrast is a one-line
    # win for dim screenshots; ImageEnhance.Sharpness factor=1.4 makes
    # body text crisp without introducing visible halos.
    from PIL import ImageEnhance, ImageOps
    try:
        img = ImageOps.autocontrast(img, cutoff=1)
        img = ImageEnhance.Sharpness(img).enhance(1.4)
    except Exception as exc:
        notes.append(f"enhance_skipped: {exc}")

    # Step 5: cap final width.
    if img.width > MAX_OUTPUT_WIDTH:
        from PIL import Image
        ratio = MAX_OUTPUT_WIDTH / img.width
        new_size = (MAX_OUTPUT_WIDTH, int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
        notes.append(f"downscaled_to_{MAX_OUTPUT_WIDTH}w")

    # Re-classify on the cleaned image — sharpening can flip a
    # borderline `generic_image` into `code_screenshot`.
    kind = classify_content(img)

    # Cheap text-density estimate: ratio of near-black pixels in a
    # bright image (or near-white in a dark one).
    if dark:
        density = float(s["near_white"]) if s else 0.0
    else:
        density = float(s["near_black"]) if s else 0.0
    density = min(1.0, max(0.0, density))

    # Encode.
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    out_bytes = buf.getvalue()

    return PreprocessResult(
        data=out_bytes,
        width=img.width,
        height=img.height,
        dark_mode=dark,
        content_kind=kind,
        text_density=density,
        notes=notes,
    )


# ───────────────────────────────────────────────────────────────────
# Optional OCR via pytesseract
# ───────────────────────────────────────────────────────────────────
_OCR_AVAILABLE: Optional[bool] = None


def is_ocr_available() -> bool:
    """True if pytesseract AND a working tesseract binary are present."""
    global _OCR_AVAILABLE
    if _OCR_AVAILABLE is None:
        _OCR_AVAILABLE = False
        try:
            import pytesseract
            # Probe the binary by asking for its version. If the binary
            # is missing this raises pytesseract.TesseractNotFoundError.
            pytesseract.get_tesseract_version()
            _OCR_AVAILABLE = True
        except Exception as exc:
            logger.info("[VISION] OCR unavailable: %s", exc)
    return _OCR_AVAILABLE


def extract_text(image: Union[bytes, "object"]) -> str:
    """Run OCR on `image` and return the raw text. Empty string if
    OCR isn't installed — the caller should always fall back to
    sending the raw image to the multimodal LLM."""
    if not is_ocr_available():
        return ""
    try:
        import pytesseract
        img = _load(image)
        # `--psm 6` = "Assume a single uniform block of text", best
        # default for code screenshots and book pages alike.
        return (pytesseract.image_to_string(img, config="--psm 6") or "").strip()
    except Exception as exc:
        logger.warning("[VISION] OCR failed: %s", exc)
        return ""


# ───────────────────────────────────────────────────────────────────
# Specialised analysis steers — used by the chat handler to prepend
# a content-kind-aware system instruction so the LLM responds with
# the right *shape* of answer.
# ───────────────────────────────────────────────────────────────────
ANALYSIS_STEERS: dict[str, str] = {
    "code_screenshot": (
        "The user has shared a screenshot of code, a terminal, or a "
        "compiler/runtime error. Treat this as a debugging request. "
        "First identify the language and the framework. If an error "
        "is visible, quote the most relevant line, explain the root "
        "cause in one or two sentences, and provide a corrected code "
        "snippet. If the screenshot is just code, summarise what it "
        "does and call out any bugs, smells, or improvements. Use "
        "fenced code blocks for every code suggestion."
    ),
    "ui_mockup": (
        "The user has shared a UI screenshot or a design mockup. "
        "Give a UX review: layout, visual hierarchy, spacing, "
        "colour balance, typography, accessibility (contrast, "
        "touch-target sizes), and responsiveness. Suggest concrete, "
        "prioritised improvements — not generic platitudes. If you "
        "spot specific elements (buttons, forms, charts), name them."
    ),
    "pdf_page": (
        "The user has shared a page from a PDF. Summarise the key "
        "ideas in 3–5 bullet points, define any technical terms, and "
        "answer any explicit questions in the user's message. If the "
        "page contains a diagram or table, describe what it shows."
    ),
    "diagram": (
        "The user has shared a diagram, flowchart, whiteboard photo, "
        "or hand-drawn sketch. Describe the structure first (nodes, "
        "edges, regions), then explain the underlying concept. If it "
        "looks like a study aid (e.g. a CS data structure, a biology "
        "diagram), simplify the explanation for a learner."
    ),
    "photo": (
        "The user has shared a real-world photograph. Describe what "
        "is in it succinctly, then answer the user's specific "
        "question. Avoid hallucinating details that aren't visible."
    ),
    "generic_image": (
        "The user has shared an image. Describe what you see briefly, "
        "then directly answer their question. Use a code block if "
        "the image contains code or a terminal."
    ),
}


def steer_for_kind(kind: str) -> str:
    """Lookup helper — returns the steer for `kind`, or the generic
    image steer if `kind` is unknown."""
    return ANALYSIS_STEERS.get(kind, ANALYSIS_STEERS["generic_image"])
