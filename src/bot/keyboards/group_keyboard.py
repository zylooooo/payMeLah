from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import Optional, Tuple, List
from models import GroupMemberRole
from config import BOT_NAME


class GroupKeyboard:
    """Class to create inline keyboards for group management operations."""

    PREFIX = "group_"

    # Actions
    ACTION_CREATE = "create"
    ACTION_SELECT = "select"
    ACTION_CANCEL = "cancel"
    ACTION_CONFIRM = "confirm"
    ACTION_EDIT = "edit"
    ACTION_DELETE = "delete"
    ACTION_ADD_MEMBER = "add_member"
    ACTION_REMOVE_MEMBER = "remove_member"
    ACTION_LEAVE = "leave"
    ACTION_CHANGE_ROLE = "change_role"
    ACTION_BACK = "back"
    ACTION_NEXT = "next"
    ACTION_PREV = "prev"
    ACTION_SKIP = "skip"
    ACTION_VIEW_MEMBERS = "view_members"

    @classmethod
    def get_group_list_keyboard(cls, groups: List[dict], page: int = 0, per_page: int = 5) -> InlineKeyboardMarkup:
        """Generate keyboard for listing groups with pagination."""
        buttons = []

        start_idx = page * per_page
        end_idx = start_idx + per_page
        page_groups = groups[start_idx:end_idx]

        # Group buttons
        for group in page_groups:
            buttons.append([
                InlineKeyboardButton(
                    f"{group['name']}",
                    callback_data=cls._build_callback_data(cls.ACTION_SELECT, str(group['id']))
                )
            ])
        
        # Pagination buttons
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
        
        # Cancel button
        buttons.append([
            InlineKeyboardButton("X Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL))
        ])

        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_group_actions_keyboard(cls, group_id: int, user_role: Optional[GroupMemberRole] = None) -> InlineKeyboardMarkup:
        """Generate keyboard for group actions based on user's role in the group."""
        buttons = []

        # View members (all can view)
        buttons.append([
            InlineKeyboardButton(
                "View Members",
                callback_data=cls._build_callback_data(cls.ACTION_VIEW_MEMBERS, str(group_id))
            )
        ])

        # Owner and admin actions
        if user_role in [GroupMemberRole.OWNER, GroupMemberRole.ADMIN]:
            buttons.append([
                InlineKeyboardButton(
                    "Add Member",
                    callback_data=cls._build_callback_data(cls.ACTION_ADD_MEMBER, str(group_id))
                ),
                InlineKeyboardButton(
                    "Remove Member",
                    callback_data=cls._build_callback_data(cls.ACTION_REMOVE_MEMBER, str(group_id))
                )
            ])
        
        # Owner only actions
        if user_role == GroupMemberRole.OWNER:
            buttons.append([
                InlineKeyboardButton(
                    "Edit Group",
                    callback_data=cls._build_callback_data(cls.ACTION_EDIT, str(group_id))
                ),
                InlineKeyboardButton(
                    "Delete Group",
                    callback_data=cls._build_callback_data(cls.ACTION_DELETE, str(group_id))
                )
            ])
        
        # Leave group (not owner)
        if user_role != GroupMemberRole.OWNER:
            buttons.append([
                InlineKeyboardButton(
                    "Leave Group",
                    callback_data=cls._build_callback_data(cls.ACTION_LEAVE, str(group_id))
                )
            ])
        
        # Cancel button
        buttons.append([
            InlineKeyboardButton("X Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL))
        ])
    
        return InlineKeyboardMarkup(buttons)
    
    @classmethod
    def get_confirm_keyboard(cls, action: str, group_id: int) -> InlineKeyboardMarkup:
        """Generate confirmation keyboard for destructive actions."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "Confirm",
                    callback_data=cls._build_callback_data(cls.ACTION_CONFIRM, f"{action}:{group_id}")
                ),
                InlineKeyboardButton(
                    "Cancel",
                    callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
                )
            ]
        ])
    
    @classmethod
    def get_role_selection_keyboard(cls, group_id: int, user_id: int) -> InlineKeyboardMarkup:
        """Generate keyboard for selecting member role."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "Member",
                    callback_data=cls._build_callback_data(
                        cls.ACTION_CHANGE_ROLE,
                        f"{group_id}:{user_id}:{GroupMemberRole.MEMBER.value}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "Admin",
                    callback_data=cls._build_callback_data(
                        cls.ACTION_CHANGE_ROLE,
                        f"{group_id}:{user_id}:{GroupMemberRole.ADMIN.value}"
                    )
                )
            ],
            [
                InlineKeyboardButton("Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL))
            ]
        ])
    
    @classmethod
    def get_join_group_keyboard(cls, group_id: int) -> InlineKeyboardMarkup:
        """Generate keyboard for joining a group via deeplink."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "Join Group",
                    url=f"https://t.me/{BOT_NAME}?start=join_group_{group_id}"
                )
            ]
        ])

    @classmethod
    def get_navigation_keyboard(
        cls,
        current_field: str,
        is_first: bool = False,
        show_skip: bool = False
    ) -> InlineKeyboardMarkup:
        """Generate navigation keyboard for field input during conversation."""
        buttons = []

        # Back button (not shown on first field)
        if not is_first:
            buttons.append([
                InlineKeyboardButton(
                    "<< Back",
                    callback_data=cls._build_callback_data(cls.ACTION_BACK, current_field)
                )
            ])

        # Skip button (only for optional fields) and Cancel button
        bottom_row = []
        if show_skip:
            bottom_row.append(
                InlineKeyboardButton(
                    ">> Skip",
                    callback_data=cls._build_callback_data(cls.ACTION_SKIP, current_field)
                )
            )
        bottom_row.append(
            InlineKeyboardButton(
                "X Cancel",
                callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
            )
        )
        buttons.append(bottom_row)

        return InlineKeyboardMarkup(buttons)
    
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
