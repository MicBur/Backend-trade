-- ============================================
-- TimescaleDB Initialisierung für Trading Bot
-- ============================================

-- TimescaleDB Extension aktivieren
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================
-- 📊 HYPERTABLES (Time-Series optimiert)
-- ============================================

-- Market Data (OHLCV) - HAUPTTABELLE
CREATE TABLE IF NOT EXISTS market_data (
    time TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume BIGINT,
    UNIQUE(time, ticker)  -- Für ON CONFLICT in INSERTs
);

-- Convert to Hypertable (automatische Zeit-Partitionierung)
SELECT create_hypertable('market_data', 'time', 
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Compound Index für schnelle Ticker-Abfragen
CREATE INDEX IF NOT EXISTS idx_market_data_ticker_time 
    ON market_data (ticker, time DESC);

-- Compression Policy (nach 7 Tagen komprimieren = 90% weniger Speicher)
ALTER TABLE market_data SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'ticker',
    timescaledb.compress_orderby = 'time DESC'
);

SELECT add_compression_policy('market_data', INTERVAL '7 days');

-- Retention Policy (Optional: Daten älter als 1 Jahr löschen)
-- SELECT add_retention_policy('market_data', INTERVAL '1 year');


-- ============================================
-- 🤖 ML Predictions Hypertable
-- ============================================

CREATE TABLE IF NOT EXISTS predictions (
    time TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    horizon INT NOT NULL,  -- 15, 30, 60 min
    predicted_price DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    model_version TEXT
);

SELECT create_hypertable('predictions', 'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_predictions_ticker_time 
    ON predictions (ticker, time DESC);

-- Compression nach 3 Tagen
ALTER TABLE predictions SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'ticker,horizon',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('predictions', INTERVAL '3 days');


-- ============================================
-- 💰 Portfolio Tracking Hypertables
-- ============================================

CREATE TABLE IF NOT EXISTS portfolio_equity (
    time TIMESTAMPTZ NOT NULL,
    equity_value DOUBLE PRECISION,
    cash DOUBLE PRECISION,
    buying_power DOUBLE PRECISION
);

SELECT create_hypertable('portfolio_equity', 'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_portfolio_equity_time 
    ON portfolio_equity (time DESC);


-- ============================================
-- 📊 Alpaca Account Snapshots
-- ============================================

CREATE TABLE IF NOT EXISTS alpaca_account (
    time TIMESTAMPTZ NOT NULL,
    portfolio_value DOUBLE PRECISION,
    buying_power DOUBLE PRECISION,
    equity DOUBLE PRECISION,
    day_trade_buying_power DOUBLE PRECISION,
    daytrade_count INT,
    trading_blocked BOOLEAN,
    account_blocked BOOLEAN,
    pattern_day_trader BOOLEAN
);

SELECT create_hypertable('alpaca_account', 'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_alpaca_account_time 
    ON alpaca_account (time DESC);


-- ============================================
-- 📍 Alpaca Positions History
-- ============================================

CREATE TABLE IF NOT EXISTS alpaca_positions (
    time TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    qty INT,
    avg_entry_price DOUBLE PRECISION,
    market_value DOUBLE PRECISION,
    unrealized_pl DOUBLE PRECISION,
    unrealized_pl_pct DOUBLE PRECISION
);

SELECT create_hypertable('alpaca_positions', 'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_alpaca_positions_symbol_time 
    ON alpaca_positions (symbol, time DESC);


-- ============================================
-- 🤖 Grok Recommendations
-- ============================================

CREATE TABLE IF NOT EXISTS grok_recommendations (
    time TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    score DOUBLE PRECISION,
    reason TEXT
);

SELECT create_hypertable('grok_recommendations', 'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_grok_recommendations_ticker_time 
    ON grok_recommendations (ticker, time DESC);


CREATE TABLE IF NOT EXISTS grok_deepersearch (
    time TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    sentiment DOUBLE PRECISION,
    explanation_de TEXT
);

SELECT create_hypertable('grok_deepersearch', 'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_grok_deepersearch_ticker_time 
    ON grok_deepersearch (ticker, time DESC);


CREATE TABLE IF NOT EXISTS grok_topstocks (
    time TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    expected_gain DOUBLE PRECISION,
    sentiment DOUBLE PRECISION,
    reason TEXT
);

SELECT create_hypertable('grok_topstocks', 'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_grok_topstocks_ticker_time 
    ON grok_topstocks (ticker, time DESC);


CREATE TABLE IF NOT EXISTS grok_health_log (
    time TIMESTAMPTZ NOT NULL,
    sdk_ok BOOLEAN,
    http_ok BOOLEAN,
    error TEXT
);

SELECT create_hypertable('grok_health_log', 'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_grok_health_log_time 
    ON grok_health_log (time DESC);


-- ============================================
-- 📦 NORMALE TABELLEN (keine Time-Series)
-- ============================================

-- Aktuelle Positionen (nur 1 Zeile pro Ticker)
CREATE TABLE IF NOT EXISTS portfolio_positions (
    ticker TEXT PRIMARY KEY,
    qty INT,
    avg_price DOUBLE PRECISION,
    side TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Aktive Orders
CREATE TABLE IF NOT EXISTS active_orders (
    id SERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    side TEXT,
    price DOUBLE PRECISION,
    status TEXT,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_active_orders_ticker_time 
    ON active_orders (ticker, timestamp);


-- Alpaca Orders
CREATE TABLE IF NOT EXISTS alpaca_orders (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT,
    qty INT,
    filled_qty INT,
    status TEXT,
    created_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_alpaca_orders_symbol_time 
    ON alpaca_orders (symbol, created_at);


-- Settings
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);


-- ============================================
-- 🚀 CONTINUOUS AGGREGATES (Materialized Views)
-- ============================================

-- 15-Min Candles aus 1-Min Daten (automatisch aktualisiert!)
CREATE MATERIALIZED VIEW IF NOT EXISTS market_data_15min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('15 minutes', time) AS bucket,
    ticker,
    FIRST(open, time) AS open,
    MAX(high) AS high,
    MIN(low) AS low,
    LAST(close, time) AS close,
    SUM(volume) AS volume
FROM market_data
GROUP BY bucket, ticker
WITH NO DATA;

-- Refresh Policy (alle 15 Minuten)
SELECT add_continuous_aggregate_policy('market_data_15min',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '15 minutes');


-- 1-Hour Candles
CREATE MATERIALIZED VIEW IF NOT EXISTS market_data_1hour
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    ticker,
    FIRST(open, time) AS open,
    MAX(high) AS high,
    MIN(low) AS low,
    LAST(close, time) AS close,
    SUM(volume) AS volume
FROM market_data
GROUP BY bucket, ticker
WITH NO DATA;

SELECT add_continuous_aggregate_policy('market_data_1hour',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 hour');


-- Daily Candles
CREATE MATERIALIZED VIEW IF NOT EXISTS market_data_1day
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    ticker,
    FIRST(open, time) AS open,
    MAX(high) AS high,
    MIN(low) AS low,
    LAST(close, time) AS close,
    SUM(volume) AS volume
FROM market_data
GROUP BY bucket, ticker
WITH NO DATA;

SELECT add_continuous_aggregate_policy('market_data_1day',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day');


-- ============================================
-- 📈 PERFORMANCE VIEWS
-- ============================================

-- Portfolio Performance (letzte 30 Tage)
CREATE OR REPLACE VIEW portfolio_performance_30d AS
SELECT
    time_bucket('1 hour', time) AS hour,
    AVG(equity_value) AS avg_equity,
    MAX(equity_value) AS max_equity,
    MIN(equity_value) AS min_equity
FROM portfolio_equity
WHERE time > NOW() - INTERVAL '30 days'
GROUP BY hour
ORDER BY hour DESC;


-- Top Gainers (heute)
CREATE OR REPLACE VIEW top_gainers_today AS
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
ORDER BY change_percent DESC
LIMIT 10;


-- ============================================
-- ✅ INITIAL DATA / WARMUP
-- ============================================

-- Refresh Continuous Aggregates einmalig (mit TimescaleDB Funktion)
-- (wird danach automatisch aktualisiert)
CALL refresh_continuous_aggregate('market_data_15min', NULL, NULL);
CALL refresh_continuous_aggregate('market_data_1hour', NULL, NULL);
CALL refresh_continuous_aggregate('market_data_1day', NULL, NULL);


-- ============================================
-- 📊 HILFSFUNKTIONEN
-- ============================================

-- Funktion: Hole OHLCV für beliebiges Timeframe
CREATE OR REPLACE FUNCTION get_ohlcv(
    p_ticker TEXT,
    p_timeframe TEXT,
    p_limit INT DEFAULT 100
)
RETURNS TABLE (
    time TIMESTAMPTZ,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume BIGINT
) AS $$
BEGIN
    CASE p_timeframe
        WHEN '15min' THEN
            RETURN QUERY
            SELECT bucket AS time, open, high, low, close, volume
            FROM market_data_15min
            WHERE ticker = p_ticker
            ORDER BY bucket DESC
            LIMIT p_limit;
        
        WHEN '1hour' THEN
            RETURN QUERY
            SELECT bucket AS time, open, high, low, close, volume
            FROM market_data_1hour
            WHERE ticker = p_ticker
            ORDER BY bucket DESC
            LIMIT p_limit;
        
        WHEN '1day' THEN
            RETURN QUERY
            SELECT bucket AS time, open, high, low, close, volume
            FROM market_data_1day
            WHERE ticker = p_ticker
            ORDER BY bucket DESC
            LIMIT p_limit;
        
        ELSE
            -- Fallback: Raw data mit time_bucket
            RETURN QUERY
            SELECT
                time_bucket(p_timeframe::INTERVAL, time) AS time,
                FIRST(market_data.open, market_data.time) AS open,
                MAX(market_data.high) AS high,
                MIN(market_data.low) AS low,
                LAST(market_data.close, market_data.time) AS close,
                SUM(market_data.volume) AS volume
            FROM market_data
            WHERE ticker = p_ticker
            GROUP BY time_bucket(p_timeframe::INTERVAL, market_data.time)
            ORDER BY time DESC
            LIMIT p_limit;
    END CASE;
END;
$$ LANGUAGE plpgsql;


-- ============================================
-- ✅ FERTIG!
-- ============================================

-- Zeige TimescaleDB Status
SELECT * FROM timescaledb_information.hypertables;

-- Zeige Continuous Aggregates
SELECT * FROM timescaledb_information.continuous_aggregates;

-- Zeige Compression Policies
SELECT * FROM timescaledb_information.compression_settings;
