import socket
import threading
import time
import random
from .constants import *

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
