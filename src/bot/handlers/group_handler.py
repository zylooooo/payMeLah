from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler
from typing import List
from infrastructure import get_db
from services import GroupService
from bot.keyboards import GroupKeyboard
from bot.utils import validate_chat_type
from models import GroupMemberRole
from shared import (
    GroupNotFoundException,
    GroupMemberNotFoundException,
    UnauthorizedActionException
)
import logging


logger = logging.getLogger(__name__)

ERROR_MSG: str = "An unexpected error has occurred. Please try again later."

@validate_chat_type("private")
async def groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/groups command handler to show the groups a user is a member of."""
    telegram_user = update.effective_user
    if not telegram_user:
        logger.warning("Received /groups command without telegram user information")
        return
    
    try:
        async with get_db() as db:
            groups = await GroupService.get_all_groups_by_user_id(db, telegram_user.id)
            # Case where user is not a member of any groups
            if not groups or len(groups) == 0:
                await update.message.reply_text(
                    "You are not a member of any groups yet.\n"
                    "You can create a new group by adding me into a new group chat and invite other members to join the group.\n"
                )
                return
            
        # Store groups in user context for pagination
        context.user_data['user_groups'] = groups
        context.user_data['groups_page'] = 0

        message = _format_groups_list_message(groups, page=0)
        keyboard = GroupKeyboard.get_group_list_keyboard(groups, page=0)

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


def _format_groups_list_message(groups: List[int], page: int = 0, per_page: int = 5) -> str:
    """Helper function to format the groups list message for pagination."""
    start_index = page * per_page
    end_index = start_index + per_page
    page_groups = groups[start_index:end_index]
    total_groups = len(groups)

    if total_groups == 0:
        return "You are not a member of any groups yet."
    
    message = f"<b>Your Groups: {total_groups}</b>\n\n"

    for idx, group in enumerate(page_groups, start=start_index + 1):
        description = group.get("description", "No description")
        if description:
            description = description[:50] + "..." if len(description) > 50 else description
        else:
            description = "No description"
        
        message += (
            f"<b>{idx}. {group['name']}</b>\n"
            f"  {description}\n"
            f"  Currency: {group['default_currency']}\n\n"
        )
    
    if total_groups > per_page:
        message += f"<i>Page {page + 1} of {(total_groups + per_page - 1) // per_page}</i>"
    
    return message

async def handle_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries from group keyboard (selection, pagination, etc.)"""
    query = update.callback_query
    await query.answer()

    telegram_user = update.effective_user
    if not telegram_user:
        logger.warning("Received group callback query without telegram user information")
        return
    
    action, data = GroupKeyboard.extract_callback_info(query.data)

    if action == GroupKeyboard.ACTION_CANCEL:
        await query.edit_message_text("Cancelled.")
        return
    
    # Back to groups list
    if action == GroupKeyboard.ACTION_BACK_TO_LIST:
        await _handle_back_to_list(query, context, telegram_user.id)
        return
    
    if action == GroupKeyboard.ACTION_SELECT:
        # User selected a group - show group details
        if not data:
            await query.edit_message_text("Invalid group selection.")
            return
    
        try:
            group_id = int(data)
            await _show_group_details(query, context, group_id, telegram_user.id)
        except ValueError:
            await query.edit_message_text("Invalid Group ID.")
        except Exception as e:
            logger.error(f"Error showing group details: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return
    
    if action in [GroupKeyboard.ACTION_NEXT, GroupKeyboard.ACTION_PREV]:
        # Handle pagination
        try:
            page = int(data) if data else 0
            groups = context.user_data.get('user_groups', [])

            if not groups:
                await query.edit_message_text("Groups list expired. Please use /groups again to see the list that you are a member of.")
                return
            
            message = _format_groups_list_message(groups, page=page)
            keyboard = GroupKeyboard.get_group_list_keyboard(groups, page=page)

            await query.edit_message_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            context.user_data['groups_page'] = page
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

    # Handle confirmations (delete, leave, remove)
    if action == GroupKeyboard.ACTION_CONFIRM:
        await _handle_confirmation(query, context, data, telegram_user.id)
        return

async def _show_group_details(query, context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int) -> None:
    """Show detailed information about a selected group."""
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
            if not is_member:
                await query.edit_message_text(
                    "<b>Access denied.</b>\n\n"
                    "You are not a member of this group.",
                    parse_mode="HTML"
                )
                return
            
            # Get user's role in the group
            member_role = await GroupService.get_member_role(db, group_id, user_id)
            
            # Get group members count
            members = await GroupService.get_group_members(db, group_id)
            
            # Format group details message
            message = _format_group_details(group, members, member_role)
            keyboard = GroupKeyboard.get_group_actions_keyboard(group_id, member_role)
            
            await query.edit_message_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
    except Exception as e:
        logger.error(f"Error showing group details: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)

def _format_group_details(group: dict, members: list, user_role: GroupMemberRole = None) -> str:
    """Format group details message."""
    description = group.get('description') or "No description"
    role_display = user_role.value.title() if user_role else "Member"
    
    message = (
        f"<b>{group['name']}</b>\n\n"
        f"<b>Description:</b> {description}\n"
        f"<b>Default Currency:</b> {group['default_currency']}\n"
        f"<b>Members:</b> {len(members)}\n"
        f"<b>Your Role:</b> {role_display}\n\n"
        f"<i>Group ID: {group['id']}</i>"
    )
    
    return message


async def _handle_back_to_list(query, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle back to groups list navigation."""
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
    message = f"<b>Members of {group['name']}</b>\n\n"
    
    # Sort by role (owner first, then admin, then member)
    role_order = {'owner': 0, 'admin': 1, 'member': 2}
    sorted_members = sorted(members, key=lambda m: role_order.get(m.get('role', 'member'), 2))
    
    for member in sorted_members:
        role = member.get('role', 'member')
        
        # Get display name
        display_name = member.get('first_name') or member.get('username') or f"User {member.get('user_id')}"
        if member.get('last_name'):
            display_name += f" {member.get('last_name')}"
        
        message += f"<b>{display_name}</b> - {role.title()}\n"
    
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
                f"<b>Delete Group: {group['name']}</b>\n\n"
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
                f"<b>Leave Group: {group['name']}</b>\n\n"
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
                f"<b>Remove Member from {group['name']}</b>\n\n"
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
            group_id = int(parts[1])
            await _execute_delete_group(query, context, group_id, user_id)
        elif action_type == "leave":
            group_id = int(parts[1])
            await _execute_leave_group(query, context, group_id, user_id)
        elif action_type == "remove":
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
            target_name = "Unknown user"
            if target_info:
                target_name = target_info.get('first_name') or target_info.get('username') or f"User {target_user_id}"
            
            await GroupService.remove_member(db, group_id, target_user_id, user_id)
            
            await query.edit_message_text(
                f"<b>Member Removed</b>\n\n"
                f"<b>{target_name}</b> has been removed from <b>{group['name']}</b>.",
                parse_mode="HTML"
            )
    except UnauthorizedActionException as e:
        await query.edit_message_text(str(e))
    except GroupMemberNotFoundException as e:
        await query.edit_message_text(str(e))


def create_group_callback_handler() -> CallbackQueryHandler:
    """
    Factory function to create the group callback query handler.
    Encapsulates the handler and its pattern for cleaner registration in bot.py.
    """
    return CallbackQueryHandler(
        handle_group_callback,
        pattern=f"^{GroupKeyboard.PREFIX}"
    )
