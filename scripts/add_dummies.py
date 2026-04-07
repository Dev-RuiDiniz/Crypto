import os
import sys
from configparser import ConfigParser

# Add current dir to sys.path to find core, etc.
sys.path.append(os.getcwd())

from core.credentials_service import ExchangeCredentialsService

def add_dummies():
    cfg = ConfigParser()
    cfg.read('config.txt')
    # Use the master key we generated
    os.environ["EXCHANGE_CREDENTIALS_MASTER_KEY"] = "5d55baa08e6acd8450349ea89e3150b77b67af2990c9044748efd7f047c2a80c"
    
    service = ExchangeCredentialsService(cfg)
    
    try:
        service.create_credentials(
            tenant_id="default",
            exchange="mercadobitcoin",
            label="Dummy MB",
            api_key="dummy_key",
            api_secret="dummy_secret",
            passphrase=None,
            user_id="antigravity"
        )
        print("MB dummy added.")
    except Exception as e:
        print(f"Error adding MB: {e}")

    try:
        service.create_credentials(
            tenant_id="default",
            exchange="novadax",
            label="Dummy Novadax",
            api_key="dummy_key",
            api_secret="dummy_secret",
            passphrase=None,
            user_id="antigravity"
        )
        print("Novadax dummy added.")
    except Exception as e:
        print(f"Error adding Novadax: {e}")

    try:
        service.create_credentials(
            tenant_id="default",
            exchange="gate",
            label="Dummy Gate",
            api_key="dummy_key",
            api_secret="dummy_secret",
            passphrase=None,
            user_id="antigravity"
        )
        print("Gate dummy added.")
    except Exception as e:
        print(f"Error adding Gate: {e}")

    try:
        service.create_credentials(
            tenant_id="default",
            exchange="mexc",
            label="Dummy MEXC",
            api_key="dummy_key",
            api_secret="dummy_secret",
            passphrase=None,
            user_id="antigravity"
        )
        print("MEXC dummy added.")
    except Exception as e:
        print(f"Error adding MEXC: {e}")

if __name__ == "__main__":
    add_dummies()
