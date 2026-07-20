from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import Optional, Tuple, List


class BalanceKeyboard:
    """Class to create inline keyboards for balance-related operations."""

    PREFIX = "balance_"

    # Actions
    ACTION_SELECT_GROUP = "select_group"
    ACTION_VIEW_DETAILS = "view_details"
    ACTION_SETTLE_UP = "settle_up"
    ACTION_REFRESH = "refresh"
    ACTION_BACK = "back"
    ACTION_BACK_TO_LIST = "back_list"
    ACTION_TOGGLE_SIMPLIFY = "toggle_simplify"
    ACTION_CANCEL = "cancel"
    ACTION_NEXT = "next"
    ACTION_PREV = "prev"
    ACTION_PAYMENT_HISTORY = "pay_hist"
    ACTION_NUDGE        = "nudge"         # opens person picker
    ACTION_NUDGE_PERSON = "nudge_person"  # sends nudge to a specific person

    @classmethod
    def get_group_selection_keyboard(
        cls,
        groups: List[dict],
        page: int = 0,
        per_page: int = 5,
        action_prefix: str = "balances"
    ) -> InlineKeyboardMarkup:
        """
        Generate keyboard for selecting a group to view balances.

        Args:
            groups: List of group dictionaries.
            page: Current page number.
            per_page: Number of groups per page.
            action_prefix: Prefix for action context (balances, mybalance, etc.)
        """
        buttons = []

        start_idx = page * per_page
        end_idx = start_idx + per_page
        page_groups = groups[start_idx:end_idx]

        # Group selection buttons
        for group in page_groups:
            buttons.append([
                InlineKeyboardButton(
                    f"{group['name']} ({group['default_currency']})",
                    callback_data=cls._build_callback_data(
                        cls.ACTION_SELECT_GROUP,
                        f"{action_prefix}:{group['id']}"
                    )
                )
            ])

        # Pagination buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    "<< Previous",
                    callback_data=cls._build_callback_data(
                        cls.ACTION_PREV,
                        f"{action_prefix}:{page - 1}"
                    )
                )
            )
        if end_idx < len(groups):
            nav_buttons.append(
                InlineKeyboardButton(
                    "Next >>",
                    callback_data=cls._build_callback_data(
                        cls.ACTION_NEXT,
                        f"{action_prefix}:{page + 1}"
                    )
                )
            )
        if nav_buttons:
            buttons.append(nav_buttons)

        # Cancel button
        buttons.append([
            InlineKeyboardButton(
                "X Cancel",
                callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
            )
        ])

        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_group_balances_keyboard(
        cls,
        group_id: int,
        has_debts: bool = True,
        is_simplified: bool = True
    ) -> InlineKeyboardMarkup:
        """
        Generate keyboard for group balances view.

        Args:
            group_id: The group ID.
            has_debts: Whether there are outstanding debts to settle.
            is_simplified: Whether the current view is showing simplified debts.
        """
        buttons = []

        # Settle up button (only if there are debts).
        # "group" mode: record a payment for any outstanding debt in the group.
        if has_debts:
            buttons.append([
                InlineKeyboardButton(
                    "Settle Up",
                    callback_data=cls._build_callback_data(
                        cls.ACTION_SETTLE_UP,
                        f"group:{group_id}"
                    )
                )
            ])

        # Simplified/raw toggle
        toggle_label = "View: Simplified ✓" if is_simplified else "View: Raw Debts"
        buttons.append([
            InlineKeyboardButton(
                toggle_label,
                callback_data=cls._build_callback_data(
                    cls.ACTION_TOGGLE_SIMPLIFY,
                    f"group:{group_id}"
                )
            )
        ])

        # Payment history
        buttons.append([
            InlineKeyboardButton(
                "Payment History",
                callback_data=cls._build_callback_data(
                    cls.ACTION_PAYMENT_HISTORY,
                    str(group_id)
                )
            )
        ])

        # Refresh button
        buttons.append([
            InlineKeyboardButton(
                "Refresh",
                callback_data=cls._build_callback_data(
                    cls.ACTION_REFRESH,
                    f"group:{group_id}"
                )
            )
        ])

        # Back to group list
        buttons.append([
            InlineKeyboardButton(
                "<< Back to Groups",
                callback_data=cls._build_callback_data(cls.ACTION_BACK_TO_LIST)
            ),
            InlineKeyboardButton(
                "X Close",
                callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
            )
        ])

        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_user_balance_keyboard(
        cls,
        group_id: int,
        has_debts: bool = True,
        owes_money: bool = False,
        is_simplified: bool = True,
        has_owed_by: bool = False,
    ) -> InlineKeyboardMarkup:
        """
        Generate keyboard for user's balance in a group.

        Args:
            group_id: The group ID.
            has_debts: Whether the user has any debts/credits.
            owes_money: Whether the user owes money (can settle).
            is_simplified: Whether the current view is showing simplified debts.
            has_owed_by: Whether someone owes the user money (show Nudge button).
        """
        buttons = []

        # Settle up button (only if user owes money).
        # "user" mode: settle the presser's own debts.
        if owes_money:
            buttons.append([
                InlineKeyboardButton(
                    "Settle My Debts",
                    callback_data=cls._build_callback_data(
                        cls.ACTION_SETTLE_UP,
                        f"user:{group_id}"
                    )
                )
            ])

        # Nudge button (only if someone owes the user)
        if has_owed_by:
            buttons.append([
                InlineKeyboardButton(
                    "Nudge",
                    callback_data=cls._build_callback_data(
                        cls.ACTION_NUDGE,
                        str(group_id)
                    )
                )
            ])

        # Simplified/raw toggle
        toggle_label = "View: Simplified ✓" if is_simplified else "View: Raw Debts"
        buttons.append([
            InlineKeyboardButton(
                toggle_label,
                callback_data=cls._build_callback_data(
                    cls.ACTION_TOGGLE_SIMPLIFY,
                    f"user:{group_id}"
                )
            )
        ])

        # Refresh button
        buttons.append([
            InlineKeyboardButton(
                "Refresh",
                callback_data=cls._build_callback_data(
                    cls.ACTION_REFRESH,
                    f"user:{group_id}"
                )
            )
        ])

        # Navigation
        buttons.append([
            InlineKeyboardButton(
                "<< Back to Groups",
                callback_data=cls._build_callback_data(cls.ACTION_BACK_TO_LIST)
            ),
            InlineKeyboardButton(
                "X Close",
                callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
            )
        ])

        return InlineKeyboardMarkup(buttons)


    @classmethod
    def get_nudge_person_picker_keyboard(
        cls,
        group_id: int,
        owed_by: list,
        on_cooldown_ids: set,
        recently_nudged_ids: set,
    ) -> InlineKeyboardMarkup:
        """
        Person picker for the nudge flow.

        Args:
            group_id: Group ID (for callback data).
            owed_by: List of dicts with keys user_id, first_name, username.
            on_cooldown_ids: Set of user_ids currently on cooldown.
            recently_nudged_ids: Set of user_ids nudged in this session (show ✓).
        """
        buttons = []
        for person in owed_by:
            uid = person['user_id']
            name = person.get('first_name') or person.get('username') or f"User {uid}"
            if uid in recently_nudged_ids:
                label = f"{name} ✓ Nudged"
            elif uid in on_cooldown_ids:
                label = f"{name} ⏳"
            else:
                label = name
            buttons.append([InlineKeyboardButton(
                label,
                callback_data=cls._build_callback_data(
                    cls.ACTION_NUDGE_PERSON,
                    f"{uid}:{group_id}"
                )
            )])

        buttons.append([
            InlineKeyboardButton(
                "<< Back",
                callback_data=cls._build_callback_data(cls.ACTION_BACK, str(group_id))
            ),
            InlineKeyboardButton(
                "X Cancel",
                callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
            )
        ])
        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_close_keyboard(cls) -> InlineKeyboardMarkup:
        """Generate a simple close keyboard."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "X Close",
                    callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
                )
            ]
        ])

    @classmethod
    def _build_callback_data(cls, action: str, data: Optional[str] = None) -> str:
        """Build callback data string."""
        if data:
            return f"{cls.PREFIX}{action}:{data}"
        return f"{cls.PREFIX}{action}"

    @classmethod
    def extract_callback_info(cls, callback_data: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract action and data from callback data.

        Returns:
            Tuple of (action, data) or (None, None) if invalid
        """
        if not callback_data or not callback_data.startswith(cls.PREFIX):
            return None, None

        data_str = callback_data[len(cls.PREFIX):]

        if ':' in data_str:
            action, data = data_str.split(':', 1)
            return action, data
        else:
            return data_str, None

    @classmethod
    def matches_prefix(cls, callback_data: str) -> bool:
        """Check if callback data matches this keyboard's prefix."""
        return callback_data and callback_data.startswith(cls.PREFIX)
