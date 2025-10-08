"""
HybridBot Trading API Router
Endpoints für Bot-Control, Alpaca-Integration und Portfolio-Management
"""

import os
import json
import threading
import time
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field
import redis
from cryptography.fernet import Fernet

# Alpaca SDK
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import GetAssetsRequest
    from alpaca.trading.enums import AssetClass
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    print("⚠️  alpaca-py nicht installiert - /alpaca/* Endpoints deaktiviert")

# Redis Connection (Port 6379 - Standard)
redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = int(os.getenv("REDIS_PORT", 6379))
redis_password = os.getenv("REDIS_PASSWORD", "pass123")

try:
    bot_redis = redis.Redis(
        host=redis_host,
        port=redis_port,
        password=redis_password,
        decode_responses=True,
    )
    bot_redis.ping()
    print(f"✅ Bot Redis connected: {redis_host}:{redis_port}")
except Exception as e:
    print(f"❌ Bot Redis connection failed: {e}")
    bot_redis = None

# Encryption Key für Alpaca Credentials
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    # Generiere neuen Key wenn nicht vorhanden
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    print(f"⚠️  Neuer Encryption Key generiert - in .env speichern:")
    print(f"   ENCRYPTION_KEY={ENCRYPTION_KEY}")

cipher_suite = Fernet(ENCRYPTION_KEY.encode())

# Router
router = APIRouter(prefix="/bot", tags=["HybridBot"])

# Global Bot State
bot_thread: Optional[threading.Thread] = None
bot_running = False


# === Pydantic Models ===

class BotStartRequest(BaseModel):
    aggressiveness: int = Field(..., ge=1, le=10, description="Trading Aggressiveness (1=conservative, 10=aggressive)")
    max_amount: float = Field(..., gt=0, description="Maximum amount per trade in USD")
    reserve_pct: float = Field(..., ge=0, le=1, description="Reserve percentage (0.0-1.0)")

    class Config:
        json_schema_extra = {
            "example": {
                "aggressiveness": 5,
                "max_amount": 1000.0,
                "reserve_pct": 0.2
            }
        }


class AlpacaConnectRequest(BaseModel):
    api_key: str = Field(..., description="Alpaca API Key")
    secret: str = Field(..., description="Alpaca Secret Key")
    paper: bool = Field(True, description="Use paper trading (True) or live (False)")

    class Config:
        json_schema_extra = {
            "example": {
                "api_key": "PK...",
                "secret": "...",
                "paper": True
            }
        }


class PositionResponse(BaseModel):
    symbol: str
    qty: float
    value: float
    pnl: float
    pnl_pct: float


# === Bot Control Functions ===

def bot_trading_loop():
    """
    Haupt-Trading-Loop für den Bot
    Läuft in separatem Thread
    """
    global bot_running
    
    print("🤖 Bot Trading Loop gestartet")
    
    while bot_running:
        try:
            # Bot-Config aus Redis laden
            config = bot_redis.hgetall("bot_config")
            if not config:
                print("⚠️  Keine Bot-Config in Redis - Loop pausiert")
                time.sleep(10)
                continue
            
            aggressiveness = int(config.get("aggressiveness", 5))
            max_amount = float(config.get("max_amount", 1000))
            reserve_pct = float(config.get("reserve_pct", 0.2))
            
            # TODO: Hier echte Trading-Logik implementieren
            # - Market Data abrufen
            # - ML-Predictions nutzen
            # - Trading-Entscheidungen treffen
            # - Orders über Alpaca aufgeben
            
            print(f"🔄 Bot Tick - Aggressiveness: {aggressiveness}, Max: ${max_amount}")
            
            # Trading Interval basierend auf Aggressiveness
            sleep_time = max(5, 60 - (aggressiveness * 5))
            time.sleep(sleep_time)
            
        except Exception as e:
            print(f"❌ Bot Loop Error: {e}")
            time.sleep(30)
    
    print("🛑 Bot Trading Loop beendet")


# === Endpoints ===

@router.post("/start")
async def start_bot(config: BotStartRequest):
    """
    Startet den HybridBot mit gegebener Konfiguration
    
    - Speichert Config in Redis
    - Startet Trading-Thread
    - Validiert Alpaca-Connection (optional)
    """
    global bot_thread, bot_running
    
    if not bot_redis:
        raise HTTPException(status_code=500, detail="Redis connection not available")
    
    # Check ob Bot bereits läuft
    current_status = bot_redis.hget("bot_config", "running")
    if current_status == "true":
        raise HTTPException(status_code=409, detail="Bot already running")
    
    # Config in Redis speichern
    config_dict = config.model_dump()
    config_dict["running"] = "true"
    config_dict["started_at"] = time.time()
    
    bot_redis.hmset("bot_config", config_dict)
    
    # Thread starten
    bot_running = True
    bot_thread = threading.Thread(target=bot_trading_loop, daemon=True)
    bot_thread.start()
    
    return {
        "started": True,
        "config": config.model_dump(),
        "message": "HybridBot started successfully"
    }


@router.post("/stop")
async def stop_bot():
    """
    Stoppt den laufenden HybridBot
    """
    global bot_running
    
    if not bot_redis:
        raise HTTPException(status_code=500, detail="Redis connection not available")
    
    current_status = bot_redis.hget("bot_config", "running")
    if current_status != "true":
        raise HTTPException(status_code=409, detail="Bot not running")
    
    # Bot stoppen
    bot_running = False
    bot_redis.hset("bot_config", "running", "false")
    bot_redis.hset("bot_config", "stopped_at", time.time())
    
    # Warte auf Thread-Ende (max 5 Sekunden)
    if bot_thread and bot_thread.is_alive():
        bot_thread.join(timeout=5)
    
    return {
        "stopped": True,
        "message": "HybridBot stopped successfully"
    }


@router.get("/status")
async def get_bot_status():
    """
    Liefert aktuellen Bot-Status und Konfiguration
    """
    if not bot_redis:
        raise HTTPException(status_code=500, detail="Redis connection not available")
    
    try:
        config = bot_redis.hgetall("bot_config")
        
        if not config:
            return {
                "running": False,
                "aggressiveness": None,
                "max_amount": None,
                "reserve_pct": None,
                "started_at": None,
                "stopped_at": None
            }
        
        # Konvertiere Typen
        return {
            "running": config.get("running", "false") == "true",
            "aggressiveness": int(config.get("aggressiveness", 0)) if config.get("aggressiveness") else None,
            "max_amount": float(config.get("max_amount", 0)) if config.get("max_amount") else None,
            "reserve_pct": float(config.get("reserve_pct", 0)) if config.get("reserve_pct") else None,
            "started_at": float(config.get("started_at", 0)) if config.get("started_at") else None,
            "stopped_at": float(config.get("stopped_at", 0)) if config.get("stopped_at") else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis error: {str(e)}")


# === Alpaca Integration ===

@router.post("/alpaca/connect", tags=["Alpaca"])
async def connect_alpaca(credentials: AlpacaConnectRequest):
    """
    Verbindet mit Alpaca Trading API
    
    - Verschlüsselt und speichert Credentials in Redis
    - Testet Verbindung mit get_account()
    """
    if not ALPACA_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="alpaca-py nicht installiert - bitte 'pip install alpaca-py' ausführen"
        )
    
    if not bot_redis:
        raise HTTPException(status_code=500, detail="Redis connection not available")
    
    try:
        # Test Connection
        client = TradingClient(
            api_key=credentials.api_key,
            secret_key=credentials.secret,
            paper=credentials.paper
        )
        
        # Verify Credentials
        account = client.get_account()
        
        # Encrypt und speichere Credentials
        encrypted_key = cipher_suite.encrypt(credentials.api_key.encode()).decode()
        encrypted_secret = cipher_suite.encrypt(credentials.secret.encode()).decode()
        
        bot_redis.hmset("alpaca_credentials", {
            "api_key": encrypted_key,
            "secret": encrypted_secret,
            "paper": str(credentials.paper),
            "connected_at": time.time(),
            "account_number": account.account_number
        })
        
        return {
            "connected": True,
            "broker": "alpaca",
            "paper": credentials.paper,
            "account_number": account.account_number,
            "buying_power": float(account.buying_power),
            "cash": float(account.cash)
        }
        
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "unauthorized" in error_msg.lower():
            raise HTTPException(status_code=401, detail="Invalid Alpaca credentials")
        raise HTTPException(status_code=500, detail=f"Alpaca connection failed: {error_msg}")


@router.get("/portfolio", tags=["Alpaca"])
async def get_bot_portfolio() -> List[PositionResponse]:
    """
    Liefert aktuelle Positionen aus Alpaca Portfolio
    
    Benötigt vorherige Verbindung via /bot/alpaca/connect
    """
    if not ALPACA_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="alpaca-py nicht installiert"
        )
    
    if not bot_redis:
        raise HTTPException(status_code=500, detail="Redis connection not available")
    
    try:
        # Lade Credentials aus Redis
        creds = bot_redis.hgetall("alpaca_credentials")
        
        if not creds or not creds.get("api_key"):
            raise HTTPException(
                status_code=404,
                detail="No Alpaca connection - use POST /bot/alpaca/connect first"
            )
        
        # Decrypt Credentials
        api_key = cipher_suite.decrypt(creds["api_key"].encode()).decode()
        secret = cipher_suite.decrypt(creds["secret"].encode()).decode()
        paper = creds.get("paper", "True") == "True"
        
        # Connect to Alpaca
        client = TradingClient(api_key=api_key, secret_key=secret, paper=paper)
        
        # Get all positions
        positions = client.get_all_positions()
        
        # Map to response format
        result = []
        for pos in positions:
            result.append(PositionResponse(
                symbol=pos.symbol,
                qty=float(pos.qty),
                value=float(pos.market_value),
                pnl=float(pos.unrealized_pl),
                pnl_pct=float(pos.unrealized_plpc) * 100
            ))
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "unauthorized" in error_msg.lower():
            raise HTTPException(status_code=401, detail="Alpaca credentials invalid or expired")
        raise HTTPException(status_code=500, detail=f"Failed to fetch portfolio: {error_msg}")


@router.delete("/alpaca/disconnect", tags=["Alpaca"])
async def disconnect_alpaca():
    """
    Löscht gespeicherte Alpaca Credentials aus Redis
    """
    if not bot_redis:
        raise HTTPException(status_code=500, detail="Redis connection not available")
    
    bot_redis.delete("alpaca_credentials")
    
    return {
        "disconnected": True,
        "message": "Alpaca credentials removed"
    }
