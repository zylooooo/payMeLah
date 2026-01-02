from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)

def validate_group_name(name: str) -> Tuple[bool, Optional[str]]:
    """
    Validate if the user's input group name is valid.

    Args:
        name: str - The group name to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name or not name.strip():
        return False, "Group name cannot be empty. Please enter a valid group name between 1 and 255 characters."
    
    name = name.strip()

    if len(name) < 1 or len(name) > 255:
        return False, "Group name must be between 1 and 255 characters. Please enter a valid group name."
    
    return True, None
