from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from models import Expense, ExpenseParticipant, Payment, Group
from shared import (
    GroupNotFoundException,
    UnauthorizedActionException
)
from .group_service import GroupService
from .user_service import UserService
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from collections import defaultdict
import logging


logger = logging.getLogger(__name__)


class BalanceService:
    """
    Service for calculating and managing balances between users in groups.
    Handles balance calculations considering expenses and payments.
    """

    @staticmethod
    async def get_group_balances(
        db: AsyncSession,
        group_id: int,
        requesting_user_id: int
    ) -> Dict[str, any]:
        """
        Calculate all balances within a group.
        Returns who owes whom and the net balance for each member.

        Args:
            db: AsyncSession - The database session.
            group_id: int - The group ID.
            requesting_user_id: int - The user requesting (must be a member).

        Returns:
            Dict containing:
                - 'group': Group information
                - 'members': List of member balances
                - 'debts': List of individual debts (who owes whom)
                - 'currency': The group's default currency

        Raises:
            GroupNotFoundException - If group doesn't exist.
            UnauthorizedActionException - If user is not a member.
        """
        logger.info(f"Calculating group balances for group {group_id}")

        # Verify group exists
        group = await GroupService.get_group_by_id(db, group_id)
        if not group:
            raise GroupNotFoundException(f"Group with ID {group_id} not found")

        # Verify user is a member
        if not await GroupService.is_member(db, group_id, requesting_user_id):
            raise UnauthorizedActionException(
                f"User {requesting_user_id} is not a member of group {group_id}"
            )

        # Get all group members with details
        members = await GroupService.get_group_members_with_details(db, group_id)
        member_ids = [m['user_id'] for m in members]

        # Calculate balances from expenses
        expense_debts = await BalanceService._calculate_expense_debts(
            db, group_id, member_ids
        )

        # Get payments/settlements and adjust debts
        payment_credits = await BalanceService._calculate_payment_credits(
            db, group_id, member_ids
        )

        # Combine expense debts and payment credits to get net debts
        net_debts = BalanceService._combine_debts_and_payments(
            expense_debts, payment_credits
        )

        # Calculate net balance for each member
        member_balances = BalanceService._calculate_member_balances(
            net_debts, member_ids
        )

        # Build member balance list with user details
        members_with_balances = []
        for member in members:
            user_id = member['user_id']
            balance = member_balances.get(user_id, Decimal('0'))
            members_with_balances.append({
                'user_id': user_id,
                'username': member.get('username'),
                'first_name': member.get('first_name'),
                'last_name': member.get('last_name'),
                'balance': balance  # Positive = owed money, Negative = owes money
            })

        # Sort by balance (most owed first, then most owing)
        members_with_balances.sort(key=lambda x: x['balance'], reverse=True)

        # Format debts list for display
        debts_list = []
        for (from_user_id, to_user_id), amount in net_debts.items():
            if amount > 0:
                debts_list.append({
                    'from_user_id': from_user_id,
                    'to_user_id': to_user_id,
                    'amount': amount
                })

        logger.info(f"Successfully calculated balances for group {group_id}")
        return {
            'group': group,
            'members': members_with_balances,
            'debts': debts_list,
            'currency': group['default_currency']
        }

    @staticmethod
    async def get_user_balance_in_group(
        db: AsyncSession,
        group_id: int,
        user_id: int
    ) -> Dict[str, any]:
        """
        Get a specific user's balance details in a group.

        Args:
            db: AsyncSession - The database session.
            group_id: int - The group ID.
            user_id: int - The user ID.

        Returns:
            Dict containing:
                - 'group': Group information
                - 'net_balance': Net balance (positive = owed, negative = owes)
                - 'owes_to': List of users this user owes money to
                - 'owed_by': List of users who owe this user money
                - 'currency': The group's default currency

        Raises:
            GroupNotFoundException - If group doesn't exist.
            UnauthorizedActionException - If user is not a member.
        """
        logger.info(f"Getting balance for user {user_id} in group {group_id}")

        # Get full group balances
        group_balances = await BalanceService.get_group_balances(
            db, group_id, user_id
        )

        # Find this user's balance
        user_balance = None
        for member in group_balances['members']:
            if member['user_id'] == user_id:
                user_balance = member
                break

        # Get members lookup for names
        members_lookup = {
            m['user_id']: m for m in group_balances['members']
        }

        # Calculate what user owes and is owed
        owes_to = []
        owed_by = []

        for debt in group_balances['debts']:
            if debt['from_user_id'] == user_id:
                to_user = members_lookup.get(debt['to_user_id'], {})
                owes_to.append({
                    'user_id': debt['to_user_id'],
                    'username': to_user.get('username'),
                    'first_name': to_user.get('first_name'),
                    'last_name': to_user.get('last_name'),
                    'amount': debt['amount']
                })
            elif debt['to_user_id'] == user_id:
                from_user = members_lookup.get(debt['from_user_id'], {})
                owed_by.append({
                    'user_id': debt['from_user_id'],
                    'username': from_user.get('username'),
                    'first_name': from_user.get('first_name'),
                    'last_name': from_user.get('last_name'),
                    'amount': debt['amount']
                })

        return {
            'group': group_balances['group'],
            'net_balance': user_balance['balance'] if user_balance else Decimal('0'),
            'owes_to': owes_to,
            'owed_by': owed_by,
            'currency': group_balances['currency']
        }

    @staticmethod
    async def get_user_total_balances(
        db: AsyncSession,
        user_id: int
    ) -> Dict[str, any]:
        """
        Get a user's total balances across all groups.

        Args:
            db: AsyncSession - The database session.
            user_id: int - The user ID.

        Returns:
            Dict containing:
                - 'groups': List of group balances
                - 'total_owed': Total amount owed to user (by currency)
                - 'total_owes': Total amount user owes (by currency)
        """
        logger.info(f"Getting total balances for user {user_id}")

        # Get all groups user is a member of
        groups = await GroupService.get_all_groups_by_user_id(db, user_id)

        if not groups:
            return {
                'groups': [],
                'total_owed': {},
                'total_owes': {}
            }

        group_balances = []
        total_owed_by_currency = defaultdict(Decimal)
        total_owes_by_currency = defaultdict(Decimal)

        for group in groups:
            try:
                balance = await BalanceService.get_user_balance_in_group(
                    db, group['id'], user_id
                )
                currency = balance['currency']
                net = balance['net_balance']

                group_balances.append({
                    'group_id': group['id'],
                    'group_name': group['name'],
                    'currency': currency,
                    'net_balance': net,
                    'owes_to': balance['owes_to'],
                    'owed_by': balance['owed_by']
                })

                # Aggregate totals by currency
                if net > 0:
                    total_owed_by_currency[currency] += net
                elif net < 0:
                    total_owes_by_currency[currency] += abs(net)

            except Exception as e:
                logger.warning(f"Error getting balance for group {group['id']}: {e}")
                continue

        logger.info(f"Successfully calculated total balances for user {user_id}")
        return {
            'groups': group_balances,
            'total_owed': dict(total_owed_by_currency),
            'total_owes': dict(total_owes_by_currency)
        }

    @staticmethod
    async def _calculate_expense_debts(
        db: AsyncSession,
        group_id: int,
        member_ids: List[int]
    ) -> Dict[Tuple[int, int], Decimal]:
        """
        Calculate debts from unsettled expense participations.

        Returns:
            Dict mapping (from_user_id, to_user_id) -> amount
            where from_user owes to_user the amount
        """
        debts = defaultdict(Decimal)

        # Get all unsettled expense participations in the group
        result = await db.execute(
            select(ExpenseParticipant, Expense.payer_id)
            .join(Expense, ExpenseParticipant.expense_id == Expense.id)
            .where(
                and_(
                    Expense.group_id == group_id,
                    ExpenseParticipant.is_settled == False,
                    ExpenseParticipant.user_id != Expense.payer_id  # Don't include payer's self-share
                )
            )
        )
        participations = result.all()

        for participation, payer_id in participations:
            # participant owes payer
            debtor = participation.user_id
            creditor = payer_id
            amount = Decimal(str(participation.share_amount))

            debts[(debtor, creditor)] += amount

        return debts

    @staticmethod
    async def _calculate_payment_credits(
        db: AsyncSession,
        group_id: int,
        member_ids: List[int]
    ) -> Dict[Tuple[int, int], Decimal]:
        """
        Calculate credits from payments/settlements.

        Returns:
            Dict mapping (from_user_id, to_user_id) -> amount
            representing payments made (reduces debt)
        """
        credits = defaultdict(Decimal)

        # Get all payments in the group
        result = await db.execute(
            select(Payment)
            .where(Payment.group_id == group_id)
        )
        payments = result.scalars().all()

        for payment in payments:
            if payment.from_user_id and payment.to_user_id:
                # Payment from from_user to to_user reduces debt
                credits[(payment.from_user_id, payment.to_user_id)] += Decimal(str(payment.amount))

        return credits

    @staticmethod
    def _combine_debts_and_payments(
        debts: Dict[Tuple[int, int], Decimal],
        payments: Dict[Tuple[int, int], Decimal]
    ) -> Dict[Tuple[int, int], Decimal]:
        """
        Combine expense debts and payment credits to get net debts.
        Also consolidates bidirectional debts (A owes B and B owes A).
        """
        # Start with expense debts
        net = defaultdict(Decimal)
        for key, amount in debts.items():
            net[key] += amount

        # Subtract payments
        for key, amount in payments.items():
            net[key] -= amount

        # Consolidate bidirectional debts
        consolidated = {}
        processed = set()

        for (from_user, to_user), amount in net.items():
            if (from_user, to_user) in processed:
                continue

            reverse_amount = net.get((to_user, from_user), Decimal('0'))

            # Calculate net debt
            net_amount = amount - reverse_amount

            if net_amount > 0:
                consolidated[(from_user, to_user)] = net_amount
            elif net_amount < 0:
                consolidated[(to_user, from_user)] = abs(net_amount)
            # If net_amount == 0, no debt exists

            processed.add((from_user, to_user))
            processed.add((to_user, from_user))

        return consolidated

    @staticmethod
    def _calculate_member_balances(
        debts: Dict[Tuple[int, int], Decimal],
        member_ids: List[int]
    ) -> Dict[int, Decimal]:
        """
        Calculate net balance for each member.
        Positive = they are owed money
        Negative = they owe money
        """
        balances = {uid: Decimal('0') for uid in member_ids}

        for (from_user, to_user), amount in debts.items():
            # from_user owes, so their balance decreases
            if from_user in balances:
                balances[from_user] -= amount
            # to_user is owed, so their balance increases
            if to_user in balances:
                balances[to_user] += amount

        return balances

    @staticmethod
    async def get_simplified_debts(
        db: AsyncSession,
        group_id: int,
        requesting_user_id: int
    ) -> List[Dict]:
        """
        Get simplified debts for a group (debt simplification).
        Minimizes the number of transactions needed to settle all debts.

        This will be fully implemented in Phase 4.
        For now, returns the raw debts.

        Args:
            db: AsyncSession - The database session.
            group_id: int - The group ID.
            requesting_user_id: int - The user requesting.

        Returns:
            List of simplified debt transactions.
        """
        logger.info(f"Getting simplified debts for group {group_id}")

        # Get group balances
        group_balances = await BalanceService.get_group_balances(
            db, group_id, requesting_user_id
        )

        # For now, return the raw debts
        # Phase 4 will implement the simplification algorithm
        return group_balances['debts']
