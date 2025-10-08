import subprocess
import json
import redis
import psycopg2
import os
from datetime import datetime

# API-Key aus Umgebungsvariable laden
API_KEY = os.getenv("XAI_API_KEY")
prompt = {
    "messages": [
        {"role": "system", "content": "You are a helpful assistant with access to real-time search. Give the top 10 US stocks with highest 7-day gain probability. Output JSON with ticker, score, reason."},
        {"role": "user", "content": "Gib die Top 10 US-Aktien mit höchster 7-Tage-Gewinnwahrscheinlichkeit als JSON."}
    ],
    "model": "grok-4-latest",
    "stream": False,
    "temperature": 0
}

# Curl-Request
curl_cmd = [
    "curl", "https://api.x.ai/v1/chat/completions",
    "-H", "Content-Type: application/json",
    "-H", f"Authorization: Bearer {API_KEY}",
    "-d", json.dumps(prompt)
]
result = subprocess.run(curl_cmd, capture_output=True, text=True)
response = result.stdout

# Extrahiere JSON aus Antwort
try:
    data = json.loads(response)
    top10 = None
    # Versuche, die eigentliche Top10-Liste zu finden
    if "choices" in data and data["choices"]:
        msg = data["choices"][0]["message"]["content"]
        top10 = json.loads(msg) if isinstance(msg, str) else msg
except Exception:
    top10 = response

# Schreibe in Redis
r = redis.Redis(host="qbot-redis-1", port=6379, password="pass123", decode_responses=True)
r.set("grok_top10", json.dumps(top10))

# Schreibe in Postgres
def save_to_postgres(top10):
    conn = psycopg2.connect(dbname="qbot", user="postgres", password="pass123", host="qbot-timescaledb-1")
    cur = conn.cursor()
    if isinstance(top10, list):
        for rec in top10:
            cur.execute("""
                INSERT INTO grok_recommendations (time, ticker, score, reason)
                VALUES (%s, %s, %s, %s)
            """, (datetime.now(), rec.get("ticker"), rec.get("score"), rec.get("reason")))
        conn.commit()
    cur.close()
    conn.close()

save_to_postgres(top10)
print("Grok Top10 gespeichert in Redis und Postgres.")
