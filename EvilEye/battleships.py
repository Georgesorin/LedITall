"""
battleships.py – Simultaneous Multiplayer BattleShips for Evil Eye LED hardware

The Rules of the Game:
1. You can have 2, 3, or 4 players. Each player stands in front of their own LED wall.
2. The game starts in "Placement Mode". Everyone secretly presses 3 buttons on their wall to hide their ships.
3. Once everyone hides 3 ships, the "Battle" begins! The ships turn invisible.
4. It's a race! You press a button on your wall to guess where someone else hid a ship.
5. If you press the same button again, you change WHO you are attacking (Player A, B, C, or NOBODY).
6. When the giant timer hits zero, all missiles fire at the exact same time!
"""

import os
import sys
import time
import socket
import random
import struct
import threading
import tkinter as tk

# ==============================================================================
# --- BORROWING TOOLS ---
# We need some special tools from another file called 'Controller.py'
# This file knows how to talk to the physical LED walls.
# ==============================================================================
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from Controller import (
    LightService, load_config, save_config,
    LEDS_PER_CHANNEL,
)

# We check if we have a tool called 'psutil'. 
# It helps us find our computer's Wi-Fi addresses.
try:
    import psutil
    PSUTIL_AVAILABLE = True
except Exception:
    PSUTIL_AVAILABLE = False


# ==============================================================================
# --- THE GAME SETTINGS (Constants) ---
# Here we decide the rules of our universe.
# ==============================================================================
MAX_PLAYERS = 4
MIN_PLAYERS = 2

EYE_LED = 0 # The big center light on the wall that shows if you are alive or dead
BUTTONS = list(range(1, 11))  # The 10 buttons you can press on your wall
SHIPS_PER_PLAYER = 3 # Everyone gets 3 ships!

ROUND_MIN_SECONDS = 10.0 # The shortest time a battle round can take
ROUND_MAX_SECONDS = 15.0 # The longest time a battle round can take
TICK_RATE = 1.0 / 30.0 # How fast the game thinks (30 times a second)
INPUT_DEBOUNCE_S = 0.08 # A tiny pause so the button doesn't accidentally click twice really fast

# Which wall belongs to which player?
PLAYER_WALLS = {
    2: {0: 1, 1: 2}, # If 2 players: Player A gets Wall 1, Player B gets Wall 2
    3: {0: 1, 1: 2, 2: 3},
    4: {0: 1, 1: 2, 2: 3, 3: 4},
}

# Colors for the players!
PLAYER_COLORS_RGB = [
    (255,  60,   0),   # A: Orange-Red
    (0,   100, 255),   # B: Blue
    (0,   210,  60),   # C: Green
    (200,   0, 200),   # D: Purple
]
PLAYER_HEX = ["#ff3c00", "#0064ff", "#00d23c", "#c800c8"] # Same colors, but for the computer screen
PLAYER_NAMES_DEFAULT = ["PLAYER A", "PLAYER B", "PLAYER C", "PLAYER D"]

# Simple colors
RED    = (255,   0,   0)
GREEN  = (0,   255,   0)
YELLOW = (255, 200,   0)
WHITE  = (255, 255, 255)
OFF    = (0,     0,   0) # Black means the light is off
ORANGE = (255, 120,   0)

# The color of the big center "EYE" depends on how many ships you have left
LIFE_COLORS = {
    3: GREEN,  # 3 ships = Healthy (Green)
    2: YELLOW, # 2 ships = Warning (Yellow)
    1: ORANGE, # 1 ship = Danger (Orange)
    0: RED,    # 0 ships = Dead (Red)
}

# The different chapters (States) of the game
S_SETUP = "setup"         # Changing settings on the computer
S_PLACEMENT = "placement" # Hiding your ships on the wall
S_ACTIVE = "active"       # Missiles are flying!
S_GAMEOVER = "gameover"   # The game is finished

# Colors for the computer screen (Dark Mode UI)
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


# ==============================================================================
# --- RADAR & WIFI (Network Discovery) ---
# These functions act like a radar. They yell out into the Wi-Fi: "Are there any 
# LED walls out there?!" and wait for the walls to reply "I'm here!"
# (This part is very technical computer networking stuff).
# ==============================================================================
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
    """Finds all the Wi-Fi and cable connections on your computer."""
    interfaces = []
    # (Complex logic to find the correct Wi-Fi channel is hidden here)
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
                item = (iface_name, ip, bcast)
                if item not in seen:
                    seen.add(item)
                    interfaces.append(item)
        if interfaces:
            return interfaces
            
    # Fallback if psutil fails
    candidates = set()
    try:
        hostname = socket.gethostname()
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

    out = []
    for i, ip in enumerate(sorted(candidates)):
        bcast = "169.254.255.255" if ip.startswith("169.254.") else broadcast_from_ip_mask(ip, "255.255.255.0")
        out.append((f"Interface {i}", ip, bcast))
    return out

def build_discovery_packet():
    """Creates a special 'HELLO!' message to send to the hardware."""
    rand1, rand2 = random.randint(0, 127), random.randint(0, 127)
    payload = bytearray([0x0A, 0x02, *b"KX-HC04", 0x03, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x14])
    pkt = bytearray([0x67, rand1, rand2, len(payload)]) + payload
    pkt.append(calc_sum(pkt))
    return pkt, rand1, rand2

def discover_devices_on_interface(bind_ip: str, broadcast_ip: str, timeout_s: float = 3.0):
    """Yells 'HELLO!' and waits 3 seconds to see if the hardware yells back."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    devices = []

    try:
        try:
            sock.bind((bind_ip, 0))   # bind to a random free port
        except Exception:
            sock.bind(("", 0))

        pkt, r1, r2 = build_discovery_packet()
        sock.sendto(pkt, (broadcast_ip, 4626))

        sock.settimeout(0.5)
        end_time = time.time() + timeout_s

        while time.time() < end_time:
            try:
                data, addr = sock.recvfrom(1024)
                if len(data) >= 30 and data[0] == 0x68 and data[1] == r1 and data[2] == r2:
                    if addr[0] not in [d["ip"] for d in devices]:
                        model = data[6:13].decode(errors="ignore").strip("\x00") or "UNKNOWN"
                        devices.append({
                            "ip": addr[0],
                            "model": model,
                        })
            except socket.timeout:
                continue
            except Exception:
                pass
    finally:
        sock.close()

    return devices


# ==============================================================================
# --- COMPUTER SCREEN BUTTON MAKER (UI Helpers) ---
# Small robots that create pretty buttons for the computer screen.
# ==============================================================================
def _make_lbl_btn(parent, text, command, bg, fg=FG_MAIN, **kw):
    """Makes a clickable button out of a label (so we can control colors easily)."""
    hover_bg = kw.pop("hover_bg", "#555")
    lbl = tk.Label(
        parent,
        text=text,
        bg=bg,
        fg=fg,
        font=kw.pop("font", FONT_SM),
        padx=kw.pop("padx", 20),
        pady=kw.pop("pady", 10),
        cursor="hand2",
        **kw
    )
    lbl.bind("<Button-1>", lambda e: command()) # When clicked
    lbl.bind("<Enter>", lambda e: lbl.configure(bg=hover_bg)) # When mouse hovers over
    lbl.bind("<Leave>", lambda e: lbl.configure(bg=bg)) # When mouse leaves
    return lbl

def _seg_btn(parent, text, var, value, **kw):
    """Makes a toggle button (like choosing 2, 3, or 4 players)."""
    active_bg = kw.get("active_bg", "#ff3c00")
    inactive_bg = "#383838"

    lbl = tk.Label(
        parent,
        text=text,
        bg=inactive_bg,
        fg=FG_MAIN,
        font=kw.get("font", FONT_SM),
        width=kw.get("width", 6),
        height=kw.get("height", 1),
        cursor="hand2",
    )

    def _refresh(*_):
        lbl.configure(bg=active_bg if var.get() == value else inactive_bg)

    lbl.bind("<Button-1>", lambda e: var.set(value))
    lbl.bind("<Enter>", lambda e: lbl.configure(
        bg=active_bg if var.get() == value else "#4a4a4a"
    ))
    lbl.bind("<Leave>", lambda e: _refresh())
    var.trace_add("write", _refresh)
    _refresh()
    return lbl


# ==============================================================================
# --- THE GAME BRAIN (BattleShipsGame) ---
# This class knows all the rules of the game. It knows who is alive, 
# where the ships are, and what happens when someone gets hit!
# ==============================================================================
class BattleShipsGame:
    def __init__(self, service, on_event):
        self._svc = service # The robot that sends lights to the walls
        self._notify = on_event # The messenger that tells the computer screen what happened
        self._lock = threading.RLock() # Stops the game from getting confused
        self._stop = threading.Event()
        self._thread = None

        self._feedback_stop = threading.Event()
        self._feedback_thread = None

        self.num_players = 2
        self.player_names = list(PLAYER_NAMES_DEFAULT)
        self.state = S_SETUP

        # These notebooks remember everything about the players:
        self.ships = [set() for _ in range(MAX_PLAYERS)] # Where the ships are hidden
        self.destroyed = [set() for _ in range(MAX_PLAYERS)] # Which ships got exploded
        self.ready = [False] * MAX_PLAYERS # Have they finished hiding their ships?
        self.alive = [False] * MAX_PLAYERS # Are they still in the game?

        self.round_index = 0
        self.round_deadline = 0.0 # What time the big timer hits zero
        self.round_duration = 0.0 # How many seconds the round lasts

        # Notebooks for remembering what button they are currently pressing to attack
        self.selected_tile = [None] * MAX_PLAYERS
        self.target_cycle = [[] for _ in range(MAX_PLAYERS)]
        self.target_index = [0] * MAX_PLAYERS
        self.last_press_at = [0.0] * MAX_PLAYERS

    # ── Starting the Game ───────────────────────────────────────────────────
    def start_game(self, num_players, player_names=None):
        """Cleans off the board and gets ready for a brand new game."""
        self.stop_game()

        self.num_players = max(MIN_PLAYERS, min(MAX_PLAYERS, num_players))
        if player_names:
            for i, n in enumerate(player_names[:MAX_PLAYERS]):
                self.player_names[i] = (n or "").strip() or PLAYER_NAMES_DEFAULT[i]

        # Erase old ships and memories
        self.ships = [set() for _ in range(MAX_PLAYERS)]
        self.destroyed = [set() for _ in range(MAX_PLAYERS)]
        self.ready = [False] * MAX_PLAYERS
        self.alive = [i < self.num_players for i in range(MAX_PLAYERS)]

        self.round_index = 0
        self.round_deadline = 0.0
        self.round_duration = 0.0

        self.selected_tile = [None] * MAX_PLAYERS
        self.target_cycle = [[] for _ in range(MAX_PLAYERS)]
        self.target_index = [0] * MAX_PLAYERS
        self.last_press_at = [0.0] * MAX_PLAYERS

        self.state = S_PLACEMENT # Go into Hiding phase!
        self._stop.clear()

        self._svc.all_off() # Turn off all lights
        self._refresh_all_leds()

        # Start the heartbeat of the game in the background
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop_game(self):
        """Freezes the game and turns off all lights."""
        self._stop.set()
        self._stop_feedback_thread()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._svc.all_off()
        self.state = S_SETUP

    def handle_button(self, ch, led, is_triggered, is_disconnected):
        """This runs EVERY time someone physically presses a button on the wall!"""
        if is_disconnected or not is_triggered:
            return # Ignore if they let go of the button, or if wall disconnected
        if ch not in (1, 2, 3, 4):
            return # Ignore weird walls
        if led not in BUTTONS:
            return # Ignore weird buttons
        if self.state not in (S_PLACEMENT, S_ACTIVE):
            return # Ignore if game is over

        # Figure out who pushed the button
        player = self._player_for_wall(ch)
        if player is None:
            return

        # Tell the brain what to do based on what chapter of the game we are in
        if self.state == S_PLACEMENT:
            self._handle_placement_press(player, ch, led)
        elif self.state == S_ACTIVE:
            self._handle_battle_press(player, ch, led)

    # ── Small Helper Tools ─────────────────────────────────────────────────
    def _player_for_wall(self, ch):
        """Asks: Which player owns wall number 'ch'?"""
        for p, wall in PLAYER_WALLS.get(self.num_players, {}).items():
            if ch == wall:
                return p
        return None

    def _wall_for_player(self, player):
        """Asks: Which wall does 'player' own?"""
        return PLAYER_WALLS.get(self.num_players, {}).get(player)

    def _alive_ship_count(self, player):
        """Counts how many ships haven't exploded yet."""
        return len(self.ships[player] - self.destroyed[player])

    def _update_alive_flags(self):
        """Checks if anyone died because they ran out of ships."""
        for p in range(self.num_players):
            self.alive[p] = self._alive_ship_count(p) > 0

    def _alive_players(self):
        """Makes a list of everyone who is still in the game."""
        return [p for p in range(self.num_players) if self.alive[p]]

    def _all_ready(self):
        """Returns True if everyone has hidden exactly 3 ships."""
        return all(self.ready[p] for p in range(self.num_players))

    def _ships_left_list(self):
        return [self._alive_ship_count(p) for p in range(self.num_players)]

    def _life_eye_color(self, player):
        """Returns Green, Yellow, Orange, or Red depending on health."""
        return LIFE_COLORS.get(self._alive_ship_count(player), RED)

    def _stop_feedback_thread(self):
        """Stops the explosion light effects."""
        self._feedback_stop.set()
        thr = self._feedback_thread
        if thr and thr.is_alive():
            thr.join(timeout=0.5)
        self._feedback_thread = None
        self._feedback_stop.clear()

    def _start_feedback_thread(self, results, eliminated_now):
        """Starts a background movie (explosion animations) on the LED wall."""
        self._stop_feedback_thread()
        self._feedback_stop.clear()
        self._feedback_thread = threading.Thread(
            target=self._flash_round_feedback,
            args=(results, eliminated_now),
            daemon=True
        )
        self._feedback_thread.start()

    def _refresh_all_leds(self):
        self._svc.all_off()
        if self.state == S_PLACEMENT:
            self._draw_placement_leds()
        elif self.state == S_ACTIVE:
            self._draw_battle_leds()
        elif self.state == S_GAMEOVER:
            self._draw_gameover_leds()

    # ── Drawing Lights ──────────────────────────────────────────────────────
    def _draw_placement_leds(self):
        """Lights up the buttons a player has selected to be their ships."""
        for p in range(self.num_players):
            wall = self._wall_for_player(p)
            if wall is None:
                continue

            p_rgb = PLAYER_COLORS_RGB[p] # The player's assigned color

            for led in BUTTONS:
                # If they placed a ship here, turn it their color. If not, turn it off.
                self._svc.set_led(wall, led, *(p_rgb if led in self.ships[p] else OFF))

            # If they finished placing 3 ships, turn the giant EYE LED Green!
            self.ready[p] = (len(self.ships[p]) == SHIPS_PER_PLAYER)
            self._svc.set_led(wall, EYE_LED, *(GREEN if self.ready[p] else p_rgb))

    def _draw_battle_leds(self):
        """Hides the ships, and only shows where you are aiming your missile."""
        for p in range(self.num_players):
            wall = self._wall_for_player(p)
            if wall is None:
                continue

            # Hide all ships (turn off all normal buttons)
            for led in BUTTONS:
                self._svc.set_led(wall, led, *OFF)

            # Keep the giant EYE LED on to show health
            self._svc.set_led(wall, EYE_LED, *self._life_eye_color(p))

        # Show the targeting missile!
        for p in range(self.num_players):
            if not self.alive[p]:
                continue # Dead players can't aim

            wall = self._wall_for_player(p)
            tile = self.selected_tile[p]
            if wall is None or tile is None:
                continue

            cycle = self.target_cycle[p]
            if not cycle:
                continue

            # Look at who they are attacking, and light up that button with the ENEMY'S color!
            # If they chose "NOTHING", light it up WHITE.
            target = cycle[self.target_index[p]]
            self._svc.set_led(wall, tile, *(WHITE if target is None else PLAYER_COLORS_RGB[target]))

    def _draw_gameover_leds(self):
        """Shows the winner!"""
        alive = self._alive_players()
        winner = alive[0] if len(alive) == 1 else None

        for p in range(self.num_players):
            wall = self._wall_for_player(p)
            if wall is None:
                continue

            for led in BUTTONS:
                self._svc.set_led(wall, led, *OFF)

            self._svc.set_led(wall, EYE_LED, *self._life_eye_color(p))

            # If this player won, turn ALL their buttons to their color to celebrate!
            if winner is not None and p == winner:
                for led in BUTTONS:
                    self._svc.set_led(wall, led, *PLAYER_COLORS_RGB[p])

    # ── Placement Rules ──────────────────────────────────────────────────────
    def _handle_placement_press(self, player, ch, led):
        """What happens when you press a button during the hiding phase."""
        wall = self._wall_for_player(player)
        if ch != wall:
            return

        with self._lock:
            # If they press a ship they already placed, erase it (let them change their mind)
            if led in self.ships[player]:
                self.ships[player].remove(led)
            # If they haven't placed 3 ships yet, add a new one here!
            elif len(self.ships[player]) < SHIPS_PER_PLAYER:
                self.ships[player].add(led)

            # Did they hit the magic number of 3?
            self.ready[player] = (len(self.ships[player]) == SHIPS_PER_PLAYER)

        self._draw_placement_leds()
        # Tell the computer screen what happened
        self._notify("placement_update", {
            "player": player,
            "name": self.player_names[player],
            "placed": len(self.ships[player]),
            "ready": self.ready[player],
            "ready_flags": list(self.ready[:self.num_players]),
        })

    # ── Battle Rules ─────────────────────────────────────────────────────────
    def _build_cycle_for_player(self, player):
        """Creates a list of enemies you can attack. (e.g., Player A can attack B, C, or None)"""
        return [p for p in range(self.num_players) if self.alive[p] and p != player] + [None]

    def _begin_round(self):
        """Starts the timer for a new missile-firing round."""
        self.round_index += 1
        # Pick a random time between 10 and 15 seconds
        self.round_duration = random.uniform(ROUND_MIN_SECONDS, ROUND_MAX_SECONDS) 
        self.round_deadline = time.perf_counter() + self.round_duration

        # Reset everyone's aiming missile to nothing
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
        """What happens when you press a button to aim your missile."""
        wall = self._wall_for_player(player)
        if ch != wall:
            return
        if not self.alive[player]:
            return # Dead players can't fire

        now = time.perf_counter()

        with self._lock:
            # Wait a tiny bit so a fat finger doesn't count as two clicks
            if now - self.last_press_at[player] < INPUT_DEBOUNCE_S:
                return
            self.last_press_at[player] = now

            # If they clicked a BRAND NEW tile, aim there!
            if self.selected_tile[player] != led:
                self.selected_tile[player] = led
                self.target_cycle[player] = self._build_cycle_for_player(player)
                self.target_index[player] = 0 # Default target is the first enemy in the list
            # If they clicked the SAME tile again, switch targets! (A -> B -> C -> Nobody)
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
            "target_name": self.player_names[target] if target is not None else "NOTHING",
            "ships_left": self._ships_left_list(),
        })

    def _collect_round_attacks(self):
        """When the timer hits zero, collect all the missiles people aimed."""
        attacks = []
        for p in range(self.num_players):
            if not self.alive[p]:
                continue

            tile = self.selected_tile[p]
            cycle = self.target_cycle[p]
            if tile is None or not cycle:
                continue # They didn't aim at anything

            target = cycle[self.target_index[p]]
            if target is None:
                continue # They aimed at "NOTHING"

            attacks.append({
                "attacker": p,
                "target": target,
                "tile": tile,
            })
        return attacks

    def _resolve_round_simultaneous(self, attacks):
        """KABOOM! Figure out which missiles hit a ship and which ones missed."""
        results = []
        pending_hits = []
        alive_before = set(self._alive_players())

        # Check every missile fired
        for atk in attacks:
            attacker = atk["attacker"]
            target = atk["target"]
            tile = atk["tile"]

            # Did the missile land exactly on a tile where the enemy hid a ship?
            hit = (tile in self.ships[target] and tile not in self.destroyed[target])

            results.append({
                "attacker": attacker,
                "target": target,
                "tile": tile,
                "hit": hit,
            })

            # Add it to a list, but don't destroy it yet (Simultaneous hits!)
            if hit:
                pending_hits.append((target, tile))

        # Now destroy all the hit ships at the exact same time
        for target, tile in pending_hits:
            self.destroyed[target].add(tile)

        self._update_alive_flags()
        
        # Check if anyone died this exact round
        eliminated_now = [p for p in alive_before if not self.alive[p]]
        eliminated_now.sort()

        return results, eliminated_now

    def _flash_round_feedback(self, results, eliminated_now):
        """The Movie Maker! Flashes lights so players know if they hit or missed."""
        stop_evt = self._feedback_stop

        # Flash the hit/miss colors twice!
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
                    # BOOM! Attacker sees Green, Victim sees Red!
                    self._svc.set_led(a_wall, tile, *GREEN)
                    self._svc.set_led(t_wall, tile, *RED)
                else:
                    # SPLASH! Attacker sees Yellow (miss), Victim sees White
                    self._svc.set_led(a_wall, tile, *YELLOW)
                    self._svc.set_led(t_wall, tile, *WHITE)

            # Wait a tiny bit so humans can see the flash
            end_t = time.perf_counter() + 0.12
            while time.perf_counter() < end_t:
                if self._stop.is_set() or stop_evt.is_set(): return
                time.sleep(0.005)

            # Turn off the flash
            self._draw_battle_leds()

            end_t = time.perf_counter() + 0.06
            while time.perf_counter() < end_t:
                if self._stop.is_set() or stop_evt.is_set(): return
                time.sleep(0.005)

        # If someone died, flash their whole wall RED twice!
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
                    if self._stop.is_set() or stop_evt.is_set(): return
                    time.sleep(0.005)

                self._draw_battle_leds()

                end_t = time.perf_counter() + 0.05
                while time.perf_counter() < end_t:
                    if self._stop.is_set() or stop_evt.is_set(): return
                    time.sleep(0.005)

    def _do_game_over(self, winners):
        """Shows the winner, or calls a draw."""
        self.state = S_GAMEOVER
        self._draw_gameover_leds()

        if len(winners) == 1:
            winner = winners[0]
            win_wall = self._wall_for_player(winner)
            color = PLAYER_COLORS_RGB[winner]

            if win_wall is not None:
                # Winner's wall flashes their color 5 times!
                for _ in range(5):
                    if self._stop.is_set(): break
                    for led in range(LEDS_PER_CHANNEL):
                        self._svc.set_led(win_wall, led, *color)
                    time.sleep(0.18)
                    self._svc.all_off()
                    time.sleep(0.08)

            self._draw_gameover_leds()
            self._notify("game_over", {
                "draw": False,
                "winner": winner,
                "winner_name": self.player_names[winner],
                "ships_left": self._ships_left_list(),
            })
        else:
            # It's a draw! Flash everything off and on.
            for _ in range(4):
                if self._stop.is_set(): break
                self._svc.all_off()
                time.sleep(0.10)
                self._draw_gameover_leds()
                time.sleep(0.10)

            self._notify("game_over", {
                "draw": True,
                "winner": None,
                "winner_name": None,
                "ships_left": self._ships_left_list(),
            })

    # ── The Main Engine Loop ─────────────────────────────────────────────────
    def _loop(self):
        """This runs constantly in the background, keeping the game alive."""
        self._notify("placement_started", {
            "names": list(self.player_names[:self.num_players]),
            "ships_per_player": SHIPS_PER_PLAYER,
        })

        # 1. Wait until everyone has hidden their 3 ships
        while not self._stop.is_set() and self.state == S_PLACEMENT:
            self._draw_placement_leds()
            if self._all_ready():
                break
            time.sleep(0.03)

        if self._stop.is_set(): return

        # 2. START BATTLE!
        self.state = S_ACTIVE
        self._update_alive_flags()
        self._draw_battle_leds()

        self._notify("battle_started", {
            "ships_left": self._ships_left_list(),
        })

        # 3. Keep doing rounds until only 1 person is left alive
        while not self._stop.is_set() and self.state == S_ACTIVE:
            alive = self._alive_players()
            if len(alive) <= 1:
                break # Only 1 (or 0) players left! Game over!

            self._stop_feedback_thread()
            self._begin_round() # Start a new timer!

            next_tick = time.perf_counter()

            # Wait for the timer to hit zero
            while not self._stop.is_set():
                now = time.perf_counter()
                round_left = max(0.0, self.round_deadline - now)

                # PANIC MODE! If less than 3 seconds left, make the giant EYE blink!
                if round_left < 3.0:
                    phase = int(now * 8) % 2 # Blinks fast

                    for p in range(self.num_players):
                        wall = self._wall_for_player(p)
                        if wall is None: continue
                        # Blink their eye color on and off
                        col = self._life_eye_color(p) if phase == 0 else OFF
                        self._svc.set_led(wall, EYE_LED, *col)

                    # Redraw the targeting missiles
                    for p in range(self.num_players):
                        if not self.alive[p]: continue
                        tile = self.selected_tile[p]
                        wall = self._wall_for_player(p)
                        cycle = self.target_cycle[p]
                        if tile is None or wall is None or not cycle: continue
                        target = cycle[self.target_index[p]]
                        self._svc.set_led(wall, tile, *(WHITE if target is None else PLAYER_COLORS_RGB[target]))
                else:
                    self._draw_battle_leds()

                # Tell the computer screen how much time is left
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
                                if self.alive[p] and self.target_cycle[p] and self.target_cycle[p][self.target_index[p]] is not None
                                else "NOTHING" if self.alive[p] and self.selected_tile[p] is not None else None
                            )
                        }
                        for p in range(self.num_players)
                    ]
                })

                # Did the timer hit zero?
                if round_left <= 0:
                    break

                # Sleep a tiny bit to not explode the computer processor
                next_tick += TICK_RATE
                sleep_time = next_tick - time.perf_counter()
                if sleep_time > 0:
                    time.sleep(sleep_time)
                else:
                    next_tick = time.perf_counter()

            if self._stop.is_set(): return

            self._draw_battle_leds()

            # 4. TIMER IS ZERO! Collect all missiles and blow things up!
            attacks = self._collect_round_attacks()
            results, eliminated_now = self._resolve_round_simultaneous(attacks)

            # Play the visual light explosions on the walls
            self._start_feedback_thread(results, eliminated_now)

            # Tell the computer screen who hit who
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

            # Did the game end?
            alive = self._alive_players()
            if len(alive) <= 1:
                break

        # 5. Handle the winner!
        self._stop_feedback_thread()
        alive = self._alive_players()
        if not self._stop.is_set():
            if len(alive) == 1:
                self._do_game_over(alive)
            elif len(alive) == 0:
                self._do_game_over([]) # Draw (Everyone died)


# ==============================================================================
# --- THE COMPUTER WINDOW (BattleShipsApp) ---
# This builds the actual app you click on. It has a Setup Screen to type names,
# and a Game Screen to watch the battle unfold.
# ==============================================================================
class BattleShipsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BattleShips – Evil Eye")
        self.configure(bg=BG_DARK)
        self.minsize(960, 700)

        # F11 makes it full screen, ESC makes it normal size
        self.bind("<F11>", lambda e: self.attributes("-fullscreen", not self.attributes("-fullscreen")))
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        # ── Start the Radio (Service) ──
        self._cfg = load_config()
        self._service = LightService()
        self._service.on_status = lambda m: self.after(0, lambda msg=m: self._set_status(msg))

        ip = self._cfg.get("device_ip", "127.0.0.1") or "127.0.0.1"
        self._service.set_device(ip, self._cfg.get("udp_port", 4626))
        self._service.set_recv_port(self._cfg.get("receiver_port", 7800))
        self._service.set_poll_rate(self._cfg.get("polling_rate_ms", 100))
        self._service.start_receiver()
        self._service.start_polling()

        # ── Give the Radio to the Game Brain ──
        self._game = BattleShipsGame(self._service, self._on_game_event)
        self._service.on_button_state = self._game.handle_button

        # ── Variables for the setup menu ──
        self._v_players = tk.IntVar(value=2)
        self._v_player_names = [tk.StringVar(value=PLAYER_NAMES_DEFAULT[i]) for i in range(MAX_PLAYERS)]
        self._v_device_ip = tk.StringVar(value=ip)
        self._v_use_discovery = tk.BooleanVar(value=True)

        # ── Build the screens ──
        self._frame_setup = tk.Frame(self, bg=BG_DARK)
        self._frame_game  = tk.Frame(self, bg=BG_DARK)
        for frm in (self._frame_setup, self._frame_game):
            frm.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._build_setup_screen()
        self._build_game_screen()
        self._show_setup() # Start by looking at the setup screen

    # ── Flipping between screens ──
    def _show_setup(self):
        self._frame_setup.lift()

    def _show_game(self):
        self._frame_game.lift()

    # -------------------------------------------------------------------------
    # Building the SETUP Screen (Where you type names and press START)
    # -------------------------------------------------------------------------
    def _build_setup_screen(self):
        f = self._frame_setup

        self._status_lbl = tk.Label(f, text="Ready", bg=BG_DARK, fg=FG_DIM, font=FONT_XS)
        self._status_lbl.pack(side=tk.BOTTOM, pady=(0, 8))

        _make_lbl_btn(
            f, "▶   START GAME", self._start_game,
            bg="#ff3c00", fg="white",
            font=("Consolas", 20, "bold"),
            padx=50, pady=18,
            hover_bg="#cc3000"
        ).pack(side=tk.BOTTOM, pady=(6, 6))

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

        for i in range(MAX_PLAYERS):
            col = PLAYER_HEX[i]
            tk.Label(names_frame, text=f"{chr(65+i)}:", bg=BG_DARK, fg=col,
                     font=FONT_SM).grid(
                row=i // 2, column=(i % 2) * 2,
                padx=(10, 4), pady=4, sticky="e"
            )

            e = tk.Entry(names_frame, textvariable=self._v_player_names[i],
                         width=12, bg=BG_PANEL, fg=FG_MAIN,
                         font=("Consolas", 13), insertbackground="white",
                         relief="flat", highlightthickness=1,
                         highlightbackground=col, highlightcolor=col)
            e.grid(row=i // 2, column=(i % 2) * 2 + 1, padx=(0, 20), pady=4)

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
        ip_row.grid(row=row, column=0, columnspan=2, pady=(0, 8)); row += 1

        tk.Entry(ip_row, textvariable=self._v_device_ip,
                 width=20, bg=BG_PANEL, fg=FG_MAIN,
                 font=("Consolas", 13), insertbackground="white",
                 relief="flat", highlightthickness=1,
                 highlightbackground="#444").pack(side=tk.LEFT, padx=6)

        _make_lbl_btn(ip_row, "APPLY", self._apply_ip,
                      bg="#444", padx=12, pady=5,
                      font=FONT_XS, hover_bg="#666").pack(side=tk.LEFT, padx=4)

        tk.Checkbutton(
            content,
            text="Use network discovery before starting",
            variable=self._v_use_discovery,
            bg=BG_DARK,
            fg=FG_MAIN,
            activebackground=BG_DARK,
            activeforeground=FG_MAIN,
            selectcolor=BG_PANEL,
            font=("Consolas", 10)
        ).grid(row=row, column=0, columnspan=2, pady=(0, 14)); row += 1

    def _setup_lbl(self, parent, text, row):
        tk.Label(parent, text=text, bg=BG_DARK, fg=FG_DIM,
                 font=("Consolas", 9, "bold")).grid(
            row=row, column=0, columnspan=2, pady=(6, 2)
        )

    def _refresh_wall_info(self, *_):
        n = self._v_players.get()
        mapping = PLAYER_WALLS.get(n, {})
        parts = []
        for p, wall in sorted(mapping.items()):
            parts.append(f"{PLAYER_NAMES_DEFAULT[p][:8]}→Wall{wall}")
        self._lbl_wall_info.configure(text="  |  ".join(parts))

    # -------------------------------------------------------------------------
    # Building the GAME Screen (Where you watch the battle happening)
    # -------------------------------------------------------------------------
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
            pf = tk.Frame(self._score_bar, bg=BG_PANEL, padx=16, pady=6, highlightthickness=0)
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

        # This draws the shrinking progress bar at the bottom
        self._turn_bar = tk.Canvas(f, bg=BG_PANEL, height=10, highlightthickness=0)
        self._turn_bar.pack(fill=tk.X, padx=60, pady=(0, 12))
        self._turn_bar_max = ROUND_MAX_SECONDS

    # ── Discovery UI (Pop-up asking you to choose Wi-Fi network) ────────────
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
            text="Select the network for the receiver device",
            bg=BG_DARK,
            fg=FG_MAIN,
            font=("Consolas", 12, "bold")
        ).pack(padx=20, pady=(16, 10))

        selected = tk.IntVar(value=0)

        box = tk.Frame(win, bg=BG_DARK)
        box.pack(padx=20, pady=(0, 12), fill=tk.BOTH, expand=True)

        for i, (iface, ip, _bcast) in enumerate(interfaces):
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
            iface, ip, bcast = item
            if ip == "169.254.182.44":
                preferred = item
                break

        selected = preferred or self._choose_interface_dialog(interfaces)
        if not selected:
            self._set_status("Network selection canceled.")
            return None

        iface_name, bind_ip, bcast_ip = selected
        self._set_status(f"Scanning on {iface_name} ({bind_ip})...")

        try:
            devices = discover_devices_on_interface(bind_ip, bcast_ip, timeout_s=3.0)
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

    # ── Updating Text on Screen ──────────────────────────────────────────────
    def _update_scores(self, ships_left, num_players):
        """Updates the top bar with how many ships everyone has left."""
        for i, (pf, nl, sl) in enumerate(self._score_panels):
            pf.pack_forget()

        for i in range(num_players):
            pf, nl, sl = self._score_panels[i]
            nl.configure(text=self._game.player_names[i], fg=PLAYER_HEX[i])
            sl.configure(text=f"{ships_left[i]} ship{'s' if ships_left[i] != 1 else ''}")

            is_alive = ships_left[i] > 0
            pf.configure(
                bg=BG_PANEL,
                highlightbackground=("#333" if is_alive else "#660000"), # Turn red if dead
                highlightthickness=1,
                highlightcolor="#333",
            )
            pf.pack(side=tk.LEFT, padx=6, pady=6, expand=True)

    def _update_turn_bar(self, left_s, max_s):
        """Draws the shrinking timer bar at the bottom."""
        pct = 0 if max_s <= 0 else max(0.0, min(1.0, left_s / max_s))
        w = self._turn_bar.winfo_width() or 600
        self._turn_bar.delete("all")
        self._turn_bar.create_rectangle(0, 0, w, 10, fill=BG_PANEL, outline="")
        bw = int(w * pct)
        if bw > 0:
            col = FG_GREEN if pct > 0.5 else (FG_GOLD if pct > 0.25 else FG_RED)
            self._turn_bar.create_rectangle(0, 0, bw, 10, fill=col, outline="")

    # This catches the messages from the Game Brain and changes the text on screen
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

    # ── Clicking buttons on the Computer Screen ──────────────────────────────
    def _apply_ip(self):
        ip = self._v_device_ip.get().strip() or "127.0.0.1"
        self._service.set_device(ip, self._cfg.get("udp_port", 4626))
        self._cfg["device_ip"] = ip
        save_config(self._cfg)
        self._set_status(f"Device → {ip}")

    def _start_game(self):
        if self._v_use_discovery.get():
            discovered_ip = self._run_discovery_flow_gui()
            if discovered_ip:
                self._v_device_ip.set(discovered_ip)

        self._apply_ip()

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


# ==============================================================================
# Make the App open when we double-click the file!
# ==============================================================================
if __name__ == "__main__":
    BattleShipsApp().mainloop()