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
    ACTION_TOGGLE_SIMPLIFY = "toggle_simplify"
    ACTION_MANAGE_ROLES = "manage_roles"
    ACTION_PROMOTE = "promote"
    ACTION_NEXT = "next"
    ACTION_PREV = "prev"
    ACTION_SKIP = "skip"
    ACTION_VIEW_MEMBERS = "view_members"
    ACTION_SIMPLIFY_ON = "simplify_on"
    ACTION_SIMPLIFY_OFF = "simplify_off"
    ACTION_ARCHIVE = "archive"
    ACTION_UNARCHIVE = "unarchive"
    ACTION_VIEW_ARCHIVED = "view_archived"

    @classmethod
    def get_group_list_keyboard(
        cls,
        groups: List[dict],
        page: int = 0,
        per_page: int = 5,
        show_archived_button: bool = False,
    ) -> InlineKeyboardMarkup:
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

        # View archived groups (private chat only)
        if show_archived_button:
            buttons.append([
                InlineKeyboardButton(
                    "📦 Archived Groups",
                    callback_data=cls._build_callback_data(cls.ACTION_VIEW_ARCHIVED)
                )
            ])

        # Cancel button
        buttons.append([
            InlineKeyboardButton("X Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL))
        ])

        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_group_actions_keyboard(
        cls,
        group_id: int,
        user_role: Optional[GroupMemberRole] = None,
        simplify_debts: bool = True,
        is_archived: bool = False,
    ) -> InlineKeyboardMarkup:
        """
        Generate keyboard for group actions based on user's role.

        Args:
            group_id: The group ID.
            user_role: The requesting user's role in this group.
            simplify_debts: Current group simplify_debts setting (shown on toggle button).
            is_archived: Whether the group is currently archived.
        """
        buttons = []

        # View members (all roles)
        buttons.append([
            InlineKeyboardButton(
                "View Members",
                callback_data=cls._build_callback_data(cls.ACTION_VIEW_MEMBERS, str(group_id))
            )
        ])

        # Admin/owner: remove member + debt simplification toggle
        if user_role in [GroupMemberRole.OWNER, GroupMemberRole.ADMIN]:
            buttons.append([
                InlineKeyboardButton(
                    "Remove Member",
                    callback_data=cls._build_callback_data(cls.ACTION_REMOVE_MEMBER, str(group_id))
                )
            ])
            # Toggle group-wide default for debt simplification
            simplify_label = "Group Default: Simplified ✓" if simplify_debts else "Group Default: Raw Debts"
            buttons.append([
                InlineKeyboardButton(
                    simplify_label,
                    callback_data=cls._build_callback_data(cls.ACTION_TOGGLE_SIMPLIFY, str(group_id))
                )
            ])

        # Owner only: manage roles + archive/delete group
        if user_role == GroupMemberRole.OWNER:
            buttons.append([
                InlineKeyboardButton(
                    "Manage Roles",
                    callback_data=cls._build_callback_data(cls.ACTION_MANAGE_ROLES, str(group_id))
                )
            ])
            if is_archived:
                buttons.append([
                    InlineKeyboardButton(
                        "Unarchive Group",
                        callback_data=cls._build_callback_data(cls.ACTION_UNARCHIVE, str(group_id))
                    )
                ])
            else:
                buttons.append([
                    InlineKeyboardButton(
                        "Archive Trip",
                        callback_data=cls._build_callback_data(cls.ACTION_ARCHIVE, str(group_id))
                    )
                ])
            buttons.append([
                InlineKeyboardButton(
                    "Delete Group",
                    callback_data=cls._build_callback_data(cls.ACTION_DELETE, str(group_id))
                )
            ])

        # Non-owner: leave group
        if user_role != GroupMemberRole.OWNER:
            buttons.append([
                InlineKeyboardButton(
                    "Leave Group",
                    callback_data=cls._build_callback_data(cls.ACTION_LEAVE, str(group_id))
                )
            ])

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
    def get_simplify_debts_keyboard(cls) -> InlineKeyboardMarkup:
        """Button-selection keyboard for the simplify_debts step during group creation."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "Simplified ✓ (Recommended)",
                    callback_data=cls._build_callback_data(cls.ACTION_SIMPLIFY_ON)
                )
            ],
            [
                InlineKeyboardButton(
                    "Raw Debts",
                    callback_data=cls._build_callback_data(cls.ACTION_SIMPLIFY_OFF)
                )
            ],
            [
                InlineKeyboardButton(
                    "<< Back",
                    callback_data=cls._build_callback_data(cls.ACTION_BACK, "simplify_debts")
                ),
                InlineKeyboardButton(
                    "X Cancel",
                    callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
                )
            ]
        ])

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

    @classmethod
    def get_manage_roles_keyboard(cls, group_id: int, members: List[dict]) -> InlineKeyboardMarkup:
        """
        Generate keyboard for managing member roles (owner only).
        Each non-owner member gets a button showing their current role and the action to take.
        Clicking promotes members to admin or demotes admins back to member.
        """
        buttons = []

        role_order = {'owner': 0, 'admin': 1, 'member': 2}
        sorted_members = sorted(members, key=lambda m: role_order.get(m.get('role', 'member'), 2))

        for member in sorted_members:
            member_role = member.get('role', 'member')
            user_id = member.get('user_id')

            # Owner row is shown as read-only info, not a button
            if member_role == 'owner':
                continue

            display_name = member.get('first_name') or member.get('username') or f"User {user_id}"

            if member_role == 'admin':
                # Demote admin → member
                button_text = f"⬇ Demote {display_name} (Admin → Member)"
                new_role = "member"
            else:
                # Promote member → admin
                button_text = f"⬆ Promote {display_name} (Member → Admin)"
                new_role = "admin"

            buttons.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=cls._build_callback_data(
                        cls.ACTION_PROMOTE, f"{group_id}:{user_id}:{new_role}"
                    )
                )
            ])

        if not buttons:
            # No members to manage (only owner in group)
            buttons.append([
                InlineKeyboardButton(
                    "No other members",
                    callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "<< Back to Group",
                callback_data=cls._build_callback_data(cls.ACTION_SELECT, str(group_id))
            )
        ])

        return InlineKeyboardMarkup(buttons)
