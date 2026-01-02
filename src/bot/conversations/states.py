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
