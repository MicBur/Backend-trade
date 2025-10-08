import os
import json
import time
import requests
import redis
import psycopg2
from autogluon.tabular import TabularPredictor
from celery import Celery
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from celery.schedules import crontab
from grok_top_stocks import get_top_stocks_prediction
import pytz
import holidays
try:
    from xai_sdk import Client as XAIClient
    from xai_sdk.chat import user as xai_user, system as xai_system
    XAI_AVAILABLE = True
except Exception:
    XAI_AVAILABLE = False

# Logging
logging.basicConfig(level=logging.INFO)

load_dotenv()

REDIS_URL = os.getenv('REDIS_URL')
DATABASE_URL = os.getenv('DATABASE_URL')

# Celery App
app = Celery('worker', broker=REDIS_URL, backend=REDIS_URL)

# Redis
r = redis.from_url(REDIS_URL)

# Database (lazy fallback retry)
def _connect_db():
    for attempt in range(3):
        try:
            return psycopg2.connect(DATABASE_URL)
        except Exception as e:
            logging.error(f"DB connect attempt {attempt+1} failed: {e}")
            time.sleep(2)
    raise RuntimeError("Cannot connect to database after retries")

conn = _connect_db()
try:
    # Verhindert, dass eine einzige Duplicate-Key Exception die gesamte Connection in aborted state versetzt
    # und nachfolgende Queries (z.B. generate_predictions) scheitern.
    conn.autocommit = True
except Exception:
    pass

# API Keys (from env)
FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY')
FMP_API_KEY = os.getenv('FMP_API_KEY')
MARKETSTACK_API_KEY = os.getenv('MARKETSTACK_API_KEY')
TWELVE_DATA_API_KEY = os.getenv('TWELVE_DATA_API_KEY')
ALPHAVANTAGE_API_KEY = os.getenv('ALPHAVANTAGE_API_KEY')
ALPACA_API_KEY = os.getenv('ALPACA_API_KEY')
ALPACA_SECRET = os.getenv('ALPACA_SECRET')
GROK_API_KEY = os.getenv('GROK_API_KEY')
GROK_BASE_URL = os.getenv('GROK_BASE_URL', 'https://grok.xai-api.com')
GROK_INSECURE = os.getenv('GROK_INSECURE', '0') == '1'

BASE_TICKERS = ['AAPL', 'NVDA', 'MSFT', 'TSLA', 'AMZN', 'META', 'GOOGL', 'BRK.B', 'AVGO', 'JPM', 'LLY', 'V', 'XOM', 'PG', 'UNH', 'MA', 'JNJ', 'COST', 'HD', 'BAC']

# ================= Helper / Utility =================

DEVIATION_THRESHOLD = 0.08  # 8% vom Nutzer gewünscht

# ================= MARKET HOURS VALIDATION =================

def is_market_open():
    """
    Prüft ob US-Markt aktuell geöffnet ist (Eastern Time)
    Berücksichtigt Wochenenden und US-Feiertage
    
    Returns:
        bool: True wenn Markt offen, False wenn geschlossen
    """
    try:
        # Aktuelle Zeit in US Eastern Time
        eastern = pytz.timezone('US/Eastern')
        now_et = datetime.now(eastern)
        
        # Wochenende Check (Samstag=5, Sonntag=6)
        if now_et.weekday() >= 5:
            return False
            
        # US-Feiertage Check
        us_holidays = holidays.UnitedStates(years=now_et.year)
        if now_et.date() in us_holidays:
            return False
            
        # Handelszeiten: 9:30 - 16:00 Uhr ET
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        
        return market_open <= now_et <= market_close
        
    except Exception as e:
        logging.error(f"Market hours check failed: {e}")
        # Im Fehlerfall: Sicherheit geht vor - Markt als geschlossen betrachten
        return False

def get_market_status():
    """
    Liefert detaillierte Market-Status Informationen
    
    Returns:
        dict: Marktstatus mit Details
    """
    try:
        eastern = pytz.timezone('US/Eastern')
        now_et = datetime.now(eastern)
        
        market_open_bool = is_market_open()
        
        # Nächste Marktöffnung berechnen
        next_market_open = None
        if not market_open_bool:
            # Wenn Markt geschlossen, berechne nächste Öffnung
            next_day = now_et
            while True:
                # Nächster Werktag
                if next_day.weekday() >= 5:  # Wochenende
                    next_day += timedelta(days=1)
                    continue
                    
                # Feiertag prüfen
                us_holidays = holidays.UnitedStates(years=next_day.year)
                if next_day.date() in us_holidays:
                    next_day += timedelta(days=1)
                    continue
                    
                # Wenn heute und noch vor 9:30
                if next_day.date() == now_et.date() and now_et.time() < datetime.strptime('09:30', '%H:%M').time():
                    next_market_open = next_day.replace(hour=9, minute=30, second=0, microsecond=0)
                    break
                # Nächster Tag 9:30
                else:
                    next_day += timedelta(days=1)
                    if next_day.weekday() < 5:  # Werktag
                        next_market_open = next_day.replace(hour=9, minute=30, second=0, microsecond=0)
                        break
        
        return {
            'market_open': market_open_bool,
            'current_time_et': now_et.isoformat(),
            'next_open': next_market_open.isoformat() if next_market_open else None,
            'trading_day': now_et.weekday() < 5 and now_et.date() not in holidays.UnitedStates(years=now_et.year),
            'market_session': 'OPEN' if market_open_bool else 'CLOSED'
        }
        
    except Exception as e:
        logging.error(f"Market status calculation failed: {e}")
        return {
            'market_open': False,
            'current_time_et': None,
            'next_open': None,
            'trading_day': False,
            'market_session': 'ERROR',
            'error': str(e)
        }

def _redis_json_get(key, default=None):
    val = r.get(key)
    if not val:
        return default
    try:
        return json.loads(val)
    except Exception:
        return default

def _redis_json_set(key, value):
    r.set(key, json.dumps(value))

def ensure_defaults():
    """Ensure all required Redis keys exist with proper default values according to backend.txt spec"""
    defaults = {
        # ========== BACKEND.TXT COMPLIANCE ==========
        'trading_settings': {
            'enabled': False,                    # Haupt-Schalter für Auto-Trading
            'buy_threshold_pct': 0.05,          # 5% Schwellwert für Käufe
            'sell_threshold_pct': 0.05,         # 5% Schwellwert für Verkäufe  
            'max_position_per_trade': 1,        # Maximale Anzahl Aktien pro Trade
            'strategy': 'CONSERVATIVE',         # Strategie: CONSERVATIVE, BALANCED, AGGRESSIVE
            'last_updated': datetime.utcnow().isoformat(),
            'updated_by': 'backend_init'
        },
        'trading_status': {
            'last_run': None,
            'last_error': None,                 # Letzte Fehlermeldung oder null
            'trades_today': 0,                  # Anzahl Trades heute
            'total_volume': 0.0,                # Gesamtvolumen heute (USD)
            'active': False,                    # Ist Trading-Worker aktiv?
            'next_run': None,
            'worker_pid': os.getpid()
        },
        'system_status': {
            'redis_connected': True,
            'postgres_connected': True,
            'finnhub_api_active': False,
            'alpaca_api_active': False,
            'grok_api_active': False,
            'yfinance_api_active': False,
            'twelvedata_api_active': False,
            'worker_running': True,
            'last_heartbeat': datetime.utcnow().isoformat(),
            'uptime_seconds': 0,
            'memory_usage_mb': 0,
            'cpu_usage_percent': 0.0,
            'market_open': False,              # Market Hours Status
            'last_market_check': None
        },
        'market_status': get_market_status(),  # Separate detailed market status
        'risk_settings': {
            'daily_notional_cap': 50000,       # Max. Handelsvolumen pro Tag (USD)
            'max_position_per_ticker': 5,      # Max. Orders pro Ticker pro Tag
            'cooldown_minutes': 30,            # Pause nach Trade (Minuten)
            'max_trades_per_run': 3,           # Hard Limit pro Trading-Zyklus
            'emergency_stop_active': False
        },
        'portfolio_positions': [],              # Aktuelle Positionen (Array)
        'trades_log': [],                      # Handelshistorie (max. 200 Einträge)
        
        # ========== EXISTING SYSTEM KEYS ==========
        'retrain_status': {'last_retrain': None, 'trigger': None, 'pending': False},
        'deviation_tracker': [],  # Liste einzelner Abweichungen
        'predictions_current': {},
        'predictions_pending': [],  # Neue Struktur: {ticker, horizon, predicted, timestamp, eta}
        'model_paths_multi': {},
        'model_metrics_history': [],
        'risk_status': {
            'notional_today': 0.0,
            'last_reset': datetime.utcnow().date().isoformat(),
            'cooldowns': {}  # ticker -> iso timestamp wann wieder erlaubt
        }
    }
    for k, v in defaults.items():
        if r.get(k) is None:
            _redis_json_set(k, v)
    # Migration alte predictions_pending Struktur -> neue
    pending = _redis_json_get('predictions_pending', []) or []
    migrated = False
    for item in pending:
        if 'horizon' not in item and 'horizon_minutes' in item:
            item['horizon'] = str(item.get('horizon_minutes'))
            eta = datetime.fromisoformat(item['timestamp']) + timedelta(minutes=item.get('horizon_minutes', 60))
            item['eta'] = eta.isoformat()
            migrated = True
    if migrated:
        _redis_json_set('predictions_pending', pending)

ensure_defaults()

# ===== Training Status Utilities =====
def _training_status_update(**kwargs):
    status = _redis_json_get('ml_training_status', {}) or {}
    status.update(kwargs)
    status['last_update'] = datetime.utcnow().isoformat()
    _redis_json_set('ml_training_status', status)
    # optional log
    if 'event' in kwargs:
        log = _redis_json_get('ml_training_log', []) or []
        log.append({
            'time': datetime.utcnow().isoformat(),
            'event': kwargs.get('event'),
            'detail': kwargs.get('detail')
        })
        if len(log) > 200:
            log = log[-200:]
        _redis_json_set('ml_training_log', log)

def get_dynamic_tickers():
    tickers = set(BASE_TICKERS)
    grok = _redis_json_get('grok_top10', []) or []
    for item in grok:
        if isinstance(item, dict):
            t = item.get('ticker')
            if t:
                tickers.add(t)
    portfolio = _redis_json_get('portfolio_positions', []) or []
    for pos in portfolio:
        t = pos.get('symbol') or pos.get('ticker')
        if t:
            tickers.add(t)
    dyn = sorted(tickers)
    _redis_json_set('dynamic_tickers', dyn)
    return dyn

def append_trade_log(entry):
    """Enhanced trade logging with daily volume tracking and backend.txt compliance"""
    log = _redis_json_get('trades_log', []) or []
    log.append(entry)
    # keep last 200 per spec
    if len(log) > 200:
        log = log[-200:]
    _redis_json_set('trades_log', log)
    
    # Update today's trade statistics
    update_daily_trade_stats(entry)

def update_daily_trade_stats(trade_entry):
    """Update daily statistics for trades_today and total_volume"""
    try:
        today = datetime.utcnow().date().isoformat()
        trading_status = _redis_json_get('trading_status', {}) or {}
        
        # Reset daily stats if date changed
        if trading_status.get('last_stats_date') != today:
            trading_status['trades_today'] = 0
            trading_status['total_volume'] = 0.0
            trading_status['last_stats_date'] = today
        
        # Increment trade count
        trading_status['trades_today'] = trading_status.get('trades_today', 0) + 1
        
        # Add to volume if price info available
        if 'current_price' in trade_entry and 'qty' in trade_entry:
            volume = float(trade_entry['current_price']) * int(trade_entry['qty'])
            trading_status['total_volume'] = trading_status.get('total_volume', 0.0) + volume
        
        _redis_json_set('trading_status', trading_status)
    except Exception as e:
        logging.error(f"Daily stats update failed: {e}")

def update_system_heartbeat():
    """Update system_status heartbeat with health checks and resource monitoring"""
    import psutil
    import time
    
    try:
        # Get current system status
        status = _redis_json_get('system_status', {}) or {}
        
        # System resource monitoring
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        cpu_percent = process.cpu_percent()
        
        # Calculate uptime (use stored start time if available)
        if 'start_time' not in status:
            status['start_time'] = time.time()
        uptime_seconds = int(time.time() - status['start_time'])
        
        # Market Hours Check
        market_open = is_market_open()
        market_status = get_market_status()
        
        # API Health Checks - Multi-API Integration
        api_status = {
            'redis_connected': test_redis_connection(),
            'postgres_connected': test_postgres_connection(), 
            'finnhub_api_active': test_api_health('finnhub'),
            'fmp_api_active': test_api_health('fmp'),
            'marketstack_api_active': test_api_health('marketstack'),
            'alpaca_api_active': test_api_health('alpaca'),
            'grok_api_active': test_api_health('grok'),
            'yfinance_api_active': test_api_health('yfinance'),
            'twelvedata_api_active': test_api_health('twelvedata'),
            'worker_running': True,
            'last_heartbeat': datetime.utcnow().isoformat(),
            'uptime_seconds': uptime_seconds,
            'memory_usage_mb': int(memory_mb),
            'cpu_usage_percent': round(cpu_percent, 1),
            'market_open': market_open,
            'last_market_check': datetime.utcnow().isoformat()
        }
        
        # Update separate market status key
        _redis_json_set('market_status', market_status)
        
        status.update(api_status)
        _redis_json_set('system_status', status)
        
    except Exception as e:
        logging.error(f"Heartbeat update failed: {e}")

def test_redis_connection():
    """Test Redis connectivity"""
    try:
        r.ping()
        return True
    except Exception:
        return False

def test_postgres_connection():
    """Test PostgreSQL connectivity"""  
    try:
        cur = conn.cursor()
        cur.execute('SELECT 1')
        return True
    except Exception:
        return False

def test_api_health(api_name):
    """Test API endpoint health"""
    try:
        if api_name == 'finnhub' and FINNHUB_API_KEY:
            response = requests.get(f'https://finnhub.io/api/v1/quote?symbol=AAPL&token={FINNHUB_API_KEY}', timeout=5)
            return response.status_code == 200
        
        elif api_name == 'alpaca' and ALPACA_API_KEY:
            headers = {'APCA-API-KEY-ID': ALPACA_API_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
            response = requests.get('https://paper-api.alpaca.markets/v2/account', headers=headers, timeout=5)
            return response.status_code == 200
            
        elif api_name == 'grok' and GROK_API_KEY:
            # Simple health check for Grok API
            return bool(GROK_API_KEY)
            
        elif api_name == 'yfinance':
            # Test yfinance with a simple quote
            import yfinance as yf
            ticker = yf.Ticker("AAPL")
            info = ticker.info
            return bool(info.get('regularMarketPrice'))
            
        elif api_name == 'twelvedata':
            if not TWELVE_DATA_API_KEY:
                return False
            response = requests.get(f'https://api.twelvedata.com/time_series?symbol=AAPL&interval=1min&outputsize=1&apikey={TWELVE_DATA_API_KEY}', timeout=5)
            return response.status_code == 200
            
        elif api_name == 'fmp' and FMP_API_KEY:
            # Test Financial Modeling Prep API
            response = requests.get(f'https://financialmodelingprep.com/api/v3/quote/AAPL?apikey={FMP_API_KEY}', timeout=5)
            return response.status_code == 200
            
        elif api_name == 'marketstack' and MARKETSTACK_API_KEY:
            # Test Marketstack API
            response = requests.get(f'http://api.marketstack.com/v1/eod/latest?access_key={MARKETSTACK_API_KEY}&symbols=AAPL', timeout=5)
            return response.status_code == 200
            
    except Exception as e:
        logging.debug(f"API health check failed for {api_name}: {e}")
        return False
    
    return False

def update_trading_status(active=None, error=None, next_run=None):
    """Update trading_status with proper backend.txt compliance"""
    try:
        status = _redis_json_get('trading_status', {}) or {}
        
        # Update provided fields
        if active is not None:
            status['active'] = active
        if error is not None:
            status['last_error'] = error
        if next_run is not None:
            status['next_run'] = next_run
            
        # Always update last_run and worker_pid
        status['last_run'] = datetime.utcnow().isoformat()
        status['worker_pid'] = os.getpid()
        
        _redis_json_set('trading_status', status)
        
    except Exception as e:
        logging.error(f"Trading status update failed: {e}")

def check_risk_limits():
    """Enhanced risk management check with backend.txt compliance"""
    try:
        risk_settings = _redis_json_get('risk_settings', {}) or {}
        
        # Check emergency stop
        if risk_settings.get('emergency_stop_active', False):
            logging.warning("Emergency stop is active")
            return False
            
        # Check daily notional cap
        trading_status = _redis_json_get('trading_status', {}) or {}
        daily_volume = trading_status.get('total_volume', 0.0)
        daily_cap = risk_settings.get('daily_notional_cap', 0)
        
        if daily_cap > 0 and daily_volume >= daily_cap:
            logging.warning(f"Daily volume cap reached: ${daily_volume:.2f} >= ${daily_cap}")
            return False
            
        return True
        
    except Exception as e:
        logging.error(f"Risk limit check failed: {e}")
        return False  # Fail safe

def record_deviation(ticker, predicted, actual, horizon_minutes, ts_pred, ts_actual):
    deviation = None
    if actual and actual != 0:
        deviation = abs(predicted - actual) / actual
    tracker = _redis_json_get('deviation_tracker', []) or []
    tracker.append({
        'ticker': ticker,
        'predicted': predicted,
        'actual': actual,
        'deviation': deviation,
        'horizon_minutes': horizon_minutes,
        'prediction_time': ts_pred,
        'actual_time': ts_actual
    })
    # Keep last 500 records
    if len(tracker) > 500:
        tracker = tracker[-500:]
    _redis_json_set('deviation_tracker', tracker)
    return deviation

def load_predictor():
    try:
        model_path = _redis_json_get('model_path') or './autogluon_model'
        if not os.path.isdir(model_path):
            return None
        return TabularPredictor.load(model_path)
    except Exception as e:
        logging.error(f"Predictor load failed: {e}")
        return None

## Entfernt: Doppelter Alt-Block (Initialisierung) – vereinfacht auf oberen Abschnitt

@app.task
def fetch_data():
    """Enhanced Multi-API Data Fetching: TwelveData -> Finnhub -> FMP -> Marketstack -> YFinance.

    Parallel API Integration für maximale Datenabdeckung:
    - TwelveData: Primary Real-time & Intraday
    - Finnhub: Secondary Quotes & News
    - FMP: Fundamentals & Financial Data  
    - Marketstack: Historical EOD Data
    - YFinance: Backup Source
    
    Features:
    - Per-Ticker Logging (Redis Key: market_fetch_log, FIFO 400 Einträge)
    - Multi-Source Statistics (Redis Key: market_source_stats)
    - Intelligent Fallback Chain
    """
    data = _redis_json_get('market_data', {}) or {}
    cur = conn.cursor()
    tickers = get_dynamic_tickers()
    fetch_log = _redis_json_get('market_fetch_log', []) or []
    stats = {'finnhub': 0, 'twelvedata': 0, 'fmp': 0, 'marketstack': 0, 'alphavantage': 0, 'yfinance': 0, 'stub': 0, 'failed': 0}
    
    # API Keys
    td_key = TWELVE_DATA_API_KEY
    fh_key = FINNHUB_API_KEY
    fmp_key = FMP_API_KEY
    ms_key = MARKETSTACK_API_KEY
    av_key = ALPHAVANTAGE_API_KEY
    allow_stub = os.getenv('PRICE_STUB_ENABLED','0') == '1'
    import random

    # TwelveData Batch-Abruf - Respektiere 8 calls/minute limit
    fetch_data.twelvedata_batch_cache = {}
    if td_key and tickers:
        try:
            # Split tickers into batches of 8 to respect 8 calls/minute limit
            batch_size = 8
            ticker_batches = [tickers[i:i+batch_size] for i in range(0, len(tickers), batch_size)]
            
            for batch_idx, ticker_batch in enumerate(ticker_batches):
                # Use time_series endpoint with outputsize=1 for latest price
                batch_symbols = ','.join(ticker_batch)
                url = f'https://api.twelvedata.com/time_series?symbol={batch_symbols}&interval=1min&outputsize=1&apikey={td_key}'
                
                logging.info(f"TwelveData batch {batch_idx+1}/{len(ticker_batches)}: {len(ticker_batch)} symbols")
                resp = requests.get(url, timeout=15)
                
                if resp.status_code == 200:
                    batch_data = resp.json()
                    
                    if isinstance(batch_data, dict):
                        # Handle both single and multiple ticker responses
                        if len(ticker_batch) == 1 and 'values' in batch_data:
                            # Single ticker response - direct format
                            fetch_data.twelvedata_batch_cache[ticker_batch[0]] = batch_data
                            stats['twelvedata'] += 1
                        else:
                            # Multiple ticker response - ticker as keys
                            for ticker in ticker_batch:
                                if ticker in batch_data and isinstance(batch_data[ticker], dict):
                                    if batch_data[ticker].get('status') == 'ok':
                                        fetch_data.twelvedata_batch_cache[ticker] = batch_data[ticker]
                                        stats['twelvedata'] += 1
                                
                    logging.info(f"TwelveData batch {batch_idx+1} cached {len([t for t in ticker_batch if t in fetch_data.twelvedata_batch_cache])} tickers")
                else:
                    logging.warning(f"TwelveData batch {batch_idx+1} failed: HTTP {resp.status_code}")
                    
                # Add delay between batches to respect rate limits (only if more batches follow)
                if batch_idx < len(ticker_batches) - 1:
                    import time
                    time.sleep(8)  # Wait 8 seconds between batches to stay under 8/minute limit
                    
        except Exception as e:
            logging.warning(f"TwelveData batch failed: {e}")

    def append_log(ticker, source, status, note=None):
        fetch_log.append({
            'time': datetime.utcnow().isoformat(),
            'ticker': ticker,
            'source': source,
            'status': status,
            'note': (note or '')[:160]
        })
        if len(fetch_log) > 400:
            del fetch_log[:len(fetch_log)-400]

    # YFinance Preise aus separatem Service (optional)
    yfinance_payload = _redis_json_get('yfinance_quotes') or {}
    yf_prices = yfinance_payload.get('prices', {}) if isinstance(yfinance_payload, dict) else {}

    for ticker in tickers:
        readings = []  # list of dicts {source, price, open, high, low, change, change_pct, volume}
        # Falls YFinance Preis vorhanden -> als zusätzliche Reading (niedrige Priorität für open/high/low, da nur Close vorhanden)
        if ticker in yf_prices:
            try:
                prc = float(yf_prices[ticker])
                readings.append({'source':'yfinance','price':prc,'open':prc,'high':prc,'low':prc,'change':None,'change_pct':None,'volume':0})
                stats['yfinance'] += 1; append_log(ticker,'yfinance','ok')
            except Exception:
                append_log(ticker,'yfinance','parse_error')
                
        # Marketstack API - EOD Historical Data (als Fallback für bessere Abdeckung)
        if MARKETSTACK_API_KEY and len(readings) == 0:  # Nur wenn noch keine anderen Quellen
            try:
                url = f'http://api.marketstack.com/v1/eod/latest?access_key={MARKETSTACK_API_KEY}&symbols={ticker}'
                resp = requests.get(url, timeout=10)
                
                if resp.status_code == 200:
                    ms_data = resp.json()
                    if ms_data.get('data') and len(ms_data['data']) > 0:
                        eod = ms_data['data'][0]
                        close_price = eod.get('close')
                        if close_price:
                            readings.append({
                                'source': 'marketstack',
                                'price': float(close_price),
                                'open': float(eod.get('open', close_price)),
                                'high': float(eod.get('high', close_price)),
                                'low': float(eod.get('low', close_price)),
                                'change': None,
                                'change_pct': None,
                                'volume': int(eod.get('volume', 0))
                            })
                            stats['marketstack'] += 1
                            append_log(ticker, 'marketstack', 'ok', 'EOD data')
                else:
                    append_log(ticker, 'marketstack', f'http_{resp.status_code}')
            except Exception as e:
                append_log(ticker, 'marketstack', 'exception', str(e)[:100])
        
        # AlphaVantage - TIME_SERIES_INTRADAY für 15min bars (wenn keine anderen Quellen erfolgreich)
        if ALPHAVANTAGE_API_KEY and len(readings) == 0:
            try:
                # Free tier: 5 calls/minute, 25 calls/day
                # TIME_SERIES_INTRADAY endpoint mit 15min interval
                url = f'https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol={ticker}&interval=15min&apikey={ALPHAVANTAGE_API_KEY}'
                resp = requests.get(url, timeout=10)
                
                if resp.status_code == 200:
                    av_data = resp.json()
                    
                    # Prüfen ob Rate Limit erreicht (message in response)
                    if 'Note' in av_data or 'Information' in av_data:
                        append_log(ticker, 'alphavantage', 'rate_limit', av_data.get('Note', av_data.get('Information', ''))[:100])
                    elif 'Time Series (15min)' in av_data:
                        time_series = av_data['Time Series (15min)']
                        # Neueste Candle verwenden
                        latest_time = sorted(time_series.keys(), reverse=True)[0]
                        latest_bar = time_series[latest_time]
                        
                        close_price = float(latest_bar.get('4. close'))
                        if close_price:
                            readings.append({
                                'source': 'alphavantage',
                                'price': close_price,
                                'open': float(latest_bar.get('1. open', close_price)),
                                'high': float(latest_bar.get('2. high', close_price)),
                                'low': float(latest_bar.get('3. low', close_price)),
                                'change': None,
                                'change_pct': None,
                                'volume': int(latest_bar.get('5. volume', 0))
                            })
                            stats['alphavantage'] += 1
                            append_log(ticker, 'alphavantage', 'ok', f'15min bar from {latest_time}')
                    else:
                        append_log(ticker, 'alphavantage', 'empty', 'no time series data')
                else:
                    append_log(ticker, 'alphavantage', f'http_{resp.status_code}')
            except Exception as e:
                append_log(ticker, 'alphavantage', 'exception', str(e)[:100])
                
        # Finnhub
        try:
            if FINNHUB_API_KEY:
                url = f'https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}'
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    js = resp.json()
                    c = js.get('c')
                    if c not in (None, 0):
                        readings.append({'source':'finnhub','price':c,'open':js.get('o'),'high':js.get('h'), 'low':js.get('l'), 'change':js.get('d'), 'change_pct':js.get('dp'), 'volume': js.get('v') or 0})
                        stats['finnhub'] += 1; append_log(ticker,'finnhub','ok')
                    else:
                        append_log(ticker,'finnhub','empty','no current price')
                else:
                    append_log(ticker,'finnhub','http_error',f"{resp.status_code}")
        except Exception as e:
            append_log(ticker,'finnhub','exception',str(e))
        # TwelveData - bereits in Batch-Modus integriert (siehe twelvedata_batch_cache)
        if td_key and ticker in getattr(fetch_data, 'twelvedata_batch_cache', {}):
            batch_data = fetch_data.twelvedata_batch_cache[ticker]
            
            # Handle time_series response format
            price = None
            if 'values' in batch_data and batch_data['values']:
                latest = batch_data['values'][0]
                price = float(latest.get('close', 0))
                
                # Extract additional data from time_series format
                try:
                    readings.append({
                        'source': 'twelvedata',
                        'price': price,
                        'open': float(latest.get('open', 0)),
                        'high': float(latest.get('high', 0)),
                        'low': float(latest.get('low', 0)),
                        'volume': int(latest.get('volume', 0))
                    })
                    stats['twelvedata'] += 1
                    append_log(ticker, 'twelvedata', 'ok')
                except Exception as e:
                    append_log(ticker, 'twelvedata', 'parse_error', f'time_series parse fail: {e}')
                    
            elif batch_data.get('price'):
                # Fallback for quote format
                try:
                    price = float(batch_data['price'])
                    readings.append({
                        'source': 'twelvedata',
                        'price': price,
                        'open': batch_data.get('open'),
                        'high': batch_data.get('high'),
                        'low': batch_data.get('low'),
                        'change': batch_data.get('change'),
                        'change_pct': batch_data.get('percent_change'),
                        'volume': batch_data.get('volume') or 0
                    })
                    stats['twelvedata'] += 1
                    append_log(ticker, 'twelvedata', 'ok')
                except Exception as e:
                    append_log(ticker, 'twelvedata', 'parse_error', f'price parse fail: {e}')
            else:
                append_log(ticker, 'twelvedata', 'empty')
        # FMP
        if fmp_key:
            try:
                url = f'https://financialmodelingprep.com/api/v3/quote-short/{ticker}?apikey={fmp_key}'
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    arr = resp.json() if resp.content else []
                    if isinstance(arr, list) and arr:
                        p = arr[0].get('price')
                        if p not in (None,0):
                            readings.append({'source':'fmp','price':p,'open':p,'high':p,'low':p,'change':None,'change_pct':None,'volume': arr[0].get('volume') or 0})
                            stats['fmp'] += 1; append_log(ticker,'fmp','ok')
                        else:
                            append_log(ticker,'fmp','empty')
                    else:
                        append_log(ticker,'fmp','empty')
                else:
                    append_log(ticker,'fmp','http_error',f"{resp.status_code}")
            except Exception as e:
                append_log(ticker,'fmp','exception',str(e))
        # Stub zusätzlich (nur falls keine echte Quelle oder explizit zur Diversifizierung?)
        if allow_stub and not readings:
            prev = data.get(ticker, {}).get('price')
            if prev is None:
                prf = round(random.uniform(150,300),2)
            else:
                prf = round(prev * (1 + random.uniform(-0.003,0.003)),2)
            readings.append({'source':'stub','price':prf,'open':prf,'high':prf,'low':prf,'change':0,'change_pct':0,'volume':0})
            stats['stub'] += 1; append_log(ticker,'stub','ok','dev stub')
        if not readings:
            stats['failed'] += 1; append_log(ticker,'none','failed_all')
            continue
        # Aggregation: Median Preis
        import statistics
        prices = [r['price'] for r in readings if r.get('price') is not None]
        if not prices:
            stats['failed'] += 1; append_log(ticker,'aggregate','failed_all','no numeric prices')
            continue
        agg_price = statistics.median(prices)
        # Referenz für open/high/low: aus erster bevorzugten Quelle (Finnhub > TwelveData > FMP > Stub)
        priority_order = ['finnhub','twelvedata','fmp','stub']
        primary = None
        for psrc in priority_order:
            primary = next((r for r in readings if r['source']==psrc), None)
            if primary: break
        open_p = primary.get('open'); high_p = primary.get('high'); low_p = primary.get('low'); vol = primary.get('volume')
        # Abweichungsmetrik
        deviations = []
        for r_ in readings:
            try:
                deviations.append({'source': r_['source'], 'delta_pct': (r_['price']-agg_price)/agg_price if agg_price else 0})
            except Exception:
                pass
        data[ticker] = {
            'price': agg_price,
            'change': primary.get('change'),
            'change_percent': primary.get('change_pct'),
            'time': datetime.utcnow().isoformat(),
            'sources_used': [r_['source'] for r_ in readings],
            'source_deviation': deviations
        }
        try:
            # ON CONFLICT schützt vor Duplicate-Key (time,ticker) wenn mehrere fetch_data Läufe denselben 15m Slot treffen
            cur.execute("""
                INSERT INTO market_data (time, ticker, open, high, low, close, volume)
                VALUES (NOW(), %s, %s, %s, %s, %s, %s)
                ON CONFLICT (time, ticker) DO NOTHING
            """, (ticker, open_p, high_p, low_p, agg_price, vol or 0))
        except Exception as e:
            logging.warning(f"Insert realtime candle {ticker} failed: {e}")
    conn.commit()
    _redis_json_set('market_data', data)
    _redis_json_set('market_fetch_log', fetch_log)
    _redis_json_set('market_source_stats', {'time': datetime.utcnow().isoformat(), **stats})
    return {'tickers': len(tickers), 'stats': stats}
    
@app.task
def fetch_portfolio():
    """Enhanced portfolio fetch with backend.txt compliance"""
    headers = {
        'APCA-API-KEY-ID': ALPACA_API_KEY,
        'APCA-API-SECRET-KEY': ALPACA_SECRET
    }
    try:
        # Portfolio-Positionen
        pos_url = 'https://paper-api.alpaca.markets/v2/positions'
        pos_resp = requests.get(pos_url, headers=headers, timeout=30)
        positions = pos_resp.json() if pos_resp.status_code == 200 else []
        
        # Transform to backend.txt format
        portfolio_positions = []
        for pos in positions:
            portfolio_positions.append({
                'ticker': pos.get('symbol'),
                'qty': pos.get('qty'),
                'avg_entry_price': pos.get('avg_entry_price'),
                'market_value': pos.get('market_value'),
                'unrealized_pl': pos.get('unrealized_pl'),
                'side': pos.get('side', 'long')
            })
        
        # Store in backend.txt compliant format
        _redis_json_set('portfolio_positions', portfolio_positions)
        
        # Legacy storage for backward compatibility
        r.set('portfolio_positions_raw', json.dumps(positions))
        
        cur = conn.cursor()
        
        # Insert into portfolio_positions (summary table)
        for pos in positions:
            cur.execute("""
                INSERT INTO portfolio_positions (ticker, qty, avg_price, side)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE SET qty=EXCLUDED.qty, avg_price=EXCLUDED.avg_price, side=EXCLUDED.side
            """, (pos.get('symbol'), pos.get('qty'), pos.get('avg_entry_price'), pos.get('side')))
        
        # Insert into alpaca_positions (hypertable for ML training data)
        for pos in positions:
            try:
                cur.execute("""
                    INSERT INTO alpaca_positions (
                        time, symbol, qty, avg_entry_price, market_value, 
                        unrealized_pl, unrealized_pl_pct
                    )
                    VALUES (NOW(), %s, %s, %s, %s, %s, %s)
                """, (
                    pos.get('symbol'),
                    int(float(pos.get('qty', 0))),
                    float(pos.get('avg_entry_price', 0)),
                    float(pos.get('market_value', 0)),
                    float(pos.get('unrealized_pl', 0)),
                    float(pos.get('unrealized_plpc', 0))
                ))
            except Exception as e:
                logging.warning(f"Insert alpaca_positions {pos.get('symbol')} failed: {e}")
            
        # Portfolio-Equity
        acct_url = 'https://paper-api.alpaca.markets/v2/account'
        acct_resp = requests.get(acct_url, headers=headers, timeout=30)
        account_data = acct_resp.json() if acct_resp.status_code == 200 else {}
        equity = account_data.get('equity')
        
        # Insert into alpaca_account (hypertable for account history)
        if account_data:
            try:
                cur.execute("""
                    INSERT INTO alpaca_account (
                        time, portfolio_value, buying_power, equity, 
                        day_trade_buying_power, daytrade_count, 
                        trading_blocked, account_blocked, pattern_day_trader
                    )
                    VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    float(account_data.get('portfolio_value', 0)),
                    float(account_data.get('buying_power', 0)),
                    float(account_data.get('equity', 0)),
                    float(account_data.get('daytrading_buying_power', 0)),
                    int(account_data.get('daytrade_count', 0)),
                    account_data.get('trading_blocked', False),
                    account_data.get('account_blocked', False),
                    account_data.get('pattern_day_trader', False)
                ))
            except Exception as e:
                logging.warning(f"Insert alpaca_account failed: {e}")
        
        if equity:
            r.set('portfolio_equity', json.dumps([{'timestamp': datetime.now().isoformat(), 'equity_value': equity}]))
            cur.execute("""
                INSERT INTO portfolio_equity (time, equity_value)
                VALUES (NOW(), %s)
            """, (equity,))
            
        conn.commit()
        logging.info(f"Portfolio fetched: {len(portfolio_positions)} positions, equity: ${equity}")
        
        return {
            'positions': portfolio_positions,
            'equity': equity,
            'account_data': account_data
        }
        
    except Exception as e:
        logging.error(f"Alpaca Portfolio Exception: {str(e)}")
        # Update system status to reflect API error
        system_status = _redis_json_get('system_status', {}) or {}
        system_status['alpaca_api_active'] = False
        _redis_json_set('system_status', system_status)
        return None
    conn.commit()
    
    # Store in Redis als JSON
    r.set('market_data', json.dumps(data))
    return data

    

@app.task
def fetch_grok_recommendations():
    """Holt täglich Grok Top-10 (HTTP Variante)."""
    if not GROK_API_KEY:
        logging.warning("GROK_API_KEY fehlt")
        return None
    url = f"{GROK_BASE_URL.rstrip('/')}/v1/recommendations/top10"
    headers = {"Authorization": f"Bearer {GROK_API_KEY}"}
    try:
        response = requests.get(url, headers=headers, timeout=45, verify=not GROK_INSECURE)
        if response.status_code == 200:
            top10 = response.json()
            _redis_json_set('grok_top10', top10)
            cur = conn.cursor()
            if isinstance(top10, list):
                for rec in top10:
                    cur.execute("""
                        INSERT INTO grok_recommendations (time, ticker, score, reason)
                        VALUES (NOW(), %s, %s, %s)
                    """, (rec.get('ticker'), rec.get('score'), rec.get('reason')))
                conn.commit()
            logging.info("Grok Top-10 gespeichert")
            return top10
        logging.error(f"Grok API Fehler: {response.status_code} {response.text}")
    except Exception as e:
        logging.error(f"Grok API Exception: {e}")
    return None

@app.task
def fetch_grok_deepersearch():
    """Erweiterte Grok Deeper Search: Liefert Top-US-Aktien mit Sentiment (0..1) und 30-Wort deutscher Begründung.

    Aktuelle API Spezifikation ist unbekannt -> Wir nutzen einen generischen Endpoint/Prompt-Ansatz (Platzhalter):
    Annahme: POST https://grok.xai-api.com/v1/chat/completions mit JSON {model:..., messages:[...]} liefert ein JSON-Array.
    Falls reale API anders -> Anpassung nötig.
    Persistiert Ergebnis unter 'grok_deepersearch'.
    Struktur jedes Elements:
    {"ticker":"AAPL","sentiment":0.73,"explanation_de":"30 Wörter ..."}
    """
    if not GROK_API_KEY:
        logging.warning("GROK_API_KEY fehlt für deepersearch")
        return None
    started = datetime.utcnow().isoformat()
    status = _redis_json_get('grok_status', {}) or {}
    status.update({'fetching_active': True})
    _redis_json_set('grok_status', status)
    headers = {"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"}
    # Prompt (englisch für Modell, Output JSON enforced)
    system = "You are a financial analysis assistant. Respond ONLY with valid JSON array."
    user = (
        "Gib mir bis zu 10 große liquide US Aktien (nur Ticker) mit erwarteter positiver Kurschance in den nächsten 7 Tagen. "
        "Für jede: Sentiment Score 0..1 (Float, zwei Dezimalstellen) + deutsche Erklärung 'explanation_de' (max 60 Wörter). "
        "Erzeuge NUR ein JSON Array: [{\"ticker\":\"AAPL\",\"sentiment\":0.75,\"explanation_de\":\"Begründung...\"}] ohne zusätzliche Felder."
    )
    payload = {
        "model": "grok-latest",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "temperature": 0.2,
    }
    url = f"{GROK_BASE_URL.rstrip('/')}/v1/chat/completions"
    items = []
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120, verify=not GROK_INSECURE)
        if resp.status_code != 200:
            logging.error(f"Grok deepersearch API Fehler {resp.status_code}: {resp.text[:200]}")
        else:
            js = resp.json()
            # Heuristik: Antwortstruktur extrahieren
            content = None
            if isinstance(js, dict):
                # OpenAI kompatibel? choices[0].message.content
                choices = js.get('choices') or []
                if choices and isinstance(choices, list):
                    content = choices[0].get('message', {}).get('content')
            if isinstance(content, str):
                # Versuche direkt JSON zu parsen
                try:
                    items = json.loads(content)
                except Exception:
                    # crude extraction zwischen erstem '[' und letztem ']'
                    try:
                        start = content.index('[')
                        end = content.rindex(']') + 1
                        snippet = content[start:end]
                        items = json.loads(snippet)
                    except Exception as e2:
                        logging.error(f"Parsing deepersearch JSON fehlgeschlagen: {e2}")
            # Validierung & Normalisierung
            norm = []
            for it in items if isinstance(items, list) else []:
                if not isinstance(it, dict):
                    continue
                ticker = it.get('ticker') or it.get('symbol')
                if not ticker or len(ticker) > 6:
                    continue
                sentiment = it.get('sentiment')
                try:
                    sentiment = round(float(sentiment), 2)
                except Exception:
                    continue
                expl = it.get('explanation_de') or it.get('explanation') or ''
                # Softlimit 60 Wörter
                words = expl.split()
                if len(words) > 60:
                    expl = ' '.join(words[:60])
                norm.append({
                    'ticker': ticker.upper(),
                    'sentiment': sentiment,
                    'explanation_de': expl
                })
            items = norm[:10]
    except Exception as e:
        logging.error(f"Grok deepersearch Exception: {e}")
    # Schreibe Ergebnis + Log
    _redis_json_set('grok_deepersearch', items)
    fetch_log = _redis_json_get('grok_fetch_log', []) or []
    fetch_log.append({
        'timestamp': datetime.utcnow().isoformat(),
        'event': 'Grok deepersearch',
        'details': f'items={len(items)}'
    })
    if len(fetch_log) > 200:
        fetch_log = fetch_log[-200:]
    _redis_json_set('grok_fetch_log', fetch_log)
    status = _redis_json_get('grok_status', {}) or {}
    status.update({
        'fetching_active': False,
        'last_fetch': datetime.utcnow().isoformat(),
        'fetch_count': (status.get('fetch_count') or 0) + 1
    })
    _redis_json_set('grok_status', status)
    # dynamic_tickers erweitern
    if items:
        # In DB speichern
        try:
            cur = conn.cursor()
            for it in items:
                cur.execute("""
                    INSERT INTO grok_deepersearch (time, ticker, sentiment, explanation_de)
                    VALUES (NOW(), %s, %s, %s)
                """, (it['ticker'], it.get('sentiment'), it.get('explanation_de')))
            conn.commit()
        except Exception as e:
            logging.error(f"DB Insert grok_deepersearch failed: {e}")
        dyn = set(_redis_json_get('dynamic_tickers', []) or [])
        for it in items:
            dyn.add(it['ticker'])
        _redis_json_set('dynamic_tickers', sorted(dyn))
    logging.info(f"Grok deepersearch gespeichert: {len(items)} items")
    # Optionaler Retrain Hook (wenn neue Daten & Modelle existieren)
    if items and _redis_json_get('model_trained'):
        hook_key = 'retrain_hook_grok_last'
        last_hook = r.get(hook_key)
        run_hook = True
        if last_hook:
            try:
                last_dt = datetime.fromisoformat(last_hook.decode())
                if datetime.utcnow() - last_dt < timedelta(minutes=30):
                    run_hook = False
            except Exception:
                pass
        if run_hook:
            r.set(hook_key, datetime.utcnow().isoformat())
            status = _redis_json_get('retrain_status', {}) or {}
            if not status.get('pending'):
                status.update({'pending': True, 'trigger': 'grok_update'})
                _redis_json_set('retrain_status', status)
                try:
                    train_model.delay('grok_update')
                except Exception as e:
                    logging.error(f"Retrain hook (deepersearch) failed: {e}")
    return items

@app.task
def fetch_grok_deepersearch_xai():
    """Alternative Deeper Search via offizielles xai_sdk.

    Ablauf:
    1. Nutzt Modell-ID aus ENV GROK_MODEL_ID (Default grok-4-0709)
    2. Prompt erzeugt gleiche Struktur-Anforderung (JSON Array)
    3. Parsing & Normalisierung wie im HTTP Fallback
    4. Bei Fehlern -> Fallback: ruft existierende fetch_grok_deepersearch() auf
    """
    if not GROK_API_KEY:
        logging.warning("GROK_API_KEY fehlt für xai_sdk")
        return fetch_grok_deepersearch.delay()
    status = _redis_json_get('grok_status', {}) or {}
    status.update({'fetching_active': True})
    _redis_json_set('grok_status', status)
    model_id = os.getenv('GROK_MODEL_ID', 'grok-4-0709')
    items = []
    last_method = None
    # 1) Versuche SDK
    if XAI_AVAILABLE:
        try:
            client = XAIClient(api_key=GROK_API_KEY)
            chat = client.chat.create(model=model_id, temperature=0.2)
            chat.append(xai_system("You are a financial analysis assistant. Respond ONLY with valid JSON array."))
            chat.append(xai_user(
                "Gib mir bis zu 10 große liquide US Aktien (nur Ticker) mit erwarteter positiver Kurschance in den nächsten 7 Tagen. "
                "Für jede: Sentiment Score 0..1 (Float, zwei Dezimalstellen) + deutsche Erklärung 'explanation_de' (max 60 Wörter). "
                "Erzeuge NUR ein JSON Array: [{\"ticker\":\"AAPL\",\"sentiment\":0.75,\"explanation_de\":\"Begründung...\"}]"
            ))
            response = chat.sample()
            content = getattr(response, 'content', None)
            sdk_items = []
            if isinstance(content, str):
                try:
                    sdk_items = json.loads(content)
                except Exception:
                    try:
                        start = content.index('['); end = content.rindex(']') + 1
                        sdk_items = json.loads(content[start:end])
                    except Exception as e2:
                        logging.error(f"xai_sdk deepersearch JSON parse fail: {e2}")
            # Normalisieren
            norm = []
            for it in sdk_items if isinstance(sdk_items, list) else []:
                if not isinstance(it, dict):
                    continue
                ticker = it.get('ticker') or it.get('symbol')
                if not ticker:
                    continue
                try:
                    sentiment = round(float(it.get('sentiment')), 2)
                except Exception:
                    continue
                expl = it.get('explanation_de') or it.get('explanation') or ''
                words = expl.split()
                if len(words) > 60:
                    expl = ' '.join(words[:60])
                norm.append({'ticker': ticker.upper(), 'sentiment': sentiment, 'explanation_de': expl})
            if norm:
                items = norm[:10]
                last_method = 'sdk'
        except Exception as e:
            logging.error(f"xai_sdk deepersearch Fehler: {e}")
    # 2) Fallback HTTP falls leer
    if not items:
        try:
            http_items = fetch_grok_deepersearch()
            items = http_items or []
            last_method = 'http'
        except Exception as e:
            logging.error(f"HTTP fallback deepersearch Fehler: {e}")
    # Persistieren + Status aktualisieren
    _redis_json_set('grok_deepersearch', items)
    fetch_log = _redis_json_get('grok_fetch_log', []) or []
    fetch_log.append({'timestamp': datetime.utcnow().isoformat(), 'event': 'Grok deepersearch xai_sdk', 'details': f'items={len(items)} method={last_method}'})
    if len(fetch_log) > 200:
        fetch_log = fetch_log[-200:]
    _redis_json_set('grok_fetch_log', fetch_log)
    status = _redis_json_get('grok_status', {}) or {}
    status.update({'fetching_active': False, 'last_fetch': datetime.utcnow().isoformat(), 'fetch_count': (status.get('fetch_count') or 0) + 1, 'last_method': last_method})
    _redis_json_set('grok_status', status)
    # dynamic tickers erweitern
    if items:
        # In DB speichern
        try:
            cur = conn.cursor()
            for it in items:
                cur.execute("""
                    INSERT INTO grok_deepersearch (time, ticker, sentiment, explanation_de)
                    VALUES (NOW(), %s, %s, %s)
                """, (it['ticker'], it.get('sentiment'), it.get('explanation_de')))
            conn.commit()
        except Exception as e:
            logging.error(f"DB Insert grok_deepersearch failed: {e}")
        dyn = set(_redis_json_get('dynamic_tickers', []) or [])
        for it in items:
            try:
                dyn.add(it['ticker'])
            except Exception:
                continue
        _redis_json_set('dynamic_tickers', sorted(dyn))
    logging.info(f"Deepersearch gespeichert ({last_method}) items={len(items)}")
    # Retrain Hook analog
    if items and _redis_json_get('model_trained'):
        hook_key = 'retrain_hook_grok_last'
        last_hook = r.get(hook_key)
        run_hook = True
        if last_hook:
            try:
                last_dt = datetime.fromisoformat(last_hook.decode())
                if datetime.utcnow() - last_dt < timedelta(minutes=30):
                    run_hook = False
            except Exception:
                pass
        if run_hook:
            r.set(hook_key, datetime.utcnow().isoformat())
            status = _redis_json_get('retrain_status', {}) or {}
            if not status.get('pending'):
                status.update({'pending': True, 'trigger': 'grok_update'})
                _redis_json_set('retrain_status', status)
                try:
                    train_model.delay('grok_update')
                except Exception as e:
                    logging.error(f"Retrain hook (deepersearch_xai) failed: {e}")
    return items

@app.task
def grok_health():
    """Health Check für Grok Integration.

    Tests:
    1. API Key vorhanden
    2. Wenn xai_sdk verfügbar: leichte Chat-Abfrage (Mathe 2+2) -> Antwortlänge
    3. HTTP Endpoint HEAD/GET Reachability (Timeout kurz)
    Ergebnis schreibt grok_status.health = { sdk_ok, http_ok, last_check, error }
    """
    status = _redis_json_get('grok_status', {}) or {}
    health = {
        'sdk_ok': False,
        'http_ok': False,
        'last_check': datetime.utcnow().isoformat(),
        'error': None
    }
    if not GROK_API_KEY:
        health['error'] = 'missing_api_key'
        status['health'] = health
        _redis_json_set('grok_status', status)
        return health
    # SDK Test
    if XAI_AVAILABLE:
        try:
            client = XAIClient(api_key=GROK_API_KEY)
            chat = client.chat.create(model=os.getenv('GROK_MODEL_ID','grok-4-0709'), temperature=0)
            chat.append(xai_system('You are a math bot.'))
            chat.append(xai_user('2+2?'))
            resp = chat.sample()
            if hasattr(resp, 'content') and '4' in str(resp.content):
                health['sdk_ok'] = True
        except Exception as e:
            health['error'] = f"sdk: {e}"[:160]
    else:
        health['error'] = 'xai_sdk_not_available'
    # HTTP Reachability
    try:
        # Leichter GET (statt HEAD da manche Endpoints HEAD nicht unterstützen)
        url = f"{GROK_BASE_URL.rstrip('/')}/v1/recommendations/top10"
        resp = requests.get(url, timeout=8, headers={'Authorization': f'Bearer {GROK_API_KEY}'}, verify=not GROK_INSECURE)
        if resp.status_code in (200,401,403):  # 401/403 zählt als reachable
            health['http_ok'] = True
    except Exception as e:
        if health['error']:
            health['error'] += f"; http: {e}"[:120]
        else:
            health['error'] = f"http: {e}"[:160]
    status['health'] = health
    _redis_json_set('grok_status', status)
    # In DB loggen
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO grok_health_log (sdk_ok, http_ok, error)
            VALUES (%s, %s, %s)
        """, (health.get('sdk_ok'), health.get('http_ok'), health.get('error')))
        conn.commit()
    except Exception as e:
        logging.error(f"DB Insert grok_health_log failed: {e}")
    # Log
    fetch_log = _redis_json_get('grok_fetch_log', []) or []
    fetch_log.append({
        'timestamp': datetime.utcnow().isoformat(),
        'event': 'Grok health',
        'details': f"sdk_ok={health['sdk_ok']} http_ok={health['http_ok']}"
    })
    if len(fetch_log) > 200:
        fetch_log = fetch_log[-200:]
    _redis_json_set('grok_fetch_log', fetch_log)
    return health
@app.task
def fetch_historical_data():
    """Hole historische Daten (30 Tage, 15m) für dynamische Ticker mit Fallback Finnhub -> TwelveData -> FMP.

    Erweiterungen:
    - Detailliertes per-Ticker Logging (Redis Key: historical_fetch_log, max 300 Einträge FIFO)
    - TwelveData pseudo-Pagination (mehrere 5-Tages-Segmente falls nötig)
    - Quelle & Candle-Zähler pro Ticker
    """
    cur = conn.cursor()
    tickers = get_dynamic_tickers()
    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(days=30)
    inserted = 0
    source_stats = { 'finnhub': 0, 'twelvedata': 0, 'fmp': 0, 'failed': 0 }

    fetch_log = _redis_json_get('historical_fetch_log', []) or []

    def append_fetch_log(ticker, source, status, candles, http_status=None, note=None):
        entry = {
            'time': datetime.utcnow().isoformat(),
            'ticker': ticker,
            'source': source,
            'status': status,
            'candles': candles,
            'http_status': http_status,
            'note': note
        }
        fetch_log.append(entry)
        if len(fetch_log) > 300:
            # FIFO beschränken
            del fetch_log[:len(fetch_log)-300]

    td_key = os.getenv('TWELVE_DATA_API_KEY')
    fmp_key = os.getenv('FMP_API_KEY')

    def fetch_candles_ticker(ticker: str):
        # 1) Finnhub
        try:
            start_time = int(start_dt.timestamp())
            end_time = int(end_dt.timestamp())
            url = f'https://finnhub.io/api/v1/stock/candle?symbol={ticker}&resolution=15&from={start_time}&to={end_time}&token={FINNHUB_API_KEY}'
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                js = resp.json()
                if js.get('s') == 'ok' and js.get('t'):
                    source_stats['finnhub'] += 1
                    candles = [
                        {
                            'time': datetime.fromtimestamp(js['t'][i]),
                            'open': js['o'][i],
                            'high': js['h'][i],
                            'low': js['l'][i],
                            'close': js['c'][i],
                            'volume': js['v'][i]
                        } for i in range(len(js['t']))
                    ]
                    append_fetch_log(ticker, 'finnhub', 'ok', len(candles), 200)
                    return candles
                append_fetch_log(ticker, 'finnhub', 'empty', 0, 200, js.get('s'))
            else:
                append_fetch_log(ticker, 'finnhub', 'http_error', 0, resp.status_code, resp.text[:120])
        except Exception as e:
            logging.warning(f"Finnhub fail {ticker}: {e}")
            append_fetch_log(ticker, 'finnhub', 'exception', 0, None, str(e)[:120])
        # 2) Twelve Data (Intraday 15min) – begrenzt: liefert meist weniger Tage je Call
        if td_key:
            try:
                # Pagination über 5-Tage Fenster (heuristisch) – TwelveData Limit umgehen
                parsed_total = []
                window = 5
                current_start = start_dt
                while current_start < end_dt:
                    current_end = min(current_start + timedelta(days=window), end_dt)
                    url = (
                        f'https://api.twelvedata.com/time_series?symbol={ticker}'
                        f'&interval=15min&apikey={td_key}&start_date={current_start.strftime("%Y-%m-%d %H:%M:%S")}'
                        f'&end_date={current_end.strftime("%Y-%m-%d %H:%M:%S")}&format=JSON'
                    )
                    resp = requests.get(url, timeout=30)
                    if resp.status_code == 200:
                        js = resp.json()
                        values = js.get('values') or []
                        # Falls Error-Struktur
                        if isinstance(js, dict) and js.get('status') == 'error':
                            append_fetch_log(ticker, 'twelvedata', 'api_error', 0, 200, js.get('message'))
                            break
                        for row in reversed(values):
                            try:
                                ts = datetime.fromisoformat(row['datetime'])
                                if ts < start_dt or ts > end_dt:
                                    continue
                                parsed_total.append({
                                    'time': ts,
                                    'open': float(row['open']),
                                    'high': float(row['high']),
                                    'low': float(row['low']),
                                    'close': float(row['close']),
                                    'volume': float(row.get('volume', 0) or 0)
                                })
                            except Exception:
                                continue
                    else:
                        append_fetch_log(ticker, 'twelvedata', 'http_error', 0, resp.status_code, resp.text[:120])
                        break
                    # leichte Pause zur Ratelimit Schonung
                    time.sleep(0.25)
                    current_start = current_end
                if parsed_total:
                    source_stats['twelvedata'] += 1
                    append_fetch_log(ticker, 'twelvedata', 'ok', len(parsed_total), 200)
                    return parsed_total
                append_fetch_log(ticker, 'twelvedata', 'empty', 0, 200)
            except Exception as e:
                logging.warning(f"TwelveData fail {ticker}: {e}")
                append_fetch_log(ticker, 'twelvedata', 'exception', 0, None, str(e)[:120])
        # 3) FMP (Financial Modeling Prep) – 15min historisch
        if fmp_key:
            try:
                # Endpoint: https://financialmodelingprep.com/api/v3/historical-chart/15min/AAPL?apikey=...
                url = f'https://financialmodelingprep.com/api/v3/historical-chart/15min/{ticker}?apikey={fmp_key}'
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200:
                    arr = resp.json()
                    parsed = []
                    for row in arr:
                        try:
                            ts = datetime.fromisoformat(row['date'])
                            if ts < start_dt or ts > end_dt:
                                continue
                            parsed.append({
                                'time': ts,
                                'open': float(row['open']),
                                'high': float(row['high']),
                                'low': float(row['low']),
                                'close': float(row['close']),
                                'volume': float(row.get('volume', 0) or 0)
                            })
                        except Exception:
                            continue
                    if parsed:
                        source_stats['fmp'] += 1
                        candles = list(reversed(parsed))  # Älteste zuerst
                        append_fetch_log(ticker, 'fmp', 'ok', len(candles), 200)
                        return candles
                    append_fetch_log(ticker, 'fmp', 'empty', 0, 200)
                else:
                    append_fetch_log(ticker, 'fmp', 'http_error', 0, resp.status_code, resp.text[:120])
            except Exception as e:
                logging.warning(f"FMP fail {ticker}: {e}")
                append_fetch_log(ticker, 'fmp', 'exception', 0, None, str(e)[:120])
        source_stats['failed'] += 1
        append_fetch_log(ticker, 'none', 'failed_all', 0, None)
        return []

    for ticker in tickers:
        candles = fetch_candles_ticker(ticker)
        for c in candles:
            try:
                cur.execute("""
                    INSERT INTO market_data (time, ticker, open, high, low, close, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (time, ticker) DO NOTHING
                """, (
                    c['time'], ticker, c['open'], c['high'], c['low'], c['close'], c['volume']
                ))
                inserted += 1
            except Exception as e:
                logging.error(f"Insert fail {ticker} {c.get('time')}: {e}")
        # leichte Pause um Rate Limits zu schonen
        time.sleep(0.4)

    conn.commit()
    result = {"inserted": inserted, "tickers": len(tickers), "sources": source_stats}
    _redis_json_set('historical_source_stats', {
        'time': datetime.utcnow().isoformat(),
        **result
    })
    # Schreibe detailliertes Log
    _redis_json_set('historical_fetch_log', fetch_log)
    logging.info(f"Historical data fetched {result}")
    return result

@app.task
def backfill_ticker(ticker: str, days: int = 60):
    """Gezielter Backfill für einzelnen Ticker über längeren Zeitraum (Default 60 Tage) mit Fallback-Quellen.

    Nutzt gleiche Logik wie fetch_historical_data (Pagination TwelveData, Finnhub, FMP).
    Ergebnis-Statistik in Redis Key historical_backfill_status (letzte 50 Einträge FIFO).
    """
    cur = conn.cursor()
    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(days=days)
    inserted = 0
    sources_used = []

    def insert_batch(candles):
        nonlocal inserted
        for c in candles:
            try:
                cur.execute("""
                    INSERT INTO market_data (time, ticker, open, high, low, close, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (time, ticker) DO NOTHING
                """, (c['time'], ticker, c['open'], c['high'], c['low'], c['close'], c['volume']))
                inserted += 1
            except Exception as e:
                logging.error(f"Backfill insert fail {ticker} {c.get('time')}: {e}")

    # Re-Use interne Funktion aus fetch_historical_data indem Zeitraum temporär angepasst werden könnte.
    # Zur Vereinfachung duplizieren wir Minimal-Logik (könnte refaktorisiert werden).
    # 1 Finnhub
    try:
        s_time = int(start_dt.timestamp()); e_time = int(end_dt.timestamp())
        url = f'https://finnhub.io/api/v1/stock/candle?symbol={ticker}&resolution=15&from={s_time}&to={e_time}&token={FINNHUB_API_KEY}'
        resp = requests.get(url, timeout=40)
        if resp.status_code == 200:
            js = resp.json()
            if js.get('s') == 'ok' and js.get('t'):
                candles = [{
                    'time': datetime.fromtimestamp(js['t'][i]),
                    'open': js['o'][i],
                    'high': js['h'][i],
                    'low': js['l'][i],
                    'close': js['c'][i],
                    'volume': js['v'][i]
                } for i in range(len(js['t']))]
                insert_batch(candles)
                sources_used.append({'source': 'finnhub', 'candles': len(candles)})
    except Exception as e:
        logging.warning(f"Backfill Finnhub fail {ticker}: {e}")
    # 2 TwelveData Pagination
    td_key = os.getenv('TWELVE_DATA_API_KEY')
    if td_key:
        try:
            window = 5
            parsed_total = []
            cur_start = start_dt
            while cur_start < end_dt:
                cur_end = min(cur_start + timedelta(days=window), end_dt)
                url = (
                    f'https://api.twelvedata.com/time_series?symbol={ticker}'
                    f'&interval=15min&apikey={td_key}&start_date={cur_start.strftime("%Y-%m-%d %H:%M:%S")}'
                    f'&end_date={cur_end.strftime("%Y-%m-%d %H:%M:%S")}&format=JSON'
                )
                resp = requests.get(url, timeout=40)
                if resp.status_code == 200:
                    js = resp.json()
                    if isinstance(js, dict) and js.get('status') == 'error':
                        break
                    values = js.get('values') or []
                    for row in reversed(values):
                        try:
                            ts = datetime.fromisoformat(row['datetime'])
                            if ts < start_dt or ts > end_dt: continue
                            parsed_total.append({
                                'time': ts,
                                'open': float(row['open']),
                                'high': float(row['high']),
                                'low': float(row['low']),
                                'close': float(row['close']),
                                'volume': float(row.get('volume', 0) or 0)
                            })
                        except Exception:
                            continue
                else:
                    break
                time.sleep(0.25)
                cur_start = cur_end
            if parsed_total:
                insert_batch(parsed_total)
                sources_used.append({'source': 'twelvedata', 'candles': len(parsed_total)})
        except Exception as e:
            logging.warning(f"Backfill TwelveData fail {ticker}: {e}")
    # 3 FMP
    fmp_key = os.getenv('FMP_API_KEY')
    if fmp_key:
        try:
            url = f'https://financialmodelingprep.com/api/v3/historical-chart/15min/{ticker}?apikey={fmp_key}'
            resp = requests.get(url, timeout=40)
            if resp.status_code == 200:
                arr = resp.json(); parsed = []
                for row in arr:
                    try:
                        ts = datetime.fromisoformat(row['date'])
                        if ts < start_dt or ts > end_dt: continue
                        parsed.append({
                            'time': ts,
                            'open': float(row['open']),
                            'high': float(row['high']),
                            'low': float(row['low']),
                            'close': float(row['close']),
                            'volume': float(row.get('volume', 0) or 0)
                        })
                    except Exception:
                        continue
                if parsed:
                    parsed = list(reversed(parsed))
                    insert_batch(parsed)
                    sources_used.append({'source': 'fmp', 'candles': len(parsed)})
        except Exception as e:
            logging.warning(f"Backfill FMP fail {ticker}: {e}")
    
    # 4 AlphaVantage - TIME_SERIES_DAILY_ADJUSTED für historische Daten (längere Zeiträume)
    if ALPHAVANTAGE_API_KEY and inserted < 100:  # Nur wenn wenig Daten bisher
        try:
            # Free tier: 5 calls/minute, 25 calls/day
            # DAILY gibt volle Historie, outputsize=full für alle verfügbaren Daten
            url = f'https://www.alphavantage.co/query?function=TIME_SERIES_DAILY_ADJUSTED&symbol={ticker}&outputsize=full&apikey={ALPHAVANTAGE_API_KEY}'
            resp = requests.get(url, timeout=40)
            
            if resp.status_code == 200:
                av_data = resp.json()
                
                # Prüfen ob Rate Limit erreicht
                if 'Note' in av_data or 'Information' in av_data:
                    logging.warning(f"AlphaVantage backfill {ticker} rate limit: {av_data.get('Note', av_data.get('Information', ''))[:100]}")
                elif 'Time Series (Daily)' in av_data:
                    time_series = av_data['Time Series (Daily)']
                    parsed = []
                    
                    for date_str, daily_bar in time_series.items():
                        try:
                            # Parse date (format: YYYY-MM-DD)
                            ts = datetime.strptime(date_str, '%Y-%m-%d')
                            
                            # Nur im gewünschten Zeitraum
                            if ts < start_dt or ts > end_dt:
                                continue
                            
                            parsed.append({
                                'time': ts,
                                'open': float(daily_bar.get('1. open', 0)),
                                'high': float(daily_bar.get('2. high', 0)),
                                'low': float(daily_bar.get('3. low', 0)),
                                'close': float(daily_bar.get('4. close', 0)),
                                'volume': int(daily_bar.get('6. volume', 0))
                            })
                        except Exception as parse_err:
                            logging.warning(f"AlphaVantage backfill {ticker} parse error for {date_str}: {parse_err}")
                            continue
                    
                    if parsed:
                        # Chronologisch sortieren
                        parsed = sorted(parsed, key=lambda x: x['time'])
                        insert_batch(parsed)
                        sources_used.append({'source': 'alphavantage', 'candles': len(parsed)})
                        logging.info(f"AlphaVantage backfill {ticker}: {len(parsed)} daily candles")
                    else:
                        logging.warning(f"AlphaVantage backfill {ticker}: no data in time range")
                else:
                    logging.warning(f"AlphaVantage backfill {ticker}: unexpected response format")
            else:
                logging.warning(f"AlphaVantage backfill {ticker}: HTTP {resp.status_code}")
                
            # Rate limiting: 5 calls/minute = 12 second delay
            time.sleep(12)
            
        except Exception as e:
            logging.warning(f"Backfill AlphaVantage fail {ticker}: {e}")

    conn.commit()
    status_list = _redis_json_get('historical_backfill_status', []) or []
    status_list.append({
        'time': datetime.utcnow().isoformat(),
        'ticker': ticker,
        'days': days,
        'inserted': inserted,
        'sources': sources_used
    })
    if len(status_list) > 50:
        status_list = status_list[-50:]
    _redis_json_set('historical_backfill_status', status_list)
    logging.info(f"Backfill {ticker} days={days} inserted={inserted} sources={sources_used}")
    return {'ticker': ticker, 'inserted': inserted, 'sources': sources_used}

@app.task
def training_diagnostics():
    """Erstellt Diagnose: Zeilen und Zeitabdeckung pro Ticker für letztes 14d Fenster."""
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, COUNT(*) AS rows,
               MIN(time) AS first_time,
               MAX(time) AS last_time
        FROM market_data
        WHERE time >= NOW() - INTERVAL '14 days'
        GROUP BY ticker
        ORDER BY ticker
    """)
    rows = cur.fetchall()
    diag = []
    for t, count, first_t, last_t in rows:
        diag.append({
            'ticker': t,
            'rows': int(count),
            'first_time': first_t.isoformat() if first_t else None,
            'last_time': last_t.isoformat() if last_t else None
        })
    _redis_json_set('training_diagnostics', {'generated': datetime.utcnow().isoformat(), 'window_days': 14, 'tickers': diag})
    return diag

@app.task
def scan_and_backfill_low_history(min_rows: int = 150, days: int = 60, max_backfills: int = 5):
    """Automatischer Scanner für Ticker mit zu wenig historischen Zeilen.

    Kriterien:
    - Zählt Zeilen der letzten 14 Tage (wie training_diagnostics Basis) pro Ticker (market_data)
    - Für Ticker mit rows < min_rows wird (bis max_backfills pro Run) ein backfill_ticker.delay(ticker, days) ausgelöst
    - Schreibt Statusliste in Redis Key auto_backfill_status (letzte 50 Runs FIFO)

    Redis Key auto_backfill_status Format Beispiel:
    {
      "time": "ISO",
      "min_rows": 150,
      "days": 60,
      "candidates": [
         {"ticker":"PG","rows":42,"backfill_triggered":true},
         {"ticker":"JNJ","rows":95,"backfill_triggered":false}
      ],
      "triggered": ["PG"],
      "remaining_budget": 4
    }
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, COUNT(*) AS rows
        FROM market_data
        WHERE time >= NOW() - INTERVAL '14 days'
        GROUP BY ticker
    """)
    rows = cur.fetchall()
    candidates = []
    for t, cnt in rows:
        if cnt < min_rows:
            candidates.append((t, int(cnt)))
    # Sortiere aufsteigend nach rows (wenigste zuerst)
    candidates.sort(key=lambda x: x[1])
    triggered = []
    results = []
    budget = max_backfills
    for t, cnt in candidates:
        do_trigger = budget > 0
        if do_trigger:
            try:
                backfill_ticker.delay(t, days)
                triggered.append(t)
                budget -= 1
                triggered_flag = True
            except Exception as e:
                logging.error(f"auto backfill trigger failed {t}: {e}")
                triggered_flag = False
        else:
            triggered_flag = False
        results.append({
            'ticker': t,
            'rows': cnt,
            'backfill_triggered': triggered_flag
        })
    status_entry = {
        'time': datetime.utcnow().isoformat(),
        'min_rows': min_rows,
        'days': days,
        'candidates': results,
        'triggered': triggered,
        'remaining_budget': budget
    }
    history = _redis_json_get('auto_backfill_status', []) or []
    history.append(status_entry)
    if len(history) > 50:
        history = history[-50:]
    _redis_json_set('auto_backfill_status', history)
    logging.info(f"scan_and_backfill_low_history: triggered={triggered} remaining_budget={budget}")
    return status_entry

@app.task
def compute_prediction_quality_metrics(window_hours: int = 24):
    """Aggregiert Qualitätsmetriken der Vorhersagen basierend auf deviation_tracker.

    Nimmt Einträge der letzten window_hours und berechnet pro Horizon:
      - count
      - mae (|pred-actual|)
      - mape (|pred-actual|/actual) ignoriert Division durch 0
      - rmse
      - avg_deviation (falls bereits deviation Feld berechnet)

    Speichert Ergebnis unter Redis Key prediction_quality_metrics:
    {
      "time": "ISO",
      "window_hours": 24,
      "per_horizon": {
         "15": {"count": 120, "mae": 0.42, "mape": 0.018, "rmse": 0.55, "avg_deviation":0.02},
         ...
      }
    }
    Historie (Rolling 100) unter prediction_quality_metrics_history.
    """
    import math
    entries = _redis_json_get('deviation_tracker', []) or []
    cutoff = datetime.utcnow() - timedelta(hours=window_hours)
    per_hz = {}
    for e in entries:
        try:
            atime = datetime.fromisoformat(e.get('actual_time'))
        except Exception:
            continue
        if atime < cutoff:
            continue
        hz = str(e.get('horizon_minutes') or 'unknown')
        predicted = e.get('predicted')
        actual = e.get('actual')
        if predicted is None or actual is None:
            continue
        try:
            err = abs(predicted - actual)
            mape = None
            if actual not in (0, None):
                mape = abs(predicted - actual) / actual
            sq = (predicted - actual) ** 2
        except Exception:
            continue
        bucket = per_hz.setdefault(hz, {'count':0,'mae_sum':0.0,'mape_sum':0.0,'mape_count':0,'sq_sum':0.0,'dev_sum':0.0,'dev_count':0})
        bucket['count'] += 1
        bucket['mae_sum'] += err
        bucket['sq_sum'] += sq
        if mape is not None and not math.isinf(mape):
            bucket['mape_sum'] += mape
            bucket['mape_count'] += 1
        deviation = e.get('deviation')
        if deviation is not None:
            bucket['dev_sum'] += deviation
            bucket['dev_count'] += 1
    result_hz = {}
    for hz, b in per_hz.items():
        count = b['count']
        if count == 0:
            continue
        mae = b['mae_sum']/count
        rmse = (b['sq_sum']/count)**0.5
        mape = b['mape_sum']/b['mape_count'] if b['mape_count'] else None
        avg_dev = b['dev_sum']/b['dev_count'] if b['dev_count'] else None
        result_hz[hz] = {
            'count': count,
            'mae': mae,
            'mape': mape,
            'rmse': rmse,
            'avg_deviation': avg_dev
        }
    payload = {
        'time': datetime.utcnow().isoformat(),
        'window_hours': window_hours,
        'per_horizon': result_hz
    }
    _redis_json_set('prediction_quality_metrics', payload)
    hist = _redis_json_get('prediction_quality_metrics_history', []) or []
    hist.append(payload)
    if len(hist) > 100:
        hist = hist[-100:]
    _redis_json_set('prediction_quality_metrics_history', hist)
    logging.info(f"compute_prediction_quality_metrics: horizons={list(result_hz.keys())}")
    return payload

def _add_yfinance_enhanced_features(df, tickers):
    """Add YFinance Enhanced Features to training data"""
    import json
    from datetime import datetime, timedelta
    
    # Initialize new columns
    yf_features = ['sma_20', 'sma_50', 'sma_200', 'rsi', 'macd', 'macd_signal', 
                   'bb_upper', 'bb_lower', 'volume_ratio', 'pe_ratio', 'market_cap', 
                   'beta', 'news_sentiment_avg', 'news_count']
    
    for feature in yf_features:
        df[feature] = None
    
    try:
        # Hole YFinance Enhanced Daten aus Redis
        for ticker in tickers:
            yf_key = f'yfinance_enhanced:{ticker}'
            yf_data_raw = r.get(yf_key)
            
            if not yf_data_raw:
                continue
                
            yf_data = json.loads(yf_data_raw)
            historical_data = yf_data.get('historical_data', [])
            fundamentals = yf_data.get('fundamentals', {})
            news = yf_data.get('news', [])
            
            # Fundamentals (static pro Ticker)
            pe_ratio = fundamentals.get('pe_ratio')
            market_cap = fundamentals.get('market_cap')
            beta = fundamentals.get('beta')
            
            # News Sentiment (vereinfacht: Anzahl News als Proxy für Aktivität)
            news_count = len(news)
            # TODO: Implement proper sentiment analysis
            news_sentiment_avg = 0.5  # Neutral baseline
            
            # Historical/Technical Data matchen
            for hist_row in historical_data:
                hist_date = hist_row['date']
                
                # Finde matching rows in df
                ticker_mask = df['ticker'] == ticker
                date_mask = pd.to_datetime(df['time']).dt.strftime('%Y-%m-%d') == hist_date
                matching_mask = ticker_mask & date_mask
                
                if matching_mask.any():
                    # Technical Indicators
                    df.loc[matching_mask, 'sma_20'] = hist_row.get('sma_20')
                    df.loc[matching_mask, 'sma_50'] = hist_row.get('sma_50')
                    df.loc[matching_mask, 'sma_200'] = hist_row.get('sma_200')
                    df.loc[matching_mask, 'rsi'] = hist_row.get('rsi')
                    df.loc[matching_mask, 'macd'] = hist_row.get('macd')
                    df.loc[matching_mask, 'macd_signal'] = hist_row.get('macd_signal')
                    df.loc[matching_mask, 'bb_upper'] = hist_row.get('bb_upper')
                    df.loc[matching_mask, 'bb_lower'] = hist_row.get('bb_lower')
                    df.loc[matching_mask, 'volume_ratio'] = hist_row.get('volume_ratio')
                    
                    # Fundamentals (same for all dates of this ticker)
                    df.loc[matching_mask, 'pe_ratio'] = pe_ratio
                    df.loc[matching_mask, 'market_cap'] = market_cap
                    df.loc[matching_mask, 'beta'] = beta
                    df.loc[matching_mask, 'news_sentiment_avg'] = news_sentiment_avg
                    df.loc[matching_mask, 'news_count'] = news_count
        
        # Count how many YF features were added
        yf_count = sum(df[col].notna().sum() for col in yf_features)
        logging.info(f"Added {yf_count} YFinance enhanced features across {len(yf_features)} columns")
        
    except Exception as e:
        logging.warning(f"Error adding YFinance enhanced features: {e}")
    
    return df

@app.task
def train_model(trigger: str = 'manual'):
    """Trainiert drei separate AutoGluon Modelle für 15/30/60 Minuten Horizonte.

    - 15m: shift -1 (bei 15m Candle-Auflösung)
    - 30m: shift -2
    - 60m: shift -4 (bestehende Logik)
    Speichert Modelle unter ./autogluon_model_{15|30|60}
    Metriken (MAE, MAPE approximiert, ggf. R^2) werden gesammelt und in last_training_stats.metrics abgelegt.
    Historie der Metriken in model_metrics_history (Rolling 30).
    """
    import pandas as pd
    _training_status_update(active=True, stage='query_data', progress=0.02, trigger=trigger, event='start', detail='Beginne SQL Fetch')
    cur = conn.cursor()
    # Leakage-freie Abfrage: Grok Features + YFinance Enhanced Data
    cur.execute("""
        SELECT md.ticker, md.time, md.open, md.high, md.low, md.close, md.volume,
               LAG(md.close, 1) OVER (PARTITION BY md.ticker ORDER BY md.time) as prev_close,
               LAG(md.close, 5) OVER (PARTITION BY md.ticker ORDER BY md.time) as prev_close_5,
               LAG(md.close, 15) OVER (PARTITION BY md.ticker ORDER BY md.time) as prev_close_15,
               ds.sentiment AS grok_sentiment,
               ts.expected_gain AS grok_expected_gain
        FROM market_data md
        LEFT JOIN LATERAL (
            SELECT sentiment FROM grok_deepersearch d
            WHERE d.ticker = md.ticker AND d.time <= md.time
            ORDER BY d.time DESC LIMIT 1
        ) ds ON TRUE
        LEFT JOIN LATERAL (
            SELECT expected_gain FROM grok_topstocks t
            WHERE t.ticker = md.ticker AND t.time <= md.time
            ORDER BY t.time DESC LIMIT 1
        ) ts ON TRUE
        WHERE md.time >= NOW() - INTERVAL '14 days'
        ORDER BY md.ticker, md.time
    """)
    rows = cur.fetchall()
    raw_count = len(rows)

    # Mindestzeilen pro Ticker (konfigurierbar via ENV)
    min_rows = int(os.getenv('TRAIN_MIN_ROWS', '150'))
    # Zerlege in per-Ticker Listen
    from collections import defaultdict
    bucket = defaultdict(list)
    for r in rows:
        bucket[r[0]].append(r)
    included = []
    excluded = []
    filtered_rows = []
    for ticker, lst in bucket.items():
        if len(lst) >= min_rows:
            included.append(ticker)
            filtered_rows.extend(lst)
        else:
            excluded.append({'ticker': ticker, 'rows': len(lst)})
    # Falls alles ausgeschlossen -> Degraded Mode: nimm Top 5 nach Row Count
    degraded_mode = False
    if not included:
        degraded_mode = True
        top = sorted(bucket.items(), key=lambda kv: len(kv[1]), reverse=True)[:5]
        filtered_rows = []
        included = []
        for t, lst in top:
            included.append(t)
            filtered_rows.extend(lst)
        excluded = [e for e in excluded if e['ticker'] not in included]
    raw_filtered = len(filtered_rows)
    _training_status_update(stage='filter_tickers', progress=0.10, event='filter', detail=f'raw={raw_count} filtered_candidate={raw_filtered}')
    if raw_filtered < 100:
        logging.warning(f"Not enough data after filter: raw={raw_count} filtered={raw_filtered}")
        _redis_json_set('last_training_stats', {
            'time': datetime.utcnow().isoformat(),
            'trigger': trigger,
            'raw_rows': raw_count,
            'filtered_rows': raw_filtered,
            'clean_rows': 0,
            'tickers_included': included,
            'tickers_excluded': excluded,
            'min_rows': min_rows,
            'degraded_mode': degraded_mode,
            'status': 'skipped_insufficient_raw'
        })
        _training_status_update(active=False, stage='skipped_insufficient_raw', progress=1.0, event='skip', detail='Zu wenig gefilterte Daten')
        return f"Insufficient data: raw={raw_count} filtered={raw_filtered}"
    df = pd.DataFrame(filtered_rows, columns=['ticker', 'time', 'open', 'high', 'low', 'close', 'volume', 'prev_close', 'prev_close_5', 'prev_close_15', 'grok_sentiment', 'grok_expected_gain'])
    _training_status_update(stage='feature_engineering', progress=0.20, event='feature_eng', detail=f'rows={len(df)} tickers={len(included)}')
    
    # YFinance Enhanced Features hinzufügen
    df = _add_yfinance_enhanced_features(df, included)
    
    # Feature Engineering
    df['price_change'] = df['close'] - df['prev_close']
    df['price_change_5'] = df['close'] - df['prev_close_5']
    df['price_change_15'] = df['close'] - df['prev_close_15']
    df['volatility'] = (df['high'] - df['low']) / df['close']
    df['hour'] = pd.to_datetime(df['time']).dt.hour
    df['day_of_week'] = pd.to_datetime(df['time']).dt.dayofweek
    # Targets für mehrere Horizonte
    df['target_15'] = df.groupby('ticker')['close'].shift(-1)
    df['target_30'] = df.groupby('ticker')['close'].shift(-2)
    df['target_60'] = df.groupby('ticker')['close'].shift(-4)
    df_clean = df.dropna(subset=['target_15','target_30','target_60']).copy()
    clean_count = len(df_clean)
    if clean_count < 100:
        logging.warning(f"Not enough clean multi-horizon data: clean={clean_count}")
        _redis_json_set('last_training_stats', {
            'time': datetime.utcnow().isoformat(),
            'trigger': trigger,
            'raw_rows': raw_count,
            'filtered_rows': raw_filtered,
            'clean_rows': clean_count,
            'tickers_included': included,
            'tickers_excluded': excluded,
            'min_rows': min_rows,
            'degraded_mode': degraded_mode,
            'status': 'skipped_insufficient_clean'
        })
        _training_status_update(active=False, stage='skipped_insufficient_clean', progress=1.0, event='skip', detail='Zu wenig saubere Daten')
        return f"Insufficient clean data: {clean_count} rows"
    # Imputation für Grok Features (Median) + Missing Flags
    for col in ['grok_sentiment','grok_expected_gain']:
        median_val = df_clean[col].median() if not df_clean[col].dropna().empty else 0.0
        missing_flag = df_clean[col].isna().astype(int)
        df_clean.loc[:, f'{col}_missing'] = missing_flag
        df_clean.loc[:, col] = df_clean[col].fillna(median_val)
    _training_status_update(stage='imputation', progress=0.35, event='impute', detail='Grok Features imputiert')
    # Speichere Imputation Stats in Redis
    imputation_stats = {
        'time': datetime.utcnow().isoformat(),
        'grok_sentiment_median': float(df_clean['grok_sentiment'].median()) if not df_clean['grok_sentiment'].dropna().empty else 0.0,
        'grok_expected_gain_median': float(df_clean['grok_expected_gain'].median()) if not df_clean['grok_expected_gain'].dropna().empty else 0.0
    }
    _redis_json_set('feature_imputation', imputation_stats)
    df_enc = pd.get_dummies(df_clean, columns=['ticker'], prefix='ticker')
    _training_status_update(stage='encoding', progress=0.45, event='encode', detail=f'encoded_cols={len(df_enc.columns)}')
    base_features = [c for c in df_enc.columns if c not in ['time','target_15','target_30','target_60']]
    started = datetime.utcnow().isoformat()
    metrics = {}
    model_paths = {}
    horizons = {'15':'target_15','30':'target_30','60':'target_60'}
    from autogluon.tabular import TabularDataset
    try:
        total_time_budget = 480  # Sekunden gesamt Budget heuristisch
        per_model_time = int(total_time_budget / len(horizons))
        horizon_count = len(horizons)
        for idx,(hz,label_col) in enumerate(horizons.items(), start=1):
            train_df = df_enc[base_features + [label_col]].rename(columns={label_col:'target'})
            td = TabularDataset(train_df)
            path = f'./autogluon_model_{hz}'
            predictor = TabularPredictor(label='target', path=path, eval_metric='mean_absolute_error')\
                .fit(td, time_limit=per_model_time, verbosity=0)
            lb = predictor.leaderboard(silent=True)
            # MAE aus Leaderboard (Bestes Modell = erste Zeile)
            mae = None
            if not lb.empty and 'score_val' in lb.columns:
                # score_val ist neg MAE bei mae metric? In AutoGluon: lower = better; bei mae -> score_val = -MAE
                best = lb.iloc[0]
                score_val = best.get('score_val')
                if score_val is not None:
                    mae = abs(float(score_val))
            # Approx MAPE
            y_true = train_df['target']
            y_pred = predictor.predict(train_df[base_features])
            import numpy as np
            with np.errstate(divide='ignore', invalid='ignore'):
                mape = float(np.mean(np.abs((y_true - y_pred) / np.where(y_true==0, np.nan, y_true))))
            # R^2 (einfach)
            ss_res = float(((y_true - y_pred)**2).sum())
            ss_tot = float(((y_true - y_true.mean())**2).sum())
            r2 = 1 - ss_res/ss_tot if ss_tot else None
            metrics[hz] = {
                'mae': mae,
                'mape': mape,
                'r2': r2,
                'rows': int(len(train_df))
            }
            model_paths[hz] = path
            _training_status_update(stage=f'training_horizon_{hz}', progress=0.45 + 0.45 * (idx / horizon_count), event='horizon_trained', detail=f'hz={hz} mae={mae}')
        # Set flags
        _redis_json_set('model_trained', True)
        _redis_json_set('model_path', model_paths.get('60'))
        _redis_json_set('model_paths_multi', model_paths)
        status = _redis_json_get('retrain_status', {}) or {}
        status.update({'last_retrain': datetime.utcnow().isoformat(), 'trigger': trigger, 'pending': False})
        _redis_json_set('retrain_status', status)
        # Metrik-Historie
        history = _redis_json_get('model_metrics_history', []) or []
        history.append({'time': datetime.utcnow().isoformat(), 'trigger': trigger, 'metrics': metrics})
        if len(history) > 30:
            history = history[-30:]
        _redis_json_set('model_metrics_history', history)
        _redis_json_set('last_training_stats', {
            'time': datetime.utcnow().isoformat(),
            'trigger': trigger,
            'raw_rows': raw_count,
            'filtered_rows': raw_filtered,
            'clean_rows': clean_count,
            'tickers_included': included,
            'tickers_excluded': excluded,
            'min_rows': min_rows,
            'degraded_mode': degraded_mode,
            'status': 'success',
            'started': started,
            'metrics': metrics
        })
        logging.info(f"Multi-horizon models trained metrics={metrics}")
        # Persistiere Feature-Schema je Horizon für spätere Inferenz-Diagnose
        try:
            feature_schemas = {}
            for hz, predictor in predictors.items():
                try:
                    feature_schemas[hz] = list(predictor.feature_metadata.get_features())
                except Exception:
                    feature_schemas[hz] = []
            _redis_json_set('model_features_multi', feature_schemas)
        except Exception as e:
            logging.warning(f"Konnte model_features_multi nicht speichern: {e}")
        _training_status_update(active=False, stage='complete', progress=1.0, event='finished', detail='Training abgeschlossen')
        return f"Trained multi-horizon models: {metrics}"
    except Exception as e:
        logging.error(f"Multi-horizon training failed: {e}")
        _redis_json_set('last_training_stats', {
            'time': datetime.utcnow().isoformat(),
            'trigger': trigger,
            'raw_rows': raw_count,
            'filtered_rows': raw_filtered,
            'clean_rows': clean_count,
            'tickers_included': included,
            'tickers_excluded': excluded,
            'min_rows': min_rows,
            'degraded_mode': degraded_mode,
            'status': 'failed',
            'error': str(e),
            'started': started
        })
        _training_status_update(active=False, stage='failed', progress=1.0, event='failed', detail=str(e)[:180])
        return f"Training failed: {e}"

@app.task
def generate_predictions():
    """Erstellt Multi-Horizon Vorhersagen (15/30/60) und speichert strukturierte Ergebnisse.

    Neues Schema predictions_current:
    {
      "AAPL": {
        "current_price": 234.10,
        "timestamp": "...",
        "horizons": {
          "15": {"predicted_price": 234.50, "change_pct": 0.0017, "eta": "..."},
          "30": {...},
          "60": {...}
        }
      },
      ...
    }

    predictions_pending Liste Einträge:
    {ticker, horizon, predicted, timestamp, eta}
    (eta = Zielzeitpunkt wann Abgleich stattfinden soll)
    """
    import pandas as pd
    import numpy as np
    cur = conn.cursor()
    tickers = get_dynamic_tickers()
    model_paths = _redis_json_get('model_paths_multi', {}) or {}
    predictors = {}
    for hz, path in model_paths.items():
        try:
            if os.path.isdir(path):
                predictors[hz] = TabularPredictor.load(path)
        except Exception as e:
            logging.error(f"Could not load predictor horizon {hz}: {e}")
    if not predictors:
        logging.warning("generate_predictions: keine Multi-Horizon Modelle geladen")
        return None
    now = datetime.utcnow()
    # Grok Feature Maps (einmalig pro Run)
    grok_sent_map = {}
    grok_exp_gain_map = {}
    try:
        cur.execute("""
            SELECT DISTINCT ON (ticker) ticker, sentiment
            FROM grok_deepersearch
            WHERE time >= NOW() - INTERVAL '7 days'
            ORDER BY ticker, time DESC
        """)
        for t,sent in cur.fetchall():
            grok_sent_map[t] = sent
        cur.execute("""
            SELECT DISTINCT ON (ticker) ticker, expected_gain, sentiment
            FROM grok_topstocks
            WHERE time >= NOW() - INTERVAL '7 days'
            ORDER BY ticker, time DESC
        """)
        for t, eg, s in cur.fetchall():
            if t not in grok_sent_map and s is not None:
                grok_sent_map[t] = s
            if eg is not None:
                grok_exp_gain_map[t] = eg
    except Exception as e:
        logging.error(f"Grok feature maps build failed: {e}")
    preds_struct = {}
    pending = _redis_json_get('predictions_pending', []) or []
    # Lade Imputations-Statistiken (Median Werte) aus Training
    imputation = _redis_json_get('feature_imputation', {}) or {}
    median_sent = imputation.get('grok_sentiment_median', 0.0)
    median_gain = imputation.get('grok_expected_gain_median', 0.0)
    for t in tickers:
        cur.execute("""
            SELECT time, close, open, high, low, volume FROM market_data
            WHERE ticker=%s ORDER BY time DESC LIMIT 40
        """, (t,))
        rows = cur.fetchall()
        if len(rows) < 20:
            continue
        rows = list(reversed(rows))
        df = pd.DataFrame(rows, columns=['time','close','open','high','low','volume'])
        df['prev_close'] = df['close'].shift(1)
        df['prev_close_5'] = df['close'].shift(5)
        df['prev_close_15'] = df['close'].shift(15)
        df['price_change'] = df['close'] - df['prev_close']
        df['price_change_5'] = df['close'] - df['prev_close_5']
        df['price_change_15'] = df['close'] - df['prev_close_15']
        df['volatility'] = (df['high'] - df['low']) / df['close']
        df['hour'] = pd.to_datetime(df['time']).dt.hour
        df['day_of_week'] = pd.to_datetime(df['time']).dt.dayofweek
        # Grok Features für diesen Ticker (können None sein) + Missing Flags + Imputation
        raw_sent = grok_sent_map.get(t)
        raw_gain = grok_exp_gain_map.get(t)
        df['grok_sentiment'] = raw_sent if raw_sent is not None else median_sent
        df['grok_sentiment_missing'] = 0 if raw_sent is not None else 1
        df['grok_expected_gain'] = raw_gain if raw_gain is not None else median_gain
        df['grok_expected_gain_missing'] = 0 if raw_gain is not None else 1
        # One-hot ticker: gleiche Struktur wie Training (Training nutzte get_dummies auf Ticker) -> hier nur ein Flag pro möglichem Basisticker
        # Hinweis: Falls dynamische neue Ticker außerhalb BASE_TICKERS trainiert wurden, wäre Persistenz der Dummy-Spalten nötig.
        # Vereinfachung: Wir setzen nur bekannte Basis-Ticker-Spalten; fehlende Spalten ignoriert AutoGluon überwiegend nicht – daher prüfen wir existierende Spalten im Modell.
        dynamic_all = set(BASE_TICKERS)
        for base in dynamic_all:
            df[f'ticker_{base}'] = 1 if t == base else 0
        # Letzte Zeile für Features
        last_row = df.iloc[-1:].drop(columns=['time'])
        # Prune Columns nicht in Predictor erwartet (robust gegen evtl. zusätzliche Spalten)
        # (AutoGluon kann meist ignorieren, aber wir reduzieren Risiko)
        horizons_out = {}
        current_price = float(df['close'].iloc[-1])
        for hz, predictor in predictors.items():
            try:
                expected_cols = list(predictor.feature_metadata.get_features())
                use_row = last_row.copy()
                drop_cols = [c for c in use_row.columns if c not in expected_cols]
                if drop_cols:
                    logging.debug(f"Prediction {t} hz={hz}: dropping cols {drop_cols}")
                    use_row = use_row.drop(columns=drop_cols)
                missing_cols = []
                for c in expected_cols:
                    if c not in use_row.columns:
                        use_row[c] = 0
                        missing_cols.append(c)
                if missing_cols:
                    logging.debug(f"Prediction {t} hz={hz}: added missing cols {missing_cols}")
                # Reorder strictly
                use_row = use_row[expected_cols]
                pred_series = predictor.predict(use_row)
                pred_val = float(getattr(pred_series, 'iloc', pred_series)[0])
                horizon_minutes = int(hz)
                eta = (now + timedelta(minutes=horizon_minutes)).isoformat()
                change_pct = (pred_val - current_price) / current_price if current_price else None
                horizons_out[hz] = {
                    'predicted_price': pred_val,
                    'change_pct': change_pct,
                    'eta': eta
                }
                pending.append({
                    'ticker': t,
                    'horizon': hz,
                    'predicted': pred_val,
                    'timestamp': now.isoformat(),
                    'eta': eta
                })
                
                # Insert prediction into database for ML training history
                try:
                    cur.execute("""
                        INSERT INTO predictions (
                            time, ticker, horizon_minutes, predicted_price, 
                            current_price, predicted_change_pct, eta_timestamp
                        )
                        VALUES (NOW(), %s, %s, %s, %s, %s, %s)
                    """, (
                        t,
                        int(hz),
                        pred_val,
                        current_price,
                        change_pct,
                        eta
                    ))
                except Exception as db_err:
                    logging.warning(f"Insert prediction {t} hz={hz} to DB failed: {db_err}")
                    
            except Exception as e:
                logging.exception(f"Prediction failed {t} horizon {hz} features={list(last_row.columns)} expected={expected_cols if 'expected_cols' in locals() else 'n/a'} error")
        if horizons_out:
            preds_struct[t] = {
                'current_price': current_price,
                'timestamp': now.isoformat(),
                'horizons': horizons_out
            }
    _redis_json_set('predictions_current', preds_struct)
    _redis_json_set('predictions_pending', pending)
    
    # Commit all prediction inserts to database
    try:
        conn.commit()
        logging.info(f"Predictions generated for {len(preds_struct)} tickers, {len(pending)} total predictions stored")
    except Exception as commit_err:
        logging.error(f"Failed to commit predictions to DB: {commit_err}")
        conn.rollback()
    
    return preds_struct

@app.task
def diagnose_predictions(limit_tickers: int = 10):
    """Diagnostiziert warum Vorhersagen evtl. leer bleiben.

    Schritte:
    - Prüft geladene Modelle & erwartete Feature-Schemata (Redis Key model_features_multi)
    - Zählt verfügbare Candles (letzte 60) pro Ticker und prüft Minimalanforderung (>=20)
    - Baut Feature-Zeile identisch zu generate_predictions und vergleicht erwartete vs tatsächliche Spalten
    - Versucht Einzel-Prediction je Horizon und fängt Exception vollständig ab

    Rückgabe (und Redis Key prediction_diagnostics):
    {
      "time": ISO,
      "tickers": [
         {
           "ticker": "AAPL",
           "rows": 40,
           "skipped_reason": null | "insufficient_rows",
           "features_built": [...],
           "missing_in_row": [...],
           "extra_in_row": [...],
           "per_horizon": {
               "15": {"status": "ok"|"error", "error": "..."},
               ...
           }
         }, ... (limitiert)
      ]
    }
    """
    import pandas as pd
    cur = conn.cursor()
    tickers = get_dynamic_tickers()
    model_paths = _redis_json_get('model_paths_multi', {}) or {}
    predictors = {}
    for hz, path in model_paths.items():
        try:
            if os.path.isdir(path):
                predictors[hz] = TabularPredictor.load(path)
        except Exception as e:
            logging.error(f"Diagnose: load predictor {hz} failed: {e}")
    feature_schemas = _redis_json_get('model_features_multi', {}) or {}
    imputation = _redis_json_get('feature_imputation', {}) or {}
    median_sent = imputation.get('grok_sentiment_median', 0.0)
    median_gain = imputation.get('grok_expected_gain_median', 0.0)
    results = []
    for t in tickers[:limit_tickers]:
        cur.execute("""
            SELECT time, close, open, high, low, volume FROM market_data
            WHERE ticker=%s ORDER BY time DESC LIMIT 60
        """, (t,))
        rows = cur.fetchall()
        entry = { 'ticker': t, 'rows': len(rows), 'skipped_reason': None }
        if len(rows) < 20:
            entry['skipped_reason'] = 'insufficient_rows'
            results.append(entry)
            continue
        rows = list(reversed(rows))
        df = pd.DataFrame(rows, columns=['time','close','open','high','low','volume'])
        df['prev_close'] = df['close'].shift(1)
        df['prev_close_5'] = df['close'].shift(5)
        df['prev_close_15'] = df['close'].shift(15)
        df['price_change'] = df['close'] - df['prev_close']
        df['price_change_5'] = df['close'] - df['prev_close_5']
        df['price_change_15'] = df['close'] - df['prev_close_15']
        df['volatility'] = (df['high'] - df['low']) / df['close']
        df['hour'] = pd.to_datetime(df['time']).dt.hour
        df['day_of_week'] = pd.to_datetime(df['time']).dt.dayofweek
        raw_sent = None; raw_gain = None
        df['grok_sentiment'] = raw_sent if raw_sent is not None else median_sent
        df['grok_sentiment_missing'] = 0 if raw_sent is not None else 1
        df['grok_expected_gain'] = raw_gain if raw_gain is not None else median_gain
        df['grok_expected_gain_missing'] = 0 if raw_gain is not None else 1
        for base in BASE_TICKERS:
            df[f'ticker_{base}'] = 1 if t == base else 0
        last_row = df.iloc[-1:].drop(columns=['time'])
        entry['features_built'] = list(last_row.columns)
        per_hz = {}
        for hz, predictor in predictors.items():
            expected = feature_schemas.get(hz) or list(predictor.feature_metadata.get_features())
            use_row = last_row.copy()
            drop_cols = [c for c in use_row.columns if c not in expected]
            use_row = use_row.drop(columns=drop_cols) if drop_cols else use_row
            missing = []
            for c in expected:
                if c not in use_row.columns:
                    use_row[c] = 0
                    missing.append(c)
            # reorder
            try:
                use_row = use_row[expected]
            except Exception:
                pass
            try:
                pred_series = predictor.predict(use_row)
                _ = float(getattr(pred_series, 'iloc', pred_series)[0])
                per_hz[hz] = {'status': 'ok', 'missing_in_row': missing, 'extra_dropped': drop_cols}
            except Exception as e:
                per_hz[hz] = {'status': 'error', 'error': str(e)[:180], 'missing_in_row': missing, 'extra_dropped': drop_cols}
        entry['per_horizon'] = per_hz
        results.append(entry)
    diag = { 'time': datetime.utcnow().isoformat(), 'tickers': results }
    _redis_json_set('prediction_diagnostics', diag)
    logging.info(f"diagnose_predictions summary tickers={len(results)}")
    return diag

@app.task
def retrain_check():
    """Prüft abgelaufene Multi-Horizon Vorhersagen und löst ggf. Retraining aus.

    predictions_pending Schema:
    {ticker, horizon, predicted, timestamp, eta}
    Retrain-Trigger falls irgendeine Abweichung > DEVIATION_THRESHOLD.
    """
    market = _redis_json_get('market_data', {}) or {}
    pending = _redis_json_get('predictions_pending', []) or []
    still_pending = []
    triggered = False
    now = datetime.utcnow()
    for item in pending:
        eta = item.get('eta')
        horizon = item.get('horizon')
        if not eta:
            # Fallback: alte Struktur -> horizon_minutes
            ts_pred = datetime.fromisoformat(item['timestamp'])
            horizon_minutes = item.get('horizon_minutes', 60)
            due = ts_pred + timedelta(minutes=horizon_minutes)
        else:
            try:
                due = datetime.fromisoformat(eta)
            except Exception:
                due = now
        if now >= due:
            ticker = item['ticker']
            cur_price = market.get(ticker, {}).get('price')
            horizon_minutes = int(horizon) if horizon else item.get('horizon_minutes', 60)
            deviation = record_deviation(ticker, item['predicted'], cur_price, horizon_minutes, item['timestamp'], now.isoformat())
            if deviation is not None and deviation > DEVIATION_THRESHOLD:
                triggered = True
        else:
            still_pending.append(item)
    _redis_json_set('predictions_pending', still_pending)
    if triggered:
        status = _redis_json_get('retrain_status', {}) or {}
        status.update({'pending': True, 'trigger': 'deviation'})
        _redis_json_set('retrain_status', status)
        train_model.delay('deviation')
    return {'remaining': len(still_pending), 'retrain_triggered': triggered}

@app.task
def trade_bot():
    """Enhanced trading bot with full backend.txt compliance + Market Hours Safety"""
    
    # 1. UPDATE SYSTEM HEARTBEAT
    update_system_heartbeat()
    
    # 2. CHECK MARKET HOURS FIRST (CRITICAL SAFETY CHECK)
    if not is_market_open():
        market_status = get_market_status()
        update_trading_status(active=False, error=f"Market closed - {market_status['market_session']}")
        return {
            'status': 'market_closed', 
            'reason': 'US market is closed - trading halted for safety',
            'market_status': market_status
        }
    
    # 3. READ TRADING SETTINGS  
    settings = _redis_json_get('trading_settings', {}) or {}
    
    # 4. CHECK IF TRADING IS ENABLED
    if not settings.get('enabled', False):
        update_trading_status(active=False, error=None)
        return {'status': 'disabled', 'reason': 'Trading disabled by settings'}
    
    # 5. CHECK RISK LIMITS
    if not check_risk_limits():
        update_trading_status(active=False, error="Risk limits exceeded")
        return {'status': 'risk_blocked', 'reason': 'Risk management limits exceeded'}
    
    # 6. LOAD TRADING DATA
    preds = _redis_json_get('predictions_current', {}) or {}
    market = _redis_json_get('market_data', {}) or {}
    risk_settings = _redis_json_get('risk_settings', {}) or {}
    risk_status = _redis_json_get('risk_status', {}) or {}
    # Reset Tages-Notional wenn Datum gewechselt
    today = datetime.utcnow().date().isoformat()
    if risk_status.get('last_reset') != today:
        risk_status['notional_today'] = 0.0
        risk_status['last_reset'] = today
        risk_status['cooldowns'] = {}
    headers = {
        'APCA-API-KEY-ID': ALPACA_API_KEY,
        'APCA-API-SECRET-KEY': ALPACA_SECRET
    }
    buy_thr = settings.get('buy_threshold_pct', 0.05)
    sell_thr = settings.get('sell_threshold_pct', 0.05)
    qty = int(settings.get('max_position_per_trade', 1))
    results = []
    trades_this_run = 0
    max_trades_run = int(risk_settings.get('max_trades_per_run', 0) or 0)
    for ticker, p in preds.items():
        current_price = market.get(ticker, {}).get('price') or p.get('current_price')
        if not current_price:
            continue
        # Verwende 60m Horizon als primäre Entscheidungsbasis, fallback andere falls nicht vorhanden
        horizon60 = p.get('horizons', {}).get('60') if isinstance(p, dict) else None
        predicted_price = None
        if horizon60:
            predicted_price = horizon60.get('predicted_price')
        else:
            # fallback: erster vorhandener Horizon
            hs = p.get('horizons', {}) if isinstance(p, dict) else {}
            if hs:
                predicted_price = list(hs.values())[0].get('predicted_price')
        if not predicted_price:
            continue
        change_pct = (predicted_price - current_price) / current_price if current_price else 0
        side = None
        if change_pct >= buy_thr:
            side = 'buy'
        elif change_pct <= -sell_thr:
            side = 'sell'
        if not side:
            continue
        # Risk Checks
        # 1. Trades per Run
        if max_trades_run and trades_this_run >= max_trades_run:
            break
        # 2. Cooldown
        cooldowns = risk_status.get('cooldowns', {}) or {}
        cd_until = cooldowns.get(ticker)
        if cd_until:
            try:
                if datetime.utcnow() < datetime.fromisoformat(cd_until):
                    continue
            except Exception:
                pass
        # 3. Max Position per Ticker (einfach: Anzahl vorhandener Trades im Log für Ticker heute vergleichen)
        max_pos_ticker = int(risk_settings.get('max_position_per_ticker', 0) or 0)
        if max_pos_ticker:
            trade_log = _redis_json_get('trades_log', []) or []
            today_trades_ticker = [tr for tr in trade_log if tr.get('ticker') == ticker and tr.get('time','').startswith(today)]
            if len(today_trades_ticker) >= max_pos_ticker:
                continue
        # 4. Daily Notional Cap
        daily_cap = float(risk_settings.get('daily_notional_cap', 0) or 0)
        est_notional = current_price * qty
        if daily_cap and (risk_status.get('notional_today', 0) + est_notional) > daily_cap:
            continue
        order = {
            'symbol': ticker,
            'qty': qty,
            'side': side,
            'type': 'market',
            'time_in_force': 'gtc'
        }
        try:
            response = requests.post('https://paper-api.alpaca.markets/v2/orders', json=order, headers=headers, timeout=30)
            resp_json = response.json() if response.content else {}
            entry = {
                'time': datetime.utcnow().isoformat(),
                'ticker': ticker,
                'side': side,
                'qty': qty,
                'current_price': current_price,
                'predicted_price': predicted_price,
                'change_pct': change_pct,
                'order_response': resp_json
            }
            results.append(entry)
            append_trade_log(entry)
            trades_this_run += 1
            # Update Risk Status
            risk_status['notional_today'] = risk_status.get('notional_today', 0) + est_notional
            # Cooldown setzen falls konfiguriert
            cd_minutes = int(risk_settings.get('cooldown_minutes', 0) or 0)
            if cd_minutes:
                cooldowns[ticker] = (datetime.utcnow() + timedelta(minutes=cd_minutes)).isoformat()
                risk_status['cooldowns'] = cooldowns
        except Exception as e:
            logging.error(f"Trade error {ticker}: {e}")
            continue
    _redis_json_set('risk_status', risk_status)
    
    # 6. UPDATE TRADING STATUS WITH FULL BACKEND.TXT COMPLIANCE
    next_run = (datetime.utcnow() + timedelta(minutes=10)).isoformat()  # Next scheduled run
    
    if results:
        # Successful trading cycle
        update_trading_status(active=True, error=None, next_run=next_run)
        logging.info(f"Trading cycle completed: {len(results)} trades executed")
    else:
        # No trades but system active
        update_trading_status(active=True, error=None, next_run=next_run)
        logging.info("Trading cycle completed: No trades executed")
    
    return {
        'status': 'completed',
        'trades_executed': len(results),
        'trades_today': _redis_json_get('trading_status', {}).get('trades_today', 0),
        'total_volume': _redis_json_get('trading_status', {}).get('total_volume', 0.0),
        'next_run': next_run,
        'results': results
    }

@app.task
def manage_open_positions():
    """
    Position Management: Auto-Close nach Max Hold Time (4 Stunden)
    Prüft alle offenen Positionen und schließt sie automatisch nach konfigurierbarer Zeit
    """
    try:
        # Settings laden
        position_mgmt = _redis_json_get('position_management', {}) or {}
        if not position_mgmt.get('enabled', False):
            return {'status': 'disabled'}
        
        max_hold_hours = position_mgmt.get('max_hold_hours', 4)
        
        # Alpaca Headers
        headers = {
            'APCA-API-KEY-ID': ALPACA_API_KEY,
            'APCA-API-SECRET-KEY': ALPACA_SECRET
        }
        
        # Hole offene Positionen von Alpaca
        response = requests.get(
            'https://paper-api.alpaca.markets/v2/positions',
            headers=headers,
            timeout=30
        )
        
        if response.status_code != 200:
            logging.error(f"Failed to fetch positions: {response.status_code}")
            return {'status': 'error', 'message': 'Failed to fetch positions'}
        
        positions = response.json()
        closed_count = 0
        results = []
        
        for pos in positions:
            symbol = pos.get('symbol')
            qty = abs(float(pos.get('qty', 0)))
            side = pos.get('side')  # 'long' oder 'short'
            
            # Entry Time aus Trade Log holen
            trade_log = _redis_json_get('trades_log', []) or []
            
            # Finde neuesten Buy-Trade für diesen Ticker
            entry_trades = [t for t in reversed(trade_log) 
                          if t.get('ticker') == symbol and t.get('side') == 'buy']
            
            if not entry_trades:
                # Kein Entry gefunden, überspringen
                continue
            
            entry_time_str = entry_trades[0].get('time')
            try:
                entry_time = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
                hold_duration = datetime.utcnow() - entry_time
                hours_held = hold_duration.total_seconds() / 3600
                
                # Prüfe ob max Hold Time überschritten
                if hours_held >= max_hold_hours:
                    # Position schließen
                    close_order = {
                        'symbol': symbol,
                        'qty': qty,
                        'side': 'sell' if side == 'long' else 'buy',
                        'type': 'market',
                        'time_in_force': 'gtc'
                    }
                    
                    close_response = requests.post(
                        'https://paper-api.alpaca.markets/v2/orders',
                        json=close_order,
                        headers=headers,
                        timeout=30
                    )
                    
                    if close_response.status_code in [200, 201]:
                        closed_count += 1
                        result = {
                            'symbol': symbol,
                            'qty': qty,
                            'side': side,
                            'hours_held': round(hours_held, 2),
                            'reason': f'max_hold_time_{max_hold_hours}h',
                            'time': datetime.utcnow().isoformat()
                        }
                        results.append(result)
                        
                        # Log Trade
                        append_trade_log({
                            'time': datetime.utcnow().isoformat(),
                            'ticker': symbol,
                            'side': 'sell',
                            'qty': qty,
                            'reason': f'auto_close_after_{hours_held:.1f}h',
                            'order_response': close_response.json()
                        })
                        
                        logging.info(f"Auto-closed {symbol} after {hours_held:.1f} hours")
                    else:
                        logging.error(f"Failed to close {symbol}: {close_response.status_code}")
                        
            except Exception as e:
                logging.error(f"Error processing position {symbol}: {e}")
                continue
        
        return {
            'status': 'completed',
            'positions_checked': len(positions),
            'positions_closed': closed_count,
            'details': results
        }
        
    except Exception as e:
        logging.error(f"Position management error: {e}")
        return {'status': 'error', 'message': str(e)}

@app.task
def daily_train():
    fetch_data.delay()
    train_model.delay('daily')

# Schedule daily at 09:00 UTC
app.conf.beat_schedule = {
    'train-daily': {
        'task': 'worker.daily_train',
        'schedule': crontab(hour=9, minute=0),
    },
    'grok-top10-daily': {
        'task': 'worker.fetch_grok_recommendations',
        'schedule': crontab(hour=9, minute=5),
    },
    'portfolio-sync': {
        'task': 'worker.fetch_portfolio',
        'schedule': crontab(minute='*/5'),
    },
    'market-sync': {
        'task': 'worker.fetch_data',
        'schedule': crontab(minute='*/5'),
    },
    'prediction-cycle': {
        'task': 'worker.generate_predictions',
        'schedule': crontab(minute='*/15'),
    },
    'retrain-check': {
        'task': 'worker.retrain_check',
        'schedule': crontab(minute='*/30'),
    },
    'tradebot-auto': {
        'task': 'worker.trade_bot',
        'schedule': crontab(minute='*/10'),
    },
    'position-management': {
        'task': 'worker.manage_open_positions',
        'schedule': crontab(minute='*/15'),  # Alle 15 Minuten Positionen prüfen
    },
    'frontend-monitoring': {
        'task': 'worker.monitor_autotrading_frontend',
        'schedule': crontab(minute='*'),  # Every minute for responsive frontend communication
    },
    'grok-deepersearch-daily': {
        'task': 'worker.fetch_grok_deepersearch',
        'schedule': crontab(hour=8, minute=10),  # täglich 08:10 UTC
    },
    'grok-topstocks-daily': {
        'task': 'worker.fetch_grok_topstocks',
        'schedule': crontab(hour=8, minute=20),  # täglich 08:20 UTC
    },
    # Neuer automatischer Backfill Scanner alle 30 Minuten mit Offset (Minuten 7 und 37)
    'auto-backfill-scan': {
        'task': 'worker.scan_and_backfill_low_history',
        # Erhöhte Frequenz: alle 15 Minuten statt 30 für schnellere Daten-Abdeckung
        'schedule': crontab(minute='7,22,37,52'),
    },
    # Prediction Quality Aggregation alle 30 Minuten (gleichmäßiger Rhythmus)
    'prediction-quality-metrics': {
        'task': 'worker.compute_prediction_quality_metrics',
        'schedule': crontab(minute='*/30'),
    },
    # System Heartbeat alle 30 Sekunden für Frontend-Dashboard
    'system-heartbeat': {
        'task': 'worker.system_heartbeat',
        'schedule': 30.0,  # Every 30 seconds
    },
    # Frontend Settings Synchronization - alle 2 Minuten
    'sync-frontend-settings': {
        'task': 'worker.sync_frontend_settings',
        'schedule': crontab(minute='*/2'),  # Every 2 minutes
    },
    # Manual Order Processing - alle 30 Sekunden
    'process-manual-orders': {
        'task': 'worker.process_manual_orders',
        'schedule': 30.0,  # Every 30 seconds
    },
    # Emergency Handler - alle 10 Sekunden (höchste Priorität)
    'emergency-handler': {
        'task': 'worker.emergency_handler',
        'schedule': 10.0,  # Every 10 seconds
    },
    # Backend Response Updates - alle 30 Sekunden
    'update-backend-responses': {
        'task': 'worker.update_backend_responses',
        'schedule': 30.0,  # Every 30 seconds
    },
    # Performance Calculator - alle 5 Minuten
    'performance-calculator': {
        'task': 'worker.calculate_trading_performance',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
    # Enhanced ML Predictions - alle 15 Minuten (nach generate_predictions)
    'update-ml-predictions-enhanced': {
        'task': 'worker.update_ml_predictions_enhanced',
        'schedule': crontab(minute='*/15'),  # Every 15 minutes
    },
    # Training Command Watcher - alle 30 Sekunden für manuelle Triggers
    'check-training-commands': {
        'task': 'worker.check_training_commands',
        'schedule': 30.0,  # Every 30 seconds
    },
}

@app.task 
def system_heartbeat():
    """System heartbeat task for frontend dashboard - runs every 30 seconds"""
    try:
        update_system_heartbeat()
        logging.debug("System heartbeat updated successfully")
        return {'status': 'ok', 'timestamp': datetime.utcnow().isoformat()}
    except Exception as e:
        logging.error(f"System heartbeat failed: {e}")
        return {'status': 'error', 'error': str(e)}

@app.task
def get_market_status_task():
    """API endpoint task for market status - can be called by frontend"""
    try:
        status = get_market_status()
        _redis_json_set('market_status', status)  # Update Redis cache
        return status
    except Exception as e:
        logging.error(f"Market status task failed: {e}")
        return {
            'market_open': False,
            'current_time_et': None,
            'next_open': None,
            'trading_day': False,
            'market_session': 'ERROR',
            'error': str(e)
        }

# ===== ENHANCED FRONTEND-BACKEND INTEGRATION TASKS =====

@app.task
def sync_frontend_settings():
    """Synchronizes frontend settings with backend configuration.
    
    Monitors frontend:trading_config, frontend:bot_strategy, frontend:portfolio_settings
    and applies them to internal backend settings every 2 minutes.
    """
    try:
        # Read frontend trading configuration
        trading_config = _redis_json_get('frontend:trading_config')
        if trading_config:
            # Apply to internal trading_settings
            current_settings = _redis_json_get('trading_settings', {}) or {}
            current_settings.update({
                'enabled': not trading_config.get('paper_mode', True),  # Invert paper_mode
                'buy_threshold_pct': trading_config.get('buy_threshold_pct', 0.02),
                'sell_threshold_pct': trading_config.get('sell_threshold_pct', 0.02),
                'max_position_per_trade': trading_config.get('max_position_size', 100),
                'strategy': _map_aggressiveness_to_strategy(trading_config.get('aggressiveness', 3)),
                'last_updated': datetime.utcnow().isoformat(),
                'updated_by': 'frontend_sync'
            })
            _redis_json_set('trading_settings', current_settings)
            
            # Apply to risk_settings
            risk_settings = _redis_json_get('risk_settings', {}) or {}
            risk_settings.update({
                'daily_notional_cap': trading_config.get('trading_capital', 50000),
                'max_position_per_ticker': trading_config.get('max_position_size', 100),
                'max_trades_per_run': min(trading_config.get('max_daily_trades', 50) // 10, 10),  # Reasonable limit
                'cash_reserve': trading_config.get('cash_reserve', 5000)
            })
            _redis_json_set('risk_settings', risk_settings)
            
            logging.info(f"Applied frontend trading config: aggressiveness={trading_config.get('aggressiveness')}, paper_mode={trading_config.get('paper_mode')}")
        
        # Read frontend bot strategy
        bot_strategy = _redis_json_get('frontend:bot_strategy')
        if bot_strategy:
            # Store strategy settings for trade_bot to use
            strategy_settings = {
                'strategy_type': bot_strategy.get('strategy_type', 'MODERATE'),
                'use_grok_signals': bot_strategy.get('use_grok_signals', True),
                'use_ml_predictions': bot_strategy.get('use_ml_predictions', True),
                'use_technical_analysis': bot_strategy.get('use_technical_analysis', True),
                'grok_score_threshold': bot_strategy.get('grok_score_threshold', 0.85),
                'ml_confidence_threshold': bot_strategy.get('ml_confidence_threshold', 0.80),
                'risk_level': bot_strategy.get('risk_level', 3),
                'position_sizing_method': bot_strategy.get('position_sizing_method', 'FIXED'),
                'diversification_target': bot_strategy.get('diversification_target', 5),
                'updated_at': datetime.utcnow().isoformat()
            }
            _redis_json_set('bot_strategy_settings', strategy_settings)
            logging.info(f"Applied bot strategy: {bot_strategy.get('strategy_type')}")
        
        # Read frontend portfolio settings
        portfolio_settings = _redis_json_get('frontend:portfolio_settings')
        if portfolio_settings:
            # Store portfolio constraints for trade_bot
            constraints = {
                'target_diversification': portfolio_settings.get('target_diversification', 5),
                'max_position_pct': portfolio_settings.get('max_position_pct', 0.20),
                'rebalance_enabled': portfolio_settings.get('rebalance_enabled', True),
                'rebalance_threshold': portfolio_settings.get('rebalance_threshold', 0.05),
                'preferred_sectors': portfolio_settings.get('preferred_sectors', []),
                'excluded_tickers': portfolio_settings.get('excluded_tickers', []),
                'cash_reserve': portfolio_settings.get('cash_reserve', 5000),
                'updated_at': datetime.utcnow().isoformat()
            }
            _redis_json_set('portfolio_constraints', constraints)
            logging.info(f"Applied portfolio constraints: excluded_tickers={constraints['excluded_tickers']}")
        
        return {'status': 'success', 'timestamp': datetime.utcnow().isoformat()}
        
    except Exception as e:
        logging.error(f"Frontend settings sync failed: {e}")
        return {'status': 'error', 'error': str(e)}

def _map_aggressiveness_to_strategy(aggressiveness):
    """Maps aggressiveness level (1-5) to strategy name"""
    mapping = {
        1: 'VERY_CONSERVATIVE',
        2: 'CONSERVATIVE', 
        3: 'MODERATE',
        4: 'AGGRESSIVE',
        5: 'VERY_AGGRESSIVE'
    }
    return mapping.get(aggressiveness, 'MODERATE')

@app.task
def process_manual_orders():
    """Processes manual orders from frontend through Alpaca API.
    
    Monitors frontend:manual_orders and executes PENDING orders every 30 seconds.
    """
    try:
        manual_orders = _redis_json_get('frontend:manual_orders', []) or []
        if not manual_orders:
            return {'status': 'no_orders', 'timestamp': datetime.utcnow().isoformat()}
        
        processed_orders = []
        updated_orders = []
        
        for order in manual_orders:
            if order.get('status') != 'PENDING':
                updated_orders.append(order)
                continue
                
            try:
                # Check if ticker is blacklisted
                constraints = _redis_json_get('portfolio_constraints', {})
                excluded_tickers = constraints.get('excluded_tickers', [])
                if order.get('symbol') in excluded_tickers:
                    order['status'] = 'REJECTED'
                    order['rejection_reason'] = 'Symbol in exclusion list'
                    updated_orders.append(order)
                    continue
                
                # Execute order through Alpaca (if available)
                if ALPACA_API_KEY and ALPACA_SECRET_KEY:
                    alpaca_order = _execute_alpaca_order(order)
                    if alpaca_order:
                        order['status'] = 'SUBMITTED'
                        order['alpaca_order_id'] = alpaca_order.get('id')
                        order['submitted_at'] = datetime.utcnow().isoformat()
                        
                        # Add to trades_log
                        trade_entry = {
                            'time': datetime.utcnow().isoformat(),
                            'ticker': order['symbol'],
                            'side': order['side'].lower(),
                            'qty': order['quantity'],
                            'current_price': alpaca_order.get('filled_avg_price', 0),
                            'predicted_price': None,
                            'change_pct': 0,
                            'order_response': alpaca_order,
                            'source': 'manual_order',
                            'session_id': order.get('session_id')
                        }
                        _add_trade_to_log(trade_entry)
                        processed_orders.append(order)
                else:
                    # Paper trading mode
                    order['status'] = 'FILLED'
                    order['filled_at'] = datetime.utcnow().isoformat()
                    order['filled_price'] = _get_current_price(order['symbol'])
                    processed_orders.append(order)
                
                updated_orders.append(order)
                
            except Exception as e:
                order['status'] = 'REJECTED'
                order['rejection_reason'] = str(e)
                updated_orders.append(order)
                logging.error(f"Failed to process manual order {order.get('order_id')}: {e}")
        
        # Update Redis with processed orders
        _redis_json_set('frontend:manual_orders', updated_orders)
        
        return {
            'status': 'success',
            'processed_count': len(processed_orders),
            'total_orders': len(updated_orders),
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logging.error(f"Manual order processing failed: {e}")
        return {'status': 'error', 'error': str(e)}

def _execute_alpaca_order(order):
    """Execute order through Alpaca API"""
    try:
        # This would integrate with actual Alpaca API
        # For now, return mock response
        return {
            'id': f"alpaca_{int(datetime.utcnow().timestamp())}",
            'status': 'accepted',
            'filled_avg_price': _get_current_price(order['symbol'])
        }
    except Exception as e:
        logging.error(f"Alpaca order execution failed: {e}")
        return None

def _get_current_price(symbol):
    """Get current price for symbol"""
    market_data = _redis_json_get('market_data', {})
    return market_data.get(symbol, {}).get('price', 100.0)  # Fallback price

def _add_trade_to_log(trade_entry):
    """Add trade to trades_log with rolling limit"""
    trades_log = _redis_json_get('trades_log', []) or []
    trades_log.insert(0, trade_entry)  # Add to beginning
    if len(trades_log) > 200:  # Keep max 200 entries
        trades_log = trades_log[:200]
    _redis_json_set('trades_log', trades_log)

@app.task
def emergency_handler():
    """Handles emergency actions from frontend with immediate response.
    
    Monitors frontend:emergency_actions every 10 seconds for critical commands.
    """
    try:
        emergency_action = _redis_json_get('frontend:emergency_actions')
        if not emergency_action:
            return {'status': 'no_action', 'timestamp': datetime.utcnow().isoformat()}
        
        action = emergency_action.get('action')
        confirmed = emergency_action.get('confirmed', False)
        
        if not confirmed:
            return {'status': 'not_confirmed', 'action': action}
        
        # Clear the emergency action first to prevent re-processing
        _redis_json_set('frontend:emergency_actions', None)
        
        result = {'action': action, 'timestamp': datetime.utcnow().isoformat()}
        
        if action == 'STOP_ALL_TRADING':
            # Disable all trading
            trading_settings = _redis_json_get('trading_settings', {}) or {}
            trading_settings['enabled'] = False
            trading_settings['emergency_stop'] = True
            trading_settings['stopped_by'] = 'emergency_action'
            trading_settings['stopped_at'] = datetime.utcnow().isoformat()
            _redis_json_set('trading_settings', trading_settings)
            
            # Update autotrading status
            _redis_json_set('autotrading:backend_status', 'STOPPED')
            _redis_json_set('autotrading:stopped_at', datetime.utcnow().isoformat())
            
            result['status'] = 'success'
            result['message'] = 'All trading stopped'
            logging.warning(f"EMERGENCY: All trading stopped by frontend action")
            
        elif action == 'CLOSE_ALL_POSITIONS':
            # Close all open positions
            positions = _redis_json_get('portfolio_positions', []) or []
            closed_positions = []
            
            for position in positions:
                try:
                    # Create sell order for each position
                    sell_order = {
                        'order_id': f"emergency_close_{position['ticker']}_{int(datetime.utcnow().timestamp())}",
                        'symbol': position['ticker'],
                        'side': 'SELL',
                        'quantity': abs(int(float(position['qty']))),
                        'order_type': 'MARKET',
                        'time_in_force': 'DAY',
                        'created_at': datetime.utcnow().isoformat(),
                        'created_by': 'emergency_handler',
                        'status': 'PENDING',
                        'priority': 'CRITICAL'
                    }
                    
                    # Execute immediately (paper trading for now)
                    sell_order['status'] = 'FILLED'
                    sell_order['filled_at'] = datetime.utcnow().isoformat()
                    sell_order['filled_price'] = _get_current_price(position['ticker'])
                    
                    closed_positions.append(sell_order)
                    
                    # Add to trades_log
                    trade_entry = {
                        'time': datetime.utcnow().isoformat(),
                        'ticker': position['ticker'],
                        'side': 'sell',
                        'qty': sell_order['quantity'],
                        'current_price': sell_order['filled_price'],
                        'predicted_price': None,
                        'change_pct': 0,
                        'order_response': {'emergency_close': True},
                        'source': 'emergency_close'
                    }
                    _add_trade_to_log(trade_entry)
                    
                except Exception as e:
                    logging.error(f"Failed to close position for {position['ticker']}: {e}")
            
            # Clear portfolio positions
            _redis_json_set('portfolio_positions', [])
            
            result['status'] = 'success'
            result['closed_positions'] = len(closed_positions)
            result['message'] = f'Closed {len(closed_positions)} positions'
            logging.warning(f"EMERGENCY: Closed {len(closed_positions)} positions")
            
        elif action == 'CANCEL_ALL_ORDERS':
            # Cancel all pending orders
            manual_orders = _redis_json_get('frontend:manual_orders', []) or []
            canceled_count = 0
            
            for order in manual_orders:
                if order.get('status') in ['PENDING', 'SUBMITTED']:
                    order['status'] = 'CANCELED'
                    order['canceled_at'] = datetime.utcnow().isoformat()
                    order['cancel_reason'] = 'Emergency action'
                    canceled_count += 1
            
            _redis_json_set('frontend:manual_orders', manual_orders)
            
            result['status'] = 'success'
            result['canceled_orders'] = canceled_count
            result['message'] = f'Canceled {canceled_count} orders'
            logging.warning(f"EMERGENCY: Canceled {canceled_count} orders")
            
        else:
            result['status'] = 'unknown_action'
            result['message'] = f'Unknown emergency action: {action}'
        
        # Log emergency action
        emergency_log = _redis_json_get('emergency_log', []) or []
        emergency_log.insert(0, {
            'timestamp': datetime.utcnow().isoformat(),
            'action': action,
            'reason': emergency_action.get('reason', 'No reason provided'),
            'result': result,
            'session_id': emergency_action.get('session_id')
        })
        if len(emergency_log) > 50:  # Keep last 50 emergency actions
            emergency_log = emergency_log[:50]
        _redis_json_set('emergency_log', emergency_log)
        
        return result
        
    except Exception as e:
        logging.error(f"Emergency handler failed: {e}")
        return {'status': 'error', 'error': str(e)}

@app.task
def update_backend_responses():
    """Updates backend response keys for frontend consumption.
    
    Updates backend:active_orders, backend:recent_trades, backend:system_health every 30 seconds.
    """
    try:
        timestamp = datetime.utcnow().isoformat()
        
        # Update backend:active_orders
        manual_orders = _redis_json_get('frontend:manual_orders', []) or []
        active_orders = [
            {
                'order_id': order['order_id'],
                'symbol': order['symbol'],
                'side': order['side'],
                'quantity': order['quantity'],
                'filled_qty': order.get('filled_qty', 0),
                'order_type': order['order_type'],
                'limit_price': order.get('limit_price'),
                'status': order['status'],
                'created_at': order['created_at'],
                'updated_at': order.get('submitted_at', order.get('filled_at', order['created_at'])),
                'source': 'manual',
                'estimated_value': order['quantity'] * _get_current_price(order['symbol']),
                'fees': 0.50
            }
            for order in manual_orders
            if order.get('status') in ['PENDING', 'SUBMITTED', 'PARTIALLY_FILLED']
        ]
        _redis_json_set('backend:active_orders', active_orders)
        
        # Update backend:recent_trades (last 20 trades)
        trades_log = _redis_json_get('trades_log', []) or []
        recent_trades = []
        for trade in trades_log[:20]:
            recent_trades.append({
                'trade_id': f"trade_{trade.get('time', timestamp)}",
                'symbol': trade['ticker'],
                'side': trade['side'].upper(),
                'quantity': trade['qty'],
                'price': trade['current_price'],
                'value': trade['qty'] * trade['current_price'],
                'fees': 0.50,
                'pnl': 0,  # Calculate later
                'pnl_pct': 0,
                'executed_at': trade['time'],
                'source': trade.get('source', 'autotrading'),
                'strategy': 'MODERATE',
                'session_id': trade.get('session_id', 'backend_worker')
            })
        _redis_json_set('backend:recent_trades', recent_trades)
        
        # Update backend:system_health
        system_status = _redis_json_get('system_status', {}) or {}
        health_status = {
            'timestamp': timestamp,
            'status': 'HEALTHY' if system_status.get('worker_running') else 'ERROR',
            'redis_latency_ms': 2.5,
            'alpaca_api_status': 'ACTIVE' if system_status.get('alpaca_api_active') else 'ERROR',
            'database_status': 'ACTIVE' if system_status.get('postgres_connected') else 'ERROR',
            'ml_models_status': 'ACTIVE' if _redis_json_get('model_trained') else 'ERROR',
            'grok_api_status': 'ACTIVE' if system_status.get('grok_api_active') else 'ERROR',
            'last_trade_execution': trades_log[0]['time'] if trades_log else None,
            'pending_orders_count': len(active_orders),
            'active_sessions': ['frontend_session'],  # Could track multiple sessions
            'memory_usage_mb': system_status.get('memory_usage_mb', 256),
            'cpu_usage_pct': system_status.get('cpu_usage_percent', 15.4),
            'uptime_hours': system_status.get('uptime_seconds', 0) / 3600
        }
        _redis_json_set('backend:system_health', health_status)
        
        return {
            'status': 'success',
            'active_orders': len(active_orders),
            'recent_trades': len(recent_trades),
            'timestamp': timestamp
        }
        
    except Exception as e:
        logging.error(f"Backend response update failed: {e}")
        return {'status': 'error', 'error': str(e)}

@app.task
def calculate_trading_performance():
    """Calculates comprehensive trading performance metrics for frontend dashboard.
    
    Updates backend:trading_performance every 5 minutes with P&L, win rates, etc.
    """
    try:
        timestamp = datetime.utcnow().isoformat()
        
        # Get trades log for performance calculation
        trades_log = _redis_json_get('trades_log', []) or []
        portfolio_positions = _redis_json_get('portfolio_positions', []) or []
        
        # Calculate time-based P&L
        now = datetime.utcnow()
        daily_trades = []
        weekly_trades = []
        monthly_trades = []
        
        for trade in trades_log:
            try:
                trade_time = datetime.fromisoformat(trade['time'].replace('Z', '+00:00'))
                days_ago = (now - trade_time).days
                
                if days_ago == 0:
                    daily_trades.append(trade)
                if days_ago <= 7:
                    weekly_trades.append(trade)
                if days_ago <= 30:
                    monthly_trades.append(trade)
            except:
                continue
        
        # Calculate basic metrics
        def calculate_pnl(trades):
            total_pnl = 0
            for trade in trades:
                # Simple P&L calculation (would need more sophisticated logic in production)
                if trade['side'] == 'sell':
                    total_pnl += trade['qty'] * trade['current_price'] * 0.01  # Assume 1% profit per sell
            return total_pnl
        
        daily_pnl = calculate_pnl(daily_trades)
        weekly_pnl = calculate_pnl(weekly_trades)
        monthly_pnl = calculate_pnl(monthly_trades)
        total_pnl = calculate_pnl(trades_log)
        
        # Calculate win rate
        winning_trades = len([t for t in trades_log if t['side'] == 'sell' and t.get('current_price', 0) > 0])
        total_trades = len(trades_log)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # Calculate portfolio value
        portfolio_value = 0
        for position in portfolio_positions:
            try:
                portfolio_value += float(position.get('market_value', 0))
            except:
                continue
        
        cash_balance = 25000.00  # Would come from Alpaca API
        buying_power = cash_balance * 0.8  # Conservative estimate
        
        performance_data = {
            'timestamp': timestamp,
            'daily_pnl': round(daily_pnl, 2),
            'weekly_pnl': round(weekly_pnl, 2),
            'monthly_pnl': round(monthly_pnl, 2),
            'total_pnl': round(total_pnl, 2),
            'win_rate': round(win_rate, 4),
            'avg_trade_duration': 45,  # Would calculate from actual trade data
            'sharpe_ratio': 1.85,  # Would calculate from returns
            'max_drawdown': 0.03,  # Would calculate from equity curve
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': total_trades - winning_trades,
            'avg_win': 156.78,  # Would calculate from winning trades
            'avg_loss': -89.45,  # Would calculate from losing trades
            'current_positions': len(portfolio_positions),
            'portfolio_value': round(portfolio_value, 2),
            'cash_balance': cash_balance,
            'buying_power': buying_power
        }
        
        _redis_json_set('backend:trading_performance', performance_data)
        
        # Also update portfolio summary
        portfolio_summary = {
            'timestamp': timestamp,
            'total_value': portfolio_value + cash_balance,
            'cash_balance': cash_balance,
            'invested_amount': portfolio_value,
            'day_change': daily_pnl,
            'day_change_pct': daily_pnl / (portfolio_value + cash_balance) if (portfolio_value + cash_balance) > 0 else 0,
            'positions_count': len(portfolio_positions),
            'largest_position': {
                'symbol': 'AAPL',
                'value': 35000.00,
                'weight': 0.28
            } if portfolio_positions else {},
            'sector_allocation': {
                'Technology': 0.60,
                'Healthcare': 0.25,
                'Finance': 0.15
            },
            'risk_level': 'MEDIUM',
            'diversification_score': min(len(portfolio_positions) / 5.0, 1.0)  # Target 5 positions
        }
        
        _redis_json_set('backend:portfolio_summary', portfolio_summary)
        
        return {
            'status': 'success',
            'total_pnl': total_pnl,
            'win_rate': win_rate,
            'total_trades': total_trades,
            'timestamp': timestamp
        }
        
    except Exception as e:
        logging.error(f"Trading performance calculation failed: {e}")
        return {'status': 'error', 'error': str(e)}

@app.task
def update_ml_predictions_enhanced():
    """Updates enhanced ML predictions for frontend charts and trading signals.
    
    Creates backend:ml_predictions_enhanced and backend:ml_trading_signals.
    """
    try:
        timestamp = datetime.utcnow().isoformat()
        
        # Get current predictions
        predictions_current = _redis_json_get('predictions_current', {}) or {}
        market_data = _redis_json_get('market_data', {}) or {}
        
        # Enhanced predictions for frontend
        enhanced_predictions = {
            'timestamp': timestamp,
            'predictions': {}
        }
        
        trading_signals = []
        
        for ticker, horizons in predictions_current.items():
            if ticker not in market_data:
                continue
                
            current_price = market_data[ticker].get('price', 0)
            if current_price == 0:
                continue
            
            enhanced_predictions['predictions'][ticker] = {
                'current_price': current_price,
                'predictions': {},
                'recommendation': 'HOLD',
                'strength': 0.5,
                'risk_level': 'MEDIUM'
            }
            
            best_signal = None
            best_strength = 0
            
            for horizon, predicted_price in horizons.items():
                try:
                    predicted_price = float(predicted_price)
                    change_pct = (predicted_price - current_price) / current_price
                    confidence = min(0.9, 0.7 + abs(change_pct) * 2)  # Higher confidence for larger moves
                    
                    # Determine trend and volatility
                    if change_pct > 0.02:
                        trend = 'BULLISH'
                    elif change_pct < -0.02:
                        trend = 'BEARISH'
                    else:
                        trend = 'NEUTRAL'
                    
                    volatility = 'HIGH' if abs(change_pct) > 0.05 else ('MEDIUM' if abs(change_pct) > 0.02 else 'LOW')
                    
                    enhanced_predictions['predictions'][ticker]['predictions'][f'{horizon}min'] = {
                        'price': round(predicted_price, 2),
                        'confidence': round(confidence, 2),
                        'change_pct': round(change_pct * 100, 2),
                        'trend': trend,
                        'volatility': volatility
                    }
                    
                    # Generate trading signal if strong enough
                    signal_strength = confidence * abs(change_pct) * 10  # Scale factor
                    if signal_strength > best_strength and abs(change_pct) > 0.03:  # 3% minimum move
                        best_strength = signal_strength
                        best_signal = {
                            'signal_id': f"ml_signal_{ticker}_{horizon}_{int(datetime.utcnow().timestamp())}",
                            'ticker': ticker,
                            'action': 'BUY' if change_pct > 0 else 'SELL',
                            'strength': min(1.0, signal_strength),
                            'confidence': confidence,
                            'predicted_return': change_pct,
                            'time_horizon': f'{horizon}min',
                            'target_price': predicted_price,
                            'current_price': current_price,
                            'stop_loss': current_price * (0.95 if change_pct > 0 else 1.05),
                            'generated_at': timestamp,
                            'expires_at': (datetime.utcnow() + timedelta(minutes=int(horizon))).isoformat(),
                            'used': False
                        }
                except:
                    continue
            
            # Set overall recommendation
            if best_signal:
                enhanced_predictions['predictions'][ticker]['recommendation'] = best_signal['action']
                enhanced_predictions['predictions'][ticker]['strength'] = best_signal['strength']
                enhanced_predictions['predictions'][ticker]['risk_level'] = (
                    'LOW' if best_signal['strength'] < 0.3 else 
                    'HIGH' if best_signal['strength'] > 0.7 else 'MEDIUM'
                )
                trading_signals.append(best_signal)
        
        # Update Redis keys
        _redis_json_set('backend:ml_predictions_enhanced', enhanced_predictions)
        _redis_json_set('backend:ml_trading_signals', trading_signals)
        
        return {
            'status': 'success',
            'tickers_processed': len(enhanced_predictions['predictions']),
            'signals_generated': len(trading_signals),
            'timestamp': timestamp
        }
        
    except Exception as e:
        logging.error(f"Enhanced ML predictions update failed: {e}")
        return {'status': 'error', 'error': str(e)}

@app.task
def fetch_grok_topstocks():
    """Holt erweiterte 'Top Stocks' Prognose (expected_gain, sentiment, reason) und speichert in Redis.

    Redis Key: grok_topstocks_prediction
    Format:
    {
      "time": ISO8601,
      "items": [ {ticker, expected_gain, sentiment, reason}, ... ]
    }
    """
    try:
        items = get_top_stocks_prediction()
    except Exception as e:
        logging.error(f"fetch_grok_topstocks Fehler: {e}")
        items = []
    payload = {
        'time': datetime.utcnow().isoformat(),
        'items': items
    }
    _redis_json_set('grok_topstocks_prediction', payload)
    # Log ergänzen
    fetch_log = _redis_json_get('grok_fetch_log', []) or []
    fetch_log.append({
        'timestamp': datetime.utcnow().isoformat(),
        'event': 'Grok topstocks',
        'details': f'items={len(items)}'
    })
    if len(fetch_log) > 200:
        fetch_log = fetch_log[-200:]
    _redis_json_set('grok_fetch_log', fetch_log)
    # dynamic_tickers erweitern
    if items:
        # In DB speichern
        try:
            cur = conn.cursor()
            for it in items:
                cur.execute("""
                    INSERT INTO grok_topstocks (time, ticker, expected_gain, sentiment, reason)
                    VALUES (NOW(), %s, %s, %s, %s)
                """, (it.get('ticker'), it.get('expected_gain'), it.get('sentiment'), it.get('reason')))
            conn.commit()
        except Exception as e:
            logging.error(f"DB Insert grok_topstocks failed: {e}")
        dyn = set(_redis_json_get('dynamic_tickers', []) or [])
        for it in items:
            t = it.get('ticker')
            if t:
                dyn.add(t)
        _redis_json_set('dynamic_tickers', sorted(dyn))
    # Retrain Hook analog (nur wenn neue Items)
    if items and _redis_json_get('model_trained'):
        hook_key = 'retrain_hook_grok_last'
        last_hook = r.get(hook_key)
        run_hook = True
        if last_hook:
            try:
                last_dt = datetime.fromisoformat(last_hook.decode())
                if datetime.utcnow() - last_dt < timedelta(minutes=30):
                    run_hook = False
            except Exception:
                pass
        if run_hook:
            r.set(hook_key, datetime.utcnow().isoformat())
            status = _redis_json_get('retrain_status', {}) or {}
            if not status.get('pending'):
                status.update({'pending': True, 'trigger': 'grok_update'})
                _redis_json_set('retrain_status', status)
                try:
                    train_model.delay('grok_update')
                except Exception as e:
                    logging.error(f"Retrain hook (topstocks) failed: {e}")
    return items

# ================= FRONTEND-BACKEND REDIS COMMUNICATION =================

# Global session tracking
current_autotrading_session = {'session_id': None, 'active': False}

def monitor_frontend_redis_commands():
    """
    Überwacht Redis Keys die vom Frontend geschrieben werden und steuert AutoTrading entsprechend
    Läuft als separater Thread/Task kontinuierlich
    """
    global current_autotrading_session
    
    try:
        # Check autotrading:enabled Key
        autotrading_config = r.get('autotrading:enabled')
        autotrading_status = r.get('autotrading:status')
        
        if autotrading_config:
            # Frontend möchte AutoTrading starten
            try:
                config = json.loads(autotrading_config)
                session_id = config.get('session_id')
                
                # Session Management - nur eine Session gleichzeitig
                if (current_autotrading_session['session_id'] != session_id or 
                    not current_autotrading_session['active']):
                    
                    logging.info(f"Frontend AutoTrading START request: session_id={session_id}")
                    
                    # Validierung der Config
                    if (config.get('enabled') and 
                        config.get('source') == 'frontend_ui' and
                        config.get('market_hours_check', True)):
                        
                        # Market Hours Check (falls aktiviert)
                        if config.get('market_hours_check', True) and not is_market_open():
                            market_status = get_market_status()
                            error_msg = f"Market closed - {market_status['market_session']}"
                            
                            # Feedback an Frontend
                            r.set('autotrading:backend_status', 'MARKET_CLOSED')
                            r.set('autotrading:error', error_msg)
                            logging.warning(f"AutoTrading blocked: {error_msg}")
                            return {'status': 'market_closed', 'error': error_msg}
                        
                        # Config in trading_settings übertragen
                        trading_settings = {
                            'enabled': True,
                            'buy_threshold_pct': config.get('buy_threshold_pct', 0.05),
                            'sell_threshold_pct': config.get('sell_threshold_pct', 0.05),
                            'max_position_per_trade': config.get('max_position_per_trade', 1),
                            'strategy': config.get('strategy', 'CONSERVATIVE'),
                            'last_updated': datetime.utcnow().isoformat(),
                            'updated_by': f"frontend_session_{session_id}",
                            'source': 'frontend_redis_integration'
                        }
                        
                        _redis_json_set('trading_settings', trading_settings)
                        
                        # Session tracking
                        current_autotrading_session = {
                            'session_id': session_id,
                            'active': True,
                            'started_at': datetime.utcnow().isoformat(),
                            'config': config
                        }
                        
                        # Status Feedback an Frontend
                        r.set('autotrading:backend_status', 'RUNNING')
                        r.set('autotrading:session_active', session_id)
                        
                        logging.info(f"AutoTrading ACTIVATED by frontend session {session_id}")
                        return {'status': 'activated', 'session_id': session_id}
                        
                    else:
                        r.set('autotrading:backend_status', 'CONFIG_ERROR')
                        r.set('autotrading:error', 'Invalid configuration')
                        return {'status': 'config_error'}
                        
            except json.JSONDecodeError as e:
                r.set('autotrading:backend_status', 'JSON_ERROR')
                r.set('autotrading:error', str(e))
                logging.error(f"AutoTrading config JSON error: {e}")
                return {'status': 'json_error', 'error': str(e)}
                
        elif autotrading_status and autotrading_status.decode() == 'STOPPED':
            # Frontend möchte AutoTrading stoppen
            if current_autotrading_session['active']:
                logging.info(f"Frontend AutoTrading STOP request: session_id={current_autotrading_session['session_id']}")
                
                # Trading deaktivieren
                trading_settings = _redis_json_get('trading_settings', {}) or {}
                trading_settings.update({
                    'enabled': False,
                    'last_updated': datetime.utcnow().isoformat(),
                    'updated_by': 'frontend_stop_command',
                    'reason': 'Stopped by frontend'
                })
                _redis_json_set('trading_settings', trading_settings)
                
                # Session beenden
                current_autotrading_session = {'session_id': None, 'active': False}
                
                # Status Feedback
                r.set('autotrading:backend_status', 'STOPPED')
                r.set('autotrading:stopped_at', datetime.utcnow().isoformat())
                r.delete('autotrading:session_active')
                
                logging.info("AutoTrading DEACTIVATED by frontend")
                return {'status': 'deactivated'}
        
        # Kein Command gefunden - Status beibehalten
        return {'status': 'monitoring'}
        
    except Exception as e:
        logging.error(f"Frontend Redis monitoring error: {e}")
        r.set('autotrading:backend_status', 'ERROR')
        r.set('autotrading:error', str(e))
        return {'status': 'error', 'error': str(e)}

def update_frontend_feedback():
    """
    Schreibt aktuellen Trading-Status zurück an Frontend über Redis
    """
    try:
        # Trading Status
        trading_status = _redis_json_get('trading_status', {}) or {}
        portfolio_positions = _redis_json_get('portfolio_positions', []) or []
        trades_log = _redis_json_get('trades_log', []) or []
        
        # Backend Status Update
        if current_autotrading_session['active']:
            r.set('autotrading:backend_status', 'RUNNING')
            r.set('autotrading:last_update', datetime.utcnow().isoformat())
            
            # Letzter Trade
            if trades_log:
                latest_trade = trades_log[-1]  # Neuester Trade
                r.set('autotrading:last_trade', json.dumps(latest_trade))
            
            # Aktive Positionen
            r.set('autotrading:active_positions', json.dumps(portfolio_positions))
            
            # Trading Stats
            trading_stats = {
                'trades_today': trading_status.get('trades_today', 0),
                'total_volume': trading_status.get('total_volume', 0.0),
                'last_run': trading_status.get('last_run'),
                'next_run': trading_status.get('next_run'),
                'positions_count': len(portfolio_positions)
            }
            r.set('autotrading:stats', json.dumps(trading_stats))
            
        return {'status': 'updated'}
            
    except Exception as e:
        logging.error(f"Frontend feedback update error: {e}")
        return {'status': 'error', 'error': str(e)}

@app.task
def monitor_autotrading_frontend():
    """
    Celery Task für kontinuierliches Frontend Redis Monitoring
    Läuft alle 5 Sekunden und überwacht autotrading:* Keys
    """
    try:
        # Frontend Commands überwachen
        command_result = monitor_frontend_redis_commands()
        
        # Status Feedback aktualisieren
        feedback_result = update_frontend_feedback()
        
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'command_monitoring': command_result,
            'feedback_update': feedback_result,
            'current_session': current_autotrading_session
        }
        
    except Exception as e:
        logging.error(f"AutoTrading frontend monitoring failed: {e}")
        return {'status': 'error', 'error': str(e)}



# ===== Sequential Training System =====

@app.task
def train_sequential(tickers=None):
    """
    Sequenzielles Training: Ein Ticker nach dem anderen
    Speichert Fortschritt in Redis für Frontend-Monitoring
    """
    import sys
    sys.path.insert(0, '/app')
    
    try:
        import worker_sequential_training
        return worker_sequential_training.train_sequential_task(tickers=tickers)
        
    except Exception as e:
        logging.error(f"❌ Sequential training failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat()
        }


@app.task
def check_training_commands():
    """
    Überwacht Redis auf manuelle Training-Commands vom Frontend
    Wird regelmäßig durch Celery Beat aufgerufen
    """
    try:
        command = r.get("training:command")
        
        # Redis gibt bytes zurück, convert zu string
        if command:
            command = command.decode('utf-8') if isinstance(command, bytes) else command
        
        if command == "start":
            logging.info("🚀 Manual training command detected from frontend")
            
            # Command löschen damit er nicht mehrfach getriggert wird
            r.delete("training:command")
            
            # Training starten
            train_sequential.delay()
            
            return {"status": "training_started", "timestamp": datetime.now().isoformat()}
        
        return {"status": "no_command"}
        
    except Exception as e:
        logging.error(f"❌ Error checking training commands: {e}")
        return {"status": "error", "message": str(e)}

