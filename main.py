
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

# Middleware CORS para permitir peticiones desde cualquier origen
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
    "merchant_filter": None,
    "error": None
}

URL_BINANCE = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
HEADERS_BINANCE = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0"
}

def fetch_binance_prices(trade_type, pro_merchant_only, rows=10):
    """Consulta Binance P2P y devuelve la lista de precios de los anuncios encontrados,
    en el mismo orden en que Binance los entrega (mejor precio primero)."""
    payload = {
        "page": 1,
        "rows": rows,
        "payTypes": [],
        "asset": "USDT",
        "fiat": "VES",
        "tradeType": trade_type,
        "proMerchantAds": pro_merchant_only
    }
    r_bin = requests.post(URL_BINANCE, headers=HEADERS_BINANCE, json=payload, timeout=15)
    r_bin.raise_for_status()
    data = r_bin.json()
    ads = data.get("data", []) or []
    return [float(ad.get("adv", {}).get("price")) for ad in ads if ad.get("adv", {}).get("price")]


def fetch_data():
    error_msg = None

    # 1. Obtener precio Binance USDT (Venta de USDT)
    # Preferimos solo comerciantes verificados, pero en el lado "Vender" a veces
    # no hay ninguno activo en el momento de la consulta. Si eso pasa, hacemos
    # fallback a la lista general para no quedarnos sin dato.
    try:
        prices = fetch_binance_prices("SELL", pro_merchant_only=True)
        used_fallback = False

        if not prices:
            prices = fetch_binance_prices("SELL", pro_merchant_only=False)
            used_fallback = True

        if prices:
            # Promedio de los primeros N anuncios (mejor precio primero según Binance).
            # Esto diluye cualquier anuncio puntual con precio atípico en vez de
            # depender de un único valor máximo.
            N = 7
            top_n = prices[:N]
            avg_price = sum(top_n) / len(top_n)
            cache["usdt_price"] = round(avg_price, 4)
            cache["count"] = len(top_n)
            cache["merchant_filter"] = not used_fallback
        else:
            error_msg = "No se encontraron anuncios de venta (ni con ni sin filtro de comerciante)"
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
            raise ValueError("No se detectó el precio en la web del BCV")

    except Exception as e:
        error_bcv = f"Error BCV: {str(e)}"
        error_msg = f"{error_msg} | {error_bcv}" if error_msg else error_bcv

    cache["error"] = error_msg
    cache["last_update"] = datetime.now(timezone.utc).isoformat()

# Configuración del scheduler
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
        "merchant_filter": cache["merchant_filter"],
        "error": cache["error"]
    }
    
