# Changelog

*[English version](CHANGELOG.en.md)*

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Hinzugefügt
- Mehrsprachigkeit: komplette Oberfläche auf Deutsch oder Englisch, per
  Setup-Seite umschaltbar (Setting „Sprache"), Default über die neue
  ENV-Variable `LANG` steuerbar.
- Kanal-Anzeige als „Kanaltasten": alternativ zu bunten Knöpfen können alle
  neun Kanäle neutral/grau mit fortlaufender Nummer (1–9) statt Farbname
  angezeigt werden, per Setup-Seite umschaltbar (Setting „Kanal-Anzeige") –
  für hörbert-Varianten/Nachbauten ohne Farbtasten.
- Globale Tonspur-Einstellung (Mono/Stereo) auf der Setup-Seite. Gilt für
  neue Downloads; bereits geladene Titel behalten ihre bisherige Tonspur.
- Abspielreihenfolge im Feed umschaltbar (Setting „Abspielreihenfolge"):
  „Chronologisch" (älteste Folge zuerst, neuer Standard – passend für
  fortlaufende Geschichten) oder „Neueste zuerst" (bisheriges Verhalten,
  RSS-Konvention für normale Podcast-Apps).

### Geändert
- Der Feed listet Folgen standardmäßig chronologisch (älteste zuerst) statt
  wie bisher nach RSS-Konvention (neueste zuerst) – ein Gerät, das den Feed
  einfach der Reihe nach abspielt, spielte fortlaufende Geschichten dadurch
  rückwärts ab. Über die neue Einstellung „Abspielreihenfolge" lässt sich
  das alte Verhalten bei Bedarf wiederherstellen.

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
