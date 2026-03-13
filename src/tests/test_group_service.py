"""
Unit tests for GroupService.update_member_role.
Tests all authorization rules and valid role transitions without a real database.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from models import GroupMemberRole
from services.group_service import GroupService
from shared import UnauthorizedActionException, GroupMemberNotFoundException


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
