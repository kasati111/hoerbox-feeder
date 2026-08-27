#!/bin/bash
# hoerbox-feeder – Update-Skript
#
# Aktualisiert eine bestehende Installation sicher und wiederholbar:
#   1. Prüft, ob das neue Archiv vollständig ist (kein abgebrochener Upload)
#   2. Sichert den alten Code (Rollback möglich)
#   3. Entpackt das neue Archiv
#   4. Baut das Image neu und startet den Container
#   5. Der Farb-/Namens-Abgleich der Kanäle passiert automatisch beim Start
#      (KEIN manueller Datenbank-Befehl mehr nötig)
#
# Aufruf:  ./update.sh

set -euo pipefail

INSTALL_DIR="/opt/hoerbox-feeder"
ARCHIVE="hoerbox-feeder-deploy.tar.gz"
CONTAINER="hoerbox-feeder"

cd "$INSTALL_DIR"

echo "======================================"
echo "hoerbox-feeder – Update"
echo "======================================"
echo ""

# 1. Archiv vorhanden?
if [ ! -f "$ARCHIVE" ]; then
    echo "❌ '$ARCHIVE' nicht gefunden in $INSTALL_DIR"
    echo "   Bitte das neue Archiv hierher hochladen und erneut ausführen."
    exit 1
fi

# 2. Integrität prüfen – fängt genau den 'unexpected end of file'-Fehler ab
echo "🔎 Prüfe Archiv auf Vollständigkeit..."
if ! gzip -t "$ARCHIVE" 2>/dev/null; then
    echo ""
    echo "❌ Das Archiv ist beschädigt oder unvollständig!"
    echo "   Der Upload (scp) wurde vermutlich abgebrochen."
    echo ""
    echo "→ Datei erneut komplett hochladen, dann ./update.sh nochmal ausführen."
    echo "   Der laufende Container wurde NICHT verändert."
    exit 1
fi
echo "✓ Archiv ist vollständig"
echo ""

# 3. Backup des alten Codes (Rollback-Sicherheit)
BACKUP_DIR="backup_$(date +%Y%m%d_%H%M%S)"
echo "💾 Sichere aktuellen Code nach $BACKUP_DIR/ ..."
mkdir -p "$BACKUP_DIR"
for item in app templates static docker-compose.yml Dockerfile requirements.txt; do
    [ -e "$item" ] && cp -r "$item" "$BACKUP_DIR/" 2>/dev/null || true
done
echo "✓ Backup erstellt"
echo ""

# 4. Entpacken
# --strip-components=1 entfernt das führende "hoerbox-feeder/" aus den Pfaden
# im Archiv – Dateien landen direkt im Installationsverzeichnis und überschreiben
# die alten Versionen. Ohne diesen Parameter würde ein "hoerbox-feeder/"-Unterordner
# angelegt, der vom Docker-Build niemals genutzt wird.
echo "📦 Entpacke neues Archiv..."
tar -xzf "$ARCHIVE" --strip-components=1
echo "✓ Entpackt"
echo ""

# 5. Container neu bauen und starten
# --no-cache verhindert, dass Docker alte gecachte Layer (z.B. für templates/)
# wiederverwendet – stellt sicher, dass alle Dateiänderungen wirklich übernommen werden.
echo "🚀 Baue Image neu und starte Container..."
docker compose build --no-cache
docker compose up -d
echo ""

# 6. Kurzer Health-Check
echo "⏳ Warte auf Start..."
sleep 5
if docker compose ps "$CONTAINER" 2>/dev/null | grep -q "Up\|running"; then
    echo "✓ Container läuft"
else
    echo "⚠️  Container-Status unklar – bitte prüfen mit:"
    echo "    docker compose logs -f $CONTAINER"
fi
echo ""

echo "======================================"
echo "✅ Update abgeschlossen!"
echo "======================================"
echo ""
echo "Die Kanal-Farben und -Namen werden automatisch beim Start abgeglichen."
echo "→ Im Browser einmal neu laden (Strg+Shift+R)."
echo ""
echo "Falls etwas nicht stimmt, Rollback mit:"
echo "  cp -r $BACKUP_DIR/* .  &&  docker compose up -d --build"
echo ""
echo "Logs ansehen:  docker compose logs -f $CONTAINER"
echo ""
