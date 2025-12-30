from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import User
from typing import Optional, Any
from datetime import timezone, datetime
from shared import UserAlreadyExistsException, UserNotFoundException
import logging


logger = logging.getLogger(__name__)


class UserService:
    """Service for user management operations."""

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[dict]:
        """
        Get a user by their Telegram user ID.

        Args:
            db: AsyncSession - The database session.
            user_id: int - The Telegram user ID.
        
        Returns:
            dict - The user data if found, None otherwise
        """
        logger.info(f"Getting user by ID: {user_id}")
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            logger.warning(f"User with ID {user_id} not found")
            return None
        logger.info(f"User with ID {user_id} found successfully")
        return user.to_dict()
    
    @staticmethod
    async def create_user(
        db: AsyncSession,
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str]
    ) -> dict:
        """
        Create a new user.
        New users cannot have an existing user ID.
        Remaining fields are passed from Telegram user object.
        Users are created with the default currency of SGD and it can be updated along with their other details.

        Args:
            db: AsyncSession - The database session.
            user_id: int - The Telegram user ID.
            username: Optional[str] - The Telegram username.
            first_name: Optional[str] - The Telegram user's first name.
            last_name: Optional[str] - The Telegram user's last name.
        
        Returns:
            dict - The created user data.
        """
        logger.info(f"Creating user with ID: {user_id}")
        try:
            # Check if the user already exists
            existing_user = await UserService.get_user_by_id(db, user_id)
            if existing_user:
                logger.warning(f"User with ID {user_id} already exists, skipping creation")
                raise UserAlreadyExistsException(f"User with ID {user_id} already exists")
            
            # Create the new user
            new_user = User(
                id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                preferred_currency='SGD',
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )

            db.add(new_user)
            await db.commit()
            await db.refresh(new_user)
            logger.info(f"User with ID {user_id} created successfully")
            return new_user.to_dict()
        except Exception as e:
            logger.error(f"An unexpected error occurred while creating user with ID: {user_id}: {e}", exc_info=True)
            raise e

    @staticmethod
    async def update_user(
        db: AsyncSession,
        user_id: int,
        update_data: dict[str, Any]
    ) -> dict:
        """
        Update a user's details. Namely updating their first name, last name and preferred currency.

        Args:
            db: AsyncSession - The database session.
            user_id: int - The Telegram user ID.
            update_data: dict[str, Any] - The data to update the user with.
        
        Returns:
            dict - The updated user data.
        """
        logger.info(f"Updating user with ID: {user_id}")
        # Check if the user exists
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            logger.warning(f"User with ID {user_id} not found, skipping update")
            raise UserNotFoundException(f"User with ID {user_id} not found")
        
        # Only update the fields that are provided in the update_data
        for key, value in update_data.items():
            if hasattr(user, key) and value is not None:
                setattr(user, key, value)
        
        user.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(user)
        logger.info(f"User with ID {user_id} updated successfully")
        return user.to_dict()