"""
momeala_coop.py – Co-op Stealth & Greed pentru Evil Eye
Jucătorii se ascund după stâlpul central și farmează puncte.
"""

import os
import sys
import random
import threading
import time
import tkinter as tk

_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from Controller import (
    LightService, load_config, save_config,
    NUM_CHANNELS, LEDS_PER_CHANNEL,
)

# ─────────────────────────────────────────────────────────────────────────────
# Setări Joc
# ─────────────────────────────────────────────────────────────────────────────
GAME_SECONDS = 180  # 3 minute pentru co-op
EYE_LED      = 0
BUTTONS      = list(range(1, 11))
WALLS        = [1, 2, 3, 4] # Presupunem 4 pereți/canale

# Dificultate: Fereastra de timp cât stă ochiul închis (secunde)
SAFE_WINDOWS = {"easy": (4.0, 5.0), "medium": (3.0, 4.0), "hard": (2.0, 3.0)}

# Punctaje
PT_HIGH = 5
PT_LOW  = 1
PENALTY = 5

# Culori
RED    = (255,   0,   0)  # Ochi Deschis (Pericol)
BLUE   = (  0, 100, 255)  # Momeală Valoroasă
GREEN  = (  0, 255,   0)  # Butoane Safe (Ieftine)
YELLOW = (255, 200,   0)  # Ochi care se pregătește să se deschidă
OFF    = (  0,   0,   0)

# Faze Ochi
P_WATCHING = "watching"
P_CLOSED   = "closed"
P_TRAP     = "trap"

# UI
BG_DARK  = "#0f0f0f"
BG_PANEL = "#252525"
BG_MID   = "#1e1e1e"
FG_MAIN  = "#f0f0f0"
FG_DIM   = "#555555"
FONT_SM  = ("Consolas", 12, "bold")
FONT_XS  = ("Consolas", 10)

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

# ─────────────────────────────────────────────────────────────────────────────
# Engine Joc
# ─────────────────────────────────────────────────────────────────────────────
class CoopMomealaGame:
    def __init__(self, service: LightService, on_event):
        self._svc    = service
        self._notify = on_event
        self._lock   = threading.Lock()
        self._stop   = threading.Event()
        self._thr    = None

        self.difficulty = "medium"
        self.score      = 0
        self.game_left  = GAME_SECONDS
        
        # State tracking
        self.active_wall = 1
        self.phase       = P_WATCHING
        self.high_baits  = [] # [(ch, led)] pe active_wall
        self.low_baits   = [] # [(ch, led)] pe pereții inactivi

    def start_game(self, difficulty):
        self.stop_game()
        self.difficulty = difficulty
        self.score      = 0
        self.game_left  = GAME_SECONDS
        self.active_wall = random.choice(WALLS)
        self.phase       = P_WATCHING
        self.high_baits  = []
        self.low_baits   = []

        self._stop.clear()
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def stop_game(self):
        self._stop.set()
        if self._thr and self._thr.is_alive():
            self._thr.join(timeout=2.0)
        self._svc.all_off()

    def handle_button(self, ch, led, is_triggered, is_disconnected):
        if not is_triggered or self.game_left <= 0:
            return
            
        with self._lock:
            # ── 1. VERIFICĂM SENZORUL DE MIȘCARE (OCHIUL) ──
            if led == EYE_LED:
                # Senzorul IR a detectat mișcare!
                if ch == self.active_wall and self.phase in [P_WATCHING, P_TRAP]:
                    # Ochiul este DESCHIS și a văzut mișcare -> Jucătorii au fost prinși!
                    self.score = max(0, self.score - PENALTY)
                    self.high_baits.clear()
                    self._flash_wall(ch, RED)
                    self._notify("caught", {"score": self.score, "wall": ch})
                return # Ieșim, senzorul de mișcare nu dă puncte
            
            # ── 2. VERIFICĂM BUTOANELE DE PUNCTE (LED-urile 1-10) ──
            # Dacă am ajuns aici, cineva a apăsat un buton fizic cu mâna
            
            if ch == self.active_wall:
                if self.phase == P_CLOSED:
                    # Ochiul e închis (SAFE)! Jucătorul a luat momeala?
                    if (ch, led) in self.high_baits:
                        self.score += PT_HIGH
                        self.high_baits.remove((ch, led))
                        self._svc.set_led(ch, led, *GREEN) # Feedback vizual că a luat punctele
                        self._notify("score_high", {"score": self.score})
                
                elif self.phase in [P_WATCHING, P_TRAP]:
                    # Jucătorul a atins un buton în timp ce ochiul era deschis!
                    # (În caz că senzorul IR nu l-a văzut, dar el totuși a apăsat)
                    self.score = max(0, self.score - PENALTY)
                    self.high_baits.clear()
                    self._flash_wall(ch, RED)
                    self._notify("caught", {"score": self.score, "wall": ch})
            
            else:
                # Este pe un perete INACTIV (Farming sigur de la distanță)
                if (ch, led) in self.low_baits:
                    self.score += PT_LOW
                    self.low_baits.remove((ch, led))
                    self._svc.set_led(ch, led, *OFF)
                    self._notify("score_low", {"score": self.score})

    def _flash_wall(self, ch, color):
        for l in range(LEDS_PER_CHANNEL):
            self._svc.set_led(ch, l, *color)

    def _spawn_high_baits(self):
        with self._lock:
            n = random.randint(2, 4)
            leds = random.sample(BUTTONS, n)
            self.high_baits = [(self.active_wall, l) for l in leds]

    def _manage_low_baits(self):
        """Menține 2-4 butoane safe aprinse pe pereții inactivi."""
        with self._lock:
            if len(self.low_baits) < 4 and random.random() < 0.3:
                inactive_walls = [w for w in WALLS if w != self.active_wall]
                if inactive_walls:
                    ch = random.choice(inactive_walls)
                    led = random.choice(BUTTONS)
                    if (ch, led) not in self.low_baits:
                        self.low_baits.append((ch, led))

    def _update_leds(self, pulse_phase):
        with self._lock:
            for w in WALLS:
                if w == self.active_wall:
                    # Peretele Boss-ului
                    if self.phase == P_WATCHING:
                        self._svc.set_led(w, EYE_LED, *RED)
                        c = BLUE if pulse_phase < 0.5 else OFF
                        for (c_bait, l_bait) in self.high_baits:
                            self._svc.set_led(c_bait, l_bait, *c)
                    elif self.phase == P_CLOSED:
                        self._svc.set_led(w, EYE_LED, *OFF)
                        for (c_bait, l_bait) in self.high_baits:
                            self._svc.set_led(c_bait, l_bait, *BLUE)
                    elif self.phase == P_TRAP:
                        self._svc.set_led(w, EYE_LED, *YELLOW) # Se trezește!
                        for (c_bait, l_bait) in self.high_baits:
                            self._svc.set_led(c_bait, l_bait, *OFF)
                else:
                    # Pereții normali - stingem ochiul și curățăm ce nu e buton de farmat
                    self._svc.set_led(w, EYE_LED, *OFF)
            
            # Desenăm butoanele low pe pereții inactivi
            for (c_bait, l_bait) in self.low_baits:
                self._svc.set_led(c_bait, l_bait, *GREEN)

    def _loop(self):
        game_end = time.time() + self.game_left
        self._notify("game_started", {"score": self.score})

        while not self._stop.is_set():
            now = time.time()
            self.game_left = max(0.0, game_end - now)
            if self.game_left <= 0: break

            # ── 1. WATCHING ──
            with self._lock:
                self.phase = P_WATCHING
                self.active_wall = random.choice([w for w in WALLS if w != self.active_wall])
                self.high_baits.clear()
                self._svc.all_off()
            
            self._spawn_high_baits()
            self._notify("phase", {"text": f"👁 Ochiul veghează pe Peretele {self.active_wall}!", "color": "#ff4444"})
            
            watch_time = random.uniform(4.0, 8.0)
            end_watch = time.time() + watch_time
            while time.time() < end_watch and not self._stop.is_set():
                self._manage_low_baits()
                pulse = (time.time() * 4) % 1.0
                self._update_leds(pulse)
                self.game_left = max(0.0, game_end - time.time())
                self._notify("tick", {"game_left": self.game_left})
                time.sleep(0.1)

            if self._stop.is_set() or self.game_left <= 0: break

            # ── 2. CLOSED ──
            with self._lock: self.phase = P_CLOSED
            self._notify("phase", {"text": f"✅ OCHI ÎNCHIS! Fugi la Peretele {self.active_wall} (+5 pct)!", "color": "#00ff88"})
            
            min_s, max_s = SAFE_WINDOWS[self.difficulty]
            safe_time = random.uniform(min_s, max_s)
            end_safe = time.time() + safe_time
            while time.time() < end_safe and not self._stop.is_set():
                self._manage_low_baits()
                self._update_leds(0)
                self.game_left = max(0.0, game_end - time.time())
                self._notify("tick", {"game_left": self.game_left})
                time.sleep(0.05)

            if self._stop.is_set() or self.game_left <= 0: break

            # ── 3. TRAP ──
            with self._lock: self.phase = P_TRAP
            self._notify("phase", {"text": "🚨 SE TREZEȘTE! Înapoi la stâlp!", "color": "#ffd700"})
            
            trap_time = 1.0
            end_trap = time.time() + trap_time
            while time.time() < end_trap and not self._stop.is_set():
                pulse = (time.time() * 15) % 1.0
                self._update_leds(pulse)
                self.game_left = max(0.0, game_end - time.time())
                self._notify("tick", {"game_left": self.game_left})
                time.sleep(0.05)

        # ── Game Over ──
        if not self._stop.is_set():
            self._svc.all_off()
            for _ in range(5):
                if self._stop.is_set(): break
                for w in WALLS:
                    for l in range(LEDS_PER_CHANNEL):
                        self._svc.set_led(w, l, *GREEN)
                time.sleep(0.4)
                self._svc.all_off()
                time.sleep(0.2)
            self._notify("game_over", {"score": self.score})


# ─────────────────────────────────────────────────────────────────────────────
# UI Application
# ─────────────────────────────────────────────────────────────────────────────
class CoopApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Co-op Momeala – Stealth & Greed")
        self.configure(bg=BG_DARK)
        self.minsize(860, 640)
        self.bind("<F11>", lambda e: self.attributes("-fullscreen", not self.attributes("-fullscreen")))
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        # ── Conexiune Rețea (Restaurată la formatul funcțional) ──
        self._cfg = load_config()
        self._service = LightService()
        self._service.on_status = lambda m: self.after(0, lambda msg=m: self._set_status(msg))

        ip = self._cfg.get("device_ip", "127.0.0.1")
        if ip:
            self._service.set_device(ip, self._cfg.get("udp_port", 6967))
        self._service.set_recv_port(self._cfg.get("receiver_port", 5555))
        self._service.set_poll_rate(self._cfg.get("polling_rate_ms", 100))
        self._service.start_receiver()
        self._service.start_polling()

        self._game = CoopMomealaGame(self._service, self._on_game_event)
        self._service.on_button_state = self._game.handle_button

        self._v_diff = tk.StringVar(value="medium")
        self._v_device_ip = tk.StringVar(value=ip or "127.0.0.1")

        # Screens
        self._f_setup = tk.Frame(self, bg=BG_DARK)
        self._f_game  = tk.Frame(self, bg=BG_DARK)
        for f in (self._f_setup, self._f_game):
            f.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._build_setup()
        self._build_game()
        self._f_setup.lift()

    def _build_setup(self):
        f = self._f_setup
        
        self._status_lbl = tk.Label(f, text="Ready", bg=BG_DARK, fg=FG_DIM, font=FONT_XS)
        self._status_lbl.pack(side=tk.BOTTOM, pady=(0, 8))

        _make_lbl_btn(f, "▶   START JOC", self._start, bg="#ff3c00", fg="white",
                      font=("Consolas", 20, "bold"), padx=50, pady=18, hover_bg="#cc3000").pack(side=tk.BOTTOM, pady=(6, 6))

        tk.Label(f, text="CO-OP HEIST", bg=BG_DARK, fg="#00aaff", font=("Consolas", 40, "bold")).pack(pady=(40, 10))
        tk.Label(f, text="Stați după stâlp. Furați punctele când ochiul e închis.", bg=BG_DARK, fg=FG_DIM, font=("Consolas", 12)).pack()
        
        d_frame = tk.Frame(f, bg=BG_DARK)
        d_frame.pack(pady=30)
        tk.Radiobutton(d_frame, text="Ușor (Fereastră 4-5s)", variable=self._v_diff, value="easy", bg=BG_DARK, fg="white", selectcolor=BG_PANEL, font=("Consolas", 14)).pack(anchor="w", pady=5)
        tk.Radiobutton(d_frame, text="Mediu (Fereastră 3-4s)", variable=self._v_diff, value="medium", bg=BG_DARK, fg="white", selectcolor=BG_PANEL, font=("Consolas", 14)).pack(anchor="w", pady=5)
        tk.Radiobutton(d_frame, text="Greu (Fereastră 2-3s)", variable=self._v_diff, value="hard", bg=BG_DARK, fg="white", selectcolor=BG_PANEL, font=("Consolas", 14)).pack(anchor="w", pady=5)

        # Setare IP readusă
        ip_row = tk.Frame(f, bg=BG_DARK)
        ip_row.pack(pady=20)
        tk.Label(ip_row, text="IP Sistem:", bg=BG_DARK, fg=FG_DIM, font=FONT_SM).pack(side=tk.LEFT, padx=6)
        tk.Entry(ip_row, textvariable=self._v_device_ip, width=15, bg=BG_PANEL, fg=FG_MAIN, font=("Consolas", 13), insertbackground="white", relief="flat", highlightthickness=1).pack(side=tk.LEFT, padx=6)
        _make_lbl_btn(ip_row, "APLICĂ", self._apply_ip, bg="#444", padx=12, pady=5, font=FONT_XS, hover_bg="#666").pack(side=tk.LEFT, padx=4)

    def _build_game(self):
        f = self._f_game
        btm = tk.Frame(f, bg=BG_MID, pady=8)
        btm.pack(side=tk.BOTTOM, fill=tk.X)
        _make_lbl_btn(btm, "⚙ Setup", self._stop, bg="#333", padx=14, pady=6, font=FONT_XS, hover_bg="#555").pack(side=tk.LEFT, padx=8)
        self._game_status = tk.Label(btm, text="", bg=BG_MID, fg=FG_DIM, font=FONT_XS)
        self._game_status.pack(side=tk.RIGHT, padx=12)

        top = tk.Frame(f, bg=BG_DARK)
        top.pack(fill=tk.X, pady=20)
        
        self._l_time = tk.Label(top, text="3:00", bg=BG_DARK, fg="white", font=("Consolas", 60, "bold"))
        self._l_time.pack()

        mid = tk.Frame(f, bg=BG_DARK)
        mid.pack(expand=True)
        
        tk.Label(mid, text="SCOR GLOBAL", bg=BG_DARK, fg=FG_DIM, font=("Consolas", 16)).pack()
        self._l_score = tk.Label(mid, text="0", bg=BG_DARK, fg="#00ff88", font=("Consolas", 100, "bold"))
        self._l_score.pack()

        self._l_phase = tk.Label(mid, text="Pregătire...", bg=BG_DARK, fg="white", font=("Consolas", 24, "bold"))
        self._l_phase.pack(pady=20)

        self._l_event = tk.Label(mid, text="", bg=BG_DARK, fg="white", font=("Consolas", 16))
        self._l_event.pack()

    def _apply_ip(self):
        ip = self._v_device_ip.get().strip()
        # Notă: port-ul 4626 era folosit in hot_potato la metoda _apply_ip. 
        self._service.set_device(ip, self._cfg.get("udp_port", 4626))
        self._cfg["device_ip"] = ip
        save_config(self._cfg)
        self._set_status(f"Device → {ip}")

    def _start(self):
        self._apply_ip()
        self._game.start_game(self._v_diff.get())
        self._f_game.lift()

    def _stop(self):
        self._game.stop_game()
        self._f_setup.lift()

    def _set_status(self, msg):
        try:
            self._status_lbl.configure(text=msg)
            self._game_status.configure(text=msg)
        except tk.TclError:
            pass

    def _on_game_event(self, event, data):
        self.after(0, lambda: self._dispatch(event, data))

    def _dispatch(self, ev, d):
        if ev == "game_started":
            self._l_score.configure(text="0", fg="#00ff88")
            self._l_event.configure(text="")
        elif ev == "tick":
            m, s = divmod(int(d["game_left"]), 60)
            self._l_time.configure(text=f"{m}:{s:02d}", fg=("white" if d["game_left"]>30 else "#ff4444"))
        elif ev == "phase":
            self._l_phase.configure(text=d["text"], fg=d["color"])
        elif ev == "caught":
            self._l_score.configure(text=str(d["score"]), fg="#ff4444")
            self._l_event.configure(text=f"❌ PRINS! Ochiul {d['wall']} a văzut mișcare (-{PENALTY})", fg="#ff4444")
        elif ev == "score_high":
            self._l_score.configure(text=str(d["score"]), fg="#00ff88")
            self._l_event.configure(text=f"⚡ Momeală mare luată! (+{PT_HIGH})", fg="#00aaff")
        elif ev == "score_low":
            self._l_score.configure(text=str(d["score"]), fg="#00ff88")
            self._l_event.configure(text=f"✅ Buton safe apăsat (+{PT_LOW})", fg="#00ff88")
        elif ev == "game_over":
            self._l_time.configure(text="0:00", fg="#ff4444")
            self._l_phase.configure(text="JOC TERMINAT!", fg="white")
            self._l_event.configure(text=f"Scor final: {d['score']}", fg="#00ff88")

if __name__ == "__main__":
    CoopApp().mainloop()