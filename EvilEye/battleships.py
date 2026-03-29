"""
battleships.py – Simultaneous Multiplayer BattleShips for Evil Eye LED hardware

Rules
─────
• 2–4 players, one player per wall.
• Each player places exactly 3 ships on their own wall (3 of 10 buttons).
• After placement, ships are HIDDEN from the LEDs to prevent cheating.
• Game runs in simultaneous rounds.
• Each round lasts 10–15 seconds.
• During a round, every alive player can choose one attack:
    - select one tile on their own wall
    - repeated presses on the SAME tile cycle target:
        press 1 -> first alive opponent
        press 2 -> second alive opponent
        ...
        last press -> nothing
        then back to first opponent
• At round end, all chosen attacks resolve simultaneously.
• Attack hits the same tile index on the chosen opponent's wall.
• Last player with at least one ship alive wins.

Run:
    python battleships.py
"""

import os
import sys
import random
import threading
import time
import tkinter as tk
import socket
import struct

# ── Import LightService from sibling Controller.py ───────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from Controller import (
    LightService, load_config, save_config,
    LEDS_PER_CHANNEL,
)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
MAX_PLAYERS = 4
MIN_PLAYERS = 2

EYE_LED = 0
BUTTONS = list(range(1, 11))  # 1..10
SHIPS_PER_PLAYER = 3

ROUND_MIN_SECONDS = 10.0
ROUND_MAX_SECONDS = 15.0

PLAYER_WALLS = {
    2: {0: [1], 1: [2]},
    3: {0: [1], 1: [2], 2: [3]},
    4: {0: [1], 1: [2], 2: [3], 3: [4]},
}

PLAYER_COLORS_RGB = [
    (194,  75,   19),   # A – orange-dark
    (  0, 100, 255),   # B – blue
    (  0, 210,  60),   # C – green
    (200,   0, 200),   # D – purple
]
PLAYER_HEX = ["#ff3c00", "#0064ff", "#00d23c", "#c800c8"]
PLAYER_NAMES_DEFAULT = ["PLAYER A", "PLAYER B", "PLAYER C", "PLAYER D"]

RED    = (255,   0,   0)
GREEN  = (  0, 255,   0)
YELLOW = (255, 200,   0)
WHITE  = (255, 255, 255)
OFF    = (  0,   0,   0)
DIM    = ( 25,  25,  25)
ORANGE = (255, 120, 0)

LIFE_COLORS = {
    3: GREEN,
    2: YELLOW,
    1: ORANGE,
    0: RED,
}

S_SETUP      = "setup"
S_PLACEMENT  = "placement"
S_ACTIVE     = "active"
S_GAMEOVER   = "gameover"

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
    lbl.bind("<Enter>",    lambda e: lbl.configure(bg=hover_bg))
    lbl.bind("<Leave>",    lambda e: lbl.configure(bg=bg))
    return lbl


def _seg_btn(parent, text, var, value, **kw):
    active_bg   = kw.get("active_bg", "#ff3c00")
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


def prefix_to_netmask(prefix_len: int) -> str:
    mask = (0xFFFFFFFF << (32 - prefix_len)) & 0xFFFFFFFF
    return int_to_ip(mask)


def broadcast_from_ip_mask(ip: str, netmask: str) -> str:
    ip_i = ip_to_int(ip)
    mask_i = ip_to_int(netmask)
    bcast_i = ip_i | (~mask_i & 0xFFFFFFFF)
    return int_to_ip(bcast_i)


def get_local_interfaces():
    """
    Return list of tuples:
        (interface_name, local_ip, broadcast_ip)

    Tries to detect IPv4 interfaces using socket.getaddrinfo / hostname.
    Also injects link-local broadcast for 169.254.x.x if present.
    """
    interfaces = []
    seen = set()

    hostname = socket.gethostname()

    candidates = set()

    # hostname lookup
    try:
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_DGRAM):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                candidates.add(ip)
    except Exception:
        pass

    # default route style probe
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            candidates.add(ip)
    except Exception:
        pass

    # fallback localhost-less guess
    try:
        local_ip = socket.gethostbyname(hostname)
        if local_ip and not local_ip.startswith("127."):
            candidates.add(local_ip)
    except Exception:
        pass

    for idx, ip in enumerate(sorted(candidates)):
        iface_name = f"Interface {idx}"

        # Heuristic broadcast
        if ip.startswith("169.254."):
            # link-local APIPA range
            bcast = "169.254.255.255"
        else:
            # assume /24 if we cannot inspect mask
            bcast = broadcast_from_ip_mask(ip, "255.255.255.0")

        key = (iface_name, ip, bcast)
        if key not in seen:
            interfaces.append(key)
            seen.add(key)

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


def discover_devices_on_interface(bind_ip: str, broadcast_ip: str, recv_port: int = 7800, send_port: int = 4626, timeout_s: float = 3.0):
    """
    Returns list of dicts:
        [{'ip': 'x.x.x.x', 'model': 'KX-HC04'}, ...]
    """
    devices = []

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        try:
            sock.bind((bind_ip, recv_port))
        except Exception:
            try:
                sock.bind(("", recv_port))
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
class BattleShipsGame:
    """
    Simultaneous-round multiplayer BattleShips engine.
    Background thread for game flow.
    on_event(name, data) for UI notifications.
    """

    def __init__(self, service: LightService, on_event):
        self._svc    = service
        self._notify = on_event
        self._lock   = threading.Lock()
        self._stop   = threading.Event()
        self._thr    = None

        # Config
        self.num_players = 2
        self.player_names = list(PLAYER_NAMES_DEFAULT)

        # Runtime
        self.state = S_SETUP

        self.ships = [set() for _ in range(MAX_PLAYERS)]
        self.destroyed = [set() for _ in range(MAX_PLAYERS)]
        self.ready = [False] * MAX_PLAYERS
        self.alive = [True] * MAX_PLAYERS

        # Simultaneous round selections
        self.round_index = 0
        self.round_deadline = 0.0
        self.round_duration = 0.0

        self.selected_tile = [None] * MAX_PLAYERS       # chosen tile on own wall
        self.target_cycle = [[] for _ in range(MAX_PLAYERS)]  # [opponents..., None]
        self.target_index = [0] * MAX_PLAYERS           # active index in target_cycle
        self.last_press_at = [0.0] * MAX_PLAYERS        # optional debounce aid
        
        self._feedback_stop = threading.Event()
        self._feedback_thr = None
        self._tick_rate = 1.0 / 30.0   # 30 FPS logic tick

    # ── Public API ────────────────────────────────────────────────────────────
    def start_game(self, num_players, player_names=None):
        self.stop_game()

        self.num_players = max(MIN_PLAYERS, min(MAX_PLAYERS, num_players))
        if player_names:
            for i, n in enumerate(player_names[:MAX_PLAYERS]):
                self.player_names[i] = n.strip() or PLAYER_NAMES_DEFAULT[i]

        self.ships = [set() for _ in range(MAX_PLAYERS)]
        self.destroyed = [set() for _ in range(MAX_PLAYERS)]
        self.ready = [False] * MAX_PLAYERS
        self.alive = [True] * MAX_PLAYERS

        self.round_index = 0
        self.round_deadline = 0.0
        self.round_duration = 0.0

        self.selected_tile = [None] * MAX_PLAYERS
        self.target_cycle = [[] for _ in range(MAX_PLAYERS)]
        self.target_index = [0] * MAX_PLAYERS
        self.last_press_at = [0.0] * MAX_PLAYERS

        self.state = S_PLACEMENT
        self._stop.clear()

        self._svc.all_off()
        self._refresh_all_leds()

        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def stop_game(self):
        self._stop.set()
        self._stop_feedback_thread()
        if self._thr and self._thr.is_alive():
            self._thr.join(timeout=2.0)
        self._svc.all_off()
        self.state = S_SETUP

    def _stop_feedback_thread(self):
        self._feedback_stop.set()
        thr = self._feedback_thr
        if thr and thr.is_alive():
            thr.join(timeout=0.5)
        self._feedback_thr = None
        self._feedback_stop.clear()

    def _start_feedback_thread(self, results, eliminated_now):
        self._stop_feedback_thread()
        self._feedback_stop.clear()
        self._feedback_thr = threading.Thread(
            target=self._flash_round_feedback,
            args=(results, eliminated_now),
            daemon=True
        )
        self._feedback_thr.start()

    def handle_button(self, ch, led, is_triggered, is_disconnected):
        if not is_triggered:
            return
        if led not in BUTTONS:
            return
        if self.state not in (S_PLACEMENT, S_ACTIVE):
            return

        player = self._player_for_wall(ch)
        if player is None:
            return

        if self.state == S_PLACEMENT:
            self._handle_placement_press(player, ch, led)
        elif self.state == S_ACTIVE:
            self._handle_battle_press(player, ch, led)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _life_eye_color(self, player):
        ships_left = self._alive_ship_count(player)
        return LIFE_COLORS.get(ships_left, RED)

    def _player_for_wall(self, ch):
        mapping = PLAYER_WALLS.get(self.num_players, {})
        for p, walls in mapping.items():
            if ch in walls:
                return p
        return None

    def _wall_for_player(self, player):
        walls = PLAYER_WALLS[self.num_players].get(player, [])
        return walls[0] if walls else None

    def _alive_ship_count(self, player):
        return len(self.ships[player] - self.destroyed[player])

    def _update_alive_flags(self):
        for p in range(self.num_players):
            self.alive[p] = self._alive_ship_count(p) > 0

    def _alive_players(self):
        return [p for p in range(self.num_players) if self.alive[p]]

    def _all_ready(self):
        return all(self.ready[p] for p in range(self.num_players))

    def _ships_left_list(self):
        return [self._alive_ship_count(p) for p in range(self.num_players)]

    def _refresh_all_leds(self):
        self._svc.all_off()

        if self.state == S_PLACEMENT:
            self._draw_placement_leds()
        elif self.state == S_ACTIVE:
            self._draw_battle_leds()
        elif self.state == S_GAMEOVER:
            self._draw_gameover_leds()

    # ── Drawing ───────────────────────────────────────────────────────────────
    def _draw_placement_leds(self):
        for p in range(self.num_players):
            wall = self._wall_for_player(p)
            if wall is None:
                continue

            p_rgb = PLAYER_COLORS_RGB[p]
            for led in BUTTONS:
                if led in self.ships[p]:
                    self._svc.set_led(wall, led, *p_rgb)
                else:
                    self._svc.set_led(wall, led, *OFF)

            if len(self.ships[p]) == SHIPS_PER_PLAYER:
                self.ready[p] = True
                self._svc.set_led(wall, EYE_LED, *GREEN)
            else:
                self.ready[p] = False
                self._svc.set_led(wall, EYE_LED, *p_rgb)

    def _draw_battle_leds(self):
        """
        Ships are hidden during battle.
        Only show:
        - eye LED as life indicator
        - player's currently selected attack tile in target colour, or white for 'nothing'
        """
        for p in range(self.num_players):
            wall = self._wall_for_player(p)
            if wall is None:
                continue

            # Hide all ship positions to prevent cheating
            for led in BUTTONS:
                self._svc.set_led(wall, led, *OFF)

            # Eye = remaining lives
            self._svc.set_led(wall, EYE_LED, *self._life_eye_color(p))

        # Overlay current selections
        for p in range(self.num_players):
            if not self.alive[p]:
                continue

            wall = self._wall_for_player(p)
            tile = self.selected_tile[p]
            if tile is None:
                continue

            cycle = self.target_cycle[p]
            if not cycle:
                continue

            target = cycle[self.target_index[p]]
            if target is None:
                self._svc.set_led(wall, tile, *WHITE)
            else:
                self._svc.set_led(wall, tile, *PLAYER_COLORS_RGB[target])

    def _draw_gameover_leds(self):
        alive = self._alive_players()
        winner = alive[0] if len(alive) == 1 else None

        for p in range(self.num_players):
            wall = self._wall_for_player(p)
            if wall is None:
                continue

            # all tiles off by default
            for led in BUTTONS:
                self._svc.set_led(wall, led, *OFF)

            # eye shows life state
            self._svc.set_led(wall, EYE_LED, *self._life_eye_color(p))

            # optional winner highlight on wall tiles
            if p == winner:
                for led in BUTTONS:
                    self._svc.set_led(wall, led, *PLAYER_COLORS_RGB[p])

    # ── Placement ─────────────────────────────────────────────────────────────
    def _handle_placement_press(self, player, ch, led):
        wall = self._wall_for_player(player)
        if ch != wall:
            return

        with self._lock:
            if led in self.ships[player]:
                self.ships[player].remove(led)
            else:
                if len(self.ships[player]) < SHIPS_PER_PLAYER:
                    self.ships[player].add(led)

            self.ready[player] = (len(self.ships[player]) == SHIPS_PER_PLAYER)

        self._draw_placement_leds()
        self._notify("placement_update", {
            "player": player,
            "name": self.player_names[player],
            "placed": len(self.ships[player]),
            "ready": self.ready[player],
            "ready_flags": list(self.ready[:self.num_players]),
        })

    # ── Battle ────────────────────────────────────────────────────────────────
    def _build_cycle_for_player(self, player):
        """
        Cycle order:
        [alive opponents in numeric order] + [None]
        """
        return [p for p in range(self.num_players) if self.alive[p] and p != player] + [None]

    def _begin_round(self):
        self.round_index += 1
        self.round_duration = random.uniform(ROUND_MIN_SECONDS, ROUND_MAX_SECONDS)
        self.round_deadline = time.perf_counter() + self.round_duration

        for p in range(self.num_players):
            self.selected_tile[p] = None
            self.target_cycle[p] = self._build_cycle_for_player(p) if self.alive[p] else []
            self.target_index[p] = 0
            self.last_press_at[p] = 0.0

        self._draw_battle_leds()
        self._notify("round_started", {
            "round_index": self.round_index,
            "round_time": self.round_duration,
            "ships_left": self._ships_left_list(),
        })

    def _handle_battle_press(self, player, ch, led):
        wall = self._wall_for_player(player)
        if ch != wall:
            return
        if not self.alive[player]:
            return

        now = time.perf_counter()

        with self._lock:
            # Optional soft debounce
            if now - self.last_press_at[player] < 0.08:
                return
            self.last_press_at[player] = now

            # If new tile, select it and start at first cycle entry
            if self.selected_tile[player] != led:
                self.selected_tile[player] = led
                self.target_cycle[player] = self._build_cycle_for_player(player)
                self.target_index[player] = 0
            else:
                cycle = self.target_cycle[player]
                if cycle:
                    self.target_index[player] = (self.target_index[player] + 1) % len(cycle)

            cycle = self.target_cycle[player]
            target = cycle[self.target_index[player]] if cycle else None

        self._draw_battle_leds()
        self._notify("selection_changed", {
            "player": player,
            "name": self.player_names[player],
            "tile": led,
            "target": target,
            "target_name": (self.player_names[target] if target is not None else "NOTHING"),
            "ships_left": self._ships_left_list(),
        })

    def _collect_round_attacks(self):
        """
        Freeze attacks for this round.
        Returns list of dicts:
            {attacker, target, tile}
        Only attacks with target != None and tile selected are included.
        """
        attacks = []
        for p in range(self.num_players):
            if not self.alive[p]:
                continue
            tile = self.selected_tile[p]
            cycle = self.target_cycle[p]
            if tile is None or not cycle:
                continue

            target = cycle[self.target_index[p]]
            if target is None:
                continue

            attacks.append({
                "attacker": p,
                "target": target,
                "tile": tile,
            })
        return attacks

    def _resolve_round_simultaneous(self, attacks):
        """
        Simultaneous resolution:
        - determine all hits from the board state at round end
        - then apply all destroys together
        - then update alive flags
        """
        pending_hits = []  # list of (target, tile, attacker)
        results = []

        for atk in attacks:
            attacker = atk["attacker"]
            target = atk["target"]
            tile = atk["tile"]

            hit = (tile in self.ships[target] and tile not in self.destroyed[target])

            results.append({
                "attacker": attacker,
                "target": target,
                "tile": tile,
                "hit": hit,
            })

            if hit:
                pending_hits.append((target, tile, attacker))

        # Apply all hits together
        hit_targets_before = set(p for p in range(self.num_players) if self.alive[p])

        for target, tile, attacker in pending_hits:
            self.destroyed[target].add(tile)

        self._update_alive_flags()

        eliminated_now = []
        for p in range(self.num_players):
            if p in hit_targets_before and not self.alive[p]:
                eliminated_now.append(p)

        return results, eliminated_now

    def _flash_round_feedback(self, results, eliminated_now):
        """
        Runs in a separate thread so the round timer is never delayed.
        """
        stop_evt = self._feedback_stop

        # Flash attack results
        for _ in range(2):
            if self._stop.is_set() or stop_evt.is_set():
                return

            for res in results:
                a = res["attacker"]
                t = res["target"]
                tile = res["tile"]

                a_wall = self._wall_for_player(a)
                t_wall = self._wall_for_player(t)

                if a_wall is None or t_wall is None:
                    continue

                if res["hit"]:
                    self._svc.set_led(a_wall, tile, *GREEN)
                    self._svc.set_led(t_wall, tile, *RED)
                else:
                    self._svc.set_led(a_wall, tile, *YELLOW)
                    self._svc.set_led(t_wall, tile, *WHITE)

            end_t = time.perf_counter() + 0.12
            while time.perf_counter() < end_t:
                if self._stop.is_set() or stop_evt.is_set():
                    return
                time.sleep(0.005)

            self._draw_battle_leds()

            end_t = time.perf_counter() + 0.06
            while time.perf_counter() < end_t:
                if self._stop.is_set() or stop_evt.is_set():
                    return
                time.sleep(0.005)

        # Flash eliminated players
        for p in eliminated_now:
            wall = self._wall_for_player(p)
            if wall is None:
                continue

            for _ in range(2):
                if self._stop.is_set() or stop_evt.is_set():
                    return

                for led in range(LEDS_PER_CHANNEL):
                    self._svc.set_led(wall, led, *RED)

                end_t = time.perf_counter() + 0.10
                while time.perf_counter() < end_t:
                    if self._stop.is_set() or stop_evt.is_set():
                        return
                    time.sleep(0.005)

                self._draw_battle_leds()

                end_t = time.perf_counter() + 0.05
                while time.perf_counter() < end_t:
                    if self._stop.is_set() or stop_evt.is_set():
                        return
                    time.sleep(0.005)

    def _do_game_over(self, winners):
        self.state = S_GAMEOVER
        self._draw_gameover_leds()

        if len(winners) == 1:
            winner = winners[0]
            win_wall = self._wall_for_player(winner)
            color = PLAYER_COLORS_RGB[winner]

            for _ in range(5):
                if self._stop.is_set():
                    break
                for led in range(LEDS_PER_CHANNEL):
                    self._svc.set_led(win_wall, led, *color)
                time.sleep(0.22)
                self._svc.all_off()
                time.sleep(0.12)

            self._draw_gameover_leds()
            self._notify("game_over", {
                "draw": False,
                "winner": winner,
                "winner_name": self.player_names[winner],
                "ships_left": self._ships_left_list(),
            })
        else:
            # Rare case: all remaining players eliminated in same round
            for _ in range(4):
                if self._stop.is_set():
                    break
                self._svc.all_off()
                time.sleep(0.14)
                self._draw_gameover_leds()
                time.sleep(0.14)

            self._notify("game_over", {
                "draw": True,
                "winner": None,
                "winner_name": None,
                "ships_left": self._ships_left_list(),
            })

    # ── Main loop ─────────────────────────────────────────────────────────────
    def _loop(self):
        self._notify("placement_started", {
            "names": list(self.player_names[:self.num_players]),
            "ships_per_player": SHIPS_PER_PLAYER,
        })

        # Placement phase
        while not self._stop.is_set() and self.state == S_PLACEMENT:
            self._draw_placement_leds()

            if self._all_ready():
                break

            time.sleep(0.03)

        if self._stop.is_set():
            return

        # Start battle
        self.state = S_ACTIVE
        self._update_alive_flags()
        self._draw_battle_leds()

        self._notify("battle_started", {
            "ships_left": self._ships_left_list(),
        })

        # Simultaneous rounds
        while not self._stop.is_set() and self.state == S_ACTIVE:
            alive = self._alive_players()
            if len(alive) <= 1:
                break

            self._stop_feedback_thread()
            self._begin_round()

            next_tick = time.perf_counter()

            while not self._stop.is_set():
                now = time.perf_counter()
                round_left = max(0.0, self.round_deadline - now)

                # Fast blink eye LEDs under 3 sec
                if round_left < 3.0:
                    phase = int(now * 8) % 2
                    for p in range(self.num_players):
                        wall = self._wall_for_player(p)
                        if wall is None:
                            continue
                        col = self._life_eye_color(p) if phase == 0 else OFF
                        self._svc.set_led(wall, EYE_LED, *col)

                    # restore selected overlays after blink write
                    for p in range(self.num_players):
                        tile = self.selected_tile[p]
                        if tile is None or not self.alive[p]:
                            continue
                        wall = self._wall_for_player(p)
                        cycle = self.target_cycle[p]
                        if not cycle:
                            continue
                        target = cycle[self.target_index[p]]
                        if target is None:
                            self._svc.set_led(wall, tile, *WHITE)
                        else:
                            self._svc.set_led(wall, tile, *PLAYER_COLORS_RGB[target])
                else:
                    # keep LEDs stable outside blink phase
                    self._draw_battle_leds()

                self._notify("tick", {
                    "round_index": self.round_index,
                    "round_left": round_left,
                    "round_max": self.round_duration,
                    "ships_left": self._ships_left_list(),
                    "selections": [
                        {
                            "tile": self.selected_tile[p],
                            "target_name": (
                                self.player_names[self.target_cycle[p][self.target_index[p]]]
                                if self.alive[p]
                                and self.target_cycle[p]
                                and self.target_cycle[p][self.target_index[p]] is not None
                                else "NOTHING" if self.alive[p] and self.selected_tile[p] is not None else None
                            )
                        }
                        for p in range(self.num_players)
                    ]
                })

                if round_left <= 0:
                    break

                next_tick += self._tick_rate
                sleep_time = next_tick - time.perf_counter()
                if sleep_time > 0:
                    time.sleep(sleep_time)
                else:
                    # catch up if system lagged, no cumulative drift
                    next_tick = time.perf_counter()

            if self._stop.is_set():
                return

            self._draw_battle_leds()

            attacks = self._collect_round_attacks()
            results, eliminated_now = self._resolve_round_simultaneous(attacks)

            self._start_feedback_thread(results, eliminated_now)

            self._notify("round_resolved", {
                "results": [
                    {
                        "attacker": r["attacker"],
                        "attacker_name": self.player_names[r["attacker"]],
                        "target": r["target"],
                        "target_name": self.player_names[r["target"]],
                        "tile": r["tile"],
                        "hit": r["hit"],
                    }
                    for r in results
                ],
                "eliminated": eliminated_now,
                "eliminated_names": [self.player_names[p] for p in eliminated_now],
                "ships_left": self._ships_left_list(),
            })

            alive = self._alive_players()
            if len(alive) <= 1:
                break
            if len(alive) == 0:
                break

        self._stop_feedback_thread()

        alive = self._alive_players()
        if not self._stop.is_set():
            if len(alive) == 1:
                self._do_game_over(alive)
            elif len(alive) == 0:
                self._do_game_over([])

# ─────────────────────────────────────────────────────────────────────────────
# Main Application
# ─────────────────────────────────────────────────────────────────────────────
class BattleShipsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BattleShips – Evil Eye")
        self.configure(bg=BG_DARK)
        self.minsize(960, 700)

        self.bind("<F11>", lambda e: self.attributes("-fullscreen",
                                                     not self.attributes("-fullscreen")))
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        # ── Service ────────────────────────────────────────────────────────────
        self._cfg = load_config()
        self._service = LightService()
        self._service.on_status = lambda m: self.after(0, lambda msg=m: self._set_status(msg))

        ip = self._cfg.get("device_ip", "127.0.0.1")
        if ip:
            self._service.set_device(ip, self._cfg.get("udp_port", 4626))
        self._service.set_recv_port(self._cfg.get("receiver_port", 7800))
        self._service.set_poll_rate(self._cfg.get("polling_rate_ms", 100))
        self._service.start_receiver()
        self._service.start_polling()

        # ── Game ───────────────────────────────────────────────────────────────
        self._game = BattleShipsGame(self._service, self._on_game_event)
        self._service.on_button_state = self._game.handle_button

        # ── Setup vars ────────────────────────────────────────────────────────
        self._v_players = tk.IntVar(value=2)
        self._v_player_names = [tk.StringVar(value=PLAYER_NAMES_DEFAULT[i]) for i in range(MAX_PLAYERS)]
        self._v_device_ip = tk.StringVar(value=ip or "127.0.0.1")

        # ── Screens ───────────────────────────────────────────────────────────
        self._frame_setup = tk.Frame(self, bg=BG_DARK)
        self._frame_game  = tk.Frame(self, bg=BG_DARK)
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
    
    def _choose_interface_dialog(self, interfaces):
        """
        Returns selected tuple: (iface_name, ip, bcast) or None
        """
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
        win.wait_visibility()
        win.grab_set()
        self.wait_window(win)

        return result["value"]
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

        self.wait_window(win)
        return result["value"]


    def _run_discovery_flow_gui(self):
        interfaces = get_local_interfaces()
        if not interfaces:
            self._set_status("No active network interfaces found.")
            return None

        selected = self._choose_interface_dialog(interfaces)
        if not selected:
            self._set_status("Network selection canceled.")
            return None

        iface_name, bind_ip, bcast_ip = selected
        self._set_status(f"Scanning on {iface_name} ({bind_ip})...")

        try:
            devices = discover_devices_on_interface(
                bind_ip=bind_ip,
                broadcast_ip=bcast_ip,
                recv_port=self._cfg.get("receiver_port", 7800),
                send_port=self._cfg.get("udp_port", 4626),
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

        tk.Label(f, text="BATTLESHIPS", bg=BG_DARK, fg="#ff3c00",
                 font=("Consolas", 34, "bold")).pack(pady=(20, 2))
        tk.Label(f, text="Simultaneous rounds · Hidden ships · Evil Eye", bg=BG_DARK, fg=FG_DIM,
                 font=FONT_SM).pack(pady=(0, 10))

        content = tk.Frame(f, bg=BG_DARK)
        content.pack(fill=tk.BOTH, expand=True)

        row = 0

        self._setup_lbl(content, "NUMBER OF PLAYERS", row); row += 1
        r = tk.Frame(content, bg=BG_DARK)
        r.grid(row=row, column=0, columnspan=2, pady=(0, 14)); row += 1
        for n in range(2, 5):
            _seg_btn(r, str(n), self._v_players, n,
                     active_bg=PLAYER_HEX[n - 2], width=5, height=2,
                     font=("Consolas", 18, "bold")).pack(side=tk.LEFT, padx=6)

        self._lbl_wall_info = tk.Label(content, text="", bg=BG_DARK, fg=FG_DIM,
                                       font=("Consolas", 9))
        self._lbl_wall_info.grid(row=row, column=0, columnspan=2, pady=(0, 14)); row += 1
        self._v_players.trace_add("write", self._refresh_wall_info)
        self._refresh_wall_info()

        self._setup_lbl(content, "PLAYER NAMES", row); row += 1
        names_frame = tk.Frame(content, bg=BG_DARK)
        names_frame.grid(row=row, column=0, columnspan=2, pady=(0, 14)); row += 1

        self._name_entries = []
        for i in range(MAX_PLAYERS):
            col = PLAYER_HEX[i]
            tk.Label(names_frame, text=f"{chr(65+i)}:", bg=BG_DARK, fg=col,
                     font=FONT_SM).grid(row=i // 2, column=(i % 2) * 2,
                                        padx=(10, 4), pady=4, sticky="e")
            e = tk.Entry(names_frame, textvariable=self._v_player_names[i],
                         width=12, bg=BG_PANEL, fg=FG_MAIN,
                         font=("Consolas", 13), insertbackground="white",
                         relief="flat", highlightthickness=1,
                         highlightbackground=col, highlightcolor=col)
            e.grid(row=i // 2, column=(i % 2) * 2 + 1, padx=(0, 20), pady=4)
            self._name_entries.append(e)

        self._setup_lbl(content, "RULES", row); row += 1
        rules = (
            "1) Each player places 3 ships on their own wall.\n"
            "2) Ships disappear from LEDs after placement.\n"
            "3) Every round, all alive players choose attack at the same time.\n"
            "4) Press one tile on your wall.\n"
            "5) Re-press same tile to cycle target through opponents, then NOTHING.\n"
            "6) At round end, all attacks resolve simultaneously."
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

    def _refresh_wall_info(self, *_):
        n = self._v_players.get()
        mapping = PLAYER_WALLS.get(n, {})
        parts = []
        for p, walls in sorted(mapping.items()):
            parts.append(f"{PLAYER_NAMES_DEFAULT[p][:8]}→Wall{walls[0]}")
        self._lbl_wall_info.configure(text="  |  ".join(parts))

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

        self._score_bar = tk.Frame(f, bg=BG_MID)
        self._score_bar.pack(fill=tk.X, pady=(0, 4))
        self._score_panels = []
        for i in range(MAX_PLAYERS):
            pf = tk.Frame(self._score_bar, bg=BG_PANEL, padx=16, pady=6,
                          highlightthickness=0)
            nl = tk.Label(pf, text=PLAYER_NAMES_DEFAULT[i], bg=BG_PANEL,
                          fg=PLAYER_HEX[i], font=("Consolas", 10, "bold"))
            nl.pack()
            sl = tk.Label(pf, text="3 ships", bg=BG_PANEL, fg=FG_MAIN,
                          font=("Consolas", 18, "bold"))
            sl.pack()
            self._score_panels.append((pf, nl, sl))

        self._lbl_phase = tk.Label(f, text="", bg=BG_DARK, fg=FG_BLUE,
                                   font=("Consolas", 22, "bold"))
        self._lbl_phase.pack(pady=(8, 2))

        self._lbl_round = tk.Label(f, text="", bg=BG_DARK, fg=FG_MAIN,
                                   font=("Consolas", 26, "bold"))
        self._lbl_round.pack(pady=(2, 2))

        self._lbl_action = tk.Label(f, text="", bg=BG_DARK, fg=FG_DIM,
                                    font=("Consolas", 13))
        self._lbl_action.pack()

        clock_frame = tk.Frame(f, bg=BG_DARK)
        clock_frame.pack(expand=True)

        self._lbl_clock = tk.Label(clock_frame, text="--.-", bg=BG_DARK, fg=FG_MAIN,
                                   font=("Consolas", 72, "bold"))
        self._lbl_clock.pack()

        self._lbl_turn = tk.Label(clock_frame, text="", bg=BG_DARK, fg=FG_DIM,
                                  font=("Consolas", 14), justify="center")
        self._lbl_turn.pack(pady=(0, 8))

        self._turn_bar = tk.Canvas(f, bg=BG_PANEL, height=10, highlightthickness=0)
        self._turn_bar.pack(fill=tk.X, padx=60, pady=(0, 12))
        self._turn_bar_max = ROUND_MAX_SECONDS

    # ── UI updates ────────────────────────────────────────────────────────────
    def _update_scores(self, ships_left, num_players):
        for i, (pf, nl, sl) in enumerate(self._score_panels):
            pf.pack_forget()

        for i in range(num_players):
            pf, nl, sl = self._score_panels[i]
            nl.configure(text=self._game.player_names[i], fg=PLAYER_HEX[i])
            sl.configure(text=f"{ships_left[i]} ship{'s' if ships_left[i] != 1 else ''}")

            is_alive = ships_left[i] > 0
            pf.configure(
                bg=BG_PANEL,
                highlightbackground=("#333" if is_alive else "#660000"),
                highlightthickness=1,
                highlightcolor="#333",
            )
            pf.pack(side=tk.LEFT, padx=6, pady=6, expand=True)

    def _update_turn_bar(self, left_s, max_s):
        pct = 0 if max_s <= 0 else max(0.0, min(1.0, left_s / max_s))
        w = self._turn_bar.winfo_width() or 600
        self._turn_bar.delete("all")
        self._turn_bar.create_rectangle(0, 0, w, 10, fill=BG_PANEL, outline="")
        bw = int(w * pct)
        if bw > 0:
            col = FG_GREEN if pct > 0.5 else (FG_GOLD if pct > 0.25 else FG_RED)
            self._turn_bar.create_rectangle(0, 0, bw, 10, fill=col, outline="")

    def _on_game_event(self, event, data):
        self.after(0, lambda e=event, d=data: self._dispatch(e, d))

    def _dispatch(self, event, data):
        if event == "placement_started":
            self._lbl_phase.configure(text="PLACEMENT", fg=FG_BLUE)
            self._lbl_round.configure(text="Choose 3 ships on each wall", fg=FG_MAIN)
            self._lbl_action.configure(
                text="Placement LEDs are visible now. They will disappear when battle starts.",
                fg=FG_DIM
            )
            self._lbl_clock.configure(text="---", fg=FG_MAIN)
            self._lbl_turn.configure(text="")
            self._update_scores([SHIPS_PER_PLAYER] * self._game.num_players, self._game.num_players)
            self._update_turn_bar(0, 1)

        elif event == "placement_update":
            ready_count = sum(1 for x in data["ready_flags"] if x)
            self._lbl_action.configure(
                text=f"{data['name']} placed {data['placed']}/{SHIPS_PER_PLAYER} ships · Ready: {ready_count}/{self._game.num_players}",
                fg=FG_GOLD if data["ready"] else FG_DIM
            )

        elif event == "battle_started":
            self._lbl_phase.configure(text="BATTLE", fg=FG_RED)
            self._lbl_round.configure(text="Ships hidden · Simultaneous rounds", fg=FG_MAIN)
            self._lbl_action.configure(
                text="Press one tile. Re-press same tile to cycle target. White = NOTHING.",
                fg=FG_MAIN
            )
            self._update_scores(data["ships_left"], self._game.num_players)

        elif event == "round_started":
            self._turn_bar_max = data["round_time"]
            self._lbl_round.configure(text=f"ROUND {data['round_index']}", fg=FG_MAIN)
            self._lbl_action.configure(
                text="All alive players choose attacks now.",
                fg=FG_MAIN
            )
            self._update_scores(data["ships_left"], self._game.num_players)

        elif event == "selection_changed":
            target_name = data["target_name"]
            color = FG_GOLD if target_name == "NOTHING" else (
                PLAYER_HEX[data["target"]] if data["target"] is not None else FG_GOLD
            )
            self._lbl_action.configure(
                text=f"{data['name']} selected tile {data['tile']} → {target_name}",
                fg=color
            )
            self._update_scores(data["ships_left"], self._game.num_players)

        elif event == "tick":
            left_s = data["round_left"]
            self._lbl_clock.configure(
                text=f"{left_s:0.1f}",
                fg=(FG_GREEN if left_s > 5 else FG_GOLD if left_s > 2 else FG_RED)
            )

            lines = []
            for i in range(self._game.num_players):
                sel = data["selections"][i]
                tile = sel["tile"]
                target_name = sel["target_name"]

                if data["ships_left"][i] <= 0:
                    lines.append(f"{self._game.player_names[i]}: ELIMINATED")
                elif tile is None:
                    lines.append(f"{self._game.player_names[i]}: no attack selected")
                elif target_name == "NOTHING":
                    lines.append(f"{self._game.player_names[i]}: tile {tile} → NOTHING")
                else:
                    lines.append(f"{self._game.player_names[i]}: tile {tile} → {target_name}")

            self._lbl_turn.configure(text="\n".join(lines), fg=FG_DIM)
            self._update_turn_bar(left_s, data["round_max"])
            self._update_scores(data["ships_left"], self._game.num_players)

        elif event == "round_resolved":
            if not data["results"]:
                self._lbl_action.configure(
                    text="No attacks were confirmed this round.",
                    fg=FG_GOLD
                )
            else:
                parts = []
                for r in data["results"]:
                    verdict = "HIT" if r["hit"] else "MISS"
                    parts.append(f"{r['attacker_name']}→{r['target_name']}@{r['tile']} {verdict}")
                txt = "  |  ".join(parts)
                self._lbl_action.configure(
                    text=txt,
                    fg=FG_GREEN if any(r["hit"] for r in data["results"]) else FG_GOLD
                )

            if data["eliminated_names"]:
                self._lbl_round.configure(
                    text="Eliminated: " + ", ".join(data["eliminated_names"]),
                    fg=FG_RED
                )
            self._update_scores(data["ships_left"], self._game.num_players)

        elif event == "game_over":
            self._lbl_phase.configure(text="GAME OVER", fg=FG_GOLD)
            self._lbl_clock.configure(text="0.0", fg=FG_RED)
            self._lbl_turn.configure(text="")

            if data["draw"]:
                self._lbl_round.configure(text="DRAW", fg=FG_GOLD)
                self._lbl_action.configure(
                    text="All remaining players were eliminated in the same round.",
                    fg=FG_GOLD
                )
            else:
                self._lbl_round.configure(
                    text=f"🏆 {data['winner_name']} wins!",
                    fg=PLAYER_HEX[data["winner"]]
                )
                self._lbl_action.configure(
                    text="Only one player has ships remaining.",
                    fg=FG_GOLD
                )

            self._update_scores(data["ships_left"], self._game.num_players)
            self._update_turn_bar(0, 1)

    # ── Controls ──────────────────────────────────────────────────────────────
    def _apply_ip(self):
        ip = self._v_device_ip.get().strip()
        self._service.set_device(ip, self._cfg.get("udp_port", 4626))
        self._cfg["device_ip"] = ip
        save_config(self._cfg)
        self._set_status(f"Device → {ip}")

    def _start_game(self):
        # 1) user chooses network + discovery runs
        discovered_ip = self._run_discovery_flow_gui()

        # 2) if a device is found, set it automatically
        if discovered_ip:
            self._v_device_ip.set(discovered_ip)

        # 3) apply current/found IP
        self._apply_ip()

        # 4) start game
        names = [v.get() for v in self._v_player_names]
        self._game.start_game(
            num_players=self._v_players.get(),
            player_names=names,
        )

        self._lbl_phase.configure(text="PLACEMENT", fg=FG_BLUE)
        self._lbl_clock.configure(text="---", fg=FG_MAIN)
        self._lbl_round.configure(text="", fg=FG_MAIN)
        self._lbl_action.configure(text="", fg=FG_DIM)
        self._lbl_turn.configure(text="")
        self._update_scores([SHIPS_PER_PLAYER] * self._v_players.get(), self._v_players.get())
        self._show_game()

    def _stop_game(self):
        self._game.stop_game()
        self._lbl_action.configure(text="Game stopped.", fg=FG_DIM)
        self._lbl_turn.configure(text="")

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
    BattleShipsApp().mainloop()