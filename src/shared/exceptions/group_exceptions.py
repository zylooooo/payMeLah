class GroupNotFoundException(Exception):
    """Exception raised when a group is not found."""
    pass

class GroupMemberAlreadyExistsException(Exception):
    """Exception raised when a user is already a member of a group."""
    pass

class UnauthorizedGroupJoinException(Exception):
    """Exception raised when a user tries to join a group that he is not a member of."""
    pass