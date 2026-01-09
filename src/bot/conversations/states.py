from enum import Enum, auto

class UpdateProfileStates(Enum):
    """States for the update profile conversation."""
    FIRST_NAME = auto()
    LAST_NAME = auto()
    PREFERRED_CURRENCY = auto()
    SUMMARY = auto()

class CreateGroupStates(Enum):
    """States for the create group conversation."""
    NAME = auto()
    DESCRIPTION = auto()
    CURRENCY = auto()
    SUMMARY = auto()

class CreateExpenseStates(Enum):
    """States for the create expense conversation."""
    SELECT_GROUP = auto()
    SELECT_CURRENCY = auto()
    AMOUNT = auto()
    DESCRIPTION = auto()
    SELECT_PAYER = auto()
    SELECT_PARTICIPANTS = auto()
    SELECT_SPLIT_TYPE = auto()
    ENTER_EXACT_AMOUNTS = auto()
    ENTER_PERCENTAGES = auto()
    ENTER_CUSTOM = auto()
    SUMMARY = auto()
