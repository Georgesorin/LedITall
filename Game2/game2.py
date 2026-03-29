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

# --- AUTO-INSTALL DEPENDENȚE ACTUALIZAT ---
def verifica_si_instaleaza(pachet, nume_import=None):
    if nume_import is None:
        nume_import = pachet
    try:
        __import__(nume_import)
    except ImportError:
        print(f"Instalez {pachet}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pachet])

verifica_si_instaleaza('pygame')
verifica_si_instaleaza('pygame_gui') # Pentru interfața de control
verifica_si_instaleaza('yt-dlp', 'yt_dlp')
verifica_si_instaleaza('librosa')
verifica_si_instaleaza('soundfile')

import pygame
import pygame_gui
import yt_dlp
import librosa

SONG_DATA = {}

# --- CONFIGURARE EXISTENTĂ ---
UDP_SEND_IP         = "255.255.255.255"
UDP_SEND_PORT_MAIN  = 4626
UDP_LISTEN_PORT     = 7800
UDP_SCORE_PORT = 4445

NUM_CHANNELS        = 8
LEDS_PER_CHANNEL    = 64
BOARD_W, BOARD_H    = 16, 32
FRAME_LEN           = NUM_CHANNELS * LEDS_PER_CHANNEL * 3 

WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
RED   = (255, 0, 0)
BLACK = (0, 0, 0)
CYAN  = (0, 255, 255)
PURPLE = (170, 0, 255)

# --- CONFIGURARE CULORI TEMATICE ---
CLR_BG = (10, 10, 18)          
CLR_CARD = (30, 30, 50, 150)    # Card semi-transparent (cu Alpha)
CLR_CYAN = (0, 255, 255)
CLR_NEON_PINK = (255, 20, 147)
CLR_TEXT = (230, 230, 230)
CLR_INPUT_BG = (10, 10, 15)
class InterfaceManager:
    def __init__(self):
        pygame.init()
        # Dimensiuni fereastră
        self.screen_width, self.screen_height = 550, 700
        self.screen_ctrl = pygame.display.set_mode((self.screen_width, self.screen_height))
        pygame.display.set_caption("🎧 STUDIO MASTER - Control Deck")
        
        self.gui_manager = pygame_gui.UIManager((self.screen_width, self.screen_height))
        
        # Culori locale
        self.clr_glass = (30, 30, 55, 160)
        self.clr_neon_pink = (255, 20, 147)

        self.setup_ui_elements()
        self.clock = pygame.time.Clock()
        self.running = True
        self.game_started = False
        self.start_time = time.time()

    def setup_ui_elements(self):
        # Card Jucători
        self.rect_players = pygame.Rect(50, 100, 450, 150)
        pygame_gui.elements.UILabel(relative_rect=pygame.Rect(70, 115, 410, 30), 
                                    text="SETUP JUCĂTORI ACTIVI", manager=self.gui_manager)
        
        self.input_players = pygame_gui.elements.UITextEntryLine(relative_rect=pygame.Rect(215, 160, 120, 45), 
                                                               manager=self.gui_manager)
        self.input_players.set_text("1")

        # Card Muzică
        self.rect_music = pygame.Rect(50, 280, 450, 170)
        pygame_gui.elements.UILabel(relative_rect=pygame.Rect(70, 295, 410, 30), 
                                    text="CONFIGURARE PLAYLIST / CĂUTARE", manager=self.gui_manager)
        
        self.input_search = pygame_gui.elements.UITextEntryLine(relative_rect=pygame.Rect(80, 350, 390, 45), 
                                                              manager=self.gui_manager)
        self.input_search.set_text("Tzanca Uraganu - Trotinete")

        # Buton START
        self.btn_start = pygame_gui.elements.UIButton(relative_rect=pygame.Rect(150, 480, 250, 70), 
                                                     text="LANSEAZĂ SESIUNEA", manager=self.gui_manager)
        
        # Status Box
        self.status_label = pygame_gui.elements.UITextBox(html_text="<b>Sistem:</b> Gata de start...",
                                                         relative_rect=pygame.Rect(50, 580, 450, 90), 
                                                         manager=self.gui_manager)

    def draw_glass_card(self, rect, color):
        """Desenează un card stil 'Glass' curat, fără artefacte."""
        s = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(s, color, (0, 0, rect.width, rect.height), border_radius=20)
        # Border subtil pentru definiție
        pygame.draw.rect(s, (0, 255, 255, 80), (0, 0, rect.width, rect.height), width=2, border_radius=20)
        self.screen_ctrl.blit(s, rect.topleft)

    def draw_studio_deck(self):
        now = time.time() - self.start_time
        
        # 1. Fundal Master Gradient
        for y in range(self.screen_height):
            ratio = y / self.screen_height
            color = (int(10*(1-ratio)+5*ratio), int(10*(1-ratio)+5*ratio), int(25*(1-ratio)+15*ratio))
            pygame.draw.line(self.screen_ctrl, color, (0, y), (self.screen_width, y))

        # 2. Cardurile decorative
        self.draw_glass_card(self.rect_players, self.clr_glass)
        self.draw_glass_card(self.rect_music, self.clr_glass)

        # 3. Vinil (fără linia de pickup!)
        v_center = (90, 175)
        pygame.draw.circle(self.screen_ctrl, (5, 5, 10), v_center, 35) # Disc
        pygame.draw.circle(self.screen_ctrl, self.clr_neon_pink, v_center, 12) # Centru

    def render_all(self, time_delta):
        self.draw_studio_deck()
        self.gui_manager.update(time_delta)
        self.gui_manager.draw_ui(self.screen_ctrl)
        
        if not self.game_started:
            pulse = (math.sin(time.time() * 5) + 1) / 2
            glow_color = (int(255 * pulse), 20, 147)
            pygame.draw.rect(self.screen_ctrl, glow_color, self.btn_start.get_abs_rect(), 3, border_radius=8)
        
        pygame.display.update()

    def update_status(self, msg):
        self.status_label.set_text(msg)

    def draw_scoreboard(self, game):
        try:
            if pygame.mixer.music.get_busy():
                curr_pos = pygame.mixer.music.get_pos() / 1000.0
                path = game.playlist[game.current_song_idx]
                total_dur = SONG_DATA.get(path, {}).get("duration", 180)
                rem_time = max(0, total_dur - curr_pos)
            else: rem_time = 0

            data_to_send = {
                "scores": game.scores,
                "time_left": int(rem_time),
                "song_name": game.current_song_name,
                "num_players": game.num_players,
                "status": self.game_started
            }
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(json.dumps(data_to_send).encode(), ("127.0.0.1", 4445))
        except: pass
        self.btn_start = pygame_gui.elements.UIButton(relative_rect=pygame.Rect(150, 480, 250, 70), 
                                                     text="LANSEAZĂ SESIUNEA", manager=self.gui_manager)
        
        # Status Box
        self.status_label = pygame_gui.elements.UITextBox(html_text="<b>Sistem:</b> Așteptare comandă DJ...",
                                                         relative_rect=pygame.Rect(50, 580, 450, 90), 
                                                         manager=self.gui_manager)

    def draw_rounded_rect(self, surface, rect, color, radius=15):
        """Desenează un dreptunghi rotunjit curat, fără artefacte vizibile."""
        rect = pygame.Rect(rect)
        color = pygame.Color(*color)
        alpha = color.a
        
        # Creăm o suprafață temporară pentru transparență (SRCALPHA)
        shape_surf = pygame.Surface(rect.size, pygame.SRCALPHA)
        
        # Desenăm dreptunghiul cu colțuri rotunjite direct
        # Pygame se ocupă intern de antialiasing și îmbinări
        pygame.draw.rect(shape_surf, (color.r, color.g, color.b, alpha), 
                        (0, 0, rect.width, rect.height), border_radius=radius)
        
        surface.blit(shape_surf, rect.topleft)

    def draw_studio_deck(self):
        now = time.time() - self.start_time
        
        # 1. Fundal Master Gradient
        for y in range(self.screen_height):
            ratio = y / self.screen_height
            color = (int(12*(1-ratio)+5*ratio), int(12*(1-ratio)+5*ratio), int(22*(1-ratio)+10*ratio))
            pygame.draw.line(self.screen_ctrl, color, (0, y), (self.screen_width, y))

        # 2. Elemente Decorative
        for i in range(0, self.screen_width, 40):
            pygame.draw.line(self.screen_ctrl, (20, 20, 35), (i, 0), (i, self.screen_height), 1)

        # 3. Carduri Glassmorphism
        self.draw_rounded_rect(self.screen_ctrl, self.rect_players, CLR_GLASS, 20)
        self.draw_rounded_rect(self.screen_ctrl, self.rect_music, CLR_GLASS, 20)
        
        pygame.draw.rect(self.screen_ctrl, (0, 180, 180), self.rect_players, 1, border_radius=20)
        pygame.draw.rect(self.screen_ctrl, (0, 180, 180), self.rect_music, 1, border_radius=20)

        # 4. Vinil & Pickup
        v_angle = now * 2
        v_center = (90, 175)
        pygame.draw.circle(self.screen_ctrl, (5, 5, 8), v_center, 35) 
        pygame.draw.circle(self.screen_ctrl, (30, 30, 40), v_center, 30, 1) 
        pygame.draw.circle(self.screen_ctrl, CLR_NEON_PINK, v_center, 12) 
        pygame.draw.line(self.screen_ctrl, (200, 200, 200), (110, 310), (145, 345), 4)

    def render_all(self, time_delta):
        self.draw_studio_deck()
        self.gui_manager.update(time_delta)
        self.gui_manager.draw_ui(self.screen_ctrl)
        
        if not self.game_started:
            pulse = (math.sin(time.time() * 4) + 1) / 2
            glow_size = int(2 + pulse * 6)
            glow_color = (int(255 * pulse), 20, 147)
            for i in range(glow_size):
                pygame.draw.rect(self.screen_ctrl, glow_color, 
                                 self.btn_start.get_abs_rect().inflate(i*2, i*2), 1, border_radius=8)
        
        pygame.display.update()

    def draw_scoreboard(self, game):
        try:
            if pygame.mixer.music.get_busy():
                curr_pos = pygame.mixer.music.get_pos() / 1000.0
                path = game.playlist[game.current_song_idx]
                total_dur = SONG_DATA.get(path, {}).get("duration", 180)
                rem_time = max(0, total_dur - curr_pos)
            else: rem_time = 0

            data_to_send = {
                "scores": game.scores,
                "time_left": int(rem_time),
                "song_name": game.current_song_name,
                "num_players": game.num_players,
                "status": self.game_started
            }
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(json.dumps(data_to_send).encode(), ("127.0.0.1", UDP_SCORE_PORT))
        except: pass

    def update_status(self, msg):
        self.status_label.set_text(msg)    

    def __init__(self):
        pygame.init()
        # Mărim puțin fereastra pentru un aspect mai "pro"
        self.screen_width, self.screen_height = 550, 700
        self.screen_ctrl = pygame.display.set_mode((self.screen_width, self.screen_height))
        pygame.display.set_caption("🎧 STUDIO MASTER - Control Deck")
        
        self.gui_manager = pygame_gui.UIManager((self.screen_width, self.screen_height))
        
        # Fonturi
        self.font_main = pygame.font.SysFont("Segoe UI", 24, bold=True)
        self.font_small = pygame.font.SysFont("Segoe UI", 14)

        self.setup_ui_elements()
        self.clock = pygame.time.Clock()
        self.running = True
        self.game_started = False
        self.start_time = time.time()

    def setup_ui_elements(self):
        # Card Jucători
        self.rect_players = pygame.Rect(50, 100, 450, 150)
        pygame_gui.elements.UILabel(relative_rect=pygame.Rect(70, 115, 410, 30), 
                                    text="SETUP JUCĂTORI ACTIVI", manager=self.gui_manager)
        
        self.input_players = pygame_gui.elements.UITextEntryLine(relative_rect=pygame.Rect(215, 160, 120, 45), 
                                                               manager=self.gui_manager)
        self.input_players.set_text("1")

        # Card Muzică
        self.rect_music = pygame.Rect(50, 280, 450, 170)
        pygame_gui.elements.UILabel(relative_rect=pygame.Rect(70, 295, 410, 30), 
                                    text="CONFIGURARE PLAYLIST / CĂUTARE", manager=self.gui_manager)
        
        self.input_search = pygame_gui.elements.UITextEntryLine(relative_rect=pygame.Rect(80, 350, 390, 45), 
                                                              manager=self.gui_manager)
        self.input_search.set_text("Tzanca Uraganu - Trotinete")

        # Buton START
        self.btn_start = pygame_gui.elements.UIButton(relative_rect=pygame.Rect(150, 480, 250, 70), 
                                                     text="LANSEAZĂ SESIUNEA", manager=self.gui_manager)
        
        # Status Box
        self.status_label = pygame_gui.elements.UITextBox(html_text="<b>Sistem:</b> Așteptare comandă DJ...",
                                                         relative_rect=pygame.Rect(50, 580, 450, 90), 
                                                         manager=self.gui_manager)

    def draw_rounded_rect(self, surface, rect, color, radius=15):
        """Desenează un dreptunghi rotunjit cu Anti-Aliasing (fără pixeli urâți)."""
        rect = pygame.Rect(rect)
        color = pygame.Color(*color)
        alpha = color.a
        color.a = 0
        pos = rect.topleft
        rect.topleft = 0, 0
        rectangle = pygame.Surface(rect.size, pygame.SRCALPHA)

        circle = pygame.Surface([min(rect.size)*3]*2, pygame.SRCALPHA)
        pygame.draw.ellipse(circle, (color.r, color.g, b'#00' if color.b==0 else color.b, alpha), circle.get_rect(), 0)
        circle = pygame.transform.smoothscale(circle, [int(min(rect.size)*0.5)]*2)

        radius = min(radius, rect.width // 2, rect.height // 2)
        if radius > 0:
            rect_smooth = pygame.Surface(rect.size, pygame.SRCALPHA)
            pygame.draw.rect(rect_smooth, (color.r, color.g, color.b, alpha), rect.inflate(-radius*2, 0))
            pygame.draw.rect(rect_smooth, (color.r, color.g, color.b, alpha), rect.inflate(0, -radius*2))
            
            circle_rect = circle.get_rect()
            for corner in [(rect.left, rect.top), (rect.right-radius, rect.top), 
                           (rect.left, rect.bottom-radius), (rect.right-radius, rect.bottom-radius)]:
                rect_smooth.blit(circle, corner)
            surface.blit(rect_smooth, pos)
        else:
            pygame.draw.rect(surface, color, rect)

    def draw_studio_deck(self):
        now = time.time() - self.start_time
        
        # 1. Fundal Master Gradient
        for y in range(self.screen_height):
            ratio = y / self.screen_height
            # Gradient de la un Deep Navy la un Black luxos
            color = (int(12*(1-ratio)+5*ratio), int(12*(1-ratio)+5*ratio), int(22*(1-ratio)+10*ratio))
            pygame.draw.line(self.screen_ctrl, color, (0, y), (self.screen_width, y))

        # 2. Elemente Decorative de fundal (Linii tech)
        for i in range(0, self.screen_width, 40):
            pygame.draw.line(self.screen_ctrl, (20, 20, 35), (i, 0), (i, self.screen_height), 1)

        # 3. Carduri Glassmorphism (Fără pixeli vizibili)
        self.draw_rounded_rect(self.screen_ctrl, self.rect_players, CLR_GLASS, 20)
        self.draw_rounded_rect(self.screen_ctrl, self.rect_music, CLR_GLASS, 20)
        
        # Border subțire Cyan pentru carduri (pentru definiție)
        pygame.draw.rect(self.screen_ctrl, (0, 180, 180), self.rect_players, 1, border_radius=20)
        pygame.draw.rect(self.screen_ctrl, (0, 180, 180), self.rect_music, 1, border_radius=20)

        # 4. Iconițe stilizate (Vinil & Pickup)
        # Vinilul acum se rotește discret
        v_angle = now * 2
        v_center = (90, 175)
        pygame.draw.circle(self.screen_ctrl, (5, 5, 8), v_center, 35) # Disc
        pygame.draw.circle(self.screen_ctrl, (30, 30, 40), v_center, 30, 1) # Groove
        pygame.draw.circle(self.screen_ctrl, CLR_NEON_PINK, v_center, 12) # Center
        # Acul pickup-ului
        pygame.draw.line(self.screen_ctrl, (200, 200, 200), (110, 310), (145, 345), 4)

    def render_all(self, time_delta):
        self.draw_studio_deck()
        self.gui_manager.update(time_delta)
        self.gui_manager.draw_ui(self.screen_ctrl)
        
        # Buton START cu Glow Premium
        if not self.game_started:
            pulse = (math.sin(time.time() * 4) + 1) / 2
            # Glow exterior
            glow_size = int(2 + pulse * 6)
            glow_color = (int(255 * pulse), 20, 147)
            for i in range(glow_size):
                pygame.draw.rect(self.screen_ctrl, glow_color, 
                                 self.btn_start.get_abs_rect().inflate(i*2, i*2), 1, border_radius=8)
        
        pygame.display.update()

    def draw_scoreboard(self, game):
        try:
            if pygame.mixer.music.get_busy():
                curr_pos = pygame.mixer.music.get_pos() / 1000.0
                path = game.playlist[game.current_song_idx]
                total_dur = SONG_DATA.get(path, {}).get("duration", 180)
                rem_time = max(0, total_dur - curr_pos)
            else: rem_time = 0

            data_to_send = {
                "scores": game.scores,
                "time_left": int(rem_time),
                "song_name": game.current_song_name,
                "num_players": game.num_players,
                "status": self.game_started
            }
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(json.dumps(data_to_send).encode(), ("127.0.0.1", UDP_SCORE_PORT))
        except: pass

    def update_status(self, msg):
        self.status_label.set_text(msg)

    def __init__(self):
        pygame.init()
        self.screen_width, self.screen_height = 500, 650
        self.screen_ctrl = pygame.display.set_mode((self.screen_width, self.screen_height))
        pygame.display.set_caption("🎧 DJ DECK - Control Panel")
        
        # Managerul UI fără tema problematică
        self.gui_manager = pygame_gui.UIManager((self.screen_width, self.screen_height))

        self.setup_ui_elements()
        self.clock = pygame.time.Clock()
        self.running = True
        self.game_started = False
        self.score_display = None
        self.start_time = time.time()

    def setup_ui_elements(self):
        # Containere pentru organizare
        self.cont_p = pygame.Rect((50, 80), (400, 140))
        self.cont_m = pygame.Rect((50, 240), (400, 160))

        # Input Jucători
        pygame_gui.elements.UILabel(relative_rect=pygame.Rect((70, 90), (360, 20)), 
                                    text="CONFIGURARE JUCĂTORI", manager=self.gui_manager)
        self.input_players = pygame_gui.elements.UITextEntryLine(relative_rect=pygame.Rect((200, 130), (100, 50)), 
                                                               manager=self.gui_manager)
        self.input_players.set_text("1")

        # Input Muzică
        pygame_gui.elements.UILabel(relative_rect=pygame.Rect((70, 250), (360, 20)), 
                                    text="SELECTEAZĂ TRACK (YouTube/Search)", manager=self.gui_manager)
        self.input_search = pygame_gui.elements.UITextEntryLine(relative_rect=pygame.Rect((80, 290), (340, 50)), 
                                                              manager=self.gui_manager)
        self.input_search.set_text("Rockstar Post Malone")

        # Buton START (îl lăsăm în GUI manager dar îl desenăm noi peste)
        self.btn_start = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((125, 430), (250, 70)), 
                                                     text="START SESSION", manager=self.gui_manager)
        
        # Status
        self.status_label = pygame_gui.elements.UITextBox(html_text="Ready to mix...",
                                                         relative_rect=pygame.Rect((50, 520), (400, 100)), 
                                                         manager=self.gui_manager)

    # --- DESENARE MANUALA (FĂRĂ PIXELI URÂȚI) ---
    def draw_studio_deck(self):
        now = time.time() - self.start_time
        
        # 1. Gradient Fundal Studio
        for y in range(self.screen_height):
            ratio = y / self.screen_height
            color = (int(15*(1-ratio)+25*ratio), int(15*(1-ratio)+15*ratio), int(25*(1-ratio)+45*ratio))
            pygame.draw.line(self.screen_ctrl, color, (0, y), (self.screen_width, y))

        # 2. Note muzicale plutitoare
        for i, pos in enumerate([(80, 100), (420, 250), (100, 500), (350, 50)]):
            y_vib = math.sin(now * 2 + i) * 10
            pygame.draw.circle(self.screen_ctrl, (60, 60, 100), (pos[0], int(pos[1] + y_vib)), 5)
            pygame.draw.line(self.screen_ctrl, (60, 60, 100), (pos[0]+5, int(pos[1]+y_vib)), (pos[0]+5, int(pos[1]+y_vib-20)), 2)

        # 3. Carduri "Glass"
        for r in [self.cont_p, self.cont_m]:
            s = pygame.Surface((r.width, r.height), pygame.SRCALPHA)
            pygame.draw.rect(s, (255, 255, 255, 20), (0, 0, r.width, r.height), border_radius=15)
            pygame.draw.rect(s, (0, 255, 255, 50), (0, 0, r.width, r.height), width=2, border_radius=15)
            self.screen_ctrl.blit(s, r.topleft)

        # 4. Vinil & Pickup
        # Vinil
        pygame.draw.circle(self.screen_ctrl, (10, 10, 10), (90, 150), 30)
        pygame.draw.circle(self.screen_ctrl, (255, 20, 147), (90, 150), 10) # Centru roz
        # Pickup (Braț)

    def render_all(self, time_delta):
        self.draw_studio_deck()
        self.gui_manager.update(time_delta)
        self.gui_manager.draw_ui(self.screen_ctrl)
        
        # Efect Neon pe butonul de start peste GUI
        if not self.game_started:
            pulse = (math.sin(time.time() * 5) + 1) / 2
            color = (int(255 * pulse), 20, 147)
            pygame.draw.rect(self.screen_ctrl, color, self.btn_start.get_abs_rect(), width=3, border_radius=5)
        
        pygame.display.update()

    def setup_score_window(self):
        self.score_display = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
        pygame.display.set_caption("SCOREBOARD LIVE")

    def draw_scoreboard(self, game):
        # Această metodă acum doar TRIMITE datele prin rețea către scriptul 2
        try:
            if pygame.mixer.music.get_busy():
                # Calculăm timpul real
                curr_pos = pygame.mixer.music.get_pos() / 1000.0
                # Luăm durata din SONG_DATA dacă există, altfel punem 180s default
                path = game.playlist[game.current_song_idx]
                total_dur = SONG_DATA.get(path, {}).get("duration", 180)
                rem_time = max(0, total_dur - curr_pos)
            else:
                rem_time = 0

            # Pregătim pachetul de date
            data_to_send = {
                "scores": game.scores,
                "time_left": int(rem_time),
                "song_name": game.current_song_name,
                "num_players": game.num_players,
                "status": self.game_started
            }
            
            # Trimitem prin UDP către portul 4445 (unde ascultă scriptul 2)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(json.dumps(data_to_send).encode(), ("127.0.0.1", UDP_SCORE_PORT))
        except Exception as e:
            print(f"Eroare trimitere scor: {e}")

    def update_status(self, msg):
        self.status_label.set_text(msg)

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
# FUNCȚII AUXILIARE (SCOASE DIN CLASĂ)
# ════════════════════════════════════════════════════════════════════════
def proceseaza_melodie_online(cautare):
    print(f"\n⏳ Caut pe YouTube: '{cautare}'...")
    
    if not os.path.exists('temp_songs'):
        os.makedirs('temp_songs')
        
    cale_fisier = 'temp_songs/melodie_curenta.mp3'
    if os.path.exists(cale_fisier):
        try: os.remove(cale_fisier)
        except: pass

    # 1. Descărcarea
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': cale_fisier[:cale_fisier.rfind('.')] + '.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'noplaylist': True,
        'default_search': 'ytsearch1:',
        'quiet': True,
        'no_warnings': True
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            rezultat = ydl.extract_info(cautare, download=True)
            titlu = rezultat['entries'][0]['title']
            print(f"✅ Am descărcat: {titlu}")
    except Exception as e:
        print(f"❌ Eroare la descărcare: {e}")
        return None

    # 2. Analiza BPM cu Librosa
    print("🧠 Analizez ritmul (BPM)... Te rog așteaptă (poate dura 10-20 secunde)...")
    try:
        # Încărcăm doar primele 45 de secunde pentru a grăbi procesul masiv
        y, sr = librosa.load(cale_fisier, duration=None)
        duration = librosa.get_duration(y=y, sr=sr)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        
        # Extragem valoarea numerică (librosa returnează uneori un array, alteori un float)
        bpm = float(tempo[0]) if hasattr(tempo, '__iter__') else float(tempo)
        bpm = round(bpm)
        print(f"🎵 BPM Detectat: {bpm}")
        
        return {"path": cale_fisier, "name": titlu, "bpm": bpm}
    except Exception as e:
        print(f"❌ Eroare la analiza audio: {e}")
        return None
     

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
# MAIN LOOP MODIFICAT
# ════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    ui = InterfaceManager()
    game = None
    net = None
    
    while ui.running:
        time_delta = ui.clock.tick(60)/1000.0
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                ui.running = False
            
            ui.gui_manager.process_events(event)
            
            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == ui.btn_start:
                    try:
                        n_players = int(ui.input_players.get_text())
                        search_term = ui.input_search.get_text()

                        import subprocess
                        import sys
                        # Aceasta porneste automat al doilea script intr-o fereastra noua
                        subprocess.Popen([sys.executable, "scoreboard.py"])

                        ui.update_status(f"Searching: {search_term}...")
                        ui.render_all(0.01)
                        
                        res = proceseaza_melodie_online(search_term)
                        if res:
                            # AICI luăm durata reală pentru cronometru
                            y_dur, sr_dur = librosa.load(res["path"], sr=None)
                            real_duration = librosa.get_duration(y=y_dur, sr=sr_dur)
                            
                            SONG_DATA[res["path"]] = {
                                "bpm": res["bpm"], 
                                "name": res["name"], 
                                "duration": real_duration
                            }
                            
                            game = PianoTilesPro(n_players, [res["path"]])
                            ui.game_started = True
                            # NU mai apelăm setup_score_window() aici!
                            net = NetworkManager(game)
                            threading.Thread(target=net.run, daemon=True).start()
                            ui.update_status("LIVE SESSION ACTIVE")
                        else:
                            ui.update_status("Download Error!")
                    except Exception as e:
                        ui.update_status(f"Error: {e}")

        # Randăm consola de DJ
        ui.render_all(time_delta)
        
        # Dacă jocul rulează, trimitem datele către scoreboard.py
        if ui.game_started and game:
            ui.draw_scoreboard(game)

    pygame.quit()