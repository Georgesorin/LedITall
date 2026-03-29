import os
import math
import wave
import struct
import tempfile
try:
    import pygame
except ImportError:
    pygame = None

class SoundManager:
    def __init__(self, enabled=True, volume=0.5):
        self.enabled = enabled and (pygame is not None)
        self.volume = volume
        self.sounds = {}
        self.temp_files = []

        if not self.enabled:
            print("[AUDIO] pygame nu este instalat.")
            return

        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
            self._build_sounds()
            print("[AUDIO] Sunet OK")
        except Exception as e:
            print(f"[AUDIO] ERROR: {e}")
            self.enabled = False

    def cleanup(self):
        for f in self.temp_files:
            try:
                os.remove(f)
            except:
                pass
        if self.enabled:
            pygame.mixer.quit()

    def _make_wave(self, freqs, duration=0.2, volume=0.5):
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        self.temp_files.append(path)

        sample_rate = 44100
        n = int(sample_rate * duration)

        with wave.open(path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)

            frames = bytearray()
            for i in range(n):
                t = i / sample_rate
                env = (1 - i / n)  # fade out

                sample = 0
                for f in freqs:
                    sample += math.sin(2 * math.pi * f * t)

                sample /= len(freqs)
                sample = int(32767 * volume * env * sample)

                frames += struct.pack("<h", sample)

            wf.writeframes(frames)

        return pygame.mixer.Sound(path)

    def _build_sounds(self):
        # 🎵 note muzicale (mai nice decât random freqs)
        notes = [
            261.63, 293.66, 329.63,
            349.23, 392.00, 440.00,
            493.88, 523.25, 587.33,
            659.25, 698.46, 783.99
        ]

        # TILE sounds (clar, distinct)
        for i, f in enumerate(notes):
            snd = self._make_wave([f], 0.18, self.volume)
            snd.set_volume(self.volume)
            self.sounds[f"tile_{i}"] = snd

        # SUCCESS (uplifting)
        self.sounds["success"] = self._make_wave([523.25, 659.25, 783.99], 0.35)

        # FAIL (low + rough)
        self.sounds["wrong"] = self._make_wave([140, 110], 0.45)

        # GAME OVER (deep)
        self.sounds["game_over"] = self._make_wave([100, 80], 0.7)

        # COUNTDOWN (increasing pitch)
        self.sounds["count_3"] = self._make_wave([500], 0.2)
        self.sounds["count_2"] = self._make_wave([700], 0.2)
        self.sounds["count_1"] = self._make_wave([900], 0.25)

        # INTRO (arcade vibe)
        self.sounds["intro"] = self._make_wave([440, 660], 0.4)

    def play(self, name):
        if not self.enabled:
            return
        try:
            if name in self.sounds:
                self.sounds[name].play(maxtime=500)
        except:
            pass
