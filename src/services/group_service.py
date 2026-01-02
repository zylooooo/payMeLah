from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload
from models import Group, GroupMember, User, GroupMemberRole
from shared import (
    UserNotFoundException,
    GroupNotFoundException,
    GroupMemberAlreadyExistsException,
    UnauthorizedGroupJoinException
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
        created_by: int
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
        try:
            # Check if the user exists
            user = await UserService.get_user_by_id(db, created_by)
            if not user:
                logger.warning(f"User with ID {created_by} is not a valid user, skipping group creation")
                raise UserNotFoundException(
                    f"User with ID {created_by} not found. User tried to create a group with invalid user account."
                )
            
            # Create the new group
            new_group = Group(
                name=name,
                description=description,
                default_currency=default_currency,
                telegram_chat_id=telegram_chat_id,
                created_by=created_by,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            db.add(new_group)
            await db.flush() # Flush to get the new group ID

            # Add creator as owner
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
        except Exception as e:
            logger.error(f"An unexpected error occurred while creating group '{name}': {e}", exc_info=True)
            await db.rollback()
            raise e
        
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
        logger.info(f"User with ID {user_id} is trying to join group with ID: {group_id}")

        # Check if the group exists in the database
        try:
            group = await GroupService.get_group_by_id(db, group_id)
            if not group:
                raise GroupNotFoundException(f"Group with ID {group_id} not found. User tried to join a non-existent group.")
            
            # Check if the user is already a member of the group
            if await GroupService.is_member(db, group_id, user_id):
                logger.info(f"User with ID: {user_id} is already a member of group {group_id}")
                raise GroupMemberAlreadyExistsException(
                    f"User {user_id} is already a member of group {group_id}."
                )
            
            # Validate user is in the Telegram group
            if user_id not in telegram_group_member_ids:
                logger.warning(f"User with ID: {user_id} is trying to join a group that he is not a member of")
                raise UnauthorizedGroupJoinException(
                    f"User: {user_id} is not a member of the Telegram group chat where this group is created."
                )
            
            # Create user account if it doesn't exist
            user = await UserService.get_user_by_id(db, user_id)
            if not user:
                user = await UserService.create_user(
                    db,
                    user_id=user_id,
                    username=user_data.get('username'),
                    first_name=user_data.get('first_name'),
                    last_name=user_data.get('last_name')
                )
            
            # Add user as member to the group
            new_member = GroupMember(
                group_id=group_id,
                user_id=user_id,
                role=GroupMemberRole.MEMBER,
                joined_at=datetime.now(timezone.utc)
            )
            db.add(new_member)
            await db.commit()
            await db.refresh(new_member)

            logger.info(f"User with ID: {user_id} joined group with ID: {group_id} successfully")
            return True
        except Exception as e:
            logger.error(f"An unexpected error occurred while joining user {user_id} to group {group_id}: {e}", exc_info=True)
            await db.rollback()
            raise e

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
            