"""Generate a small WAV fixture (1 sec, 16kHz mono, 440Hz sine)."""
import wave, math, struct, os
path = os.path.join(os.path.dirname(__file__), "sine.wav")
sr = 16000
dur = 1
with wave.open(path, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    for i in range(sr * dur):
        v = int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / sr))
        w.writeframes(struct.pack("<h", v))
print("Wrote", path, os.path.getsize(path), "bytes")
