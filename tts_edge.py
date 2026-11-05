"""
Edge TTS — cinematic neural voice for Study Mode intro quotes.
Falls back to pyttsx3 via tts.py when Edge TTS or playback fails.
"""

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
import threading

logger = logging.getLogger("jarvis.tts_edge")

_lock = threading.Lock()
VOICE = "en-US-DavisNeural"   # deeper, calmer, more cinematic than Guy
RATE  = "-12%"                # slower for motivational pacing
PITCH = "-4Hz"                # deeper resonance
MAX_SECONDS = 20


async def _generate_mp3(text: str, path: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH)
    await communicate.save(path)


def _play_mp3_windows(path: str) -> None:
    path_esc = path.replace("'", "''")
    ps = (
        f"$p = New-Object System.Windows.Media.MediaPlayer; "
        f"$p.Open('{path_esc}'); $p.Volume = 1.0; $p.Play(); "
        f"Start-Sleep -Milliseconds 250; "
        f"$dur = $p.NaturalDuration.TimeSpan.TotalSeconds; "
        f"if ($dur -le 0) {{ $dur = 8 }}; "
        f"$t0 = [DateTime]::UtcNow; "
        f"while (([DateTime]::UtcNow - $t0).TotalSeconds -lt ($dur + 0.15)) {{ "
        f"  Start-Sleep -Milliseconds 80; "
        f"}}; "
        f"$p.Close()"
    )
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        creationflags=flags,
        timeout=MAX_SECONDS,
        check=False,
    )


def _play_mp3(path: str) -> None:
    if sys.platform == "win32":
        _play_mp3_windows(path)
        return
    try:
        import playsound
        playsound.playsound(path, block=True)
    except Exception as e:
        logger.warning("[TTS_EDGE] playsound failed: %s", e)
        raise


def _speak_edge(text: str) -> bool:
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name
        asyncio.run(_generate_mp3(text, path))
        _play_mp3(path)
        return True
    except Exception as e:
        logger.warning("[TTS_EDGE] Edge TTS failed: %s", e)
        return False
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def speak_study(text: str) -> None:
    """Blocking study quote — Edge TTS first, pyttsx3 fallback."""
    if not text or not text.strip():
        return
    acquired = _lock.acquire(timeout=8)
    if not acquired:
        logger.warning("[TTS_EDGE] Lock busy — skipping")
        return
    try:
        clean = text.strip()
        if _speak_edge(clean):
            return
        import tts
        logger.info("[TTS_EDGE] Falling back to pyttsx3")
        tts.speak(clean)
    finally:
        _lock.release()


def is_available() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False
