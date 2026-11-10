# CS2 Plugin Compiler 1.3.4

Online compiler for **CounterStrikeSharp** plugins (C#) and **Metamod:Source** plugins (C++) for CS2, for self-hosting on your own Ubuntu server.
Visitors upload their project as a `.zip`, pick the CounterStrikeSharp.API version and get the finished plugin back.

## Features

- Upload as `.zip` (project with `.csproj` + `.cs`); `bin/`, `obj/` and `.git/` are ignored
- Built-in code editor with project tree, create/delete files, demo project
- Choose the CounterStrikeSharp.API version (live from NuGet, with search) or "use version from project"
- **Version check before the build**: if target framework and API version don't match, the compiler suggests the right version or switches the framework on request
- Automatic fixes: local `CounterStrikeSharp.API.dll` reference → NuGet package, missing reference added
- Release/Debug, error list with click on file:line (jumps into the editor), hints on likely causes, full compiler output
- Result ZIP is ready to use: `addons/counterstrikesharp/plugins/<Name>/…`
- Queue, limit per IP and hour, statistics by framework
- German/English, light/dark/auto theme, mobile-friendly
- Admin area at `/admin` (jobs with logs, statistics, maintenance)
- **Metamod:Source plugins (C++)**: from a Git repository or .zip, Linux build with AMBuild
- **Editor for Metamod projects**: open a repository or ZIP in the browser, edit code, compile directly, jump to errors with one click, save the project as .zip
- **Resizable editor**: drag the bottom edge to change the height, drag the border to the settings panel to make the editor wider, drag the right edge of the page up to full screen width, resize the file list sideways, "Wide" for full page width – remembered in the browser
- **Design and texts in the admin area**: site name, subtitle and logo, all style variables (colors separately for light/dark, font, corner radius), custom CSS and all headings and texts in German/English can be customized – including downloading/restoring a backup

## Metamod:Source compiler

Switch between **CounterStrikeSharp (C#)** and **Metamod:Source (C++)** at the top of the page.

- Source: public Git repository (github.com, gitlab.com, codeberg.org, bitbucket.org – configurable via `GIT_HOSTS`) including submodules, or upload as `.zip`
- Supported are projects using **AMBuild** (`configure.py` + `AMBuildScript`), like all plugins from Source2ZE/AlliedModders
- The **Linux version** (`.so`) is built with Clang in the real Steam runtime environment (SteamRT3, optionally SteamRT4) against Metamod:Source and the current CS2 SDK
- The result ZIP contains `addons/<plugin>/bin/linuxsteamrt64/*.so` and the `.vdf` – just extract it into `game/csgo/`
- Process: fetch repository (with network access, it is **only cloned**, no project code is executed) → build **without network access**, with the same protections as the C# build
- Missing `hl2sdk-manifests` (typical for GitHub ZIP downloads) are added automatically; without Git tags the version number you entered is used

**Editing code:** With a Git source, click "Open in editor", or select a .zip – the project opens in the editor on the right. Your changes are sent along when compiling; use "Project as .zip" to save your work (the editor does not store anything permanently on the server).

**First start:** The build environment is built automatically. Docker downloads the Source2ZE build container plus Metamod:Source and the CS2 SDK (several GB, takes a few minutes). You can follow the progress in the status bar at the top ("Metamod: Setting up") and in the admin area.

**After CS2 updates:** Admin area → Maintenance → "Update Metamod/CS2 SDK".

Settings in the `.env` (all optional): `METAMOD_ENABLED`, `METAMOD_RUNTIMES`, `MM_FETCH_TIMEOUT`, `MM_BUILD_TIMEOUT`, `MM_MAX_REPO_MB`, `GIT_HOSTS`.

## Customizing design and texts

In the admin area under **Design** and **Texts**:

- **Style variables**: the whole interface uses CSS variables only (`--accent`, `--panel`, `--text` …). Empty field = default value.
- **Custom CSS**: loaded after the default CSS and can override everything.
- **Texts**: every text of the interface can be replaced via its key (e.g. `hero.title`). Custom texts take priority over `HERO_TITLE_*`/`HERO_TEXT_*` from the `.env`.
- Stored in `DATA_DIR/customize.json` (kept during updates; the previous state is saved next to it as `customize.json.bak`).
- **Emergency**: if custom CSS has made the admin area unusable, open `/admin?safe=1` – custom CSS is not loaded there.

## Security

Uploaded code is untrusted code. Therefore:

1. **Restore** (downloading NuGet packages) runs in its own container. Beforehand, all custom MSBuild targets/tasks are removed from the project files, NuGet sources are fixed to nuget.org, and third-party MSBuild SDKs are rejected.
2. **Build** runs in a container **without network access**.
3. Both containers: separate user (not root), read-only system, no privileges (`cap-drop ALL`), RAM/CPU/process and time limits. Only the folder of the respective job is mounted.
4. Source code is deleted right after the build, the result after `JOB_TTL_MIN` minutes.
5. IP addresses are only stored as a hash. The site loads no external scripts, fonts or trackers.

> Note: The web container gets access to the Docker socket so it can start the build containers. It never executes uploaded code itself. The port is only reachable locally (`127.0.0.1`).

## Installation

Requirement: Ubuntu server with root access. Docker is set up by the installation script if needed.

```bash
tar xzf cssharp-compiler_1.3.4.tar.gz
cd cssharp-compiler
sudo ./install.sh
```

The script checks/installs Docker, creates the `.env` with a random admin password, sets the data folder to `data/` inside the installation directory, downloads the .NET SDK image (about 900 MB) and starts the compiler locally on `127.0.0.1:<PORT>` (default 8085).

The installation folder can be chosen freely – there are no fixed paths or domains in the code. In the templates under `deploy/`, `example.com` is a placeholder for your own domain.

### Setting up the web server

**Option A – sub-path `https://example.com/compiler/` (default, `BASE_PATH=/compiler` in the `.env`)**

No subdomain and no new certificate needed – your domain's existing web server just forwards `/compiler/` to the compiler.

- **nginx**: paste the contents of `deploy/nginx-unterpfad.conf` into your domain's existing `server { … }` block (the one with `listen 443 ssl`), then run `nginx -t && systemctl reload nginx`
- **Apache**: run `a2enmod proxy proxy_http headers`, paste the contents of `deploy/apache-unterpfad.conf` into your domain's existing `<VirtualHost *:443>`, then run `apachectl configtest && systemctl reload apache2`

**Option B – separate subdomain `https://compiler.example.com` (leave `BASE_PATH` empty)**

- DNS: `compiler CNAME example.com`
- **nginx**: `deploy/nginx.conf` → `/etc/nginx/sites-available/`, enable it, `certbot --nginx -d compiler.example.com`
- **Apache**: `deploy/apache.conf` → `/etc/apache2/sites-available/`, `a2enmod proxy proxy_http headers`, enable it, `certbot --apache -d compiler.example.com`

### Settings

Everything is configured in the `.env` (descriptions are in the file itself). After changes:

```bash
docker compose up -d --force-recreate
```

Put text values with spaces or special characters in single quotes, e.g. `SITE_OWNER='My Clan'`.

Important for Germany: set `IMPRESSUM_URL` (legal notice) and `DATENSCHUTZ_URL` (privacy policy) to your real pages (empty = link is hidden). Briefly mention the compiler in your privacy policy (uploads are only processed for compiling and deleted after 60 minutes at the latest; IP addresses are only stored as a hash for the hourly limit).

## Day-to-day operation

| What | Command |
|---|---|
| Status / logs | `docker compose ps` · `docker compose logs -f` |
| Restart | `docker compose restart` |
| Stop | `docker compose down` |
| Update (new version + .NET security updates) | `sudo ./update.sh` |

Update the .NET SDK image from time to time (`./update.sh` or "Update .NET SDK image" in the admin area).

## Resources

Each concurrent build uses up to `BUILD_MEMORY` of RAM (default 2 GB) and `BUILD_CPUS` cores. With `MAX_PARALLEL=2` you should have about 4 GB of free RAM. If your CS2 server runs on the same machine, set `MAX_PARALLEL=1` and possibly `BUILD_CPUS=1` so the game server doesn't lag.

Disk space: SDK image about 900 MB, the NuGet cache grows over time (visible and clearable in the admin area).

## Structure

```
app/            Python application (FastAPI)
  main.py       Pages + API
  project.py    Check ZIP, analyze/adjust project, parse logs
  sandbox.py    Restore/build in Docker containers
  jobs.py       Queue
  nuget.py      Version list from NuGet
  static/       Interface (HTML/CSS/JS, CodeMirror and JSZip bundled locally)
deploy/         Web server examples
```

## Author

[ddbmaster](https://ddbmaster.com)
