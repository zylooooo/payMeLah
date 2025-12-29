class UserNotFoundException(Exception):
    """Exception raised when a user is not found."""
    pass

class UserAlreadyExistsException(Exception):
    """Exception raises when a user with the same Telegram user ID already exists."""
    pass