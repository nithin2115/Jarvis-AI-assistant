"""
JARVIS Microphone Diagnostic Test
Tests: device detection, audio capture, resampling, and Vosk recognition.
Run: python test_mic.py
"""
import time
import sys
import os
import numpy as np

def rms_energy(audio_bytes):
    samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2)))

def resample(audio_data, from_rate, to_rate):
    if from_rate == to_rate:
        return audio_data
    samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
    duration = len(samples) / from_rate
    new_length = int(duration * to_rate)
    if new_length == 0:
        return b'\x00\x00'
    indices = np.linspace(0, len(samples) - 1, new_length)
    resampled = np.interp(indices, np.arange(len(samples)), samples)
    return resampled.astype(np.int16).tobytes()

def main():
    print("=" * 60)
    print("  JARVIS MICROPHONE DIAGNOSTIC")
    print("=" * 60)

    # Step 1: Check sounddevice
    print("\n[1/5] Checking sounddevice...")
    try:
        import sounddevice as sd
        print("  [OK] sounddevice installed")
    except ImportError:
        print("  [FAIL] sounddevice NOT installed. Run: pip install sounddevice")
        return

    # Step 2: List devices
    print("\n[2/5] Listing audio devices...")
    devices = sd.query_devices()
    input_devs = []
    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            is_def = " * DEFAULT" if i == sd.default.device[0] else ""
            print("  [%d] %s | ch=%d | rate=%dHz%s" % (
                i, dev['name'], dev['max_input_channels'],
                int(dev['default_samplerate']), is_def))
            input_devs.append(i)

    if not input_devs:
        print("  [FAIL] No input devices found!")
        return

    # Step 3: Test default input device
    default_idx = 27
    default_dev = devices[default_idx]
    native_rate = 16000

    print("\n[3/5] Testing device [%d] at native %dHz..." % (default_idx, native_rate))
    import queue
    audio_q = queue.Queue()
    def cb(indata, frames, time_info, status):
        if status:
            print("  [WARN] Audio status: %s" % str(status))
        audio_q.put(bytes(indata))

    block_size = int(native_rate * 0.25)  # 250ms

    try:
        with sd.RawInputStream(
            device=default_idx,
            samplerate=native_rate,
            blocksize=block_size,
            dtype='int16',
            channels=1,
            callback=cb
        ):
            print("  [OK] Stream opened successfully")
            print("  Recording 3 seconds of audio...")
            print("  >> SPEAK NOW! <<")

            chunks = []
            start = time.time()
            while time.time() - start < 3.0:
                try:
                    data = audio_q.get(timeout=1.0)
                    chunks.append(data)
                    energy = rms_energy(data)
                    bar_len = min(50, int(energy / 100))
                    bar = '#' * bar_len
                    print("  Energy: %8.1f |%s" % (energy, bar))
                except queue.Empty:
                    print("  [WARN] No audio data received!")

        if not chunks:
            print("  [FAIL] No audio chunks captured!")
            return

        all_audio = b''.join(chunks)
        total_energy = rms_energy(all_audio)
        print("\n  Total samples: %d" % (len(all_audio) // 2))
        print("  Total energy: %.1f" % total_energy)
        if total_energy < 10:
            print("  [WARN] Very low energy -- mic may be muted or disconnected")
        else:
            print("  [OK] Audio capture working!")

    except Exception as e:
        print("  [FAIL] Stream error: %s" % str(e))
        return

    # Step 4: Test resampling
    print("\n[4/5] Testing resampling %dHz -> 16000Hz..." % native_rate)
    try:
        test_chunk = chunks[0]
        resampled = resample(test_chunk, native_rate, 16000)
        print("  Input: %d bytes (%dHz)" % (len(test_chunk), native_rate))
        print("  Output: %d bytes (16000Hz)" % len(resampled))
        print("  Ratio: %.3f (expected: %.3f)" % (len(resampled)/len(test_chunk), 16000/native_rate))
        print("  [OK] Resampling working!")
    except Exception as e:
        print("  [FAIL] Resampling error: %s" % str(e))
        return

    # Step 5: Test Vosk recognition
    print("\n[5/5] Testing Vosk recognition...")
    try:
        from vosk import Model, KaldiRecognizer, SetLogLevel
        import json
        SetLogLevel(-1)

        model_path = os.path.join(os.path.dirname(__file__), "data", "vosk-model")
        if not os.path.isdir(model_path):
            print("  [FAIL] Vosk model not found at %s" % model_path)
            return

        model = Model(model_path)
        rec = KaldiRecognizer(model, 16000)
        rec.SetWords(True)
        print("  [OK] Vosk model loaded")

        # Feed all captured audio (resampled) to Vosk
        print("  Feeding captured audio to Vosk...")
        all_resampled = resample(all_audio, native_rate, 16000)
        chunk_size = 4000  # ~250ms at 16kHz
        recognized = []
        for i in range(0, len(all_resampled), chunk_size):
            chunk = all_resampled[i:i+chunk_size]
            if rec.AcceptWaveform(chunk):
                result = json.loads(rec.Result())
                text = result.get("text", "").strip()
                if text:
                    recognized.append(text)
                    print("  Recognized: \"%s\"" % text)
            else:
                partial = json.loads(rec.PartialResult())
                p = partial.get("partial", "").strip()
                if p:
                    print("  Partial: \"%s\"" % p)

        # Get final result
        result = json.loads(rec.FinalResult())
        text = result.get("text", "").strip()
        if text:
            recognized.append(text)
            print("  Final: \"%s\"" % text)

        if recognized:
            print("  [OK] Vosk recognized: %s" % ' '.join(recognized))
        else:
            print("  [INFO] No speech recognized (OK if you didn't speak)")

    except ImportError:
        print("  [FAIL] vosk NOT installed. Run: pip install vosk")
    except Exception as e:
        print("  [FAIL] Vosk error: %s" % str(e))

    print("\n" + "=" * 60)
    print("  DIAGNOSTIC COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
