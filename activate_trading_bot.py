#!/usr/bin/env python3
"""
Trading Bot Aktivierung mit benutzerdefinierten Parametern
Konfiguriert den Bot für:
- 1% Wechsel Threshold (Buy/Sell)
- Nicht aggressiv (konservative Limits)
- Max 4 Stunden Position halten
- Alle verfügbaren Tickers
"""

import redis
import json
from datetime import datetime, timedelta

# Redis Connection
r = redis.Redis(host='redis', port=6379, password='pass123', decode_responses=True)

print("🤖 Trading Bot Aktivierung gestartet...")
print("=" * 60)

# 1. TRADING SETTINGS - Hauptkonfiguration
trading_settings = {
    "enabled": True,  # ✅ Bot aktivieren
    "buy_threshold_pct": 0.01,  # 1% Aufwärtspotential für Kauf
    "sell_threshold_pct": 0.01,  # 1% Abwärtspotential für Verkauf
    "max_position_per_trade": 10,  # 10 Aktien pro Trade (nicht aggressiv)
    "auto_mode": True,
    "max_hold_hours": 4,  # Max 4 Stunden halten
    "use_all_tickers": True,  # Alle verfügbaren Tickers nutzen
    "trading_mode": "conservative"  # Konservativer Modus
}

r.set('trading_settings', json.dumps(trading_settings))
print("✅ Trading Settings konfiguriert:")
print(f"   - Buy Threshold: {trading_settings['buy_threshold_pct']*100}%")
print(f"   - Sell Threshold: {trading_settings['sell_threshold_pct']*100}%")
print(f"   - Position Size: {trading_settings['max_position_per_trade']} Aktien")
print(f"   - Max Hold Time: {trading_settings['max_hold_hours']} Stunden")

# 2. RISK SETTINGS - Konservative Limits
risk_settings = {
    "max_trades_per_run": 3,  # Max 3 Trades pro 10-Minuten-Zyklus (nicht aggressiv)
    "max_position_per_ticker": 2,  # Max 2 Positionen pro Ticker gleichzeitig
    "daily_notional_cap": 50000.0,  # Max $50k Trading-Volumen pro Tag
    "max_position_size": 10000.0,  # Max $10k pro einzelne Position
    "stop_loss_pct": 0.05,  # 5% Stop Loss
    "take_profit_pct": 0.03,  # 3% Take Profit
    "cooldown_minutes": 30,  # 30 Minuten Cooldown zwischen Trades pro Ticker
    "max_daily_loss": 2000.0,  # Max $2k Verlust pro Tag
    "position_timeout_hours": 4  # Auto-close nach 4 Stunden
}

r.set('risk_settings', json.dumps(risk_settings))
print("\n✅ Risk Management konfiguriert:")
print(f"   - Max Trades/Run: {risk_settings['max_trades_per_run']}")
print(f"   - Max Positions/Ticker: {risk_settings['max_position_per_ticker']}")
print(f"   - Daily Cap: ${risk_settings['daily_notional_cap']:,.0f}")
print(f"   - Position Timeout: {risk_settings['position_timeout_hours']} Stunden")
print(f"   - Stop Loss: {risk_settings['stop_loss_pct']*100}%")
print(f"   - Take Profit: {risk_settings['take_profit_pct']*100}%")

# 3. POSITION MANAGEMENT SETTINGS
position_management = {
    "enabled": True,
    "check_interval_minutes": 15,  # Alle 15 Minuten Positionen prüfen
    "auto_close_enabled": True,
    "max_hold_hours": 4,  # Nach 4 Stunden automatisch verkaufen
    "trailing_stop_enabled": False,  # Kein Trailing Stop (zu aggressiv)
    "partial_exit_enabled": False  # Kein partieller Exit (einfach halten)
}

r.set('position_management', json.dumps(position_management))
print("\n✅ Position Management aktiviert:")
print(f"   - Auto-Close nach: {position_management['max_hold_hours']} Stunden")
print(f"   - Check Interval: {position_management['check_interval_minutes']} Minuten")

# 4. RISK STATUS initialisieren
risk_status = {
    "notional_today": 0.0,
    "last_reset": datetime.utcnow().date().isoformat(),
    "cooldowns": {},
    "daily_pnl": 0.0,
    "trades_today": 0
}

r.set('risk_status', json.dumps(risk_status))
print("\n✅ Risk Status initialisiert")

# 5. TRADING STATUS
trading_status = {
    "active": True,
    "mode": "auto",
    "last_run": datetime.utcnow().isoformat(),
    "next_run": (datetime.utcnow() + timedelta(minutes=10)).isoformat(),
    "trades_today": 0,
    "total_volume": 0.0,
    "error": None
}

r.set('trading_status', json.dumps(trading_status))
print("\n✅ Trading Status aktiviert")

# 6. Zeige verfügbare Tickers
portfolio_tickers = r.get('portfolio_positions')
if portfolio_tickers:
    tickers_data = json.loads(portfolio_tickers)
    if isinstance(tickers_data, list):
        # Liste von Strings oder Dicts
        if tickers_data and isinstance(tickers_data[0], dict):
            tickers = [t.get('ticker', str(t)) for t in tickers_data]
        else:
            tickers = tickers_data
    else:
        tickers = list(tickers_data.keys()) if isinstance(tickers_data, dict) else []
    
    print(f"\n📊 Verfügbare Tickers ({len(tickers)}):")
    print(f"   {', '.join(tickers) if tickers else 'Keine'}")
else:
    print("\n⚠️  Keine Portfolio Tickers gefunden - wird beim nächsten Sync geladen")

print("\n" + "=" * 60)
print("✅ Trading Bot AKTIVIERT!")
print("\n📋 Zusammenfassung:")
print(f"   - Trading: ENABLED ✅")
print(f"   - Modus: CONSERVATIVE (nicht aggressiv)")
print(f"   - Threshold: ±1% für Buy/Sell Signale")
print(f"   - Position Size: 10 Aktien/Trade")
print(f"   - Max Hold: 4 Stunden (automatischer Verkauf)")
print(f"   - Risk Limits: Aktiv")
print(f"   - Nächster Run: ~10 Minuten")
print("\n🔄 Der Bot wird automatisch alle 10 Minuten ausgeführt")
print("📊 Status prüfen: http://91.99.236.5:8000/trading/status")
print("\n⚠️  HINWEIS: Bot tradet nur während US Marktzeiten!")
print("=" * 60)
