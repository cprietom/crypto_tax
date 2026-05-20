import yfinance as yf
import pandas as pd
import sys
import os
import warnings
import urllib.request
import json
from contextlib import redirect_stdout, redirect_stderr
from datetime import timedelta

warnings.filterwarnings("ignore")

# --- MEMORIA Y MAPEOS ---
price_cache = {}
market_data_cache = {}

TICKER_MAP = {
    'XBT': 'BTC', 'ZEUR': 'EUR', 'ZUSD': 'USD', 'ZGBP': 'GBP',
    'XETH': 'ETH', 'XXRP': 'XRP', 'XLTC': 'LTC', 'XXLM': 'XLM',
    'IOTA': 'IOTA',
    'MIOTA': 'IOTA', # Si el CSV origen dice MIOTA, lo normaliza a IOTA
    'REPV2': 'REP'
}

STABLECOINS = ["USD", "USDC", "USDT", "BUSD", "DAI", "PYUSD"]

def normalize_ticker(symbol):
    s = str(symbol).upper().strip()
    return TICKER_MAP.get(s, s)

def split_pair(pair):
    """Separa un par pegado (ej: BTCUSDC) en base y cotizada"""
    pair = pair.upper().strip()

    # Lista limpia de un solo nivel con las monedas de cotización comunes
    quotes = ["EUR", "USD", "USDC", "USDT", "BTC", "ETH", "BNB", "BUSD", "ZEUR", "ZUSD"]

    # Ordenamos de mayor a menor longitud para que detecte antes USDC/USDT que USD
    for q in sorted(quotes, key=len, reverse=True):
        if pair.endswith(q):
            return pair[:-len(q)], q

    return pair, "USD"

def fetch_yahoo_bulk(ticker, dt_obj):
    """Descarga datos de Yahoo Finance de forma limpia silenciando errores nativos."""
    import warnings
    warnings.filterwarnings("ignore")

    # Normalizar cruces de divisas tradicionales
    if ticker == "USD-EUR":
        ticker = "EURUSD=X"

    if ticker in market_data_cache:
        df_period = market_data_cache[ticker]
    else:
        with open(os.devnull, 'w') as fnull:
            with redirect_stdout(fnull), redirect_stderr(fnull):
                try:
                    t = yf.Ticker(ticker)

                    # Ventana temporal alrededor de la transacción histórica
                    start_dt = dt_obj - timedelta(days=30)
                    end_dt = dt_obj + timedelta(days=30)
                    start_str = start_dt.strftime('%Y-%m-%d')
                    end_str = end_dt.strftime('%Y-%m-%d')

                    df_period = t.history(start=start_str, end=end_str, interval="1d")

                    # CORRECCIÓN CRÍTICA: Validamos si el dataframe no tiene filas reales
                    if df_period is None or df_period.empty or len(df_period) == 0:
                        # Si falla, pedimos el histórico completo para asegurar que baje el año 2021
                        df_period = t.history(period="max", interval="1d")

                    market_data_cache[ticker] = df_period
                except Exception:
                    market_data_cache[ticker] = pd.DataFrame()
                    return None

    if df_period is None or df_period.empty or len(df_period) == 0:
        return None

    # Procesado de fechas eliminando zonas horarias para evitar conflictos de casamiento
    df_period = df_period.copy()
    df_period.index = pd.to_datetime(df_period.index, utc=True).tz_localize(None)
    target_date = pd.to_datetime(dt_obj).tz_localize(None).date()

    # 1. Buscar coincidencia exacta del día de la transacción
    match = df_period[df_period.index.date == target_date]
    if not match.empty:
        return float(match['Close'].iloc[0])

    # 2. Si no hay día exacto (fines de semana en Forex), buscar el más cercano en un entorno de 7 días
    try:
        target_datetime = pd.to_datetime(dt_obj).tz_localize(None)
        idx = df_period.index.get_indexer([target_datetime], method='nearest')[0]
        if idx != -1:
            found_date = df_period.index[idx].date()
            if abs((found_date - target_date).days) <= 10:
                return float(df_period['Close'].iloc[idx])
    except Exception:
        pass

    return None

def fetch_binance_fallback(asset, dt_obj):
    # Solo aplicamos este fallback para IOTA
    if asset not in ["IOTA", "MIOTA"]:
        return None

    symbol = "IOTAUSDT"

    # Binance usa milisegundos. Restamos 24h para asegurarnos de capturar la vela diaria correcta
    target_ms = int(dt_obj.timestamp() * 1000)
    start_ms = target_ms - 86400000

    # Solicitamos velas de 1 día (1d)
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&startTime={start_ms}&limit=2"
    print(f"url:  {url}")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            if data and len(data) > 0:
                # El formato de Binance es:
                # [Open time, Open, High, Low, Close, Volume, ...]
                # El índice 4 corresponde al precio de cierre (Close)
                return float(data[0][4])
    except Exception as e:
        print(f"Error en Binance fallback: {e}")
        pass

    return None

def get_price_info(asset, target_currency, dt_obj):
    """
    Motor de precios: Resuelve consultas directas, Fiat y Triangula altcoins.
    """
    asset = normalize_ticker(asset)
    target_currency = normalize_ticker(target_currency)

    if asset == target_currency:
        return 1.0

    cache_key = f"{asset}_{target_currency}_{dt_obj.strftime('%Y%m%d_%H')}"
    if cache_key in price_cache:
        return price_cache[cache_key]

    # 1. CASO FIAT PURO: USD/EUR u otras combinaciones inversas fijas
    if asset == "USD" and target_currency == "EUR":
        precio_eur_usd = fetch_yahoo_bulk("EURUSD=X", dt_obj)
        if precio_eur_usd and precio_eur_usd > 0:
            precio_final = 1.0 / precio_eur_usd
            price_cache[cache_key] = precio_final
            return precio_final

    if asset == "EUR" and target_currency == "USD":
        precio_eur_usd = fetch_yahoo_bulk("EURUSD=X", dt_obj)
        if precio_eur_usd and precio_eur_usd > 0:
            price_cache[cache_key] = precio_eur_usd
            return precio_eur_usd

    # 2. CASO DIRECTO: Par nativo en Yahoo (ej: BTC-EUR, BTC-USD)
    ticker_directo = f"{asset}-{target_currency}"
    precio = fetch_yahoo_bulk(ticker_directo, dt_obj)
    if precio and precio > 0:
        price_cache[cache_key] = precio
        return precio

    if target_currency in ["EUR", "USD", "GBP"]:
        ticker_fiat = f"{asset}{target_currency}=X"
        precio = fetch_yahoo_bulk(ticker_fiat, dt_obj)
        if precio and precio > 0:
            price_cache[cache_key] = precio
            return precio

    # 3. TRIANGULACIÓN: Fallback si no existe el par directo (Ej: IOTA-USDC)
    ticker_a_buscar = f"{asset}-USD"
    p_asset_usd = fetch_yahoo_bulk(ticker_a_buscar, dt_obj)
    if p_asset_usd and p_asset_usd > 0:
        # Caso A: Se pide en EUR pero solo tenemos el precio en USD
        if target_currency == "EUR":
            p_eur_usd = fetch_yahoo_bulk("EURUSD=X", dt_obj)
            p_usd_eur = (1.0 / p_eur_usd) if (p_eur_usd and p_eur_usd > 0) else 0.83
            precio_final = p_asset_usd * p_usd_eur
            price_cache[cache_key] = precio_final
            return precio_final

        # Caso B: Se pide contra una Stablecoin indexada al USD (USDC, USDT, etc.)
        elif target_currency in STABLECOINS:
            price_cache[cache_key] = p_asset_usd
            return p_asset_usd


        # Caso C: Paridad cruzada entre criptos
        else:

            p_target_usd = fetch_yahoo_bulk(f"{target_currency}-USD", dt_obj)
            if p_target_usd and p_target_usd > 0:
                precio_final = p_asset_usd / p_target_usd
                price_cache[cache_key] = precio_final
                return precio_final

    fallback_price = fetch_binance_fallback(asset, dt_obj)
    if fallback_price:
        # Si el target es EUR, hacemos la conversión desde el proxy USD(T)
        if target_currency == "EUR":
            p_eur_usd = fetch_yahoo_bulk("EURUSD=X", dt_obj)
            p_usd_eur = (1.0 / p_eur_usd) if (p_eur_usd and p_eur_usd > 0) else 0.83
            precio_final = fallback_price * p_usd_eur
            price_cache[cache_key] = precio_final
            return precio_final

        # Si el target es USD, USDC, etc. devolvemos directamente
        price_cache[cache_key] = fallback_price
        return fallback_price

    price_cache[cache_key] = 0.0
    return 0.0

def find_col(columns, keywords):
    for c in columns:
        c_clean = str(c).lower().replace('\n', ' ').strip()
        if all(k.lower() in c_clean for k in keywords):
            return c
    return None

def modo_csv(file_path):
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        print(f"❌ Error: {e}"); return

    cols = df.columns.tolist()
    c_time = find_col(cols, ['Timestamp']) or find_col(cols, ['Date'])
    c_asset_base = find_col(cols, ['Asset Base'])
    c_amount = find_col(cols, ['Amount in/out'])
    c_spot_price_orig = find_col(cols, ['Spot Price'])
    c_fee_val = find_col(cols, ['Crypto Fee'])
    c_fee_asset = find_col(cols, ['Crypto-fee asset'])

    df['dt_utc'] = pd.to_datetime(df[c_time], dayfirst=True, utc=True, errors='coerce')
    if df['dt_utc'].isna().sum() > len(df) * 0.5:
        df['dt_utc'] = pd.to_datetime(df[c_time], dayfirst=False, utc=True, errors='coerce')

    res_spot_eur, res_amount_eur, res_fee_eur = [], [], []

    print(f"🚀 Procesando {len(df)} filas (incluyendo depósitos/retiros)...")
    for i, row in enumerate(df.to_dict('records')):
        dt = row['dt_utc']
        if pd.isna(dt):
            res_spot_eur.append(0); res_amount_eur.append(0); res_fee_eur.append(0)
            continue

        base_asset = row.get(c_asset_base)
        p_base_eur = get_price_info(base_asset, 'EUR', dt)
        amount_eur = float(row.get(c_amount, 0) or 0) * p_base_eur

        raw_price = row.get(c_spot_price_orig)
        if pd.isna(raw_price) or raw_price is None or float(raw_price) <= 0:
            spot_price_eur = p_base_eur
        else:
            orig_price = float(raw_price)
            quote_asset = row.get(find_col(cols, ['Asset Quote']), 'USD')
            p_quote_eur = get_price_info(quote_asset, 'EUR', dt)
            spot_price_eur = orig_price * p_quote_eur

        res_spot_eur.append(spot_price_eur)
        res_amount_eur.append(amount_eur)

        f_val = float(row.get(c_fee_val, 0) or 0)
        f_asset = row.get(c_fee_asset)
        fee_eur = f_val * get_price_info(f_asset, 'EUR', dt) if f_asset and f_val > 0 else 0
        res_fee_eur.append(fee_eur)

        if (i + 1) % 50 == 0 or (i + 1) == len(df):
            sys.stdout.write(f"\r📊 PROGRESO: {((i+1)/len(df))*100:6.2f}%")
            sys.stdout.flush()

    df['Spot Price (EUR)'] = res_spot_eur
    df['Amount out/in (EUR)'] = res_amount_eur
    df['FIAT Fee'] = res_fee_eur

    out = file_path.replace('.csv', '_PROCESADO.csv')
    df.drop(columns=['dt_utc']).to_csv(out, index=False)
    print(f"\n✅ Completado: {out}")

def modo_single(pair, date_str):
    dt = pd.to_datetime(date_str, utc=True, errors='coerce')
    if pd.isna(dt):
        print(f"❌ Error: No se pudo entender la fecha '{date_str}'")
        return

    base, quote = split_pair(pair)
    precio = get_price_info(base, quote, dt)

    if precio > 0:
        print(f"\n✅ RESULTADO:")
        print(f"Par:     {base}/{quote}")
        print(f"Fecha:   {dt.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"Precio:  {precio:,.8f} {quote}")
    else:
        print(f"❌ No se pudo obtener el precio para {pair}: {precio}.")

if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 1 and args[0].endswith('.csv'):
        modo_csv(args[0])
    elif len(args) >= 2:
        modo_single(args[0], " ".join(args[1:]))
    else:
        print("Uso:")
        print("  Procesar CSV:   python3 crypto_tool.py archivo.csv")
        print("  Consulta única: python3 crypto_tool.py BTCUSDC \"2026-03-08 12:13:17\"")