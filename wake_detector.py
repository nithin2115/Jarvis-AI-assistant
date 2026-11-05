"""
JARVIS Wake Word Detector
Listens for 'Hey Jarvis' and triggers voice activation
"""

import speech_recognition as sr
import threading
import time
from typing import Callable, Optional

class WakeWordDetector:
    """Detects 'Hey Jarvis' wake word and triggers callback"""
    
    WAKE_WORDS = ["hey jarvis", "hi jarvis", "jarvis", "ok jarvis"]
    
    def __init__(self, on_wake: Optional[Callable] = None):
        self.recognizer = sr.Recognizer()
        self.microphone = None
        self.on_wake = on_wake
        self.listening = False
        self.thread = None
        
    def start(self):
        """Start background listening for wake word"""
        if self.listening:
            return
            
        try:
            self.microphone = sr.Microphone()
            # Calibrate for ambient noise
            with self.microphone as source:
                print("[WAKE] Calibrating microphone...")
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                
            self.listening = True
            self.thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.thread.start()
            print("[WAKE] Wake word detection started - listening for 'Hey Jarvis'")
            
        except Exception as e:
            print(f"[WAKE] Failed to start: {e}")
            
    def stop(self):
        """Stop listening"""
        self.listening = False
        print("[WAKE] Stopped")
        
    def _listen_loop(self):
        """Continuous listening loop"""
        while self.listening:
            try:
                with self.microphone as source:
                    # Listen with short timeout
                    audio = self.recognizer.listen(source, timeout=2, phrase_time_limit=3)
                    
                # Try to recognize
                text = self.recognizer.recognize_google(audio).lower()
                print(f"[WAKE] Heard: '{text}'")
                
                # Check if wake word detected
                if any(wake in text for wake in self.WAKE_WORDS):
                    print("[WAKE] WAKE WORD DETECTED!")
                    if self.on_wake:
                        self.on_wake(text)
                        
            except sr.WaitTimeoutError:
                pass  # No speech detected, keep listening
            except sr.UnknownValueError:
                pass  # Could not understand audio
            except sr.RequestError as e:
                print(f"[WAKE] API error: {e}")
            except Exception as e:
                print(f"[WAKE] Error: {e}")
                time.sleep(0.5)
                
    def listen_once(self, timeout: int = 5) -> Optional[str]:
        """Listen for single command after wake word"""
        try:
            with self.microphone as source:
                print("[WAKE] Listening for command...")
                audio = self.recognizer.listen(source, timeout=timeout)
                text = self.recognizer.recognize_google(audio)
                print(f"[WAKE] Command: '{text}'")
                return text
        except Exception as e:
            print(f"[WAKE] Command error: {e}")
            return None
