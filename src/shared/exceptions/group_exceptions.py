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
