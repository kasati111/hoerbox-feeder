# hoerbox-feeder

[![CI](https://github.com/kasati111/hoerbox-feeder/actions/workflows/ci.yml/badge.svg)](https://github.com/kasati111/hoerbox-feeder/actions/workflows/ci.yml)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)

Selbst-gehostete Web-App: per Browser (am Handy, Tablet, PC) einen Link einfügen (YouTube,
Spotify, Podcast, ...), der Server lädt den Inhalt herunter, wandelt ihn in
ein einheitliches, normalisiertes MP3-Format um und stellt ihn als
Podcast-RSS-Feed bereit – einmal die Feed-Adresse im Zielgerät eintragen,
danach kommen neue Folgen bei Playlists/Abos automatisch nach.

Damit lässt sich eine Hörbox automatisch verwalten – **kein Kabel, kein
SD-Karten-Gefummel, kein Dateiname-Sortieren**, nur ein Browser und ein Link.

## Wie es funktioniert

1. Link einfügen, einem von neun Kanälen zuordnen.
2. hoerbox-feeder lädt den Inhalt, konvertiert ihn zu MP3 (Mono, normalisierte
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
- Automatische Lautstärke-Normalisierung, Mono-Umwandlung, Cover-Einbettung.
- Übersicht über Speicherbelegung pro Kanal, SD-Karten-Export als ZIP.
- Bibliothek zum Parken von Inhalten außerhalb der aktiven Kanäle.
- Läuft komplett lokal im eigenen Netzwerk, keine Cloud-Abhängigkeit.

## Schnellstart

```bash
git clone https://github.com/kasati111/hoerbox-feeder.git
cd hoerbox-feeder
docker compose up -d --build
```

Danach `http://<deine-server-ip>:8080` im Browser öffnen.

**Aktualisieren:** `git pull && docker compose up -d --build`. Für ein
Deployment ohne Git-Zugriff auf dem Zielserver (Tarball-basiert, inkl.
Rollback) siehe [DEVELOPER.md § 8](DEVELOPER.md#8-deployment). Details zu
Architektur und Entwicklung ebenfalls dort.

## Lizenz

[GPL-3.0](LICENSE) – Copyright © 2026 [kasati111](https://github.com/kasati111).

## Kontakt

Fragen, Bugs, Ideen: bitte über [GitHub Issues](https://github.com/kasati111/hoerbox-feeder/issues).
