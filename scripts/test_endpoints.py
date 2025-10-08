#!/usr/bin/env python3
"""
QBot API Endpoint Tester
Automatischer Test aller verfügbaren Endpoints
"""

import requests
import json
from datetime import datetime
from typing import Dict, List, Tuple

BASE_URL = "http://localhost:8000"
EXTERNAL_URL = "http://91.99.236.5:8000"

# Verwende externe URL wenn lokal nicht erreichbar
try:
    requests.get(f"{BASE_URL}/health", timeout=2)
    API_URL = BASE_URL
    print(f"✅ Using LOCAL API: {API_URL}")
except:
    API_URL = EXTERNAL_URL
    print(f"🌐 Using EXTERNAL API: {API_URL}")

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def test_endpoint(method: str, path: str, params: Dict = None, json_data: Dict = None) -> Tuple[bool, int, str, dict]:
    """Test einen einzelnen Endpoint"""
    url = f"{API_URL}{path}"
    
    try:
        if method == "GET":
            response = requests.get(url, params=params, timeout=10)
        elif method == "POST":
            response = requests.post(url, json=json_data, timeout=10)
        else:
            return False, 0, "Unsupported method", {}
        
        status_code = response.status_code
        success = 200 <= status_code < 300
        
        try:
            data = response.json()
        except:
            data = {"raw": response.text[:200]}
        
        return success, status_code, response.reason, data
        
    except requests.exceptions.Timeout:
        return False, 0, "Timeout", {}
    except requests.exceptions.ConnectionError:
        return False, 0, "Connection Error", {}
    except Exception as e:
        return False, 0, str(e), {}

def main():
    print(f"\n{'='*60}")
    print(f"🤖 QBot API Endpoint Tester")
    print(f"{'='*60}\n")
    print(f"API URL: {API_URL}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    endpoints = [
        # Core
        ("GET", "/", None, None, "Root Endpoint"),
        ("GET", "/health", None, None, "Health Check"),
        
        # Portfolio
        ("GET", "/portfolio", None, None, "Portfolio Overview"),
        ("GET", "/positions", None, None, "Active Positions"),
        ("GET", "/trades", {"limit": 5}, None, "Recent Trades"),
        ("GET", "/portfolio/summary", None, None, "Portfolio Summary (Legacy)"),
        ("GET", "/portfolio/positions", None, None, "Positions (Legacy)"),
        ("GET", "/trade/status", None, None, "Trading Status"),
        
        # Training
        ("GET", "/training/status", None, None, "Training Status"),
        ("GET", "/training/models", None, None, "Trained Models"),
        ("GET", "/training/history", None, None, "Training History"),
        # POST start wird übersprungen im Auto-Test
        
        # Market Data
        ("GET", "/market/latest/AAPL", None, None, "Latest Price (AAPL)"),
        ("GET", "/market/data/AAPL", {"timeframe": "15min", "limit": 10}, None, "OHLCV Data (AAPL 15min)"),
        ("GET", "/market/ohlcv/AAPL/multi", {"timeframes": "15min,1hour", "limit": 5}, None, "Multi-Timeframe (AAPL)"),
        ("GET", "/market/top-movers", {"limit": 3}, None, "Top Movers"),
        
        # Performance
        ("GET", "/portfolio/performance", {"days": 7}, None, "Performance (7 days)"),
        ("GET", "/portfolio/performance/summary", {"limit": 10}, None, "Performance Summary"),
        
        # AI & System
        ("GET", "/ai/grok-insights", {"limit": 3}, None, "Grok AI Insights"),
        ("GET", "/system/database-stats", None, None, "Database Statistics"),
    ]
    
    results = []
    passed = 0
    failed = 0
    
    print(f"{'#':<3} {'Method':<6} {'Endpoint':<45} {'Status':<8} {'Code':<5} {'Description'}")
    print(f"{'-'*90}")
    
    for idx, (method, path, params, json_data, description) in enumerate(endpoints, 1):
        success, status_code, reason, data = test_endpoint(method, path, params, json_data)
        
        if success:
            passed += 1
            status_str = f"{Colors.GREEN}✅ PASS{Colors.END}"
            code_str = f"{Colors.GREEN}{status_code}{Colors.END}"
        else:
            failed += 1
            status_str = f"{Colors.RED}❌ FAIL{Colors.END}"
            code_str = f"{Colors.RED}{status_code if status_code else 'N/A'}{Colors.END}"
        
        # Kürze Path für Anzeige
        display_path = (path[:42] + "...") if len(path) > 45 else path
        
        print(f"{idx:<3} {method:<6} {display_path:<45} {status_str:<16} {code_str:<13} {description}")
        
        results.append({
            "endpoint": path,
            "method": method,
            "params": params,
            "success": success,
            "status_code": status_code,
            "reason": reason,
            "description": description
        })
    
    # Summary
    print(f"\n{'-'*90}")
    print(f"\n📊 Test Summary:")
    print(f"   Total Endpoints: {len(endpoints)}")
    print(f"   {Colors.GREEN}✅ Passed: {passed}{Colors.END}")
    print(f"   {Colors.RED}❌ Failed: {failed}{Colors.END}")
    print(f"   Success Rate: {(passed/len(endpoints)*100):.1f}%")
    
    # Failed Details
    if failed > 0:
        print(f"\n{Colors.RED}❌ Failed Endpoints:{Colors.END}")
        for result in results:
            if not result['success']:
                print(f"   - {result['method']} {result['endpoint']}")
                print(f"     Status: {result['status_code']} - {result['reason']}")
    
    # Swagger UI Check
    print(f"\n🔗 Interactive Documentation:")
    print(f"   Swagger UI: {API_URL}/docs")
    print(f"   ReDoc:      {API_URL}/redoc")
    print(f"   OpenAPI:    {API_URL}/openapi.json")
    
    print(f"\n{'='*60}")
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    # Exit code
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    exit(main())
