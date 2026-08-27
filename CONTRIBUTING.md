# Mitwirken

Danke für dein Interesse an hoerbox-feeder! Das ist ein kleines
Hobby-Projekt, entsprechend informell läuft auch das Mitwirken.

## Setup

Siehe [DEVELOPER.md](DEVELOPER.md) für Architektur, lokale Einrichtung und
Umgebungsvariablen.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v
```

## Pull Requests

- Kleine, fokussierte Änderungen sind leichter zu reviewen als große.
- Tests laufen lassen, bevor du einen PR öffnest.
- Kurz beschreiben, *warum* die Änderung nötig ist, nicht nur *was* sie tut.

## Issues

Bug gefunden oder Idee für ein Feature? Gerne ein Issue eröffnen –
Reproduktionsschritte bzw. der konkrete Anwendungsfall helfen am meisten.
