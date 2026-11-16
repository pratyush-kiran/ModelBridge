# Model Bridge

Model Bridge is a Windows desktop app that exposes an OpenAI-compatible text endpoint on your PC. It builds its model catalog from the installed Codex and Claude Code CLIs and uses the provider sign-ins stored by those CLIs.

1. Open **Overview** and connect ChatGPT or Claude. If the CLI is missing, the app links to its setup guide.
2. Create a named key under **API keys** and copy it into your client. Only the key fingerprint is saved. Revoke the key to immediately block new requests using it.
3. Start the API from **Overview** and copy the displayed URL. The app uses port 8765 when available and picks a free port otherwise.
4. Select a model under **Models** and copy its API model ID. Test the model in the app to confirm access. The test uses one provider request.

The API listens on `127.0.0.1` and accepts a local bearer key. It supports `GET /v1/models` and single-response text calls to `POST /v1/chat/completions`. The CLI catalog can include models your account cannot run. Subscription availability and request limits are controlled by the providers.

## Develop and build

Run `python desktop.py` with Python 3.12 and Tk. For a standalone Windows executable, install PyInstaller and run `./build.ps1`. The executable will be in `dist/ModelBridge.exe`. Codex and Claude Code are installed separately.

`bridge.py` also retains the original console entry point.
