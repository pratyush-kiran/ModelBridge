"""Runs the app under a normal Tk main loop (as a user would) and screenshots it (run by CI).

python tests/diagnose_mainloop.py <scenario> <folder>
Scenarios: tour, notour, repack
"""

from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import desktop
import keys
import ui

scenario, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
folder = Path(tempfile.mkdtemp())
models = {"codex": {"codex/gpt-0": ("codex", "gpt-0", "GPT 0")}, "claude": {"claude/opus": ("claude", "opus", "Opus")}}
flag = folder / "tour"
if scenario != "tour":
    flag.touch()
mock.patch.object(desktop, "SETTINGS", folder / "settings.json").start()
mock.patch.object(desktop, "TOUR_FLAG", flag).start()
mock.patch.object(desktop, "discover", lambda p: ("x · models reported by CLI", models[p])).start()
root = desktop.make_root()
app = desktop.Desktop(root, keys.KeyStore(folder / "keys.json"))


def shot(name):
    subprocess.run(["screencapture", "-x", str(out / f"{scenario}-{name}.png")], check=False)


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def remedy():
    for widget in walk(root):
        if isinstance(widget, ui.RoundFrame):
            widget.itemconfigure(widget.window, state="hidden")
            widget.update_idletasks()
            widget.itemconfigure(widget.window, state="normal")


steps = [(3000, lambda: shot("a"))]
if scenario == "repack":
    steps = [(2000, lambda: app.navigate("Models")), (2800, lambda: app.navigate("Overview")),
             (3600, lambda: app.navigate("Models")), (5000, lambda: shot("a")),
             (5300, remedy), (6500, lambda: shot("b"))]
else:
    steps += [(3300, remedy), (4500, lambda: shot("b"))]
for delay, action in steps:
    root.after(delay, action)
root.after(steps[-1][0] + 800, root.destroy)
root.mainloop()
print(scenario, "done")
