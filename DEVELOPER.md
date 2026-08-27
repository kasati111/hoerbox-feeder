# hoerbox-feeder – Entwicklerdokumentation

> **Zielgruppe:** Nachfolgende Entwickler, die das Projekt übernehmen, pflegen
> oder erweitern.  Dieses Dokument erklärt die Architektur, alle relevanten
> Designentscheidungen und bekannte Fallstricke.

---

## 1. Überblick

**hoerbox-feeder** ist eine selbst-gehostete Webanwendung (FastAPI + SQLite),
die es ermöglicht, Audio-Inhalte von YouTube, Spotify und Podcasts automatisch
auf eine SD-Karte für den [hörbert](https://www.hoerbert.com/) – einen
Audioplayer für Kinder – zu laden. hoerbox-feeder ist ein inoffizielles
Community-Projekt ohne jede Verbindung zum Hersteller des hörbert.

```
Nutzer (Browser) → FastAPI (Port 8080) → yt-dlp/spotdl → Audio-Dateien
                                        ↓
                                   SQLite-DB (Queue/Status)
                                        ↓
                                   APScheduler (Abo-Sync)
                                        ↓
                                   Worker-Thread (Download)
```

Der hörbert selbst hat **9 Tasten (0–8)**, jede entspricht einem Kanal
(SD-Karte-Verzeichnis `0/` – `8/`).  Die App verwaltet Inhalt für alle
9 Kanäle.

---

## 2. Verzeichnisstruktur

```
hoerbox-feeder/
├── app/
│   ├── main.py          – FastAPI-App, lifespan (startup/shutdown)
│   ├── config.py        – Konfiguration (env-vars, Pfade)
│   ├── database.py      – SQLAlchemy-Setup + session helpers
│   ├── models.py        – ORM-Modelle (Channel, Item, Subscription)
│   ├── crud.py          – Datenbankoperationen
│   ├── downloader.py    – yt-dlp + Spotify-Integration
│   ├── audio.py         – ffmpeg-Pipeline (loudnorm, mono/stereo, MP3)
│   ├── worker.py        – Download-Worker-Thread
│   ├── scheduler.py     – APScheduler (Abo-Sync, yt-dlp-Update)
│   ├── feed.py          – Podcast-Feed-Generator (feedgen)
│   ├── sd_export.py     – SD-Karten-Export-Hilfsfunktionen
│   └── routers/
│       ├── ui.py        – HTML-Routen (Jinja2)
│       ├── api.py       – REST-API-Routen (JSON)
│       ├── feed_routes.py – RSS/Atom-Feed-Routen
│       └── media.py     – Mediendatei-Auslieferung
├── templates/           – Jinja2-HTML-Templates
├── static/              – CSS, JS, Icons
├── tests/               – pytest-Tests
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── schnellstart.sh      – Installationsskript für Raspberry Pi / Linux-Server
```

---

## 3. Datenfluss

### Einmaliger Download (manuell)

```
POST /api/channels/{n}/items   (URL vom Nutzer)
  → crud.create_item() → Status: 'queued'
  → worker.py holt Job aus Warteschlange
  → downloader.analyze(url) – Typ erkennen, Playlist aufklappen
  → downloader.download_audio(url, dest_dir) – yt-dlp
  → audio.py – ffmpeg loudnorm + mono/stereo + 128k MP3
  → CRUD: Status 'done', Dateipfad speichern
```

### Abo-Sync (automatisch)

```
APScheduler → scheduler.py → crud.list_due_subscriptions()
  → downloader.analyze(abo_url) – neue Einträge holen
  → nur neue URLs (Idempotenz per URL-Hash) → worker-Queue
```

---

## 4. Abhängigkeiten und Versionsanforderungen

### 4.1 Python-Pakete (`requirements.txt`)

| Paket | Mindestversion | Wichtig warum |
|---|---|---|
| `fastapi` | ≥ 0.110 | Moderne lifespan-API |
| `starlette` | ≥ 1.0.0 | **Kritisch – siehe §5.1** |
| `uvicorn[standard]` | ≥ 0.27 | Websocket-Support im `[standard]` extra |
| `yt-dlp[default]` | ≥ 2026.1.1 | EJS-Solver für YouTube n-challenge |
| `apscheduler` | ≥ 3.10 | Abo-Sync-Scheduler |
| `feedgen` | ≥ 1.0 | RSS/Atom-Feed-Erzeugung |
| `sqlalchemy` | ≥ 2.0 | Neue Session-API |

### 4.2 System-Abhängigkeiten (Dockerfile / schnellstart.sh)

| Tool | Version | Zweck |
|---|---|---|
| `ffmpeg` | beliebig | Audio-Konvertierung (loudnorm, mono/stereo, MP3) |
| `node` | **≥ 22** | yt-dlp EJS-Solver für YouTube n-challenge |
| `spotdl` | ≥ 4.5 | Spotify-Metadaten (nur Metadaten, kein Download!) |

**Node.js 22** muss über NodeSource installiert werden – Debian/Ubuntu `nodejs`
Paket liefert v18, das yt-dlp ab 2026 ablehnt.

### 4.3 spotdl-Installation (Sonderfall)

spotdl deklariert `fastapi<0.104`, wir brauchen `fastapi≥0.110`.  Lösung:

```dockerfile
# spotdl's fastapi-Konflikt umgehen:
RUN pip install --no-cache-dir \
        beautifulsoup4 python-slugify soundcloud-v2 spotipyfree \
    && pip install --no-cache-dir --no-deps spotdl
```

`--no-deps` installiert spotdl ohne seine Abhängigkeiten zu erzwingen.
Die fehlenden Deps werden manuell davor installiert.
spotdl verwendet fastapi nur für sein optionales OAuth-Web-UI – das nutzen
wir nicht; Spotify-Metadaten funktionieren ohne fastapi.

---

## 5. Bekannte Fallstricke

### 5.1 starlette-API-Versionsbruch (WICHTIGSTER PUNKT)

Die `TemplateResponse`-Signatur hat sich zwischen starlette 0.27 und 1.0
geändert:

```python
# starlette < 1.0 (ALT – NICHT VERWENDEN):
templates.TemplateResponse("index.html", {"request": request, ...})
#                           ^ name zuerst, request IM Context-Dict

# starlette ≥ 1.0 (NEU – im aktuellen Code):
templates.TemplateResponse(request, "index.html", {...})
#                           ^ request zuerst, name zweiter Parameter
```

Das Projekt nutzt starlette ≥ 1.0 (`requirements.txt` + `fastapi≥0.110` zieht
starlette 1.x automatisch).  **Alle Aufrufe in `app/routers/ui.py` müssen das
neue Format nutzen.**  Das alte Format erzeugt in starlette ≥ 1.0 den Fehler:

```
TypeError: unhashable type: 'dict'   (interner Starlette-Fehler)
→ FastAPI gibt HTTP 500 Internal Server Error zurück
```

Das war der Hauptfehler, der dieses Projekt anfangs immer auf der Startseite
kaputt machte.  Nie auf starlette < 1.0 downgraden – das würde alle 5 Routen
in `ui.py` brechen.

### 5.2 yt-dlp: ytsearch1 gibt ein Playlist-Dict zurück

Wenn `ytsearch1:artist - titel` als URL übergeben wird (kommt von der
Spotify-Integration), liefert yt-dlp ein Meta-Dict mit `_type: 'playlist'`
und `entries: [...]`.  Das echte Ergebnis steckt in `entries[0]`.

Der Code in `download_audio()` enthält deshalb diesen Unwrap:

```python
if info.get("_type") == "playlist" and info.get("entries"):
    real = info["entries"][0]
    if real is not None:
        info = real
```

**Ohne diesen Unwrap fehlt `info["requested_downloads"]` und die Datei kann
nicht gefunden werden** → RuntimeError.

### 5.3 spotdl Singleton

`SpotifyClient` (in spotdl) darf pro Prozess nur einmal initialisiert werden.
Ein zweites `Spotdl(...)` im selben Prozess wirft einen Exception.

Lösung in `downloader.py`: Module-level Singleton mit `threading.Lock`:

```python
_spotdl_instance = None
_spotdl_lock = threading.Lock()

def _get_spotdl():
    global _spotdl_instance
    if _spotdl_instance is None:
        with _spotdl_lock:
            if _spotdl_instance is None:
                _spotdl_instance = Spotdl(client_id=..., client_secret=...)
    return _spotdl_instance
```

### 5.4 Node.js-Pfad für yt-dlp

yt-dlp sucht `node` im PATH.  Im Docker-Container ist `/usr/bin/node` vorhanden,
aber wenn jemand Node.js anderswo installiert, schlägt der EJS-Solver lautlos
fehl → alle YouTube-Downloads scheitern mit Fehlercode 403.

`_base_ydl_opts()` in `downloader.py` sucht deshalb explizit nach `node`:

```python
def _node_path() -> Optional[str]:
    for candidate in ("node", "/usr/bin/node", "/usr/local/bin/node"):
        found = shutil.which(candidate)
        if found:
            return found
    return None
```

Und setzt `opts["js_runtimes"] = {"node": {"path": node}}`.

### 5.5 yt-dlp: `prepare_filename()` außerhalb des `with`-Blocks nicht verfügbar

Das yt-dlp-Objekt schließt seinen Cache nach dem `with`-Block.
`ydl.prepare_filename(info)` kann danach nicht mehr aufgerufen werden.
Datei-Lokalisierung basiert deshalb auf `info["requested_downloads"][0]["filepath"]`
oder dem Muster `dest_dir / f"{info['id']}.{info['ext']}"`.

### 5.6 anyio-Versionskonflikt durch spotdl Pre-Deps

`soundcloud-v2` und `spotipyfree` (die vor spotdl manuell installiert werden)
haben Abhängigkeiten, die `anyio` auf Version 3.x downgraden können.
`fastapi`/`uvicorn` brauchen aber `anyio>=4.0`.

Das Symptom ist ein HTTP 500 auf **jeder Seite** mit diesem Log-Fehler:

```
KeyError: 'asyncio'
ImportError: cannot import name 'ExceptionGroup' from 'anyio._core._exceptions'
```

**Ursache:** `anyio 3.x` hat kein `ExceptionGroup` in `_exceptions.py`, aber
`anyio 4.x` erwartet es dort.  Wenn nach dem Haupt-`pip install` die Pre-Deps
anyio downgraden, ist der Zustand inkonsistent.

**Fix im Dockerfile:** Nach dem spotdl-Installationsblock anyio explizit erzwingen:

```dockerfile
RUN pip install --no-cache-dir \
        beautifulsoup4 python-slugify soundcloud-v2 spotipyfree \
    && pip install --no-cache-dir --no-deps spotdl \
    && pip install --no-cache-dir "anyio>=4.0,<5"
```

Zusätzlich steht `anyio>=4.0` in `requirements.txt` als dokumentierte Mindestversion.

### 5.7 spotdl: nur Metadaten, kein Audio

`_resolve_spotify()` ruft spotdl **nur für Metadaten** auf (Künstler, Titel).
Der eigentliche Download erfolgt über yt-dlp mit einem `ytsearch1:`-Query.
Das ist wichtig, weil spotdl seinen eigenen yt-dlp-Prozess hat, der unsere
Cookies-Datei und Node.js-Konfiguration nicht kennt.

---

## 6. Konfiguration

Alle Einstellungen werden über Umgebungsvariablen gesteuert:

| Variable | Standard | Bedeutung |
|---|---|---|
| `DATA_DIR` | `/data` | Basisverzeichnis für alle Daten |
| `AUDIO_DIR` | `$DATA_DIR/audio` | Audio-Dateien pro Kanal (`0/` – `8/`) |
| `DB_DIR` | `$DATA_DIR/db` | Verzeichnis der SQLite-Datenbank |
| `DB_PATH` | `$DB_DIR/hoerbert.sqlite3` | Vollständiger DB-Pfad |
| `PORT` | `8080` | HTTP-Port |
| `HOST` | `0.0.0.0` | Bind-Adresse |
| `TZ` | `Europe/Berlin` | Zeitzone für Scheduler |
| `AUDIO_BITRATE` | `128k` | CBR-Bitrate der MP3-Ausgabe |
| `AUDIO_SAMPLE_RATE` | `44100` | Sample-Rate der MP3-Ausgabe |
| `DEFAULT_RETENTION` | `20` | Standardanzahl Dateien pro Kanal |
| `MAX_INITIAL_PLAYLIST_ITEMS` | `60` | Maximale Anzahl Items beim ersten Abo-Sync |
| `STORAGE_WARN_MB` | `100` | Warnschwelle freier Speicher in MB |
| `LEGAL_NOTICE` | *(leer)* | Optionaler Hinweistext im Footer |
| `SELFTEST_URL` | *(leer)* | URL für wöchentlichen Selbsttest |

Für Docker: in `docker-compose.yml` unter `environment:` setzen.
Für lokale Entwicklung: als Shell-Export vor dem Start:

```bash
DATA_DIR=/tmp/hoerbox-test python -m uvicorn app.main:app --port 8080
```

---

## 7. Spotify-Integration

### Funktionsweise

1. Nutzer gibt Spotify-URL ein (Track, Album oder Playlist).
2. `_is_spotify(url)` erkennt `open.spotify.com`.
3. `_resolve_spotify(url)` ruft spotdl auf → erhält Liste von `Song`-Objekten
   mit Künstler und Titel.
4. Für jeden Song wird ein `SourceEntry(url="ytsearch1:Künstler - Titel")`
   erzeugt.
5. `download_audio("ytsearch1:...")` sucht auf YouTube und lädt das
   erste Ergebnis herunter.
6. Fallback: wenn YouTube nichts findet → `ytsearchmusic1:...` (YouTube Music).

### Credentials

Die Client-ID/Secret in `downloader.py` sind öffentliche Demo-Credentials von
spotdl (im spotdl-Quellcode öffentlich einsehbar).  Sie können durch eigene
Spotify-App-Credentials ersetzt werden:

```python
_SPOTDL_CLIENT_ID = "..."   # aus https://developer.spotify.com/dashboard
_SPOTDL_CLIENT_SECRET = "..."
```

---

## 8. Deployment

Zwei Wege, je nachdem ob der Zielserver direkten Zugriff auf GitHub hat.

### Weg A: Git-basiert (empfohlen, siehe auch README)

```bash
git clone https://github.com/kasati111/hoerbox-feeder.git
cd hoerbox-feeder
docker compose up -d --build

# Logs verfolgen
docker compose logs -f
```

### Weg B: Tarball-basiert (kein Git/Internetzugang auf dem Zielserver)

Für Server ohne Zugriff auf GitHub (z. B. ein abgeschottetes Heimnetz-Gerät,
auf das nur per `scp` kopiert wird). Das Archiv lokal bauen und übertragen:

```bash
# Lokal, im Repo-Verzeichnis:
tar czf hoerbox-feeder-deploy.tar.gz --exclude=.git .
scp hoerbox-feeder-deploy.tar.gz user@zielserver:/opt/
```

**Erstinstallation** – `schnellstart.sh` prüft Docker, legt
`/opt/hoerbox-feeder` an, entpackt das Archiv dorthin und baut/startet den
Container (`docker compose up -d --build`):

```bash
cd /opt
chmod +x schnellstart.sh   # aus dem entpackten Archiv, falls nicht schon
sudo ./schnellstart.sh
```

**Updates** einer bestehenden Tarball-Installation – `update.sh` prüft das
neue Archiv auf Vollständigkeit (fängt abgebrochene Uploads ab), sichert den
aktuellen Code nach `backup_<timestamp>/` (Rollback möglich), entpackt das
neue Archiv darüber, baut das Image ohne Cache neu (`--no-cache`, damit
geänderte Templates/Static-Dateien sicher übernommen werden) und macht
danach einen kurzen Health-Check:

```bash
cd /opt/hoerbox-feeder
# neues hoerbox-feeder-deploy.tar.gz vorher dorthin kopiert haben
./update.sh
```

Rollback bei Problemen steht am Ende der Skript-Ausgabe (`cp -r
backup_<timestamp>/* . && docker compose up -d --build`).

Für **beide Wege** gilt: Kanal-Farben/-Namen werden beim Container-Start
automatisch aus `app/config.py` synchronisiert (siehe `crud.seed_channels()`)
– kein manueller Datenbank-Befehl nötig, auch nicht nach einem Update.

### Produktions-URL

Standard: `http://<deine-server-ip>:8080`

Der Server lauscht auf allen Interfaces (`0.0.0.0`).
**Nicht direkt ins Internet exponieren** – kein Auth, keine TLS.

### Cookies (YouTube-Authentifizierung)

Um YouTube-Einschränkungen auf Server-IPs zu umgehen:

1. Browser-Cookies mit der Erweiterung „Get cookies.txt LOCALLY" exportieren
   (auf einem normalen PC, in einem eingeloggten YouTube-Account).
2. Datei speichern unter: `/opt/hoerbox-feeder-data/cookies.txt`
   (in Docker gemountet als `/data/cookies.txt`).
3. `downloader._cookies_path()` erkennt die Datei automatisch und setzt
   `cookiefile` in den yt-dlp-Optionen.

---

## 9. Lokale Entwicklung

```bash
# Virtuelle Umgebung
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# App lokal starten (DATA_DIR zeigt auf ein beschreibbares Verzeichnis)
DATA_DIR=/tmp/hoerbox-dev uvicorn app.main:app --reload --port 8080
```

Wichtig: `DATA_DIR` muss existieren und beschreibbar sein.  `/data` existiert
nur im Docker-Container.

---

## 10. Tests

```bash
# Alle Tests ausführen
DATA_DIR=/tmp/hoerbox-test pytest tests/ -v

# Einzelne Testdatei
pytest tests/test_downloader.py -v
```

### Testabdeckung

| Datei | Was wird getestet |
|---|---|
| `test_channel_seed.py` | Initialisierung und Idempotenz der 9 Kanäle |
| `test_idempotency.py` | Duplikat-URL-Erkennung pro Kanal |
| `test_playlist_limit.py` | MAX_INITIAL_PLAYLIST_ITEMS-Begrenzung |
| `test_queue_position.py` | Warteschlangenposition (1-basiert) |
| `test_retention.py` | Retention-Policy (älteste Dateien löschen) |
| `test_sort_index.py` | Reihenfolge der Items pro Kanal |
| `test_subscription_sync.py` | Abo-Sync: neue/bekannte Einträge |

Die Tests verwenden eine In-Memory-SQLite-Datenbank und mocken yt-dlp (kein
echter Netzwerkzugriff).

---

## 11. Architektur-Entscheidungen

### Warum kein celery/redis?

Das Projekt läuft auf einem Raspberry Pi ohne Redis.  Ein einfacher
Python-`threading.Thread` als Worker reicht aus und hat keine externen
Abhängigkeiten.

### Warum SQLite statt PostgreSQL?

Einzelnutzer, kein Hochlast-Szenario.  SQLite ist wartungsärmer und
benötigt keine separate Datenbankinstallation.

### Warum `_base_ydl_opts()` als zentrale Funktion?

Alle yt-dlp-Aufrufe (in `analyze()` und `download_audio()`) teilen sich
dieselben Basisoptionen (cookies, js_runtimes, quiet).  Ändert sich ein
Parameter (z.B. neuer Node-Pfad), muss er nur an einer Stelle angepasst werden.

### Warum spotdl nur für Metadaten?

spotdl hat seinen eigenen internen yt-dlp-Prozess, der unsere Konfiguration
(cookies, Node.js-Pfad) nicht kennt.  Er würde auf Server-IPs scheitern.
Indem wir spotdl nur für Spotify-API-Metadaten verwenden und den eigentlichen
Download über unser konfiguriertes yt-dlp laufen lassen, funktioniert die
Spotify-Integration auch in eingeschränkten Netzwerkumgebungen.

---

## 12. Changelog (Session 2025-08)

Diese Änderungen wurden in einer Entwicklungs-Session eingeführt:

### Fehler behoben: HTTP 500 Internal Server Error (Startseite)

**Ursache:** `fastapi≥0.110` zieht `starlette≥1.0` als Abhängigkeit.
In starlette 1.0 hat `TemplateResponse` eine neue Signatur:
`(request, name, context)` statt `(name, context)`.  Der alte Code verwendete
die veraltete Signatur → `TypeError: unhashable type: 'dict'` intern →
HTTP 500 auf **allen** HTML-Seiten.

**Fix:** In `app/routers/ui.py` alle 5 `TemplateResponse`-Aufrufe von
`templates.TemplateResponse("name.html", ctx)` auf
`templates.TemplateResponse(request, "name.html", ctx)` umgestellt.
In `requirements.txt` explizit `starlette>=1.0.0` dokumentiert.

### Spotify-Unterstützung hinzugefügt

- `app/downloader.py`: `_is_spotify()`, `_resolve_spotify()`, `_get_spotdl()`
  (Singleton), `_ytmusic_fallback_url()`, `_try_download()`.
- `app/downloader.py`: `download_audio()` entpackt den `ytsearch1:`-Playlist-
  Wrapper von yt-dlp.
- `app/main.py`: spotdl wird beim Start automatisch mitgeupdatet.
- `Dockerfile`: Node.js 22 über NodeSource; spotdl mit `--no-deps`.
- `requirements.txt`: `starlette>=1.0.0`; spotdl aus requirements entfernt
  (wird über Dockerfile installiert).
- `templates/index.html`: Placeholder-Text „YouTube, Spotify oder einem Podcast".

---

## 13. Häufige Probleme

| Symptom | Wahrscheinliche Ursache | Lösung |
|---|---|---|
| HTTP 500 + `KeyError: 'asyncio'` + `ImportError: ExceptionGroup` | anyio 3.x durch spotdl Pre-Deps | Dockerfile: `pip install "anyio>=4.0,<5"` am Ende der spotdl-RUN-Zeile (§5.6) |
| HTTP 500 auf allen Seiten | Falsche `TemplateResponse`-Signatur | Starlette-Version prüfen; ui.py-Aufrufe kontrollieren (§5.1) |
| YouTube-Downloads scheitern mit 403 | Node.js fehlt oder zu alt | `node --version` im Container; NodeSource v22 nötig |
| YouTube-Downloads scheitern mit 403 (trotz Node) | Fehlende Cookies | cookies.txt hinterlegen (§8) |
| Spotify-URL → „Kein Inhalt gefunden" | spotdl nicht installiert oder veraltet | `pip install --upgrade --no-deps spotdl` |
| `SpotifyClient already initialized` | spotdl Singleton verletzt | Nur `_get_spotdl()` verwenden, nie direkt `Spotdl(...)` konstruieren |
| `Die Datei konnte nicht geladen werden` | ytsearch-Wrapper nicht entpackt | `download_audio()` → Unwrap-Block prüfen (§5.2) |
| Scheduler startet nicht | APScheduler-Version | apscheduler≥3.10 |
| „Kein Platz mehr" erscheint sofort beim Hinzufügen | `STORAGE_WARN_MB` zu hoch; Host-Dateisystem hat weniger freien Speicher als der Schwellwert | Standard ist 100 MB. Mit `df -h /opt/hoerbox-feeder-data` auf dem Host prüfen. Schwellwert per Env-Var anpassen: `STORAGE_WARN_MB=50` in `docker-compose.yml`. |
| Icons haben einen schwarzen oder dunklen Rahmen | Browser-/PWA-Cache zeigt alte Version | Browser-Cache leeren (Hard Refresh: Strg+Umschalt+R). Die PNG-Icons haben transparenten Hintergrund. |

---

## 14. Weiterentwicklung

### Ideen / offene Punkte

- **Authentifizierung:** Aktuell keine – bei öffentlicher Exposition Basic Auth
  oder VPN vorschalten.
- **Multi-User:** SQLite-WAL-Modus aktivieren wenn mehrere Nutzer gleichzeitig
  aktiv sind.
- **Spotify Playlist als Abo:** Aktuell wird eine Spotify-Playlist beim
  ersten Aufruf vollständig heruntergeladen.  Künftig könnte periodisch nach
  neuen Einträgen gesucht werden (wie YouTube-Abo).
- **Test-Coverage für Downloader:** Die Tests mocken yt-dlp.  Echter
  Integrationstest wäre wünschenswert (benötigt Internet im CI).

---

## 15. Changelog (Folge-Session August 2026)

### Fehler behoben: „Kein Platz mehr" erscheint sofort

**Ursache:** `STORAGE_WARN_MB` war auf **500 MB** voreingestellt.
Auf einem typischen Heimserver oder Raspberry Pi ist der Speicher auf dem
Root-Dateisystem oft knapper als 500 MB – der Storage-Guard schlug deshalb
sofort an, auch wenn noch genug Platz für Audio-Dateien vorhanden war.

**Fix:** Voreinstellung in `app/config.py` auf **100 MB** gesenkt.
Wer einen anderen Schwellwert braucht, setzt `STORAGE_WARN_MB=…` in
`docker-compose.yml`.

### Fehler behoben: Icons haben dunklen Rahmen (schwarze Umrandung)

**Ursache:** Die PNG-Icon-Dateien (`apple-touch-icon.png`, `icon-192.png`,
`favicon.png`) hatten ein undurchsichtiges dunkelblaues Hintergrundquadrat
(#0b1d33). In modernen Browsern und auf dem Homescreen erschien das als
schwarzer oder dunkelblauer Rand ums Logo.

**Fix:** Alle drei PNGs wurden mit Pillow neu gerendert – der dunkle
Hintergrund wurde durch Alpha-Transparenz ersetzt (Pixel nah an der
Eck-Hintergrundfarbe → `alpha=0`, fließender Übergang für Anti-Aliasing).
Das Logo (gelber Pac-Man mit weißem „h") bleibt voll sichtbar.
`favicon.ico` wurde ebenfalls aus dem transparenten PNG neu generiert.

---

## 16. Changelog (Folge-Session August 2026, Teil 2)

### Kritischer Fix: Verzeichnisstruktur war verflacht

Beim Kopieren/Entpacken des Deployments auf ein anderes System lagen alle
Module aus `app/`, `app/routers/`, `templates/` und `static/` versehentlich
flach im Projekt-Root. Der Code selbst (relative Imports, `Dockerfile`
`COPY app ./app`) setzt aber genau die Paketstruktur voraus – weder
`docker compose up` noch `uvicorn app.main:app` starteten. Struktur anhand
der Imports und eines Referenz-Deployment-Archivs (byte-identisch geprüft)
wiederhergestellt.

### Fix: `STORAGE_WARN_MB=500` in `docker-compose.yml` hob den §15-Fix wieder auf

Der in §15 dokumentierte Fix senkte nur den Python-Default in `config.py`.
`docker-compose.yml` (der empfohlene Deploy-Weg) setzte die Umgebungsvariable
aber weiterhin explizit auf 500 MB. Zeile entfernt; der App-Default (100 MB)
greift jetzt auch im Docker-Betrieb.

### Fix: Spotify-Downloads funktionierten nie (`ModuleNotFoundError: rapidfuzz`)

spotdl wurde mit `--no-deps` installiert, dazu eine manuell gepflegte
Teilliste vermeintlich fehlender Abhängigkeiten (§4.3). spotdl 4.5.2 braucht
tatsächlich deutlich mehr (u. a. `rapidfuzz`, `platformdirs`, `pykakasi`,
`datastar-py`, `syncedlyrics`, `spotipy`, `ytmusicapi`) – jeder Spotify-Import
scheiterte zur Laufzeit mit `ModuleNotFoundError`, was `downloader.py` als
generisches „spotdl ist nicht installiert" maskierte.

**Fix:** spotdl in `Dockerfile` und `app/main.py._update_yt_dlp()` jetzt MIT
vollständigem Dependency-Tree installieren, danach nur die tatsächlich
kollidierenden Pakete (`fastapi`/`starlette`/`anyio`/`uvicorn`, wegen spotdls
ungenutztem Web-UI) auf die von der App benötigten Versionen zurückpinnen.
Robuster als eine manuelle Teilliste, die bei jedem spotdl-Update erneut
brechen kann. §4.3 ist damit überholt – hier die aktuelle Referenz.

### Feature: Browser-nativer SD-Export (ZIP-Download)

Der bestehende Server-Pfad-Export (`POST /api/sd-export`, §7/§14) setzt eine
SD-Karte voraus, die auf dem *Server* gemountet ist – unpraktisch bei einem
headless Raspberry Pi ohne Kartenleser. Neuer Endpoint
`GET /api/sd-export/zip` (`app/routers/api.py`) liefert dieselbe
Ordnerstruktur (`0/`–`8/`, Dateien als „NN Titel.mp3") als ZIP-Datei zum
normalen Browser-Download – funktioniert von jedem Gerät im LAN, ganz ohne
serverseitigen Kartenzugriff. Button auf `/belegung` (nur sichtbar wenn
Dateien vorhanden sind).

**Bewusst kein `showDirectoryPicker()`/File System Access API:** Diese
bräuchte einen „secure context" (HTTPS oder `localhost`); die App läuft
laut §8 aber ausschließlich über HTTP auf der LAN-IP – der Picker wäre dort
schlicht nicht verfügbar, zusätzlich fehlt Firefox/Safari-Support komplett.
ZIP-Download funktioniert dagegen in jedem Browser ohne TLS.

**Implementierung:** `app/sd_export.py` – gemeinsame Iterationslogik
`_iter_export_files()` liefert `(channel_id, dest_name, src_path)` für beide
Export-Varianten; `build_export_zip()` schreibt unkomprimiert (`ZIP_STORED`,
MP3s sind schon komprimiert) in eine echte Temp-Datei auf Platte statt in
den RAM (die Bibliothek kann mehrere hundert MB groß werden – zu viel für
den Pi-Arbeitsspeicher). Temp-Datei wird über Starlettes `BackgroundTask`
nach dem Senden automatisch gelöscht.

*Dieses Dokument zuletzt aktualisiert: August 2026*
