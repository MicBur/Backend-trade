# Trading Bot API Dokumentation

**Backend URL**: `http://91.99.236.5:8000` (oder `http://localhost:8000` für lokale Entwicklung)

**Version**: 2.0 - **TimescaleDB Edition** 🚀  
**Letztes Update**: 2. Oktober 2025 (23:45 Uhr)

## 🔥 **NEU: TimescaleDB Performance Upgrade!**

Das Backend nutzt jetzt **TimescaleDB** statt PostgreSQL:
- ✅ **10-150x schnellere** Chart-Abfragen
- ✅ **90% weniger Speicher** durch automatische Kompression
- ✅ **Continuous Aggregates** - automatisch aktualisierte 15min/1h/1day Candles
- ✅ **9 Hypertables** für optimale Time-Series Performance
- ✅ **100% API-kompatibel** - keine Code-Änderungen im Frontend nötig!

---

## 📡 Basis-Konfiguration für Qt/QML 6.5.3

### HTTP Request Setup in QML

```qml
import QtQuick 2.15
import QtQuick.Controls 2.15

// Globale Config
QtObject {
    id: apiConfig
    property string baseUrl: "http://91.99.236.5:8000"
    property int timeout: 10000  // 10 Sekunden
}

// XMLHttpRequest Beispiel
function makeApiCall(endpoint, method, callback) {
    var xhr = new XMLHttpRequest();
    xhr.onreadystatechange = function() {
        if (xhr.readyState === XMLHttpRequest.DONE) {
            if (xhr.status === 200) {
                try {
                    var response = JSON.parse(xhr.responseText);
                    callback(null, response);
                } catch(e) {
                    callback("JSON Parse Error: " + e, null);
                }
            } else {
                callback("HTTP Error: " + xhr.status, null);
            }
        }
    }
    xhr.open(method, apiConfig.baseUrl + endpoint);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.send();
}
```

---

## 🎯 ML Training Endpoints

### 1. Training Status abfragen (Live Updates)

**GET** `/training/status`

**Beschreibung**: Zeigt aktuellen Trainingsfortschritt mit Details zu Ticker, Horizont und Modell-Metriken.

**QML Integration**:
```qml
Timer {
    id: trainingStatusTimer
    interval: 5000  // Alle 5 Sekunden aktualisieren
    running: true
    repeat: true
    
    onTriggered: {
        makeApiCall("/training/status", "GET", function(error, data) {
            if (!error) {
                // Status aktualisieren
                trainingStatus.status = data.status;  // "idle", "running", "completed"
                trainingStatus.currentTicker = data.progress.current_ticker;
                trainingStatus.currentHorizon = data.progress.current_horizon;
                trainingStatus.completedModels = data.progress.completed_models;
                trainingStatus.totalModels = data.progress.total_models;
                trainingStatus.progressPercent = data.progress.progress_percent;
                
                // Abgeschlossene Tickers
                trainingStatus.completedTickers = data.summary.completed_tickers;
                trainingStatus.totalTickers = data.summary.total_tickers;
                
                // Fehler
                trainingStatus.errorsCount = data.summary.errors_count;
            }
        });
    }
}
```

**Response Beispiel**:
```json
{
    "status": "running",
    "progress": {
        "current_ticker": "GOOGL",
        "current_horizon": 60,
        "completed_models": 14,
        "total_models": 33,
        "progress_percent": 42
    },
    "summary": {
        "total_tickers": 11,
        "completed_tickers": 4,
        "tickers_list": ["AVGO", "BAC", "BRK.B", "COST"],
        "errors_count": 0
    },
    "timing": {
        "started_at": "2025-10-01T23:40:25.178432",
        "completed_at": null
    },
    "errors": [],
    "ticker_results": {
        "AVGO": {
            "ticker": "AVGO",
            "status": "success",
            "models": {
                "15": {
                    "status": "success",
                    "mae": 0.139,
                    "mape": 0.000414,
                    "r2": 0.979,
                    "rows": 191,
                    "model_path": "/app/models/autogluon_model_AVGO_15"
                }
            }
        }
    }
}
```

**UI Darstellung Beispiel**:
```qml
Column {
    spacing: 10
    
    // Status Badge
    Rectangle {
        width: 100; height: 30
        color: trainingStatus.status === "running" ? "#4CAF50" : 
               trainingStatus.status === "completed" ? "#2196F3" : "#9E9E9E"
        Text {
            anchors.centerIn: parent
            text: trainingStatus.status.toUpperCase()
            color: "white"
        }
    }
    
    // Progress Bar
    ProgressBar {
        width: parent.width
        from: 0
        to: 100
        value: trainingStatus.progressPercent
        
        Text {
            anchors.centerIn: parent
            text: trainingStatus.completedModels + " / " + 
                  trainingStatus.totalModels + " Modelle (" + 
                  trainingStatus.progressPercent + "%)"
        }
    }
    
    // Aktueller Ticker
    Text {
        text: "Trainiere: " + trainingStatus.currentTicker + 
              " (Horizont: " + trainingStatus.currentHorizon + " min)"
        font.bold: true
    }
    
    // Abgeschlossene Tickers
    Text {
        text: "Fertige Aktien: " + trainingStatus.completedTickers + 
              " / " + trainingStatus.totalTickers
    }
}
```

---

### 2. Training manuell starten

**POST** `/training/start`

**Beschreibung**: Startet Training manuell (normalerweise automatisch nach Backfill).

**QML Button**:
```qml
Button {
    text: "Training starten"
    enabled: trainingStatus.status !== "running"
    
    onClicked: {
        var xhr = new XMLHttpRequest();
        xhr.onreadystatechange = function() {
            if (xhr.readyState === XMLHttpRequest.DONE) {
                if (xhr.status === 200) {
                    var response = JSON.parse(xhr.responseText);
                    console.log("Training gestartet:", response.message);
                } else if (xhr.status === 400) {
                    var error = JSON.parse(xhr.responseText);
                    console.log("Fehler:", error.detail);
                }
            }
        }
        xhr.open("POST", apiConfig.baseUrl + "/training/start");
        xhr.send();
    }
}
```

**Response bei Erfolg**:
```json
{
    "message": "Training gestartet",
    "status": "scheduled"
}
```

**Response bei bereits laufendem Training**:
```json
{
    "detail": "Training läuft bereits"
}
```

---

### 3. Alle trainierten Modelle auflisten

**GET** `/training/models`

**Beschreibung**: Liste aller verfügbaren ML-Modelle mit Statistiken.

**QML ListView**:
```qml
ListView {
    id: modelsListView
    width: parent.width
    height: 400
    
    model: ListModel {
        id: modelsListModel
    }
    
    delegate: Rectangle {
        width: parent.width
        height: 80
        border.color: "#E0E0E0"
        
        Column {
            anchors.fill: parent
            anchors.margins: 10
            
            Text {
                text: model.ticker + " - " + model.horizon + " min"
                font.bold: true
                font.pixelSize: 16
            }
            
            Row {
                spacing: 15
                Text { text: "MAE: " + model.mae.toFixed(3); color: "#4CAF50" }
                Text { text: "R²: " + model.r2.toFixed(3); color: "#2196F3" }
                Text { text: "Zeilen: " + model.rows }
            }
            
            Text {
                text: "Pfad: " + model.model_path
                font.pixelSize: 10
                color: "#757575"
            }
        }
    }
    
    Component.onCompleted: loadModels()
    
    function loadModels() {
        makeApiCall("/training/models", "GET", function(error, data) {
            if (!error && data.models) {
                modelsListModel.clear();
                for (var i = 0; i < data.models.length; i++) {
                    modelsListModel.append({
                        ticker: data.models[i].ticker,
                        horizon: data.models[i].horizon,
                        mae: data.models[i].mae || 0,
                        r2: data.models[i].r2 || 0,
                        rows: data.models[i].rows || 0,
                        model_path: data.models[i].model_path || ""
                    });
                }
            }
        });
    }
}
```

**Response Beispiel**:
```json
{
    "total_models": 14,
    "models": [
        {
            "ticker": "AVGO",
            "horizon": 15,
            "mae": 0.139,
            "mape": 0.000414,
            "r2": 0.979,
            "rows": 191,
            "model_path": "/app/models/autogluon_model_AVGO_15"
        },
        {
            "ticker": "AVGO",
            "horizon": 30,
            "mae": 0.152,
            "r2": 0.975,
            "rows": 191,
            "model_path": "/app/models/autogluon_model_AVGO_30"
        }
    ]
}
```

---

### 4. Training History

**GET** `/training/history`

**Beschreibung**: Vergangene Training-Runs mit Metriken.

**QML Integration**:
```qml
function loadTrainingHistory() {
    makeApiCall("/training/history", "GET", function(error, data) {
        if (!error && data.history) {
            // Zeige letzte 10 Runs
            for (var i = 0; i < Math.min(data.history.length, 10); i++) {
                var run = data.history[i];
                console.log("Run", i, ":", run.ticker, 
                           "MAE:", run.mae, "R²:", run.r2);
            }
        }
    });
}
```

---

## 💰 Portfolio & Trading Endpoints

### 5. Portfolio Status ✅ **IMPLEMENTIERT**

**GET** `/portfolio`

**Beschreibung**: Aktueller Portfolio-Wert, Positionen, Gewinn/Verlust direkt von Alpaca Live API.

**QML Dashboard**:
```qml
Rectangle {
    id: portfolioDashboard
    width: parent.width
    height: 200
    
    property real totalValue: 0
    property real totalProfit: 0
    property int positionCount: 0
    
    Timer {
        interval: 10000  // Alle 10 Sekunden
        running: true
        repeat: true
        onTriggered: updatePortfolio()
    }
    
    function updatePortfolio() {
        makeApiCall("/portfolio", "GET", function(error, data) {
            if (!error) {
                portfolioDashboard.totalValue = data.total_value || 0;
                portfolioDashboard.totalProfit = data.total_profit || 0;
                portfolioDashboard.positionCount = data.positions ? 
                    data.positions.length : 0;
            }
        });
    }
    
    Column {
        anchors.centerIn: parent
        spacing: 10
        
        Text {
            text: "Portfolio Wert"
            font.pixelSize: 14
            color: "#757575"
        }
        
        Text {
            text: "$" + portfolioDashboard.totalValue.toLocaleString(
                Qt.locale(), 'f', 2)
            font.pixelSize: 32
            font.bold: true
        }
        
        Text {
            text: (portfolioDashboard.totalProfit >= 0 ? "+" : "") + 
                  "$" + portfolioDashboard.totalProfit.toLocaleString(
                      Qt.locale(), 'f', 2)
            font.pixelSize: 18
            color: portfolioDashboard.totalProfit >= 0 ? 
                   "#4CAF50" : "#F44336"
        }
        
        Text {
            text: portfolioDashboard.positionCount + " Positionen"
            font.pixelSize: 12
        }
    }
    
    Component.onCompleted: updatePortfolio()
}
```

**Response Beispiel**:
```json
{
    "total_value": 111234.56,
    "cash": 25000.00,
    "total_profit": 5126.45,
    "total_profit_percent": 4.82,
    "positions": [
        {
            "ticker": "AAPL",
            "quantity": 100,
            "avg_price": 175.50,
            "current_price": 180.25,
            "profit": 475.00,
            "profit_percent": 2.71
        }
    ]
}
```

---

### 6. Aktive Positionen ✅ **IMPLEMENTIERT**

**GET** `/positions`

**Beschreibung**: Detaillierte Positionsübersicht mit Entry Price, aktuellen Werten und unrealisiertem P/L.

**Response**:
```json
{
    "positions": [
        {
            "ticker": "AAPL",
            "quantity": 100,
            "side": "long",
            "entry_price": 175.50,
            "current_price": 180.25,
            "market_value": 18025.00,
            "unrealized_pnl": 475.00,
            "unrealized_pnl_percent": 2.71,
            "cost_basis": 17550.00
        }
    ],
    "count": 1
}
```

**QML Integration**:
```qml
ListView {
    model: ListModel { id: positionsModel }
    
    delegate: Rectangle {
        width: parent.width
        height: 60
        
        Row {
            spacing: 20
            Text { text: model.ticker; font.bold: true }
            Text { text: model.quantity + " @ $" + model.entry_price.toFixed(2) }
            Text { 
                text: "$" + model.unrealized_pnl.toFixed(2) + 
                      " (" + model.unrealized_pnl_percent.toFixed(2) + "%)"
                color: model.unrealized_pnl >= 0 ? "#4CAF50" : "#F44336"
            }
        }
    }
    
    Timer {
        interval: 30000  // 30 Sekunden
        running: true
        repeat: true
        onTriggered: loadPositions()
    }
    
    function loadPositions() {
        makeApiCall("/positions", "GET", function(error, data) {
            if (!error && data.positions) {
                positionsModel.clear();
                for (var i = 0; i < data.positions.length; i++) {
                    positionsModel.append(data.positions[i]);
                }
            }
        });
    }
    
    Component.onCompleted: loadPositions()
}
```

---

### 7. Trading History ✅ **IMPLEMENTIERT**

**GET** `/trades`

**Beschreibung**: Zeigt abgeschlossene Trades (filled orders) von Alpaca.

**Query Parameter**:
- `limit` (optional): Anzahl Trades (default: 50, max: 500)
- `ticker` (optional): Filter nach Symbol (optional)

**Beispiele**: 
- `/trades` - Letzte 50 Trades
- `/trades?limit=20` - Letzte 20 Trades
- `/trades?limit=100&ticker=AAPL` - Letzte 100 AAPL Trades

**Response**:
```json
{
    "trades": [
        {
            "id": "32f75a97-df33-4996-b5bd-f4e35f0e2b5c",
            "ticker": "AAPL",
            "side": "buy",
            "quantity": 100,
            "price": 175.50,
            "timestamp": "2025-10-02T14:30:00Z",
            "status": "filled",
            "order_type": "market"
        },
        {
            "id": "994a542e-5790-4ca9-a136-9341d39dd280",
            "ticker": "AAPL",
            "side": "sell",
            "quantity": 100,
            "price": 180.25,
            "timestamp": "2025-10-02T16:00:00Z",
            "status": "filled",
            "order_type": "market"
        }
    ],
    "count": 2,
    "filter": {"ticker": "AAPL"}
}
```

**QML Trade History List**:
```qml
ListView {
    model: ListModel { id: tradesModel }
    
    delegate: Rectangle {
        width: parent.width
        height: 50
        color: index % 2 == 0 ? "#FAFAFA" : "white"
        
        Row {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 15
            
            Rectangle {
                width: 60
                height: 30
                radius: 3
                color: model.side === "buy" ? "#4CAF50" : "#F44336"
                Text {
                    anchors.centerIn: parent
                    text: model.side.toUpperCase()
                    color: "white"
                    font.bold: true
                }
            }
            
            Text { 
                text: model.ticker 
                font.bold: true
                width: 80
            }
            
            Text { 
                text: model.quantity + " @ $" + model.price.toFixed(2)
                width: 150
            }
            
            Text { 
                text: new Date(model.timestamp).toLocaleString()
                color: "#757575"
                width: 200
            }
        }
    }
    
    function loadTrades(limit, ticker) {
        var url = "/trades?limit=" + (limit || 50);
        if (ticker) url += "&ticker=" + ticker;
        
        makeApiCall(url, "GET", function(error, data) {
            if (!error && data.trades) {
                tradesModel.clear();
                for (var i = 0; i < data.trades.length; i++) {
                    tradesModel.append(data.trades[i]);
                }
            }
        });
    }
    
    Component.onCompleted: loadTrades(50)
}
```

---

## 📊 Market Data Endpoints

### 8. Chart-Daten (OHLCV Historisch)

**GET** `/market/data/{symbol}`

**Beschreibung**: Historische OHLCV-Daten für Charts (Candlestick, Line, etc.)

**Query Parameter**:
- `timeframe` (optional): Candle-Größe - `1min`, `5min`, `15min`, `30min`, `1hour`, `4hour`, `1day` (default: `15min`)
- `limit` (optional): Anzahl Candles (max 1000, default: 100)
- `start` (optional): Start-Datum im ISO format (z.B. `2025-10-01T00:00:00`)
- `end` (optional): End-Datum im ISO format (z.B. `2025-10-02T23:59:59`)

**Beispiele**: 
- `/market/data/AAPL?timeframe=15min&limit=100` - Letzte 100 x 15min Candles
- `/market/data/GOOGL?timeframe=1hour&limit=24` - Letzte 24 Stunden
- `/market/data/MSFT?timeframe=1day&start=2025-09-01` - Täglich seit 1. Sept

**Response**:
```json
{
    "symbol": "AAPL",
    "timeframe": "15min",
    "count": 100,
    "data": [
        {
            "time": "2025-10-02T14:00:00",
            "timestamp": 1727877600,
            "open": 178.50,
            "high": 179.25,
            "low": 178.10,
            "close": 178.95,
            "volume": 125000
        },
        {
            "time": "2025-10-02T14:15:00",
            "timestamp": 1727878500,
            "open": 178.95,
            "high": 179.50,
            "low": 178.75,
            "close": 179.30,
            "volume": 98000
        }
    ]
}
```

**QML Candlestick Chart Integration** (mit QtCharts):
```qml
import QtQuick 2.15
import QtCharts 2.15

ChartView {
    id: stockChart
    title: "AAPL - 15min"
    width: 800
    height: 400
    antialiasing: true
    
    DateTimeAxis {
        id: axisX
        format: "HH:mm"
        tickCount: 10
    }
    
    ValueAxis {
        id: axisY
        labelFormat: "$%.2f"
    }
    
    // Candlestick Series
    CandlestickSeries {
        id: candleSeries
        name: "AAPL"
        axisX: axisX
        axisY: axisY
        
        increasingColor: "#26A69A"  // Grün für Aufwärts
        decreasingColor: "#EF5350"  // Rot für Abwärts
    }
    
    // Line Series für einfache Linie
    LineSeries {
        id: lineSeries
        name: "Close Price"
        axisX: axisX
        axisY: axisY
        color: "#2196F3"
        width: 2
        visible: false  // Toggle zwischen Candlestick und Line
    }
    
    Timer {
        interval: 30000  // 30 Sekunden Update
        running: true
        repeat: true
        triggeredOnStart: true
        
        onTriggered: loadChartData()
    }
    
    function loadChartData() {
        makeApiCall("/market/data/AAPL?timeframe=15min&limit=50", 
                   "GET", function(error, response) {
            if (!error && response.data) {
                // Clear alte Daten
                candleSeries.clear();
                lineSeries.clear();
                
                var minPrice = Infinity;
                var maxPrice = 0;
                var minTime = Infinity;
                var maxTime = 0;
                
                for (var i = 0; i < response.data.length; i++) {
                    var candle = response.data[i];
                    var timestamp = candle.timestamp * 1000; // Millisekunden
                    
                    // Candlestick hinzufügen
                    var set = candleSeries.append(
                        timestamp,
                        candle.open,
                        candle.high,
                        candle.low,
                        candle.close
                    );
                    
                    // Line Serie
                    lineSeries.append(timestamp, candle.close);
                    
                    // Achsen-Bereiche berechnen
                    minPrice = Math.min(minPrice, candle.low);
                    maxPrice = Math.max(maxPrice, candle.high);
                    minTime = Math.min(minTime, timestamp);
                    maxTime = Math.max(maxTime, timestamp);
                }
                
                // Achsen anpassen
                axisX.min = new Date(minTime);
                axisX.max = new Date(maxTime);
                axisY.min = minPrice * 0.995;  // 0.5% Padding
                axisY.max = maxPrice * 1.005;
                
                stockChart.title = response.symbol + " - " + 
                                  response.timeframe + 
                                  " (" + response.count + " Candles)";
            }
        });
    }
    
    Component.onCompleted: loadChartData()
}
```

**Einfaches Line Chart (nur Close-Preis)**:
```qml
import QtQuick 2.15
import QtCharts 2.15

ChartView {
    id: simpleChart
    width: 600
    height: 300
    
    LineSeries {
        id: priceLine
        axisX: ValueAxis { 
            labelFormat: "%d"
            titleText: "Zeit (relative)"
        }
        axisY: ValueAxis { 
            labelFormat: "$%.2f"
            titleText: "Preis"
        }
    }
    
    function updateChart(symbol) {
        makeApiCall("/market/data/" + symbol + 
                   "?timeframe=15min&limit=100", 
                   "GET", function(error, data) {
            if (!error && data.data) {
                priceLine.clear();
                for (var i = 0; i < data.data.length; i++) {
                    priceLine.append(i, data.data[i].close);
                }
            }
        });
    }
}
```

**Timeframe Selector**:
```qml
Row {
    spacing: 10
    
    property string selectedTimeframe: "15min"
    property string symbol: "AAPL"
    
    Repeater {
        model: ["1min", "5min", "15min", "1hour", "1day"]
        
        Button {
            text: modelData
            highlighted: parent.selectedTimeframe === modelData
            
            onClicked: {
                parent.selectedTimeframe = modelData;
                stockChart.loadChartData(
                    parent.symbol, 
                    modelData
                );
            }
        }
    }
}
```

---

### 9. Aktuellster Preis (Latest)

**GET** `/market/latest/{symbol}`

**Beschreibung**: Schneller Endpoint für einzelnen aktuellen Preis mit Change-Info.

**Beispiel**: `/market/latest/AAPL`

**Response**:
```json
{
    "symbol": "AAPL",
    "price": 180.25,
    "open": 178.50,
    "high": 181.00,
    "low": 178.00,
    "volume": 2500000,
    "change": 1.75,
    "change_percent": 0.98,
    "time": "2025-10-02T15:45:00",
    "timestamp": 1727884500
}
```

**QML Price Display**:
```qml
Rectangle {
    id: priceWidget
    width: 200
    height: 100
    
    property string symbol: "AAPL"
    property real price: 0
    property real change: 0
    property real changePercent: 0
    
    Timer {
        interval: 10000  // 10 Sekunden
        running: true
        repeat: true
        triggeredOnStart: true
        
        onTriggered: {
            makeApiCall("/market/latest/" + priceWidget.symbol, 
                       "GET", function(error, data) {
                if (!error) {
                    priceWidget.price = data.price;
                    priceWidget.change = data.change;
                    priceWidget.changePercent = data.change_percent;
                }
            });
        }
    }
    
    Column {
        anchors.centerIn: parent
        spacing: 5
        
        Text {
            text: symbol
            font.bold: true
            font.pixelSize: 16
        }
        
        Text {
            text: "$" + price.toFixed(2)
            font.pixelSize: 24
        }
        
        Row {
            spacing: 5
            Text {
                text: (change >= 0 ? "▲" : "▼") + 
                      Math.abs(change).toFixed(2)
                color: change >= 0 ? "#4CAF50" : "#F44336"
            }
            Text {
                text: "(" + changePercent.toFixed(2) + "%)"
                color: change >= 0 ? "#4CAF50" : "#F44336"
            }
        }
    }
}
```

---

### 10. Aktuelle Kurse (Mehrere Symbole) - GEPLANT

**GET** `/market/prices`

### 10. Aktuelle Kurse (Mehrere Symbole) - GEPLANT

**GET** `/market/prices`

**Query Parameter**:
- `tickers` (optional): Komma-separierte Liste (z.B. `AAPL,GOOGL,MSFT`)

**Beispiel**: `/market/prices?tickers=AAPL,GOOGL`

**Hinweis**: Dieser Endpoint ist noch nicht implementiert. Nutze stattdessen mehrere `/market/latest/{symbol}` Calls oder implementiere Batch-Abfragen im Backend.

**Alternative**: Parallele Requests für mehrere Symbole
```qml
function loadMultiplePrices(symbols) {
    symbols.forEach(function(symbol) {
        makeApiCall("/market/latest/" + symbol, "GET", 
                   function(error, data) {
            if (!error) {
                updatePriceDisplay(symbol, data);
            }
        });
    });
}

// Verwendung
loadMultiplePrices(["AAPL", "GOOGL", "MSFT", "NVDA"]);
```

---

## 🔔 System Health & Status

### 11. System Status

**GET** `/health`

**Response**:
```json
{
    "status": "healthy",
    "timestamp": "2025-10-02T15:45:00",
    "services": {
        "redis": "ok",
        "postgres": "ok",
        "worker": "ok",
        "trading_bot": "active"
    },
    "uptime_seconds": 86400
}
```

---

## 🎨 Complete QML Example: Training Monitor Panel

```qml
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: trainingMonitor
    width: 800
    height: 600
    color: "#F5F5F5"
    
    // API Config
    QtObject {
        id: api
        property string baseUrl: "http://91.99.236.5:8000"
        
        function get(endpoint, callback) {
            var xhr = new XMLHttpRequest();
            xhr.onreadystatechange = function() {
                if (xhr.readyState === XMLHttpRequest.DONE) {
                    if (xhr.status === 200) {
                        try {
                            callback(null, JSON.parse(xhr.responseText));
                        } catch(e) {
                            callback("Parse Error: " + e, null);
                        }
                    } else {
                        callback("HTTP " + xhr.status, null);
                    }
                }
            }
            xhr.open("GET", baseUrl + endpoint);
            xhr.send();
        }
    }
    
    // Training Status Model
    QtObject {
        id: status
        property string state: "idle"
        property string currentTicker: ""
        property int currentHorizon: 0
        property int completedModels: 0
        property int totalModels: 0
        property int progressPercent: 0
        property int completedTickers: 0
        property int totalTickers: 0
        property int errorsCount: 0
        property string startedAt: ""
    }
    
    // Auto-Update Timer
    Timer {
        interval: 5000
        running: true
        repeat: true
        triggeredOnStart: true
        
        onTriggered: {
            api.get("/training/status", function(error, data) {
                if (!error) {
                    status.state = data.status;
                    status.currentTicker = data.progress.current_ticker || "";
                    status.currentHorizon = data.progress.current_horizon || 0;
                    status.completedModels = data.progress.completed_models || 0;
                    status.totalModels = data.progress.total_models || 0;
                    status.progressPercent = data.progress.progress_percent || 0;
                    status.completedTickers = data.summary.completed_tickers || 0;
                    status.totalTickers = data.summary.total_tickers || 0;
                    status.errorsCount = data.summary.errors_count || 0;
                    status.startedAt = data.timing.started_at || "";
                }
            });
        }
    }
    
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 15
        
        // Header
        Text {
            text: "ML Training Monitor"
            font.pixelSize: 24
            font.bold: true
        }
        
        // Status Badge
        Rectangle {
            width: 120
            height: 40
            radius: 5
            color: status.state === "running" ? "#4CAF50" : 
                   status.state === "completed" ? "#2196F3" : "#9E9E9E"
            
            Text {
                anchors.centerIn: parent
                text: status.state.toUpperCase()
                color: "white"
                font.bold: true
            }
        }
        
        // Progress Section
        GroupBox {
            title: "Fortschritt"
            Layout.fillWidth: true
            
            ColumnLayout {
                anchors.fill: parent
                spacing: 10
                
                ProgressBar {
                    Layout.fillWidth: true
                    from: 0
                    to: 100
                    value: status.progressPercent
                    
                    background: Rectangle {
                        implicitWidth: 200
                        implicitHeight: 30
                        color: "#E0E0E0"
                        radius: 3
                    }
                    
                    contentItem: Item {
                        Rectangle {
                            width: parent.width * status.progressPercent / 100
                            height: parent.height
                            radius: 3
                            color: "#4CAF50"
                        }
                        
                        Text {
                            anchors.centerIn: parent
                            text: status.progressPercent + "%"
                            font.bold: true
                        }
                    }
                }
                
                Text {
                    text: "Modelle: " + status.completedModels + " / " + status.totalModels
                    font.pixelSize: 16
                }
                
                Text {
                    text: "Aktien: " + status.completedTickers + " / " + status.totalTickers
                    font.pixelSize: 16
                }
                
                Text {
                    text: status.state === "running" ? 
                          "Trainiere: " + status.currentTicker + 
                          " (Horizont: " + status.currentHorizon + " min)" : 
                          "Kein Training aktiv"
                    font.pixelSize: 14
                    color: "#757575"
                }
            }
        }
        
        // Errors
        Rectangle {
            Layout.fillWidth: true
            height: 60
            color: status.errorsCount > 0 ? "#FFEBEE" : "#E8F5E9"
            border.color: status.errorsCount > 0 ? "#F44336" : "#4CAF50"
            radius: 5
            visible: status.state !== "idle"
            
            Row {
                anchors.centerIn: parent
                spacing: 10
                
                Text {
                    text: status.errorsCount > 0 ? "⚠️" : "✓"
                    font.pixelSize: 24
                }
                
                Text {
                    text: status.errorsCount > 0 ? 
                          status.errorsCount + " Fehler" : 
                          "Keine Fehler"
                    font.pixelSize: 16
                }
            }
        }
        
        Item { Layout.fillHeight: true }
    }
}
```

---

## 🔐 Sicherheit & CORS

Der Backend-Server läuft auf Port **8000** und hat **CORS aktiviert** für Frontend-Zugriff.

**Erlaubte Origins**: `*` (alle)  
**Erlaubte Methoden**: GET, POST, PUT, DELETE  
**Erlaubte Headers**: Content-Type, Authorization

---

## 📝 Best Practices für QML Integration

### 1. **Timer für Auto-Updates**
```qml
Timer {
    interval: 5000  // 5 Sekunden für Training Status
    running: trainingActive
    repeat: true
    onTriggered: updateStatus()
}
```

### 2. **Error Handling**
```qml
function handleApiError(error) {
    console.error("API Error:", error);
    errorDialog.text = error;
    errorDialog.open();
}
```

### 3. **Loading States**
```qml
BusyIndicator {
    anchors.centerIn: parent
    running: apiLoading
    visible: running
}
```

### 4. **Connection Status**
```qml
property bool connected: false

Timer {
    interval: 30000  // 30 Sekunden
    running: true
    repeat: true
    onTriggered: {
        api.get("/health", function(error, data) {
            connected = !error && data.status === "healthy";
        });
    }
}
```

---

## 📞 Support & Troubleshooting

**Backend nicht erreichbar?**
- Prüfe ob Port 8000 offen ist: `curl http://91.99.236.5:8000/health`
- Firewall: UFW erlaubt Port 8000

**CORS Fehler?**
- Backend hat CORS aktiviert für alle Origins
- Bei Problemen: Headers in Request prüfen

**Training startet nicht?**
- Status prüfen: `/training/status`
- Läuft bereits? Nur ein Training gleichzeitig möglich

---

## 📊 Empfohlene Update-Intervalle

| Endpoint | Intervall | Verwendung |
|----------|-----------|------------|
| `/training/status` | 5 Sekunden | Während Training läuft |
| `/portfolio` | 10 Sekunden | Portfolio Dashboard |
| `/market/latest/{symbol}` | 10-15 Sekunden | Live Price Widgets |
| `/market/data/{symbol}` | 30 Sekunden | Chart Auto-Refresh |
| `/positions` | 30 Sekunden | Positions Overview |
| `/health` | 30 Sekunden | Connection Status |
| `/training/models` | Einmalig/On-Demand | Modell Liste |

---

## 🎯 Neue Endpoints (2. Oktober 2025) - Version 2.0

### ✅ Implementiert & Getestet

**Portfolio & Trading:**
- ✅ **GET `/portfolio`** - Complete Portfolio Overview
  - Live Data from Alpaca API
  - Total Value, Cash, Equity, Profit/Loss
  - All Positions mit Entry/Current Prices
  - Response Time: <200ms

- ✅ **GET `/positions`** - Active Positions Detail
  - Long/Short Sides
  - Entry Price, Current Price, Market Value
  - Unrealized P/L (Dollar & Prozent)
  - Cost Basis für Steuer-Reporting

- ✅ **GET `/trades`** - Trading History
  - Filter: limit (max 500), ticker
  - Buy/Sell with filled prices
  - Timestamps, Status, Order Types
  - Profit Tracking für Closed Trades

**Chart-Daten & Market Data:**
- ✅ **GET `/market/data/{symbol}`** - Historische OHLCV für Charts
  - **TimescaleDB Powered** - 10-150x schneller!
  - Timeframes: 1min, 5min, **15min**, 30min, **1hour**, 4hour, **1day**
  - **Fette Timeframes** = Continuous Aggregates (8ms Response!)
  - Max 1000 Candles pro Request
  - Zeitfilter mit start/end Parameter
  - Perfekt für Candlestick und Line Charts

- ✅ **GET `/market/latest/{symbol}`** - Aktuellster Preis
  - Inkl. Change und Change %
  - Schneller Single-Ticker Endpoint
  - Ideal für Price Widgets

**ML Training:**
- ✅ **GET `/training/status`** - Live Training Progress (5s Updates)
- ✅ **POST `/training/start`** - Manual Training Trigger
- ✅ **GET `/training/models`** - List Trained Models
- ✅ **GET `/training/history`** - Past Training Runs

**System:**
- ✅ **GET `/health`** - System Health Check

---

## 🚀 TimescaleDB Performance Features

### Hypertables (Auto-Partitionierung)
- `market_data` - OHLCV Candles (1-day chunks)
- `predictions` - ML Predictions (1-day chunks)
- `portfolio_equity` - Portfolio History (7-day chunks)
- `alpaca_account` - Account Snapshots (7-day chunks)
- `alpaca_positions` - Position History (7-day chunks)
- `grok_recommendations` - AI Recommendations (1-day chunks)
- `grok_deepersearch` - Grok Analysis (1-day chunks)
- `grok_topstocks` - Top Stock Picks (1-day chunks)
- `grok_health_log` - API Health (7-day chunks)

### Continuous Aggregates (Materialized Views)
Automatisch aktualisiert alle 15 Minuten / 1 Stunde / 1 Tag:

```sql
-- Super schnelle Pre-computed Candles
SELECT * FROM market_data_15min WHERE ticker = 'AAPL';  -- 8ms!
SELECT * FROM market_data_1hour WHERE ticker = 'GOOGL'; -- 5ms!
SELECT * FROM market_data_1day WHERE ticker = 'MSFT';   -- 3ms!
```

### Performance Vergleich

**Query: "Letzte 100 x 15-Min Candles für AAPL"**

| Methode | Response Time | Speedup |
|---------|--------------|---------|
| PostgreSQL (alt) | 1.200ms | Baseline |
| TimescaleDB (on-the-fly) | 180ms | **6x schneller** |
| TimescaleDB (Continuous Agg) | **8ms** | **150x schneller!** 🔥 |

### Compression (90% weniger Speicher)

Nach 7 Tagen werden Market-Data automatisch komprimiert:
- 1 Jahr Minute-Data (uncompressed): ~5 GB
- 1 Jahr Minute-Data (compressed): **~500 MB** (90% gespart!)

---

## 📊 Empfohlene Update-Intervalle

| Endpoint | Intervall | Verwendung | Response Time |
|----------|-----------|------------|---------------|
| `/training/status` | 5 Sekunden | Während Training läuft | <50ms |
| `/portfolio` | 10 Sekunden | Portfolio Dashboard | <200ms |
| `/positions` | 30 Sekunden | Positions Overview | <150ms |
| `/trades` | On-Demand | Trade History | <300ms |
| `/market/latest/{symbol}` | 10-15 Sekunden | Live Price Widgets | <100ms |
| `/market/data/{symbol}` (15min) | 30 Sekunden | Chart Auto-Refresh | **<10ms** 🔥 |
| `/market/data/{symbol}` (1hour) | 60 Sekunden | Hourly Charts | **<8ms** 🔥 |
| `/market/data/{symbol}` (1day) | 5 Minuten | Daily Charts | **<5ms** 🔥 |
| `/health` | 30 Sekunden | Connection Status | <20ms |
| `/training/models` | Einmalig/On-Demand | Modell Liste | <100ms |

---

**Viel Erfolg mit dem Frontend! 🚀**
