#!/usr/bin/env bash
# CS2 Plugin Compiler – Update (neue Version einspielen + .NET SDK aktualisieren)
set -euo pipefail
cd "$(dirname "$0")"
[ "$(id -u)" -eq 0 ] || { echo "Bitte als root ausführen: sudo ./update.sh"; exit 1; }
SDK_IMAGE="$(grep -E "^SDK_IMAGE=" .env | tail -1 | cut -d= -f2- | tr -d '"')"

docker pull "${SDK_IMAGE:-mcr.microsoft.com/dotnet/sdk:10.0}"
docker compose build --pull
docker compose up -d
docker image prune -f >/dev/null
echo "✓ Update fertig"
