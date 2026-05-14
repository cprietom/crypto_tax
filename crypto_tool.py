import yfinance as yf
import pandas as pd
import sys
import time
import warnings
import os
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone

warnings.filterwarnings("ignore")

# --- MEMORIA RAM ---
price_cache = {}
market_data_cache = {}

# Lista de stablecoins vinculadas al USD
STABLECOINS = ["USD", "USDC", "USDT", "BUSD", "DAI"]

def get_ticker_candidates(symbol: str):
    symbol = str(symbol).upper()
    mapeo = {
        'IOTA': ['IOTA-USD', 'MIOTA-USD'],
        'DOT': ['DOT1-USD', 'DOT-USD'],
        'MATIC': ['POL-USD', 'MATIC-USD'],
        'COMP': ['COMP-USD', 'COMP1-USD'],
        'LUNA': ['LUNC-USD', 'LUNA1-USD'],
        'EUR': ['EURUSD=X']
    }
    return mapeo.get(symbol, [f"{symbol}-USD"])

def fetch_yahoo_bulk(ticker, dt_obj):
    try:
        chunk_id = f"{ticker}_{dt_obj.year}_{dt_obj.month}"

        if chunk_id not in market_data_cache:
            # Ampliamos el rango de descarga para asegurar que asof() tenga datos previos
            start_dt = datetime(dt_obj.year, dt_obj.month, 1) - timedelta(days=10)
            if dt_obj.month == 12:
                end_dt = datetime(dt_obj.year + 1, 1, 1) + timedelta(days=10)
            else:
                end_dt = datetime(dt_obj.year, dt_obj.month + 1, 1) + timedelta(days=10)

            with open(os.devnull, 'w') as f, redirect_stdout(f), redirect_stderr(f):
                # Usamos 1d para datos antiguos y 1h para recientes
                dias_dif = (datetime.now(timezone.utc) - dt_obj.replace(tzinfo=timezone.utc)).days
                intervalo = "1h" if dias_dif < 700 else "1d"

                df = yf.download(ticker, start=start_dt.strftime('%Y-%m-%d'),
                                 end=end_dt.strftime('%Y-%m-%d'),
                                 interval=intervalo, progress=False, group_by='column')

            if df.empty or 'Close' not in df.columns:
                if ticker == "EURUSD=X":
                    df = yf.download(ticker, period="1mo", interval="1d", progress=False)

                if df.empty:
                    market_data_cache[chunk_id] = None
                    return None

            # Limpieza de MultiIndex si existe
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC')
            else:
                df.index = df.index.tz_convert('UTC')

            # Reindexar para cubrir huecos (fines de semana en Forex)
            df = df.sort_index()
            new_index = pd.date_range(df.index.min(), df.index.max(), freq='h')
            df = df.reindex(new_index, method='ffill')
            market_data_cache[chunk_id] = df

        data = market_data_cache[chunk_id]
        if data is None: return None

        # Intentar obtener el precio exacto o el más cercano anterior
        price_val = data['Close'].asof(dt_obj)
        if pd.isna(price_val):
            idx = data.index.get_indexer([dt_obj], method='nearest')[0]
            price_val = data.iloc[idx]['Close']

        return float(price_val)
    except Exception:
        return None

def get_price_info(pair: str, dt_obj):
    if pd.isna(pair) or pd.isna(dt_obj): return None
    pair = str(pair).upper()

    cache_key = f"{pair}-{dt_obj.strftime('%Y%m%d%H%M')}"
    if cache_key in price_cache: return price_cache[cache_key]

    # Identificar base y target (ej: BTC y USDC)
    quote_symbols = ["EUR", "USD", "USDC", "USDT", "BTC", "ETH", "BNB", "BUSD"]
    target, crypto = "", ""
    for q in sorted(quote_symbols, key=len, reverse=True): # Buscar los más largos primero (USDC antes que USD)
        if pair.endswith(q):
            target, crypto = q, pair[:-len(q)]
            break

    if not crypto: return None
    if target == crypto:
        return {"pair": pair, "price": 1.0, "target": target, "date": dt_obj.strftime('%Y-%m-%d %H:%M:%S')}

    # 1. Obtener EURUSD para conversiones finales si se requiere EUR
    eur_rate = fetch_yahoo_bulk("EURUSD=X", dt_obj)

    # 2. Obtener precio Crypto en USD
    if crypto in STABLECOINS:
        p_usd = 1.0
    else:
        p_usd = fetch_yahoo_bulk(f"{crypto}-USD", dt_obj)

    # 3. Calcular precio final respecto al target
    final_price = 0
    if p_usd:
        if target == "EUR":
            if eur_rate: final_price = p_usd / eur_rate
        elif target in STABLECOINS:
            final_price = p_usd # Asumimos paridad 1:1 si el target es stablecoin
        else:
            # Si el target es otra crypto (ej: ETH en el par BTCETH)
            p_target_usd = fetch_yahoo_bulk(f"{target}-USD", dt_obj)
            if p_target_usd and p_target_usd > 0:
                final_price = p_usd / p_target_usd

    result = {
        "pair": pair, "crypto": crypto, "target": target,
        "date": dt_obj.strftime('%Y-%m-%d %H:%M:%S'), "price": final_price
    }
    price_cache[cache_key] = result
    return result

def modo_csv(file_path):
    start_time = time.time()
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        print(f"❌ Error al leer el CSV: {e}")
        return

    col_quote = 'Asset Quote\nSpot-priced asset'
    col_fee = 'Crypto-fee asset'

    df['dt_utc'] = pd.to_datetime(df['Timestamp'], utc=True, dayfirst=True, errors='coerce')
    precios_quote, precios_fee = [], []
    records = df.to_dict('records')

    print(f"🚀 Procesando {len(df)} filas...")
    for i, row in enumerate(records):
        dt = row['dt_utc']

        # Buscamos el valor en EUR para las columnas solicitadas
        res_q = get_price_info(f"{row.get(col_quote)}EUR", dt)
        res_f = get_price_info(f"{row.get(col_fee)}EUR", dt)

        precios_quote.append(res_q['price'] if res_q else 0)
        precios_fee.append(res_f['price'] if res_f else 0)

        if (i + 1) % 10 == 0 or (i + 1) == len(df):
            elapsed = time.time() - start_time
            avg_speed = (i + 1) / elapsed
            eta = (len(df) - (i + 1)) / avg_speed
            sys.stdout.write(f"\r📊 PROGRESO: {((i+1)/len(df))*100:6.2f}% | Vel: {avg_speed:6.1f} f/s | ETA: {int(eta//60)}m {int(eta%60)}s ")
            sys.stdout.flush()

    # Cálculo de columnas en EUR
    df['Spot Price (EUR)'] = df['Spot Price'].fillna(0).astype(float) * precios_quote
    df['Amount out/in (EUR)'] = df['Amount out/in'].fillna(0).astype(float) * precios_quote
    df['FIAT Fee'] = df['Crypto Fee'].fillna(0).astype(float) * precios_fee

    output_name = file_path.replace('.csv', '_PROCESADO.csv')
    df.drop(columns=['dt_utc']).to_csv(output_name, index=False)
    print(f"\n✅ Proceso completado. Archivo: {output_name}")

def modo_single(pair, date):
    # Intentar varios formatos de fecha comunes
    dt = pd.to_datetime(date, utc=True, errors='coerce')
    if pd.isna(dt):
        print(f"❌ Error: No se pudo interpretar la fecha '{date}'.")
        return

    res = get_price_info(pair, dt)
    if res and res['price'] > 0:
        print(f"\n✅ PRECIO ENCONTRADO:")
        print(f"Par:    {res['pair']}")
        print(f"Fecha:  {res['date']}")
        print(f"Precio: {res['price']:,.8f} {res['target']}")
    else:
        print(f"\n❌ Error: No se pudo obtener precio para {pair}. Verifica si el activo existe en Yahoo Finance.")

if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 1 and args[0].endswith('.csv'):
        modo_csv(args[0])
    elif len(args) >= 2:
        # Combinar todos los argumentos de fecha en uno solo
        modo_single(args[0], " ".join(args[1:]))
    else:
        print("Uso:")
        print("  CSV:    python3 crypto_tool.py archivo.csv")
        print("  Single: python3 crypto_tool.py BTCUSDC \"2026-03-08 12:13:17\"")