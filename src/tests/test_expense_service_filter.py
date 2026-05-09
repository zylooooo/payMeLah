"""
Tests for ExpenseService category filter parameters.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.expense_service import ExpenseService


class TestGetExpensesByGroupIdSignature:
    def test_category_param_defaults_to_none(self):
        """Verify category is an optional parameter with None default."""
        import inspect
        sig = inspect.signature(ExpenseService.get_expenses_by_group_id)
        assert 'category' in sig.parameters
        assert sig.parameters['category'].default is None

    def test_count_category_param_defaults_to_none(self):
        import inspect
        sig = inspect.signature(ExpenseService.get_expense_count_by_group_id)
        assert 'category' in sig.parameters
        assert sig.parameters['category'].default is None


class TestCategoryFilterLogic:

    def _make_db(self, count_value=5) -> AsyncMock:
        """
        Build a mock DB for get_expense_count_by_group_id tests.
        db.execute is called once for the count query; result.scalar() returns count_value.
        """
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = count_value
        db.execute.return_value = count_result
        return db

    @pytest.mark.asyncio
    async def test_no_filter_when_category_is_none(self):
        """When category=None, no category WHERE clause should be in the query."""
        db = self._make_db()

        with patch('services.expense_service.GroupService.get_group_by_id', new_callable=AsyncMock) as mock_get_group, \
             patch('services.expense_service.GroupService.is_member', new_callable=AsyncMock) as mock_is_member:
            mock_get_group.return_value = MagicMock()  # group exists
            mock_is_member.return_value = True          # user is a member

            await ExpenseService.get_expense_count_by_group_id(
                db, group_id=1, requesting_user_id=42, category=None
            )

        call_args = db.execute.call_args[0][0]
        compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
        assert 'category' not in compiled.lower()

    @pytest.mark.asyncio
    async def test_filter_applied_when_category_set(self):
        """When category is set, query should include a WHERE category = X clause."""
        db = self._make_db()

        with patch('services.expense_service.GroupService.get_group_by_id', new_callable=AsyncMock) as mock_get_group, \
             patch('services.expense_service.GroupService.is_member', new_callable=AsyncMock) as mock_is_member:
            mock_get_group.return_value = MagicMock()  # group exists
            mock_is_member.return_value = True          # user is a member

            await ExpenseService.get_expense_count_by_group_id(
                db, group_id=1, requesting_user_id=42, category='food_and_drink'
            )

        call_args = db.execute.call_args[0][0]
        compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
        assert 'food_and_drink' in compiled
