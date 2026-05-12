import requests
from datetime import datetime
from typing import Union, Tuple, Dict, Optional
import sys
import time

# CoinGecko API endpoints
COINGECKO_API_URL = "https://api.coingecko.com/api/v3"

# Mapping of common crypto and FIAT symbols to CoinGecko IDs
CRYPTO_ID_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "XRP": "ripple",
    "ADA": "cardano",
    "SOL": "solana",
    "DOGE": "dogecoin",
    "USDT": "tether",
    "USDC": "usd-coin",
    "BUSD": "binance-usd",
    "DAI": "dai",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "XLM": "stellar",
    "ATOM": "cosmos",
    "DOT": "polkadot",
    "SHIB": "shiba-inu",
    "UNI": "uniswap",
    "AAVE": "aave",
}

FIAT_CURRENCIES = {
    "USD": "usd",
    "EUR": "eur",
    "GBP": "gbp",
    "JPY": "jpy",
    "AUD": "aud",
    "CAD": "cad",
    "CHF": "chf",
    "CNY": "cny",
    "SEK": "sek",
    "NZD": "nzd",
}

# Rate limiting
REQUEST_DELAY = 0.5  # seconds between requests
last_request_time = 0


def rate_limit():
    """Implement rate limiting to avoid API throttling."""
    global last_request_time
    elapsed = time.time() - last_request_time
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)
    last_request_time = time.time()


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
            
            if crypto in CRYPTO_ID_MAP or crypto in FIAT_CURRENCIES:
                if target in CRYPTO_ID_MAP or target in FIAT_CURRENCIES:
                    return crypto, target
    
    raise ValueError(
        f"Invalid pair format: {pair}. "
        f"Use format like 'BTCUSDC' or 'ETHEUR'. "
        f"Supported cryptos: {', '.join(sorted(CRYPTO_ID_MAP.keys()))} "
        f"Supported fiats: {', '.join(sorted(FIAT_CURRENCIES.keys()))}"
    )


def get_crypto_id(symbol: str) -> str:
    """Get CoinGecko ID for a crypto symbol."""
    symbol = symbol.upper()
    if symbol in CRYPTO_ID_MAP:
        return CRYPTO_ID_MAP[symbol]
    raise ValueError(f"Unknown cryptocurrency: {symbol}")


def get_fiat_code(symbol: str) -> str:
    """Get FIAT code for a currency symbol."""
    symbol = symbol.upper()
    if symbol in FIAT_CURRENCIES:
        return FIAT_CURRENCIES[symbol]
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


def get_historical_price(
    pair: str, date: str
) -> Optional[Dict]:
    """
    Fetch historical price for a crypto pair on a specific date.
    
    Uses CoinGecko's market chart endpoint which is more reliable for
    historical data and doesn't have the same rate limiting issues.
    
    Args:
        pair: Crypto pair like 'BTCUSDC' or 'ETHEUR'
        date: Date in format 'YYYY-MM-DD'
        
    Returns:
        Dictionary with price information or None if fetch fails
    """
    try:
        # Parse the pair
        crypto_symbol, target_symbol = parse_pair(pair)
        
        # Get CoinGecko IDs
        crypto_id = get_crypto_id(crypto_symbol)
        
        # Validate date
        target_date = validate_date(date)
        
        # Determine if target is crypto or fiat
        if target_symbol in CRYPTO_ID_MAP:
            # Crypto-to-crypto pair
            target_id = get_crypto_id(target_symbol)
            vs_currency = "usd"  # Use USD as intermediate
            is_crypto_target = True
        else:
            # Crypto-to-fiat pair
            vs_currency = get_fiat_code(target_symbol)
            target_id = None
            is_crypto_target = False
        
        rate_limit()
        
        # Fetch data from CoinGecko market chart endpoint
        # This is more reliable for historical data
        url = f"{COINGECKO_API_URL}/coins/{crypto_id}/market_chart"
        
        # Calculate days before target date
        days_diff = (datetime.now() - target_date).days
        
        params = {
            "vs_currency": vs_currency,
            "days": max(days_diff, 1),
            "interval": "daily"
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Find the price closest to the target date
        prices = data.get("prices", [])
        if not prices:
            return None
        
        # Convert timestamp to date and find closest match
        target_timestamp = int(target_date.timestamp() * 1000)
        closest_price = None
        closest_diff = float('inf')
        
        for timestamp, price in prices:
            diff = abs(timestamp - target_timestamp)
            if diff < closest_diff:
                closest_diff = diff
                closest_price = price
        
        if closest_price is None:
            return None
        
        price = closest_price
        
        if is_crypto_target:
            # Get price in USD for target crypto
            rate_limit()
            
            target_url = f"{COINGECKO_API_URL}/coins/{target_id}/market_chart"
            target_response = requests.get(target_url, params=params, timeout=10)
            target_response.raise_for_status()
            target_data = target_response.json()
            
            target_prices = target_data.get("prices", [])
            if not target_prices:
                return None
            
            closest_target_price = None
            closest_target_diff = float('inf')
            
            for timestamp, target_price in target_prices:
                diff = abs(timestamp - target_timestamp)
                if diff < closest_target_diff:
                    closest_target_diff = diff
                    closest_target_price = target_price
            
            if closest_target_price and closest_target_price != 0:
                price = price / closest_target_price
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
        
    except requests.exceptions.RequestException as e:
        print(f"API Error: {e}", file=sys.stderr)
        return None
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
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
