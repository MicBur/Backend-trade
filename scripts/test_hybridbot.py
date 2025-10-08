#!/usr/bin/env python3
"""
HybridBot API Testing Script
Tests alle neuen Bot-Endpoints
"""

import requests
import time
import sys
from typing import Optional

# Base URL
BASE_URL = "http://localhost:8000"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_test(name: str, passed: bool, details: Optional[str] = None):
    """Print test result"""
    status = f"{Colors.GREEN}✅ PASS{Colors.END}" if passed else f"{Colors.RED}❌ FAIL{Colors.END}"
    print(f"{status} - {name}")
    if details:
        print(f"     {Colors.YELLOW}{details}{Colors.END}")

def test_bot_status():
    """Test GET /bot/status"""
    try:
        response = requests.get(f"{BASE_URL}/bot/status")
        passed = response.status_code == 200 and "running" in response.json()
        print_test("GET /bot/status", passed, f"Status: {response.status_code}")
        return passed
    except Exception as e:
        print_test("GET /bot/status", False, str(e))
        return False

def test_bot_start():
    """Test POST /bot/start"""
    try:
        payload = {
            "aggressiveness": 5,
            "max_amount": 1000.0,
            "reserve_pct": 0.2
        }
        response = requests.post(f"{BASE_URL}/bot/start", json=payload)
        data = response.json()
        passed = response.status_code == 200 and data.get("started") == True
        print_test("POST /bot/start", passed, f"Started: {data.get('started')}")
        return passed
    except Exception as e:
        print_test("POST /bot/start", False, str(e))
        return False

def test_bot_start_duplicate():
    """Test POST /bot/start (should fail wenn already running)"""
    try:
        payload = {
            "aggressiveness": 7,
            "max_amount": 500.0,
            "reserve_pct": 0.3
        }
        response = requests.post(f"{BASE_URL}/bot/start", json=payload)
        # Should return 409 Conflict
        passed = response.status_code == 409
        print_test("POST /bot/start (duplicate)", passed, f"Expected 409, got {response.status_code}")
        return passed
    except Exception as e:
        print_test("POST /bot/start (duplicate)", False, str(e))
        return False

def test_bot_status_running():
    """Test GET /bot/status (should be running)"""
    try:
        response = requests.get(f"{BASE_URL}/bot/status")
        data = response.json()
        passed = response.status_code == 200 and data.get("running") == True
        details = f"Running: {data.get('running')}, Aggressiveness: {data.get('aggressiveness')}"
        print_test("GET /bot/status (running)", passed, details)
        return passed
    except Exception as e:
        print_test("GET /bot/status (running)", False, str(e))
        return False

def test_bot_stop():
    """Test POST /bot/stop"""
    try:
        response = requests.post(f"{BASE_URL}/bot/stop")
        data = response.json()
        passed = response.status_code == 200 and data.get("stopped") == True
        print_test("POST /bot/stop", passed, f"Stopped: {data.get('stopped')}")
        return passed
    except Exception as e:
        print_test("POST /bot/stop", False, str(e))
        return False

def test_bot_stop_duplicate():
    """Test POST /bot/stop (should fail when not running)"""
    try:
        response = requests.post(f"{BASE_URL}/bot/stop")
        # Should return 409 Conflict
        passed = response.status_code == 409
        print_test("POST /bot/stop (duplicate)", passed, f"Expected 409, got {response.status_code}")
        return passed
    except Exception as e:
        print_test("POST /bot/stop (duplicate)", False, str(e))
        return False

def test_alpaca_connect_missing_creds():
    """Test POST /bot/alpaca/connect (should fail with invalid creds)"""
    try:
        payload = {
            "api_key": "INVALID_KEY",
            "secret": "INVALID_SECRET",
            "paper": True
        }
        response = requests.post(f"{BASE_URL}/bot/alpaca/connect", json=payload)
        # Should return 401 or 500
        passed = response.status_code in [401, 500, 501]
        print_test("POST /bot/alpaca/connect (invalid)", passed, f"Status: {response.status_code}")
        return passed
    except Exception as e:
        print_test("POST /bot/alpaca/connect (invalid)", False, str(e))
        return False

def test_bot_portfolio_no_connection():
    """Test GET /bot/portfolio (should fail without Alpaca connection)"""
    try:
        response = requests.get(f"{BASE_URL}/bot/portfolio")
        # Should return 404 or 501
        passed = response.status_code in [404, 501]
        print_test("GET /bot/portfolio (no connection)", passed, f"Status: {response.status_code}")
        return passed
    except Exception as e:
        print_test("GET /bot/portfolio (no connection)", False, str(e))
        return False

def test_alpaca_disconnect():
    """Test DELETE /bot/alpaca/disconnect"""
    try:
        response = requests.delete(f"{BASE_URL}/bot/alpaca/disconnect")
        data = response.json()
        passed = response.status_code == 200 and data.get("disconnected") == True
        print_test("DELETE /bot/alpaca/disconnect", passed, f"Status: {response.status_code}")
        return passed
    except Exception as e:
        print_test("DELETE /bot/alpaca/disconnect", False, str(e))
        return False

def main():
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}")
    print("HybridBot API Test Suite")
    print(f"{'='*60}{Colors.END}\n")
    
    print(f"{Colors.BOLD}Testing Base URL: {BASE_URL}{Colors.END}\n")
    
    tests = []
    
    # Test Sequence
    print(f"\n{Colors.BOLD}🔍 Phase 1: Initial Status{Colors.END}")
    tests.append(test_bot_status())
    
    print(f"\n{Colors.BOLD}🚀 Phase 2: Start Bot{Colors.END}")
    tests.append(test_bot_start())
    time.sleep(1)  # Wait for bot to start
    tests.append(test_bot_status_running())
    tests.append(test_bot_start_duplicate())
    
    print(f"\n{Colors.BOLD}🛑 Phase 3: Stop Bot{Colors.END}")
    tests.append(test_bot_stop())
    time.sleep(1)  # Wait for bot to stop
    tests.append(test_bot_stop_duplicate())
    
    print(f"\n{Colors.BOLD}🔐 Phase 4: Alpaca Integration{Colors.END}")
    tests.append(test_alpaca_connect_missing_creds())
    tests.append(test_bot_portfolio_no_connection())
    tests.append(test_alpaca_disconnect())
    
    # Summary
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}")
    print("Test Summary")
    print(f"{'='*60}{Colors.END}\n")
    
    passed = sum(tests)
    total = len(tests)
    percentage = (passed / total * 100) if total > 0 else 0
    
    print(f"Total Tests:  {total}")
    print(f"{Colors.GREEN}✅ Passed:    {passed}{Colors.END}")
    print(f"{Colors.RED}❌ Failed:    {total - passed}{Colors.END}")
    print(f"Success Rate: {percentage:.1f}%\n")
    
    # Swagger Link
    print(f"{Colors.BOLD}📚 Swagger UI:{Colors.END}")
    print(f"   {BASE_URL}/docs\n")
    
    # Exit code
    sys.exit(0 if passed == total else 1)

if __name__ == "__main__":
    main()
