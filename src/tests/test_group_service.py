"""
Unit tests for GroupService.update_member_role.
Tests all authorization rules and valid role transitions without a real database.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import GroupMemberRole
from services.group_service import GroupService
from shared import (
    GroupMemberNotFoundException,
    OutstandingBalanceException,
    UnauthorizedActionException,
)


def _make_member_mock(role: GroupMemberRole, user_id: int, group_id: int = 1) -> MagicMock:
    """Build a mock GroupMember ORM object."""
    member = MagicMock()
    member.role = role
    member.user_id = user_id
    member.group_id = group_id
    member.to_dict.return_value = {
        'user_id': user_id,
        'group_id': group_id,
        'role': role.value,
    }
    return member


def _make_db(target_member=None) -> AsyncMock:
    """Build a mock AsyncSession that returns target_member from execute()."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = target_member
    db.execute.return_value = result
    return db


OWNER_ID = 10
ADMIN_ID = 20
MEMBER_ID = 30
GROUP_ID = 1


class TestUpdateMemberRole:

    @pytest.mark.asyncio
    @patch.object(GroupService, 'get_member_role', new_callable=AsyncMock)
    async def test_owner_promotes_member_to_admin(self, mock_get_role):
        """Owner can promote a regular member to admin."""
        mock_get_role.return_value = GroupMemberRole.OWNER
        target = _make_member_mock(GroupMemberRole.MEMBER, MEMBER_ID)
        db = _make_db(target)

        result = await GroupService.update_member_role(
            db, GROUP_ID, MEMBER_ID, GroupMemberRole.ADMIN, OWNER_ID
        )

        assert target.role == GroupMemberRole.ADMIN
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(target)
        assert result['user_id'] == MEMBER_ID

    @pytest.mark.asyncio
    @patch.object(GroupService, 'get_member_role', new_callable=AsyncMock)
    async def test_owner_demotes_admin_to_member(self, mock_get_role):
        """Owner can demote an admin back to member."""
        mock_get_role.return_value = GroupMemberRole.OWNER
        target = _make_member_mock(GroupMemberRole.ADMIN, ADMIN_ID)
        db = _make_db(target)

        await GroupService.update_member_role(
            db, GROUP_ID, ADMIN_ID, GroupMemberRole.MEMBER, OWNER_ID
        )

        assert target.role == GroupMemberRole.MEMBER
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    @patch.object(GroupService, 'get_member_role', new_callable=AsyncMock)
    async def test_admin_cannot_change_roles(self, mock_get_role):
        """An admin trying to change roles should be rejected."""
        mock_get_role.return_value = GroupMemberRole.ADMIN
        db = _make_db()

        with pytest.raises(UnauthorizedActionException, match="Only the group owner"):
            await GroupService.update_member_role(
                db, GROUP_ID, MEMBER_ID, GroupMemberRole.ADMIN, ADMIN_ID
            )

        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch.object(GroupService, 'get_member_role', new_callable=AsyncMock)
    async def test_member_cannot_change_roles(self, mock_get_role):
        """A regular member trying to change roles should be rejected."""
        mock_get_role.return_value = GroupMemberRole.MEMBER
        db = _make_db()

        with pytest.raises(UnauthorizedActionException, match="Only the group owner"):
            await GroupService.update_member_role(
                db, GROUP_ID, ADMIN_ID, GroupMemberRole.MEMBER, MEMBER_ID
            )

        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch.object(GroupService, 'get_member_role', new_callable=AsyncMock)
    async def test_owner_cannot_change_own_role(self, mock_get_role):
        """Owner cannot change their own role."""
        mock_get_role.return_value = GroupMemberRole.OWNER
        db = _make_db()

        with pytest.raises(UnauthorizedActionException, match="cannot change your own role"):
            await GroupService.update_member_role(
                db, GROUP_ID, OWNER_ID, GroupMemberRole.MEMBER, OWNER_ID
            )

        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch.object(GroupService, 'get_member_role', new_callable=AsyncMock)
    async def test_cannot_promote_to_owner(self, mock_get_role):
        """Ownership transfer should be rejected regardless of requester."""
        mock_get_role.return_value = GroupMemberRole.OWNER
        db = _make_db()

        with pytest.raises(UnauthorizedActionException, match="Ownership transfer"):
            await GroupService.update_member_role(
                db, GROUP_ID, MEMBER_ID, GroupMemberRole.OWNER, OWNER_ID
            )

        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch.object(GroupService, 'get_member_role', new_callable=AsyncMock)
    async def test_target_not_a_member_raises(self, mock_get_role):
        """Attempting to change the role of a non-member raises GroupMemberNotFoundException."""
        mock_get_role.return_value = GroupMemberRole.OWNER
        db = _make_db(target_member=None)  # No member found

        with pytest.raises(GroupMemberNotFoundException):
            await GroupService.update_member_role(
                db, GROUP_ID, 999, GroupMemberRole.ADMIN, OWNER_ID
            )

        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch.object(GroupService, 'get_member_role', new_callable=AsyncMock)
    async def test_cannot_change_another_owners_role(self, mock_get_role):
        """Cannot change the role of a user who is already an owner (edge case: multiple owners)."""
        mock_get_role.return_value = GroupMemberRole.OWNER
        # target_member is also an owner
        target = _make_member_mock(GroupMemberRole.OWNER, 99)
        db = _make_db(target)

        with pytest.raises(UnauthorizedActionException, match="Cannot change the owner"):
            await GroupService.update_member_role(
                db, GROUP_ID, 99, GroupMemberRole.MEMBER, OWNER_ID
            )

        db.commit.assert_not_awaited()


def _balances(user_id: int, balance: str, currency: str = "SGD") -> dict:
    """Shape returned by BalanceService.get_group_balances, trimmed to what the guard reads."""
    return {"members": [{"user_id": user_id, "balance": Decimal(balance)}], "currency": currency}


class TestSettleBeforeLeaving:
    """Members with a non-zero balance cannot leave or be removed."""

    @pytest.mark.asyncio
    @patch("services.balance_service.BalanceService.get_group_balances", new_callable=AsyncMock)
    async def test_leave_blocked_when_member_owes(self, mock_balances):
        mock_balances.return_value = _balances(MEMBER_ID, "-12.50")
        db = _make_db(_make_member_mock(GroupMemberRole.MEMBER, MEMBER_ID))

        with pytest.raises(OutstandingBalanceException) as exc:
            await GroupService.leave_group(db, GROUP_ID, MEMBER_ID)

        assert exc.value.amount == Decimal("-12.50")
        assert exc.value.currency == "SGD"
        db.delete.assert_not_called()

    @pytest.mark.asyncio
    @patch("services.balance_service.BalanceService.get_group_balances", new_callable=AsyncMock)
    async def test_leave_blocked_when_member_is_owed(self, mock_balances):
        mock_balances.return_value = _balances(MEMBER_ID, "5.00")
        db = _make_db(_make_member_mock(GroupMemberRole.MEMBER, MEMBER_ID))

        with pytest.raises(OutstandingBalanceException):
            await GroupService.leave_group(db, GROUP_ID, MEMBER_ID)

    @pytest.mark.asyncio
    @patch("services.balance_service.BalanceService.get_group_balances", new_callable=AsyncMock)
    async def test_leave_allowed_when_settled(self, mock_balances):
        mock_balances.return_value = _balances(MEMBER_ID, "0.00")
        member = _make_member_mock(GroupMemberRole.MEMBER, MEMBER_ID)
        db = _make_db(member)

        assert await GroupService.leave_group(db, GROUP_ID, MEMBER_ID) is True
        db.delete.assert_awaited_once_with(member)

    @pytest.mark.asyncio
    @patch("services.balance_service.BalanceService.get_group_balances", new_callable=AsyncMock)
    @patch.object(GroupService, "get_member_role", new_callable=AsyncMock)
    async def test_remove_blocked_when_target_has_balance(self, mock_role, mock_balances):
        mock_role.return_value = GroupMemberRole.OWNER
        mock_balances.return_value = _balances(MEMBER_ID, "-3.00")
        db = _make_db(_make_member_mock(GroupMemberRole.MEMBER, MEMBER_ID))

        with pytest.raises(OutstandingBalanceException):
            await GroupService.remove_member(db, GROUP_ID, MEMBER_ID, OWNER_ID)
        db.delete.assert_not_called()

    @pytest.mark.asyncio
    @patch("services.balance_service.BalanceService.get_group_balances", new_callable=AsyncMock)
    @patch.object(GroupService, "get_member_role", new_callable=AsyncMock)
    async def test_remove_allowed_when_target_settled(self, mock_role, mock_balances):
        mock_role.return_value = GroupMemberRole.ADMIN
        mock_balances.return_value = _balances(MEMBER_ID, "0")
        target = _make_member_mock(GroupMemberRole.MEMBER, MEMBER_ID)
        db = _make_db(target)

        assert await GroupService.remove_member(db, GROUP_ID, MEMBER_ID, ADMIN_ID) is True
        db.delete.assert_awaited_once_with(target)


def _make_db_members(*members) -> AsyncMock:
    """Mock session whose execute().scalars().all() returns the given members."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(members)
    db.execute.return_value = result
    return db


class TestTransferOwnership:

    @pytest.mark.asyncio
    async def test_owner_transfers_to_member(self):
        owner = _make_member_mock(GroupMemberRole.OWNER, OWNER_ID)
        member = _make_member_mock(GroupMemberRole.MEMBER, MEMBER_ID)
        db = _make_db_members(owner, member)

        await GroupService.transfer_ownership(db, GROUP_ID, MEMBER_ID, OWNER_ID)

        assert member.role == GroupMemberRole.OWNER
        assert owner.role == GroupMemberRole.ADMIN
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_admin_cannot_transfer(self):
        admin = _make_member_mock(GroupMemberRole.ADMIN, ADMIN_ID)
        member = _make_member_mock(GroupMemberRole.MEMBER, MEMBER_ID)
        db = _make_db_members(admin, member)

        with pytest.raises(UnauthorizedActionException):
            await GroupService.transfer_ownership(db, GROUP_ID, MEMBER_ID, ADMIN_ID)
        assert member.role == GroupMemberRole.MEMBER
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_target_not_a_member(self):
        db = _make_db_members(_make_member_mock(GroupMemberRole.OWNER, OWNER_ID))

        with pytest.raises(GroupMemberNotFoundException):
            await GroupService.transfer_ownership(db, GROUP_ID, MEMBER_ID, OWNER_ID)
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_cannot_transfer_to_self(self):
        db = _make_db_members(_make_member_mock(GroupMemberRole.OWNER, OWNER_ID))

        with pytest.raises(UnauthorizedActionException):
            await GroupService.transfer_ownership(db, GROUP_ID, OWNER_ID, OWNER_ID)
