import yfinance as yf
import pandas as pd
import sys
import os
import warnings
import urllib.request
import urllib.error
import json
import time
from datetime import datetime

# Silenciar ruidos visuales de librerías externas
warnings.filterwarnings("ignore")
os.environ["YF_NO_PRINTS"] = "1"

# --- MEMORIA Y MAPEOS DE ALTO RENDIMIENTO ---
price_cache = {}             # Clave: "ASSET_TARGET_YYYYMMDD_HHMM"
market_data_cache = {}       # Guarda DataFrames completos indexados por Ticker
KNOWN_INVALID_PAIRS = set()  # Evita llamadas repetidas a pares inexistentes en Binance
VERBOSE = False              # Flag dinámico de diagnóstico

TICKER_MAP = {
    'XBT': 'BTC', 'ZEUR': 'EUR', 'ZUSD': 'USD', 'ZGBP': 'GBP',
    'XETH': 'ETH', 'XXRP': 'XRP', 'XLTC': 'LTC', 'XXLM': 'XLM',
    'IOTA': 'IOTA', 'MIOTA': 'IOTA', 'REPV2': 'REP'
}

STABLECOINS = ["USD", "USDC", "USDT", "BUSD", "DAI", "PYUSD"]

def get_now_str():
    """Devuelve el instante actual con precisión de milisegundos."""
    return datetime.now().strftime('%H:%M:%S.%f')[:-3]

def log_verbose(msg):
    if VERBOSE:
        print(f"   [{get_now_str()}] [DEBUG] {msg}")

def normalize_ticker(symbol):
    if pd.isna(symbol) or not symbol:
        return ""
    s = str(symbol).upper().strip()
    return TICKER_MAP.get(s, s)

def split_pair(pair):
    pair = pair.upper().strip()
    quotes = ["EUR", "USD", "USDC", "USDT", "BTC", "ETH", "BNB", "BUSD", "ZEUR", "ZUSD"]
    for q in sorted(quotes, key=len, reverse=True):
        if pair.endswith(q):
            return pair[:-len(q)], q
    return pair, "USD"

def precargar_puentes_diarios(df_timestamps):
    min_dt = pd.to_datetime(df_timestamps).dropna().min()
    if pd.isna(min_dt): return

    timestamp_ms = int(min_dt.timestamp() * 1000)
    pairs_to_precache = ["EURUSDT", "BTCEUR", "ETHEUR", "BNBEUR"]

    for symbol in pairs_to_precache:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&startTime={timestamp_ms}&limit=1000"
        log_verbose(f"Precargando puente diario: {url}")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode())
                for kline in data:
                    k_time = pd.to_datetime(kline[0], unit='ms', utc=True)
                    k_close = float(kline[4])
                    if symbol == "EURUSDT":
                        k_close = 1.0 / k_close

                    day_key = f"BRIDGE_{symbol}_{k_time.strftime('%Y%m%d')}"
                    price_cache[day_key] = k_close
        except Exception as e:
            log_verbose(f"Fallo en precarga de {symbol}: {e}")

def get_core_fiat_bridge(asset, dt_obj):
    asset = normalize_ticker(asset)
    if asset == "EUR": return 1.0

    asset_pair = "EURUSDT" if asset in STABLECOINS else f"{asset}EUR"
    day_key = f"BRIDGE_{asset_pair}_{dt_obj.strftime('%Y%m%d')}"

    if day_key in price_cache:
        return price_cache[day_key]

    fallbacks = {"BTCEUR": 35000.0, "ETHEUR": 22000.0, "BNBEUR": 300.0, "EURUSDT": 0.92}
    return fallbacks.get(asset_pair, 1.0)

def get_binance_direct_price(base, quote, dt_obj):
    base = normalize_ticker(base)
    quote = normalize_ticker(quote)

    if not base or not quote or base == quote: return 1.0
    if base in STABLECOINS and quote == "USD": return 1.0
    if base == "USD" and quote in STABLECOINS: return 1.0

    pair_symbol = f"{base}{quote}"
    if pair_symbol in KNOWN_INVALID_PAIRS:
        return None

    cache_key = f"{base}_{quote}_{dt_obj.strftime('%Y%m%d_%H%M')}"
    if cache_key in price_cache:
        return price_cache[cache_key]

    timestamp_ms = int(dt_obj.timestamp() * 1000)
    url = f"https://api.binance.com/api/v3/klines?symbol={pair_symbol}&interval=1m&startTime={timestamp_ms}&limit=1000"

    log_verbose(f"Llamando a Binance (1m): {url}")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=1.5) as response:
            data = json.loads(response.read().decode())
            if data and len(data) > 0:
                for kline in data:
                    k_time = pd.to_datetime(kline[0], unit='ms', utc=True)
                    k_close = float(kline[4])
                    c_key = f"{base}_{quote}_{k_time.strftime('%Y%m%d_%H%M')}"
                    price_cache[c_key] = k_close

                if cache_key in price_cache:
                    return price_cache[cache_key]
                return float(data[0][4])
            else:
                KNOWN_INVALID_PAIRS.add(pair_symbol)
    except urllib.error.HTTPError as e:
        if e.code == 400:
            log_verbose(f"Par inválido detectado en Binance (400): {pair_symbol}. Se añade a la lista negra.")
            KNOWN_INVALID_PAIRS.add(pair_symbol)
    except Exception as e:
        log_verbose(f"Error de red/timeout en Binance para {pair_symbol}: {e}")

    return None

def fetch_yahoo_bulk(ticker, dt_obj):
    if ticker in market_data_cache:
        df = market_data_cache[ticker]
        if df is None: return None
        return extract_from_dataframe(df, dt_obj)

    df_period = None
    old_stderr = sys.stderr
    sys.stderr = open(os.devnull, 'w')

    start_str = f"{dt_obj.strftime('%Y')}-01-01"
    log_verbose(f"Llamando a Yahoo Finance Masivo ({ticker}) desde {start_str}")

    try:
        t = yf.Ticker(ticker)
        df_period = t.history(start=start_str, interval="1d", progress=False)

        if df_period is not None and not df_period.empty:
            market_data_cache[ticker] = df_period
            val = extract_from_dataframe(df_period, dt_obj)
            sys.stderr.close()
            sys.stderr = old_stderr
            return val
        else:
            market_data_cache[ticker] = None
    except Exception as e:
        sys.stderr.close()
        sys.stderr = old_stderr
        log_verbose(f"Error cargando {ticker} en Yahoo Finance: {e}")
        market_data_cache[ticker] = None

    return None

def extract_from_dataframe(df_period, dt_obj):
    if df_period is None or df_period.empty: return None
    df_period = df_period.copy()
    df_period.index = pd.to_datetime(df_period.index, utc=True).tz_localize(None)
    target_date = pd.to_datetime(dt_obj).tz_localize(None).date()

    match = df_period[df_period.index.date == target_date]
    if not match.empty:
        return float(match['Close'].iloc[0])

    try:
        target_datetime = pd.to_datetime(dt_obj).tz_localize(None)
        idx = df_period.index.get_indexer([target_datetime], method='nearest')[0]
        if idx != -1: return float(df_period['Close'].iloc[idx])
    except:
        pass
    return None

def get_price_info(asset, target_currency, dt_obj):
    asset = normalize_ticker(asset)
    target_currency = normalize_ticker(target_currency)

    if not asset or not target_currency or asset == target_currency:
        return 1.0

    cache_key = f"{asset}_{target_currency}_{dt_obj.strftime('%Y%m%d_%H%M')}"
    if cache_key in price_cache:
        return price_cache[cache_key]

    binance_price = get_binance_direct_price(asset, target_currency, dt_obj)
    if binance_price is not None and binance_price > 0:
        price_cache[cache_key] = binance_price
        return binance_price

    if target_currency == "EUR":
        p_asset_usd = get_binance_direct_price(asset, "USDT", dt_obj) or fetch_yahoo_bulk(f"{asset}-USD", dt_obj)
        p_stable_eur = get_binance_direct_price("EUR", "USDT", dt_obj) or get_binance_direct_price("EUR", "USDC", dt_obj)

        if p_stable_eur and p_stable_eur > 0:
            p_eur_usd = 1.0 / p_stable_eur
        else:
            p_eur_usd = get_core_fiat_bridge("USDT", dt_obj)

        if p_asset_usd and p_eur_usd:
            val = p_asset_usd * p_eur_usd
            price_cache[cache_key] = val
            return val

    if target_currency in STABLECOINS or target_currency == "USD":
        price = fetch_yahoo_bulk(f"{asset}-USD", dt_obj)
        if price:
            price_cache[cache_key] = price
            return price

    return None

def find_col(columns, valid_names):
    for name in valid_names:
        for c in columns:
            if name.lower() in c.lower():
                return c
    return None

def procesar_csv(file_path):
    print(f"[{get_now_str()}] 📖 Cargando fichero en memoria: {file_path}")
    df = pd.read_csv(file_path)
    cols = df.columns.tolist()

    c_timestamp = find_col(cols, ['timestamp', 'time', 'fecha'])
    c_pair = find_col(cols, ['pair', 'par'])
    c_base = find_col(cols, ['Asset Base', 'base'])
    c_quote = find_col(cols, ['Asset Quote', 'quote'])
    c_spot_price_orig = find_col(cols, ['Spot Price', 'precio'])
    c_amount_orig = find_col(cols, ['Amount out/in', 'amount', 'cantidad'])
    c_fee = find_col(cols, ['Crypto Fee', 'fee', 'comision'])
    c_fee_asset = find_col(cols, ['Crypto-fee Asset', 'fee asset', 'comision asset'])

    if not c_timestamp or not c_pair:
        print(f"[{get_now_str()}] ❌ Error Crítico: No se encuentran columnas de Fecha o Par.")
        return

    df['dt_utc'] = pd.to_datetime(df[c_timestamp], utc=True, errors='coerce')
    out_file = file_path.replace('.csv', '_PROCESADO.csv')
    total_filas = len(df)

    # --- LÓGICA DE REANUDACIÓN (CHECKPOINT) ---
    start_index = 0
    res_spot_eur = []
    res_amount_eur = []
    res_fee_eur = []

    if os.path.exists(out_file):
        print(f"[{get_now_str()}] 🔄 Fichero parcial detectado: {out_file}")
        try:
            df_prev = pd.read_csv(out_file)
            start_index = len(df_prev)
            if start_index > 0 and start_index <= total_filas:
                print(f"[{get_now_str()}] ⏭️ Restaurando estado... Saltando las primeras {start_index} filas ya procesadas.")
                res_spot_eur = df_prev['Spot Price (EUR)'].tolist()
                res_amount_eur = df_prev['Amount out/in (EUR)'].tolist()
                res_fee_eur = df_prev['FIAT Fee'].tolist()
            elif start_index >= total_filas:
                print(f"[{get_now_str()}] ✅ El fichero ya está completamente procesado ({start_index} filas).")
                return
        except Exception as e:
            print(f"[{get_now_str()}] ⚠️ Error leyendo checkpoint. Empezando de cero. Detalles: {e}")
            start_index = 0

    # --- FASE 1: PRECARGA ---
    if start_index < total_filas:
        t_inicio_precarga = time.time()
        print(f"[{get_now_str()}] ⏳ Comenzando precarga masiva de puentes diarios...")
        precargar_puentes_diarios(df['dt_utc'])
        print(f"[{get_now_str()}] ✅ Precarga terminada en {time.time() - t_inicio_precarga:.2f} segundos.")

    exitos = 0
    errores = 0

    # --- FASE 2: PROCESAMIENTO ---
    t_inicio_proc = time.time()
    print(f"[{get_now_str()}] 🚀 Retomando procesamiento analítico desde la fila {start_index + 1}...")

    for i, row in df.iterrows():
        # Saltar filas ya calculadas en ejecuciones anteriores
        if i < start_index:
            continue

        dt = row['dt_utc']
        raw_pair = str(row[c_pair])
        csv_line = i + 2

        if VERBOSE:
            print(f"[{get_now_str()}] ▶️ [Fila {csv_line}/{total_filas+1}] Par: {raw_pair} | Fecha: {dt}")

        if pd.isna(dt):
            res_spot_eur.append(0.0)
            res_amount_eur.append(0.0)
            res_fee_eur.append(0.0)
            errores += 1
        else:
            base_asset, quote_asset = split_pair(raw_pair)
            if c_base and pd.notna(row[c_base]): base_asset = str(row[c_base])
            if c_quote and pd.notna(row[c_quote]): quote_asset = str(row[c_quote])

            base_asset = normalize_ticker(base_asset)
            quote_asset = normalize_ticker(quote_asset)

            spot_price_eur = None
            raw_price = row.get(c_spot_price_orig) if c_spot_price_orig else None
            is_erg = (base_asset == "ERG" or quote_asset == "ERG")

            # --- CÁLCULO SPOT PRICE EUR ---
            if is_erg:
                year_str = dt.strftime('%Y')
                spot_price_eur = 1.95 if year_str == "2022" else (1.40 if year_str == "2024" else 1.70)
            else:
                computed_base_eur = get_price_info(base_asset, 'EUR', dt)
                if computed_base_eur and computed_base_eur > 0:
                    spot_price_eur = computed_base_eur
                else:
                    if pd.notna(raw_price) and float(raw_price) > 0:
                        orig_price = float(raw_price)
                        if quote_asset == "EUR":
                            spot_price_eur = orig_price
                        else:
                            p_quote_eur = get_price_info(quote_asset, 'EUR', dt)
                            spot_price_eur = orig_price * p_quote_eur if p_quote_eur else 0.0

            if spot_price_eur is None or spot_price_eur <= 0:
                spot_price_eur = 0.0
                errores += 1
            else:
                exitos += 1

            res_spot_eur.append(spot_price_eur)

            # --- CÁLCULO VOLUMEN EUR ---
            amount_orig = float(row[c_amount_orig]) if c_amount_orig and pd.notna(row[c_amount_orig]) else 0.0
            if quote_asset == "EUR":
                res_amount_eur.append(amount_orig)
            elif is_erg and quote_asset == "ERG":
                year_str = dt.strftime('%Y')
                res_amount_eur.append(amount_orig * (1.95 if year_str == "2022" else (1.40 if year_str == "2024" else 1.70)))
            else:
                p_quote_eur = get_price_info(quote_asset, 'EUR', dt)
                res_amount_eur.append(amount_orig * p_quote_eur if p_quote_eur else 0.0)

            # --- CÁLCULO COMISIONES ---
            fee_eur = 0.0
            if c_fee and c_fee_asset:
                f_val_raw = row[c_fee]
                f_asset_raw = row[c_fee_asset]

                if pd.notna(f_val_raw) and pd.notna(f_asset_raw) and str(f_asset_raw).strip() != "" and float(f_val_raw) > 0:
                    f_val = float(f_val_raw)
                    f_asset = normalize_ticker(f_asset_raw)
                    if f_asset == "EUR":
                        fee_eur = f_val
                    elif f_asset == "ERG":
                        year_str = dt.strftime('%Y')
                        fee_eur = f_val * (1.95 if year_str == "2022" else (1.40 if year_str == "2024" else 1.70))
                    else:
                        p_fee_asset_eur = get_price_info(f_asset, 'EUR', dt)
                        fee_eur = f_val * p_fee_asset_eur if p_fee_asset_eur else 0.0

            res_fee_eur.append(fee_eur)

        # --- AUTO-GUARDADO CADA 100 FILAS ---
        if (i + 1) % 100 == 0 or (i + 1) == total_filas:
            # Creamos un dataframe temporal solo con las filas completadas hasta ahora
            temp_df = df.iloc[:i+1].copy()
            temp_df['Spot Price (EUR)'] = res_spot_eur
            temp_df['Amount out/in (EUR)'] = res_amount_eur
            temp_df['FIAT Fee'] = res_fee_eur
            temp_df.drop(columns=['dt_utc']).to_csv(out_file, index=False)

            if VERBOSE:
                print(f"   💾 [Auto-Save] Progreso guardado en disco ({i+1} filas).")

        # --- TELEMETRÍA ---
        if VERBOSE:
            elapsed = time.time() - t_inicio_proc
            filas_proc = (i + 1) - start_index
            v_speed = filas_proc / elapsed if elapsed > 0 else 0
            print(f"   📊 PROGRESO ACTUAL: {((i+1)/total_filas)*100:.2f}% | Velocidad: {v_speed:.1f} filas/s")
        elif (i + 1) % 10 == 0 or (i + 1) == total_filas:
            elapsed = time.time() - t_inicio_proc
            filas_proc = (i + 1) - start_index
            v_speed = filas_proc / elapsed if elapsed > 0 else 0
            sys.stdout.write(f"\r📊 PROGRESO: {((i+1)/total_filas)*100:6.2f}% | Fila: {i+1}/{total_filas} | Velocidad (sesión): {v_speed:.1f} filas/s")
            sys.stdout.flush()

    t_fin_proc = time.time()
    print(f"\n\n[{get_now_str()}] ✅ Procesamiento finalizado.")
    print(f"=======================================================")
    print(f"📋 RESUMEN DE SESIÓN")
    print(f"=======================================================")
    print(f"✅ Filas nuevas procesadas: {total_filas - start_index}")
    print(f"💾 Archivo Final Consolidado: {out_file}")
    print(f"=======================================================")

def modo_single(pair, date_str):
    """Mantiene la ejecución para consultas individuales directas desde terminal."""
    dt = pd.to_datetime(date_str, utc=True, errors='coerce')
    if pd.isna(dt):
        print(f"❌ Error: No se pudo entender la fecha '{date_str}'")
        return
    base, quote = split_pair(pair)
    print(f"pair: {pair}: {base}/{quote}")
    precio = get_price_info(base, quote, dt)
    if precio and precio > 0:
        print(f"\n✅ RESULTADO:\nPar: {base}/{quote}\nFecha: {dt.strftime('%Y-%m-%d %H:%M:%S')} UTC\nPrecio: {precio:.8f} {quote}")
    else:
        print(f"\n❌ ERROR: No se pudo obtener cotización para {base}/{quote}.")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(1)
    param = sys.argv[1]

    if "--verbose" in sys.argv:
        VERBOSE = True

    if param.endswith('.csv'):
        procesar_csv(param)
    else:
        if len(sys.argv) < 3:
            sys.exit(1)
        modo_single(param, sys.argv[2])