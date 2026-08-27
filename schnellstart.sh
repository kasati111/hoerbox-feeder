#!/bin/bash
# hoerbox-feeder Schnellstart-Skript
# Kopiere diesen Code auf deinen Server und führe ihn aus

set -e

echo "======================================"
echo "hoerbox-feeder Installation"
echo "======================================"
echo ""

# Installationsverzeichnis
INSTALL_DIR="/opt/hoerbox-feeder"

# Prüfen ob Docker läuft
if ! command -v docker &> /dev/null; then
    echo "❌ Docker ist nicht installiert!"
    exit 1
fi

if ! command -v docker compose &> /dev/null && ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose ist nicht installiert!"
    exit 1
fi

echo "✓ Docker gefunden"
echo ""

# Verzeichnis erstellen
echo "📁 Erstelle Verzeichnis: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Prüfen ob Archiv vorhanden
if [ ! -f "hoerbox-feeder-deploy.tar.gz" ]; then
    echo ""
    echo "❌ Archiv 'hoerbox-feeder-deploy.tar.gz' nicht gefunden!"
    echo ""
    echo "Bitte platziere die Datei in: $INSTALL_DIR"
    echo "Dann führe dieses Skript erneut aus."
    exit 1
fi

# Archiv auf Integrität prüfen (fängt unvollständige Uploads ab)
echo "🔎 Prüfe Archiv..."
if ! gzip -t hoerbox-feeder-deploy.tar.gz 2>/dev/null; then
    echo ""
    echo "❌ Das Archiv ist beschädigt oder unvollständig!"
    echo "   (Der Upload wurde vermutlich abgebrochen.)"
    echo ""
    echo "→ Bitte die Datei erneut hochladen und dieses Skript nochmal ausführen."
    exit 1
fi
echo "✓ Archiv ist vollständig"
echo ""

# Entpacken
echo "📦 Entpacke Archiv..."
tar -xzf hoerbox-feeder-deploy.tar.gz --strip-components=1
echo "✓ Archiv entpackt"
echo ""

# Docker Compose starten (mit Neubau des Images)
echo "🚀 Starte Container..."
docker compose up -d --build

echo ""
echo "======================================"
echo "✅ Installation abgeschlossen!"
echo "======================================"
echo ""
echo "Die Anwendung läuft jetzt auf:"
echo ""
echo "  http://localhost:8080"
echo ""

# IP-Adresse ermitteln
IP=$(hostname -I | awk '{print $1}')
if [ ! -z "$IP" ]; then
    echo "Oder von anderen Geräten im Netzwerk:"
    echo ""
    echo "  http://$IP:8080"
    echo ""
fi

echo "Nützliche Befehle:"
echo ""
echo "  Status prüfen:     docker compose ps"
echo "  Logs ansehen:      docker compose logs -f hoerbox-feeder"
echo "  Container stoppen: docker compose down"
echo "  Neu starten:       docker compose restart hoerbox-feeder"
echo ""
echo "Viel Spaß! 🎵"
