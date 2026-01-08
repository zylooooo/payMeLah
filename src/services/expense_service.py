from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from models import Expense, ExpenseParticipant, ExpenseSplitType, Group
from shared import (
    ExpenseNotFoundException,
    ExpenseValidationException,
    ExpenseNotEditableException,
    InvalidSplitException,
    GroupNotFoundException,
    GroupMemberNotFoundException,
    UnauthorizedActionException
)
from .group_service import GroupService
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
                    is_settled=(participant_id == expense_data['payer_id']) # Payer's share is auto-settled
                )
                db.add(participant)
            
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
