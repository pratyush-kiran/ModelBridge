"""Local chat-completions adapter for the Codex and Claude Code CLIs."""

import argparse
import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


def executable_for(model):
    name = model + ".exe" if os.name == "nt" else model
    path = shutil.which(name)
    if not path and os.name == "nt":
        candidates = (
            os.path.expanduser("~/.local/bin/" + name),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                         "OpenAI", "Codex", "bin", name) if model == "codex" else "",
        )
        path = next((path for path in candidates if os.path.isfile(path)), None)
    return path


def subscription_environment():
    env = os.environ.copy()
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY",
                 "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
                 "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
                 "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDECODE"):
        env.pop(name, None)
    return env


QUIET_PROCESS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
CLAUDE_OPTIONS = ["--tools", "", "--setting-sources", "", "--strict-mcp-config",
                  "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
                  "--no-session-persistence"]


def ask(model, prompt, model_id=None):
    executable = executable_for(model)
    if not executable:
        raise RuntimeError(f"Install {model} and make its executable available on PATH.")
    env = subscription_environment()
    selection = ["--model", model_id] if model_id else []
    with tempfile.TemporaryDirectory(prefix="local-ai-bridge-") as directory:
        if model == "codex":
            output = os.path.join(directory, "answer.txt")
            command = [executable, "--ask-for-approval", "never", "exec",
                       "--ephemeral", "--skip-git-repo-check", "--sandbox",
                       "read-only", "--output-last-message", output, *selection, "-"]
        else:
            command = [executable, "-p", *CLAUDE_OPTIONS, *selection,
                       "--output-format", "text"]
        result = subprocess.run(command, input=prompt, capture_output=True,
                                encoding="utf-8", errors="replace",
                                cwd=directory, env=env, timeout=180,
                                creationflags=QUIET_PROCESS)
        if result.returncode:
            raise RuntimeError(f"{model} exited with code {result.returncode}. "
                               f"Check its sign-in and try a prompt in the CLI.")
        if model == "codex":
            with open(output, encoding="utf-8") as answer:
                return answer.read().strip()
        return result.stdout.strip()


class Handler(BaseHTTPRequestHandler):
    timeout = 10

    def log_message(self, format, *args):
        pass

    def send_json(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def error(self, status, message):
        self.send_json(status, {"error": {"message": message}})

    def authorized(self):
        scheme, _, supplied = self.headers.get("Authorization", "").partition(" ")
        if scheme.lower() == "bearer" and supplied and getattr(self.server, "key_check", None):
            valid = self.server.key_check(hashlib.sha256(supplied.encode()).hexdigest())
        else:
            expected = getattr(self.server, "token", "").encode()
            valid = bool(expected) and scheme.lower() == "bearer" and hmac.compare_digest(
                supplied.encode(), expected)
        if valid:
            return True
        self.error(401, "Use an active local Model Bridge API key.")
        return False

    def do_GET(self):
        if not self.authorized():
            return
        if self.path != "/v1/models":
            return self.error(404, "Unknown route.")
        self.send_json(200, {"object": "list", "data": [
            {"id": model, "object": "model", "owned_by": provider}
            for model, (provider, _) in self.server.models.items()
        ]})

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != "/v1/chat/completions":
            return self.error(404, "Unknown route.")
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 256_000:
                raise ValueError("Send a JSON body of up to 256 KB.")
            request = json.loads(self.rfile.read(size))
            if not isinstance(request, dict):
                raise ValueError("Send a JSON object.")
            if request.get("stream") or request.get("tools") or request.get("n", 1) != 1:
                raise ValueError("Only single, non-streaming text completions are supported.")
            model = request.get("model")
            models = self.server.models
            if not isinstance(model, str) or model not in models:
                raise ValueError("Choose a model ID from GET /v1/models.")
            provider, model_id = models[model]
            messages = request.get("messages")
            if not isinstance(messages, list) or not messages or any(
                not isinstance(item, dict)
                or item.get("role") not in ("system", "developer", "user", "assistant")
                or not isinstance(item.get("content"), str) for item in messages
            ):
                raise ValueError("Provide a nonempty messages list with text content.")
        except (ValueError, UnicodeError) as exc:
            return self.error(400, str(exc))
        prompt = "\n\n".join(f"{item['role']}: {item['content']}" for item in messages)
        try:
            answer = ask(provider, prompt, model_id)
        except subprocess.TimeoutExpired:
            return self.error(504, f"{model} timed out after 180 seconds.")
        except RuntimeError as exc:
            return self.error(502, str(exc))
        except OSError:
            return self.error(502, f"Could not run {model} or read its response.")
        self.send_json(200, {
            "id": "chatcmpl-" + secrets.token_hex(12),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": answer},
                         "finish_reason": "stop"}],
        })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    options = parser.parse_args()
    with HTTPServer(("127.0.0.1", options.port), Handler) as server:
        server.token = secrets.token_urlsafe(32)
        server.models = {"codex": ("codex", None), "claude": ("claude", None)}
        print(f"Base URL: http://127.0.0.1:{server.server_port}/v1", flush=True)
        print(f"Local API key: {server.token}", flush=True)
        print("Models: codex, claude. Press Ctrl+C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
