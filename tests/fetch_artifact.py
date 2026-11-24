"""Download a GitHub Actions artifact in small, verified pieces (plain `gh run download` often stalls).

python tests/fetch_artifact.py <run-id> <artifact-name> <folder>
"""

import json
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

REPO = "pratyush-kiran/ModelBridge"
PIECE = 512 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def signed_url(artifact_id):
    """The download link is on another host and expires, so ask for it just before use."""
    token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    call = urllib.request.Request(f"https://api.github.com/repos/{REPO}/actions/artifacts/{artifact_id}/zip",
                                  headers={"Authorization": f"Bearer {token}"})
    try:
        urllib.request.build_opener(NoRedirect).open(call, timeout=30)
    except urllib.error.HTTPError as redirect:
        return redirect.headers["Location"]
    raise RuntimeError("GitHub did not return a download link.")


def main(run, name, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    listing = json.loads(subprocess.run(
        ["gh", "api", f"repos/{REPO}/actions/runs/{run}/artifacts"], capture_output=True, text=True, check=True).stdout)
    artifact = next(item for item in listing["artifacts"] if item["name"] == name)
    size, target = artifact["size_in_bytes"], folder / "artifact.zip"
    data = bytearray()
    url, failures = None, 0
    while len(data) < size:
        start, end = len(data), min(len(data) + PIECE, size) - 1
        try:
            url = url or signed_url(artifact["id"])
            call = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(call, timeout=30) as reply:
                piece = reply.read()
            if reply.status != 206 or len(piece) != end - start + 1:
                raise OSError(f"unexpected reply {reply.status}, {len(piece)} bytes")
            data += piece
            failures = 0
        except (OSError, urllib.error.URLError, RuntimeError) as error:
            url, failures = None, failures + 1
            if failures > 15:
                sys.exit(f"failed {name} at {len(data)}/{size}: {error}")
    target.write_bytes(data)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip():
            sys.exit(f"failed {name}: corrupt archive")
        archive.extractall(folder)
    print(f"downloaded {name} ({size} bytes)")


if __name__ == "__main__":
    main(*sys.argv[1:4])
