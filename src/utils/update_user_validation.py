import pycountry
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

MAX_NAME_LENGTH = 64
CURRENCY_CODE_LENGTH = 3


def validate_name(name: str) -> Tuple[bool, Optional[str]]:
    """
    Validate the user's input first name or last name

    Args:
        name: str - The name to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name or not name.strip():
        return False, "Name cannot be empty. Please enter a valid name or use 'Skip'."
    
    name = name.strip()

    if len(name) > MAX_NAME_LENGTH:
        return False, f"Name is too long. Maximum length is {MAX_NAME_LENGTH} characters."
    elif len(name) < 1:
        return False, "Name cannot be empty. Please enter a valid name or use 'Skip'."
    
    return True, None

def validate_currency_code(currency_code: str) -> Tuple[bool, Optional[str]]:
    """
    Validate an ISO 4217 currency code using pycountry.

    Args:
        currency_code: str - The currency code input by the user
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not currency_code or not currency_code.strip():
        return False, "Currency code cannot be empty. Please enter a valid currency code or use 'Skip'."
    
    currency_code = currency_code.strip().upper()

    if len(currency_code) != CURRENCY_CODE_LENGTH:
        return False, f"Currency code must be {CURRENCY_CODE_LENGTH} characters long. Please enter a valid currency code eg. (SGD, MYR, USD) etc."
    
    try:
        currency = pycountry.currencies.get(alpha_3=currency_code)
        if currency is None:
            return False, f"{currency_code} is not a valid currency code. Please enter a valid currency code eg. (SGD, MYR, USD) etc."
        return True, None
    except (AttributeError, KeyError) as e:
        logger.warning(f"Error validating currency code {currency_code}: {e}")
        return False, f"{currency_code} is not a valid currency code. Please enter a valid currency code eg. (SGD, MYR, USD) etc."
    except Exception as e:
        logger.error(f"An unexpected error occurred while validating currency code {currency_code}: {e}", exc_info=True)
        return False, f"An unexpected error occurred while validating currency code {currency_code}. Please try again."
