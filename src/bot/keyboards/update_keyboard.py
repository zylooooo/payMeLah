from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional, Tuple

class UpdateKeyboard:
    """Class to create inline keyboards for updating user information."""

    PREFIX = "update_profile_"
    
    # Field names (removed redundant wrapper)
    FIELD_FIRST_NAME = "first_name"
    FIELD_LAST_NAME = "last_name"
    FIELD_PREFERRED_CURRENCY = "preferred_currency"
    
    # Callback actions
    ACTION_SKIP = "skip"
    ACTION_CANCEL = "cancel"
    ACTION_BACK = "back"
    ACTION_EDIT = "edit"
    ACTION_CONFIRM = "confirm"

    @classmethod
    def get_navigation_keyboard(cls, current_field: str, is_first: bool = False) -> InlineKeyboardMarkup:
        """Generate navigation keyboard for field input."""
        buttons = []

        if not is_first:
            buttons.append([
                InlineKeyboardButton(
                    "<< Back",
                    callback_data=cls._build_callback_data(cls.ACTION_BACK, current_field)
                )
            ])

        row = [
            InlineKeyboardButton(
                ">> Skip",
                callback_data=cls._build_callback_data(cls.ACTION_SKIP, current_field)
            ),
            InlineKeyboardButton(
                "X Cancel",
                callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
            )
        ]
        buttons.append(row)

        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_summary_keyboard(cls) -> InlineKeyboardMarkup:
        """Generate keyboard for summary screen."""
        buttons = [
            [
                InlineKeyboardButton(
                    "Edit First Name",
                    callback_data=cls._build_callback_data(cls.ACTION_EDIT, cls.FIELD_FIRST_NAME)
                ),
                InlineKeyboardButton(
                    "Edit Last Name",
                    callback_data=cls._build_callback_data(cls.ACTION_EDIT, cls.FIELD_LAST_NAME)
                )
            ],
            [
                InlineKeyboardButton(
                    "Edit Currency",
                    callback_data=cls._build_callback_data(cls.ACTION_EDIT, cls.FIELD_PREFERRED_CURRENCY)
                )
            ],
            [
                InlineKeyboardButton(
                    "Confirm",
                    callback_data=cls._build_callback_data(cls.ACTION_CONFIRM)
                ),
                InlineKeyboardButton(
                    "X Cancel",
                    callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
                )
            ]
        ]
        return InlineKeyboardMarkup(buttons)

    @classmethod
    def _build_callback_data(cls, action: str, field: Optional[str] = None) -> str:
        """Build callback data string."""
        if field:
            return f"{cls.PREFIX}{action}:{field}"
        return f"{cls.PREFIX}{action}"

    @classmethod
    def extract_callback_info(cls, callback_data: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract action and field from callback data.
        
        Args:
            callback_data: The callback data string
            
        Returns:
            Tuple of (action, field) or (None, None) if invalid
        """
        if not callback_data or not callback_data.startswith(cls.PREFIX):
            return None, None
        
        data = callback_data[len(cls.PREFIX):]
        
        if ':' in data:
            action, field = data.split(':', 1)
            return action, field
        else:
            return data, None

    @classmethod
    def matches_prefix(cls, callback_data: str) -> bool:
        """Check if callback data matches this keyboard's prefix."""
        return callback_data and callback_data.startswith(cls.PREFIX)
    