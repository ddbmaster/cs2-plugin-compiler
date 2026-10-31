"""Entpacken, Prüfen und Anpassen hochgeladener CounterStrikeSharp-Projekte.

Sicherheitsprinzip: Alles, was hier passiert, läuft im Web-Container und führt
KEINEN Code aus dem Upload aus. Ausgeführt wird nur in den Sandbox-Containern.
"""
from __future__ import annotations

import io
import re
import shutil
import stat
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import config
from .nuget import normalize_tf

API_NAME = "counterstrikesharp.api"
SKIP_DIRS = {"bin", "obj", ".git", ".vs", ".idea", ".vscode", "node_modules", "__macosx", "packages"}
SKIP_FILES = {".ds_store", "thumbs.db", "desktop.ini"}
MSBUILD_EXT = (".csproj", ".props", ".targets", ".proj")
ALLOWED_SDK = re.compile(r"^Microsoft\.NET\.Sdk(\.[A-Za-z]+)?(/[\w.\-]+)?$")
OUT_DIR = "__out"


class ProjectError(Exception):
    """Fehler mit Code (wird im Frontend übersetzt) und optionalem Detail."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass
class ProjectInfo:
    csproj: str                      # relativer Pfad des Hauptprojekts
    candidates: list[str]            # alle gefundenen .csproj
    target_framework: str            # z. B. net8.0 ('' = unbekannt)
    target_frameworks: list[str]
    assembly_name: str
    api_kind: str                    # package | central | reference | none
    api_version: str                 # Version im Projekt ('' = keine)
    files: int
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Entpacken
# --------------------------------------------------------------------------- #
def _clean_parts(name: str) -> list[str] | None:
    name = name.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise ProjectError("zip_unsafe", name)
    parts = [p for p in PurePosixPath(name).parts if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ProjectError("zip_unsafe", name)
    if not parts:
        return None
    if any(p.lower() in SKIP_DIRS for p in parts[:-1]) or parts[-1].lower() in SKIP_FILES:
        return None
    return parts


def safe_extract(data: bytes, dest: Path) -> int:
    """Entpackt das ZIP sicher (kein Zip-Slip, keine Symlinks, Größenlimits)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ProjectError("zip_invalid", str(e)) from e

    limit = config.MAX_EXTRACTED_MB * 1024 * 1024
    total = 0
    count = 0
    infos = zf.infolist()
    if len(infos) > config.MAX_FILES:
        raise ProjectError("too_many_files", str(len(infos)))

    dest.mkdir(parents=True, exist_ok=True)
    for info in infos:
        if info.is_dir():
            continue
        mode = (info.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise ProjectError("zip_unsafe", f"Symlink: {info.filename}")
        if info.flag_bits & 0x1:
            raise ProjectError("zip_encrypted", info.filename)
        parts = _clean_parts(info.filename)
        if parts is None:
            continue
        target = dest.joinpath(*parts)
        if not str(target.resolve()).startswith(str(dest.resolve()) + "/"):
            raise ProjectError("zip_unsafe", info.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            while True:
                chunk = src.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ProjectError("zip_too_big", f"> {config.MAX_EXTRACTED_MB} MB")
                out.write(chunk)
        count += 1
    if count == 0:
        raise ProjectError("zip_empty")
    return count


# --------------------------------------------------------------------------- #
# XML-Hilfen (MSBuild-Dateien)
# --------------------------------------------------------------------------- #
def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def load_xml(path: Path) -> ET.ElementTree:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    try:
        return ET.parse(path, parser=parser)
    except ET.ParseError as e:
        raise ProjectError("csproj_invalid", f"{path.name}: {e}") from e


def save_xml(tree: ET.ElementTree, path: Path) -> None:
    root = tree.getroot()
    ns = _ns(root.tag)
    if ns:
        ET.register_namespace("", ns)
    tree.write(path, encoding="utf-8", xml_declaration=False)


def _q(root: ET.Element, name: str) -> str:
    ns = _ns(root.tag)
    return f"{{{ns}}}{name}" if ns else name


def _iter(root: ET.Element, name: str):
    for el in root.iter():
        if isinstance(el.tag, str) and _local(el.tag) == name:
            yield el


def _parent_map(root: ET.Element) -> dict:
    return {c: p for p in root.iter() for c in p}


def _prop(root: ET.Element, name: str) -> str:
    for el in _iter(root, name):
        if el.text and el.text.strip():
            return el.text.strip()
    return ""


def _is_api(include: str | None) -> bool:
    if not include:
        return False
    return include.split(",")[0].strip().lower() == API_NAME


def _msbuild_files(src: Path) -> list[Path]:
    return [p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in MSBUILD_EXT]


def _rel(src: Path, p: Path) -> str:
    return p.relative_to(src).as_posix()


# --------------------------------------------------------------------------- #
# Analyse
# --------------------------------------------------------------------------- #
def _check_sdk(src: Path) -> None:
    """Nur offizielle Microsoft-SDKs zulassen (fremde SDKs bringen eigenen Build-Code mit)."""
    for f in _msbuild_files(src):
        root = load_xml(f).getroot()
        sdks = []
        if root.get("Sdk"):
            sdks += [s.strip() for s in root.get("Sdk", "").split(";") if s.strip()]
        for el in _iter(root, "Sdk"):
            sdks.append(el.get("Name", ""))
        for el in _iter(root, "Import"):
            if el.get("Sdk"):
                sdks.append(el.get("Sdk", ""))
        for s in sdks:
            if not ALLOWED_SDK.match(s):
                raise ProjectError("sdk_not_allowed", f"{_rel(src, f)}: {s}")


def _directory_props(src: Path, proj: Path, name: str) -> list[Path]:
    """Directory.Build.props/Directory.Packages.props vom Projektordner aufwärts."""
    found = []
    d = proj.parent
    while True:
        for cand in d.iterdir():
            if cand.is_file() and cand.name.lower() == name.lower():
                found.append(cand)
        if d == src:
            break
        d = d.parent
    return found


def _api_reference(src: Path, proj: Path) -> tuple[str, str]:
    root = load_xml(proj).getroot()
    for el in _iter(root, "PackageReference"):
        if _is_api(el.get("Include") or el.get("Update")):
            ver = el.get("Version") or el.get("VersionOverride") or ""
            if not ver:
                for ch in el:
                    if isinstance(ch.tag, str) and _local(ch.tag) in ("Version", "VersionOverride"):
                        ver = (ch.text or "").strip()
            if ver:
                return "package", ver
            for dp in _directory_props(src, proj, "Directory.Packages.props"):
                for pv in _iter(load_xml(dp).getroot(), "PackageVersion"):
                    if _is_api(pv.get("Include")):
                        return "central", pv.get("Version", "")
            return "package", ""
    for el in _iter(root, "Reference"):
        if _is_api(el.get("Include")):
            return "reference", ""
    for dp in _directory_props(src, proj, "Directory.Build.props"):
        for el in _iter(load_xml(dp).getroot(), "PackageReference"):
            if _is_api(el.get("Include")):
                return "package", el.get("Version", "")
    return "none", ""


def _target_frameworks(src: Path, proj: Path) -> list[str]:
    sources = [proj] + _directory_props(src, proj, "Directory.Build.props")
    for f in sources:
        root = load_xml(f).getroot()
        single = _prop(root, "TargetFramework")
        if single and "$(" not in single:
            return [normalize_tf(single)]
        multi = _prop(root, "TargetFrameworks")
        if multi and "$(" not in multi:
            return [normalize_tf(t) for t in multi.split(";") if t.strip()]
    return []


def analyze(src: Path, wanted: str | None = None) -> ProjectInfo:
    csprojs = sorted(_rel(src, p) for p in src.rglob("*.csproj") if p.is_file())
    if not csprojs:
        if any(src.rglob("*.cs")):
            raise ProjectError("no_csproj_only_cs")
        raise ProjectError("no_csproj")

    _check_sdk(src)

    if wanted:
        if wanted not in csprojs:
            raise ProjectError("csproj_not_found", wanted)
        main = wanted
    elif len(csprojs) == 1:
        main = csprojs[0]
    else:
        with_api = [c for c in csprojs if _api_reference(src, src / c)[0] != "none"]
        pool = with_api or csprojs
        main = sorted(pool, key=lambda c: (c.count("/"), c.lower()))[0]

    proj = src / main
    root = load_xml(proj).getroot()
    tfs = _target_frameworks(src, proj)
    kind, ver = _api_reference(src, proj)
    asm = _prop(root, "AssemblyName")
    if not asm or "$(" in asm:
        asm = proj.stem
    files = sum(1 for p in src.rglob("*") if p.is_file())
    return ProjectInfo(
        csproj=main,
        candidates=csprojs,
        target_framework=tfs[0] if tfs else "",
        target_frameworks=tfs,
        assembly_name=asm,
        api_kind=kind,
        api_version=ver,
        files=files,
    )


# --------------------------------------------------------------------------- #
# Vorbereitung (Version setzen, gefährliche Dateien entfernen)
# --------------------------------------------------------------------------- #
NUGET_CONFIG = f"""<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="nuget.org" value="{config.NUGET_SOURCE}" protocolVersion="3" />
  </packageSources>
  <disabledPackageSources><clear /></disabledPackageSources>
  <fallbackPackageFolders><clear /></fallbackPackageFolders>
</configuration>
"""


def _remove_unwanted(src: Path, notes: list[str]) -> None:
    for p in list(src.rglob("*")):
        if not p.is_file():
            continue
        n = p.name.lower()
        if n == "nuget.config":
            p.unlink()
            notes.append(f"ignored_nuget_config:{_rel(src, p)}")
        elif n == "global.json":
            p.unlink()
            notes.append(f"ignored_global_json:{_rel(src, p)}")
        elif n.endswith(".rsp"):
            p.unlink()
            notes.append(f"ignored_rsp:{_rel(src, p)}")


def _set_api_version(src: Path, info: ProjectInfo, version: str, notes: list[str]) -> None:
    proj = src / info.csproj
    tree = load_xml(proj)
    root = tree.getroot()

    if info.api_kind == "central":
        for dp in _directory_props(src, proj, "Directory.Packages.props"):
            t = load_xml(dp)
            changed = False
            for pv in _iter(t.getroot(), "PackageVersion"):
                if _is_api(pv.get("Include")):
                    pv.set("Version", version)
                    changed = True
            if changed:
                save_xml(t, dp)
                break
        notes.append(f"api_version_set:{version}")
        return

    if info.api_kind == "package":
        found = False
        for el in _iter(root, "PackageReference"):
            if _is_api(el.get("Include") or el.get("Update")):
                found = True
                if el.get("VersionOverride"):
                    el.set("VersionOverride", version)
                else:
                    el.set("Version", version)
                for ch in list(el):
                    if isinstance(ch.tag, str) and _local(ch.tag) in ("Version", "VersionOverride"):
                        el.remove(ch)
        if found:
            save_xml(tree, proj)
        else:  # Referenz steht in Directory.Build.props
            for dp in _directory_props(src, proj, "Directory.Build.props"):
                t = load_xml(dp)
                for el in _iter(t.getroot(), "PackageReference"):
                    if _is_api(el.get("Include")):
                        el.set("Version", version)
                save_xml(t, dp)
        notes.append(f"api_version_set:{version}")
        return

    # 'reference' (lokale DLL per HintPath) oder 'none' -> PackageReference einfügen
    parents = _parent_map(root)
    group = None
    for el in list(_iter(root, "Reference")):
        if _is_api(el.get("Include")):
            group = parents.get(el)
            if group is not None:
                group.remove(el)
    if group is None:
        group = ET.SubElement(root, _q(root, "ItemGroup"))
    pr = ET.SubElement(group, _q(root, "PackageReference"))
    pr.set("Include", "CounterStrikeSharp.API")
    pr.set("Version", version)
    pr.set("ExcludeAssets", "runtime")
    save_xml(tree, proj)
    notes.append(
        f"api_reference_replaced:{version}" if info.api_kind == "reference" else f"api_reference_added:{version}"
    )


def _retarget(src: Path, info: ProjectInfo, tf: str, notes: list[str]) -> None:
    proj = src / info.csproj
    tree = load_xml(proj)
    root = tree.getroot()
    parents = _parent_map(root)
    done = False
    for el in list(_iter(root, "TargetFrameworks")):
        parents[el].remove(el)
    for el in _iter(root, "TargetFramework"):
        el.text = tf
        done = True
    if not done:
        groups = [g for g in root if isinstance(g.tag, str) and _local(g.tag) == "PropertyGroup"]
        group = groups[0] if groups else ET.SubElement(root, _q(root, "PropertyGroup"))
        el = ET.SubElement(group, _q(root, "TargetFramework"))
        el.text = tf
    save_xml(tree, proj)
    info.target_framework = tf
    info.target_frameworks = [tf]
    notes.append(f"retargeted:{tf}")


def prepare(src: Path, info: ProjectInfo, api_version: str, retarget_tf: str | None) -> list[str]:
    notes: list[str] = []
    _remove_unwanted(src, notes)
    if api_version:
        _set_api_version(src, info, api_version, notes)
    if retarget_tf:
        _retarget(src, info, retarget_tf, notes)
    (src / "NuGet.Config").write_text(NUGET_CONFIG)
    return notes


# --------------------------------------------------------------------------- #
# Restore-Entschärfung: eigene Targets/Tasks dürfen NICHT mit Netzwerk laufen
# --------------------------------------------------------------------------- #
def _sanitize_tree(tree: ET.ElementTree) -> None:
    root = tree.getroot()
    parents = _parent_map(root)
    for el in list(root.iter()):
        if not isinstance(el.tag, str) or el is root:
            continue
        name = _local(el.tag)
        drop = False
        if name in ("Target", "UsingTask"):
            drop = True
        elif name.startswith("Restore") or name in ("NuGetPackageRoot", "NuGetAudit"):
            drop = True
        elif name == "Import":
            proj = (el.get("Project") or "").strip().lower()
            if not el.get("Sdk") and not proj.endswith(MSBUILD_EXT):
                drop = True
        if drop and el in parents:
            try:
                parents[el].remove(el)
            except ValueError:
                pass
    for attr in ("InitialTargets", "DefaultTargets"):
        root.attrib.pop(attr, None)


def sanitize_for_restore(src: Path) -> dict[Path, bytes]:
    backup: dict[Path, bytes] = {}
    for f in _msbuild_files(src):
        backup[f] = f.read_bytes()
        tree = load_xml(f)
        _sanitize_tree(tree)
        save_xml(tree, f)
    return backup


def restore_originals(backup: dict[Path, bytes]) -> None:
    for path, data in backup.items():
        path.write_bytes(data)


# --------------------------------------------------------------------------- #
# Log-Auswertung
# --------------------------------------------------------------------------- #
DIAG_RE = re.compile(
    r"^(?P<file>[^\s].*?)(?:\((?P<line>\d+),(?P<col>\d+)(?:,\d+,\d+)?\))?\s*:\s*"
    r"(?P<sev>error|warning)\s+(?P<code>[A-Z]+\d+)\s*:\s*(?P<msg>.*?)(?:\s+\[[^\]]+\])?\s*$"
)


def parse_log(log: str) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    seen = set()
    for raw in log.splitlines():
        line = raw.strip()
        m = DIAG_RE.match(line)
        if not m:
            continue
        d = m.groupdict()
        f = (d["file"] or "").replace("/src/", "")
        key = (f, d["line"], d["code"], d["msg"])
        if key in seen:
            continue
        seen.add(key)
        item = {
            "file": f,
            "line": int(d["line"]) if d["line"] else None,
            "col": int(d["col"]) if d["col"] else None,
            "code": d["code"],
            "message": d["msg"],
        }
        (errors if d["sev"] == "error" else warnings).append(item)
    return {"errors": errors, "warnings": warnings, "hints": hints_for(errors, log)}


def hints_for(errors: list[dict], log: str) -> list[str]:
    hints: list[str] = []

    def add(h: str) -> None:
        if h not in hints:
            hints.append(h)

    for e in errors:
        c, msg = e["code"], e["message"]
        if c in ("NU1202", "NU1201", "NU1213"):
            add("framework_mismatch")
        elif c in ("NU1101", "NU1102", "NU1103"):
            add("package_not_found")
        elif c in ("NU1301", "NU1100"):
            add("nuget_unreachable")
        elif c in ("CS0246", "CS0234") and "CounterStrikeSharp" in msg:
            add("missing_api")
        elif c in ("CS0246", "CS0234"):
            add("missing_reference")
        elif c in ("CS0006", "MSB9008", "MSB3202", "NU1105"):
            add("missing_project_reference")
        elif c == "NETSDK1045":
            add("sdk_too_old")
        elif c == "NETSDK1004":
            add("restore_failed")
        elif c in ("CS1705", "CS1701", "CS1702"):
            add("dependency_version")
        elif c == "MSB4019":
            add("missing_import")
        elif c in ("MSB4025", "MSB4024", "MSB4068"):
            add("csproj_invalid")
        elif c.startswith("CS") and "obsolete" in msg.lower():
            add("api_changed")
        elif c in ("CS0117", "CS1061", "CS0103", "CS1501", "CS7036"):
            add("api_changed")
    if "__TIMEOUT__" in log:
        add("timeout")
    return hints


# --------------------------------------------------------------------------- #
# Ergebnis verpacken
# --------------------------------------------------------------------------- #
EXCLUDE_OUTPUT = {"counterstrikesharp.api.dll", "counterstrikesharp.api.xml", "counterstrikesharp.api.pdb"}


def package_result(src: Path, info: ProjectInfo, configuration: str, dest_zip: Path) -> list[dict]:
    out = src / OUT_DIR
    main_dll = out / f"{info.assembly_name}.dll"
    if not main_dll.exists():
        raise ProjectError("no_output", f"{info.assembly_name}.dll")

    # Sprachdateien mitnehmen, falls das Projekt sie nicht selbst kopiert
    proj_dir = (src / info.csproj).parent
    lang = proj_dir / "lang"
    if lang.is_dir() and not (out / "lang").exists():
        shutil.copytree(lang, out / "lang")

    prefix = f"addons/counterstrikesharp/plugins/{info.assembly_name}/"
    listing: list[dict] = []
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(out.rglob("*")):
            if not p.is_file() or p.is_symlink():
                continue
            name = p.name.lower()
            if name in EXCLUDE_OUTPUT:
                continue
            if configuration == "Release" and name.endswith(".pdb"):
                continue
            rel = p.relative_to(out).as_posix()
            zf.write(p, prefix + rel)
            listing.append({"path": prefix + rel, "size": p.stat().st_size})
    return listing
