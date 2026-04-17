import requests

BASE_URL = "http://127.0.0.1:8000"

def probe_endpoint(endpoint):
    try:
        response = requests.get(f"{BASE_URL}{endpoint}")
        print(f"{endpoint}: {response.status_code} - {response.text[:100]}...")
        return response.json()
    except Exception as e:
        print(f"{endpoint}: ERRO - {e}")
        return None

if __name__ == "__main__":
    print("=== TESTANDO ENDPOINTS ===")
    probe_endpoint("/api/debug")
    probe_endpoint("/api/balances")
    probe_endpoint("/api/orders?state=pending")
    probe_endpoint("/api/mids?pair=SOL-USDT")
