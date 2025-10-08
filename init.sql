-- Create market data table (ohne TimescaleDB für jetzt)
CREATE TABLE IF NOT EXISTS market_data (
    id SERIAL PRIMARY KEY,
    time TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume BIGINT
);

-- Create predictions table
CREATE TABLE IF NOT EXISTS predictions (
    id SERIAL PRIMARY KEY,
    time TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    predicted_price DOUBLE PRECISION
);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_market_data_ticker_time ON market_data(ticker, time);
CREATE INDEX IF NOT EXISTS idx_predictions_ticker_time ON predictions(ticker, time);

-- Portfolio-Daten
CREATE TABLE IF NOT EXISTS portfolio_equity (
    id SERIAL PRIMARY KEY,
    time TIMESTAMPTZ NOT NULL,
    equity_value DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_portfolio_equity_time ON portfolio_equity(time);

CREATE TABLE IF NOT EXISTS portfolio_positions (
    id SERIAL PRIMARY KEY,
    ticker TEXT NOT NULL UNIQUE,
    qty INT,
    avg_price DOUBLE PRECISION,
    side TEXT
);
CREATE INDEX IF NOT EXISTS idx_portfolio_positions_ticker ON portfolio_positions(ticker);

-- Aktive Orders
CREATE TABLE IF NOT EXISTS active_orders (
    id SERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    side TEXT,
    price DOUBLE PRECISION,
    status TEXT,
    timestamp TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_active_orders_ticker_time ON active_orders(ticker, timestamp);

CREATE TABLE IF NOT EXISTS settings (
    id SERIAL PRIMARY KEY,
    key TEXT UNIQUE,
    value TEXT
);

-- Grok Top-10 Empfehlungen
CREATE TABLE IF NOT EXISTS grok_recommendations (
    id SERIAL PRIMARY KEY,
    time TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    score DOUBLE PRECISION,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_grok_recommendations_ticker_time ON grok_recommendations(ticker, time);

CREATE TABLE IF NOT EXISTS grok_deepersearch_results (
    id SERIAL PRIMARY KEY,
    time TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    score DOUBLE PRECISION,
    analysis TEXT,
    details JSONB
);
CREATE INDEX IF NOT EXISTS idx_grok_deepersearch_ticker_time ON grok_deepersearch_results(ticker, time);

-- Neue vereinheitlichte Grok Deepersearch Tabelle (vereinfachte, aktuelle Struktur)
CREATE TABLE IF NOT EXISTS grok_deepersearch (
    id SERIAL PRIMARY KEY,
    time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ticker TEXT NOT NULL,
    sentiment DOUBLE PRECISION,
    explanation_de TEXT
);
CREATE INDEX IF NOT EXISTS idx_grok_deepersearch_ticker_time_new ON grok_deepersearch(ticker, time);

-- Grok Top Stocks Prognose
CREATE TABLE IF NOT EXISTS grok_topstocks (
    id SERIAL PRIMARY KEY,
    time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ticker TEXT NOT NULL,
    expected_gain DOUBLE PRECISION,
    sentiment DOUBLE PRECISION,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_grok_topstocks_ticker_time ON grok_topstocks(ticker, time);

-- Grok Health Log (optional für Monitoring)
CREATE TABLE IF NOT EXISTS grok_health_log (
    id SERIAL PRIMARY KEY,
    time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sdk_ok BOOLEAN,
    http_ok BOOLEAN,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_grok_health_log_time ON grok_health_log(time);

-- Alpaca Account
CREATE TABLE IF NOT EXISTS alpaca_account (
    id SERIAL PRIMARY KEY,
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

-- Alpaca Positionen
CREATE TABLE IF NOT EXISTS alpaca_positions (
    id SERIAL PRIMARY KEY,
    time TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    qty INT,
    avg_entry_price DOUBLE PRECISION,
    market_value DOUBLE PRECISION,
    unrealized_pl DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_alpaca_positions_symbol_time ON alpaca_positions(symbol, time);

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
CREATE INDEX IF NOT EXISTS idx_alpaca_orders_symbol_time ON alpaca_orders(symbol, created_at);
