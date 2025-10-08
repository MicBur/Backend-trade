"""
Training Monitoring API Endpoints für FastAPI
Muss in app.py integriert werden
"""

# Diese Endpoints in app.py einfügen VOR if __name__ == "__main__":

"""
# ===== ML TRAINING MONITORING ENDPOINTS =====

@app.get("/training/status")
async def get_training_status():
    '''
    Aktueller Training-Status mit Live-Progress
    Frontend kann Fortschritt überwachen
    '''
    try:
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
async def start_training(tickers: list = None):
    '''
    Startet sequenzielles Training manuell
    
    Optional: Liste von Tickern angeben
    Ohne Parameter: Alle Portfolio + Grok Tickers
    '''
    try:
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
        
        # Training starten via Celery
        from worker import train_sequential
        task = train_sequential.delay(tickers=tickers)
        
        return {
            "success": True,
            "message": "Training started",
            "task_id": str(task.id),
            "tickers": tickers if tickers else "all (portfolio + grok)",
            "monitor_endpoint": "/training/status"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/training/models")
async def get_trained_models():
    '''
    Liste aller trainierten Modelle
    Zeigt verfügbare Ticker und Horizons
    '''
    try:
        import os
        models_dir = "/app/models"
        
        if not os.path.exists(models_dir):
            return {"models": [], "total": 0}
        
        models = []
        for item in os.listdir(models_dir):
            if item.startswith("autogluon_model_"):
                parts = item.replace("autogluon_model_", "").split("_")
                if len(parts) >= 2:
                    ticker = parts[0]
                    horizon = parts[1]
                    
                    model_path = os.path.join(models_dir, item)
                    
                    # Metadaten auslesen wenn verfügbar
                    try:
                        import datetime as dt
                        last_modified = os.path.getmtime(model_path)
                        modified_date = dt.datetime.fromtimestamp(last_modified).isoformat()
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
    '''
    Training-Historie aus Redis
    Zeigt vergangene Training-Runs
    '''
    try:
        # Aus last_training_stats (vom alten Training-System)
        old_stats = r.get("last_training_stats")
        
        # Aus model_metrics_history
        history_data = r.get("model_metrics_history")
        
        history = []
        if history_data:
            history = json.loads(history_data)
        
        return {
            "history": history[-10:] if history else [],  # Letzte 10
            "last_training": json.loads(old_stats) if old_stats else None,
            "total_runs": len(history)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
"""
