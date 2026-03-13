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
from bot.keyboards import GroupKeyboard
from .states import CreateGroupStates
from utils import validate_currency_code, validate_group_name
from services import GroupService, UserService
from infrastructure import get_db
from bot.utils import validate_chat_type
from models import GroupMemberRole
from shared import UserAlreadyExistsException
import logging


logger = logging.getLogger(__name__)


ERROR_MSG = "An unexpected error has occured while creating the group. Please try again later."
CONVERSATION_TIMEOUT = 600

# Field configuration for group creation
FIELD_CONFIG = [
    {
        'name': 'name',
        'label': 'Group Name',
        'state': CreateGroupStates.NAME,
        'validator': validate_group_name
    },
    {
        'name': 'description',
        'label': 'Group Description',
        'state': CreateGroupStates.DESCRIPTION,
        'validator': None
    },
    {
        'name': 'default_currency',
        'label': 'Default Currency',
        'state': CreateGroupStates.CURRENCY,
        'validator': validate_currency_code
    }
]

_FIELD_BY_NAME = {f['name']: f for f in FIELD_CONFIG}
_FIELD_BY_STATE = {f['state']: f for f in FIELD_CONFIG}


#============================================================================
# Helper functions
#============================================================================
def _get_next_field(current_field: str) -> Optional[Dict]:
    """Get the next field config, or None if at end."""
    for i, field in enumerate(FIELD_CONFIG):
        if field['name'] == current_field and i + 1 < len(FIELD_CONFIG):
            return FIELD_CONFIG[i + 1]
    return None


def _get_prev_field(current_field: str) -> Optional[Dict]:
    """Get the previous field config, or None if at start."""
    for i, field in enumerate(FIELD_CONFIG):
        if field['name'] == current_field and i > 0:
            return FIELD_CONFIG[i - 1]
    return None


def _is_field_skippable(field_name: str) -> bool:
    """Check if a field can be skipped (i.e., is optional)."""
    # Only description is optional/skippable
    return field_name == 'description'

def _format_field_prompt(field_name: str, field_label: str) -> str:
    """Format the prompt message for a field input."""
    if field_name == 'default_currency':
        return (
            f"<b>{field_label}</b>\n\n"
            "Please enter a 3-letter currency code (e.g., SGD, MYR, USD).\n"
            "This will be the default currency for your expenses in this group."
        )
    elif field_name == 'description':
        return (
            f"<b>{field_label}</b>\n\n"
            "Enter a description for your group (Optional).\n"
            "Press 'Skip' to not enter a description."
        )
    
    return (
        f"<b>{field_label}</b>\n\n"
        f"Please enter your {field_label.lower()}:"
    )

def _format_summary(group_data: Dict[str, Any]) -> str:
    """Format the summary of group creation."""
    name = group_data.get('name', 'Not set')
    description = group_data.get('description') or 'Not set'
    currency = group_data.get('default_currency', 'SGD').upper()
    simplify = group_data.get('simplify_debts', True)
    simplify_label = "Simplified ✓" if simplify else "Raw Debts"

    return (
        "<b>Group Creation Summary</b>\n\n"
        f"<b>Name:</b> {name}\n"
        f"<b>Description:</b> {description}\n"
        f"<b>Default Currency:</b> {currency}\n"
        f"<b>Debt View Default:</b> {simplify_label}\n\n"
        "Please review and confirm to create the group."
    )


async def _cleanup_previous_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clean up inline keyboard from previous bot message."""
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
    except Exception:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass
    finally:
        context.user_data.pop('last_message_id', None)


async def _send_or_edit_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    keyboard=None
) -> None:
    """Unified message handler."""
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
    """Cleanup conversation state."""
    for key in ['group_data', 'conversation_active', 'last_message_id', 'group_creation_msg_id']:
        context.user_data.pop(key, None)


async def _show_field_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    field_name: str
) -> int:
    """Show prompt for a field and return its state."""
    field_config = _FIELD_BY_NAME[field_name]
    message = _format_field_prompt(field_name, field_config['label'])
    is_first = (field_name == FIELD_CONFIG[0]['name'])
    show_skip = _is_field_skippable(field_name)
    keyboard = GroupKeyboard.get_navigation_keyboard(
        field_name,
        is_first=is_first,
        show_skip=show_skip
    )
    
    await _send_or_edit_message(update, context, message, keyboard)
    return field_config['state']


async def _show_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show summary and return SUMMARY state."""
    message = _format_summary(context.user_data['group_data'])
    await _send_or_edit_message(update, context, message, GroupKeyboard.get_confirm_keyboard("create", 0))
    return CreateGroupStates.SUMMARY


async def _show_simplify_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show the debt simplification preference step."""
    message = (
        "<b>Debt View Default</b>\n\n"
        "<b>Simplified</b> — minimises the number of payments needed to settle all debts "
        "(recommended for most groups).\n\n"
        "<b>Raw Debts</b> — shows every individual debt exactly as recorded.\n\n"
        "You can change this later in the group settings."
    )
    keyboard = GroupKeyboard.get_simplify_debts_keyboard()
    await _send_or_edit_message(update, context, message, keyboard)
    return CreateGroupStates.SIMPLIFY_DEBTS


async def _navigate_to_next(update: Update, context: ContextTypes.DEFAULT_TYPE, current_field: str) -> int:
    """Navigate to the next field; insert simplify_debts step after currency."""
    if current_field == 'default_currency':
        return await _show_simplify_prompt(update, context)
    next_field = _get_next_field(current_field)
    if next_field:
        return await _show_field_prompt(update, context, next_field['name'])
    return await _show_summary(update, context)


#============================================================================
# Conversation Handlers
#============================================================================
@validate_chat_type("group", "supergroup")
async def start_create_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the create group conversation."""
    telegram_user = update.effective_user
    if not telegram_user:
        logger.warning("Received /create_group command without telegram user information")
        return ConversationHandler.END
    
    logger.info(f"Starting create group conversation for user: {telegram_user.id} @{telegram_user.username}")

    # Auto-create user account if it doesn't exist
    try:
        async with get_db() as db:
            user = await UserService.get_user_by_id(db, telegram_user.id)
            
            if not user:
                # Create the new user if user does not already exist
                logger.info(f"Auto-creating user account for new user: {telegram_user.id}")
                user = await UserService.create_user(
                    db,
                    telegram_user.id,
                    telegram_user.username,
                    telegram_user.first_name,
                    telegram_user.last_name
                )
                logger.info(f"User account created successfully for user: {telegram_user.id}")
    except UserAlreadyExistsException:
        # User was created between our check and creation (race condition)
        logger.debug(f"User {telegram_user.id} already exists, continuing with group creation")
    except Exception as e:
        logger.error(f"Error auto-creating user account for user {telegram_user.id}: {e}", exc_info=True)
        # Continue with group creation even if user creation fails
        # The group creation will fail later if the user truly doesn't exist

    context.user_data['conversation_active'] = True
    context.user_data['group_data'] = {}

    first_field = FIELD_CONFIG[0]
    return await _show_field_prompt(update, context, first_field['name'])

async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle group name input."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if not context.user_data.get('conversation_active'):
            await query.answer("This is not your interaction.", show_alert=True)
            return ConversationHandler.END
        action, _ = GroupKeyboard.extract_callback_info(query.data)

        if action == GroupKeyboard.ACTION_CANCEL:
            return await cancel_group_creation(update, context)

        return CreateGroupStates.NAME
    
    # Handle text input
    field_config = _FIELD_BY_NAME['name']
    user_input = update.message.text.strip()
    is_valid, error_msg = field_config['validator'](user_input)

    if not is_valid:
        logger.warning(f"Invalid group name input by user: {update.effective_user.id}, error: {error_msg}")
        await update.message.reply_text(error_msg)
        return CreateGroupStates.NAME
    
    context.user_data['group_data']['name'] = user_input
    return await _navigate_to_next(update, context, 'name')

async def handle_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Description input."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if not context.user_data.get('conversation_active'):
            await query.answer("This is not your interaction.", show_alert=True)
            return ConversationHandler.END
        action, _ = GroupKeyboard.extract_callback_info(query.data)
        
        if action == GroupKeyboard.ACTION_CANCEL:
            return await cancel_group_creation(update, context)
        elif action == GroupKeyboard.ACTION_BACK:
            prev_field = _get_prev_field('description')
            if prev_field:
                return await _show_field_prompt(update, context, prev_field['name'])
            return CreateGroupStates.DESCRIPTION
        elif action == GroupKeyboard.ACTION_SKIP:
            # Skip description (set to None) and move to next field
            context.user_data['group_data']['description'] = None
            return await _navigate_to_next(update, context, 'description')
        
        return CreateGroupStates.DESCRIPTION
    
    # Handle text input
    user_input = update.message.text.strip()
    context.user_data['group_data']['description'] = user_input
    return await _navigate_to_next(update, context, 'description')

async def handle_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle currency input."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if not context.user_data.get('conversation_active'):
            await query.answer("This is not your interaction.", show_alert=True)
            return ConversationHandler.END
        action, _ = GroupKeyboard.extract_callback_info(query.data)
        
        if action == GroupKeyboard.ACTION_CANCEL:
            return await cancel_group_creation(update, context)
        elif action == GroupKeyboard.ACTION_BACK:
            prev_field = _get_prev_field('default_currency')
            if prev_field:
                return await _show_field_prompt(update, context, prev_field['name'])
            return CreateGroupStates.CURRENCY
        # Currency is required, so no SKIP action allowed
        
        return CreateGroupStates.CURRENCY
    
    field_config = _FIELD_BY_NAME['default_currency']
    user_input = update.message.text.strip().upper()
    is_valid, error_msg = field_config['validator'](user_input)
    if not is_valid:
        logger.warning(f"Invalid currency input by user: {update.effective_user.id}, error: {error_msg}")
        await update.message.reply_text(error_msg)
        return CreateGroupStates.CURRENCY
    
    context.user_data['group_data']['default_currency'] = user_input
    return await _navigate_to_next(update, context, 'default_currency')

async def handle_simplify_debts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle debt simplification preference selection."""
    query = update.callback_query
    await query.answer()

    if not context.user_data.get('conversation_active'):
        await query.answer("This is not your interaction.", show_alert=True)
        return ConversationHandler.END

    action, data = GroupKeyboard.extract_callback_info(query.data)

    if action == GroupKeyboard.ACTION_CANCEL:
        return await cancel_group_creation(update, context)

    if action == GroupKeyboard.ACTION_BACK:
        # Back to currency field
        return await _show_field_prompt(update, context, 'default_currency')

    if action == GroupKeyboard.ACTION_SIMPLIFY_ON:
        context.user_data['group_data']['simplify_debts'] = True
        return await _show_summary(update, context)

    if action == GroupKeyboard.ACTION_SIMPLIFY_OFF:
        context.user_data['group_data']['simplify_debts'] = False
        return await _show_summary(update, context)

    return CreateGroupStates.SIMPLIFY_DEBTS


async def handle_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirm and create the group."""
    query = update.callback_query
    await query.answer()

    if not context.user_data.get('conversation_active'):
        await query.answer("This is not your interaction.", show_alert=True)
        return ConversationHandler.END

    telegram_user = update.effective_user

    # Extract action from callback
    action, _ = GroupKeyboard.extract_callback_info(query.data)
    
    if action == GroupKeyboard.ACTION_CANCEL:
        return await cancel_group_creation(update, context)
    
    # Handle confirm action - create the group
    if action != GroupKeyboard.ACTION_CONFIRM:
        return CreateGroupStates.SUMMARY

    try:
        group_data = context.user_data.get('group_data', {})
        if not group_data or 'name' not in group_data or 'default_currency' not in group_data:
            await query.edit_message_text("Missing required data. Please start again using /newgroup command.")
            _cleanup_conversation(context)
            return ConversationHandler.END
        
        async with get_db() as db:
            group = await GroupService.create_group(
                db,
                name=group_data.get('name'),
                description=group_data.get('description'),
                default_currency=group_data.get('default_currency'),
                simplify_debts=group_data.get('simplify_debts', True),
                telegram_chat_id=update.effective_chat.id,
                created_by=telegram_user.id
            )
        
        success_message = (
            "<b>Group created successfully!</b>\n\n"
            f"<b>Name:</b> {group.get('name')}\n\n"
            "To all members in this group chat, you are invited to join this group to start splitting your bills!\n"
            "To join this group, simply press the button below:"
        )

        await query.edit_message_text(
            success_message,
            parse_mode="HTML",
            reply_markup=GroupKeyboard.get_join_group_keyboard(group.get('id'))
        )
        _cleanup_conversation(context)
        logger.info(f"Group {group['id']} created successfully by user: {telegram_user.id}")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"An unexpected error occurred while creating group: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)
        _cleanup_conversation(context)
        return ConversationHandler.END
    
async def cancel_group_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the group creation process."""
    message = "Group creation cancelled. No changes were saved."

    if update.callback_query:
        await update.callback_query.edit_message_text(message)
    else:
        await update.message.reply_text(message)
    
    _cleanup_conversation(context)
    return ConversationHandler.END

def create_group_conversation_handler() -> ConversationHandler:
    """Create and return the group creation conversation handler."""
    return ConversationHandler(
        entry_points=[CommandHandler("newgroup", start_create_group)],
        states={
            CreateGroupStates.NAME: [
                CallbackQueryHandler(handle_name, pattern=f"^{GroupKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)
            ],
            CreateGroupStates.DESCRIPTION: [
                CallbackQueryHandler(handle_description, pattern=f"^{GroupKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_description)
            ],
            CreateGroupStates.CURRENCY: [
                CallbackQueryHandler(handle_currency, pattern=f"^{GroupKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_currency)
            ],
            CreateGroupStates.SIMPLIFY_DEBTS: [
                CallbackQueryHandler(handle_simplify_debts, pattern=f"^{GroupKeyboard.PREFIX}")
            ],
            CreateGroupStates.SUMMARY: [
                CallbackQueryHandler(handle_summary, pattern=f"^{GroupKeyboard.PREFIX}")
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_group_creation)],
        conversation_timeout=CONVERSATION_TIMEOUT,
        name="create_group",
        per_chat=True,
        per_user=True
    )
