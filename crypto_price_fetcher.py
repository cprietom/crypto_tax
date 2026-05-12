import requests
from datetime import datetime, timedelta
from typing import Union, Tuple, Dict, Optional
import sys
import time

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
REQUEST_DELAY = 1  # seconds between requests
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


def get_price_from_coingecko(crypto_id: str, vs_currency: str, target_date: datetime) -> Optional[float]:
    """
    Get historical price from CoinGecko using range-based approach.
    Uses the /market_chart/range endpoint which is more stable.
    
    Args:
        crypto_id: CoinGecko cryptocurrency ID
        vs_currency: Target currency code (e.g., 'usd', 'eur')
        target_date: Target date as datetime object
        
    Returns:
        Price or None if unavailable
    """
    try:
        rate_limit()
        
        # Use the range endpoint with a 60-day window around the target date
        url = f"https://api.coingecko.com/api/v3/coins/{crypto_id}/market_chart/range"
        
        # Calculate date range (30 days before and 30 days after target)
        start_date = target_date - timedelta(days=30)
        end_date = target_date + timedelta(days=30)
        
        start_timestamp = int(start_date.timestamp())
        end_timestamp = int(end_date.timestamp())
        
        params = {
            "vs_currency": vs_currency,
            "from": start_timestamp,
            "to": end_timestamp,
        }
        
        print(f"  Querying {crypto_id} from {start_date.date()} to {end_date.date()}...", file=sys.stderr)
        
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # Find the price closest to the target date
        prices = data.get("prices", [])
        if not prices:
            print(f"  No price data found for {crypto_id}", file=sys.stderr)
            return None
        
        target_timestamp = int(target_date.timestamp() * 1000)
        closest_price = None
        closest_diff = float('inf')
        closest_date = None
        
        for timestamp, price in prices:
            diff = abs(timestamp - target_timestamp)
            if diff < closest_diff:
                closest_diff = diff
                closest_price = price
                closest_date = datetime.fromtimestamp(timestamp / 1000)
        
        if closest_price is not None:
            print(f"  Found price for {crypto_id}: {closest_price} on {closest_date.date()}", file=sys.stderr)
        
        return closest_price
        
    except requests.exceptions.RequestException as e:
        print(f"  API Error for {crypto_id}: {e}", file=sys.stderr)
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
        
        # Get crypto price
        price = get_price_from_coingecko(crypto_id, vs_currency, target_date)
        
        if price is None:
            return None
        
        if is_crypto_target:
            # Get target crypto price in USD
            target_price = get_price_from_coingecko(target_id, "usd", target_date)
            
            if target_price and target_price != 0:
                price = price / target_price
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
