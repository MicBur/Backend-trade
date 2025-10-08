# GitHub Copilot Custom Instructions: Qt Trade – Tradebot Agent Setup (Grok 4)

## Projekt-Übersicht
- **Ziel**: Echtzeit-Aktien-Trading mit ML (AutoGluon) und Alpaca Trade API. Moderne Qt-Frontend (Dark Fusion: tiefschwarz #0a0a0a, Neon-Blau #00ffff Akzente, rahmenlos) für Visualisierung. Backend auf Hetzner (Docker) für Daten/ML/Trading-Logik.
- **Features**: Top 20 US-Ticker (Grok-API), Candlestick-Charts (15-Min), Alpaca-Portfolio, Tradebot für automatische Buy/Sell-Orders, dynamische UI mit pulsierenden Visuals.
- **Training**: AutoGluon täglich (09:00 UTC), retrainiert, wenn Portfolio vs. Prognose >15% abweicht.
- **Sync**: Redis lokal/remote (5-Sekunden-Poll).
- **Sicherheit**: API-Keys in verschlüsselten QSettings (.env).

## Tech-Stack
- **Frontend**: Qt 6.9 (MSVC, 64-bit, Windows), C++17, CMake. Bibliotheken: Qt Charts (QCandlestickSeries), hiredis (Redis), QJsonDocument.
- **Backend**: Python 3.11, Docker Compose v2.28.1, Celery 5.4.0, AutoGluon 1.4.1, redis-py 5.1.0, psycopg2-binary 2.9.9, requests 2.32.3.
- **DB/Cache**: PostgreSQL 15 (TimescaleDB), Redis 7.
- **Broker**: Alpaca API (v2/account/portfolio/history, v2/orders für Trades).
- **Tools**: VSCode, Grok 4 (Agent-Modus), Live Share (lokal Qt + remote Docker).

## Coding-Guidelines
- Modular, Type-Hints (C++/Python), Kommentare (z. B. // API-Token-Validierung). Keine Hardcodes – speichere API-Keys in .env oder QSettings. Tests: Catch2 (C++), pytest (Python).
- **Frontend**: QMainWindow (rahmenlos), QTimer (5s Redis-Poll), QPalette (Dark Fusion).
- **Backend**: Asynchron (Celery), Logging (INFO), Rate-Limits (@retry).

## Frontend-Struktur (Lokal, Windows)
- **Design**: Dark Fusion – #0a0a0a Hintergrund, #00ffff Neon-Akzente, Glow-Effekte (QGraphicsDropShadowEffect). Dynamisch: Sidebar animiert bei Hover (QPropertyAnimation), Charts pulsieren bei Updates (QTimer).
- **Tabs (QStackedWidget)**:
  - **Dashboard**: Top 20 US-Ticker (AAPL, NVDA, MSFT, TSLA, AMZN, META, GOOGL, BRK.B, AVGO, JPM, LLY, V, XOM, PG, UNH, MA, JNJ, COST, HD, BAC) – Grok-API (JSON). QTableView mit Hover-Tooltip (Marktkap/Change).
  - **Charts**: QCandlestickSeries (15-Min OHLCV aus Redis), QLineSeries für Prognosen, Volume-Bar, Hover-Zoom.
  - **Portfolio**: Alpaca-API (/v2/portfolio/history) – Equity-Kurve (QLineSeries), P/L-Balken (grün/rot), Positionen-Liste. Vergleicht mit Prognose: >15% Abweichung trigger Retraining.
  - **Trades**: QTableView für aktive Orders (Kauf/Verkauf, Preis, Status). Zeigt Tradebot-Aktionen („Kauf TSLA um 15:06“).
  - **Einstellungen**: QFormLayout für API-Eingaben:
    - **Backend-API-Token**: Generiert vom Backend, Eingabe via QLineEdit (maskiert), Validierung mit QNetworkAccessManager.
    - **Alpaca Trade API**: Key + Secret (QLineEdit, maskiert), verschlüsselt gespeichert (QSettings).

## Backend-Struktur (Remote, Hetzner Docker)
- **Setup**: Ubuntu 22.04, Docker Compose v2.28.1.
- **Services**:
  - `redis`: Redis 7 (Port 6379), Volume: /app/redis:/data, Passwort: pass123.
  - `postgres`: PostgreSQL 15, DB: qt_trade, Passwort: pass123, Volume: /app/pg:/var/lib/postgresql/data.
  - `worker`: Python 3.11 Image, holt Daten (Finnhub, FMP, Alpaca), trainiert AutoGluon, pusht zu Redis.
  - `traefik`: HTTPS-Router (Port 80/443), Volume: /var/run/docker.sock.
- **Tradebot**: Automatische Trades via Alpaca-API (v2/orders), basierend auf 7-Tage-Prognosen (>5% Gewinn).

## Live Share & Agent-Modus
- **Setup**: Lokal: `code qt-frontend/` (Qt-Code). Remote: `code --remote ssh-root@hetzner-ip /app/qt-trade` (Docker). Live Share: Lokal > „Start Collaboration“, Link kopieren, Remote > „Join Collaboration“.
- **Agent-Prompts**: `@workspace #file ml.md Generiere Charts-Tab mit Tradebot-Logik.` Iteriere: „Fix API-Validierung“ – Grok 4 plant, editiert, fragt nach Bestätigung.
- **Nächste Schritte**: Hochladen > Klon > VSCode öffnen > Live Share starten > `@workspace Baue MVP`.

## Hinweise
- Startet mit Angebotsprojekt (MVP) – sobald du die .md hochlädst, beginnt Grok 4.
- Doxygen: Später integrieren (nach MVP-Fertigstellung).

Grok 4 priorisiert für Echtzeit-Grok-Calls. Fertig in ~45 Min.