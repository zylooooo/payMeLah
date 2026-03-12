"""
Unit tests for BalanceService._simplify_debts.
Tests the core debt simplification algorithm with various scenarios.
The algorithm should minimize the number of transactions to settle all debts.
"""
import pytest
from decimal import Decimal
from collections import defaultdict
from services.balance_service import BalanceService


def make_debts(pairs: list) -> dict:
    """Helper to build a net_debts dict from a list of (from_id, to_id, amount) tuples."""
    debts = {}
    for from_id, to_id, amount in pairs:
        debts[(from_id, to_id)] = Decimal(str(amount))
    return debts


class TestSimplifyDebts:
    def test_no_debts(self):
        result = BalanceService._simplify_debts({}, [1, 2, 3])
        assert result == []

    def test_single_debt_unchanged(self):
        """A simple A→B debt should remain unchanged."""
        debts = make_debts([(1, 2, '50.00')])
        result = BalanceService._simplify_debts(debts, [1, 2])
        assert len(result) == 1
        assert result[0]['from_user_id'] == 1
        assert result[0]['to_user_id'] == 2
        assert result[0]['amount'] == Decimal('50.00')

    def test_circular_debt_simplifies(self):
        """
        A owes B $10, B owes C $10, C owes A $10 → all net to zero.
        Simplified result should have 0 transactions.
        """
        debts = make_debts([(1, 2, '10.00'), (2, 3, '10.00'), (3, 1, '10.00')])
        result = BalanceService._simplify_debts(debts, [1, 2, 3])
        assert result == []

    def test_chain_debt_simplifies(self):
        """
        A owes B $10, B owes C $10.
        Simplified: A owes C $10 (1 transaction instead of 2).
        """
        debts = make_debts([(1, 2, '10.00'), (2, 3, '10.00')])
        result = BalanceService._simplify_debts(debts, [1, 2, 3])
        assert len(result) == 1
        assert result[0]['from_user_id'] == 1
        assert result[0]['to_user_id'] == 3
        assert result[0]['amount'] == Decimal('10.00')

    def test_total_amount_preserved(self):
        """Total debt amount should be the same before and after simplification."""
        debts = make_debts([
            (1, 2, '30.00'),
            (2, 3, '20.00'),
            (3, 4, '15.00'),
            (4, 1, '5.00'),
        ])
        member_ids = [1, 2, 3, 4]
        result = BalanceService._simplify_debts(debts, member_ids)

        # Each person's net balance should be preserved
        original_balances = defaultdict(Decimal)
        for (f, t), a in debts.items():
            original_balances[f] -= a
            original_balances[t] += a

        simplified_balances = defaultdict(Decimal)
        for txn in result:
            simplified_balances[txn['from_user_id']] -= txn['amount']
            simplified_balances[txn['to_user_id']] += txn['amount']

        for uid in member_ids:
            assert abs(original_balances[uid] - simplified_balances[uid]) < Decimal('0.01')

    def test_simplified_has_fewer_or_equal_transactions(self):
        """Simplified result should never have more transactions than raw debts."""
        debts = make_debts([
            (1, 2, '10.00'),
            (2, 3, '10.00'),
            (3, 4, '10.00'),
        ])
        result = BalanceService._simplify_debts(debts, [1, 2, 3, 4])
        assert len(result) <= 3

    def test_already_settled_returns_empty(self):
        """If net debts is empty, result should be empty."""
        result = BalanceService._simplify_debts({}, [1, 2, 3, 4, 5])
        assert result == []

    def test_all_amounts_positive(self):
        """All transaction amounts in result must be positive."""
        debts = make_debts([
            (1, 2, '25.00'),
            (3, 2, '15.00'),
            (1, 3, '10.00'),
        ])
        result = BalanceService._simplify_debts(debts, [1, 2, 3])
        for txn in result:
            assert txn['amount'] > 0
