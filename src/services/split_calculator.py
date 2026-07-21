import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import List

from shared import InvalidSplitException

logger = logging.getLogger(__name__)

class SplitCalculator:
    """
    Class for calculating expense split operations.
    Supports equal, exact, percentage and custom split types.
    """

    # Precision for currency calculations (2 decimal places)
    PRECISION = Decimal('0.01')

    @staticmethod
    def calculate_equal_split(total: Decimal, participant_count: int) -> List[Decimal]:
        """
        Calculate equal split among participants.
        Handles rounding by giving remainder cents to the first few participant.

        Args:
            total: Decimal - Total expense amount.
            participant_count: int - Number of participants.

        Returns:
            List[Decimal] - List of share amounts for each participant.
        """
        if participant_count <= 0:
            logger.warning(f"Invalid participant count: {participant_count}. Must be greater than 0.")
            raise InvalidSplitException("There must be at least one participant to split the expense.")

        total = Decimal(str(total))
        base_share = (total / participant_count).quantize(
            SplitCalculator.PRECISION, rounding=ROUND_HALF_UP
        )

        # Calculate remainder to distribute
        total_distributed = base_share * participant_count
        remainder = total - total_distributed
        remainder_cents = int(remainder / SplitCalculator.PRECISION)

        shares = []
        for i in range(participant_count):
            share = base_share
            if i < abs(remainder_cents):
                adjustment = SplitCalculator.PRECISION if remainder_cents > 0 else -SplitCalculator.PRECISION
                share += adjustment
            shares.append(share)

        return shares

    @staticmethod
    def calculate_exact_split(total: Decimal, amounts: List[Decimal]) -> List[Decimal]:
        """
        Validate and return exact split amounts.

        Args:
            total: Decimal - Total expense amount.
            amounts: List[Decimal] - List of exact split amounts given by the user.

        Returns:
            List[Decimal] - List of share amounts for each participant.
        """
        total = Decimal(str(total))
        amounts = [Decimal(str(a)).quantize(SplitCalculator.PRECISION) for a in amounts]

        # Check if the sum of split amounts matches the total amount
        amounts_sum = sum(amounts)
        if abs(amounts_sum - total) > SplitCalculator.PRECISION:
            logger.warning(
                f"Exact split validation failed: split amounts sum ({amounts_sum}) "
                f"does not match total amount ({total})"
            )
            raise InvalidSplitException(
                f"Split amounts {amounts_sum} do not match the total amount {total}"
            )

        return amounts

    @staticmethod
    def calculate_percentage_split(total: Decimal, percentages: List[Decimal]) -> List[Decimal]:
        """
        Calculate split based on percentages provided by the user.
        Handles rounding by giving the remainder cents to the first participant

        Args:
            total: Decimal - Total expense amount.
            percentages: List[Decimal] - List of percentages for each participant.

        Returns:
            List[Decimal] - List of share amounts for each participant.
        """
        total = Decimal(str(total))
        percentages = [Decimal(str(p)) for p in percentages]

        percentages_sum = sum(percentages)
        if abs(percentages_sum - Decimal('100')) > Decimal('0.01'):
            logger.warning(
                f"Percentage split validation failed: percentages sum ({percentages_sum}%) "
                f"does not equal 100%"
            )
            raise InvalidSplitException(
                f"Percentages must sum up to 100% but got {percentages_sum}"
            )

        shares = []
        for percentage in percentages:
            share = (total * percentage / Decimal('100')).quantize(
                SplitCalculator.PRECISION, rounding=ROUND_HALF_UP
            )
            shares.append(share)

        # Adjust for rounding errors
        diff = total - sum(shares)
        if diff != 0 and shares:
            shares[0] += diff

        return shares

    @staticmethod
    def calculate_custom_split(total: Decimal, shares: List[int]) -> List[Decimal]:
        """
        Calculate split based on share ratios provided by the user.
        E.g. [1, 2, 1] = [25%, 50%, 25%]
        Handles rounding by giving the remainder cents to the first participant.

        Args:
            total: Decimal - Total expense amount.
            shares: List of share ratios (integers)

        Returns:
            List[Decimal] - List of share amounts for each participant.
        """
        total = Decimal(str(total))
        total_shares = sum(shares)

        if total_shares <= 0:
            logger.warning(f"Invalid custom split: total share ratios ({total_shares}) must be greater than 0")
            raise InvalidSplitException("Total share ratios must be greater than 0")

        amounts = []
        for share in shares:
            amount = (total * Decimal(share) / Decimal(total_shares)).quantize(
                SplitCalculator.PRECISION, rounding=ROUND_HALF_UP
            )
            amounts.append(amount)

        # Adjust for rounding
        diff = total - sum(amounts)
        if diff != 0 and amounts:
            amounts[0] += diff

        return amounts
