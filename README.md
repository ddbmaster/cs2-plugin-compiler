# CS2 Plugin Compiler 1.3.4

Online-Compiler für **CounterStrikeSharp**-Plugins (C#) und **Metamod:Source**-Plugins (C++) für CS2, zum Selbsthosten auf deinem Ubuntu-Server.
Besucher laden ihr Projekt als `.zip` hoch, wählen die CounterStrikeSharp.API-Version und bekommen das fertige Plugin zurück.

## Funktionen

- Upload als `.zip` (Projekt mit `.csproj` + `.cs`), `bin/`, `obj/` und `.git/` werden ignoriert
- Eingebauter Code-Editor mit Projektbaum, neue Dateien anlegen/löschen, Demo-Projekt
- Auswahl der CounterStrikeSharp.API-Version (live von NuGet, mit Suche) oder „aus dem Projekt übernehmen“
- **Versionsprüfung vor dem Build**: Passen Ziel-Framework und API-Version nicht zusammen, schlägt der Compiler die passende Version vor oder stellt das Framework auf Wunsch um
- Automatische Korrekturen: lokale `CounterStrikeSharp.API.dll`-Referenz → NuGet-Paket, fehlende Referenz ergänzt
- Release/Debug, Fehlerliste mit Klick auf Datei:Zeile (springt in den Editor), Ursachen-Hinweise, komplette Compiler-Ausgabe
- Ergebnis-ZIP ist fertig aufgebaut: `addons/counterstrikesharp/plugins/<Name>/…`
- Warteschlange, Limit pro IP und Stunde, Statistik nach Framework
- Deutsch/Englisch, Hell/Dunkel/Automatisch, mobil nutzbar
- Admin-Bereich unter `/admin` (Aufträge mit Logs, Statistik, Wartung)
- **Metamod:Source-Plugins (C++)** (ab 1.2.0): aus Git-Repository oder .zip, Linux-Build mit AMBuild
- **Editor für Metamod-Projekte** (ab 1.3.0): Repository oder ZIP im Browser öffnen, Code ändern, direkt kompilieren, Fehler per Klick anspringen, Projekt als .zip sichern
- **Editor-Größe anpassbar** (ab 1.3.1): Höhe unten ziehen, Editor an der Grenze zu den Einstellungen breiter ziehen (ab 1.3.2), ganze Seite am rechten Rand bis zur vollen Bildschirmbreite ziehen (ab 1.3.3), Dateiliste seitlich ziehen, „Breit“ für volle Seitenbreite – wird im Browser gemerkt
- **Design und Texte im Admin-Bereich** (ab 1.1.0): Seitenname, Untertitel und Logo, alle Stilvariablen (Farben getrennt für Hell/Dunkel, Schrift, Eckenradius), eigenes CSS sowie alle Überschriften und Texte auf Deutsch/Englisch anpassbar – inkl. Sicherung herunterladen/einspielen

## Metamod:Source-Compiler (ab 1.2.0)

Oben auf der Seite zwischen **CounterStrikeSharp (C#)** und **Metamod:Source (C++)** umschalten.

- Quelle: öffentliches Git-Repository (github.com, gitlab.com, codeberg.org, bitbucket.org – einstellbar über `GIT_HOSTS`) inkl. Submodulen, oder Upload als `.zip`
- Unterstützt werden Projekte mit **AMBuild** (`configure.py` + `AMBuildScript`), wie alle Plugins von Source2ZE/AlliedModders
- Gebaut wird die **Linux-Version** (`.so`) mit Clang in der echten Steam-Laufzeitumgebung (SteamRT3, optional SteamRT4) gegen Metamod:Source und das aktuelle CS2-SDK
- Ergebnis-ZIP enthält `addons/<plugin>/bin/linuxsteamrt64/*.so` und die `.vdf` – einfach nach `game/csgo/` entpacken
- Ablauf: Repository laden (mit Netzwerk, es wird **nur geklont**, kein Projektcode ausgeführt) → Bauen **ohne Netzwerk**, mit denselben Schutzmaßnahmen wie beim C#-Build
- Fehlende `hl2sdk-manifests` (typisch bei GitHub-ZIP-Downloads) werden automatisch ergänzt; ohne Git-Tags wird die eingegebene Versionsnummer verwendet

**Code ändern (ab 1.3.0):** Bei Git-Quelle auf „Im Editor öffnen“ klicken bzw. eine .zip auswählen – das Projekt öffnet sich rechts im Editor. Änderungen werden beim Kompilieren mitgeschickt; mit „Projekt als .zip“ sicherst du deinen Stand (der Editor speichert nichts dauerhaft auf dem Server).

**Erster Start:** Die Build-Umgebung wird automatisch gebaut. Dafür lädt Docker den Source2ZE-Build-Container sowie Metamod:Source und das CS2-SDK (mehrere GB, einige Minuten). Den Stand siehst du oben in der Statusanzeige („Metamod: Wird eingerichtet“) und im Admin-Bereich.

**Nach CS2-Updates:** Admin-Bereich → Wartung → „Metamod/CS2-SDK aktualisieren“.

Einstellungen in der `.env` (alle optional): `METAMOD_ENABLED`, `METAMOD_RUNTIMES`, `MM_FETCH_TIMEOUT`, `MM_BUILD_TIMEOUT`, `MM_MAX_REPO_MB`, `GIT_HOSTS`.

## Design und Texte anpassen

Im Admin-Bereich unter **Design** und **Texte**:

- **Stilvariablen**: Die ganze Oberfläche nutzt nur CSS-Variablen (`--accent`, `--panel`, `--text` …). Leeres Feld = Standardwert.
- **Eigenes CSS**: wird nach dem Standard-CSS geladen und kann alles überschreiben.
- **Texte**: jeder Text der Oberfläche über seinen Schlüssel (z. B. `hero.title`) ersetzbar. Eigene Texte haben Vorrang vor `HERO_TITLE_*`/`HERO_TEXT_*` aus der `.env`.
- Gespeichert wird in `DATA_DIR/customize.json` (bleibt bei Updates erhalten, der vorherige Stand liegt als `customize.json.bak` daneben).
- **Notfall**: Hat eigenes CSS den Admin-Bereich unbrauchbar gemacht, `/admin?safe=1` öffnen – dort wird es nicht geladen.

## Sicherheit

Hochgeladener Code ist fremder Code. Deshalb:

1. **Restore** (NuGet-Pakete laden) läuft in einem eigenen Container. Vorher werden alle eigenen MSBuild-Targets/Tasks aus den Projektdateien entfernt, NuGet-Quellen sind fest auf nuget.org gesetzt, fremde MSBuild-SDKs werden abgelehnt.
2. **Build** läuft in einem Container **ohne Netzwerk**.
3. Beide Container: eigener Benutzer (kein root), schreibgeschütztes System, keine Rechte (`cap-drop ALL`), RAM-/CPU-/Prozess- und Zeitlimits. Eingebunden ist nur der Ordner des jeweiligen Auftrags.
4. Der Quellcode wird direkt nach dem Build gelöscht, das Ergebnis nach `JOB_TTL_MIN` Minuten.
5. IP-Adressen werden nur als Hash gespeichert. Die Seite lädt keine externen Skripte, Schriften oder Tracker.

> Hinweis: Der Web-Container bekommt Zugriff auf den Docker-Socket, um die Build-Container zu starten. Er selbst führt keinen hochgeladenen Code aus. Der Port ist nur lokal (`127.0.0.1`) erreichbar.

## Installation

Voraussetzung: Ubuntu-Server mit root-Zugang. Docker wird bei Bedarf vom Installationsskript eingerichtet.

```bash
tar xzf cssharp-compiler_1.3.4.tar.gz
cd cssharp-compiler
sudo ./install.sh
```

Das Skript prüft/installiert Docker, legt die `.env` mit einem zufälligen Admin-Passwort an, setzt den Datenordner auf `data/` im Installationsverzeichnis, lädt das .NET-SDK-Image (ca. 900 MB) und startet den Compiler lokal auf `127.0.0.1:<PORT>` (Standard 8085).

Der Installationsordner ist frei wählbar – im Code gibt es keine festen Pfade oder Domains. In den Vorlagen unter `deploy/` steht `example.com` als Platzhalter für deine eigene Domain.

### Webserver einrichten

**Variante A – Unterpfad `https://example.com/compiler/` (Standard, `BASE_PATH=/compiler` in der `.env`)**

Keine Subdomain und kein neues Zertifikat nötig – der vorhandene Webserver deiner Domain leitet nur `/compiler/` an den Compiler weiter.

- **nginx**: Inhalt von `deploy/nginx-unterpfad.conf` in den vorhandenen `server { … }`-Block deiner Domain (der mit `listen 443 ssl`) einfügen, dann `nginx -t && systemctl reload nginx`
- **Apache**: `a2enmod proxy proxy_http headers`, Inhalt von `deploy/apache-unterpfad.conf` in den vorhandenen `<VirtualHost *:443>` deiner Domain einfügen, dann `apachectl configtest && systemctl reload apache2`

**Variante B – eigene Subdomain `https://compiler.example.com` (`BASE_PATH` leer lassen)**

- DNS: `compiler CNAME example.com`
- **nginx**: `deploy/nginx.conf` → `/etc/nginx/sites-available/`, aktivieren, `certbot --nginx -d compiler.example.com`
- **Apache**: `deploy/apache.conf` → `/etc/apache2/sites-available/`, `a2enmod proxy proxy_http headers`, aktivieren, `certbot --apache -d compiler.example.com`

### Einstellungen

Alles steht in der `.env` (Beschreibung direkt in der Datei). Nach Änderungen:

```bash
docker compose up -d
```

Wichtig für Deutschland: `IMPRESSUM_URL` und `DATENSCHUTZ_URL` auf deine echten Seiten setzen. In der Datenschutzerklärung den Compiler kurz erwähnen (Upload wird nur zum Kompilieren verarbeitet und nach spätestens 60 Minuten gelöscht, IP nur gehasht für das Stundenlimit).

## Bedienung im Alltag

| Was | Befehl |
|---|---|
| Status / Logs | `docker compose ps` · `docker compose logs -f` |
| Neu starten | `docker compose restart` |
| Stoppen | `docker compose down` |
| Update (neue Version + .NET-Sicherheitsupdates) | `sudo ./update.sh` |

Das .NET-SDK-Image ab und zu aktualisieren (`./update.sh` oder im Admin-Bereich „.NET-SDK-Image aktualisieren“).

## Ressourcen

Pro gleichzeitigem Build bis zu `BUILD_MEMORY` RAM (Standard 2 GB) und `BUILD_CPUS` Kerne. Bei `MAX_PARALLEL=2` solltest du also rund 4 GB RAM frei haben. Läuft auf demselben Server dein CS2-Server, setze `MAX_PARALLEL=1` und ggf. `BUILD_CPUS=1`, damit der Gameserver nicht ruckelt.

Plattenplatz: SDK-Image ca. 900 MB, NuGet-Cache wächst mit der Zeit (im Admin-Bereich sichtbar und leerbar).

## Aufbau

```
app/            Python-Anwendung (FastAPI)
  main.py       Seiten + API
  project.py    ZIP prüfen, Projekt analysieren/anpassen, Log auswerten
  sandbox.py    Restore/Build in Docker-Containern
  jobs.py       Warteschlange
  nuget.py      Versionsliste von NuGet
  static/       Oberfläche (HTML/CSS/JS, CodeMirror und JSZip lokal)
deploy/         Webserver-Beispiele
```

## Autor

[ddbmaster](https://ddbmaster.com)
