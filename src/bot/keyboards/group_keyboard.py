from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import Optional, Tuple, List
from models import GroupMemberRole
from config import BOT_NAME


class GroupKeyboard:
    """Class to create inline keyboards for group management operations."""

    PREFIX = "group_"

    # Actions
    ACTION_SELECT = "select"
    ACTION_CANCEL = "cancel"
    ACTION_CONFIRM = "confirm"
    ACTION_DELETE = "delete"
    ACTION_REMOVE_MEMBER = "remove_member"
    ACTION_LEAVE = "leave"
    ACTION_BACK = "back"
    ACTION_BACK_TO_LIST = "back_list"
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

        # Owner and admin actions - Remove Member
        if user_role in [GroupMemberRole.OWNER, GroupMemberRole.ADMIN]:
            buttons.append([
                InlineKeyboardButton(
                    "Remove Member",
                    callback_data=cls._build_callback_data(cls.ACTION_REMOVE_MEMBER, str(group_id))
                )
            ])
        
        # Owner only actions - Delete Group
        if user_role == GroupMemberRole.OWNER:
            buttons.append([
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
        
        # Back and Cancel buttons
        buttons.append([
            InlineKeyboardButton("<< Back", callback_data=cls._build_callback_data(cls.ACTION_BACK_TO_LIST)),
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
    def get_group_info_keyboard(cls, group_id: int, is_member: bool) -> InlineKeyboardMarkup:
        """Generate keyboard for group info view (used in group chat context)."""
        buttons = []
        
        if not is_member:
            buttons.append([
                InlineKeyboardButton(
                    "Join Group",
                    url=f"https://t.me/{BOT_NAME}?start=join_group_{group_id}"
                )
            ])
        
        # Back button
        buttons.append([
            InlineKeyboardButton("<< Back to List", callback_data=cls._build_callback_data(cls.ACTION_BACK_TO_LIST))
        ])
        
        return InlineKeyboardMarkup(buttons)

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

    @classmethod
    def get_members_list_keyboard(cls, group_id: int) -> InlineKeyboardMarkup:
        """Generate keyboard for members list view."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "<< Back to Group",
                    callback_data=cls._build_callback_data(cls.ACTION_SELECT, str(group_id))
                )
            ],
            [
                InlineKeyboardButton("X Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL))
            ]
        ])

    @classmethod
    def get_delete_confirmation_keyboard(cls, group_id: int) -> InlineKeyboardMarkup:
        """Generate confirmation keyboard for deleting a group."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "Yes, Delete",
                    callback_data=cls._build_callback_data(cls.ACTION_CONFIRM, f"delete:{group_id}")
                )
            ],
            [
                InlineKeyboardButton(
                    "<< Back",
                    callback_data=cls._build_callback_data(cls.ACTION_SELECT, str(group_id))
                )
            ]
        ])

    @classmethod
    def get_leave_confirmation_keyboard(cls, group_id: int) -> InlineKeyboardMarkup:
        """Generate confirmation keyboard for leaving a group."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "Yes, Leave",
                    callback_data=cls._build_callback_data(cls.ACTION_CONFIRM, f"leave:{group_id}")
                )
            ],
            [
                InlineKeyboardButton(
                    "<< Back",
                    callback_data=cls._build_callback_data(cls.ACTION_SELECT, str(group_id))
                )
            ]
        ])

    @classmethod
    def get_remove_member_keyboard(cls, group_id: int, members: List[dict], requesting_user_role: GroupMemberRole) -> InlineKeyboardMarkup:
        """
        Generate keyboard for selecting a member to remove.
        Shows removable members based on requester's role.
        """
        buttons = []
        
        # Sort by role (owner first, then admin, then member)
        role_order = {'owner': 0, 'admin': 1, 'member': 2}
        sorted_members = sorted(members, key=lambda m: role_order.get(m.get('role', 'member'), 2))
        
        for member in sorted_members:
            member_role = member.get('role', 'member')
            user_id = member.get('user_id')
            
            # Skip owner (cannot be removed)
            if member_role == 'owner':
                continue
            
            # Admins can only remove members, not other admins
            if requesting_user_role == GroupMemberRole.ADMIN and member_role == 'admin':
                continue
            
            # Get display name with role indicator
            display_name = member.get('first_name') or member.get('username') or f"User {user_id}"
            role_label = f"[{member_role.title()}]" if member_role == 'admin' else ""
            button_text = f"{display_name} {role_label}".strip()
            
            buttons.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=cls._build_callback_data(cls.ACTION_CONFIRM, f"remove:{group_id}:{user_id}")
                )
            ])
        
        # Back button
        buttons.append([
            InlineKeyboardButton(
                "<< Back",
                callback_data=cls._build_callback_data(cls.ACTION_SELECT, str(group_id))
            )
        ])
        
        return InlineKeyboardMarkup(buttons)
