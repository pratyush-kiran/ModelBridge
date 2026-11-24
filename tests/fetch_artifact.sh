#!/bin/bash
# Download a CI artifact with resume, since plain `gh run download` often stalls: fetch_artifact.sh <run-id> <name> <folder>
set -u
run="$1"; name="$2"; folder="$3"
mkdir -p "$folder"
id=$(gh api "repos/pratyush-kiran/ModelBridge/actions/runs/$run/artifacts" -q ".artifacts[]|select(.name==\"$name\")|.id")
url=$(curl -s -m 30 -H "Authorization: Bearer $(gh auth token)" -D - -o /dev/null \
    "https://api.github.com/repos/pratyush-kiran/ModelBridge/actions/artifacts/$id/zip" | grep -i '^location:' | tr -d '\r' | cut -d' ' -f2)
for _ in 1 2 3 4 5 6 7 8; do
    curl -sS -m 40 -C - -o "$folder/artifact.zip" "$url" 2>/dev/null
    python -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).testzip()" "$folder/artifact.zip" 2>/dev/null && break
done
python -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$folder/artifact.zip" "$folder" && echo "downloaded $name"
