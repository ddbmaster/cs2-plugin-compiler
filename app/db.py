"""SQLite-Speicher für Jobs und dauerhafte Statistik."""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any

from . import config

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    created REAL NOT NULL,
    finished REAL,
    ip_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    project TEXT,
    api_version TEXT,
    framework TEXT,
    configuration TEXT,
    duration REAL,
    errors INTEGER DEFAULT 0,
    warnings INTEGER DEFAULT 0,
    summary TEXT,
    log TEXT
);
CREATE INDEX IF NOT EXISTS jobs_ip ON jobs(ip_hash, created);
CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created);

CREATE TABLE IF NOT EXISTS stats (
    framework TEXT NOT NULL,
    api_version TEXT NOT NULL,
    success INTEGER NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (framework, api_version, success)
);

CREATE TABLE IF NOT EXISTS admin_attempts (
    ip_hash TEXT NOT NULL,
    ts REAL NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


_conn: sqlite3.Connection | None = None


def init() -> None:
    global _conn
    _conn = _connect()
    with _lock:
        _conn.executescript(SCHEMA)
        # Jobs, die beim letzten Neustart hängen geblieben sind
        _conn.execute(
            "UPDATE jobs SET status='failed', summary='Abgebrochen durch Neustart' "
            "WHERE status IN ('queued','restoring','building')"
        )
        _conn.commit()


@contextmanager
def tx():
    assert _conn is not None
    with _lock:
        try:
            yield _conn
            _conn.commit()
        except Exception:
            _conn.rollback()
            raise


def insert_job(**fields: Any) -> None:
    cols = ",".join(fields)
    marks = ",".join("?" for _ in fields)
    with tx() as c:
        c.execute(f"INSERT INTO jobs ({cols}) VALUES ({marks})", tuple(fields.values()))


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    sets = ",".join(f"{k}=?" for k in fields)
    with tx() as c:
        c.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))


def get_job(job_id: str) -> dict | None:
    with tx() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def count_recent(ip_hash: str, seconds: int) -> int:
    since = time.time() - seconds
    with tx() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM jobs WHERE ip_hash=? AND created>? "
            "AND status NOT IN ('mismatch','rejected')",
            (ip_hash, since),
        ).fetchone()
    return int(row[0])


def count_active(ip_hash: str) -> int:
    with tx() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM jobs WHERE ip_hash=? AND status IN ('queued','restoring','building')",
            (ip_hash,),
        ).fetchone()
    return int(row[0])


def add_stat(framework: str, api_version: str, success: bool) -> None:
    with tx() as c:
        c.execute(
            "INSERT INTO stats (framework, api_version, success, count) VALUES (?,?,?,1) "
            "ON CONFLICT(framework, api_version, success) DO UPDATE SET count=count+1",
            (framework or "?", api_version or "?", 1 if success else 0),
        )


def stats() -> dict:
    with tx() as c:
        rows = c.execute(
            "SELECT framework, success, SUM(count) AS n FROM stats GROUP BY framework, success"
        ).fetchall()
        versions = c.execute(
            "SELECT api_version, SUM(count) AS n, SUM(CASE WHEN success=1 THEN count ELSE 0 END) AS ok "
            "FROM stats GROUP BY api_version ORDER BY n DESC LIMIT 10"
        ).fetchall()
    out: dict = {"success": {}, "failed": {}, "total_success": 0, "total_failed": 0}
    for r in rows:
        key = "success" if r["success"] else "failed"
        out[key][r["framework"]] = int(r["n"])
        out["total_" + key] += int(r["n"])
    out["versions"] = [
        {"version": r["api_version"], "total": int(r["n"]), "success": int(r["ok"])} for r in versions
    ]
    return out


def recent_jobs(limit: int = 200) -> list[dict]:
    with tx() as c:
        rows = c.execute(
            "SELECT id, created, finished, ip_hash, status, project, api_version, framework, "
            "configuration, duration, errors, warnings, summary FROM jobs "
            "ORDER BY created DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def prune(history_days: int) -> None:
    cutoff = time.time() - history_days * 86400
    with tx() as c:
        c.execute("DELETE FROM jobs WHERE created<?", (cutoff,))
        c.execute("DELETE FROM admin_attempts WHERE ts<?", (time.time() - 86400,))


def admin_attempt(ip_hash: str) -> int:
    """Speichert einen fehlgeschlagenen Login und liefert die Anzahl der letzten 15 Min."""
    now = time.time()
    with tx() as c:
        c.execute("INSERT INTO admin_attempts (ip_hash, ts) VALUES (?,?)", (ip_hash, now))
        row = c.execute(
            "SELECT COUNT(*) FROM admin_attempts WHERE ip_hash=? AND ts>?", (ip_hash, now - 900)
        ).fetchone()
    return int(row[0])


def admin_attempts(ip_hash: str) -> int:
    with tx() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM admin_attempts WHERE ip_hash=? AND ts>?",
            (ip_hash, time.time() - 900),
        ).fetchone()
    return int(row[0])
