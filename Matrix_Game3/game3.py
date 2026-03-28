import socket
import time
import threading
import random
import os
import math

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("Pygame lipseste. Instaleaza cu: pip install pygame")

# --- Configurare Retea Matrix Room ---
UDP_SEND_IP = "255.255.255.255"
UDP_SEND_PORT = 6967
UDP_LISTEN_PORT = 5555

NUM_CHANNELS = 8
LEDS_PER_CHANNEL = 64
FRAME_DATA_LENGTH = NUM_CHANNELS * LEDS_PER_CHANNEL * 3

BOARD_WIDTH = 16
BOARD_HEIGHT = 32 # 512 placi fizice

# --- Culori Joc ---
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
CYAN = (0, 255, 255)
MAGENTA = (255, 0, 255)
ORANGE = (255, 165, 0)
PURPLE = (128, 0, 128)

COLORS_LIST = [RED, GREEN, BLUE, YELLOW, CYAN, MAGENTA, ORANGE, PURPLE]

# --- Font pentru Numaratoare (5x7 scalat x2) ---
DIGITS = {
    3: [" ### ", "#   #", "    #", "  ## ", "    #", "#   #", " ### "],
    2: [" ### ", "#   #", "    #", "  ## ", " #   ", "#    ", "#####"],
    1: ["  #  ", " ##  ", "# #  ", "  #  ", "  #  ", "  #  ", "#####"]
}

# --- Font compact pentru LedITall pe orizontala ---
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
        if self.enabled:
            pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
            self._generate_sounds()
            self.snd_tick = pygame.mixer.Sound("tick.wav")
            self.snd_error = pygame.mixer.Sound("error.wav")
            self.snd_win = pygame.mixer.Sound("win.wav")
            self.snd_start = pygame.mixer.Sound("start.wav")

    def _generate_sounds(self):
        import wave, struct
        def make_wav(name, freq, duration, volume=0.5):
            if os.path.exists(name): return
            sample_rate = 44100
            with wave.open(name, 'w') as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(sample_rate)
                for i in range(int(sample_rate * duration)):
                    value = int(volume * 32767.0 * math.sin(2.0 * math.pi * freq * i / sample_rate))
                    f.writeframesraw(struct.pack('<h', value))
        
        make_wav("tick.wav", 1000, 0.05)   
        make_wav("error.wav", 150, 0.8)    
        make_wav("win.wav", 600, 0.4)      
        make_wav("start.wav", 400, 0.8)    

    def play(self, name):
        if not self.enabled: return
        try:
            if name == 'tick': self.snd_tick.play()
            elif name == 'error': self.snd_error.play()
            elif name == 'win': self.snd_win.play()
            elif name == 'start': self.snd_start.play()
        except: pass

# --- Logica Jocului Fizic ---
class PhysicalBlockParty:
    def __init__(self):
        self.board = [[BLACK for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
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

    def initiate_start_sequence(self):
        with self.lock:
            self.state = 'BRANDING_SEQUENCE'
            self.sequence_timer = 3.0 
            self.last_tick_time = time.time()
            self.last_seq_sec = 6
            print("\n" + "="*40)
            print("✨ PREGATIRE JOC... BRANDING INIT ✨")
            print("="*40)

    def start_game_logic(self):
        self.round = 1
        self.score = 0
        self.global_timer = 15 * 60  
        self.last_printed_minute = 15
        
        print("\n" + "🚀"*10)
        print(" JOCUL A INCEPUT! TIMP: 15 MINUTE")
        print("🚀"*10)
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
            print(f"\n--- RUNDA {self.round} | SCOR ACTUAL: {self.score} ---")
            print("👁️ Memorati culoarea!")

    def generate_blocks(self):
        """Genereaza un grid de blocuri care mixeaza orizontale cu verticale fara a lasa goluri."""
        with self.lock:
            blocks = [] 
            
            if self.round <= 4:
                target_count = random.randint(6, 8)
                for gy in range(8): 
                    for gx in range(4): 
                        blocks.append((gx * 4, gy * 4, 4, 4))
                        
            elif self.round <= 8:
                target_count = random.randint(8, 12)
                for gy in range(8): 
                    for gx in range(4):
                        px, py = gx * 4, gy * 4
                        if random.choice([True, False]):
                            blocks.append((px, py, 4, 2))
                            blocks.append((px, py + 2, 4, 2))
                        else:
                            blocks.append((px, py, 2, 4))
                            blocks.append((px + 2, py, 2, 4))
                            
            else:
                target_count = random.randint(12, 18)
                for gy in range(16): 
                    for gx in range(8): 
                        blocks.append((gx * 2, gy * 2, 2, 2))

            total_blocks = len(blocks)
            wrong_colors = [c for c in COLORS_LIST if c != self.target_color]
            
            block_colors = [random.choice(wrong_colors) for _ in range(total_blocks)]
            
            target_indices = random.sample(range(total_blocks), min(target_count, total_blocks))
            for idx in target_indices:
                block_colors[idx] = self.target_color
                
            for i, (bx, by, bw, bh) in enumerate(blocks):
                color = block_colors[i]
                for y in range(by, by + bh):
                    for x in range(bx, bx + bw):
                        self.board[y][x] = color

    def evaluate_floor(self):
        wrong_tiles_pressed = 0
        correct_tiles_pressed = 0
        
        with self.lock:
            for i in range(512):
                if self.button_states[i]: 
                    channel = i // 64
                    idx_in_channel = i % 64
                    r_in_c = idx_in_channel // 16
                    c_raw = idx_in_channel % 16
                    x = c_raw if r_in_c % 2 == 0 else 15 - c_raw
                    y = (channel * 4) + r_in_c
                    
                    if self.board[y][x] != self.target_color:
                        wrong_tiles_pressed += 1
                    else:
                        correct_tiles_pressed += 1

            if wrong_tiles_pressed > 0:
                penalty = wrong_tiles_pressed * 5
                self.score -= penalty
                print(f"❌ EROARE! Ati calcat pe {wrong_tiles_pressed} placi gresite.")
                print(f"📉 Penalizare: -{penalty} puncte. Scor actual: {self.score}")
                self.audio.play('error')
                
                for y in range(BOARD_HEIGHT):
                    for x in range(BOARD_WIDTH):
                        self.board[y][x] = RED
            
            elif correct_tiles_pressed > 0:
                self.score += 10
                print(f"✅ PERFECT! Toti sunteti in siguranta.")
                print(f"📈 Bonus: +10 puncte. Scor actual: {self.score}")
                self.audio.play('win')
                self.round += 1
                
                for y in range(BOARD_HEIGHT):
                    for x in range(BOARD_WIDTH):
                        if self.board[y][x] != self.target_color:
                            self.board[y][x] = BLACK
            else:
                print("⚠️ Nimeni nu a calcat pe nicio placa! 0 puncte.")
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
            print("\n" + "🌟"*20)
            print("   TIMPUL A EXPIRAT! JOCUL S-A TERMINAT")
            print(f"   SCORUL VOSTRU FINAL ESTE: {self.score} PUNCTE")
            print("🌟"*20 + "\n")
            
            self.audio.play('win')
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    self.board[y][x] = WHITE

    def draw_branding(self, t):
        """Deseneaza textul LedITall rotit la 90 grade, citibil pe axa lunga (32 placi)"""
        for y in range(BOARD_HEIGHT):
            for x in range(BOARD_WIDTH):
                self.board[y][x] = (10, 0, 20) # Fundal mov inchis subtil

        curr_y = 2 # Incepem de la placa 2 (pentru a-l centra perfect pe 32)
        for char in TEXT_BRAND:
            if char in FONT_LEDITALL:
                glyph = FONT_LEDITALL[char]
                char_width = len(glyph[0])
                for r_idx, row in enumerate(glyph):
                    for c_idx, pixel in enumerate(row):
                        if pixel == '#':
                            # Prin inversarea r_idx cu c_idx textul se scrie pe lungime
                            board_y = curr_y + c_idx
                            board_x = 10 - r_idx # Centram litera de inaltime 5 pe latimea camerei de 16
                            
                            wave = (math.sin(board_y * 0.5 + board_x * 0.5 - t * 10.0) + 1) / 2
                            intensity = 0.4 + (wave * 0.6)
                            
                            r = int(255 * intensity)
                            g = int(50 * intensity)
                            b = int(200 * intensity)
                            
                            if 0 <= board_y < BOARD_HEIGHT and 0 <= board_x < BOARD_WIDTH:
                                self.board[board_y][board_x] = (r, g, b)
                
                # Urmatoarea litera
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
                    self.audio.play('tick')
                    self.last_seq_sec = current_digit
                    
                    with self.lock:
                        for y in range(BOARD_HEIGHT):
                            for x in range(BOARD_WIDTH):
                                self.board[y][x] = BLACK
                                
                        if current_digit in DIGITS:
                            template = DIGITS[current_digit]
                            start_x, start_y = 3, 9
                            
                            for row_idx, row_str in enumerate(template):
                                for col_idx, char in enumerate(row_str):
                                    if char == '#':
                                        px = start_x + col_idx * 2
                                        py = start_y + row_idx * 2
                                        self.board[py][px] = WHITE
                                        self.board[py][px+1] = WHITE
                                        self.board[py+1][px] = WHITE
                                        self.board[py+1][px+1] = WHITE
                                        
            if self.sequence_timer <= 0:
                self.start_game_logic()
            return
            
        self.global_timer -= dt
        
        current_minute = int(self.global_timer // 60)
        if current_minute != self.last_printed_minute and current_minute >= 0:
            print(f"⏳ Timp global ramas: {current_minute} minute")
            self.last_printed_minute = current_minute

        if self.global_timer <= 0:
            self.finish_game()
            return

        if self.state == 'SHOW_TARGET':
            self.round_timer -= dt

            if self.round_timer <= 0:
                self.generate_blocks()
                self.state = 'PLAYING'
                self.round_timer = max(3.0, 8.5 - (self.round * 0.4))
                self.last_second_beep = int(self.round_timer)
                print("🏃 FUGEEETI catre culoare!")

        elif self.state == 'PLAYING':
            self.round_timer -= dt
            current_sec = int(self.round_timer)
            if current_sec != self.last_second_beep and current_sec > 0:
                self.audio.play('tick')
                self.last_second_beep = current_sec

            if self.round_timer <= 0:
                self.evaluate_floor()

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
        except: pass

    def send_loop(self):
        while self.running:
            frame = self.game.render()
            self.send_packet(frame)
            time.sleep(0.05) 

    def send_packet(self, frame_data):
        self.sequence_number = (self.sequence_number + 1) & 0xFFFF
        if self.sequence_number == 0: self.sequence_number = 1
        port = UDP_SEND_PORT
        
        sp = bytearray([0x75, random.randint(0,127), random.randint(0,127), 0x00, 0x08, 0x02, 0x00, 0x00, 0x33, 0x44, (self.sequence_number >> 8) & 0xFF, self.sequence_number & 0xFF, 0x00, 0x00, 0x00, 0x0E, 0x00])
        try: self.sock_send.sendto(sp, (UDP_SEND_IP, port)); self.sock_send.sendto(sp, ("127.0.0.1", port))
        except: pass

        f_p = bytearray()
        for _ in range(NUM_CHANNELS): f_p += bytes([(LEDS_PER_CHANNEL >> 8) & 0xFF, LEDS_PER_CHANNEL & 0xFF])
        f_i = bytearray([0x02, 0x00, 0x00, 0x88, 0x77, 0xFF, 0xF0, (len(f_p) >> 8) & 0xFF, (len(f_p) & 0xFF)]) + f_p
        f_pkt = bytearray([0x75, random.randint(0,127), random.randint(0,127), ((len(f_i)-1) >> 8) & 0xFF, ((len(f_i)-1) & 0xFF)]) + f_i + bytearray([0x1E, 0x00])
        try: self.sock_send.sendto(f_pkt, (UDP_SEND_IP, port)); self.sock_send.sendto(f_pkt, ("127.0.0.1", port))
        except: pass
        
        chunk_size = 984 
        d_idx = 1
        for i in range(0, len(frame_data), chunk_size):
            chk = frame_data[i:i+chunk_size]
            d_i = bytearray([0x02, 0x00, 0x00, 0x88, 0x77, (d_idx >> 8) & 0xFF, d_idx & 0xFF, (len(chk) >> 8) & 0xFF, (len(chk) & 0xFF)]) + chk
            d_pkt = bytearray([0x75, random.randint(0,127), random.randint(0,127), ((len(d_i)-1) >> 8) & 0xFF, ((len(d_i)-1) & 0xFF)]) + d_i
            d_pkt.append(0x1E if len(chk) == 984 else 0x36); d_pkt.append(0x00)
            try: self.sock_send.sendto(d_pkt, (UDP_SEND_IP, port)); self.sock_send.sendto(d_pkt, ("127.0.0.1", port))
            except: pass
            d_idx += 1; time.sleep(0.005)

        ep = bytearray([0x75, random.randint(0,127), random.randint(0,127), 0x00, 0x08, 0x02, 0x00, 0x00, 0x55, 0x66, (self.sequence_number >> 8) & 0xFF, self.sequence_number & 0xFF, 0x00, 0x00, 0x00, 0x0E, 0x00])
        try: self.sock_send.sendto(ep, (UDP_SEND_IP, port)); self.sock_send.sendto(ep, ("127.0.0.1", port))
        except: pass

    def recv_loop(self):
        while self.running:
            try:
                data, _ = self.sock_recv.recvfrom(2048)
                if len(data) >= 1373 and data[0] == 0x88:
                    for c in range(8):
                        offset = 2 + (c * 171) + 1 
                        for i, val in enumerate(data[offset : offset + 64]):
                            self.game.button_states[(c * 64) + i] = (val == 0xCC)
            except: pass

if __name__ == "__main__":
    game = PhysicalBlockParty()
    net = NetworkManager(game)
    
    threading.Thread(target=net.send_loop, daemon=True).start()
    threading.Thread(target=net.recv_loop, daemon=True).start()
    
    print("="*40)
    print("MATRIX ROOM: BLOCK PARTY MARATHON")
    print("="*40)
    print("Scrie 'start' si apasa Enter pentru a incepe!")
    print("Scrie 'quit' pentru a iesi.")
    
    def logic_loop():
        while game.running:
            game.tick()
            time.sleep(0.01) 
            
    threading.Thread(target=logic_loop, daemon=True).start()
    
    try:
        while game.running:
            cmd = input("> ").strip().lower()
            if cmd == 'start':
                game.initiate_start_sequence()
            elif cmd == 'quit' or cmd == 'exit':
                game.running = False
                break
    except KeyboardInterrupt:
        game.running = False

    net.running = False