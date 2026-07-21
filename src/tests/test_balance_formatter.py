"""
Unit tests for _format_group_balances_message() in balance_handler.
Tests the My Stats section (private chat) and group-chat hint rendering,
including balance sign formatting and the None-stats guard.
"""
from decimal import Decimal

from bot.handlers.balance_handler import _format_group_balances_message


def _make_balances(requesting_user_stats=None):
    return {
        'group': {'name': 'Trip to Bali'},
        'members': [
            {'user_id': 1, 'first_name': 'Alice', 'last_name': None, 'username': None, 'balance': Decimal('50.00')},
            {'user_id': 2, 'first_name': 'Bob', 'last_name': None, 'username': None, 'balance': Decimal('-50.00')},
        ],
        'debts': [{'from_user_id': 2, 'to_user_id': 1, 'amount': Decimal('50.00')}],
        'currency': 'SGD',
        'conversion_warnings': [],
        'total_spend': Decimal('100.00'),
        'per_currency_totals': {'SGD': Decimal('100.00')},
        'requesting_user_stats': requesting_user_stats,
    }


class TestFormatGroupBalancesMessageMyStats:
    def test_private_chat_shows_my_stats_section(self):
        stats = {
            'total_paid': Decimal('100.00'),
            'total_share': Decimal('50.00'),
            'net_balance': Decimal('50.00'),
        }
        msg = _format_group_balances_message(_make_balances(stats), is_private=True)
        assert 'My Stats' in msg
        assert 'My expenses' in msg
        assert 'Total amount paid first' in msg
        assert 'My balance' in msg

    def test_private_positive_balance_shows_plus_sign(self):
        stats = {'total_paid': Decimal('100.00'), 'total_share': Decimal('50.00'), 'net_balance': Decimal('50.00')}
        msg = _format_group_balances_message(_make_balances(stats), is_private=True)
        assert '+SGD 50.00' in msg

    def test_private_negative_balance_shows_minus_sign(self):
        stats = {'total_paid': Decimal('50.00'), 'total_share': Decimal('100.00'), 'net_balance': Decimal('-50.00')}
        msg = _format_group_balances_message(_make_balances(stats), is_private=True)
        assert '-SGD 50.00' in msg

    def test_private_zero_balance_shows_settled_up(self):
        stats = {'total_paid': Decimal('50.00'), 'total_share': Decimal('50.00'), 'net_balance': Decimal('0')}
        msg = _format_group_balances_message(_make_balances(stats), is_private=True)
        assert 'My balance:              Settled up' in msg
        assert 'My Stats' in msg

    def test_group_chat_does_not_show_my_stats(self):
        stats = {'total_paid': Decimal('100.00'), 'total_share': Decimal('50.00'), 'net_balance': Decimal('50.00')}
        msg = _format_group_balances_message(_make_balances(stats), is_private=False)
        assert 'My Stats' not in msg

    def test_group_chat_shows_private_hint(self):
        msg = _format_group_balances_message(_make_balances(), is_private=False)
        assert '💡' in msg
        assert 'Send me a private message' in msg

    def test_private_chat_no_stats_no_my_stats_section(self):
        """When requesting_user_stats is None, My Stats section and hint are both omitted in private."""
        msg = _format_group_balances_message(_make_balances(requesting_user_stats=None), is_private=True)
        assert 'My Stats' not in msg
        assert '💡' not in msg
