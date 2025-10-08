import os, time, json, logging, redis, requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import concurrent.futures
from threading import Lock

load_dotenv()
logging.basicConfig(level=logging.INFO, format='[multi-api-enhanced] %(asctime)s %(levelname)s %(message)s')

REDIS_URL = os.getenv('REDIS_URL', 'redis://:pass123@redis:6379/0')
INTERVAL = int(os.getenv('MULTI_API_INTERVAL','300'))  # 5 Minuten zwischen Läufen

# API Keys
FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY')
FMP_API_KEY = os.getenv('FMP_API_KEY')
MARKETSTACK_API_KEY = os.getenv('MARKETSTACK_API_KEY')
TWELVE_DATA_API_KEY = os.getenv('TWELVE_DATA_API_KEY')

r = redis.from_url(REDIS_URL)
rate_limit_lock = Lock()

def get_tickers():
    """Hole aktuelle Ticker Liste aus Redis dynamic_tickers"""
    try:
        dyn_raw = r.get('dynamic_tickers')
        if dyn_raw:
            return json.loads(dyn_raw)
    except Exception as e:
        logging.error(f"Error getting tickers: {e}")
    return ['AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','NFLX','CRM','ORCL']

def fetch_finnhub_batch(tickers):
    """Fetch batch data from Finnhub API"""
    results = {}
    if not FINNHUB_API_KEY:
        return results
        
    for ticker in tickers:
        try:
            # Rate limiting
            with rate_limit_lock:
                time.sleep(0.2)  # 5 calls per second max
            
            # Real-time quote
            url = f'https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}'
            resp = requests.get(url, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get('c'):  # Current price exists
                    results[ticker] = {
                        'source': 'finnhub',
                        'price': data.get('c'),
                        'open': data.get('o'),
                        'high': data.get('h'),
                        'low': data.get('l'),
                        'change': data.get('d'),
                        'change_pct': data.get('dp'),
                        'volume': data.get('v', 0),
                        'timestamp': datetime.utcnow().isoformat()
                    }
            
        except Exception as e:
            logging.warning(f"Finnhub error for {ticker}: {e}")
    
    return results

def fetch_fmp_batch(tickers):
    """Fetch batch data from Financial Modeling Prep API"""
    results = {}
    if not FMP_API_KEY:
        return results
        
    try:
        # FMP supports batch requests
        symbols = ','.join(tickers[:50])  # Limit to 50 symbols per request
        url = f'https://financialmodelingprep.com/api/v3/quote/{symbols}?apikey={FMP_API_KEY}'
        
        resp = requests.get(url, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                for item in data:
                    ticker = item.get('symbol')
                    if ticker and item.get('price'):
                        results[ticker] = {
                            'source': 'fmp',
                            'price': item.get('price'),
                            'open': item.get('open'),
                            'high': item.get('dayHigh'),
                            'low': item.get('dayLow'),
                            'change': item.get('change'),
                            'change_pct': item.get('changesPercentage'),
                            'volume': item.get('volume', 0),
                            'market_cap': item.get('marketCap'),
                            'pe_ratio': item.get('pe'),
                            'timestamp': datetime.utcnow().isoformat()
                        }
        
    except Exception as e:
        logging.warning(f"FMP batch error: {e}")
    
    return results

def fetch_marketstack_batch(tickers):
    """Fetch batch data from Marketstack API"""
    results = {}
    if not MARKETSTACK_API_KEY:
        return results
        
    try:
        # Marketstack supports up to 100 symbols per request
        symbols = ','.join(tickers[:100])
        url = f'http://api.marketstack.com/v1/eod/latest?access_key={MARKETSTACK_API_KEY}&symbols={symbols}'
        
        resp = requests.get(url, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get('data'):
                for item in data['data']:
                    ticker = item.get('symbol')
                    if ticker and item.get('close'):
                        results[ticker] = {
                            'source': 'marketstack',
                            'price': item.get('close'),
                            'open': item.get('open'),
                            'high': item.get('high'),
                            'low': item.get('low'),
                            'change': None,
                            'change_pct': None,
                            'volume': item.get('volume', 0),
                            'date': item.get('date'),
                            'timestamp': datetime.utcnow().isoformat()
                        }
        
    except Exception as e:
        logging.warning(f"Marketstack batch error: {e}")
    
    return results

def fetch_multi_api_data():
    """Parallel fetch from multiple APIs"""
    tickers = get_tickers()
    logging.info(f"Starting multi-API data collection for {len(tickers)} tickers")
    
    all_results = {}
    api_stats = {
        'finnhub': {'success': 0, 'errors': 0},
        'fmp': {'success': 0, 'errors': 0},
        'marketstack': {'success': 0, 'errors': 0},
        'total_tickers': len(tickers)
    }
    
    # Parallel API calls
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(fetch_finnhub_batch, tickers): 'finnhub',
            executor.submit(fetch_fmp_batch, tickers): 'fmp',
            executor.submit(fetch_marketstack_batch, tickers): 'marketstack'
        }
        
        for future in concurrent.futures.as_completed(futures):
            api_name = futures[future]
            try:
                results = future.result()
                api_stats[api_name]['success'] = len(results)
                
                # Merge results
                for ticker, data in results.items():
                    if ticker not in all_results:
                        all_results[ticker] = []
                    all_results[ticker].append(data)
                    
                logging.info(f"✅ {api_name}: {len(results)} tickers")
                
            except Exception as e:
                api_stats[api_name]['errors'] = 1
                logging.error(f"❌ {api_name}: {e}")
    
    # Process and aggregate results
    aggregated_data = {}
    for ticker, sources in all_results.items():
        if not sources:
            continue
            
        # Priority: FMP > Finnhub > Marketstack
        primary = None
        for source_priority in ['fmp', 'finnhub', 'marketstack']:
            primary = next((s for s in sources if s['source'] == source_priority), None)
            if primary:
                break
        
        if primary:
            # Calculate price consensus if multiple sources
            prices = [s['price'] for s in sources if s.get('price')]
            consensus_price = sum(prices) / len(prices) if prices else primary['price']
            
            aggregated_data[ticker] = {
                'price': consensus_price,
                'open': primary.get('open'),
                'high': primary.get('high'),
                'low': primary.get('low'),
                'change': primary.get('change'),
                'change_pct': primary.get('change_pct'),
                'volume': primary.get('volume', 0),
                'primary_source': primary['source'],
                'sources_count': len(sources),
                'sources_used': [s['source'] for s in sources],
                'market_cap': primary.get('market_cap'),
                'pe_ratio': primary.get('pe_ratio'),
                'timestamp': datetime.utcnow().isoformat()
            }
    
    # Store results in Redis
    r.set('multi_api_enhanced_data', json.dumps(aggregated_data))
    
    # Store API statistics
    api_stats['timestamp'] = datetime.utcnow().isoformat()
    api_stats['tickers_with_data'] = len(aggregated_data)
    api_stats['coverage_pct'] = round((len(aggregated_data) / len(tickers)) * 100, 1) if tickers else 0
    
    r.set('multi_api_enhanced_stats', json.dumps(api_stats))
    
    logging.info(f"Multi-API Enhanced: {len(aggregated_data)}/{len(tickers)} tickers ({api_stats['coverage_pct']}% coverage)")
    
    return {
        'tickers_processed': len(tickers),
        'tickers_with_data': len(aggregated_data),
        'api_stats': api_stats
    }

def main():
    """Main service loop"""
    logging.info("Multi-API Enhanced Data Service starting...")
    
    while True:
        start_time = time.time()
        
        try:
            result = fetch_multi_api_data()
            logging.info(f"Cycle complete: {result['tickers_with_data']}/{result['tickers_processed']} tickers")
            
        except Exception as e:
            logging.error(f"Error in main loop: {e}")
        
        # Calculate sleep time
        elapsed = time.time() - start_time
        sleep_time = max(60, INTERVAL - elapsed)
        
        logging.info(f"Sleeping for {sleep_time:.0f} seconds until next cycle...")
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()