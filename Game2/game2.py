import sys
import subprocess
import socket
import time
import threading
import random
import os
import colorsys

# --- AUTO-INSTALL PYGAME ---
def verifica_si_instaleaza(pachet):
    try:
        __import__(pachet)
    except ImportError:
        print(f"📦 Pachetul '{pachet}' nu este instalat. Îl instalez acum...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pachet])
        print(f"✅ Pachetul '{pachet}' a fost instalat cu succes!")

verifica_si_instaleaza('pygame')
import pygame

# --- FIX AUDIO WSL ---
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
os.environ['SDL_AUDIODRIVER'] = 'pulseaudio'

PYGAME_AVAILABLE = True

# --- CONFIGURARE REȚEA ---
UDP_SEND_IP = "127.0.0.1" 
UDP_SEND_PORT_MAIN = 4226    
UDP_SEND_PORT_SCORE = 4227   
UDP_LISTEN_PORT = 4444

NUM_CHANNELS = 8
LEDS_PER_CHANNEL = 64
FRAME_DATA_LENGTH = NUM_CHANNELS * LEDS_PER_CHANNEL * 3

BOARD_WIDTH = 16
BOARD_HEIGHT = 32 

RED = (255, 0, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)

# --- PLAYLIST & BPM ---
SONG_DATA = {
    "songs/saxobeat.mp3": {"bpm": 127, "name": "Mr. Saxobeat"},
    "songs/dont_stop.mp3": {"bpm": 123, "name": "Don't Stop The Music"},
    "songs/s_and_m.mp3": {"bpm": 128, "name": "S&M"},
    "songs/everything.mp3": {"bpm": 129, "name": "Give Me Everything"},
    "songs/promiscuous.mp3": {"bpm": 114, "name": "Promiscuous"}
}

BEAT_SCALER = 0.5 

# --- MINI FONT 3x5 ---
MINI_FONT = {
    '0': [[1,1,1],[1,0,1],[1,0,1],[1,0,1],[1,1,1]],
    '1': [[0,1,0],[1,1,0],[0,1,0],[0,1,0],[1,1,1]],
    '2': [[1,1,1],[0,0,1],[1,1,1],[1,0,0],[1,1,1]],
    '3': [[1,1,1],[0,0,1],[1,1,1],[0,0,1],[1,1,1]],
    '4': [[1,0,1],[1,0,1],[1,1,1],[0,0,1],[0,0,1]],
    '5': [[1,1,1],[1,0,0],[1,1,1],[0,0,1],[1,1,1]],
    '6': [[1,1,1],[1,0,0],[1,1,1],[1,0,1],[1,1,1]],
    '7': [[1,1,1],[0,0,1],[0,0,1],[0,0,1],[0,0,1]],
    '8': [[1,1,1],[1,0,1],[1,1,1],[1,0,1],[1,1,1]],
    '9': [[1,1,1],[1,0,1],[1,1,1],[0,0,1],[1,1,1]],
    'P': [[1,1,1],[1,0,1],[1,1,1],[1,0,0],[1,0,0]],
    'G': [[1,1,1],[1,0,0],[1,0,1],[1,0,1],[1,1,1]],
    'O': [[1,1,1],[1,0,1],[1,0,1],[1,0,1],[1,1,1]],
    'E': [[1,1,1],[1,0,0],[1,1,1],[1,0,0],[1,1,1]],
    'N': [[1,0,1],[1,1,1],[1,1,1],[1,0,1],[1,0,1]], 
    'X': [[1,0,1],[1,0,1],[0,1,0],[1,0,1],[1,0,1]],
    'T': [[1,1,1],[0,1,0],[0,1,0],[0,1,0],[0,1,0]],
    'D': [[1,1,0],[1,0,1],[1,0,1],[1,0,1],[1,1,0]],
    ':': [[0,0,0],[0,1,0],[0,0,0],[0,1,0],[0,0,0]]
}

class SyncNote:
    def __init__(self, relative_y_positions, lane_starts, color):
        self.x = 0.0
        self.rel_y = relative_y_positions
        self.lane_starts = lane_starts 
        self.color = color
        self.active_map = [[True for _ in range(len(relative_y_positions))] for _ in range(6)]

    def move(self, speed):
        self.x += speed

class PianoTilesTzancaEdition:
    def __init__(self, initial_song=None):
        self.running = True
        self.lock = threading.RLock()
        self.scores = [0] * 6
        
        self.state = "START_ANIM" 
        self.state_start_time = time.time()
        
        self.horizontal_lines = [0, 5, 10, 15, 16, 21, 26, 31]
        self.lane_starts = [1, 6, 11, 17, 22, 27]
        
        self.notes = []
        self.current_song_start_time = 0 
        self.spawn_timer = time.time()
        self.last_tick = time.time()
        
        self.last_y_pos = [1] 
        self.button_states = [False] * 512
        self.prev_button_states = [False] * 512
        
        self.current_song_name = "Pregătire..."
        self.chosen_song_path = None
        self.current_spawn_interval = 0.8 
        
        # Salvăm alegerea utilizatorului
        self.initial_song_choice = initial_song

        try:
            pygame.mixer.quit()
            pygame.mixer.pre_init(44100, -16, 2, 512)
            pygame.mixer.init()
        except Exception as e: 
            print(f"⚠ Eroare audio: {e}")

    def start_music(self):
        self.current_song_start_time = time.time()
        available_songs = [s for s in SONG_DATA.keys() if os.path.exists(s)]
        
        if available_songs:
            # Dacă utilizatorul a ales o melodie la început și există
            if self.initial_song_choice and self.initial_song_choice in available_songs:
                self.chosen_song_path = self.initial_song_choice
                self.initial_song_choice = None # O resetăm, astfel încât următoarea piesă să fie random
            else:
                choices = [s for s in available_songs if s != self.chosen_song_path]
                if not choices: choices = available_songs
                self.chosen_song_path = random.choice(choices)
                
            song_info = SONG_DATA[self.chosen_song_path]
            self.current_song_name = song_info["name"]
            
            beats_per_second = (song_info["bpm"] / 60.0) * BEAT_SCALER
            self.current_spawn_interval = 1.0 / beats_per_second

            pygame.mixer.music.load(self.chosen_song_path)
            pygame.mixer.music.play(0) 
        else:
            self.current_song_name = "Lipsă Folder/Melodii"
            self.current_spawn_interval = 0.8

    def tick(self):
        with self.lock:
            now = time.time()
            dt = now - self.last_tick
            self.last_tick = now

            if self.state == "START_ANIM":
                elapsed_anim = now - self.state_start_time
                if elapsed_anim >= 4.0: 
                    self.state = "PLAYING"
                    self.start_music()
                return

            if self.state == "TRANSITION_ANIM":
                elapsed_anim = now - self.state_start_time
                if elapsed_anim >= 3.0: 
                    self.state = "PLAYING"
                    self.start_music()
                return

            if self.state == "PLAYING":
                song_elapsed = now - self.current_song_start_time
                song_ended = False
                
                if self.chosen_song_path:
                    if song_elapsed > 2.0 and not pygame.mixer.music.get_busy():
                        song_ended = True
                else:
                    if song_elapsed > 30.0: song_ended = True

                if song_ended:
                    self.state = "TRANSITION_ANIM"
                    self.state_start_time = now
                    self.notes.clear()
                    return

                speed = 4.0 + (song_elapsed * 0.03) 

                if now - self.spawn_timer > self.current_spawn_interval:
                    num_notes = random.randint(1, 2)
                    new_rel_y = []
                    for _ in range(num_notes):
                        offset = random.choice([-1, 0, 1])
                        target_y = max(0, min(3, self.last_y_pos[0] + offset))
                        if target_y not in new_rel_y: new_rel_y.append(target_y)
                    
                    self.last_y_pos = new_rel_y
                    color = (random.randint(100, 255), random.randint(100, 255), random.randint(100, 255))
                    self.notes.append(SyncNote(new_rel_y, self.lane_starts, color))
                    self.spawn_timer = now

                for note in self.notes[:]:
                    note.move(speed * dt)
                    if note.x >= BOARD_WIDTH:
                        self.notes.remove(note)

                for i in range(512):
                    if self.button_states[i] and not self.prev_button_states[i]:
                        self.handle_click(i)
                    self.prev_button_states[i] = self.button_states[i]

    def handle_click(self, led_idx):
        if self.state != "PLAYING": return
        channel = led_idx // 64
        idx_in_ch = led_idx % 64
        row_in_ch = idx_in_ch // 16
        col_raw = idx_in_ch % 16
        x_click = col_raw if row_in_ch % 2 == 0 else 15 - col_raw
        y_click = (channel * 4) + row_in_ch

        player_idx = -1
        for i, start_y in enumerate(self.lane_starts):
            if start_y <= y_click <= start_y + 3:
                player_idx = i
                break
        if player_idx == -1: return

        hit = False
        for note in self.notes:
            rel_click_y = y_click - self.lane_starts[player_idx]
            if rel_click_y in note.rel_y:
                pix_idx = note.rel_y.index(rel_click_y)
                if note.active_map[player_idx][pix_idx]:
                    if abs(x_click - note.x) <= 1.8:
                        self.scores[player_idx] += 3
                        note.active_map[player_idx][pix_idx] = False
                        hit = True
                        break
        
        if not hit and not (y_click in self.horizontal_lines):
            self.scores[player_idx] = max(0, self.scores[player_idx] - 2)

    def display_status(self):
        if self.state == "PLAYING" or self.state == "TRANSITION_ANIM":
            song_elapsed = time.time() - self.current_song_start_time
            score_str = " ".join([f"P{i+1}:{self.scores[i]}" for i in range(6)])
            nume = self.current_song_name[:10] + ".." if len(self.current_song_name) > 10 else self.current_song_name
            st_text = "[Schimbare]" if self.state == "TRANSITION_ANIM" else f"[{nume}]"
            
            out_str = f"\r{st_text} {int(song_elapsed//60):02d}:{int(song_elapsed%60):02d} | {score_str}"
            
            if not hasattr(self, 'last_out_str') or self.last_out_str != out_str:
                sys.stdout.write(out_str.ljust(75))
                sys.stdout.flush()
                self.last_out_str = out_str

    def draw_text(self, buffer, text, start_x, start_y, color=WHITE):
        x_offset = start_x
        for char in text:
            if char in MINI_FONT:
                char_matrix = MINI_FONT[char]
                for r_idx, row in enumerate(char_matrix):
                    for c_idx, val in enumerate(row):
                        if val == 1:
                            self.set_led(buffer, x_offset + c_idx, start_y + r_idx, color)
                x_offset += 4

    def render_rainbow_bg(self, buffer, time_factor):
        for y in range(BOARD_HEIGHT):
            for x in range(BOARD_WIDTH):
                hue = (time_factor * 1.5 + (x / 16.0) + (y / 32.0)) % 1.0
                rgb = colorsys.hsv_to_rgb(hue, 1.0, 0.8) 
                color = (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
                self.set_led(buffer, x, y, color)

    def render(self):
        buffer = bytearray(FRAME_DATA_LENGTH)
        with self.lock:
            now = time.time()
            
            if self.state == "START_ANIM":
                elapsed = now - self.state_start_time
                self.render_rainbow_bg(buffer, now)
                
                if elapsed < 1.0: self.draw_text(buffer, "3", 6, 13)
                elif elapsed < 2.0: self.draw_text(buffer, "2", 6, 13)
                elif elapsed < 3.0: self.draw_text(buffer, "1", 6, 13)
                else: self.draw_text(buffer, "GO", 4, 13)
                return buffer

            if self.state == "TRANSITION_ANIM":
                self.render_rainbow_bg(buffer, now * 3.0)
                self.draw_text(buffer, "NEXT", 1, 13, BLACK) 
                return buffer

            color_grid = RED
            for y in range(BOARD_HEIGHT):
                if y in self.horizontal_lines:
                    for x in range(BOARD_WIDTH):
                        self.set_led(buffer, x, y, color_grid)
            
            for note in self.notes:
                tx = int(note.x)
                if 0 <= tx < 16:
                    for p in range(6):
                        for pix_idx, ry in enumerate(note.rel_y):
                            if note.active_map[p][pix_idx]:
                                y_final = self.lane_starts[p] + ry
                                self.set_led(buffer, tx, y_final, note.color)
        return buffer

    def render_scores_screen(self):
        buffer = bytearray(FRAME_DATA_LENGTH)
        with self.lock:
            colors = [WHITE, GREEN, BLUE, WHITE, GREEN, BLUE]
            y_offset = 1
            for i in range(6):
                score_txt = f"P{i+1}:{self.scores[i]}"
                self.draw_text(buffer, score_txt, 1, y_offset, colors[i])
                y_offset += 5 
        return buffer

    def set_led(self, buffer, x, y, color):
        if x < 0 or x >= BOARD_WIDTH or y < 0 or y >= BOARD_HEIGHT: return
        channel = y // 4
        row_in_ch = y % 4
        led_idx = row_in_ch * 16 + x if row_in_ch % 2 == 0 else row_in_ch * 16 + (15 - x)
        offset = led_idx * (NUM_CHANNELS * 3) + channel
        if offset + NUM_CHANNELS*2 < len(buffer):
            buffer[offset] = color[1]
            buffer[offset + NUM_CHANNELS] = color[0]
            buffer[offset + NUM_CHANNELS*2] = color[2]

class NetworkManager:
    def __init__(self, game):
        self.game = game
        self.sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sequence = 0
        try:
            self.sock_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock_recv.bind(("0.0.0.0", UDP_LISTEN_PORT))
        except: pass

    def send_packet(self, frame_data, target_port):
        self.sequence = (self.sequence + 1) & 0xFFFF
        target = (UDP_SEND_IP, target_port)
        self.sock_send.sendto(bytearray([0x75, 0x01, 0x02, 0x00, 0x08, 0x02, 0x00, 0x00, 0x33, 0x44, (self.sequence >> 8) & 0xFF, self.sequence & 0xFF, 0x00, 0x00, 0x00, 0x0E, 0x00]), target)
        fff0 = bytearray([0x75, 0x03, 0x04, 0x00, 0x19, 0x02, 0x00, 0x00, 0x88, 0x77, 0xFF, 0xF0, 0x00, 0x10]) + (bytearray([0x00, 0x40]) * 8) + bytearray([0x1E, 0x00])
        self.sock_send.sendto(fff0, target)
        chunk_size = 984
        for i in range(0, len(frame_data), chunk_size):
            chunk = frame_data[i:i+chunk_size]
            internal = bytearray([0x02, 0x00, 0x00, 0x88, 0x77, 0x00, (i//chunk_size)+1, (len(chunk) >> 8) & 0xFF, (len(chunk) & 0xFF)]) + chunk
            p = bytearray([0x75, 0x05, 0x06, ((len(internal)-1) >> 8) & 0xFF, (len(internal)-1) & 0xFF]) + internal + bytearray([0x1E if len(chunk) == 984 else 0x36, 0x00])
            self.sock_send.sendto(p, target)
        self.sock_send.sendto(bytearray([0x75, 0x07, 0x08, 0x00, 0x08, 0x02, 0x00, 0x00, 0x55, 0x66, (self.sequence >> 8) & 0xFF, self.sequence & 0xFF, 0x00, 0x00, 0x00, 0x0E, 0x00]), target)

    def recv_loop(self):
        while True:
            try:
                data, _ = self.sock_recv.recvfrom(2048)
                if len(data) >= 1373 and data[0] == 0x88:
                    for c in range(8):
                        offset = 2 + (c * 171) + 1 
                        ch_data = data[offset : offset + 64]
                        for i, val in enumerate(ch_data):
                            self.game.button_states[(c * 64) + i] = (val == 0xCC)
            except: pass

    def run(self):
        threading.Thread(target=self.recv_loop, daemon=True).start()
        print("\n▶ Jocul a început! Animația de start rulează pe panou.")
        while True:
            self.game.tick()
            
            game_frame = self.game.render()
            self.send_packet(game_frame, UDP_SEND_PORT_MAIN)
            
            scores_frame = self.game.render_scores_screen()
            self.send_packet(scores_frame, UDP_SEND_PORT_SCORE)
            
            self.game.display_status()
            time.sleep(0.04)

# --- MENIU DE START ---
def select_song_menu():
    available_songs = list(SONG_DATA.keys())
    if not available_songs:
        print("⚠ Eroare: Nu s-au găsit melodii configurate!")
        return None

    print("\n" + "="*40)
    print(" 🎹 PIANO TILES - SELECTEAZĂ MELODIA 🎹")
    print("="*40)
    
    for i, path in enumerate(available_songs):
        print(f" {i + 1}. {SONG_DATA[path]['name']}")
    
    random_opt_idx = len(available_songs) + 1
    print(f" {random_opt_idx}. Alege Aleatoriu (Surprinde-mă)")
    print("="*40)

    while True:
        try:
            alegere = int(input(f"Alege un număr (1-{random_opt_idx}): "))
            if 1 <= alegere <= len(available_songs):
                return available_songs[alegere - 1]
            elif alegere == random_opt_idx:
                return None # Returnăm None pentru random
            else:
                print(f"❌ Te rog să introduci un număr valid între 1 și {random_opt_idx}.")
        except ValueError:
            print("❌ Te rog să introduci doar cifre.")

if __name__ == "__main__":
    # 1. Apelăm meniul chiar înainte să inițializăm jocul
    melodie_aleasa = select_song_menu()
    
    # 2. Trimitem opțiunea mai departe către logica jocului
    game = PianoTilesTzancaEdition(initial_song=melodie_aleasa)
    net = NetworkManager(game)
    net.run()