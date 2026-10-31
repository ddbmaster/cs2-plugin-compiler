#!/usr/bin/env bash
# CS2 Plugin Compiler – Installation auf Ubuntu
set -euo pipefail

cd "$(dirname "$0")"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "Bitte als root ausführen:  sudo ./install.sh"

# 1) Docker prüfen / installieren --------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  warn "Docker ist nicht installiert."
  read -r -p "Docker jetzt installieren? [J/n] " a
  case "${a:-j}" in
    [JjYy]*) curl -fsSL https://get.docker.com | sh ;;
    *) fail "Ohne Docker geht es nicht. Abbruch." ;;
  esac
fi
docker info >/dev/null 2>&1 || { systemctl enable --now docker >/dev/null 2>&1 || true; }
docker info >/dev/null 2>&1 || fail "Docker läuft nicht (systemctl status docker)."
docker compose version >/dev/null 2>&1 || fail "'docker compose' fehlt. Paket docker-compose-plugin installieren."
ok "Docker $(docker version --format '{{.Server.Version}}') läuft"

# 2) Einstellungen -------------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  PW="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20 || true)"
  sed -i "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=${PW}|" .env
  ok ".env angelegt (Admin-Passwort wurde erzeugt)"
else
  ok ".env vorhanden – wird beibehalten"
fi
envget() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/'; }
DATA_DIR="$(envget DATA_DIR)"; PORT="$(envget PORT)"; BASE_PATH="$(envget BASE_PATH)"; SDK_IMAGE="$(envget SDK_IMAGE)"
DATA_DIR="${DATA_DIR:-/opt/cssharp-compiler/data}"
mkdir -p "$DATA_DIR"
chmod 750 "$DATA_DIR"
ok "Datenordner: $DATA_DIR"

# 3) Images bauen/laden ---------------------------------------------------------
echo "Baue Web-Oberfläche …"
docker compose build --pull
echo "Lade .NET SDK ($SDK_IMAGE) – das dauert beim ersten Mal ein paar Minuten …"
docker pull "${SDK_IMAGE:-mcr.microsoft.com/dotnet/sdk:10.0}"
ok "Images bereit"

# 4) Starten --------------------------------------------------------------------
docker compose up -d
sleep 3
if curl -fsS "http://127.0.0.1:${PORT:-8085}${BASE_PATH:-}/api/status" >/dev/null 2>&1; then
  ok "Compiler läuft auf http://127.0.0.1:${PORT:-8085}"
else
  warn "Compiler antwortet noch nicht – Logs: docker compose logs -f"
fi

echo
echo "-------------------------------------------------------------"
if [ -n "${BASE_PATH:-}" ]; then
  echo " Nächster Schritt: Webserver von ddbmaster.de ergänzen"
  echo " nginx:  deploy/nginx-unterpfad.conf"
  echo " Apache: deploy/apache-unterpfad.conf"
  echo
  echo " Compiler:       https://ddbmaster.de${BASE_PATH}/"
  echo " Admin-Bereich:  https://ddbmaster.de${BASE_PATH}/admin"
else
  echo " Nächster Schritt: Subdomain im Webserver einrichten"
  echo " Beispiele: deploy/nginx.conf oder deploy/apache.conf"
  echo
  echo " Admin-Bereich:  https://<deine-subdomain>/admin"
fi
echo " Passwort:       $(grep '^ADMIN_PASSWORD=' .env | cut -d= -f2-)"
echo "-------------------------------------------------------------"
