"""Model catalogs reported by the installed provider CLIs."""

from contextlib import contextmanager
import json
import queue
import re
import subprocess
import tempfile
import threading
import time

from bridge import CLAUDE_OPTIONS, QUIET_PROCESS, executable_for, subscription_environment

@contextmanager
def cli_process(command, directory):
    with subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        encoding="utf-8", errors="replace", cwd=directory,
        env=subscription_environment(), creationflags=QUIET_PROCESS,
    ) as process:
        lines = queue.Queue()

        def collect():
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()

        def send(data):
            process.stdin.write(json.dumps(data) + "\n")
            process.stdin.flush()

        def receive(matches):
            deadline = time.monotonic() + 20
            while True:
                try:
                    line = lines.get(timeout=max(0, deadline - time.monotonic()))
                except queue.Empty:
                    raise RuntimeError("The CLI did not respond. Check its sign-in and version.")
                if line is None:
                    raise RuntimeError("The CLI closed before returning its catalog.")
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if isinstance(data, dict) and matches(data):
                    return data

        try:
            yield send, receive
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            reader.join(timeout=1)


def codex_catalog(executable, directory):
    with cli_process([executable, "app-server"], directory) as (send, receive):
        sequence = 0

        def call(method, params):
            nonlocal sequence
            sequence += 1
            send({"id": sequence, "method": method, "params": params})
            reply = receive(lambda item: item.get("id") == sequence)
            if "error" in reply:
                raise RuntimeError(f"Codex could not complete {method}. Update the CLI and retry.")
            return reply["result"]

        call("initialize", {"clientInfo": {"name": "local_model_bridge", "version": "1.0"}})
        send({"method": "initialized"})
        account = call("account/read", {"refreshToken": False}).get("account") or {}
        if account.get("type") != "chatgpt":
            raise RuntimeError("Sign in with ChatGPT using codex login, then refresh.")
        records = []
        params = {"limit": 100, "includeHidden": False}
        while True:
            page = call("model/list", params)
            records.extend((row["model"], row.get("displayName", row["model"]))
                           for row in page["data"] if not row.get("hidden"))
            cursor = page.get("nextCursor")
            if not cursor:
                break
            if params.get("cursor") == cursor:
                raise RuntimeError("Codex returned a repeated catalog page.")
            params["cursor"] = cursor
        plan = str(account.get("planType") or "").replace("_", " ").title()
        return ("ChatGPT " + plan).strip(), records


def claude_catalog(executable, directory):
    status = subprocess.run(
        [executable, "auth", "status", "--json"],
        capture_output=True, encoding="utf-8", errors="replace",
        cwd=directory, env=subscription_environment(), timeout=15,
        creationflags=QUIET_PROCESS,
    )
    account = json.loads(status.stdout)
    if not isinstance(account, dict) or not account.get("loggedIn") or account.get("authMethod") != "claude.ai":
        raise RuntimeError("Sign in with your Claude account using claude auth login, then refresh.")
    command = [executable, "-p", *CLAUDE_OPTIONS, "--input-format", "stream-json",
               "--output-format", "stream-json", "--verbose"]
    with cli_process(command, directory) as (send, receive):
        send({"type": "control_request", "request_id": "catalog",
              "request": {"subtype": "initialize"}})
        message = receive(lambda item: item.get("type") == "control_response"
                          and item.get("response", {}).get("request_id") == "catalog")
        response = message["response"]
        if response["subtype"] != "success":
            raise RuntimeError("Claude Code could not load its model picker.")
        records = [(row["value"], row.get("displayName", row["value"]))
                   for row in response["response"]["models"] if row.get("value")]
    plan = str(account.get("subscriptionType") or "").replace("_", " ").title()
    return ("Claude " + plan).strip(), records


def discover(provider):
    executable = executable_for(provider)
    if not executable:
        label = "Codex" if provider == "codex" else "Claude Code"
        return f"{label} CLI not found. Install it, sign in, then refresh.", {}
    try:
        with tempfile.TemporaryDirectory(prefix="model-catalog-") as directory:
            catalog = codex_catalog if provider == "codex" else claude_catalog
            account, records = catalog(executable, directory)
        models = {
            f"{provider}/{model}": (provider, model, label)
            for model, label in records
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:\[\]-]*", model)
        }
        return f"{account} · {len(models)} models reported by CLI", models
    except RuntimeError as exc:
        return str(exc), {}
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired):
        return f"Could not read the {provider} catalog. Check the CLI version and sign-in.", {}
