from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
from decimal import Decimal
from typing import Optional, Dict, Any, List
from bot.keyboards import ExpenseKeyboard
from .states import EditExpenseStates
from utils import (
    validate_expense_amount,
    validate_expense_description,
    validate_currency_code,
    validate_exact_split_amount,
    validate_percentage_split,
    validate_custom_share
)
from services import ExpenseService, GroupService, SplitCalculator
from infrastructure import get_db
from models import ExpenseSplitType
from shared import (
    ExpenseNotFoundException,
    UnauthorizedActionException,
    ExpenseNotEditableException
)
from datetime import datetime, timezone, date
import logging


logger = logging.getLogger(__name__)

ERROR_MSG = "An unexpected error has occurred while editing the expense. Please try again later."
CONVERSATION_TIMEOUT = 600  # 10 minutes


# ===================================================================================
# Helper Functions
# ===================================================================================
def _cleanup_conversation(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cleanup conversation state."""
    keys_to_remove = [
        'edit_expense_id',
        'edit_original_data',
        'edit_changes',
        'edit_group_members',
        'edit_selected_participants',
        'edit_exact_amounts_pending',
        'edit_percentages_pending',
        'edit_custom_shares_pending',
        'edit_conversation_active',
        'edit_last_message_id'
    ]
    for key in keys_to_remove:
        context.user_data.pop(key, None)


async def _cleanup_previous_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clean up inline keyboard from previous bot message."""
    message_id = context.user_data.get('edit_last_message_id')
    if not message_id:
        return
    
    chat_id = update.effective_chat.id
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None
        )
    except Exception as e:
        logger.debug(f"Failed to remove keyboard for message {message_id}: {e}")
    finally:
        context.user_data.pop('edit_last_message_id', None)


async def _send_or_edit_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    keyboard=None
) -> None:
    """Unified message handler for both callback queries and text messages."""
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        context.user_data['edit_last_message_id'] = update.callback_query.message.message_id
    else:
        await _cleanup_previous_keyboard(update, context)
        sent_message = await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        context.user_data['edit_last_message_id'] = sent_message.message_id


async def _send_validation_error(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: str,
    keyboard=None
) -> None:
    """Send validation error message."""
    message_id = context.user_data.get('edit_last_message_id')
    chat_id = update.effective_chat.id
    
    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=error_msg,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            return
        except Exception as e:
            logger.debug(f"Failed to edit message for validation error: {e}")
    
    await _cleanup_previous_keyboard(update, context)
    sent_message = await update.message.reply_text(
        error_msg,
        parse_mode="HTML",
        reply_markup=keyboard
    )
    context.user_data['edit_last_message_id'] = sent_message.message_id


def _get_member_display_name(member: dict) -> str:
    """Get display name for a member."""
    return member.get('first_name') or member.get('username') or f"User {member.get('user_id')}"


def _get_effective_value(context: ContextTypes.DEFAULT_TYPE, field: str) -> Any:
    """Get the effective value for a field (changed value or original)."""
    changes = context.user_data.get('edit_changes', {})
    original = context.user_data.get('edit_original_data', {})
    return changes.get(field, original.get(field))


def _has_changes(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if there are any pending changes."""
    return bool(context.user_data.get('edit_changes', {}))


# ===================================================================================
# Entry Point - From expense details view
# ===================================================================================
async def start_edit_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Start the edit expense conversation.
    Called from expense details view when user clicks Edit button.
    """
    query = update.callback_query
    await query.answer()
    
    telegram_user = update.effective_user
    if not telegram_user:
        logger.warning("Edit expense started without telegram user information")
        return ConversationHandler.END
    
    # Extract expense_id from callback data
    action, data = ExpenseKeyboard.extract_callback_info(query.data)
    if not data:
        await query.edit_message_text("Invalid expense selection.")
        return ConversationHandler.END
    
    try:
        expense_id = int(data)
    except ValueError:
        await query.edit_message_text("Invalid expense ID.")
        return ConversationHandler.END
    
    logger.info(f"User {telegram_user.id} starting edit for expense {expense_id}")
    
    try:
        async with get_db() as db:
            # Check authorization
            can_modify, reason = await ExpenseService.can_modify_expense(
                db, expense_id, telegram_user.id
            )
            
            if not can_modify:
                await query.edit_message_text(reason)
                return ConversationHandler.END
            
            # Get expense data with participants
            expense_data = await ExpenseService.get_expense_with_participants(
                db, expense_id, telegram_user.id
            )
            
            # Get group members for payer/participant selection
            group_members = await GroupService.get_group_members_with_details(
                db, expense_data['group_id']
            )
        
        # Initialize conversation state
        context.user_data['edit_conversation_active'] = True
        context.user_data['edit_expense_id'] = expense_id
        context.user_data['edit_original_data'] = expense_data
        context.user_data['edit_changes'] = {}
        context.user_data['edit_group_members'] = group_members
        context.user_data['edit_selected_participants'] = [
            p['user_id'] for p in expense_data.get('participants', [])
        ]
        
        return await _show_edit_menu(update, context)
    
    except ExpenseNotFoundException:
        await query.edit_message_text("Expense not found. It may have been deleted.")
        return ConversationHandler.END
    except UnauthorizedActionException as e:
        await query.edit_message_text(str(e))
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error starting edit expense: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)
        return ConversationHandler.END


# ===================================================================================
# State: SELECT_FIELD (Edit Menu)
# ===================================================================================
async def _show_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show the edit menu with all editable fields."""
    original = context.user_data.get('edit_original_data', {})
    changes = context.user_data.get('edit_changes', {})
    
    # Get effective values
    description = changes.get('description', original.get('description')) or 'No description'
    amount = changes.get('amount', original.get('amount', 0))
    currency = changes.get('currency', original.get('currency', 'SGD'))
    
    # Format the current state message
    message = (
        "<b>Edit Expense</b>\n\n"
        f"<b>Current:</b> {description}\n"
        f"<b>Amount:</b> {currency} {amount}\n\n"
        "Select a field to edit:"
    )
    
    # Show pending changes if any
    if changes:
        change_lines = []
        for field, new_value in changes.items():
            old_value = original.get(field)
            if field == 'split_type' and hasattr(new_value, 'value'):
                new_value = new_value.value
            if field == 'split_type' and hasattr(old_value, 'value'):
                old_value = old_value.value
            change_lines.append(f"  {field}: {old_value} -> {new_value}")
        
        message += "\n\n<b>Pending changes:</b>\n" + "\n".join(change_lines)
    
    keyboard = ExpenseKeyboard.get_edit_menu_keyboard(has_changes=_has_changes(context))
    await _send_or_edit_message(update, context, message, keyboard)
    return EditExpenseStates.SELECT_FIELD


async def handle_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle edit menu selections."""
    query = update.callback_query
    await query.answer()
    
    action, data = ExpenseKeyboard.extract_callback_info(query.data)
    
    if action == ExpenseKeyboard.ACTION_CANCEL:
        return await cancel_edit(update, context)
    
    if action == ExpenseKeyboard.ACTION_SAVE:
        return await _show_edit_summary(update, context)
    
    if action == ExpenseKeyboard.ACTION_EDIT_FIELD:
        if data == ExpenseKeyboard.FIELD_DESCRIPTION:
            return await _prompt_edit_description(update, context)
        elif data == ExpenseKeyboard.FIELD_AMOUNT:
            return await _prompt_edit_amount(update, context)
        elif data == ExpenseKeyboard.FIELD_CURRENCY:
            return await _prompt_edit_currency(update, context)
        elif data == ExpenseKeyboard.FIELD_DATE:
            return await _prompt_edit_date(update, context)
        elif data == ExpenseKeyboard.FIELD_PAYER:
            return await _prompt_edit_payer(update, context)
        elif data == ExpenseKeyboard.FIELD_PARTICIPANTS:
            return await _prompt_edit_participants(update, context)
        elif data == ExpenseKeyboard.FIELD_SPLIT_TYPE:
            return await _prompt_edit_split_type(update, context)
    
    return EditExpenseStates.SELECT_FIELD


# ===================================================================================
# State: EDIT_DESCRIPTION
# ===================================================================================
async def _prompt_edit_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new description."""
    current = _get_effective_value(context, 'description') or 'No description'
    
    message = (
        "<b>Edit Description</b>\n\n"
        f"Current: {current}\n\n"
        "Enter new description (or Skip to clear):"
    )
    keyboard = ExpenseKeyboard.get_edit_field_keyboard(
        ExpenseKeyboard.FIELD_DESCRIPTION,
        show_skip=True
    )
    await _send_or_edit_message(update, context, message, keyboard)
    return EditExpenseStates.EDIT_DESCRIPTION


async def handle_edit_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle description edit input."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, data = ExpenseKeyboard.extract_callback_info(query.data)
        
        if action == ExpenseKeyboard.ACTION_CANCEL:
            return await cancel_edit(update, context)
        if action == ExpenseKeyboard.ACTION_BACK_TO_EDIT:
            return await _show_edit_menu(update, context)
        if action == ExpenseKeyboard.ACTION_SKIP:
            context.user_data['edit_changes']['description'] = None
            return await _show_edit_menu(update, context)
        
        return EditExpenseStates.EDIT_DESCRIPTION
    
    # Handle text input
    is_valid, error_msg = validate_expense_description(update.message.text)
    if not is_valid:
        await _send_validation_error(
            update, context, error_msg,
            ExpenseKeyboard.get_edit_field_keyboard(ExpenseKeyboard.FIELD_DESCRIPTION, show_skip=True)
        )
        return EditExpenseStates.EDIT_DESCRIPTION
    
    context.user_data['edit_changes']['description'] = update.message.text.strip()
    return await _show_edit_menu(update, context)


# ===================================================================================
# State: EDIT_AMOUNT
# ===================================================================================
async def _prompt_edit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new amount."""
    current = _get_effective_value(context, 'amount')
    currency = _get_effective_value(context, 'currency')
    
    message = (
        "<b>Edit Amount</b>\n\n"
        f"Current: {currency} {current}\n\n"
        "Enter new amount:"
    )
    keyboard = ExpenseKeyboard.get_edit_field_keyboard(ExpenseKeyboard.FIELD_AMOUNT)
    await _send_or_edit_message(update, context, message, keyboard)
    return EditExpenseStates.EDIT_AMOUNT


async def handle_edit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle amount edit input."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, _ = ExpenseKeyboard.extract_callback_info(query.data)
        
        if action == ExpenseKeyboard.ACTION_CANCEL:
            return await cancel_edit(update, context)
        if action == ExpenseKeyboard.ACTION_BACK_TO_EDIT:
            return await _show_edit_menu(update, context)
        
        return EditExpenseStates.EDIT_AMOUNT
    
    # Handle text input
    is_valid, error_msg, amount = validate_expense_amount(update.message.text)
    if not is_valid:
        await _send_validation_error(
            update, context, error_msg,
            ExpenseKeyboard.get_edit_field_keyboard(ExpenseKeyboard.FIELD_AMOUNT)
        )
        return EditExpenseStates.EDIT_AMOUNT
    
    context.user_data['edit_changes']['amount'] = amount
    
    # Check if we need to re-enter split data for EXACT split type
    split_type = _get_effective_value(context, 'split_type')
    if isinstance(split_type, str):
        split_type = ExpenseSplitType(split_type)
    
    if split_type == ExpenseSplitType.EXACT:
        # Need to re-enter exact amounts since total changed
        context.user_data['edit_exact_amounts_pending'] = {
            'amounts': {},
            'current_index': 0
        }
        return await _prompt_exact_amounts(update, context)
    
    return await _show_edit_menu(update, context)


# ===================================================================================
# State: EDIT_CURRENCY
# ===================================================================================
async def _prompt_edit_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new currency."""
    current = _get_effective_value(context, 'currency')
    
    message = (
        "<b>Edit Currency</b>\n\n"
        f"Current: {current}\n\n"
        "Enter new currency code (e.g., SGD, USD, MYR):"
    )
    keyboard = ExpenseKeyboard.get_edit_field_keyboard(ExpenseKeyboard.FIELD_CURRENCY)
    await _send_or_edit_message(update, context, message, keyboard)
    return EditExpenseStates.EDIT_CURRENCY


async def handle_edit_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle currency edit input."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, _ = ExpenseKeyboard.extract_callback_info(query.data)
        
        if action == ExpenseKeyboard.ACTION_CANCEL:
            return await cancel_edit(update, context)
        if action == ExpenseKeyboard.ACTION_BACK_TO_EDIT:
            return await _show_edit_menu(update, context)
        
        return EditExpenseStates.EDIT_CURRENCY
    
    # Handle text input
    currency_code = update.message.text.strip().upper()
    is_valid, error_msg = validate_currency_code(currency_code)
    if not is_valid:
        await _send_validation_error(
            update, context, error_msg,
            ExpenseKeyboard.get_edit_field_keyboard(ExpenseKeyboard.FIELD_CURRENCY)
        )
        return EditExpenseStates.EDIT_CURRENCY
    
    context.user_data['edit_changes']['currency'] = currency_code
    return await _show_edit_menu(update, context)


# ===================================================================================
# State: EDIT_DATE
# ===================================================================================
async def _prompt_edit_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new date."""
    current = _get_effective_value(context, 'expense_date')
    
    message = (
        "<b>Edit Date</b>\n\n"
        f"Current: {current}\n\n"
        "Enter new date (YYYY-MM-DD format):\n"
        "<i>Example: 2025-01-20</i>\n\n"
        "Or type 'today' to use today's date."
    )
    keyboard = ExpenseKeyboard.get_edit_field_keyboard(ExpenseKeyboard.FIELD_DATE)
    await _send_or_edit_message(update, context, message, keyboard)
    return EditExpenseStates.EDIT_DATE


async def handle_edit_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle date edit input."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, _ = ExpenseKeyboard.extract_callback_info(query.data)
        
        if action == ExpenseKeyboard.ACTION_CANCEL:
            return await cancel_edit(update, context)
        if action == ExpenseKeyboard.ACTION_BACK_TO_EDIT:
            return await _show_edit_menu(update, context)
        
        return EditExpenseStates.EDIT_DATE
    
    # Handle text input
    date_text = update.message.text.strip().lower()
    
    if date_text == 'today':
        new_date = date.today()
    else:
        try:
            new_date = datetime.strptime(date_text, '%Y-%m-%d').date()
        except ValueError:
            await _send_validation_error(
                update, context,
                "Invalid date format. Please use YYYY-MM-DD (e.g., 2025-01-20) or type 'today'.",
                ExpenseKeyboard.get_edit_field_keyboard(ExpenseKeyboard.FIELD_DATE)
            )
            return EditExpenseStates.EDIT_DATE
    
    context.user_data['edit_changes']['expense_date'] = new_date
    return await _show_edit_menu(update, context)


# ===================================================================================
# State: EDIT_PAYER
# ===================================================================================
async def _prompt_edit_payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new payer selection."""
    members = context.user_data.get('edit_group_members', [])
    current_payer_id = _get_effective_value(context, 'payer_id')
    
    message = "<b>Edit Payer</b>\n\nSelect who paid for this expense:"
    keyboard = ExpenseKeyboard.get_edit_payer_keyboard(members, current_payer_id)
    await _send_or_edit_message(update, context, message, keyboard)
    return EditExpenseStates.EDIT_PAYER


async def handle_edit_payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle payer selection."""
    query = update.callback_query
    await query.answer()
    
    action, data = ExpenseKeyboard.extract_callback_info(query.data)
    
    if action == ExpenseKeyboard.ACTION_CANCEL:
        return await cancel_edit(update, context)
    if action == ExpenseKeyboard.ACTION_BACK_TO_EDIT:
        return await _show_edit_menu(update, context)
    
    if action == ExpenseKeyboard.ACTION_SELECT_PAYER:
        payer_id = int(data)
        context.user_data['edit_changes']['payer_id'] = payer_id
        return await _show_edit_menu(update, context)
    
    return EditExpenseStates.EDIT_PAYER


# ===================================================================================
# State: EDIT_PARTICIPANTS
# ===================================================================================
async def _prompt_edit_participants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for participant selection."""
    members = context.user_data.get('edit_group_members', [])
    selected = context.user_data.get('edit_selected_participants', [])
    
    message = (
        "<b>Edit Participants</b>\n\n"
        "Select all participants who are splitting this expense.\n"
        "<i>Tap to select/deselect, then press Done.</i>"
    )
    keyboard = ExpenseKeyboard.get_edit_participants_keyboard(members, selected)
    await _send_or_edit_message(update, context, message, keyboard)
    return EditExpenseStates.EDIT_PARTICIPANTS


async def handle_edit_participants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle participant selection."""
    query = update.callback_query
    await query.answer()
    
    action, data = ExpenseKeyboard.extract_callback_info(query.data)
    
    if action == ExpenseKeyboard.ACTION_CANCEL:
        return await cancel_edit(update, context)
    if action == ExpenseKeyboard.ACTION_BACK_TO_EDIT:
        # Reset selected participants to original
        original = context.user_data.get('edit_original_data', {})
        context.user_data['edit_selected_participants'] = [
            p['user_id'] for p in original.get('participants', [])
        ]
        return await _show_edit_menu(update, context)
    
    if action == ExpenseKeyboard.ACTION_TOGGLE_PARTICIPANT:
        user_id = int(data)
        selected = context.user_data.get('edit_selected_participants', [])
        
        if user_id in selected:
            selected.remove(user_id)
        else:
            selected.append(user_id)
        
        context.user_data['edit_selected_participants'] = selected
        return await _prompt_edit_participants(update, context)
    
    if action == ExpenseKeyboard.ACTION_DONE_PARTICIPANTS:
        selected = context.user_data.get('edit_selected_participants', [])
        if not selected:
            await query.answer("Please select at least one participant.", show_alert=True)
            return EditExpenseStates.EDIT_PARTICIPANTS
        
        context.user_data['edit_changes']['participant_ids'] = selected
        
        # Check if we need to re-enter split data
        split_type = _get_effective_value(context, 'split_type')
        if isinstance(split_type, str):
            split_type = ExpenseSplitType(split_type)
        
        if split_type == ExpenseSplitType.EQUAL:
            # Auto-recalculate for equal split
            return await _show_edit_menu(update, context)
        else:
            # Need to re-enter split values
            if split_type == ExpenseSplitType.EXACT:
                context.user_data['edit_exact_amounts_pending'] = {
                    'amounts': {},
                    'current_index': 0
                }
                return await _prompt_exact_amounts(update, context)
            elif split_type == ExpenseSplitType.PERCENTAGE:
                context.user_data['edit_percentages_pending'] = {
                    'percentages': {},
                    'current_index': 0
                }
                return await _prompt_percentages(update, context)
            elif split_type == ExpenseSplitType.CUSTOM:
                context.user_data['edit_custom_shares_pending'] = {
                    'shares': {},
                    'current_index': 0
                }
                return await _prompt_custom_shares(update, context)
        
        return await _show_edit_menu(update, context)
    
    return EditExpenseStates.EDIT_PARTICIPANTS


# ===================================================================================
# State: EDIT_SPLIT_TYPE
# ===================================================================================
async def _prompt_edit_split_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for split type selection."""
    current = _get_effective_value(context, 'split_type')
    if hasattr(current, 'value'):
        current = current.value
    
    message = "<b>Edit Split Type</b>\n\nSelect how to split this expense:"
    keyboard = ExpenseKeyboard.get_edit_split_type_keyboard(current)
    await _send_or_edit_message(update, context, message, keyboard)
    return EditExpenseStates.EDIT_SPLIT_TYPE


async def handle_edit_split_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle split type selection."""
    query = update.callback_query
    await query.answer()
    
    action, data = ExpenseKeyboard.extract_callback_info(query.data)
    
    if action == ExpenseKeyboard.ACTION_CANCEL:
        return await cancel_edit(update, context)
    if action == ExpenseKeyboard.ACTION_BACK_TO_EDIT:
        return await _show_edit_menu(update, context)
    
    if action == ExpenseKeyboard.ACTION_SELECT_SPLIT:
        split_type = ExpenseSplitType(data)
        context.user_data['edit_changes']['split_type'] = split_type
        
        if split_type == ExpenseSplitType.EQUAL:
            return await _show_edit_menu(update, context)
        elif split_type == ExpenseSplitType.EXACT:
            context.user_data['edit_exact_amounts_pending'] = {
                'amounts': {},
                'current_index': 0
            }
            return await _prompt_exact_amounts(update, context)
        elif split_type == ExpenseSplitType.PERCENTAGE:
            context.user_data['edit_percentages_pending'] = {
                'percentages': {},
                'current_index': 0
            }
            return await _prompt_percentages(update, context)
        elif split_type == ExpenseSplitType.CUSTOM:
            context.user_data['edit_custom_shares_pending'] = {
                'shares': {},
                'current_index': 0
            }
            return await _prompt_custom_shares(update, context)
    
    return EditExpenseStates.EDIT_SPLIT_TYPE


# ===================================================================================
# State: ENTER_EXACT_AMOUNTS
# ===================================================================================
async def _prompt_exact_amounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for exact amounts for each participant."""
    participant_ids = context.user_data.get('edit_selected_participants', [])
    if 'participant_ids' in context.user_data.get('edit_changes', {}):
        participant_ids = context.user_data['edit_changes']['participant_ids']
    
    members = context.user_data.get('edit_group_members', [])
    amount = _get_effective_value(context, 'amount')
    currency = _get_effective_value(context, 'currency')
    
    pending = context.user_data.get('edit_exact_amounts_pending', {
        'amounts': {},
        'current_index': 0
    })
    current_index = pending['current_index']
    
    # Check if all amounts collected
    if current_index >= len(participant_ids):
        amounts_list = [pending['amounts'][pid] for pid in participant_ids]
        total_entered = sum(amounts_list)
        
        if abs(total_entered - Decimal(str(amount))) > Decimal('0.01'):
            await _send_or_edit_message(
                update, context,
                f"<b>Amounts don't match!</b>\n\n"
                f"Total expense: {currency} {amount}\n"
                f"Sum of amounts entered: {currency} {total_entered}\n\n"
                "Please re-enter the amounts.",
                ExpenseKeyboard.get_edit_field_keyboard('exact')
            )
            context.user_data['edit_exact_amounts_pending'] = {
                'amounts': {},
                'current_index': 0
            }
            return await _prompt_exact_amounts(update, context)
        
        context.user_data['edit_changes']['split_data'] = {'amounts': amounts_list}
        return await _show_edit_menu(update, context)
    
    # Get current participant info
    current_participant_id = participant_ids[current_index]
    current_member = next((m for m in members if m.get('user_id') == current_participant_id), {})
    current_name = _get_member_display_name(current_member)
    
    entered_so_far = sum(pending['amounts'].values())
    remaining = Decimal(str(amount)) - entered_so_far
    
    message = (
        f"<b>Enter Exact Amounts</b>\n\n"
        f"Total: {currency} {amount}\n"
        f"Remaining: {currency} {remaining}\n\n"
        f"<b>Enter amount for {current_name}:</b>\n"
        f"<i>({current_index + 1} of {len(participant_ids)} participants)</i>"
    )
    
    keyboard = ExpenseKeyboard.get_edit_field_keyboard('exact')
    await _send_or_edit_message(update, context, message, keyboard)
    return EditExpenseStates.ENTER_EXACT_AMOUNTS


async def handle_exact_amounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle exact amount input."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, _ = ExpenseKeyboard.extract_callback_info(query.data)
        
        if action == ExpenseKeyboard.ACTION_CANCEL:
            return await cancel_edit(update, context)
        if action == ExpenseKeyboard.ACTION_BACK_TO_EDIT:
            pending = context.user_data.get('edit_exact_amounts_pending', {})
            current_index = pending.get('current_index', 0)
            
            if current_index > 0:
                participant_ids = context.user_data.get('edit_selected_participants', [])
                if 'participant_ids' in context.user_data.get('edit_changes', {}):
                    participant_ids = context.user_data['edit_changes']['participant_ids']
                prev_participant_id = participant_ids[current_index - 1]
                pending['amounts'].pop(prev_participant_id, None)
                pending['current_index'] = current_index - 1
                return await _prompt_exact_amounts(update, context)
            else:
                context.user_data.pop('edit_exact_amounts_pending', None)
                return await _show_edit_menu(update, context)
        
        return EditExpenseStates.ENTER_EXACT_AMOUNTS
    
    # Handle text input
    pending = context.user_data.get('edit_exact_amounts_pending', {})
    current_index = pending.get('current_index', 0)
    
    already_allocated = sum(pending.get('amounts', {}).values())
    total_amount = Decimal(str(_get_effective_value(context, 'amount')))
    currency = _get_effective_value(context, 'currency')
    
    is_valid, error_msg, entered_amount = validate_exact_split_amount(
        update.message.text,
        total_amount,
        already_allocated
    )
    
    if not is_valid:
        remaining = total_amount - already_allocated
        enhanced_error = (
            f"{error_msg}\n\n"
            f"Total: {currency} {total_amount}\n"
            f"Already allocated: {currency} {already_allocated}\n"
            f"Remaining: {currency} {remaining}"
        )
        await _send_validation_error(
            update, context, enhanced_error,
            ExpenseKeyboard.get_edit_field_keyboard('exact')
        )
        return EditExpenseStates.ENTER_EXACT_AMOUNTS
    
    participant_ids = context.user_data.get('edit_selected_participants', [])
    if 'participant_ids' in context.user_data.get('edit_changes', {}):
        participant_ids = context.user_data['edit_changes']['participant_ids']
    
    current_participant_id = participant_ids[current_index]
    pending['amounts'][current_participant_id] = entered_amount
    pending['current_index'] = current_index + 1
    
    return await _prompt_exact_amounts(update, context)


# ===================================================================================
# State: ENTER_PERCENTAGES
# ===================================================================================
async def _prompt_percentages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for percentages for each participant."""
    participant_ids = context.user_data.get('edit_selected_participants', [])
    if 'participant_ids' in context.user_data.get('edit_changes', {}):
        participant_ids = context.user_data['edit_changes']['participant_ids']
    
    members = context.user_data.get('edit_group_members', [])
    amount = _get_effective_value(context, 'amount')
    currency = _get_effective_value(context, 'currency')
    
    pending = context.user_data.get('edit_percentages_pending', {
        'percentages': {},
        'current_index': 0
    })
    current_index = pending['current_index']
    
    # Check if all percentages collected
    if current_index >= len(participant_ids):
        percentages_list = [pending['percentages'][pid] for pid in participant_ids]
        total_percentage = sum(percentages_list)
        
        if abs(total_percentage - Decimal('100')) > Decimal('0.01'):
            await _send_or_edit_message(
                update, context,
                f"<b>Percentages don't add up!</b>\n\n"
                f"Total: 100%\n"
                f"Sum entered: {total_percentage}%\n\n"
                "Please re-enter the percentages.",
                ExpenseKeyboard.get_edit_field_keyboard('percentage')
            )
            context.user_data['edit_percentages_pending'] = {
                'percentages': {},
                'current_index': 0
            }
            return await _prompt_percentages(update, context)
        
        context.user_data['edit_changes']['split_data'] = {'percentages': percentages_list}
        return await _show_edit_menu(update, context)
    
    # Get current participant info
    current_participant_id = participant_ids[current_index]
    current_member = next((m for m in members if m.get('user_id') == current_participant_id), {})
    current_name = _get_member_display_name(current_member)
    
    entered_so_far = sum(pending['percentages'].values())
    remaining = Decimal('100') - entered_so_far
    
    message = (
        f"<b>Enter Percentages</b>\n\n"
        f"Total expense: {currency} {amount}\n"
        f"Remaining: {remaining}%\n\n"
        f"<b>Enter percentage for {current_name}:</b>\n"
        f"<i>({current_index + 1} of {len(participant_ids)} participants)</i>\n"
        f"<i>Example: 25 or 33.33</i>"
    )
    
    keyboard = ExpenseKeyboard.get_edit_field_keyboard('percentage')
    await _send_or_edit_message(update, context, message, keyboard)
    return EditExpenseStates.ENTER_PERCENTAGES


async def handle_percentages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle percentage input."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, _ = ExpenseKeyboard.extract_callback_info(query.data)
        
        if action == ExpenseKeyboard.ACTION_CANCEL:
            return await cancel_edit(update, context)
        if action == ExpenseKeyboard.ACTION_BACK_TO_EDIT:
            pending = context.user_data.get('edit_percentages_pending', {})
            current_index = pending.get('current_index', 0)
            
            if current_index > 0:
                participant_ids = context.user_data.get('edit_selected_participants', [])
                if 'participant_ids' in context.user_data.get('edit_changes', {}):
                    participant_ids = context.user_data['edit_changes']['participant_ids']
                prev_participant_id = participant_ids[current_index - 1]
                pending['percentages'].pop(prev_participant_id, None)
                pending['current_index'] = current_index - 1
                return await _prompt_percentages(update, context)
            else:
                context.user_data.pop('edit_percentages_pending', None)
                return await _show_edit_menu(update, context)
        
        return EditExpenseStates.ENTER_PERCENTAGES
    
    # Handle text input
    pending = context.user_data.get('edit_percentages_pending', {})
    current_index = pending.get('current_index', 0)
    
    already_allocated = sum(pending.get('percentages', {}).values())
    
    is_valid, error_msg, percentage = validate_percentage_split(
        update.message.text,
        already_allocated
    )
    
    if not is_valid:
        remaining = Decimal('100') - already_allocated
        enhanced_error = (
            f"{error_msg}\n\n"
            f"Already allocated: {already_allocated}%\n"
            f"Remaining: {remaining}%"
        )
        await _send_validation_error(
            update, context, enhanced_error,
            ExpenseKeyboard.get_edit_field_keyboard('percentage')
        )
        return EditExpenseStates.ENTER_PERCENTAGES
    
    participant_ids = context.user_data.get('edit_selected_participants', [])
    if 'participant_ids' in context.user_data.get('edit_changes', {}):
        participant_ids = context.user_data['edit_changes']['participant_ids']
    
    current_participant_id = participant_ids[current_index]
    pending['percentages'][current_participant_id] = percentage
    pending['current_index'] = current_index + 1
    
    return await _prompt_percentages(update, context)


# ===================================================================================
# State: ENTER_CUSTOM_SHARES
# ===================================================================================
async def _prompt_custom_shares(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for custom share ratios for each participant."""
    participant_ids = context.user_data.get('edit_selected_participants', [])
    if 'participant_ids' in context.user_data.get('edit_changes', {}):
        participant_ids = context.user_data['edit_changes']['participant_ids']
    
    members = context.user_data.get('edit_group_members', [])
    amount = _get_effective_value(context, 'amount')
    currency = _get_effective_value(context, 'currency')
    
    pending = context.user_data.get('edit_custom_shares_pending', {
        'shares': {},
        'current_index': 0
    })
    current_index = pending['current_index']
    
    # Check if all shares collected
    if current_index >= len(participant_ids):
        shares_list = [pending['shares'][pid] for pid in participant_ids]
        context.user_data['edit_changes']['split_data'] = {'shares': shares_list}
        return await _show_edit_menu(update, context)
    
    # Get current participant info
    current_participant_id = participant_ids[current_index]
    current_member = next((m for m in members if m.get('user_id') == current_participant_id), {})
    current_name = _get_member_display_name(current_member)
    
    shares_so_far = list(pending['shares'].values())
    shares_display = ", ".join(str(s) for s in shares_so_far) if shares_so_far else "None yet"
    
    message = (
        f"<b>Enter Custom Shares</b>\n\n"
        f"Total expense: {currency} {amount}\n"
        f"Shares entered: {shares_display}\n\n"
        f"<b>Enter share for {current_name}:</b>\n"
        f"<i>({current_index + 1} of {len(participant_ids)} participants)</i>\n\n"
        f"<i>Enter a number representing their share ratio.</i>\n"
        f"<i>E.g., if A=1, B=2, C=1, then B pays double.</i>"
    )
    
    keyboard = ExpenseKeyboard.get_edit_field_keyboard('custom')
    await _send_or_edit_message(update, context, message, keyboard)
    return EditExpenseStates.ENTER_CUSTOM_SHARES


async def handle_custom_shares(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom share ratio input."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, _ = ExpenseKeyboard.extract_callback_info(query.data)
        
        if action == ExpenseKeyboard.ACTION_CANCEL:
            return await cancel_edit(update, context)
        if action == ExpenseKeyboard.ACTION_BACK_TO_EDIT:
            pending = context.user_data.get('edit_custom_shares_pending', {})
            current_index = pending.get('current_index', 0)
            
            if current_index > 0:
                participant_ids = context.user_data.get('edit_selected_participants', [])
                if 'participant_ids' in context.user_data.get('edit_changes', {}):
                    participant_ids = context.user_data['edit_changes']['participant_ids']
                prev_participant_id = participant_ids[current_index - 1]
                pending['shares'].pop(prev_participant_id, None)
                pending['current_index'] = current_index - 1
                return await _prompt_custom_shares(update, context)
            else:
                context.user_data.pop('edit_custom_shares_pending', None)
                return await _show_edit_menu(update, context)
        
        return EditExpenseStates.ENTER_CUSTOM_SHARES
    
    # Handle text input
    pending = context.user_data.get('edit_custom_shares_pending', {})
    current_index = pending.get('current_index', 0)
    
    is_valid, error_msg, share = validate_custom_share(update.message.text)
    
    if not is_valid:
        shares_so_far = list(pending.get('shares', {}).values())
        shares_display = ", ".join(str(s) for s in shares_so_far) if shares_so_far else "None yet"
        enhanced_error = (
            f"{error_msg}\n\n"
            f"Shares entered so far: {shares_display}\n"
            f"<i>Enter a whole number (1, 2, 3, etc.)</i>"
        )
        await _send_validation_error(
            update, context, enhanced_error,
            ExpenseKeyboard.get_edit_field_keyboard('custom')
        )
        return EditExpenseStates.ENTER_CUSTOM_SHARES
    
    participant_ids = context.user_data.get('edit_selected_participants', [])
    if 'participant_ids' in context.user_data.get('edit_changes', {}):
        participant_ids = context.user_data['edit_changes']['participant_ids']
    
    current_participant_id = participant_ids[current_index]
    pending['shares'][current_participant_id] = share
    pending['current_index'] = current_index + 1
    
    return await _prompt_custom_shares(update, context)


# ===================================================================================
# State: SUMMARY
# ===================================================================================
async def _show_edit_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show summary of changes before saving."""
    original = context.user_data.get('edit_original_data', {})
    changes = context.user_data.get('edit_changes', {})
    members = context.user_data.get('edit_group_members', [])
    
    if not changes:
        await _send_or_edit_message(
            update, context,
            "No changes to save.",
            ExpenseKeyboard.get_edit_menu_keyboard(has_changes=False)
        )
        return EditExpenseStates.SELECT_FIELD
    
    # Build change summary
    change_lines = []
    for field, new_value in changes.items():
        if field == 'split_data':
            continue  # Don't show raw split data
        
        old_value = original.get(field)
        
        # Format display values
        if field == 'split_type':
            if hasattr(new_value, 'value'):
                new_value = new_value.value.title()
            if hasattr(old_value, 'value'):
                old_value = old_value.value.title()
        elif field == 'payer_id':
            old_member = next((m for m in members if m.get('user_id') == old_value), {})
            new_member = next((m for m in members if m.get('user_id') == new_value), {})
            old_value = _get_member_display_name(old_member) if old_member else old_value
            new_value = _get_member_display_name(new_member) if new_member else new_value
        elif field == 'participant_ids':
            old_names = []
            for p in original.get('participants', []):
                member = next((m for m in members if m.get('user_id') == p['user_id']), {})
                old_names.append(_get_member_display_name(member) if member else str(p['user_id']))
            new_names = []
            for pid in new_value:
                member = next((m for m in members if m.get('user_id') == pid), {})
                new_names.append(_get_member_display_name(member) if member else str(pid))
            old_value = ", ".join(old_names)
            new_value = ", ".join(new_names)
        elif field == 'expense_date' and hasattr(new_value, 'isoformat'):
            new_value = new_value.isoformat()
        
        change_lines.append(f"  {field}: {old_value} -> {new_value}")
    
    # Calculate new breakdown
    amount = changes.get('amount', original.get('amount'))
    currency = changes.get('currency', original.get('currency'))
    split_type = changes.get('split_type', original.get('split_type'))
    if isinstance(split_type, str):
        split_type = ExpenseSplitType(split_type)
    
    participant_ids = changes.get('participant_ids', [p['user_id'] for p in original.get('participants', [])])
    split_data = changes.get('split_data')
    
    # Calculate shares for display
    try:
        if split_type == ExpenseSplitType.EQUAL:
            shares = SplitCalculator.calculate_equal_split(Decimal(str(amount)), len(participant_ids))
        elif split_type == ExpenseSplitType.EXACT and split_data:
            shares = split_data.get('amounts', [])
        elif split_type == ExpenseSplitType.PERCENTAGE and split_data:
            shares = SplitCalculator.calculate_percentage_split(Decimal(str(amount)), split_data.get('percentages', []))
        elif split_type == ExpenseSplitType.CUSTOM and split_data:
            shares = SplitCalculator.calculate_custom_split(Decimal(str(amount)), split_data.get('shares', []))
        else:
            # Use existing shares from original if no changes
            shares = [p['share_amount'] for p in original.get('participants', [])]
    except Exception as e:
        logger.error(f"Error calculating shares for summary: {e}")
        shares = [Decimal('0')] * len(participant_ids)
    
    # Build breakdown display
    breakdown_lines = []
    for i, pid in enumerate(participant_ids):
        member = next((m for m in members if m.get('user_id') == pid), {})
        name = _get_member_display_name(member) if member else f"User {pid}"
        share = shares[i] if i < len(shares) else Decimal('0')
        breakdown_lines.append(f"  {name}: {currency} {share}")
    
    message = (
        "<b>Review Changes</b>\n\n"
        "<b>Changes:</b>\n" + "\n".join(change_lines) + "\n\n"
        "<b>Updated breakdown:</b>\n" + "\n".join(breakdown_lines) + "\n\n"
        "Confirm to save these changes?"
    )
    
    keyboard = ExpenseKeyboard.get_edit_summary_keyboard()
    await _send_or_edit_message(update, context, message, keyboard)
    return EditExpenseStates.SUMMARY


async def handle_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle summary confirmation."""
    query = update.callback_query
    await query.answer()
    
    action, _ = ExpenseKeyboard.extract_callback_info(query.data)
    
    if action == ExpenseKeyboard.ACTION_BACK_TO_EDIT:
        return await _show_edit_menu(update, context)
    
    if action == ExpenseKeyboard.ACTION_CONFIRM:
        return await _save_expense(update, context)
    
    return EditExpenseStates.SUMMARY


# ===================================================================================
# Save Expense
# ===================================================================================
async def _save_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the expense changes to the database."""
    query = update.callback_query
    telegram_user = update.effective_user
    
    expense_id = context.user_data.get('edit_expense_id')
    changes = context.user_data.get('edit_changes', {})
    
    if not expense_id:
        await query.edit_message_text("Error: Expense ID not found. Please try again.")
        _cleanup_conversation(context)
        return ConversationHandler.END
    
    if not changes:
        await query.edit_message_text("No changes to save.")
        _cleanup_conversation(context)
        return ConversationHandler.END
    
    try:
        async with get_db() as db:
            updated_expense = await ExpenseService.update_expense(
                db,
                expense_id,
                changes,
                telegram_user.id
            )
        
        logger.info(f"User {telegram_user.id} updated expense {expense_id}")
        
        await query.edit_message_text(
            "<b>Expense Updated!</b>\n\n"
            "Your changes have been saved successfully.\n\n"
            "Use /expenses to view the updated expense.",
            parse_mode="HTML"
        )
        
        _cleanup_conversation(context)
        return ConversationHandler.END
    
    except ExpenseNotFoundException:
        await query.edit_message_text("Expense not found. It may have been deleted.")
    except UnauthorizedActionException as e:
        await query.edit_message_text(str(e))
    except ExpenseNotEditableException as e:
        await query.edit_message_text(str(e))
    except Exception as e:
        logger.error(f"Error saving expense changes: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)
    
    _cleanup_conversation(context)
    return ConversationHandler.END


# ===================================================================================
# Cancel Handler
# ===================================================================================
async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel expense editing."""
    message = "Edit cancelled. No changes were saved."
    
    if update.callback_query:
        await update.callback_query.edit_message_text(message)
    else:
        await _cleanup_previous_keyboard(update, context)
        await update.message.reply_text(message)
    
    _cleanup_conversation(context)
    return ConversationHandler.END


# ===================================================================================
# Conversation Handler Factory
# ===================================================================================
def create_edit_expense_conversation_handler() -> ConversationHandler:
    """Create and return the expense editing conversation handler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                start_edit_expense,
                pattern=f"^{ExpenseKeyboard.PREFIX}{ExpenseKeyboard.ACTION_EDIT}:"
            )
        ],
        states={
            EditExpenseStates.SELECT_FIELD: [
                CallbackQueryHandler(handle_edit_menu, pattern=f"^{ExpenseKeyboard.PREFIX}")
            ],
            EditExpenseStates.EDIT_DESCRIPTION: [
                CallbackQueryHandler(handle_edit_description, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_description)
            ],
            EditExpenseStates.EDIT_AMOUNT: [
                CallbackQueryHandler(handle_edit_amount, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_amount)
            ],
            EditExpenseStates.EDIT_CURRENCY: [
                CallbackQueryHandler(handle_edit_currency, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_currency)
            ],
            EditExpenseStates.EDIT_DATE: [
                CallbackQueryHandler(handle_edit_date, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_date)
            ],
            EditExpenseStates.EDIT_PAYER: [
                CallbackQueryHandler(handle_edit_payer, pattern=f"^{ExpenseKeyboard.PREFIX}")
            ],
            EditExpenseStates.EDIT_PARTICIPANTS: [
                CallbackQueryHandler(handle_edit_participants, pattern=f"^{ExpenseKeyboard.PREFIX}")
            ],
            EditExpenseStates.EDIT_SPLIT_TYPE: [
                CallbackQueryHandler(handle_edit_split_type, pattern=f"^{ExpenseKeyboard.PREFIX}")
            ],
            EditExpenseStates.ENTER_EXACT_AMOUNTS: [
                CallbackQueryHandler(handle_exact_amounts, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exact_amounts)
            ],
            EditExpenseStates.ENTER_PERCENTAGES: [
                CallbackQueryHandler(handle_percentages, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_percentages)
            ],
            EditExpenseStates.ENTER_CUSTOM_SHARES: [
                CallbackQueryHandler(handle_custom_shares, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_shares)
            ],
            EditExpenseStates.SUMMARY: [
                CallbackQueryHandler(handle_summary, pattern=f"^{ExpenseKeyboard.PREFIX}")
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_edit, pattern=f"^{ExpenseKeyboard.PREFIX}{ExpenseKeyboard.ACTION_CANCEL}$")
        ],
        conversation_timeout=CONVERSATION_TIMEOUT,
        name="edit_expense",
        per_chat=True,
        per_user=True
    )
