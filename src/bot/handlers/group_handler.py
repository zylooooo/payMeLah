from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler
from typing import List
from infrastructure import get_db
from services import GroupService
from bot.keyboards import GroupKeyboard
from bot.utils import validate_chat_type, h, rate_limit, ERROR_MSG, get_display_name
from models import GroupMemberRole
from shared import (
    GroupNotFoundException,
    GroupMemberNotFoundException,
    UnauthorizedActionException
)
import logging


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
            context.user_data['user_groups'] = groups
            context.user_data['groups_page'] = 0

            message = _format_groups_list_message(groups, page=0)
            keyboard = GroupKeyboard.get_group_list_keyboard(groups, page=0, show_archived_button=True)

            await update.message.reply_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while listing groups for user {telegram_user.id}: {e}",
                exc_info = True
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
                        parse_mode="HTML"
                    )
                    return
                
                # Store in chat_data for pagination
                context.chat_data['chat_groups'] = groups
                context.chat_data['chat_groups_page'] = 0
                
                message = _format_groups_list_message(
                    groups,
                    page=0,
                    header="Expense Groups in this Chat",
                    footer="Select a group to view details and join."
                )
                keyboard = GroupKeyboard.get_group_list_keyboard(groups, page=0)
                
                sent = await update.message.reply_text(
                    message,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
                context.chat_data[f'kbd_owner_{sent.message_id}'] = telegram_user.id
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while listing groups for chat {telegram_chat_id}: {e}",
                exc_info=True
            )
            await update.message.reply_text(ERROR_MSG)
                



def _format_groups_list_message(
    groups: List[dict],
    page: int = 0,
    per_page: int = 5,
    header: str = "Your Groups",
    footer: str = None
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
        owner_id = context.chat_data.get(f'kbd_owner_{query.message.message_id}')
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
        groups = context.chat_data.get('chat_groups', []) if is_group_chat else context.user_data.get('user_groups', [])
        if not groups:
            await query.answer("This list has expired.", show_alert=True)
            await query.edit_message_text("Session expired. Please use /groups again.")
            return
    
    # For back to list in group chat, validate context exists
    if action == GroupKeyboard.ACTION_BACK_TO_LIST and is_group_chat:
        groups = context.chat_data.get('chat_groups', [])
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
                groups = context.chat_data.get('chat_groups', [])
                message = _format_groups_list_message(
                    groups,
                    page=page,
                    header="Expense Groups in this Chat",
                    footer="Select a group to view details and join."
                )
                context.chat_data['chat_groups_page'] = page
            else:
                groups = context.user_data.get('user_groups', [])
                message = _format_groups_list_message(groups, page=page)
                context.user_data['groups_page'] = page
            
            keyboard = GroupKeyboard.get_group_list_keyboard(groups, page=page)

            await query.edit_message_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Error handling pagination: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return

    # View Members
    if action == GroupKeyboard.ACTION_VIEW_MEMBERS:
        try:
            group_id = int(data) if data else None
            if not group_id:
                await query.edit_message_text("Invalid group.")
                return
            await _show_group_members(query, context, group_id, telegram_user.id)
        except Exception as e:
            logger.error(f"Error viewing members: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return

    # Delete Group
    if action == GroupKeyboard.ACTION_DELETE:
        try:
            group_id = int(data) if data else None
            if not group_id:
                await query.edit_message_text("Invalid group.")
                return
            await _show_delete_confirmation(query, context, group_id, telegram_user.id)
        except Exception as e:
            logger.error(f"Error showing delete confirmation: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return

    # Leave Group
    if action == GroupKeyboard.ACTION_LEAVE:
        try:
            group_id = int(data) if data else None
            if not group_id:
                await query.edit_message_text("Invalid group.")
                return
            await _show_leave_confirmation(query, context, group_id, telegram_user.id)
        except Exception as e:
            logger.error(f"Error showing leave confirmation: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return

    # Remove Member - show member selection
    if action == GroupKeyboard.ACTION_REMOVE_MEMBER:
        try:
            group_id = int(data) if data else None
            if not group_id:
                await query.edit_message_text("Invalid group.")
                return
            await _show_remove_member_selection(query, context, group_id, telegram_user.id)
        except Exception as e:
            logger.error(f"Error showing remove member selection: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return

    # Manage Roles — show role management screen (owner only)
    if action == GroupKeyboard.ACTION_MANAGE_ROLES:
        try:
            group_id = int(data) if data else None
            if not group_id:
                await query.edit_message_text("Invalid group.")
                return
            await _show_manage_roles(query, context, group_id, telegram_user.id)
        except Exception as e:
            logger.error(f"Error showing manage roles: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return

    # Promote / demote a member (owner only)
    if action == GroupKeyboard.ACTION_PROMOTE:
        try:
            await _execute_role_change(query, context, data, telegram_user.id)
        except Exception as e:
            logger.error(f"Error changing member role: {e}", exc_info=True)
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
            await _handle_archive_toggle(query, context, group_id, telegram_user.id, archive=(action == GroupKeyboard.ACTION_ARCHIVE))
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
    is_group_chat: bool = False
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
                    "<b>Group not found.</b>\n\n"
                    "The group may have been deleted.",
                    parse_mode="HTML"
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
                        "<b>Access denied.</b>\n\n"
                        "You are not a member of this group.",
                        parse_mode="HTML"
                    )
                    return
                
                # Get user's role in the group
                member_role = await GroupService.get_member_role(db, group_id, user_id)
                message = _format_group_details(group, members, member_role=member_role)
                keyboard = GroupKeyboard.get_group_actions_keyboard(
                    group_id,
                    member_role,
                    simplify_debts=group.get('simplify_debts', True),
                    is_archived=group.get('is_archived', False),
                )
            
            await query.edit_message_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
    except Exception as e:
        logger.error(f"Error showing group details: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)

def _format_group_details(
    group: dict,
    members: list,
    member_role: GroupMemberRole = None,
    is_member: bool = None
) -> str:
    """
    Format group details message.
    
    Args:
        group: Group data dict
        members: List of group members
        member_role: User's role (for private chat context with management options)
        is_member: Whether user is a member (for group chat context with join option)
    """
    description = group.get('description') or "No description"

    simplify_display = "Simplified ✓" if group.get('simplify_debts', True) else "Raw Debts"
    is_archived = group.get('is_archived', False)
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
    query,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    is_group_chat: bool = False
) -> None:
    """Handle back to groups list navigation for both private and group chat contexts."""
    if is_group_chat:
        # Group chat context - use chat_data
        groups = context.chat_data.get('chat_groups', [])
        page = context.chat_data.get('chat_groups_page', 0)
        
        if not groups:
            await query.edit_message_text("Groups list expired. Please use /groups again.")
            return
        
        message = _format_groups_list_message(
            groups,
            page=page,
            header="Expense Groups in this Chat",
            footer="Select a group to view details and join."
        )
        keyboard = GroupKeyboard.get_group_list_keyboard(groups, page=page)
    else:
        # Private chat context - use user_data
        groups = context.user_data.get('user_groups', [])
        page = context.user_data.get('groups_page', 0)
        
        if not groups:
            # Re-fetch groups if expired
            try:
                async with get_db() as db:
                    groups = await GroupService.get_all_groups_by_user_id(db, user_id)
                    context.user_data['user_groups'] = groups
                    context.user_data['groups_page'] = 0
                    page = 0
            except Exception as e:
                logger.error(f"Error fetching groups: {e}", exc_info=True)
                await query.edit_message_text("Failed to load groups. Please use /groups again.")
                return
        
        if not groups:
            await query.edit_message_text("You are not a member of any groups yet.")
            return
        
        message = _format_groups_list_message(groups, page=page)
        keyboard = GroupKeyboard.get_group_list_keyboard(groups, page=page)
    
    await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)


async def _show_group_members(query, context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int) -> None:
    """Show list of group members."""
    try:
        async with get_db() as db:
            # Verify user is a member
            if not await GroupService.is_member(db, group_id, user_id):
                await query.edit_message_text("You are not a member of this group.")
                return
            
            group = await GroupService.get_group_by_id(db, group_id)
            if not group:
                await query.edit_message_text("Group not found.")
                return
            
            members = await GroupService.get_group_members_with_details(db, group_id)
            
            message = _format_members_list(group, members)
            keyboard = GroupKeyboard.get_members_list_keyboard(group_id)
            
            await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error showing group members: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


def _format_members_list(group: dict, members: list) -> str:
    """Format the members list message."""
    message = f"<b>Members of {h(group['name'])}</b>\n\n"

    # Sort by role (owner first, then admin, then member)
    role_order = {'owner': 0, 'admin': 1, 'member': 2}
    sorted_members = sorted(members, key=lambda m: role_order.get(m.get('role', 'member'), 2))

    for member in sorted_members:
        role = member.get('role', 'member')
        message += f"<b>{get_display_name(member)}</b> - {role.title()}\n"

    message += f"\n<i>Total: {len(members)} member(s)</i>"
    return message


async def _show_delete_confirmation(query, context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int) -> None:
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
                reply_markup=GroupKeyboard.get_delete_confirmation_keyboard(group_id)
            )
    except Exception as e:
        logger.error(f"Error showing delete confirmation: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


async def _show_leave_confirmation(query, context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int) -> None:
    """Show leave confirmation dialog."""
    try:
        async with get_db() as db:
            group = await GroupService.get_group_by_id(db, group_id)
            if not group:
                await query.edit_message_text("Group not found.")
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
                reply_markup=GroupKeyboard.get_leave_confirmation_keyboard(group_id)
            )
    except Exception as e:
        logger.error(f"Error showing leave confirmation: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


async def _show_remove_member_selection(query, context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int) -> None:
    """Show member selection for removal."""
    try:
        async with get_db() as db:
            # Get requester's role
            requester_role = await GroupService.get_member_role(db, group_id, user_id)
            if requester_role not in [GroupMemberRole.OWNER, GroupMemberRole.ADMIN]:
                await query.edit_message_text("Only owners and admins can remove members.")
                return
            
            group = await GroupService.get_group_by_id(db, group_id)
            if not group:
                await query.edit_message_text("Group not found.")
                return
            
            members = await GroupService.get_group_members_with_details(db, group_id)
            
            # Filter out members that cannot be removed (self and owner)
            removable_members = [
                m for m in members 
                if m.get('user_id') != user_id and m.get('role') != 'owner'
            ]
            
            # For admins, also filter out other admins
            if requester_role == GroupMemberRole.ADMIN:
                removable_members = [m for m in removable_members if m.get('role') != 'admin']
            
            if not removable_members:
                await query.edit_message_text(
                    "<b>No members to remove</b>\n\n"
                    "There are no members that you can remove from this group.",
                    parse_mode="HTML",
                    reply_markup=GroupKeyboard.get_members_list_keyboard(group_id)
                )
                return
            
            message = (
                f"<b>Remove Member from {h(group['name'])}</b>\n\n"
                "Select a member to remove from the group:"
            )
            
            await query.edit_message_text(
                message,
                parse_mode="HTML",
                reply_markup=GroupKeyboard.get_remove_member_keyboard(group_id, members, requester_role)
            )
    except Exception as e:
        logger.error(f"Error showing remove member selection: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


async def _handle_confirmation(query, context: ContextTypes.DEFAULT_TYPE, data: str, user_id: int) -> None:
    """Handle confirmation actions (delete, leave, remove)."""
    if not data or ':' not in data:
        await query.edit_message_text("Invalid confirmation data.")
        return
    
    parts = data.split(':')
    action_type = parts[0]

    try:
        if action_type == "delete":
            if len(parts) < 2:
                await query.edit_message_text("Invalid confirmation data.")
                return
            group_id = int(parts[1])
            await _execute_delete_group(query, context, group_id, user_id)
        elif action_type == "leave":
            if len(parts) < 2:
                await query.edit_message_text("Invalid confirmation data.")
                return
            group_id = int(parts[1])
            await _execute_leave_group(query, context, group_id, user_id)
        elif action_type == "remove":
            if len(parts) < 3:
                await query.edit_message_text("Invalid confirmation data.")
                return
            group_id = int(parts[1])
            target_user_id = int(parts[2])
            await _execute_remove_member(query, context, group_id, target_user_id, user_id)
        else:
            await query.edit_message_text("Unknown action.")
    except (ValueError, IndexError):
        await query.edit_message_text("Invalid confirmation data.")
    except Exception as e:
        logger.error(f"Error handling confirmation: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


async def _execute_delete_group(query, context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int) -> None:
    """Execute group deletion."""
    try:
        async with get_db() as db:
            await GroupService.delete_group(db, group_id, user_id)
            
            # Remove from cached groups
            groups = context.user_data.get('user_groups', [])
            context.user_data['user_groups'] = [g for g in groups if g.get('id') != group_id]
            
            await query.edit_message_text(
                "<b>Group Deleted</b>\n\n"
                "The group has been permanently deleted.\n"
                "Use /groups to view your remaining groups.",
                parse_mode="HTML"
            )
    except UnauthorizedActionException as e:
        await query.edit_message_text(str(e))
    except GroupNotFoundException:
        await query.edit_message_text("Group not found.")


async def _execute_leave_group(query, context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int) -> None:
    """Execute leaving a group."""
    try:
        async with get_db() as db:
            group = await GroupService.get_group_by_id(db, group_id)
            group_name = group['name'] if group else "the group"
            
            await GroupService.leave_group(db, group_id, user_id)
            
            # Remove from cached groups
            groups = context.user_data.get('user_groups', [])
            context.user_data['user_groups'] = [g for g in groups if g.get('id') != group_id]
            
            await query.edit_message_text(
                f"<b>Left Group</b>\n\n"
                f"You have left <b>{group_name}</b>.\n"
                "Use /groups to view your remaining groups.",
                parse_mode="HTML"
            )
    except UnauthorizedActionException as e:
        await query.edit_message_text(str(e))
    except GroupMemberNotFoundException:
        await query.edit_message_text("You are not a member of this group.")


async def _execute_remove_member(query, context: ContextTypes.DEFAULT_TYPE, group_id: int, target_user_id: int, user_id: int) -> None:
    """Execute member removal."""
    try:
        async with get_db() as db:
            group = await GroupService.get_group_by_id(db, group_id)
            
            # Get target user info for display
            target_members = await GroupService.get_group_members_with_details(db, group_id)
            target_info = next((m for m in target_members if m.get('user_id') == target_user_id), None)
            target_name = get_display_name(target_info) if target_info else h(f"User {target_user_id}")
            
            await GroupService.remove_member(db, group_id, target_user_id, user_id)
            
            await query.edit_message_text(
                f"<b>Member Removed</b>\n\n"
                f"<b>{h(target_name)}</b> has been removed from <b>{h(group['name'])}</b>.",
                parse_mode="HTML"
            )
    except UnauthorizedActionException as e:
        await query.edit_message_text(str(e))
    except GroupMemberNotFoundException as e:
        await query.edit_message_text(str(e))


async def _show_manage_roles(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    user_id: int
) -> None:
    """Show the role management screen. Owner only."""
    try:
        async with get_db() as db:
            role = await GroupService.get_member_role(db, group_id, user_id)
            if role != GroupMemberRole.OWNER:
                await query.edit_message_text("Only the group owner can manage roles.")
                return

            group = await GroupService.get_group_by_id(db, group_id)
            if not group:
                await query.edit_message_text("Group not found.")
                return

            members = await GroupService.get_group_members_with_details(db, group_id)

        message = (
            f"<b>Manage Roles: {h(group['name'])}</b>\n\n"
            "Promote a member to Admin or demote an Admin back to Member.\n\n"
            "<b>Admin</b> can add expenses and remove members.\n"
            "<b>Member</b> can add expenses only."
        )
        keyboard = GroupKeyboard.get_manage_roles_keyboard(group_id, members)
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error showing manage roles: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


async def _execute_role_change(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    data: str,
    user_id: int
) -> None:
    """Execute a role promotion or demotion."""
    if not data or ':' not in data:
        await query.edit_message_text("Invalid role change data.")
        return

    parts = data.split(':')
    if len(parts) < 3:
        await query.edit_message_text("Invalid role change data.")
        return

    try:
        group_id = int(parts[0])
        target_user_id = int(parts[1])
    except ValueError:
        await query.edit_message_text("Invalid role change data.")
        return
    new_role_str = parts[2]

    role_map = {'admin': GroupMemberRole.ADMIN, 'member': GroupMemberRole.MEMBER}
    new_role = role_map.get(new_role_str)
    if not new_role:
        await query.edit_message_text("Invalid role.")
        return

    try:
        async with get_db() as db:
            await GroupService.update_member_role(db, group_id, target_user_id, new_role, user_id)
            members = await GroupService.get_group_members_with_details(db, group_id)
            group = await GroupService.get_group_by_id(db, group_id)

        action_word = "promoted to Admin" if new_role == GroupMemberRole.ADMIN else "demoted to Member"
        target_info = next((m for m in members if m.get('user_id') == target_user_id), None)
        target_name = get_display_name(target_info) if target_info else h(f"User {target_user_id}")

        await query.answer(f"{target_name} {action_word}.", show_alert=False)

        # Re-render the manage roles screen with updated data
        message = (
            f"<b>Manage Roles: {h(group['name'])}</b>\n\n"
            "Promote a member to Admin or demote an Admin back to Member.\n\n"
            "<b>Admin</b> can add expenses and remove members.\n"
            "<b>Member</b> can add expenses only."
        )
        keyboard = GroupKeyboard.get_manage_roles_keyboard(group_id, members)
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    except UnauthorizedActionException as e:
        await query.answer(str(e), show_alert=True)
    except GroupMemberNotFoundException as e:
        await query.edit_message_text(str(e))


async def _handle_toggle_simplify(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    user_id: int
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

            new_value = not group.get('simplify_debts', True)
            updated_group = await GroupService.update_simplify_setting(
                db, group_id, new_value, user_id
            )

            # Re-render group details with the updated setting
            members = await GroupService.get_group_members(db, group_id)
            member_role = await GroupService.get_member_role(db, group_id, user_id)

        message = _format_group_details(updated_group, members, member_role=member_role)
        keyboard = GroupKeyboard.get_group_actions_keyboard(
            group_id, member_role, simplify_debts=updated_group.get('simplify_debts', True)
        )
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    except UnauthorizedActionException:
        await query.answer("Only admins and owners can change group settings.", show_alert=True)
    except GroupNotFoundException:
        await query.edit_message_text("Group not found.")


async def _handle_archive_toggle(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    user_id: int,
    archive: bool
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
            simplify_debts=updated_group.get('simplify_debts', True),
            is_archived=updated_group.get('is_archived', False),
        )
        await query.answer(f"Group {verb}.", show_alert=False)
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    except UnauthorizedActionException as e:
        await query.answer(str(e), show_alert=True)
    except GroupNotFoundException:
        await query.edit_message_text("Group not found.")


async def _handle_view_archived(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int
) -> None:
    """Show the user's archived groups."""
    try:
        async with get_db() as db:
            all_groups = await GroupService.get_all_groups_by_user_id(db, user_id, include_archived=True)

        archived = [g for g in all_groups if g.get('is_archived')]

        if not archived:
            await query.edit_message_text(
                "<b>Archived Groups</b>\n\nYou have no archived groups.",
                parse_mode="HTML",
                reply_markup=GroupKeyboard.get_group_list_keyboard([], show_archived_button=False)
            )
            return

        context.user_data['user_groups'] = archived
        context.user_data['groups_page'] = 0

        message = _format_groups_list_message(
            archived, page=0,
            header="Archived Groups",
            footer="Select a group to view or unarchive."
        )
        keyboard = GroupKeyboard.get_group_list_keyboard(archived, page=0, show_archived_button=False)
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error viewing archived groups: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


def create_group_callback_handler() -> CallbackQueryHandler:
    """
    Factory function to create the group callback query handler.
    Encapsulates the handler and its pattern for cleaner registration in bot.py.
    """
    return CallbackQueryHandler(
        handle_group_callback,
        pattern=f"^{GroupKeyboard.PREFIX}"
    )
