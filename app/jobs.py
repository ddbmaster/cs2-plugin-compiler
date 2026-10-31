"""Warteschlange und Worker für Kompilier-Aufträge."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config, db, project, sandbox

log = logging.getLogger("cssharp.jobs")


@dataclass
class JobSpec:
    job_id: str
    src: Path
    info: project.ProjectInfo
    api_version: str
    configuration: str
    framework: str | None
    notes: list[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)


def job_dir(job_id: str) -> Path:
    return config.JOBS_DIR / job_id


def _chown_tree(path: Path, uid: int) -> None:
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            try:
                os.lchown(os.path.join(root, name), uid, uid)
            except OSError:
                pass
    try:
        os.lchown(path, uid, uid)
    except OSError:
        pass


def _trim(text: str) -> str:
    b = text.encode("utf-8", "replace")
    if len(b) <= config.LOG_MAX_BYTES:
        return text
    return "[… gekürzt …]\n" + b[-config.LOG_MAX_BYTES:].decode("utf-8", "replace")


class JobManager:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[JobSpec] = asyncio.Queue()
        self.waiting: list[str] = []
        self.running: dict[str, str] = {}   # job_id -> phase
        self.tasks: list[asyncio.Task] = []
        # Restores nacheinander: der NuGet-Cache wird geteilt, Container haben keine gemeinsamen Sperrdateien
        self.restore_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        for i in range(config.MAX_PARALLEL):
            self.tasks.append(asyncio.create_task(self._worker(i)))
        self.tasks.append(asyncio.create_task(self._janitor()))

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()

    def queue_length(self) -> int:
        return len(self.waiting)

    def position(self, job_id: str) -> int | None:
        try:
            return self.waiting.index(job_id) + 1
        except ValueError:
            return None

    def phase(self, job_id: str) -> str | None:
        return self.running.get(job_id)

    def load(self) -> str:
        busy = len(self.running) + len(self.waiting)
        if busy <= config.MAX_PARALLEL // 2:
            return "low"
        if busy <= config.MAX_PARALLEL:
            return "medium"
        return "high"

    def full(self) -> bool:
        return len(self.waiting) >= config.MAX_QUEUE

    async def submit(self, spec: JobSpec) -> int:
        self.waiting.append(spec.job_id)
        await self.queue.put(spec)
        return len(self.waiting)

    # ------------------------------------------------------------------ #
    async def _worker(self, idx: int) -> None:
        while True:
            spec = await self.queue.get()
            try:
                if spec.job_id in self.waiting:
                    self.waiting.remove(spec.job_id)
                await self._process(spec)
            except Exception as e:  # nie den Worker sterben lassen
                log.exception("Job %s abgestürzt", spec.job_id)
                db.update_job(
                    spec.job_id, status="failed", finished=time.time(),
                    summary=f"Interner Fehler: {e}"[:300],
                )
            finally:
                self.running.pop(spec.job_id, None)
                self.queue.task_done()

    async def _process(self, spec: JobSpec) -> None:
        jid, src, info = spec.job_id, spec.src, spec.info
        started = time.time()
        uid = int(config.SANDBOX_UID)
        log_parts: list[str] = []

        # 1) Restore mit Netzwerk – mit entschärften Projektdateien
        self.running[jid] = "restoring"
        db.update_job(jid, status="restoring")
        backup = await asyncio.to_thread(project.sanitize_for_restore, src)
        await asyncio.to_thread(_chown_tree, src, uid)
        async with self.restore_lock:
            code, out = await asyncio.to_thread(sandbox.restore, jid, src, info.csproj)
        await asyncio.to_thread(project.restore_originals, backup)
        log_parts.append("=== dotnet restore ===\n" + out)

        ok = code == 0
        if ok:
            # 2) Build ohne Netzwerk
            self.running[jid] = "building"
            db.update_job(jid, status="building")
            await asyncio.to_thread(_chown_tree, src, uid)
            code, out = await asyncio.to_thread(
                sandbox.build, jid, src, info.csproj, spec.configuration, spec.framework
            )
            log_parts.append("=== dotnet build ===\n" + out)
            ok = code == 0

        full_log = "\n".join(log_parts)
        parsed = project.parse_log(full_log)
        listing: list[dict] = []
        if ok:
            try:
                listing = await asyncio.to_thread(
                    project.package_result, src, info, spec.configuration, job_dir(jid) / "result.zip"
                )
            except project.ProjectError as e:
                ok = False
                parsed["hints"].append(e.code)

        duration = round(time.time() - started, 1)
        if not ok and not parsed["errors"] and "timeout" not in parsed["hints"] and not parsed["hints"]:
            parsed["hints"].append("unknown_failure")

        result = {
            "success": ok,
            "duration": duration,
            "files": listing,
            "errors": parsed["errors"][:200],
            "warnings": parsed["warnings"][:200],
            "warning_count": len(parsed["warnings"]),
            "hints": parsed["hints"],
            "notes": spec.notes,
            "log": _trim(full_log),
            "assembly": info.assembly_name,
            "api_version": spec.api_version,
            "framework": spec.framework or info.target_framework,
            "configuration": spec.configuration,
        }
        (job_dir(jid) / "result.json").write_text(json.dumps(result))

        # Quellcode sofort entfernen – gebraucht wird nur noch das Ergebnis
        await asyncio.to_thread(shutil.rmtree, src, True)

        first_error = parsed["errors"][0] if parsed["errors"] else None
        summary = (
            f"{first_error['code']}: {first_error['message']}"[:300]
            if first_error
            else ("OK" if ok else ", ".join(parsed["hints"]) or "Fehler")
        )
        db.update_job(
            jid,
            status="success" if ok else "failed",
            finished=time.time(),
            duration=duration,
            errors=len(parsed["errors"]),
            warnings=len(parsed["warnings"]),
            summary=summary,
            log=_trim(full_log)[-50_000:],
        )
        db.add_stat(result["framework"], spec.api_version, ok)

    # ------------------------------------------------------------------ #
    async def _janitor(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.cleanup)
            except Exception:
                log.exception("Aufräumen fehlgeschlagen")
            await asyncio.sleep(300)

    def cleanup(self, max_age_min: int | None = None) -> int:
        """Löscht Job-Ordner, die älter als JOB_TTL_MIN sind und nicht mehr laufen."""
        ttl = (config.JOB_TTL_MIN if max_age_min is None else max_age_min) * 60
        now = time.time()
        removed = 0
        active = set(self.running) | set(self.waiting)
        if config.JOBS_DIR.exists():
            for d in config.JOBS_DIR.iterdir():
                if d.name in active or not d.is_dir():
                    continue
                try:
                    if now - d.stat().st_mtime >= ttl:
                        shutil.rmtree(d, ignore_errors=True)
                        removed += 1
                except OSError:
                    pass
        db.prune(config.HISTORY_DAYS)
        return removed


manager = JobManager()
