"""
Unit tests for PaymentService.record_payment and delete_payment.
Tests validation rules and authorization without a real database.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.payment_service import PaymentService
from shared import GroupMemberNotFoundException, UnauthorizedActionException

PAYER_ID = 1
RECIPIENT_ID = 2
GROUP_ID = 10
CURRENCY = "SGD"


def _make_member_mock(user_id: int) -> MagicMock:
    m = MagicMock()
    m.user_id = user_id
    return m


def _make_payment_mock(payment_id: int, from_user_id: int) -> MagicMock:
    p = MagicMock()
    p.id = payment_id
    p.from_user_id = from_user_id
    p.to_dict.return_value = {'id': payment_id, 'from_user_id': from_user_id}
    return p


def _make_db(payer_member=None, recipient_member=None) -> AsyncMock:
    """
    Build a mock DB for record_payment tests.
    Execute call order:
      1. Deduplication check  → no duplicate (returns None)
      2. Payer membership check
      3. Recipient membership check
    """
    db = AsyncMock()

    no_dup_result = MagicMock()
    no_dup_result.scalar_one_or_none.return_value = None  # no duplicate payment

    payer_result = MagicMock()
    payer_result.scalar_one_or_none.return_value = payer_member

    recipient_result = MagicMock()
    recipient_result.scalar_one_or_none.return_value = recipient_member

    db.execute.side_effect = [no_dup_result, payer_result, recipient_result]
    return db


class TestRecordPayment:

    @pytest.mark.asyncio
    async def test_records_valid_payment(self):
        """Happy path: both users are members, amount is positive."""
        db = _make_db(
            payer_member=_make_member_mock(PAYER_ID),
            recipient_member=_make_member_mock(RECIPIENT_ID)
        )
        # db.refresh is a no-op; Payment.__init__ sets attributes so to_dict() works
        db.refresh = AsyncMock(return_value=None)

        result = await PaymentService.record_payment(
            db, GROUP_ID, PAYER_ID, RECIPIENT_ID, Decimal('50.00'), CURRENCY
        )

        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        assert result['from_user_id'] == PAYER_ID

    @pytest.mark.asyncio
    async def test_raises_if_paying_self(self):
        """Cannot record a payment to yourself."""
        db = AsyncMock()
        with pytest.raises(ValueError, match="yourself"):
            await PaymentService.record_payment(
                db, GROUP_ID, PAYER_ID, PAYER_ID, Decimal('10.00'), CURRENCY
            )
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_if_amount_zero(self):
        """Amount must be positive."""
        db = AsyncMock()
        with pytest.raises(ValueError, match="greater than zero"):
            await PaymentService.record_payment(
                db, GROUP_ID, PAYER_ID, RECIPIENT_ID, Decimal('0.00'), CURRENCY
            )
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_if_amount_negative(self):
        db = AsyncMock()
        with pytest.raises(ValueError, match="greater than zero"):
            await PaymentService.record_payment(
                db, GROUP_ID, PAYER_ID, RECIPIENT_ID, Decimal('-5.00'), CURRENCY
            )

    @pytest.mark.asyncio
    async def test_raises_if_payer_not_member(self):
        """Payer must be a group member."""
        db = _make_db(payer_member=None, recipient_member=_make_member_mock(RECIPIENT_ID))
        with pytest.raises(GroupMemberNotFoundException, match=str(PAYER_ID)):
            await PaymentService.record_payment(
                db, GROUP_ID, PAYER_ID, RECIPIENT_ID, Decimal('20.00'), CURRENCY
            )
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_if_recipient_not_member(self):
        """Recipient must be a group member."""
        db = _make_db(payer_member=_make_member_mock(PAYER_ID), recipient_member=None)
        with pytest.raises(GroupMemberNotFoundException, match=str(RECIPIENT_ID)):
            await PaymentService.record_payment(
                db, GROUP_ID, PAYER_ID, RECIPIENT_ID, Decimal('20.00'), CURRENCY
            )
        db.commit.assert_not_awaited()


class TestDeletePayment:

    def _make_delete_db(self, payment=None) -> AsyncMock:
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = payment
        db.execute.return_value = result
        return db

    @pytest.mark.asyncio
    async def test_payer_can_delete_own_payment(self):
        """The payer (from_user_id) can delete their own payment."""
        payment = _make_payment_mock(1, PAYER_ID)
        db = self._make_delete_db(payment)

        result = await PaymentService.delete_payment(db, payment_id=1, requesting_user_id=PAYER_ID)

        assert result is True
        db.delete.assert_awaited_once_with(payment)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_payer_cannot_delete(self):
        """Only the payer can delete a payment."""
        payment = _make_payment_mock(1, PAYER_ID)
        db = self._make_delete_db(payment)

        with pytest.raises(UnauthorizedActionException, match="Only the payer"):
            await PaymentService.delete_payment(db, payment_id=1, requesting_user_id=RECIPIENT_ID)

        db.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_if_payment_not_found(self):
        """Deleting a non-existent payment raises ValueError."""
        db = self._make_delete_db(payment=None)

        with pytest.raises(ValueError, match="not found"):
            await PaymentService.delete_payment(db, payment_id=999, requesting_user_id=PAYER_ID)

        db.delete.assert_not_awaited()
