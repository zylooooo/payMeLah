class InvalidSplitException(Exception):
    """Exception raised when a split type is invalid or when split amounts don't match the total amount."""
    pass

class ExpenseNotFoundException(Exception):
    """Exception raised when an expense is not found."""
    pass

class ExpenseValidationException(Exception):
    """Exception raised when expense data fails validation."""
    pass

class ExpenseNotEditableException(Exception):
    """Exception raised when trying to edit a settled expense."""
    pass
