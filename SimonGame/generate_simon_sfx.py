import wave
import math
import random
import os
import struct

SFX_DIR = "_sfx"
SAMPLE_RATE = 44100

def save_wav(filename, samples, sample_rate=SAMPLE_RATE):
    os.makedirs(SFX_DIR, exist_ok=True)
    path = os.path.join(SFX_DIR, filename)

    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)  # 16-bit PCM
        f.setframerate(sample_rate)

        frames = bytearray()
        for s in samples:
            s = max(-32768, min(32767, int(s)))
            frames.extend(struct.pack("<h", s))

        f.writeframes(frames)

    print(f"Generated {path}")

def silence(duration):
    n = int(SAMPLE_RATE * duration)
    return [0] * n

def envelope(i, n, attack=0.01, release=0.03):
    if n <= 0:
        return 0.0
    t = i / n
    if t < attack:
        return t / attack
    if t > 1.0 - release:
        return max(0.0, (1.0 - t) / release)
    return 1.0

def generate_tone(freq, duration, vol=0.4, wave_type="sine", slide=0.0, vibrato=0.0, vibrato_rate=6.0):
    n_samples = int(SAMPLE_RATE * duration)
    data = []

    for i in range(n_samples):
        t = i / SAMPLE_RATE
        env = envelope(i, n_samples, attack=0.02, release=0.08)

        cur_freq = freq + slide * t
        if vibrato > 0:
            cur_freq += math.sin(2 * math.pi * vibrato_rate * t) * vibrato

        if cur_freq <= 0:
            val = 0.0
        elif wave_type == "sine":
            val = math.sin(2 * math.pi * cur_freq * t)
        elif wave_type == "square":
            val = 1.0 if math.sin(2 * math.pi * cur_freq * t) >= 0 else -1.0
        elif wave_type == "saw":
            val = 2.0 * (t * cur_freq - math.floor(0.5 + t * cur_freq))
        elif wave_type == "noise":
            val = random.uniform(-1.0, 1.0)
        else:
            val = math.sin(2 * math.pi * cur_freq * t)

        sample = val * vol * env * 32767
        data.append(sample)

    return data

def concat_parts(parts):
    out = []
    for p in parts:
        out.extend(p)
    return out

def note(freq, dur, vol=0.35, wave_type="square", slide=0.0):
    return generate_tone(freq, dur, vol=vol, wave_type=wave_type, slide=slide)

def rest(dur):
    return silence(dur)

def mix(data1, data2):
    length = max(len(data1), len(data2))
    out = []
    for i in range(length):
        a = data1[i] if i < len(data1) else 0
        b = data2[i] if i < len(data2) else 0
        v = a + b
        v = max(-32768, min(32767, v))
        out.append(v)
    return out

def chord(freqs, duration, vol=0.2, wave_type="square"):
    layers = [generate_tone(f, duration, vol=vol, wave_type=wave_type) for f in freqs]
    if not layers:
        return silence(duration)

    out = layers[0]
    for layer in layers[1:]:
        out = mix(out, layer)
    return out

def generate_all():
    os.makedirs(SFX_DIR, exist_ok=True)

    hit = concat_parts([
        note(880, 0.05, vol=0.28, wave_type="square"),
        note(1174.66, 0.06, vol=0.25, wave_type="square")
    ])
    save_wav("hit.wav", hit)

    fail = concat_parts([
        generate_tone(420, 0.10, vol=0.35, wave_type="saw", slide=-180),
        generate_tone(280, 0.16, vol=0.38, wave_type="saw", slide=-120),
        generate_tone(160, 0.22, vol=0.42, wave_type="saw", slide=-80),
    ])
    save_wav("fail.wav", fail)

    count = concat_parts([
        note(740, 0.08, vol=0.25, wave_type="square"),
        rest(0.02),
        note(740, 0.04, vol=0.18, wave_type="square")
    ])
    save_wav("count.wav", count)

    success_1 = concat_parts([
        note(523.25, 0.08), rest(0.02),
        note(659.25, 0.08), rest(0.02),
        note(783.99, 0.14), rest(0.02),
        note(1046.50, 0.18),
    ])
    save_wav("success_1.wav", success_1)

    success_2 = concat_parts([
        note(587.33, 0.07), rest(0.015),
        note(783.99, 0.07), rest(0.015),
        note(987.77, 0.10), rest(0.02),
        note(1174.66, 0.16),
    ])
    save_wav("success_2.wav", success_2)

    success_3 = concat_parts([
        note(392.00, 0.07), rest(0.02),
        note(523.25, 0.07), rest(0.02),
        note(659.25, 0.07), rest(0.02),
        note(783.99, 0.18),
    ])
    save_wav("success_3.wav", success_3)

    success_4 = concat_parts([
        note(659.25, 0.06), rest(0.015),
        note(783.99, 0.06), rest(0.015),
        note(987.77, 0.06), rest(0.015),
        note(1318.51, 0.20),
    ])
    save_wav("success_4.wav", success_4)

    perfect = concat_parts([
        chord([523.25, 659.25, 783.99], 0.12, vol=0.10),
        rest(0.03),
        chord([659.25, 783.99, 1046.50], 0.22, vol=0.10),
    ])
    save_wav("perfect.wav", perfect)

if __name__ == "__main__":
    generate_all()