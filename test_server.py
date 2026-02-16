import requests

BASE_URL = "http://127.0.0.1:8000"

def test_endpoint(endpoint):
    try:
        response = requests.get(f"{BASE_URL}{endpoint}")
        print(f"{endpoint}: {response.status_code} - {response.text[:100]}...")
        return response.json()
    except Exception as e:
        print(f"{endpoint}: ERRO - {e}")
        return None

print("=== TESTANDO ENDPOINTS ===")
test_endpoint("/api/debug")
test_endpoint("/api/balances") 
test_endpoint("/api/orders?state=pending")
test_endpoint("/api/mids?pair=SOL-USDT")