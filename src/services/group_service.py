from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload
from models import Group, GroupMember, GroupMemberRole, User
from shared import (
    UserNotFoundException,
    GroupNotFoundException,
    GroupMemberAlreadyExistsException,
    GroupMemberNotFoundException,
    UnauthorizedGroupJoinException,
    UnauthorizedActionException
)
from .user_service import UserService
from typing import Optional, Any, List, Dict
from datetime import timezone, datetime
import logging


logger = logging.getLogger(__name__)


class GroupService:
    """
    Service for group management operations.
    Provide CRUD functionality for users to manage their groups.
    """

    @staticmethod
    async def create_group(
        db: AsyncSession,
        name: str,
        description: Optional[str],
        default_currency: str,
        telegram_chat_id: int,
        created_by: int,
        simplify_debts: bool = True
    ) -> dict:
        """
        Create a new group and add the creator as the owner of the group. By default, they are the first member of the group.

        Args:
            db: AsyncSession - The database session.
            name: str - the group name chosen by the user.
            description: Optional[str] - the group description chosen by the user.
            default_currency: str - the default currency that the group's expenses will be shown in.
            telegram_chat_id: int - the Telegram chat ID of the group chat where this expense group is created.
            created_by: int - the Telegram user ID of the user who is creating the group.
        
        Returns:
            dict - A dictionary containing the created group data.
        """
        logger.info(f"Creating group '{name}' by user with ID: {created_by}")

        user = await UserService.get_user_by_id(db, created_by)
        if not user:
            raise UserNotFoundException(
                f"User with ID {created_by} not found."
            )

        new_group = Group(
            name=name,
            description=description,
            default_currency=default_currency,
            simplify_debts=simplify_debts,
            telegram_chat_id=telegram_chat_id,
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(new_group)
        await db.flush()

        owner_member = GroupMember(
            group_id=new_group.id,
            user_id=created_by,
            role=GroupMemberRole.OWNER,
            joined_at=datetime.now(timezone.utc)
        )
        db.add(owner_member)
        await db.commit()
        await db.refresh(new_group)
        logger.info(f"Group '{name}' created successfully")
        return new_group.to_dict()
        
    @staticmethod
    async def join_group(
        db: AsyncSession,
        group_id: int,
        user_data: dict,
        telegram_group_member_ids: List[int]
    ) -> bool:
        """
        User joins a group by group ID.
        Checks if the user is already a member of the group and if the user belongs to the Telegram group chat.

        Args:
            db: AsyncSession - The database session.
            group_id: int - The ID of the group the user is trying to join.
            user_data: dict - The user data of the user who is trying to join the group.
            telegram_group_member_ids: List[int] - The list of Telegram user IDs of all members in the Telegram group chat.
        
        Returns:
            bool - True if the user successfully joined the group, False otherwise.
        """
        user_id = user_data.get('id')
        logger.info(f"User {user_id} trying to join group {group_id}")

        group = await GroupService.get_group_by_id(db, group_id)
        if not group:
            raise GroupNotFoundException(f"Group {group_id} not found.")

        if await GroupService.is_member(db, group_id, user_id):
            raise GroupMemberAlreadyExistsException(
                f"User {user_id} is already a member of group {group_id}."
            )

        if user_id not in telegram_group_member_ids:
            raise UnauthorizedGroupJoinException(
                f"User {user_id} is not a member of the Telegram group chat where this group is created."
            )

        user = await UserService.get_user_by_id(db, user_id)
        if not user:
            user = await UserService.create_user(
                db,
                user_id=user_id,
                username=user_data.get('username'),
                first_name=user_data.get('first_name'),
                last_name=user_data.get('last_name')
            )

        new_member = GroupMember(
            group_id=group_id,
            user_id=user_id,
            role=GroupMemberRole.MEMBER,
            joined_at=datetime.now(timezone.utc)
        )
        db.add(new_member)
        await db.commit()
        await db.refresh(new_member)
        logger.info(f"User {user_id} joined group {group_id} successfully")
        return True

    @staticmethod
    async def is_member(db: AsyncSession, group_id: int, user_id: int)-> bool:
        """Check if a user with user ID is a member of group with group ID."""
        result = await db.execute(
            select(GroupMember).where(
                and_(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def get_group_by_id(db: AsyncSession, group_id: int) -> Optional[dict]:
        """
        Get a group by it's ID.

        Args:
            db: AsyncSession - The database session.
            group_id: int - The ID of the group to get.
        
        Returns:
            dict - The group data if found, None otherwise.
        """
        logger.info(f"Getting group by ID: {group_id}")
        result = await db.execute(
            select(Group).where(Group.id == group_id)
        )
        group = result.scalar_one_or_none()

        if not group:
            logger.warning(f"Group with ID {group_id} not found")
            return None
        
        logger.info(f"Group with ID {group_id} found successfully")
        return group.to_dict()

    @staticmethod
    async def get_all_groups_by_user_id(
        db: AsyncSession,
        user_id: int,
        include_archived: bool = False
    ) -> List[dict]:
        """
        Get all groups that a user is a member of.

        Args:
            db: AsyncSession - The database session.
            user_id: int - The Telegram user ID of the user to get the groups for.
            include_archived: If True, include archived groups in the result.

        Returns:
            List[dict] - A list of group data that the user is a member of.
        """
        logger.info(f"Getting all groups that user with ID {user_id} is a member of.")
        query = (
            select(Group)
            .join(GroupMember)
            .where(GroupMember.user_id == user_id)
        )
        if not include_archived:
            query = query.where(Group.is_archived == False)
        query = query.order_by(Group.created_at.desc())

        result = await db.execute(query)
        groups = result.scalars().all()

        group_list = [group.to_dict() for group in groups]

        logger.info(f"Found {len(group_list)} groups that user with ID {user_id} is a member of.")
        return group_list
    
    @staticmethod
    async def get_group_members(db: AsyncSession, group_id: int) -> List[dict]:
        """
        Get all members of a group.
        
        Args:
            db: AsyncSession - The database session.
            group_id: int - The ID of the group.
        
        Returns:
            List[dict] - A list of member dictionaries.
        """
        logger.info(f"Getting members for group ID: {group_id}")
        result = await db.execute(
            select(GroupMember)
            .where(GroupMember.group_id == group_id)
            .order_by(GroupMember.joined_at)
        )
        members = result.scalars().all()
        
        members_list = [member.to_dict() for member in members]
        logger.info(f"Found {len(members_list)} members for group ID: {group_id}")
        return members_list

    @staticmethod
    async def get_member_role(db: AsyncSession, group_id: int, user_id: int) -> Optional[GroupMemberRole]:
        """
        Get the role of a user in a group.
        
        Args:
            db: AsyncSession - The database session.
            group_id: int - The ID of the group.
            user_id: int - The ID of the user.
        
        Returns:
            GroupMemberRole | None - The user's role in the group, or None if not a member.
        """
        result = await db.execute(
            select(GroupMember).where(
                and_(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
            )
        )
        member = result.scalar_one_or_none()
        
        if not member:
            return None
        
        return member.role

    @staticmethod
    async def get_group_members_with_details(db: AsyncSession, group_id: int) -> List[dict]:
        """
        Get all members of a group with their user details in a single JOIN query.

        Args:
            db: AsyncSession - The database session.
            group_id: int - The ID of the group.

        Returns:
            List[dict] - A list of member dictionaries with user details.
        """
        logger.info(f"Getting members with details for group ID: {group_id}")

        result = await db.execute(
            select(GroupMember, User)
            .join(User, GroupMember.user_id == User.id)
            .where(GroupMember.group_id == group_id)
            .order_by(GroupMember.joined_at)
        )
        members_with_details = []
        for member, user in result.all():
            member_dict = member.to_dict()
            member_dict['username'] = user.username
            member_dict['first_name'] = user.first_name
            member_dict['last_name'] = user.last_name
            members_with_details.append(member_dict)

        logger.info(f"Found {len(members_with_details)} members with details for group ID: {group_id}")
        return members_with_details

    @staticmethod
    async def delete_group(db: AsyncSession, group_id: int, requesting_user_id: int) -> bool:
        """
        Delete a group. Only the owner can delete a group.
        
        Args:
            db: AsyncSession - The database session.
            group_id: int - The ID of the group to delete.
            requesting_user_id: int - The user requesting the deletion.
        
        Returns:
            bool - True if deletion was successful.
        
        Raises:
            GroupNotFoundException - If the group doesn't exist.
            UnauthorizedActionException - If the user is not the owner.
        """
        logger.info(f"User {requesting_user_id} attempting to delete group {group_id}")

        result = await db.execute(select(Group).where(Group.id == group_id))
        group = result.scalar_one_or_none()
        if not group:
            raise GroupNotFoundException(f"Group with ID {group_id} not found.")

        role = await GroupService.get_member_role(db, group_id, requesting_user_id)
        if role != GroupMemberRole.OWNER:
            raise UnauthorizedActionException("Only the group owner can delete the group.")

        await db.delete(group)
        await db.commit()
        logger.info(f"Group {group_id} deleted successfully by user {requesting_user_id}")
        return True

    @staticmethod
    async def leave_group(db: AsyncSession, group_id: int, user_id: int) -> bool:
        """
        User leaves a group. Owners cannot leave their own group.
        
        Args:
            db: AsyncSession - The database session.
            group_id: int - The ID of the group to leave.
            user_id: int - The user leaving the group.
        
        Returns:
            bool - True if successful.
        
        Raises:
            GroupMemberNotFoundException - If the user is not a member.
            UnauthorizedActionException - If the owner tries to leave.
        """
        logger.info(f"User {user_id} attempting to leave group {group_id}")

        result = await db.execute(
            select(GroupMember).where(
                and_(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            raise GroupMemberNotFoundException(f"User {user_id} is not a member of group {group_id}.")

        if member.role == GroupMemberRole.OWNER:
            raise UnauthorizedActionException(
                "Group owners cannot leave. Transfer ownership or delete the group instead."
            )

        await db.delete(member)
        await db.commit()
        logger.info(f"User {user_id} left group {group_id} successfully")
        return True

    @staticmethod
    async def remove_member(
        db: AsyncSession,
        group_id: int,
        user_id_to_remove: int,
        requesting_user_id: int
    ) -> bool:
        """
        Remove a member from a group. Only owners and admins can remove members.
        Owners cannot be removed. Admins can only be removed by owners.
        
        Args:
            db: AsyncSession - The database session.
            group_id: int - The ID of the group.
            user_id_to_remove: int - The user ID to remove.
            requesting_user_id: int - The user requesting the removal.
        
        Returns:
            bool - True if successful.
        
        Raises:
            GroupMemberNotFoundException - If either user is not a member.
            UnauthorizedActionException - If the action is not authorized.
        """
        logger.info(f"User {requesting_user_id} attempting to remove user {user_id_to_remove} from group {group_id}")

        requester_role = await GroupService.get_member_role(db, group_id, requesting_user_id)
        if not requester_role:
            raise GroupMemberNotFoundException(f"User {requesting_user_id} is not a member of group {group_id}.")

        if requester_role not in [GroupMemberRole.OWNER, GroupMemberRole.ADMIN]:
            raise UnauthorizedActionException("Only owners and admins can remove members.")

        result = await db.execute(
            select(GroupMember).where(
                and_(GroupMember.group_id == group_id, GroupMember.user_id == user_id_to_remove)
            )
        )
        target_member = result.scalar_one_or_none()
        if not target_member:
            raise GroupMemberNotFoundException(f"User {user_id_to_remove} is not a member of group {group_id}.")

        if target_member.role == GroupMemberRole.OWNER:
            raise UnauthorizedActionException("Cannot remove the group owner.")

        if target_member.role == GroupMemberRole.ADMIN and requester_role != GroupMemberRole.OWNER:
            raise UnauthorizedActionException("Only the owner can remove admins.")

        if user_id_to_remove == requesting_user_id:
            raise UnauthorizedActionException("You cannot remove yourself. Use the leave group option instead.")

        await db.delete(target_member)
        await db.commit()
        logger.info(f"User {user_id_to_remove} removed from group {group_id} by user {requesting_user_id}")
        return True
    
    @staticmethod
    async def update_member_role(
        db: AsyncSession,
        group_id: int,
        target_user_id: int,
        new_role: GroupMemberRole,
        requesting_user_id: int
    ) -> dict:
        """
        Promote or demote a group member's role. Only the owner can do this.
        Rules:
          - Only owners can change roles.
          - Cannot change the owner's own role.
          - Cannot promote/demote to owner (ownership transfer not supported).
          - Valid transitions: member ↔ admin.

        Args:
            db: Database session.
            group_id: The group ID.
            target_user_id: The member whose role is being changed.
            new_role: The new role (MEMBER or ADMIN only).
            requesting_user_id: Must be the group owner.

        Returns:
            Updated GroupMember dict.

        Raises:
            UnauthorizedActionException, GroupMemberNotFoundException.
        """
        logger.info(
            f"User {requesting_user_id} updating role of user {target_user_id} "
            f"to {new_role} in group {group_id}"
        )

        requester_role = await GroupService.get_member_role(db, group_id, requesting_user_id)
        if requester_role != GroupMemberRole.OWNER:
            raise UnauthorizedActionException("Only the group owner can change member roles.")

        if target_user_id == requesting_user_id:
            raise UnauthorizedActionException("You cannot change your own role.")

        if new_role == GroupMemberRole.OWNER:
            raise UnauthorizedActionException("Ownership transfer is not supported.")

        result = await db.execute(
            select(GroupMember).where(
                and_(GroupMember.group_id == group_id, GroupMember.user_id == target_user_id)
            )
        )
        target_member = result.scalar_one_or_none()
        if not target_member:
            raise GroupMemberNotFoundException(
                f"User {target_user_id} is not a member of group {group_id}."
            )

        if target_member.role == GroupMemberRole.OWNER:
            raise UnauthorizedActionException("Cannot change the owner's role.")

        target_member.role = new_role
        await db.commit()
        await db.refresh(target_member)
        logger.info(f"Role updated for user {target_user_id} in group {group_id}")
        return target_member.to_dict()

    @staticmethod
    async def _set_archive_state(
        db: AsyncSession,
        group_id: int,
        requesting_user_id: int,
        is_archived: bool
    ) -> dict:
        """Set is_archived on a group. Only the owner may do this."""
        verb = "archive" if is_archived else "unarchive"
        logger.info(f"User {requesting_user_id} attempting to {verb} group {group_id}")

        role = await GroupService.get_member_role(db, group_id, requesting_user_id)
        if role != GroupMemberRole.OWNER:
            raise UnauthorizedActionException(f"Only the group owner can {verb} the group.")

        result = await db.execute(select(Group).where(Group.id == group_id))
        group = result.scalar_one_or_none()
        if not group:
            raise GroupNotFoundException(f"Group {group_id} not found.")

        group.is_archived = is_archived
        group.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(group)
        logger.info(f"Group {group_id} {verb}d by user {requesting_user_id}")
        return group.to_dict()

    @staticmethod
    async def archive_group(db: AsyncSession, group_id: int, requesting_user_id: int) -> dict:
        """Archive a group. Only the owner can archive."""
        return await GroupService._set_archive_state(db, group_id, requesting_user_id, is_archived=True)

    @staticmethod
    async def unarchive_group(db: AsyncSession, group_id: int, requesting_user_id: int) -> dict:
        """Restore an archived group. Only the owner can unarchive."""
        return await GroupService._set_archive_state(db, group_id, requesting_user_id, is_archived=False)

    @staticmethod
    async def get_group_by_chat_id(db: AsyncSession, chat_id: int) -> List[dict]:
        """
        Get a group by Telegram chat ID.

        Args:
            db - AsyncSession - The database session.
            chat_id: int - The Telegram chat ID of the group.
        
        Returns:
            List[dict] - A list of group data that is associated with the Telegram chat ID, empty if nothing is found.
        """
        logger.info(f"Getting group from Telegram chat ID: {chat_id}")
        result = await db.execute(
            select(Group)
            .where(Group.telegram_chat_id == chat_id)
            .order_by(Group.created_at.desc())
        )
        groups = result.scalars().all()

        groups_list = [group.to_dict() for group in groups]
        logger.info(f"Found {len(groups_list)} groups from Telegram chat ID: {chat_id}")
        return groups_list

    @staticmethod
    async def update_simplify_setting(
        db: AsyncSession,
        group_id: int,
        simplify_debts: bool,
        requesting_user_id: int
    ) -> dict:
        """
        Update a group's default debt simplification setting.
        Only admins and owners may change this setting.

        Args:
            db: Database session.
            group_id: The group ID.
            simplify_debts: New value for the simplify_debts flag.
            requesting_user_id: Must be an admin or owner of the group.

        Returns:
            Updated group dict.

        Raises:
            GroupNotFoundException, UnauthorizedActionException.
        """
        logger.info(f"Updating simplify_debts={simplify_debts} for group {group_id} by user {requesting_user_id}")

        member_role = await GroupService.get_member_role(db, group_id, requesting_user_id)
        if member_role not in [GroupMemberRole.ADMIN, GroupMemberRole.OWNER]:
            raise UnauthorizedActionException("Only admins and owners can change group settings.")

        result = await db.execute(select(Group).where(Group.id == group_id))
        group = result.scalar_one_or_none()
        if not group:
            raise GroupNotFoundException(f"Group {group_id} not found")

        group.simplify_debts = simplify_debts
        group.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(group)
        logger.info(f"Updated simplify_debts for group {group_id}")
        return group.to_dict()
