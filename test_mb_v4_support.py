import asyncio
import time
from exchanges.adapters import MBV4Adapter
import configparser

async def main():
    print("=== TESTE DIAGNOSTICO MERCADO BITCOIN V4 (SUPORTE) ===")
    cfg = configparser.ConfigParser()
    cfg.read("config.txt")
    
    adapter = MBV4Adapter(cfg)
    adapter.enabled = True
    print("\n--- PROBLEMA 1: OAUTH2 /authorize vs /oauth2/token ---")
    try:
        await adapter._authorize()
        print("[SUCESSO] Token obtido:", adapter.token)
    except Exception as e:
        print("[ERRO] Falha no OAuth2:", str(e))
        print(">> Confirmado erro 403 / CDN Block (Cloudflare 1010) ou endpoint incorreto.")

    print("\n--- PROBLEMA 2: TIMESTAMP / TIME SERVER ---")
    print("O MBV4Adapter nao esta enviando timestamp manual no OAuth2. O block pode estar ocorrendo aqui.")
    
    print("\n--- PROBLEMA 3: ROTAS DE ORDENS (404 Not Found) ---")
    if adapter.token:
        try:
            orders = await adapter.fetch_open_orders()
            print(f"[SUCESSO] Retornou {len(orders)} ordens")
        except Exception as e:
            print("[ERRO] Rota de ordens:", str(e))
    else:
        print("[ERRO] Nao foi possivel testar rotas de ordens pois o token nao foi emitido.")
        
    await adapter.close()

if __name__ == "__main__":
    asyncio.run(main())
