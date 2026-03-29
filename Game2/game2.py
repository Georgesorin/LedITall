import sys
import subprocess
import socket
import time
import threading
import random
import os
import colorsys
import math

# --- AUTO-INSTALL PYGAME ---
def verifica_si_instaleaza(pachet):
    try:
        __import__(pachet)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pachet])

verifica_si_instaleaza('pygame')
import pygame

# --- CONFIGURARE REȚEA & MATRICE
UDP_SEND_IP        = "127.0.0.1"
UDP_SEND_PORT_MAIN = 4226
UDP_LISTEN_PORT    = 4444

NUM_CHANNELS      = 8
LEDS_PER_CHANNEL  = 64
BOARD_W, BOARD_H   = 16, 32
FRAME_LEN         = NUM_CHANNELS * LEDS_PER_CHANNEL * 3 

# Culori de bază
RED   = (255, 0, 0)
GREEN = (0, 255, 0)
WHITE = (255, 255, 255)

# Playlist de referință
SONG_DATA = {
    "songs/saxobeat.mp3":     {"bpm": 127, "name": "Mr. Saxobeat"},
    "songs/dont_stop.mp3":    {"bpm": 123, "name": "Don't Stop The Music"},
    "songs/s_and_m.mp3":      {"bpm": 128, "name": "S&M"},
    "songs/everything.mp3":   {"bpm": 129, "name": "Give Me Everything"},
    "songs/promiscuous.mp3":  {"bpm": 114, "name": "Promiscuous"},
}

# ════════════════════════════════════════════════════════════════════════
# 3. CLASELE JOCULUI
# ════════════════════════════════════════════════════════════════════════
class Note:
    def __init__(self, player_idx, row_offset, color):
        self.player = player_idx
        self.row_offset = row_offset 
        self.color = color
        self.x = -1.0
        self.alive = True

class PianoTilesPro:
    def __init__(self, num_players, playlist):
        self.num_players = max(1, min(6, num_players))
        self.lock = threading.RLock()
        self.scores = [0] * self.num_players
        
        # State machine
        self.state = "RAINBOW_ANIM"
        self.state_start_time = time.time()
        
        self.playlist = playlist
        self.current_song_idx = 0
        
        # Layout benzi
        self.LANE_H = 5 
        total_game_h = self.num_players * self.LANE_H
        self.offset_y = (BOARD_H - total_game_h) // 2
        
        self.lane_starts = [self.offset_y + p * self.LANE_H + 1 for p in range(self.num_players)]
        self.horizontal_lines = [self.offset_y + p * self.LANE_H for p in range(self.num_players)] + [self.offset_y + total_game_h]

        self.notes = []
        self.hit_effects = [] 
        self.spawn_timer = time.time()
        self.last_tick = time.time()
        
        # Input state
        self.button_states = [False] * 512
        self.prev_button_states = [False] * 512
        
        self.current_song_name = "Ready"
        self.current_bpm = 120
        self.base_interval = 0.5
        self.song_actual_start = 0

        pygame.mixer.quit()
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.mixer.init()

    def start_music(self):
        if self.current_song_idx >= len(self.playlist):
            self.current_song_idx = 0 # Restart playlist loop
        
        path = self.playlist[self.current_song_idx]
        self.song_actual_start = time.time()
        
        if os.path.exists(path):
            info = SONG_DATA[path]
            self.current_bpm = info["bpm"]
            self.current_song_name = info["name"]
            self.base_interval = 60.0 / self.current_bpm
            pygame.mixer.music.load(path)
            pygame.mixer.music.play(0)
        else:
            self.current_song_idx += 1
            self.start_music()

    def tick(self):
        with self.lock:
            now = time.time()
            dt = now - self.last_tick
            self.last_tick = now

            # Tranziții stări
            if self.state == "RAINBOW_ANIM":
                if now - self.state_start_time > 3.0:
                    self.state = "TEXT_ANIM"
                    self.state_start_time = now
                return
            
            if self.state == "TEXT_ANIM":
                if now - self.state_start_time > 4.0:
                    self.state = "SHOW_NUMBERS"
                    self.state_start_time = now
                return
                
            if self.state == "SHOW_NUMBERS":
                # Lăsăm numerele pe ecran 3 secunde înainte să înceapă melodia
                if now - self.state_start_time > 3.0:
                    self.state = "PLAYING"
                    self.start_music()
                return

            if self.state == "PLAYING":
                # Verificare final piesă
                if not pygame.mixer.music.get_busy() and (now - self.song_actual_start > 5):
                    self.current_song_idx += 1
                    self.notes.clear()
                    self.state = "TEXT_ANIM" # Ciclul o ia de la capăt
                    self.state_start_time = now
                    return

                elapsed = now - self.song_actual_start
                difficulty = max(0.45, 1.2 - (elapsed / 65.0))
                spawn_speed = self.base_interval * difficulty
                move_speed = 8.0 + (elapsed * 0.05)
                
                # Spawn Logic
                if now - self.spawn_timer > spawn_speed:
                    chance = random.random()
                    if chance > 0.18:
                        common_row_offset = random.randint(0, 2)
                        common_color = self._get_rand_col()
                        
                        # Acum adăugăm această notă identică pentru toți jucătorii activi
                        for p in range(self.num_players):
                            self.notes.append(Note(p, common_row_offset, common_color))
                            
                    self.spawn_timer = now

                # Update Note & Consumare la Verde
                for note in self.notes[:]:
                    note.x += move_speed * dt
                    if note.x >= 13.9: # Dispar la marginea benzii verzi
                        if note.alive: self.scores[note.player] -= 1
                        self.notes.remove(note)

                self.hit_effects = [e for e in self.hit_effects if now - e['t'] < 0.2]

                # Anti-Camping Snapshots
                curr_btns = self.button_states[:]
                for i in range(512):
                    if curr_btns[i] and not self.prev_button_states[i]:
                        self.handle_click(i)
                self.prev_button_states = curr_btns
                self._print_scores()

    def handle_click(self, led_idx):
        ch, rem = led_idx // 64, led_idx % 64
        row, col = rem // 16, rem % 16
        x_c, y_c = (col if row % 2 == 0 else 15 - col), (ch * 4) + row

        for p in range(self.num_players):
            y_s = self.lane_starts[p]
            if y_s <= y_c < y_s + 4:
                hit = False
                for note in self.notes:
                    if note.player == p and note.alive and note.x > 10.0:
                        if y_c == (y_s + note.row_offset):
                            self.scores[p] += 5
                            note.alive = False
                            self.hit_effects.append({'x': x_c, 'y': y_c, 't': time.time(), 'success': True})
                            hit = True
                            break
                if not hit:
                    if x_c < 14: self.scores[p] -= 2 
                    self.hit_effects.append({'x': x_c, 'y': y_c, 't': time.time(), 'success': False})
                return

    def _get_rand_col(self):
        rgb = colorsys.hsv_to_rgb(random.random(), 1, 1)
        return (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))

    def _print_scores(self):
        # Inițializăm last_scores dacă nu există (pentru a compara cu scorul curent)
        if not hasattr(self, 'last_scores'):
            self.last_scores = []
            
        # Actualizăm terminalul DOAR dacă scorul s-a modificat!
        if self.scores == self.last_scores:
            return
            
        self.last_scores = list(self.scores)
        s = " | ".join([f"P{i+1}: {self.scores[i]}" for i in range(self.num_players)])
        # Am adăugat spații goale la final ca să șteargă caracterele "fantomă" în caz că scorul scade de la zeci la unități
        sys.stdout.write(f"\r🎹 [{self.current_song_name}] {s}          ")
        sys.stdout.flush()

    # ════════════════════════════════════════════════════════════════════════
    # 4. RANDARE & ANIMATII
    # ════════════════════════════════════════════════════════════════════════
    def render(self):
        buf = bytearray(FRAME_LEN)
        with self.lock:
            now = time.time()
            if self.state == "RAINBOW_ANIM":
                self._render_rainbow(buf, now)
            elif self.state == "TEXT_ANIM":
                self._render_text_long(buf, now)
            elif self.state == "SHOW_NUMBERS":
                self._render_numbers_state(buf)
            elif self.state == "PLAYING":
                self._render_game(buf)
        return buf

    def _draw_boundaries(self, buf):
        """Desenează liniile roșii și zonele verzi."""
        for y in self.horizontal_lines:
            for x in range(16): self.set_led(buf, x, y, RED)
        for p in range(self.num_players):
            y_s = self.lane_starts[p]
            for dy in range(4):
                self.set_led(buf, 14, y_s + dy, GREEN)
                self.set_led(buf, 15, y_s + dy, GREEN)

    def _render_background_beat(self, buf, now):
        """Fundal animat tip 'Plasma Wave' care pulsează pe ritmul muzicii."""
        if self.song_actual_start == 0: 
            return
        
        elapsed = now - self.song_actual_start
        if elapsed < 0: 
            return

        current_beat = elapsed * self.current_bpm / 60.0
        beat_index = int(current_beat)      
        beat_phase = current_beat - beat_index 
        
        # Intensitatea de bază scade ușor între beaturi pentru efectul de pompaj
        beat_intensity = max(0.4, 1.0 - (beat_phase * 1.5)) 
        
        # Culoarea principală se schimbă încet pe parcursul melodiei
        base_hue = (now * 0.05) % 1.0

        end_y = self.offset_y + (self.num_players * self.LANE_H)

        for y in range(32):
            if y < self.offset_y or y >= end_y:
                for x in range(16):
                    # Generăm efectul de val fluid combinând X, Y și Timpul
                    wave = math.sin(x * 0.4 + now * 3) + math.cos(y * 0.3 - now * 2)
                    wave_norm = (wave + 2) / 4.0 # Normalizăm între 0.0 și 1.0

                    # Amestecăm nuanța de bază cu valul pentru un gradient fin
                    pixel_hue = (base_hue + wave_norm * 0.3) % 1.0
                    
                    # Luminozitatea combină pulsul beat-ului cu "creasta" valului
                    brightness = max(0.1, wave_norm * beat_intensity)
                    
                    rgb = colorsys.hsv_to_rgb(pixel_hue, 1.0, brightness)
                    self.set_led(buf, x, y, (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255)))

    def _render_numbers_state(self, buf):
        """Afișează marginile și numărul jucătorului pe fiecare bandă."""
        self._draw_boundaries(buf)
        
        # Zona de joc activă este de la X=0 la X=13 (lățime 14).
        # Centrul este la 7. Fontul nou are 5 pixeli lățime (0,1,2,3,4).
        # Dacă începem de la X=5, numerele ocupă 5,6,7,8,9 -> perfect centrate!
        x_start = 5 
        num_color = (0, 255, 255) # Cyan

        for p in range(self.num_players):
            y_s = self.lane_starts[p]
            player_num = p + 1
            
            # Adăugăm un mic offset pe Y (jumătate de pixel) lăsând Y_s simplu,
            # astfel încât fontul de 3 pixeli înălțime să stea frumos în banda de 4.
            self._draw_number(buf, player_num, x_start, y_s, num_color)

    def _draw_number(self, buf, num, x_offset, y_offset, color):
        """
        Font desenat MANUAL, gata orientat spre stânga. 
        Top-ul cifrei indică spre X mic, baza spre X mare.
        Matrice de 5 (lățime X) pe 3 (înălțime Y).
        """
        font_rotated_left = {
            # 1: Baza e la dreapta (X=4), cârligul e sus la stânga.
            1: [(0,1), (1,1), (1,2), (2,1), (3,1), (4,0), (4,1), (4,2)],
            
            # 2: Forma de Z clară
            2: [(0,0), (0,1), (0,2), (1,0), (2,0), (2,1), (2,2), (3,2), (4,0), (4,1), (4,2)],
            
            # 3: Golurile sunt spre stânga benzii (Y=2)
            3: [(0,0), (0,1), (0,2), (1,0), (2,0), (2,1), (2,2), (3,0), (4,0), (4,1), (4,2)],
            
            # 4: Bara verticală închisă
            4: [(0,0), (0,2), (1,0), (1,2), (2,0), (2,1), (2,2), (3,0), (4,0)],
            
            # 5: Inversul lui 2
            5: [(0,0), (0,1), (0,2), (1,2), (2,0), (2,1), (2,2), (3,0), (4,0), (4,1), (4,2)],
            
            # 6: Bucla închisă jos
            6: [(0,0), (0,1), (0,2), (1,2), (2,0), (2,1), (2,2), (3,0), (3,2), (4,0), (4,1), (4,2)]
        }
        
        if num in font_rotated_left:
            for px, py in font_rotated_left[num]:
                # Desenăm pixelii exact la coordonatele dictate de fontul manual
                self.set_led(buf, x_offset + px, y_offset + py, color)

    def _render_game(self, buf):
        now = time.time()
        
        # 1. Desenăm fundalul reactiv la muzică
        self._render_background_beat(buf, now)
        
        # 2. Desenăm terenul
        self._draw_boundaries(buf)
        
        # 3. Desenăm notele care cad
        for note in self.notes:
            if note.alive and int(note.x) < 14:
                self.set_led(buf, int(note.x), self.lane_starts[note.player] + note.row_offset, note.color)
        
        # 4. Desenăm efectele de lovire
        for e in self.hit_effects:
            col = WHITE if e['success'] else (150, 0, 0)
            self.set_led(buf, int(e['x']), int(e['y']), col)

    def _render_text_long(self, buf, now):
        """Text scris 'pe loc', pixel cu pixel liniar. Litere rotite la 90 grade."""
        pulsation_val = int(127 + 127 * math.sin(now * 5))
        color = (pulsation_val, 0, 255)

        pixels_sequence = [
            # L
            (4,0), (3,0), (2,0), (1,0), (0,0), (0,1), (0,2),
            # E 
            (4,4), (3,4), (2,4), (1,4), (0,4), 
            (4,5), (4,6), 
            (2,5), (2,6), 
            (0,5), (0,6),
            # D 
            (4,8), (3,8), (2,8), (1,8), (0,8), 
            (4,9), (3,10), (2,10), (1,10), (0,9),
            # I 
            (4,13), (3,13), (2,13), (1,13), (0,13),
            # T 
            (4,16), (4,17), (4,18), 
            (3,17), (2,17), (1,17), (0,17),
            # A 
            (0,20), (1,20), (2,20), (3,20), 
            (4,21), 
            (3,22), (2,22), (1,22), (0,22), 
            (2,21),
            # L 
            (4,24), (3,24), (2,24), (1,24), (0,24), (0,25), (0,26),
            # L 
            (4,28), (3,28), (2,28), (1,28), (0,28), (0,29), (0,30)
        ]

        offset_x = 5
        elapsed = now - self.state_start_time
        draw_duration = 3.0 
        total_pixels = len(pixels_sequence)
        
        pixels_to_draw = int((elapsed / draw_duration) * total_pixels)
        pixels_to_draw = max(0, min(pixels_to_draw, total_pixels))

        for i in range(pixels_to_draw):
            px, py = pixels_sequence[i]
            self.set_led(buf, offset_x + px, py, color)

    def _render_rainbow(self, buf, t):
        for y in range(32):
            for x in range(16):
                h = (t + x/16 + y/32) % 1.0
                rgb = [int(c*255) for c in colorsys.hsv_to_rgb(h, 1.0, 0.8)]
                self.set_led(buf, x, y, rgb)

    def set_led(self, buf, x, y, col):
        if 0 <= x < 16 and 0 <= y < 32:
            ch, r = y // 4, y % 4
            idx = (r * 16 + x) if r % 2 == 0 else (r * 16 + (15 - x))
            off = idx * 24 + ch 
            buf[off], buf[off+8], buf[off+16] = col[1], col[0], col[2]

# ════════════════════════════════════════════════════════════════════════
# 5. REȚEA & PLAYLIST
# ════════════════════════════════════════════════════════════════════════
class NetworkManager:
    def __init__(self, game):
        self.game, self.seq = game, 0
        self.s_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try: self.s_recv.bind(("0.0.0.0", UDP_LISTEN_PORT))
        except: pass

    def run(self):
        threading.Thread(target=self.recv_loop, daemon=True).start()
        while True:
            self.game.tick()
            self.send_packet(self.game.render(), UDP_SEND_PORT_MAIN)
            time.sleep(0.033)

    def recv_loop(self):
        while True:
            try:
                data, _ = self.s_recv.recvfrom(2048)
                if len(data) >= 1370:
                    new_st = [False]*512
                    for c in range(8):
                        off = 2 + (c * 171) + 1 
                        for i in range(64):
                            new_st[(c * 64) + i] = (data[off + i] > 0)
                    with self.game.lock: self.game.button_states = new_st 
            except: pass

    def send_packet(self, data, port):
        self.seq = (self.seq + 1) & 0xFFFF
        addr = (UDP_SEND_IP, port)
        # Pachete Protocol Original
        self.s_send.sendto(bytearray([0x75, 0x01, 0x02, 0x00, 0x08, 0x02, 0x00, 0x00, 0x33, 0x44, self.seq>>8, self.seq&0xFF, 0,0,0,0x0E, 0]), addr)
        fff0 = bytearray([0x75, 0x03, 0x04, 0x00, 0x19, 0x02, 0x00, 0x00, 0x88, 0x77, 0xFF, 0xF0, 0, 0x10]) + (bytearray([0, 0x40])*8) + bytearray([0x1E, 0])
        self.s_send.sendto(fff0, addr)
        for i in range(0, len(data), 984):
            chunk = data[i:i+984]
            inner = bytearray([0x02, 0, 0, 0x88, 0x77, 0, (i//984)+1, len(chunk)>>8, len(chunk)&0xFF]) + chunk
            p = bytearray([0x75, 0x05, 0x06, (len(inner)-1)>>8, (len(inner)-1)&0xFF]) + inner + bytearray([0x1E if len(chunk)==984 else 0x36, 0])
            self.s_send.sendto(p, addr)
        self.s_send.sendto(bytearray([0x75, 0x07, 0x08, 0, 0x08, 0x02, 0, 0, 0x55, 0x66, self.seq>>8, self.seq&0xFF, 0,0,0,0x0E, 0]), addr)

def selecteaza_playlist():
    songs = list(SONG_DATA.keys())
    print("\n--- CONFIGURARE PLAYLIST (5 Melodii) ---")
    for i, s in enumerate(songs): print(f" {i+1}. {SONG_DATA[s]['name']}")
    user_input = input("\nAlege melodiile (ex: 1 3 5) sau ENTER pentru random: ")
    playlist = []
    try:
        idxs = [int(x)-1 for x in user_input.split() if x.isdigit()]
        for idx in idxs:
            if 0 <= idx < len(songs) and songs[idx] not in playlist:
                playlist.append(songs[idx])
    except: pass
    while len(playlist) < 5:
        r_song = random.choice(songs)
        if r_song not in playlist: playlist.append(r_song)
    return playlist[:5]

# ════════════════════════════════════════════════════════════════════════
# 6. ENTRY POINT
# ════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        print("╔══════════════════════════════════════╗")
        print("║   Piano Tiles Pro - Pink Text Ed.    ║")
        print("╚══════════════════════════════════════╝")
        n = int(input("\nNumăr jucători (1-6): "))
        my_playlist = selecteaza_playlist()
        game = PianoTilesPro(n, playlist=my_playlist)
        net = NetworkManager(game)
        net.run()
    except KeyboardInterrupt:
        print("\nJoc oprit.")