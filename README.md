# Crypto Price Fetcher

A Python utility to fetch historical cryptocurrency prices for crypto-to-FIAT and crypto-to-crypto trading pairs.

## Features

- **Crypto-to-FIAT pairs**: `BTCUSDC`, `ETHEUR`, etc.
- **Crypto-to-Crypto pairs**: `BTCETH`, `SOLBTC`, etc.
- **Historical price lookup**: Get the price at any past date
- **Flexible parsing**: Automatically detects crypto and FIAT currencies
- **Error handling**: Validates input and provides helpful error messages
- **Rate limiting**: Built-in delays to respect API rate limits
- **Reliable API**: Uses CoinGecko's market chart endpoint for better historical data support

## Supported Cryptocurrencies

BTC, ETH, XRP, ADA, SOL, DOGE, USDT, USDC, BUSD, DAI, MATIC, LINK, LTC, BCH, XLM, ATOM, DOT, SHIB, UNI, AAVE

## Supported FIAT Currencies

USD, EUR, GBP, JPY, AUD, CAD, CHF, CNY, SEK, NZD

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Command Line

```bash
# Bitcoin to USDC price on September 4, 2017
python3 crypto_price_fetcher.py BTCUSDC 2017-09-04

# Ethereum to EUR price on January 1, 2025
python3 crypto_price_fetcher.py ETHEUR 2025-01-01

# Bitcoin to Ethereum price on any date
python3 crypto_price_fetcher.py BTCETH 2022-05-12
```

### Python Module

```python
from crypto_price_fetcher import get_historical_price

result = get_historical_price("BTCUSDC", "2017-09-04")
if result:
    print(f"Price: {result['formatted_price']} {result['target']}")
    # Output: Price: 4,200.12345678 USDC
```

## Output Format

The script returns a dictionary with the following fields:

```python
{
    "pair": "BTCUSDC",           # Trading pair
    "crypto": "BTC",             # Base cryptocurrency
    "target": "USDC",            # Target currency/cryptocurrency
    "date": "2017-09-04",        # Requested date
    "price": 4200.12345678,      # Numerical price
    "formatted_price": "4,200.12345678"  # Formatted price with comma separator
}
```

## How It Works

1. **Pair Parsing**: Extracts the base cryptocurrency and target currency from the trading pair
2. **Validation**: Verifies the date format and currency symbols
3. **API Request**: Queries CoinGecko's free API for historical market data
4. **Price Calculation**: For crypto-to-crypto pairs, calculates the exchange rate via USD
5. **Result Return**: Returns the closest available price to the requested date

## API Information

- **Provider**: [CoinGecko](https://www.coingecko.com/)
- **API**: Free public API (no API key required)
- **Rate Limit**: ~10-50 calls/minute for free tier
- **Historical Data**: Available from 2013 onwards for major cryptocurrencies

## Notes

- The script finds the **closest available price** to the requested date. If exact date data isn't available, it uses the nearest date with data.
- For very old dates (pre-2013) or very new altcoins, data may not be available.
- The free CoinGecko API has rate limits; built-in delays prevent hitting these limits.
- For production use with high-frequency requests, consider using a paid API or CoinGecko's paid tier.

## Error Handling

Common errors and solutions:

| Error | Cause | Solution |
|-------|-------|----------|
| `Invalid pair format` | Wrong pair syntax | Use format like `BTCUSDC` or `ETHEUR` |
| `Unknown cryptocurrency` | Unsupported crypto | Check supported cryptos list above |
| `Invalid date format` | Wrong date syntax | Use format `YYYY-MM-DD` |
| `API Error: 401 Unauthorized` | Rare rate limiting | Wait a moment and try again |
| `Failed to fetch price data` | Data unavailable | Date may be too old or cryptocurrency too new |

## License

MIT
