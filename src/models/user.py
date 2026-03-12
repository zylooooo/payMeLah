from sqlalchemy import Column, BigInteger, String, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone, timedelta
from infrastructure import Base


class User(Base):
    """
    User model representing a Telegram user.
    Primary key is the Telegram user ID.
    """

    __tablename__ = 'users'

    id = Column(BigInteger, primary_key=True, index=True, comment='Telegram user ID')
    username = Column(String(255), nullable=True, comment='Telegram username')
    first_name = Column(String(255), nullable=True, comment='User\'s first name')
    last_name = Column(String(255), nullable=True, comment='User\'s last name')
    preferred_currency = Column(String(3), nullable=False, default='SGD', comment='User\'s preferred currency')
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, comment='User\'s creation timestamp')
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False, comment='User\'s last update timestamp')
    simplify_debts = Column(Boolean, default=True, nullable=False, comment='Whether the user prefers to see simplified debts by default')

    # Relationships
    groups = relationship('GroupMember', back_populates='user', cascade='all, delete-orphan')
    expenses_paid = relationship('Expense', foreign_keys='Expense.payer_id', back_populates='payer')
    expense_participations = relationship('ExpenseParticipant', back_populates='user', cascade='all, delete-orphan')
    payments_sent = relationship('Payment', foreign_keys='Payment.from_user_id', back_populates='from_user')
    payments_received = relationship('Payment', foreign_keys='Payment.to_user_id', back_populates='to_user')

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'preferred_currency': self.preferred_currency,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'simplify_debts': self.simplify_debts
        }