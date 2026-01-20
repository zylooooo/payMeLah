from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
from models import Expense, ExpenseParticipant, ExpenseSplitType, Group
from shared import (
    ExpenseNotFoundException,
    ExpenseValidationException,
    ExpenseNotEditableException,
    InvalidSplitException,
    GroupNotFoundException,
    GroupMemberNotFoundException,
    UnauthorizedActionException,
    UserNotFoundException
)
from .group_service import GroupService
from .user_service import UserService
from .split_calculator import SplitCalculator
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import timezone, datetime, date
import logging


logger = logging.getLogger(__name__)

class ExpenseService:
    """
    Service for expense management operations.
    Handles expense CRUD and participant management.
    """

    @staticmethod
    async def create_expense(db: AsyncSession, expense_data: Dict[str, Any]) -> dict:
        """
        Create a new expense in a group with participants.

        Args:
            db: AsyncSession - The database session.
            expense_data: Dict[str, Any] - Dictionary containing expense creation data.
        
        Returns:
            dict - Created expense data.
        """
        logger.info(f"Creating expense in group {expense_data['group_id']} by user {expense_data['created_by']}")

        try:
            # Verify that the group exists
            group = await GroupService.get_group_by_id(db, expense_data['group_id'])
            if not group:
                logger.warning(f"Group with ID {expense_data['group_id']} not found")
                raise GroupNotFoundException(f"Group with ID {expense_data['group_id']} not found")
            
            # Verify creator is a member
            if not await GroupService.is_member(db, expense_data['group_id'], expense_data['created_by']):
                logger.warning(f"Creator {expense_data['created_by']} is not a member of group {expense_data['group_id']}")
                raise UnauthorizedActionException("You must be a member of the group to create an expense")
            
            # Verify payer is a member of the group
            if not await GroupService.is_member(db, expense_data['group_id'], expense_data['payer_id']):
                logger.warning(f"Payer {expense_data['payer_id']} is not a member of group {expense_data['group_id']}")
                raise GroupMemberNotFoundException(f"Payer must be a member of the group.")
            
            # Verify all participants are members
            for participant_id in expense_data['participant_ids']:
                if not await GroupService.is_member(db, expense_data['group_id'], participant_id):
                    logger.warning(f"User {participant_id} is not a member of group {expense_data['group_id']}")
                    raise GroupMemberNotFoundException(
                        f"User {participant_id} is not a member of group {expense_data['group_id']}"
                    )
            
            # Calculate splits
            shares = ExpenseService._calculate_shares(
                amount=expense_data['amount'],
                split_type=expense_data['split_type'],
                participant_ids=expense_data['participant_ids'],
                split_data=expense_data.get('split_data', None)
            )

            # Create expense
            new_expense = Expense(
                group_id=expense_data['group_id'],
                description=expense_data['description'],
                amount=expense_data['amount'],
                currency=expense_data['currency'],
                payer_id=expense_data['payer_id'],
                expense_date=expense_data['expense_date'],
                category=expense_data['category'] if expense_data['category'] else None,
                split_type=expense_data['split_type'],
                created_by=expense_data['created_by'],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                is_settled=False
            )
            db.add(new_expense)
            await db.flush() # Get expense ID

            # Create participant records
            split_percentages = None
            if expense_data['split_type'] == ExpenseSplitType.PERCENTAGE and expense_data.get('split_data'):
                split_percentages = expense_data['split_data']['percentages']

            for i, participant_id in enumerate(expense_data['participant_ids']):
                participant = ExpenseParticipant(
                    expense_id=new_expense.id,
                    user_id=participant_id,
                    share_amount=shares[i],
                    split_percentage=split_percentages[i] if split_percentages else None,
                    is_settled=(participant_id == expense_data['payer_id']), # Payer's share is auto-settled
                    settled_at=datetime.now(timezone.utc) if (participant_id == expense_data['payer_id']) else None
                )
                db.add(participant)
            
            # Check if all participants are settled (e.g., single participant who is also the payer)
            # If so, mark the expense itself as settled
            all_participants_settled = all(
                participant_id == expense_data['payer_id']
                for participant_id in expense_data['participant_ids']
            )
            if all_participants_settled:
                new_expense.is_settled = True
            
            await db.commit()
            await db.refresh(new_expense)

            logger.info(f"Expense {new_expense.id} created successfully in group {expense_data['group_id']}")
            return new_expense.to_dict()
        except Exception as e:
            logger.error(f"Unexpected error while creating expense: {e}", exc_info=True)
            await db.rollback()
            raise e
        
    # Helper function to calculate splits using SplitCalculator
    @staticmethod
    def _calculate_shares(
        amount: Decimal,
        split_type: ExpenseSplitType,
        participant_ids: List[int],
        split_data: Optional[Dict] = None
    ) -> List[Decimal]:
        """
        Calculate share amounts based on split type.

        Args:
            amount: Decimal - The total amount of the expense.
            split_type: ExpenseSplitType - The type of split to calculate for.
            participant_ids: List[int] - The IDs of the participants involved in the expense.
            split_data: Optional[Dict] - Additional split data for exact, percentage or custom splits.
        
        Returns:
            List[Decimal] - List of share amounts for each participant, share the same index as the particpant IDs
        """
        count = len(participant_ids)

        if split_type == ExpenseSplitType.EQUAL:
            return SplitCalculator.calculate_equal_split(amount, count)
        elif split_type == ExpenseSplitType.EXACT:
            if not split_data or 'amounts' not in split_data:
                logger.warning(f"Exact split validation failed: split_data missing or missing 'amounts' key")
                raise ExpenseValidationException("Exact amounts are required for exact split type")
            if len(split_data['amounts']) != count:
                logger.warning(
                    f"Exact split validation failed: number of amounts ({len(split_data['amounts'])}) "
                    f"does not match number of participants ({count})"
                )
                raise ExpenseValidationException(
                    f"Number of exact amounts ({len(split_data['amounts'])}) "
                    f"must match number of participants ({count})"
                )
            return SplitCalculator.calculate_exact_split(amount, split_data['amounts'])
        elif split_type == ExpenseSplitType.PERCENTAGE:
            if not split_data or 'percentages' not in split_data:
                logger.warning(f"Percentage split validation failed: split_data missing or missing 'percentages' key")
                raise ExpenseValidationException("Split percentages are required for percentage split type.")
            if len(split_data['percentages']) != count:
                logger.warning(
                    f"Percentage split validation failed: number of percentages ({len(split_data['percentages'])}) "
                    f"does not match number of participants ({count})"
                )
                raise ExpenseValidationException(
                    f"Number of percentages ({len(split_data['percentages'])}) "
                    f"must match number of participants ({count})"
                )
            return SplitCalculator.calculate_percentage_split(amount, split_data['percentages'])
        elif split_type == ExpenseSplitType.CUSTOM:
            if not split_data or 'shares' not in split_data:
                logger.warning(f"Custom split validation failed: split_data missing or missing 'shares' key")
                raise ExpenseValidationException("Share ratios are required for custom split type.")
            if len(split_data['shares']) != count:
                logger.warning(
                    f"Custom split validation failed: number of share ratios ({len(split_data['shares'])}) "
                    f"does not match number of participants ({count})"
                )
                raise ExpenseValidationException(
                    f"Number of share ratios ({len(split_data['shares'])}) "
                    f"must match number of participants ({count})"
                )
            return SplitCalculator.calculate_custom_split(amount, split_data['shares'])
        else:
            logger.error(f"Invalid split type provided: {split_type}")
            raise InvalidSplitException(f"Invalid split type {split_type} provided.")
    
    @staticmethod
    async def get_expense_by_id(db: AsyncSession, expense_id: int) -> Optional[dict]:
        """
        Function to get an expense by it's ID.

        Args:
            db: AsyncSession - The database session.
            expense_id: int - The ID of the expense to get.
        
        Returns:
            Optional[dict] - The expense data if found, None otherwise.
        """
        logger.info(f"Getting expense by ID: {expense_id}")
        result = await db.execute(
            select(Expense).where(Expense.id == expense_id)
        )
        expense = result.scalar_one_or_none()

        if not expense:
            logger.warning(f"Expense with ID {expense_id} not found")
            raise ExpenseNotFoundException(f"Expense with ID {expense_id} not found")
        
        logger.info(f"Expense with ID {expense_id} found successfully")
        return expense.to_dict()
    
    @staticmethod
    async def get_expenses_by_group_id(
        db: AsyncSession,
        group_id: int,
        requesting_user_id: int,
        limit: int = 10,
        offset: int = 0
    ) -> List[dict]:
        """
        Get expenses by group ID with pagination.

        Args:
            db: AsyncSession - The database session.
            group_id: int - The ID of the group to get expenses for.
            requesting_user_id: int - The ID of the user requesting the expenses. For authorization purposes (User must be a member of the group)
            limit: int - The maximum number of expenses to return (default = 10)
            offset: int - The number of expenses to skip (default = 0)
        
        Returns:
            List[dict] - A list of expense dictionaries in descending order of expense date.
        
        Raises:
            GroupNotFoundException - If the group does not exist.
            UnautorizedActionException - If the user does not belong to the group.
        """
        logger.info(f"Getting expenses for group {group_id}")

        # Verify if the group exists, method will raise exception if group not found
        group = await GroupService.get_group_by_id(db, group_id)
        if not group:
            raise GroupNotFoundException(f"Group with ID {group_id} not found")
        
        if not await GroupService.is_member(db, group_id, requesting_user_id):
            raise UnauthorizedActionException(f"User {requesting_user_id} is requesting expenses for group {group_id} that they are not a member of.")
        
        # Get expenses with pagination
        result = await db.execute(
            select(Expense)
            .where(Expense.group_id == group_id)
            .order_by(Expense.expense_date.desc(), Expense.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        expenses = result.scalars().all()

        logger.info(f"Successfully found {len(expenses)} expenses for group {group_id}")
        return [expense.to_dict() for expense in expenses]
    
    @staticmethod
    async def get_expense_count_by_group_id(
        db: AsyncSession,
        group_id: int,
        requesting_user_id: int
    ) -> int:
        """
        Get the total count of expenses in a group.
        Used for server-side pagination.

        Args:
            db: AsyncSession - The database session.
            group_id: int - The ID of the group to count expenses for.
            requesting_user_id: int - The ID of the user requesting. For authorization purposes.
        
        Returns:
            int - Total count of expenses in the group.
        
        Raises:
            GroupNotFoundException - If the group does not exist.
            UnauthorizedActionException - If the user does not belong to the group.
        """
        logger.info(f"Getting expense count for group {group_id}")

        # Verify if the group exists
        group = await GroupService.get_group_by_id(db, group_id)
        if not group:
            raise GroupNotFoundException(f"Group with ID {group_id} not found")
        
        if not await GroupService.is_member(db, group_id, requesting_user_id):
            raise UnauthorizedActionException(
                f"User {requesting_user_id} is not a member of group {group_id}."
            )
        
        # Get count
        result = await db.execute(
            select(func.count(Expense.id))
            .where(Expense.group_id == group_id)
        )
        count = result.scalar()

        logger.info(f"Found {count} expenses for group {group_id}")
        return count or 0
    
    @staticmethod
    async def get_expenses_by_user_id(
        db: AsyncSession,
        user_id: int,
        group_id: Optional[int] = None,
        limit: int = 10,
        offset: int = 0
    ) -> List[dict]:
        """
        Get expenses of a user regardless if the user is a payer or participant.
        Supports pagination as well as optional filtering by group ID.

        Args:
            db: AsyncSession - The database session.
            user_id: int - The ID of the user to get expenses for.
            group_id: Optional[int] - The ID of the group to filter expenses by. If not provided, all expenses will be returned.
            limit: int - The maximum number of expenses to return (default = 10)
            offset: int - The number of expenses to skip (default = 0)
        
        Returns:
            List[dict] - A list of expense dictionaries in descending order of expense date.
        """
        logger.info(f"Getting expenses for user {user_id}")

        # Verify if the user exists
        user = await UserService.get_user_by_id(db, user_id)
        if not user:
            raise UserNotFoundException(f"User with ID {user_id} not found, unable to get expenses for this user.")
        
        # Build the base query
        query = (
            select(Expense)
            .distinct()
            .outerjoin(ExpenseParticipant, Expense.id == ExpenseParticipant.expense_id)
            .where(
                or_(
                    Expense.payer_id == user_id,
                    ExpenseParticipant.user_id == user_id
                )
            )
        )

        # Only add group filter if group ID is provided and group exists
        if group_id is not None and await GroupService.get_group_by_id(db, group_id):
            # Verify that the member is a member of the group
            if not await GroupService.is_member(db, group_id, user_id):
                logger.warning(f"User {user_id} is not a member of group {group_id}, they are unable to get expenses for this group.")
                raise UnauthorizedActionException(f"User {user_id} is not a member of group {group_id}, they are unable to get expenses for this group.")
            query = query.where(Expense.group_id == group_id)
        
        query = query.order_by(Expense.expense_date.desc(), Expense.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await db.execute(query)
        expenses = result.scalars().all()

        logger.info(f"Successfully found {len(expenses)} expenses for user {user_id}")
        return [expense.to_dict() for expense in expenses]
    
    @staticmethod
    async def get_expense_participants(
        db: AsyncSession,
        expense_id: int,
        requesting_user_id: Optional[int] = None
    ) -> List[dict]:
        """
        Get all participants for an expense with their user details.

        Args:
            db: AsyncSession - The database session.
            expense_id: int - The expense ID.
            requesting_user_id: Optional[int] - If provided, check if the user can view the expense

        Returns:
            List[dict] - A list of participant dictionaries with user details.
        
        Raises:
            ExpenseNotFoundException - If the expense does not exist.
            UnauthorizedActionException - If the user is not a member of the group the expense belongs to.
        """
        logger.info(f"Getting participants for expense {expense_id}")

        # First get the expense to verify it exists and get the group ID
        result = await db.execute(
            select(Expense).where(Expense.id == expense_id)
        )
        expense = result.scalar_one_or_none()

        if not expense:
            logger.warning(f"Expense with ID {expense_id} not found, unable to view participants for this expense.")
            raise ExpenseNotFoundException(f"Expense with ID {expense_id} not found, unable to view participants for this expense.")
        
        # Optional authorization check if requesting user ID is provided
        if requesting_user_id is not None and not await GroupService.is_member(db, expense.group_id, requesting_user_id):
            logger.warning(f"User {requesting_user_id} is not a member of group {expense.group_id}, they are unable to view participants for this expense.")
            raise UnauthorizedActionException(f"User {requesting_user_id} is not a member of group {expense.group_id}, they are unable to view participants for this expense.")

        # Get participants with user details
        result = await db.execute(
            select(ExpenseParticipant)
            .where(ExpenseParticipant.expense_id == expense_id)
            .order_by(ExpenseParticipant.user_id)
        )
        participants = result.scalars().all()

        # Enrich with user details
        participants_with_details = []
        for participant in participants:
            participant_dict = participant.to_dict()
            user = await UserService.get_user_by_id(db, participant.user_id)
            if user:
                participant_dict['username'] = user.get('username')
                participant_dict['first_name'] = user.get('first_name')
                participant_dict['last_name'] = user.get('last_name')
                participants_with_details.append(participant_dict)
            else:
                logger.warning(f"User with ID {participant.user_id} not found, unable to include user details for this expense participant. Skipping this participant...")
                
        
        logger.info(f"Successfully found {len(participants_with_details)} participants for expense {expense_id}")
        return participants_with_details
    
    @staticmethod
    async def get_expense_with_participants(
        db: AsyncSession,
        expense_id: int,
        requesting_user_id: int
    ) -> dict:
        """
        Get expense details with all participants and user details.
        Orchestrator method that combines get_expense_by_id and get_expense_participants.

        Args:
            db: AsyncSession - The database session.
            expens_id: int - The expense ID.
            requesting_user_id: int - The user requesting the details, for authorization purposes
        
        Returns:
            dict - Expense dictionary data with 'participants' key containing participant list.
        
        Raises:
            ExpenseNotFoundException - If the expense doesn't exist.
            UnauthorizedActionException - If user is not a group member.
        """
        logger.info(f"Getting expense {expense_id} with participants details for user {requesting_user_id}")

        expense_dict = await ExpenseService.get_expense_by_id(db, expense_id)

        if not await GroupService.is_member(db, expense_dict['group_id'], requesting_user_id):
            raise UnauthorizedActionException(f"User {requesting_user_id} is not a member of group {expense_dict['group_id']}, they are unable to view this expense.")
        
        # Get participants 
        participants = await ExpenseService.get_expense_participants(db, expense_id)

        expense_dict['participants'] = participants
        return expense_dict
