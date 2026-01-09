from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import Optional, Tuple, List
from models import ExpenseSplitType


class ExpenseKeyboard:
    """Inline keyboards for expense operations."""

    PREFIX = "expense_"

    # Actions
    ACTION_SELECT = "select"
    ACTION_SELECT_PAYER = "payer"
    ACTION_SELECT_PARTICIPANT = "participant"
    ACTION_TOGGLE_PARTICIPANT = "toggle"
    ACTION_DONE_PARTICIPANTS = "done_participants"
    ACTION_SELECT_SPLIT = "split"
    ACTION_CANCEL = "cancel"
    ACTION_CONFIRM = "confirm"
    ACTION_DELETE = "delete"
    ACTION_BACK = "back"
    ACTION_BACK_TO_LIST = "back_list"
    ACTION_NEXT = "next"
    ACTION_PREV = "prev"
    ACTION_SKIP = "skip"
    ACTION_VIEW_DETAILS = "view"

    @classmethod
    def get_group_selection_keyboard(cls, groups: List[dict], page: int = 0, per_page: int = 5) -> InlineKeyboardMarkup:
        """Keyboard for selecting a group when adding expense from private chat."""
        buttons = []
        
        start_idx = page * per_page
        end_idx = start_idx + per_page
        page_groups = groups[start_idx:end_idx]
        
        for group in page_groups:
            buttons.append([
                InlineKeyboardButton(
                    group['name'],
                    callback_data=cls._build_callback_data(cls.ACTION_SELECT, str(group['id']))
                )
            ])
        
        # Pagination
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("<< Previous", callback_data=cls._build_callback_data(cls.ACTION_PREV, str(page - 1)))
            )
        if end_idx < len(groups):
            nav_buttons.append(
                InlineKeyboardButton("Next >>", callback_data=cls._build_callback_data(cls.ACTION_NEXT, str(page + 1)))
            )
        if nav_buttons:
            buttons.append(nav_buttons)
        
        buttons.append([
            InlineKeyboardButton("X Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL))
        ])
        
        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_payer_selection_keyboard(cls, members: List[dict]) -> InlineKeyboardMarkup:
        """Keyboard for selecting who paid."""
        buttons = []
        
        for member in members:
            display_name = member.get('first_name') or member.get('username') or f"User {member.get('user_id')}"
            buttons.append([
                InlineKeyboardButton(
                    display_name,
                    callback_data=cls._build_callback_data(cls.ACTION_SELECT_PAYER, str(member.get('user_id')))
                )
            ])
        
        buttons.append([
            InlineKeyboardButton("<< Back", callback_data=cls._build_callback_data(cls.ACTION_BACK)),
            InlineKeyboardButton("X Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL))
        ])
        
        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_participant_selection_keyboard(
        cls,
        members: List[dict],
        selected_ids: List[int]
    ) -> InlineKeyboardMarkup:
        """Keyboard for multi-selecting participants with checkmarks."""
        buttons = []
        
        for member in members:
            user_id = member.get('user_id')
            display_name = member.get('first_name') or member.get('username') or f"User {user_id}"
            
            # Add checkmark if selected
            prefix = "✓ " if user_id in selected_ids else ""
            
            buttons.append([
                InlineKeyboardButton(
                    f"{prefix}{display_name}",
                    callback_data=cls._build_callback_data(cls.ACTION_TOGGLE_PARTICIPANT, str(user_id))
                )
            ])
        
        # Done button (only if at least one selected)
        action_buttons = []
        if selected_ids:
            action_buttons.append(
                InlineKeyboardButton(
                    f"Done ({len(selected_ids)} selected)",
                    callback_data=cls._build_callback_data(cls.ACTION_DONE_PARTICIPANTS)
                )
            )
        
        buttons.append(action_buttons if action_buttons else [
            InlineKeyboardButton("Select at least 1 participant", callback_data="noop")
        ])
        
        buttons.append([
            InlineKeyboardButton("<< Back", callback_data=cls._build_callback_data(cls.ACTION_BACK)),
            InlineKeyboardButton("X Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL))
        ])
        
        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_split_type_keyboard(cls) -> InlineKeyboardMarkup:
        """Keyboard for selecting split type."""
        buttons = [
            [InlineKeyboardButton(
                "Split Equally",
                callback_data=cls._build_callback_data(cls.ACTION_SELECT_SPLIT, ExpenseSplitType.EQUAL.value)
            )],
            [InlineKeyboardButton(
                "Exact Amounts",
                callback_data=cls._build_callback_data(cls.ACTION_SELECT_SPLIT, ExpenseSplitType.EXACT.value)
            )],
            [InlineKeyboardButton(
                "By Percentage",
                callback_data=cls._build_callback_data(cls.ACTION_SELECT_SPLIT, ExpenseSplitType.PERCENTAGE.value)
            )],
            [InlineKeyboardButton(
                "Custom Shares",
                callback_data=cls._build_callback_data(cls.ACTION_SELECT_SPLIT, ExpenseSplitType.CUSTOM.value)
            )],
            [
                InlineKeyboardButton("<< Back", callback_data=cls._build_callback_data(cls.ACTION_BACK)),
                InlineKeyboardButton("X Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL))
            ]
        ]
        
        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_confirmation_keyboard(cls) -> InlineKeyboardMarkup:
        """Keyboard for confirming expense creation."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✓ Confirm", callback_data=cls._build_callback_data(cls.ACTION_CONFIRM))],
            [InlineKeyboardButton("<< Back", callback_data=cls._build_callback_data(cls.ACTION_BACK))],
            [InlineKeyboardButton("X Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL))]
        ])

    @classmethod
    def get_navigation_keyboard(
        cls,
        current_field: str,
        is_first: bool = False,
        show_skip: bool = False
    ) -> InlineKeyboardMarkup:
        """Navigation keyboard for text input fields."""
        buttons = []
        
        if not is_first:
            buttons.append([
                InlineKeyboardButton("<< Back", callback_data=cls._build_callback_data(cls.ACTION_BACK, current_field))
            ])
        
        bottom_row = []
        if show_skip:
            bottom_row.append(
                InlineKeyboardButton(">> Skip", callback_data=cls._build_callback_data(cls.ACTION_SKIP, current_field))
            )
        bottom_row.append(
            InlineKeyboardButton("X Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL))
        )
        buttons.append(bottom_row)
        
        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_expense_list_keyboard(cls, expenses: List[dict], page: int = 0, per_page: int = 5) -> InlineKeyboardMarkup:
        """Keyboard for listing expenses."""
        buttons = []
        
        start_idx = page * per_page
        end_idx = start_idx + per_page
        page_expenses = expenses[start_idx:end_idx]
        
        for expense in page_expenses:
            desc = expense.get('description', 'No description')[:25]
            amount = expense.get('amount', 0)
            currency = expense.get('currency', 'SGD')
            
            buttons.append([
                InlineKeyboardButton(
                    f"{desc} - {currency} {amount}",
                    callback_data=cls._build_callback_data(cls.ACTION_VIEW_DETAILS, str(expense['id']))
                )
            ])
        
        # Pagination
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("<< Previous", callback_data=cls._build_callback_data(cls.ACTION_PREV, str(page - 1)))
            )
        if end_idx < len(expenses):
            nav_buttons.append(
                InlineKeyboardButton("Next >>", callback_data=cls._build_callback_data(cls.ACTION_NEXT, str(page + 1)))
            )
        if nav_buttons:
            buttons.append(nav_buttons)
        
        buttons.append([
            InlineKeyboardButton("X Close", callback_data=cls._build_callback_data(cls.ACTION_CANCEL))
        ])
        
        return InlineKeyboardMarkup(buttons)

    @classmethod
    def _build_callback_data(cls, action: str, data: Optional[str] = None) -> str:
        """Build callback data string."""
        if data:
            return f"{cls.PREFIX}{action}:{data}"
        return f"{cls.PREFIX}{action}"

    @classmethod
    def extract_callback_info(cls, callback_data: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract action and data from callback data."""
        if not callback_data or not callback_data.startswith(cls.PREFIX):
            return None, None
        
        data_str = callback_data[len(cls.PREFIX):]
        
        if ':' in data_str:
            action, data = data_str.split(':', 1)
            return action, data
        return data_str, None
