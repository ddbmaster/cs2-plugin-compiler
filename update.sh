#!/usr/bin/env bash
# CS2 Plugin Compiler – Update (neue Version einspielen + .NET SDK aktualisieren)
set -euo pipefail
cd "$(dirname "$0")"
[ "$(id -u)" -eq 0 ] || { echo "Bitte als root ausführen: sudo ./update.sh"; exit 1; }
# Wert aus der .env lesen (umschließende "…" oder '…' werden entfernt)
envget() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/'; }

SDK_IMAGE="$(envget SDK_IMAGE)"
DATA_DIR="$(envget DATA_DIR)"
if [ -z "$DATA_DIR" ]; then
  # Standard: Ordner "data" im Installationsverzeichnis (absoluter Pfad)
  DATA_DIR="$(pwd)/data"
  sed -i '/^DATA_DIR=/d' .env
  echo "DATA_DIR=${DATA_DIR}" >> .env
  mkdir -p "$DATA_DIR"
  echo "DATA_DIR auf ${DATA_DIR} gesetzt"
fi

docker pull "${SDK_IMAGE:-mcr.microsoft.com/dotnet/sdk:10.0}"
docker compose build --pull
docker compose up -d
docker image prune -f >/dev/null
echo "✓ Update fertig"
