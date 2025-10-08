#!/usr/bin/env python3
import os
import json
import time
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
import requests

GROK_API_KEY = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
# Offizieller Chat Endpoint (falls interne Legacy Domain weiter genutzt wird, per ENV überschreiben)
GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai")
GROK_INSECURE = os.getenv("GROK_INSECURE", "0") == "1"
GROK_MODEL_ID = os.getenv("GROK_MODEL_ID", "grok-4")
MODEL_CANDIDATES = [GROK_MODEL_ID, "grok-latest", "grok-4-mini"]
API_PATH = "/v1/chat/completions"
TIMEOUT = 60
MAX_RETRIES = 3

JSON_ARRAY_PATTERN = re.compile(r'\[\s*{.*?}\s*\]', re.DOTALL)

def _extract_json_array(text: str) -> Optional[str]:
    text = text.strip()
    if text.startswith('[') and text.endswith(']'):
        return text
    matches = list(JSON_ARRAY_PATTERN.finditer(text))
    if not matches:
        try:
            start = text.index('['); end = text.rindex(']') + 1
            return text[start:end]
        except Exception:
            return None
    best = max(matches, key=lambda m: len(m.group(0)))
    return best.group(0)

def _normalize_items(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        ticker = (it.get("ticker") or it.get("symbol") or "").upper().strip()
        if not ticker or len(ticker) > 6 or not ticker.isalnum():
            continue
        # expected_gain
        eg_candidates = [it.get('expected_gain'), it.get('gain'), it.get('expected_return')]
        expected_gain = None
        for c in eg_candidates:
            try:
                expected_gain = float(c)
                break
            except Exception:
                continue
        if expected_gain is None:
            continue
        try:
            sentiment = float(it.get('sentiment'))
        except Exception:
            continue
        if not (-50 <= expected_gain <= 200):
            continue
        if not (0.0 <= sentiment <= 1.0):
            continue
        reason = (it.get('reason') or it.get('explanation') or '').strip()
        words = reason.split()
        if len(words) > 50:
            reason = ' '.join(words[:50])
        out.append({
            'ticker': ticker,
            'expected_gain': round(expected_gain, 2),
            'sentiment': round(sentiment, 2),
            'reason': reason
        })
    return out[:10]

def _call_model(model: str, prompt: str) -> Optional[List[Dict[str, Any]]]:
    url = f"{GROK_BASE_URL.rstrip('/')}{API_PATH}"
    headers = {"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a rigorous financial analysis assistant. Output ONLY JSON unless explicitly asked otherwise."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.25,
        "max_tokens": 1800
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT, verify=not GROK_INSECURE)
            if resp.status_code >= 500:
                time.sleep(1.5 * attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
            json_block = _extract_json_array(content)
            if not json_block:
                raise ValueError('Kein JSON Array gefunden')
            parsed = json.loads(json_block)
            norm = _normalize_items(parsed)
            if norm:
                return norm
        except Exception:
            if attempt == MAX_RETRIES:
                return None
            time.sleep(1.2 * attempt)
    return None

def get_top_stocks_prediction() -> List[Dict[str, Any]]:
    if not GROK_API_KEY:
        raise RuntimeError('GROK_API_KEY oder XAI_API_KEY fehlt')
    today = datetime.utcnow().date().isoformat()
    # Wichtig: Kein f-string um das JSON Beispiel (sonst wertet Python {...} als Expression)
    prompt = (
        "Führe eine tiefe Web- und Nachrichten-/X-Sentiment Analyse durch.\n"
        "Liefere die 5 bis 10 US-Aktien (Ticker), die in den nächsten 7 Tagen wahrscheinlich positiv performen.\n"
        "Für jede Aktie Felder:\n"
        "- ticker (nur Symbol)\n"
        "- expected_gain (erwartete prozentuale Kursveränderung +X.Y ohne % Zeichen)\n"
        "- sentiment (0.0 bis 1.0)\n"
        "- reason (~40–50 deutsche Wörter, faktenbasiert, keine Übertreibung)\n\n"
        "Gib AUSSCHLIESSLICH ein JSON Array:\n"
        "[\n"
        "  {\"ticker\":\"AAPL\",\"expected_gain\":2.4,\"sentiment\":0.82,\"reason\":\"...\"},\n"
        "  ...\n"
        "]\n"
        f"Stichdatum: {today}\n"
        "Keine Einleitung, kein Text außerhalb des JSON."
    )
    for model in MODEL_CANDIDATES:
        res = _call_model(model, prompt)
        if res:
            return res
    return []

if __name__ == '__main__':
    try:
        out = get_top_stocks_prediction()
        if not out:
            print('Keine verwertbaren Daten erhalten.')
        else:
            for s in out:
                print(f"{s['ticker']:>6} gain={s['expected_gain']:>6} sentiment={s['sentiment']:.2f} reason={s['reason'][:60]}…")
    except Exception as e:
        print('Fehler:', e)
