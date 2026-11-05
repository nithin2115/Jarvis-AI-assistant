"""
Quick TTS Test - Verify pyttsx3 works on your system
"""

import pyttsx3
import time

print("="*50)
print("TTS DIAGNOSTIC TEST")
print("="*50)

try:
    print("[1] Initializing pyttsx3...")
    engine = pyttsx3.init('sapi5')
    print("   ✓ Engine initialized")
    
    print("[2] Getting voices...")
    voices = engine.getProperty('voices')
    print(f"   ✓ Found {len(voices)} voices")
    if voices:
        print(f"   ✓ Using voice: {voices[0].name}")
        engine.setProperty('voice', voices[0].id)
    
    print("[3] Setting properties...")
    engine.setProperty('rate', 170)
    engine.setProperty('volume', 1.0)
    print("   ✓ Properties set")
    
    print("[4] Testing speech...")
    engine.say("Testing. Jarvis voice system is working.")
    print("   ✓ Speech queued")
    
    print("[5] Running and waiting...")
    engine.runAndWait()
    print("   ✓ Speech completed!")
    
    print("="*50)
    print("SUCCESS! TTS is working correctly.")
    print("="*50)
    
except Exception as e:
    print("="*50)
    print(f"FAILED: {type(e).__name__}")
    print(f"Error: {e}")
    print("="*50)
    import traceback
    traceback.print_exc()

print("\nPress Enter to exit...")
input()
