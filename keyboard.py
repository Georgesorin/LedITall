import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except Exception:
    HAS_PYAUTOGUI = False


class TouchKeyboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Tastatură virtuală touch")
        self.root.geometry("1100x420")
        self.root.minsize(950, 360)
        self.root.attributes("-topmost", True)

        self.shift = False
        self.caps = False

        self.text_var = tk.StringVar()

        self.build_ui()
        self.refresh_keys()

    def build_ui(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        ttk.Label(
            top,
            text="Text de trimis",
            font=("Segoe UI", 12, "bold")
        ).pack(anchor="w")

        entry_frame = ttk.Frame(top)
        entry_frame.pack(fill="x", pady=(6, 8))

        self.entry = ttk.Entry(
            entry_frame,
            textvariable=self.text_var,
            font=("Segoe UI", 16)
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8), ipady=10)

        self.status = ttk.Label(
            top,
            text=self.status_text(),
            foreground="#333333"
        )
        self.status.pack(anchor="w", pady=(0, 8))

        action_bar = ttk.Frame(top)
        action_bar.pack(fill="x", pady=(0, 8))

        ttk.Button(action_bar, text="Space", command=lambda: self.insert_text(" ")).pack(side="left", padx=3)
        ttk.Button(action_bar, text="Backspace", command=self.backspace).pack(side="left", padx=3)
        ttk.Button(action_bar, text="Clear", command=self.clear_text).pack(side="left", padx=3)
        ttk.Button(action_bar, text="Copy", command=self.copy_text).pack(side="left", padx=3)
        ttk.Button(action_bar, text="Paste", command=self.paste_text).pack(side="left", padx=3)
        ttk.Button(action_bar, text="Enter", command=lambda: self.insert_text("\n")).pack(side="left", padx=3)
        ttk.Button(action_bar, text="Tab", command=lambda: self.insert_text("\t")).pack(side="left", padx=3)

        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=10, pady=4)

        self.keys_frame = ttk.Frame(self.root, padding=10)
        self.keys_frame.pack(fill="both", expand=True)

        self.key_rows = [
            list("1234567890"),
            list("qwertyuiop"),
            list("asdfghjkl"),
            list("zxcvbnm"),
        ]

        self.row_frames = []
        for _ in range(4):
            rf = ttk.Frame(self.keys_frame)
            rf.pack(fill="x", pady=3)
            self.row_frames.append(rf)

        self.specials = ttk.Frame(self.keys_frame)
        self.specials.pack(fill="x", pady=6)

        self.bottom = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        self.bottom.pack(fill="x")

        self.type_btn = ttk.Button(self.bottom, text="Scrie în aplicația aleasă (3 sec)", command=self.type_into_other_app)
        self.type_btn.pack(side="left", padx=4)

        self.copy_btn = ttk.Button(self.bottom, text="Copiază textul", command=self.copy_text)
        self.copy_btn.pack(side="left", padx=4)

        self.info_btn = ttk.Button(self.bottom, text="Instrucțiuni", command=self.show_help)
        self.info_btn.pack(side="right", padx=4)

        self.key_buttons = []

    def status_text(self):
        mode = []
        mode.append("CAPS ON" if self.caps else "caps off")
        mode.append("SHIFT ON" if self.shift else "shift off")
        mode.append("PyAutoGUI activ" if HAS_PYAUTOGUI else "PyAutoGUI indisponibil")
        return " | ".join(mode)

    def refresh_keys(self):
        for rf in self.row_frames:
            for child in rf.winfo_children():
                child.destroy()
        for child in self.specials.winfo_children():
            child.destroy()

        self.key_buttons.clear()

        for idx, row in enumerate(self.key_rows):
            for ch in row:
                display = self.transform_char(ch)
                btn = tk.Button(
                    self.row_frames[idx],
                    text=display,
                    width=5,
                    height=2,
                    font=("Segoe UI", 16),
                    command=lambda value=display: self.insert_text(value),
                    takefocus=0
                )
                btn.pack(side="left", padx=3, pady=2, expand=True, fill="x")
                self.key_buttons.append(btn)

        tk.Button(
            self.specials,
            text="Shift",
            width=8,
            height=2,
            font=("Segoe UI", 14, "bold"),
            command=self.toggle_shift,
            takefocus=0
        ).pack(side="left", padx=3, fill="x", expand=True)

        tk.Button(
            self.specials,
            text="Caps",
            width=8,
            height=2,
            font=("Segoe UI", 14, "bold"),
            command=self.toggle_caps,
            takefocus=0
        ).pack(side="left", padx=3, fill="x", expand=True)

        for ch in [",", ".", "-", "_", "@", ":", ";", "/", "\\", "?", "!", "(", ")"]:
            tk.Button(
                self.specials,
                text=ch,
                width=4,
                height=2,
                font=("Segoe UI", 14),
                command=lambda value=ch: self.insert_text(value),
                takefocus=0
            ).pack(side="left", padx=2)

        self.status.config(text=self.status_text())

    def transform_char(self, ch):
        if self.shift ^ self.caps:
            return ch.upper()
        return ch.lower()

    def toggle_shift(self):
        self.shift = not self.shift
        self.refresh_keys()

    def toggle_caps(self):
        self.caps = not self.caps
        self.refresh_keys()

    def insert_text(self, txt):
        self.entry.insert("insert", txt)
        if self.shift:
            self.shift = False
            self.refresh_keys()

    def backspace(self):
        current = self.entry.get()
        pos = self.entry.index("insert")
        if pos > 0:
            new_text = current[:pos-1] + current[pos:]
            self.text_var.set(new_text)
            self.entry.icursor(pos - 1)

    def clear_text(self):
        self.text_var.set("")

    def copy_text(self):
        text = self.entry.get()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
        messagebox.showinfo("Copiat", "Textul a fost copiat în clipboard.")

    def paste_text(self):
        try:
            text = self.root.clipboard_get()
            self.insert_text(text)
        except Exception:
            messagebox.showwarning("Clipboard", "Nu există text valid în clipboard.")

    def show_help(self):
        msg = (
            "Cum o folosești:\n\n"
            "1. Scrii textul din butoane.\n"
            "2. Apeși «Scrie în aplicația aleasă (3 sec)».\n"
            "3. Ai 3 secunde să atingi câmpul unde vrei să se scrie.\n"
            "4. Scriptul tastează automat textul.\n\n"
            "Dacă PyAutoGUI nu este instalat, folosește butonul «Copiază textul» "
            "și apoi lipește manual cu clipboard."
        )
        messagebox.showinfo("Instrucțiuni", msg)

    def type_into_other_app(self):
        text = self.entry.get()
        if not text:
            messagebox.showwarning("Gol", "Nu există text de trimis.")
            return

        if not HAS_PYAUTOGUI:
            self.copy_text()
            messagebox.showwarning(
                "PyAutoGUI lipsă",
                "PyAutoGUI nu este instalat.\n\n"
                "Ți-am copiat textul în clipboard. Îl poți lipi manual."
            )
            return

        self.type_btn.config(state="disabled", text="Mută-te pe câmpul dorit...")
        threading.Thread(target=self._delayed_type, args=(text,), daemon=True).start()

    def _delayed_type(self, text):
        try:
            for remaining in [3, 2, 1]:
                self.root.after(0, lambda r=remaining: self.type_btn.config(text=f"Scriu în {r}..."))
                time.sleep(1)
            pyautogui.write(text, interval=0.02)
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Eroare", f"Nu am putut trimite textul:\n{e}"))
        finally:
            self.root.after(0, lambda: self.type_btn.config(state="normal", text="Scrie în aplicația aleasă (3 sec)"))


def main():
    root = tk.Tk()
    try:
        from tkinter import TclError
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass

    app = TouchKeyboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
