# Trading Bot Backend

Vollständiges Backend-System für automatisierten Aktienhandel mit ML-Vorhersagen, TimescaleDB und FastAPI.

## 🎯 Features

### Core-Funktionalität
- **FastAPI REST API** auf Port 8000 (öffentlich)
- **TimescaleDB** mit Hypertables & Continuous Aggregates
- **Redis** für Caching & Pub/Sub
- **AutoGluon ML** Multi-Horizon Predictions (15min, 30min, 60min)
- **Grok AI** Integration für Marktanalyse
- **Alpaca API** für Live-Trading (Paper & Live)

### Endpoints
Siehe [wire.md](./wire.md) für vollständige API-Dokumentation:
- `/health` - System Health
- `/market/*` - Marktdaten (OHLCV, Latest, Top Movers)
- `/portfolio/*` - Portfolio Performance & Positionen
- `/trades` - Handelshistorie
- `/training/*` - ML-Training Status & Modelle
- `/ai/grok-insights` - KI-Empfehlungen

## 🚀 Schnellstart

### 1. Environment Setup
```bash
cp .env.example .env
# .env mit deinen API-Keys befüllen:
# - ALPACA_API_KEY / ALPACA_SECRET
# - XAI_API_KEY (Grok)
# - Optional: FINNHUB, FMP, etc.
```

### 2. Docker Compose starten
```bash
docker-compose up -d
```

Services:
- `fastapi`: REST API (0.0.0.0:8000)
- `timescaledb`: TimescaleDB (Port 5432)
- `redis`: Redis (Port 6379)
- `worker`: Celery Worker für ML-Training & Data Collection

### 3. Health Check
```bash
curl http://localhost:8000/health
```

## 📊 Architektur

```
┌─────────────┐     ┌──────────────┐     ┌────────────┐
│   FastAPI   │────▶│ TimescaleDB  │     │   Redis    │
│  (Port 8000)│     │  (Hyper-     │◀───▶│  (Cache &  │
│             │     │   tables)    │     │   Pub/Sub) │
└──────┬──────┘     └──────────────┘     └─────┬──────┘
       │                                         │
       │            ┌──────────────┐            │
       └───────────▶│Celery Worker │◀───────────┘
                    │ (ML Training)│
                    └──────────────┘
                           │
                    ┌──────▼──────┐
                    │  AutoGluon  │
                    │   Models    │
                    └─────────────┘
```

## 🔐 Sicherheit

- **API Keys**: Niemals in Code, nur in `.env`
- **Firewall**: Nur Port 8000 öffentlich
- **Redis**: Nur intern (Docker-Netzwerk)
- **.gitignore**: Models, Backups, Logs ausgeschlossen

## 📚 Dokumentation

- [wire.md](./wire.md) - Frontend-Backend Integration Guide
- [API.md](./API.md) - API-Spezifikation
- [TIMESCALEDB_MIGRATION.md](./TIMESCALEDB_MIGRATION.md) - DB-Migration
- [TRADING_BOT_STATUS.md](./TRADING_BOT_STATUS.md) - Status-Report

## 🛠️ Development

### Logs anzeigen
```bash
docker-compose logs -f fastapi
docker-compose logs -f worker
```

### Training manuell starten
```bash
curl -X POST http://localhost:8000/training/start
```

### DB-Backup
```bash
docker exec qbot-timescaledb-1 pg_dump -U postgres qt_trade > backup.sql
```

## 📈 ML-Training

AutoGluon Multi-Horizon Modelle:
- **15min**: Kurzfristige Preisprognosen
- **30min**: Mittelfristige Trends
- **60min**: Langfristige Bewegungen

Training wird automatisch gestartet für:
- Portfolio-Positionen (täglich)
- Grok Top-10 Empfehlungen (täglich)

## 🌐 Öffentlicher Zugriff

Production URL: `http://91.99.236.5:8000`

**Firewall-Hinweis**: Nur Port 8000 extern erreichbar. Redis/DB nur intern.

## 📝 License

MIT License - siehe [LICENSE](./LICENSE)

---

**Projekt-Status**: Production Ready ✅  
**Letzte Aktualisierung**: Oktober 2025  
**Repository**: https://github.com/MicBur/Backend-trade
