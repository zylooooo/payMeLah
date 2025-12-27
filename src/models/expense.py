from sqlalchemy import Column, Integer, String, Text, Numeric, BigInteger, ForeignKey, DateTime, Boolean, Enum, Date
from sqlalchemy.orm import relationship
from datetime import datetime, timezone, timedelta
from infrastructure import Base
import enum


class ExpenseSplitType(str, enum.Enum):
    """Enumeration of possible split types for an expense."""
    EQUAL = 'equal'
    EXACT = 'exact'
    PERCENTAGE = 'percentage'
    CUSTOM = 'custom'


# Singapore Time (SGT) is UTC+8
SGT = timezone(timedelta(hours=8))

class Expense(Base):
    """
    Expense model representing an singular expense item in a group.
    Tracks who paid, how much, currency paid in and split type.
    Basically the metadata of an expense
    """
    __tablename__ = 'expenses'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='Expense ID')
    group_id = Column(Integer, ForeignKey('groups.id', ondelete='CASCADE'), nullable=False, comment='ID of the group the expense belongs to')
    description = Column(Text, nullable=True, comment='Optional description of the expense')
    amount = Column(Numeric(12, 2), nullable=False, comment='Amount of the expense in the currency of this specific expense')
    currency = Column(String(3), nullable=False, comment='Currency of the expense')
    payer_id = Column(BigInteger, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, comment='ID of the user who paid for the expense')
    expense_date = Column(Date, nullable=False, default=lambda: datetime.now(SGT).date(), comment='Date that the expense was incurred')
    # TODO: consider adding a category enum here, revisit later on after base functionality is implemented
    category = Column(String(100), nullable=True, comment='Optional category of the expense')
    split_type = Column(Enum(ExpenseSplitType, native_enum=False, length=20), nullable=False, default=ExpenseSplitType.EQUAL, comment='Type of split for the expense')
    created_by = Column(BigInteger, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, comment='ID of the user who created the expense')
    created_at = Column(DateTime, default=lambda: datetime.now(SGT), nullable=False, comment='Expense creation timestamp')
    updated_at = Column(DateTime, default=lambda: datetime.now(SGT), onupdate=lambda: datetime.now(SGT), nullable=False, comment='Expense last update timestamp')
    is_settled = Column(Boolean, default=False, nullable=False, comment='Whether the expense has been settled')

    # Relationships
    group = relationship('Group', back_populates='expenses')
    payer = relationship('User', foreign_keys=[payer_id], back_populates='expenses_paid')
    creator = relationship('User', foreign_keys=[created_by])
    participants = relationship('ExpenseParticipant', back_populates='expense', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'group_id': self.group_id,
            'description': self.description,
            'amount': self.amount,
            'currency': self.currency,
            'payer_id': self.payer_id,
            'category': self.category,
            'split_type': self.split_type.value if self.split_type else None,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'is_settled': self.is_settled
        }


class ExpenseParticipant(Base):
    """
    Tracks each participant's share in an expense.
    Supports equal, exact, percentage and custom split types.
    Also marks if a participant has paid their share.
    """
    __tablename__ = 'expense_participants'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='Expense participant ID')
    expense_id = Column(Integer, ForeignKey('expenses.id', ondelete='CASCADE'), nullable=False, comment='ID of the expense the participant belongs to')
    user_id = Column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, comment='ID of the user who is a participant in the expense')
    share_amount = Column(Numeric(12, 2), nullable=False, comment='Amount the participant owes or has paid')
    # If split_type is percentage, this will be used to store the percentage of the split
    split_percentage = Column(Numeric(5, 2), nullable=True, comment='Percentage of the expense the participant owes or has paid')
    is_settled = Column(Boolean, default=False, nullable=False, comment='Whether the participant has paid their share')
    settled_at = Column(DateTime, nullable=True, comment='Timestamp when the participant paid their share')

    # Relationships
    expense = relationship('Expense', back_populates='participants')
    user = relationship('User', back_populates='expense_participations')

    def to_dict(self):
        return {
            'id': self.id,
            'expense_id': self.expense_id,
            'user_id': self.user_id,
            'share_amount': self.share_amount,
            'split_percentage': self.split_percentage,
            'is_settled': self.is_settled,
            'settled_at': self.settled_at.isoformat() if self.settled_at else None
        }
