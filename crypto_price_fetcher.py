import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd
import sys

# --- CONFIGURACIÓN DINÁMICA ---

def get_ticker_symbol(symbol: str) -> str:
    """Mapea un símbolo de cripto al formato de Yahoo Finance."""
    special_cases = {
        "DOT": "DOT1-USD",
        "MATIC": "POL-USD",  # MATIC migró a POL
    }
    if symbol in special_cases:
        return special_cases[symbol]
    return f"{symbol}-USD"

def get_fiat_rate_ticker(symbol: str) -> str:
    """Retorna el ticker para el tipo de cambio contra el USD."""
    if symbol == "USD": return None
    return f"{symbol}USD=X"

def fetch_yahoo_price(ticker: str, date_str: str) -> float:
    """Descarga el precio de cierre de un ticker de Yahoo de forma robusta."""
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d')
        # Pedimos un rango para asegurar que haya datos (fines de semana en FIAT)
        start_dt = (target_date - timedelta(days=2)).strftime('%Y-%m-%d')
        end_dt = (target_date + timedelta(days=3)).strftime('%Y-%m-%d')
        
        data = yf.download(ticker, start=start_dt, end=end_dt, progress=False)
        
        if data.empty:
            return None
        
        # Manejo de MultiIndex (Yahoo a veces anida el ticker en las columnas)
        if isinstance(data.columns, pd.MultiIndex):
            close_data = data.xs('Close', axis=1, level=0 if 'Close' in data.columns.levels[0] else 1)
        else:
            close_data = data['Close']
        
        # Forzar a Serie 1D si es un DataFrame de una columna
        if isinstance(close_data, pd.DataFrame):
            close_data = close_data.iloc[:, 0]

        target_ts = pd.Timestamp(target_date.date())
        # Buscar el índice más cercano a la fecha pedida
        idx = close_data.index.get_indexer([target_ts], method='nearest')[0]
        
        # Extraer el valor escalar
        precio_crudo = close_data.iloc[idx]
        if isinstance(precio_crudo, pd.Series):
            precio_crudo = precio_crudo.iloc[0]
            
        return float(precio_crudo)
    except Exception:
        return None

def get_historical_price(pair: str, date: str):
    """Lógica principal para calcular el precio de cualquier par."""
    pair = pair.upper()
    
    # 1. Intentar separar el par inteligentemente
    quote_symbols = ["EUR", "USD", "USDC", "USDT", "BTC", "ETH", "BNB", "DAI"]
    crypto_symbol = ""
    target_symbol = ""
    
    for q in quote_symbols:
        if pair.endswith(q):
            target_symbol = q
            crypto_symbol = pair[:-len(q)]
            break
    
    if not crypto_symbol:
        # Fallback si no coincide con los comunes: asume los últimos 3 caracteres
        crypto_symbol = pair[:-3]
        target_symbol = pair[-3:]

    try:
        # A. Precio del activo base en USD
        price_base_usd = fetch_yahoo_price(get_ticker_symbol(crypto_symbol), date)
        if price_base_usd is None:
            return None

        # B. Calcular precio final según el target
        if target_symbol in ["USD", "USDC", "USDT", "DAI"]:
            price = price_base_usd
        elif target_symbol in ["BTC", "ETH", "BNB"]:
            # Triangulación Cripto-Cripto
            price_target_usd = fetch_yahoo_price(get_ticker_symbol(target_symbol), date)
            if not price_target_usd: return None
            price = price_base_usd / price_target_usd
        else:
            # Triangulación Cripto-Fiat (EUR, GBP, etc.)
            fiat_ticker = get_fiat_rate_ticker(target_symbol)
            fiat_to_usd = fetch_yahoo_price(fiat_ticker, date) # Precio de 1 FIAT en USD
            if not fiat_to_usd: return None
            price = price_base_usd / fiat_to_usd

        # Retornamos el diccionario completo que espera main()
        return {
            "pair": pair,
            "crypto": crypto_symbol,
            "target": target_symbol,
            "date": date,
            "price": price,
            "formatted_price": f"{price:,.8f}"
        }
        
    except Exception as e:
        print(f"Unexpected error: {str(e)}", file=sys.stderr)
        return None

def main():
    """CLI interface original."""
    if len(sys.argv) != 3:
        print(
            "Usage: python crypto_price_fetcher.py <PAIR> <DATE>\n"
            "Example: python crypto_price_fetcher.py BTCUSDC 2017-09-04\n"
            "Example: python crypto_price_fetcher.py ETHEUR 2025-01-01"
        )
        sys.exit(1)
    
    pair = sys.argv[1]
    date = sys.argv[2]
    
    print(f"Fetching price for {pair} on {date}...")
    result = get_historical_price(pair, date)
    
    if result:
        print(f"\n{'='*50}")
        print(f"Pair: {result['pair']}")
        print(f"Date: {result['date']}")
        print(f"Price: {result['formatted_price']} {result['target']}")
        print(f"{'='*50}\n")
    else:
        print(f"Failed to fetch price data for {pair} on {date}")
        sys.exit(1)

if __name__ == "__main__":
    main()
