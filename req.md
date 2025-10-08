# 🤖 Backend Requirements für ML Trading System

## 📋 **Erforderliche Redis-Keys für Frontend**

Das Frontend erwartet folgende Redis-Keys vom Backend, um dynamische Multi-Ticker ML-Predictions anzuzeigen:

### 🏦 **Portfolio-Daten**
```redis
portfolio_positions
```
**Format:** JSON Array
```json
[
  {
    "ticker": "AAPL",
    "symbol": "AAPL", 
    "qty": "100",
    "market_value": "18025.00",
    "unrealized_pl": "1250.75"
  },
  {
    "ticker": "MSFT",
    "symbol": "MSFT",
    "qty": "50", 
    "market_value": "21500.00",
    "unrealized_pl": "-325.50"
  }
]
```

### 🤖 **Grok AI Kandidaten**
```redis
grok_topstocks_prediction
```
**Format:** JSON Array
```json
[
  {
    "ticker": "GOOGL",
    "score": 0.95,
    "reason": "Strong AI momentum",
    "expected_gain": 0.08
  },
  {
    "ticker": "NVDA", 
    "score": 0.88,
    "reason": "GPU demand surge",
    "expected_gain": 0.12
  }
]
```

### 📊 **Historische Daten (pro Ticker)**
```redis
yfinance_enhanced:{TICKER}  # z.B. yfinance_enhanced:AAPL
```
**Format:** JSON Object
```json
{
  "ticker": "AAPL",
  "timestamp": "2025-09-28T15:30:00Z",
  "historical_data": [
    {
      "date": "2025-09-24",
      "ticker": "AAPL", 
      "open": 180.50,
      "high": 182.00,
      "low": 179.25,
      "close": 181.75,
      "volume": 45000000
    },
    {
      "date": "2025-09-25",
      "ticker": "AAPL",
      "open": 181.75,
      "high": 183.50,
      "low": 180.80,
      "close": 182.45,
      "volume": 42000000
    }
    // ... mindestens 5 Tage für Historie
  ]
}
```

### 🔮 **ML Vorhersagen**
```redis
backend:ml_predictions_enhanced
```
**Format:** JSON Object
```json
{
  "AAPL": {
    "current_price": 182.45,
    "timestamp": "2025-09-28T15:30:00Z",
    "horizons": {
      "15": {
        "predicted_price": 183.20,
        "confidence": 0.87,
        "change_pct": 0.0041
      },
      "30": {
        "predicted_price": 184.15,
        "confidence": 0.82,
        "change_pct": 0.0093
      },
      "60": {
        "predicted_price": 185.90,
        "confidence": 0.75,
        "change_pct": 0.0189
      }
    }
  },
  "MSFT": {
    // ... gleiche Struktur für jeden Ticker
  }
}
```

## 🔄 **Update-Frequenzen**

| Redis-Key | Update-Frequenz | Zweck |
|-----------|----------------|-------|
| `portfolio_positions` | Alle 30 Sekunden | Live Portfolio-Sync |
| `grok_topstocks_prediction` | Alle 5 Minuten | AI-Kandidaten |  
| `yfinance_enhanced:{TICKER}` | Alle 15 Minuten | Historische Daten |
| `backend:ml_predictions_enhanced` | Alle 2 Minuten | ML-Vorhersagen |

## ⚡ **Dynamisches Ticker-System**

Das Frontend erstellt automatisch die Ticker-Liste aus:

1. **Portfolio-Tickers:** Alle Tickers aus `portfolio_positions`
2. **Grok-Kandidaten:** Top 5 Tickers aus `grok_topstocks_prediction`
3. **Keine Hardcoded-Tickers:** System passt sich automatisch an

**Beispiel:**
- Portfolio: [AAPL, MSFT, TSLA]
- Grok Top 5: [GOOGL, NVDA, META, AMZN, NFLX]
- → Frontend zeigt ML-Predictions für alle 8 Tickers

## 🚨 **Wichtige Hinweise**

1. **Keine Fallbacks:** Frontend zeigt nur echte Daten, keine hardcodierten Ticker
2. **Fehlende Daten:** Ticker ohne `yfinance_enhanced` Daten zeigen Fehlermeldung
3. **Leere Keys:** Wenn `portfolio_positions` UND `grok_topstocks_prediction` leer → "Warten auf Backend"-Nachricht
4. **Redis-Struktur:** Alle Keys müssen exakt diese JSON-Struktur haben

## 🔧 **Backend-Implementation Checklist**

- [ ] `portfolio_positions` Array mit aktuellen Holdings
- [ ] `grok_topstocks_prediction` Array mit AI-Kandidaten
- [ ] `yfinance_enhanced:{TICKER}` für jeden aktiven Ticker
- [ ] `backend:ml_predictions_enhanced` mit Multi-Horizon Predictions
- [ ] Automatische Updates in definierten Intervallen
- [ ] Fehlerbehandlung für API-Ausfälle

## 📱 **Frontend-Verhalten**

Das Frontend fragt diese Keys alle 45 Sekunden ab und baut dynamisch:
- ML Prediction Cards (6-8 Ticker)
- Historische 5-Tage Charts
- 60min Vorhersage-Trends
- Portfolio + Grok Integration

**Kein Backend-Data = Keine ML-Predictions** (wie gewünscht - keine Hardcoding!)