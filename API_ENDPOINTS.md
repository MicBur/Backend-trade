# QBot Trading API - Complete Endpoint Reference

**Version:** 2.0.0  
**Base URL:** `http://91.99.236.5:8000`  
**Swagger UI:** `http://91.99.236.5:8000/docs`  
**OpenAPI JSON:** `http://91.99.236.5:8000/openapi.json`  
**ReDoc:** `http://91.99.236.5:8000/redoc`

**Last Tested:** 2025-10-08 ✅ All endpoints operational

---

## 📋 Quick Reference

| Category | Endpoints | Status |
|----------|-----------|--------|
| **Core** | `/`, `/health` | ✅ |
| **Portfolio** | `/portfolio`, `/positions`, `/trades` | ✅ |
| **Training** | `/training/*` (4 endpoints) | ✅ |
| **Market Data** | `/market/*` (4 endpoints) | ✅ |
| **Performance** | `/portfolio/performance`, `/portfolio/performance/summary` | ✅ |
| **AI/System** | `/ai/grok-insights`, `/system/database-stats` | ✅ |
| **Legacy** | `/portfolio/summary`, `/portfolio/positions`, `/trade/status` | ✅ |

**Total:** 20 REST endpoints

---

## 🔍 Core Endpoints

### `GET /`
Root endpoint with API info.

**Response:**
```json
{
  "message": "QBot Trading API",
  "version": "2.0.0",
  "status": "running"
}
```

### `GET /health`
Health check for monitoring.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-10-08T14:16:42.257513"
}
```

---

## 💼 Portfolio Endpoints

### `GET /portfolio`
Complete portfolio overview with positions.

**Response:**
```json
{
  "total_value": 110930.25,
  "cash": 99379.78,
  "equity": 110930.25,
  "total_profit": -123.45,
  "total_profit_percent": -0.11,
  "positions": [
    {
      "ticker": "AAPL",
      "quantity": 10,
      "avg_price": 150.00,
      "current_price": 258.02,
      "market_value": 2580.20,
      "profit": 1080.20,
      "profit_percent": 72.01
    }
  ]
}
```

### `GET /positions`
Detailed position data.

**Response:**
```json
{
  "positions": [
    {
      "ticker": "AAPL",
      "quantity": 10,
      "side": "long",
      "entry_price": 150.00,
      "current_price": 258.02,
      "market_value": 2580.20,
      "unrealized_pnl": 1080.20,
      "unrealized_pnl_percent": 72.01,
      "cost_basis": 1500.00
    }
  ],
  "count": 11
}
```

### `GET /trades`
Trading history (filled orders).

**Query Parameters:**
- `limit` (int, default: 50, max: 500) - Number of trades
- `ticker` (string, optional) - Filter by symbol

**Example:** `GET /trades?limit=10&ticker=AAPL`

**Response:**
```json
{
  "trades": [
    {
      "id": "32f75a97-df33-4996-b5bd-f4e35f0e2b5c",
      "ticker": "JPM",
      "side": "sell",
      "quantity": 1,
      "price": 312.5,
      "timestamp": "2025-10-01T13:31:58.197912Z",
      "status": "filled",
      "order_type": "market"
    }
  ],
  "count": 3,
  "filter": {"ticker": "AAPL"}
}
```

---

## 🤖 ML Training Endpoints

### `GET /training/status`
Live training progress with real-time metrics.

**Response:**
```json
{
  "status": "idle",
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
    "tickers_list": ["AAPL", "NVDA"],
    "errors_count": 0
  },
  "timing": {
    "started_at": "2025-10-04T07:00:00Z",
    "completed_at": null
  },
  "errors": [],
  "ticker_results": {
    "AAPL": {
      "15": {"r2": 0.92, "mae": 0.12}
    }
  }
}
```

### `POST /training/start`
Start manual training run.

**Request Body (optional):**
```json
{
  "tickers": ["AAPL", "NVDA"]
}
```

**Response:**
```json
{
  "success": true,
  "message": "Training command sent to worker",
  "monitor_endpoint": "/training/status",
  "note": "Training wird vom Worker verarbeitet"
}
```

### `GET /training/models`
List all trained AutoGluon models.

**Response:**
```json
{
  "models": [
    {
      "ticker": "AAPL",
      "horizon": "15",
      "path": "autogluon_model_AAPL_15",
      "last_modified": "2025-10-03T21:41:03"
    }
  ],
  "total": 33,
  "statistics": {
    "unique_tickers": 11,
    "unique_horizons": 3,
    "by_ticker": {"AAPL": 3, "NVDA": 3},
    "by_horizon": {"15": 11, "30": 11, "60": 11}
  }
}
```

### `GET /training/history`
Training run history and metrics.

**Response:**
```json
{
  "history": [
    {
      "ts": "2025-10-03T21:40:08Z",
      "ticker": "AAPL",
      "horizon": 15,
      "r2": 0.93,
      "mae": 0.11
    }
  ],
  "last_training": {
    "started_at": "2025-10-03T21:32:00Z",
    "completed_at": "2025-10-03T21:58:00Z",
    "models": 18
  },
  "total_runs": 5
}
```

---

## 📊 Market Data Endpoints

### `GET /market/latest/{symbol}`
Latest price for a symbol.

**Example:** `GET /market/latest/AAPL`

**Response:**
```json
{
  "symbol": "AAPL",
  "price": 258.02,
  "open": 254.67,
  "high": 259.24,
  "low": 253.95,
  "volume": 0,
  "change": -0.06,
  "change_percent": -0.02,
  "time": "2025-10-04T16:00:00+00:00",
  "timestamp": 1759593600
}
```

### `GET /market/data/{symbol}`
Historical OHLCV data for charts.

**Query Parameters:**
- `timeframe` (string, default: "15min") - `1min`, `5min`, `15min`, `30min`, `1hour`, `4hour`, `1day`
- `limit` (int, default: 100, max: 1000) - Number of candles
- `start` (string, optional) - ISO datetime (e.g. `2025-10-01T00:00:00`)
- `end` (string, optional) - ISO datetime

**Example:** `GET /market/data/AAPL?timeframe=15min&limit=100`

**Response:**
```json
{
  "symbol": "AAPL",
  "timeframe": "15min",
  "count": 100,
  "data": [
    {
      "time": "2025-10-03T08:45:00+00:00",
      "timestamp": 1759481100,
      "open": 256.575,
      "high": 258.18,
      "low": 254.15,
      "close": 257.135,
      "volume": 0
    }
  ]
}
```

### `GET /market/ohlcv/{symbol}/multi`
Multiple timeframes in one request.

**Query Parameters:**
- `timeframes` (string) - Comma-separated list (e.g. `15min,1hour,1day`)
- `limit` (int, default: 100, max: 1000) - Candles per timeframe

**Example:** `GET /market/ohlcv/AAPL/multi?timeframes=15min,1hour&limit=50`

**Response:**
```json
{
  "symbol": "AAPL",
  "timeframes": {
    "15min": [...],
    "1hour": [...]
  },
  "requested": ["15min", "1hour"]
}
```

### `GET /market/top-movers`
Top gainers and losers of the day.

**Query Parameters:**
- `limit` (int, default: 10) - Results per category

**Response:**
```json
{
  "gainers": [
    {
      "ticker": "NVDA",
      "open": 100.00,
      "close": 115.50,
      "change_percent": 15.50,
      "high": 116.00,
      "low": 99.80
    }
  ],
  "losers": [...],
  "timestamp": "2025-10-08T14:16:42Z"
}
```

---

## 📈 Portfolio Performance Endpoints

### `GET /portfolio/performance`
Detailed performance over time (hourly aggregates).

**Query Parameters:**
- `days` (int, default: 30) - Lookback period

**Response:**
```json
{
  "performance": [
    {
      "time": "2025-10-03T12:00:00+00:00",
      "timestamp": 1759492800,
      "avg_equity": 111214.13,
      "max_equity": 111224.65,
      "min_equity": 111210.89,
      "avg_cash": 99379.78,
      "avg_buying_power": 198759.56
    }
  ],
  "current_stats": {
    "current_equity": null,
    "current_cash": null,
    "current_buying_power": null,
    "data_points": 0
  },
  "period_days": 7
}
```

### `GET /portfolio/performance/summary`
Compact performance overview (continuous aggregate).

**Query Parameters:**
- `limit` (int, default: 168, max: 720) - Number of hourly data points

**Response:**
```json
{
  "series": [
    {
      "time": "2025-10-03T12:00:00+00:00",
      "timestamp": 1759492800,
      "avg_equity": 111214.13,
      "max_equity": 111224.65,
      "min_equity": 111210.89
    }
  ],
  "summary": {
    "latest_equity": 111210.89,
    "first_equity": 111214.13,
    "change_absolute": -3.24,
    "change_percent": -0.00,
    "min_equity": 111210.89,
    "max_equity": 111224.65,
    "count": 10
  },
  "limit": 10,
  "generated_at": "2025-10-08T14:16:42Z"
}
```

---

## 🧠 AI & System Endpoints

### `GET /ai/grok-insights`
Grok AI analysis and recommendations.

**Query Parameters:**
- `limit` (int, default: 20) - Results per category

**Response:**
```json
{
  "topstocks": [
    {
      "time": "2025-10-08T10:00:00+00:00",
      "ticker": "NVDA",
      "expected_gain": 8.5,
      "sentiment": 0.92,
      "reason": "Strong AI chip demand"
    }
  ],
  "recommendations": [...],
  "deepersearch": [...],
  "total_insights": 15
}
```

### `GET /system/database-stats`
TimescaleDB performance metrics.

**Response:**
```json
{
  "hypertables": [
    {
      "schema": "public",
      "name": "market_data",
      "owner": "postgres",
      "dimensions": 1,
      "chunks": 42,
      "compression_enabled": true
    }
  ],
  "continuous_aggregates": [
    {
      "schema": "public",
      "view": "market_data_15min",
      "materialization": "_materialized_hypertable_2"
    }
  ],
  "compression": [...],
  "table_sizes": [
    {"table": "market_data", "size": "1234 MB"}
  ],
  "data_counts": [
    {"table": "market_data", "rows": 1500000}
  ],
  "timescaledb_version": "2.22.1"
}
```

---

## 🔄 Legacy Endpoints (Deprecated)

These endpoints redirect to their modern equivalents:

| Legacy | Modern |
|--------|--------|
| `GET /portfolio/summary` | `GET /portfolio` |
| `GET /portfolio/positions` | `GET /positions` |

### `GET /trade/status`
Trading automation status (legacy).

**Response:**
```json
{
  "autotrading_enabled": null,
  "backend_status": null,
  "last_error": null
}
```

---

## 🛠️ Testing & Development

### Swagger UI (Interactive)
Open in browser: `http://91.99.236.5:8000/docs`

Features:
- Try out all endpoints live
- Auto-generated request/response schemas
- Parameter documentation
- Authentication testing

### ReDoc (Read-Only Documentation)
Open in browser: `http://91.99.236.5:8000/redoc`

### cURL Examples

```bash
# Health check
curl http://91.99.236.5:8000/health

# Get portfolio
curl http://91.99.236.5:8000/portfolio

# Get AAPL latest price
curl http://91.99.236.5:8000/market/latest/AAPL

# Get AAPL 15min chart data
curl "http://91.99.236.5:8000/market/data/AAPL?timeframe=15min&limit=100"

# Multi-timeframe data
curl "http://91.99.236.5:8000/market/ohlcv/AAPL/multi?timeframes=15min,1hour,1day&limit=50"

# Start ML training
curl -X POST http://91.99.236.5:8000/training/start

# Check training status
curl http://91.99.236.5:8000/training/status

# List trained models
curl http://91.99.236.5:8000/training/models

# Get Grok AI insights
curl "http://91.99.236.5:8000/ai/grok-insights?limit=10"

# Database stats
curl http://91.99.236.5:8000/system/database-stats
```

### Python Example

```python
import requests

BASE_URL = "http://91.99.236.5:8000"

# Get health
health = requests.get(f"{BASE_URL}/health").json()
print(health)

# Get portfolio
portfolio = requests.get(f"{BASE_URL}/portfolio").json()
print(f"Total Value: ${portfolio['total_value']:,.2f}")

# Get market data
data = requests.get(
    f"{BASE_URL}/market/data/AAPL",
    params={"timeframe": "15min", "limit": 100}
).json()
print(f"Retrieved {data['count']} candles for {data['symbol']}")

# Start training
response = requests.post(f"{BASE_URL}/training/start").json()
print(response['message'])
```

---

## 📝 Response Codes

| Code | Meaning |
|------|---------|
| `200` | Success |
| `400` | Bad Request (invalid parameters) |
| `404` | Not Found (symbol/resource not found) |
| `500` | Internal Server Error |
| `503` | Service Unavailable (external API timeout) |

---

## 🔐 Security Notes

- **API Keys**: Not required for read operations
- **Write Operations**: Only `/training/start` is POST (no authentication yet)
- **Rate Limiting**: Not implemented (consider for production)
- **CORS**: Enabled for all origins (`*`)

---

## 📌 Key Features

✅ **Real-time Data**: Sub-second latency for latest prices  
✅ **Multi-Timeframe**: 1min to 1day candles from single source  
✅ **ML Integration**: Live training status & model management  
✅ **TimescaleDB**: Optimized time-series queries with continuous aggregates  
✅ **Alpaca Integration**: Live paper trading positions & orders  
✅ **Grok AI**: Market analysis & recommendations  
✅ **Swagger UI**: Interactive API documentation  

---

**Last Updated:** 2025-10-08  
**Status:** ✅ Production Ready  
**Repository:** https://github.com/MicBur/Backend-trade
