"""
Quick TTS test - run this to verify voice output works
"""
import tts

print("="*50)
print("TESTING TTS")
print("="*50)

if tts.is_available():
    print("TTS is available, speaking test phrase...")
    result = tts.speak("Jarvis voice system is working")
    print(f"TTS result: {result}")
else:
    print("TTS not available - check pyttsx3 and sapi5")

print("="*50)
