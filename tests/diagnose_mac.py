"""Prints widget state and saves screenshots to find macOS drawing problems (run by CI).

python tests/diagnose_mac.py <folder>
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from tkinter import ttk
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import desktop
import keys

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
MODELS = {"codex": {f"codex/gpt-{n}": ("codex", f"gpt-{n}", f"GPT {n}") for n in range(3)},
          "claude": {"claude/opus": ("claude", "opus", "Opus")}}
folder = Path(tempfile.mkdtemp())


def make(tour):
    flag = folder / ("tour-" + str(time.time()))
    if not tour:
        flag.touch()
    patches = [mock.patch.object(desktop, "SETTINGS", folder / "settings.json"),
               mock.patch.object(desktop, "TOUR_FLAG", flag),
               mock.patch.object(desktop, "discover", lambda p: ("x · models reported by CLI", MODELS[p]))]
    for patch in patches:
        patch.start()
    root = desktop.make_root()
    root.geometry("+30+40")
    return root, desktop.Desktop(root, keys.KeyStore(folder / "keys.json"))


def settle(root, seconds=1.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(0.01)


def shot(root, name):
    settle(root, 0.6)
    subprocess.run(["screencapture", "-x", str(OUT / f"{name}.png")], check=False)


def tree(widget, depth=0, limit=3):
    line = f"{'  ' * depth}{widget.winfo_class()} {widget.winfo_manager() or '-'} mapped={widget.winfo_ismapped()} " \
           f"{widget.winfo_width()}x{widget.winfo_height()}+{widget.winfo_x()}+{widget.winfo_y()}"
    print(line)
    if depth < limit:
        for child in widget.winfo_children():
            tree(child, depth + 1, limit)


print("Tk", tk.Tcl().call("info", "patchlevel"), "theme", flush=True)

# 1. Models page, no tour.
root, app = make(False)
settle(root, 1.5)
app.navigate("Models")
shot(root, "models-a-asis")
print("--- models page tree")
tree(app.pages["Models"], limit=4)
print("tree rows", len(app.model_tree.get_children()), "theme", ttk.Style(root).theme_use())
root.destroy()

# 2. Models page with the default Treeview layout.
root, app = make(False)
settle(root, 1.5)
ttk.Style(root).layout("Treeview", ttk.Style(root).layout("Treeview"))
ttk.Style(root).layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
app.navigate("Models")
app.model_tree.configure(show="headings")
shot(root, "models-b-headings-only")
root.destroy()

root, app = make(False)
settle(root, 1.5)
style = ttk.Style(root)
style.theme_use("default")
app.navigate("Models")
shot(root, "models-c-default-theme")
root.destroy()

# 3. Tour: separate shade windows versus none.
for mode in ("window", "off"):
    desktop.SHADE_MODE = mode
    root, app = make(True)
    settle(root, 1.5)
    app.tour_window.event_generate("<Right>")

    def press(widget):
        for child in widget.winfo_children():
            if isinstance(child, desktop.Button) and child.text == "Next":
                return child
            found = press(child)
            if found:
                return found

    press(app.tour_window).invoke()
    settle(root, 0.5)
    shot(root, f"tour-shade-{mode}")
    print(f"--- tour {mode}: toplevels",
          [(w.winfo_geometry(), w.overrideredirect()) for w in root.winfo_children() if isinstance(w, tk.Toplevel)])
    root.destroy()
print("done", flush=True)
