import os
import sys
import subprocess
import socket
import threading
import time
import random
import tkinter as tk
from tkinter import font

# ==========================================
# 1. AUTO-INSTALARE DEPENDENȚE
# ==========================================
def install_and_import(package):
    try:
        __import__(package)
    except ImportError:
        print(f"📦 Installing '{package}'...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])

install_and_import('pygame')
install_and_import('numpy')

import numpy as np
import pygame

# ==========================================
# 2. GENERATOR AUDIO "ETHEREAL" (MID-TONE)
# ==========================================
pygame.mixer.init(frequency=44100, size=-16, channels=2)

def generate_ethereal_tone(freq, duration=0.8):
    """Generează un sunet moale, de tip clopot de sticlă, cu frecvențe medii."""
    sample_rate = 44100
    n_samples = int(sample_rate * duration)
    t = np.linspace(0, duration, n_samples, False)
    
    # Undă sinusoidală pură, foarte blândă cu urechea
    wave = 0.5 * np.sin(2 * np.pi * freq * t)
    
    # Efect de Fade-in și Fade-out (ca să nu "înțepe" la început/sfârșit)
    attack_len = int(sample_rate * 0.05)
    release_len = int(sample_rate * 0.3)
    
    envelope = np.ones(n_samples)
    if attack_len > 0: envelope[:attack_len] = np.linspace(0, 1, attack_len)
    if release_len > 0: envelope[-release_len:] = np.linspace(1, 0, release_len)
    
    wave = wave * envelope
    audio_data = (wave * 32767).astype(np.int16)
    return pygame.mixer.Sound(buffer=audio_data)

def generate_atmospheric_bgm():
    """Muzică de fundal: un pad ambiental lent și misterios, pe tonuri medii-joase."""
    sample_rate = 44100
    duration = 12.0
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    
    # Acord lent, suspendat în aer
    wave = 0.15 * np.sin(2 * np.pi * 146.83 * t) + 0.15 * np.sin(2 * np.pi * 164.81 * t)
    wave *= (0.6 + 0.4 * np.sin(2 * np.pi * 0.08 * t)) # Pulsare extrem de lentă
    
    audio_data = (wave * 32767).astype(np.int16)
    return pygame.mixer.Sound(buffer=audio_data)

# Frecvențe mult mai joase și liniștitoare (Gama Re minor, octava 3-4)
FREQS = [146.83, 164.81, 174.61, 196.00, 220.00, 246.94, 261.63, 293.66, 329.63, 349.23]
SOUND_BANK = {}
for w in range(1, 5):
    for l in range(1, 11):
        f = FREQS[l-1]
        if w == 2: f *= 1.2 # Modificări subtile de pitch între pereți
        if w == 3: f *= 0.8
        if w == 4: f *= 1.1
        SOUND_BANK[(w, l)] = generate_ethereal_tone(f)

# Sunete specifice (Mai blânde)
INTRO_SOUND = generate_ethereal_tone(293.66, duration=1.5)
FAIL_SOUND = generate_ethereal_tone(98.00, duration=1.2) # Un ton grav, nu un buzzer
SUCCESS_SOUND = generate_ethereal_tone(440.00, duration=1.0)
BGM_TRACK = generate_atmospheric_bgm()

# ==========================================
# 3. REȚEA & VARIABILE GLOBALE
# ==========================================
PORT_SEND = 4626
PORT_RECV = 7800
MAGIC_HEADER = bytearray([0x75, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x88, 0x77, 0x00, 0x00, 0x00, 0x00])

TARGET_IP = "127.0.0.1"
current_frame = bytearray(132)
player_input = None
running = True
game_started = False

game_score = 0
game_status_text = "AWAITING INITIALIZATION"
game_time_left = "10:00"

# ==========================================
# 4. DISCOVERY FLOW
# ==========================================
def get_local_interfaces():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except: ip = '127.0.0.1'
    finally: s.close()
    parts = ip.split('.')
    bcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
    return [ip, bcast]

def run_discovery_flow():
    ip, bcast = get_local_interfaces()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try: sock.bind((ip, 7800))
    except: pass
    
    payload = bytearray([0x0A, 0x02, *b"KX-HC04", 0x03, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x14])
    rand1, rand2 = random.randint(0, 127), random.randint(0, 127)
    pkt = bytearray([0x67, rand1, rand2, len(payload)]) + payload
    pkt.append(sum(pkt) & 0xFF)
    
    try: sock.sendto(pkt, (bcast, 4626))
    except: return None
    
    sock.settimeout(0.5)
    end_time = time.time() + 2
    found_ip = None
    while time.time() < end_time:
        try:
            data, addr = sock.recvfrom(1024)
            if len(data) >= 30 and data[0] == 0x68:
                found_ip = addr[0]
                break
        except: pass
    sock.close()
    return found_ip

# ==========================================
# 5. CAMERA VISUALS (CULORI ELEGANTE)
# ==========================================
def set_led(wall, led_idx, r, g, b):
    global current_frame
    if not (1 <= wall <= 4 and 0 <= led_idx <= 10): return
    idx = wall - 1
    current_frame[led_idx * 12 + idx] = g
    current_frame[led_idx * 12 + 4 + idx] = r
    current_frame[led_idx * 12 + 8 + idx] = b

def get_ambient_color(wall):
    """Culori stinse, adânci, care nu obosesc ochiul în spații întunecate."""
    colors = {
        1: (0, 140, 200),    # Ocean Cyan
        2: (140, 50, 180),   # Deep Purple
        3: (200, 100, 0),    # Soft Amber
        4: (0, 180, 120)     # Muted Emerald
    }
    return colors.get(wall, (150, 150, 150))

def clear_room():
    global current_frame
    current_frame = bytearray(132)

def restore_ambient_light(active_wall):
    """Lumină de fundal discretă pentru a ghida jucătorii."""
    clear_room()
    c = get_ambient_color(active_wall)
    
    # Ochiul central este luminos
    set_led(active_wall, 0, c[0], c[1], c[2])
    
    # Tile-urile de pe perete sunt doar o umbră (luminozitate redusă la ~15%)
    dim_c = (c[0]//6, c[1]//6, c[2]//6)
    for l in range(1, 11):
        set_led(active_wall, l, *dim_c)

def play_tile(wall, led, duration=0.5, active_wall=None):
    color = get_ambient_color(wall)
    set_led(wall, led, *color)
    if led != 0: pygame.mixer.Channel(0).play(SOUND_BANK[(wall, led)])
    
    time.sleep(duration) # Un timp mai lung și calm
    
    if active_wall is not None: restore_ambient_light(active_wall)
    else: set_led(wall, led, 0, 0, 0)

def wait_for_input():
    global player_input
    player_input = None
    while player_input is None and running: time.sleep(0.01)
    return player_input

def set_status(text):
    global game_status_text
    game_status_text = text

# ==========================================
# 6. GAME LOGIC (RITM LENT ȘI ELEGANT)
# ==========================================
def run_demo():
    set_status("OBSERVE THE SEQUENCE")
    demo_seq = []
    time.sleep(1.0)
    
    for _ in range(3): # Demo mai scurt și mai lent
        if not running: return
        aw = random.randint(1, 4)
        restore_ambient_light(aw)
        time.sleep(1.0)
        
        for w, l in demo_seq:
            play_tile(w, l, 0.5, aw)
            time.sleep(0.3)
            
        nl = random.randint(1, 10)
        play_tile(aw, nl, 0.7, aw)
        demo_seq.append((aw, nl))
        time.sleep(0.6); clear_room(); time.sleep(0.5)

def main_game_logic():
    global player_input, game_score, game_time_left
    GAME_DURATION = 600
    
    pygame.mixer.Channel(1).play(BGM_TRACK, loops=-1)
    
    set_status("SYSTEM ONLINE")
    pygame.mixer.Channel(0).play(INTRO_SOUND)
    
    # Pulse lent la început
    for _ in range(2):
        for w in range(1, 5): set_led(w, 0, *get_ambient_color(w))
        time.sleep(0.6); clear_room(); time.sleep(0.4)
        
    run_demo()
    
    set_status("COMMENCING")
    time.sleep(1.5)
        
    game_start = time.time()
    
    while running:
        sequence = []
        game_score = 0
        
        while running:
            elapsed = int(time.time() - game_start)
            rem = GAME_DURATION - elapsed
            if rem <= 0:
                set_status("TIME EXPIRED")
                time.sleep(5)
                game_start = time.time()
                break 
            
            game_time_left = f"{rem//60:02d}:{rem%60:02d}"
            
            active_wall = random.randint(1, 4)
            set_status(f"FOCUS: WALL {active_wall}")
            restore_ambient_light(active_wall)
            time.sleep(1.5) # Mai mult timp să observe unde e Ochiul
            
            failed = False
            
            if len(sequence) > 0:
                set_status("RECALL SEQUENCE")
                for expected_wall, expected_led in sequence:
                    inp = wait_for_input()
                    if not running: return
                    pressed_w, pressed_l = inp
                    
                    if (pressed_w, pressed_l) == (expected_wall, expected_led):
                        play_tile(pressed_w, pressed_l, 0.4, active_wall)
                    else:
                        failed = True
                        break
                        
            if failed:
                set_status("INCORRECT")
                pygame.mixer.Channel(0).play(FAIL_SOUND)
                # Un roșu stins, nu blinding red
                for _ in range(2):
                    for w in range(1, 5):
                        for l in range(0, 11): set_led(w, l, 150, 0, 0)
                    time.sleep(0.3); clear_room(); time.sleep(0.2)
                time.sleep(1.5)
                break 
                
            set_status("ADD CONNECTION")
            new_note = None
            
            while running:
                inp = wait_for_input()
                if not running: return
                pressed_w, pressed_l = inp
                
                if pressed_w == active_wall:
                    new_note = (pressed_w, pressed_l)
                    play_tile(pressed_w, pressed_l, 0.6, active_wall)
                    pygame.mixer.Channel(0).play(SUCCESS_SOUND)
                    break
            
            sequence.append(new_note)
            game_score = len(sequence)
            clear_room()
            time.sleep(1.0)

def sender_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while running:
        if TARGET_IP: sock.sendto(MAGIC_HEADER + current_frame, (TARGET_IP, PORT_SEND))
        time.sleep(0.05)

def listener_loop():
    global player_input
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: sock.bind(("0.0.0.0", PORT_RECV))
    except: return
    while running:
        data, _ = sock.recvfrom(1024)
        if len(data) == 687 and data[0] == 0x88:
            for ch in range(1, 5):
                base = 2 + (ch - 1) * 171
                for led in range(1, 11):
                    if data[base + 1 + led] == 0xCC: player_input = (ch, led)

# ==========================================
# 7. GUI - SLEEK MODERN INTERFACE
# ==========================================
class EchoSequenceApp:
    def __init__(self, root):
        self.root = root
        self.root.title("System Control")
        self.root.geometry("450x300")
        
        # Tematica Slate/Dark Mode modernă
        self.bg_main = "#12141A" 
        self.text_dim = "#71798A"
        self.text_light = "#E8EAED"
        self.accent = "#00C3FF" # Cyan elegant
        
        self.root.configure(bg=self.bg_main)
        
        self.font_norm = font.Font(family="Helvetica", size=12)
        self.font_title = font.Font(family="Helvetica", size=18, weight="bold")
        
        self.score_win = tk.Toplevel(self.root)
        self.score_win.title("ECHO SEQUENCE")
        self.score_win.geometry("900x600")
        self.score_win.configure(bg=self.bg_main)
        self.fullscreen = False
        
        self.score_win.bind("<F11>", self.toggle_fs)
        self.score_win.bind("<Escape>", self.exit_fs)
        
        self.setup_admin()
        self.setup_dash()
        
        threading.Thread(target=self.auto_discover, daemon=True).start()
        self.update_ui()

    def toggle_fs(self, event=None):
        self.fullscreen = not self.fullscreen
        self.score_win.attributes("-fullscreen", self.fullscreen)

    def exit_fs(self, event=None):
        self.fullscreen = False
        self.score_win.attributes("-fullscreen", False)

    def auto_discover(self):
        self.lbl_disc.config(text="Locating Interface...", fg=self.text_dim)
        ip = run_discovery_flow()
        if ip:
            self.ip_entry.delete(0, tk.END)
            self.ip_entry.insert(0, ip)
            self.lbl_disc.config(text="Hardware Synchronized", fg=self.accent)
        else:
            self.ip_entry.delete(0, tk.END)
            self.ip_entry.insert(0, "127.0.0.1")
            self.lbl_disc.config(text="Simulator Mode", fg="#FFB347")

    def setup_admin(self):
        tk.Label(self.root, text="ECHO SEQUENCE", font=self.font_title, fg=self.text_light, bg=self.bg_main).pack(pady=(30, 5))
        self.lbl_disc = tk.Label(self.root, text="Initializing...", font=self.font_norm, fg=self.text_dim, bg=self.bg_main)
        self.lbl_disc.pack(pady=5)
        
        self.ip_entry = tk.Entry(self.root, font=self.font_norm, justify="center", bg="#1C1F26", fg=self.accent, insertbackground="white", bd=0)
        self.ip_entry.pack(pady=15, ipady=6, ipadx=10)
        
        self.btn_start = tk.Button(self.root, text="EXECUTE", font=self.font_norm, bg=self.accent, fg="#000000", command=self.start_game, relief="flat", cursor="hand2")
        self.btn_start.pack(pady=10, ipadx=30, ipady=6)

    def setup_dash(self):
        font_huge = font.Font(family="Helvetica", size=140, weight="bold")
        font_status = font.Font(family="Helvetica", size=24)
        
        top = tk.Frame(self.score_win, bg=self.bg_main)
        top.pack(fill="x", pady=30, padx=50)
        
        tk.Label(top, text="ECHO SEQUENCE", font=self.font_title, fg=self.text_dim, bg=self.bg_main).pack(side="left")
        self.lbl_time = tk.Label(top, text="10:00", font=self.font_title, fg=self.text_light, bg=self.bg_main)
        self.lbl_time.pack(side="right")
        
        mid = tk.Frame(self.score_win, bg=self.bg_main)
        mid.pack(expand=True, fill="both")
        
        tk.Label(mid, text="CURRENT CHAIN", font=self.font_norm, fg=self.text_dim, bg=self.bg_main).pack(pady=(40, 0))
        self.lbl_score = tk.Label(mid, text="0", font=font_huge, fg=self.accent, bg=self.bg_main)
        self.lbl_score.pack(pady=0)
        
        self.lbl_status = tk.Label(self.score_win, text=game_status_text, font=font_status, fg=self.text_light, bg=self.bg_main)
        self.lbl_status.pack(fill="x", side="bottom", pady=40)

    def start_game(self):
        global TARGET_IP, game_started
        TARGET_IP = self.ip_entry.get().strip()
        self.btn_start.config(text="RUNNING", state="disabled", bg="#1C1F26", fg=self.text_dim)
        
        if not game_started:
            game_started = True
            threading.Thread(target=sender_loop, daemon=True).start()
            threading.Thread(target=listener_loop, daemon=True).start()
            threading.Thread(target=main_game_logic, daemon=True).start()

    def update_ui(self):
        if running:
            # Aspect curat: format simplu pentru scor (01, 02)
            self.lbl_score.config(text=f"{game_score:02d}")
            self.lbl_time.config(text=game_time_left)
            self.lbl_status.config(text=game_status_text)
            
            # Culorile textului se adaptează minimalist
            if "INCORRECT" in game_status_text or "EXPIRED" in game_status_text:
                self.lbl_status.config(fg="#FF5555")
            elif "ADD" in game_status_text:
                self.lbl_status.config(fg=self.accent)
            else:
                self.lbl_status.config(fg=self.text_light)
                
            self.root.after(100, self.update_ui)

if __name__ == "__main__":
    root = tk.Tk()
    app = EchoSequenceApp(root)
    
    def on_closing():
        global running
        running = False
        clear_room()
        pygame.mixer.quit()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(MAGIC_HEADER + current_frame, (TARGET_IP, PORT_SEND))
        except: pass
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()