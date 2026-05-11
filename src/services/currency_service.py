import httpx
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
import logging


logger = logging.getLogger(__name__)

_CACHE_TTL = timedelta(hours=1)
# ExchangeRate-API open endpoint — no key required, ~160 currencies, updates daily
# Attribution: https://www.exchangerate-api.com
_API_BASE = "https://open.er-api.com/v6/latest"

# In-memory rate cache: {base_currency: {'rates': {target: float, ...}, 'fetched_at': datetime}}
_rate_cache: Dict[str, dict] = {}


class CurrencyService:
    """
    Fetches live exchange rates from ExchangeRate-API open endpoint (no API key required).
    Covers ~160 currencies. Rates update daily; cached in-memory for 1 hour.
    """

    @classmethod
    async def get_rate(cls, from_currency: str, to_currency: str) -> Decimal:
        """
        Return how many units of to_currency equal 1 unit of from_currency.

        Args:
            from_currency: ISO 4217 source currency code (e.g. "USD").
            to_currency: ISO 4217 target currency code (e.g. "SGD").

        Returns:
            Exchange rate as a Decimal.

        Raises:
            ValueError: If the rate cannot be obtained (unsupported currency or API failure).
        """
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        if from_currency == to_currency:
            return Decimal('1')

        rates = await cls._get_rates_for_base(from_currency)

        if to_currency not in rates:
            raise ValueError(
                f"Exchange rate not available for {from_currency} → {to_currency}. "
                "The currency may not be supported by the rate provider."
            )

        return Decimal(str(rates[to_currency]))

    @classmethod
    async def convert(
        cls,
        amount: Decimal,
        from_currency: str,
        to_currency: str
    ) -> Decimal:
        """
        Convert an amount from one currency to another, rounded to 2 decimal places.

        Args:
            amount: The amount to convert.
            from_currency: Source currency code.
            to_currency: Target currency code.

        Returns:
            Converted amount rounded to 2 decimal places.
        """
        if from_currency.upper() == to_currency.upper():
            return amount
        rate = await cls.get_rate(from_currency, to_currency)
        return (amount * rate).quantize(Decimal('0.01'))

    @classmethod
    async def _get_rates_for_base(cls, base: str) -> dict:
        """Return rates for the given base currency, using cache when fresh."""
        cached = _rate_cache.get(base)
        if cached:
            age = datetime.now(timezone.utc) - cached['fetched_at']
            if age < _CACHE_TTL:
                logger.debug(f"Cache hit for base currency {base}")
                return cached['rates']

        logger.info(f"Fetching exchange rates for base currency {base}")
        rates = await cls._fetch_rates(base)
        _rate_cache[base] = {'rates': rates, 'fetched_at': datetime.now(timezone.utc)}
        return rates

    @classmethod
    async def _fetch_rates(cls, base: str) -> dict:
        """Hit ExchangeRate-API open endpoint and return the rates dict."""
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(f"{_API_BASE}/{base}")
                if response.status_code == 429:
                    raise ValueError(
                        f"Exchange rate API rate limit hit for {base}. Try again in ~20 minutes."
                    )
                response.raise_for_status()
                data = response.json()
                if data.get('result') != 'success':
                    error_type = data.get('error-type', 'unknown')
                    raise ValueError(
                        f"Exchange rate API error for {base}: {error_type}"
                    )
                return data.get('rates', {})
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching rates for {base}: {e}")
            raise ValueError(f"Failed to fetch exchange rates for {base}: HTTP {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"Network error fetching rates for {base}: {e}")
            raise ValueError(f"Network error while fetching exchange rates: {e}")

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the in-memory rate cache (useful for testing)."""
        _rate_cache.clear()
