"""Unit tests for the nudge cooldown limiter."""
from datetime import datetime, timedelta, timezone

import pytest

import bot.utils.nudge_limiter as nl


@pytest.fixture(autouse=True)
def reset():
    """Clear limiter state before every test."""
    nl.clear_all()


class TestCanNudge:
    def test_first_nudge_always_allowed(self):
        assert nl.can_nudge(1, 2, 10) is True

    def test_blocked_immediately_after_nudge(self):
        nl.record_nudge(1, 2, 10)
        assert nl.can_nudge(1, 2, 10) is False

    def test_allowed_after_cooldown_expires(self):
        past = datetime.now(timezone.utc) - timedelta(hours=25)
        nl._nudge_log[(1, 2, 10)] = past
        assert nl.can_nudge(1, 2, 10) is True

    def test_different_group_independent(self):
        nl.record_nudge(1, 2, 10)
        assert nl.can_nudge(1, 2, 99) is True

    def test_different_nudgee_independent(self):
        nl.record_nudge(1, 2, 10)
        assert nl.can_nudge(1, 3, 10) is True

    def test_different_nudger_independent(self):
        nl.record_nudge(1, 2, 10)
        assert nl.can_nudge(9, 2, 10) is True


class TestCooldownRemaining:
    def test_no_cooldown_when_never_nudged(self):
        assert nl.cooldown_remaining(1, 2, 10) is None

    def test_returns_timedelta_when_active(self):
        nl.record_nudge(1, 2, 10)
        remaining = nl.cooldown_remaining(1, 2, 10)
        assert remaining is not None
        assert remaining.total_seconds() > 0
        assert remaining.total_seconds() <= 24 * 3600

    def test_returns_none_after_expiry(self):
        past = datetime.now(timezone.utc) - timedelta(hours=25)
        nl._nudge_log[(1, 2, 10)] = past
        assert nl.cooldown_remaining(1, 2, 10) is None
