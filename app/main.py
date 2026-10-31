"""CS2 Plugin Compiler – Web-Oberfläche und API."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, db, jobs, nuget, project, sandbox

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cssharp")

STATIC = Path(__file__).parent / "static"
SECRET = b""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global SECRET
    config.ensure_dirs()
    SECRET = config.secret_key()
    db.init()
    await asyncio.to_thread(sandbox.cleanup_orphans)
    asyncio.get_running_loop().run_in_executor(None, sandbox.ensure_image)
    jobs.manager.start()
    asyncio.create_task(nuget.get_versions())
    yield
    await jobs.manager.stop()


api = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
api.mount("/static", StaticFiles(directory=STATIC), name="static")
app = api  # wird am Dateiende ggf. durch den Unterpfad-Wrapper ersetzt


@api.middleware("http")
async def security_headers(request: Request, call_next):
    resp: Response = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'",
    )
    return resp


# --------------------------------------------------------------------------- #
# Hilfen
# --------------------------------------------------------------------------- #
def client_ip(request: Request) -> str:
    if config.TRUST_PROXY:
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            # letzter Eintrag = vom eigenen Webserver angehängt (vorne kann der Besucher fälschen)
            return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "0.0.0.0"


def ip_hash(request: Request) -> str:
    # Datensparsam: IP-Adressen werden nur gehasht gespeichert
    return hmac.new(SECRET, client_ip(request).encode(), hashlib.sha256).hexdigest()[:20]


def err(code: str, status: int = 400, detail: str = "", **extra) -> JSONResponse:
    return JSONResponse({"error": code, "detail": detail, **extra}, status_code=status)


def _site_texts() -> dict:
    """Eigene Texte aus der .env, die die Standardtexte der Oberfläche ersetzen."""
    out: dict = {"de": {}, "en": {}}
    for lang in ("de", "en"):
        title = getattr(config, f"HERO_TITLE_{lang.upper()}")
        text = getattr(config, f"HERO_TEXT_{lang.upper()}")
        if title:
            out[lang]["hero.title"] = title
        if text:
            out[lang]["hero.text"] = text
    return out


def render(name: str) -> HTMLResponse:
    html = (STATIC / name).read_text(encoding="utf-8")
    repl = {
        "{{SITE_NAME}}": escape(config.SITE_NAME),
        "{{SITE_OWNER}}": escape(config.SITE_OWNER),
        "{{SITE_OWNER_URL}}": escape(config.SITE_OWNER_URL),
        "{{VERSION}}": config.VERSION,
        "{{BASE}}": escape(config.BASE_PATH),
        "{{SITE_SUBTITLE}}": escape(config.SITE_SUBTITLE),
        "{{SITE_LOGO}}": escape(config.SITE_LOGO),
        "{{SITE_TEXTS}}": escape(json.dumps(_site_texts(), ensure_ascii=False), quote=True),
    }
    for k, v in repl.items():
        html = html.replace(k, v)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


# --------------------------------------------------------------------------- #
# Seiten
# --------------------------------------------------------------------------- #
@api.get("/", response_class=HTMLResponse)
async def index():
    return render("index.html")


@api.get("/hilfe", response_class=HTMLResponse)
@api.get("/help", response_class=HTMLResponse)
async def help_page():
    return render("help.html")


@api.get("/admin", response_class=HTMLResponse)
async def admin_page():
    return render("admin.html")


@api.get("/robots.txt")
async def robots():
    return Response("User-agent: *\nDisallow: /admin\nDisallow: /api/\n", media_type="text/plain")


# --------------------------------------------------------------------------- #
# Öffentliche API
# --------------------------------------------------------------------------- #
@api.get("/api/info")
async def info():
    return {
        "site_name": config.SITE_NAME,
        "owner": config.SITE_OWNER,
        "owner_url": config.SITE_OWNER_URL,
        "impressum_url": config.IMPRESSUM_URL,
        "datenschutz_url": config.DATENSCHUTZ_URL,
        "version": config.VERSION,
        "max_upload_mb": config.MAX_UPLOAD_MB,
        "rate_limit_per_hour": config.RATE_LIMIT_PER_HOUR,
        "sdk_max_major": config.SDK_MAX_MAJOR,
        "job_ttl_min": config.JOB_TTL_MIN,
    }


@api.get("/api/versions")
async def versions():
    vs = await nuget.get_versions()
    latest = next((v["version"] for v in vs if not v["prerelease"]), vs[0]["version"] if vs else None)
    return {"versions": vs, "latest": latest}


@api.get("/api/status")
async def status():
    s = await asyncio.to_thread(sandbox.status)
    sandbox_state = "running" if s["docker"] and s["image"] == "ready" else (
        "pulling" if s["image"] == "pulling" else ("down" if not s["docker"] else s["image"])
    )
    return {
        "sandbox": sandbox_state,
        "load": jobs.manager.load(),
        "queue": jobs.manager.queue_length(),
        "running": len(jobs.manager.running),
    }


@api.get("/api/stats")
async def stats():
    return db.stats()


def _resolve_version(choice: str, info: project.ProjectInfo, vs: list[dict]) -> tuple[str, dict | None]:
    latest = next((v for v in vs if not v["prerelease"]), vs[0] if vs else None)
    choice = (choice or "latest").strip()
    if choice == "latest":
        if latest is None:
            raise project.ProjectError("versions_unavailable")
        return latest["version"], latest
    if choice == "project":
        pv = info.api_version
        if info.api_kind in ("package", "central") and pv and not any(ch in pv for ch in "*[]()"):
            return pv, nuget.find(vs, pv)
        if info.api_kind in ("package", "central") and pv:
            return "", None  # Platzhalter-Version (z. B. "*") unverändert lassen
        if latest is None:
            raise project.ProjectError("versions_unavailable")
        return latest["version"], latest
    if not all(c.isalnum() or c in ".-" for c in choice) or len(choice) > 40:
        raise project.ProjectError("unknown_version", choice)
    entry = nuget.find(vs, choice)
    if vs and entry is None:
        raise project.ProjectError("unknown_version", choice)
    return choice, entry


@api.post("/api/compile")
async def compile_project(
    request: Request,
    file: UploadFile = File(...),
    api_version: str = Form("latest"),
    configuration: str = Form("Release"),
    csproj: str = Form(""),
    retarget: str = Form(""),
):
    ih = ip_hash(request)
    if configuration not in ("Release", "Debug"):
        return err("bad_configuration")
    if jobs.manager.full():
        return err("queue_full", 503)
    if db.count_active(ih) > 0:
        return err("already_running", 429)
    if config.RATE_LIMIT_PER_HOUR and db.count_recent(ih, 3600) >= config.RATE_LIMIT_PER_HOUR:
        return err("rate_limited", 429, limit=config.RATE_LIMIT_PER_HOUR)

    # Upload mit Größenlimit einlesen
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    data = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > limit:
            return err("upload_too_big", 413, limit=config.MAX_UPLOAD_MB)
    if not data:
        return err("zip_empty")

    job_id = secrets.token_hex(16)
    jdir = jobs.job_dir(job_id)
    src = jdir / "src"

    def fail(e: project.ProjectError, status_name: str = "rejected") -> JSONResponse:
        shutil.rmtree(jdir, ignore_errors=True)
        db.insert_job(
            id=job_id, created=time.time(), finished=time.time(), ip_hash=ih,
            status=status_name, summary=f"{e.code} {e.detail}"[:300],
        )
        return err(e.code, 400, e.detail)

    try:
        await asyncio.to_thread(project.safe_extract, bytes(data), src)
        info = await asyncio.to_thread(project.analyze, src, csproj or None)
        vs = await nuget.get_versions()
        version, entry = _resolve_version(api_version, info, vs)
    except project.ProjectError as e:
        return fail(e)

    pkg_tfs = entry["frameworks"] if entry else []
    project_tf = info.target_framework
    framework_arg: str | None = None

    # Ziel-Framework: anpassen auf Wunsch, sonst prüfen
    retarget_tf: str | None = None
    if retarget:
        wanted = retarget if retarget != "auto" else (pkg_tfs[0] if pkg_tfs else "")
        wanted = nuget.normalize_tf(wanted)
        if not nuget.tf_major(wanted) or nuget.tf_major(wanted) > config.SDK_MAX_MAJOR:
            return fail(project.ProjectError("bad_framework", wanted))
        retarget_tf = wanted
        project_tf = wanted
    else:
        pm = nuget.tf_major(project_tf)
        if pm and pm > config.SDK_MAX_MAJOR:
            return fail(project.ProjectError("framework_too_new", project_tf))
        if len(info.target_frameworks) > 1:
            usable = [t for t in info.target_frameworks if nuget.compatible(t, pkg_tfs)
                      and (nuget.tf_major(t) or 0) <= config.SDK_MAX_MAJOR]
            if usable:
                framework_arg = sorted(usable, key=lambda t: nuget.tf_major(t) or 0)[-1]
                project_tf = framework_arg
        if project_tf and pkg_tfs and not nuget.compatible(project_tf, pkg_tfs):
            suggestion = nuget.best_for_framework(vs, project_tf)
            retarget_option = next(
                (t for t in pkg_tfs if (nuget.tf_major(t) or 99) <= config.SDK_MAX_MAJOR), None
            )
            shutil.rmtree(jdir, ignore_errors=True)
            db.insert_job(
                id=job_id, created=time.time(), finished=time.time(), ip_hash=ih,
                status="mismatch", project=info.assembly_name, api_version=version,
                framework=project_tf, summary=f"{project_tf} vs {','.join(pkg_tfs)}",
            )
            return JSONResponse({
                "job_id": job_id,
                "status": "mismatch",
                "project": _project_json(info),
                "api_version": version,
                "package_frameworks": pkg_tfs,
                "suggested_version": suggestion["version"] if suggestion else None,
                "suggested_version_frameworks": suggestion["frameworks"] if suggestion else [],
                "retarget_framework": retarget_option,
            })

    try:
        notes = await asyncio.to_thread(project.prepare, src, info, version, retarget_tf)
    except project.ProjectError as e:
        return fail(e)

    if info.api_version and version and info.api_version != version and info.api_kind in ("package", "central"):
        notes.insert(0, f"api_version_changed:{info.api_version}>{version}")

    spec = jobs.JobSpec(
        job_id=job_id, src=src, info=info, api_version=version or info.api_version,
        configuration=configuration, framework=framework_arg, notes=notes,
    )
    db.insert_job(
        id=job_id, created=time.time(), ip_hash=ih, status="queued",
        project=info.assembly_name, api_version=spec.api_version,
        framework=project_tf or "?", configuration=configuration,
    )
    position = await jobs.manager.submit(spec)
    return {
        "job_id": job_id,
        "status": "queued",
        "position": position,
        "project": _project_json(info),
        "api_version": spec.api_version,
        "notes": notes,
    }


def _project_json(info: project.ProjectInfo) -> dict:
    return {
        "csproj": info.csproj,
        "candidates": info.candidates,
        "target_framework": info.target_framework,
        "target_frameworks": info.target_frameworks,
        "assembly": info.assembly_name,
        "api_kind": info.api_kind,
        "api_version": info.api_version,
        "files": info.files,
    }


def _valid_id(job_id: str) -> bool:
    return len(job_id) == 32 and all(c in "0123456789abcdef" for c in job_id)


@api.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    if not _valid_id(job_id):
        return err("not_found", 404)
    row = db.get_job(job_id)
    if not row:
        return err("not_found", 404)
    out = {
        "job_id": job_id,
        "status": row["status"],
        "project": row["project"],
        "api_version": row["api_version"],
        "framework": row["framework"],
        "configuration": row["configuration"],
    }
    if row["status"] == "queued":
        out["position"] = jobs.manager.position(job_id)
    if row["status"] in ("success", "failed"):
        rj = jobs.job_dir(job_id) / "result.json"
        if rj.exists():
            out["result"] = json.loads(rj.read_text())
            out["downloadable"] = (jobs.job_dir(job_id) / "result.zip").exists()
        else:
            out["expired"] = True
            out["summary"] = row["summary"]
    return out


@api.get("/api/jobs/{job_id}/download")
async def job_download(job_id: str):
    if not _valid_id(job_id):
        return err("not_found", 404)
    row = db.get_job(job_id)
    path = jobs.job_dir(job_id) / "result.zip"
    if not row or not path.exists():
        return err("expired", 404)
    name = "".join(c for c in (row["project"] or "plugin") if c.isalnum() or c in "-_.") or "plugin"
    ver = (row["api_version"] or "").replace("/", "")
    return FileResponse(
        path, media_type="application/zip",
        filename=f"{name}_{row['configuration'] or 'Release'}_css{ver}.zip",
    )


# --------------------------------------------------------------------------- #
# Admin
# --------------------------------------------------------------------------- #
COOKIE = "cssc_admin"


def _make_token() -> str:
    exp = str(int(time.time()) + 8 * 3600)
    sig = hmac.new(SECRET, f"admin:{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def _is_admin(request: Request) -> bool:
    if not config.ADMIN_PASSWORD:
        return False
    tok = request.cookies.get(COOKIE, "")
    exp, _, sig = tok.partition(".")
    if not exp.isdigit() or int(exp) < time.time():
        return False
    good = hmac.new(SECRET, f"admin:{exp}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(good, sig)


@api.post("/api/admin/login")
async def admin_login(request: Request):
    if not config.ADMIN_PASSWORD:
        return err("admin_disabled", 403)
    ih = ip_hash(request)
    if db.admin_attempts(ih) >= 5:
        return err("too_many_attempts", 429)
    try:
        body = await request.json()
    except ValueError:
        body = {}
    pw = str(body.get("password", ""))
    if not hmac.compare_digest(pw.encode(), config.ADMIN_PASSWORD.encode()):
        db.admin_attempt(ih)
        await asyncio.sleep(1)
        return err("wrong_password", 401)
    resp = JSONResponse({"ok": True})
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(COOKIE, _make_token(), httponly=True, samesite="strict", secure=secure,
                    max_age=8 * 3600, path=(config.BASE_PATH or "") + "/")
    return resp


@api.post("/api/admin/logout")
async def admin_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path=(config.BASE_PATH or "") + "/")
    return resp


@api.get("/api/admin/overview")
async def admin_overview(request: Request):
    if not _is_admin(request):
        return err("unauthorized", 401, enabled=bool(config.ADMIN_PASSWORD))
    st = await asyncio.to_thread(sandbox.status)
    disk = shutil.disk_usage(config.DATA_DIR)
    return {
        "stats": db.stats(),
        "jobs": db.recent_jobs(200),
        "queue": jobs.manager.queue_length(),
        "running": dict(jobs.manager.running),
        "sandbox": st,
        "nuget_cache_bytes": await asyncio.to_thread(sandbox.nuget_cache_size),
        "disk_free": disk.free,
        "disk_total": disk.total,
        "config": {
            "sdk_image": config.SDK_IMAGE,
            "max_parallel": config.MAX_PARALLEL,
            "max_queue": config.MAX_QUEUE,
            "rate_limit_per_hour": config.RATE_LIMIT_PER_HOUR,
            "max_upload_mb": config.MAX_UPLOAD_MB,
            "build_memory": config.BUILD_MEMORY,
            "build_cpus": config.BUILD_CPUS,
            "restore_timeout": config.RESTORE_TIMEOUT,
            "build_timeout": config.BUILD_TIMEOUT,
            "job_ttl_min": config.JOB_TTL_MIN,
            "history_days": config.HISTORY_DAYS,
        },
        "version": config.VERSION,
    }


@api.get("/api/admin/jobs/{job_id}/log")
async def admin_job_log(job_id: str, request: Request):
    if not _is_admin(request):
        return err("unauthorized", 401)
    row = db.get_job(job_id) if _valid_id(job_id) else None
    if not row:
        return err("not_found", 404)
    return {"log": row["log"] or "", "summary": row["summary"]}


@api.post("/api/admin/action/{action}")
async def admin_action(action: str, request: Request):
    if not _is_admin(request):
        return err("unauthorized", 401)
    if action == "cleanup":
        n = await asyncio.to_thread(jobs.manager.cleanup, 0)
        return {"ok": True, "removed": n}
    if action == "clear-nuget":
        if jobs.manager.running:
            return err("busy", 409)
        base = config.NUGET_DIR / "packages"
        await asyncio.to_thread(shutil.rmtree, base, True)
        config.ensure_dirs()
        return {"ok": True}
    if action == "refresh-versions":
        vs = await nuget.get_versions(force=True)
        return {"ok": True, "count": len(vs)}
    if action == "pull-image":
        asyncio.get_running_loop().run_in_executor(None, sandbox.ensure_image, True)
        return {"ok": True}
    return err("unknown_action", 404)


# --------------------------------------------------------------------------- #
# Betrieb unter einem Unterpfad (z. B. https://ddbmaster.de/compiler/)
# --------------------------------------------------------------------------- #
class BasePath:
    """Setzt root_path, damit alle Routen unter BASE_PATH erreichbar sind."""

    def __init__(self, inner, base: str):
        self.inner = inner
        self.base = base

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path == self.base and scope["type"] == "http":
                qs = scope.get("query_string", b"").decode()
                resp = RedirectResponse(self.base + "/" + (("?" + qs) if qs else ""), status_code=308)
                await resp(scope, receive, send)
                return
            if path.startswith(self.base + "/"):
                scope = dict(scope, root_path=scope.get("root_path", "") + self.base)
        await self.inner(scope, receive, send)


if config.BASE_PATH:
    app = BasePath(api, config.BASE_PATH)

