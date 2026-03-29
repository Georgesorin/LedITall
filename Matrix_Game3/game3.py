# Block Party - Remember the color desplayed and step only on those tiles! Get the highest score
#               before time runs out.

import socket
import time
import threading
import random
import os
import math
import tkinter as tk

# --- DASHBOARD CONFIGURATION (MONITOR 2) ---
DASHBOARD_FULLSCREEN = False  # Change to True for production
DASHBOARD_MONITOR = 1         # 0 = First monitor, 1 = Second monitor
# -----------------------------------------

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

# --- Matrix Room Network Configuration ---
UDP_SEND_IP = "255.255.255.255"
UDP_SEND_PORT = 4626
UDP_LISTEN_PORT = 7800
NUM_CHANNELS = 8
LEDS_PER_CHANNEL = 64
FRAME_DATA_LENGTH = NUM_CHANNELS * LEDS_PER_CHANNEL * 3
BOARD_WIDTH = 16
BOARD_HEIGHT = 32 # 512 physical tiles

# --- Game Colors ---
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
CYAN = (0, 255, 255)
MAGENTA = (255, 0, 255)
ORANGE = (194, 75, 19)
PURPLE = (90, 33, 156)
PINK = (255, 133, 158)

COLORS_LIST = [PINK, GREEN, BLUE, YELLOW, CYAN, MAGENTA, ORANGE, PURPLE]

# --- Countdown Font (5x7 scaled x2) ---
DIGITS = {
    3: [" ### ", "#   #", "    #", "  ## ", "    #", "#   #", " ### "],
    2: [" ### ", "#   #", "    #", "  ## ", " #   ", "#    ", "#####"],
    1: ["  #  ", " ##  ", "# #  ", "  #  ", "  #  ", "  #  ", "#####"]
}

# --- Compact font for horizontal LedITall ---

FONT_LEDITALL = {
    'L': ["#  ", "#  ", "#  ", "#  ", "###"],
    'e': [" ##", "# #", "###", "#  ", "###"],
    'd': ["  #", "  #", "###", "# #", "###"],
    'I': ["###", " # ", " # ", " # ", "###"],
    'T': ["###", " # ", " # ", " # ", " # "],
    'a': [" ##", "  #", "###", "# #", "###"],
    'l': ["#", "#", "#", "#", "#"]
}

TEXT_BRAND = "LedITall"

# --- Audio Manager ---
class SoundManager:
    def __init__(self):
        self.enabled = PYGAME_AVAILABLE
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        if self.enabled:
            # Reset the mixer and give it multiple channels to avoid audio blockages

            if pygame.mixer.get_init():
                pygame.mixer.quit()

            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            pygame.mixer.set_num_channels(32) # Open 32 simultaneous channels

            self._generate_sounds()
            self.snd_tick = pygame.mixer.Sound(os.path.join(self.base_dir, "tick.wav"))
            self.snd_error = pygame.mixer.Sound(os.path.join(self.base_dir, "error2.wav"))
            self.snd_win = pygame.mixer.Sound(os.path.join(self.base_dir, "win2.wav"))
            self.snd_start = pygame.mixer.Sound(os.path.join(self.base_dir, "start.wav"))

            # FORCE effects volume to MAXIMUM (1.0)
            self.snd_tick.set_volume(1.0)
            self.snd_error.set_volume(1.0)
            self.snd_win.set_volume(1.0)
            self.snd_start.set_volume(1.0)

            try:
                bgm_path = os.path.join(self.base_dir, "start3.mp3")
                pygame.mixer.music.load(bgm_path)
                # Play the background music MUCH softer to hear the effects clearly
                pygame.mixer.music.set_volume(0.7)
                pygame.mixer.music.play(-1)
            except:
                pass

    def _generate_sounds(self):
        import wave, struct

        def make_wav(name, freq, duration, volume=1.0):
            filepath = os.path.join(self.base_dir, name) 
            if os.path.exists(filepath): return
            sample_rate = 44100

            with wave.open(filepath, 'w') as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(sample_rate)

                for i in range(int(sample_rate * duration)):
                    value = int(volume * 32767.0 * math.sin(2.0 * math.pi * freq * i / sample_rate))
                    f.writeframesraw(struct.pack('<h', value))

        def make_bgm(name):
            filepath = os.path.join(self.base_dir, name)

            if os.path.exists(filepath): return
            sample_rate = 44100

            with wave.open(filepath, 'w') as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(sample_rate)
                notes = [220, 0, 277, 0, 330, 0, 277, 0]

                for freq in notes:
                    for i in range(int(sample_rate * 0.125)): 
                        if freq == 0: value = 0
                        else: value = int(0.2 * 32767.0 * math.sin(2.0 * math.pi * freq * i / sample_rate))
                        f.writeframesraw(struct.pack('<h', value))

        make_wav("tick.wav", 1000, 0.05)
        make_wav("error2.wav", 150, 0.8)
        make_wav("win2.wav", 600, 0.4)
        make_wav("start.wav", 400, 0.8)
        make_bgm("bgm.wav")

    def play(self, name):
        if not self.enabled: return
        try:
            if name == 'tick':
                self.snd_tick.play()
            elif name == 'error':
                self.snd_error.stop() # Ensure it doesn't overlap itself
                self.snd_error.play()
            elif name == 'win': 
                self.snd_win.stop()
                self.snd_win.play()
            elif name == 'start': 
                self.snd_start.play()
        except:
            pass

    def play_bgm(self):
        pass

    def stop_bgm(self):
        pass

# --- Helper Logic ---
def blocks_touch(b1, b2):
    x1, y1, w1, h1 = b1
    x2, y2, w2, h2 = b2
    return not (x1 + w1 < x2 or x2 + w2 < x1 or y1 + h1 < y2 or y2 + h2 < y1)

# --- Helper Logic for Stars ---
def get_star_points(x, y, radius, points=5):
    """Calculates the coordinates of a star-shaped polygon"""
    inner_radius = radius * 0.4
    angle = math.pi / points
    vertices = []

    for i in range(2 * points):
        r = radius if i % 2 == 0 else inner_radius
        a = i * angle - math.pi / 2
        vx = x + math.cos(a) * r
        vy = y + math.sin(a) * r
        vertices.append((vx, vy))

    return vertices

# --- Physical Game Logic ---
class PhysicalBlockParty:
    def __init__(self):
        self.board = [[BLACK for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
        self.blob_board = [[-1 for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]

        self.running = True
        self.lock = threading.RLock()
        self.audio = SoundManager()
        self.button_states = [False] * 512

        self.state = 'WAITING_TO_START'
        self.round = 1
        self.score = 0

        self.target_color = RED

        self.global_timer = 0.0
        self.round_timer = 0.0
        self.sequence_timer = 0.0

        self.last_tick_time = time.time()
        self.last_second_beep = 0
        self.last_seq_sec = 0
        self.last_printed_minute = -1
    
        self.error_blobs = []
        self.correct_blobs = []

    def initiate_start_sequence(self):
        with self.lock:
            self.state = 'BRANDING_SEQUENCE'
            self.sequence_timer = 3.0
            self.last_tick_time = time.time()
            self.last_seq_sec = 6
            self.audio.play_bgm()

    def start_game_logic(self):
        self.round = 1
        self.score = 0
        self.global_timer = 7 * 60
        self.last_printed_minute = 7
        self.start_round()

    def start_round(self):
        with self.lock:
            self.state = 'SHOW_TARGET'
            self.target_color = random.choice(COLORS_LIST)
            self.audio.play('start')

            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    self.board[y][x] = self.target_color
            self.round_timer = 3.0 
            self.last_tick_time = time.time()

    def generate_blocks(self):
        with self.lock:
            MACRO_W = 8
            MACRO_H = 16
            blob_grid = [[-1 for _ in range(MACRO_W)] for _ in range(MACRO_H)]
            blobs = []
            min_bg, max_bg = 4, 8

            for y in range(MACRO_H):
                for x in range(MACRO_W):

                    if blob_grid[y][x] == -1:
                        target_size = random.randint(min_bg, max_bg)
                        blob_id = len(blobs)
                        current_blob = []
                        q = [(y, x)]

                        while q and len(current_blob) < target_size:
                            idx = random.randint(0, len(q)-1)
                            cy, cx = q.pop(idx)

                            if blob_grid[cy][cx] == -1:
                                blob_grid[cy][cx] = blob_id
                                current_blob.append((cy, cx))

                                for dy, dx in [(-1,0), (1,0), (0,-1), (0,1)]:
                                    ny, nx = cy+dy, cx+dx

                                    if 0 <= ny < MACRO_H and 0 <= nx < MACRO_W:
                                        if blob_grid[ny][nx] == -1:
                                            q.append((ny, nx))

                        blobs.append(current_blob)

            adj = {i: set() for i in range(len(blobs))}

            for y in range(MACRO_H):
                for x in range(MACRO_W):
                    b1 = blob_grid[y][x]

                    if x + 1 < MACRO_W:
                        b2 = blob_grid[y][x+1]
                        if b1 != b2:
                            adj[b1].add(b2)
                            adj[b2].add(b1)

                    if y + 1 < MACRO_H:
                        b2 = blob_grid[y+1][x]
                        if b1 != b2:
                            adj[b1].add(b2)
                            adj[b2].add(b1)

            wrong_colors = [c for c in COLORS_LIST if c != self.target_color]
            blob_colors = {}

            for i in range(len(blobs)):
                neighbor_colors = {blob_colors[n] for n in adj[i] if n in blob_colors}
                avail = [c for c in wrong_colors if c not in neighbor_colors]
                if not avail:
                    avail = wrong_colors 
                blob_colors[i] = random.choice(avail)

            for y in range(MACRO_H):
                for x in range(MACRO_W):
                    bid = blob_grid[y][x]
                    color = blob_colors[bid]
                    self.board[y*2][x*2] = color
                    self.blob_board[y*2][x*2] = bid
                    self.board[y*2][x*2+1] = color
                    self.blob_board[y*2][x*2+1] = bid
                    self.board[y*2+1][x*2] = color
                    self.blob_board[y*2+1][x*2] = bid
                    self.board[y*2+1][x*2+1] = color
                    self.blob_board[y*2+1][x*2+1] = bid
            elapsed_seconds = (7 * 60) - self.global_timer

            if elapsed_seconds >= 250:
                target_count = random.randint(2, 3)
                target_size = 2
            elif elapsed_seconds >= 150: 
                target_count = random.randint(2, 3)
                target_size = random.randint(2, 3)
            elif elapsed_seconds >= 60:
                target_count = random.randint(3, 4)
                target_size = random.randint(3, 4)
            else:                        
                target_count = random.randint(4, 6)
                target_size = random.randint(4, 6)

            safe_macros_global = set()

            for i in range(target_count):
                start_y = random.randint(0, MACRO_H-1)
                start_x = random.randint(0, MACRO_W-1)
                q = [(start_y, start_x)]
                current_safe = set()

                while q and len(current_safe) < target_size:
                    idx = random.randint(0, len(q)-1)
                    cy, cx = q.pop(idx)
                    if (cy, cx) not in safe_macros_global and (cy, cx) not in current_safe:
                        current_safe.add((cy, cx))
                        for dy, dx in [(-1,0), (1,0), (0,-1), (0,1)]:
                            ny, nx = cy+dy, cx+dx
                            if 0 <= ny < MACRO_H and 0 <= nx < MACRO_W:
                                q.append((ny, nx))

                safe_blob_id = 1000 + i

                for (my, mx) in current_safe:
                    safe_macros_global.add((my, mx))
                    self.board[my*2][mx*2] = self.target_color
                    self.blob_board[my*2][mx*2] = safe_blob_id
                    self.board[my*2][mx*2+1] = self.target_color
                    self.blob_board[my*2][mx*2+1] = safe_blob_id
                    self.board[my*2+1][mx*2] = self.target_color
                    self.blob_board[my*2+1][mx*2] = safe_blob_id
                    self.board[my*2+1][mx*2+1] = self.target_color
                    self.blob_board[my*2+1][mx*2+1] = safe_blob_id

    def evaluate_floor(self):
        self.audio.stop_bgm()
        wrong_tiles_pressed = 0
        correct_tiles_pressed = 0
        wrong_blobs_stepped = set()
        correct_blobs_stepped = set()

        with self.lock:
            for i in range(512):
                if self.button_states[i]:
                    channel = i // 64
                    idx_in_channel = i % 64
                    r_in_c = idx_in_channel // 16
                    c_raw = idx_in_channel % 16
                    x = c_raw if r_in_c % 2 == 0 else 15 - c_raw
                    y = (channel * 4) + r_in_c
                    stepped_color = self.board[y][x]

                    if stepped_color != self.target_color:
                        wrong_tiles_pressed += 1
                        wrong_blobs_stepped.add(self.blob_board[y][x])
                    else:
                        correct_tiles_pressed += 1
                        correct_blobs_stepped.add(self.blob_board[y][x])

            if wrong_tiles_pressed > 0:
                # NO PENALTY - The score no longer decreases
                self.audio.play('error')
                self.frozen_board = [row[:] for row in self.board]
                self.error_blobs = list(wrong_blobs_stepped)
                self.correct_blobs = list(correct_blobs_stepped) 
                self.state = 'ROUND_OVER_ERROR'

            elif correct_tiles_pressed > 0:
                # ROUND-BASED SCORE SCALING (10 base points + 5 extra per round)
                points_earned = int(20 * math.sqrt(self.round))
                self.score += points_earned
                self.audio.play('win')
                self.round += 1

                for y in range(BOARD_HEIGHT):
                    for x in range(BOARD_WIDTH):
                        if self.board[y][x] != self.target_color:
                            self.board[y][x] = BLACK
                self.state = 'ROUND_OVER'

            else:
                self.audio.play('error')
                for y in range(BOARD_HEIGHT):
                    for x in range(BOARD_WIDTH):
                        self.board[y][x] = BLACK
                self.state = 'ROUND_OVER'

            if self.global_timer > 3:
                threading.Timer(3.0, self.start_round).start()

    def finish_game(self):
        with self.lock:
            self.state = 'GAME_FINISHED'
            self.audio.stop_bgm()
            self.audio.play('win')
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    self.board[y][x] = WHITE

    def draw_branding(self, t):
        for y in range(BOARD_HEIGHT):
            for x in range(BOARD_WIDTH):
                self.board[y][x] = (10, 0, 20)
        curr_y = 2
        for char in TEXT_BRAND:
            if char in FONT_LEDITALL:
                glyph = FONT_LEDITALL[char]
                char_width = len(glyph[0])
                for r_idx, row in enumerate(glyph):
                    for c_idx, pixel in enumerate(row):
                        if pixel == '#':
                            board_y = curr_y + c_idx
                            board_x = 10 - r_idx
                            ratio = board_y / 31.0
                            if ratio < 0.5:
                                p = ratio * 2.0
                                r_base = int(255 + p * (138 - 255))
                                g_base = int(20 + p * (43 - 20))
                                b_base = int(147 + p * (226 - 147))
                            else:
                                p = (ratio - 0.5) * 2.0
                                r_base = int(138 + p * (0 - 138))
                                g_base = int(43 + p * (191 - 43))
                                b_base = int(226 + p * (255 - 226))

                            wave = (math.sin(board_x * 0.5 + board_y * 0.5 - t * 8.0) + 1) / 2
                            intensity = 0.3 + (wave * 0.7)
                            r = int(r_base * intensity)
                            g = int(g_base * intensity)
                            b = int(b_base * intensity)
                            if 0 <= board_y < BOARD_HEIGHT and 0 <= board_x < BOARD_WIDTH:
                                self.board[board_y][board_x] = (r, g, b)
                curr_y += char_width + 1

    def tick(self):
        if self.state == 'WAITING_TO_START' or self.state == 'GAME_FINISHED':
            return

        now = time.time()
        dt = now - self.last_tick_time
        self.last_tick_time = now

        if self.state == 'BRANDING_SEQUENCE':
            self.sequence_timer -= dt
            with self.lock:
                self.draw_branding(time.time())
            if self.sequence_timer <= 0:
                self.state = 'START_SEQUENCE'
                self.sequence_timer = 6.0 
            return

        if self.state == 'START_SEQUENCE':
            self.sequence_timer -= dt
            if self.sequence_timer > 3.0:
                with self.lock:
                    t = time.time()
                    for y in range(BOARD_HEIGHT):
                        ratio = y / 31.0
                        if ratio < 0.5:
                            p = ratio * 2.0
                            r_base = int(255 + p * (138 - 255))
                            g_base = int(20 + p * (43 - 20))
                            b_base = int(147 + p * (226 - 147))
                        else:
                            p = (ratio - 0.5) * 2.0
                            r_base = int(138 + p * (0 - 138))
                            g_base = int(43 + p * (191 - 43))
                            b_base = int(226 + p * (255 - 226))

                        for x in range(BOARD_WIDTH):
                            wave = (math.sin(x * 0.5 + y * 0.5 - t * 8.0) + 1) / 2
                            intensity = 0.1 + (wave * 0.9)
                            r = int(r_base * intensity)
                            g = int(g_base * intensity)
                            b = int(b_base * intensity)
                            self.board[y][x] = (r, g, b)

            else:
                current_digit = int(math.ceil(self.sequence_timer))
                if current_digit != self.last_seq_sec and current_digit > 0:
                    if current_digit == 3:          
                        self.audio.stop_bgm()       
                    self.audio.play('tick')
                    self.last_seq_sec = current_digit

                    with self.lock:
                        for y in range(BOARD_HEIGHT):
                            for x in range(BOARD_WIDTH):
                                self.board[y][x] = (10, 0, 20)

                        if current_digit in DIGITS:
                            template = DIGITS[current_digit]
                            start_x, start_y = 13, 12
                            digit_color = WHITE
                            if current_digit == 3:
                                digit_color = MAGENTA
                            elif current_digit == 2:
                                digit_color = PINK
                            elif current_digit == 1:
                                digit_color = CYAN
                            for row_idx, row_str in enumerate(template):
                                for col_idx, char in enumerate(row_str):
                                    if char == '#':
                                        px = start_x - row_idx * 2
                                        py = start_y + col_idx * 2
                                        if 0 <= py < BOARD_HEIGHT and 0 <= px < BOARD_WIDTH:
                                            self.board[py][px] = digit_color
                                        if 0 <= py < BOARD_HEIGHT and 0 <= px+1 < BOARD_WIDTH:
                                            self.board[py][px+1] = digit_color
                                        if 0 <= py+1 < BOARD_HEIGHT and 0 <= px < BOARD_WIDTH:
                                            self.board[py+1][px] = digit_color
                                        if 0 <= py+1 < BOARD_HEIGHT and 0 <= px+1 < BOARD_WIDTH:
                                            self.board[py+1][px+1] = digit_color

            if self.sequence_timer <= 0:
                self.start_game_logic()
            return

        self.global_timer -= dt
        current_minute = int(self.global_timer // 60)

        if current_minute != self.last_printed_minute and current_minute >= 0:
            self.last_printed_minute = current_minute
        if self.global_timer <= 0:
            self.finish_game()
            return
        if self.state == 'SHOW_TARGET':
            self.round_timer -= dt
            if self.round_timer <= 0:
                self.generate_blocks()
                self.state = 'PLAYING'
                self.round_timer = max(2.5, 6.4 - (self.round * 0.4))
                self.last_second_beep = int(math.ceil(self.round_timer))
                self.audio.play_bgm()

        elif self.state == 'PLAYING':
            self.round_timer -= dt
            current_sec = int(math.ceil(self.round_timer))
            if current_sec != self.last_second_beep and current_sec > 0 and current_sec <= 3:
                self.audio.play('tick')
            if current_sec != self.last_second_beep:
                self.last_second_beep = current_sec
            if self.round_timer <= 0:
                self.evaluate_floor()

        elif self.state == 'ROUND_OVER_ERROR':
            with self.lock:
                t = time.time()
                is_red = int(t * 6) % 2 == 0 
                for y in range(BOARD_HEIGHT):
                    for x in range(BOARD_WIDTH):
                        current_blob_id = self.blob_board[y][x]
                        if current_blob_id in self.error_blobs:
                            self.board[y][x] = RED if is_red else BLACK
                        elif current_blob_id in self.correct_blobs:
                            self.board[y][x] = self.target_color
                        else:
                            self.board[y][x] = BLACK

    def render(self):
        buffer = bytearray(FRAME_DATA_LENGTH)
        with self.lock:
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    self.set_led(buffer, x, y, self.board[y][x])
            if self.state == 'GAME_FINISHED':
                if int(time.time() * 4) % 2 == 0:
                    for i in range(len(buffer)): buffer[i] = 0
        return buffer

    def set_led(self, buffer, x, y, color):
        if x < 0 or x >= 16 or y < 0 or y >= 32: return
        channel = y // 4
        row_in_channel = y % 4
        led_index = row_in_channel * 16 + x if row_in_channel % 2 == 0 else row_in_channel * 16 + (15 - x)
        offset = led_index * (NUM_CHANNELS * 3) + channel
        if offset + NUM_CHANNELS*2 < len(buffer):
            buffer[offset] = color[1]   
            buffer[offset + NUM_CHANNELS] = color[0]
            buffer[offset + NUM_CHANNELS*2] = color[2]

# --- Network Manager ---
class NetworkManager:
    def __init__(self, game):
        self.game = game
        self.sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.running = True
        self.sequence_number = 0
        try:
            self.sock_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock_recv.bind(("0.0.0.0", UDP_LISTEN_PORT))
        except:
            pass

    def send_loop(self):
        while self.running:
            frame = self.game.render()
            self.send_packet(frame)
            time.sleep(0.05)

    def send_packet(self, frame_data):
        self.sequence_number = (self.sequence_number + 1) & 0xFFFF
        if self.sequence_number == 0:
            self.sequence_number = 1
        port = UDP_SEND_PORT
        sp = bytearray([0x75, random.randint(0,127), random.randint(0,127), 0x00, 0x08, 0x02, 0x00, 0x00, 0x33, 0x44, (self.sequence_number >> 8) & 0xFF, self.sequence_number & 0xFF, 0x00, 0x00, 0x00, 0x0E, 0x00])
        try:
            self.sock_send.sendto(sp, (UDP_SEND_IP, port))
            self.sock_send.sendto(sp, ("127.0.0.1", port))
        except:
            pass

        f_p = bytearray()
        for _ in range(NUM_CHANNELS): 
            f_p += bytes([(LEDS_PER_CHANNEL >> 8) & 0xFF, LEDS_PER_CHANNEL & 0xFF])
        f_i = bytearray([0x02, 0x00, 0x00, 0x88, 0x77, 0xFF, 0xF0, (len(f_p) >> 8) & 0xFF, (len(f_p) & 0xFF)]) + f_p
        f_pkt = bytearray([0x75, random.randint(0,127), random.randint(0,127), ((len(f_i)-1) >> 8) & 0xFF, ((len(f_i)-1) & 0xFF)]) + f_i + bytearray([0x1E, 0x00])
        try:
            self.sock_send.sendto(f_pkt, (UDP_SEND_IP, port))
            self.sock_send.sendto(f_pkt, ("127.0.0.1", port))
        except:
            pass
        chunk_size = 984 
        d_idx = 1

        for i in range(0, len(frame_data), chunk_size):
            chk = frame_data[i:i+chunk_size]
            d_i = bytearray([0x02, 0x00, 0x00, 0x88, 0x77, (d_idx >> 8) & 0xFF, d_idx & 0xFF, (len(chk) >> 8) & 0xFF, (len(chk) & 0xFF)]) + chk
            d_pkt = bytearray([0x75, random.randint(0,127), random.randint(0,127), ((len(d_i)-1) >> 8) & 0xFF, ((len(d_i)-1) & 0xFF)]) + d_i
            d_pkt.append(0x1E if len(chk) == 984 else 0x36)
            d_pkt.append(0x00)
            try:
                self.sock_send.sendto(d_pkt, (UDP_SEND_IP, port))
                self.sock_send.sendto(d_pkt, ("127.0.0.1", port))
            except:
                pass

            d_idx += 1
            time.sleep(0.005)

        ep = bytearray([0x75, random.randint(0,127), random.randint(0,127), 0x00, 0x08, 0x02, 0x00, 0x00, 0x55, 0x66, (self.sequence_number >> 8) & 0xFF, self.sequence_number & 0xFF, 0x00, 0x00, 0x00, 0x0E, 0x00])
        try:
            self.sock_send.sendto(ep, (UDP_SEND_IP, port))
            self.sock_send.sendto(ep, ("127.0.0.1", port))
        except:
            pass

    def recv_loop(self):
        while self.running:
            try:
                data, _ = self.sock_recv.recvfrom(2048)
                if len(data) >= 1373 and data[0] == 0x88:
                    for c in range(8):
                        offset = 2 + (c * 171) + 1 
                        for i, val in enumerate(data[offset : offset + 64]):
                            self.game.button_states[(c * 64) + i] = (val == 0xCC)
            except:
                pass

# --- Dashboard Class (Monitor 2) ---
class Dashboard:
    def __init__(self, game):
        self.game = game
        self.running = True
        self.screen = None
        self.font_large = None
        self.font_medium = None
        self.font_small = None
        self.clock = None
        self.bg_stars = []
        for _ in range(150):
            x = random.randint(0, 4000)
            y = random.randint(0, 3000)
            radius = random.randint(5, 20)
            color_idx = random.randint(0, 3)
            self.bg_stars.append({"x": x, "y": y, "r": radius, "c": color_idx, "base_a": random.random() * math.pi})

    def format_time(self, seconds):
        if seconds <= 0:
            return "00:00"
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m:02d}:{s:02d}"

    def draw_full_background(self, surface, w, h):
        """Draws the background sprinkled with star polygons"""
        surface.fill((18, 18, 24))
        colors = [(139, 233, 253), (80, 250, 123), (255, 121, 198), (241, 250, 140)]
        t = time.time()

        for star in self.bg_stars:
            if star["x"] > w or star["y"] > h:
                continue
            # Subtle pulsation
            alpha = (math.sin(t * 2 + star["base_a"]) + 1) / 2 * 0.5 + 0.1 
            base_color = colors[star["c"]]
            r = int(base_color[0] * alpha + 18 * (1 - alpha))
            g = int(base_color[1] * alpha + 18 * (1 - alpha))
            b = int(base_color[2] * alpha + 24 * (1 - alpha))
            points = get_star_points(star["x"], star["y"], star["r"])
            pygame.draw.polygon(surface, (r, g, b), points)

    def run(self):
        if not PYGAME_AVAILABLE:
            return
        if not pygame.get_init():
            pygame.init()
        num_displays = pygame.display.get_num_displays()
        target_display = DASHBOARD_MONITOR if num_displays > DASHBOARD_MONITOR else 0

        if DASHBOARD_FULLSCREEN:
            # Use (0,0) with FULLSCREEN to automatically pick the monitor's native resolution
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN, display=target_display)
        else:
            self.screen = pygame.display.set_mode((800, 600), pygame.RESIZABLE, display=target_display)
        pygame.display.set_caption("Block Party - Score (Monitor 2)")

        try:
            self.font_large = pygame.font.SysFont("courier", 140, bold=True)
            self.font_medium = pygame.font.SysFont("courier", 60, bold=True)
            self.font_small = pygame.font.SysFont("courier", 50, bold=True)
        except:
            self.font_large = pygame.font.Font(None, 140)
            self.font_medium = pygame.font.Font(None, 60)
            self.font_small = pygame.font.Font(None, 50)

        self.clock = pygame.time.Clock()
        while self.running and self.game.running:
            screen_width, screen_height = self.screen.get_size()
            center_x = screen_width // 2
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    self.game.running = False 
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
                        self.game.running = False
            # Background with just polygonal stars
            self.draw_full_background(self.screen, screen_width, screen_height)
            with self.game.lock:
                score = self.game.score
                round_num = self.game.round
                time_left = self.game.global_timer
                state = self.game.state
            # --- HEADER FOR STATUS ---
            pygame.draw.rect(self.screen, (30, 30, 42), (0, 0, screen_width, screen_height * 0.2))
            pygame.draw.line(self.screen, (50, 50, 70), (0, screen_height * 0.2), (screen_width, screen_height * 0.2), 4)

            if getattr(self.game, 'is_paused', False):
                status_text = "PAUSE"
                status_color = (255, 204, 0)
            elif state == 'WAITING_TO_START':
                status_text = "WAITING TO START"
                status_color = (150, 150, 160)
            elif state == 'GAME_FINISHED':
                status_text = "GAME OVER"
                status_color = (255, 85, 85)
            else:
                status_text = f"ROUND {round_num}"
                status_color = (80, 250, 123)

            surf_status_shadow = self.font_small.render(status_text, True, (0, 0, 0))
            surf_status = self.font_small.render(status_text, True, status_color)
            status_rect = surf_status.get_rect(center=(center_x, screen_height * 0.1))
            self.screen.blit(surf_status_shadow, status_rect.move(3, 3))
            self.screen.blit(surf_status, status_rect)

            # --- TIME PANEL ---
            time_panel_rect = pygame.Rect(0, 0, min(screen_width * 0.7, 650), screen_height * 0.32)
            time_panel_rect.center = (center_x, screen_height * 0.42)

            pygame.draw.rect(self.screen, (25, 25, 35), time_panel_rect, border_radius=20)
            pygame.draw.rect(self.screen, (60, 60, 80), time_panel_rect, width=3, border_radius=20)

            time_str = self.format_time(time_left)
            time_color = (255, 85, 85) if time_left > 0 and time_left < 60 else (248, 248, 242)

            surf_time_label = self.font_medium.render("TIME LEFT:", True, (150, 150, 170))
            surf_time = self.font_large.render(time_str, True, time_color)
            surf_time_shadow = self.font_large.render(time_str, True, (0, 0, 0))

            # ABSOLUTE centering inside the time panel
            time_label_rect = surf_time_label.get_rect(center=(time_panel_rect.centerx, time_panel_rect.top + time_panel_rect.height * 0.25))
            time_rect = surf_time.get_rect(center=(time_panel_rect.centerx, time_panel_rect.bottom - time_panel_rect.height * 0.35))

            self.screen.blit(surf_time_label, time_label_rect)
            self.screen.blit(surf_time_shadow, time_rect.move(4, 4)) 
            self.screen.blit(surf_time, time_rect)

            # --- SCORE PANEL ---
            score_panel_rect = pygame.Rect(0, 0, min(screen_width * 0.7, 650), screen_height * 0.32)
            score_panel_rect.center = (center_x, screen_height * 0.78)

            pygame.draw.rect(self.screen, (25, 25, 35), score_panel_rect, border_radius=20)
            pygame.draw.rect(self.screen, (60, 60, 80), score_panel_rect, width=3, border_radius=20)

            surf_score_label = self.font_medium.render("SCORE:", True, (150, 150, 170))
            surf_score = self.font_large.render(f"{score}", True, (139, 233, 253))
            surf_score_shadow = self.font_large.render(f"{score}", True, (0, 0, 0))

            # ABSOLUTE centering inside the score panel
            score_label_rect = surf_score_label.get_rect(center=(score_panel_rect.centerx, score_panel_rect.top + score_panel_rect.height * 0.25))
            score_rect = surf_score.get_rect(center=(score_panel_rect.centerx, score_panel_rect.bottom - score_panel_rect.height * 0.35))

            self.screen.blit(surf_score_label, score_label_rect)
            self.screen.blit(surf_score_shadow, score_rect.move(4, 4))
            self.screen.blit(surf_score, score_rect)
            pygame.display.flip()
            self.clock.tick(30)

        pygame.quit()

if __name__ == "__main__":
    game = PhysicalBlockParty()
    game.is_paused = False 
    net = NetworkManager(game)
    threading.Thread(target=net.send_loop, daemon=True).start()
    threading.Thread(target=net.recv_loop, daemon=True).start()

    # --- Logic loop allowing PAUSE ---
    def logic_loop():
        while game.running:
            if getattr(game, 'is_paused', False):
                game.last_tick_time = time.time()
            else:
                game.tick()
            time.sleep(0.01)
    threading.Thread(target=logic_loop, daemon=True).start()

    # --- Start the secondary screen in the background ---
    dashboard = Dashboard(game)
    threading.Thread(target=dashboard.run, daemon=True).start()

    # --- GRAPHICAL CONTROL INTERFACE (MONITOR 1) ---
    root = tk.Tk()
    root.title("Control Panel - Block Party")
    if DASHBOARD_FULLSCREEN:
        # This makes the Tkinter window cover the entire primary monitor
        root.attributes("-fullscreen", True)
        # SAFETY FEATURE: Pressing 'Escape' on the control panel exits fullscreen
        root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))
    else:
        root.geometry("1000x700")

    # Modern Dark Theme color palette
    BG_MAIN = "#121218" 
    BG_PANEL = "#282A36"
    BORDER_COLOR = "#44475A"
    TEXT_LIGHT = "#F8F8F2"
    COLOR_TIME = "#FF5555"
    COLOR_SCORE = "#8BE9FD"
    root.configure(bg=BG_MAIN)

    # Add huge width and height to prevent clipping of the initial window in Linux
    bg_canvas = tk.Canvas(root, bg=BG_MAIN, highlightthickness=0, width=4000, height=3000)
    bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
    tk_stars = []
    colors_rgb = [(139, 233, 253), (80, 250, 123), (255, 121, 198), (241, 250, 140)]
    def create_tk_star(canvas, x, y, radius, color_idx):
        points = get_star_points(x, y, radius)
        flat_points = [coord for point in points for coord in point]
        poly_id = canvas.create_polygon(*flat_points, fill="#000000", outline="")
        return {
            "id": poly_id,
            "c": colors_rgb[color_idx],
            "base_a": random.random() * math.pi
        }

    for _ in range(150): 
        x = random.randint(0, 4000)
        y = random.randint(0, 3000)
        r = random.randint(5, 20)
        c_idx = random.randint(0, 3)
        star_data = create_tk_star(bg_canvas, x, y, r, c_idx)
        tk_stars.append(star_data)

    def rgb_to_hex(r, g, b):
        return f"#{int(r):02x}{int(g):02x}{int(b):02x}"

    def update_tk_stars():
        if not game.running: return
        t = time.time()
        for star in tk_stars:

            # Same pulsation math as Pygame
            alpha = (math.sin(t * 2 + star["base_a"]) + 1) / 2 * 0.5 + 0.1 
            r = int(star["c"][0] * alpha + 18 * (1 - alpha))
            g = int(star["c"][1] * alpha + 18 * (1 - alpha))
            b = int(star["c"][2] * alpha + 24 * (1 - alpha))
            bg_canvas.itemconfig(star["id"], fill=rgb_to_hex(r, g, b))
        root.after(50, update_tk_stars)
    update_tk_stars()

    # Main container with margins and 'Card' style (central)
    main_container = tk.Frame(root, bg=BG_PANEL, bd=0, highlightthickness=3, highlightbackground=BORDER_COLOR, padx=80, pady=60)
    main_container.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    # Title
    lbl_title = tk.Label(main_container, text="BLOCK PARTY", font=("Helvetica", 65, "bold"), bg=BG_PANEL, fg=TEXT_LIGHT)
    lbl_title.pack(pady=(0, 40))

    # Time
    lbl_time = tk.Label(main_container, text="TIME: 00:00", font=("Consolas", 60, "bold"), bg=BG_PANEL, fg=COLOR_TIME)
    lbl_time.pack(pady=15)

    # Score
    lbl_score = tk.Label(main_container, text="SCORE: 0", font=("Consolas", 60, "bold"), bg=BG_PANEL, fg=COLOR_SCORE)
    lbl_score.pack(pady=(15, 40))

    def on_start():
        game.is_paused = False
        if PYGAME_AVAILABLE: pygame.mixer.music.unpause()
        btn_pause.config(text="PAUSE", bg="#FFB86C", fg=BG_PANEL)
        game.initiate_start_sequence()

    def on_pause():
        if game.state == 'WAITING_TO_START' or game.state == 'GAME_FINISHED':
            return
        game.is_paused = not getattr(game, 'is_paused', False)
        if game.is_paused:
            btn_pause.config(text="RESUME", bg="#F1FA8C", fg=BG_PANEL)
            if PYGAME_AVAILABLE: pygame.mixer.music.pause()
        else:
            btn_pause.config(text="PAUSE", bg="#FFB86C", fg=BG_PANEL)
            if PYGAME_AVAILABLE: pygame.mixer.music.unpause()

    # Button frame
    btn_frame = tk.Frame(main_container, bg=BG_PANEL)
    btn_frame.pack(pady=20)

    # Buttons with "Flat Design"
    btn_start = tk.Button(btn_frame, text="START", font=("Helvetica", 35, "bold"), 
                          bg="#50FA7B", fg=BG_PANEL, activebackground="#5af182", 
                          command=on_start, width=10, height=2, cursor="hand2", relief="flat")

    btn_start.pack(side=tk.LEFT, padx=30)
    btn_pause = tk.Button(btn_frame, text="PAUSE", font=("Helvetica", 35, "bold"), 
                          bg="#FFB86C", fg=BG_PANEL, activebackground="#ffc68a",
                          command=on_pause, width=10, height=2, cursor="hand2", relief="flat")

    btn_pause.pack(side=tk.RIGHT, padx=30)

    def update_gui():
        if game.running:
            secs = max(0, game.global_timer)
            m = int(secs // 60)
            s = int(secs % 60)
            lbl_time.config(text=f"TIME: {m:02d}:{s:02d}")
            lbl_score.config(text=f"SCORE: {game.score}")
            root.after(100, update_gui)
    update_gui()

    def on_closing():
        game.running = False
        dashboard.running = False
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

    # When you close the small window, clean up the rest
    net.running = False