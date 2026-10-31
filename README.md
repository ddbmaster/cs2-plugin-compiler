# CS2 Plugin Compiler 1.0.3

Online-Compiler für **CounterStrikeSharp**-Plugins (CS2), zum Selbsthosten auf deinem Ubuntu-Server.
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
tar xzf cssharp-compiler_1.0.3.tar.gz
cd cssharp-compiler
sudo ./install.sh
```

Das Skript prüft/installiert Docker, legt die `.env` mit einem zufälligen Admin-Passwort an, lädt das .NET-SDK-Image (ca. 900 MB) und startet den Compiler auf `127.0.0.1:8085`.

### Webserver einrichten

**Variante A – Unterpfad `https://Your-name.de/compiler/` (Standard, `BASE_PATH=/compiler` in der `.env`)**

Keine Subdomain und kein neues Zertifikat nötig – der vorhandene Webserver von Your-name.de leitet nur `/compiler/` an den Compiler weiter.

- **nginx**: Inhalt von `deploy/nginx-unterpfad.conf` in den vorhandenen `server { … }`-Block von Your-name.de (der mit `listen 443 ssl`) einfügen, dann `nginx -t && systemctl reload nginx`
- **Apache**: `a2enmod proxy proxy_http headers`, Inhalt von `deploy/apache-unterpfad.conf` in den vorhandenen `<VirtualHost *:443>` von Your-name.de einfügen, dann `apachectl configtest && systemctl reload apache2`

**Variante B – eigene Subdomain `https://compiler.Your-name.de` (`BASE_PATH` leer lassen)**

- DNS: `compiler CNAME Your-name.de`
- **nginx**: `deploy/nginx.conf` → `/etc/nginx/sites-available/`, aktivieren, `certbot --nginx -d compiler.Your-name.de`
- **Apache**: `deploy/apache.conf` → `/etc/apache2/sites-available/`, `a2enmod proxy proxy_http headers`, aktivieren, `certbot --apache -d compiler.Your-name.de`

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
