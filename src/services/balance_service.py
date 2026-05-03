from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from models import Expense, ExpenseParticipant, Payment, Group
from shared import (
    GroupNotFoundException,
    UnauthorizedActionException
)
from .group_service import GroupService
from .user_service import UserService
from .currency_service import CurrencyService
from typing import Dict, List, Tuple
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
        requesting_user_id: int,
        simplify: bool = True
    ) -> Dict[str, any]:
        """
        Calculate all balances within a group.

        Args:
            db: Database session.
            group_id: The group ID.
            requesting_user_id: Must be a member of the group.
            simplify: If True, apply min-transactions simplification to debts.

        Returns:
            Dict with keys: group, members, debts, currency, conversion_warnings,
            total_spend, per_currency_totals, requesting_user_stats.
            members: sorted list of {user_id, username, first_name, last_name, balance}.
            debts: list of {from_user_id, to_user_id, amount} — simplified or raw.
            requesting_user_stats: {total_paid, total_share, net_balance} for the requesting user.

        Raises:
            GroupNotFoundException, UnauthorizedActionException.
        """
        logger.info(f"Calculating group balances for group {group_id} (simplify={simplify})")

        group = await GroupService.get_group_by_id(db, group_id)
        if not group:
            raise GroupNotFoundException(f"Group {group_id} not found")

        if not await GroupService.is_member(db, group_id, requesting_user_id):
            raise UnauthorizedActionException(
                f"User {requesting_user_id} is not a member of group {group_id}"
            )

        members = await GroupService.get_group_members_with_details(db, group_id)
        member_ids = [m['user_id'] for m in members]
        group_currency = group['default_currency']

        # Calculate raw net debts (expense debts minus payments already made).
        # All amounts are converted to the group's default currency before summing.
        expense_debts, expense_warnings = await BalanceService._calculate_expense_debts(
            db, group_id, member_ids, group_currency
        )
        payment_credits, payment_warnings = await BalanceService._calculate_payment_credits(
            db, group_id, member_ids, group_currency
        )
        net_debts = BalanceService._combine_debts_and_payments(expense_debts, payment_credits)
        conversion_warnings = expense_warnings + payment_warnings

        # Produce the debt list — simplified or raw
        if simplify:
            debts_list = BalanceService._simplify_debts(net_debts, member_ids)
        else:
            debts_list = [
                {'from_user_id': from_id, 'to_user_id': to_id, 'amount': amount}
                for (from_id, to_id), amount in net_debts.items()
                if amount > 0
            ]

        # Net balance per member (positive = owed money, negative = owes money)
        member_balances = BalanceService._calculate_member_balances(net_debts, member_ids)

        members_with_balances = []
        for member in members:
            uid = member['user_id']
            members_with_balances.append({
                'user_id': uid,
                'username': member.get('username'),
                'first_name': member.get('first_name'),
                'last_name': member.get('last_name'),
                'balance': member_balances.get(uid, Decimal('0'))
            })
        members_with_balances.sort(key=lambda x: x['balance'], reverse=True)

        total_spend, spend_warnings = await BalanceService._calculate_total_spend(
            db, group_id, group_currency
        )
        per_currency_totals = await BalanceService._get_per_currency_totals(db, group_id)
        conversion_warnings = list(dict.fromkeys(conversion_warnings + spend_warnings))

        user_paid, user_share, user_spend_warnings = await BalanceService._calculate_user_spend_stats(
            db, group_id, requesting_user_id, group_currency
        )
        requesting_user_stats = {
            'total_paid': user_paid,
            'total_share': user_share,
            'net_balance': member_balances.get(requesting_user_id, Decimal('0')),
        }
        conversion_warnings = list(dict.fromkeys(conversion_warnings + user_spend_warnings))

        logger.info(f"Calculated balances for group {group_id}: {len(debts_list)} debt(s)")
        return {
            'group': group,
            'members': members_with_balances,
            'debts': debts_list,
            'currency': group_currency,
            'conversion_warnings': conversion_warnings,
            'total_spend': total_spend,
            'per_currency_totals': per_currency_totals,
            'requesting_user_stats': requesting_user_stats,
        }

    @staticmethod
    async def get_user_balance_in_group(
        db: AsyncSession,
        group_id: int,
        user_id: int,
        simplify: bool = True
    ) -> Dict[str, any]:
        """
        Get a specific user's balance details in a group.

        Args:
            db: Database session.
            group_id: The group ID.
            user_id: The user ID.
            simplify: Whether to apply debt simplification.

        Returns:
            Dict with keys: group, net_balance, owes_to, owed_by, currency.

        Raises:
            GroupNotFoundException, UnauthorizedActionException.
        """
        logger.info(f"Getting balance for user {user_id} in group {group_id} (simplify={simplify})")

        group_balances = await BalanceService.get_group_balances(
            db, group_id, user_id, simplify=simplify
        )

        user_balance = next(
            (m for m in group_balances['members'] if m['user_id'] == user_id),
            None
        )
        members_lookup = {m['user_id']: m for m in group_balances['members']}

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

        stats = group_balances.get('requesting_user_stats') or {}
        total_paid = stats.get('total_paid', Decimal('0'))
        total_share = stats.get('total_share', Decimal('0'))

        return {
            'group': group_balances['group'],
            'net_balance': user_balance['balance'] if user_balance else Decimal('0'),
            'owes_to': owes_to,
            'owed_by': owed_by,
            'currency': group_balances['currency'],
            'conversion_warnings': group_balances.get('conversion_warnings', []),
            'total_paid': total_paid,
            'total_share': total_share,
            'total_spend': group_balances.get('total_spend', Decimal('0')),
        }

    @staticmethod
    async def get_user_total_balances(
        db: AsyncSession,
        user_id: int
    ) -> Dict[str, any]:
        """
        Get a user's total balances across all groups.
        Always uses simplified debts (summary view).

        Returns:
            Dict with keys: groups, total_owed (by currency), total_owes (by currency),
            preferred_currency, preferred_total (converted grand total).
        """
        logger.info(f"Getting total balances for user {user_id}")

        groups = await GroupService.get_all_groups_by_user_id(db, user_id)
        if not groups:
            return {
                'groups': [], 'total_owed': {}, 'total_owes': {},
                'preferred_currency': 'SGD',
                'preferred_total': {'owed': Decimal('0'), 'owes': Decimal('0'), 'conversion_failed': False}
            }

        user = await UserService.get_user_by_id(db, user_id)
        preferred_currency = user.get('preferred_currency', 'SGD') if user else 'SGD'

        group_balances = []
        total_owed_by_currency = defaultdict(Decimal)
        total_owes_by_currency = defaultdict(Decimal)
        preferred_owed = Decimal('0')
        preferred_owes = Decimal('0')
        conversion_failed = False

        for group in groups:
            try:
                balance = await BalanceService.get_user_balance_in_group(
                    db, group['id'], user_id, simplify=True
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

                if net > 0:
                    total_owed_by_currency[currency] += net
                elif net < 0:
                    total_owes_by_currency[currency] += abs(net)

                # Contribute to the preferred-currency grand total
                if net != 0:
                    try:
                        converted = await CurrencyService.convert(abs(net), currency, preferred_currency)
                        if net > 0:
                            preferred_owed += converted
                        else:
                            preferred_owes += converted
                    except ValueError:
                        conversion_failed = True

            except Exception as e:
                logger.warning(f"Error getting balance for group {group['id']}: {e}")
                continue

        logger.info(f"Calculated total balances for user {user_id}")
        return {
            'groups': group_balances,
            'total_owed': dict(total_owed_by_currency),
            'total_owes': dict(total_owes_by_currency),
            'preferred_currency': preferred_currency,
            'preferred_total': {
                'owed': preferred_owed,
                'owes': preferred_owes,
                'conversion_failed': conversion_failed,
            },
        }

    @staticmethod
    def _simplify_debts(
        net_debts: Dict[Tuple[int, int], Decimal],
        member_ids: List[int]
    ) -> List[Dict]:
        """
        Reduce the number of transactions needed to settle all debts using
        the greedy min-transactions algorithm.

        Algorithm:
        1. Compute net balance per person from the raw debt pairs.
        2. Repeatedly match the biggest debtor with the biggest creditor.
        3. Transfer min(|debtor_balance|, creditor_balance) between them.
        4. Continue until all balances reach zero.

        This produces the minimum number of transactions to clear all debts.

        Args:
            net_debts: Consolidated pairwise debts {(from_id, to_id): amount}.
            member_ids: All member IDs in the group.

        Returns:
            List of {from_user_id, to_user_id, amount} dicts.
        """
        # Build net balance per person (positive = owed, negative = owes)
        balances: Dict[int, Decimal] = defaultdict(Decimal)
        for (from_user, to_user), amount in net_debts.items():
            balances[from_user] -= amount
            balances[to_user] += amount

        # Work only with non-zero balances (threshold to handle floating-point noise)
        EPSILON = Decimal('0.005')
        non_zero = {uid: bal for uid, bal in balances.items() if abs(bal) > EPSILON}

        simplified = []
        while len(non_zero) >= 2:
            debtor = min(non_zero, key=lambda x: non_zero[x])    # most negative
            creditor = max(non_zero, key=lambda x: non_zero[x])  # most positive

            # Both sides must be non-trivially non-zero
            if non_zero[creditor] <= EPSILON or abs(non_zero[debtor]) <= EPSILON:
                break

            transfer = min(abs(non_zero[debtor]), non_zero[creditor])
            transfer = transfer.quantize(Decimal('0.01'))

            if transfer > 0:
                simplified.append({
                    'from_user_id': debtor,
                    'to_user_id': creditor,
                    'amount': transfer
                })

            non_zero[debtor] += transfer
            non_zero[creditor] -= transfer

            # Remove settled balances
            non_zero = {uid: bal for uid, bal in non_zero.items() if abs(bal) > EPSILON}

        return simplified

    @staticmethod
    async def _get_per_currency_totals(
        db: AsyncSession,
        group_id: int,
    ) -> dict:
        """
        Sum all expense amounts per original currency (before any conversion).
        Used to show a multi-currency breakdown in the balance view.

        Returns:
            Dict of {currency_code: total_amount} in original currencies.
        """
        totals: dict = {}
        result = await db.execute(
            select(Expense.amount, Expense.currency).where(Expense.group_id == group_id)
        )
        for amount, currency in result.all():
            amount = Decimal(str(amount))
            totals[currency] = totals.get(currency, Decimal('0')) + amount
        return totals

    @staticmethod
    async def _calculate_total_spend(
        db: AsyncSession,
        group_id: int,
        group_currency: str,
    ) -> Tuple[Decimal, List[str]]:
        """
        Sum the amount of every expense in the group, converted to group_currency.
        Includes all expenses regardless of settlement status.

        Returns:
            Tuple of (total_spend, conversion_warning_strings).
        """
        total = Decimal('0')
        warnings: List[str] = []

        result = await db.execute(
            select(Expense.amount, Expense.currency).where(Expense.group_id == group_id)
        )
        for amount, currency in result.all():
            amount = Decimal(str(amount))
            if currency != group_currency:
                try:
                    amount = await CurrencyService.convert(amount, currency, group_currency)
                except ValueError:
                    warning = f"{currency} → {group_currency}"
                    if warning not in warnings:
                        warnings.append(warning)
            total += amount

        return total, warnings

    @staticmethod
    async def _calculate_user_spend_stats(
        db: AsyncSession,
        group_id: int,
        user_id: int,
        group_currency: str,
    ) -> Tuple[Decimal, Decimal, List[str]]:
        """
        Calculate how much a user has paid out-of-pocket and what their total
        share across all group expenses is (regardless of settlement status).

        Returns:
            Tuple of (total_paid, total_share, conversion_warning_strings).
        """
        total_paid = Decimal('0')
        total_share = Decimal('0')
        warnings: List[str] = []

        # Expenses where the user was the payer
        paid_result = await db.execute(
            select(Expense.amount, Expense.currency)
            .where(and_(Expense.group_id == group_id, Expense.payer_id == user_id))
        )
        for amount, currency in paid_result.all():
            amount = Decimal(str(amount))
            if currency != group_currency:
                try:
                    amount = await CurrencyService.convert(amount, currency, group_currency)
                except ValueError:
                    warning = f"{currency} → {group_currency}"
                    if warning not in warnings:
                        warnings.append(warning)
            total_paid += amount

        # Sum of the user's share across all participations
        share_result = await db.execute(
            select(ExpenseParticipant.share_amount, Expense.currency)
            .join(Expense, ExpenseParticipant.expense_id == Expense.id)
            .where(and_(Expense.group_id == group_id, ExpenseParticipant.user_id == user_id))
        )
        for share_amount, currency in share_result.all():
            amount = Decimal(str(share_amount))
            if currency != group_currency:
                try:
                    amount = await CurrencyService.convert(amount, currency, group_currency)
                except ValueError:
                    warning = f"{currency} → {group_currency}"
                    if warning not in warnings:
                        warnings.append(warning)
            total_share += amount

        return total_paid, total_share, warnings

    @staticmethod
    async def _calculate_expense_debts(
        db: AsyncSession,
        group_id: int,
        member_ids: List[int],
        group_currency: str,
    ) -> Tuple[Dict[Tuple[int, int], Decimal], List[str]]:
        """
        Calculate debts from unsettled expense participations.
        Each share amount is converted to group_currency before summing.

        Returns:
            Tuple of (debts dict, list of human-readable conversion warning strings).
            debts: {(debtor_id, creditor_id): amount} in group_currency.
        """
        debts: Dict[Tuple[int, int], Decimal] = defaultdict(Decimal)
        warnings: List[str] = []

        result = await db.execute(
            select(ExpenseParticipant, Expense.payer_id, Expense.currency)
            .join(Expense, ExpenseParticipant.expense_id == Expense.id)
            .where(
                and_(
                    Expense.group_id == group_id,
                    ExpenseParticipant.user_id != Expense.payer_id
                )
            )
        )
        for participation, payer_id, expense_currency in result.all():
            amount = Decimal(str(participation.share_amount))
            if expense_currency != group_currency:
                try:
                    amount = await CurrencyService.convert(amount, expense_currency, group_currency)
                except ValueError as e:
                    logger.warning(f"Currency conversion failed ({expense_currency}→{group_currency}): {e}")
                    warning = f"{expense_currency} → {group_currency}"
                    if warning not in warnings:
                        warnings.append(warning)
            debts[(participation.user_id, payer_id)] += amount

        return debts, warnings

    @staticmethod
    async def _calculate_payment_credits(
        db: AsyncSession,
        group_id: int,
        member_ids: List[int],
        group_currency: str,
    ) -> Tuple[Dict[Tuple[int, int], Decimal], List[str]]:
        """
        Calculate credits from recorded payments/settlements.
        Each payment amount is converted to group_currency before summing.

        Returns:
            Tuple of (credits dict, list of conversion warning strings).
        """
        credits: Dict[Tuple[int, int], Decimal] = defaultdict(Decimal)
        warnings: List[str] = []

        result = await db.execute(
            select(Payment).where(Payment.group_id == group_id)
        )
        for payment in result.scalars().all():
            if payment.from_user_id and payment.to_user_id:
                amount = Decimal(str(payment.amount))
                if payment.currency != group_currency:
                    try:
                        amount = await CurrencyService.convert(amount, payment.currency, group_currency)
                    except ValueError as e:
                        logger.warning(f"Payment currency conversion failed ({payment.currency}→{group_currency}): {e}")
                        warning = f"{payment.currency} → {group_currency}"
                        if warning not in warnings:
                            warnings.append(warning)
                credits[(payment.from_user_id, payment.to_user_id)] += amount

        return credits, warnings

    @staticmethod
    def _combine_debts_and_payments(
        debts: Dict[Tuple[int, int], Decimal],
        payments: Dict[Tuple[int, int], Decimal]
    ) -> Dict[Tuple[int, int], Decimal]:
        """
        Combine expense debts and payment credits into net pairwise debts.
        Also consolidates bidirectional debts (A owes B and B owes A → one net debt).
        """
        net: Dict[Tuple[int, int], Decimal] = defaultdict(Decimal)
        for key, amount in debts.items():
            net[key] += amount
        for key, amount in payments.items():
            net[key] -= amount

        # Consolidate bidirectional debts
        consolidated = {}
        processed = set()
        for (from_user, to_user), amount in net.items():
            if (from_user, to_user) in processed:
                continue
            reverse = net.get((to_user, from_user), Decimal('0'))
            net_amount = amount - reverse
            if net_amount > 0:
                consolidated[(from_user, to_user)] = net_amount
            elif net_amount < 0:
                consolidated[(to_user, from_user)] = abs(net_amount)
            processed.add((from_user, to_user))
            processed.add((to_user, from_user))

        return consolidated

    @staticmethod
    def _calculate_member_balances(
        debts: Dict[Tuple[int, int], Decimal],
        member_ids: List[int]
    ) -> Dict[int, Decimal]:
        """
        Compute net balance per member.
        Positive = they are owed money. Negative = they owe money.
        """
        balances = {uid: Decimal('0') for uid in member_ids}
        for (from_user, to_user), amount in debts.items():
            if from_user in balances:
                balances[from_user] -= amount
            if to_user in balances:
                balances[to_user] += amount
        return balances
