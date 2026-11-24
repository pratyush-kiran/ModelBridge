"""macOS helpers: Keychain storage and commands that run in a Terminal window."""

from pathlib import Path
import shlex
import subprocess
import tempfile
import time

SERVICE = "ModelBridge"
INSTALLERS = {
    "codex": "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
    "claude": "curl -fsSL https://claude.ai/install.sh | bash",
}


def security(command, failure):
    # Commands go through stdin so that keys never appear in the process list.
    result = subprocess.run(["/usr/bin/security", "-i"], input=command + "\n",
                            capture_output=True, encoding="utf-8", timeout=60)
    if result.returncode or "security:" in result.stderr or "returned -" in result.stderr:
        raise OSError(f"{failure} {result.stderr.strip()}".strip())
    return result.stdout.strip()


def keychain_save(account, token):
    security(f"add-generic-password -U -s {SERVICE} -a {account} -w {shlex.quote(token)}",
             "The macOS Keychain could not save the key.")


def keychain_read(account):
    return security(f"find-generic-password -s {SERVICE} -a {account} -w",
                    "The macOS Keychain could not read the key.")


def keychain_delete(account):
    security(f"delete-generic-password -s {SERVICE} -a {account}",
             "The macOS Keychain could not delete the key.")


class TerminalJob:
    """Run a shell command in Terminal, with the parts of Popen that the app uses."""

    def __init__(self, command, path, unset=(), opener=("/usr/bin/open", "-a", "Terminal")):
        self.directory = tempfile.TemporaryDirectory(prefix="model-bridge-")
        folder = Path(self.directory.name)
        self.marker = folder / "exit-code"
        self.returncode = None
        script = folder / "model-bridge.command"
        marker, partial = shlex.quote(str(self.marker)), shlex.quote(str(self.marker) + ".part")
        script.write_text("\n".join((
            "#!/bin/bash",
            "set -o pipefail",
            f"finish() {{ code=$?; echo $code > {partial} && mv {partial} {marker}; }}",
            "trap finish EXIT",
            "trap 'exit 1' HUP INT TERM",
            f"unset {' '.join(unset)}" if unset else ":",
            f"export PATH={shlex.quote(path)}",
            command,
            "code=$?",
            "echo",
            'if [ $code -eq 0 ]; then echo "Done. Return to Model Bridge."',
            'else echo "That did not finish (code $code). Return to Model Bridge to try again."; fi',
            "exit $code",
            "")), encoding="utf-8")
        script.chmod(0o700)
        subprocess.run([*opener, str(script)], check=True, timeout=30)

    def poll(self):
        if self.returncode is None and self.marker.exists():
            self.returncode = int(self.marker.read_text().strip() or 1)
        return self.returncode

    def wait(self):
        while self.poll() is None:
            time.sleep(0.3)
        return self.returncode

    def terminate(self):
        self.returncode = 1
