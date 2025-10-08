# Frontend ↔️ Backend Wire Guide

Dieser Leitfaden fasst alle relevanten Datenflüsse zwischen Backend (FastAPI + TimescaleDB + Redis) und dem Qt-Frontend zusammen. Er ist die Grundlage, um Widgets zielgerichtet mit Live-Daten zu versorgen.

## 1. Infrastruktur auf einen Blick

- **Redis** (Container `qbot-redis-1`, Passwort `pass123`): schnelles Key/Value-Caching für das Frontend (nur im internen Netzwerk erreichbar; extern blockiert).
- **FastAPI** (Container `qbot-fastapi-1`, Port 8000, erreichbar unter `http://91.99.236.5:8000/`): liefert REST-Endpoints mit frisch aggregierten TimescaleDB-Daten.
- **TimescaleDB** (Container `qbot-timescaledb-1`, DB `qbot`): persistente Speicherung, Continuous Aggregates und Views.

**Firewall-Hinweis:** Von außen ist ausschließlich Port 8000 freigeschaltet. Das Qt-Frontend kann daher _nur_ über die REST-Endpoints auf `http://91.99.236.5:8000/` kommunizieren. Direkte Redis-Verbindungen sind lediglich innerhalb des Docker-Netzwerks bzw. via VPN/SSH-Tunnel möglich.

## 2. FastAPI-Endpoints für das Frontend

**Basis-URL (extern erreichbar):** `http://91.99.236.5:8000`

| Zweck | Methode | Pfad (an Basis-URL anhängen) | Query / Body | Liefert & Hinweise |
|-------|---------|-----------------------------|---------------|--------------------|
| API-Übersicht | GET | `/` | – | `{ message, version, status }` – Health-Widget |
| Health Check | GET | `/health` | – | `{ status, timestamp }` – Ping für Monitoring |
| Trading Automation Status | GET | `/trade/status` | – | Redis-Flags: Autotrading, Backend, letzte Fehler |
| Portfolio Snapshot | GET | `/portfolio` | – | Alpaca-Konto (Equity, Cash, Positionen); benötigt gültige API-Creds im Backend |
| Positions-Only | GET | `/positions` | – | Reine Positionsliste (Alpaca) |
| Legacy Portfolio Alias | GET | `/portfolio/summary` | – | Weiterleitung auf `/portfolio` für ältere Clients |
| Legacy Positions Alias | GET | `/portfolio/positions` | – | Weiterleitung auf `/positions` |
| Trade-Historie | GET | `/trades` | `limit`, `ticker` optional | Zuletzt abgeschlossene Alpaca Orders |
| Portfolio Verlauf | GET | `/portfolio/performance` | `days` (default 30) | Stunden-Equity, Cash, Buying Power |
| Portfolio Summary 30d | GET | `/portfolio/performance/summary` | `limit` (default 168) | Continuous Aggregate `portfolio_performance_30d` |
| Candlestick-Daten | GET | `/market/data/{symbol}` | `timeframe`, `limit`, `start`, `end` | OHLCV-Zeitreihe aus Timescale Hypertables |
| Multi-Timeframe Candles | GET | `/market/ohlcv/{symbol}/multi` | `timeframes`, `limit` | Mehrere Zeitreihen in einem Call (Timescale-Aggregation im Backend) |
| Letzter Tick | GET | `/market/latest/{symbol}` | – | Letzte Minute Candle incl. Preisänderung |
| Tagesgewinner/-verlierer | GET | `/market/top-movers` | `limit` | Top Gainer & Loser des Handelstages |
| Grok AI Insights | GET | `/ai/grok-insights` | `limit` | TopStocks, Recommendations, DeeperSearch |
| Timescale Status | GET | `/system/database-stats` | – | Hypertables, Continuous Aggregates, Table Sizes |
| Training Monitor | GET | `/training/status` | – | Laufender Trainings-Progress (Redis) |
| Training Start | POST | `/training/start` | Optional JSON `{ "tickers": [...] }` | Stößt sequenzielles Training im Worker an |
| Modell-Verzeichnis | GET | `/training/models` | – | Auflistung aller AutoGluon-Modelle auf Disk |
| Training-Historie | GET | `/training/history` | – | Letzte Trainingsläufe & Kennzahlen |

### Beispiel: Multi-Timeframe Candles

```bash
curl "http://91.99.236.5:8000/market/ohlcv/AAPL/multi?timeframes=15min,1hour,1day&limit=120"
```

Antwort (gekürzt):

```json
{
	"symbol": "AAPL",
	"requested": ["15min", "1hour", "1day"],
	"timeframes": {
		"15min": [
			{"time": "2025-10-03T10:45:00+00:00", "open": 234.1, "high": 235.2, ...},
			{"time": "2025-10-03T11:00:00+00:00", "open": 235.2, "high": 236.0, ...}
		],
		"1hour": [ ... ],
		"1day": [ ... ]
	}
}
```

### Beispiel: Letzter Tick

```bash
curl "http://91.99.236.5:8000/market/latest/AAPL"
```

Fehlerfälle:
- 404, wenn kein Datensatz für `{symbol}` vorhanden ist (z. B. Tippfehler oder unbekannter Ticker).
- 500, falls die DB temporär nicht erreichbar ist.

## 3. Redis Keys für das Frontend

Aus `redis.txt`/`redis-endpoints.txt` wurden folgende Keys als „Frontend-Futter“ identifiziert:

| Key | Inhalt | Update-Quelle | Nutzung im UI |
|-----|--------|---------------|----------------|
| `market_data` | `{"AAPL": {"price": 234.07, "change": 4.04, ...}, ...}` | Worker → Redis | Dashboard-Tickerliste (nur intern erreichbar; extern per REST ersetzen) |
| `chart_data_<TICKER>` | Array aus Candle-Objekten | Worker → Redis | ChartsTab Candlestick (extern via `/market/data` bzw. `/market/ohlcv/...`) |
| `predictions_<TICKER>` | Liste aus `{ timestamp, predicted_price }` | Worker (AutoGluon) | Chart-Overlay (über `/ai/grok-insights` & `predictions_current` spiegeln) |
| `predictions_current` | Multi-Horizon Modell-Vorhersagen | Worker | Predictions-Widget (per REST abrufbar) |
| `portfolio_equity` | Equity-Zeitreihe (Timestamp, Wert) | Worker → Redis | Portfolio-Tab Chart (extern via `/portfolio/performance/summary`) |
| `portfolio_positions` | Liste offener Positionen | Worker → Redis | Portfolio-Tab Tabelle (extern via `/portfolio` erweitern) |
| `alpaca_account`, `alpaca_positions`, `alpaca_orders` | Alpaca-Snapshots | Worker | Portfolio/Trades Ansicht (REST in Arbeit) |
| `grok_top10`, `grok_topstocks_prediction`, `grok_deepersearch` | AI-Recommendations inkl. Sentiment/Reason | Worker (Grok Tasks) | Dashboard & Analytics (extern via `/ai/grok-insights`) |
| `system_status` | Backend Health Flags | Worker | Status-Panel (extern via `/system/database-stats` + Health-Endpunkte) |
| `ml_status`, `ml_training_log` | Trainingsfortschritt | Worker | Model Monitor (REST Endpoint TODO) |
| `manual_trigger_status` | Manuelle Trigger-Indikatoren | Worker | Buttons + Feedback (nur intern; extern via REST Trigger später) |
| `performance_metrics` | Latenz, Auslastung, Datenfrische | Worker | System-Monitor (extern via `/system/database-stats`) |
| `model_metrics_history`, `model_paths_multi` | AutoGluon-Modelldetails | Worker | ML-Tab (REST Endpoint TODO) |

> **Polling-Empfehlung:** Extern ausschließlich REST-Endpoints nutzen (Port 8000). Redis-Polling steht nur intern/VPN zur Verfügung; falls benötigt SSH-Tunnel auf Port 6379 einrichten.

## 4. Datenkontrakte (Beispiele)

### 4.1 Dashboard – Marktübersicht

- **Primärquelle:** `market_data` (Redis) und `/market/top-movers`
- **Darstellung:** Ticker-Grid mit Farbe (positiv/negativ), Chart-Sparkline optional.

```json
{
	"AAPL": {"price": 234.07, "change": 4.04, "change_percent": 1.76},
	"NVDA": {"price": 177.82, "change": 0.65, "change_percent": 0.37}
}
```

### 4.2 ChartsTab – Candles & Prognosen

- **Candles:** HTTP → `http://91.99.236.5:8000/market/ohlcv/{symbol}/multi`
- **Predictions-Overlay:** REST → `http://91.99.236.5:8000/ai/grok-insights` bzw. `predictions_current`
- **Fallback:** (nur intern) Redis → `chart_data_<SYMBOL>`

```json
[
	{"timestamp": 1696320300, "time": "2025-10-03T10:45:00Z", "open": 234.1, "high": 235.2, "low": 233.8, "close": 235.0, "volume": 1812300}
]
```

### 4.3 PortfolioTab – Equity & Positionen

- **Equity Chart:** `http://91.99.236.5:8000/portfolio/performance/summary` (Start). Optional intern Redis `portfolio_equity` für Live-Updates.
- **Positionen:** `http://91.99.236.5:8000/portfolio` (REST-Ausbau empfohlen). Intern weiter `portfolio_positions` verfügbar.
- **Account KPIs:** REST Ergänzung geplant; bis dahin nur intern via Redis `alpaca_account`.

```json
{
	"time": "2025-10-03T08:30:00Z",
	"avg_equity": 111230.54,
	"max_equity": 112045.12,
	"min_equity": 110982.33
}
```

### 4.4 AI Insights – Grok & ML

- **REST:** `/ai/grok-insights`
- **Redis-Spiegel:** `grok_top10`, `grok_deepersearch`
- **ML Modelle:** Redis `predictions_current`, `ml_status`

```json
{
	"topstocks": [
		{
			"ticker": "NVDA",
			"expected_gain": 2.4,
			"sentiment": 0.82,
			"reason": "Starker AI-Bereich, solide Earnings"
		}
	]
}
```

### 4.5 System/Training Monitor

- **Redis:** `system_status`, `ml_status`, `grok_status`, `manual_trigger_status`
- **REST:** `/system/database-stats`, `/training/status` (bestehender Endpoint, nicht gezeigt)

```json
{
	"redis_connected": true,
	"postgres_connected": true,
	"worker_running": true,
	"grok_api_active": true,
	"last_heartbeat": "2025-10-03T08:34:17.865463",
	"uptime_seconds": 40123
}
```

## 5. UI-Empfehlungen & Polling-Strategie

| Bereich | Datenquelle | Update-Intervall | Hinweise |
|---------|-------------|------------------|----------|
| Dashboard (marktweit) | Redis `market_data` | 5 s | Bei Ausfall REST-Endpoint `http://91.99.236.5:8000/market/latest/{ticker}` fallback |
| Candles & Prognosen | REST + Redis | On demand + 15 s | REST liefert historische Daten; Prognosen per Redis overlay |
| Portfolio | REST `http://91.99.236.5:8000/portfolio/performance/summary` (beim Öffnen), danach Redis | 30 s | Equity-Chart via Continuous Aggregate effizient |
| AI Insights | REST `http://91.99.236.5:8000/ai/grok-insights` | 5 Min | Werte ändern nur täglich oder nach manuellem Trigger |
| System Monitor | REST `http://91.99.236.5:8000/system/database-stats` + `/health` | 10 s | Für tiefere Diagnosen SSH/VPN → Redis `system_status` |

## 6. Qt-Integration (Snippet)

```cpp
// Beispiel: REST → JSON → Qt Model
QNetworkRequest req(QUrl("http://91.99.236.5:8000/market/top-movers"));
auto reply = networkManager->get(req);
connect(reply, &QNetworkReply::finished, this, [this, reply]() {
		auto doc = QJsonDocument::fromJson(reply->readAll());
		const auto gainers = doc["gainers"].toArray();
		for (const auto &item : gainers) {
				const auto obj = item.toObject();
				addRow(obj["ticker"].toString(), obj["change_percent"].toDouble());
		}
});
```

```cpp
// Optional (nur bei VPN/SSH): Redis Polling
// QString payload = redisClient->get("market_data");
// auto doc = QJsonDocument::fromJson(payload.toUtf8());
// auto marketObject = doc.object();
```

## 7. Offene Punkte / Nächste Schritte

1. **Worker-Feeds ergänzen:** Sicherstellen, dass alle oben genannten Redis-Keys regelmäßig aktualisiert werden (teilweise bereits implementiert, sonst TODO).
2. **Frontend wiring:** Tabs so erweitern, dass neue REST-Endpoints genutzt werden (Qt JSON Parsing + Models).
3. **Error Handling:** Fallback-Logik (REST → Redis → Mock) zentralisieren.
4. **Tests:** API-Responses mit `pytest`/`curl` verifizieren, UI Widgets manuell abnehmen.

---

_Stand: 03.10.2025 – bitte bei Schema- oder API-Änderungen aktualisieren._

## 8. ML/Training – Frontend Guide

Dieser Abschnitt bündelt alle derzeit verfügbaren ML-/Training-Infos für das Frontend.

Basis-URL extern: `http://91.99.236.5:8000`

### 8.1 REST-Endpoints (aktiv)

- GET `/training/status`
	- Laufstatus und Fortschritt (Redis-gestützt).
	- Beispiel-Response (gekürzt):
	```json
	{
		"status": "running",
		"progress": {
			"current_ticker": "AAPL",
			"current_horizon": 15,
			"completed_models": 8,
			"total_models": 24,
			"progress_percent": 33
		},
		"summary": {
			"total_tickers": 6,
			"completed_tickers": 2,
			"tickers_list": ["AAPL","NVDA"],
			"errors_count": 0
		},
		"timing": {"started_at": "2025-10-04T07:00:00Z", "completed_at": null},
		"errors": [],
		"ticker_results": {"AAPL": {"15": {"r2": 0.92, "mae": 0.12}}}
	}
	```

- POST `/training/start`
	- Startet Training im Worker; ohne Body nutzt der Worker Standardlisten (Portfolio/Grok Ticker).
	- Optionaler Body:
	```json
	{ "tickers": ["AAPL","NVDA"] }
	```
	- Beispiel-Response:
	```json
	{
		"success": true,
		"message": "Training command sent to worker",
		"monitor_endpoint": "/training/status",
		"note": "Training wird vom Worker verarbeitet"
	}
	```

- GET `/training/models`
	- Listet verfügbare AutoGluon-Modelle (aus `/app/models`).
	- Beispiel-Response (gekürzt):
	```json
	{
		"models": [
			{"ticker": "AAPL", "horizon": "15", "path": "autogluon_model_AAPL_15", "last_modified": "2025-10-03T21:41:03"},
			{"ticker": "NVDA", "horizon": "30", "path": "autogluon_model_NVDA_30", "last_modified": "2025-10-03T21:51:12"}
		],
		"total": 12,
		"statistics": {
			"unique_tickers": 6,
			"unique_horizons": 3,
			"by_ticker": {"AAPL": 3, "NVDA": 3},
			"by_horizon": {"15": 4, "30": 4, "60": 4}
		}
	}
	```

- GET `/training/history`
	- Historie der Trainingsläufe (aus `model_metrics_history` und `last_training_stats` in Redis).
	- Beispiel-Response (gekürzt):
	```json
	{
		"history": [
			{"ts": "2025-10-03T21:40:08Z", "ticker": "AAPL", "horizon": 15, "r2": 0.93, "mae": 0.11},
			{"ts": "2025-10-03T21:45:22Z", "ticker": "NVDA", "horizon": 30, "r2": 0.95, "mae": 0.09}
		],
		"last_training": {"started_at": "2025-10-03T21:32:00Z", "completed_at": "2025-10-03T21:58:00Z", "models": 18},
		"total_runs": 5
	}
	```

- GET `/ai/grok-insights`
	- Aktuelle Empfehlungen und DeeperSearch-Ergebnisse.

### 8.2 Interne Redis-Keys (nur VPN/SSH)

- `ml_status` → Trainingsstatus in Echtzeit
- `predictions_current` → aktuelle Multi-Horizon-Vorhersagen je Ticker
- `model_metrics_history` → Historie der Metriken je Horizon/Ticker

Hinweis: Extern vorzugsweise die REST-Endpoints nutzen; Redis nur intern.

### 8.3 Polling-Empfehlungen (ML)

- `/training/status`: alle 5–10 s während eines Laufs, sonst on demand
- `/training/models`: on demand (beim Öffnen ML-Tab)
- `/training/history`: on demand, optional Refresh alle 5–10 min
- `/ai/grok-insights`: alle 5–10 min oder nach manuellem Trigger

### 8.4 Fehler- und Fallback-Logik

- 404 bei leeren/fehlenden Daten (UI: neutrale States anzeigen, CTA „Training starten“)
- 500/503: Hinweis „Training temporär nicht verfügbar“, Retry mit Backoff
- Optional intern: Redis `ml_status` als schneller Fallback lesen
