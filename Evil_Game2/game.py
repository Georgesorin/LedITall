import os
import sys
import subprocess
import socket
import threading
import time
import random
import tkinter as tk
from tkinter import font

# ==============================================================================
# 1. THE TOOLBOX CHECKER (Auto-Installer)
# Imagine we need magic paint (numpy) and a music player (pygame).
# If the computer doesn't have them, this little robot runs to the store 
# and downloads them for us automatically before the game starts!
# ==============================================================================
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

# ==============================================================================
# 2. THE MAGICAL MUSIC MAKER (Audio Generator)
# Instead of using annoying, loud computer beeps, we use math (numpy) to draw 
# smooth sound waves. It makes the buttons sound like gentle glass bells! 🛎️
# ==============================================================================
pygame.mixer.init(frequency=44100, size=-16, channels=2)

def generate_ethereal_tone(freq, duration=0.8):
    """Draws a smooth, floating sound wave (like tapping a crystal glass)."""
    sample_rate = 44100
    n_samples = int(sample_rate * duration)
    t = np.linspace(0, duration, n_samples, False)
    
    # A pure, smooth wave that is very gentle on the ears
    wave = 0.5 * np.sin(2 * np.pi * freq * t)
    
    # Fade-in and Fade-out (so the sound doesn't "click" or hurt your ears)
    attack_len = int(sample_rate * 0.05)
    release_len = int(sample_rate * 0.3)
    
    envelope = np.ones(n_samples)
    if attack_len > 0: envelope[:attack_len] = np.linspace(0, 1, attack_len)
    if release_len > 0: envelope[-release_len:] = np.linspace(1, 0, release_len)
    
    wave = wave * envelope
    audio_data = (wave * 32767).astype(np.int16)
    return pygame.mixer.Sound(buffer=audio_data)

def generate_atmospheric_bgm():
    """Background Music: A slow, mysterious hum that makes the room feel magical."""
    sample_rate = 44100
    duration = 12.0
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    
    # A slow, floating chord
    wave = 0.15 * np.sin(2 * np.pi * 146.83 * t) + 0.15 * np.sin(2 * np.pi * 164.81 * t)
    wave *= (0.6 + 0.4 * np.sin(2 * np.pi * 0.08 * t)) # Pulses super slowly, like breathing
    
    audio_data = (wave * 32767).astype(np.int16)
    return pygame.mixer.Sound(buffer=audio_data)

# We make a list of musical notes (like piano keys)
FREQS = [146.83, 164.81, 174.61, 196.00, 220.00, 246.94, 261.63, 293.66, 329.63, 349.23]
SOUND_BANK = {}

# Give every button on every wall its own special crystal bell sound!
for w in range(1, 5):
    for l in range(1, 11):
        f = FREQS[l-1]
        # Each wall sounds slightly different (pitch shifts)
        if w == 2: f *= 1.2 
        if w == 3: f *= 0.8
        if w == 4: f *= 1.1
        SOUND_BANK[(w, l)] = generate_ethereal_tone(f)

# Special Game Sounds
INTRO_SOUND = generate_ethereal_tone(293.66, duration=1.5) # Game is starting
FAIL_SOUND = generate_ethereal_tone(98.00, duration=1.2)   # A deep, sad tone for making a mistake
SUCCESS_SOUND = generate_ethereal_tone(440.00, duration=1.0) # A happy ding for getting it right
BGM_TRACK = generate_atmospheric_bgm()

# ==============================================================================
# 3. NETWORK & MEMORY (The Walkie-Talkies and the Notebook)
# ==============================================================================
PORT_SEND = 4626 # Channel to yell to the LED walls
PORT_RECV = 7800 # Channel to listen for button presses
# The secret envelope we wrap our messages in so the LED walls understand us
MAGIC_HEADER = bytearray([0x75, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x88, 0x77, 0x00, 0x00, 0x00, 0x00])

TARGET_IP = "127.0.0.1"
current_frame = bytearray(132) # The blank canvas where we paint the LED colors
player_input = None
running = True
game_started = False

game_score = 0
game_status_text = "AWAITING INITIALIZATION"
game_time_left = "10:00"

# ==============================================================================
# 4. THE RADAR ROBOT (Discovery Flow)
# This robot shouts "Where is the light room?!" into the Wi-Fi 
# and waits for the room to shout back its IP Address.
# ==============================================================================
def get_local_interfaces():
    """Finds our own computer's Wi-Fi address."""
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
    
    # The 'HELLO!' message
    payload = bytearray([0x0A, 0x02, *b"KX-HC04", 0x03, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x14])
    rand1, rand2 = random.randint(0, 127), random.randint(0, 127)
    pkt = bytearray([0x67, rand1, rand2, len(payload)]) + payload
    pkt.append(sum(pkt) & 0xFF)
    
    try: sock.sendto(pkt, (bcast, 4626))
    except: return None
    
    # Wait 2 seconds for a reply
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

# ==============================================================================
# 5. THE PAINTER (Camera Visuals & Elegant Colors)
# This controls the lights. We use deep, calming colors so that playing 
# in a dark room doesn't hurt anyone's eyes.
# ==============================================================================
def set_led(wall, led_idx, r, g, b):
    """Puts a specific color (Red, Green, Blue) on one specific button."""
    global current_frame
    if not (1 <= wall <= 4 and 0 <= led_idx <= 10): return
    idx = wall - 1
    # Hardware expects GRB instead of RGB!
    current_frame[led_idx * 12 + idx] = g
    current_frame[led_idx * 12 + 4 + idx] = r
    current_frame[led_idx * 12 + 8 + idx] = b

def get_ambient_color(wall):
    """Deep, calm colors for each wall. (No blinding lasers!)"""
    colors = {
        1: (0, 140, 200),    # Ocean Cyan
        2: (140, 50, 180),   # Deep Purple
        3: (200, 100, 0),    # Soft Amber
        4: (0, 180, 120)     # Muted Emerald
    }
    return colors.get(wall, (150, 150, 150))

def clear_room():
    """Turns off all the lights (wipes the canvas clean)."""
    global current_frame
    current_frame = bytearray(132)

def restore_ambient_light(active_wall):
    """A gentle night-light mode. The active wall glows softly so you know where to look."""
    clear_room()
    c = get_ambient_color(active_wall)
    
    # The big center "Eye" is bright
    set_led(active_wall, 0, c[0], c[1], c[2])
    
    # The small buttons are very dim (only ~15% brightness) so they look like shadows
    dim_c = (c[0]//6, c[1]//6, c[2]//6)
    for l in range(1, 11):
        set_led(active_wall, l, *dim_c)

def play_tile(wall, led, duration=0.5, active_wall=None):
    """Flashes a button bright and plays its crystal bell sound."""
    color = get_ambient_color(wall)
    set_led(wall, led, *color)
    if led != 0: pygame.mixer.Channel(0).play(SOUND_BANK[(wall, led)])
    
    time.sleep(duration) # Keep it glowing for a moment
    
    # Return to the dim night-light mode
    if active_wall is not None: restore_ambient_light(active_wall)
    else: set_led(wall, led, 0, 0, 0)

def wait_for_input():
    """The game freezes and waits patiently until a human presses a button."""
    global player_input
    player_input = None
    while player_input is None and running: time.sleep(0.01)
    return player_input

def set_status(text):
    """Changes the text on the computer screen so the DJ knows what's happening."""
    global game_status_text
    game_status_text = text

# ==============================================================================
# 6. THE GAME BRAIN (Simon Says Logic)
# This is the master of the game. It creates the song sequence and checks 
# if you press the right buttons in the exact right order.
# ==============================================================================
def run_demo():
    """Before the game starts, the room shows a quick light show so you know it's working."""
    set_status("OBSERVE THE SEQUENCE")
    demo_seq = []
    time.sleep(1.0)
    
    for _ in range(3): # Show 3 random buttons lighting up
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
    """The real game loop!"""
    global player_input, game_score, game_time_left
    GAME_DURATION = 600 # You have 10 minutes to survive!
    
    # Start the creepy/magical background hum
    pygame.mixer.Channel(1).play(BGM_TRACK, loops=-1)
    
    set_status("SYSTEM ONLINE")
    pygame.mixer.Channel(0).play(INTRO_SOUND)
    
    # Slowly pulse the room twice to say "Get ready"
    for _ in range(2):
        for w in range(1, 5): set_led(w, 0, *get_ambient_color(w))
        time.sleep(0.6); clear_room(); time.sleep(0.4)
        
    run_demo()
    
    set_status("COMMENCING")
    time.sleep(1.5)
        
    game_start = time.time()
    
    # This big loop keeps starting new games forever until you close the app
    while running:
        sequence = [] # The empty song. We add one note to it every round!
        game_score = 0
        
        while running:
            # Check the big timer
            elapsed = int(time.time() - game_start)
            rem = GAME_DURATION - elapsed
            if rem <= 0:
                set_status("TIME EXPIRED")
                time.sleep(5)
                game_start = time.time()
                break # Game Over! Time ran out.
            
            game_time_left = f"{rem//60:02d}:{rem%60:02d}"
            
            # The room picks a random wall to be the "Active" wall
            active_wall = random.randint(1, 4)
            set_status(f"FOCUS: WALL {active_wall}")
            restore_ambient_light(active_wall)
            time.sleep(1.5) # Give players time to turn around and look at the wall
            
            failed = False
            
            # Phase 1: RECALL (You have to repeat everything from memory first)
            if len(sequence) > 0:
                set_status("RECALL SEQUENCE")
                for expected_wall, expected_led in sequence:
                    inp = wait_for_input() # Wait for player to press something
                    if not running: return
                    pressed_w, pressed_l = inp
                    
                    # Did they press the exact right button?
                    if (pressed_w, pressed_l) == (expected_wall, expected_led):
                        play_tile(pressed_w, pressed_l, 0.4, active_wall)
                    else:
                        # Oh no! Wrong button!
                        failed = True
                        break
                        
            if failed:
                # PLAY SAD SOUND AND FLASH RED 
                set_status("INCORRECT")
                pygame.mixer.Channel(0).play(FAIL_SOUND)
                # A dim, spooky red (not blinding bright)
                for _ in range(2):
                    for w in range(1, 5):
                        for l in range(0, 11): set_led(w, l, 150, 0, 0)
                    time.sleep(0.3); clear_room(); time.sleep(0.2)
                time.sleep(1.5)
                break # Break out of the round, they lost! Start a new sequence.
                
            # Phase 2: ADD NEW NOTE
            # If they got everything right, the room adds ONE NEW BUTTON to the song
            set_status("ADD CONNECTION")
            new_note = None
            
            while running:
                inp = wait_for_input()
                if not running: return
                pressed_w, pressed_l = inp
                
                # They can choose any button on the current active wall to add to the song
                if pressed_w == active_wall:
                    new_note = (pressed_w, pressed_l)
                    play_tile(pressed_w, pressed_l, 0.6, active_wall)
                    pygame.mixer.Channel(0).play(SUCCESS_SOUND) # Happy ding!
                    break
            
            # Save the new note and increase the score
            sequence.append(new_note)
            game_score = len(sequence)
            clear_room()
            time.sleep(1.0)

# The robot that throws the LED canvas to the walls via Wi-Fi
def sender_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while running:
        if TARGET_IP: sock.sendto(MAGIC_HEADER + current_frame, (TARGET_IP, PORT_SEND))
        time.sleep(0.05)

# The robot that listens to the Wi-Fi for button presses
def listener_loop():
    global player_input
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: sock.bind(("0.0.0.0", PORT_RECV))
    except: return
    while running:
        data, _ = sock.recvfrom(1024)
        if len(data) == 687 and data[0] == 0x88: # Correct message size
            for ch in range(1, 5):
                base = 2 + (ch - 1) * 171
                for led in range(1, 11):
                    # 0xCC means the button is being pressed down right now!
                    if data[base + 1 + led] == 0xCC: player_input = (ch, led)

# ==============================================================================
# 7. THE COMPUTER SCREENS (GUI)
# This builds the sleek, dark-mode windows you see on your laptop.
# ==============================================================================
class EchoSequenceApp:
    def __init__(self, root):
        self.root = root
        self.root.title("System Control")
        self.root.geometry("450x300")
        
        # Slate/Dark Mode color palette (Very hacker-movie style)
        self.bg_main = "#12141A" 
        self.text_dim = "#71798A"
        self.text_light = "#E8EAED"
        self.accent = "#00C3FF" # Elegant glowing Cyan
        
        self.root.configure(bg=self.bg_main)
        
        self.font_norm = font.Font(family="Helvetica", size=12)
        self.font_title = font.Font(family="Helvetica", size=18, weight="bold")
        
        # This is the giant second window that the audience looks at
        self.score_win = tk.Toplevel(self.root)
        self.score_win.title("ECHO SEQUENCE")
        self.score_win.geometry("900x600")
        self.score_win.configure(bg=self.bg_main)
        self.fullscreen = False
        
        # Press F11 to make the giant window full screen!
        self.score_win.bind("<F11>", self.toggle_fs)
        self.score_win.bind("<Escape>", self.exit_fs)
        
        self.setup_admin()
        self.setup_dash()
        
        # Send out the Radar robot in the background
        threading.Thread(target=self.auto_discover, daemon=True).start()
        self.update_ui()

    def toggle_fs(self, event=None):
        self.fullscreen = not self.fullscreen
        self.score_win.attributes("-fullscreen", self.fullscreen)

    def exit_fs(self, event=None):
        self.fullscreen = False
        self.score_win.attributes("-fullscreen", False)

    def auto_discover(self):
        """Tells the UI what the Radar robot found."""
        self.lbl_disc.config(text="Locating Interface...", fg=self.text_dim)
        ip = run_discovery_flow()
        if ip:
            self.ip_entry.delete(0, tk.END)
            self.ip_entry.insert(0, ip)
            self.lbl_disc.config(text="Hardware Synchronized", fg=self.accent)
        else:
            self.ip_entry.delete(0, tk.END)
            self.ip_entry.insert(0, "127.0.0.1")
            self.lbl_disc.config(text="Simulator Mode", fg="#FFB347") # Orange warning

    def setup_admin(self):
        """Builds the DJ's small control panel."""
        tk.Label(self.root, text="ECHO SEQUENCE", font=self.font_title, fg=self.text_light, bg=self.bg_main).pack(pady=(30, 5))
        self.lbl_disc = tk.Label(self.root, text="Initializing...", font=self.font_norm, fg=self.text_dim, bg=self.bg_main)
        self.lbl_disc.pack(pady=5)
        
        self.ip_entry = tk.Entry(self.root, font=self.font_norm, justify="center", bg="#1C1F26", fg=self.accent, insertbackground="white", bd=0)
        self.ip_entry.pack(pady=15, ipady=6, ipadx=10)
        
        self.btn_start = tk.Button(self.root, text="EXECUTE", font=self.font_norm, bg=self.accent, fg="#000000", command=self.start_game, relief="flat", cursor="hand2")
        self.btn_start.pack(pady=10, ipadx=30, ipady=6)

    def setup_dash(self):
        """Builds the giant audience screen (Score and Timer)."""
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
        """When you click EXECUTE, wake up all the robots!"""
        global TARGET_IP, game_started
        TARGET_IP = self.ip_entry.get().strip()
        self.btn_start.config(text="RUNNING", state="disabled", bg="#1C1F26", fg=self.text_dim)
        
        if not game_started:
            game_started = True
            threading.Thread(target=sender_loop, daemon=True).start()
            threading.Thread(target=listener_loop, daemon=True).start()
            threading.Thread(target=main_game_logic, daemon=True).start()

    def update_ui(self):
        """Constantly updates the text on the screens so the audience knows what's happening."""
        if running:
            # Clean format for score (e.g., "01", "02", "09")
            self.lbl_score.config(text=f"{game_score:02d}")
            self.lbl_time.config(text=game_time_left)
            self.lbl_status.config(text=game_status_text)
            
            # The text changes color depending on the mood of the game
            if "INCORRECT" in game_status_text or "EXPIRED" in game_status_text:
                self.lbl_status.config(fg="#FF5555") # Turn Red on fail
            elif "ADD" in game_status_text:
                self.lbl_status.config(fg=self.accent) # Turn glowing cyan when adding a note
            else:
                self.lbl_status.config(fg=self.text_light) # Normal white text
                
            self.root.after(100, self.update_ui)

# ==============================================================================
# When you double click the file, this part wakes up the app!
# ==============================================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = EchoSequenceApp(root)
    
    def on_closing():
        """When you click the 'X', this ensures everything shuts down safely and the lights turn off."""
        global running
        running = False
        clear_room()
        pygame.mixer.quit()
        try:
            # Send one last blank canvas to the walls to turn them off
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(MAGIC_HEADER + current_frame, (TARGET_IP, PORT_SEND))
        except: pass
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()