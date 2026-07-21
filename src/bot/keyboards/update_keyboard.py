from typing import Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


class UpdateKeyboard:
    """Class to create inline keyboards for updating user information."""

    PREFIX = "update_profile_"

    # Field names
    FIELD_FIRST_NAME = "first_name"
    FIELD_LAST_NAME = "last_name"
    FIELD_PREFERRED_CURRENCY = "preferred_currency"
    FIELD_SIMPLIFY_DEBTS = "simplify_debts"

    # Callback actions
    ACTION_SKIP = "skip"
    ACTION_CANCEL = "cancel"
    ACTION_BACK = "back"
    ACTION_EDIT = "edit"
    ACTION_CONFIRM = "confirm"
    ACTION_SELECT = "select"  # Used for boolean/choice field selections

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
    def get_boolean_field_keyboard(cls, current_field: str, is_first: bool = False) -> InlineKeyboardMarkup:
        """
        Generate a selection keyboard for boolean fields.
        Shows two labelled options plus Skip/Back/Cancel navigation.
        Callback data encodes both field and value: action:field:value.
        """
        buttons = []

        if not is_first:
            buttons.append([
                InlineKeyboardButton(
                    "<< Back",
                    callback_data=cls._build_callback_data(cls.ACTION_BACK, current_field)
                )
            ])

        # Option buttons — value encoded in the field segment
        buttons.append([
            InlineKeyboardButton(
                "Simplified Debts",
                callback_data=cls._build_callback_data(cls.ACTION_SELECT, f"{current_field}:true")
            ),
            InlineKeyboardButton(
                "Raw Debts",
                callback_data=cls._build_callback_data(cls.ACTION_SELECT, f"{current_field}:false")
            )
        ])

        buttons.append([
            InlineKeyboardButton(
                ">> Skip",
                callback_data=cls._build_callback_data(cls.ACTION_SKIP, current_field)
            ),
            InlineKeyboardButton(
                "X Cancel",
                callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
            )
        ])

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
                ),
                InlineKeyboardButton(
                    "Edit Debt View",
                    callback_data=cls._build_callback_data(cls.ACTION_EDIT, cls.FIELD_SIMPLIFY_DEBTS)
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
