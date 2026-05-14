import yfinance as yf
import pandas as pd
import sys
import time
import warnings
import os
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone

warnings.filterwarnings("ignore")

# --- MEMORIA Y MAPEOS ---
price_cache = {}
market_data_cache = {}

TICKER_MAP = {
    'XBT': 'BTC', 'ZEUR': 'EUR', 'ZUSD': 'USD', 'ZGBP': 'GBP',
    'XETH': 'ETH', 'XXRP': 'XRP', 'XLTC': 'LTC', 'XXLM': 'XLM',
    'MIOTA': 'IOTA', 'IOTA': 'IOTA', 'REPV2': 'REP'
}

STABLECOINS = ["USD", "USDC", "USDT", "BUSD", "DAI", "PYUSD"]

def normalize_ticker(symbol):
    s = str(symbol).upper().strip()
    return TICKER_MAP.get(s, s)

def split_pair(pair):
    """Separa un par pegado (ej: BTCUSDC) en base y cotizada"""
    pair = pair.upper().strip()
    # Lista de monedas de cotización comunes
    quotes = ["EUR", "USD", "USDC", "USDT", "BTC", "ETH", "BNB", "BUSD", "ZEUR", "ZUSD"]
    for q in sorted(quotes, key=len, reverse=True):
        if pair.endswith(q):
            return pair[:-len(q)], q
    return pair, "USD" # Por defecto intenta USD si no reconoce el final

def fetch_yahoo_bulk(ticker, dt_obj):
    try:
        chunk_id = f"{ticker}_{dt_obj.year}_{dt_obj.month}"
        if chunk_id not in market_data_cache:
            start_dt = datetime(dt_obj.year, dt_obj.month, 1) - timedelta(days=10)
            if dt_obj.month == 12:
                end_dt = datetime(dt_obj.year + 1, 1, 1) + timedelta(days=10)
            else:
                end_dt = datetime(dt_obj.year, dt_obj.month + 1, 1) + timedelta(days=10)

            with open(os.devnull, 'w') as f, redirect_stdout(f), redirect_stderr(f):
                dias_dif = (datetime.now(timezone.utc) - dt_obj.replace(tzinfo=timezone.utc)).days
                intervalo = "1h" if dias_dif < 700 else "1d"
                df = yf.download(ticker, start=start_dt.strftime('%Y-%m-%d'),
                                 end=end_dt.strftime('%Y-%m-%d'),
                                 interval=intervalo, progress=False)

            if df.empty:
                market_data_cache[chunk_id] = None
                return None

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC')
            else:
                df.index = df.index.tz_convert('UTC')

            df = df.sort_index()
            new_index = pd.date_range(df.index.min(), df.index.max(), freq='h')
            df = df.reindex(new_index, method='ffill')
            market_data_cache[chunk_id] = df

        data = market_data_cache[chunk_id]
        if data is None: return None

        val = data['Close'].asof(dt_obj)
        if pd.isna(val):
            idx = data.index.get_indexer([dt_obj], method='nearest')[0]
            val = data.iloc[idx]['Close']
        return float(val)
    except:
        return None

def get_price_info(asset, target_currency, dt_obj):
    asset = normalize_ticker(asset)
    target = normalize_ticker(target_currency)

    if asset == target: return 1.0

    cache_key = f"{asset}{target}-{dt_obj.strftime('%Y%m%d%H%M')}"
    if cache_key in price_cache: return price_cache[cache_key]

    eur_usd = fetch_yahoo_bulk("EURUSD=X", dt_obj) or 1.08

    p_usd = 0.0
    if asset == "USD" or asset in STABLECOINS:
        p_usd = 1.0
    elif asset == "EUR":
        p_usd = eur_usd
    else:
        p_usd = fetch_yahoo_bulk(f"{asset}-USD", dt_obj)

    final_price = 0.0
    if p_usd:
        if target == "EUR":
            final_price = p_usd / eur_usd
        elif target == "USD" or target in STABLECOINS:
            final_price = p_usd
        else:
            p_target_usd = fetch_yahoo_bulk(f"{target}-USD", dt_obj)
            if p_target_usd: final_price = p_usd / p_target_usd

    price_cache[cache_key] = final_price
    return final_price

def find_col(columns, keywords):
    for c in columns:
        c_clean = str(c).lower().replace('\n', ' ').strip()
        if all(k.lower() in c_clean for k in keywords):
            return c
    return None

def modo_csv(file_path):
    start_time = time.time()
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        print(f"❌ Error al leer el archivo: {e}")
        return

    cols = df.columns.tolist()
    c_time = find_col(cols, ['Timestamp']) or find_col(cols, ['Date'])
    c_quote_asset = find_col(cols, ['Asset Quote', 'Spot-priced']) or find_col(cols, ['Asset Quote'])
    c_fee_asset = find_col(cols, ['Fee asset'])
    c_spot_price = find_col(cols, ['Spot Price'])
    c_amount = find_col(cols, ['Amount out/in'])
    c_fee_val = find_col(cols, ['Crypto Fee'])

    if not all([c_time, c_quote_asset, c_spot_price]):
        print("❌ Error: Columnas necesarias no detectadas.")
        return

    df['dt_utc'] = pd.to_datetime(df[c_time], dayfirst=True, utc=True, errors='coerce')
    if df['dt_utc'].isna().sum() > len(df) * 0.5:
        df['dt_utc'] = pd.to_datetime(df[c_time], dayfirst=False, utc=True, errors='coerce')

    precios_quote_eur, precios_fee_eur = [], []
    records = df.to_dict('records')

    print(f"🚀 Procesando CSV: {len(df)} filas...")
    for i, row in enumerate(records):
        dt = row['dt_utc']
        if pd.isna(dt):
            precios_quote_eur.append(0); precios_fee_eur.append(0)
            continue

        q_asset = row.get(c_quote_asset, 'EUR')
        precios_quote_eur.append(get_price_info(q_asset, 'EUR', dt))

        f_asset = row.get(c_fee_asset)
        precios_fee_eur.append(get_price_info(f_asset, 'EUR', dt) if f_asset else 0)

        if (i + 1) % 100 == 0 or (i + 1) == len(df):
            sys.stdout.write(f"\r📊 PROGRESO: {((i+1)/len(df))*100:6.2f}% | Fila: {i+1}/{len(df)}")
            sys.stdout.flush()

    df['Spot Price (EUR)'] = df[c_spot_price].fillna(0).astype(float) * precios_quote_eur
    df['Amount out/in (EUR)'] = df[c_amount].fillna(0).astype(float) * precios_quote_eur
    df['FIAT Fee'] = df[c_fee_val].fillna(0).astype(float) * precios_fee_eur

    output_name = file_path.replace('.csv', '_PROCESADO.csv')
    df.drop(columns=['dt_utc'], errors='ignore').to_csv(output_name, index=False)
    print(f"\n✅ Archivo generado: {output_name}")

def modo_single(pair, date_str):
    # Intentar parsear la fecha
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
        print(f"❌ No se pudo obtener el precio para {pair}.")

if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 1 and args[0].endswith('.csv'):
        modo_csv(args[0])
    elif len(args) >= 2:
        # El primer argumento es el par, el resto es la fecha
        modo_single(args[0], " ".join(args[1:]))
    else:
        print("Uso:")
        print("  Procesar CSV:   python3 crypto_tool.py archivo.csv")
        print("  Consulta única: python3 crypto_tool.py BTCUSDC \"2026-03-08 12:13:17\"")