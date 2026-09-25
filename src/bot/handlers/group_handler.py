import logging
from decimal import Decimal
from typing import List

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.keyboards import GroupKeyboard
from bot.utils import ERROR_MSG, get_display_name, h, rate_limit, validate_chat_type
from infrastructure import get_db
from models import GroupMemberRole
from services import BalanceService, GroupService
from shared import (
    GroupMemberNotFoundException,
    GroupNotFoundException,
    OutstandingBalanceException,
    UnauthorizedActionException,
)

logger = logging.getLogger(__name__)


@rate_limit
@validate_chat_type("private", "group", "supergroup")
async def groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /groups command handler.
    - If the command is used in a private chat, it will show all the groups that the user is a member of.
    - If the command is used in a group chat, it will show all the groups that is associated with the group chat.
    """
    chat_type = update.effective_chat.type
    telegram_user = update.effective_user
    if not telegram_user:
        logger.warning("Received /groups command without telegram user information")
        return

    if chat_type == "private":
        logger.info("Showing list of groups that user is a member of in a private chat.")
        try:
            async with get_db() as db:
                groups = await GroupService.get_all_groups_by_user_id(db, telegram_user.id)
                # Case where user is not a member of any groups
                if not groups:
                    await update.message.reply_text(
                        "You are not a member of any groups yet.\n"
                        "You can create a new group by adding me into a new group chat and invite other members to join the group.\n"
                    )
                    return

            # Store groups in user context for pagination
            context.user_data["user_groups"] = groups
            context.user_data["groups_page"] = 0
            context.user_data["groups_archived_view"] = False

            message = _format_groups_list_message(groups, page=0)
            keyboard = GroupKeyboard.get_group_list_keyboard(
                groups, page=0, show_archived_button=True
            )

            await update.message.reply_text(message, parse_mode="HTML", reply_markup=keyboard)
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while listing groups for user {telegram_user.id}: {e}",
                exc_info=True,
            )
            await update.message.reply_text(ERROR_MSG)
    elif chat_type in ["group", "supergroup"]:
        telegram_chat_id = update.effective_chat.id

        if not telegram_chat_id:
            logger.warning("Received /groups command without telegram chat ID")
            return

        logger.info(f"Showing expense groups for Telegram chat ID: {telegram_chat_id}")

        try:
            async with get_db() as db:
                groups = await GroupService.get_group_by_chat_id(db, telegram_chat_id)

                if not groups:
                    await update.message.reply_text(
                        "There are no groups associated with this group chat yet.\n"
                        "Anyone can create a new group by using the /newgroup command.\n\n"
                        "<i>Do ensure that all intended members are added to this group chat first before creating a new expense group.</i>",
                        parse_mode="HTML",
                    )
                    return

                # Store in chat_data for pagination
                context.chat_data["chat_groups"] = groups
                context.chat_data["chat_groups_page"] = 0

                message = _format_groups_list_message(
                    groups,
                    page=0,
                    header="Expense Groups in this Chat",
                    footer="Select a group to view details and join.",
                )
                keyboard = GroupKeyboard.get_group_list_keyboard(groups, page=0)

                sent = await update.message.reply_text(
                    message, parse_mode="HTML", reply_markup=keyboard
                )
                context.chat_data[f"kbd_owner_{sent.message_id}"] = telegram_user.id
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while listing groups for chat {telegram_chat_id}: {e}",
                exc_info=True,
            )
            await update.message.reply_text(ERROR_MSG)


def _format_groups_list_message(
    groups: List[dict],
    page: int = 0,
    per_page: int = 5,
    header: str = "Your Groups",
    footer: str = None,
) -> str:
    """Helper function to format the groups list message for pagination."""
    start_index = page * per_page
    end_index = start_index + per_page
    page_groups = groups[start_index:end_index]
    total_groups = len(groups)

    if total_groups == 0:
        return "No groups found."

    message = f"<b>{h(header)}: {total_groups}</b>\n\n"

    for idx, group in enumerate(page_groups, start=start_index + 1):
        description = group.get("description") or "No description"
        if len(description) > 50:
            description = description[:50] + "..."

        message += (
            f"<b>{idx}. {h(group['name'])}</b>\n"
            f"   {h(description)}\n"
            f"   Currency: {h(group['default_currency'])}\n\n"
        )

    if total_groups > per_page:
        message += f"<i>Page {page + 1} of {(total_groups + per_page - 1) // per_page}</i>\n"

    if footer:
        message += f"\n<i>{footer}</i>"

    return message


async def handle_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries from group keyboard (selection, pagination, etc.)"""
    query = update.callback_query

    telegram_user = update.effective_user
    if not telegram_user:
        logger.warning("Received group callback query without telegram user information")
        await query.answer("Session expired. Please try again.", show_alert=True)
        return

    # Determine chat context
    chat_type = update.effective_chat.type if update.effective_chat else "private"
    is_group_chat = chat_type in ["group", "supergroup"]

    # In group chats, only the user who triggered the command can interact with the keyboard
    if is_group_chat:
        owner_id = context.chat_data.get(f"kbd_owner_{query.message.message_id}")
        if owner_id is not None and owner_id != telegram_user.id:
            await query.answer("This is not your interaction.", show_alert=True)
            return

    action, data = GroupKeyboard.extract_callback_info(query.data)

    # Cancel is always safe - answer and close
    if action == GroupKeyboard.ACTION_CANCEL:
        await query.answer()
        await query.edit_message_text("Cancelled.")
        return

    # For pagination, validate context data exists before answering
    if action in [GroupKeyboard.ACTION_NEXT, GroupKeyboard.ACTION_PREV]:
        groups = (
            context.chat_data.get("chat_groups", [])
            if is_group_chat
            else context.user_data.get("user_groups", [])
        )
        if not groups:
            await query.answer("This list has expired.", show_alert=True)
            await query.edit_message_text("Session expired. Please use /groups again.")
            return

    # For back to list in group chat, validate context exists
    if action == GroupKeyboard.ACTION_BACK_TO_LIST and is_group_chat:
        groups = context.chat_data.get("chat_groups", [])
        if not groups:
            await query.answer("This list has expired.", show_alert=True)
            await query.edit_message_text("Session expired. Please use /groups again.")
            return

    # Validation passed, acknowledge the callback
    await query.answer()

    # Back to groups list
    if action == GroupKeyboard.ACTION_BACK_TO_LIST:
        await _handle_back_to_list(query, context, telegram_user.id, is_group_chat)
        return

    if action == GroupKeyboard.ACTION_SELECT:
        # User selected a group - show group details
        if not data:
            await query.edit_message_text("Invalid group selection.")
            return

        try:
            group_id = int(data)
            await _show_group_details(query, context, group_id, telegram_user.id, is_group_chat)
        except ValueError:
            await query.edit_message_text("Invalid Group ID.")
        except Exception as e:
            logger.error(f"Error showing group details: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return

    if action in [GroupKeyboard.ACTION_NEXT, GroupKeyboard.ACTION_PREV]:
        # Handle pagination - context already validated above
        try:
            page = int(data) if data else 0

            if is_group_chat:
                groups = context.chat_data.get("chat_groups", [])
                message = _format_groups_list_message(
                    groups,
                    page=page,
                    header="Expense Groups in this Chat",
                    footer="Select a group to view details and join.",
                )
                context.chat_data["chat_groups_page"] = page
            else:
                groups = context.user_data.get("user_groups", [])
                message = _format_groups_list_message(groups, page=page)
                context.user_data["groups_page"] = page

            keyboard = GroupKeyboard.get_group_list_keyboard(
                groups,
                page=page,
                show_archived_button=not is_group_chat
                and not context.user_data.get("groups_archived_view"),
            )

            await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Error handling pagination: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return

    # Members screen and member actions
    member_screens = {
        GroupKeyboard.ACTION_VIEW_MEMBERS: _show_group_members,
        GroupKeyboard.ACTION_MEMBER: _show_member_details,
        GroupKeyboard.ACTION_REMOVE_MEMBER: _show_remove_confirmation,
        GroupKeyboard.ACTION_MAKE_OWNER: _show_make_owner_confirmation,
        GroupKeyboard.ACTION_PROMOTE: _execute_role_change,
    }
    if action in member_screens:
        try:
            await member_screens[action](query, context, data, telegram_user.id)
        except Exception as e:
            logger.error(f"Error handling member action {action}: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return

    if action in (
        GroupKeyboard.ACTION_INVITE,
        GroupKeyboard.ACTION_DELETE,
        GroupKeyboard.ACTION_LEAVE,
    ):
        show = {
            GroupKeyboard.ACTION_INVITE: _show_invite,
            GroupKeyboard.ACTION_DELETE: _show_delete_confirmation,
            GroupKeyboard.ACTION_LEAVE: _show_leave_confirmation,
        }[action]
        try:
            await show(query, context, int(data), telegram_user.id)
        except (TypeError, ValueError):
            await query.edit_message_text("Invalid group.")
        except Exception as e:
            logger.error(f"Error handling group action {action}: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return

    # Toggle group debt simplification default (admin/owner only)
    if action == GroupKeyboard.ACTION_TOGGLE_SIMPLIFY:
        try:
            group_id = int(data) if data else None
            if not group_id:
                await query.edit_message_text("Invalid group.")
                return
            await _handle_toggle_simplify(query, context, group_id, telegram_user.id)
        except Exception as e:
            logger.error(f"Error toggling simplify setting: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return

    # Handle confirmations (delete, leave, remove)
    if action == GroupKeyboard.ACTION_CONFIRM:
        await _handle_confirmation(query, context, data, telegram_user.id)
        return

    # Archive / Unarchive
    if action in [GroupKeyboard.ACTION_ARCHIVE, GroupKeyboard.ACTION_UNARCHIVE]:
        try:
            group_id = int(data) if data else None
            if not group_id:
                await query.edit_message_text("Invalid group.")
                return
            await _handle_archive_toggle(
                query,
                context,
                group_id,
                telegram_user.id,
                archive=(action == GroupKeyboard.ACTION_ARCHIVE),
            )
        except Exception as e:
            logger.error(f"Error toggling archive: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return

    # View archived groups
    if action == GroupKeyboard.ACTION_VIEW_ARCHIVED:
        await _handle_view_archived(query, context, telegram_user.id)
        return


async def _show_group_details(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    user_id: int,
    is_group_chat: bool = False,
) -> None:
    """
    Show detailed information about a selected group.

    Args:
        query: The callback query
        context: Bot context
        group_id: The group ID to show details for
        user_id: The requesting user's ID
        is_group_chat: If True, shows join option instead of management actions
    """
    try:
        async with get_db() as db:
            group = await GroupService.get_group_by_id(db, group_id)
            if not group:
                await query.edit_message_text(
                    "<b>Group not found.</b>\n\nThe group may have been deleted.", parse_mode="HTML"
                )
                return

            # Check if user is a member
            is_member = await GroupService.is_member(db, group_id, user_id)

            # Get group members count
            members = await GroupService.get_group_members(db, group_id)

            if is_group_chat:
                # Group chat context: show info with join option
                message = _format_group_details(group, members, is_member=is_member)
                keyboard = GroupKeyboard.get_group_info_keyboard(group_id, is_member)
            else:
                # Private chat context: require membership for management
                if not is_member:
                    await query.edit_message_text(
                        "<b>Access denied.</b>\n\nYou are not a member of this group.",
                        parse_mode="HTML",
                    )
                    return

                # Get user's role in the group
                member_role = await GroupService.get_member_role(db, group_id, user_id)
                message = _format_group_details(group, members, member_role=member_role)
                keyboard = GroupKeyboard.get_group_actions_keyboard(
                    group_id,
                    member_role,
                    simplify_debts=group.get("simplify_debts", True),
                    is_archived=group.get("is_archived", False),
                    member_count=len(members),
                )

            await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error showing group details: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


def _format_group_details(
    group: dict, members: list, member_role: GroupMemberRole = None, is_member: bool = None
) -> str:
    """
    Format group details message.

    Args:
        group: Group data dict
        members: List of group members
        member_role: User's role (for private chat context with management options)
        is_member: Whether user is a member (for group chat context with join option)
    """
    description = group.get("description") or "No description"

    simplify_display = "Simplified ✓" if group.get("simplify_debts", True) else "Raw Debts"
    is_archived = group.get("is_archived", False)
    archived_tag = " [ARCHIVED]" if is_archived else ""
    message = (
        f"<b>{h(group['name'])}{archived_tag}</b>\n\n"
        f"<b>Description:</b> {h(description)}\n"
        f"<b>Default Currency:</b> {h(group['default_currency'])}\n"
        f"<b>Members:</b> {len(members)}\n"
        f"<b>Debt View Default:</b> {simplify_display}\n"
    )

    # Show role if in private chat (member management context)
    if member_role is not None:
        role_display = member_role.value.title()
        message += f"<b>Your Role:</b> {role_display}\n"

    # Show join hint if in group chat and not a member
    if is_member is not None and not is_member:
        message += "\n\n<i>Click 'Join Group' to start splitting bills!</i>"
    elif is_member is not None and is_member:
        message += "\n\n<i>You are already a member of this group.</i>"

    return message


async def _handle_back_to_list(
    query, context: ContextTypes.DEFAULT_TYPE, user_id: int, is_group_chat: bool = False
) -> None:
    """Handle back to groups list navigation for both private and group chat contexts."""
    if is_group_chat:
        # Group chat context - use chat_data
        groups = context.chat_data.get("chat_groups", [])
        page = context.chat_data.get("chat_groups_page", 0)

        if not groups:
            await query.edit_message_text("Groups list expired. Please use /groups again.")
            return

        message = _format_groups_list_message(
            groups,
            page=page,
            header="Expense Groups in this Chat",
            footer="Select a group to view details and join.",
        )
        keyboard = GroupKeyboard.get_group_list_keyboard(groups, page=page)
    else:
        # Private chat context - always re-fetch so archive/unarchive/leave show up
        try:
            async with get_db() as db:
                groups = await GroupService.get_all_groups_by_user_id(db, user_id)
        except Exception as e:
            logger.error(f"Error fetching groups: {e}", exc_info=True)
            await query.edit_message_text("Failed to load groups. Please use /groups again.")
            return

        if not groups:
            await query.edit_message_text("You are not a member of any groups yet.")
            return

        last_page = (len(groups) - 1) // 5
        page = min(context.user_data.get("groups_page", 0), last_page)
        context.user_data["user_groups"] = groups
        context.user_data["groups_page"] = page
        context.user_data["groups_archived_view"] = False

        message = _format_groups_list_message(groups, page=page)
        keyboard = GroupKeyboard.get_group_list_keyboard(
            groups, page=page, show_archived_button=True
        )

    await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)


async def _show_group_members(
    query, context: ContextTypes.DEFAULT_TYPE, data: str, user_id: int
) -> None:
    """
    Members screen, one page at a time: role + balance per person, manageable members as buttons.
    data is "group_id:page", or just "group_id" to return to the page last viewed for that group
    (used by the "<< Members" back buttons so you land where you left off).
    """
    group_id = _parse_ids(data, 1)
    if not group_id:
        await query.edit_message_text("Invalid group.")
        return
    group_id = group_id[0]
    explicit_page = _parse_ids(data, 2)
    last_group, last_page = context.user_data.get("members_page", (None, 0))
    if explicit_page:
        page = explicit_page[1]
    else:
        page = last_page if last_group == group_id else 0

    try:
        async with get_db() as db:
            viewer_role = await GroupService.get_member_role(db, group_id, user_id)
            if not viewer_role:
                await query.edit_message_text("You are not a member of this group.")
                return

            group = await GroupService.get_group_by_id(db, group_id)
            if not group:
                await query.edit_message_text("Group not found.")
                return

            members = await GroupService.get_group_members_with_details(db, group_id)
            balances = await BalanceService.get_group_balances(db, group_id, user_id)

        balance_by_id = {m["user_id"]: m["balance"] for m in balances["members"]}
        members = sorted(members, key=lambda m: _ROLE_ORDER.get(m.get("role"), 2))
        total_pages = max(1, -(-len(members) // _MEMBERS_PER_PAGE))
        page = min(max(page, 0), total_pages - 1)  # list may have shrunk since the button was drawn
        context.user_data["members_page"] = (group_id, page)
        page_members = members[page * _MEMBERS_PER_PAGE : (page + 1) * _MEMBERS_PER_PAGE]
        keyboard = GroupKeyboard.get_members_keyboard(
            group_id, page_members, user_id, viewer_role, page, total_pages
        )

        lines = []
        for m in page_members:
            you = " (you)" if m["user_id"] == user_id else ""
            balance = _balance_text(balance_by_id.get(m["user_id"], 0), balances["currency"])
            lines.append(
                f"{_ROLE_ICON.get(m.get('role'), '')}{get_display_name(m)}{you} · {balance}"
            )

        can_manage = any(
            m["user_id"] != user_id and GroupKeyboard.member_actions(viewer_role, m.get("role"))
            for m in page_members
        )
        page_note = f"\n<i>Page {page + 1} of {total_pages}</i>" if total_pages > 1 else ""
        message = (
            f"<b>👥 Members of {h(group['name'])}</b> ({len(members)})\n\n"
            + "\n".join(lines)
            + "\n\n👑 Owner  ⭐ Admin"
            + page_note
            + ("\n<i>Tap a name below to manage them.</i>" if can_manage else "")
        )
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error showing group members: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


_ROLE_ORDER = {"owner": 0, "admin": 1, "member": 2}
_ROLE_ICON = {"owner": "👑 ", "admin": "⭐ "}
_MEMBERS_PER_PAGE = 8


def _balance_text(balance, currency: str, you: bool = False) -> str:
    """'settled up' / 'owes SGD 12.50' / 'is owed SGD 4.00' ('owe' / 'are owed' when you=True)."""
    if abs(balance) < Decimal("0.01"):
        return "settled up"
    if balance < 0:
        verb = "owe" if you else "owes"
    else:
        verb = "are owed" if you else "is owed"
    return f"{verb} {h(currency)} {abs(balance):,.2f}"


def _parse_ids(data: str, count: int):
    """Parse 'a:b[:...]' callback data into `count` ints, or None if malformed."""
    try:
        parts = [int(p) for p in (data or "").split(":")[:count]]
    except ValueError:
        return None
    return parts if len(parts) == count else None


async def _get_member(db, group_id: int, user_id: int):
    """Return a member-with-details dict, or None if not a member."""
    members = await GroupService.get_group_members_with_details(db, group_id)
    return next((m for m in members if m["user_id"] == user_id), None)


async def _notify(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, text: str
) -> None:
    """DM the user; fall back to the group chat if they never started the bot."""
    for target in (user_id, chat_id):
        try:
            await context.bot.send_message(chat_id=target, text=text, parse_mode="HTML")
            return
        except Exception as e:
            logger.warning(f"Could not notify {target}: {e}")


def _blocked_message(name: str, balance, currency: str, action: str) -> str:
    """Explain why someone with a balance can't leave / be removed. name="You" for self."""
    return (
        f"<b>Can't {action} yet</b>\n\n"
        f"{name} {_balance_text(balance, currency, you=name == 'You')} in this group. "
        "Balances must be settled before anyone leaves the group.\n\n"
        "Use /balances → Settle Up, then try again."
    )


async def _show_member_details(
    query, context: ContextTypes.DEFAULT_TYPE, data: str, user_id: int
) -> None:
    """Person screen: one member's role, balance and the actions the viewer may take."""
    ids = _parse_ids(data, 2)
    if not ids:
        await query.edit_message_text("Invalid member.")
        return
    group_id, target_id = ids

    async with get_db() as db:
        viewer_role = await GroupService.get_member_role(db, group_id, user_id)
        if not viewer_role:
            await query.edit_message_text("You are not a member of this group.")
            return
        target = await _get_member(db, group_id, target_id)
        if not target:
            await query.edit_message_text(
                "This person is no longer in the group.",
                reply_markup=GroupKeyboard.get_back_to_members_keyboard(group_id),
            )
            return
        balance, currency = await GroupService.get_member_balance(db, group_id, target_id)

    message = (
        f"<b>{get_display_name(target)}</b>\n\n"
        f"<b>Role:</b> {target['role'].title()}\n"
        f"<b>Balance:</b> {_balance_text(balance, currency)}"
    )
    keyboard = GroupKeyboard.get_member_actions_keyboard(group_id, target, viewer_role)
    await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)


async def _show_remove_confirmation(
    query, context: ContextTypes.DEFAULT_TYPE, data: str, user_id: int
) -> None:
    """Confirm removal, or explain why it's blocked (unsettled balance / no permission)."""
    ids = _parse_ids(data, 2)
    if not ids:
        await query.edit_message_text("Invalid member.")
        return
    group_id, target_id = ids

    async with get_db() as db:
        viewer_role = await GroupService.get_member_role(db, group_id, user_id)
        target = await _get_member(db, group_id, target_id)
        group = await GroupService.get_group_by_id(db, group_id)
        if (
            not target
            or not group
            or "remove" not in GroupKeyboard.member_actions(viewer_role, target["role"])
        ):
            await query.edit_message_text(
                "You can't remove this member.",
                reply_markup=GroupKeyboard.get_back_to_members_keyboard(group_id),
            )
            return
        balance, currency = await GroupService.get_member_balance(db, group_id, target_id)

    name = get_display_name(target)
    if abs(balance) >= Decimal("0.01"):
        await query.edit_message_text(
            _blocked_message(name, balance, currency, f"remove {name}"),
            parse_mode="HTML",
            reply_markup=GroupKeyboard.get_back_to_members_keyboard(group_id),
        )
        return

    message = (
        f"<b>Remove {name} from {h(group['name'])}?</b>\n\n"
        "They'll lose access to this group's expenses and balances. "
        "Past expenses stay as they are.\n\n"
        "<i>They can rejoin later with the invite link.</i>"
    )
    keyboard = GroupKeyboard.get_member_confirm_keyboard(
        "remove", group_id, target_id, "Yes, Remove"
    )
    await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)


async def _show_make_owner_confirmation(
    query, context: ContextTypes.DEFAULT_TYPE, data: str, user_id: int
) -> None:
    """Confirm handing ownership to another member."""
    ids = _parse_ids(data, 2)
    if not ids:
        await query.edit_message_text("Invalid member.")
        return
    group_id, target_id = ids

    async with get_db() as db:
        viewer_role = await GroupService.get_member_role(db, group_id, user_id)
        target = await _get_member(db, group_id, target_id)
        group = await GroupService.get_group_by_id(db, group_id)

    if (
        not target
        or not group
        or "owner" not in GroupKeyboard.member_actions(viewer_role, target["role"])
    ):
        await query.edit_message_text(
            "Only the group owner can transfer ownership.",
            reply_markup=GroupKeyboard.get_back_to_members_keyboard(group_id),
        )
        return

    name = get_display_name(target)
    message = (
        f"<b>Make {name} the owner of {h(group['name'])}?</b>\n\n"
        f"{name} will be able to manage roles, archive and delete the group. "
        "You'll become an Admin.\n\n"
        f"<i>Only {name} can hand ownership back.</i>"
    )
    keyboard = GroupKeyboard.get_member_confirm_keyboard(
        "owner", group_id, target_id, "Yes, Make Owner"
    )
    await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)


async def _show_invite(
    query, context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int
) -> None:
    """Invite screen: tap-to-copy join link + Telegram share sheet."""
    async with get_db() as db:
        if not await GroupService.is_member(db, group_id, user_id):
            await query.edit_message_text("You are not a member of this group.")
            return
        group = await GroupService.get_group_by_id(db, group_id)

    message = (
        f"<b>Invite people to {h(group['name'])}</b>\n\n"
        "Share this link. Anyone in the group's Telegram chat can tap it to join:\n\n"
        f"<code>{h(GroupKeyboard.join_link(group_id))}</code>\n\n"
        "<i>Not in the Telegram chat yet? Add them to the chat first.</i>"
    )
    keyboard = GroupKeyboard.get_invite_keyboard(group_id, group["name"])
    await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)


async def _show_delete_confirmation(
    query, context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int
) -> None:
    """Show delete confirmation dialog."""
    try:
        async with get_db() as db:
            # Verify user is owner
            role = await GroupService.get_member_role(db, group_id, user_id)
            if role != GroupMemberRole.OWNER:
                await query.edit_message_text("Only the group owner can delete the group.")
                return

            group = await GroupService.get_group_by_id(db, group_id)
            if not group:
                await query.edit_message_text("Group not found.")
                return

            message = (
                f"<b>Delete Group: {h(group['name'])}</b>\n\n"
                "Are you sure you want to delete this group?\n\n"
                "<b>This action cannot be undone!</b>\n"
                "- All members will be removed\n"
                "- All expenses in this group will be deleted\n"
                "- All payment records will be lost"
            )

            await query.edit_message_text(
                message,
                parse_mode="HTML",
                reply_markup=GroupKeyboard.get_delete_confirmation_keyboard(group_id),
            )
    except Exception as e:
        logger.error(f"Error showing delete confirmation: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


async def _show_leave_confirmation(
    query, context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int
) -> None:
    """Show leave confirmation dialog, or explain why leaving is blocked."""
    try:
        async with get_db() as db:
            group = await GroupService.get_group_by_id(db, group_id)
            if not group:
                await query.edit_message_text("Group not found.")
                return
            balance, currency = await GroupService.get_member_balance(db, group_id, user_id)

        if abs(balance) >= Decimal("0.01"):
            await query.edit_message_text(
                _blocked_message("You", balance, currency, "leave"),
                parse_mode="HTML",
                reply_markup=GroupKeyboard.get_back_to_group_keyboard(group_id),
            )
            return

        message = (
            f"<b>Leave Group: {h(group['name'])}</b>\n\n"
            "Are you sure you want to leave this group?\n\n"
            "- You will no longer see expenses in this group\n"
            "- You can rejoin later if you're still in the Telegram group chat"
        )

        await query.edit_message_text(
            message,
            parse_mode="HTML",
            reply_markup=GroupKeyboard.get_leave_confirmation_keyboard(group_id),
        )
    except Exception as e:
        logger.error(f"Error showing leave confirmation: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


async def _handle_confirmation(
    query, context: ContextTypes.DEFAULT_TYPE, data: str, user_id: int
) -> None:
    """Handle confirmation actions (delete, leave, remove, owner)."""
    action_type, _, rest = (data or "").partition(":")
    handlers = {
        "delete": (1, lambda gid: _execute_delete_group(query, context, gid, user_id)),
        "leave": (1, lambda gid: _execute_leave_group(query, context, gid, user_id)),
        "remove": (2, lambda gid, uid: _execute_remove_member(query, context, gid, uid, user_id)),
        "owner": (
            2,
            lambda gid, uid: _execute_transfer_ownership(query, context, gid, uid, user_id),
        ),
    }
    if action_type not in handlers:
        await query.edit_message_text("Invalid confirmation data.")
        return

    count, run = handlers[action_type]
    ids = _parse_ids(rest, count)
    if not ids:
        await query.edit_message_text("Invalid confirmation data.")
        return

    try:
        await run(*ids)
    except Exception as e:
        logger.error(f"Error handling confirmation: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


async def _execute_leave_group(
    query, context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int
) -> None:
    """Execute leaving a group."""
    try:
        async with get_db() as db:
            group = await GroupService.get_group_by_id(db, group_id)
            group_name = h(group["name"]) if group else "the group"

            await GroupService.leave_group(db, group_id, user_id)

            # Remove from cached groups
            groups = context.user_data.get("user_groups", [])
            context.user_data["user_groups"] = [g for g in groups if g.get("id") != group_id]

            await query.edit_message_text(
                f"<b>Left Group</b>\n\n"
                f"You have left <b>{group_name}</b>.\n"
                "Use /groups to view your remaining groups.",
                parse_mode="HTML",
            )
    except OutstandingBalanceException as e:
        await query.edit_message_text(
            _blocked_message("You", e.amount, e.currency, "leave"),
            parse_mode="HTML",
            reply_markup=GroupKeyboard.get_back_to_group_keyboard(group_id),
        )
    except UnauthorizedActionException as e:
        await query.edit_message_text(h(str(e)))
    except GroupMemberNotFoundException:
        await query.edit_message_text("You are not a member of this group.")


async def _execute_remove_member(
    query, context: ContextTypes.DEFAULT_TYPE, group_id: int, target_user_id: int, user_id: int
) -> None:
    """Execute member removal and let the removed person know."""
    back = GroupKeyboard.get_back_to_members_keyboard(group_id)
    try:
        async with get_db() as db:
            group = await GroupService.get_group_by_id(db, group_id)
            target = await _get_member(db, group_id, target_user_id)
            target_name = get_display_name(target) if target else h(f"User {target_user_id}")

            await GroupService.remove_member(db, group_id, target_user_id, user_id)
    except OutstandingBalanceException as e:
        await query.edit_message_text(
            _blocked_message(target_name, e.amount, e.currency, f"remove {target_name}"),
            parse_mode="HTML",
            reply_markup=back,
        )
        return
    except (UnauthorizedActionException, GroupMemberNotFoundException) as e:
        await query.edit_message_text(h(str(e)), reply_markup=back)
        return

    group_name = h(group["name"])
    await query.edit_message_text(
        f"<b>{target_name}</b> has been removed from <b>{group_name}</b>.",
        parse_mode="HTML",
        reply_markup=back,
    )
    remover = get_display_name(
        {
            "first_name": query.from_user.first_name,
            "username": query.from_user.username,
            "id": user_id,
        }
    )
    await _notify(
        context,
        target_user_id,
        group["telegram_chat_id"],
        f"{target_name}, you were removed from the expense group <b>{group_name}</b> by {remover}.",
    )


async def _execute_transfer_ownership(
    query, context: ContextTypes.DEFAULT_TYPE, group_id: int, target_user_id: int, user_id: int
) -> None:
    """Make another member the owner; the current owner becomes an admin."""
    back = GroupKeyboard.get_back_to_members_keyboard(group_id)
    try:
        async with get_db() as db:
            group = await GroupService.get_group_by_id(db, group_id)
            target = await _get_member(db, group_id, target_user_id)
            await GroupService.transfer_ownership(db, group_id, target_user_id, user_id)
    except (UnauthorizedActionException, GroupMemberNotFoundException) as e:
        await query.edit_message_text(h(str(e)), reply_markup=back)
        return

    target_name = get_display_name(target)
    group_name = h(group["name"])
    await query.edit_message_text(
        f"<b>{target_name}</b> is now the owner of <b>{group_name}</b>.\n\nYou're now an Admin.",
        parse_mode="HTML",
        reply_markup=back,
    )
    previous = get_display_name(
        {
            "first_name": query.from_user.first_name,
            "username": query.from_user.username,
            "id": user_id,
        }
    )
    await _notify(
        context,
        target_user_id,
        group["telegram_chat_id"],
        f"{target_name}, {previous} made you the owner of the expense group <b>{group_name}</b>.",
    )


async def _execute_role_change(
    query, context: ContextTypes.DEFAULT_TYPE, data: str, user_id: int
) -> None:
    """Promote/demote a member, then re-render their person screen."""
    ids = _parse_ids(data, 2)
    new_role = {"admin": GroupMemberRole.ADMIN, "member": GroupMemberRole.MEMBER}.get(
        (data or "").split(":")[-1]
    )
    if not ids or not new_role:
        await query.edit_message_text("Invalid role change data.")
        return
    group_id, target_user_id = ids

    try:
        async with get_db() as db:
            await GroupService.update_member_role(db, group_id, target_user_id, new_role, user_id)
    except (UnauthorizedActionException, GroupMemberNotFoundException) as e:
        await query.edit_message_text(
            h(str(e)), reply_markup=GroupKeyboard.get_back_to_members_keyboard(group_id)
        )
        return

    await _show_member_details(query, context, f"{group_id}:{target_user_id}", user_id)


async def _execute_delete_group(
    query, context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int
) -> None:
    """Execute group deletion."""
    try:
        async with get_db() as db:
            await GroupService.delete_group(db, group_id, user_id)

            # Remove from cached groups
            groups = context.user_data.get("user_groups", [])
            context.user_data["user_groups"] = [g for g in groups if g.get("id") != group_id]

            await query.edit_message_text(
                "<b>Group Deleted</b>\n\n"
                "The group has been permanently deleted.\n"
                "Use /groups to view your remaining groups.",
                parse_mode="HTML",
            )
    except UnauthorizedActionException as e:
        await query.edit_message_text(str(e))
    except GroupNotFoundException:
        await query.edit_message_text("Group not found.")


async def _handle_toggle_simplify(
    query, context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int
) -> None:
    """
    Toggle the group's default debt simplification setting.
    Flips the current value and re-renders the group details view.
    Only admins and owners can do this (enforced by GroupService).
    """
    try:
        async with get_db() as db:
            group = await GroupService.get_group_by_id(db, group_id)
            if not group:
                await query.edit_message_text("Group not found.")
                return

            new_value = not group.get("simplify_debts", True)
            updated_group = await GroupService.update_simplify_setting(
                db, group_id, new_value, user_id
            )

            # Re-render group details with the updated setting
            members = await GroupService.get_group_members(db, group_id)
            member_role = await GroupService.get_member_role(db, group_id, user_id)

        message = _format_group_details(updated_group, members, member_role=member_role)
        keyboard = GroupKeyboard.get_group_actions_keyboard(
            group_id,
            member_role,
            simplify_debts=updated_group.get("simplify_debts", True),
            is_archived=updated_group.get("is_archived", False),
            member_count=len(members),
        )
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    except UnauthorizedActionException:
        await query.answer("Only admins and owners can change group settings.", show_alert=True)
    except GroupNotFoundException:
        await query.edit_message_text("Group not found.")


async def _handle_archive_toggle(
    query, context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int, archive: bool
) -> None:
    """Archive or unarchive a group."""
    try:
        async with get_db() as db:
            if archive:
                updated_group = await GroupService.archive_group(db, group_id, user_id)
                verb = "archived"
            else:
                updated_group = await GroupService.unarchive_group(db, group_id, user_id)
                verb = "unarchived"

            members = await GroupService.get_group_members(db, group_id)
            member_role = await GroupService.get_member_role(db, group_id, user_id)

        message = _format_group_details(updated_group, members, member_role=member_role)
        keyboard = GroupKeyboard.get_group_actions_keyboard(
            group_id,
            member_role,
            simplify_debts=updated_group.get("simplify_debts", True),
            is_archived=updated_group.get("is_archived", False),
            member_count=len(members),
        )
        await query.answer(f"Group {verb}.", show_alert=False)
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    except UnauthorizedActionException as e:
        await query.answer(str(e), show_alert=True)
    except GroupNotFoundException:
        await query.edit_message_text("Group not found.")


async def _handle_view_archived(query, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Show the user's archived groups."""
    try:
        async with get_db() as db:
            all_groups = await GroupService.get_all_groups_by_user_id(
                db, user_id, include_archived=True
            )

        archived = [g for g in all_groups if g.get("is_archived")]

        if not archived:
            await query.edit_message_text(
                "<b>Archived Groups</b>\n\nYou have no archived groups.",
                parse_mode="HTML",
                reply_markup=GroupKeyboard.get_group_list_keyboard([], show_archived_button=False),
            )
            return

        context.user_data["user_groups"] = archived
        context.user_data["groups_page"] = 0
        context.user_data["groups_archived_view"] = True

        message = _format_groups_list_message(
            archived,
            page=0,
            header="Archived Groups",
            footer="Select a group to view or unarchive.",
        )
        keyboard = GroupKeyboard.get_group_list_keyboard(
            archived, page=0, show_archived_button=False
        )
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error viewing archived groups: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


def create_group_callback_handler() -> CallbackQueryHandler:
    """
    Factory function to create the group callback query handler.
    Encapsulates the handler and its pattern for cleaner registration in bot.py.
    """
    return CallbackQueryHandler(handle_group_callback, pattern=f"^{GroupKeyboard.PREFIX}")
