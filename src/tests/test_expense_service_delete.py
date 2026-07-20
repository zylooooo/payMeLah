"""
Tests for expense deletion behavior:
- Settled expenses CAN be deleted (auth-only check for delete).
- Settled expenses still CANNOT be edited.
- Deletion cascades to participants so live balance computation stays correct.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import inspect as sa_inspect

from services.expense_service import ExpenseService
from models import Expense
from shared import (
    UnauthorizedActionException,
    ExpenseNotEditableException,
    ExpenseNotFoundException,
)


def _make_result(scalar_value):
    """Build a mock query result whose scalar_one_or_none() returns scalar_value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    return result


def _make_expense(expense_id=1, created_by=42, payer_id=42):
    expense = MagicMock()
    expense.id = expense_id
    expense.created_by = created_by
    expense.payer_id = payer_id
    return expense


class TestDeleteSettledExpense:
    """Delete must only require authorization (creator/payer), not settlement state."""

    @pytest.mark.asyncio
    async def test_delete_succeeds_when_participant_settled(self):
        """Deleting an expense with settled non-payer participants must succeed."""
        expense = _make_expense()
        settled_participant = MagicMock()  # a settled non-payer participant exists

        db = AsyncMock()
        # First query: expense lookup. Any subsequent query (settled check) would
        # find a settled participant — delete must not be blocked by it.
        db.execute.side_effect = [
            _make_result(expense),
            _make_result(settled_participant),
        ]

        result = await ExpenseService.delete_expense(db, expense_id=1, requesting_user_id=42)

        assert result is True
        db.delete.assert_awaited_once_with(expense)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_still_requires_authorization(self):
        """A user who is neither creator nor payer cannot delete."""
        expense = _make_expense(created_by=42, payer_id=42)

        db = AsyncMock()
        db.execute.side_effect = [
            _make_result(expense),
            _make_result(None),
        ]

        with pytest.raises(UnauthorizedActionException):
            await ExpenseService.delete_expense(db, expense_id=1, requesting_user_id=999)

        db.delete.assert_not_awaited()


class TestCanDeleteExpense:
    """Handler-facing check used to show the Delete button / gate confirmation."""

    @pytest.mark.asyncio
    async def test_can_delete_true_for_creator_even_when_settled(self):
        expense = _make_expense()
        db = AsyncMock()
        db.execute.side_effect = [
            _make_result(expense),
            _make_result(MagicMock()),  # settled participant exists
        ]

        can_delete, reason = await ExpenseService.can_delete_expense(
            db, expense_id=1, requesting_user_id=42
        )

        assert can_delete is True
        assert reason == ""

    @pytest.mark.asyncio
    async def test_can_delete_false_for_unrelated_user(self):
        expense = _make_expense(created_by=42, payer_id=42)
        db = AsyncMock()
        db.execute.side_effect = [
            _make_result(expense),
            _make_result(None),
        ]

        can_delete, reason = await ExpenseService.can_delete_expense(
            db, expense_id=1, requesting_user_id=999
        )

        assert can_delete is False
        assert reason != ""


class TestEditStillBlockedWhenSettled:
    """Regression: editing a settled expense remains blocked."""

    @pytest.mark.asyncio
    async def test_update_blocked_when_participant_settled(self):
        expense = _make_expense()
        db = AsyncMock()
        db.execute.side_effect = [
            _make_result(expense),
            _make_result(MagicMock()),  # settled non-payer participant
        ]

        with pytest.raises(ExpenseNotEditableException):
            await ExpenseService.update_expense(
                db, expense_id=1, update_data={'description': 'x'}, requesting_user_id=42
            )

    @pytest.mark.asyncio
    async def test_can_modify_false_when_participant_settled(self):
        expense = _make_expense()
        db = AsyncMock()
        db.execute.side_effect = [
            _make_result(expense),
            _make_result(MagicMock()),
        ]

        can_modify, reason = await ExpenseService.can_modify_expense(
            db, expense_id=1, requesting_user_id=42
        )

        assert can_modify is False
        assert "settled" in reason.lower()


class TestHasRelatedSettlements:
    """
    has_related_settlements powers the delete-confirmation warning: True when a
    non-payer participant is marked settled OR a payment from any non-payer
    participant to the payer exists in the expense's group (i.e. the debt may
    already have been paid via /settleup, which never sets is_settled).
    """

    def _expense(self):
        expense = _make_expense(payer_id=42)
        expense.group_id = 7
        return expense

    def _participants_result(self, rows):
        """rows: list of (user_id, is_settled) tuples."""
        result = MagicMock()
        result.all.return_value = rows
        return result

    @pytest.mark.asyncio
    async def test_true_when_non_payer_participant_settled(self):
        db = AsyncMock()
        db.execute.side_effect = [
            _make_result(self._expense()),
            self._participants_result([(99, True)]),
        ]
        assert await ExpenseService.has_related_settlements(db, expense_id=1) is True

    @pytest.mark.asyncio
    async def test_true_when_payment_from_participant_to_payer_exists(self):
        db = AsyncMock()
        db.execute.side_effect = [
            _make_result(self._expense()),
            self._participants_result([(99, False)]),
            _make_result(MagicMock()),  # a matching Payment row exists
        ]
        assert await ExpenseService.has_related_settlements(db, expense_id=1) is True

    @pytest.mark.asyncio
    async def test_false_when_no_settlement_and_no_payments(self):
        db = AsyncMock()
        db.execute.side_effect = [
            _make_result(self._expense()),
            self._participants_result([(99, False)]),
            _make_result(None),  # no matching Payment row
        ]
        assert await ExpenseService.has_related_settlements(db, expense_id=1) is False

    @pytest.mark.asyncio
    async def test_false_when_payer_is_only_participant(self):
        """No non-payer participants → nothing can be owed, no payment query needed."""
        db = AsyncMock()
        db.execute.side_effect = [
            _make_result(self._expense()),
            self._participants_result([]),
        ]
        assert await ExpenseService.has_related_settlements(db, expense_id=1) is False

    @pytest.mark.asyncio
    async def test_raises_when_expense_missing(self):
        db = AsyncMock()
        db.execute.side_effect = [_make_result(None)]
        with pytest.raises(ExpenseNotFoundException):
            await ExpenseService.has_related_settlements(db, expense_id=1)


class TestDeleteCascadesToParticipants:
    """
    Regression: balances are computed live from ExpenseParticipant rows, so
    deleting an expense must cascade-delete its participants for balances to
    update. Locks in the ORM cascade configuration that guarantees this.
    """

    def test_participants_relationship_has_delete_orphan_cascade(self):
        rel = sa_inspect(Expense).relationships['participants']
        assert rel.cascade.delete
        assert rel.cascade.delete_orphan
