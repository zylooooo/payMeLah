import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import GroupMember, Payment
from shared import GroupMemberNotFoundException, UnauthorizedActionException

logger = logging.getLogger(__name__)


class PaymentService:
    """Service for recording and managing settlements between group members."""

    @staticmethod
    async def record_payment(
        db: AsyncSession,
        group_id: int,
        from_user_id: int,
        to_user_id: int,
        amount: Decimal,
        currency: str,
        description: Optional[str] = None
    ) -> dict:
        """
        Record a payment from one group member to another.

        Args:
            db: Database session.
            group_id: The group this payment belongs to.
            from_user_id: The user who is paying.
            to_user_id: The user being paid.
            amount: The payment amount (must be > 0).
            currency: The currency code (e.g. "SGD").
            description: Optional note about the payment.

        Returns:
            The created Payment as a dict.

        Raises:
            ValueError: If amount <= 0 or payer == recipient.
            GroupMemberNotFoundException: If either user is not in the group.
        """
        logger.info(f"Recording payment: user {from_user_id} pays {to_user_id} "
                    f"{currency} {amount} in group {group_id}")

        if from_user_id == to_user_id:
            raise ValueError("Cannot record a payment to yourself.")

        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero.")

        # Deduplication: reject identical payment within the last 30 seconds
        dedup_cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)
        dup_result = await db.execute(
            select(Payment).where(
                and_(
                    Payment.group_id == group_id,
                    Payment.from_user_id == from_user_id,
                    Payment.to_user_id == to_user_id,
                    Payment.amount == amount,
                    Payment.currency == currency,
                    Payment.created_at >= dedup_cutoff
                )
            )
        )
        if dup_result.scalar_one_or_none():
            raise ValueError(
                "An identical payment was just recorded. "
                "Please wait a moment before recording another."
            )

        # Both users must be members of the group
        payer_result = await db.execute(
            select(GroupMember).where(
                and_(GroupMember.group_id == group_id, GroupMember.user_id == from_user_id)
            )
        )
        if not payer_result.scalar_one_or_none():
            raise GroupMemberNotFoundException(
                f"Payer {from_user_id} is not a member of group {group_id}."
            )

        recipient_result = await db.execute(
            select(GroupMember).where(
                and_(GroupMember.group_id == group_id, GroupMember.user_id == to_user_id)
            )
        )
        if not recipient_result.scalar_one_or_none():
            raise GroupMemberNotFoundException(
                f"Recipient {to_user_id} is not a member of group {group_id}."
            )

        payment = Payment(
            group_id=group_id,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            amount=amount,
            currency=currency,
            description=description,
            created_at=datetime.now(timezone.utc)
        )
        db.add(payment)
        await db.commit()
        await db.refresh(payment)

        logger.info(f"Payment {payment.id} recorded successfully")
        return payment.to_dict()

    @staticmethod
    async def get_payments_in_group(db: AsyncSession, group_id: int) -> List[dict]:
        """Return all payments in a group, newest first."""
        result = await db.execute(
            select(Payment)
            .where(Payment.group_id == group_id)
            .order_by(Payment.created_at.desc())
        )
        return [p.to_dict() for p in result.scalars().all()]

    @staticmethod
    async def delete_payment(
        db: AsyncSession,
        payment_id: int,
        requesting_user_id: int
    ) -> bool:
        """
        Delete a recorded payment. Only the payer (from_user_id) can delete it.

        Raises:
            ValueError: If payment not found.
            UnauthorizedActionException: If requester is not the payer.
        """
        result = await db.execute(select(Payment).where(Payment.id == payment_id))
        payment = result.scalar_one_or_none()

        if not payment:
            raise ValueError(f"Payment {payment_id} not found.")

        if payment.from_user_id != requesting_user_id:
            raise UnauthorizedActionException("Only the payer can delete this payment.")

        await db.delete(payment)
        await db.commit()

        logger.info(f"Payment {payment_id} deleted by user {requesting_user_id}")
        return True
