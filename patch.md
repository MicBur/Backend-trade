Backend-Update für HybridBot Trading API
Anweisungen für Claude Sonnet 4.5 als Agent:
Du bist ein Code-Agent in VS Code oder ähnlicher Umgebung. Lies alle Python-Skripte im Backend-Ordner (z.B. main.py, routers/*.py). Füge die neuen Endpoints hinzu, ohne bestehenden Code zu löschen. Verwende FastAPI-Standards (from fastapi import APIRouter, Body). Integriere mit Redis (Port 6380) für State-Speicherung (z.B. via redis-py). Teste Verbindungen (z.B. alpaca-py für Alpaca). Keine Dummy-Daten – echte Logik mit Error-Handling. Nach dem Patch: Generiere /openapi.json neu und starte den Server mit uvicorn --reload. Swagger aktualisiert sich automatisch unter /docs.
Neue Endpoints (füge zu einem Router hinzu, z.B. bot_router.py)

POST /bot/start
Body: {"aggressiveness": int = Body(..., ge=1, le=10), "max_amount": float = Body(..., gt=0), "reserve_pct": float = Body(..., ge=0, le=1)}
Funktion: Speichere in Redis (z.B. redis_client.hmset("bot_config", body.dict())). Starte Autotrade-Thread (integriere mit bestehendem Training-Service, falls vorhanden; sonst neuer Thread mit sleep-Loop für Simulation). Setze "running": True. Return: {"started": True, "config": body.dict()}
Fehler: 422 (ValidationError), 409 (wenn running == True: raise HTTPException(409, "Bot already running")).
POST /bot/stop
Body: None
Funktion: Stoppe Thread (z.B. thread.stop()), setze "running": False in Redis. Return: {"stopped": True}
Fehler: 409 (wenn nicht running: "Bot not running").
GET /bot/status
Return: Redis.hmget("bot_config", ["running", "aggressiveness", "max_amount", "reserve_pct"]) als Dict (konvertiere bool/float/int; null bei inaktiv).
Fehler: 500 (bei Redis-Fehler).
POST /alpaca/connect
Body: {"api_key": str = Body(...), "secret": str = Body(...)}
Funktion: Verschlüssle Keys (z.B. mit cryptography.fernet) und speichere in Redis ("alpaca_keys"). Teste Verbindung: from alpaca_trade_api import REST; client = REST(api_key, secret); try: client.get_account(); except: raise 401. Return: {"connected": True, "broker": "alpaca"}
Fehler: 401 (falsche Keys: "Invalid credentials"), 500 (andere Fehler).
GET /bot/portfolio
Funktion: Lade Keys aus Redis, entschlüssle. Wenn connected: client.get_all_positions() -> mappe zu [{"symbol": pos.symbol, "qty": float(pos.qty), "value": float(pos.market_value), "pnl": float(pos.unrealized_pl)}]. Return: List.
Sonst: raise HTTPException(404, "No Alpaca connection").
Fehler: 401 (nicht connected), 500 (API-Fehler).

Extra Anweisungen

Initialisierung: In main.py oder init: import redis; redis_client = redis.Redis(host='localhost', port=6380); app.state.redis = redis_client; app.state.bot_config_key = "bot_config".
Abhängigkeiten: Füge zu requirements.txt: alpaca-py, cryptography, redis (falls nicht da).
Integration mit Bestehendem: Verbinde mit /training/start (z.B. rufe es intern auf, wenn Bot startet). Nutze Yahoo/Finnhub für Market-Data in Bot-Logik.
Test: Nach Patch: POST /alpaca/connect mit Test-Keys, dann /bot/start, check /bot/status. Kein Crash – handle Exceptions.
Docker-Update: Passe Dockerfile/Compose an (add requirements, expose 8000). Rebuild mit docker-compose up --build.

Gib nach Ausführung aus: "Patch abgeschlossen. Swagger unter http://91.99.236.5:8000/docs aktualisiert."