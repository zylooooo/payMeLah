from typing import List, Optional, Tuple
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import BOT_NAME
from models import GroupMemberRole


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
    ACTION_MEMBER = "member"
    ACTION_MAKE_OWNER = "make_owner"
    ACTION_INVITE = "invite"

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
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"{group['name']}",
                        callback_data=cls._build_callback_data(cls.ACTION_SELECT, str(group["id"])),
                    )
                ]
            )

        # Pagination buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    "<< Previous",
                    callback_data=cls._build_callback_data(cls.ACTION_PREV, str(page - 1)),
                )
            )
        if end_idx < len(groups):
            nav_buttons.append(
                InlineKeyboardButton(
                    "Next >>",
                    callback_data=cls._build_callback_data(cls.ACTION_NEXT, str(page + 1)),
                )
            )
        if nav_buttons:
            buttons.append(nav_buttons)

        # View archived groups (private chat only)
        if show_archived_button:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "📦 Archived Groups",
                        callback_data=cls._build_callback_data(cls.ACTION_VIEW_ARCHIVED),
                    )
                ]
            )

        # Cancel button
        buttons.append(
            [
                InlineKeyboardButton(
                    "X Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
                )
            ]
        )

        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_group_actions_keyboard(
        cls,
        group_id: int,
        user_role: Optional[GroupMemberRole] = None,
        simplify_debts: bool = True,
        is_archived: bool = False,
        member_count: int = 0,
    ) -> InlineKeyboardMarkup:
        """
        Generate keyboard for group actions based on user's role.

        Args:
            group_id: The group ID.
            user_role: The requesting user's role in this group.
            simplify_debts: Current group simplify_debts setting (shown on toggle button).
            is_archived: Whether the group is currently archived.
            member_count: Shown on the Members button.
        """
        buttons = []

        # Members (all roles) — single entry point for view/invite/roles/remove
        buttons.append(
            [
                InlineKeyboardButton(
                    f"👥 Members ({member_count})",
                    callback_data=cls._build_callback_data(cls.ACTION_VIEW_MEMBERS, f"{group_id}:0"),
                )
            ]
        )

        # Admin/owner: debt simplification toggle
        if user_role in [GroupMemberRole.OWNER, GroupMemberRole.ADMIN]:
            simplify_label = (
                "Group Default: Simplified ✓" if simplify_debts else "Group Default: Raw Debts"
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        simplify_label,
                        callback_data=cls._build_callback_data(
                            cls.ACTION_TOGGLE_SIMPLIFY, str(group_id)
                        ),
                    )
                ]
            )

        # Owner only: archive/delete group
        if user_role == GroupMemberRole.OWNER:
            if is_archived:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            "Unarchive Group",
                            callback_data=cls._build_callback_data(
                                cls.ACTION_UNARCHIVE, str(group_id)
                            ),
                        )
                    ]
                )
            else:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            "Archive Trip",
                            callback_data=cls._build_callback_data(
                                cls.ACTION_ARCHIVE, str(group_id)
                            ),
                        )
                    ]
                )
            buttons.append(
                [
                    InlineKeyboardButton(
                        "Delete Group",
                        callback_data=cls._build_callback_data(cls.ACTION_DELETE, str(group_id)),
                    )
                ]
            )

        # Non-owner: leave group
        if user_role != GroupMemberRole.OWNER:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "Leave Group",
                        callback_data=cls._build_callback_data(cls.ACTION_LEAVE, str(group_id)),
                    )
                ]
            )

        buttons.append(
            [
                InlineKeyboardButton(
                    "<< Back", callback_data=cls._build_callback_data(cls.ACTION_BACK_TO_LIST)
                ),
                InlineKeyboardButton(
                    "X Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
                ),
            ]
        )

        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_confirm_keyboard(cls, action: str, group_id: int) -> InlineKeyboardMarkup:
        """Generate confirmation keyboard for destructive actions."""
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Confirm",
                        callback_data=cls._build_callback_data(
                            cls.ACTION_CONFIRM, f"{action}:{group_id}"
                        ),
                    ),
                    InlineKeyboardButton(
                        "Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
                    ),
                ]
            ]
        )

    @classmethod
    def get_join_group_keyboard(cls, group_id: int) -> InlineKeyboardMarkup:
        """Generate keyboard for joining a group via deeplink."""
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("Join Group", url=cls.join_link(group_id))]]
        )

    @classmethod
    def get_group_info_keyboard(cls, group_id: int, is_member: bool) -> InlineKeyboardMarkup:
        """Generate keyboard for group info view (used in group chat context)."""
        buttons = []

        if not is_member:
            buttons.append([InlineKeyboardButton("Join Group", url=cls.join_link(group_id))])

        # Back button
        buttons.append(
            [
                InlineKeyboardButton(
                    "<< Back to List",
                    callback_data=cls._build_callback_data(cls.ACTION_BACK_TO_LIST),
                )
            ]
        )

        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_navigation_keyboard(
        cls, current_field: str, is_first: bool = False, show_skip: bool = False
    ) -> InlineKeyboardMarkup:
        """Generate navigation keyboard for field input during conversation."""
        buttons = []

        # Back button (not shown on first field)
        if not is_first:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "<< Back",
                        callback_data=cls._build_callback_data(cls.ACTION_BACK, current_field),
                    )
                ]
            )

        # Skip button (only for optional fields) and Cancel button
        bottom_row = []
        if show_skip:
            bottom_row.append(
                InlineKeyboardButton(
                    ">> Skip",
                    callback_data=cls._build_callback_data(cls.ACTION_SKIP, current_field),
                )
            )
        bottom_row.append(
            InlineKeyboardButton(
                "X Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
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

        data_str = callback_data[len(cls.PREFIX) :]

        if ":" in data_str:
            action, data = data_str.split(":", 1)
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
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Simplified ✓ (Recommended)",
                        callback_data=cls._build_callback_data(cls.ACTION_SIMPLIFY_ON),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Raw Debts", callback_data=cls._build_callback_data(cls.ACTION_SIMPLIFY_OFF)
                    )
                ],
                [
                    InlineKeyboardButton(
                        "<< Back",
                        callback_data=cls._build_callback_data(cls.ACTION_BACK, "simplify_debts"),
                    ),
                    InlineKeyboardButton(
                        "X Cancel", callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
                    ),
                ],
            ]
        )

    @classmethod
    def get_delete_confirmation_keyboard(cls, group_id: int) -> InlineKeyboardMarkup:
        """Generate confirmation keyboard for deleting a group."""
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Yes, Delete",
                        callback_data=cls._build_callback_data(
                            cls.ACTION_CONFIRM, f"delete:{group_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "<< Back",
                        callback_data=cls._build_callback_data(cls.ACTION_SELECT, str(group_id)),
                    )
                ],
            ]
        )

    @classmethod
    def get_leave_confirmation_keyboard(cls, group_id: int) -> InlineKeyboardMarkup:
        """Generate confirmation keyboard for leaving a group."""
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Yes, Leave",
                        callback_data=cls._build_callback_data(
                            cls.ACTION_CONFIRM, f"leave:{group_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "<< Back",
                        callback_data=cls._build_callback_data(cls.ACTION_SELECT, str(group_id)),
                    )
                ],
            ]
        )

    @staticmethod
    def member_actions(viewer_role, target_role) -> List[str]:
        """
        Which actions the viewer may take on a target member.
        Owner: change role, make owner, remove. Admin: remove plain members only.
        Nobody can act on the owner.
        """
        if target_role == GroupMemberRole.OWNER:
            return []
        if viewer_role == GroupMemberRole.OWNER:
            return ["role", "owner", "remove"]
        if viewer_role == GroupMemberRole.ADMIN and target_role == GroupMemberRole.MEMBER:
            return ["remove"]
        return []

    @classmethod
    def get_members_keyboard(
        cls,
        group_id: int,
        members: List[dict],
        viewer_id: int,
        viewer_role: GroupMemberRole,
        page: int = 0,
        total_pages: int = 1,
    ) -> InlineKeyboardMarkup:
        """
        Members screen for one page: a button per member the viewer can manage
        (two per row), Prev/Next when there is more than one page, then Invite and Back.
        `members` is already the current page's slice.
        """
        member_buttons = [
            InlineKeyboardButton(
                m.get("first_name") or m.get("username") or f"User {m['user_id']}",
                callback_data=cls._build_callback_data(
                    cls.ACTION_MEMBER, f"{group_id}:{m['user_id']}"
                ),
            )
            for m in members
            if m["user_id"] != viewer_id and cls.member_actions(viewer_role, m.get("role"))
        ]
        buttons = [member_buttons[i : i + 2] for i in range(0, len(member_buttons), 2)]
        nav = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    "<< Prev",
                    callback_data=cls._build_callback_data(cls.ACTION_VIEW_MEMBERS, f"{group_id}:{page - 1}"),
                )
            )
        if page < total_pages - 1:
            nav.append(
                InlineKeyboardButton(
                    "Next >>",
                    callback_data=cls._build_callback_data(cls.ACTION_VIEW_MEMBERS, f"{group_id}:{page + 1}"),
                )
            )
        if nav:
            buttons.append(nav)
        buttons.append(
            [
                InlineKeyboardButton(
                    "➕ Invite Members",
                    callback_data=cls._build_callback_data(cls.ACTION_INVITE, str(group_id)),
                )
            ]
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    "<< Back",
                    callback_data=cls._build_callback_data(cls.ACTION_SELECT, str(group_id)),
                )
            ]
        )
        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_member_actions_keyboard(
        cls, group_id: int, target: dict, viewer_role: GroupMemberRole
    ) -> InlineKeyboardMarkup:
        """Person screen: the actions the viewer may take on one member."""
        uid = target["user_id"]
        actions = cls.member_actions(viewer_role, target.get("role"))
        buttons = []
        if "role" in actions:
            if target.get("role") == GroupMemberRole.ADMIN:
                label, new_role = "Make Member", "member"
            else:
                label, new_role = "Make Admin", "admin"
            buttons.append(
                [
                    InlineKeyboardButton(
                        label,
                        callback_data=cls._build_callback_data(
                            cls.ACTION_PROMOTE, f"{group_id}:{uid}:{new_role}"
                        ),
                    )
                ]
            )
        if "owner" in actions:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "Make Owner",
                        callback_data=cls._build_callback_data(
                            cls.ACTION_MAKE_OWNER, f"{group_id}:{uid}"
                        ),
                    )
                ]
            )
        if "remove" in actions:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "Remove from Group",
                        callback_data=cls._build_callback_data(
                            cls.ACTION_REMOVE_MEMBER, f"{group_id}:{uid}"
                        ),
                    )
                ]
            )
        buttons.append([cls._back_to_members_button(group_id)])
        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_member_confirm_keyboard(
        cls, action: str, group_id: int, user_id: int, confirm_label: str
    ) -> InlineKeyboardMarkup:
        """Confirm a destructive member action; Back returns to the person screen."""
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        confirm_label,
                        callback_data=cls._build_callback_data(
                            cls.ACTION_CONFIRM, f"{action}:{group_id}:{user_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "<< Back",
                        callback_data=cls._build_callback_data(
                            cls.ACTION_MEMBER, f"{group_id}:{user_id}"
                        ),
                    )
                ],
            ]
        )

    @classmethod
    def get_back_to_group_keyboard(cls, group_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "<< Back",
                        callback_data=cls._build_callback_data(cls.ACTION_SELECT, str(group_id)),
                    )
                ]
            ]
        )

    @classmethod
    def get_back_to_members_keyboard(cls, group_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[cls._back_to_members_button(group_id)]])

    @classmethod
    def get_invite_keyboard(cls, group_id: int, group_name: str) -> InlineKeyboardMarkup:
        """Invite screen: Telegram's native share sheet for the join link, plus Back."""
        share_url = (
            "https://t.me/share/url?url="
            + quote(cls.join_link(group_id), safe="")
            + "&text="
            + quote(f"Join {group_name} on PayMeLah to split bills with us!", safe="")
        )
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📤 Share Invite Link", url=share_url)],
                [cls._back_to_members_button(group_id)],
            ]
        )

    @classmethod
    def join_link(cls, group_id: int) -> str:
        return f"https://t.me/{BOT_NAME}?start=join_group_{group_id}"

    @classmethod
    def _back_to_members_button(cls, group_id: int) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            "<< Members",
            callback_data=cls._build_callback_data(cls.ACTION_VIEW_MEMBERS, str(group_id)),
        )
