# hoerbox-feeder

*[English version](README.en.md)*

[![CI](https://github.com/kasati111/hoerbox-feeder/actions/workflows/ci.yml/badge.svg)](https://github.com/kasati111/hoerbox-feeder/actions/workflows/ci.yml)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)

**Aus jedem Link ein Hörspiel für die Hörbox, ohne Gefummel mit SD-Karten.**

Selbst-gehostete Web-App: Link einfügen (YouTube, Spotify, Podcast, ...) –
Download, MP3-Konvertierung und Podcast-Feed laufen automatisch. Einmal im
Zielgerät eingerichtet, kommen neue Folgen von selbst nach.

Damit lässt sich eine Hörbox automatisch verwalten – **kein Kabel, kein
Dateiname-Sortieren**, nur ein Browser und ein Link.

<p>
  <img src="docs/screenshots/start.png" alt="Startseite: Link einfügen und Kanal wählen" width="46%" style="margin-right: 4%;">
  <img src="docs/screenshots/kanal.png" alt="Kanal-Ansicht mit einem geladenen Titel" width="46%">
</p>

*(Beispielinhalt im Screenshot: „Die Sterntaler“ von den Brüdern Grimm,
gemeinfrei, via [vorleser.net](https://vorleser.net).)*

📖 **Für Eltern:** ausführliches, bebildertes
[Benutzerhandbuch (PDF)](docs/BENUTZERHANDBUCH.pdf) mit allen Funktionen –
auch als [English User Guide (PDF)](docs/USER_MANUAL.pdf).

## Wie es funktioniert

1. Link einfügen, einem von neun Kanälen zuordnen.
2. hoerbox-feeder lädt den Inhalt, konvertiert ihn zu MP3 (normalisierte
   Lautstärke, eingebettetes Cover).
3. Jeder Kanal ist als eigener Podcast-RSS-Feed abrufbar
   (`http://<server>:8080/feed/<kanal>.xml`).

Da es ein ganz normaler Podcast-RSS-Feed ist, funktioniert hoerbox-feeder
mit **jedem podcastfähigen Gerät** – klassische Podcast-Apps, viele
internetfähige Webradios, oder eben ein dedizierter Kinder-Audioplayer.

## Hintergrund: entwickelt für den hörbert

Entwickelt und getestet wurde hoerbox-feeder für den
[hörbert](https://www.hoerbert.com/), einen Holz-Audioplayer für Kinder mit
neun Farbtasten – daher die neun Kanäle. hoerbox-feeder ist ein
**inoffizielles Community-Projekt ohne jede Verbindung** zum Hersteller des
hörbert; das Projekt steht in keiner geschäftlichen Beziehung zu diesem und
wird von ihm weder unterstützt noch empfohlen. Es lässt sich unabhängig
davon mit jedem anderen podcastfähigen Gerät nutzen.

## Wichtiger Hinweis zur Nutzung

Downloads von Streaming-Plattformen können deren Nutzungsbedingungen und/oder
Urheberrecht verletzen. **Du bist selbst dafür verantwortlich, hoerbox-feeder
nur für Inhalte zu verwenden, die du dazu nutzen darfst** – z. B. Podcasts
mit offenem RSS-Feed, gemeinfreie Inhalte oder eigenes Material. Dieses
Projekt übernimmt keine Haftung für die Art, wie es genutzt wird.

## Features

- Link einfügen → Kanal wählen → Fertig. Playlists/Podcasts werden erkannt
  und automatisch als Abo eingerichtet (neue Folgen kommen von selbst).
- Automatische Lautstärke-Normalisierung, Cover-Einbettung, Tonspur
  (Mono/Stereo) global einstellbar (Setup-Seite).
- Sprache (Deutsch/Englisch) und Kanal-Anzeige (bunte Knöpfe oder
  nummerierte Kanaltasten, für hörbert-Varianten ohne Farbtasten)
  individuell einstellbar (Setup-Seite).
- Übersicht über Speicherbelegung pro Kanal, SD-Karten-Export als ZIP.
- Bibliothek zum Parken von Inhalten außerhalb der aktiven Kanäle.
- Läuft komplett lokal im eigenen Netzwerk, keine Cloud-Abhängigkeit.

## Für Admins

Dieser Abschnitt richtet sich an die Person, die hoerbox-feeder installiert
und betreut – nicht an die Eltern, die später nur Links einfügen. Für sie
gibt es das separate [Benutzerhandbuch (PDF)](docs/BENUTZERHANDBUCH.pdf) –
am besten nach der Einrichtung weiterreichen.

### Installation

```bash
git clone https://github.com/kasati111/hoerbox-feeder.git
cd hoerbox-feeder
docker compose up -d --build
```

Danach `http://<deine-server-ip>:8080` im Browser öffnen.

### Update

```bash
git pull && docker compose up -d --build
```

Für ein Deployment ohne Git-Zugriff auf dem Zielserver (Tarball-basiert,
inkl. Rollback über `schnellstart.sh`/`update.sh`) siehe
[DEVELOPER.md § 8](DEVELOPER.md#8-deployment). Architektur/Entwicklung
ebenfalls dort.

### Kompatible Dienste

- **YouTube** – Einzelvideo, Playlist oder ganzer Kanal (via yt-dlp).
- **Spotify** – Track, Album oder Playlist (via spotdl aufgelöst; der
  passende Titel wird dann auf YouTube gesucht und von dort geladen).
- **Podcasts** – jeder offene RSS-Feed.
- **Direkte Audio-Downloads** – z. B. [vorleser.net](https://vorleser.net)
  (siehe Screenshot oben).
- Deutsche Kinder-/Familieninhalte, die yt-dlp per eigenem Extractor
  unterstützt: u. a. **KiKA**, **ARD Audiothek**, **ARD Mediathek**, **ZDF**
  (inkl. ZDFtivi).
- Darüber hinaus grundsätzlich auch vieles von den mehreren hundert weiteren
  Seiten, die yt-dlp unterstützt.

Diese Aufzählung ist rein technisch gemeint (was yt-dlp extrahieren kann) –
keine Empfehlung. Ob eine Nutzung im Einzelfall erlaubt ist, hängt von den
Nutzungsbedingungen der jeweiligen Plattform ab, siehe
["Wichtiger Hinweis zur Nutzung"](#wichtiger-hinweis-zur-nutzung) oben.

### RSS-URLs

Jeder der neun Kanäle hat einen eigenen Podcast-Feed unter
`http://<deine-server-ip>:8080/feed/<kanal-id>.xml`:

| ID | Kanal |
|----|-------|
| 0 | Violett |
| 1 | Rot |
| 2 | Dunkelblau |
| 3 | Grün |
| 4 | Gelb |
| 5 | Türkis |
| 6 | Hellblau |
| 7 | Orange |
| 8 | Dunkelgrün |

Diese Adressen einmalig im Zielgerät oder einer Podcast-App eintragen –
siehe auch die „Adressen“-Seite (`/einrichtung`) in der App selbst, die die
fertigen URLs (inkl. QR-Codes) pro Kanal anzeigt.

### Bekannte Einschränkungen

- **Kein SSL out of the box:** hoerbox-feeder läuft standardmäßig über
  reines HTTP im LAN, ohne eigenes HTTPS-Zertifikat. Dadurch kann der
  📋-Einfügen-Button auf der Startseite (Clipboard-Zugriff per Browser-API)
  in manchen Browsern nicht funktionieren – das ist keine Fehlfunktion,
  sondern eine Browser-Sicherheitsvorgabe (Clipboard-API nur über HTTPS
  oder `localhost`). Manuelles Einfügen per Strg+V funktioniert davon
  unabhängig immer. Details, Ursache und browserspezifische Fixes: siehe
  [DEVELOPER.md § 13.1](DEVELOPER.md#131-clipboard-einfügen-funktioniert-nicht-fehlendes-https).

## Lizenz

[GPL-3.0](LICENSE) – Copyright © 2026 [kasati111](https://github.com/kasati111).

## Kontakt

Fragen, Bugs, Ideen: bitte über [GitHub Issues](https://github.com/kasati111/hoerbox-feeder/issues).
