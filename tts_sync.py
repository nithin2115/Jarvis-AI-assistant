"""
JARVIS TTS Module - Synchronous Version
pyttsx3 works best when run synchronously in main thread
"""

import pyttsx3
import re
import sys

# Global TTS engine - initialized once
_engine = None
_engine_ready = False

def init_engine():
    """Initialize the global TTS engine"""
    global _engine, _engine_ready
    
    if _engine is not None and _engine_ready:
        return True
    
    try:
        print("[TTS] Initializing voice engine...")
        _engine = pyttsx3.init('sapi5')
        
        voices = _engine.getProperty('voices')
        if voices:
            _engine.setProperty('voice', voices[0].id)
            print(f"[TTS] Voice: {voices[0].name}")
        
        _engine.setProperty('rate', 170)
        _engine.setProperty('volume', 1.0)
        
        _engine_ready = True
        print("[TTS] Engine ready")
        return True
        
    except Exception as e:
        print(f"[TTS] Init failed: {e}")
        _engine = None
        _engine_ready = False
        return False


def speak(text):
    """
    Speak text SYNCHRONOUSLY (blocking)
    This ensures pyttsx3 works correctly
    """
    global _engine, _engine_ready
    
    print(f"[TTS] Speaking: {text[:60]}...")
    
    if not text or not text.strip():
        print("[TTS] Empty text")
        return False
    
    if _engine is None or not _engine_ready:
        if not init_engine():
            print("[TTS] Cannot initialize")
            return False
    
    try:
        clean_text = _clean_text(text)
        _engine.say(clean_text)
        _engine.runAndWait()
        print("[TTS] Done")
        return True
    except Exception as e:
        print(f"[TTS] Error: {e}")
        return False


def _clean_text(text):
    """Clean text for speech"""
    text = re.sub(r'[\*_`#\[\]]', '', text)
    text = re.sub(r'http[s]?://\S+', 'link', text)
    text = ' '.join(text.split())
    text = re.sub(r'```[\s\S]*?```', 'code block', text)
    text = re.sub(r'`[^`]*`', 'code', text)
    return text


def is_available():
    """Check if TTS is available"""
    if _engine is None or not _engine_ready:
        return init_engine()
    return True


# Auto-initialize on import
if __name__ != "__main__":
    init_engine()


if __name__ == "__main__":
    if is_available():
        speak("Jarvis voice system initialized")
