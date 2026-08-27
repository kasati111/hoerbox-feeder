# Changelog

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

## [0.1.0] - 2026-08-27

Erste öffentliche Version.

### Hinzugefügt
- Link einfügen (YouTube, Spotify, Podcast, ...) per Browser, einem von neun
  Kanälen zuordnen; automatischer Download und Konvertierung zu MP3.
- Automatische Lautstärke-Normalisierung, Mono-Umwandlung, Cover-Einbettung.
- Podcast-RSS-Feed pro Kanal – funktioniert mit jedem podcastfähigen Gerät.
- Automatisches Abo für Playlists/Podcast-Feeds inkl. Retention (älteste
  Folgen werden als ganze Playlist geparkt, nicht einzeln).
- Übersicht über Speicherbelegung pro Kanal, SD-Karten-Export als ZIP.
- Bibliothek zum Parken von Inhalten außerhalb der aktiven Kanäle.
- Kanäle einzeln deaktivierbar (für extern/manuell bespielten Inhalt).
- Docker-Compose-Deployment, Setup-/Update-Skripte für manuelle Installation.
