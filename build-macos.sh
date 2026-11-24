#!/bin/bash
# Build dist/ModelBridge.app and a zip to share. Run on a Mac: ./build-macos.sh
set -euo pipefail
cd "$(dirname "$0")"
python3 -m PyInstaller --noconfirm --clean --onedir --windowed --name ModelBridge \
    --icon assets/logo.png --osx-bundle-identifier com.modelbridge.desktop \
    --add-data "assets/icons:assets/icons" --add-data "assets/logo-header.png:assets" desktop.py
codesign --verify --deep --strict dist/ModelBridge.app
# ditto keeps the symlinks and signature that an ordinary zip would break.
ditto -c -k --keepParent dist/ModelBridge.app "dist/ModelBridge-macOS-$(uname -m).zip"
