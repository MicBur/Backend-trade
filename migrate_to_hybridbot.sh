#!/bin/bash

# QBot to HybridBot Migration Script
# Migriert das QBot Trading System zu GitHub HybridBot Repository

set -e

echo "🚀 QBot to HybridBot Migration Script"
echo "======================================"

# Variablen
QBOT_DIR="/home/pool/qbot"
TEMP_DIR="/tmp/hybridbot-migration"
HYBRIDBOT_REPO="https://github.com/MicBur/hybridbot.git"
USER_EMAIL="micbur1488@gmail.com"
USER_NAME="MicBur"

# Cleanup function
cleanup() {
    echo "🧹 Cleaning up temporary files..."
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

# 1. Erstelle temporäres Verzeichnis
echo "📁 Creating temporary directory..."
mkdir -p "$TEMP_DIR"
cd "$TEMP_DIR"

# 2. Clone HybridBot Repository
echo "📥 Cloning HybridBot repository..."
git clone "$HYBRIDBOT_REPO" .

# Configure git credentials
git config user.email "$USER_EMAIL"
git config user.name "$USER_NAME"

# 3. Erstelle Backend-Ordner
echo "📂 Creating backend directory..."
mkdir -p backend

# 4. Kopiere QBot-Dateien (ohne Git und sensitive Daten)
echo "📋 Copying QBot files to backend..."
cd "$QBOT_DIR"

# Kopiere Kern-Dateien
cp worker.py "$TEMP_DIR/backend/"
cp docker-compose.yml "$TEMP_DIR/backend/"
cp Dockerfile "$TEMP_DIR/backend/"
cp Dockerfile.yfinance "$TEMP_DIR/backend/"
cp requirements.txt "$TEMP_DIR/backend/"
cp init.sql "$TEMP_DIR/backend/"
cp redis-endpoints.txt "$TEMP_DIR/backend/"

# Kopiere Konfigurationsdateien
cp backend.txt "$TEMP_DIR/backend/" 2>/dev/null || echo "⚠️  backend.txt not found, skipping..."
cp at.txt "$TEMP_DIR/backend/" 2>/dev/null || echo "⚠️  at.txt not found, skipping..."
cp ml.md "$TEMP_DIR/backend/" 2>/dev/null || echo "⚠️  ml.md not found, skipping..."
cp README.md "$TEMP_DIR/backend/" 2>/dev/null || echo "⚠️  README.md not found, skipping..."
cp RELEASE_NOTES.md "$TEMP_DIR/backend/" 2>/dev/null || echo "⚠️  RELEASE_NOTES.md not found, skipping..."
cp LICENSE "$TEMP_DIR/backend/" 2>/dev/null || echo "⚠️  LICENSE not found, skipping..."

# Kopiere Python-Scripts
cp grok_top_stocks.py "$TEMP_DIR/backend/" 2>/dev/null || echo "⚠️  grok_top_stocks.py not found, skipping..."
cp multi_api_enhanced_service.py "$TEMP_DIR/backend/" 2>/dev/null || echo "⚠️  multi_api_enhanced_service.py not found, skipping..."
cp yfinance_enhanced_service.py "$TEMP_DIR/backend/" 2>/dev/null || echo "⚠️  yfinance_enhanced_service.py not found, skipping..."
cp yfinance_service.py "$TEMP_DIR/backend/" 2>/dev/null || echo "⚠️  yfinance_service.py not found, skipping..."

# Kopiere ML-Modelle (falls vorhanden)
if [ -d "autogluon_model" ]; then
    echo "🤖 Copying AutoGluon models..."
    cp -r autogluon_model "$TEMP_DIR/backend/"
fi
if [ -d "autogluon_model_15" ]; then
    cp -r autogluon_model_15 "$TEMP_DIR/backend/"
fi
if [ -d "autogluon_model_30" ]; then
    cp -r autogluon_model_30 "$TEMP_DIR/backend/"
fi
if [ -d "autogluon_model_60" ]; then
    cp -r autogluon_model_60 "$TEMP_DIR/backend/"
fi

# Kopiere Qt-Frontend (falls vorhanden)
if [ -d "qt-frontend" ]; then
    echo "🖥️  Copying Qt frontend..."
    cp -r qt-frontend "$TEMP_DIR/backend/"
fi
if [ -d "qml" ]; then
    cp -r qml "$TEMP_DIR/backend/"
fi

# Kopiere Scripts-Ordner (falls vorhanden)
if [ -d "scripts" ]; then
    echo "📜 Copying scripts..."
    cp -r scripts "$TEMP_DIR/backend/"
fi

# 5. Erstelle sanitized .env.example
echo "🔐 Creating sanitized .env.example..."
cat > "$TEMP_DIR/backend/.env.example" << 'EOF'
# QBot Trading Backend Environment Configuration
# Copy this file to .env and fill in your actual API keys

# Database Configuration
DATABASE_URL=postgresql://postgres:pass123@postgres:5432/qt_trade
POSTGRES_PASSWORD=pass123

# Redis Configuration
REDIS_URL=redis://:pass123@redis:6379/0
REDIS_PASSWORD=pass123

# Trading API Keys
ALPACA_API_KEY=your_alpaca_api_key_here
ALPACA_SECRET_KEY=your_alpaca_secret_key_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Market Data API Keys
FINNHUB_API_KEY=your_finnhub_api_key_here
FMP_API_KEY=your_fmp_api_key_here
TWELVEDATA_API_KEY=your_twelvedata_api_key_here
MARKETSTACK_API_KEY=your_marketstack_api_key_here

# AI/ML APIs
GROK_API_KEY=your_grok_api_key_here
GROK_API_URL=https://api.x.ai/v1

# Trading Configuration
DEVIATION_THRESHOLD=0.08
TRAIN_MIN_ROWS=150

# System Configuration
LOG_LEVEL=INFO
DEBUG=false

# Docker Configuration
COMPOSE_PROJECT_NAME=qbot
EOF

# 6. Erstelle Backend-spezifische README.md
echo "📚 Creating backend README..."
cat > "$TEMP_DIR/backend/README.md" << 'EOF'
# QBot Trading Backend

🤖 **Multi-Horizon ML Trading System** with Real-time Market Data Integration

## Features

### 🧠 Machine Learning
- **AutoGluon Multi-Horizon Models**: 15min, 30min, 60min prediction horizons
- **Automatic Retraining**: Triggers when prediction deviation >8%
- **Model Types**: LightGBM, XGBoost, CatBoost, Neural Networks, Ensemble Methods
- **Performance Tracking**: MAE, MAPE, R² metrics with historical tracking

### 📊 Multi-API Data Integration
- **Finnhub** ✅ (Primary): Real-time market data
- **TwelveData** ✅ (Secondary): Enhanced market coverage  
- **FMP** ⚡ (Available): Financial fundamentals
- **Marketstack** ⚡ (Available): Additional market data
- **Cross-Validation**: Data quality through source comparison

### 💰 Trading Engine
- **Alpaca API**: Real-time trading execution
- **Risk Management**: Daily caps, position limits, cooldowns
- **Market Hours Safety**: Auto-stop during market closure
- **Trade Logging**: Comprehensive trade history and analytics

### 🏗️ Architecture
- **Docker Containerized**: Redis, PostgreSQL, Python Worker
- **Celery Tasks**: Scheduled data fetching, ML training, trading
- **Real-time Communication**: Redis pub/sub for frontend integration
- **Comprehensive Monitoring**: System health, API status, performance metrics

## Quick Start

```bash
# 1. Setup environment
cp .env.example .env
# Edit .env with your API keys

# 2. Start services
docker-compose up -d

# 3. Check system status
docker-compose logs -f worker
```

## API Documentation

See `redis-endpoints.txt` for complete Redis API documentation including:
- Trading controls and status
- ML model metrics and predictions  
- Market data and analytics
- System monitoring endpoints

## ML Model Performance

Current model metrics (example):
```json
{
  "15min": {"mae": 148.42, "mape": 1.93, "r2": 0.85},
  "30min": {"mae": 156.78, "mape": 2.14, "r2": 0.82}, 
  "60min": {"mae": 165.23, "mape": 2.45, "r2": 0.79}
}
```

## System Requirements

- Docker & Docker Compose
- 4GB+ RAM (for AutoGluon ML models)
- API keys for market data and trading services

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run worker locally
python worker.py

# Run specific ML training
docker exec qbot-worker-1 python -c "from worker import train_model; train_model.delay('manual')"
```

## Architecture Diagram

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Market APIs   │    │   ML Training   │    │   Trading API   │
│  Finnhub/Twelve│────│   AutoGluon     │────│   Alpaca API    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │  Redis + Postgres│
                    │   Data Layer     │
                    └─────────────────┘
                                 │
                    ┌─────────────────┐
                    │  Worker Process │
                    │   (Celery)      │
                    └─────────────────┘
```

## License

MIT License - See LICENSE file for details.
EOF

# 7. Erstelle .gitignore für Backend
echo "🚫 Creating .gitignore..."
cat > "$TEMP_DIR/backend/.gitignore" << 'EOF'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual Environment
.venv/
venv/
env/
ENV/

# Environment Variables
.env
.env.local
.env.production

# Redis Runtime Files
celerybeat-schedule
dump.rdb

# Logs
logs/
*.log

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Temporary files
*.tmp
*.bak
*.backup
*~

# Database
*.db
*.sqlite3

# Archives
*.zip
*.tar.gz
*.rar
QtTradeFrontend-*.zip
EOF

# 8. Git Operationen
cd "$TEMP_DIR"

echo "📝 Adding files to git..."
git add backend/

echo "💾 Committing changes..."
git commit -m "feat: Add QBot Trading Backend

🤖 Multi-Horizon AutoGluon ML Trading System

Features:
- Multi-horizon ML models (15/30/60min predictions)
- Multi-API integration (Finnhub, TwelveData, FMP, Marketstack)
- Real-time trading via Alpaca API
- Docker containerized architecture
- Redis + PostgreSQL data persistence
- Automatic retraining on >8% prediction deviation
- Comprehensive Redis API documentation (481 lines)
- 2859+ lines of core trading logic

Architecture:
- AutoGluon ML: LightGBM, XGBoost, CatBoost, Neural Networks
- Market Data: Cross-validated multi-source aggregation
- Trading Engine: Risk management with market hours safety
- System Monitoring: Complete health and performance tracking

API Coverage: 90.9% with 2 active premium data sources"

echo "🚀 Pushing to GitHub..."
git push origin master

echo ""
echo "✅ Migration completed successfully!"
echo ""
echo "🎯 QBot Backend is now available at:"
echo "   https://github.com/MicBur/hybridbot/tree/main/backend"
echo ""
echo "📊 Next Steps:"
echo "   1. Review the migrated files on GitHub"
echo "   2. Set up GitHub Actions for CI/CD"
echo "   3. Configure Docker Hub integration"
echo "   4. Plan frontend integration"
echo ""
echo "🔗 Repository Structure:"
echo "   hybridbot/"
echo "   └── backend/"
echo "       ├── worker.py              # Core trading logic"
echo "       ├── docker-compose.yml     # Container orchestration"
echo "       ├── redis-endpoints.txt    # API documentation"
echo "       ├── autogluon_model*/      # Trained ML models"
echo "       ├── README.md              # Backend documentation"
echo "       └── .env.example           # Configuration template"
echo ""