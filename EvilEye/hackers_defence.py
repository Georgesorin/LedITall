"""
hackers_defense.py – Hackers / Apărarea Bazei for Evil Eye LED hardware

Stage-based co-op game
──────────────────────
• 2–4 active walls.
• Viruses spawn on all active walls.
• Players clear viruses by pressing lit buttons.
• If a wall exceeds 5 active viruses in a stage, it locks for the rest of that stage.
• A locked wall reduces the maximum stars obtainable in that stage by 1.
• Locked walls are automatically reset and unlocked at the start of the next stage.
• Stage durations grow over time:
    stage 1 = 30s
    stage 2 = 40s
    stage 3 = 50s
    ...
• Total game duration is capped at 10 minutes.
• Spread gets faster every stage.
• Each stage awards up to N stars, where N = number of active players/walls.
• If one wall locked during the stage, max stars becomes N-1 for that stage.
"""

import os
import sys
import random
import threading
import time
import socket
import struct
import tkinter as tk

# ── Import LightService from sibling Controller.py ───────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from Controller import (
    LightService, load_config, save_config,
    LEDS_PER_CHANNEL,
)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except Exception:
    PSUTIL_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
MAX_WALLS = 4
MIN_WALLS = 2

EYE_LED = 0
BUTTONS = list(range(1, 11))   # protocol buttons = 1..10

OVERLOAD_LIMIT = 5
MAX_GAME_SECONDS = 600.0
BASE_STAGE_SECONDS = 30.0
STAGE_STEP_SECONDS = 10.0

POINT_CLEAR = 1
POINT_LOCK_PENALTY = 5

DISCOVERY_RECV_PORT = 7800
DISCOVERY_SEND_PORT = 4626

RED    = (255,   0,   0)
GREEN  = (  0, 255,   0)
YELLOW = (255, 200,   0)
ORANGE = (255, 120,   0)
BLUE   = (  0, 120, 255)
WHITE  = (255, 255, 255)
OFF    = (  0,   0,   0)
DIM    = ( 25,  25,  25)

TEAM_HEX = ["#ff3c00", "#0064ff", "#00d23c", "#c800c8"]

S_SETUP    = "setup"
S_ACTIVE   = "active"
S_GAMEOVER = "gameover"

BG_DARK  = "#0f0f0f"
BG_MID   = "#1e1e1e"
BG_PANEL = "#252525"
FG_MAIN  = "#f0f0f0"
FG_DIM   = "#666666"
FG_GREEN = "#00ff88"
FG_RED   = "#ff4444"
FG_GOLD  = "#ffd700"
FG_BLUE  = "#44aaff"

FONT_SM = ("Consolas", 12, "bold")
FONT_XS = ("Consolas", 10)

TICK_RATE = 1.0 / 20.0
INPUT_DEBOUNCE_S = 0.08

STAGE_CONFIGS = [
    {"spawn_interval": 1.40, "spawn_count": 1},
    {"spawn_interval": 1.15, "spawn_count": 1},
    {"spawn_interval": 0.95, "spawn_count": 2},
    {"spawn_interval": 0.80, "spawn_count": 2},
    {"spawn_interval": 0.65, "spawn_count": 3},
    {"spawn_interval": 0.55, "spawn_count": 3},
    {"spawn_interval": 0.45, "spawn_count": 4},
]


# ─────────────────────────────────────────────────────────────────────────────
# UI helpers
# ─────────────────────────────────────────────────────────────────────────────
def _make_lbl_btn(parent, text, command, bg, fg=FG_MAIN, **kw):
    hover_bg = kw.pop("hover_bg", "#555")
    lbl = tk.Label(parent, text=text, bg=bg, fg=fg,
                   font=kw.pop("font", FONT_SM),
                   padx=kw.pop("padx", 20), pady=kw.pop("pady", 10),
                   cursor="hand2", **kw)
    lbl.bind("<Button-1>", lambda e: command())
    lbl.bind("<Enter>", lambda e: lbl.configure(bg=hover_bg))
    lbl.bind("<Leave>", lambda e: lbl.configure(bg=bg))
    return lbl


def _seg_btn(parent, text, var, value, **kw):
    active_bg = kw.get("active_bg", "#ff3c00")
    inactive_bg = "#383838"

    lbl = tk.Label(parent, text=text,
                   bg=inactive_bg, fg=FG_MAIN,
                   font=kw.get("font", FONT_SM),
                   width=kw.get("width", 6),
                   height=kw.get("height", 1),
                   cursor="hand2")

    def _refresh(*_):
        lbl.configure(bg=active_bg if var.get() == value else inactive_bg)

    lbl.bind("<Button-1>", lambda e: var.set(value))
    lbl.bind("<Enter>", lambda e: lbl.configure(
        bg=active_bg if var.get() == value else "#4a4a4a"))
    lbl.bind("<Leave>", lambda e: _refresh())
    var.trace_add("write", _refresh)
    _refresh()
    return lbl


# ─────────────────────────────────────────────────────────────────────────────
# Network discovery helpers
# ─────────────────────────────────────────────────────────────────────────────
def calc_sum(data: bytes) -> int:
    return sum(data) & 0xFF


def ip_to_int(ip: str) -> int:
    return struct.unpack("!I", socket.inet_aton(ip))[0]


def int_to_ip(value: int) -> str:
    return socket.inet_ntoa(struct.pack("!I", value))


def broadcast_from_ip_mask(ip: str, netmask: str) -> str:
    ip_i = ip_to_int(ip)
    mask_i = ip_to_int(netmask)
    bcast_i = ip_i | (~mask_i & 0xFFFFFFFF)
    return int_to_ip(bcast_i)


def get_local_interfaces():
    interfaces = []

    if PSUTIL_AVAILABLE:
        seen = set()
        for iface_name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family != socket.AF_INET:
                    continue

                ip = getattr(addr, "address", "")
                if not ip or ip.startswith("127."):
                    continue

                bcast = getattr(addr, "broadcast", None)
                mask = getattr(addr, "netmask", None)

                if not bcast:
                    if ip.startswith("169.254."):
                        bcast = "169.254.255.255"
                    elif mask:
                        try:
                            bcast = broadcast_from_ip_mask(ip, mask)
                        except Exception:
                            bcast = "255.255.255.255"
                    else:
                        bcast = "255.255.255.255"

                interfaces.append((iface_name, ip, bcast))

        if interfaces:
            interfaces.sort(key=lambda item: (0 if item[1].startswith("169.254.") else 1, item[0], item[1]))
            return interfaces

    # fallback fără psutil
    seen = set()
    hostname = socket.gethostname()
    candidates = set()

    try:
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_DGRAM):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                candidates.add(ip)
    except Exception:
        pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            candidates.add(ip)
    except Exception:
        pass

    try:
        local_ip = socket.gethostbyname(hostname)
        if local_ip and not local_ip.startswith("127."):
            candidates.add(local_ip)
    except Exception:
        pass

    ordered = sorted(candidates, key=lambda ip: (0 if ip.startswith("169.254.") else 1, ip))
    for idx, ip in enumerate(ordered):
        iface_name = "Ethernet" if ip.startswith("169.254.") else f"Interface {idx}"
        bcast = "169.254.255.255" if ip.startswith("169.254.") else broadcast_from_ip_mask(ip, "255.255.255.0")
        key = (iface_name, ip, bcast)
        if key not in seen:
            seen.add(key)
            interfaces.append(key)

    return interfaces


def build_discovery_packet():
    rand1, rand2 = random.randint(0, 127), random.randint(0, 127)
    payload = bytearray([
        0x0A, 0x02, *b"KX-HC04", 0x03,
        0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x14
    ])
    pkt = bytearray([0x67, rand1, rand2, len(payload)]) + payload
    pkt.append(calc_sum(pkt))
    return pkt, rand1, rand2


def discover_devices_on_interface(bind_ip: str, broadcast_ip: str,
                                  send_port: int = DISCOVERY_SEND_PORT,
                                  timeout_s: float = 3.0):
    devices = []

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        try:
            sock.bind((bind_ip, 0))   # important: port random, nu 7800
        except Exception:
            try:
                sock.bind(("", 0))
            except Exception:
                pass

        pkt, r1, r2 = build_discovery_packet()
        sock.sendto(pkt, (broadcast_ip, send_port))

        sock.settimeout(0.5)
        end_time = time.time() + timeout_s

        while time.time() < end_time:
            try:
                data, addr = sock.recvfrom(1024)
                if len(data) >= 30 and data[0] == 0x68 and data[1] == r1 and data[2] == r2:
                    if addr[0] not in [d["ip"] for d in devices]:
                        model = data[6:13].decode(errors="ignore").strip("\x00")
                        devices.append({
                            "ip": addr[0],
                            "model": model or "UNKNOWN"
                        })
            except socket.timeout:
                continue
            except Exception:
                pass
    finally:
        sock.close()

    return devices


# ─────────────────────────────────────────────────────────────────────────────
# Game Engine
# ─────────────────────────────────────────────────────────────────────────────
class HackersDefenseGame:
    def __init__(self, service: LightService, on_event):
        self._svc = service
        self._notify = on_event
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thr = None

        self.state = S_SETUP
        self.num_walls = 4

        self.score = 0
        self.clears = 0
        self.current_streak = 0
        self.best_streak = 0

        self.total_game_left = MAX_GAME_SECONDS
        self.game_end = 0.0

        self.stage_index = 0
        self.stage_start = 0.0
        self.stage_end = 0.0
        self.stage_duration = 0.0
        self.stage_left = 0.0

        self.spawn_interval = 1.2
        self.spawn_count = 1
        self.next_spawn_at = 0.0

        self.active_viruses = [set() for _ in range(MAX_WALLS)]
        self.locked_this_stage = [False] * MAX_WALLS
        self.wall_locked_now = [False] * MAX_WALLS
        self.last_press_at = [0.0] * MAX_WALLS

        self.total_stars = 0
        self.max_total_stars = 0
        self.stage_star_history = []

        self._last_eye_blink_phase = None
        self._last_virus_blink_phase = None

    # ── Public API ────────────────────────────────────────────────────────────
    def start_game(self, num_walls):
        self.stop_game()

        self.num_walls = max(MIN_WALLS, min(MAX_WALLS, num_walls))
        self.state = S_ACTIVE

        self.score = 0
        self.clears = 0
        self.current_streak = 0
        self.best_streak = 0

        self.total_game_left = MAX_GAME_SECONDS
        self.game_end = time.perf_counter() + MAX_GAME_SECONDS

        self.stage_index = 0
        self.stage_start = 0.0
        self.stage_end = 0.0
        self.stage_duration = 0.0
        self.stage_left = 0.0

        self.spawn_interval = 1.2
        self.spawn_count = 1
        self.next_spawn_at = 0.0

        self.active_viruses = [set() for _ in range(MAX_WALLS)]
        self.locked_this_stage = [False] * MAX_WALLS
        self.wall_locked_now = [False] * MAX_WALLS
        self.last_press_at = [0.0] * MAX_WALLS

        self.total_stars = 0
        self.max_total_stars = 0
        self.stage_star_history = []

        self._last_eye_blink_phase = None
        self._last_virus_blink_phase = None

        self._svc.all_off()
        self._stop.clear()

        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def stop_game(self):
        self._stop.set()
        if self._thr and self._thr.is_alive():
            self._thr.join(timeout=2.0)
        self._svc.all_off()
        self.state = S_SETUP

    def handle_button(self, ch, led, is_triggered, is_disconnected):
        if is_disconnected:
            return
        if not is_triggered:
            return
        if self.state != S_ACTIVE:
            return
        if led not in BUTTONS:
            return
        if ch < 1 or ch > self.num_walls:
            return

        wall_idx = ch - 1
        if self.wall_locked_now[wall_idx]:
            return

        now = time.perf_counter()
        if now - self.last_press_at[wall_idx] < INPUT_DEBOUNCE_S:
            return
        self.last_press_at[wall_idx] = now

        with self._lock:
            if led in self.active_viruses[wall_idx]:
                self.active_viruses[wall_idx].remove(led)
                self.score += POINT_CLEAR
                self.clears += 1
                self.current_streak += 1
                self.best_streak = max(self.best_streak, self.current_streak)

                self._svc.set_led(ch, led, *GREEN)

                self._notify("virus_cleared", {
                    "wall": ch,
                    "led": led,
                    "score": self.score,
                    "clears": self.clears,
                    "streak": self.current_streak,
                    "best_streak": self.best_streak,
                    "viruses_per_wall": self._virus_counts(),
                    "stage": self.stage_index,
                    "stage_left": self.stage_left,
                    "stars": self.total_stars,
                    "max_stars": self.max_total_stars,
                })

    # ── Stage helpers ─────────────────────────────────────────────────────────
    def _stage_duration_for_index(self, stage_index):
        return BASE_STAGE_SECONDS + (stage_index - 1) * STAGE_STEP_SECONDS

    def _difficulty_for_stage(self, stage_index):
        if stage_index <= len(STAGE_CONFIGS):
            cfg = STAGE_CONFIGS[stage_index - 1]
            return cfg["spawn_interval"], cfg["spawn_count"]

        extra = stage_index - len(STAGE_CONFIGS)
        interval = max(0.18, STAGE_CONFIGS[-1]["spawn_interval"] - extra * 0.05)
        count = min(6, STAGE_CONFIGS[-1]["spawn_count"] + extra // 2)
        return interval, count

    def _begin_stage(self, now):
        self.stage_index += 1
        self.stage_duration = self._stage_duration_for_index(self.stage_index)

        remaining_total = max(0.0, self.game_end - now)
        if self.stage_duration > remaining_total:
            self.stage_duration = remaining_total

        self.stage_start = now
        self.stage_end = now + self.stage_duration
        self.stage_left = self.stage_duration

        self.spawn_interval, self.spawn_count = self._difficulty_for_stage(self.stage_index)
        self.next_spawn_at = now + min(0.5, self.spawn_interval)

        for w in range(self.num_walls):
            self.active_viruses[w].clear()
            self.locked_this_stage[w] = False
            self.wall_locked_now[w] = False
            self.last_press_at[w] = 0.0

        self.max_total_stars += self.num_walls
        self._last_eye_blink_phase = None
        self._last_virus_blink_phase = None

        self._draw_world(now)

        self._notify("stage_started", {
            "stage": self.stage_index,
            "stage_duration": self.stage_duration,
            "spawn_interval": self.spawn_interval,
            "spawn_count": self.spawn_count,
            "stars": self.total_stars,
            "max_stars": self.max_total_stars,
            "viruses_per_wall": self._virus_counts(),
        })

    def _finish_stage(self):
        locked_count = sum(1 for x in self.locked_this_stage[:self.num_walls] if x)
        max_stage_stars = max(0, self.num_walls - locked_count)

        remaining = sum(len(self.active_viruses[w]) for w in range(self.num_walls))
        if remaining == 0:
            earned = max_stage_stars
        elif remaining <= 2:
            earned = max(0, max_stage_stars - 1)
        elif remaining <= 5:
            earned = max(0, max_stage_stars - 2)
        else:
            earned = max(0, max_stage_stars - 3)

        earned = min(max_stage_stars, earned)
        self.total_stars += earned

        stage_result = {
            "stage": self.stage_index,
            "earned": earned,
            "possible_after_locks": max_stage_stars,
            "base_possible": self.num_walls,
            "locked_count": locked_count,
            "remaining_viruses": remaining,
            "total_stars": self.total_stars,
            "max_total_stars": self.max_total_stars,
        }
        self.stage_star_history.append(stage_result)
        self._notify("stage_ended", stage_result)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _virus_counts(self):
        return [len(self.active_viruses[w]) for w in range(self.num_walls)]

    def _spawn_one(self):
        candidates = []
        for w in range(self.num_walls):
            if self.wall_locked_now[w]:
                continue
            free = [led for led in BUTTONS if led not in self.active_viruses[w]]
            if free:
                candidates.append((w, free))

        if not candidates:
            return

        candidates.sort(key=lambda item: len(self.active_viruses[item[0]]))
        top_bucket = candidates[:max(1, min(3, len(candidates)))]
        wall_idx, free_leds = random.choice(top_bucket)
        led = random.choice(free_leds)
        self.active_viruses[wall_idx].add(led)

    def _trigger_wall_lock(self, wall_idx):
        self.wall_locked_now[wall_idx] = True
        self.locked_this_stage[wall_idx] = True
        self.score = max(0, self.score - POINT_LOCK_PENALTY)
        self.current_streak = 0

        self._notify("wall_locked", {
            "wall": wall_idx + 1,
            "score": self.score,
            "clears": self.clears,
            "streak": self.current_streak,
            "best_streak": self.best_streak,
            "viruses_per_wall": self._virus_counts(),
            "stage": self.stage_index,
            "stars": self.total_stars,
            "stage_max_now": max(0, self.num_walls - sum(1 for x in self.locked_this_stage[:self.num_walls] if x)),
        })

    def _check_overloads(self):
        for w in range(self.num_walls):
            if self.wall_locked_now[w]:
                continue
            if len(self.active_viruses[w]) > OVERLOAD_LIMIT:
                self._trigger_wall_lock(w)

    def _eye_color_for_wall(self, wall_idx, now, blink_phase=None):
        if self.wall_locked_now[wall_idx]:
            phase = blink_phase if blink_phase is not None else int(now * 8) % 2
            return RED if phase == 0 else OFF

        count = len(self.active_viruses[wall_idx])
        if count == 0:
            return DIM
        if count <= 2:
            return GREEN
        if count <= 4:
            return YELLOW
        return ORANGE

    def _draw_world(self, now, force=False):
        eye_phase = None
        virus_phase = None

        if any(self.wall_locked_now[:self.num_walls]):
            eye_phase = int(now * 8) % 2

        if self.stage_left < 8:
            virus_phase = int(now * 10) % 2

        if not force:
            if eye_phase == self._last_eye_blink_phase and virus_phase == self._last_virus_blink_phase:
                # dacă nu s-a schimbat faza de blink, tot redesenăm când există modificări de gameplay
                pass

        self._last_eye_blink_phase = eye_phase
        self._last_virus_blink_phase = virus_phase

        for w in range(self.num_walls):
            ch = w + 1
            locked = self.wall_locked_now[w]

            self._svc.set_led(ch, EYE_LED, *self._eye_color_for_wall(w, now, eye_phase))

            for led in BUTTONS:
                if locked:
                    if led in self.active_viruses[w]:
                        phase = virus_phase if virus_phase is not None else int(now * 10) % 2
                        self._svc.set_led(ch, led, *(RED if phase == 0 else OFF))
                    else:
                        self._svc.set_led(ch, led, *OFF)
                else:
                    if led in self.active_viruses[w]:
                        if self.stage_left < 8:
                            phase = virus_phase if virus_phase is not None else int(now * 10) % 2
                            self._svc.set_led(ch, led, *(BLUE if phase == 0 else WHITE))
                        else:
                            self._svc.set_led(ch, led, *BLUE)
                    else:
                        self._svc.set_led(ch, led, *OFF)

        for ch in range(self.num_walls + 1, MAX_WALLS + 1):
            self._svc.set_led(ch, EYE_LED, *OFF)
            for led in BUTTONS:
                self._svc.set_led(ch, led, *OFF)

    def _do_game_over(self):
        self.state = S_GAMEOVER
        self._svc.all_off()

        star_ratio = 0 if self.max_total_stars == 0 else self.total_stars / self.max_total_stars
        final_color = GREEN if star_ratio >= 0.75 else ORANGE if star_ratio >= 0.4 else RED

        for _ in range(5):
            if self._stop.is_set():
                break
            for ch in range(1, self.num_walls + 1):
                for led in range(LEDS_PER_CHANNEL):
                    self._svc.set_led(ch, led, *final_color)
            time.sleep(0.18)
            self._svc.all_off()
            time.sleep(0.10)

        self._notify("game_over", {
            "score": self.score,
            "clears": self.clears,
            "best_streak": self.best_streak,
            "stars": self.total_stars,
            "max_stars": self.max_total_stars,
            "stages": len(self.stage_star_history),
        })

    # ── Main loop ─────────────────────────────────────────────────────────────
    def _loop(self):
        self._notify("game_started", {
            "score": self.score,
            "clears": self.clears,
            "streak": self.current_streak,
            "best_streak": self.best_streak,
            "game_left": MAX_GAME_SECONDS,
            "viruses_per_wall": self._virus_counts(),
            "stars": self.total_stars,
            "max_stars": self.max_total_stars,
        })

        now = time.perf_counter()
        self._begin_stage(now)

        next_tick = time.perf_counter()

        while not self._stop.is_set():
            now = time.perf_counter()
            self.total_game_left = max(0.0, self.game_end - now)
            self.stage_left = max(0.0, self.stage_end - now)

            if self.total_game_left <= 0:
                break

            redraw_needed = False

            if self.stage_left <= 0:
                self._finish_stage()
                if self.total_game_left <= 0:
                    break
                self._begin_stage(now)
                continue

            if now >= self.next_spawn_at:
                for _ in range(self.spawn_count):
                    self._spawn_one()
                self.next_spawn_at = now + self.spawn_interval
                redraw_needed = True

            prev_locked = list(self.wall_locked_now[:self.num_walls])
            self._check_overloads()
            if prev_locked != self.wall_locked_now[:self.num_walls]:
                redraw_needed = True

            if self.stage_left < 8 or any(self.wall_locked_now[:self.num_walls]):
                redraw_needed = True

            if redraw_needed:
                self._draw_world(now)

            self._notify("tick", {
                "score": self.score,
                "clears": self.clears,
                "streak": self.current_streak,
                "best_streak": self.best_streak,
                "game_left": self.total_game_left,
                "stage_left": self.stage_left,
                "stage": self.stage_index,
                "stage_duration": self.stage_duration,
                "viruses_per_wall": self._virus_counts(),
                "spawn_interval": self.spawn_interval,
                "spawn_count": self.spawn_count,
                "stars": self.total_stars,
                "max_stars": self.max_total_stars,
                "locked_this_stage": list(self.locked_this_stage[:self.num_walls]),
            })

            next_tick += TICK_RATE
            sleep_time = next_tick - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                next_tick = time.perf_counter()

        if not self._stop.is_set():
            self._do_game_over()


# ─────────────────────────────────────────────────────────────────────────────
# Main Application
# ─────────────────────────────────────────────────────────────────────────────
class HackersDefenseApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Hackers / Defense – Evil Eye")
        self.configure(bg=BG_DARK)
        self.minsize(1020, 780)

        self.bind("<F11>", lambda e: self.attributes("-fullscreen",
                                                     not self.attributes("-fullscreen")))
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        self._cfg = load_config()
        self._service = LightService()
        self._service.on_status = lambda m: self.after(0, lambda msg=m: self._set_status(msg))

        ip = self._cfg.get("device_ip", "127.0.0.1") or "127.0.0.1"
        self._service.set_device(ip, self._cfg.get("udp_port", DISCOVERY_SEND_PORT))
        self._service.set_recv_port(self._cfg.get("receiver_port", DISCOVERY_RECV_PORT))
        self._service.set_poll_rate(self._cfg.get("polling_rate_ms", 100))
        self._service.start_receiver()
        self._service.start_polling()

        self._game = HackersDefenseGame(self._service, self._on_game_event)
        self._service.on_button_state = self._game.handle_button

        self._v_walls = tk.IntVar(value=4)
        self._v_device_ip = tk.StringVar(value=ip)

        self._frame_setup = tk.Frame(self, bg=BG_DARK)
        self._frame_game = tk.Frame(self, bg=BG_DARK)
        for frm in (self._frame_setup, self._frame_game):
            frm.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._build_setup_screen()
        self._build_game_screen()
        self._show_setup()

    # ── Screen switching ──────────────────────────────────────────────────────
    def _show_setup(self):
        self._frame_setup.lift()

    def _show_game(self):
        self._frame_game.lift()

    # ── Discovery GUI ─────────────────────────────────────────────────────────
    def _choose_interface_dialog(self, interfaces):
        if not interfaces:
            return None

        result = {"value": None}

        win = tk.Toplevel(self)
        win.title("Select Network")
        win.configure(bg=BG_DARK)
        win.transient(self)
        win.resizable(False, False)

        tk.Label(
            win,
            text="Selectează rețeaua pentru device-ul de recepție",
            bg=BG_DARK,
            fg=FG_MAIN,
            font=("Consolas", 12, "bold")
        ).pack(padx=20, pady=(16, 10))

        selected = tk.IntVar(value=0)
        box = tk.Frame(win, bg=BG_DARK)
        box.pack(padx=20, pady=(0, 12), fill=tk.BOTH, expand=True)

        for i, (iface, ip, bcast) in enumerate(interfaces):
            txt = f"[{i}] {iface} - {ip}"
            rb = tk.Radiobutton(
                box,
                text=txt,
                variable=selected,
                value=i,
                anchor="w",
                justify="left",
                bg=BG_DARK,
                fg=FG_MAIN,
                selectcolor=BG_PANEL,
                activebackground=BG_DARK,
                activeforeground=FG_MAIN,
                font=("Consolas", 11),
                highlightthickness=0
            )
            rb.pack(fill=tk.X, anchor="w", pady=2)

        btns = tk.Frame(win, bg=BG_DARK)
        btns.pack(pady=(0, 16))

        def _ok():
            idx = selected.get()
            if 0 <= idx < len(interfaces):
                result["value"] = interfaces[idx]
            win.destroy()

        def _cancel():
            win.destroy()

        _make_lbl_btn(
            btns, "SCAN", _ok,
            bg="#ff3c00", fg="white",
            padx=18, pady=8, hover_bg="#cc3000"
        ).pack(side=tk.LEFT, padx=6)

        _make_lbl_btn(
            btns, "CANCEL", _cancel,
            bg="#444", fg="white",
            padx=18, pady=8, hover_bg="#666"
        ).pack(side=tk.LEFT, padx=6)

        win.update_idletasks()
        win.deiconify()
        win.lift()
        win.focus_force()
        win.wait_visibility()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        self.wait_window(win)

        return result["value"]

    def _run_discovery_flow_gui(self):
        interfaces = get_local_interfaces()
        if not interfaces:
            self._set_status("No active network interfaces found.")
            return None

        preferred = None
        for item in interfaces:
            if item[1] == "169.254.182.44":
                preferred = item
                break

        selected = preferred or self._choose_interface_dialog(interfaces)
        if not selected:
            self._set_status("Network selection canceled.")
            return None

        iface_name, bind_ip, bcast_ip = selected
        self._set_status(f"Scanning on {iface_name} ({bind_ip})...")

        try:
            devices = discover_devices_on_interface(
                bind_ip=bind_ip,
                broadcast_ip=bcast_ip,
                send_port=self._cfg.get("udp_port", DISCOVERY_SEND_PORT),
                timeout_s=3.0
            )
        except Exception as e:
            self._set_status(f"Discovery failed: {e}")
            return None

        if devices:
            found_ip = devices[0]["ip"]
            model = devices[0]["model"]
            self._set_status(f"Found {model} at {found_ip}")
            return found_ip

        self._set_status("No devices found. Using current config.")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # SETUP SCREEN
    # ─────────────────────────────────────────────────────────────────────────
    def _build_setup_screen(self):
        f = self._frame_setup

        self._status_lbl = tk.Label(f, text="Ready", bg=BG_DARK, fg=FG_DIM, font=FONT_XS)
        self._status_lbl.pack(side=tk.BOTTOM, pady=(0, 8))

        _make_lbl_btn(f, "▶   START GAME", self._start_game,
                      bg="#ff3c00", fg="white",
                      font=("Consolas", 20, "bold"),
                      padx=50, pady=18,
                      hover_bg="#cc3000").pack(side=tk.BOTTOM, pady=(6, 6))

        tk.Label(f, text="HACKERS / BASE DEFENSE", bg=BG_DARK, fg="#ff3c00",
                 font=("Consolas", 30, "bold")).pack(pady=(20, 2))
        tk.Label(f, text="Co-op strategic defense · Stage-based · Evil Eye", bg=BG_DARK, fg=FG_DIM,
                 font=FONT_SM).pack(pady=(0, 10))

        content = tk.Frame(f, bg=BG_DARK)
        content.pack(fill=tk.BOTH, expand=True)

        row = 0

        self._setup_lbl(content, "ACTIVE WALLS", row); row += 1
        r = tk.Frame(content, bg=BG_DARK)
        r.grid(row=row, column=0, columnspan=2, pady=(0, 14)); row += 1
        for n in range(2, 5):
            _seg_btn(
                r, str(n), self._v_walls, n,
                active_bg=TEAM_HEX[n - 2], width=5, height=2,
                font=("Consolas", 18, "bold")
            ).pack(side=tk.LEFT, padx=6)

        self._setup_lbl(content, "RULES", row); row += 1
        rules = (
            "• Stage 1 lasts 30s, stage 2 lasts 40s, stage 3 lasts 50s, etc.\n"
            "• Total game time is capped at 10 minutes.\n"
            "• Spread gets faster each stage.\n"
            "• Each stage can award up to N stars, where N = number of players/walls.\n"
            "• If one wall locks in that stage, max stars become N-1.\n"
            "• Locked walls recover automatically in the next stage."
        )
        tk.Label(content, text=rules, justify="left", bg=BG_DARK, fg=FG_DIM,
                 font=("Consolas", 10)).grid(row=row, column=0, columnspan=2, pady=(0, 14)); row += 1

        self._setup_lbl(content, "DEVICE IP", row); row += 1
        ip_row = tk.Frame(content, bg=BG_DARK)
        ip_row.grid(row=row, column=0, columnspan=2, pady=(0, 14)); row += 1

        tk.Entry(ip_row, textvariable=self._v_device_ip,
                 width=20, bg=BG_PANEL, fg=FG_MAIN,
                 font=("Consolas", 13), insertbackground="white",
                 relief="flat", highlightthickness=1,
                 highlightbackground="#444").pack(side=tk.LEFT, padx=6)

        _make_lbl_btn(ip_row, "APPLY", self._apply_ip,
                      bg="#444", padx=12, pady=5,
                      font=FONT_XS, hover_bg="#666").pack(side=tk.LEFT, padx=4)

    def _setup_lbl(self, parent, text, row):
        tk.Label(parent, text=text, bg=BG_DARK, fg=FG_DIM,
                 font=("Consolas", 9, "bold")).grid(
            row=row, column=0, columnspan=2, pady=(6, 2))

    # ─────────────────────────────────────────────────────────────────────────
    # GAME SCREEN
    # ─────────────────────────────────────────────────────────────────────────
    def _build_game_screen(self):
        f = self._frame_game

        btm = tk.Frame(f, bg=BG_MID, pady=8)
        btm.pack(side=tk.BOTTOM, fill=tk.X)
        _make_lbl_btn(btm, "⚙ Setup", self._go_setup,
                      bg="#333", padx=14, pady=6,
                      font=FONT_XS, hover_bg="#555").pack(side=tk.LEFT, padx=8)
        _make_lbl_btn(btm, "⏹ Stop", self._stop_game,
                      bg="#333", padx=14, pady=6,
                      font=FONT_XS, hover_bg="#555").pack(side=tk.LEFT, padx=4)
        self._game_status = tk.Label(btm, text="", bg=BG_MID, fg=FG_DIM, font=FONT_XS)
        self._game_status.pack(side=tk.RIGHT, padx=12)

        top = tk.Frame(f, bg=BG_MID)
        top.pack(fill=tk.X, pady=(0, 4))

        self._score_card = tk.Frame(top, bg=BG_PANEL, padx=18, pady=8)
        self._score_card.pack(side=tk.LEFT, padx=6, pady=6, expand=True, fill=tk.X)

        self._lbl_score = tk.Label(self._score_card, text="0", bg=BG_PANEL, fg=FG_MAIN,
                                   font=("Consolas", 28, "bold"))
        self._lbl_score.pack()
        tk.Label(self._score_card, text="TEAM SCORE", bg=BG_PANEL, fg=FG_DIM,
                 font=("Consolas", 10, "bold")).pack()

        self._stats_card = tk.Frame(top, bg=BG_PANEL, padx=18, pady=8)
        self._stats_card.pack(side=tk.LEFT, padx=6, pady=6, expand=True, fill=tk.X)

        self._lbl_stats = tk.Label(self._stats_card, text="", bg=BG_PANEL, fg=FG_MAIN,
                                   font=("Consolas", 12, "bold"), justify="center")
        self._lbl_stats.pack()
        tk.Label(self._stats_card, text="CLEARS / BEST", bg=BG_PANEL, fg=FG_DIM,
                 font=("Consolas", 10, "bold")).pack()

        self._stars_card = tk.Frame(top, bg=BG_PANEL, padx=18, pady=8)
        self._stars_card.pack(side=tk.LEFT, padx=6, pady=6, expand=True, fill=tk.X)

        self._lbl_stars = tk.Label(self._stars_card, text="", bg=BG_PANEL, fg=FG_MAIN,
                                   font=("Consolas", 12, "bold"), justify="center")
        self._lbl_stars.pack()
        tk.Label(self._stars_card, text="STARS", bg=BG_PANEL, fg=FG_DIM,
                 font=("Consolas", 10, "bold")).pack()

        self._walls_card = tk.Frame(top, bg=BG_PANEL, padx=18, pady=8)
        self._walls_card.pack(side=tk.LEFT, padx=6, pady=6, expand=True, fill=tk.X)

        self._lbl_walls = tk.Label(self._walls_card, text="", bg=BG_PANEL, fg=FG_MAIN,
                                   font=("Consolas", 12, "bold"), justify="center")
        self._lbl_walls.pack()
        tk.Label(self._walls_card, text="WALL STATUS", bg=BG_PANEL, fg=FG_DIM,
                 font=("Consolas", 10, "bold")).pack()

        self._lbl_phase = tk.Label(f, text="DEFEND THE BASE", bg=BG_DARK, fg=FG_BLUE,
                                   font=("Consolas", 24, "bold"))
        self._lbl_phase.pack(pady=(10, 2))

        self._lbl_action = tk.Label(f, text="", bg=BG_DARK, fg=FG_DIM,
                                    font=("Consolas", 14))
        self._lbl_action.pack()

        clock_frame = tk.Frame(f, bg=BG_DARK)
        clock_frame.pack(expand=True)

        self._lbl_clock = tk.Label(clock_frame, text="0:30", bg=BG_DARK, fg=FG_MAIN,
                                   font=("Consolas", 72, "bold"))
        self._lbl_clock.pack()

        self._lbl_sub = tk.Label(clock_frame, text="", bg=BG_DARK, fg=FG_DIM,
                                 font=("Consolas", 14), justify="center")
        self._lbl_sub.pack(pady=(0, 8))

        self._danger_bar = tk.Canvas(f, bg=BG_PANEL, height=10, highlightthickness=0)
        self._danger_bar.pack(fill=tk.X, padx=60, pady=(0, 12))

    # ── UI updates ────────────────────────────────────────────────────────────
    def _update_dashboard(self, score, clears, streak, best_streak, virus_counts, stars, max_stars, locked_this_stage):
        self._lbl_score.configure(text=str(score))
        self._lbl_stats.configure(text=f"{clears} / {best_streak}")
        self._lbl_stars.configure(text=f"{stars} / {max_stars}")

        wall_lines = []
        for i, count in enumerate(virus_counts, start=1):
            if i - 1 < len(locked_this_stage) and locked_this_stage[i - 1]:
                wall_lines.append(f"W{i}: LOCK")
            else:
                wall_lines.append(f"W{i}: {count}")
        self._lbl_walls.configure(text="   ".join(wall_lines))

        max_count = max(virus_counts) if virus_counts else 0
        pct = min(1.0, max_count / (OVERLOAD_LIMIT + 2))
        w = self._danger_bar.winfo_width() or 600
        self._danger_bar.delete("all")
        self._danger_bar.create_rectangle(0, 0, w, 10, fill=BG_PANEL, outline="")
        bw = int(w * pct)
        if bw > 0:
            col = FG_GREEN if max_count <= 2 else (FG_GOLD if max_count <= 4 else FG_RED)
            self._danger_bar.create_rectangle(0, 0, bw, 10, fill=col, outline="")

    def _on_game_event(self, event, data):
        self.after(0, lambda e=event, d=data: self._dispatch(e, d))

    def _dispatch(self, event, data):
        if event == "game_started":
            self._lbl_phase.configure(text="DEFEND THE BASE", fg=FG_BLUE)
            self._lbl_action.configure(text="Survive the stages and collect stars.", fg=FG_MAIN)
            self._update_dashboard(
                data["score"], data["clears"], data["streak"], data["best_streak"],
                data["viruses_per_wall"], data["stars"], data["max_stars"], [False] * self._game.num_walls
            )

        elif event == "stage_started":
            self._lbl_phase.configure(text=f"STAGE {data['stage']}", fg=FG_BLUE)
            self._lbl_action.configure(
                text=f"Stage {data['stage']} started · Spawn {data['spawn_interval']:.2f}s · x{data['spawn_count']}",
                fg=FG_MAIN
            )
            self._update_dashboard(
                self._game.score, self._game.clears, self._game.current_streak, self._game.best_streak,
                data["viruses_per_wall"], data["stars"], data["max_stars"], [False] * self._game.num_walls
            )

        elif event == "virus_cleared":
            self._lbl_action.configure(
                text=f"✔ Cleared virus on Wall {data['wall']} · Streak {data['streak']}",
                fg=FG_GREEN
            )
            self._update_dashboard(
                data["score"], data["clears"], data["streak"], data["best_streak"],
                data["viruses_per_wall"], data["stars"], data["max_stars"], self._game.locked_this_stage[:self._game.num_walls]
            )

        elif event == "wall_locked":
            self._lbl_action.configure(
                text=f"✖ Wall {data['wall']} overloaded! Stage reward reduced.",
                fg=FG_RED
            )
            self._update_dashboard(
                data["score"], data["clears"], data["streak"], data["best_streak"],
                data["viruses_per_wall"], data["stars"], self._game.max_total_stars, self._game.locked_this_stage[:self._game.num_walls]
            )

        elif event == "stage_ended":
            self._lbl_action.configure(
                text=f"Stage {data['stage']} complete · Earned {data['earned']}/{data['possible_after_locks']} stars",
                fg=FG_GOLD
            )

        elif event == "tick":
            sl = data["stage_left"]
            mm, ss = divmod(int(sl), 60)
            self._lbl_clock.configure(
                text=f"{mm}:{ss:02d}",
                fg=(FG_MAIN if sl > 15 else FG_GOLD if sl > 7 else FG_RED)
            )

            self._lbl_sub.configure(
                text=f"Stage {data['stage']}   ·   Total left {int(data['game_left'])}s   ·   Spawn {data['spawn_interval']:.2f}s x{data['spawn_count']}",
                fg=FG_DIM
            )

            self._update_dashboard(
                data["score"], data["clears"], data["streak"], data["best_streak"],
                data["viruses_per_wall"], data["stars"], data["max_stars"], data["locked_this_stage"]
            )

        elif event == "game_over":
            self._lbl_phase.configure(text="GAME OVER", fg=FG_GOLD)
            self._lbl_clock.configure(text="0:00", fg=FG_RED)
            self._lbl_sub.configure(text="")
            self._lbl_action.configure(
                text=f"Final score {data['score']} · Stars {data['stars']}/{data['max_stars']} · Stages {data['stages']}",
                fg=FG_GOLD
            )
            self._update_dashboard(
                data["score"], data["clears"], 0, data["best_streak"],
                [0] * self._game.num_walls, data["stars"], data["max_stars"], [False] * self._game.num_walls
            )

    # ── Controls ──────────────────────────────────────────────────────────────
    def _apply_ip(self):
        ip = self._v_device_ip.get().strip() or "127.0.0.1"
        self._service.set_device(ip, self._cfg.get("udp_port", DISCOVERY_SEND_PORT))
        self._cfg["device_ip"] = ip
        save_config(self._cfg)
        self._set_status(f"Device → {ip}")

    def _start_game(self):
        discovered_ip = self._run_discovery_flow_gui()

        if discovered_ip:
            self._v_device_ip.set(discovered_ip)

        self._apply_ip()
        self._game.start_game(self._v_walls.get())

        self._lbl_clock.configure(text="0:30", fg=FG_MAIN)
        self._lbl_action.configure(text="", fg=FG_DIM)
        self._lbl_sub.configure(text="")
        self._show_game()

    def _stop_game(self):
        self._game.stop_game()
        self._lbl_action.configure(text="Game stopped.", fg=FG_DIM)
        self._lbl_sub.configure(text="")

    def _go_setup(self):
        self._game.stop_game()
        self._show_setup()

    def _set_status(self, msg):
        try:
            self._status_lbl.configure(text=msg)
            self._game_status.configure(text=msg)
        except tk.TclError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    HackersDefenseApp().mainloop()