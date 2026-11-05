"""
JARVIS Auth — Face Verification
Uses face_recognition (dlib) if available, falls back to OpenCV Haar+HOG.
Only embeddings are stored — never raw images.
"""
import base64, logging
from typing import Optional, Tuple
import numpy as np 
import cv2

logger = logging.getLogger("jarvis.face")

# OpenCV-only mode (reliable on all platforms).
# dlib/face_recognition can segfault at the C level on Windows+Python 3.11,
# which Python's try/except cannot catch. OpenCV HOG is sufficient for 1:1
# identity verification and runs without any native library issues.
_lib = "opencv"
logger.info("[FACE] Using OpenCV HOG embeddings")

_cascade = None
try:
    if hasattr(cv2, "CascadeClassifier") and hasattr(cv2, "data") and hasattr(cv2.data, "haarcascades"):
        _cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    else:
        logger.warning("[FACE] CascadeClassifier or haarcascades data not found in cv2")
except Exception as e:
    logger.warning(f"[FACE] Failed to load cascade: {e}")


# ── Helpers ────────────────────────────────────────────────────

def decode_b64_image(b64: str) -> Optional[np.ndarray]:
    """Decode a base64 data-URI or raw base64 string → BGR numpy array."""
    try:
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        raw = base64.b64decode(b64)
        arr = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as e:
        logger.error(f"[FACE] decode error: {e}")
        return None


def _detect_face_rect(gray: np.ndarray):
    """Return (x,y,w,h) of largest detected face or None."""
    if _cascade is None:
        return None
    try:
        faces = _cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        if len(faces) == 0:
            return None
        return max(faces, key=lambda f: f[2] * f[3])
    except Exception:
        return None


# ── Public API ─────────────────────────────────────────────────

def _opencv_embedding(img_bgr: np.ndarray) -> Optional[np.ndarray]:
    """OpenCV HOG-based face embedding (always available)."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    rect = _detect_face_rect(gray)
    if rect is None:
        return None
    x, y, w, h = rect
    face = cv2.resize(gray[y:y+h, x:x+w], (80, 80))
    hog  = cv2.HOGDescriptor((80, 80), (16, 16), (8, 8), (8, 8), 9)
    desc = hog.compute(face)
    return (desc / (np.linalg.norm(desc) + 1e-10)).astype(np.float32).flatten()


def get_embedding(b64_image: str) -> Optional[np.ndarray]:
    """
    Extract a face embedding from a base64-encoded image.
    Returns a 1-D numpy float32 array, or None if no face is found.
    Tries face_recognition first, falls back to OpenCV on any error.
    """
    img_bgr = decode_b64_image(b64_image)
    if img_bgr is None:
        return None

    if _lib == "face_recognition":
        try:
            img_rgb = img_bgr[:, :, ::-1]
            locs = _fr.face_locations(img_rgb, model="hog")
            if not locs:
                return None
            encs = _fr.face_encodings(img_rgb, locs)
            if encs:
                return encs[0].astype(np.float32)
            # encodings failed — fall through to OpenCV
        except Exception as e:
            logger.warning(f"[FACE] face_recognition failed, using OpenCV fallback: {e}")

    return _opencv_embedding(img_bgr)


def compare(stored: np.ndarray, candidate: np.ndarray,
            threshold: Optional[float] = None) -> Tuple[bool, float]:
    """
    Compare two embeddings.
    Returns (match: bool, score: float).
    Score is Euclidean distance for face_recognition, cosine similarity for OpenCV.
    """
    if stored is None or candidate is None:
        return False, 999.0

    if _lib == "face_recognition":
        t    = threshold if threshold is not None else 0.58
        dist = float(np.linalg.norm(stored - candidate))
        return dist < t, dist

    # OpenCV: cosine similarity (higher = better)
    t   = threshold if threshold is not None else 0.80
    sim = float(np.dot(stored, candidate) /
                (np.linalg.norm(stored) * np.linalg.norm(candidate) + 1e-10))
    return sim > t, sim


def has_face(b64_image: str) -> bool:
    """Quick check: does this image contain a detectable face?"""
    if _cascade is None:
        return False
    img_bgr = decode_b64_image(b64_image)
    if img_bgr is None:
        return False
    try:
        gray  = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        faces = _cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
        return len(faces) > 0
    except Exception:
        return False
