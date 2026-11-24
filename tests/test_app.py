"""Run with: python -m unittest discover -s tests -v

Set MODEL_BRIDGE_SHOTS to a folder to also save screenshots (needs Pillow).
"""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest import mock
from urllib import error, request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if os.name == "nt":
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()

import bridge
import desktop
import keys
import macos
import providers

FAKE_CLI = Path(__file__).with_name("fake_cli.py")
SHOTS = os.environ.get("MODEL_BRIDGE_SHOTS")
POSIX = os.name != "nt"


class Base(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.store = keys.KeyStore(self.folder / "keys.json")
        self.addCleanup(lambda: [self.store.revoke(digest) for digest in list(self.store.keys)])


class KeyTests(Base):
    def test_round_trip_and_revoke(self):
        token = self.store.create("Cursor")
        digest = next(iter(self.store.keys))
        self.assertEqual(self.store.reveal(digest), token)
        self.assertNotIn(token, (self.folder / "keys.json").read_text(encoding="utf-8"))
        self.assertEqual(keys.KeyStore(self.folder / "keys.json").reveal(digest), token)
        self.store.revoke(digest)
        self.assertFalse(self.store.contains(digest))
        if sys.platform == "darwin":
            with self.assertRaises(OSError):
                macos.keychain_read(digest)

    def test_old_keys_still_work(self):
        self.store.commit({"abc": {"name": "Old", "suffix": "abcdef", "date": "1 Jan 2026"}})
        self.assertTrue(self.store.contains("abc"))
        self.assertIsNone(self.store.reveal("abc"))


class PortTests(Base):
    def test_port_is_remembered(self):
        with mock.patch.object(desktop, "SETTINGS", self.folder / "settings.json"):
            self.assertEqual(desktop.load_port(), desktop.DEFAULT_PORT)
            desktop.save_port(8790)
            self.assertEqual(desktop.load_port(), 8790)

    def test_port_is_never_shared(self):
        with bridge.LocalServer(("127.0.0.1", 0), bridge.Handler) as first:
            with self.assertRaises(OSError):
                bridge.LocalServer(("127.0.0.1", first.server_port), bridge.Handler)


class ShadeTests(unittest.TestCase):
    def test_cut_out_covers_everything_but_the_hole(self):
        box, hole = (0, 0, 30, 20), (5, 5, 12, 15)
        pieces = desktop.cut_out(box, hole)
        for x in range(30):
            for y in range(20):
                inside = 5 <= x < 12 and 5 <= y < 15
                hits = sum(p[0] <= x < p[2] and p[1] <= y < p[3] for p in pieces)
                self.assertEqual(hits, 0 if inside else 1)
        self.assertEqual(desktop.cut_out(box, (40, 40, 50, 50)), [box])


@unittest.skipUnless(POSIX, "macOS and Linux only")
class TerminalTests(unittest.TestCase):
    def job(self, command, unset=()):
        job = macos.TerminalJob(command, bridge.search_path(), unset,
                                opener=("/bin/bash", "-c", '"$0" >/dev/null 2>&1 & true'))
        deadline = time.monotonic() + 20
        while job.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        return job.returncode

    def test_exit_codes(self):
        self.assertEqual(self.job("true"), 0)
        self.assertEqual(self.job("exit 7"), 7)
        self.assertEqual(self.job("false | cat"), 1)

    def test_provider_variables_are_removed(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "x"}):
            self.assertEqual(self.job('test -z "$OPENAI_API_KEY"', bridge.PROVIDER_VARIABLES), 0)


@unittest.skipUnless(sys.platform == "darwin", "macOS only")
class RealTerminalTest(unittest.TestCase):
    def test_terminal_app_runs_the_job(self):
        job = macos.TerminalJob("true", bridge.search_path())
        deadline = time.monotonic() + 60
        while job.poll() is None and time.monotonic() < deadline:
            time.sleep(0.3)
        self.assertEqual(job.returncode, 0)


@unittest.skipUnless(POSIX, "the stand-in CLIs are shell scripts")
class CliTests(Base):
    def setUp(self):
        super().setUp()
        # As from Finder: a minimal PATH, with the CLIs only in ~/.local/bin.
        folder = self.folder / ".local" / "bin"
        folder.mkdir(parents=True)
        for name in ("codex", "claude"):
            script = folder / name
            script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_CLI}" {name} "$@"\n')
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
        patch = mock.patch.dict(os.environ, {"HOME": str(self.folder), "PATH": "/usr/bin:/bin"})
        patch.start()
        self.addCleanup(patch.stop)

    def test_catalogs(self):
        status, models = providers.discover("codex")
        self.assertEqual((status, list(models)), ("ChatGPT Plus · 1 models reported by CLI", ["codex/gpt-test"]))
        status, models = providers.discover("claude")
        self.assertEqual((status, list(models)), ("Claude Pro · 1 models reported by CLI", ["claude/opus"]))

    def test_chat_over_http(self):
        token = "mb_test"
        with bridge.LocalServer(("127.0.0.1", 0), bridge.Handler) as server:
            server.token = token
            server.models = {"codex/gpt-test": ("codex", "gpt-test"), "claude/opus": ("claude", "opus")}
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{server.server_port}/v1"
            try:
                with self.assertRaises(error.HTTPError) as caught:
                    request.urlopen(base + "/models", timeout=10)
                self.assertEqual(caught.exception.code, 401)
                for model in server.models:
                    call = request.Request(base + "/chat/completions", json.dumps(
                        {"model": model, "messages": [{"role": "user", "content": "Hi"}]}).encode(),
                        {"Authorization": "Bearer " + token, "Content-Type": "application/json"})
                    reply = json.load(request.urlopen(call, timeout=60))
                    self.assertEqual(reply["choices"][0]["message"]["content"],
                                     f"{model.split('/')[0]} heard: user: Hi")
            finally:
                server.shutdown()


class AppTests(Base):
    def setUp(self):
        super().setUp()
        models = {"codex": {f"codex/gpt-{n}": ("codex", f"gpt-{n}", f"GPT {n}") for n in range(3)},
                  "claude": {"claude/opus": ("claude", "opus", "Opus")}}
        for target, value in (("SETTINGS", self.folder / "settings.json"), ("TOUR_FLAG", self.folder / "tour"),
                              ("discover", lambda provider: (f"{provider} · models reported by CLI", models[provider]))):
            patch = mock.patch.object(desktop, target, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.root = desktop.make_root()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.geometry("+30+40")
        self.app = desktop.Desktop(self.root, self.store)
        self.addCleanup(self.finish)

    def finish(self):
        if self.app.server:
            self.app.server.shutdown()
            self.app.server.server_close()
        self.root.destroy()

    def run_for(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)

    def shot(self, name):
        self.run_for(0.5)
        if not SHOTS:
            return
        for window in [self.root] + [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]:
            window.attributes("-topmost", True)
        self.run_for(0.3)
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        target = str(Path(SHOTS) / f"{name}.png")
        if sys.platform == "darwin":
            subprocess.run(["screencapture", "-x", target], check=False)
        else:
            from PIL import ImageGrab
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            ImageGrab.grab((x, y, x + self.root.winfo_width(), y + self.root.winfo_height())).save(target)

    def test_walk_through(self):
        app = self.app
        self.run_for(1.2)
        self.assertTrue(app.tour_window.winfo_ismapped(), "the tour opens on first launch")

        def button(widget, text):
            for child in widget.winfo_children():
                found = child if isinstance(child, desktop.Button) and child.text == text else button(child, text)
                if found:
                    return found

        for step in range(len(desktop.TOUR)):
            self.shot(f"tour-{step}")
            card = app.tour_window
            self.assertGreaterEqual(card.winfo_x(), 0)
            self.assertLessEqual(card.winfo_x() + card.winfo_width(), self.root.winfo_width())
            self.assertGreaterEqual(card.winfo_y(), 0)
            self.assertLessEqual(card.winfo_y() + card.winfo_height(), self.root.winfo_height())
            button(card, "Get started" if step == len(desktop.TOUR) - 1 else "Next").invoke()
            self.run_for(0.3)
        self.assertFalse(app.tour_window.winfo_exists())
        self.assertTrue(desktop.TOUR_FLAG.exists())
        self.assertFalse([w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)])

        app.navigate("API keys")
        self.shot("keys-empty")
        token = self.store.create("Cursor")
        digest = next(iter(self.store.keys))
        app.render_keys()
        app.view_key(digest)
        app.key_rows.winfo_children()[0].event_generate("<Enter>")
        self.shot("keys")
        app.copy_key(digest)
        self.assertEqual(self.root.clipboard_get(), token)

        app.navigate("Models")
        self.shot("models")
        self.assertEqual(len(app.model_tree.get_children()), 4)
        app.filter.set("nothing")
        self.shot("models-no-match")
        app.filter.set("")

        app.navigate("Overview")
        app.toggle()
        port = app.server.server_port
        self.shot("overview-running")
        call = request.Request(app.url.get() + "/models", headers={"Authorization": "Bearer " + token})
        self.assertEqual(len(json.load(request.urlopen(call, timeout=10))["data"]), 4)
        app.toggle()
        self.run_for(1.5)
        self.assertIsNone(app.server)
        app.toggle()
        self.assertEqual(app.server.server_port, port, "a restart keeps the port")

        app.install("codex")
        self.shot("install-dialog")
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
