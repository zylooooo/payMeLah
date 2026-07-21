from html import escape as _html_escape

from .decorators import validate_chat_type
from .nudge_limiter import can_nudge, cooldown_remaining, record_nudge
from .rate_limiter import rate_limit

ERROR_MSG: str = "An unexpected error has occurred. Please try again later."


def h(text) -> str:
    """HTML-escape any user-supplied content before embedding in HTML messages."""
    if text is None:
        return ''
    return _html_escape(str(text))


def get_display_name(user_data: dict) -> str:
    """
    Return an HTML-escaped display name from a user data dict.
    Prefers first+last name, falls back to username, then 'User <id>'.
    Accepts dicts with keys: first_name, last_name, username, user_id or id.
    """
    if user_data.get('first_name'):
        name = user_data['first_name']
        if user_data.get('last_name'):
            name += f" {user_data['last_name']}"
        return h(name)
    uid = user_data.get('user_id') or user_data.get('id')
    return h(user_data.get('username') or f"User {uid}")


__all__ = ["validate_chat_type", "rate_limit", "h", "ERROR_MSG", "get_display_name", "can_nudge", "record_nudge", "cooldown_remaining"]
