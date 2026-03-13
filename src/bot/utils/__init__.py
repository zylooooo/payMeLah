from .decorators import validate_chat_type
from .rate_limiter import rate_limit
from html import escape as _html_escape


def h(text) -> str:
    """HTML-escape any user-supplied content before embedding in HTML messages."""
    if text is None:
        return ''
    return _html_escape(str(text))


__all__ = ["validate_chat_type", "rate_limit", "h"]