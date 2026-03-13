"""
Unit tests for CurrencyService.
All HTTP calls are mocked — no real network requests are made.
"""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
from services.currency_service import CurrencyService, _rate_cache, _CACHE_TTL


def _mock_http_response(rates: dict) -> MagicMock:
    """Build a mock httpx Response that returns the given rates dict."""
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {'rates': rates}
    return response


@pytest.fixture(autouse=True)
def clear_cache():
    """Ensure each test starts with a clean cache."""
    CurrencyService.clear_cache()
    yield
    CurrencyService.clear_cache()


class TestGetRate:

    @pytest.mark.asyncio
    async def test_same_currency_returns_one(self):
        """No network call needed when from == to."""
        rate = await CurrencyService.get_rate('SGD', 'SGD')
        assert rate == Decimal('1')

    @pytest.mark.asyncio
    @patch('services.currency_service.httpx.AsyncClient')
    async def test_fetches_rate_from_api(self, mock_client_cls):
        """Rate is fetched from API when cache is empty."""
        mock_response = _mock_http_response({'MYR': 3.35, 'USD': 0.74})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        rate = await CurrencyService.get_rate('SGD', 'MYR')

        assert rate == Decimal('3.35')
        mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    @patch('services.currency_service.httpx.AsyncClient')
    async def test_uses_cache_on_second_call(self, mock_client_cls):
        """Second call for same base currency hits cache, not API."""
        mock_response = _mock_http_response({'USD': 0.74})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await CurrencyService.get_rate('SGD', 'USD')
        await CurrencyService.get_rate('SGD', 'USD')

        # API should only be called once despite two get_rate calls
        assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    @patch('services.currency_service.httpx.AsyncClient')
    async def test_cache_refreshes_after_ttl(self, mock_client_cls):
        """Expired cache triggers a fresh API call."""
        mock_response = _mock_http_response({'USD': 0.74})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        # Seed cache with an expired entry
        _rate_cache['SGD'] = {
            'rates': {'USD': 0.70},
            'fetched_at': datetime.now(timezone.utc) - _CACHE_TTL - timedelta(seconds=1)
        }

        rate = await CurrencyService.get_rate('SGD', 'USD')

        # Should have re-fetched and used the fresh rate
        assert rate == Decimal('0.74')
        mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    @patch('services.currency_service.httpx.AsyncClient')
    async def test_raises_for_unsupported_currency(self, mock_client_cls):
        """ValueError raised when the target currency is not in the API response."""
        mock_response = _mock_http_response({'USD': 0.74})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ValueError, match="not available"):
            await CurrencyService.get_rate('SGD', 'XYZ')


class TestConvert:

    @pytest.mark.asyncio
    async def test_same_currency_returns_original_amount(self):
        amount = Decimal('100.00')
        result = await CurrencyService.convert(amount, 'SGD', 'SGD')
        assert result == amount

    @pytest.mark.asyncio
    @patch('services.currency_service.httpx.AsyncClient')
    async def test_converts_and_rounds_to_two_decimals(self, mock_client_cls):
        """Converted amount is quantized to 2 decimal places."""
        mock_response = _mock_http_response({'MYR': 3.3512345})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await CurrencyService.convert(Decimal('10.00'), 'SGD', 'MYR')

        assert result == Decimal('33.51')  # 10 * 3.3512345 = 33.512345 → 33.51

    @pytest.mark.asyncio
    @patch('services.currency_service.httpx.AsyncClient')
    async def test_zero_amount_converts_to_zero(self, mock_client_cls):
        mock_response = _mock_http_response({'USD': 0.74})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await CurrencyService.convert(Decimal('0.00'), 'SGD', 'USD')
        assert result == Decimal('0.00')
