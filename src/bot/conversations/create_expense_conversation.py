from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from decimal import Decimal
from typing import Optional
from bot.keyboards import ExpenseKeyboard
from .states import CreateExpenseStates
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
from bot.utils import validate_chat_type
from models import ExpenseSplitType
import logging


logger = logging.getLogger(__name__)

ERROR_MSG = "An unexpected error has occurred while creating the expense. Please try again later."
CONVERSATION_TIMEOUT = 600 # 10 minutes

# ===================================================================================
# Helper functions
# ===================================================================================
def _cleanup_conversation(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cleanup conversation state."""
    keys_to_remove = [
        'expense_data', 
        'conversation_active',
        'last_message_id',
        'group_members',
        'selected_participants',
        'user_groups',
        'chat_groups',
        'exact_amounts_pending',
        'percentages_pending',
        'custom_shares_pending'
    ]
    for key in keys_to_remove:
        context.user_data.pop(key, None)

async def _cleanup_previous_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clean up inline keyboard from previous bot message."""
    message_id = context.user_data.get('last_message_id')
    # Nothing to clean if no message ID
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
        # Clean up failures does not block the conversation, fail silently
        logger.warning(f"Failed to remove keyboard for message {message_id} in chat {chat_id}: {e}", exc_info=True)
        pass
    finally:
        context.user_data.pop('last_message_id', None)

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
        context.user_data['last_message_id'] = update.callback_query.message.message_id
    else:
        await _cleanup_previous_keyboard(update, context)
        sent_message = await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        context.user_data['last_message_id'] = sent_message.message_id


async def _send_validation_error(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: str,
    keyboard=None
) -> None:
    """
    Send validation error message with proper keyboard cleanup.
    Tries to edit the previous message first, falls back to sending new message.
    """
    message_id = context.user_data.get('last_message_id')
    chat_id = update.effective_chat.id
    
    # Try to edit the previous message if it exists
    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=error_msg,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            # Keep the same message_id - no need to update
            return
        except Exception as e:
            # Edit failed (message too different, deleted, etc.) - fall back to new message
            logger.debug(f"Failed to edit message {message_id} for validation error: {e}")
            # Continue to fallback below
    
    # Fallback: send new message if no previous message or edit failed
    await _cleanup_previous_keyboard(update, context)
    sent_message = await update.message.reply_text(
        error_msg,
        parse_mode="HTML",
        reply_markup=keyboard
    )
    context.user_data['last_message_id'] = sent_message.message_id

def _get_member_display_name(member: dict) -> str:
    """Get display name for a member."""
    return member.get('first_name') or member.get('username') or f"User {member.get('user_id')}"

# ===================================================================================
# Entry point
# ===================================================================================
@validate_chat_type("private", "group", "supergroup")
async def start_add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the add expense conversation. Entry point for the /addexpense command."""
    telegram_user = update.effective_user
    chat_type = update.effective_chat.type

    if not telegram_user:
        logger.warning("Received /addexpense command without telegram user information")
        return ConversationHandler.END
    
    logger.info(f"Starting add expense conversation for user: {telegram_user.id}")

    # Initialize conversation data
    context.user_data['conversation_active'] = True
    context.user_data['expense_data'] = {}
    context.user_data['selected_participants'] = []

    # The user must be a member of at least one group to add an expense
    groups = []
    try:
        if chat_type == "private":
            # If the user is in a private chat, get all the groups that the user is a part of
            async with get_db() as db:
                groups = await GroupService.get_all_groups_by_user_id(db, telegram_user.id)
        else:
            # If the user is in a Telegram group chat, get the groups associated with the chat
            async with get_db() as db:
                groups = await GroupService.get_group_by_chat_id(db, update.effective_chat.id)
        
        # The user must have at least one group to add an expense
        if not groups or len(groups) == 0:
            logger.warning(f"User {telegram_user.id} is not a member of any groups, cannot add expense.")
            await _send_or_edit_message(
                update,
                context,
                "You are not currently a member of any groups. Please create or join a group first to start adding expenses."
            )
            _cleanup_conversation(context)
            return ConversationHandler.END
        
        # If the user is only part of one group or if there is only one group in the chat, use it directly
        if len(groups) == 1:
            group = groups[0]
            context.user_data['expense_data']['group_id'] = group['id']
            context.user_data['expense_data']['currency'] = group['default_currency']
            context.user_data['expense_data']['group_name'] = group['name']
            return await _prompt_currency(update, context)
        else:
            # Let the users select the group that they want to add an expense to
            context.user_data['groups'] = groups
            return await _prompt_select_group(update, context)
    except Exception as e:
        logger.error(f"An unexpected error occured while creating an expense for user {telegram_user.id}: {e}", exc_info=True)
        await _send_or_edit_message(
            update,
            context,
            ERROR_MSG
        )
        _cleanup_conversation(context)
        return ConversationHandler.END

# ===================================================================================
# State: SELECT_GROUP
# ===================================================================================
async def _prompt_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt the user to select a group."""
    groups = context.user_data.get('groups')
    if not groups:
        logger.warning("No groups available for selection")
        await _send_or_edit_message(
            update,
            context,
            "No groups available. Please create or join a group first."
        )
        _cleanup_conversation(context)
        return ConversationHandler.END
    
    message = "<b>Select a group to add expense to</b>"
    keyboard = ExpenseKeyboard.get_group_selection_keyboard(groups)
    await _send_or_edit_message(update, context, message, keyboard)
    return CreateExpenseStates.SELECT_GROUP

async def handle_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle group selection callback"""
    query = update.callback_query
    await query.answer()

    action, data = ExpenseKeyboard.extract_callback_info(query.data)

    if action == ExpenseKeyboard.ACTION_CANCEL:
        return await cancel_expense(update, context)
    
    if action in [ExpenseKeyboard.ACTION_PREV, ExpenseKeyboard.ACTION_NEXT]:
        # Handle pagination
        page = int(data) if data else 0
        groups = context.user_data.get('groups')

        message = "<b>Select a group to add expense to</b>"
        keyboard = ExpenseKeyboard.get_group_selection_keyboard(groups, page=page)
        await query.edit_message_text(
            message,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return CreateExpenseStates.SELECT_GROUP
    
    if action == ExpenseKeyboard.ACTION_SELECT:
        try:
            group_id = int(data)
            async with get_db() as db:
                group = await GroupService.get_group_by_id(db, group_id)
            
            if not group:
                logger.warning(f"Invalid group selection, group with ID {group_id} not found.")
                await query.edit_message_text("Invalid group selection. Please try again.")
                _cleanup_conversation(context)
                return ConversationHandler.END
            
            context.user_data['expense_data']['group_id'] = group['id']
            context.user_data['expense_data']['currency'] = group['default_currency']
            context.user_data['expense_data']['group_name'] = group['name']

            return await _prompt_currency(update, context)
        except Exception as e:
            logger.error(f"An unexpected error occured while selecting a group for user {update.effective_user.id}: {e}", exc_info=True)
            await query.edit_message_text(ERROR_MSG)
            _cleanup_conversation(context)
            return ConversationHandler.END
    
    # Fall back
    return CreateExpenseStates.SELECT_GROUP

# ===================================================================================
# State: SELECT_CURRENCY
# ===================================================================================
async def _prompt_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt the user for currency selection."""
    currency = context.user_data['expense_data'].get('currency', 'SGD')
    message = (
        "<b>Select Currency</b>\n\n"
        "Please select the currency to record this expense in.\n"
        "<i>E.g. SGD, MYR, USD etc.</i>\n\n"
        f"If you wish to use the default currency of the group: <b>{currency}</b>, press 'Skip'"
    )
    keyboard = ExpenseKeyboard.get_navigation_keyboard(current_field='currency', is_first=False, show_skip=True)
    await _send_or_edit_message(update, context, message, keyboard)
    return CreateExpenseStates.SELECT_CURRENCY

async def handle_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, _ = ExpenseKeyboard.extract_callback_info(query.data)

        if action == ExpenseKeyboard.ACTION_CANCEL:
            return cancel_expense(update, context)
        if action == ExpenseKeyboard.ACTION_SKIP:
            return await _prompt_amount(update, context)
        if action == ExpenseKeyboard.ACTION_BACK:
            return await _prompt_select_group(update, context)
        
        return CreateExpenseStates.SELECT_CURRENCY
    
    currency_code = update.message.text.strip().upper()
    is_valid, error_msg = validate_currency_code(currency_code)
    if not is_valid:
        await _send_or_edit_message(
            update,
            context,
            error_msg,
            ExpenseKeyboard.get_navigation_keyboard(current_field='currency', is_first=False, show_skip=True)
        )
        return CreateExpenseStates.SELECT_CURRENCY
    
    context.user_data['expense_data']['currency'] = currency_code
    return await _prompt_amount(update, context)

# ===================================================================================
# State: AMOUNT
# ===================================================================================
async def _prompt_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Prompt the user for input amount
    currency = context.user_data['expense_data'].get('currency', 'SGD')
    message = (
        "<b>Enter expense amount</b>\n\n"
        f"Enter the expense amount in <b>{currency}</b>:\n"
        "<i>Example: 25.50</i>"
    )
    keyboard = ExpenseKeyboard.get_navigation_keyboard(current_field='amount', is_first=False, show_skip=False)
    await _send_or_edit_message(update, context, message, keyboard)
    return CreateExpenseStates.AMOUNT

async def handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle amount input."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, _ = ExpenseKeyboard.extract_callback_info(query.data)

        if action == ExpenseKeyboard.ACTION_CANCEL:
            return await cancel_expense(update, context)
        if action == ExpenseKeyboard.ACTION_BACK:
            return await _prompt_currency(update, context)
        
        # Fallback
        return CreateExpenseStates.AMOUNT
    
    # Handle user input
    is_valid, error_msg, amount = validate_expense_amount(update.message.text)

    if not is_valid:
        await _send_validation_error(
            update,
            context,
            error_msg,
            ExpenseKeyboard.get_navigation_keyboard(current_field='amount', is_first=False, show_skip=False)
        )
        return CreateExpenseStates.AMOUNT
    
    context.user_data['expense_data']['amount'] = amount
    return await _prompt_description(update, context)

# ===================================================================================
# State: DESCRIPTION
# ===================================================================================
async def _prompt_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt the user for expense description"""
    message = (
        "<b>Enter Description</b> (Optional)\n\n"
        "What is this expense for?\n"
        "<i>Example: Dinner with friends (I don't have any friends 😭)</i>"
    )
    keyboard = ExpenseKeyboard.get_navigation_keyboard(current_field='description', is_first=False, show_skip=True)
    await _send_or_edit_message(update, context, message, keyboard)
    return CreateExpenseStates.DESCRIPTION

async def handle_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle expense description input."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, _ = ExpenseKeyboard.extract_callback_info(query.data)

        if action == ExpenseKeyboard.ACTION_CANCEL:
            return await cancel_expense(update, context)
        if action == ExpenseKeyboard.ACTION_BACK:
            return await _prompt_amount(update, context)
        if action == ExpenseKeyboard.ACTION_SKIP:
            context.user_data['expense_data']['description'] = None
            return await _prompt_payer_selection(update, context)

        return CreateExpenseStates.DESCRIPTION
    
    # Handle text input
    is_valid, error_msg = validate_expense_description(update.message.text)

    if not is_valid:
        await _send_validation_error(
            update,
            context,
            error_msg,
            ExpenseKeyboard.get_navigation_keyboard(current_field='description', is_first=False, show_skip=True)
        )
        return CreateExpenseStates.DESCRIPTION
    
    context.user_data['expense_data']['description'] = update.message.text.strip()
    return await _prompt_payer_selection(update, context)

# ===================================================================================
# State: SELECT_PAYER
# ===================================================================================
async def _prompt_payer_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt user to select who paid for the expense."""
    group_id = context.user_data['expense_data']['group_id']

    try:
        async with get_db() as db:
            members = await GroupService.get_group_members_with_details(db, group_id)
        
        context.user_data['group_members'] = members

        message = "<b>Who Paid?</b>\n\nSelect the person who paid for this expense:"
        keyboard = ExpenseKeyboard.get_payer_selection_keyboard(members)
        await _send_or_edit_message(update, context, message, keyboard)
        return CreateExpenseStates.SELECT_PAYER
    except Exception as e:
        logger.error(f"Error loading group members: {e}", exc_info=True)
        await _send_or_edit_message(update, context, ERROR_MSG, None)
        _cleanup_conversation(context)
        return ConversationHandler.END


async def handle_payer_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle payer selection callback."""
    query = update.callback_query
    await query.answer()

    action, data = ExpenseKeyboard.extract_callback_info(query.data)

    if action == ExpenseKeyboard.ACTION_CANCEL:
        return await cancel_expense(update, context)
    if action == ExpenseKeyboard.ACTION_BACK:
        return await _prompt_description(update, context)
    
    if action == ExpenseKeyboard.ACTION_SELECT_PAYER:
        payer_id = int(data)
        context.user_data['expense_data']['payer_id'] = payer_id

        # Store payer name for summary display
        members = context.user_data.get('group_members', [])
        payer = next((m for m in members if m.get('user_id') == payer_id), {})
        context.user_data['expense_data']['payer_name'] = _get_member_display_name(payer)

        return await _prompt_participant_selection(update, context)
    
    return CreateExpenseStates.SELECT_PAYER


# ===================================================================================
# State: SELECT_PARTICIPANTS
# ===================================================================================
async def _prompt_participant_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt user to select participants (multi-select)."""
    members = context.user_data.get('group_members', [])
    selected = context.user_data.get('selected_participants', [])

    message = (
        "<b>Who's Splitting?</b>\n\n"
        "Select all participants who are splitting this expense.\n"
        "<i>Tap to select/deselect, then press Done.</i>"
    )
    keyboard = ExpenseKeyboard.get_participant_selection_keyboard(members, selected)
    await _send_or_edit_message(update, context, message, keyboard)
    return CreateExpenseStates.SELECT_PARTICIPANTS


async def handle_participant_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle participant toggle callbacks."""
    query = update.callback_query
    await query.answer()

    action, data = ExpenseKeyboard.extract_callback_info(query.data)

    if action == ExpenseKeyboard.ACTION_CANCEL:
        return await cancel_expense(update, context)
    if action == ExpenseKeyboard.ACTION_BACK:
        return await _prompt_payer_selection(update, context)
    
    if action == ExpenseKeyboard.ACTION_TOGGLE_PARTICIPANT:
        user_id = int(data)
        selected = context.user_data.get('selected_participants', [])

        if user_id in selected:
            selected.remove(user_id)
        else:
            selected.append(user_id)
        
        context.user_data['selected_participants'] = selected
        return await _prompt_participant_selection(update, context)
    
    if action == ExpenseKeyboard.ACTION_DONE_PARTICIPANTS:
        selected = context.user_data.get('selected_participants', [])
        if not selected:
            await query.answer("Please select at least one participant.", show_alert=True)
            return CreateExpenseStates.SELECT_PARTICIPANTS
        
        context.user_data['expense_data']['participant_ids'] = selected
        return await _prompt_split_type(update, context)
    
    return CreateExpenseStates.SELECT_PARTICIPANTS


# ===================================================================================
# State: SELECT_SPLIT_TYPE
# ===================================================================================
async def _prompt_split_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt user to select split type."""
    message = "<b>How to Split?</b>\n\nChoose how to split this expense:"
    keyboard = ExpenseKeyboard.get_split_type_keyboard()
    await _send_or_edit_message(update, context, message, keyboard)
    return CreateExpenseStates.SELECT_SPLIT_TYPE


async def handle_split_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle split type selection."""
    query = update.callback_query
    await query.answer()

    action, data = ExpenseKeyboard.extract_callback_info(query.data)

    if action == ExpenseKeyboard.ACTION_CANCEL:
        return await cancel_expense(update, context)
    if action == ExpenseKeyboard.ACTION_BACK:
        return await _prompt_participant_selection(update, context)
    
    if action == ExpenseKeyboard.ACTION_SELECT_SPLIT:
        split_type = ExpenseSplitType(data)
        context.user_data['expense_data']['split_type'] = split_type

        if split_type == ExpenseSplitType.EQUAL:
            # For equal split, go directly to summary
            return await _show_summary(update, context)
        elif split_type == ExpenseSplitType.EXACT:
            # For exact split, need to collect amounts per participant
            return await _prompt_exact_amounts(update, context)
        elif split_type == ExpenseSplitType.PERCENTAGE:
            # For percentage split, need to collect percentages per participant
            return await _prompt_percentages(update, context)
        elif split_type == ExpenseSplitType.CUSTOM:
            # For custom split, need to collect share ratios per participant
            return await _prompt_custom_shares(update, context)
    
    return CreateExpenseStates.SELECT_SPLIT_TYPE


# ===================================================================================
# State: ENTER_EXACT_AMOUNTS
# ===================================================================================
async def _prompt_exact_amounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt user to enter exact amounts for each participant."""
    participant_ids = context.user_data['expense_data'].get('participant_ids', [])
    members = context.user_data.get('group_members', [])
    amount = context.user_data['expense_data'].get('amount', Decimal('0'))
    currency = context.user_data['expense_data'].get('currency', 'SGD')

    # Initialize pending amounts tracker if not exists
    if 'exact_amounts_pending' not in context.user_data:
        context.user_data['exact_amounts_pending'] = {
            'amounts': {},
            'current_index': 0
        }
    
    pending = context.user_data['exact_amounts_pending']
    current_index = pending['current_index']

    # Check if all amounts have been collected
    if current_index >= len(participant_ids):
        # All amounts collected, validate total
        amounts_list = [pending['amounts'][pid] for pid in participant_ids]
        total_entered = sum(amounts_list)

        if abs(total_entered - amount) > Decimal('0.01'):
            # Amounts don't match total - show error and reset
            await _send_or_edit_message(
                update, context,
                f"<b>Amounts don't match!</b>\n\n"
                f"Total expense: {currency} {amount}\n"
                f"Sum of amounts entered: {currency} {total_entered}\n\n"
                "Please re-enter the amounts.",
                ExpenseKeyboard.get_navigation_keyboard('exact', is_first=False)
            )
            # Reset and start over
            context.user_data['exact_amounts_pending'] = {
                'amounts': {},
                'current_index': 0
            }
            return await _prompt_exact_amounts(update, context)
        
        # Store split data and proceed to summary
        context.user_data['expense_data']['split_data'] = {'amounts': amounts_list}
        return await _show_summary(update, context)
    
    # Get current participant info
    current_participant_id = participant_ids[current_index]
    current_member = next((m for m in members if m.get('user_id') == current_participant_id), {})
    current_name = _get_member_display_name(current_member)

    # Calculate remaining amount
    entered_so_far = sum(pending['amounts'].values())
    remaining = amount - entered_so_far

    message = (
        f"<b>Enter Exact Amounts</b>\n\n"
        f"Total: {currency} {amount}\n"
        f"Remaining: {currency} {remaining}\n\n"
        f"<b>Enter amount for {current_name}:</b>\n"
        f"<i>({current_index + 1} of {len(participant_ids)} participants)</i>"
    )

    keyboard = ExpenseKeyboard.get_navigation_keyboard('exact', is_first=False)
    await _send_or_edit_message(update, context, message, keyboard)
    return CreateExpenseStates.ENTER_EXACT_AMOUNTS


async def handle_exact_amounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle exact amount input for each participant."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, _ = ExpenseKeyboard.extract_callback_info(query.data)

        if action == ExpenseKeyboard.ACTION_CANCEL:
            return await cancel_expense(update, context)
        if action == ExpenseKeyboard.ACTION_BACK:
            pending = context.user_data.get('exact_amounts_pending', {})
            current_index = pending.get('current_index', 0)

            if current_index > 0:
                # Go back to previous participant
                participant_ids = context.user_data['expense_data'].get('participant_ids', [])
                prev_participant_id = participant_ids[current_index - 1]

                # Remove the previous amount
                pending['amounts'].pop(prev_participant_id, None)
                pending['current_index'] = current_index - 1

                return await _prompt_exact_amounts(update, context)
            else:
                # Go back to split type selection
                context.user_data.pop('exact_amounts_pending', None)
                return await _prompt_split_type(update, context)
        
        return CreateExpenseStates.ENTER_EXACT_AMOUNTS
    
    # Handle text input - validate against total and remaining amount
    pending = context.user_data.get('exact_amounts_pending', {})
    current_index = pending.get('current_index', 0)
    
    # Calculate already allocated amount
    already_allocated = sum(pending.get('amounts', {}).values())
    total_amount = context.user_data['expense_data'].get('amount', Decimal('0'))
    currency = context.user_data['expense_data'].get('currency', 'SGD')
    
    is_valid, error_msg, entered_amount = validate_exact_split_amount(
        update.message.text,
        total_amount,
        already_allocated
    )

    if not is_valid:
        # Enhance error message with context
        remaining = total_amount - already_allocated
        enhanced_error = (
            f"{error_msg}\n\n"
            f"Total: {currency} {total_amount}\n"
            f"Already allocated: {currency} {already_allocated}\n"
            f"Remaining: {currency} {remaining}"
        )
        await _send_validation_error(
            update,
            context,
            enhanced_error,
            ExpenseKeyboard.get_navigation_keyboard('exact', is_first=False)
        )
        return CreateExpenseStates.ENTER_EXACT_AMOUNTS
    
    # Store the amount for this participant
    participant_ids = context.user_data['expense_data'].get('participant_ids', [])
    current_participant_id = participant_ids[current_index]

    pending['amounts'][current_participant_id] = entered_amount
    pending['current_index'] = current_index + 1

    # Continue to next participant or summary
    return await _prompt_exact_amounts(update, context)


# ===================================================================================
# State: ENTER_PERCENTAGES
# ===================================================================================
async def _prompt_percentages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt user to enter percentages for each participant."""
    participant_ids = context.user_data['expense_data'].get('participant_ids', [])
    members = context.user_data.get('group_members', [])
    amount = context.user_data['expense_data'].get('amount', Decimal('0'))
    currency = context.user_data['expense_data'].get('currency', 'SGD')

    # Initialize pending percentages tracker if not exists
    if 'percentages_pending' not in context.user_data:
        context.user_data['percentages_pending'] = {
            'percentages': {},
            'current_index': 0
        }
    
    pending = context.user_data['percentages_pending']
    current_index = pending['current_index']

    # Check if all percentages have been collected
    if current_index >= len(participant_ids):
        # All percentages collected, validate total equals 100%
        percentages_list = [pending['percentages'][pid] for pid in participant_ids]
        total_percentage = sum(percentages_list)

        if abs(total_percentage - Decimal('100')) > Decimal('0.01'):
            # Percentages don't sum to 100% - show error and reset
            await _send_or_edit_message(
                update, context,
                f"<b>Percentages don't add up!</b>\n\n"
                f"Total: 100%\n"
                f"Sum entered: {total_percentage}%\n\n"
                "Please re-enter the percentages.",
                ExpenseKeyboard.get_navigation_keyboard('percentage', is_first=False)
            )
            # Reset and start over
            context.user_data['percentages_pending'] = {
                'percentages': {},
                'current_index': 0
            }
            return await _prompt_percentages(update, context)
        
        # Store split data and proceed to summary
        context.user_data['expense_data']['split_data'] = {'percentages': percentages_list}
        return await _show_summary(update, context)
    
    # Get current participant info
    current_participant_id = participant_ids[current_index]
    current_member = next((m for m in members if m.get('user_id') == current_participant_id), {})
    current_name = _get_member_display_name(current_member)

    # Calculate remaining percentage
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

    keyboard = ExpenseKeyboard.get_navigation_keyboard('percentage', is_first=False)
    await _send_or_edit_message(update, context, message, keyboard)
    return CreateExpenseStates.ENTER_PERCENTAGES


async def handle_percentages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle percentage input for each participant."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, _ = ExpenseKeyboard.extract_callback_info(query.data)

        if action == ExpenseKeyboard.ACTION_CANCEL:
            return await cancel_expense(update, context)
        if action == ExpenseKeyboard.ACTION_BACK:
            pending = context.user_data.get('percentages_pending', {})
            current_index = pending.get('current_index', 0)

            if current_index > 0:
                # Go back to previous participant
                participant_ids = context.user_data['expense_data'].get('participant_ids', [])
                prev_participant_id = participant_ids[current_index - 1]

                # Remove the previous percentage
                pending['percentages'].pop(prev_participant_id, None)
                pending['current_index'] = current_index - 1

                return await _prompt_percentages(update, context)
            else:
                # Go back to split type selection
                context.user_data.pop('percentages_pending', None)
                return await _prompt_split_type(update, context)
        
        return CreateExpenseStates.ENTER_PERCENTAGES
    
    # Handle text input
    pending = context.user_data.get('percentages_pending', {})
    current_index = pending.get('current_index', 0)
    
    # Calculate already allocated percentage
    already_allocated = sum(pending.get('percentages', {}).values())
    
    is_valid, error_msg, percentage = validate_percentage_split(
        update.message.text,
        already_allocated
    )

    if not is_valid:
        # Enhance error message with context
        remaining = Decimal('100') - already_allocated
        enhanced_error = (
            f"⚠️ {error_msg}\n\n"
            f"<b>Enter Percentages</b>\n\n"
            f"Already allocated: {already_allocated}%\n"
            f"Remaining: {remaining}%"
        )
        await _send_validation_error(
            update,
            context,
            enhanced_error,
            ExpenseKeyboard.get_navigation_keyboard('percentage', is_first=False)
        )
        return CreateExpenseStates.ENTER_PERCENTAGES
    
    # Store the percentage for this participant
    participant_ids = context.user_data['expense_data'].get('participant_ids', [])
    current_participant_id = participant_ids[current_index]

    pending['percentages'][current_participant_id] = percentage
    pending['current_index'] = current_index + 1

    # Continue to next participant or summary
    return await _prompt_percentages(update, context)


# ===================================================================================
# State: ENTER_CUSTOM_SHARES
# ===================================================================================
async def _prompt_custom_shares(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt user to enter custom share ratios for each participant."""
    participant_ids = context.user_data['expense_data'].get('participant_ids', [])
    members = context.user_data.get('group_members', [])
    amount = context.user_data['expense_data'].get('amount', Decimal('0'))
    currency = context.user_data['expense_data'].get('currency', 'SGD')

    # Initialize pending shares tracker if not exists
    if 'custom_shares_pending' not in context.user_data:
        context.user_data['custom_shares_pending'] = {
            'shares': {},
            'current_index': 0
        }
    
    pending = context.user_data['custom_shares_pending']
    current_index = pending['current_index']

    # Check if all shares have been collected
    if current_index >= len(participant_ids):
        # All shares collected, store and proceed to summary
        shares_list = [pending['shares'][pid] for pid in participant_ids]
        
        # Store split data
        context.user_data['expense_data']['split_data'] = {'shares': shares_list}
        return await _show_summary(update, context)
    
    # Get current participant info
    current_participant_id = participant_ids[current_index]
    current_member = next((m for m in members if m.get('user_id') == current_participant_id), {})
    current_name = _get_member_display_name(current_member)

    # Show entered shares so far
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

    keyboard = ExpenseKeyboard.get_navigation_keyboard('custom', is_first=False)
    await _send_or_edit_message(update, context, message, keyboard)
    return CreateExpenseStates.ENTER_CUSTOM


async def handle_custom_shares(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom share ratio input for each participant."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, _ = ExpenseKeyboard.extract_callback_info(query.data)

        if action == ExpenseKeyboard.ACTION_CANCEL:
            return await cancel_expense(update, context)
        if action == ExpenseKeyboard.ACTION_BACK:
            pending = context.user_data.get('custom_shares_pending', {})
            current_index = pending.get('current_index', 0)

            if current_index > 0:
                # Go back to previous participant
                participant_ids = context.user_data['expense_data'].get('participant_ids', [])
                prev_participant_id = participant_ids[current_index - 1]

                # Remove the previous share
                pending['shares'].pop(prev_participant_id, None)
                pending['current_index'] = current_index - 1

                return await _prompt_custom_shares(update, context)
            else:
                # Go back to split type selection
                context.user_data.pop('custom_shares_pending', None)
                return await _prompt_split_type(update, context)
        
        return CreateExpenseStates.ENTER_CUSTOM
    
    # Handle text input
    pending = context.user_data.get('custom_shares_pending', {})
    current_index = pending.get('current_index', 0)
    
    is_valid, error_msg, share = validate_custom_share(update.message.text)

    if not is_valid:
        # Enhance error message with context
        shares_so_far = list(pending.get('shares', {}).values())
        shares_display = ", ".join(str(s) for s in shares_so_far) if shares_so_far else "None yet"
        enhanced_error = (
            f"⚠️ {error_msg}\n\n"
            f"<b>Enter Custom Shares</b>\n\n"
            f"Shares entered so far: {shares_display}\n"
            f"<i>Enter a whole number (1, 2, 3, etc.)</i>"
        )
        await _send_validation_error(
            update,
            context,
            enhanced_error,
            ExpenseKeyboard.get_navigation_keyboard('custom', is_first=False)
        )
        return CreateExpenseStates.ENTER_CUSTOM
    
    # Store the share for this participant
    participant_ids = context.user_data['expense_data'].get('participant_ids', [])
    current_participant_id = participant_ids[current_index]

    pending['shares'][current_participant_id] = share
    pending['current_index'] = current_index + 1

    # Continue to next participant or summary
    return await _prompt_custom_shares(update, context)


# ===================================================================================
# State: SUMMARY
# ===================================================================================
async def _show_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show expense summary for confirmation."""
    expense_data = context.user_data.get('expense_data', {})
    members = context.user_data.get('group_members', [])

    # Get participant info (maintaining order)
    participant_ids = expense_data.get('participant_ids', [])
    participants = []
    for pid in participant_ids:
        member = next((m for m in members if m.get('user_id') == pid), {})
        participants.append({
            'user_id': pid,
            'name': _get_member_display_name(member)
        })

    amount = expense_data.get('amount', Decimal('0'))
    currency = expense_data.get('currency', 'SGD')
    description = expense_data.get('description') or 'No description'
    payer_name = expense_data.get('payer_name', 'Unknown')
    split_type = expense_data.get('split_type', ExpenseSplitType.EQUAL)
    group_name = expense_data.get('group_name', 'Unknown Group')
    split_data = expense_data.get('split_data', {})

    # Calculate the split amounts based on split type
    try:
        if split_type == ExpenseSplitType.EQUAL:
            share_amounts = SplitCalculator.calculate_equal_split(amount, len(participants))
        elif split_type == ExpenseSplitType.EXACT:
            share_amounts = split_data.get('amounts', [])
        elif split_type == ExpenseSplitType.PERCENTAGE:
            percentages = split_data.get('percentages', [])
            share_amounts = SplitCalculator.calculate_percentage_split(amount, percentages)
        elif split_type == ExpenseSplitType.CUSTOM:
            shares = split_data.get('shares', [])
            share_amounts = SplitCalculator.calculate_custom_split(amount, shares)
        else:
            share_amounts = [amount / len(participants)] * len(participants)
    except Exception as e:
        logger.error(f"Error calculating split amounts for summary: {e}", exc_info=True)
        share_amounts = [Decimal('0')] * len(participants)

    # Build the breakdown section
    breakdown_lines = []
    for i, participant in enumerate(participants):
        share = share_amounts[i] if i < len(share_amounts) else Decimal('0')
        line = f"  • {participant['name']}: {currency} {share}"
        
        # Add extra info for percentage/custom splits
        if split_type == ExpenseSplitType.PERCENTAGE and split_data.get('percentages'):
            pct = split_data['percentages'][i] if i < len(split_data['percentages']) else 0
            line += f" ({pct}%)"
        elif split_type == ExpenseSplitType.CUSTOM and split_data.get('shares'):
            share_ratio = split_data['shares'][i] if i < len(split_data['shares']) else 0
            line += f" ({share_ratio} share{'s' if share_ratio != 1 else ''})"
        
        breakdown_lines.append(line)
    
    breakdown_text = "\n".join(breakdown_lines)

    message = (
        "<b>📋 Expense Summary</b>\n\n"
        f"<b>Group:</b> {group_name}\n"
        f"<b>Description:</b> {description}\n"
        f"<b>Total:</b> {currency} {amount}\n"
        f"<b>Paid by:</b> {payer_name}\n"
        f"<b>Split type:</b> {split_type.value.title()}\n\n"
        f"<b>Breakdown:</b>\n{breakdown_text}\n\n"
        "Confirm to add this expense?"
    )

    keyboard = ExpenseKeyboard.get_confirmation_keyboard()
    await _send_or_edit_message(update, context, message, keyboard)
    return CreateExpenseStates.SUMMARY


async def handle_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle summary confirmation."""
    query = update.callback_query
    await query.answer()

    action, _ = ExpenseKeyboard.extract_callback_info(query.data)

    if action == ExpenseKeyboard.ACTION_CANCEL:
        return await cancel_expense(update, context)
    if action == ExpenseKeyboard.ACTION_BACK:
        split_type = context.user_data['expense_data'].get('split_type', ExpenseSplitType.EQUAL)

        if split_type == ExpenseSplitType.EXACT:
            # Reset exact amounts and go back to re-enter
            context.user_data['exact_amounts_pending'] = {
                'amounts': {},
                'current_index': 0
            }
            return await _prompt_exact_amounts(update, context)
        elif split_type == ExpenseSplitType.PERCENTAGE:
            # Reset percentages and go back to re-enter
            context.user_data['percentages_pending'] = {
                'percentages': {},
                'current_index': 0
            }
            return await _prompt_percentages(update, context)
        elif split_type == ExpenseSplitType.CUSTOM:
            # Reset custom shares and go back to re-enter
            context.user_data['custom_shares_pending'] = {
                'shares': {},
                'current_index': 0
            }
            return await _prompt_custom_shares(update, context)
        else:
            return await _prompt_split_type(update, context)
    
    if action == ExpenseKeyboard.ACTION_CONFIRM:
        return await _create_expense(update, context)
    
    return CreateExpenseStates.SUMMARY


# ===================================================================================
# Create Expense
# ===================================================================================
async def _create_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Create the expense in the database."""
    query = update.callback_query
    telegram_user = update.effective_user
    expense_data = context.user_data.get('expense_data', {})

    try:
        from datetime import datetime, timezone

        # Build the expense data dict for the service
        service_data = {
            'group_id': expense_data['group_id'],
            'amount': expense_data['amount'],
            'currency': expense_data['currency'],
            'description': expense_data.get('description'),
            'payer_id': expense_data['payer_id'],
            'participant_ids': expense_data['participant_ids'],
            'split_type': expense_data['split_type'],
            'created_by': telegram_user.id,
            'expense_date': datetime.now(timezone.utc).date(),
            'category': None,
            'split_data': expense_data.get('split_data')
        }

        async with get_db() as db:
            expense = await ExpenseService.create_expense(db, service_data)
        
        currency = expense_data['currency']
        amount = expense_data['amount']
        description = expense_data.get('description') or 'No description'

        await query.edit_message_text(
            "<b>✓ Expense Added!</b>\n\n"
            f"<b>{description}</b>\n"
            f"{currency} {amount}\n\n"
            "Use /addexpense to add another expense.",
            parse_mode="HTML"
        )

        logger.info(f"Expense {expense['id']} created successfully by user {telegram_user.id}")
        _cleanup_conversation(context)
        return ConversationHandler.END
    
    except Exception as e:
        logger.error(f"Error creating expense: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)
        _cleanup_conversation(context)
        return ConversationHandler.END


# ===================================================================================
# Cancel Handler
# ===================================================================================
async def cancel_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel expense creation."""
    message = "Expense creation cancelled. No changes were saved."

    if update.callback_query:
        await update.callback_query.edit_message_text(message)
    else:
        # Clean up the previous keyboard before sending cancellation message
        await _cleanup_previous_keyboard(update, context)
        await update.message.reply_text(message)
    
    _cleanup_conversation(context)
    return ConversationHandler.END


# ===================================================================================
# Conversation Handler Factory
# ===================================================================================
def create_expense_conversation_handler() -> ConversationHandler:
    """Create and return the expense creation conversation handler."""
    return ConversationHandler(
        entry_points=[CommandHandler("addexpense", start_add_expense)],
        states={
            CreateExpenseStates.SELECT_GROUP: [
                CallbackQueryHandler(handle_select_group, pattern=f"^{ExpenseKeyboard.PREFIX}")
            ],
            CreateExpenseStates.SELECT_CURRENCY: [
                CallbackQueryHandler(handle_currency, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_currency)
            ],
            CreateExpenseStates.AMOUNT: [
                CallbackQueryHandler(handle_amount, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount)
            ],
            CreateExpenseStates.DESCRIPTION: [
                CallbackQueryHandler(handle_description, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_description)
            ],
            CreateExpenseStates.SELECT_PAYER: [
                CallbackQueryHandler(handle_payer_selection, pattern=f"^{ExpenseKeyboard.PREFIX}")
            ],
            CreateExpenseStates.SELECT_PARTICIPANTS: [
                CallbackQueryHandler(handle_participant_selection, pattern=f"^{ExpenseKeyboard.PREFIX}")
            ],
            CreateExpenseStates.SELECT_SPLIT_TYPE: [
                CallbackQueryHandler(handle_split_type, pattern=f"^{ExpenseKeyboard.PREFIX}")
            ],
            CreateExpenseStates.ENTER_EXACT_AMOUNTS: [
                CallbackQueryHandler(handle_exact_amounts, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exact_amounts)
            ],
            CreateExpenseStates.ENTER_PERCENTAGES: [
                CallbackQueryHandler(handle_percentages, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_percentages)
            ],
            CreateExpenseStates.ENTER_CUSTOM: [
                CallbackQueryHandler(handle_custom_shares, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_shares)
            ],
            CreateExpenseStates.SUMMARY: [
                CallbackQueryHandler(handle_summary, pattern=f"^{ExpenseKeyboard.PREFIX}")
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_expense)],
        conversation_timeout=CONVERSATION_TIMEOUT,
        name="add_expense",
        per_chat=True,
        per_user=True
    )