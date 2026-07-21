"""
Simple per-user in-memory rate limiter for Telegram command handlers.

Limits each user to MAX_REQUESTS commands within WINDOW_SECONDS.
State is process-local — sufficient for single-instance free-tier deployment.
"""
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps

logger = logging.getLogger(__name__)

# Allow up to 5 commands per 10 seconds per user
MAX_REQUESTS = 5
WINDOW_SECONDS = 10

# {user_id: deque of UTC timestamps}
_request_log: dict = defaultdict(lambda: deque())


def _is_rate_limited(user_id: int) -> bool:
    """Return True if the user has exceeded the rate limit."""
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - WINDOW_SECONDS
    bucket = _request_log[user_id]

    # Drop timestamps outside the window
    while bucket and bucket[0] < cutoff:
        bucket.popleft()

    if len(bucket) >= MAX_REQUESTS:
        return True

    bucket.append(now)
    return False


def rate_limit(func):
    """
    Decorator that rejects commands from users who exceed the rate limit.
    Apply to command handler coroutines.
    """
    @wraps(func)
    async def wrapper(update, context):
        user = update.effective_user
        if user and _is_rate_limited(user.id):
            logger.warning(f"Rate limit hit for user {user.id}")
            if update.message:
                await update.message.reply_text(
                    "You are sending commands too quickly. Please slow down."
                )
            return
        return await func(update, context)
    return wrapper
