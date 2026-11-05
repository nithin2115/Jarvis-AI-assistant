"""
JARVIS TTS Module
Fresh sapi5 engine per utterance (avoids pyttsx3 reuse-after-runAndWait bug).
A single threading.Lock ensures only one voice plays at a time.
Timeout protection: if TTS hangs for > MAX_TTS_SECONDS, it is forcefully skipped.

NOTE: pyttsx3 is Windows-only (uses SAPI5). On Linux/Mac this module loads safely
but all speak calls are silent no-ops. Voice is handled by the browser's Web Speech API.
"""

import threading
import re
import time
import logging
import platform

logger = logging.getLogger("jarvis.tts")

_lock = threading.Lock()   # serialises all speak calls
MAX_TTS_SECONDS = 15       # max time for a single TTS utterance

# Detect platform once at import time — safe on all OSes
_IS_WINDOWS = platform.system() == "Windows"

# Try to import pyttsx3 (Windows only); silently skip on Linux/Mac
_pyttsx3 = None
if _IS_WINDOWS:
    try:
        import pyttsx3 as _pyttsx3
    except ImportError:
        logger.warning("[TTS] pyttsx3 not installed — TTS disabled")
        _pyttsx3 = None


def _clean(text: str) -> str:
    text = re.sub(r'[\*_`#\[\]]', '', text)
    text = re.sub(r'http[s]?://\S+', 'link', text)
    text = re.sub(r'```[\s\S]*?```', 'code block', text)
    text = re.sub(r'`[^`]*`', '', text)
    return ' '.join(text.split())


def _do_speak(text: str) -> None:
    """Speak with timeout protection. Never blocks forever. No-op on Linux."""
    if not _IS_WINDOWS or _pyttsx3 is None:
        return  # Silent on Linux/cloud deployments

    acquired = _lock.acquire(timeout=5)
    if not acquired:
        logger.warning("[TTS] Could not acquire lock (timeout 5s) — skipping")
        print("[TTS] ⚠️ Lock busy — skipping utterance")
        return

    try:
        t0 = time.time()
        result_box = [False]  # did TTS complete?
        error_box = [None]

        def _engine_work():
            try:
                engine = _pyttsx3.init('sapi5')
                voices = engine.getProperty('voices')
                if voices:
                    engine.setProperty('voice', voices[0].id)
                engine.setProperty('rate', 180)
                engine.setProperty('volume', 1.0)
                engine.say(text)
                engine.runAndWait()
                result_box[0] = True
            except Exception as e:
                error_box[0] = e

        t = threading.Thread(target=_engine_work, daemon=True)
        t.start()
        t.join(timeout=MAX_TTS_SECONDS)

        elapsed = time.time() - t0
        if t.is_alive():
            logger.warning(f"[TTS] Engine hung for {elapsed:.1f}s — skipping (thread abandoned)")
            print(f"[TTS] ⚠️ Timeout after {elapsed:.1f}s — skipping")
        elif error_box[0]:
            logger.error(f"[TTS] Engine error: {error_box[0]}")
            print(f"[TTS] ERROR: {error_box[0]}")
        else:
            logger.info(f"[TTS] Done in {elapsed:.1f}s")
            print(f"[TTS] Done ({elapsed:.1f}s)")
    finally:
        _lock.release()


def speak(text: str) -> None:
    """Blocking speak — returns after the engine finishes (with timeout protection)."""
    if not text or not text.strip():
        return
    _do_speak(_clean(text))


def speak_async(text: str) -> None:
    """Non-blocking speak — fires in a background thread."""
    if not text or not text.strip():
        return
    threading.Thread(target=_do_speak, args=(_clean(text),), daemon=True).start()


def is_available() -> bool:
    if not _IS_WINDOWS or _pyttsx3 is None:
        return False
    try:
        _pyttsx3.init('sapi5')
        return True
    except Exception:
        return False


if __name__ != "__main__":
    _status = "TTS available (Windows)" if is_available() else "TTS NOT available (Linux/cloud — silent mode)"
    print(f"[TTS] Module loaded — {_status}")

if __name__ == "__main__":
    print("JARVIS TTS TEST")
    if is_available():
        speak("Jarvis voice system initialized. Ready for commands.")
    else:
        print("[TEST] TTS not available (non-Windows or pyttsx3 missing)")
