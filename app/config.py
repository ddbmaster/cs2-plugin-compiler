"""Zentrale Einstellungen – alles über Umgebungsvariablen (.env) steuerbar."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

VERSION = "1.3.4"


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
# Standard: Ordner "data" im Installationsordner (install.sh trägt den Pfad in die .env ein).
DATA_DIR = Path(
    os.environ.get("DATA_DIR") or str(Path(__file__).resolve().parent.parent / "data")
).resolve()
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

# Unterpfad, z. B. "/compiler" für https://example.com/compiler/ (leer = eigene (Sub-)Domain)
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

SITE_OWNER = os.environ.get("SITE_OWNER", "")
SITE_OWNER_URL = os.environ.get("SITE_OWNER_URL", "")
IMPRESSUM_URL = os.environ.get("IMPRESSUM_URL", "")
DATENSCHUTZ_URL = os.environ.get("DATENSCHUTZ_URL", "")

# --- Metamod:Source (C++) ------------------------------------------------- #
METAMOD_ENABLED = _bool("METAMOD_ENABLED", True)
# Laufzeitumgebungen: steamrt3 (Standard, passt zu den meisten Servern), steamrt4 (neuere Linux-Systeme)
METAMOD_RUNTIMES = [
    r.strip() for r in os.environ.get("METAMOD_RUNTIMES", "steamrt3").split(",")
    if r.strip() in ("steamrt3", "steamrt4")
] or ["steamrt3"]
METAMOD_BASE_IMAGE = os.environ.get("METAMOD_BASE_IMAGE", "ghcr.io/source2ze/build-containers")
METAMOD_IMAGE = os.environ.get("METAMOD_IMAGE", "cssharp-compiler-mm")
METAMOD_MMS_REF = os.environ.get("METAMOD_MMS_REF", "master")
METAMOD_SDK_REF = os.environ.get("METAMOD_SDK_REF", "cs2")
MM_FETCH_TIMEOUT = _int("MM_FETCH_TIMEOUT", 180)
MM_BUILD_TIMEOUT = _int("MM_BUILD_TIMEOUT", 420)
MM_MAX_REPO_MB = _int("MM_MAX_REPO_MB", 300)
# Git-Quellen nur von diesen Hosts (Schutz vor Zugriffen ins eigene Netzwerk)
GIT_HOSTS = [
    h.strip().lower() for h in os.environ.get(
        "GIT_HOSTS", "github.com,gitlab.com,codeberg.org,bitbucket.org"
    ).split(",") if h.strip()
]

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
