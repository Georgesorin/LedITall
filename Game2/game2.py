import socket
import time
import threading
import random
import sys
import os
import colorsys

# --- FIX AUDIO WSL ---
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
os.environ['SDL_AUDIODRIVER'] = 'pulseaudio'

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("Eroare: Pygame nu este instalat. Muzica nu va rula.")

# --- CONFIGURARE REȚEA ---
UDP_SEND_IP = "127.0.0.1" 
UDP_SEND_PORT = 4226
UDP_LISTEN_PORT = 4444

NUM_CHANNELS = 8
LEDS_PER_CHANNEL = 64
FRAME_DATA_LENGTH = NUM_CHANNELS * LEDS_PER_CHANNEL * 3

BOARD_WIDTH = 16
BOARD_HEIGHT = 32 

RED = (255, 0, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

# --- CONFIGURARE JOC ---
GAME_DURATION = 180 # Timpul total al unei sesiuni de joc

# --- PLAYLIST ---
SONG_LIST = [
    "songs/dont_stop.mp3",
    "songs/everything.mp3",
    "songs/promiscuous.mp3",
    "songs/s_and_m.mp3",
    "songs/saxobeat.mp3"
]

# --- MINI FONT 3x5 ---
MINI_FONT = {
    '3': [[1,1,1],[0,0,1],[1,1,1],[0,0,1],[1,1,1]],
    '2': [[1,1,1],[0,0,1],[1,1,1],[1,0,0],[1,1,1]],
    '1': [[0,1,0],[1,1,0],[0,1,0],[0,1,0],[1,1,1]],
    'G': [[1,1,1],[1,0,0],[1,0,1],[1,0,1],[1,1,1]],
    'O': [[1,1,1],[1,0,1],[1,0,1],[1,0,1],[1,1,1]],
    'E': [[1,1,1],[1,0,0],[1,1,1],[1,0,0],[1,1,1]],
    'N': [[1,0,1],[1,1,1],[1,1,1],[1,0,1],[1,0,1]], 
    'X': [[1,0,1],[1,0,1],[0,1,0],[1,0,1],[1,0,1]],
    'T': [[1,1,1],[0,1,0],[0,1,0],[0,1,0],[0,1,0]],
    'D': [[1,1,0],[1,0,1],[1,0,1],[1,0,1],[1,1,0]]
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
    def __init__(self):
        self.running = True
        self.lock = threading.RLock()
        self.scores = [0] * 6
        
        # Stările jocului: START_ANIM -> PLAYING <-> TRANSITION_ANIM -> END_ANIM
        self.state = "START_ANIM" 
        self.state_start_time = time.time()
        
        self.horizontal_lines = [0, 5, 10, 15, 16, 21, 26, 31]
        self.lane_starts = [1, 6, 11, 17, 22, 27]
        
        self.notes = []
        self.start_time = 0 
        self.last_song_start = 0 
        self.spawn_timer = time.time()
        self.last_tick = time.time()
        
        self.last_y_pos = [1] 
        self.button_states = [False] * 512
        self.prev_button_states = [False] * 512
        self.current_song_name = "Pregătire..."
        self.chosen_song_path = None

        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.quit()
                pygame.mixer.pre_init(44100, -16, 2, 512)
                pygame.mixer.init()
            except Exception as e: 
                print(f"⚠ Eroare audio: {e}")

    def start_music(self):
        """Alege o piesă la întâmplare și o redă O SINGURĂ DATĂ."""
        self.last_song_start = time.time()
        if PYGAME_AVAILABLE:
            available_songs = [s for s in SONG_LIST if os.path.exists(s)]
            if available_songs:
                # Evităm să punem aceeași piesă de două ori la rând dacă avem mai multe
                choices = [s for s in available_songs if s != self.chosen_song_path]
                if not choices: choices = available_songs
                
                self.chosen_song_path = random.choice(choices)
                self.current_song_name = os.path.basename(self.chosen_song_path).replace('.mp3', '')
                
                pygame.mixer.music.load(self.chosen_song_path)
                pygame.mixer.music.play(0) # 0 înseamnă că se redă o singură dată (nu pe repeat)
            else:
                self.current_song_name = "Nicio melodie"

    def tick(self):
        with self.lock:
            now = time.time()
            dt = now - self.last_tick
            self.last_tick = now

            if self.state == "START_ANIM":
                elapsed_anim = now - self.state_start_time
                if elapsed_anim >= 4.0: 
                    self.state = "PLAYING"
                    self.start_time = now # Începe contorul principal de 180s
                    self.start_music()
                return

            if self.state == "END_ANIM":
                return

            if self.state == "TRANSITION_ANIM":
                elapsed_anim = now - self.state_start_time
                if elapsed_anim >= 3.0: # 3 secunde de tranziție între piese
                    self.state = "PLAYING"
                    self.start_music()
                return

            if self.state == "PLAYING":
                elapsed_total = now - self.start_time
                
                # 1. Verificăm dacă s-a terminat timpul total de joc
                if elapsed_total >= GAME_DURATION:
                    self.state = "END_ANIM"
                    self.state_start_time = now
                    if PYGAME_AVAILABLE: pygame.mixer.music.stop()
                    return

                # 2. Verificăm dacă melodia curentă s-a terminat natural
                song_ended = False
                if PYGAME_AVAILABLE and self.chosen_song_path:
                    # get_busy() returnează False când melodia se oprește
                    if not pygame.mixer.music.get_busy():
                        song_ended = True
                else:
                    # Fallback dacă nu e audio: schimbăm la fiecare 30 secunde
                    if now - self.last_song_start > 30.0:
                        song_ended = True

                if song_ended:
                    self.state = "TRANSITION_ANIM"
                    self.state_start_time = now
                    self.notes.clear() # Curățăm tabla de joc pentru o tranziție curată
                    return

                # --- Logica normală de mișcare a notelor ---
                speed = 4.0 + (elapsed_total * 0.03) 

                if now - self.spawn_timer > 0.7:
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
            elapsed = time.time() - self.start_time
            rem = max(0, GAME_DURATION - elapsed)
            score_str = " | ".join([f"P{i+1}: {self.scores[i]}" for i in range(6)])
            
            st_text = "[Schimbare Melodie] " if self.state == "TRANSITION_ANIM" else f"[🎵 {self.current_song_name}] "
            sys.stdout.write(f"\r{st_text} TIMP: {int(rem//60):02d}:{int(rem%60):02d} | {score_str}")
            sys.stdout.flush()

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
                self.render_rainbow_bg(buffer, now * 3.0) # Curcubeu mai intens și rapid
                self.draw_text(buffer, "NEXT", 1, 13, BLACK) # Textul NEXT centrat (aprox)
                return buffer

            if self.state == "END_ANIM":
                self.render_rainbow_bg(buffer, now * 2.0)
                self.draw_text(buffer, "END", 2, 13, BLACK) 
                return buffer

            # RENDER NORMAL (PLAYING)
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

    def send_packet(self, frame_data):
        self.sequence = (self.sequence + 1) & 0xFFFF
        target = (UDP_SEND_IP, UDP_SEND_PORT)
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
        print("\nJoc pornit! Animația de start rulează. Apasă Ctrl+C pentru a opri.")
        while True:
            self.game.tick()
            self.send_packet(self.game.render())
            self.game.display_status()
            time.sleep(0.04)

if __name__ == "__main__":
    game = PianoTilesTzancaEdition()
    net = NetworkManager(game)
    net.run()