"""Zentrale Einstellungen – alles über Umgebungsvariablen (.env) steuerbar."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

VERSION = "1.0.3"


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on", "ja")


# Daten-Verzeichnis. WICHTIG: muss im Container unter dem GLEICHEN Pfad
# eingebunden sein wie auf dem Host, weil die Build-Container über den
# Docker-Socket des Hosts gestartet werden und Host-Pfade brauchen.
DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/cssharp-compiler/data")).resolve()
JOBS_DIR = DATA_DIR / "jobs"
NUGET_DIR = DATA_DIR / "nuget"
DB_PATH = DATA_DIR / "compiler.sqlite"

SDK_IMAGE = os.environ.get("SDK_IMAGE", "mcr.microsoft.com/dotnet/sdk:10.0")
SDK_MAX_MAJOR = _int("SDK_MAX_MAJOR", 10)  # höchstes .NET, das das SDK-Image bauen kann

MAX_PARALLEL = max(1, _int("MAX_PARALLEL", 2))
MAX_QUEUE = max(1, _int("MAX_QUEUE", 30))
MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 20)
MAX_EXTRACTED_MB = _int("MAX_EXTRACTED_MB", 150)
MAX_FILES = _int("MAX_FILES", 3000)

RATE_LIMIT_PER_HOUR = _int("RATE_LIMIT_PER_HOUR", 20)
RESTORE_TIMEOUT = _int("RESTORE_TIMEOUT", 240)
BUILD_TIMEOUT = _int("BUILD_TIMEOUT", 240)
BUILD_MEMORY = os.environ.get("BUILD_MEMORY", "2g")
BUILD_CPUS = float(os.environ.get("BUILD_CPUS", "2"))
SANDBOX_UID = os.environ.get("SANDBOX_UID", "10001")

JOB_TTL_MIN = _int("JOB_TTL_MIN", 60)          # Dateien eines Jobs (Upload/Ergebnis)
HISTORY_DAYS = _int("HISTORY_DAYS", 30)        # Job-Liste im Admin-Bereich
LOG_MAX_BYTES = _int("LOG_MAX_BYTES", 200_000)

TRUST_PROXY = _bool("TRUST_PROXY", True)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# Unterpfad, z. B. "/compiler" für https://ddbmaster.de/compiler/ (leer = eigene (Sub-)Domain)
BASE_PATH = "/" + os.environ.get("BASE_PATH", "").strip().strip("/")
BASE_PATH = "" if BASE_PATH == "/" else BASE_PATH

SITE_NAME = os.environ.get("SITE_NAME", "CS2 Plugin Compiler")
SITE_SUBTITLE = os.environ.get("SITE_SUBTITLE", "CounterStrikeSharp · CS2")
SITE_LOGO = os.environ.get("SITE_LOGO", "C#")[:4]

# Eigene Texte für die große Überschrift und den Text darunter (leer = Standardtext)
HERO_TITLE_DE = os.environ.get("HERO_TITLE_DE", "")
HERO_TEXT_DE = os.environ.get("HERO_TEXT_DE", "")
HERO_TITLE_EN = os.environ.get("HERO_TITLE_EN", "")
HERO_TEXT_EN = os.environ.get("HERO_TEXT_EN", "")

SITE_OWNER = os.environ.get("SITE_OWNER", "ddbmaster.de")
SITE_OWNER_URL = os.environ.get("SITE_OWNER_URL", "https://ddbmaster.de")
IMPRESSUM_URL = os.environ.get("IMPRESSUM_URL", "")
DATENSCHUTZ_URL = os.environ.get("DATENSCHUTZ_URL", "")

NUGET_PACKAGE = "counterstrikesharp.api"
NUGET_SOURCE = "https://api.nuget.org/v3/index.json"
NUGET_REGISTRATION = (
    "https://api.nuget.org/v3/registration5-gz-semver2/counterstrikesharp.api/index.json"
)
VERSIONS_CACHE_MIN = _int("VERSIONS_CACHE_MIN", 30)


def ensure_dirs() -> None:
    for d in (DATA_DIR, JOBS_DIR, NUGET_DIR / "packages"):
        d.mkdir(parents=True, exist_ok=True)
    # Sandbox-Benutzer muss den NuGet-Cache beschreiben können
    try:
        uid = int(SANDBOX_UID)
        for p in (NUGET_DIR, NUGET_DIR / "packages"):
            os.chown(p, uid, uid)
    except (PermissionError, ValueError, OSError):
        pass


def secret_key() -> bytes:
    """Geheimer Schlüssel (für IP-Hashes und Admin-Sitzungen), einmalig erzeugt."""
    path = DATA_DIR / "secret.key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path.read_text().strip().encode()
