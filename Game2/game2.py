import socket
import time
import threading
import random
import sys
import os

# --- FIX AUDIO WSL ---
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
os.environ['SDL_AUDIODRIVER'] = 'pulseaudio'

# Încercăm să importăm pygame pentru sunet
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

# --- CONFIGURARE JOC ---
GAME_DURATION = 180 

# --- PLAYLIST ---
SONG_LIST = [
    "songs/dont_stop.mp3",
    "songs/everything.mp3",
    "songs/promiscuous.mp3",
    "songs/s_and_m.mp3",
    "songs/saxobeat.mp3"
]

class SyncNote:
    def __init__(self, relative_y_positions, lane_starts, color):
        self.x = 0.0
        self.rel_y = relative_y_positions
        self.lane_starts = lane_starts 
        self.color = color
        # [jucător][pixel_index]
        self.active_map = [[True for _ in range(len(relative_y_positions))] for _ in range(6)]

    def move(self, speed):
        self.x += speed

class PianoTilesTzancaEdition:
    def __init__(self):
        self.running = True
        self.lock = threading.RLock()
        self.scores = [0] * 6
        self.game_over = False
        
        # Grid orizontal: 0, 5, 10 sunt simple. 15 ȘI 16 formează linia dublă de la mijloc.
        self.horizontal_lines = [0, 5, 10, 15, 16, 21, 26, 31]
        
        # Zonele de start pentru cei 6 jucători (4 rânduri libere între linii)
        self.lane_starts = [1, 6, 11, 17, 22, 27]
        
        self.notes = []
        self.start_time = time.time()
        self.spawn_timer = time.time()
        self.last_tick = time.time()
        
        self.last_y_pos = [1] 
        self.button_states = [False] * 512
        self.prev_button_states = [False] * 512
        self.current_song_name = "Fără muzică"

        if PYGAME_AVAILABLE:
            try:
                # Resetăm mixer-ul în caz că a rămas agățat în WSL
                pygame.mixer.quit()
                pygame.mixer.pre_init(44100, -16, 2, 512)
                pygame.mixer.init()
                
                # Verificăm ce melodii există fizic
                available_songs = [s for s in SONG_LIST if os.path.exists(s)]
                
                if available_songs:
                    chosen_song = random.choice(available_songs)
                    pygame.mixer.music.load(chosen_song)
                    pygame.mixer.music.play(-1)
                    # Extragem doar numele fișierului pentru afișare (fără 'songs/' și '.mp3')
                    self.current_song_name = os.path.basename(chosen_song).replace('.mp3', '')
                else:
                    print("⚠ Nicio melodie nu a fost găsită în folderul 'songs/'. Verificați calea.")
            except Exception as e: 
                print(f"⚠ Eroare la inițializarea audio: {e}")

    def tick(self):
        with self.lock:
            if self.game_over: return
            now = time.time()
            elapsed = now - self.start_time
            
            if elapsed >= GAME_DURATION:
                self.game_over = True
                return

            dt = now - self.last_tick
            self.last_tick = now
            speed = 4.0 + (elapsed * 0.03) 

            # Spawning (Note sincronizate)
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

            # Mișcare
            for note in self.notes[:]:
                note.move(speed * dt)
                if note.x >= BOARD_WIDTH:
                    self.notes.remove(note)

            # Input
            for i in range(512):
                if self.button_states[i] and not self.prev_button_states[i]:
                    self.handle_click(i)
                self.prev_button_states[i] = self.button_states[i]

    def handle_click(self, led_idx):
        if self.game_over: return
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
        elapsed = time.time() - self.start_time
        rem = max(0, GAME_DURATION - elapsed)
        score_str = " | ".join([f"P{i+1}: {self.scores[i]}" for i in range(6)])
        # Am adăugat numele melodiei aici ca să vezi ce rulează!
        sys.stdout.write(f"\r[🎵 {self.current_song_name}] TIMP: {int(rem//60):02d}:{int(rem%60):02d} | {score_str}")
        sys.stdout.flush()

    def render(self):
        buffer = bytearray(FRAME_DATA_LENGTH)
        with self.lock:
            color_grid = RED if not self.game_over else (0, 255, 0)
            
            # 1. Randăm Grid-ul orizontal (Fără margini laterale)
            for y in range(BOARD_HEIGHT):
                if y in self.horizontal_lines:
                    for x in range(BOARD_WIDTH):
                        self.set_led(buffer, x, y, color_grid)
            
            # 2. Randăm Notele (Pixel curat)
            if not self.game_over:
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

# --- NETWORK MANAGER ---
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
        print("\nJoc pornit! Apasă Ctrl+C pentru a opri.")
        while True:
            self.game.tick()
            self.send_packet(self.game.render())
            self.game.display_status()
            time.sleep(0.04)

if __name__ == "__main__":
    game = PianoTilesTzancaEdition()
    net = NetworkManager(game)
    net.run()