"""Liest die verfügbaren CounterStrikeSharp.API-Versionen samt Ziel-Frameworks von NuGet."""
from __future__ import annotations

import asyncio
import json
import re
import time

import httpx

from . import config

_cache: dict = {"ts": 0.0, "versions": []}
_lock = asyncio.Lock()
CACHE_FILE = config.DATA_DIR / "versions.json"


def normalize_tf(tf: str | None) -> str:
    """'.NETCoreApp8.0' / 'net8.0' / 'NET8.0-windows' -> 'net8.0'."""
    if not tf:
        return ""
    t = tf.strip().lower()
    m = re.match(r"^\.?netcoreapp(\d+)\.(\d+)", t)
    if m:
        return f"net{m.group(1)}.{m.group(2)}"
    m = re.match(r"^net(\d+)\.(\d+)", t)
    if m:
        return f"net{m.group(1)}.{m.group(2)}"
    return t


def tf_major(tf: str | None) -> int | None:
    m = re.match(r"^net(\d+)\.\d+$", normalize_tf(tf))
    return int(m.group(1)) if m else None


def version_key(v: str) -> tuple:
    main, _, pre = v.partition("-")
    parts = []
    for p in main.split("."):
        parts.append(int(p) if p.isdigit() else 0)
    while len(parts) < 4:
        parts.append(0)
    # Vorabversionen vor der finalen Version einsortieren
    return (*parts, 0 if pre else 1, pre)


def _entry_from_catalog(entry: dict) -> dict | None:
    version = entry.get("version")
    if not version:
        return None
    tfs = sorted(
        {
            normalize_tf(g.get("targetFramework"))
            for g in entry.get("dependencyGroups") or []
            if g.get("targetFramework")
        },
        key=lambda t: tf_major(t) or 0,
    )
    return {
        "version": version,
        "frameworks": [t for t in tfs if t],
        "listed": entry.get("listed", True) is not False,
        "prerelease": "-" in version,
    }


async def _fetch() -> list[dict]:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(config.NUGET_REGISTRATION)
        r.raise_for_status()
        index = r.json()
        result: list[dict] = []
        for page in index.get("items", []):
            items = page.get("items")
            if items is None:
                pr = await client.get(page["@id"])
                pr.raise_for_status()
                items = pr.json().get("items", [])
            for leaf in items:
                e = _entry_from_catalog(leaf.get("catalogEntry") or {})
                if e and e["listed"]:
                    result.append(e)
    result.sort(key=lambda e: version_key(e["version"]), reverse=True)
    return result


def _load_file() -> list[dict]:
    try:
        data = json.loads(CACHE_FILE.read_text())
        return data.get("versions", [])
    except (OSError, ValueError):
        return []


async def get_versions(force: bool = False) -> list[dict]:
    async with _lock:
        fresh = time.time() - _cache["ts"] < config.VERSIONS_CACHE_MIN * 60
        if _cache["versions"] and fresh and not force:
            return _cache["versions"]
        try:
            versions = await _fetch()
            if versions:
                _cache.update(ts=time.time(), versions=versions)
                try:
                    CACHE_FILE.write_text(json.dumps({"ts": time.time(), "versions": versions}))
                except OSError:
                    pass
        except (httpx.HTTPError, ValueError, KeyError):
            if not _cache["versions"]:
                _cache["versions"] = _load_file()
                _cache["ts"] = time.time() - config.VERSIONS_CACHE_MIN * 60 + 120  # bald neu versuchen
        return _cache["versions"]


def find(versions: list[dict], version: str) -> dict | None:
    for e in versions:
        if e["version"].lower() == version.lower():
            return e
    return None


def compatible(project_tf: str, package_tfs: list[str]) -> bool:
    """Ein Projekt mit net10.0 kann ein net8.0-Paket nutzen, aber nicht umgekehrt."""
    pm = tf_major(project_tf)
    if pm is None or not package_tfs:
        return True  # unbekannt -> nicht blockieren
    majors = [m for m in (tf_major(t) for t in package_tfs) if m is not None]
    if not majors:
        return True
    return min(majors) <= pm


def best_for_framework(versions: list[dict], project_tf: str) -> dict | None:
    """Neueste stabile Version, die mit dem Ziel-Framework des Projekts funktioniert."""
    for e in versions:
        if e["prerelease"]:
            continue
        if e["frameworks"] and compatible(project_tf, e["frameworks"]):
            return e
    return None
