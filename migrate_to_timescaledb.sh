#!/bin/bash
# ============================================
# TimescaleDB Migration Script
# Von PostgreSQL 15 zu TimescaleDB
# ============================================

set -e  # Exit on error

echo "🚀 Starting TimescaleDB Migration..."
echo ""

# ============================================
# 1. BACKUP EXISTING DATA
# ============================================

echo "📦 Step 1: Backing up existing PostgreSQL data..."

# Backup erstellen
docker exec qbot-postgres-1 pg_dump -U postgres qt_trade > backup_postgres_$(date +%Y%m%d_%H%M%S).sql

if [ $? -eq 0 ]; then
    echo "✅ Backup erfolgreich!"
else
    echo "❌ Backup fehlgeschlagen - Abbruch!"
    exit 1
fi

echo ""

# ============================================
# 2. STOP EXISTING CONTAINERS
# ============================================

echo "⏸️  Step 2: Stopping existing containers..."
docker-compose down

echo "✅ Containers gestoppt"
echo ""

# ============================================
# 3. RENAME OLD DATA DIRECTORY
# ============================================

echo "📁 Step 3: Renaming old PostgreSQL data..."

if [ -d "/app/pg" ]; then
    mv /app/pg /app/pg_backup_$(date +%Y%m%d_%H%M%S)
    echo "✅ Alte Daten gesichert"
else
    echo "⚠️  Kein /app/pg Verzeichnis gefunden"
fi

echo ""

# ============================================
# 4. USE TIMESCALEDB DOCKER-COMPOSE
# ============================================

echo "🔄 Step 4: Switching to TimescaleDB..."

# Backup alte docker-compose.yml
cp docker-compose.yml docker-compose.yml.backup_$(date +%Y%m%d_%H%M%S)

# Neue verwenden
cp docker-compose.timescaledb.yml docker-compose.yml

echo "✅ docker-compose.yml ersetzt"
echo ""

# ============================================
# 5. START TIMESCALEDB
# ============================================

echo "🚀 Step 5: Starting TimescaleDB containers..."

docker-compose up -d timescaledb redis

# Warte bis TimescaleDB bereit ist
echo "⏳ Warte auf TimescaleDB..."
sleep 10

# Check ob TimescaleDB läuft
docker exec qbot-timescaledb-1 pg_isready -U postgres > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo "✅ TimescaleDB ist bereit!"
else
    echo "❌ TimescaleDB startet nicht - bitte Logs prüfen:"
    echo "   docker logs qbot-timescaledb-1"
    exit 1
fi

echo ""

# ============================================
# 6. RESTORE DATA (Optional)
# ============================================

echo "📥 Step 6: Restore old data? (y/n)"
read -p "Möchtest du die alten Daten importieren? " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    LATEST_BACKUP=$(ls -t backup_postgres_*.sql | head -1)
    echo "📥 Importiere $LATEST_BACKUP..."
    
    # Restore
    cat $LATEST_BACKUP | docker exec -i qbot-timescaledb-1 psql -U postgres -d qt_trade
    
    if [ $? -eq 0 ]; then
        echo "✅ Daten erfolgreich importiert!"
    else
        echo "⚠️  Import hatte Fehler (normal wenn Schema-Unterschiede)"
        echo "   Hypertables werden durch init_timescaledb.sql neu erstellt"
    fi
else
    echo "⏭️  Überspringe Daten-Import (fresh start)"
fi

echo ""

# ============================================
# 7. VERIFY TIMESCALEDB
# ============================================

echo "🔍 Step 7: Verifying TimescaleDB installation..."

docker exec qbot-timescaledb-1 psql -U postgres -d qt_trade -c "\dx" | grep timescaledb

if [ $? -eq 0 ]; then
    echo "✅ TimescaleDB Extension aktiv!"
else
    echo "❌ TimescaleDB Extension nicht gefunden!"
    exit 1
fi

echo ""

# Zeige Hypertables
echo "📊 Hypertables:"
docker exec qbot-timescaledb-1 psql -U postgres -d qt_trade -c "SELECT * FROM timescaledb_information.hypertables;"

echo ""

# ============================================
# 8. START ALL SERVICES
# ============================================

echo "🚀 Step 8: Starting all services..."

docker-compose up -d

echo "✅ Alle Services gestartet!"
echo ""

# ============================================
# 9. FINAL STATUS
# ============================================

echo "📊 Final Status:"
docker-compose ps

echo ""
echo "✅ Migration abgeschlossen!"
echo ""
echo "📝 Nächste Schritte:"
echo "   1. Logs prüfen: docker-compose logs -f"
echo "   2. Worker starten: docker-compose restart worker celery-beat"
echo "   3. Daten testen: docker exec qbot-timescaledb-1 psql -U postgres -d qt_trade -c 'SELECT COUNT(*) FROM market_data;'"
echo ""
echo "🔥 TimescaleDB Features:"
echo "   - Hypertables: Automatische Zeit-Partitionierung"
echo "   - Compression: 90% weniger Speicher nach 7 Tagen"
echo "   - Continuous Aggregates: market_data_15min, market_data_1hour, market_data_1day"
echo "   - Fast Queries: time_bucket() für beliebige Timeframes"
echo ""
echo "🧪 Test Query:"
echo "   docker exec qbot-timescaledb-1 psql -U postgres -d qt_trade -c \"SELECT * FROM get_ohlcv('AAPL', '15min', 10);\""
echo ""
