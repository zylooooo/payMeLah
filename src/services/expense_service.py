import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Expense, ExpenseParticipant, ExpenseSplitType, Payment
from shared import (
    ExpenseNotEditableException,
    ExpenseNotFoundException,
    ExpenseValidationException,
    GroupMemberNotFoundException,
    GroupNotFoundException,
    InvalidSplitException,
    UnauthorizedActionException,
    UserNotFoundException,
)

from .group_service import GroupService
from .split_calculator import SplitCalculator
from .user_service import UserService

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

        group = await GroupService.get_group_by_id(db, expense_data['group_id'])
        if not group:
            logger.warning(f"Group with ID {expense_data['group_id']} not found")
            raise GroupNotFoundException(f"Group with ID {expense_data['group_id']} not found")

        if not await GroupService.is_member(db, expense_data['group_id'], expense_data['created_by']):
            logger.warning(f"Creator {expense_data['created_by']} is not a member of group {expense_data['group_id']}")
            raise UnauthorizedActionException("You must be a member of the group to create an expense")

        if not await GroupService.is_member(db, expense_data['group_id'], expense_data['payer_id']):
            logger.warning(f"Payer {expense_data['payer_id']} is not a member of group {expense_data['group_id']}")
            raise GroupMemberNotFoundException("Payer must be a member of the group.")

        for participant_id in expense_data['participant_ids']:
            if not await GroupService.is_member(db, expense_data['group_id'], participant_id):
                logger.warning(f"User {participant_id} is not a member of group {expense_data['group_id']}")
                raise GroupMemberNotFoundException(
                    f"User {participant_id} is not a member of group {expense_data['group_id']}"
                )

        shares = ExpenseService._calculate_shares(
            amount=expense_data['amount'],
            split_type=expense_data['split_type'],
            participant_ids=expense_data['participant_ids'],
            split_data=expense_data.get('split_data', None)
        )

        new_expense = Expense(
            group_id=expense_data['group_id'],
            description=expense_data['description'],
            amount=expense_data['amount'],
            currency=expense_data['currency'],
            payer_id=expense_data['payer_id'],
            expense_date=expense_data['expense_date'],
            category=expense_data['category'],
            split_type=expense_data['split_type'],
            created_by=expense_data['created_by'],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            is_settled=False
        )
        db.add(new_expense)
        await db.flush()

        split_percentages = None
        if expense_data['split_type'] == ExpenseSplitType.PERCENTAGE and expense_data.get('split_data'):
            split_percentages = expense_data['split_data']['percentages']

        for i, participant_id in enumerate(expense_data['participant_ids']):
            participant = ExpenseParticipant(
                expense_id=new_expense.id,
                user_id=participant_id,
                share_amount=shares[i],
                split_percentage=split_percentages[i] if split_percentages else None,
                is_settled=(participant_id == expense_data['payer_id']),
                settled_at=datetime.now(timezone.utc) if (participant_id == expense_data['payer_id']) else None
            )
            db.add(participant)

        # Settle immediately when the only participant is also the payer
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
                logger.warning("Exact split validation failed: split_data missing or missing 'amounts' key")
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
                logger.warning("Percentage split validation failed: split_data missing or missing 'percentages' key")
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
                logger.warning("Custom split validation failed: split_data missing or missing 'shares' key")
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
        offset: int = 0,
        category: Optional[str] = None
    ) -> List[dict]:
        """
        Get expenses by group ID with pagination.

        Args:
            db: AsyncSession - The database session.
            group_id: int - The ID of the group to get expenses for.
            requesting_user_id: int - The ID of the user requesting the expenses. For authorization purposes (User must be a member of the group)
            limit: int - The maximum number of expenses to return (default = 10)
            offset: int - The number of expenses to skip (default = 0)
            category: Optional[str] - The category to filter expenses by (default = None)

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
        query = (
            select(Expense)
            .where(Expense.group_id == group_id)
        )
        if category is not None:
            query = query.where(Expense.category == category)
        query = query.order_by(Expense.expense_date.desc(), Expense.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await db.execute(query)
        expenses = result.scalars().all()

        logger.info(f"Successfully found {len(expenses)} expenses for group {group_id}")
        return [expense.to_dict() for expense in expenses]

    @staticmethod
    async def get_expense_count_by_group_id(
        db: AsyncSession,
        group_id: int,
        requesting_user_id: int,
        category: Optional[str] = None
    ) -> int:
        """
        Get the total count of expenses in a group.
        Used for server-side pagination.

        Args:
            db: AsyncSession - The database session.
            group_id: int - The ID of the group to count expenses for.
            requesting_user_id: int - The ID of the user requesting. For authorization purposes.
            category: Optional[str] - The category to filter expenses by (default = None)

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
        count_query = select(func.count(Expense.id)).where(Expense.group_id == group_id)
        if category is not None:
            count_query = count_query.where(Expense.category == category)
        result = await db.execute(count_query)
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

    @staticmethod
    async def _assert_authorized(
        db: AsyncSession,
        expense_id: int,
        requesting_user_id: int
    ) -> 'Expense':
        """
        Raise if the expense doesn't exist or the user is neither creator nor payer.
        Returns the Expense ORM object when the check passes.

        Raises:
            ExpenseNotFoundException, UnauthorizedActionException.
        """
        result = await db.execute(select(Expense).where(Expense.id == expense_id))
        expense = result.scalar_one_or_none()
        if not expense:
            raise ExpenseNotFoundException(f"Expense with ID {expense_id} not found")

        if expense.created_by != requesting_user_id and expense.payer_id != requesting_user_id:
            logger.debug(f"User {requesting_user_id} is neither creator nor payer of expense {expense_id}")
            raise UnauthorizedActionException("You can only modify expenses you created or paid for.")

        return expense

    @staticmethod
    async def _assert_modifiable(
        db: AsyncSession,
        expense_id: int,
        requesting_user_id: int
    ) -> 'Expense':
        """
        Raise the appropriate exception if the user cannot edit this expense.
        Editing is blocked once any non-payer participant has settled their share;
        deletion is not (see delete_expense).
        Returns the Expense ORM object when the check passes.

        Raises:
            ExpenseNotFoundException, UnauthorizedActionException, ExpenseNotEditableException.
        """
        expense = await ExpenseService._assert_authorized(db, expense_id, requesting_user_id)

        result = await db.execute(
            select(ExpenseParticipant).where(
                and_(
                    ExpenseParticipant.expense_id == expense_id,
                    ExpenseParticipant.user_id != expense.payer_id,
                    ExpenseParticipant.is_settled
                )
            )
        )
        if result.scalar_one_or_none():
            logger.debug(f"Expense {expense_id} has settled participants other than payer")
            raise ExpenseNotEditableException(
                "Cannot modify: one or more participants have already settled their share."
            )

        return expense

    @staticmethod
    async def can_modify_expense(
        db: AsyncSession,
        expense_id: int,
        requesting_user_id: int
    ) -> tuple[bool, str]:
        """
        Check if a user can edit an expense.

        Authorization rules:
        - Only creator or payer can edit
        - Cannot edit if any participant (other than payer) has settled

        Returns:
            tuple[bool, str] - (can_modify, reason_if_not)
        """
        try:
            await ExpenseService._assert_modifiable(db, expense_id, requesting_user_id)
            return True, ""
        except (ExpenseNotFoundException, UnauthorizedActionException, ExpenseNotEditableException) as e:
            return False, str(e)

    @staticmethod
    async def can_delete_expense(
        db: AsyncSession,
        expense_id: int,
        requesting_user_id: int
    ) -> tuple[bool, str]:
        """
        Check if a user can delete an expense.

        Authorization rules:
        - Only creator or payer can delete
        - Settlement status does not block deletion

        Returns:
            tuple[bool, str] - (can_delete, reason_if_not)
        """
        try:
            await ExpenseService._assert_authorized(db, expense_id, requesting_user_id)
            return True, ""
        except (ExpenseNotFoundException, UnauthorizedActionException) as e:
            return False, str(e)

    @staticmethod
    async def has_related_settlements(
        db: AsyncSession,
        expense_id: int
    ) -> bool:
        """
        Check whether this expense's debt may already have been settled:
        a non-payer participant is marked settled, OR any non-payer participant
        has a recorded payment to the payer in the same group (/settleup records
        payments without setting participant is_settled flags).

        Used to warn before deletion — deleting the expense removes the debt but
        never the payments, so balances may shift.

        Raises:
            ExpenseNotFoundException - If expense doesn't exist.
        """
        result = await db.execute(select(Expense).where(Expense.id == expense_id))
        expense = result.scalar_one_or_none()
        if not expense:
            raise ExpenseNotFoundException(f"Expense with ID {expense_id} not found")

        result = await db.execute(
            select(ExpenseParticipant.user_id, ExpenseParticipant.is_settled).where(
                and_(
                    ExpenseParticipant.expense_id == expense_id,
                    ExpenseParticipant.user_id != expense.payer_id
                )
            )
        )
        rows = result.all()
        if not rows:
            return False
        if any(is_settled for _, is_settled in rows):
            return True

        participant_ids = [user_id for user_id, _ in rows]
        result = await db.execute(
            select(Payment.id).where(
                and_(
                    Payment.group_id == expense.group_id,
                    Payment.to_user_id == expense.payer_id,
                    Payment.from_user_id.in_(participant_ids)
                )
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def delete_expense(
        db: AsyncSession,
        expense_id: int,
        requesting_user_id: int
    ) -> bool:
        """
        Delete an expense and all its participants (cascade).
        Settled expenses can be deleted too — balances are recomputed live from
        the remaining data, but recorded payments are untouched, so net balances
        may shift after deleting an already-settled expense.

        Args:
            db: AsyncSession - The database session.
            expense_id: int - The expense ID to delete.
            requesting_user_id: int - The user requesting deletion.

        Returns:
            bool - True if deleted successfully.

        Raises:
            ExpenseNotFoundException - If expense doesn't exist.
            UnauthorizedActionException - If user cannot delete this expense.
        """
        logger.info(f"User {requesting_user_id} attempting to delete expense {expense_id}")
        expense = await ExpenseService._assert_authorized(db, expense_id, requesting_user_id)
        await db.delete(expense)
        await db.commit()
        logger.info(f"Expense {expense_id} deleted successfully by user {requesting_user_id}")
        return True

    @staticmethod
    async def update_expense(
        db: AsyncSession,
        expense_id: int,
        update_data: Dict[str, Any],
        requesting_user_id: int
    ) -> dict:
        """
        Update an expense with new data.
        Handles recalculation of splits when amount, participants, or split type changes.

        Args:
            db: AsyncSession - The database session.
            expense_id: int - The expense ID to update.
            update_data: Dict[str, Any] - Dictionary containing fields to update.
                Supported fields: description, amount, currency, expense_date, payer_id,
                participant_ids, split_type, split_data
            requesting_user_id: int - The user requesting the update.

        Returns:
            dict - Updated expense data.

        Raises:
            ExpenseNotFoundException - If expense doesn't exist.
            UnauthorizedActionException - If user cannot edit this expense.
            ExpenseNotEditableException - If expense has settled participants.
            GroupMemberNotFoundException - If payer or participant is not a group member.
        """
        logger.info(f"User {requesting_user_id} attempting to update expense {expense_id}")
        await ExpenseService._assert_modifiable(db, expense_id, requesting_user_id)

        result = await db.execute(
            select(Expense)
            .options(selectinload(Expense.participants))
            .where(Expense.id == expense_id)
        )
        expense = result.scalar_one_or_none()

        # Track what's changing for recalculation logic
        amount_changed = 'amount' in update_data and update_data['amount'] != expense.amount
        participants_changed = 'participant_ids' in update_data
        split_type_changed = 'split_type' in update_data and update_data['split_type'] != expense.split_type
        payer_changed = 'payer_id' in update_data and update_data['payer_id'] != expense.payer_id

        # Determine the values to use for recalculation
        new_amount = update_data.get('amount', expense.amount)
        new_split_type = update_data.get('split_type', expense.split_type)
        new_payer_id = update_data.get('payer_id', expense.payer_id)
        old_payer_id = expense.payer_id

        # Validate payer is a group member if changing
        if 'payer_id' in update_data:
            if not await GroupService.is_member(db, expense.group_id, new_payer_id):
                raise GroupMemberNotFoundException("Payer must be a member of the group.")

        # Handle participant changes
        if participants_changed:
            new_participant_ids = update_data['participant_ids']

            # Validate all new participants are group members
            for pid in new_participant_ids:
                if not await GroupService.is_member(db, expense.group_id, pid):
                    raise GroupMemberNotFoundException(f"User {pid} is not a member of the group.")

            # Delete existing participants
            await db.execute(
                ExpenseParticipant.__table__.delete().where(
                    ExpenseParticipant.expense_id == expense_id
                )
            )
            await db.flush()

            # Calculate new shares
            split_data = update_data.get('split_data')
            shares = ExpenseService._calculate_shares(
                amount=new_amount,
                split_type=new_split_type,
                participant_ids=new_participant_ids,
                split_data=split_data
            )

            # Get split percentages if applicable
            split_percentages = None
            if new_split_type == ExpenseSplitType.PERCENTAGE and split_data:
                split_percentages = split_data.get('percentages')

            # Create new participant records
            for i, participant_id in enumerate(new_participant_ids):
                participant = ExpenseParticipant(
                    expense_id=expense_id,
                    user_id=participant_id,
                    share_amount=shares[i],
                    split_percentage=split_percentages[i] if split_percentages else None,
                    is_settled=(participant_id == new_payer_id),
                    settled_at=datetime.now(timezone.utc) if (participant_id == new_payer_id) else None
                )
                db.add(participant)

        elif amount_changed or split_type_changed:
            # Recalculate shares for existing participants
            current_participant_ids = [p.user_id for p in expense.participants]
            split_data = update_data.get('split_data')

            shares = ExpenseService._calculate_shares(
                amount=new_amount,
                split_type=new_split_type,
                participant_ids=current_participant_ids,
                split_data=split_data
            )

            # Get split percentages if applicable
            split_percentages = None
            if new_split_type == ExpenseSplitType.PERCENTAGE and split_data:
                split_percentages = split_data.get('percentages')

            # Update each participant's share
            for i, participant in enumerate(expense.participants):
                participant.share_amount = shares[i]
                if split_percentages:
                    participant.split_percentage = split_percentages[i]
                elif new_split_type != ExpenseSplitType.PERCENTAGE:
                    participant.split_percentage = None

            # If payer also changed, re-assign is_settled on existing participants
            if payer_changed:
                for participant in expense.participants:
                    if participant.user_id == new_payer_id:
                        participant.is_settled = True
                        participant.settled_at = datetime.now(timezone.utc)
                    elif participant.user_id == old_payer_id:
                        participant.is_settled = False
                        participant.settled_at = None

        elif payer_changed:
            # Only the payer changed — re-assign is_settled flags without touching shares
            for participant in expense.participants:
                if participant.user_id == new_payer_id:
                    participant.is_settled = True
                    participant.settled_at = datetime.now(timezone.utc)
                elif participant.user_id == old_payer_id:
                    participant.is_settled = False
                    participant.settled_at = None

        # Update simple fields
        if 'description' in update_data:
            expense.description = update_data['description']
        if 'amount' in update_data:
            expense.amount = update_data['amount']
        if 'currency' in update_data:
            expense.currency = update_data['currency']
        if 'expense_date' in update_data:
            expense.expense_date = update_data['expense_date']
        if 'payer_id' in update_data:
            expense.payer_id = update_data['payer_id']
        if 'split_type' in update_data:
            expense.split_type = update_data['split_type']

        # Update timestamp
        expense.updated_at = datetime.now(timezone.utc)

        # Check if expense should be marked as settled
        # (all participants settled, which happens if only participant is payer)
        await db.flush()

        # Re-fetch to get updated participants
        await db.refresh(expense)
        result = await db.execute(
            select(ExpenseParticipant).where(ExpenseParticipant.expense_id == expense_id)
        )
        updated_participants = result.scalars().all()

        all_settled = all(p.is_settled for p in updated_participants)
        expense.is_settled = all_settled

        await db.commit()
        await db.refresh(expense)

        logger.info(f"Expense {expense_id} updated successfully by user {requesting_user_id}")
        return expense.to_dict()
