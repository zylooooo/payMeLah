from datetime import datetime, timedelta, timezone
from typing import Optional

_COOLDOWN = timedelta(hours=24)

# {(nudger_id, nudgee_id, group_id): datetime of last nudge (UTC)}
_nudge_log: dict[tuple[int, int, int], datetime] = {}


def _key(nudger_id: int, nudgee_id: int, group_id: int) -> tuple[int, int, int]:
    return (nudger_id, nudgee_id, group_id)


def can_nudge(nudger_id: int, nudgee_id: int, group_id: int) -> bool:
    """Return True if the cooldown has expired (or was never set)."""
    last = _nudge_log.get(_key(nudger_id, nudgee_id, group_id))
    if last is None:
        return True
    return datetime.now(timezone.utc) - last >= _COOLDOWN


def record_nudge(nudger_id: int, nudgee_id: int, group_id: int) -> None:
    """Record that a nudge was just sent."""
    _nudge_log[_key(nudger_id, nudgee_id, group_id)] = datetime.now(timezone.utc)


def cooldown_remaining(nudger_id: int, nudgee_id: int, group_id: int) -> Optional[timedelta]:
    """Return the remaining cooldown duration, or None if no cooldown is active."""
    last = _nudge_log.get(_key(nudger_id, nudgee_id, group_id))
    if last is None:
        return None
    elapsed = datetime.now(timezone.utc) - last
    remaining = _COOLDOWN - elapsed
    return remaining if remaining.total_seconds() > 0 else None


def clear_all() -> None:
    """Clear all cooldown records. Used in tests."""
    _nudge_log.clear()
