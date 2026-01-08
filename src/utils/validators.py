import pycountry
import logging
from typing import Tuple, Optional, List
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

# Constants
MAX_NAME_LENGTH = 64
MAX_GROUP_NAME_LENGTH = 255
CURRENCY_CODE_LENGTH = 3
MAX_EXPENSE_AMOUNT = Decimal('99999999.99')
MIN_EXPENSE_AMOUNT = Decimal('0.01')
MAX_DESCRIPTION_LENGTH = 500


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


def validate_group_name(name: str) -> Tuple[bool, Optional[str]]:
    """
    Validate if the user's input group name is valid.

    Args:
        name: str - The group name to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name or not name.strip():
        return False, "Group name cannot be empty. Please enter a valid group name between 1 and 255 characters."
    
    name = name.strip()

    if len(name) > MAX_GROUP_NAME_LENGTH:
        return False, f"Group name must be between 1 and {MAX_GROUP_NAME_LENGTH} characters. Please enter a valid group name."
    
    return True, None

def validate_expense_amount(amount_str: str) -> Tuple[bool, Optional[str], Optional[Decimal]]:
    """
    Validate expense amount input by the user.

    Args:
        amount_str: str - The expense amount input by the user

    Returns:
        Tuple of (is_valid, error_message, validated_amount)
    """
    if not amount_str or not amount_str.strip():
        return False, "Amount cannot be empty.", None
    
    # Remove currency symbols and whitespace
    cleaned = amount_str.strip().replace('$', '').replace(',', '')

    try:
        amount = Decimal(cleaned).quantize(Decimal('0.01'))

        if amount < MIN_EXPENSE_AMOUNT:
            return False, f"Amount cannot be less than {MIN_EXPENSE_AMOUNT}", None
        if amount > MAX_EXPENSE_AMOUNT:
            return False, f"Amount cannot be greater than {MAX_EXPENSE_AMOUNT}", None
        
        return True, None, amount
    except InvalidOperation:
        return False, "Invalid amount. Please enter a valid number (e.g., 25.50)", None
    
def validate_exact_split_amount(
    amount_str: str, 
    total_amount: Decimal,
    already_allocated: Decimal = Decimal('0')
) -> Tuple[bool, Optional[str], Optional[Decimal]]:
    """
    Validate an individual exact split amount against the total expense amount.

    Args:
        amount_str: str - The amount input by the user
        total_amount: Decimal - The total expense amount
        already_allocated: Decimal - Sum of amounts already allocated to other participants
    
    Returns:
        Tuple of (is_valid, error_message, validated_amount)
    """
    # First, perform basic amount validation
    is_valid, error_msg, validated_amount = validate_expense_amount(amount_str)
    
    if not is_valid:
        return False, error_msg, None
    
    # Check if the individual amount exceeds the total expense
    if validated_amount > total_amount:
        return False, f"Amount cannot exceed the total expense of {total_amount}", None
    
    # Check if the amount exceeds the remaining unallocated amount
    remaining = total_amount - already_allocated
    if validated_amount > remaining:
        return False, f"Amount cannot exceed the remaining amount of {remaining}", None
    
    return True, None, validated_amount

def validate_expense_description(description: str) -> Tuple[bool, Optional[str]]:
    """
    Validate expense description input by the user.

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Allow for empty or no description
    if not description or not description.strip():
        return True, None

    description = description.strip()

    # Date type is set to be TEXT in the database, but just set a soft cap to reduce data size 
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return False, f"Description cannot be longer than {MAX_DESCRIPTION_LENGTH} characters."
    
    return True, None
