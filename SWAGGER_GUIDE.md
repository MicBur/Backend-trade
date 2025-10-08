# 🚀 QBot API - Swagger UI & Testing Guide

## 📋 Quick Access

| Resource | URL |
|----------|-----|
| **Swagger UI** (Interactive) | http://91.99.236.5:8000/docs |
| **ReDoc** (Pretty Docs) | http://91.99.236.5:8000/redoc |
| **OpenAPI JSON** | http://91.99.236.5:8000/openapi.json |
| **Health Check** | http://91.99.236.5:8000/health |

---

## 📖 Using Swagger UI

### 1. Open in Browser
```
http://91.99.236.5:8000/docs
```

### 2. Features

#### ✅ Try It Out
1. Click on any endpoint to expand
2. Click "Try it out" button
3. Fill in parameters (if needed)
4. Click "Execute"
5. See response below

#### ✅ Auto-Generated Schemas
- Request body schemas
- Response schemas
- Parameter descriptions
- Example values

#### ✅ Categories
All 20 endpoints organized by:
- **default** - Core & Portfolio
- **Training** - ML operations
- **Market** - Market data
- **Performance** - Charts & metrics
- **AI** - Grok insights
- **System** - Database stats

---

## 🧪 Testing Endpoints

### Option 1: Swagger UI (Recommended)
**Best for:** Interactive testing, exploring schemas

1. Open http://91.99.236.5:8000/docs
2. Click endpoint → "Try it out"
3. Fill parameters → "Execute"
4. View response

### Option 2: Python Script
**Best for:** Automated testing, CI/CD

```bash
cd /home/pool/qbot
python3 scripts/test_endpoints.py
```

**Output:**
```
============================================================
🤖 QBot API Endpoint Tester
============================================================

#   Method Endpoint                                      Status   Code  Description
------------------------------------------------------------------------------------------
1   GET    /                                             ✅ PASS  200  Root Endpoint
2   GET    /health                                       ✅ PASS  200  Health Check
...
19  GET    /system/database-stats                        ✅ PASS  200  Database Statistics

📊 Test Summary:
   Total Endpoints: 19
   ✅ Passed: 19
   ❌ Failed: 0
   Success Rate: 100.0%
```

### Option 3: cURL
**Best for:** Quick checks, shell scripting

```bash
# Health check
curl http://91.99.236.5:8000/health

# Portfolio
curl http://91.99.236.5:8000/portfolio

# Market data with parameters
curl "http://91.99.236.5:8000/market/data/AAPL?timeframe=15min&limit=100"

# POST request (training)
curl -X POST http://91.99.236.5:8000/training/start \
  -H "Content-Type: application/json"
```

### Option 4: Postman Collection
**Best for:** Team collaboration, request collections

Import OpenAPI spec:
```
http://91.99.236.5:8000/openapi.json
```

---

## 📊 All Endpoints (20 Total)

### Core (2)
- `GET /` - API info
- `GET /health` - Health status

### Portfolio (6)
- `GET /portfolio` - Complete overview
- `GET /positions` - Position details
- `GET /trades` - Trade history
- `GET /portfolio/summary` *(legacy)*
- `GET /portfolio/positions` *(legacy)*
- `GET /trade/status` - Automation status

### Training (4)
- `GET /training/status` - Live progress
- `POST /training/start` - Start training
- `GET /training/models` - List models
- `GET /training/history` - Past runs

### Market (4)
- `GET /market/latest/{symbol}` - Current price
- `GET /market/data/{symbol}` - OHLCV candles
- `GET /market/ohlcv/{symbol}/multi` - Multi-timeframe
- `GET /market/top-movers` - Gainers/losers

### Performance (2)
- `GET /portfolio/performance` - Hourly data
- `GET /portfolio/performance/summary` - Summary

### AI & System (2)
- `GET /ai/grok-insights` - AI recommendations
- `GET /system/database-stats` - DB metrics

---

## 💡 Example Workflows

### Workflow 1: Check System Health
```bash
# 1. Check API
curl http://91.99.236.5:8000/health

# 2. Check database
curl http://91.99.236.5:8000/system/database-stats

# 3. Check training
curl http://91.99.236.5:8000/training/status
```

### Workflow 2: Analyze Portfolio
```bash
# 1. Get overview
curl http://91.99.236.5:8000/portfolio

# 2. Get positions
curl http://91.99.236.5:8000/positions

# 3. Get performance
curl "http://91.99.236.5:8000/portfolio/performance?days=30"
```

### Workflow 3: Market Analysis
```bash
# 1. Latest price
curl http://91.99.236.5:8000/market/latest/AAPL

# 2. Chart data
curl "http://91.99.236.5:8000/market/data/AAPL?timeframe=15min&limit=100"

# 3. AI insights
curl http://91.99.236.5:8000/ai/grok-insights
```

### Workflow 4: ML Training
```bash
# 1. Check status
curl http://91.99.236.5:8000/training/status

# 2. Start training
curl -X POST http://91.99.236.5:8000/training/start

# 3. Monitor (repeat)
curl http://91.99.236.5:8000/training/status

# 4. List models
curl http://91.99.236.5:8000/training/models
```

---

## 🐍 Python Client Example

```python
import requests
from typing import Dict, List

class QBotAPI:
    def __init__(self, base_url: str = "http://91.99.236.5:8000"):
        self.base_url = base_url
    
    def health(self) -> Dict:
        return requests.get(f"{self.base_url}/health").json()
    
    def portfolio(self) -> Dict:
        return requests.get(f"{self.base_url}/portfolio").json()
    
    def positions(self) -> List[Dict]:
        data = requests.get(f"{self.base_url}/positions").json()
        return data["positions"]
    
    def trades(self, limit: int = 50, ticker: str = None) -> List[Dict]:
        params = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        data = requests.get(f"{self.base_url}/trades", params=params).json()
        return data["trades"]
    
    def latest_price(self, symbol: str) -> Dict:
        return requests.get(f"{self.base_url}/market/latest/{symbol}").json()
    
    def market_data(self, symbol: str, timeframe: str = "15min", limit: int = 100) -> Dict:
        params = {"timeframe": timeframe, "limit": limit}
        return requests.get(f"{self.base_url}/market/data/{symbol}", params=params).json()
    
    def start_training(self, tickers: List[str] = None) -> Dict:
        json_data = {"tickers": tickers} if tickers else None
        return requests.post(f"{self.base_url}/training/start", json=json_data).json()
    
    def training_status(self) -> Dict:
        return requests.get(f"{self.base_url}/training/status").json()

# Usage
api = QBotAPI()

# Check health
print(api.health())

# Get portfolio
portfolio = api.portfolio()
print(f"Portfolio Value: ${portfolio['total_value']:,.2f}")

# Get AAPL price
aapl = api.latest_price("AAPL")
print(f"AAPL: ${aapl['price']:.2f} ({aapl['change_percent']:+.2f}%)")

# Start ML training
result = api.start_training(["AAPL", "NVDA"])
print(result['message'])
```

---

## 📝 Response Formats

### Success Response (200)
```json
{
  "data": [...],
  "count": 10,
  "timestamp": "2025-10-08T14:00:00Z"
}
```

### Error Response (4xx/5xx)
```json
{
  "detail": "Error message here"
}
```

---

## 🔒 Security

- ✅ CORS enabled for all origins
- ⚠️ No authentication yet (planned)
- ⚠️ No rate limiting (planned)
- ✅ Read operations safe
- ⚠️ Write operations limited to `/training/start`

---

## 🐛 Troubleshooting

### Issue: Endpoint returns 404
**Solution:** Check URL spelling, symbol exists

### Issue: Timeout
**Solution:** Check network, try external URL

### Issue: Empty data
**Solution:** Data might not exist, check recent market hours

### Issue: 500 Error
**Solution:** Check logs: `docker logs qbot-fastapi-1`

---

## 📚 Documentation Files

- [API_ENDPOINTS.md](../API_ENDPOINTS.md) - Complete reference
- [API_STATUS.md](../API_STATUS.md) - Test results
- [wire.md](../wire.md) - Frontend guide
- [README_BACKEND.md](../README_BACKEND.md) - Backend setup

---

## 🎯 Status

✅ **19/19 endpoints operational** (100% success rate)  
✅ **Swagger UI fully functional**  
✅ **All schemas documented**  
✅ **Automated tests passing**  

**Last Tested:** 2025-10-08  
**Version:** 2.0.0  
**Repository:** https://github.com/MicBur/Backend-trade
