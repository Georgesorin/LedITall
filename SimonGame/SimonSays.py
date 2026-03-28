import socket
import time
import threading
import random
import math
import os

# =========================================================
#                      CONFIGURATION
# =========================================================
def _load_config():
    return {
        "device_ip": "192.168.1.135",
        "send_port": 4227,
        "recv_port": 4444,
        "bind_ip": "0.0.0.0",
    }

CONFIG = _load_config()

UDP_SEND_IP = CONFIG.get("device_ip", "192.168.1.135")
UDP_SEND_PORT = CONFIG.get("send_port", 4227)
UDP_LISTEN_PORT = CONFIG.get("recv_port", 4444)

# =========================================================
#                      MATRIX CONSTANTS
# =========================================================
NUM_CHANNELS = 8
LEDS_PER_CHANNEL = 64
FRAME_DATA_LENGTH = NUM_CHANNELS * LEDS_PER_CHANNEL * 3

BOARD_WIDTH = 16
BOARD_HEIGHT = 32

GAME_DURATION_MINUTES = 3      # N minute tot jocul
ROUND_DURATION_SECONDS = 6     # M secunde pentru fiecare rundă

BLACK   = (0, 0, 0)
WHITE   = (220, 220, 220)

RED     = (255, 60, 60)
GREEN   = (60, 255, 60)
BLUE    = (60, 60, 255)
YELLOW  = (255, 255, 60)
MAGENTA = (255, 60, 255)
CYAN    = (60, 255, 255)
ORANGE  = (255, 140, 40)
PURPLE  = (170, 70, 255)
PINK    = (255, 100, 180)
BROWN   = (121, 85, 72)
AQUA    = (80, 220, 255)
GOLD    = (255, 200, 40)

BORDER_COLOR = (120, 255, 0)

WAVE_RED_1   = (70, 8, 16)
WAVE_RED_2   = (105, 12, 30)
WAVE_PINK_1  = (70, 18, 42)
WAVE_PINK_2  = (110, 28, 58)

FONT_3X5 = {
    "L": ["100","100","100","100","111"],
    "e": ["000","111","110","100","111"],
    "d": ["001","111","101","101","111"],
    "I": ["111","010","010","010","111"],
    "T": ["111","010","010","010","010"],
    "a": ["000","111","001","111","111"],
    "l": ["010","010","010","010","011"],
    "space": ["000","000","000","000","000"]
}

FONT_5X7 = {
    "A": ["01110","10001","10001","11111","10001","10001","10001"],
    "D": ["11110","10001","10001","10001","10001","10001","11110"],
    "E": ["11111","10000","10000","11110","10000","10000","11111"],
    "I": ["11111","00100","00100","00100","00100","00100","11111"],
    "L": ["10000","10000","10000","10000","10000","10000","11111"],
    "T": ["11111","00100","00100","00100","00100","00100","00100"],
    "a": ["00000","00000","01110","00001","01111","10001","01111"],
    "d": ["00001","00001","01111","10001","10001","10001","01111"],
    "e": ["00000","00000","01110","10001","11111","10000","01110"],
    "l": ["00100","00100","00100","00100","00100","00100","00011"],
    "space": ["000","000","000","000","000","000","000"],
    "1": ["00100","01100","00100","00100","00100","00100","01110"],
    "2": ["01110","10001","00001","00010","00100","01000","11111"],
    "3": ["11110","00001","00001","01110","00001","00001","11110"]
}


# =========================================================
#                         SIMON GAME
# =========================================================
class SimonGame:
    def __init__(self):
        self.board = [[BLACK for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
        self.running = True
        self.lock = threading.RLock()

        # stări butoane hardware
        self.button_states = [False] * 512
        self.prev_button_states = [False] * 512

        self.tile_w = 4
        self.tile_h = 1

        # 12 tile-uri, împărțite în 4 blocuri a câte 3:
        # - stânga sus
        # - dreapta sus
        # - stânga jos
        # - dreapta jos
        #
        # toate orientate din margine spre centru
        self.tiles = [
            # STÂNGA SUS
            {"id": 0,  "x": 3,  "y": 4,  "w": 4, "h": 1, "color": RED},
            {"id": 1,  "x": 3,  "y": 6,  "w": 4, "h": 1, "color": GREEN},
            {"id": 2,  "x": 3,  "y": 8,  "w": 4, "h": 1, "color": BLUE},

            # DREAPTA SUS
            {"id": 3,  "x": 9, "y": 4,  "w": 4, "h": 1, "color": YELLOW},
            {"id": 4,  "x": 9, "y": 6,  "w": 4, "h": 1, "color": MAGENTA},
            {"id": 5,  "x": 9, "y": 8,  "w": 4, "h": 1, "color": AQUA},

            # STÂNGA JOS
            {"id": 6,  "x": 3,  "y": 23, "w": 4, "h": 1, "color": CYAN},
            {"id": 7,  "x": 3,  "y": 25, "w": 4, "h": 1, "color": ORANGE},
            {"id": 8,  "x": 3,  "y": 27, "w": 4, "h": 1, "color": PURPLE},

            # DREAPTA JOS
            {"id": 9,  "x": 9, "y": 23, "w": 4, "h": 1, "color": PINK},
            {"id": 10, "x": 9, "y": 25, "w": 4, "h": 1, "color": BROWN},
            {"id": 11, "x": 9, "y": 27, "w": 4, "h": 1, "color": GOLD},
        ]

        # stare joc
        self.sequence = []
        self.player_index = 0
        self.level = 0
        self.state = "idle"

        self.game_duration_sec = GAME_DURATION_MINUTES * 60
        self.round_duration_sec = ROUND_DURATION_SECONDS

        self.game_start_time = None
        self.game_end_time = None
        self.round_deadline = None
        self.last_clock_visible_segments = -1

        # multiplayer / anti-repeat per tile
        self.pressed_tiles = set()   # tile-uri considerate apăsate activ

        # NU mai pornim jocul direct aici
        self.clear_board()

    # -----------------------------------------------------
    #                    DRAW FUNCTIONS
    # -----------------------------------------------------
    def clear_board(self):
        with self.lock:
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    self.board[y][x] = BLACK

    def fill_board(self, color):
        with self.lock:
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    self.board[y][x] = color

    def draw_border(self, color=BORDER_COLOR):
        with self.lock:
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    if x < 2 or x >= BOARD_WIDTH - 2 or y < 2 or y >= BOARD_HEIGHT - 2:
                        self.board[y][x] = color
    
    def draw_sequence_background(self):
        self.clear_board()
        self.draw_border()

    def draw_tile(self, tile, color=None):
        c = color if color is not None else tile["color"]
        x0 = tile["x"]
        y0 = tile["y"]
        w = tile.get("w", 2)
        h = tile.get("h", 2)

        with self.lock:
            for dy in range(h):
                for dx in range(w):
                    x = x0 + dx
                    y = y0 + dy
                    if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT:
                        self.board[y][x] = c

    def draw_all_tiles(self, dim=False):
        self.redraw_game_scene(dim=dim)

    def flash_tile(self, tile_id, duration=0.25):
        self.draw_sequence_background()

        tile = self.tiles[tile_id]
        self.draw_tile(tile, tile["color"])
        time.sleep(duration)

        self.draw_sequence_background()
        time.sleep(0.08)

    def flash_all(self, color=WHITE, times=2, on_time=0.18, off_time=0.12):
        for _ in range(times):
            self.fill_board(color)
            time.sleep(on_time)
            self.clear_board()
            time.sleep(off_time)

    # -----------------------------------------------------
    #                    INTRO FUNCTIONS
    # -----------------------------------------------------
    def get_char_bitmap_from_font(self, ch, font):
        if ch in font:
            return font[ch]
        if ch.upper() in font:
            return font[ch.upper()]
        return font["space"]

    def build_text_bitmap_with_font(self, text, font, spacing=1):
        char_height = len(next(iter(font.values())))
        rows = [[] for _ in range(char_height)]

        for i, ch in enumerate(text):
            bmp = self.get_char_bitmap_from_font(ch, font)

            for r in range(char_height):
                rows[r].extend(1 if px == "1" else 0 for px in bmp[r])

            if i != len(text) - 1:
                for r in range(char_height):
                    rows[r].extend([0] * spacing)

        return rows

    def blend(self, c1, c2, t):
        return (
            int(c1[0] * (1 - t) + c2[0] * t),
            int(c1[1] * (1 - t) + c2[1] * t),
            int(c1[2] * (1 - t) + c2[2] * t)
        )

    def dim_color(self, c, factor):
        return (
            max(0, min(255, int(c[0] * factor))),
            max(0, min(255, int(c[1] * factor))),
            max(0, min(255, int(c[2] * factor))),
        )

    def put_pixel(self, x, y, color):
        if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT:
            self.board[y][x] = color

    def redraw_game_scene(self, dim=False):
        self.clear_board()
        self.draw_border()

        for tile in self.tiles:
            if dim:
                c = tuple(max(20, v // 5) for v in tile["color"])
                self.draw_tile(tile, c)
            else:
                self.draw_tile(tile)

        if self.state == "input":
            self.draw_clock_pie(
                self.get_clock_segments_for_round(),
                color=YELLOW,
                off_color=BLACK
            )

    def draw_clock_pie(self, visible_segments=None, color=YELLOW, off_color=BLACK):
        """
        Ceas circular 10x10.
        visible_segments:
            8 = cerc complet
            7 = lipsește 1/8
            6 = lipsesc 2/8
            ...
            0 = gol complet

        Feliile dispar în sens orar, pornind de sus (ora 12),
        exact ca un pie chart / tort tăiat.
        """
        if visible_segments is None:
            visible_segments = 8

        visible_segments = max(0, min(8, visible_segments))
        missing_segments = 8 - visible_segments

        # top-left pentru un cerc 10x10 centrat pe board 16x32
        origin_x = 3
        origin_y = 11

        # centru local al cercului 10x10
        cx = 4.5
        cy = 4.5
        radius = 4.6

        for ly in range(10):
            for lx in range(10):
                dx = lx - cx
                dy = ly - cy
                dist = math.sqrt(dx * dx + dy * dy)

                # desenăm doar pixelii din cerc
                if dist <= radius:
                    # unghi:
                    # 0° = sus
                    # crește în sens orar
                    angle = (math.degrees(math.atan2(dx, -dy)) + 360.0) % 360.0

                    # 8 sectoare a câte 45°
                    sector = int(angle // 45.0)  # 0..7

                    # Scoatem feliile în ordine:
                    # 0 = sus -> sus-dreapta -> dreapta -> ...
                    px = origin_x + lx
                    py = origin_y + ly

                    if sector < missing_segments:
                        self.put_pixel(px, py, off_color)
                    else:
                        self.put_pixel(px, py, color)

    def get_round_time_left(self):
        if self.round_deadline is None:
            return self.round_duration_sec
        return max(0.0, self.round_deadline - time.time())

    def get_game_time_left(self):
        if self.game_end_time is None:
            return self.game_duration_sec
        return max(0.0, self.game_end_time - time.time())

    def get_clock_segments_for_round(self):
        if self.state != "input":
            return 8

        total = self.get_round_duration()
        left = self.get_round_time_left()

        ratio = 0.0 if total <= 0 else (left / total)
        segments = math.ceil(ratio * 8)

        return max(0, min(8, segments))

    def get_char_bitmap(self, ch):
        if ch in FONT_5X7:
            return FONT_5X7[ch]
        if ch.upper() in FONT_5X7:
            return FONT_5X7[ch.upper()]
        return FONT_5X7["space"]

    def rotate_bitmap_90(self, bitmap_rows, clockwise=True):
        """
        bitmap_rows: list de rânduri, ex. [[0,1,1], [1,0,1], ...]
        returnează bitmap rotit la 90°
        """
        if not bitmap_rows or not bitmap_rows[0]:
            return bitmap_rows

        h = len(bitmap_rows)
        w = len(bitmap_rows[0])

        if clockwise:
            # noul bitmap va avea w rânduri, fiecare de lungime h
            return [
                [bitmap_rows[h - 1 - y][x] for y in range(h)]
                for x in range(w)
            ]
        else:
            return [
                [bitmap_rows[y][w - 1 - x] for y in range(h)]
                for x in range(w)
            ]

    def build_text_bitmap(self, text, spacing=1):
        rows = [[] for _ in range(7)]

        for i, ch in enumerate(text):
            bmp = self.get_char_bitmap(ch)
            width = len(bmp[0])

            for r in range(7):
                rows[r].extend(1 if px == "1" else 0 for px in bmp[r])

            if i != len(text) - 1:
                for r in range(7):
                    rows[r].extend([0] * spacing)

        return rows

    def draw_text_bitmap(self, bitmap_rows, offset_x, offset_y, color=WHITE):
        with self.lock:
            for y in range(len(bitmap_rows)):
                row = bitmap_rows[y]
                for x in range(len(row)):
                    if row[x]:
                        xx = x + offset_x
                        yy = y + offset_y
                        if 0 <= xx < BOARD_WIDTH and 0 <= yy < BOARD_HEIGHT:
                            self.board[yy][xx] = color

    def draw_wave_background(self, phase=0.0):
        with self.lock:
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    v1 = math.sin((y * 0.42) + phase + (x * 0.18))
                    v2 = math.sin((x * 0.75) - (phase * 1.2) + (y * 0.12))
                    mix = (v1 + v2 + 2.0) / 4.0  # 0..1

                    if mix < 0.33:
                        col = self.blend(BLACK, WAVE_RED_1, mix / 0.33)
                    elif mix < 0.66:
                        col = self.blend(WAVE_RED_1, WAVE_PINK_1, (mix - 0.33) / 0.33)
                    else:
                        col = self.blend(WAVE_PINK_1, WAVE_PINK_2, (mix - 0.66) / 0.34)

                    # îl facem soft
                    col = self.dim_color(col, 0.75)
                    self.board[y][x] = col

    def run_intro(self):
        self.state = "intro"
        text = "  LedITall  "

        # -----------------------------
        # 1) SCROLL - fontul vechi 5x7
        # -----------------------------
        bitmap_scroll = self.build_text_bitmap(text, spacing=1)
        bitmap_scroll = self.rotate_bitmap_90(bitmap_scroll, clockwise=True)

        scroll_width = len(bitmap_scroll[0])
        scroll_height = len(bitmap_scroll)

        text_x = (BOARD_WIDTH - scroll_width) // 2

        for offset_y in range(BOARD_HEIGHT, -scroll_height - 1, -1):
            if not self.running:
                return

            self.draw_wave_background(phase=time.time() * 2.4)
            self.draw_text_bitmap(bitmap_scroll, text_x, offset_y, color=WHITE)
            time.sleep(0.05)

        # -------------------------------------
        # 2) POP FINAL - font mic 3x5
        # -------------------------------------
        final_text = "LedITall"
        bitmap_final = self.build_text_bitmap_with_font(final_text, FONT_3X5, spacing=1)
        bitmap_final = self.rotate_bitmap_90(bitmap_final, clockwise=True)

        final_width = len(bitmap_final[0])
        final_height = len(bitmap_final)

        final_x = (BOARD_WIDTH - final_width) // 2
        final_y = (BOARD_HEIGHT - final_height) // 2

        for _ in range(20):
            if not self.running:
                return

            self.draw_wave_background(phase=time.time() * 2.4)
            self.draw_text_bitmap(bitmap_final, final_x, final_y, color=WHITE)
            time.sleep(0.05)

        self.run_countdown()
        self.start_new_game()
        
    def play_intro_then_start_async(self):
        t = threading.Thread(target=self.run_intro, daemon=True)
        t.start()

    def show_centered_text(self, text, color=WHITE, duration=0.7, with_wave=True):
        bitmap = self.build_text_bitmap(text, spacing=1)
        bitmap = self.rotate_bitmap_90(bitmap, clockwise=True)

        w = len(bitmap[0])
        h = len(bitmap)

        x = (BOARD_WIDTH - w) // 2
        y = (BOARD_HEIGHT - h) // 2

        end_time = time.time() + duration
        while time.time() < end_time and self.running:
            if with_wave:
                self.draw_wave_background(phase=time.time() * 2.4)
            else:
                self.clear_board()
            self.draw_text_bitmap(bitmap, x, y, color=color)
            time.sleep(0.05)

    def run_countdown(self):
        self.state = "countdown"

        items = [
            ("3", 0.75),
            ("2", 0.75),
            ("1", 0.75),
        ]

        start_time = time.time()
        total = sum(duration for _, duration in items)

        bitmap_cache = {}
        elapsed_limits = []
        acc = 0.0
        for text, duration in items:
            acc += duration
            elapsed_limits.append((text, acc))

            bitmap = self.build_text_bitmap(text, spacing=1)
            bitmap = self.rotate_bitmap_90(bitmap, clockwise=True)
            bitmap_cache[text] = bitmap

        while self.running:
            elapsed = time.time() - start_time
            if elapsed >= total:
                break

            current_text = "1"
            for text, limit in elapsed_limits:
                if elapsed < limit:
                    current_text = text
                    break

            bitmap = bitmap_cache[current_text]
            w = len(bitmap[0])
            h = len(bitmap)

            x = (BOARD_WIDTH - w) // 2
            y = (BOARD_HEIGHT - h) // 2

            self.draw_wave_background(phase=time.time() * 2.4)
            self.draw_text_bitmap(bitmap, x, y, color=WHITE)
            time.sleep(0.05)

    # -----------------------------------------------------
    #                     GAME FLOW
    # -----------------------------------------------------
    def start_new_game(self):
        self.sequence = []
        self.player_index = 0
        self.level = 0
        self.pressed_tiles.clear()

        self.game_start_time = time.time()
        self.game_end_time = self.game_start_time + self.game_duration_sec
        self.round_deadline = None
        self.last_clock_visible_segments = -1

        self.add_random_step()
        self.show_sequence_async()
    def add_random_step(self):
        self.sequence.append(random.randint(0, len(self.tiles) - 1))
        self.level = len(self.sequence)

    def show_sequence_async(self):
        self.state = "showing"
        self.player_index = 0
        self.pressed_tiles.clear()

        t = threading.Thread(target=self.run_show_sequence, daemon=True)
        t.start()

    def run_show_sequence(self):
        self.draw_sequence_background()
        time.sleep(0.18)

        for tile_id in self.sequence:
            self.flash_tile(tile_id, duration=0.42)

        self.draw_all_tiles(dim=False)
        self.round_deadline = time.time() + self.get_round_duration()
        self.state = "input"

    def success_async(self):
        self.state = "success"
        t = threading.Thread(target=self.run_success, daemon=True)
        t.start()

    def run_success(self):
        self.state = "success"
        self.round_deadline = None
        self.last_clock_visible_segments = -1

        self.flash_all(color=GREEN, times=2, on_time=0.18, off_time=0.12)

        if self.get_game_time_left() <= 0:
            self.end_game()
            return

        self.add_random_step()
        self.show_sequence_async()

    def end_game(self):
        self.state = "game_over"

        end_time = time.time() + 2.5
        while time.time() < end_time and self.running:
            self.clear_board()
            self.draw_border()
            self.draw_clock_pie(0, base_color=(60, 0, 0), active_color=RED)
            time.sleep(0.06)

        # dacă vrei să repornească automat:
        self.run_countdown()
        self.start_new_game()

    def repeat_sequence_async(self, play_sound=True):
        self.state = "repeat"
        t = threading.Thread(target=self.run_repeat_sequence, args=(play_sound,), daemon=True)
        t.start()

    def run_repeat_sequence(self, play_sound=True):
        self.state = "repeat"
        self.round_deadline = None
        self.last_clock_visible_segments = -1

        self.flash_all(color=RED, times=2, on_time=0.2, off_time=0.12)
        time.sleep(0.3)
        self.player_index = 0
        self.show_sequence_async()

    # -----------------------------------------------------
    #                    INPUT HANDLING
    # -----------------------------------------------------

    def get_round_duration(self):
        """
        Runda 1-2: 8 sec
        De la runda 3: +3 sec per nivel
        """
        if self.level < 3:
            return self.round_duration_sec
        else:
            return min(25, self.round_duration_sec + (self.level - 3) * 2)
    
    def tick(self):
        # eliberare tile-uri
        to_release = []
        for tile_id in self.pressed_tiles:
            if not self.is_tile_currently_pressed(tile_id):
                to_release.append(tile_id)

        for tile_id in to_release:
            self.pressed_tiles.discard(tile_id)

        # timer total joc
        if self.state in ("showing", "input", "success", "repeat"):
            if self.game_end_time is not None and time.time() >= self.game_end_time:
                self.end_game()
                return

        # timer rundă + update ceas DOAR în input
        if self.state == "input":
            if self.round_deadline is not None and time.time() >= self.round_deadline:
                self.repeat_sequence_async(play_sound=False)
                return

            segs = self.get_clock_segments_for_round()
            if segs != self.last_clock_visible_segments:
                self.last_clock_visible_segments = segs
                self.redraw_game_scene(dim=False)

    def handle_physical_press(self, led_idx):
        if self.state != "input":
            return

        x, y = self.led_index_to_xy(led_idx)
        tile_id = self.find_tile_by_xy(x, y)

        if tile_id is None:
            return

        if tile_id in self.pressed_tiles:
            return

        self.pressed_tiles.add(tile_id)

        self.handle_game_input(tile_id)

        # apoi pornește highlight-ul vizual
        t = threading.Thread(
            target=self.flash_pressed_tile_feedback,
            args=(tile_id,),
            daemon=True
        )
        t.start()

    def handle_game_input(self, tile_id):
        expected = self.sequence[self.player_index]

        if tile_id == expected:
            self.player_index += 1
            if self.player_index >= len(self.sequence):
                self.state = "success"
                self.round_deadline = None
                self.success_async()
        else:
            self.state = "repeat"
            self.round_deadline = None
            self.repeat_sequence_async(play_sound=False)

    def flash_pressed_tile_feedback(self, tile_id):
        self.redraw_game_scene(dim=False)
        tile = self.tiles[tile_id]

        self.draw_tile(tile, WHITE)
        time.sleep(0.15)

        if self.state == "input":
            self.redraw_game_scene(dim=False)

    # -----------------------------------------------------
    #              HARDWARE INDEX -> X,Y MAPPING
    # -----------------------------------------------------
    def led_index_to_xy(self, led_idx):
        channel = led_idx // 64
        idx_in_channel = led_idx % 64

        row_in_channel = idx_in_channel // 16
        col_raw = idx_in_channel % 16

        if row_in_channel % 2 == 0:
            x = col_raw
        else:
            x = 15 - col_raw

        y = (channel * 4) + row_in_channel
        return x, y

    def xy_to_led_index(self, x, y):
        if not (0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT):
            return None

        channel = y // 4
        if channel >= NUM_CHANNELS:
            return None

        row_in_channel = y % 4

        if row_in_channel % 2 == 0:
            idx_in_row = x
        else:
            idx_in_row = 15 - x

        return channel * 64 + row_in_channel * 16 + idx_in_row

    def find_tile_by_xy(self, x, y):
        for tile in self.tiles:
            x0 = tile["x"]
            y0 = tile["y"]
            w = tile.get("w", 2)
            h = tile.get("h", 2)

            if x0 <= x < x0 + w and y0 <= y < y0 + h:
                return tile["id"]
        return None

    def is_tile_currently_pressed(self, tile_id):
        tile = self.tiles[tile_id]
        x0 = tile["x"]
        y0 = tile["y"]
        w = tile.get("w", 2)
        h = tile.get("h", 2)

        for dy in range(h):
            for dx in range(w):
                x = x0 + dx
                y = y0 + dy
                led_idx = self.xy_to_led_index(x, y)
                if led_idx is not None and self.button_states[led_idx]:
                    return True
        return False
        # -----------------------------------------------------
    #                        RENDER
    # -----------------------------------------------------
    def render(self):
        buffer = bytearray(FRAME_DATA_LENGTH)
        with self.lock:
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    self.set_led(buffer, x, y, self.board[y][x])
        return buffer

    def set_led(self, buffer, x, y, color):
        if x < 0 or x >= 16:
            return

        channel = y // 4
        if channel >= 8:
            return

        row_in_channel = y % 4
        if row_in_channel % 2 == 0:
            led_index = row_in_channel * 16 + x
        else:
            led_index = row_in_channel * 16 + (15 - x)

        block_size = NUM_CHANNELS * 3
        offset = led_index * block_size + channel

        if offset + NUM_CHANNELS * 2 < len(buffer):
            # format hardware: G, R, B
            buffer[offset] = color[1]
            buffer[offset + NUM_CHANNELS] = color[0]
            buffer[offset + NUM_CHANNELS * 2] = color[2]

# =========================================================
#                     NETWORK MANAGER
# =========================================================
class NetworkManager:
    def __init__(self, game):
        self.game = game
        self.sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self.sock_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.running = True
        self.sequence_number = 0

        bind_ip = CONFIG.get("bind_ip", "0.0.0.0")
        if bind_ip != "0.0.0.0":
            try:
                self.sock_send.bind((bind_ip, 0))
            except:
                pass

        try:
            self.sock_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock_recv.bind(("0.0.0.0", UDP_LISTEN_PORT))
        except Exception as e:
            print(f"Eroare bind: {e}")
            self.running = False

    def send_loop(self):
        while self.running:
            frame = self.game.render()
            self.send_packet(frame)
            time.sleep(0.05)

    def send_packet(self, frame_data):
        self.sequence_number = (self.sequence_number + 1) & 0xFFFF
        if self.sequence_number == 0:
            self.sequence_number = 1

        target_ip = UDP_SEND_IP
        port = UDP_SEND_PORT

        # 1. Start Packet
        rand1, rand2 = random.randint(0, 127), random.randint(0, 127)
        start_packet = bytearray([
            0x75, rand1, rand2, 0x00, 0x08,
            0x02, 0x00, 0x00, 0x33, 0x44,
            (self.sequence_number >> 8) & 0xFF,
            self.sequence_number & 0xFF,
            0x00, 0x00, 0x00, 0x0E, 0x00
        ])
        try:
            self.sock_send.sendto(start_packet, (target_ip, port))
            self.sock_send.sendto(start_packet, ("127.0.0.1", port))
        except:
            pass

        # 2. FFF0 Packet
        rand1, rand2 = random.randint(0, 127), random.randint(0, 127)
        fff0_payload = bytearray()
        for _ in range(NUM_CHANNELS):
            fff0_payload += bytes([
                (LEDS_PER_CHANNEL >> 8) & 0xFF,
                LEDS_PER_CHANNEL & 0xFF
            ])

        fff0_internal = bytearray([
            0x02, 0x00, 0x00, 0x88, 0x77, 0xFF, 0xF0,
            (len(fff0_payload) >> 8) & 0xFF,
            len(fff0_payload) & 0xFF
        ]) + fff0_payload

        fff0_len = len(fff0_internal) - 1
        fff0_packet = bytearray([
            0x75, rand1, rand2,
            (fff0_len >> 8) & 0xFF,
            fff0_len & 0xFF
        ]) + fff0_internal + bytearray([0x1E, 0x00])

        try:
            self.sock_send.sendto(fff0_packet, (target_ip, port))
            self.sock_send.sendto(fff0_packet, ("127.0.0.1", port))
        except:
            pass

        # 3. Data Packets
        chunk_size = 984
        data_packet_index = 1

        for i in range(0, len(frame_data), chunk_size):
            rand1, rand2 = random.randint(0, 127), random.randint(0, 127)
            chunk = frame_data[i:i + chunk_size]

            internal_data = bytearray([
                0x02, 0x00, 0x00,
                (0x8877 >> 8) & 0xFF,
                0x8877 & 0xFF,
                (data_packet_index >> 8) & 0xFF,
                data_packet_index & 0xFF,
                (len(chunk) >> 8) & 0xFF,
                len(chunk) & 0xFF
            ]) + chunk

            payload_len = len(internal_data) - 1
            packet = bytearray([
                0x75, rand1, rand2,
                (payload_len >> 8) & 0xFF,
                payload_len & 0xFF
            ]) + internal_data

            packet.append(0x1E if len(chunk) == 984 else 0x36)
            packet.append(0x00)

            try:
                self.sock_send.sendto(packet, (target_ip, port))
                self.sock_send.sendto(packet, ("127.0.0.1", port))
            except:
                pass

            data_packet_index += 1
            time.sleep(0.005)

        # 4. End Packet
        rand1, rand2 = random.randint(0, 127), random.randint(0, 127)
        end_packet = bytearray([
            0x75, rand1, rand2, 0x00, 0x08,
            0x02, 0x00, 0x00, 0x55, 0x66,
            (self.sequence_number >> 8) & 0xFF,
            self.sequence_number & 0xFF,
            0x00, 0x00, 0x00, 0x0E, 0x00
        ])

        try:
            self.sock_send.sendto(end_packet, (target_ip, port))
            self.sock_send.sendto(end_packet, ("127.0.0.1", port))
        except:
            pass

    def recv_loop(self):
        while self.running:
            try:
                data, _ = self.sock_recv.recvfrom(2048)

                if len(data) >= 1373 and data[0] == 0x88:
                    newly_pressed = []

                    for c in range(8):
                        offset = 2 + (c * 171) + 1
                        ch_data = data[offset: offset + 64]

                        for i, val in enumerate(ch_data):
                            global_idx = (c * 64) + i
                            new_state = (val == 0xCC)
                            old_state = self.game.button_states[global_idx]

                            self.game.button_states[global_idx] = new_state

                            if new_state and not old_state:
                                newly_pressed.append(global_idx)

                    for led_idx in newly_pressed:
                        self.game.handle_physical_press(led_idx)

            except Exception:
                time.sleep(0.001)

    def start_bg(self):
        t1 = threading.Thread(target=self.send_loop, daemon=True)
        t2 = threading.Thread(target=self.recv_loop, daemon=True)
        t1.start()
        t2.start()

# =========================================================
#                        GAME LOOP
# =========================================================
def game_thread_func(game):
    while game.running:
        game.tick()
        time.sleep(0.002)


# =========================================================
#                           MAIN
# =========================================================
if __name__ == "__main__":
    game = SimonGame()
    net = NetworkManager(game)
    net.start_bg()

    # Pornim intro-ul DUPĂ ce pornește rețeaua
    game.play_intro_then_start_async()

    gt = threading.Thread(target=game_thread_func, args=(game,), daemon=True)
    gt.start()

    print("Simon Game pornit.")
    print("Intro activ: LedITall")
    print("Urmareste secventa, apoi apasa patratele in ordinea afisata.")
    print("Scrie 'quit' sau 'exit' ca sa iesi.")

    try:
        while game.running:
            cmd = input("> ").strip().lower()
            if cmd in ("quit", "exit"):
                game.running = False
                break
    except KeyboardInterrupt:
        game.running = False

    net.running = False
    print("Exiting...")