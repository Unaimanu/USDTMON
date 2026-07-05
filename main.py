
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone
import requests
import re
import urllib3

# Desactivar advertencias SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="USDT/VES y BCV API")

# Middleware CORS para permitir conexiones desde cualquier origen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cache = {
    "last_update": None,
    "usdt_price": 0.00,
    "bcv_price": 0.00,
    "count": 0,
    "error": None
}

URL_BINANCE = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
HEADERS_BINANCE = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0"
}

def fetch_data():
    error_msg = None
    
    # 1. Obtener precio Binance USDT (Venta = tradeType: SELL)
    try:
        payload = {
            "page": 1, 
            "rows": 20, 
            "payTypes": [], 
            "asset": "USDT", 
            "fiat": "VES", 
            "tradeType": "SELL" # Cambiado a SELL
        }
        r_bin = requests.post(URL_BINANCE, headers=HEADERS_BINANCE, json=payload, timeout=15)
        r_bin.raise_for_status()
        data = r_bin.json()
        ads = data.get("data", []) or []
        
        # Filtramos precios válidos
        prices = [float(ad.get("adv", {}).get("price")) for ad in ads if ad.get("adv", {}).get("price")]
        
        if prices:
            # Seleccionamos el precio máximo porque queremos vender al mejor postor
            cache["usdt_price"] = round(max(prices), 4)
            cache["count"] = len(prices)
        else:
            error_msg = "No se encontraron precios P2P para venta"
    except Exception as e:
        error_msg = f"Error Binance: {str(e)}"

    # 2. Obtener precio Oficial BCV
    try:
        headers_bcv = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r_bcv = requests.get("https://www.bcv.org.ve/", headers=headers_bcv, verify=False, timeout=15)
        r_bcv.raise_for_status()
        
        match = re.search(r'id="dolar"[\s\S]*?([\d]+,[\d]+)', r_bcv.text, re.IGNORECASE)
        
        if match:
            precio_str = match.group(1).replace(',', '.')
            cache["bcv_price"] = round(float(precio_str), 2)
        else:
            raise ValueError("No se detectó la estructura del precio en el HTML del BCV")
            
    except Exception as e:
        error_bcv = f"Error BCV: {str(e)}"
        error_msg = f"{error_msg} | {error_bcv}" if error_msg else error_bcv

    cache["error"] = error_msg
    cache["last_update"] = datetime.now(timezone.utc).isoformat()

scheduler = BackgroundScheduler()
scheduler.add_job(fetch_data, "interval", minutes=1)
scheduler.start()

@app.on_event("startup")
def startup_event():
    fetch_data()

@app.get("/v1/usdt")
def get_rates():
    return {
        "last_update": cache["last_update"],
        "usdt_price": cache["usdt_price"],
        "bcv_price": cache["bcv_price"],
        "ads_used": cache["count"],
        "error": cache["error"]
    }
    
