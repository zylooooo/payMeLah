class GroupNotFoundException(Exception):
    """Exception raised when a group is not found."""
    pass


class GroupMemberAlreadyExistsException(Exception):
    """Exception raised when a user is already a member of a group."""
    pass


class GroupMemberNotFoundException(Exception):
    """Exception raised when a group member is not found."""
    pass


class UnauthorizedGroupJoinException(Exception):
    """Exception raised when a user tries to join a group that he is not a member of."""
    pass


class UnauthorizedActionException(Exception):
    """Exception raised when a user tries to perform an unauthorized action."""
    pass


class OutstandingBalanceException(Exception):
    """Raised when a member with a non-zero balance tries to leave or is removed."""

    def __init__(self, amount, currency: str):
        self.amount = amount  # positive = they are owed, negative = they owe
        self.currency = currency
        super().__init__(f"Member has an outstanding balance of {amount} {currency}.")
