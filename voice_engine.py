"""
JARVIS Voice Engine - Full Voice Interaction System
Manages wake word detection, listening, and voice output
"""

import threading
import time
from typing import Callable, Optional
from wake_detector import WakeWordDetector
import tts

class VoiceEngine:
    """
    Full voice-driven AI system
    Flow: Wake Word -> Confirm -> Listen -> Process -> Speak Response
    """
    
    def __init__(self, on_command: Optional[Callable] = None):
        self.wake_detector = WakeWordDetector(on_wake=self._on_wake_word)
        self.on_command = on_command
        self.is_active = False
        self.is_speaking = False
        
    def start(self):
        """Start the always-listening voice system"""
        print("[VOICE] Starting voice engine...")
        
        # Test TTS
        if tts.is_available():
            print("[VOICE] TTS ready")
            tts.speak("Jarvis voice system activated")
            time.sleep(2)
        else:
            print("[VOICE] TTS not available!")
            
        # Start wake word detection
        self.wake_detector.start()
        print("[VOICE] Voice engine running - say 'Hey Jarvis' to activate")
        
    def stop(self):
        """Stop the voice system"""
        self.wake_detector.stop()
        self.is_active = False
        print("[VOICE] Voice engine stopped")
        
    def _on_wake_word(self, text: str):
        """Handle wake word detection"""
        if self.is_active or self.is_speaking:
            return
            
        self.is_active = True
        print("[VOICE] Wake word detected!")
        
        # STEP 1: Confirm activation with voice
        tts.speak("Yes, tell me boss")
        time.sleep(2)
        
        # STEP 2: Listen for command
        command = self.wake_detector.listen_once(timeout=8)
        
        if command:
            # STEP 3: Process command
            print(f"[VOICE] Processing command: '{command}'")
            if self.on_command:
                self._handle_command(command)
        else:
            # No command heard
            tts.speak("I did not hear that. Please try again.")
            time.sleep(2)
            
        self.is_active = False
        print("[VOICE] Ready for next wake word")
        
    def _handle_command(self, command: str):
        """Process user command through callback"""
        if self.on_command:
            # This will trigger AI processing in app.py
            self.on_command(command)
            
    def speak_response(self, response: str):
        """Speak AI response"""
        self.is_speaking = True
        print(f"[VOICE] Speaking response: {response[:80]}...")
        tts.speak(response)
        self.is_speaking = False


# Global voice engine instance
_voice_engine = None

def get_voice_engine(on_command=None) -> VoiceEngine:
    """Get or create global voice engine"""
    global _voice_engine
    if _voice_engine is None:
        _voice_engine = VoiceEngine(on_command=on_command)
    return _voice_engine

def start_voice_system(on_command=None):
    """Start the voice system with callback"""
    engine = get_voice_engine(on_command)
    engine.start()
    return engine

def stop_voice_system():
    """Stop the voice system"""
    global _voice_engine
    if _voice_engine:
        _voice_engine.stop()
        _voice_engine = None
