import os
import sys
import subprocess
import socket
import threading
import time
import random

# ==========================================
# 1. AUTO-INSTALARE DEPENDENȚE
# ==========================================
def install_and_import(package):
    try:
        __import__(package)
    except ImportError:
        print(f"📦 Pachetul '{package}' lipsește. Se instalează acum...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])

install_and_import('pygame')
install_and_import('numpy')

import numpy as np
import pygame

# ==========================================
# 2. GENERATOR DE SUNET ARCADE (8-BIT)
# ==========================================
pygame.mixer.init(frequency=44100, size=-16, channels=1)

def generate_arcade_tone(freq, duration=0.4):
    sample_rate = 44100
    n_samples = int(sample_rate * duration)
    t = np.linspace(0, duration, n_samples, False)
    wave = 0.4 * np.sign(np.sin(2 * np.pi * freq * t))
    attack_len = int(sample_rate * 0.02)
    noise = (np.random.rand(attack_len) * 2 - 1) * 0.3
    wave[:attack_len] += noise
    decay = np.exp(-5 * t)
    wave = wave * decay
    audio_data = (wave * 32767).astype(np.int16)
    return pygame.mixer.Sound(buffer=audio_data)

FREQS = [329.63, 392.00, 440.00, 523.25, 587.33, 659.25, 783.99, 880.00, 987.77, 1046.50]
SOUND_BANK = {}

print("🕹️  Sintetizăm sunetele Arcade...")
for w in range(1, 5):
    for l in range(1, 11):
        f = FREQS[l-1]
        if w == 2: f *= 1.5
        if w == 4: f *= 0.5
        SOUND_BANK[(w, l)] = generate_arcade_tone(f)

FAIL_SOUND = generate_arcade_tone(110.0, duration=0.8)

# ==========================================
# 3. CONFIGURARE REȚEA & VIZUAL
# ==========================================
TARGET_IP = "172.24.130.214"
PORT_SEND = 4626
PORT_RECV = 7800
MAGIC_HEADER = bytearray([0x75, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x88, 0x77, 0x00, 0x00, 0x00, 0x00])

current_frame = bytearray(132)
player_input = None
running = True

def set_led(wall, led_idx, r, g, b):
    global current_frame
    if not (1 <= wall <= 4 and 1 <= led_idx <= 10): return
    idx = wall - 1
    current_frame[led_idx * 12 + idx] = g
    current_frame[led_idx * 12 + 4 + idx] = r
    current_frame[led_idx * 12 + 8 + idx] = b

def get_arcade_color(wall):
    colors = {1: (255, 0, 255), 2: (0, 255, 255), 3: (255, 255, 0), 4: (0, 255, 0)}
    return colors.get(wall, (255, 255, 255))

# ==========================================
# 4. LOGICA JOCULUI (MODIFICATĂ)
# ==========================================
def play_tile(wall, led, duration=0.3):
    color = get_arcade_color(wall)
    set_led(wall, led, *color)
    SOUND_BANK[(wall, led)].play()
    time.sleep(duration)
    set_led(wall, led, 0, 0, 0)

def main_game():
    global player_input
    seq_len = 3
    sequence = []
    need_new_sequence = True # Variabilă care decide dacă generăm ceva nou
    
    while running:
        # Faza 1: Intro (doar la pornire sau reset total)
        if need_new_sequence:
            print("\n--- 🌊 INITIALIZARE ---")
            for l in range(1, 11):
                for w in range(1, 5):
                    set_led(w, l, *get_arcade_color(w))
                    if w == 1: SOUND_BANK[(w, l)].play() 
                    time.sleep(0.04)
                    set_led(w, l, 0, 0, 0)
            time.sleep(0.5)
            
            # Generăm secvența nouă doar dacă am ghicit-o pe cea veche
            sequence = [(random.randint(1, 4), random.randint(1, 10)) for _ in range(seq_len)]
            need_new_sequence = False

        # Faza 2: Jocul îți arată secvența (aceeași până o ghicești)
        print(f"\nREPETARE SECVENȚĂ: {seq_len} NOTE")
        time.sleep(0.5)
        for w, l in sequence:
            play_tile(w, l, 0.4)
            time.sleep(0.2)
            
        # Faza 3: Rândul jucătorului
        print(">> ASCULT INPUT...")
        failed = False
        for w_exp, l_exp in sequence:
            player_input = None
            while player_input is None and running:
                time.sleep(0.01)
            
            if not running: return
            
            w_pre, l_pre = player_input
            if (w_pre, l_pre) == (w_exp, l_exp):
                play_tile(w_pre, l_pre, 0.2)
            else:
                failed = True
                break
        
        # Faza 4: Verificare rezultat
        if failed:
            print("💥 GRESIT! Încearcă din nou aceeași secvență.")
            FAIL_SOUND.play()
            # Flash Roșu
            for _ in range(2):
                for w in range(1,5):
                    for l in range(1,11): set_led(w,l,255,0,0)
                time.sleep(0.2)
                for w in range(1,5):
                    for l in range(1,11): set_led(w,l,0,0,0)
                time.sleep(0.2)
            # NU setăm need_new_sequence pe True, deci bucla va repeta sequence
            time.sleep(1)
        else:
            print("⭐ CORECT! Trecem la nivelul următor.")
            # Flash Verde de succes
            for w in range(1,5):
                for l in range(1,11): set_led(w,l,0,255,0)
            time.sleep(0.5)
            for w in range(1,5):
                for l in range(1,11): set_led(w,l,0,0,0)
            
            seq_len += 1
            need_new_sequence = True # Doar acum generăm o secvență nouă
            time.sleep(1)

# --- THREADS REȚEA ---
def sender_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while running:
        sock.sendto(MAGIC_HEADER + current_frame, (TARGET_IP, PORT_SEND))
        time.sleep(0.05)

def listener_loop():
    global player_input
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", PORT_RECV))
    while running:
        data, _ = sock.recvfrom(1024)
        if len(data) == 687 and data[0] == 0x88:
            for ch in range(1, 5):
                base = 2 + (ch - 1) * 171
                for led in range(1, 11):
                    if data[base + 1 + led] == 0xCC:
                        player_input = (ch, led)

if __name__ == "__main__":
    threading.Thread(target=sender_loop, daemon=True).start()
    threading.Thread(target=listener_loop, daemon=True).start()
    try:
        main_game()
    except KeyboardInterrupt:
        running = False