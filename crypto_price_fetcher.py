import yfinance as yf
from datetime import datetime, timedelta
from typing import Tuple, Dict, Optional
import sys

# Mapping of common crypto and FIAT symbols
CRYPTO_SYMBOLS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "XRP": "XRP-USD",
    "ADA": "ADA-USD",
    "SOL": "SOL-USD",
    "DOGE": "DOGE-USD",
    "USDT": "USDT-USD",
    "USDC": "USDC-USD",
    "BUSD": "BUSD-USD",
    "DAI": "DAI-USD",
    "MATIC": "MATIC-USD",
    "LINK": "LINK-USD",
    "LTC": "LTC-USD",
    "BCH": "BCH-USD",
    "XLM": "XLM-USD",
    "ATOM": "ATOM-USD",
    "DOT": "DOT-USD",
    "SHIB": "SHIB-USD",
    "UNI": "UNI-USD",
    "AAVE": "AAVE-USD",
}

# Stablecoins that are always ~1.0 USD
STABLECOINS = {"USDT", "USDC", "BUSD", "DAI", "USDP", "TUSD"}

# Mapping for fiat to crypto pairs
FIAT_TO_CRYPTO_PAIRS = {
    "USD": None,  # USD is base
    "EUR": "EURUSD=X",
    "GBP": "GBPUSD=X",
    "JPY": "JPYUSD=X",
    "AUD": "AUDUSD=X",
    "CAD": "CADUSD=X",
    "CHF": "CHFUSD=X",
    "CNY": "CNYUSD=X",
    "SEK": "SEKUSD=X",
    "NZD": "NZDUSD=X",
}

FIAT_CURRENCIES = set(FIAT_TO_CRYPTO_PAIRS.keys())


def parse_pair(pair: str) -> Tuple[str, str]:
    """
    Parse a crypto pair like 'BTCUSDC' into components.
    
    Args:
        pair: String in format 'CRYPTO1CRYPTO2' or 'CRYPTOFIAT'
        
    Returns:
        Tuple of (crypto_symbol, target_symbol)
    """
    pair = pair.upper()
    
    # Try to find common crypto symbols (usually 3-4 chars)
    for crypto_len in [4, 3]:
        if len(pair) > crypto_len:
            crypto = pair[:crypto_len]
            target = pair[crypto_len:]
            
            if crypto in CRYPTO_SYMBOLS or crypto in FIAT_CURRENCIES:
                if target in CRYPTO_SYMBOLS or target in FIAT_CURRENCIES:
                    return crypto, target
    
    raise ValueError(
        f"Invalid pair format: {pair}. "
        f"Use format like 'BTCUSDC' or 'ETHEUR'. "
        f"Supported cryptos: {', '.join(sorted(CRYPTO_SYMBOLS.keys()))} "
        f"Supported fiats: {', '.join(sorted(FIAT_CURRENCIES))}"
    )


def get_yfinance_symbol(symbol: str, is_crypto: bool) -> Optional[str]:
    """Get yfinance symbol for a cryptocurrency or fiat currency."""
    symbol = symbol.upper()
    
    if is_crypto:
        if symbol in CRYPTO_SYMBOLS:
            return CRYPTO_SYMBOLS[symbol]
        raise ValueError(f"Unknown cryptocurrency: {symbol}")
    else:
        if symbol in FIAT_CURRENCIES:
            return FIAT_TO_CRYPTO_PAIRS[symbol]
        raise ValueError(f"Unknown FIAT currency: {symbol}")


def validate_date(date_str: str) -> datetime:
    """
    Validate and return datetime object.
    
    Args:
        date_str: Date in format 'YYYY-MM-DD'
        
    Returns:
        datetime object
    """
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return date_obj
    except ValueError:
        raise ValueError(
            f"Invalid date format: {date_str}. Use format 'YYYY-MM-DD'"
        )


def get_price_at_date(ticker_symbol: str, target_date: datetime, is_stablecoin: bool = False) -> Optional[float]:
    """
    Get price for a ticker on a specific date using yfinance.
    
    Args:
        ticker_symbol: yfinance ticker symbol (e.g., 'BTC-USD')
        target_date: Target date as datetime object
        is_stablecoin: Whether this is a stablecoin (always returns ~1.0)
        
    Returns:
        Price or None if unavailable
    """
    try:
        # Stablecoins are always 1.0
        if is_stablecoin:
            print(f"  Using stablecoin value: 1.0 USD", file=sys.stderr)
            return 1.0
        
        # Add buffer to ensure we get data
        start_date = target_date - timedelta(days=5)
        end_date = target_date + timedelta(days=2)
        
        print(f"  Fetching {ticker_symbol} data from {start_date.date()} to {end_date.date()}...", file=sys.stderr)
        
        # Download data - suppress warnings
        data = yf.download(ticker_symbol, start=start_date, end=end_date, progress=False, ignore_tz=True)
        
        if data.empty:
            print(f"  No data found for {ticker_symbol}", file=sys.stderr)
            return None
        
        # Check if we got a valid dataframe
        if not hasattr(data, 'index') or len(data) == 0:
            print(f"  No price data available for {ticker_symbol}", file=sys.stderr)
            return None
        
        # Find closest date manually
        closest_idx = 0
        target_date_only = target_date.date()
        min_diff = abs((data.index[0].date() - target_date_only).days)
        
        for i in range(len(data)):
            current_date = data.index[i].date()
            current_diff = abs((current_date - target_date_only).days)
            if current_diff < min_diff:
                min_diff = current_diff
                closest_idx = i
        
        closest_date = data.index[closest_idx]
        
        # Get the Close price - access as scalar value first
        row = data.iloc[closest_idx]
        close_value = row['Close']
        
        # Convert to Python float - handle different numeric types
        if hasattr(close_value, 'item'):
            # numpy/pandas scalar
            closest_price = float(close_value.item())
        else:
            closest_price = float(close_value)
        
        print(f"  Found price for {ticker_symbol}: {closest_price:.8f} on {closest_date.date()}", file=sys.stderr)
        
        return closest_price
        
    except Exception as e:
        print(f"  Error fetching {ticker_symbol}: {str(e)}", file=sys.stderr)
        return None


def get_historical_price(pair: str, date: str) -> Optional[Dict]:
    """
    Fetch historical price for a crypto pair on a specific date.
    
    Args:
        pair: Crypto pair like 'BTCUSDC' or 'ETHEUR'
        date: Date in format 'YYYY-MM-DD'
        
    Returns:
        Dictionary with price information or None if fetch fails
    """
    try:
        # Parse the pair
        crypto_symbol, target_symbol = parse_pair(pair)
        
        # Validate date
        target_date = validate_date(date)
        
        # Get crypto price (always in terms of USD)
        crypto_yf_symbol = get_yfinance_symbol(crypto_symbol, is_crypto=True)
        crypto_price = get_price_at_date(crypto_yf_symbol, target_date)
        
        if crypto_price is None:
            return None
        
        # Determine if target is crypto or fiat
        if target_symbol in CRYPTO_SYMBOLS:
            # Crypto-to-crypto pair
            target_yf_symbol = get_yfinance_symbol(target_symbol, is_crypto=True)
            
            # Check if target is a stablecoin
            is_target_stablecoin = target_symbol in STABLECOINS
            
            target_price = get_price_at_date(target_yf_symbol, target_date, is_stablecoin=is_target_stablecoin)
            
            if target_price and target_price != 0:
                price = crypto_price / target_price
            else:
                return None
        else:
            # Crypto-to-fiat pair
            target_yf_symbol = get_yfinance_symbol(target_symbol, is_crypto=False)
            
            if target_yf_symbol is None:
                # USD is the base, so crypto_price is already in USD
                price = crypto_price
            else:
                # Get fiat exchange rate to USD
                fiat_rate = get_price_at_date(target_yf_symbol, target_date)
                
                if fiat_rate and fiat_rate != 0:
                    # Convert USD price to target fiat
                    price = crypto_price / fiat_rate
                else:
                    return None
        
        return {
            "pair": pair.upper(),
            "crypto": crypto_symbol,
            "target": target_symbol,
            "date": date,
            "price": price,
            "formatted_price": f"{price:,.8f}" if price else "N/A"
        }
        
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Unexpected error: {str(e)}", file=sys.stderr)
        return None


def main():
    """CLI interface for the crypto price fetcher."""
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
