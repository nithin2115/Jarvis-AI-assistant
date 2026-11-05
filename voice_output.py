"""
JARVIS Voice Output Module (TTS)
Production-grade text-to-speech with pyttsx3
"""

import pyttsx3
import threading
import logging
import time
from typing import Optional, Callable

logger = logging.getLogger('jarvis.tts')

class VoiceOutput:
    """Text-to-Speech engine for JARVIS"""
    
    def __init__(self):
        self.engine = None
        self.is_speaking = False
        self._lock = threading.Lock()
        self._init_engine()
        
    def _init_engine(self):
        """Initialize TTS engine with error handling"""
        try:
            logger.info("[TTS] Initializing voice engine...")
            self.engine = pyttsx3.init()
            
            # Configure voice properties
            self.engine.setProperty('rate', 175)  # Speech rate
            self.engine.setProperty('volume', 0.9)  # Volume 0-1
            
            # Get available voices
            voices = self.engine.getProperty('voices')
            if voices:
                # Try to use a male voice (usually index 0)
                self.engine.setProperty('voice', voices[0].id)
                logger.info(f"[TTS] Voice set to: {voices[0].name}")
            
            logger.info("[TTS] Voice engine initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"[TTS] Initialization failed: {e}")
            self.engine = None
            return False
    
    def speak(self, text: str, on_start: Optional[Callable] = None, 
              on_end: Optional[Callable] = None) -> bool:
        """
        Speak text with callbacks
        
        Args:
            text: Text to speak
            on_start: Callback when speaking starts
            on_end: Callback when speaking ends
            
        Returns:
            bool: True if speech started successfully
        """
        if not text or not text.strip():
            logger.warning("[TTS] Empty text provided")
            return False
        
        if not self.engine:
            logger.error("[TTS] Engine not initialized")
            return False
        
        with self._lock:
            if self.is_speaking:
                logger.warning("[TTS] Already speaking, queueing...")
            
            self.is_speaking = True
        
        def speak_async():
            try:
                logger.info(f"[TTS] Speaking: {text[:60]}...")
                
                if on_start:
                    try:
                        on_start()
                    except Exception as e:
                        logger.error(f"[TTS] on_start callback error: {e}")
                
                # Clean text for speech
                clean_text = self._clean_text(text)
                
                # Speak
                self.engine.say(clean_text)
                self.engine.runAndWait()
                
                logger.info("[TTS] Speaking finished")
                
                if on_end:
                    try:
                        on_end()
                    except Exception as e:
                        logger.error(f"[TTS] on_end callback error: {e}")
                        
            except Exception as e:
                logger.error(f"[TTS] Speech error: {e}")
            finally:
                with self._lock:
                    self.is_speaking = False
        
        # Run speech in background thread
        thread = threading.Thread(target=speak_async, daemon=True)
        thread.start()
        return True
    
    def _clean_text(self, text: str) -> str:
        """Clean text for better speech"""
        # Remove markdown
        import re
        text = re.sub(r'[\*_`#]', '', text)
        # Remove URLs
        text = re.sub(r'http[s]?://\S+', 'link', text)
        # Remove extra whitespace
        text = ' '.join(text.split())
        return text
    
    def stop(self):
        """Stop current speech"""
        if self.engine:
            try:
                self.engine.stop()
                logger.info("[TTS] Speech stopped")
            except Exception as e:
                logger.error(f"[TTS] Stop error: {e}")
        
        with self._lock:
            self.is_speaking = False
    
    def is_available(self) -> bool:
        """Check if TTS is available"""
        return self.engine is not None


# Global TTS instance
tts_engine = VoiceOutput()

def speak_text(text: str, on_start=None, on_end=None) -> bool:
    """Global function to speak text"""
    return tts_engine.speak(text, on_start, on_end)

def stop_speaking():
    """Global function to stop speech"""
    tts_engine.stop()

def is_voice_available() -> bool:
    """Check if voice output is available"""
    return tts_engine.is_available()


if __name__ == "__main__":
    # Test TTS
    logging.basicConfig(level=logging.INFO)
    
    print("Testing JARVIS TTS...")
    
    if is_voice_available():
        print("✓ TTS Engine ready")
        
        def on_start():
            print("🎙️  Speaking started...")
        
        def on_end():
            print("✓ Speaking finished")
        
        speak_text("JARVIS online. All systems operational. Ready for your commands, boss.", 
                   on_start, on_end)
        
        # Wait for speech to complete
        time.sleep(5)
    else:
        print("✗ TTS Engine failed to initialize")
