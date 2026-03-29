import tkinter as tk

def insert_text(char):
    entry.insert("end", char)

def backspace():
    text = entry.get()
    entry.delete(0, "end")
    entry.insert(0, text[:-1])

def clear():
    entry.delete(0, "end")

root = tk.Tk()
root.title("Mini Tastatura")
root.geometry("300x250")
root.attributes("-topmost", True)

entry = tk.Entry(root, font=("Arial", 20), justify="center")
entry.pack(fill="x", padx=10, pady=10, ipady=10)

frame = tk.Frame(root)
frame.pack(expand=True)

# Butoane
btn2 = tk.Button(frame, text="2", font=("Arial", 24), width=5, height=2, command=lambda: insert_text("2"))
btn5 = tk.Button(frame, text="5", font=("Arial", 24), width=5, height=2, command=lambda: insert_text("5"))
btnDot = tk.Button(frame, text=".", font=("Arial", 24), width=5, height=2, command=lambda: insert_text("."))

btn2.grid(row=0, column=0, padx=5, pady=5)
btn5.grid(row=0, column=1, padx=5, pady=5)
btnDot.grid(row=0, column=2, padx=5, pady=5)

# Extra utile
btnBack = tk.Button(root, text="⌫", font=("Arial", 16), command=backspace)
btnClear = tk.Button(root, text="Clear", font=("Arial", 16), command=clear)

btnBack.pack(side="left", expand=True, fill="x", padx=5, pady=5)
btnClear.pack(side="right", expand=True, fill="x", padx=5, pady=5)

root.mainloop()