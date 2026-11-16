$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    python -m PyInstaller --noconfirm --onefile --windowed --name ModelBridge --icon assets/model-bridge.ico --add-data "assets/model-bridge.ico;assets" desktop.py
    if ($LASTEXITCODE -ne 0) { throw "Build failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
