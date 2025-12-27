from sqlalchemy import Column, Integer, String, Text, BigInteger, ForeignKey, DateTime, Enum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone, timedelta
from infrastructure import Base
import enum


class GroupMemberRole(str, enum.Enum):
    """
    Enumeration of possible roles for a group member.
    """
    MEMBER = 'member'
    ADMIN = 'admin'
    OWNER = 'owner'


# Singapore Time (SGT) is UTC+8
SGT = timezone(timedelta(hours=8))


class Group(Base):
    """
    Group model representing an expense group, a group of users.
    Users can create groups to organize their expenses and payments.
    """
    __tablename__ = 'groups'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='Group ID')
    name = Column(String(255), nullable=False, comment='Group name chosen by the user')
    description = Column(Text, nullable=True, comment='Additional description of the group')
    default_currency = Column(String(3), nullable=False, default='SGD', comment='Default currency for the group\'s expenses')
    created_by = Column(BigInteger, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, comment='User who created the group')
    created_at = Column(DateTime, default=lambda: datetime.now(SGT), nullable=False, comment='Group creation timestamp')
    updated_at = Column(DateTime, default=lambda: datetime.now(SGT), onupdate=lambda: datetime.now(SGT), nullable=False, comment='Group last update timestamp')

    # Relationships
    members = relationship('GroupMember', back_populates='group', cascade='all, delete-orphan')
    expenses = relationship('Expense', back_populates='group', cascade='all, delete-orphan')
    payments = relationship('Payment', back_populates='group')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'default_currency': self.default_currency,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class GroupMember(Base):
    """
    Tracks group memberships and roles of users in a group.
    """
    __tablename__ = 'group_members'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='Group member ID')
    group_id = Column(Integer, ForeignKey('groups.id', ondelete='CASCADE'), nullable=False, comment='ID of the group the member belongs to')
    user_id = Column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, comment='ID of the user who is a member of the group')
    role = Column(Enum(GroupMemberRole, native_enum=False, length=20), nullable=False, default=GroupMemberRole.MEMBER, comment='Role of the user in the group')
    joined_at = Column(DateTime, default=lambda: datetime.now(SGT), nullable=False, comment='Timestamp when the user joined the group')

    # Relationships
    group = relationship('Group', back_populates='members')
    user = relationship('User', back_populates='groups')

    def to_dict(self):
        return {
            'id': self.id,
            'group_id': self.group_id,
            'user_id': self.user_id,
            'role': self.role.value if self.role else None,
            'joined_at': self.joined_at.isoformat()
        }
