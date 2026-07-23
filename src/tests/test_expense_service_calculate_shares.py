"""
Tests for ExpenseService._calculate_shares — table-driven split validation.
"""

from decimal import Decimal

import pytest

from models import ExpenseSplitType
from services.expense_service import ExpenseService
from shared import ExpenseValidationException, InvalidSplitException


class TestCalculateSharesEqual:
    def test_equal_split_ignores_split_data(self):
        shares = ExpenseService._calculate_shares(
            Decimal("100"), ExpenseSplitType.EQUAL, [1, 2], split_data=None
        )
        assert shares == [Decimal("50"), Decimal("50")]


class TestCalculateSharesExact:
    def test_missing_split_data_raises(self):
        with pytest.raises(ExpenseValidationException, match="Exact amounts are required"):
            ExpenseService._calculate_shares(
                Decimal("100"), ExpenseSplitType.EXACT, [1, 2], split_data=None
            )

    def test_missing_amounts_key_raises(self):
        with pytest.raises(ExpenseValidationException, match="Exact amounts are required"):
            ExpenseService._calculate_shares(
                Decimal("100"), ExpenseSplitType.EXACT, [1, 2], split_data={}
            )

    def test_length_mismatch_raises(self):
        with pytest.raises(ExpenseValidationException, match="must match number of participants"):
            ExpenseService._calculate_shares(
                Decimal("100"),
                ExpenseSplitType.EXACT,
                [1, 2],
                split_data={"amounts": [Decimal("100")]},
            )

    def test_valid_exact_split(self):
        shares = ExpenseService._calculate_shares(
            Decimal("100"),
            ExpenseSplitType.EXACT,
            [1, 2],
            split_data={"amounts": [Decimal("40"), Decimal("60")]},
        )
        assert shares == [Decimal("40"), Decimal("60")]


class TestCalculateSharesPercentage:
    def test_missing_percentages_key_raises(self):
        with pytest.raises(ExpenseValidationException, match="Split percentages are required"):
            ExpenseService._calculate_shares(
                Decimal("100"), ExpenseSplitType.PERCENTAGE, [1, 2], split_data={}
            )

    def test_length_mismatch_raises(self):
        with pytest.raises(ExpenseValidationException, match="must match number of participants"):
            ExpenseService._calculate_shares(
                Decimal("100"),
                ExpenseSplitType.PERCENTAGE,
                [1, 2],
                split_data={"percentages": [Decimal("100")]},
            )

    def test_valid_percentage_split(self):
        shares = ExpenseService._calculate_shares(
            Decimal("100"),
            ExpenseSplitType.PERCENTAGE,
            [1, 2],
            split_data={"percentages": [Decimal("30"), Decimal("70")]},
        )
        assert shares == [Decimal("30"), Decimal("70")]


class TestCalculateSharesCustom:
    def test_missing_shares_key_raises(self):
        with pytest.raises(ExpenseValidationException, match="Share ratios are required"):
            ExpenseService._calculate_shares(
                Decimal("100"), ExpenseSplitType.CUSTOM, [1, 2], split_data={}
            )

    def test_length_mismatch_raises(self):
        with pytest.raises(ExpenseValidationException, match="must match number of participants"):
            ExpenseService._calculate_shares(
                Decimal("100"), ExpenseSplitType.CUSTOM, [1, 2], split_data={"shares": [1]}
            )

    def test_valid_custom_split(self):
        shares = ExpenseService._calculate_shares(
            Decimal("100"), ExpenseSplitType.CUSTOM, [1, 2], split_data={"shares": [1, 3]}
        )
        assert shares == [Decimal("25"), Decimal("75")]


class TestCalculateSharesInvalidType:
    def test_invalid_split_type_raises(self):
        with pytest.raises(InvalidSplitException, match="Invalid split type"):
            ExpenseService._calculate_shares(Decimal("100"), "not_a_split_type", [1, 2])
