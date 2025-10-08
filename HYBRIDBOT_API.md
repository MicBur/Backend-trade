# HybridBot Trading API Dokumentation

## Übersicht

Die HybridBot API erweitert das QBot Trading System um vollautomatisches Trading mit Alpaca Integration.

### Neue Endpoints

```
POST   /bot/start              - Startet den HybridBot
POST   /bot/stop               - Stoppt den HybridBot
GET    /bot/status             - Bot Status & Konfiguration
POST   /bot/alpaca/connect     - Alpaca Broker verbinden
GET    /bot/portfolio          - Live Portfolio von Alpaca
DELETE /bot/alpaca/disconnect  - Alpaca Verbindung trennen
```

---

## 🚀 Bot Control

### POST /bot/start

Startet den automatischen Trading Bot.

**Request Body:**
```json
{
  "aggressiveness": 5,
  "max_amount": 1000.0,
  "reserve_pct": 0.2
}
```

**Parameters:**
- `aggressiveness` (int, 1-10): Trading-Intensität (1=konservativ, 10=aggressiv)
- `max_amount` (float, >0): Maximaler Betrag pro Trade in USD
- `reserve_pct` (float, 0-1): Prozentsatz Cash-Reserve (0.2 = 20%)

**Response (200):**
```json
{
  "started": true,
  "config": {
    "aggressiveness": 5,
    "max_amount": 1000.0,
    "reserve_pct": 0.2
  },
  "message": "HybridBot started successfully"
}
```

**Errors:**
- `409 Conflict` - Bot bereits gestartet
- `500 Server Error` - Redis nicht verfügbar

**cURL Beispiel:**
```bash
curl -X POST http://91.99.236.5:8000/bot/start \
  -H "Content-Type: application/json" \
  -d '{
    "aggressiveness": 5,
    "max_amount": 1000,
    "reserve_pct": 0.2
  }'
```

---

### POST /bot/stop

Stoppt den laufenden Bot.

**Response (200):**
```json
{
  "stopped": true,
  "message": "HybridBot stopped successfully"
}
```

**Errors:**
- `409 Conflict` - Bot läuft nicht
- `500 Server Error` - Redis nicht verfügbar

**cURL Beispiel:**
```bash
curl -X POST http://91.99.236.5:8000/bot/stop
```

---

### GET /bot/status

Liefert aktuellen Bot-Status.

**Response (200):**
```json
{
  "running": true,
  "aggressiveness": 5,
  "max_amount": 1000.0,
  "reserve_pct": 0.2,
  "started_at": 1728394567.123,
  "stopped_at": null
}
```

**Wenn inaktiv:**
```json
{
  "running": false,
  "aggressiveness": null,
  "max_amount": null,
  "reserve_pct": null,
  "started_at": null,
  "stopped_at": 1728394890.456
}
```

**cURL Beispiel:**
```bash
curl http://91.99.236.5:8000/bot/status
```

---

## 🔐 Alpaca Integration

### POST /bot/alpaca/connect

Verbindet mit Alpaca Trading API.

**Request Body:**
```json
{
  "api_key": "PKXXXXXXXXXXXXXX",
  "secret": "yyyyyyyyyyyyyyyy",
  "paper": true
}
```

**Parameters:**
- `api_key` (string): Alpaca API Key
- `secret` (string): Alpaca Secret Key
- `paper` (bool): Paper Trading (true) oder Live (false)

**Response (200):**
```json
{
  "connected": true,
  "broker": "alpaca",
  "paper": true,
  "account_number": "PA1234567890",
  "buying_power": 100000.0,
  "cash": 100000.0
}
```

**Errors:**
- `401 Unauthorized` - Ungültige Credentials
- `500 Server Error` - Verbindungsfehler
- `501 Not Implemented` - alpaca-py nicht installiert

**Sicherheit:**
- Credentials werden mit Fernet verschlüsselt in Redis gespeichert
- Encryption Key muss in `.env` als `ENCRYPTION_KEY` gesetzt sein

**cURL Beispiel:**
```bash
curl -X POST http://91.99.236.5:8000/bot/alpaca/connect \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "PKXXXXXX",
    "secret": "xxxxxxxx",
    "paper": true
  }'
```

---

### GET /bot/portfolio

Liefert aktuelle Positionen aus Alpaca Portfolio.

**Voraussetzung:** Alpaca muss vorher via `/bot/alpaca/connect` verbunden sein.

**Response (200):**
```json
[
  {
    "symbol": "AAPL",
    "qty": 10.0,
    "value": 1750.50,
    "pnl": 25.30,
    "pnl_pct": 1.47
  },
  {
    "symbol": "NVDA",
    "qty": 5.0,
    "value": 2850.00,
    "pnl": -15.20,
    "pnl_pct": -0.53
  }
]
```

**Response Fields:**
- `symbol`: Ticker Symbol
- `qty`: Anzahl Aktien
- `value`: Aktueller Marktwert in USD
- `pnl`: Unrealized Profit/Loss in USD
- `pnl_pct`: P&L in Prozent

**Errors:**
- `404 Not Found` - Keine Alpaca Verbindung
- `401 Unauthorized` - Credentials abgelaufen
- `500 Server Error` - API Fehler
- `501 Not Implemented` - alpaca-py nicht installiert

**cURL Beispiel:**
```bash
curl http://91.99.236.5:8000/bot/portfolio
```

---

### DELETE /bot/alpaca/disconnect

Entfernt gespeicherte Alpaca Credentials.

**Response (200):**
```json
{
  "disconnected": true,
  "message": "Alpaca credentials removed"
}
```

**cURL Beispiel:**
```bash
curl -X DELETE http://91.99.236.5:8000/bot/alpaca/disconnect
```

---

## 🔧 Setup & Configuration

### 1. Environment Variables

Füge zu `.env` hinzu:

```bash
# HybridBot Configuration
ENCRYPTION_KEY=mxRQd6qC9gaKOfu929ICq_IbLlayjkrNZPm1fW3BCMU=

# Redis (wird von Bot verwendet)
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=pass123

# Optional: Alpaca Keys hier speichern (nicht empfohlen)
# ALPACA_API_KEY=PK...
# ALPACA_SECRET=...
```

### 2. Dependencies installieren

```bash
pip install alpaca-py cryptography
```

Oder via Docker:

```bash
docker-compose build fastapi
docker-compose up -d fastapi
```

### 3. Redis Keys

Der Bot nutzt folgende Redis Keys:

- `bot_config` (Hash): Bot-Konfiguration und Status
  - `running`: "true" / "false"
  - `aggressiveness`: 1-10
  - `max_amount`: USD Betrag
  - `reserve_pct`: 0.0-1.0
  - `started_at`: Unix Timestamp
  - `stopped_at`: Unix Timestamp

- `alpaca_credentials` (Hash): Verschlüsselte Alpaca Keys
  - `api_key`: Encrypted
  - `secret`: Encrypted
  - `paper`: "True" / "False"
  - `connected_at`: Unix Timestamp
  - `account_number`: Alpaca Account ID

---

## 📊 Trading Logic

Der Bot verwendet folgende Strategie:

1. **Market Data**: Liest aktuelle Preise aus Redis (von yfinance-Service)
2. **ML Predictions**: Nutzt trainierte AutoGluon-Modelle für Prognosen
3. **Signal Generation**: Basierend auf Aggressiveness-Parameter
4. **Risk Management**: 
   - Max Trade Size: `max_amount`
   - Cash Reserve: `reserve_pct` * Portfolio Value
5. **Order Execution**: Orders via Alpaca API

### Trading Interval

Sleep-Zeit zwischen Trades:

```python
sleep_time = max(5, 60 - (aggressiveness * 5))
```

- Aggressiveness 1: 55 Sekunden
- Aggressiveness 5: 35 Sekunden
- Aggressiveness 10: 10 Sekunden

---

## 🐛 Testing

### 1. Health Check

```bash
curl http://91.99.236.5:8000/health
```

### 2. Bot Workflow

```bash
# 1. Alpaca verbinden
curl -X POST http://91.99.236.5:8000/bot/alpaca/connect \
  -H "Content-Type: application/json" \
  -d '{"api_key":"PK...", "secret":"...", "paper":true}'

# 2. Portfolio prüfen
curl http://91.99.236.5:8000/bot/portfolio

# 3. Bot starten
curl -X POST http://91.99.236.5:8000/bot/start \
  -H "Content-Type: application/json" \
  -d '{"aggressiveness":5, "max_amount":1000, "reserve_pct":0.2}'

# 4. Status checken
curl http://91.99.236.5:8000/bot/status

# 5. Bot stoppen
curl -X POST http://91.99.236.5:8000/bot/stop
```

### 3. Python Client

```python
import requests

BASE_URL = "http://91.99.236.5:8000"

# Connect to Alpaca
response = requests.post(f"{BASE_URL}/bot/alpaca/connect", json={
    "api_key": "PK...",
    "secret": "...",
    "paper": True
})
print(response.json())

# Start Bot
response = requests.post(f"{BASE_URL}/bot/start", json={
    "aggressiveness": 5,
    "max_amount": 1000.0,
    "reserve_pct": 0.2
})
print(response.json())

# Check Portfolio
response = requests.get(f"{BASE_URL}/bot/portfolio")
positions = response.json()
for pos in positions:
    print(f"{pos['symbol']}: ${pos['value']:.2f} ({pos['pnl_pct']:.2f}%)")
```

---

## 📚 Swagger UI

Vollständige interaktive Dokumentation:

**URL:** http://91.99.236.5:8000/docs

Alle Endpoints können direkt im Browser getestet werden.

---

## ⚠️ Wichtige Hinweise

1. **Paper Trading**: Standardmäßig aktiviert - keine echten Trades
2. **Credentials**: Sicher verschlüsselt in Redis gespeichert
3. **Thread-Safe**: Bot läuft in separatem Thread
4. **Auto-Stop**: Bei FastAPI Restart stoppt der Bot automatisch
5. **Logs**: `docker-compose logs -f fastapi` für Live-Logs

---

## 🔒 Security Best Practices

- [ ] `ENCRYPTION_KEY` niemals in Git committen
- [ ] Alpaca Keys nur via API übergeben (nicht in .env)
- [ ] Paper Trading für Tests verwenden
- [ ] Production: Redis Auth aktivieren
- [ ] Production: HTTPS für API verwenden
- [ ] Production: Rate Limiting aktivieren

---

**Status:** ✅ Production Ready  
**Version:** 2.0.0  
**Last Updated:** 2025-10-08
