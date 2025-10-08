import os, time, json, logging, redis, yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
import numpy as np

load_dotenv()
logging.basicConfig(level=logging.INFO, format='[yfinance-enhanced] %(asctime)s %(levelname)s %(message)s')

REDIS_URL = os.getenv('REDIS_URL', 'redis://:pass123@redis:6379/0')
INTERVAL = int(os.getenv('YF_ENHANCED_INTERVAL','300'))  # 5 Minuten zwischen Läufen
HISTORY_DAYS = int(os.getenv('YF_HISTORY_DAYS','365'))  # 1 Jahr historische Daten

r = redis.from_url(REDIS_URL)

def get_tickers():
    """Hole aktuelle Ticker Liste aus Redis dynamic_tickers"""
    try:
        dyn_raw = r.get('dynamic_tickers')
        if dyn_raw:
            return json.loads(dyn_raw)
    except Exception as e:
        logging.error(f"Error getting tickers: {e}")
    return ['AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','NFLX','CRM','ORCL']

def fetch_historical_data(ticker, period='1y'):
    """Fetch comprehensive historical data for ML training with robust error handling"""
    try:
        stock = yf.Ticker(ticker)
        
        # 1. Historische OHLCV Daten mit Retry Logic
        hist = None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                hist = stock.history(period=period, interval='1d')
                if not hist.empty:
                    break
                time.sleep(2 ** attempt)  # Exponential backoff
            except Exception as e:
                logging.warning(f"Attempt {attempt + 1} failed for {ticker}: {e}")
                if attempt == max_retries - 1:
                    return None
                time.sleep(5 * (attempt + 1))  # Progressive delay
        
        if hist is None or hist.empty:
            logging.warning(f"No historical data for {ticker}")
            return None
            
        # 2. Fundamentals (mit Rate Limiting und Fallback)
        info = {'fundamentals': {}}
        try:
            # Rate limiting für info API
            time.sleep(2)  # 2 seconds between info calls
            
            stock_info = stock.info
            if stock_info and isinstance(stock_info, dict):
                # Wichtige Fundamentals für ML
                fundamentals = {
                    'market_cap': stock_info.get('marketCap'),
                    'pe_ratio': stock_info.get('trailingPE'),
                    'peg_ratio': stock_info.get('pegRatio'),
                    'price_to_book': stock_info.get('priceToBook'),
                    'revenue_growth': stock_info.get('revenueGrowth'),
                    'profit_margin': stock_info.get('profitMargins'),
                    'operating_margin': stock_info.get('operatingMargins'),
                    'return_on_equity': stock_info.get('returnOnEquity'),
                    'debt_to_equity': stock_info.get('debtToEquity'),
                    'current_ratio': stock_info.get('currentRatio'),
                    'beta': stock_info.get('beta'),
                    'fifty_two_week_high': stock_info.get('fiftyTwoWeekHigh'),
                    'fifty_two_week_low': stock_info.get('fiftyTwoWeekLow'),
                    'dividend_yield': stock_info.get('dividendYield'),
                    'sector': stock_info.get('sector'),
                    'industry': stock_info.get('industry')
                }
                info['fundamentals'] = fundamentals
                logging.info(f"✅ {ticker}: Fundamentals fetched")
            else:
                logging.warning(f"⚠️ {ticker}: Empty stock info")
        except Exception as e:
            logging.warning(f"❌ {ticker}: Fundamentals failed: {e}")
            # Skip fundamentals but continue with historical data
        
        # 3. News (mit Fallback und Rate Limiting)
        info['news'] = []
        try:
            # Rate limiting für news API
            time.sleep(1)
            
            news = stock.news[:5] if hasattr(stock, 'news') and stock.news else []  # Reduziert auf 5
            news_data = []
            for article in news:
                if isinstance(article, dict):
                    news_data.append({
                        'title': article.get('title', '')[:200],  # Titel begrenzen
                        'publisher': article.get('publisher', ''),
                        'published': datetime.fromtimestamp(article.get('providerPublishTime', 0)).isoformat() if article.get('providerPublishTime') else None,
                        'sentiment': 0.5  # Neutral default
                    })
            info['news'] = news_data
            logging.info(f"📰 {ticker}: {len(news_data)} news articles")
        except Exception as e:
            logging.warning(f"❌ {ticker}: News failed: {e}")
            # Continue without news
        
        # 4. Technical Indicators berechnen
        try:
            # Simple Moving Averages
            hist['SMA_20'] = hist['Close'].rolling(window=20).mean()
            hist['SMA_50'] = hist['Close'].rolling(window=50).mean()
            hist['SMA_200'] = hist['Close'].rolling(window=200).mean()
            
            # RSI (Relative Strength Index)
            delta = hist['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            hist['RSI'] = 100 - (100 / (1 + rs))
            
            # MACD
            exp1 = hist['Close'].ewm(span=12).mean()
            exp2 = hist['Close'].ewm(span=26).mean()
            hist['MACD'] = exp1 - exp2
            hist['MACD_Signal'] = hist['MACD'].ewm(span=9).mean()
            hist['MACD_Histogram'] = hist['MACD'] - hist['MACD_Signal']
            
            # Bollinger Bands
            hist['BB_Middle'] = hist['Close'].rolling(window=20).mean()
            bb_std = hist['Close'].rolling(window=20).std()
            hist['BB_Upper'] = hist['BB_Middle'] + (bb_std * 2)
            hist['BB_Lower'] = hist['BB_Middle'] - (bb_std * 2)
            
            # Volume indicators
            hist['Volume_SMA'] = hist['Volume'].rolling(window=20).mean()
            hist['Volume_Ratio'] = hist['Volume'] / hist['Volume_SMA']
            
        except Exception as e:
            logging.warning(f"Could not calculate technical indicators for {ticker}: {e}")
        
        # 5. Prepare ML features
        ml_features = []
        for idx, row in hist.iterrows():
            if pd.isna(row['Close']):
                continue
                
            feature_row = {
                'date': idx.strftime('%Y-%m-%d'),
                'ticker': ticker,
                'open': float(row['Open']) if not pd.isna(row['Open']) else None,
                'high': float(row['High']) if not pd.isna(row['High']) else None,
                'low': float(row['Low']) if not pd.isna(row['Low']) else None,
                'close': float(row['Close']),
                'volume': int(row['Volume']) if not pd.isna(row['Volume']) else 0,
                'sma_20': float(row['SMA_20']) if not pd.isna(row['SMA_20']) else None,
                'sma_50': float(row['SMA_50']) if not pd.isna(row['SMA_50']) else None,
                'sma_200': float(row['SMA_200']) if not pd.isna(row['SMA_200']) else None,
                'rsi': float(row['RSI']) if not pd.isna(row['RSI']) else None,
                'macd': float(row['MACD']) if not pd.isna(row['MACD']) else None,
                'macd_signal': float(row['MACD_Signal']) if not pd.isna(row['MACD_Signal']) else None,
                'bb_upper': float(row['BB_Upper']) if not pd.isna(row['BB_Upper']) else None,
                'bb_lower': float(row['BB_Lower']) if not pd.isna(row['BB_Lower']) else None,
                'volume_ratio': float(row['Volume_Ratio']) if not pd.isna(row['Volume_Ratio']) else None
            }
            ml_features.append(feature_row)
        
        return {
            'ticker': ticker,
            'timestamp': datetime.utcnow().isoformat(),
            'historical_data': ml_features,
            'fundamentals': info['fundamentals'],
            'news': info['news'],
            'data_points': len(ml_features)
        }
        
    except Exception as e:
        logging.error(f"Error fetching data for {ticker}: {e}")
        return None

def update_redis_data():
    """Update Redis with enhanced YFinance data"""
    tickers = get_tickers()
    logging.info(f"Starting enhanced YFinance data collection for {len(tickers)} tickers")
    
    success_count = 0
    error_count = 0
    
    for ticker in tickers:
        try:
            data = fetch_historical_data(ticker)
            if data:
                # Store individual ticker data
                r.set(f'yfinance_enhanced:{ticker}', json.dumps(data))
                success_count += 1
                logging.info(f"✅ {ticker}: {data['data_points']} data points, {len(data['news'])} news articles")
            else:
                error_count += 1
                logging.warning(f"❌ {ticker}: No data fetched")
                
        except Exception as e:
            error_count += 1
            logging.error(f"❌ {ticker}: Error {e}")
        
        # Aggressive rate limiting to avoid 429 errors
        time.sleep(5)  # 5 seconds between tickers
    
    # Update status
    status = {
        'timestamp': datetime.utcnow().isoformat(),
        'tickers_processed': len(tickers),
        'success_count': success_count,
        'error_count': error_count,
        'next_update': (datetime.utcnow() + timedelta(seconds=INTERVAL)).isoformat()
    }
    r.set('yfinance_enhanced_status', json.dumps(status))
    
    logging.info(f"Enhanced YFinance update complete: {success_count} success, {error_count} errors")

def main():
    """Main service loop"""
    logging.info("YFinance Enhanced Data Service starting...")
    
    while True:
        start_time = time.time()
        
        try:
            update_redis_data()
        except Exception as e:
            logging.error(f"Error in main loop: {e}")
        
        # Calculate sleep time
        elapsed = time.time() - start_time
        sleep_time = max(60, INTERVAL - elapsed)
        
        logging.info(f"Sleeping for {sleep_time:.0f} seconds until next update...")
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()