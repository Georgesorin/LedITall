import tkinter as tk


class HelperDisplay:
    def __init__(self, game):
        self.game = game
        self.root = tk.Tk()
        self.root.title("Simon Game Helper Display")
        self.root.configure(bg="black")

        # fullscreen; dacă vrei doar fereastră normală, comentezi linia asta
        self.root.state("normal")
        self.root.geometry("1920x1080+1920+0")
        self.root.configure(bg="black")

        # ESC închide doar fereastra helper
        self.root.bind("<Escape>", self.close)

        self.score_var = tk.StringVar(value="0")
        self.time_var = tk.StringVar(value="03:00")
        self.level_var = tk.StringVar(value="1")
        self.state_var = tk.StringVar(value="WAITING")

        container = tk.Frame(self.root, bg="black")
        container.pack(expand=True, fill="both")

        title = tk.Label(
            container,
            text="SIMON GAME",
            font=("Arial", 34, "bold"),
            fg="white",
            bg="black"
        )
        title.pack(pady=(40, 20))

        score_title = tk.Label(
            container,
            text="SCOR",
            font=("Arial", 28, "bold"),
            fg="#00ff88",
            bg="black"
        )
        score_title.pack(pady=(20, 5))

        score_value = tk.Label(
            container,
            textvariable=self.score_var,
            font=("Arial", 72, "bold"),
            fg="#00ff88",
            bg="black"
        )
        score_value.pack(pady=(0, 30))

        time_title = tk.Label(
            container,
            text="TIMP RAMAS",
            font=("Arial", 28, "bold"),
            fg="#ffd400",
            bg="black"
        )
        time_title.pack(pady=(10, 5))

        time_value = tk.Label(
            container,
            textvariable=self.time_var,
            font=("Arial", 64, "bold"),
            fg="#ffd400",
            bg="black"
        )
        time_value.pack(pady=(0, 30))

        level_title = tk.Label(
            container,
            text="NIVEL",
            font=("Arial", 24, "bold"),
            fg="#66ccff",
            bg="black"
        )
        level_title.pack(pady=(10, 5))

        level_value = tk.Label(
            container,
            textvariable=self.level_var,
            font=("Arial", 42, "bold"),
            fg="#66ccff",
            bg="black"
        )
        level_value.pack(pady=(0, 20))

        state_value = tk.Label(
            container,
            textvariable=self.state_var,
            font=("Arial", 22, "bold"),
            fg="#ff6666",
            bg="black"
        )
        state_value.pack(pady=(20, 40))

        self.running = True
        self.update_loop()

    def format_mmss(self, seconds):
        seconds = max(0, int(seconds))
        m = seconds // 60
        s = seconds % 60
        return f"{m:02}:{s:02}"

    def update_loop(self):
        if not self.running:
            return

        try:
            self.score_var.set(str(self.game.score))
            self.time_var.set(self.format_mmss(self.game.get_game_time_left()))
            self.level_var.set(str(max(1, self.game.level)))
            self.state_var.set(self.game.state.upper())
        except Exception:
            pass

        self.root.after(100, self.update_loop)

    def close(self, event=None):
        self.running = False
        try:
            self.root.destroy()
        except:
            pass

    def run(self):
        self.root.mainloop()
