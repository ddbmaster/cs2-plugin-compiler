"""Führt Restore und Build in abgeschotteten Docker-Containern aus."""
from __future__ import annotations

import threading
from pathlib import Path

import docker
from docker.errors import APIError, DockerException, ImageNotFound, NotFound

from . import config

_client = None
_state = {"image": "unknown", "error": "", "pulling": False}
_state_lock = threading.Lock()

ENV = {
    "HOME": "/tmp/home",
    "DOTNET_CLI_HOME": "/tmp/home",
    "NUGET_PACKAGES": "/nuget/packages",
    "NUGET_HTTP_CACHE_PATH": "/tmp/nuget-http",
    "NUGET_PLUGINS_CACHE_PATH": "/tmp/nuget-plugins",
    "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
    "DOTNET_NOLOGO": "1",
    "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
    "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false",
    "DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE": "1",
    "DOTNET_CLI_USE_MSBUILD_SERVER": "0",
    "MSBUILDDISABLENODEREUSE": "1",
    "MSBUILDTERMINALLOGGER": "off",
    "NUGET_XMLDOC_MODE": "skip",
}

RESTORE_PROPS = [
    f"-p:RestoreSources={config.NUGET_SOURCE}",
    "-p:RestoreConfigFile=/src/NuGet.Config",
    "-p:RestoreAdditionalProjectSources=",
    "-p:RestoreAdditionalProjectFallbackFolders=",
    "-p:RestoreFallbackFolders=",
    "-p:NuGetAudit=false",
]


def client():
    global _client
    if _client is None:
        _client = docker.from_env(timeout=60)
    return _client


def status() -> dict:
    try:
        client().ping()
        docker_ok = True
    except (DockerException, OSError) as e:
        with _state_lock:
            _state["error"] = str(e)[:300]
        docker_ok = False
    with _state_lock:
        return {"docker": docker_ok, **_state}


def ensure_image(force_pull: bool = False) -> None:
    """Lädt das .NET-SDK-Image (blockierend, im Hintergrund-Thread aufrufen)."""
    with _state_lock:
        if _state["pulling"]:
            return
        _state["pulling"] = True
    try:
        c = client()
        if not force_pull:
            try:
                c.images.get(config.SDK_IMAGE)
                with _state_lock:
                    _state.update(image="ready", error="")
                return
            except ImageNotFound:
                pass
        with _state_lock:
            _state["image"] = "pulling"
        repo, _, tag = config.SDK_IMAGE.rpartition(":")
        c.images.pull(repo or config.SDK_IMAGE, tag=tag or "latest")
        with _state_lock:
            _state.update(image="ready", error="")
    except (DockerException, OSError) as e:
        with _state_lock:
            _state.update(image="error", error=str(e)[:300])
    finally:
        with _state_lock:
            _state["pulling"] = False


def _run(
    job_id: str,
    phase: str,
    src: Path,
    command: list[str],
    network: bool,
    timeout: int,
) -> tuple[int, str]:
    """Startet einen Container, wartet mit Zeitlimit und liefert (Exitcode, Ausgabe)."""
    c = client()
    container = c.containers.run(
        config.SDK_IMAGE,
        command,
        name=f"cssc-{phase}-{job_id[:12]}",
        detach=True,
        user=f"{config.SANDBOX_UID}:{config.SANDBOX_UID}",
        working_dir="/src",
        environment=ENV,
        volumes={
            str(src): {"bind": "/src", "mode": "rw"},
            str(config.NUGET_DIR / "packages"): {
                "bind": "/nuget/packages",
                "mode": "rw" if network else "ro",
            },
        },
        network_mode="bridge" if network else "none",
        mem_limit=config.BUILD_MEMORY,
        memswap_limit=config.BUILD_MEMORY,
        nano_cpus=int(config.BUILD_CPUS * 1e9),
        pids_limit=512,
        read_only=True,
        tmpfs={"/tmp": "rw,exec,nosuid,size=1g"},
        cap_drop=["ALL"],
        security_opt=["no-new-privileges"],
        ipc_mode="private",
        labels={"cssharp-compiler": "1", "cssharp-compiler.job": job_id},
        auto_remove=False,
    )
    timed_out = False
    try:
        try:
            result = container.wait(timeout=timeout)
            code = int(result.get("StatusCode", 1))
        except Exception:  # Zeitüberschreitung (requests ReadTimeout) o. Ä.
            timed_out = True
            code = 124
            try:
                container.kill()
            except (APIError, NotFound):
                pass
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", "replace")
        if timed_out:
            logs += f"\n__TIMEOUT__ ({phase} > {timeout}s)\n"
        return code, logs
    finally:
        try:
            container.remove(force=True)
        except (APIError, NotFound):
            pass


def restore(job_id: str, src: Path, csproj: str) -> tuple[int, str]:
    cmd = ["dotnet", "restore", csproj, "--configfile", "/src/NuGet.Config", "-nodeReuse:false", *RESTORE_PROPS]
    return _run(job_id, "restore", src, cmd, network=True, timeout=config.RESTORE_TIMEOUT)


def build(job_id: str, src: Path, csproj: str, configuration: str, framework: str | None) -> tuple[int, str]:
    cmd = [
        "dotnet", "build", csproj,
        "-c", configuration,
        "--no-restore",
        "-o", "/src/__out",
        "-nodeReuse:false",
        "-p:UseSharedCompilation=false",
        "-p:GenerateDocumentationFile=false",
        *RESTORE_PROPS,
    ]
    if framework:
        cmd += ["-f", framework]
    return _run(job_id, "build", src, cmd, network=False, timeout=config.BUILD_TIMEOUT)


def cleanup_orphans() -> int:
    """Entfernt übrig gebliebene Sandbox-Container (z. B. nach Absturz)."""
    removed = 0
    try:
        for cont in client().containers.list(all=True, filters={"label": "cssharp-compiler=1"}):
            try:
                cont.remove(force=True)
                removed += 1
            except (APIError, NotFound):
                pass
    except (DockerException, OSError):
        pass
    return removed


def nuget_cache_size() -> int:
    total = 0
    base = config.NUGET_DIR / "packages"
    if base.exists():
        for p in base.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                pass
    return total
