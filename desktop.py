"""Model Bridge desktop application."""

import ctypes
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from bridge import HTTPServer, Handler, QUIET_PROCESS, ask, executable_for, subscription_environment
from keys import KeyStore
from providers import discover

BG, PANEL, SIDEBAR = "#0d1422", "#151f31", "#101929"
TEXT, MUTED, BORDER = "#f3f6ff", "#a5b3cb", "#2a3a54"
MINT, BLUE, DANGER = "#83efc8", "#9ab0ff", "#ff9db1"
FONT = "Segoe UI"
ICON = Path(__file__).resolve().parent / "assets" / "model-bridge.ico"
PROVIDERS = {
    "codex": ("ChatGPT", "GPT", "https://learn.chatgpt.com/docs/auth"),
    "claude": ("Claude", "CL", "https://code.claude.com/docs/en/setup"),
}


class Button(tk.Label):
    """A keyboard-operable button with a short hover transition."""

    def __init__(self, parent, title, command, primary=False, nav=False):
        self.normal = MINT if primary else (SIDEBAR if nav else "#22324b")
        self.hover = "#b4ffe6" if primary else "#334974"
        self.command = command
        self.enabled = True
        self.active = False
        self.transition = 0
        super().__init__(parent, text=title, bg=self.normal, fg=BG if primary else TEXT,
                         font=(FONT, 10, "bold"), padx=13, pady=8, cursor="hand2",
                         takefocus=True, anchor="w" if nav else "center",
                         highlightthickness=1, highlightbackground=self.normal,
                         highlightcolor=BLUE)
        self.bind("<Enter>", lambda _: self.animate(self.hover) if self.enabled else None)
        self.bind("<Leave>", lambda _: self.animate(self.base()))
        for event in ("<Button-1>", "<Return>", "<space>"):
            self.bind(event, self.invoke)

    def base(self):
        return "#283c5f" if self.active else self.normal

    def invoke(self, _=None):
        if self.enabled:
            self.command()

    def state(self, enabled):
        self.enabled = bool(enabled)
        self.configure(cursor="hand2" if self.enabled else "arrow",
                       fg=(BG if self.normal == MINT else TEXT) if self.enabled else "#7986a0",
                       takefocus=self.enabled)
        self.transition += 1
        self.configure(bg=self.base())

    def animate(self, target):
        self.transition += 1
        generation = self.transition
        start = self.winfo_rgb(self.cget("bg"))
        end = self.winfo_rgb(target)

        def step(index):
            if generation != self.transition:
                return
            color = "#" + "".join(f"{int((a + (b-a) * index / 6) / 257):02x}"
                                  for a, b in zip(start, end))
            self.configure(bg=color)
            if index < 6:
                self.after(17, step, index + 1)

        step(1)


def label(parent, value="", size=11, color=TEXT, bold=False, **options):
    return tk.Label(parent, text=value, font=(FONT, size, "bold" if bold else "normal"),
                    bg=parent.cget("bg"), fg=color, anchor="w", **options)


def card(parent, padding=18):
    outer = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
    content = tk.Frame(outer, bg=PANEL, padx=padding, pady=padding)
    content.pack(fill="both", expand=True)
    return outer, content


class Desktop:
    def __init__(self, root, store=None):
        self.root = root
        self.store = store if store is not None else KeyStore()
        self.events = queue.Queue()
        self.models = {}
        self.results = {}
        self.account = {}
        self.server = None
        self.stopping = False
        self.pending = 0
        self.testing = False
        self.sign_in = None
        self.dialog = None
        self.toast_job = None
        root.title("Model Bridge")
        root.geometry("1080x690")
        root.minsize(940, 620)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        if ICON.is_file():
            root.iconbitmap(default=str(ICON))
        if os.name == "nt":
            try:
                enabled = ctypes.c_int(1)
                get_parent = ctypes.windll.user32.GetParent
                get_parent.argtypes = (ctypes.c_void_p,)
                get_parent.restype = ctypes.c_void_p
                hwnd = get_parent(root.winfo_id()) or root.winfo_id()
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd), 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
            except OSError:
                pass
        self.setup_style()
        self.build_shell()
        self.build_overview()
        self.build_models()
        self.build_keys()
        self.render_keys()
        self.navigate("Overview")
        self.refresh()
        root.after(60, self.poll)

    def setup_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        rowheight=36, font=(FONT, 10), relief="flat", borderwidth=0)
        style.configure("Treeview.Heading", background="#202e46", foreground=MUTED,
                        font=(FONT, 10, "bold"), padding=(8, 8), relief="flat")
        style.map("Treeview", background=[("selected", "#314a73")], foreground=[("selected", TEXT)])
        style.map("Treeview.Heading", background=[("active", "#263853")])
        style.configure("Vertical.TScrollbar", background=BORDER, troughcolor=PANEL,
                        bordercolor=PANEL, arrowcolor=MUTED)
        style.configure("Horizontal.TProgressbar", background=MINT, troughcolor=BORDER,
                        bordercolor=BORDER, lightcolor=MINT, darkcolor=MINT)

    def build_shell(self):
        rail = tk.Frame(self.root, bg=SIDEBAR, padx=16, pady=22, width=202)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        brand = tk.Frame(rail, bg=SIDEBAR)
        brand.pack(fill="x", pady=(0, 30))
        glyph = tk.Canvas(brand, width=34, height=34, bg=SIDEBAR, highlightthickness=0)
        glyph.pack(side="left", padx=(2, 8))
        glyph.create_line(5, 25, 5, 16, 11, 10, 23, 10, 29, 16, 29, 25, fill=MINT, width=4)
        glyph.create_line(5, 21, 29, 21, fill=BLUE, width=3)
        label(brand, "Model Bridge", 14, bold=True).pack(side="left")
        self.nav = {}
        for name in ("Overview", "Models", "API keys"):
            button = Button(rail, name, lambda name=name: self.navigate(name), nav=True)
            button.pack(fill="x", pady=3)
            self.nav[name] = button
        status = tk.Frame(rail, bg=SIDEBAR)
        status.pack(side="bottom", fill="x")
        self.dot = tk.Canvas(status, width=15, height=18, bg=SIDEBAR, highlightthickness=0)
        self.dot.pack(side="left")
        self.dot_shape = self.dot.create_oval(3, 5, 11, 13, fill=MUTED, outline="")
        self.rail_status = label(status, "API stopped", 10, MUTED)
        self.rail_status.pack(side="left")

        main = tk.Frame(self.root, bg=BG, padx=28, pady=20)
        main.pack(side="left", fill="both", expand=True)
        self.toast = label(main, "", 10, MUTED, wraplength=680, justify="left")
        self.toast.pack(side="bottom", fill="x", pady=(6, 0))
        self.host = tk.Frame(main, bg=BG)
        self.host.pack(fill="both", expand=True)
        self.pages = {}

    def page(self, name, title, description):
        page = tk.Frame(self.host, bg=BG)
        self.pages[name] = page
        label(page, title, 27, bold=True).pack(fill="x")
        label(page, description, 11, MUTED).pack(fill="x", pady=(3, 18))
        return page

    def navigate(self, name):
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        for key, button in self.nav.items():
            button.active = key == name
            button.transition += 1
            button.configure(bg=button.base())

    def build_overview(self):
        page = self.page("Overview", "Overview", "Connect your accounts and start the API on this PC.")
        grid = tk.Frame(page, bg=BG)
        grid.pack(fill="x")
        self.provider_ui = {}
        for column, (provider, (name, initials, _)) in enumerate(PROVIDERS.items()):
            grid.columnconfigure(column, weight=1, uniform="provider")
            outer, inner = card(grid)
            outer.grid(row=0, column=column, sticky="nsew", padx=(0, 7) if column == 0 else (7, 0))
            header = tk.Frame(inner, bg=PANEL)
            header.pack(fill="x")
            badge = tk.Label(header, text=initials, width=4, height=2, bg="#263854",
                             fg=MINT if provider == "codex" else "#ffc1a1", font=(FONT, 9, "bold"))
            badge.pack(side="left", padx=(0, 10))
            label(header, name, 16, bold=True).pack(side="left")
            state = label(inner, "Checking connection…", 11, MUTED,
                          wraplength=245, height=2, justify="left")
            state.pack(fill="x", pady=(8, 10))
            button = Button(inner, "Connect", lambda provider=provider: self.connect(provider))
            button.pack(anchor="w")
            self.provider_ui[provider] = (state, button)
        self.progress = ttk.Progressbar(page, mode="indeterminate")
        self.api_card, inner = card(page)
        self.api_card.pack(fill="x", pady=(14, 0))
        endpoint_header = tk.Frame(inner, bg=PANEL)
        endpoint_header.pack(fill="x")
        label(endpoint_header, "Local API", 17, bold=True).pack(side="left")
        self.toggle_button = Button(endpoint_header, "Start local API", self.toggle, primary=True)
        self.toggle_button.pack(side="right")
        label(inner, "Use this URL in an OpenAI-compatible client.", 10, MUTED).pack(fill="x", pady=(5, 12))
        endpoint = tk.Frame(inner, bg=PANEL)
        endpoint.pack(fill="x")
        self.url = tk.StringVar(value="Start the API to get a base URL")
        self.url_entry = self.entry(endpoint, self.url, read_only=True, mono=True)
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=7)
        self.url_button = Button(endpoint, "Copy URL", lambda: self.copy(self.url.get(), "Base URL copied."))
        self.url_button.pack(side="right", padx=(8, 0))
        Button(inner, "Manage API keys", lambda: self.navigate("API keys")).pack(anchor="w", pady=(12, 0))

    def entry(self, parent, variable, read_only=False, mono=False):
        return tk.Entry(parent, textvariable=variable, state="readonly" if read_only else "normal",
                        font=("Cascadia Mono" if mono else FONT, 10),
                        bg=SIDEBAR, readonlybackground=SIDEBAR, fg=TEXT, insertbackground=TEXT,
                        relief="flat", highlightthickness=1, highlightbackground=BORDER,
                        highlightcolor=BLUE, selectbackground="#314a73")

    def table(self, parent, columns):
        frame, inner = card(parent, padding=1)
        frame.pack(fill="both", expand=True, pady=(8, 0))
        tree = ttk.Treeview(inner, columns=[key for key, _, _ in columns], show="headings",
                            selectmode="browse")
        for key, title, width in columns:
            tree.heading(key, text=title, anchor="w")
            tree.column(key, width=width, minwidth=55, anchor="w")
        tree.tag_configure("alternate", background="#19253a")
        scroll = ttk.Scrollbar(inner, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        return tree

    def build_models(self):
        page = self.page("Models", "Model catalog",
                         "Models reported by the connected CLIs. Test a model to confirm access.")
        bar = tk.Frame(page, bg=BG)
        bar.pack(fill="x")
        label(bar, "Filter", 10, MUTED).pack(side="left", padx=(0, 7))
        self.filter = tk.StringVar()
        self.entry(bar, self.filter).pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 10))
        self.refresh_button = Button(bar, "Refresh models", self.refresh)
        self.refresh_button.pack(side="right")
        self.model_tree = self.table(page, (("label", "Model", 210), ("id", "API model ID", 260),
                                           ("access", "Access", 115)))
        self.model_tree.bind("<<TreeviewSelect>>", lambda _: self.update_buttons())
        self.filter.trace_add("write", lambda *_: self.render_models())
        row = tk.Frame(page, bg=BG)
        row.pack(fill="x", pady=(10, 0))
        self.models_caption = label(row, "Loading model catalog…", 10, MUTED)
        self.models_caption.pack(side="left")
        self.test_button = Button(row, "Test model", self.test_model)
        self.test_button.pack(side="right")
        self.copy_model_button = Button(row, "Copy model ID", lambda: self.copy(
            self.selection(self.model_tree), "Model ID copied."))
        self.copy_model_button.pack(side="right", padx=8)

    def build_keys(self):
        page = self.page("API keys", "API keys",
                         "Create a separate local key for each client. Keys stay active across restarts.")
        bar = tk.Frame(page, bg=BG)
        bar.pack(fill="x")
        self.key_caption = label(bar, "", 11, MUTED)
        self.key_caption.pack(side="left")
        Button(bar, "Create key", self.create_key, primary=True).pack(side="right")
        self.key_tree = self.table(page, (("name", "Name", 250), ("key", "Key ending", 140),
                                         ("created", "Created", 130)))
        self.key_tree.bind("<<TreeviewSelect>>", lambda _: self.update_buttons())
        row = tk.Frame(page, bg=BG)
        row.pack(fill="x", pady=(10, 0))
        label(row, "Full keys are shown once. Save each key when you create it.", 10, MUTED).pack(side="left")
        self.revoke_button = Button(row, "Revoke key", self.revoke_key)
        self.revoke_button.pack(side="right")

    @staticmethod
    def selection(tree):
        selected = tree.selection()
        return selected[0] if selected else ""

    def render_models(self):
        selected = self.selection(self.model_tree)
        self.model_tree.delete(*self.model_tree.get_children())
        needle = self.filter.get().strip().casefold()
        visible = [(model, item) for model, item in self.models.items()
                   if needle in f"{model} {item[2]}".casefold()]
        for index, (model, (_, _, title)) in enumerate(visible):
            self.model_tree.insert("", "end", iid=model,
                values=(title, model, self.results.get(model, "Untested")),
                tags=("alternate",) if index % 2 else ())
        if self.model_tree.exists(selected):
            self.model_tree.selection_set(selected)
        self.models_caption.config(text="Loading model catalog…" if self.pending else
                                   f"{len(visible)} of {len(self.models)} models")
        self.update_buttons()

    def render_keys(self):
        self.key_tree.delete(*self.key_tree.get_children())
        for index, (fingerprint, record) in enumerate(reversed(self.store.keys.items())):
            self.key_tree.insert("", "end", iid=fingerprint,
                values=(record["name"], "••••  " + record["suffix"], record["date"]),
                tags=("alternate",) if index % 2 else ())
        count = len(self.store.keys)
        self.key_caption.config(text=f"{count} active {'key' if count == 1 else 'keys'}")
        self.update_buttons()

    def update_buttons(self):
        self.url_button.state(self.server is not None and not self.stopping)
        self.toggle_button.state(not self.stopping and (self.server or (self.models and not self.pending)))
        self.refresh_button.state(not (self.pending or self.testing or self.sign_in))
        model = self.selection(self.model_tree)
        self.test_button.state(model and not (self.pending or self.testing))
        self.copy_model_button.state(model)
        self.revoke_button.state(self.selection(self.key_tree))
        for _, button in self.provider_ui.values():
            button.state(not self.sign_in)

    def notify(self, text, color=MINT):
        if self.toast_job:
            self.root.after_cancel(self.toast_job)
        self.toast.config(text=text, fg=color)
        self.toast_job = self.root.after(5500, lambda: self.toast.config(text=""))

    def copy(self, value, message):
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.notify(message)

    def modal(self, title, description):
        dialog = tk.Toplevel(self.root, bg=BG)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        body = tk.Frame(dialog, bg=BG, padx=23, pady=20, width=470)
        body.pack(fill="both", expand=True)
        label(body, title, 19, bold=True).pack(fill="x")
        label(body, description, 11, MUTED, wraplength=420, justify="left").pack(fill="x", pady=(6, 14))
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        dialog.update_idletasks()
        dialog.geometry(f"+{self.root.winfo_x()+110}+{self.root.winfo_y()+100}")
        dialog.grab_set()
        dialog.focus_set()
        return dialog, body

    def create_key(self):
        dialog, body = self.modal("Create local API key", "Give this key a name so you can identify the client later.")
        name = tk.StringVar()
        entry = self.entry(body, name)
        entry.pack(fill="x", ipady=7, pady=(0, 11))
        entry.focus_set()

        def create():
            text = name.get().strip()
            if not text or len(text) > 64:
                messagebox.showinfo("Key name", "Enter a name between 1 and 64 characters.", parent=dialog)
                return
            try:
                token = self.store.create(text)
            except OSError as exc:
                messagebox.showerror("Could not save key", str(exc), parent=dialog)
                return
            dialog.destroy()
            self.render_keys()
            reveal, content = self.modal("Your API key is ready",
                "Copy the key now and save it in your client. Model Bridge keeps only a fingerprint.")
            value = tk.StringVar(master=reveal, value=token)
            field = self.entry(content, value, read_only=True, mono=True)
            field.configure(width=50)
            field.pack(fill="x", ipady=7, pady=(0, 12))
            Button(content, "Copy key", lambda: self.copy(token, f"Key for {text} copied."), primary=True).pack(side="left")
            Button(content, "Done", reveal.destroy).pack(side="right")

        entry.bind("<Return>", lambda _: create())
        Button(body, "Create key", create, primary=True).pack(side="right")
        Button(body, "Cancel", dialog.destroy).pack(side="right", padx=8)

    def revoke_key(self):
        digest = self.selection(self.key_tree)
        record = self.store.keys.get(digest)
        if not record or not messagebox.askyesno("Revoke API key",
                f"Revoke “{record['name']}”? Clients using this key will lose access immediately.",
                parent=self.root):
            return
        try:
            self.store.revoke(digest)
        except OSError as exc:
            messagebox.showerror("Could not revoke key", str(exc), parent=self.root)
            return
        self.render_keys()
        self.notify("API key revoked.")

    def connect(self, provider):
        name, _, docs = PROVIDERS[provider]
        executable = executable_for(provider)
        if not executable:
            description = ("Install the native Claude Code CLI, then return here to sign in."
                           if provider == "claude" else "Install the Codex CLI, then return here to sign in.")
            dialog, body = self.modal(f"Set up {name}", description)
            Button(body, "Open setup guide", lambda: webbrowser.open(docs), primary=True).pack(side="left")
            def check():
                dialog.destroy()
                self.connect(provider)
            Button(body, "Check again", check).pack(side="right")
            return
        dialog, body = self.modal(f"Connect {name}", f"Continue to the official {name} sign-in. "
            "A sign-in window will open. Complete the instructions there and return to Model Bridge.")
        message = label(body, "", 10, MUTED, wraplength=420, justify="left")
        message.pack(fill="x", pady=(0, 9))
        self.dialog = dialog

        def begin():
            command = [executable, "login"] if provider == "codex" else [executable, "auth", "login"]
            try:
                self.sign_in = subprocess.Popen(command, env=subscription_environment(),
                    creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0)
            except OSError as exc:
                message.config(text=f"Could not open sign-in. {exc}", fg=DANGER)
                return
            progress.pack(fill="x", pady=(0, 12), before=controls)
            progress.start(12)
            message.config(text=f"Waiting for {name} authorization…")
            start.state(False)
            self.update_buttons()
            process = self.sign_in

            def wait():
                self.events.put(("sign-in", provider, process.wait()))

            threading.Thread(target=wait, daemon=True).start()

        progress = ttk.Progressbar(body, mode="indeterminate")
        controls = tk.Frame(body, bg=BG)
        controls.pack(fill="x")
        start = Button(controls, "Continue to sign-in", begin, primary=True)
        start.pack(side="left")

        def cancel():
            if self.sign_in and self.sign_in.poll() is None:
                self.sign_in.terminate()
            dialog.destroy()

        Button(controls, "Cancel", cancel).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.bind("<Escape>", lambda _: cancel())

    def refresh(self):
        if self.pending:
            return
        self.pending = len(PROVIDERS)
        self.models = {}
        self.results = {}
        self.publish()
        self.progress.pack(fill="x", pady=(10, 0), before=self.api_card)
        self.progress.start(12)
        for provider, (state, _) in self.provider_ui.items():
            state.config(text="Checking connection…", fg=MUTED)

            def load(provider=provider):
                self.events.put(("catalog", provider, discover(provider)))

            threading.Thread(target=load, daemon=True).start()
        self.render_models()

    def publish(self):
        if self.server:
            self.server.models = {name: entry[:2] for name, entry in self.models.items()}

    def poll(self):
        while True:
            try:
                event, identifier, value = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "catalog":
                status, models = value
                self.account[identifier] = status
                state, button = self.provider_ui[identifier]
                state.config(text=status, fg=MINT if models else MUTED)
                button.config(text="Reconnect" if models else ("Set up CLI" if "not found" in status else "Sign in"))
                self.models.update(models)
                self.pending -= 1
                if not self.pending:
                    self.progress.stop()
                    self.progress.pack_forget()
                self.publish()
                self.render_models()
            elif event == "test":
                self.testing = False
                self.results[identifier] = "Verified" if value else "Test failed"
                self.notify(f"{identifier} " + ("responded successfully." if value else "did not complete."),
                            MINT if value else DANGER)
                self.render_models()
            elif event == "stopped":
                self.server = None
                self.stopping = False
                self.update_endpoint()
            else:
                self.sign_in = None
                if self.dialog and self.dialog.winfo_exists():
                    self.dialog.destroy()
                self.dialog = None
                if value:
                    self.notify(f"{PROVIDERS[identifier][0]} sign-in was not completed.", DANGER)
                else:
                    self.notify("Sign-in finished. Checking the account…")
                self.refresh()
            self.update_buttons()
        self.root.after(60, self.poll)

    def test_model(self):
        model = self.selection(self.model_tree)
        provider, model_id, _ = self.models[model]
        self.testing = True
        self.results[model] = "Testing…"
        self.render_models()

        def run():
            try:
                success = bool(ask(provider, "Reply with OK. Do not use tools.", model_id))
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                success = False
            self.events.put(("test", model, success))

        threading.Thread(target=run, daemon=True).start()

    def toggle(self):
        if self.server:
            self.stop()
            return
        if not self.store.keys:
            self.navigate("API keys")
            self.create_key()
            self.notify("Create a key, then start the API from Overview.")
            return
        try:
            try:
                self.server = HTTPServer(("127.0.0.1", 8765), Handler)
            except OSError:
                self.server = HTTPServer(("127.0.0.1", 0), Handler)
        except OSError as exc:
            messagebox.showerror("Cannot start local API", str(exc), parent=self.root)
            return
        self.server.key_check = self.store.contains
        self.publish()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.update_endpoint()

    def stop(self):
        if self.stopping:
            return
        self.stopping = True
        server = self.server
        self.update_endpoint()

        def shutdown():
            server.shutdown()
            server.server_close()
            self.events.put(("stopped", "", None))

        threading.Thread(target=shutdown, daemon=True).start()

    def update_endpoint(self):
        running = self.server and not self.stopping
        self.url.set(f"http://127.0.0.1:{self.server.server_port}/v1" if running
                     else "Start the API to get a base URL")
        self.rail_status.config(text="API running" if running else
                                ("API stopping" if self.stopping else "API stopped"),
                                fg=MINT if running else MUTED)
        self.dot.itemconfig(self.dot_shape, fill=MINT if running else MUTED)
        self.toggle_button.config(text="Stop local API" if running else
                                  ("Stopping…" if self.stopping else "Start local API"))
        self.update_buttons()

    def close(self):
        if self.sign_in and self.sign_in.poll() is None:
            self.sign_in.terminate()
        if self.server:
            self.stop()
        self.root.destroy()


def main():
    mutex = None
    if os.name == "nt":
        ctypes.windll.user32.SetProcessDPIAware()
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ModelBridge.Desktop")
        create_mutex = ctypes.windll.kernel32.CreateMutexW
        create_mutex.restype = ctypes.c_void_p
        create_mutex.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
        mutex = create_mutex(None, False, "Local\\ModelBridge.Desktop")
        already_running = ctypes.windll.kernel32.GetLastError() == 183
        if already_running:
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("Model Bridge", "Model Bridge is already open. Use its taskbar window.")
            root.destroy()
            return
    root = tk.Tk()
    try:
        Desktop(root)
    except (OSError, ValueError) as exc:
        root.withdraw()
        messagebox.showerror("Could not open Model Bridge", f"Could not load local settings.\n{exc}", parent=root)
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
