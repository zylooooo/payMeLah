"""
Unit tests for SplitCalculator.
Tests cover all four split types and critical edge cases including rounding.
"""
import pytest
from decimal import Decimal
from services.split_calculator import SplitCalculator
from shared import InvalidSplitException


class TestEqualSplit:
    def test_equal_split_basic(self):
        shares = SplitCalculator.calculate_equal_split(Decimal('30.00'), 3)
        assert shares == [Decimal('10.00'), Decimal('10.00'), Decimal('10.00')]
        assert sum(shares) == Decimal('30.00')

    def test_equal_split_with_remainder(self):
        """$10 split 3 ways: two get $3.33, one gets $3.34."""
        shares = SplitCalculator.calculate_equal_split(Decimal('10.00'), 3)
        assert sum(shares) == Decimal('10.00')
        assert len(shares) == 3

    def test_equal_split_single_participant(self):
        shares = SplitCalculator.calculate_equal_split(Decimal('50.00'), 1)
        assert shares == [Decimal('50.00')]

    def test_equal_split_zero_participants_raises(self):
        with pytest.raises(InvalidSplitException):
            SplitCalculator.calculate_equal_split(Decimal('100.00'), 0)

    def test_equal_split_negative_participants_raises(self):
        with pytest.raises(InvalidSplitException):
            SplitCalculator.calculate_equal_split(Decimal('100.00'), -1)


class TestExactSplit:
    def test_exact_split_valid(self):
        amounts = [Decimal('20.00'), Decimal('30.00'), Decimal('50.00')]
        result = SplitCalculator.calculate_exact_split(Decimal('100.00'), amounts)
        assert result == amounts

    def test_exact_split_mismatch_raises(self):
        amounts = [Decimal('20.00'), Decimal('30.00')]
        with pytest.raises(InvalidSplitException):
            SplitCalculator.calculate_exact_split(Decimal('100.00'), amounts)

    def test_exact_split_two_participants(self):
        amounts = [Decimal('15.50'), Decimal('14.50')]
        result = SplitCalculator.calculate_exact_split(Decimal('30.00'), amounts)
        assert sum(result) == Decimal('30.00')


class TestPercentageSplit:
    def test_percentage_split_basic(self):
        shares = SplitCalculator.calculate_percentage_split(
            Decimal('100.00'), [Decimal('50'), Decimal('50')]
        )
        assert shares == [Decimal('50.00'), Decimal('50.00')]

    def test_percentage_split_uneven(self):
        shares = SplitCalculator.calculate_percentage_split(
            Decimal('100.00'), [Decimal('30'), Decimal('70')]
        )
        assert sum(shares) == Decimal('100.00')

    def test_percentage_split_not_100_raises(self):
        with pytest.raises(InvalidSplitException):
            SplitCalculator.calculate_percentage_split(
                Decimal('100.00'), [Decimal('40'), Decimal('40')]
            )

    def test_percentage_split_rounding_sums_to_total(self):
        """Three-way split with rounding — must sum to total exactly."""
        shares = SplitCalculator.calculate_percentage_split(
            Decimal('10.00'),
            [Decimal('33.33'), Decimal('33.33'), Decimal('33.34')]
        )
        assert sum(shares) == Decimal('10.00')


class TestCustomSplit:
    def test_custom_split_equal_ratios(self):
        shares = SplitCalculator.calculate_custom_split(Decimal('100.00'), [1, 1, 1, 1])
        assert sum(shares) == Decimal('100.00')
        assert all(s == Decimal('25.00') for s in shares)

    def test_custom_split_unequal_ratios(self):
        shares = SplitCalculator.calculate_custom_split(Decimal('100.00'), [1, 2, 1])
        assert sum(shares) == Decimal('100.00')
        assert shares[1] == shares[0] * 2

    def test_custom_split_zero_total_raises(self):
        with pytest.raises(InvalidSplitException):
            SplitCalculator.calculate_custom_split(Decimal('100.00'), [0, 0])
