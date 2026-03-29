import sys
import subprocess
import socket
import time
import threading
import random
import os
import colorsys
import math
import json

# ==============================================================================
# --- AUTOMATIC TOOL INSTALLER ---
# This part checks if your computer has all the necessary "tools" (libraries) 
# to run the game. If it's missing something (like pygame or yt-dlp), 
# it will automatically download and install it for you!
# ==============================================================================
def verify_and_install(package, import_name=None):
    if import_name is None:
        import_name = package
    try:
        __import__(import_name)
    except ImportError:
        print(f"Installing {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

verify_and_install('pygame')
verify_and_install('pygame_gui') # For the DJ control interface buttons and text boxes
verify_and_install('yt-dlp', 'yt_dlp') # To download music from YouTube
verify_and_install('librosa') # To analyze the music and find the heartbeat (BPM)
verify_and_install('soundfile')

import pygame
import pygame_gui
import yt_dlp
import librosa

# A dictionary (like a notebook) to remember information about the downloaded songs
SONG_DATA = {}

# ==============================================================================
# --- NETWORK CONFIGURATION (THE WALKIE-TALKIES) ---
# Here we set up the secret radio channels (ports) and addresses so the computers 
# and the big LED light wall can talk to each other without getting confused.
# ==============================================================================
UDP_SEND_IP         = "255.255.255.255" # Broadcast to everyone on the network
UDP_SEND_PORT_MAIN  = 4626 # Port to send the pixel colors to the LED wall
UDP_LISTEN_PORT     = 7800 # Port to listen for when someone steps on a physical floor tile

UDP_SCORE_PORT      = 4445 # Port to send the game score to the 2nd screen
UDP_SCORE_IP        = "127.0.0.1" # Send score to this same computer (localhost)

# --- HARDWARE SETUP (THE LED WALL) ---
NUM_CHANNELS        = 8  # Number of cables connecting the LED panels
LEDS_PER_CHANNEL    = 64 # Lights per cable
BOARD_W, BOARD_H    = 16, 32 # The grid size of our physical LED floor (16x32 tiles)
FRAME_LEN           = NUM_CHANNELS * LEDS_PER_CHANNEL * 3 # Total amount of color data needed

# --- PAINT COLORS ---
WHITE  = (255, 255, 255)
GREEN  = (0, 255, 0)
RED    = (255, 0, 0)
BLACK  = (0, 0, 0)
CYAN   = (0, 255, 255)
PURPLE = (170, 0, 255)

# --- DJ CONSOLE COLORS ---
CLR_GLASS     = (30, 30, 50, 150) # Semi-transparent color for a cool glass effect
CLR_NEON_PINK = (255, 20, 147)

# ════════════════════════════════════════════════════════════════════════
# 1. THE DJ CONTROL PANEL (InterfaceManager)
# This class builds the window you see on your laptop screen where you 
# type the song name and click "START".
# ════════════════════════════════════════════════════════════════════════
class InterfaceManager:
    def __init__(self):
        pygame.init()
        # Set the size of the DJ window
        self.screen_ctrl = pygame.display.set_mode((self.screen_width, self.screen_height), pygame.FULLSCREEN)
        pygame.display.set_caption("🎧 DJ DECK - Control Panel")
        
        # This manager handles all the buttons and text boxes for us
        self.gui_manager = pygame_gui.UIManager((self.screen_width, self.screen_height))

        self.setup_ui_elements()
        self.clock = pygame.time.Clock() # Keeps track of time
        self.running = True
        self.game_started = False
        self.start_time = time.time()
        self.scoreboard_process = None # Prevents opening multiple score windows by mistake

    def setup_ui_elements(self):
        """Draws all the buttons, text boxes, and labels on the screen."""
        self.cont_p = pygame.Rect((50, 80), (400, 140))
        self.cont_m = pygame.Rect((50, 240), (400, 160))

        # "How many players?" label and input box
        pygame_gui.elements.UILabel(relative_rect=pygame.Rect((70, 90), (360, 20)), 
                                    text="SETUP ACTIVE PLAYERS", manager=self.gui_manager)
        self.input_players = pygame_gui.elements.UITextEntryLine(relative_rect=pygame.Rect((200, 130), (100, 50)), 
                                                               manager=self.gui_manager)
        self.input_players.set_text("1")

        # "What song?" label and input box
        pygame_gui.elements.UILabel(relative_rect=pygame.Rect((70, 250), (360, 20)), 
                                    text="SELECT TRACK (YouTube/Search)", manager=self.gui_manager)
        self.input_search = pygame_gui.elements.UITextEntryLine(relative_rect=pygame.Rect((80, 290), (340, 50)), 
                                                              manager=self.gui_manager)
        self.input_search.set_text("Marabou Antonia")

        # The big START button
        self.btn_start = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((125, 430), (250, 70)), 
                                                      text="START SESSION", manager=self.gui_manager)
        
        # The status box at the bottom that tells you what the system is doing
        self.status_label = pygame_gui.elements.UITextBox(html_text="Ready to mix...",
                                                         relative_rect=pygame.Rect((50, 520), (400, 100)), 
                                                         manager=self.gui_manager)

    def draw_studio_deck(self):
        """The artist! Draws the pretty background of the DJ console."""
        now = time.time() - self.start_time
        
        # 1. Draw a smooth color gradient from top to bottom (Dark blue to purple)
        for y in range(self.screen_height):
            ratio = y / self.screen_height
            color = (int(15*(1-ratio)+25*ratio), int(15*(1-ratio)+15*ratio), int(25*(1-ratio)+45*ratio))
            pygame.draw.line(self.screen_ctrl, color, (0, y), (self.screen_width, y))

        # 2. Draw little floating music notes vibrating in the background
        for i, pos in enumerate([(80, 100), (420, 250), (100, 500), (350, 50)]):
            y_vib = math.sin(now * 2 + i) * 10 # Math to make them bob up and down
            pygame.draw.circle(self.screen_ctrl, (60, 60, 100), (pos[0], int(pos[1] + y_vib)), 5)
            pygame.draw.line(self.screen_ctrl, (60, 60, 100), (pos[0]+5, int(pos[1]+y_vib)), (pos[0]+5, int(pos[1]+y_vib-20)), 2)

        # 3. Draw the glass-looking rectangles behind the text boxes
        for r in [self.cont_p, self.cont_m]:
            s = pygame.Surface((r.width, r.height), pygame.SRCALPHA)
            pygame.draw.rect(s, (255, 255, 255, 20), (0, 0, r.width, r.height), border_radius=15)
            pygame.draw.rect(s, (0, 255, 255, 50), (0, 0, r.width, r.height), width=2, border_radius=15)
            self.screen_ctrl.blit(s, r.topleft)

        # 4. Draw a cool spinning vinyl record
        pygame.draw.circle(self.screen_ctrl, (10, 10, 10), (90, 150), 30)
        pygame.draw.circle(self.screen_ctrl, (255, 20, 147), (90, 150), 10)

    def render_all(self, time_delta):
        """Updates the DJ window every fraction of a second."""
        self.draw_studio_deck()
        self.gui_manager.update(time_delta)
        self.gui_manager.draw_ui(self.screen_ctrl)
        
        # Add a pulsing glowing neon effect to the Start button before the game starts
        if not self.game_started:
            pulse = (math.sin(time.time() * 5) + 1) / 2
            color = (int(255 * pulse), 20, 147) # Pink glow
            pygame.draw.rect(self.screen_ctrl, color, self.btn_start.get_abs_rect(), width=3, border_radius=5)
        
        pygame.display.update()

    def draw_scoreboard(self, game):
        """Packages the game scores and time left, and sends them to the Audience Scoreboard screen."""
        try:
            # Calculate how much time is left in the song
            if pygame.mixer.music.get_busy() and game.state == "PLAYING":
                curr_pos = pygame.mixer.music.get_pos() / 1000.0
                path = game.playlist[game.current_song_idx]
                total_dur = SONG_DATA.get(path, {}).get("duration", 180)
                rem_time = max(0, total_dur - curr_pos)
            else:
                rem_time = 0

            # Put all the info in a nice package (JSON)
            data_to_send = {
                "scores": game.scores,
                "time_left": int(rem_time),
                "song_name": "GAME OVER" if game.state == "FINISHED" else game.current_song_name,
                "num_players": game.num_players,
                "status": self.game_started
            }
            
            # Send the package via the UDP walkie-talkie to port 4445
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(json.dumps(data_to_send).encode(), (UDP_SCORE_IP, UDP_SCORE_PORT))
        except Exception as e:
            pass # If it fails to send, ignore it so the game doesn't crash

    def update_status(self, msg):
        """Updates the text in the little status box at the bottom of the DJ screen."""
        self.status_label.set_text(msg)

# ════════════════════════════════════════════════════════════════════════
# 2. THE GAME LOGIC (PianoTilesPro)
# This is the "Brain" of the game. It controls the falling blocks, 
# keeps score, and checks if players step on the right tiles.
# ════════════════════════════════════════════════════════════════════════
class Note:
    """A small class representing one single falling block on the LED matrix."""
    def __init__(self, player_idx, row_offset, color):
        self.player = player_idx # Which player lane it belongs to
        self.row_offset = row_offset # Which row inside the lane
        self.color = color
        self.x = -1.0 # Starting position (off-screen left)
        self.alive = True # Is it still falling?

class PianoTilesPro:
    def __init__(self, num_players, playlist):
        self.num_players = max(1, min(6, num_players)) # Max 6 players allowed
        self.lock = threading.RLock() # Keeps threads from crashing into each other
        self.scores = [0] * self.num_players
        
        # Game "Moods" (States) - We start with the Rainbow animation
        self.state = "RAINBOW_ANIM"
        self.state_start_time = time.time()
        
        self.playlist = playlist
        self.current_song_idx = 0
        
        # Organize the LED floor into "Lanes" for each player (5 rows per player)
        self.LANE_H = 5 
        total_game_h = self.num_players * self.LANE_H
        self.offset_y = (BOARD_H - total_game_h) // 2 # Center the lanes vertically
        
        self.lane_starts = [self.offset_y + p * self.LANE_H + 1 for p in range(self.num_players)]
        self.horizontal_lines = [self.offset_y + p * self.LANE_H for p in range(self.num_players)] + [self.offset_y + total_game_h]

        self.notes = []
        self.hit_effects = [] 
        self.spawn_timer = time.time()
        self.last_tick = time.time()
        
        # Density Control: Makes sure blocks don't spawn too close or too far apart
        self.consecutive_spawns = 0
        self.consecutive_pauses = 0

        # Memory of the physical floor buttons (which tiles are currently stepped on)
        self.button_states = [False] * 512
        self.prev_button_states = [False] * 512
        
        self.current_song_name = "Ready"
        self.current_bpm = 120
        self.base_interval = 0.5
        self.song_actual_start = 0

        # Initialize the music player
        pygame.mixer.quit()
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.mixer.init()

    def start_music(self):
        """Loads and plays the downloaded song."""
        if self.current_song_idx >= len(self.playlist):
            self.current_song_idx = 0 
        
        path = self.playlist[self.current_song_idx]
        self.song_actual_start = time.time()
        
        if os.path.exists(path):
            info = SONG_DATA[path]
            self.current_bpm = info["bpm"]
            self.current_song_name = info["name"]
            # The interval between blocks depends entirely on the song's BPM (Heartbeat)
            self.base_interval = 60.0 / self.current_bpm
            pygame.mixer.music.load(path)
            pygame.mixer.music.play(0)

    def tick(self):
        """THE HEARTBEAT OF THE GAME. Runs continuously to update movements and logic."""
        with self.lock:
            now = time.time()
            dt = now - self.last_tick
            self.last_tick = now

            # -- INTRO ANIMATIONS --
            if self.state == "RAINBOW_ANIM":
                if now - self.state_start_time > 3.0: # Show rainbow for 3 seconds
                    self.state = "TEXT_ANIM"
                    self.state_start_time = now
                return
            
            if self.state == "TEXT_ANIM":
                if now - self.state_start_time > 4.0: # Write text for 4 seconds
                    self.state = "SHOW_NUMBERS"
                    self.state_start_time = now
                return
                
            if self.state == "SHOW_NUMBERS":
                if now - self.state_start_time > 3.0: # Show Player Numbers for 3 seconds
                    self.state = "PLAYING"
                    self.start_music() # Play the music!
                return

            # -- MAIN GAME LOGIC --
            if self.state == "PLAYING":
                # Check if song is over. If yes, go to Game Over (FINISHED) state.
                if not pygame.mixer.music.get_busy() and (now - self.song_actual_start > 5):
                    self.notes.clear()
                    self.state = "FINISHED" 
                    self.state_start_time = now
                    return

                elapsed = now - self.song_actual_start
                
                # We create an invisible "grid" timed perfectly with the music's BPM
                grid_interval = self.base_interval / 1.5 
                
                # Speed at which blocks move across the screen. 
                # Gets slightly faster over time (+0.005)
                move_speed = 3.8 + (elapsed * 0.005)
                
                # SPAWN LOGIC: Should we drop a new block?
                if now - self.spawn_timer > grid_interval:
                    self.spawn_timer = now
                    
                    # --- SMART BLOCK DISTRIBUTION ---
                    should_spawn = False
                    
                    # Don't leave too much empty space (max 2 pauses)
                    if self.consecutive_pauses >= 2: 
                        should_spawn = True
                    # Don't put too many blocks tightly together (force a pause after 2 or 3)
                    elif self.consecutive_spawns >= random.choice([2, 3]): 
                        should_spawn = False
                    # Otherwise, there's a 60% normal chance to drop a block
                    else:
                        should_spawn = random.random() > 0.4
                        
                    if should_spawn:
                        self.consecutive_spawns += 1
                        self.consecutive_pauses = 0
                        
                        common_row_offset = random.randint(0, 2)
                        common_color = self._get_rand_col()
                        
                        # Choose 1 or 2 random players to get this block
                        num_targets = random.choice([1, 2])
                        num_targets = min(num_targets, self.num_players)
                        targets = random.sample(range(self.num_players), num_targets)
                        
                        # Add the falling block to the screen
                        for p in targets:
                            self.notes.append(Note(p, common_row_offset, common_color))
                            
                    else:
                        self.consecutive_spawns = 0
                        self.consecutive_pauses += 1

                # Move the blocks down the screen
                for note in self.notes[:]:
                    note.x += move_speed * dt
                    # If the block goes past the green area (X >= 13.9), the player missed it!
                    if note.x >= 13.9: 
                        if note.alive: 
                            self.scores[note.player] -= 1 # Penalty (-1) for missing
                        self.notes.remove(note)

                # Remove hit effects (flashes) after 0.2 seconds
                self.hit_effects = [e for e in self.hit_effects if now - e['t'] < 0.2]

                # Check the physical floor tiles for new steps
                curr_btns = self.button_states[:]
                for i in range(512):
                    # If a tile was JUST stepped on right now
                    if curr_btns[i] and not self.prev_button_states[i]:
                        self.handle_click(i)
                self.prev_button_states = curr_btns
                
                # Print live scores in the background terminal
                self._print_scores()

    def handle_click(self, led_idx):
        """Checks if a player stepping on a physical floor tile hit a block or made a mistake."""
        # Convert the physical wire index into X, Y coordinates on the grid
        ch, rem = led_idx // 64, led_idx % 64
        row, col = rem // 16, rem % 16
        x_c, y_c = (col if row % 2 == 0 else 15 - col), (ch * 4) + row

        for p in range(self.num_players):
            y_s = self.lane_starts[p]
            # Check if the step happened in Player P's lane
            if y_s <= y_c < y_s + 4:
                hit = False
                # Look at all falling notes to see if we stepped on one
                for note in self.notes:
                    # Is the note in the "Green Target Zone" (X > 10)?
                    if note.player == p and note.alive and note.x > 10.0:
                        # Is the step on the exact correct row?
                        if y_c == (y_s + note.row_offset):
                            self.scores[p] += 5 # SUCCESS! +5 points
                            note.alive = False
                            self.hit_effects.append({'x': x_c, 'y': y_c, 't': time.time(), 'success': True})
                            hit = True
                            break
                
                # If they stepped but there was no block there (or they stepped too early)
                if not hit:
                    # Only penalize if they stepped before the absolute edge
                    if x_c < 14: 
                        self.scores[p] -= 2 # FAIL! -2 points
                        self.hit_effects.append({'x': x_c, 'y': y_c, 't': time.time(), 'success': False}) # Red flash
                return

    def _get_rand_col(self):
        """Generates a random, bright color for the blocks."""
        rgb = colorsys.hsv_to_rgb(random.random(), 1, 1)
        return (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))

    def _print_scores(self):
        """Prints the score in the developer console."""
        if not hasattr(self, 'last_scores'): self.last_scores = []
        if self.scores == self.last_scores: return
            
        self.last_scores = list(self.scores)
        s = " | ".join([f"P{i+1}: {self.scores[i]}" for i in range(self.num_players)])
        sys.stdout.write(f"\r🎹 [{self.current_song_name}] {s}           ")
        sys.stdout.flush()

    # ════════════════════════════════════════════════════════════════════════
    # THE PAINTER (LED Matrix Renderer)
    # These functions translate the game into colored pixels for the LED wall.
    # ════════════════════════════════════════════════════════════════════════
    def render(self):
        """Creates the giant list of RGB bytes to send to the LED wall."""
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
            elif self.state == "FINISHED": # Game Over Animation
                self._render_finished(buf, now)
        return buf

    def _render_finished(self, buf, t):
        """Game Over Effect: The entire LED wall pulses a golden/yellow color."""
        pulse = (math.sin(t * 3) + 1) / 2
        r = int(100 + pulse * 155)
        g = int(80 + pulse * 100)
        for y in range(32):
            for x in range(16):
                self.set_led(buf, x, y, (r, g, 0))

    def _draw_boundaries(self, buf):
        """Draws the red separating lines and the green target zone on the right."""
        for y in self.horizontal_lines:
            for x in range(16): self.set_led(buf, x, y, RED)
        for p in range(self.num_players):
            y_s = self.lane_starts[p]
            for dy in range(4):
                self.set_led(buf, 14, y_s + dy, GREEN)
                self.set_led(buf, 15, y_s + dy, GREEN)

    def _render_background_beat(self, buf, now):
        """Draws a cool 'Plasma Wave' background that pulses to the music's BPM."""
        if self.song_actual_start == 0: return
        elapsed = now - self.song_actual_start
        if elapsed < 0: return

        current_beat = elapsed * self.current_bpm / 60.0
        beat_phase = current_beat - int(current_beat) 
        beat_intensity = max(0.4, 1.0 - (beat_phase * 1.5)) 
        base_hue = (now * 0.05) % 1.0
        end_y = self.offset_y + (self.num_players * self.LANE_H)

        for y in range(32):
            # Only draw background OUTSIDE the active lanes
            if y < self.offset_y or y >= end_y:
                for x in range(16):
                    wave = math.sin(x * 0.4 + now * 3) + math.cos(y * 0.3 - now * 2)
                    wave_norm = (wave + 2) / 4.0 
                    pixel_hue = (base_hue + wave_norm * 0.3) % 1.0
                    brightness = max(0.1, wave_norm * beat_intensity)
                    rgb = colorsys.hsv_to_rgb(pixel_hue, 1.0, brightness)
                    self.set_led(buf, x, y, (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255)))

    def _render_numbers_state(self, buf):
        """Draws the player numbers (1, 2, 3, etc.) centered in their lanes."""
        self._draw_boundaries(buf)
        x_start = 5 
        num_color = (0, 255, 255) 
        for p in range(self.num_players):
            self._draw_number(buf, p + 1, x_start, self.lane_starts[p], num_color)

    def _draw_number(self, buf, num, x_offset, y_offset, color):
        """A manual pixel-art dictionary for drawing numbers rotated sideways."""
        font_rotated_left = {
            1: [(0,1), (1,1), (1,2), (2,1), (3,1), (4,0), (4,1), (4,2)],
            2: [(0,0), (0,1), (0,2), (1,0), (2,0), (2,1), (2,2), (3,2), (4,0), (4,1), (4,2)],
            3: [(0,0), (0,1), (0,2), (1,0), (2,0), (2,1), (2,2), (3,0), (4,0), (4,1), (4,2)],
            4: [(0,0), (0,2), (1,0), (1,2), (2,0), (2,1), (2,2), (3,0), (4,0)],
            5: [(0,0), (0,1), (0,2), (1,2), (2,0), (2,1), (2,2), (3,0), (4,0), (4,1), (4,2)],
            6: [(0,0), (0,1), (0,2), (1,2), (2,0), (2,1), (2,2), (3,0), (3,2), (4,0), (4,1), (4,2)]
        }
        if num in font_rotated_left:
            for px, py in font_rotated_left[num]:
                self.set_led(buf, x_offset + px, y_offset + py, color)

    def _render_game(self, buf):
        """The main painter for the active game."""
        now = time.time()
        self._render_background_beat(buf, now)
        self._draw_boundaries(buf)
        
        # Draw the falling blocks
        for note in self.notes:
            if note.alive and int(note.x) < 14:
                self.set_led(buf, int(note.x), self.lane_starts[note.player] + note.row_offset, note.color)
        
        # Draw the hit/miss flashes
        for e in self.hit_effects:
            col = WHITE if e['success'] else (150, 0, 0)
            self.set_led(buf, int(e['x']), int(e['y']), col)

    def _render_text_long(self, buf, now):
        """Animation that slowly writes 'LedITall' sideways."""
        pulsation_val = int(127 + 127 * math.sin(now * 5))
        color = (pulsation_val, 0, 255)
        pixels_sequence = [
            (4,0), (3,0), (2,0), (1,0), (0,0), (0,1), (0,2),
            (4,4), (3,4), (2,4), (1,4), (0,4), (4,5), (4,6), (2,5), (2,6), (0,5), (0,6),
            (4,8), (3,8), (2,8), (1,8), (0,8), (4,9), (3,10), (2,10), (1,10), (0,9),
            (4,13), (3,13), (2,13), (1,13), (0,13),
            (4,16), (4,17), (4,18), (3,17), (2,17), (1,17), (0,17),
            (0,20), (1,20), (2,20), (3,20), (4,21), (3,22), (2,22), (1,22), (0,22), (2,21),
            (4,24), (3,24), (2,24), (1,24), (0,24), (0,25), (0,26),
            (4,28), (3,28), (2,28), (1,28), (0,28), (0,29), (0,30)
        ]
        offset_x = 5
        elapsed = now - self.state_start_time
        pixels_to_draw = int((elapsed / 3.0) * len(pixels_sequence)) # Reveal letter by letter over 3s
        for i in range(max(0, min(pixels_to_draw, len(pixels_sequence)))):
            px, py = pixels_sequence[i]
            self.set_led(buf, offset_x + px, py, color)

    def _render_rainbow(self, buf, t):
        """Intro animation: Full grid scrolling rainbow."""
        for y in range(32):
            for x in range(16):
                h = (t + x/16 + y/32) % 1.0
                rgb = [int(c*255) for c in colorsys.hsv_to_rgb(h, 1.0, 0.8)]
                self.set_led(buf, x, y, rgb)

    def set_led(self, buf, x, y, col):
        """Helper to place a pixel color into the correct position in the network array."""
        if 0 <= x < 16 and 0 <= y < 32:
            ch, r = y // 4, y % 4
            # LED panels often snake back and forth, so we reverse every other row
            idx = (r * 16 + x) if r % 2 == 0 else (r * 16 + (15 - x))
            off = idx * 24 + ch 
            # Network protocol expects GRB color order, not RGB
            buf[off], buf[off+8], buf[off+16] = col[1], col[0], col[2]


# ════════════════════════════════════════════════════════════════════════
# 3. YOUTUBE DOWNLOAD & NETWORK (The Robots)
# ════════════════════════════════════════════════════════════════════════
def proceseaza_melodie_online(cautare):
    """Robot that searches YouTube, downloads the song, and finds the BPM heartbeat."""
    print(f"\n⏳ Searching YouTube for: '{cautare}'...")
    if not os.path.exists('temp_songs'): os.makedirs('temp_songs')
        
    cale_fisier = 'temp_songs/melodie_curenta.mp3'
    if os.path.exists(cale_fisier):
        try: os.remove(cale_fisier)
        except: pass

    # Rules for the downloader: grab the best audio, convert it to mp3
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': cale_fisier[:cale_fisier.rfind('.')] + '.%(ext)s',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        'noplaylist': True,
        'default_search': 'ytsearch1:', # Pick the first result
        'quiet': True, 'no_warnings': True
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            rezultat = ydl.extract_info(cautare, download=True)
            titlu = rezultat['entries'][0]['title']
            print(f"✅ Download complete: {titlu}")
    except Exception as e:
        print(f"❌ Download Error: {e}")
        return None

    # Use 'librosa' (an AI audio tool) to listen to the song and detect the rhythm
    print("🧠 Analyzing rhythm (BPM)...")
    try:
        y, sr = librosa.load(cale_fisier, duration=None)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = round(float(tempo[0]) if hasattr(tempo, '__iter__') else float(tempo))
        print(f"🎵 Detected BPM: {bpm}")
        return {"path": cale_fisier, "name": titlu, "bpm": bpm}
    except Exception as e:
        return None


class NetworkManager:
    """Robot that throws data to the LED wall and catches data from the floor pads."""
    def __init__(self, game):
        self.game, self.seq = game, 0
        
        # Socket for throwing (broadcasting) the LED colors
        self.s_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        # Socket for listening to physical steps
        self.s_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try: self.s_recv.bind(("0.0.0.0", UDP_LISTEN_PORT))
        except: pass

    def run(self):
        """The main loop for the network. Runs in the background constantly."""
        # Start a background worker to listen for footsteps
        threading.Thread(target=self.recv_loop, daemon=True).start()
        
        # Loop forever: Ask the game what to paint -> Send it to the wall -> Wait -> Repeat (~30 FPS)
        while True:
            self.game.tick()
            self.send_packet(self.game.render(), UDP_SEND_PORT_MAIN)
            time.sleep(0.033)

    def recv_loop(self):
        """Listens for UDP packets coming FROM the physical LED floor."""
        while True:
            try:
                data, _ = self.s_recv.recvfrom(2048)
                # If it's a valid packet size from the hardware
                if len(data) >= 1370:
                    new_st = [False]*512 # 512 total tiles
                    for c in range(8):
                        off = 2 + (c * 171) + 1 
                        for i in range(64): 
                            new_st[(c * 64) + i] = (data[off + i] > 0) # True if stepped on
                    with self.game.lock: self.game.button_states = new_st 
            except: pass

    def send_packet(self, data, port):
        """Packages the raw bytes into the highly specific protocol the hardware expects."""
        self.seq = (self.seq + 1) & 0xFFFF
        addr = (UDP_SEND_IP, port)
        
        # Header packets
        self.s_send.sendto(bytearray([0x75, 0x01, 0x02, 0x00, 0x08, 0x02, 0x00, 0x00, 0x33, 0x44, self.seq>>8, self.seq&0xFF, 0,0,0,0x0E, 0]), addr)
        fff0 = bytearray([0x75, 0x03, 0x04, 0x00, 0x19, 0x02, 0x00, 0x00, 0x88, 0x77, 0xFF, 0xF0, 0, 0x10]) + (bytearray([0, 0x40])*8) + bytearray([0x1E, 0])
        self.s_send.sendto(fff0, addr)
        
        # Break data into 984-byte chunks and send them
        for i in range(0, len(data), 984):
            chunk = data[i:i+984]
            inner = bytearray([0x02, 0, 0, 0x88, 0x77, 0, (i//984)+1, len(chunk)>>8, len(chunk)&0xFF]) + chunk
            p = bytearray([0x75, 0x05, 0x06, (len(inner)-1)>>8, (len(inner)-1)&0xFF]) + inner + bytearray([0x1E if len(chunk)==984 else 0x36, 0])
            self.s_send.sendto(p, addr)
            
        # Footer packet
        self.s_send.sendto(bytearray([0x75, 0x07, 0x08, 0, 0x08, 0x02, 0, 0, 0x55, 0x66, self.seq>>8, self.seq&0xFF, 0,0,0,0x0E, 0]), addr)


# ════════════════════════════════════════════════════════════════════════
# 4. THE MAIN SCRIPT (The Director)
# This part starts the DJ interface and connects all the pieces together.
# ════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    ui = InterfaceManager()
    game = None
    net = None
    
    # This loop runs forever until you close the DJ Window
    while ui.running:
        time_delta = ui.clock.tick(60)/1000.0 # Limit the DJ window to 60 frames per second
        
        # --- CHECK IF SONG FINISHED ---
        if ui.game_started and game and getattr(game, 'state', '') == "FINISHED":
            ui.game_started = False
            ui.btn_start.set_text("START NEXT TRACK") # Change button text
            ui.update_status("Game Over! Ready for the next track.")
        
        # Check for mouse clicks or if the user clicked the 'X' to close the window
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                ui.running = False
            
            ui.gui_manager.process_events(event)
            
            # --- START BUTTON CLICKED ---
            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == ui.btn_start:
                    try:
                        n_players = int(ui.input_players.get_text())
                        search_term = ui.input_search.get_text()

                        # Launch the Audience Scoreboard screen (if it's not already open)
                        if ui.scoreboard_process is None or ui.scoreboard_process.poll() is not None:
                            # 1. Aflăm automat folderul în care se află acest script (game2.py)
                            director_curent = os.path.dirname(os.path.abspath(__file__))
                            # 2. Construim calea exactă către scoreboard.py în același folder
                            cale_scoreboard = os.path.join(director_curent, "scoreboard.py")
                            
                            # 3. Deschidem fișierul folosind calea completă
                            ui.scoreboard_process = subprocess.Popen([sys.executable, cale_scoreboard])

                        ui.update_status(f"Downloading: {search_term}...")
                        ui.render_all(0.01) # Force screen to update immediately
                        
                        # Go to YouTube and get the song + BPM
                        res = proceseaza_melodie_online(search_term)
                        
                        if res:
                            # Find exactly how long the song is (for the countdown timer)
                            y_dur, sr_dur = librosa.load(res["path"], sr=None)
                            real_duration = librosa.get_duration(y=y_dur, sr=sr_dur)
                            
                            SONG_DATA[res["path"]] = {"bpm": res["bpm"], "name": res["name"], "duration": real_duration}
                            
                            # Initialize the Game Brain
                            new_game = PianoTilesPro(n_players, [res["path"]])
                            ui.game_started = True
                            ui.btn_start.set_text("LIVE SESSION...")
                            
                            # Start or recycle the Network Walkie-Talkies
                            if net is None:
                                net = NetworkManager(new_game)
                                threading.Thread(target=net.run, daemon=True).start()
                            else:
                                net.game = new_game
                                
                            game = new_game
                            ui.update_status("LIVE SESSION ACTIVE")
                        else:
                            ui.update_status("Download Error!")
                    except Exception as e:
                        ui.update_status(f"Error: {e}")

        # Draw the DJ Console
        ui.render_all(time_delta)
        
        # If the game is running, throw the score to the Audience Screen
        if ui.game_started and game:
            ui.draw_scoreboard(game)

    pygame.quit()