"""Metamod:Source-Plugins (C++, AMBuild): Projekt prüfen, Ergebnis packen, Log auswerten."""
from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from . import config
from .project import ProjectError

# Beim ZIP-Upload ignorieren (lokale Build-Ordner, IDE-Kram)
SKIP_DIRS = {".git", ".vs", ".idea", ".vscode", "__macosx", "node_modules"}

GIT_URL_RE = re.compile(r"^https://([a-z0-9.-]+)/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")

# clang/gcc: datei:zeile:spalte: error: meldung
DIAG_RE = re.compile(r"^(?P<file>[^\s:][^:]*):(?P<line>\d+):(?P<col>\d+):\s+(?P<sev>error|warning|fatal error):\s+(?P<msg>.+)$")
LINK_RE = re.compile(r"(undefined reference to|undefined symbol:)\s*(?P<sym>.+)")


@dataclass
class MmProject:
    root: Path          # Ordner mit configure.py
    name: str           # Anzeigename
    has_manifests: bool
    has_package_script: bool


def runtimes() -> list[str]:
    return list(config.METAMOD_RUNTIMES)


def image_tag(runtime: str) -> str:
    return f"{config.METAMOD_IMAGE}:{runtime}"


# --------------------------------------------------------------------------- #
# Eingaben prüfen
# --------------------------------------------------------------------------- #
def parse_git_url(url: str) -> tuple[str, str]:
    """Liefert (saubere URL, Repo-Name). Nur https und erlaubte Hosts."""
    url = (url or "").strip()
    if url.startswith("github.com/") or url.startswith("gitlab.com/"):
        url = "https://" + url
    m = GIT_URL_RE.match(url)
    if not m:
        raise ProjectError("git_url_invalid", url[:120])
    host = m.group(1).lower()
    if host not in config.GIT_HOSTS:
        raise ProjectError("git_host_not_allowed", host)
    parsed = urlparse(url)
    if parsed.username or parsed.password or parsed.port:
        raise ProjectError("git_url_invalid", url[:120])
    clean = f"https://{host}/{m.group(2)}/{m.group(3)}.git"
    return clean, m.group(3)


def check_ref(ref: str) -> str:
    ref = (ref or "").strip()
    if not ref:
        return ""
    if not REF_RE.match(ref) or ".." in ref:
        raise ProjectError("git_ref_invalid", ref[:100])
    return ref


def check_tag(tag: str) -> str:
    tag = (tag or "").strip()
    if not tag:
        return ""
    if not TAG_RE.match(tag):
        raise ProjectError("mm_tag_invalid", tag[:40])
    return tag


# --------------------------------------------------------------------------- #
# Projekt analysieren
# --------------------------------------------------------------------------- #
def _dir_size(path: Path) -> tuple[int, int]:
    total = files = 0
    for root, dirs, names in os.walk(path):
        for n in names:
            p = os.path.join(root, n)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            total += st.st_size
            files += 1
    return total, files


def check_size(src: Path) -> None:
    total, files = _dir_size(src)
    if total > config.MM_MAX_REPO_MB * 1024 * 1024:
        raise ProjectError("repo_too_big", f"> {config.MM_MAX_REPO_MB} MB")
    if files > max(config.MAX_FILES, 20000):
        raise ProjectError("too_many_files", str(files))


def remove_symlinks(src: Path) -> None:
    """Symlinks aus einem geklonten Repo entfernen (könnten aus dem Ordner zeigen)."""
    for root, dirs, names in os.walk(src):
        for n in dirs + names:
            p = Path(root) / n
            if p.is_symlink():
                p.unlink()


def analyze(src: Path, fallback_name: str = "") -> MmProject:
    """Sucht configure.py + AMBuildScript (im Wurzelordner oder eine Ebene tiefer)."""
    candidates = []
    for p in [src, *[d for d in sorted(src.iterdir()) if d.is_dir() and not d.name.startswith(".")]]:
        if (p / "configure.py").is_file() and (p / "AMBuildScript").is_file():
            candidates.append(p)
    if not candidates:
        if any(src.rglob("CMakeLists.txt")) or any(src.rglob("premake5.lua")) or any(src.rglob("xmake.lua")):
            raise ProjectError("mm_unsupported_buildsystem")
        if any(src.rglob("*.csproj")):
            raise ProjectError("mm_is_csharp")
        raise ProjectError("mm_no_ambuild")
    root = candidates[0]

    # Projekt in einem Unterordner (typisch für GitHub-ZIP "repo-main/") nach oben holen
    if root != src:
        tmp = src.parent / (src.name + "__root")
        root.rename(tmp)
        shutil.rmtree(src, ignore_errors=True)
        tmp.rename(src)
        root = src

    name = ""
    meta = root / "plugin-metadata.json"
    if meta.is_file():
        try:
            data = json.loads(meta.read_text(encoding="utf-8", errors="replace"))
            name = str(data.get("name") or data.get("plugin_name") or "")
        except (ValueError, AttributeError):
            name = ""
    if not name:
        name = fallback_name
    name = re.sub(r"[^A-Za-z0-9_.-]", "", name)[:60] or "plugin"

    return MmProject(
        root=root,
        name=name,
        has_manifests=(root / "hl2sdk-manifests" / "SdkHelpers.ambuild").is_file(),
        has_package_script=(root / "PackageScript").is_file(),
    )


# --------------------------------------------------------------------------- #
# Ergebnis
# --------------------------------------------------------------------------- #
def package_result(src: Path, dest_zip: Path) -> list[dict]:
    """Packt build/package/cs2 (vom PackageScript) – sonst alle gebauten .so-Dateien."""
    build = src / "build"
    pkg = build / "package"
    base: Path | None = None
    if pkg.is_dir():
        if (pkg / "cs2").is_dir():
            base = pkg / "cs2"
        else:
            subs = [d for d in pkg.iterdir() if d.is_dir()]
            base = subs[0] if len(subs) == 1 and (subs[0] / "addons").is_dir() else pkg
    entries: list[tuple[Path, str]] = []
    if base is not None:
        for f in sorted(base.rglob("*")):
            if f.is_file() and not f.is_symlink():
                entries.append((f, f.relative_to(base).as_posix()))
    if not entries:
        for f in sorted(build.rglob("*.so")):
            if f.is_file() and not f.is_symlink() and "package" not in f.parts:
                entries.append((f, "addons/" + f.name))
    if not any(rel.endswith(".so") for _, rel in entries):
        raise ProjectError("mm_no_output")

    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    listing = []
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f, rel in entries:
            zf.write(f, rel)
            listing.append({"path": rel, "size": f.stat().st_size})
    return listing


def package_source(src: Path, dest_zip: Path) -> dict:
    """Quellcode (ohne .git) für den Editor packen."""
    files = 0
    total = 0
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, names in os.walk(src):
            dirs[:] = sorted(d for d in dirs if d != ".git" and not d.lower() == "__macosx")
            for n in sorted(names):
                if n == ".git":
                    continue
                f = Path(root) / n
                if f.is_symlink() or not f.is_file():
                    continue
                zf.write(f, f.relative_to(src).as_posix())
                files += 1
                total += f.stat().st_size
    return {"files": files, "bytes": total, "zip_bytes": dest_zip.stat().st_size}


def parse_log(log: str) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    seen = set()
    for raw in log.splitlines():
        line = raw.strip()
        m = DIAG_RE.match(line)
        if m:
            d = m.groupdict()
            f = d["file"]
            for prefix in ("/src/", "/sdk/"):
                if f.startswith(prefix):
                    f = ("SDK: " if prefix == "/sdk/" else "") + f[len(prefix):]
            key = (f, d["line"], d["msg"])
            if key in seen:
                continue
            seen.add(key)
            item = {"file": f, "line": int(d["line"]), "col": int(d["col"]), "code": d["sev"].replace("fatal error", "fatal"), "message": d["msg"][:500]}
            (warnings if d["sev"] == "warning" else errors).append(item)
            continue
        lm = LINK_RE.search(line)
        if lm and len(errors) < 200:
            key = ("link", lm.group("sym"))
            if key not in seen:
                seen.add(key)
                errors.append({"file": "", "line": None, "col": None, "code": "linker", "message": line[:500]})
    return {"errors": errors, "warnings": warnings, "hints": hints_for(errors, log)}


def hints_for(errors: list[dict], log: str) -> list[str]:
    hints: list[str] = []

    def add(h: str) -> None:
        if h not in hints:
            hints.append(h)

    if "__TIMEOUT__" in log:
        add("mm_timeout")
    if "Could not find a source copy of" in log:
        add("mm_missing_dependency")
    if "No suitable C/C++ compiler" in log:
        add("mm_no_compiler")
    if "__STEP_FAILED__ configure" in log and "Could not find" not in log:
        add("mm_configure_failed")
    if "Could not find SDK" in log or "hl2sdk-" in log and "not found" in log:
        add("mm_sdk_missing")
    if re.search(r"fatal error: '[^']+' file not found", log):
        add("mm_header_missing")
    if any(e["code"] == "linker" for e in errors):
        add("mm_link_error")
    if "No such file or directory" in log and "submodule" in log.lower():
        add("mm_submodule")
    return hints
