"""
QBot Trading System - FastAPI Backend mit Training Monitoring
Erweitert um Sequential Training Endpoints
"""

import os
import json
import redis
import requests
import psycopg2
from contextlib import contextmanager
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

# Redis Connection
redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = int(os.getenv("REDIS_PORT", 6379))
redis_password = os.getenv("REDIS_PASSWORD", "pass123")

try:
    r = redis.Redis(
        host=redis_host,
        port=redis_port,
        password=redis_password,
        decode_responses=True,
    )
    r.ping()
    print(f"✅ Redis connected: {redis_host}:{redis_port}")
except Exception as redis_error:
    print(f"❌ Redis connection failed: {redis_error}")
    r = None

# Alpaca API Configuration
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")
ALPACA_BASE_URL = os.getenv("ALPACA_API_URL", "https://paper-api.alpaca.markets")

# FastAPI App
app = FastAPI(title="QBot Trading API", version="2.0.0")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_db_config() -> Dict[str, object]:
    """Liefert die PostgreSQL/TimescaleDB Verbindungsparameter."""
    return {
        "host": os.getenv("POSTGRES_HOST", "timescaledb"),
        "port": int(os.getenv("POSTGRES_PORT", 5432)),
        "database": os.getenv("POSTGRES_DB", "qbot"),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", "pass123"),
    }


@contextmanager
def db_connection(readonly: bool = True):
    """Context Manager für eine PostgreSQL-Connection mit automatischem Close."""
    conn = psycopg2.connect(**_get_db_config())
    try:
        if readonly:
            conn.set_session(readonly=True, autocommit=True)
        else:
            conn.autocommit = True
        yield conn
    finally:
        conn.close()


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parst ISO-Strings (inkl. 'Z') in datetime oder None."""
    if not value:
        return None

    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {value}") from exc


def ensure_limit(value: int, default: int = 100, maximum: int = 1000) -> int:
    """Sichert Limit-Parameter gegen zu große Werte ab."""
    if value is None:
        return default
    value = max(1, int(value))
    return min(value, maximum)


def fetch_timescale_candles(
    symbol: str,
    timeframe: str,
    limit_val: int,
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
) -> List[Dict[str, object]]:
    """Liest OHLCV-Daten aus TimescaleDB für ein beliebiges Zeitfenster."""

    timeframe = timeframe.lower()

    aggregate_map = {
        "15min": "market_data_15min",
        "1hour": "market_data_1hour",
        "1day": "market_data_1day",
    }

    timeframe_map = {
        "1min": "1 minute",
        "5min": "5 minutes",
        "30min": "30 minutes",
        "4hour": "4 hours",
    }

    trunc_unit_map = {
        "1min": "minute",
        "5min": "minute",
        "30min": "minute",
        "4hour": "hour",
    }

    filter_clauses: List[str] = []
    filter_column = "bucket" if timeframe in aggregate_map else "time"

    params: List[object] = [symbol.upper()]
    if start_dt:
        filter_clauses.append(f"{filter_column} >= %s")
        params.append(start_dt)
    if end_dt:
        filter_clauses.append(f"{filter_column} <= %s")
        params.append(end_dt)

    time_filter = ""
    if filter_clauses:
        time_filter = " AND " + " AND ".join(filter_clauses)

    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                if timeframe in aggregate_map:
                    table_name = aggregate_map[timeframe]
                    query = f"""
                        SELECT
                            bucket,
                            ticker,
                            open,
                            high,
                            low,
                            close,
                            volume
                        FROM {table_name}
                        WHERE ticker = %s{time_filter}
                        ORDER BY bucket DESC
                        LIMIT %s
                    """
                elif timeframe in timeframe_map:
                    trunc_unit = trunc_unit_map[timeframe]

                    if timeframe in {"5min", "30min"}:
                        minutes_divisor = int(timeframe.replace("min", ""))
                        bucket_expr = f"""
                            date_trunc('{trunc_unit}', time) +
                            INTERVAL '{minutes_divisor} minutes' *
                            FLOOR(EXTRACT(minute FROM time) / {minutes_divisor})
                        """
                    elif timeframe == "4hour":
                        bucket_expr = """
                            date_trunc('day', time) +
                            INTERVAL '4 hours' * FLOOR(EXTRACT(hour FROM time) / 4)
                        """
                    else:
                        bucket_expr = f"date_trunc('{trunc_unit}', time)"

                    query = f"""
                        SELECT
                            {bucket_expr} AS bucket,
                            ticker,
                            (array_agg(open ORDER BY time))[1] AS open,
                            MAX(high) AS high,
                            MIN(low) AS low,
                            (array_agg(close ORDER BY time DESC))[1] AS close,
                            SUM(volume) AS volume
                        FROM market_data
                        WHERE ticker = %s{time_filter}
                        GROUP BY bucket, ticker
                        ORDER BY bucket DESC
                        LIMIT %s
                    """
                else:
                    allowed = sorted(list(aggregate_map.keys()) + list(timeframe_map.keys()))
                    raise HTTPException(status_code=400, detail=f"Invalid timeframe. Allowed: {allowed}")

                execute_params = [*params, limit_val]
                cur.execute(query, execute_params)
                rows = cur.fetchall()

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    candles: List[Dict[str, object]] = []
    for row in reversed(rows):  # Chronologisch sortieren
        bucket_time, ticker, open_p, high_p, low_p, close_p, vol = row
        if bucket_time is None:
            continue
        candles.append(
            {
                "time": bucket_time.isoformat(),
                "timestamp": int(bucket_time.timestamp()),
                "open": float(open_p) if open_p is not None else None,
                "high": float(high_p) if high_p is not None else None,
                "low": float(low_p) if low_p is not None else None,
                "close": float(close_p) if close_p is not None else None,
                "volume": int(vol) if vol is not None else 0,
            }
        )

    return candles

def get_alpaca_headers():
    return {
        'APCA-API-KEY-ID': ALPACA_API_KEY,
        'APCA-API-SECRET-KEY': ALPACA_SECRET,
        'Content-Type': 'application/json'
    }

# ===== EXISTING ENDPOINTS (Summary - full implementation needed) =====

@app.get("/")
async def root():
    return {"message": "QBot Trading API", "version": "2.0.0", "status": "running"}

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/portfolio")
async def get_portfolio():
    """
    Portfolio Overview (API.md Endpoint #5)
    Aktueller Portfolio-Wert, Positionen, Gewinn/Verlust
    """
    try:
        # Account Info
        response = requests.get(
            f"{ALPACA_BASE_URL}/v2/account",
            headers=get_alpaca_headers(),
            timeout=10
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Alpaca API error")
        
        account = response.json()
        
        # Positions
        pos_response = requests.get(
            f"{ALPACA_BASE_URL}/v2/positions",
            headers=get_alpaca_headers(),
            timeout=10
        )
        positions_data = pos_response.json() if pos_response.status_code == 200 else []
        
        # Format Positions
        formatted_positions = []
        for pos in positions_data:
            formatted_positions.append({
                "ticker": pos.get("symbol"),
                "quantity": int(pos.get("qty", 0)),
                "avg_price": float(pos.get("avg_entry_price", 0)),
                "current_price": float(pos.get("current_price", 0)),
                "market_value": float(pos.get("market_value", 0)),
                "profit": float(pos.get("unrealized_pl", 0)),
                "profit_percent": float(pos.get("unrealized_plpc", 0)) * 100
            })
        
        # Calculate totals
        portfolio_value = float(account.get("portfolio_value", 0))
        cash = float(account.get("cash", 0))
        equity = float(account.get("equity", 0))
        
        # Total profit (unrealized)
        total_profit = sum(p["profit"] for p in formatted_positions)
        total_profit_percent = (total_profit / equity * 100) if equity > 0 else 0
        
        return {
            "total_value": portfolio_value,
            "cash": cash,
            "equity": equity,
            "total_profit": total_profit,
            "total_profit_percent": round(total_profit_percent, 2),
            "positions": formatted_positions
        }
        
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Alpaca API unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/positions")
async def get_positions():
    """
    Active Positions (API.md Endpoint #6)
    Detaillierte Positionsübersicht
    """
    try:
        response = requests.get(
            f"{ALPACA_BASE_URL}/v2/positions",
            headers=get_alpaca_headers(),
            timeout=10
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Alpaca API error")
        
        positions_data = response.json()
        
        formatted_positions = []
        for pos in positions_data:
            formatted_positions.append({
                "ticker": pos.get("symbol"),
                "quantity": int(pos.get("qty", 0)),
                "side": pos.get("side", "long"),
                "entry_price": float(pos.get("avg_entry_price", 0)),
                "current_price": float(pos.get("current_price", 0)),
                "market_value": float(pos.get("market_value", 0)),
                "unrealized_pnl": float(pos.get("unrealized_pl", 0)),
                "unrealized_pnl_percent": float(pos.get("unrealized_plpc", 0)) * 100,
                "cost_basis": float(pos.get("cost_basis", 0))
            })
        
        return {
            "positions": formatted_positions,
            "count": len(formatted_positions)
        }
        
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Alpaca API unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/trades")
async def get_trades(limit: int = 50, ticker: str = None):
    """
    Trading History (API.md Endpoint #7)
    Zeigt abgeschlossene Trades
    
    Query Parameters:
    - limit: Anzahl Trades (default: 50, max: 500)
    - ticker: Filter nach Symbol (optional)
    """
    try:
        limit = min(limit, 500)  # Max 500
        
        # Alpaca Orders (closed/filled)
        response = requests.get(
            f"{ALPACA_BASE_URL}/v2/orders",
            headers=get_alpaca_headers(),
            params={
                "status": "closed",
                "limit": limit,
                "direction": "desc"
            },
            timeout=10
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Alpaca API error")
        
        orders = response.json()
        
        # Filter by ticker if specified
        if ticker:
            orders = [o for o in orders if o.get("symbol") == ticker.upper()]
        
        # Format trades
        formatted_trades = []
        for order in orders:
            filled_at = order.get("filled_at")
            
            formatted_trades.append({
                "id": order.get("id"),
                "ticker": order.get("symbol"),
                "side": order.get("side"),  # buy/sell
                "quantity": int(order.get("filled_qty", 0)),
                "price": float(order.get("filled_avg_price", 0)),
                "timestamp": filled_at,
                "status": order.get("status"),
                "order_type": order.get("type")
            })
        
        return {
            "trades": formatted_trades,
            "count": len(formatted_trades),
            "filter": {"ticker": ticker} if ticker else None
        }
        
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Alpaca API unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/portfolio/summary")
async def portfolio_summary():
    """Legacy endpoint - redirects to /portfolio"""
    return await get_portfolio()

@app.get("/portfolio/positions")
async def portfolio_positions():
    """Legacy endpoint - redirects to /positions"""
    return await get_positions()

@app.get("/trade/status")
async def get_trading_status():
    """Trading Status"""
    try:
        status_data = {
            "autotrading_enabled": r.get("autotrading:status") if r else None,
            "backend_status": r.get("backend:status") if r else None,
            "last_error": r.get("trading:last_error") if r else None
        }
        return status_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ===== NEW: ML TRAINING MONITORING ENDPOINTS =====

@app.get("/training/status")
async def get_training_status():
    """
    Aktueller Training-Status mit Live-Progress
    Frontend kann Fortschritt überwachen
    """
    try:
        if not r:
            return {"status": "error", "message": "Redis not connected"}
            
        status_data = r.get("training:status")
        
        if not status_data:
            return {
                "status": "idle",
                "message": "No training in progress",
                "last_training": None
            }
        
        status = json.loads(status_data)
        
        return {
            "status": status.get("status"),
            "progress": {
                "current_ticker": status.get("current_ticker"),
                "current_horizon": status.get("current_horizon"),
                "completed_models": status.get("completed_models", 0),
                "total_models": status.get("total_models", 0),
                "progress_percent": status.get("progress_percent", 0)
            },
            "summary": {
                "total_tickers": status.get("total_tickers", 0),
                "completed_tickers": len(status.get("completed_tickers", [])),
                "tickers_list": status.get("completed_tickers", []),
                "errors_count": len(status.get("errors", []))
            },
            "timing": {
                "started_at": status.get("started_at"),
                "completed_at": status.get("completed_at")
            },
            "errors": status.get("errors", [])[-10:],  # Letzte 10 Fehler
            "ticker_results": status.get("ticker_results", {})
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/training/start")
async def start_training():
    """
    Startet sequenzielles Training manuell
    Trainiert alle Portfolio + Grok Tickers
    """
    try:
        if not r:
            return {"success": False, "message": "Redis not connected"}
            
        # Prüfen ob Training bereits läuft
        status_data = r.get("training:status")
        if status_data:
            status = json.loads(status_data)
            if status.get("status") == "running":
                return {
                    "success": False,
                    "message": "Training already in progress",
                    "current_progress": status.get("progress_percent", 0),
                    "current_ticker": status.get("current_ticker")
                }
        
        # Training-Command setzen (Worker wird es aufnehmen)
        r.set("training:command", "start")
        r.expire("training:command", 300)  # 5 Minuten TTL
        
        return {
            "success": True,
            "message": "Training command sent to worker",
            "monitor_endpoint": "/training/status",
            "note": "Training wird vom Worker verarbeitet"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/training/models")
async def get_trained_models():
    """
    Liste aller trainierten Modelle
    Zeigt verfügbare Ticker und Horizons
    """
    try:
        models_dir = "/app/models"
        
        if not os.path.exists(models_dir):
            return {"models": [], "total": 0, "message": "Models directory not found"}
        
        models = []
        for item in os.listdir(models_dir):
            if item.startswith("autogluon_model_"):
                parts = item.replace("autogluon_model_", "").split("_")
                if len(parts) >= 2:
                    ticker = parts[0]
                    horizon = parts[1]
                    
                    model_path = os.path.join(models_dir, item)
                    
                    try:
                        last_modified = os.path.getmtime(model_path)
                        modified_date = datetime.fromtimestamp(last_modified).isoformat()
                    except:
                        modified_date = None
                    
                    model_info = {
                        "ticker": ticker,
                        "horizon": horizon,
                        "path": item,
                        "last_modified": modified_date
                    }
                    models.append(model_info)
        
        # Nach Datum sortieren (neueste zuerst)
        models.sort(key=lambda x: x.get("last_modified", ""), reverse=True)
        
        # Statistiken
        by_ticker = {}
        by_horizon = {}
        
        for m in models:
            ticker = m["ticker"]
            horizon = m["horizon"]
            
            by_ticker[ticker] = by_ticker.get(ticker, 0) + 1
            by_horizon[horizon] = by_horizon.get(horizon, 0) + 1
        
        return {
            "models": models,
            "total": len(models),
            "statistics": {
                "unique_tickers": len(by_ticker),
                "unique_horizons": len(by_horizon),
                "by_ticker": by_ticker,
                "by_horizon": by_horizon
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/training/history")
async def get_training_history():
    """
    Training-Historie aus Redis
    Zeigt vergangene Training-Runs
    """
    try:
        if not r:
            return {"history": [], "message": "Redis not connected"}
            
        # Metrics History
        history_data = r.get("model_metrics_history")
        history = []
        if history_data:
            history = json.loads(history_data)
        
        # Last Training Stats
        last_stats = r.get("last_training_stats")
        
        return {
            "history": history[-10:] if history else [],  # Letzte 10
            "last_training": json.loads(last_stats) if last_stats else None,
            "total_runs": len(history)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== MARKET DATA ENDPOINTS =====

@app.get("/market/data/{symbol}")
async def get_market_data(
    symbol: str,
    timeframe: str = "15min",  # 1min, 5min, 15min, 1hour, 1day
    limit: int = 100,           # Anzahl Candles
    start: str = None,          # Optional: Start-Datum (ISO format)
    end: str = None             # Optional: End-Datum (ISO format)
):
    """
    Historische OHLCV-Daten für Charts
    
    Parameters:
    - symbol: Ticker Symbol (z.B. AAPL, GOOGL)
    - timeframe: Candle-Größe (1min, 5min, 15min, 1hour, 1day)
    - limit: Anzahl Candles (max 1000, default 100)
    - start: Start-Datum (ISO format: 2025-10-01T00:00:00)
    - end: End-Datum (ISO format: 2025-10-02T23:59:59)
    
    Returns:
    - OHLCV-Daten als Array für Chart-Bibliotheken
    """
    try:
        start_dt = parse_iso_datetime(start)
        end_dt = parse_iso_datetime(end)
        if start_dt and end_dt and end_dt < start_dt:
            raise HTTPException(status_code=400, detail="Parameter 'end' muss nach 'start' liegen")

        limit_val = ensure_limit(limit)
        candles = fetch_timescale_candles(symbol, timeframe, limit_val, start_dt, end_dt)

        return {
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "count": len(candles),
            "data": candles,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/market/ohlcv/{symbol}/multi")
async def get_multi_timeframe_ohlcv(
    symbol: str,
    timeframes: str = "15min,1hour,1day",
    limit: int = 100,
):
    """Liefert mehrere TimescaleDB-Aggregate gleichzeitig."""

    frames = [frame.strip() for frame in timeframes.split(",") if frame.strip()]
    if not frames:
        raise HTTPException(status_code=400, detail="Parameter 'timeframes' darf nicht leer sein")

    limit_val = ensure_limit(limit)
    result: Dict[str, List[Dict[str, object]]] = {}

    try:
        for frame in frames:
            candles = fetch_timescale_candles(symbol, frame, limit_val)
            result[frame] = candles

        return {
            "symbol": symbol.upper(),
            "timeframes": result,
            "requested": frames,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/market/latest/{symbol}")
async def get_latest_price(symbol: str):
    """
    Aktuellster Preis für ein Symbol
    Schneller Endpoint für einzelne Ticker
    """
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT time, open, high, low, close, volume
                    FROM market_data
                    WHERE ticker = %s
                    ORDER BY time DESC
                    LIMIT 1
                    """,
                    (symbol.upper(),),
                )

                row = cur.fetchone()

                if not row:
                    raise HTTPException(status_code=404, detail=f"No data found for {symbol}")

                time_val, open_p, high_p, low_p, close_p, vol = row

                cur.execute(
                    """
                    SELECT close
                    FROM market_data
                    WHERE ticker = %s AND time < %s
                    ORDER BY time DESC
                    LIMIT 1
                    """,
                    (symbol.upper(), time_val),
                )

                prev_row = cur.fetchone()

        
        current_price = float(close_p)
        prev_close = float(prev_row[0]) if prev_row else current_price
        change = current_price - prev_close
        change_percent = (change / prev_close * 100) if prev_close else 0
        
        return {
            "symbol": symbol.upper(),
            "price": current_price,
            "open": float(open_p) if open_p else None,
            "high": float(high_p) if high_p else None,
            "low": float(low_p) if low_p else None,
            "volume": int(vol) if vol else 0,
            "change": round(change, 2),
            "change_percent": round(change_percent, 2),
            "time": time_val.isoformat(),
            "timestamp": int(time_val.timestamp())
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# 🕐 TIMESCALEDB PERFORMANCE ENDPOINTS
# ============================================

@app.get("/market/top-movers")
async def get_top_movers(limit: int = 10):
    """
    Top Gainer und Loser des aktuellen Tages
    Verwendet TimescaleDB Performance View
    """
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                # Top Gainer
                cur.execute("""
            WITH today_prices AS (
                SELECT
                    ticker,
                    FIRST(close, time) AS open_price,
                    LAST(close, time) AS close_price,
                    MAX(high) AS high_price,
                    MIN(low) AS low_price
                FROM market_data
                WHERE time > date_trunc('day', NOW())
                GROUP BY ticker
            )
            SELECT
                ticker,
                open_price,
                close_price,
                ((close_price - open_price) / open_price * 100) AS change_percent,
                high_price,
                low_price
            FROM today_prices
            WHERE open_price > 0
            ORDER BY change_percent DESC
            LIMIT %s
        """, (limit,))

                gainers = []
                for row in cur.fetchall():
                    ticker, open_p, close_p, change_pct, high_p, low_p = row
                    gainers.append({
                        "ticker": ticker,
                        "open": float(open_p),
                        "close": float(close_p),
                        "change_percent": round(float(change_pct), 2),
                        "high": float(high_p),
                        "low": float(low_p)
                    })

                # Top Loser
                cur.execute("""
            WITH today_prices AS (
                SELECT
                    ticker,
                    FIRST(close, time) AS open_price,
                    LAST(close, time) AS close_price,
                    MAX(high) AS high_price,
                    MIN(low) AS low_price
                FROM market_data
                WHERE time > date_trunc('day', NOW())
                GROUP BY ticker
            )
            SELECT
                ticker,
                open_price,
                close_price,
                ((close_price - open_price) / open_price * 100) AS change_percent,
                high_price,
                low_price
            FROM today_prices
            WHERE open_price > 0
            ORDER BY change_percent ASC
            LIMIT %s
        """, (limit,))

                losers = []
                for row in cur.fetchall():
                    ticker, open_p, close_p, change_pct, high_p, low_p = row
                    losers.append({
                        "ticker": ticker,
                        "open": float(open_p),
                        "close": float(close_p),
                        "change_percent": round(float(change_pct), 2),
                        "high": float(high_p),
                        "low": float(low_p)
                    })
        
        return {
            "gainers": gainers,
            "losers": losers,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/portfolio/performance")
async def get_portfolio_performance(days: int = 30):
    """
    Portfolio Performance über Zeitraum
    Verwendet TimescaleDB Hypertable Aggregation
    """
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
            SELECT
                time_bucket('1 hour', time) AS hour,
                AVG(equity_value) AS avg_equity,
                MAX(equity_value) AS max_equity,
                MIN(equity_value) AS min_equity,
                AVG(cash) AS avg_cash,
                AVG(buying_power) AS avg_buying_power
            FROM portfolio_equity
            WHERE time > NOW() - INTERVAL '%s days'
            GROUP BY hour
            ORDER BY hour DESC
        """, (days,))

                performance = []
                for row in cur.fetchall():
                    hour, avg_equity, max_equity, min_equity, avg_cash, avg_buying_power = row
                    performance.append({
                        "time": hour.isoformat(),
                        "timestamp": int(hour.timestamp()),
                        "avg_equity": float(avg_equity) if avg_equity else None,
                        "max_equity": float(max_equity) if max_equity else None,
                        "min_equity": float(min_equity) if min_equity else None,
                        "avg_cash": float(avg_cash) if avg_cash else None,
                        "avg_buying_power": float(avg_buying_power) if avg_buying_power else None
                    })

                cur.execute("""
            SELECT 
                AVG(equity_value) as current_equity,
                AVG(cash) as current_cash,
                AVG(buying_power) as current_buying_power,
                COUNT(*) as data_points
            FROM portfolio_equity
            WHERE time > NOW() - INTERVAL '1 day'
        """)

                stats_row = cur.fetchone()

        
        return {
            "performance": performance,
            "current_stats": {
                "current_equity": float(stats_row[0]) if stats_row and stats_row[0] else None,
                "current_cash": float(stats_row[1]) if stats_row and stats_row[1] else None,
                "current_buying_power": float(stats_row[2]) if stats_row and stats_row[2] else None,
                "data_points": stats_row[3] if stats_row else 0,
            },
            "period_days": days
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/portfolio/performance/summary")
async def get_portfolio_performance_summary(limit: int = 168):
    """Kompakte Übersicht auf Basis des Continuous Aggregates portfolio_performance_30d."""

    limit_val = ensure_limit(limit, default=168, maximum=720)

    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT hour, avg_equity, max_equity, min_equity
                    FROM portfolio_performance_30d
                    ORDER BY hour DESC
                    LIMIT %s
                    """,
                    (limit_val,),
                )
                rows = cur.fetchall()

        if not rows:
            return {
                "series": [],
                "summary": {
                    "latest_equity": None,
                    "change_absolute": None,
                    "change_percent": None,
                    "min_equity": None,
                    "max_equity": None,
                    "count": 0,
                },
                "limit": limit_val,
                "generated_at": datetime.now().isoformat(),
            }

        series: List[Dict[str, object]] = []
        for hour, avg_equity, max_equity, min_equity in reversed(rows):
            series.append(
                {
                    "time": hour.isoformat(),
                    "timestamp": int(hour.timestamp()),
                    "avg_equity": float(avg_equity) if avg_equity is not None else None,
                    "max_equity": float(max_equity) if max_equity is not None else None,
                    "min_equity": float(min_equity) if min_equity is not None else None,
                }
            )

        equity_values = [entry["avg_equity"] for entry in series if entry["avg_equity"] is not None]
        first_equity = series[0]["avg_equity"] if series and series[0]["avg_equity"] is not None else None
        latest_equity = series[-1]["avg_equity"] if series and series[-1]["avg_equity"] is not None else None

        change_absolute = None
        change_percent = None
        if first_equity is not None and latest_equity is not None:
            change_absolute = latest_equity - first_equity
            if first_equity:
                change_percent = (change_absolute / first_equity) * 100

        summary = {
            "latest_equity": latest_equity,
            "first_equity": first_equity,
            "change_absolute": round(change_absolute, 2) if change_absolute is not None else None,
            "change_percent": round(change_percent, 2) if change_percent is not None else None,
            "min_equity": min(equity_values) if equity_values else None,
            "max_equity": max(equity_values) if equity_values else None,
            "count": len(series),
        }

        return {
            "series": series,
            "summary": summary,
            "limit": limit_val,
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/ai/grok-insights")
async def get_grok_insights(limit: int = 20):
    """
    Aktuelle Grok AI Insights und Empfehlungen
    Verwendet TimescaleDB Hypertables
    """
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
            SELECT time, ticker, expected_gain, sentiment, reason
            FROM grok_topstocks
            ORDER BY time DESC, expected_gain DESC
            LIMIT %s
        """, (limit,))

                topstocks = []
                for row in cur.fetchall():
                    time_val, ticker, gain, sentiment, reason = row
                    topstocks.append({
                        "time": time_val.isoformat(),
                        "ticker": ticker,
                        "expected_gain": float(gain) if gain else None,
                        "sentiment": float(sentiment) if sentiment else None,
                        "reason": reason
                    })

                cur.execute("""
            SELECT time, ticker, score, reason
            FROM grok_recommendations
            ORDER BY time DESC, score DESC
            LIMIT %s
        """, (limit,))

                recommendations = []
                for row in cur.fetchall():
                    time_val, ticker, score, reason = row
                    recommendations.append({
                        "time": time_val.isoformat(),
                        "ticker": ticker,
                        "score": float(score) if score else None,
                        "reason": reason
                    })

                cur.execute("""
            SELECT time, ticker, sentiment, explanation_de
            FROM grok_deepersearch
            ORDER BY time DESC
            LIMIT %s
        """, (limit,))

                deepersearch = []
                for row in cur.fetchall():
                    time_val, ticker, sentiment, explanation = row
                    deepersearch.append({
                        "time": time_val.isoformat(),
                        "ticker": ticker,
                        "sentiment": float(sentiment) if sentiment else None,
                        "explanation_de": explanation
                    })
        
        return {
            "topstocks": topstocks,
            "recommendations": recommendations,
            "deepersearch": deepersearch,
            "total_insights": len(topstocks) + len(recommendations) + len(deepersearch)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/system/database-stats")
async def get_database_stats():
    """
    TimescaleDB Statistiken und Performance-Metriken
    """
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        hypertable_schema,
                        hypertable_name,
                        owner,
                        num_dimensions,
                        num_chunks,
                        compression_enabled
                    FROM timescaledb_information.hypertables
                    """
                )
                hypertables = [
                    {
                        "schema": row[0],
                        "name": row[1],
                        "owner": row[2],
                        "dimensions": row[3],
                        "chunks": row[4],
                        "compression_enabled": bool(row[5]) if row[5] is not None else None,
                    }
                    for row in cur.fetchall()
                ]

                cur.execute(
                    """
                    SELECT view_schema, view_name, materialization_hypertable_name
                    FROM timescaledb_information.continuous_aggregates
                    """
                )
                continuous_aggregates = [
                    {
                        "schema": row[0],
                        "view": row[1],
                        "materialization": row[2],
                    }
                    for row in cur.fetchall()
                ]

                cur.execute(
                    """
                    SELECT 
                        hypertable_schema,
                        hypertable_name,
                        attname,
                        segmentby_column_index,
                        orderby_column_index,
                        orderby_asc,
                        orderby_nullsfirst
                    FROM timescaledb_information.compression_settings
                    """
                )
                compression_settings = [
                    {
                        "schema": row[0],
                        "hypertable": row[1],
                        "column": row[2],
                        "segment_by_index": row[3],
                        "order_by_index": row[4],
                        "order_asc": row[5],
                        "order_nulls_first": row[6],
                    }
                    for row in cur.fetchall()
                ]

                cur.execute(
                    """
                    SELECT 
                        schemaname,
                        tablename,
                        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
                    FROM pg_tables 
                    WHERE schemaname = 'public'
                    ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
                    LIMIT 10
                    """
                )
                table_sizes = [
                    {"table": row[1], "size": row[2]}
                    for row in cur.fetchall()
                ]

                tracked_tables = [
                    "market_data",
                    "predictions",
                    "alpaca_positions",
                    "alpaca_account",
                    "grok_topstocks",
                    "grok_recommendations",
                    "grok_deepersearch",
                ]

                cur.execute(
                    """
                    SELECT relname, n_live_tup
                    FROM pg_stat_all_tables
                    WHERE schemaname = 'public'
                      AND relname = ANY(%s)
                    """,
                    (tracked_tables,),
                )
                live_rows = {row[0]: int(row[1]) for row in cur.fetchall()}
                data_counts = [
                    {"table": name, "rows": live_rows.get(name, 0)} for name in tracked_tables
                ]

                cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
                version_row = cur.fetchone()

        return {
            "hypertables": hypertables,
            "continuous_aggregates": continuous_aggregates,
            "compression": compression_settings,
            "table_sizes": table_sizes,
            "data_counts": data_counts,
            "timescaledb_version": version_row[0] if version_row else None,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
