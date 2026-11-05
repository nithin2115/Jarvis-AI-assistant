"""
JARVIS TTS Module
Fresh sapi5 engine per utterance (avoids pyttsx3 reuse-after-runAndWait bug).
A single threading.Lock ensures only one voice plays at a time.
Timeout protection: if TTS hangs for > MAX_TTS_SECONDS, it is forcefully skipped.
"""

import pyttsx3
import threading
import re
import time
import logging

logger = logging.getLogger("jarvis.tts")

_lock = threading.Lock()   # serialises all speak calls
MAX_TTS_SECONDS = 15       # max time for a single TTS utterance


def _clean(text: str) -> str:
    text = re.sub(r'[\*_`#\[\]]', '', text)
    text = re.sub(r'http[s]?://\S+', 'link', text)
    text = re.sub(r'```[\s\S]*?```', 'code block', text)
    text = re.sub(r'`[^`]*`', '', text)
    return ' '.join(text.split())


def _do_speak(text: str) -> None:
    """Speak with timeout protection. Never blocks forever."""
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
                engine = pyttsx3.init('sapi5')
                voices = engine.getProperty('voices')
                if voices:
                    engine.setProperty('voice', voices[0].id)
                # 180 WPM gives a calm, intelligent cadence with natural
                # comma/period pauses. 195 was rushed and clipped sentences.
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
    try:
        pyttsx3.init('sapi5')
        return True
    except Exception:
        return False


if __name__ != "__main__":
    print("[TTS] Module loaded -", "TTS available" if is_available() else "TTS NOT available")

if __name__ == "__main__":
    print("JARVIS TTS TEST")
    if is_available():
        speak("Jarvis voice system initialized. Ready for commands.")
    else:
        print("[TEST] TTS not available")
