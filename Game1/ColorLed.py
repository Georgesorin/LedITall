import socket
import time
import threading
import random
import os
import json

# --- Configuration ---
def _load_config():
    defaults = {
        "device_ip": "192.168.1.135", ##Change this to your device's IP and port if needed
        "send_port": 4226, 
        "recv_port": 4444,
        "bind_ip": "0.0.0.0"
    }
    return defaults

CONFIG = _load_config()

# --- Networking Constants ---
UDP_SEND_IP = CONFIG.get("device_ip", "192.168.1.135")
UDP_SEND_PORT = CONFIG.get("send_port", 4226)
UDP_LISTEN_PORT = CONFIG.get("recv_port", 4444)

# --- Matrix Constants ---
NUM_CHANNELS = 8
LEDS_PER_CHANNEL = 64
FRAME_DATA_LENGTH = NUM_CHANNELS * LEDS_PER_CHANNEL * 3

BOARD_WIDTH = 16
BOARD_HEIGHT = 32 # 8 canale * 4 randuri

BLACK = (0, 0, 0)

# --- Game Logic ---
class LedToggleGame:
    def __init__(self):
        self.board = [[BLACK for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
        self.running = True
        self.lock = threading.RLock()
        
        # Acum ascultăm TOATE cele 512 LED-uri (8 canale * 64)
        self.button_states = [False] * 512
        self.prev_button_states = [False] * 512

    def tick(self):
        # Aceasta functie verifica constant daca ai apasat ceva nou
        for i in range(512):
            is_pressed = self.button_states[i]
            was_pressed = self.prev_button_states[i]
            
            # Actionam doar cand butonul tocmai a fost apasat (evita palpairea)
            if is_pressed and not was_pressed:
                self.handle_click(i)
                
            self.prev_button_states[i] = is_pressed

    def handle_click(self, led_idx):
        # Calculam ce canal si ce index are in acel canal
        channel = led_idx // 64
        idx_in_channel = led_idx % 64
        
        row_in_channel = idx_in_channel // 16
        col_raw = idx_in_channel % 16
        
        # Logica ta de zigzag
        if row_in_channel % 2 == 0: 
            x = col_raw
        else: 
            x = 15 - col_raw
            
        y = (channel * 4) + row_in_channel

        # Schimbam culoarea (Toggle)
        with self.lock:
            if self.board[y][x] == BLACK:
                # Daca e stins, ii dam o culoare random puternica
                r = random.randint(100, 255)
                g = random.randint(100, 255)
                b = random.randint(100, 255)
                self.board[y][x] = (r, g, b)
            else:
                # Daca e aprins, il stingem
                self.board[y][x] = BLACK

    def render(self):
        buffer = bytearray(FRAME_DATA_LENGTH)
        with self.lock:
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    self.set_led(buffer, x, y, self.board[y][x])
        return buffer

    def set_led(self, buffer, x, y, color):
        if x < 0 or x >= 16: return
        channel = y // 4
        if channel >= 8: return
        
        row_in_channel = y % 4
        if row_in_channel % 2 == 0: 
            led_index = row_in_channel * 16 + x
        else: 
            led_index = row_in_channel * 16 + (15 - x)
            
        block_size = NUM_CHANNELS * 3
        offset = led_index * block_size + channel
        
        if offset + NUM_CHANNELS*2 < len(buffer):
            # Formatul tau hardware (G, R, B)
            buffer[offset] = color[1] 
            buffer[offset + NUM_CHANNELS] = color[0]
            buffer[offset + NUM_CHANNELS*2] = color[2]

# --- Networking ---
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
            try: self.sock_send.bind((bind_ip, 0))
            except: pass
        
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
        if self.sequence_number == 0: self.sequence_number = 1
        
        target_ip = UDP_SEND_IP
        port = UDP_SEND_PORT
        
        # --- 1. Start Packet ---
        rand1, rand2 = random.randint(0, 127), random.randint(0, 127)
        start_packet = bytearray([0x75, rand1, rand2, 0x00, 0x08, 0x02, 0x00, 0x00, 0x33, 0x44, (self.sequence_number >> 8) & 0xFF, self.sequence_number & 0xFF, 0x00, 0x00, 0x00, 0x0E, 0x00])
        try: 
            self.sock_send.sendto(start_packet, (target_ip, port))
            self.sock_send.sendto(start_packet, ("127.0.0.1", port)) # Trimitere dubla ca in original
        except: pass

        # --- 2. FFF0 Packet ---
        rand1, rand2 = random.randint(0, 127), random.randint(0, 127)
        fff0_payload = bytearray()
        for _ in range(NUM_CHANNELS): fff0_payload += bytes([(LEDS_PER_CHANNEL >> 8) & 0xFF, LEDS_PER_CHANNEL & 0xFF])
        fff0_internal = bytearray([0x02, 0x00, 0x00, 0x88, 0x77, 0xFF, 0xF0, (len(fff0_payload) >> 8) & 0xFF, (len(fff0_payload) & 0xFF)]) + fff0_payload
        fff0_len = len(fff0_internal) - 1
        fff0_packet = bytearray([0x75, rand1, rand2, (fff0_len >> 8) & 0xFF, (fff0_len & 0xFF)]) + fff0_internal + bytearray([0x1E, 0x00])
        try: 
            self.sock_send.sendto(fff0_packet, (target_ip, port))
            self.sock_send.sendto(fff0_packet, ("127.0.0.1", port))
        except: pass
        
        # --- 3. Data Packets ---
        chunk_size = 984 
        data_packet_index = 1
        for i in range(0, len(frame_data), chunk_size):
            rand1, rand2 = random.randint(0, 127), random.randint(0, 127)
            chunk = frame_data[i:i+chunk_size]
            internal_data = bytearray([0x02, 0x00, 0x00, (0x8877 >> 8) & 0xFF, (0x8877 & 0xFF), (data_packet_index >> 8) & 0xFF, (data_packet_index & 0xFF), (len(chunk) >> 8) & 0xFF, (len(chunk) & 0xFF)]) + chunk
            payload_len = len(internal_data) - 1 
            packet = bytearray([0x75, rand1, rand2, (payload_len >> 8) & 0xFF, (payload_len & 0xFF)]) + internal_data
            packet.append(0x1E if len(chunk) == 984 else 0x36)
            packet.append(0x00)
            try: 
                self.sock_send.sendto(packet, (target_ip, port))
                self.sock_send.sendto(packet, ("127.0.0.1", port))
            except: pass
            data_packet_index += 1
            time.sleep(0.005)

        # --- 4. End Packet ---
        rand1, rand2 = random.randint(0, 127), random.randint(0, 127)
        end_packet = bytearray([0x75, rand1, rand2, 0x00, 0x08, 0x02, 0x00, 0x00, 0x55, 0x66, (self.sequence_number >> 8) & 0xFF, self.sequence_number & 0xFF, 0x00, 0x00, 0x00, 0x0E, 0x00])
        try: 
            self.sock_send.sendto(end_packet, (target_ip, port))
            self.sock_send.sendto(end_packet, ("127.0.0.1", port))
        except: pass

    def recv_loop(self):
        while self.running:
            try:
                data, _ = self.sock_recv.recvfrom(2048)
                # Parsam datele pentru TOATE cele 8 canale, nu doar ultimul!
                if len(data) >= 1373 and data[0] == 0x88:
                    for c in range(8):
                        offset = 2 + (c * 171) + 1 
                        ch_data = data[offset : offset + 64]
                        for i, val in enumerate(ch_data):
                            global_idx = (c * 64) + i
                            self.game.button_states[global_idx] = (val == 0xCC)
            except Exception:
                pass

    def start_bg(self):
        t1 = threading.Thread(target=self.send_loop)
        t2 = threading.Thread(target=self.recv_loop)
        t1.daemon = True
        t2.daemon = True
        t1.start()
        t2.start()

def game_thread_func(game):
    while game.running:
        game.tick()
        time.sleep(0.01)

if __name__ == "__main__":
    game = LedToggleGame()
    net = NetworkManager(game)
    net.start_bg()
    
    gt = threading.Thread(target=game_thread_func, args=(game,))
    gt.daemon = True
    gt.start()
    
    print("Matrix Toggle pornit. Da click oriunde pe matrice!")
    print("Scrie 'quit' ca sa iesi.")
    
    try:
        while game.running:
            cmd = input("> ").strip().lower()
            if cmd == 'quit' or cmd == 'exit':
                game.running = False
                break
    except KeyboardInterrupt:
        game.running = False

    net.running = False
    print("Exiting...")