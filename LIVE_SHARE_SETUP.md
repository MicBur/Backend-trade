# Qt Trade - Remote Backend Configuration

## Server Details:
- **Backend Server:** Deine Server-IP
- **Redis Port:** 6379 
- **Redis Password:** pass123

## Connection Settings für lokales Qt-Frontend:

```cpp
// In RedisClient Constructor
RedisClient *redis = new RedisClient("DEINE_SERVER_IP", 6379, "pass123");
```

## Live Share Workflow:
1. Du startest Live Share in VSCode (lokal qt-frontend/)
2. Ich joine deine Session
3. Wir entwickeln gemeinsam das Qt-Frontend
4. Frontend holt Daten von Remote-Redis
5. Live-Test mit echten Daten vom AutoGluon-Modell

## Vorteile:
- ✅ Qt läuft lokal (bessere Performance)
- ✅ Echte Daten vom Remote-Backend  
- ✅ Live-Collaboration via VS Code
- ✅ Sofortiges Feedback beim UI-Design