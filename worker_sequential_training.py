"""
Sequential Training System for QBot
Trainiert ML-Modelle Ticker für Ticker mit Frontend-Monitoring
"""

import os
import json
import logging
import redis
import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from autogluon.tabular import TabularPredictor, TabularDataset
from celery import Celery

# Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv('REDIS_URL', 'redis://:pass123@redis:6379/0')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:pass123@qbot-timescaledb-1:5432/qbot')

# Redis Connection
r = redis.from_url(REDIS_URL, decode_responses=True)


class SequentialTrainer:
    """Sequenzieller Ticker-für-Ticker ML-Trainer"""
    
    def __init__(self):
        self.horizons = [15, 30, 60]
        self.min_rows = int(os.getenv('TRAIN_MIN_ROWS', '150'))
        self.time_budget_per_model = 160  # Sekunden pro Modell
        self.lookback_days = int(os.getenv('TRAIN_LOOKBACK_DAYS', '30'))  # Erhöht von 14 auf 30 Tage für mehr Daten!
        
    def get_training_tickers(self):
        """
        Hole Ticker nach Priorität:
        1. Portfolio Positionen (wichtigste)
        2. Grok Top Candidates
        3. Deduplizieren
        """
        tickers = []
        
        # 1. Portfolio Ticker
        try:
            # Versuche zuerst portfolio_positions (aktuelles Format)
            positions_data = r.get("portfolio_positions")
            if positions_data:
                portfolio = json.loads(positions_data)
                # Portfolio ist direkt ein Array
                if isinstance(portfolio, list):
                    portfolio_tickers = [p['ticker'] for p in portfolio]
                else:
                    # Fallback auf dict mit 'positions' key
                    portfolio_tickers = [p['ticker'] for p in portfolio.get('positions', [])]
                tickers.extend(portfolio_tickers)
                logger.info(f"📊 Portfolio Ticker: {len(portfolio_tickers)} - {portfolio_tickers}")
        except Exception as e:
            logger.error(f"Fehler beim Laden von Portfolio Tickern: {e}")
        
        # 2. Grok Kandidaten
        try:
            grok_data = r.get("grok:top_stocks")
            if grok_data:
                grok_stocks = json.loads(grok_data)
                grok_tickers = [s['ticker'] for s in grok_stocks]
                tickers.extend(grok_tickers)
                logger.info(f"🤖 Grok Kandidaten: {len(grok_tickers)}")
        except Exception as e:
            logger.error(f"Fehler beim Laden von Grok Tickern: {e}")
        
        # Deduplizieren, Portfolio-Ticker zuerst
        unique_tickers = []
        seen = set()
        for ticker in tickers:
            if ticker not in seen:
                unique_tickers.append(ticker)
                seen.add(ticker)
        
        logger.info(f"🎯 Gesamt Unique Ticker: {len(unique_tickers)}")
        return unique_tickers
    
    def check_ticker_data_availability(self, ticker):
        """
        Prüft ob genug Daten für Ticker verfügbar sind
        Returns: (has_enough_data, row_count)
        """
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            
            cur.execute("""
                SELECT COUNT(*) 
                FROM market_data 
                WHERE ticker = %s 
                AND time >= NOW() - INTERVAL '14 days'
            """, (ticker,))
            
            row_count = cur.fetchone()[0]
            conn.close()
            
            has_enough = row_count >= self.min_rows
            return has_enough, row_count
            
        except Exception as e:
            logger.error(f"Fehler beim Prüfen von {ticker}: {e}")
            return False, 0
    
    def load_ticker_data(self, ticker):
        """
        Lädt Trainingsdaten für einen Ticker inkl. Grok Features (optional)
        """
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            
            # Prüfe ob Grok-Tabellen existieren
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'grok_deepersearch'
                )
            """)
            has_deepersearch = cur.fetchone()[0]
            
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'grok_topstocks'
                )
            """)
            has_topstocks = cur.fetchone()[0]
            
            # Base Query ohne Grok Features
            if not has_deepersearch or not has_topstocks:
                logger.info(f"Training {ticker} ohne Grok Features (Tabellen fehlen)")
                query = """
                    SELECT md.ticker, md.time, md.open, md.high, md.low, md.close, md.volume,
                           LAG(md.close, 1) OVER (PARTITION BY md.ticker ORDER BY md.time) as prev_close,
                           LAG(md.close, 5) OVER (PARTITION BY md.ticker ORDER BY md.time) as prev_close_5,
                           LAG(md.close, 15) OVER (PARTITION BY md.ticker ORDER BY md.time) as prev_close_15,
                           0.0 AS grok_sentiment,
                           0.0 AS grok_expected_gain
                    FROM market_data md
                    WHERE md.ticker = %s 
                    AND md.time >= NOW() - INTERVAL '%s days'
                    ORDER BY md.time
                """
            else:
                # Query MIT Grok Features
                query = """
                    SELECT md.ticker, md.time, md.open, md.high, md.low, md.close, md.volume,
                           LAG(md.close, 1) OVER (PARTITION BY md.ticker ORDER BY md.time) as prev_close,
                           LAG(md.close, 5) OVER (PARTITION BY md.ticker ORDER BY md.time) as prev_close_5,
                           LAG(md.close, 15) OVER (PARTITION BY md.ticker ORDER BY md.time) as prev_close_15,
                           COALESCE(ds.sentiment, 0.0) AS grok_sentiment,
                           COALESCE(ts.expected_gain, 0.0) AS grok_expected_gain
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
                    WHERE md.ticker = %s 
                    AND md.time >= NOW() - INTERVAL '%s days'
                    ORDER BY md.time
                """
            
            df = pd.read_sql(query, conn, params=(ticker, self.lookback_days))
            conn.close()
            
            if len(df) == 0:
                logger.warning(f"Keine Daten für {ticker}")
                return None
            
            return df
            
        except Exception as e:
            logger.error(f"Fehler beim Laden von {ticker}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def prepare_features(self, df):
        """Feature Engineering für Training"""
        
        # Price Changes
        df['price_change'] = df['close'] - df['prev_close']
        df['price_change_5'] = df['close'] - df['prev_close_5']
        df['price_change_15'] = df['close'] - df['prev_close_15']
        
        # Volatility
        df['volatility'] = (df['high'] - df['low']) / df['close']
        
        # Time Features
        df['hour'] = pd.to_datetime(df['time']).dt.hour
        df['day_of_week'] = pd.to_datetime(df['time']).dt.dayofweek
        
        # Targets für alle Horizonte
        df['target_15'] = df['close'].shift(-1)   # 15min ahead
        df['target_30'] = df['close'].shift(-2)   # 30min ahead
        df['target_60'] = df['close'].shift(-4)   # 60min ahead
        
        # Grok Features Imputation
        for col in ['grok_sentiment', 'grok_expected_gain']:
            if col in df.columns:
                median_val = df[col].median() if not df[col].dropna().empty else 0.0
                df[f'{col}_missing'] = df[col].isna().astype(int)
                df[col] = df[col].fillna(median_val)
        
        # Clean data
        df_clean = df.dropna(subset=['target_15', 'target_30', 'target_60']).copy()
        
        return df_clean
    
    def train_single_ticker(self, ticker):
        """
        Trainiert alle 3 Horizonte für einen Ticker
        Returns: dict mit Ergebnissen
        """
        result = {
            'ticker': ticker,
            'status': 'unknown',
            'models': {},
            'errors': []
        }
        
        try:
            # 1. Daten prüfen
            has_data, row_count = self.check_ticker_data_availability(ticker)
            if not has_data:
                result['status'] = 'insufficient_data'
                result['error'] = f'Only {row_count} rows (need {self.min_rows})'
                logger.warning(f"⚠️  {ticker}: Zu wenig Daten ({row_count}/{self.min_rows})")
                return result
            
            # 2. Daten laden
            df = self.load_ticker_data(ticker)
            if df is None or len(df) < self.min_rows:
                result['status'] = 'load_failed'
                result['error'] = 'Failed to load data'
                return result
            
            # 3. Features vorbereiten
            df_clean = self.prepare_features(df)
            
            if len(df_clean) < 100:
                result['status'] = 'insufficient_clean_data'
                result['error'] = f'Only {len(df_clean)} clean rows'
                return result
            
            # 4. Features extrahieren
            feature_cols = [c for c in df_clean.columns 
                           if c not in ['time', 'ticker', 'target_15', 'target_30', 'target_60']]
            
            # 5. Alle 3 Horizonte trainieren
            horizons = {
                '15': 'target_15',
                '30': 'target_30',
                '60': 'target_60'
            }
            
            for horizon_idx, (horizon_name, target_col) in enumerate(horizons.items(), 1):
                try:
                    logger.info(f"  ⏳ Training {ticker} - {horizon_name}min Horizon ({horizon_idx}/3)...")
                    
                    # Status Update: Welcher Horizon läuft gerade
                    current_status = r.get("training:status")
                    if current_status:
                        status_dict = json.loads(current_status)
                        status_dict['current_horizon'] = int(horizon_name)
                        r.set("training:status", json.dumps(status_dict))
                    
                    # Training Data vorbereiten
                    train_df = df_clean[feature_cols + [target_col]].rename(
                        columns={target_col: 'target'}
                    )
                    
                    # AutoGluon Training
                    model_path = f'/app/models/autogluon_model_{ticker}_{horizon_name}'
                    
                    predictor = TabularPredictor(
                        label='target',
                        path=model_path,
                        eval_metric='mean_absolute_error'
                    )
                    
                    predictor.fit(
                        TabularDataset(train_df),
                        time_limit=self.time_budget_per_model,
                        verbosity=2  # 0=silent, 2=normal, 3=detailed, 4=debug
                    )
                    
                    # Metriken berechnen
                    y_true = train_df['target']
                    y_pred = predictor.predict(train_df.drop('target', axis=1))
                    
                    mae = float(np.mean(np.abs(y_true - y_pred)))
                    
                    with np.errstate(divide='ignore', invalid='ignore'):
                        mape = float(np.mean(np.abs((y_true - y_pred) / np.where(y_true==0, np.nan, y_true))))
                    
                    ss_res = float(((y_true - y_pred)**2).sum())
                    ss_tot = float(((y_true - y_true.mean())**2).sum())
                    r2 = 1 - ss_res/ss_tot if ss_tot else None
                    
                    result['models'][horizon_name] = {
                        'status': 'success',
                        'mae': mae,
                        'mape': mape,
                        'r2': r2,
                        'rows': len(train_df),
                        'model_path': model_path
                    }
                    
                    logger.info(f"  ✅ {ticker} - {horizon_name}min: MAE={mae:.4f}, R²={r2:.4f}")
                    
                    # Status Update: Model Counter erhöhen nach jedem erfolgreichen Horizon
                    current_status = r.get("training:status")
                    if current_status:
                        status_dict = json.loads(current_status)
                        status_dict['completed_models'] = status_dict.get('completed_models', 0) + 1
                        # Progress Percent neu berechnen
                        total_models = status_dict.get('total_models', 33)
                        status_dict['progress_percent'] = int((status_dict['completed_models'] / total_models) * 100)
                        r.set("training:status", json.dumps(status_dict))
                        logger.info(f"  📊 Progress: {status_dict['completed_models']}/{total_models} ({status_dict['progress_percent']}%)")
                    
                except Exception as e:
                    error_msg = f"{horizon_name}min: {str(e)}"
                    result['errors'].append(error_msg)
                    result['models'][horizon_name] = {
                        'status': 'failed',
                        'error': str(e)
                    }
                    logger.error(f"  ❌ {ticker} - {horizon_name}min: {e}")
            
            # Status setzen
            successful_models = sum(1 for m in result['models'].values() if m.get('status') == 'success')
            if successful_models == 3:
                result['status'] = 'success'
            elif successful_models > 0:
                result['status'] = 'partial_success'
            else:
                result['status'] = 'failed'
            
            return result
            
        except Exception as e:
            result['status'] = 'exception'
            result['error'] = str(e)
            logger.error(f"❌ Unerwarteter Fehler bei {ticker}: {e}")
            return result
    
    def update_training_status(self, status_data):
        """Speichert Training-Status in Redis"""
        try:
            r.setex(
                "training:status",
                3600,  # 1 Stunde TTL
                json.dumps(status_data, default=str)
            )
        except Exception as e:
            logger.error(f"Fehler beim Speichern von Training-Status: {e}")
    
    def run_sequential_training(self, tickers=None):
        """
        Hauptfunktion: Trainiert alle Ticker sequenziell
        """
        logger.info("🚀 Starte Sequential Training")
        
        # Ticker bestimmen
        if tickers is None:
            tickers = self.get_training_tickers()
        
        if not tickers:
            logger.warning("Keine Ticker für Training gefunden!")
            return {
                'status': 'error',
                'message': 'No tickers found'
            }
        
        total_models = len(tickers) * len(self.horizons)
        
        # Initial Status
        status = {
            'status': 'running',
            'started_at': datetime.now().isoformat(),
            'total_tickers': len(tickers),
            'total_models': total_models,
            'current_ticker': None,
            'current_horizon': None,
            'completed_tickers': [],
            'completed_models': 0,
            'progress_percent': 0,
            'errors': [],
            'ticker_results': {}
        }
        
        self.update_training_status(status)
        
        logger.info(f"📊 Training {len(tickers)} Ticker mit {len(self.horizons)} Horizonten = {total_models} Modelle")
        
        # Sequenzielles Training
        for idx, ticker in enumerate(tickers, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"📈 Ticker {idx}/{len(tickers)}: {ticker}")
            logger.info(f"{'='*60}")
            
            # Status Update: Ticker startet
            status['current_ticker'] = ticker
            status['current_horizon'] = 15  # Startet mit 15min
            self.update_training_status(status)
            
            # Ticker trainieren
            ticker_result = self.train_single_ticker(ticker)
            
            # Ergebnisse speichern
            status['ticker_results'][ticker] = ticker_result
            
            if ticker_result['status'] in ['success', 'partial_success']:
                status['completed_tickers'].append(ticker)
                successful_models = sum(
                    1 for m in ticker_result['models'].values() 
                    if m.get('status') == 'success'
                )
                status['completed_models'] += successful_models
            
            # Fehler sammeln
            if ticker_result.get('errors'):
                for error in ticker_result['errors']:
                    status['errors'].append(f"{ticker}: {error}")
            
            # Progress Update
            status['progress_percent'] = int((idx / len(tickers)) * 100)
            self.update_training_status(status)
            
            logger.info(f"✅ {ticker} abgeschlossen ({idx}/{len(tickers)})")
        
        # Training abgeschlossen
        status['status'] = 'completed'
        status['completed_at'] = datetime.now().isoformat()
        status['current_ticker'] = None
        status['current_horizon'] = None
        status['progress_percent'] = 100
        
        self.update_training_status(status)
        
        logger.info(f"\n{'='*60}")
        logger.info(f"🎉 Training abgeschlossen!")
        logger.info(f"✅ Ticker erfolgreich: {len(status['completed_tickers'])}/{len(tickers)}")
        logger.info(f"📊 Modelle trainiert: {status['completed_models']}/{total_models}")
        logger.info(f"❌ Fehler: {len(status['errors'])}")
        logger.info(f"{'='*60}\n")
        
        return status


# Celery Task Wrapper
def train_sequential_task(tickers=None):
    """Celery Task für sequenzielles Training"""
    trainer = SequentialTrainer()
    return trainer.run_sequential_training(tickers=tickers)


if __name__ == "__main__":
    # Für direktes Testing
    trainer = SequentialTrainer()
    result = trainer.run_sequential_training()
    print(json.dumps(result, indent=2, default=str))
