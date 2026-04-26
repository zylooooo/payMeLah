from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackQueryHandler
from typing import List, Optional
from infrastructure import get_db
from services import ExpenseService, GroupService, UserService
from bot.keyboards import ExpenseKeyboard
from bot.utils import validate_chat_type
from shared import (
    ExpenseNotFoundException,
    UnauthorizedActionException,
    GroupNotFoundException,
    ExpenseNotEditableException
)
from datetime import datetime, date
import logging


logger = logging.getLogger(__name__)

ERROR_MSG: str = "An unexpected error has occurred. Please try again later."
PER_PAGE: int = 5


# ===================================================================================
# Date Formatting Helpers
# ===================================================================================
def _format_date_friendly(date_str: Optional[str]) -> str:
    """
    Format date string to a user-friendly format.
    Returns relative dates for recent entries, otherwise "Jan 20" style format.
    """
    if not date_str:
        return "No date"
    
    try:
        # Parse ISO format date string (YYYY-MM-DD)
        expense_date = datetime.fromisoformat(date_str).date()
        today = date.today()
        
        # Calculate difference
        diff = (today - expense_date).days
        
        if diff == 0:
            return "Today"
        elif diff == 1:
            return "Yesterday"
        elif diff < 7:
            return expense_date.strftime("%A")  # Day name (e.g., "Monday")
        elif expense_date.year == today.year:
            return expense_date.strftime("%b %d")  # "Jan 20"
        else:
            return expense_date.strftime("%b %d, %Y")  # "Jan 20, 2024"
    except (ValueError, TypeError):
        return str(date_str)


def _format_date_full(date_str: Optional[str]) -> str:
    """Format date string to full readable format for detail view."""
    if not date_str:
        return "No date"
    
    try:
        expense_date = datetime.fromisoformat(date_str).date()
        return expense_date.strftime("%B %d, %Y")  # "January 20, 2025"
    except (ValueError, TypeError):
        return str(date_str)


# ===================================================================================
# Helper Functions
# ===================================================================================
def _format_expense_list_item(expense: dict, index: int, payer_name: Optional[str] = None) -> str:
    """
    Format a single expense for the list view.
    Follows Splitwise-style display: Description, Amount, Payer, Date
    """
    description = expense.get('description') or 'No description'
    amount = expense.get('amount', 0)
    currency = expense.get('currency', 'SGD')
    expense_date = expense.get('expense_date', '')
    is_settled = expense.get('is_settled', False)
    
    # Truncate description if too long
    if len(description) > 25:
        description = description[:22] + "..."
    
    # Format the friendly date
    friendly_date = _format_date_friendly(expense_date)
    
    # Settled indicator
    status_icon = "✓" if is_settled else ""
    
    # Build the display - Splitwise style
    # #1 🍕 Dinner at Restaurant
    #    SGD 45.00 • paid by John • Jan 20
    payer_text = f"paid by {payer_name}" if payer_name else ""
    
    line1 = f"<b>#{index}</b> {status_icon} {description}"
    line2_parts = [f"{currency} {amount}"]
    if payer_text:
        line2_parts.append(payer_text)
    line2_parts.append(friendly_date)
    line2 = " • ".join(line2_parts)
    
    return f"{line1}\n   {line2}"


def _format_expense_list_message(
    expenses: List[dict],
    group_name: str,
    payer_names: dict,
    page: int = 0,
    total_count: int = 0
) -> str:
    """
    Format the expense list message.
    
    Args:
        expenses: List of expense dictionaries
        group_name: Name of the group
        payer_names: Dict mapping payer_id to display name
        page: Current page number
        total_count: Total number of expenses
    """
    if total_count == 0:
        return (
            f"<b>💰 {group_name}</b>\n\n"
            "No expenses found in this group.\n\n"
            "Use /addexpense to add the first expense!"
        )
    
    # Calculate the starting index for display numbering
    start_idx = page * PER_PAGE
    
    # Format expense list with payer names
    expense_lines = []
    for idx, expense in enumerate(expenses, start=start_idx + 1):
        payer_id = expense.get('payer_id')
        payer_name = payer_names.get(payer_id) if payer_id else None
        expense_lines.append(_format_expense_list_item(expense, idx, payer_name))
    
    total_pages = (total_count + PER_PAGE - 1) // PER_PAGE
    
    message = (
        f"<b>💰 {group_name}</b>\n"
        f"<i>{total_count} expense{'s' if total_count != 1 else ''}</i>\n\n"
        + "\n\n".join(expense_lines)
    )
    
    if total_pages > 1:
        message += f"\n\n<i>Page {page + 1} of {total_pages}</i>"
    
    return message


def _format_expense_details(expense: dict, participants: list, payer_name: Optional[str] = None) -> str:
    """Format full expense details with payer info and proper date formatting."""
    description = expense.get('description') or 'No description'
    amount = expense.get('amount', 0)
    currency = expense.get('currency', 'SGD')
    expense_date = expense.get('expense_date', '')
    split_type = expense.get('split_type', 'equal')
    is_settled = expense.get('is_settled', False)
    
    # Format date properly
    formatted_date = _format_date_full(expense_date)
    
    # Format split type for display
    if hasattr(split_type, 'value'):
        split_type_display = split_type.value.title()
    else:
        split_type_display = str(split_type).title()
    
    # Status indicator
    status_text = "✓ Settled" if is_settled else "○ Pending"
    
    # Build participant breakdown
    breakdown_lines = []
    for p in participants:
        name = p.get('first_name') or p.get('username') or f"User {p.get('user_id')}"
        share = p.get('share_amount', 0)
        status = "✓" if p.get('is_settled') else "○"
        breakdown_lines.append(f"  {status} {name}: {currency} {share}")
    
    breakdown = "\n".join(breakdown_lines)
    
    # Build the message with clear visual hierarchy
    message = f"<b>📝 {description}</b>\n\n"
    message += f"<b>Amount:</b> {currency} {amount}\n"
    
    if payer_name:
        message += f"<b>Paid by:</b> {payer_name}\n"
    
    message += f"<b>Date:</b> {formatted_date}\n"
    message += f"<b>Split:</b> {split_type_display}\n"
    message += f"<b>Status:</b> {status_text}\n\n"
    message += f"<b>Breakdown:</b>\n{breakdown}\n\n"
    message += f"<i>✓ = settled, ○ = pending</i>"
    
    return message


def _cleanup_expense_view_data(context: ContextTypes.DEFAULT_TYPE, is_group_chat: bool = False):
    """Clean up view-related context data."""
    keys = [
        'expense_view_groups',
        'expense_view_group_id',
        'expense_view_group_name',
        'expense_view_current_page',
    ]
    if is_group_chat:
        for key in keys:
            context.chat_data.pop(key, None)
    else:
        for key in keys:
            context.user_data.pop(key, None)


# ===================================================================================
# Entry Point - /expenses command
# ===================================================================================
@validate_chat_type("private", "group", "supergroup")
async def expenses_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /expenses command handler.
    - In private chat: Shows groups to select, then expenses for that group
    - In group chat: Shows expenses directly if one group, or group selection if multiple
    """
    telegram_user = update.effective_user
    chat_type = update.effective_chat.type
    
    if not telegram_user:
        logger.warning("Received /expenses command without telegram user information")
        return
    
    logger.info(f"User {telegram_user.id} viewing expenses in {chat_type} chat")
    is_group_chat = chat_type in ["group", "supergroup"]
    
    try:
        groups = []
        async with get_db() as db:
            if chat_type == "private":
                # Get all groups user is a member of
                groups = await GroupService.get_all_groups_by_user_id(db, telegram_user.id)
            else:
                # Get groups associated with this Telegram chat
                groups = await GroupService.get_group_by_chat_id(db, update.effective_chat.id)
        
        if not groups:
            message = (
                "You are not a member of any groups yet.\n\n"
                "Create a group with /newgroup or join an existing group first."
            )
            await update.message.reply_text(message)
            return
        
        if len(groups) == 1:
            # Single group - show expenses directly
            group = groups[0]
            
            # Store group info in appropriate context
            if is_group_chat:
                context.chat_data['expense_view_group_id'] = group['id']
                context.chat_data['expense_view_group_name'] = group['name']
            else:
                context.user_data['expense_view_group_id'] = group['id']
                context.user_data['expense_view_group_name'] = group['name']
            
            await _show_expense_list(update, context, group['id'], group['name'], page=0, is_group_chat=is_group_chat)
        else:
            # Multiple groups - let user select
            if is_group_chat:
                context.chat_data['expense_view_groups'] = groups
            else:
                context.user_data['expense_view_groups'] = groups
            
            keyboard = ExpenseKeyboard.get_group_selection_keyboard(groups)
            await update.message.reply_text(
                "<b>Select a group to view expenses:</b>",
                parse_mode="HTML",
                reply_markup=keyboard
            )
    except Exception as e:
        logger.error(f"Error in expenses_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_MSG)


# ===================================================================================
# Show Expense List
# ===================================================================================
async def _show_expense_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    group_name: str,
    page: int = 0,
    is_group_chat: bool = False
):
    """Display paginated list of expenses for a group using server-side pagination."""
    telegram_user = update.effective_user
    query = update.callback_query
    
    try:
        async with get_db() as db:
            # Get total count for pagination
            total_count = await ExpenseService.get_expense_count_by_group_id(
                db,
                group_id,
                requesting_user_id=telegram_user.id
            )
            
            # Fetch only current page expenses (server-side pagination)
            offset = page * PER_PAGE
            expenses = await ExpenseService.get_expenses_by_group_id(
                db,
                group_id,
                requesting_user_id=telegram_user.id,
                limit=PER_PAGE,
                offset=offset
            )
            
            # Fetch payer names for all expenses on this page (batch query)
            payer_names = {}
            if expenses:
                payer_ids = set(e.get('payer_id') for e in expenses if e.get('payer_id'))
                for payer_id in payer_ids:
                    user = await UserService.get_user_by_id(db, payer_id)
                    if user:
                        payer_names[payer_id] = user.get('first_name') or user.get('username') or f"User {payer_id}"
        
        # Store current page so back-navigation can restore it
        if is_group_chat:
            context.chat_data['expense_view_current_page'] = page
        else:
            context.user_data['expense_view_current_page'] = page

        # Check if we should show back to groups button
        if is_group_chat:
            groups = context.chat_data.get('expense_view_groups', [])
        else:
            groups = context.user_data.get('expense_view_groups', [])
        show_back_to_groups = len(groups) > 1

        # Format message with payer names
        message = _format_expense_list_message(expenses, group_name, payer_names, page, total_count)
        
        # Build keyboard with server-side pagination info
        keyboard = ExpenseKeyboard.get_expense_list_keyboard(
            expenses=expenses,
            group_id=group_id,
            page=page,
            per_page=PER_PAGE,
            total_count=total_count,
            show_back_to_groups=show_back_to_groups
        )
        
        # Send or edit message
        if query:
            await query.edit_message_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            await update.message.reply_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
    except UnauthorizedActionException as e:
        logger.warning(f"Unauthorized access attempt: {e}")
        error_text = "You don't have permission to view expenses in this group."
        if query:
            await query.edit_message_text(error_text)
        else:
            await update.message.reply_text(error_text)
    except GroupNotFoundException as e:
        logger.warning(f"Group not found: {e}")
        error_text = "Group not found. It may have been deleted."
        if query:
            await query.edit_message_text(error_text)
        else:
            await update.message.reply_text(error_text)
    except Exception as e:
        logger.error(f"Error showing expense list: {e}", exc_info=True)
        error_text = ERROR_MSG
        if query:
            await query.edit_message_text(error_text)
        else:
            await update.message.reply_text(error_text)


# ===================================================================================
# Show Expense Details
# ===================================================================================
async def _show_expense_details(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    expense_id: int
):
    """Show detailed view of a single expense."""
    telegram_user = update.effective_user
    query = update.callback_query
    
    try:
        async with get_db() as db:
            expense_data = await ExpenseService.get_expense_with_participants(
                db,
                expense_id,
                requesting_user_id=telegram_user.id
            )
            
            # Fetch payer name
            payer_name = None
            payer_id = expense_data.get('payer_id')
            if payer_id:
                payer_user = await UserService.get_user_by_id(db, payer_id)
                if payer_user:
                    payer_name = payer_user.get('first_name') or payer_user.get('username') or f"User {payer_id}"
            
            # Check if user can modify this expense
            can_modify, _ = await ExpenseService.can_modify_expense(
                db, expense_id, telegram_user.id
            )
        
        message = _format_expense_details(expense_data, expense_data.get('participants', []), payer_name)
        group_id = expense_data.get('group_id')
        keyboard = ExpenseKeyboard.get_expense_details_keyboard(
            expense_id=expense_id,
            group_id=group_id,
            can_modify=can_modify
        )
        
        await query.edit_message_text(
            message,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except ExpenseNotFoundException:
        await query.edit_message_text("Expense not found. It may have been deleted.")
    except UnauthorizedActionException:
        await query.edit_message_text("You don't have permission to view this expense.")
    except Exception as e:
        logger.error(f"Error showing expense details: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


# ===================================================================================
# Callback Handler
# ===================================================================================
async def handle_expense_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries for expense viewing (selection, pagination, details)."""
    query = update.callback_query
    
    telegram_user = update.effective_user
    if not telegram_user:
        logger.warning("Received expense callback query without telegram user information")
        await query.answer("Session expired. Please try again.", show_alert=True)
        return
    
    # Determine chat context
    chat_type = update.effective_chat.type if update.effective_chat else "private"
    is_group_chat = chat_type in ["group", "supergroup"]
    
    action, data = ExpenseKeyboard.extract_callback_info(query.data)
    
    # Cancel is always safe - answer and close
    if action == ExpenseKeyboard.ACTION_CANCEL:
        await query.answer()
        await query.edit_message_text("Expense viewing cancelled.")
        _cleanup_expense_view_data(context, is_group_chat)
        return
    
    # For pagination on group selection (no colon in data), validate context exists
    if action in [ExpenseKeyboard.ACTION_PREV, ExpenseKeyboard.ACTION_NEXT]:
        if data and ':' not in str(data):
            # Group selection pagination - requires context
            groups = context.chat_data.get('expense_view_groups', []) if is_group_chat else context.user_data.get('expense_view_groups', [])
            if not groups:
                await query.answer("This list has expired.", show_alert=True)
                await query.edit_message_text("Session expired. Please use /expenses again.")
                return
    
    # For back to list without data (back to group selection), validate context
    if action == ExpenseKeyboard.ACTION_BACK_TO_LIST and not data:
        groups = context.chat_data.get('expense_view_groups', []) if is_group_chat else context.user_data.get('expense_view_groups', [])
        if not groups:
            await query.answer("This list has expired.", show_alert=True)
            await query.edit_message_text("Session expired. Please use /expenses again.")
            return
    
    # Validation passed, acknowledge the callback
    await query.answer()
    
    # Handle group selection (for viewing expenses)
    if action == ExpenseKeyboard.ACTION_SELECT:
        if not data:
            await query.edit_message_text("Invalid group selection.")
            return
        
        try:
            group_id = int(data)
            
            # Get group name from stored groups
            if is_group_chat:
                groups = context.chat_data.get('expense_view_groups', [])
            else:
                groups = context.user_data.get('expense_view_groups', [])
            
            group = next((g for g in groups if g['id'] == group_id), None)
            
            if group:
                group_name = group['name']
                # Store selected group info
                if is_group_chat:
                    context.chat_data['expense_view_group_id'] = group_id
                    context.chat_data['expense_view_group_name'] = group_name
                else:
                    context.user_data['expense_view_group_id'] = group_id
                    context.user_data['expense_view_group_name'] = group_name
                
                await _show_expense_list(update, context, group_id, group_name, page=0, is_group_chat=is_group_chat)
            else:
                # Group not in cache, try to fetch it
                async with get_db() as db:
                    group_data = await GroupService.get_group_by_id(db, group_id)
                    if group_data:
                        group_name = group_data['name']
                        if is_group_chat:
                            context.chat_data['expense_view_group_id'] = group_id
                            context.chat_data['expense_view_group_name'] = group_name
                        else:
                            context.user_data['expense_view_group_id'] = group_id
                            context.user_data['expense_view_group_name'] = group_name
                        await _show_expense_list(update, context, group_id, group_name, page=0, is_group_chat=is_group_chat)
                    else:
                        await query.edit_message_text("Group not found.")
        except ValueError:
            await query.edit_message_text("Invalid group ID.")
        except Exception as e:
            logger.error(f"Error handling group selection for expenses: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return
    
    # Handle pagination
    if action in [ExpenseKeyboard.ACTION_PREV, ExpenseKeyboard.ACTION_NEXT]:
        if not data:
            await query.edit_message_text("Invalid pagination data.")
            return
        
        # Check if this is group pagination or expense list pagination
        if ':' in str(data):
            # Expense list pagination: "group_id:page"
            try:
                parts = data.split(':')
                group_id = int(parts[0])
                page = int(parts[1])
                
                # Get group name from context
                if is_group_chat:
                    group_name = context.chat_data.get('expense_view_group_name', 'Group')
                else:
                    group_name = context.user_data.get('expense_view_group_name', 'Group')
                
                await _show_expense_list(update, context, group_id, group_name, page=page, is_group_chat=is_group_chat)
            except (ValueError, IndexError) as e:
                logger.error(f"Error parsing pagination data: {e}")
                await query.edit_message_text("Invalid pagination data.")
        else:
            # Group selection pagination
            try:
                page = int(data)
                
                if is_group_chat:
                    groups = context.chat_data.get('expense_view_groups', [])
                else:
                    groups = context.user_data.get('expense_view_groups', [])
                
                if not groups:
                    await query.edit_message_text("Groups list expired. Please use /expenses again.")
                    return
                
                keyboard = ExpenseKeyboard.get_group_selection_keyboard(groups, page=page)
                await query.edit_message_text(
                    "<b>Select a group to view expenses:</b>",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            except ValueError:
                await query.edit_message_text("Invalid page number.")
        return
    
    # Handle view expense details
    if action == ExpenseKeyboard.ACTION_VIEW_DETAILS:
        if not data:
            await query.edit_message_text("Invalid expense selection.")
            return
        
        try:
            expense_id = int(data)
            await _show_expense_details(update, context, expense_id)
        except ValueError:
            await query.edit_message_text("Invalid expense ID.")
        except Exception as e:
            logger.error(f"Error showing expense details: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return
    
    # Handle back to list
    if action == ExpenseKeyboard.ACTION_BACK_TO_LIST:
        if data:
            # Back from expense details to expense list
            try:
                group_id = int(data)
                
                # Get group name from context
                if is_group_chat:
                    group_name = context.chat_data.get('expense_view_group_name', 'Group')
                    saved_page = context.chat_data.get('expense_view_current_page', 0)
                else:
                    group_name = context.user_data.get('expense_view_group_name', 'Group')
                    saved_page = context.user_data.get('expense_view_current_page', 0)

                await _show_expense_list(update, context, group_id, group_name, page=saved_page, is_group_chat=is_group_chat)
            except ValueError:
                await query.edit_message_text("Invalid group ID.")
        else:
            # Back from expense list to group selection
            if is_group_chat:
                groups = context.chat_data.get('expense_view_groups', [])
            else:
                groups = context.user_data.get('expense_view_groups', [])
            
            if groups:
                keyboard = ExpenseKeyboard.get_group_selection_keyboard(groups)
                await query.edit_message_text(
                    "<b>Select a group to view expenses:</b>",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            else:
                await query.edit_message_text("Groups list expired. Please use /expenses again.")
        return
    
    # Handle delete expense
    if action == ExpenseKeyboard.ACTION_DELETE:
        if not data:
            await query.edit_message_text("Invalid expense selection.")
            return
        
        try:
            expense_id = int(data)
            
            # Check authorization before showing confirmation
            async with get_db() as db:
                can_modify, reason = await ExpenseService.can_modify_expense(
                    db, expense_id, telegram_user.id
                )
            
            if not can_modify:
                # Show error in the message since query.answer() was already called
                await query.edit_message_text(f"Cannot delete: {reason}")
                return
            
            # Show delete confirmation
            keyboard = ExpenseKeyboard.get_delete_confirmation_keyboard(expense_id)
            await query.edit_message_text(
                "<b>Delete Expense</b>\n\n"
                "Are you sure you want to delete this expense?\n\n"
                "This action cannot be undone.",
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except ValueError:
            await query.edit_message_text("Invalid expense ID.")
        except Exception as e:
            logger.error(f"Error preparing delete confirmation: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return
    
    # Handle confirm delete
    if action == ExpenseKeyboard.ACTION_CONFIRM_DELETE:
        if not data:
            await query.edit_message_text("Invalid expense selection.")
            return

        try:
            expense_id = int(data)

            # Get group_id before deletion for navigation
            async with get_db() as db:
                expense_data = await ExpenseService.get_expense_by_id(db, expense_id)
                group_id = expense_data.get('group_id')

                # Perform deletion
                await ExpenseService.delete_expense(db, expense_id, telegram_user.id)

            logger.info(f"User {telegram_user.id} deleted expense {expense_id}")

            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "<< Back to list",
                    callback_data=ExpenseKeyboard._build_callback_data(
                        ExpenseKeyboard.ACTION_BACK_TO_LIST, str(group_id)
                    )
                )
            ]])
            await query.edit_message_text(
                "Expense deleted successfully.",
                reply_markup=keyboard
            )

        except ExpenseNotFoundException:
            await query.edit_message_text("Expense not found. It may have already been deleted.")
        except UnauthorizedActionException as e:
            await query.edit_message_text(str(e))
        except ExpenseNotEditableException as e:
            await query.edit_message_text(str(e))
        except ValueError:
            await query.edit_message_text("Invalid expense ID.")
        except Exception as e:
            logger.error(f"Error deleting expense: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
        return


# ===================================================================================
# Handler Registration Helper
# ===================================================================================
def create_expense_view_callback_handler() -> CallbackQueryHandler:
    """
    Create and return the callback handler for expense viewing and deletion.
    This handles: group selection, pagination, view details, back to list, delete, cancel.
    """
    return CallbackQueryHandler(
        handle_expense_view_callback,
        pattern=f"^{ExpenseKeyboard.PREFIX}(select|view|prev|next|back_list|delete|confirm_del|cancel)"
    )
