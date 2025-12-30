from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from typing import Dict, Any, Optional
from bot.keyboards import UpdateKeyboard
from .states import UpdateProfileStates
from utils import validate_name, validate_currency_code
from shared import UserNotFoundException
from services import UserService
from infrastructure import get_db
import logging

logger = logging.getLogger(__name__)

# Constants
ERROR_MSG = "An unexpected error has occurred while updating your profile. Please try again later."
CONVERSATION_TIMEOUT = 600  # 10 minutes

# Field configuration - defines order, labels, validators, and states
FIELD_CONFIG = [
    {
        'name': UpdateKeyboard.FIELD_FIRST_NAME,
        'label': 'First Name',
        'state': UpdateProfileStates.FIRST_NAME,
        'validator': validate_name,
        'transform': None,
    },
    {
        'name': UpdateKeyboard.FIELD_LAST_NAME,
        'label': 'Last Name',
        'state': UpdateProfileStates.LAST_NAME,
        'validator': validate_name,
        'transform': None,
    },
    {
        'name': UpdateKeyboard.FIELD_PREFERRED_CURRENCY,
        'label': 'Preferred Currency',
        'state': UpdateProfileStates.PREFERRED_CURRENCY,
        'validator': validate_currency_code,
        'transform': str.upper,
    },
]

# Build lookup dictionaries for efficient access
_FIELD_BY_NAME = {f['name']: f for f in FIELD_CONFIG}
_FIELD_BY_STATE = {f['state']: f for f in FIELD_CONFIG}


def _get_next_field(current_name: str) -> Optional[Dict]:
    """Get the next field config, or None if at end."""
    for i, field in enumerate(FIELD_CONFIG):
        if field['name'] == current_name and i + 1 < len(FIELD_CONFIG):
            return FIELD_CONFIG[i + 1]
    return None


def _get_prev_field(current_name: str) -> Optional[Dict]:
    """Get the previous field config, or None if at start."""
    for i, field in enumerate(FIELD_CONFIG):
        if field['name'] == current_name and i > 0:
            return FIELD_CONFIG[i - 1]
    return None


# ============================================================================
# Formatting Helpers
# ============================================================================

def _format_field_prompt(field_name: str, current_value: Any, field_label: str) -> str:
    """Format the prompt message for a field."""
    current_display = current_value if current_value else "Not Set"

    if field_name == UpdateKeyboard.FIELD_PREFERRED_CURRENCY:
        current_display = current_display.upper() if current_display and current_display != "Not Set" else "Not Set"
        return (
            f"<b>{field_label}</b>\n\n"
            f"Current value: <code>{current_display}</code>\n\n"
            "Please enter a 3-letter currency code (e.g., SGD, MYR, USD) or use 'Skip' to keep the current value.\n"
            "Note that this value will be the default currency that your expenses will be displayed in."
        )
    
    return (
        f"<b>{field_label}</b>\n\n"
        f"Current value: <code>{current_display}</code>\n\n"
        f"Please enter your new value:\n\n"
        "<i>Note: this is different from your official Telegram name!</i>"
    )


def _format_summary(update_data: Dict[str, Any], original_user: Dict[str, Any]) -> str:
    """Format the summary of changes."""
    changes = []
    unchanged = []
    
    field_labels = {
        UpdateKeyboard.FIELD_FIRST_NAME: 'First Name',
        UpdateKeyboard.FIELD_LAST_NAME: 'Last Name',
        UpdateKeyboard.FIELD_PREFERRED_CURRENCY: 'Preferred Currency',
    }
    
    for field_name, label in field_labels.items():
        new_value = update_data.get(field_name)
        old_value = original_user.get(field_name) or (
            'SGD' if field_name == UpdateKeyboard.FIELD_PREFERRED_CURRENCY else None
        )
        old_display = old_value or 'Not set'
        
        if new_value is not None and new_value != old_value:
            changes.append(f"<b>{label}:</b> <code>{old_display}</code> → <code>{new_value}</code>")
        else:
            unchanged.append(f"<b>{label}:</b> <code>{old_display}</code>")
    
    message = "<b>Summary of Changes</b>\n\n"
    
    if changes:
        message += "<b>Changed fields:</b>\n"
        message += "".join(f"  • {change}\n" for change in changes)
        message += "\n"
    
    if unchanged:
        message += "<b>Unchanged fields:</b>\n"
        message += "".join(f"  • {field}\n" for field in unchanged)
    
    message += "\nPlease review and confirm your changes."
    return message


# ============================================================================
# Message Helpers
# ============================================================================

async def _cleanup_previous_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Clean up inline keyboard from previous bot message.
    Strategy: Remove keyboard first, fall back to delete.
    """
    message_id = context.user_data.get('last_message_id')
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
        logger.debug(f"Could not remove keyboard, attempting delete: {e}")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            logger.warning(f"Failed to cleanup keyboard for message {message_id}")
    finally:
        context.user_data.pop('last_message_id', None)


async def _send_or_edit_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    keyboard=None
) -> None:
    """Unified message handler - edits for callbacks, sends new for text input."""
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="HTML", reply_markup=keyboard
        )
        context.user_data['last_message_id'] = update.callback_query.message.message_id
    else:
        await _cleanup_previous_keyboard(update, context)
        sent_message = await update.message.reply_text(
            text, parse_mode="HTML", reply_markup=keyboard
        )
        context.user_data['last_message_id'] = sent_message.message_id


def _cleanup_conversation(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cleanup conversation state from user's context."""
    for key in ['original_user', 'update_data', 'conversation_active', 'last_message_id']:
        context.user_data.pop(key, None)


# ============================================================================
# Navigation Helpers
# ============================================================================

async def _show_field_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    field_name: str
) -> int:
    """Show prompt for a field and return its state."""
    field_config = _FIELD_BY_NAME[field_name]
    original_user = context.user_data['original_user']
    
    message = _format_field_prompt(
        field_name,
        original_user.get(field_name),
        field_config['label']
    )
    is_first = (field_name == FIELD_CONFIG[0]['name'])
    keyboard = UpdateKeyboard.get_navigation_keyboard(field_name, is_first=is_first)
    
    await _send_or_edit_message(update, context, message, keyboard)
    return field_config['state']


async def _show_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show summary of changes and return SUMMARY state."""
    message = _format_summary(
        context.user_data['update_data'],
        context.user_data['original_user']
    )
    await _send_or_edit_message(update, context, message, UpdateKeyboard.get_summary_keyboard())
    return UpdateProfileStates.SUMMARY


async def _navigate_to_next(update: Update, context: ContextTypes.DEFAULT_TYPE, current_field: str) -> int:
    """Navigate to the next field or summary."""
    next_field = _get_next_field(current_field)
    if next_field:
        return await _show_field_prompt(update, context, next_field['name'])
    return await _show_summary(update, context)


async def _navigate_to_prev(update: Update, context: ContextTypes.DEFAULT_TYPE, current_field: str) -> int:
    """Navigate to the previous field."""
    prev_field = _get_prev_field(current_field)
    if prev_field:
        return await _show_field_prompt(update, context, prev_field['name'])
    # Already at first field, stay there
    return _FIELD_BY_NAME[current_field]['state']


# ============================================================================
# Conversation Handlers
# ============================================================================

async def start_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the update profile conversation."""
    telegram_user = update.effective_user

    if not telegram_user:
        logger.warning("Received /update command without telegram user information")
        return ConversationHandler.END

    logger.info(f"Starting update profile conversation for user: {telegram_user.id}")

    try:
        async with get_db() as db:
            user = await UserService.get_user_by_id(db, telegram_user.id)

            if not user:
                await update.message.reply_text(
                    "Your profile does not exist. Please use the /start command if you are new to the bot!"
                )
                return ConversationHandler.END
        
        # Initialize conversation state
        context.user_data['original_user'] = user
        context.user_data['update_data'] = {}
        context.user_data['conversation_active'] = True

        # Start with first field
        first_field = FIELD_CONFIG[0]
        message = _format_field_prompt(
            first_field['name'],
            user.get(first_field['name']),
            first_field['label']
        )
        sent_message = await update.message.reply_text(
            message,
            parse_mode="HTML",
            reply_markup=UpdateKeyboard.get_navigation_keyboard(first_field['name'], is_first=True)
        )
        context.user_data['last_message_id'] = sent_message.message_id

        return first_field['state']
        
    except UserNotFoundException:
        logger.warning(f"User with ID {telegram_user.id} not found")
        await update.message.reply_text(
            "Your profile does not exist. Please use the /start command if you are new to the bot!"
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error starting update conversation for user {telegram_user.id}: {e}", exc_info=True)
        await update.message.reply_text(ERROR_MSG)
        return ConversationHandler.END


async def handle_field_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    field_name: str
) -> int:
    """Generic handler for field text input."""
    field_config = _FIELD_BY_NAME[field_name]
    
    # Get and optionally transform input
    user_input = update.message.text.strip()
    if field_config['transform']:
        user_input = field_config['transform'](user_input)
    
    # Validate
    is_valid, error_msg = field_config['validator'](user_input)
    if not is_valid:
        await update.message.reply_text(error_msg)
        return await _show_field_prompt(update, context, field_name)
    
    # Store and navigate to next
    context.user_data['update_data'][field_name] = user_input
    return await _navigate_to_next(update, context, field_name)


async def handle_field_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    current_field: str
) -> int:
    """Handle skip/back/cancel callbacks for field inputs."""
    query = update.callback_query
    await query.answer()

    if not context.user_data.get('conversation_active'):
        await query.edit_message_text(
            "This conversation has expired. Please start a new conversation using the /update command."
        )
        _cleanup_conversation(context)
        return ConversationHandler.END
    
    action, _ = UpdateKeyboard.extract_callback_info(query.data)

    if action == UpdateKeyboard.ACTION_CANCEL:
        return await cancel_update(update, context)
    elif action == UpdateKeyboard.ACTION_SKIP:
        return await _navigate_to_next(update, context, current_field)
    elif action == UpdateKeyboard.ACTION_BACK:
        return await _navigate_to_prev(update, context, current_field)
    
    return _FIELD_BY_NAME[current_field]['state']


# Individual field handlers (thin wrappers for ConversationHandler registration)
async def handle_first_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle first name input or callback."""
    if update.callback_query:
        return await handle_field_callback(update, context, UpdateKeyboard.FIELD_FIRST_NAME)
    return await handle_field_input(update, context, UpdateKeyboard.FIELD_FIRST_NAME)


async def handle_last_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle last name input or callback."""
    if update.callback_query:
        return await handle_field_callback(update, context, UpdateKeyboard.FIELD_LAST_NAME)
    return await handle_field_input(update, context, UpdateKeyboard.FIELD_LAST_NAME)


async def handle_preferred_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle preferred currency input or callback."""
    if update.callback_query:
        return await handle_field_callback(update, context, UpdateKeyboard.FIELD_PREFERRED_CURRENCY)
    return await handle_field_input(update, context, UpdateKeyboard.FIELD_PREFERRED_CURRENCY)


async def handle_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle summary screen callbacks (edit field, confirm, cancel)."""
    query = update.callback_query
    await query.answer()
    
    if not context.user_data.get('conversation_active'):
        await query.edit_message_text(
            "This conversation has expired. Please start a new conversation using the /update command."
        )
        _cleanup_conversation(context)
        return ConversationHandler.END
    
    action, field = UpdateKeyboard.extract_callback_info(query.data)
    
    if action == UpdateKeyboard.ACTION_CANCEL:
        return await cancel_update(update, context)
    
    if action == UpdateKeyboard.ACTION_CONFIRM:
        return await confirm_update(update, context)
    
    if action == UpdateKeyboard.ACTION_EDIT and field in _FIELD_BY_NAME:
        return await _show_field_prompt(update, context, field)
    
    return UpdateProfileStates.SUMMARY


async def confirm_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirm and save the updates."""
    query = update.callback_query
    telegram_user = update.effective_user
    
    try:
        update_data = context.user_data.get('update_data', {})
        original_user = context.user_data.get('original_user', {})
        
        if not update_data or not original_user:
            await query.edit_message_text(
                "Some data is missing. Please start the conversation again using /update."
            )
            _cleanup_conversation(context)
            return ConversationHandler.END
        
        # Filter to only changed fields
        filtered_data = {
            key: value for key, value in update_data.items()
            if value is not None and value != original_user.get(key)
        }
        
        if not filtered_data:
            await query.edit_message_text("No changes to save. Profile update cancelled.")
            _cleanup_conversation(context)
            return ConversationHandler.END
        
        async with get_db() as db:
            await UserService.update_user(db, telegram_user.id, filtered_data)
        
        # Format success message
        changes_list = [
            f"  • {key.replace('_', ' ').title()}: <code>{value}</code>"
            for key, value in filtered_data.items()
        ]
        success_msg = (
            "<b>Profile Updated Successfully!</b>\n\n"
            "The following fields have been updated:\n"
            + "\n".join(changes_list) + "\n\n"
            "Use /profile to view your updated profile."
        )
        
        await query.edit_message_text(success_msg, parse_mode="HTML")
        _cleanup_conversation(context)
        logger.info(f"Profile updated successfully for user: {telegram_user.id}")
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error confirming profile update for user {telegram_user.id}: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)
        _cleanup_conversation(context)
        return ConversationHandler.END


async def cancel_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the update process."""
    message = "Profile update cancelled. No changes were saved."
    
    if update.callback_query:
        await update.callback_query.edit_message_text(message)
    else:
        await update.message.reply_text(message)
    
    _cleanup_conversation(context)
    return ConversationHandler.END


# ============================================================================
# Conversation Handler Factory
# ============================================================================

def create_update_conversation_handler() -> ConversationHandler:
    """Create and return the update profile conversation handler."""
    return ConversationHandler(
        entry_points=[CommandHandler("update", start_update)],
        states={
            UpdateProfileStates.FIRST_NAME: [
                CallbackQueryHandler(
                    handle_first_name,
                    pattern=f"^{UpdateKeyboard.PREFIX}({UpdateKeyboard.ACTION_SKIP}|{UpdateKeyboard.ACTION_BACK}):"
                ),
                CallbackQueryHandler(
                    cancel_update,
                    pattern=f"^{UpdateKeyboard.PREFIX}{UpdateKeyboard.ACTION_CANCEL}$"
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_first_name)
            ],
            UpdateProfileStates.LAST_NAME: [
                CallbackQueryHandler(
                    handle_last_name,
                    pattern=f"^{UpdateKeyboard.PREFIX}({UpdateKeyboard.ACTION_SKIP}|{UpdateKeyboard.ACTION_BACK}):"
                ),
                CallbackQueryHandler(
                    cancel_update,
                    pattern=f"^{UpdateKeyboard.PREFIX}{UpdateKeyboard.ACTION_CANCEL}$"
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_last_name)
            ],
            UpdateProfileStates.PREFERRED_CURRENCY: [
                CallbackQueryHandler(
                    handle_preferred_currency,
                    pattern=f"^{UpdateKeyboard.PREFIX}({UpdateKeyboard.ACTION_SKIP}|{UpdateKeyboard.ACTION_BACK}):"
                ),
                CallbackQueryHandler(
                    cancel_update,
                    pattern=f"^{UpdateKeyboard.PREFIX}{UpdateKeyboard.ACTION_CANCEL}$"
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_preferred_currency)
            ],
            UpdateProfileStates.SUMMARY: [
                CallbackQueryHandler(
                    handle_summary,
                    pattern=f"^{UpdateKeyboard.PREFIX}({UpdateKeyboard.ACTION_EDIT}|{UpdateKeyboard.ACTION_CONFIRM}|{UpdateKeyboard.ACTION_CANCEL})"
                )
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_update)],
        conversation_timeout=CONVERSATION_TIMEOUT,
        name="update_profile",
        per_chat=True,
        per_user=True
    )
