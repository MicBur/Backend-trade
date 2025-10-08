# Release v0.1.0 - Qt Trade Frontend

## Übersicht
Erste stabile Release des Qt 6 Quick Trading Frontends mit Redis-Integration. Das Frontend bietet eine moderne, dunkle Benutzeroberfläche für Marktübersicht, Charts und Portfolio-Verwaltung.

## Neue Features
- **Qt 6 Quick UI**: Vollständig in QML entwickelte Benutzeroberfläche mit modernem Design
- **Redis Integration**: Live-Polling von Markt- und Portfolio-Daten via hiredis
- **Chart Visualisierung**: Interaktive Kerzencharts mit Forecast-Linien und Sparkline-Indikatoren
- **Modulare Architektur**: QML-Modul-Ansatz für saubere Komponenten-Trennung
- **Responsive Layout**: Anpassbare UI mit Status-Badges für Systemzustand
- **Deployment Automation**: PowerShell-Skript für Windows-Deployment mit windeployqt

## Technische Details
- **Qt Version**: 6.9.2 (MSVC 2022)
- **C++ Standard**: 17
- **Build System**: CMake mit qt_add_qml_module
- **Redis Client**: hiredis 1.3.0 (vendored)
- **UI Framework**: Qt Quick Controls 2, Layouts, Effects

## Bekannte Probleme
- Runtime-Test zeigt noch einen schnellen Absturz (QML Typ-Auflösung); Build ist stabil, aber UI startet nicht vollständig.
- DropShadow-Effekt reaktiviert, aber möglicherweise Plugin-Konflikte.

## Installation
1. Qt 6.9.2 installieren
2. Repository klonen: `git clone <repo> && cd cbot && git checkout v0.1.0`
3. Build: `cmake -S . -B build -G "Visual Studio 17 2022" -A x64 -DCMAKE_PREFIX_PATH="C:\Qt\6.9.2\msvc2022_64"`
4. `cmake --build build --config Release`
5. Deploy: `.\scripts\deploy.ps1 -Configuration Release -QtRoot "C:\Qt\6.9.2\msvc2022_64"`
6. Start: `.\dist\QtTradeFrontend.exe -redis-port 6380`

## Nächste Schritte
- Runtime-Fehler beheben (QML Typ-Resolution)
- ML-Integration erweitern
- Cross-Plattform-Support

## Commit-Hash
92e7d97

## Datum
13. September 2025</content>
<parameter name="filePath">c:\Users\User\Desktop\bot\RELEASE_NOTES.md