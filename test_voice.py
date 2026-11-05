"""
Jarvis Voice System Test
Tests TTS, STT, Ollama connection, and full voice flow.
"""
import asyncio
import sys
sys.path.insert(0, r'C:\Users\vamsi\CascadeProjects\jarvis')

from voice_engine import TextToSpeech, SpeechToText, VoiceEngine
from ai_brain import AIBrain, ask_ai
from config.settings import ai_config

print("=" * 50)
print("JARVIS VOICE SYSTEM TEST")
print("=" * 50)

# Test 1: TTS (pyttsx3)
print("\n[TEST 1] Text-to-Speech (pyttsx3)")
print("-" * 30)
try:
    tts = TextToSpeech(engine="pyttsx3")
    if tts._initialized:
        print("✓ TTS initialized successfully")
        
        # Test speaking
        test_text = "Hello, this is Jarvis. TTS is working correctly."
        print(f"Speaking: '{test_text}'")
        
        async def test_tts():
            result = await tts.speak(test_text)
            return result
        
        result = asyncio.run(test_tts())
        if result:
            print("✓ TTS speak completed successfully")
        else:
            print("✗ TTS speak failed")
    else:
        print("✗ TTS not initialized - pyttsx3 may not be available")
except Exception as e:
    print(f"✗ TTS test failed: {e}")

# Test 2: STT (microphone)
print("\n[TEST 2] Speech-to-Text (microphone)")
print("-" * 30)
try:
    stt = SpeechToText()
    if stt.is_available():
        print("✓ Microphone initialized successfully")
        print("Listening for 5 seconds... Speak now!")
        
        text = stt.listen(timeout=5, phrase_time_limit=10)
        if text:
            print(f"✓ Recognized: '{text}'")
        else:
            print("✗ No speech recognized (timeout or no audio)")
    else:
        print("✗ Microphone not available")
except Exception as e:
    print(f"✗ STT test failed: {e}")

# Test 3: Ollama connection
print("\n[TEST 3] Ollama Connection")
print("-" * 30)
try:
    from ai_brain import check_ollama_available, ask_ai
    
    if check_ollama_available():
        print(f"✓ Ollama is running and phi model is available")
        print(f"  Host: {ai_config.ollama_host}")
        print(f"  Model: {ai_config.model}")
        
        # Test ask_ai function
        print("\nTesting ask_ai function...")
        response = ask_ai("Say 'Ollama is working correctly' and nothing else.")
        print(f"Response: '{response[:100]}...' " if len(response) > 100 else f"Response: '{response}'")
        
        if "working" in response.lower() or "correctly" in response.lower():
            print("✓ ask_ai function working")
        else:
            print("? ask_ai responded but unexpected content")
    else:
        print("✗ Ollama not available or phi model not installed")
        print(f"  Host: {ai_config.ollama_host}")
        print("  Run: ollama pull phi")
        print("  Run: ollama serve")
except Exception as e:
    print(f"✗ Ollama test failed: {e}")

# Test 4: AI Brain
print("\n[TEST 4] AI Brain")
print("-" * 30)
try:
    brain = AIBrain()
    if brain.is_available():
        print("✓ AI Brain is available")
        
        # Test processing
        print("\nTesting AI Brain processing...")
        test_input = "Hello, are you working?"
        print(f"User input: '{test_input}'")
        
        async def test_brain():
            response = await brain.process_input(test_input)
            return response
        
        response = asyncio.run(test_brain())
        print(f"AI response: '{response.text[:100]}...' " if len(response.text) > 100 else f"AI response: '{response.text}'")
        print(f"Emotion: {response.emotion}")
        print("✓ AI Brain processing works")
    else:
        print("✗ AI Brain is offline (Ollama not running)")
except Exception as e:
    print(f"✗ AI Brain test failed: {e}")

# Test 5: Full Voice Flow
print("\n[TEST 5] Full Voice Flow (TTS → STT → AI → TTS)")
print("-" * 30)
try:
    voice = VoiceEngine()
    
    if not voice.is_available():
        print("✗ Voice engine not available")
    elif not brain.is_available():
        print("✗ Cannot test full flow - AI Brain offline")
    else:
        print("✓ Voice engine initialized")
        print("Say something after the beep...")
        
        # Speak prompt
        async def test_full_flow():
            await voice.speak("Please say something for me to process.")
            
            # Listen
            print("\nListening...")
            text = voice.stt.listen(timeout=5, phrase_time_limit=10)
            
            if text:
                print(f"Heard: '{text}'")
                
                # Send to AI
                print("Sending to AI...")
                response = await brain.process_input(text)
                
                # Speak response
                print(f"AI says: '{response.text[:100]}...' " if len(response.text) > 100 else f"AI says: '{response.text}'")
                await voice.speak(response.text)
                
                return True
            else:
                print("✗ No speech detected")
                return False
        
        result = asyncio.run(test_full_flow())
        if result:
            print("\n✓ Full voice flow completed successfully!")
        else:
            print("\n✗ Full voice flow failed")
            
except Exception as e:
    print(f"✗ Full flow test failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 50)
print("TEST COMPLETE")
print("=" * 50)
print("\nIf all tests passed, Jarvis should be working!")
print("Run 'python main.py' to start the full system.")
