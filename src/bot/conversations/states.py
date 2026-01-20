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


class EditExpenseStates(Enum):
    """States for the edit expense conversation."""
    SELECT_FIELD = auto()           # Main edit menu
    EDIT_DESCRIPTION = auto()       # Text input for description
    EDIT_AMOUNT = auto()            # Number input for amount
    EDIT_CURRENCY = auto()          # Currency code input
    EDIT_DATE = auto()              # Date input
    EDIT_PAYER = auto()             # Member selection
    EDIT_PARTICIPANTS = auto()      # Multi-select participants
    EDIT_SPLIT_TYPE = auto()        # Split type selection
    ENTER_EXACT_AMOUNTS = auto()    # Per-participant exact amounts
    ENTER_PERCENTAGES = auto()      # Per-participant percentages
    ENTER_CUSTOM_SHARES = auto()    # Per-participant share ratios
    SUMMARY = auto()                # Confirm changes before saving