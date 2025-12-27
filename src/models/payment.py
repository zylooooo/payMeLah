from sqlalchemy import Column, Integer, String, Numeric, Date, BigInteger, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime, timezone, timedelta
from infrastructure import Base


# Singapore Time (SGT) is UTC+8
SGT = timezone(timedelta(hours=8))

class Payment(Base):
    """
    Payment model representing a settlement between users.
    Tracks who paid whom, how much, and optionally which expenses were settled.
    """
    __tablename__ = 'payments'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='Payment ID')
    from_user_id = Column(BigInteger, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, comment='ID of the user who sent the payment')
    to_user_id = Column(BigInteger, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, comment='ID of the user who received the payment')
    group_id = Column(Integer, ForeignKey('groups.id', ondelete='SET NULL'), nullable=True, comment='ID of the group the payment belongs to')
    amount = Column(Numeric(12, 2), nullable=False, comment='Amount of the payment')
    currency = Column(String(3), nullable=False, comment='Currency of the payment')
    description = Column(String(500), nullable=True, comment='Optional description of the payment')
    payment_date = Column(Date, nullable=False, default=lambda: datetime.now(SGT).date(), comment='Date of the payment')
    created_at = Column(DateTime, default=lambda: datetime.now(SGT), nullable=False, comment='Payment creation timestamp')
    expense_ids = Column(JSONB, nullable=True, comment='Array of expense IDs this payment settles')  # Array of expense IDs this payment settles

    # Relationships
    from_user = relationship('User', foreign_keys=[from_user_id], back_populates='payments_sent')
    to_user = relationship('User', foreign_keys=[to_user_id], back_populates='payments_received')
    group = relationship('Group', back_populates='payments')

    def to_dict(self):
        return {
            'id': self.id,
            'from_user_id': self.from_user_id,
            'to_user_id': self.to_user_id,
            'group_id': self.group_id,
            'amount': self.amount,
            'currency': self.currency,
            'description': self.description,
            'payment_date': self.payment_date.isoformat(),
            'created_at': self.created_at.isoformat(),
            'expense_ids': self.expense_ids
        }
