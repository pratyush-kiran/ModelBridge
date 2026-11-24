"""Runs the app under a normal Tk main loop (as a user would) and screenshots it (run by CI).

python tests/diagnose_mainloop.py <scenario> <folder>
Scenarios: tour, notour, repack, repack-headings, repack-layout, repack-noempty, repack-raise
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


variant = scenario.partition("-")[2]
if variant == "headings":
    app.model_tree.configure(show="headings")
elif variant == "layout":
    from tkinter import ttk
    ttk.Style(root).layout("Treeview", [("Treeview.field", {"sticky": "nswe", "border": "1", "children": [
        ("Treeview.padding", {"sticky": "nswe", "children": [("Treeview.treearea", {"sticky": "nswe"})]})]})])
elif variant == "noempty":
    app.models_empty.destroy()
elif variant == "raise":
    app.host.grid_rowconfigure(0, weight=1)
    app.host.grid_columnconfigure(0, weight=1)
    for page in app.pages.values():
        page.pack_forget()
        page.grid(row=0, column=0, sticky="nsew")

    def navigate(name):
        app.pages[name].tkraise()
        for key, button in app.nav.items():
            button.active = key == name
            button.configure(bg=button.base())
    app.navigate = navigate


steps = [(3000, lambda: shot("a"))]
if scenario.startswith("repack"):
    steps = [(2000, lambda: app.navigate("Models")), (2800, lambda: app.navigate("Overview")),
             (3600, lambda: app.navigate("Models")), (5000, lambda: shot("a"))]
for delay, action in steps:
    root.after(delay, action)
root.after(steps[-1][0] + 800, root.destroy)
root.mainloop()
print(scenario, "done")
