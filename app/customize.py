"""Design- und Textverwaltung (Admin-Bereich).

Alles wird in DATA_DIR/customize.json gespeichert – liegt damit im Daten-Ordner
und übersteht Updates. Die Standardwerte der Stilvariablen werden direkt aus
style.css gelesen, damit sie immer zur ausgelieferten Version passen.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path

from . import config

STYLE_CSS = Path(__file__).parent / "static" / "style.css"
STORE = config.DATA_DIR / "customize.json"

# Stilvariablen, die im Admin-Bereich bearbeitet werden können.
# theme=True: eigener Wert für Hell und Dunkel; False: gilt für beide.
VARIABLES: list[dict] = [
    {"name": "bg", "label": "Seitenhintergrund", "group": "Flächen", "kind": "color", "theme": True},
    {"name": "bg-grad", "label": "Hintergrund-Verlauf", "group": "Flächen", "kind": "text", "theme": True},
    {"name": "panel", "label": "Boxen", "group": "Flächen", "kind": "color", "theme": True},
    {"name": "panel-2", "label": "Boxen (zweite Ebene)", "group": "Flächen", "kind": "color", "theme": True},
    {"name": "border", "label": "Rahmen", "group": "Flächen", "kind": "color", "theme": True},
    {"name": "shadow", "label": "Schatten", "group": "Flächen", "kind": "text", "theme": True},
    {"name": "text", "label": "Text", "group": "Text", "kind": "color", "theme": True},
    {"name": "muted", "label": "Text (gedämpft)", "group": "Text", "kind": "color", "theme": True},
    {"name": "accent", "label": "Akzentfarbe", "group": "Akzent", "kind": "color", "theme": True},
    {"name": "accent-2", "label": "Akzentfarbe 2", "group": "Akzent", "kind": "color", "theme": True},
    {"name": "accent-ink", "label": "Text auf Akzent", "group": "Akzent", "kind": "color", "theme": True},
    {"name": "ok", "label": "Erfolg", "group": "Meldungen", "kind": "color", "theme": True},
    {"name": "ok-bg", "label": "Erfolg (Hintergrund)", "group": "Meldungen", "kind": "color", "theme": True},
    {"name": "err", "label": "Fehler", "group": "Meldungen", "kind": "color", "theme": True},
    {"name": "err-bg", "label": "Fehler (Hintergrund)", "group": "Meldungen", "kind": "color", "theme": True},
    {"name": "warn", "label": "Warnung", "group": "Meldungen", "kind": "color", "theme": True},
    {"name": "warn-bg", "label": "Warnung (Hintergrund)", "group": "Meldungen", "kind": "color", "theme": True},
    {"name": "info", "label": "Hinweis", "group": "Meldungen", "kind": "color", "theme": True},
    {"name": "info-bg", "label": "Hinweis (Hintergrund)", "group": "Meldungen", "kind": "color", "theme": True},
    {"name": "code-bg", "label": "Code-Hintergrund", "group": "Code", "kind": "color", "theme": True},
    {"name": "code-text", "label": "Code-Text", "group": "Code", "kind": "color", "theme": True},
    {"name": "radius", "label": "Eckenradius", "group": "Allgemein", "kind": "text", "theme": False},
    {"name": "sans", "label": "Schriftart", "group": "Allgemein", "kind": "text", "theme": False},
    {"name": "mono", "label": "Schriftart Code", "group": "Allgemein", "kind": "text", "theme": False},
]
VAR_NAMES = {v["name"]: v for v in VARIABLES}

MAX_CSS = 200_000
MAX_TEXT = 4000
_VALUE_RE = re.compile(r"^[#a-zA-Z0-9(),.%\s\-\"'/_+*]{0,400}$")
_KEY_RE = re.compile(r"^[a-zA-Z0-9_.\-]{1,80}$")
LANGS = ("de", "en")

_lock = threading.Lock()
_cache: dict | None = None


class CustomizeError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Standardwerte aus style.css
# --------------------------------------------------------------------------- #
def _parse_block(css: str, selector_re: str) -> dict[str, str]:
    m = re.search(selector_re + r"\s*\{(.*?)\n\s*\}", css, re.S)
    if not m:
        return {}
    out = {}
    for name, value in re.findall(r"--([a-z0-9\-]+)\s*:\s*([^;]+);", m.group(1)):
        out[name] = " ".join(value.split())
    return out


def defaults() -> dict:
    css = STYLE_CSS.read_text(encoding="utf-8")
    light = _parse_block(css, r"(?m)^:root")
    dark = _parse_block(css, r':root\[data-theme="dark"\]')
    out = {"light": {}, "dark": {}}
    for v in VARIABLES:
        n = v["name"]
        out["light"][n] = light.get(n, "")
        out["dark"][n] = dark.get(n, light.get(n, "")) if v["theme"] else light.get(n, "")
    return out


# --------------------------------------------------------------------------- #
# Laden / Speichern
# --------------------------------------------------------------------------- #
def _empty() -> dict:
    return {
        "site": {"name": "", "subtitle": "", "logo": ""},
        "vars": {"light": {}, "dark": {}},
        "css": "",
        "texts": {lang: {} for lang in LANGS},
    }


def load() -> dict:
    global _cache
    with _lock:
        if _cache is not None:
            return json.loads(json.dumps(_cache))
        data = _empty()
        try:
            raw = json.loads(STORE.read_text(encoding="utf-8"))
            data = validate(raw)
        except FileNotFoundError:
            pass
        except (ValueError, CustomizeError, OSError):
            # Beschädigte Datei nicht überschreiben, sondern beiseitelegen
            try:
                STORE.rename(STORE.with_suffix(".json.broken"))
            except OSError:
                pass
        _cache = data
        return json.loads(json.dumps(data))


def save(data: dict) -> dict:
    global _cache
    clean = validate(data)
    with _lock:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        if STORE.exists():
            # Eine Sicherung des vorherigen Stands behalten
            try:
                STORE.with_suffix(".json.bak").write_bytes(STORE.read_bytes())
            except OSError:
                pass
        tmp = STORE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, STORE)
        _cache = clean
    return clean


def validate(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise CustomizeError("bad_format")
    out = _empty()

    site = raw.get("site") or {}
    if not isinstance(site, dict):
        raise CustomizeError("bad_site")
    for key, limit in (("name", 80), ("subtitle", 120), ("logo", 4)):
        val = site.get(key, "")
        if not isinstance(val, str):
            raise CustomizeError("bad_site", key)
        out["site"][key] = val.strip()[:limit]

    vars_ = raw.get("vars") or {}
    if not isinstance(vars_, dict):
        raise CustomizeError("bad_vars")
    for theme in ("light", "dark"):
        block = vars_.get(theme) or {}
        if not isinstance(block, dict):
            raise CustomizeError("bad_vars", theme)
        for name, value in block.items():
            meta = VAR_NAMES.get(name)
            if meta is None or not isinstance(value, str):
                continue
            if theme == "dark" and not meta["theme"]:
                continue
            value = " ".join(value.split())
            if not value:
                continue
            if not _VALUE_RE.match(value):
                raise CustomizeError("bad_value", f"--{name}")
            out["vars"][theme][name] = value

    css = raw.get("css", "")
    if not isinstance(css, str):
        raise CustomizeError("bad_css")
    if len(css) > MAX_CSS:
        raise CustomizeError("css_too_big", str(MAX_CSS))
    out["css"] = css.replace("\r\n", "\n")

    texts = raw.get("texts") or {}
    if not isinstance(texts, dict):
        raise CustomizeError("bad_texts")
    for lang in LANGS:
        block = texts.get(lang) or {}
        if not isinstance(block, dict):
            raise CustomizeError("bad_texts", lang)
        for key, value in block.items():
            if not isinstance(key, str) or not _KEY_RE.match(key) or not isinstance(value, str):
                continue
            if value.strip():
                out["texts"][lang][key] = value[:MAX_TEXT]
    return out


# --------------------------------------------------------------------------- #
# Ausgabe
# --------------------------------------------------------------------------- #
def site_value(key: str, fallback: str) -> str:
    return load()["site"].get(key) or fallback


def texts() -> dict:
    return load()["texts"]


def build_css(data: dict | None = None) -> str:
    data = data or load()
    light = data["vars"]["light"]
    dark = data["vars"]["dark"]

    def block(selector: str, values: dict) -> str:
        if not values:
            return ""
        body = "\n".join(f"  --{k}: {v};" for k, v in values.items())
        return f"{selector} {{\n{body}\n}}\n"

    parts = ["/* Eigenes Design aus dem Admin-Bereich – automatisch erzeugt */\n"]
    parts.append(block(":root", light))
    if dark:
        parts.append("@media (prefers-color-scheme: dark) {\n"
                     + block(':root:not([data-theme="light"])', dark) + "}\n")
        parts.append(block(':root[data-theme="dark"]', dark))
    if data["css"].strip():
        parts.append("\n/* Eigenes CSS */\n" + data["css"].strip() + "\n")
    return "".join(parts)


def css_version() -> str:
    return hashlib.sha1(build_css().encode()).hexdigest()[:10]
