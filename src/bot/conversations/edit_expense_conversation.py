import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.keyboards import ExpenseKeyboard
from bot.utils import get_display_name, h
from infrastructure import get_db
from models import CATEGORY_DISPLAY, ExpenseCategory, ExpenseSplitType
from services import ExpenseService, GroupService, SplitCalculator
from shared import (
    ExpenseNotEditableException,
    ExpenseNotFoundException,
    UnauthorizedActionException,
)
from utils import (
    validate_currency_code,
    validate_custom_share,
    validate_exact_split_amount,
    validate_expense_amount,
    validate_expense_description,
    validate_percentage_split,
)

from .expense_conversation_helpers import (
    ParticipantValueCollector,
    handle_participant_value,
    prompt_participant_value,
)
from .expense_conversation_helpers import (
    cleanup_conversation as _shared_cleanup_conversation,
)
from .expense_conversation_helpers import (
    cleanup_previous_keyboard as _shared_cleanup_previous_keyboard,
)
from .expense_conversation_helpers import (
    send_or_edit_message as _shared_send_or_edit_message,
)
from .expense_conversation_helpers import (
    send_validation_error as _shared_send_validation_error,
)
from .states import EditExpenseStates

logger = logging.getLogger(__name__)

ERROR_MSG = "An unexpected error has occurred while editing the expense. Please try again later."
CONVERSATION_TIMEOUT = 600  # 10 minutes

FIELD_LABELS = {
    "description": "Description",
    "amount": "Amount",
    "currency": "Currency",
    "expense_date": "Date",
    "payer_id": "Payer",
    "participant_ids": "Participants",
    "split_type": "Split type",
    "category": "Category",
}


# ===================================================================================
# Category Display Helper
# ===================================================================================
def _format_category_label(v) -> str:
    """Return a display label for a raw category value (or None)."""
    if v is None:
        return "None"
    try:
        return CATEGORY_DISPLAY[ExpenseCategory(v)]
    except (ValueError, KeyError):
        return str(v)


# ===================================================================================
# Helper Functions
# ===================================================================================
_MESSAGE_KEY = "edit_last_message_id"
_CLEANUP_KEYS = [
    "edit_expense_id",
    "edit_original_data",
    "edit_changes",
    "edit_group_members",
    "edit_selected_participants",
    "edit_exact_amounts_pending",
    "edit_percentages_pending",
    "edit_custom_shares_pending",
    "edit_conversation_active",
    "edit_last_message_id",
]


def _cleanup_conversation(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cleanup conversation state."""
    _shared_cleanup_conversation(context, _CLEANUP_KEYS)


async def _cleanup_previous_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clean up inline keyboard from previous bot message."""
    await _shared_cleanup_previous_keyboard(update, context, _MESSAGE_KEY)


async def _send_or_edit_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, keyboard=None
) -> None:
    """Unified message handler for both callback queries and text messages."""
    await _shared_send_or_edit_message(update, context, text, _MESSAGE_KEY, keyboard)


async def _send_validation_error(
    update: Update, context: ContextTypes.DEFAULT_TYPE, error_msg: str, keyboard=None
) -> None:
    """Send validation error message."""
    await _shared_send_validation_error(update, context, error_msg, _MESSAGE_KEY, keyboard)


def _get_effective_value(context: ContextTypes.DEFAULT_TYPE, field: str) -> Any:
    """Get the effective value for a field (changed value or original)."""
    changes = context.user_data.get("edit_changes", {})
    original = context.user_data.get("edit_original_data", {})
    return changes.get(field, original.get(field))


def _has_changes(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if there are any pending changes."""
    return bool(context.user_data.get("edit_changes", {}))


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
                db, expense_data["group_id"]
            )

        # Initialize conversation state
        context.user_data["edit_conversation_active"] = True
        context.user_data["edit_expense_id"] = expense_id
        context.user_data["edit_original_data"] = expense_data
        context.user_data["edit_changes"] = {}
        context.user_data["edit_group_members"] = group_members
        context.user_data["edit_selected_participants"] = [
            p["user_id"] for p in expense_data.get("participants", [])
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
    original = context.user_data.get("edit_original_data", {})
    changes = context.user_data.get("edit_changes", {})

    # Get effective values
    description = h(changes.get("description", original.get("description"))) or "No description"
    amount = changes.get("amount", original.get("amount", 0))
    currency = changes.get("currency", original.get("currency", "SGD"))
    category_val = changes.get("category", original.get("category"))
    category_display = ""
    if category_val:
        category_display = f"\n<b>Category:</b> {_format_category_label(category_val)}"

    # Format the current state message
    message = (
        "<b>Edit Expense</b>\n\n"
        f"<b>Current:</b> {description}\n"
        f"<b>Amount:</b> {currency} {amount}"
        f"{category_display}\n\n"
        "Select a field to edit:"
    )

    # Show pending changes if any
    if changes:
        members = context.user_data.get("edit_group_members", [])
        change_lines = []
        for field, new_value in changes.items():
            if field == "split_data":
                continue
            old_value = original.get(field)
            label = FIELD_LABELS.get(field, field)

            if field == "split_type":
                new_value = new_value.value if hasattr(new_value, "value") else new_value
                old_value = old_value.value if hasattr(old_value, "value") else old_value
            elif field == "payer_id":
                old_m = next((m for m in members if m.get("user_id") == old_value), {})
                new_m = next((m for m in members if m.get("user_id") == new_value), {})
                old_value = get_display_name(old_m) if old_m else old_value
                new_value = get_display_name(new_m) if new_m else new_value
            elif field == "participant_ids":
                old_names = [
                    get_display_name(
                        next((m for m in members if m.get("user_id") == p["user_id"]), {})
                    )
                    for p in original.get("participants", [])
                ]
                new_names = [
                    get_display_name(next((m for m in members if m.get("user_id") == pid), {}))
                    for pid in new_value
                ]
                old_value = ", ".join(old_names) or "—"
                new_value = ", ".join(new_names) or "—"
            elif field == "expense_date" and hasattr(new_value, "isoformat"):
                new_value = new_value.isoformat()
            elif field == "category":
                old_value = _format_category_label(old_value)
                new_value = _format_category_label(new_value)
            elif field == "description":
                old_value = h(old_value)
                new_value = h(new_value)

            change_lines.append(f"  {label}: {old_value} → {new_value}")

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
        elif data == ExpenseKeyboard.FIELD_CATEGORY:
            return await _prompt_edit_category(update, context)

    return EditExpenseStates.SELECT_FIELD


# ===================================================================================
# State: EDIT_DESCRIPTION
# ===================================================================================
async def _prompt_edit_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new description."""
    current = h(_get_effective_value(context, "description")) or "No description"

    message = (
        "<b>Edit Description</b>\n\n"
        f"Current: {current}\n\n"
        "Enter new description (or Skip to clear):"
    )
    keyboard = ExpenseKeyboard.get_field_navigation_keyboard(
        ExpenseKeyboard.FIELD_DESCRIPTION,
        show_skip=True,
        back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT,
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
            context.user_data["edit_changes"]["description"] = None
            return await _show_edit_menu(update, context)

        return EditExpenseStates.EDIT_DESCRIPTION

    # Handle text input
    is_valid, error_msg = validate_expense_description(update.message.text)
    if not is_valid:
        await _send_validation_error(
            update,
            context,
            error_msg,
            ExpenseKeyboard.get_field_navigation_keyboard(
                ExpenseKeyboard.FIELD_DESCRIPTION,
                show_skip=True,
                back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT,
            ),
        )
        return EditExpenseStates.EDIT_DESCRIPTION

    context.user_data["edit_changes"]["description"] = update.message.text.strip()
    return await _show_edit_menu(update, context)


# ===================================================================================
# State: EDIT_AMOUNT
# ===================================================================================
async def _prompt_edit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new amount."""
    current = _get_effective_value(context, "amount")
    currency = _get_effective_value(context, "currency")

    message = f"<b>Edit Amount</b>\n\nCurrent: {currency} {current}\n\nEnter new amount:"
    keyboard = ExpenseKeyboard.get_field_navigation_keyboard(
        ExpenseKeyboard.FIELD_AMOUNT, back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT
    )
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
            update,
            context,
            error_msg,
            ExpenseKeyboard.get_field_navigation_keyboard(
                ExpenseKeyboard.FIELD_AMOUNT, back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT
            ),
        )
        return EditExpenseStates.EDIT_AMOUNT

    context.user_data["edit_changes"]["amount"] = amount

    # Check if we need to re-enter split data for EXACT split type
    split_type = _get_effective_value(context, "split_type")
    if isinstance(split_type, str):
        split_type = ExpenseSplitType(split_type)

    if split_type == ExpenseSplitType.EXACT:
        # Need to re-enter exact amounts since total changed
        context.user_data["edit_exact_amounts_pending"] = {"amounts": {}, "current_index": 0}
        return await _prompt_exact_amounts(update, context)

    return await _show_edit_menu(update, context)


# ===================================================================================
# State: EDIT_CURRENCY
# ===================================================================================
async def _prompt_edit_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new currency."""
    current = _get_effective_value(context, "currency")

    message = (
        "<b>Edit Currency</b>\n\n"
        f"Current: {current}\n\n"
        "Enter new currency code (e.g., SGD, USD, MYR):"
    )
    keyboard = ExpenseKeyboard.get_field_navigation_keyboard(
        ExpenseKeyboard.FIELD_CURRENCY, back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT
    )
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
            update,
            context,
            error_msg,
            ExpenseKeyboard.get_field_navigation_keyboard(
                ExpenseKeyboard.FIELD_CURRENCY, back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT
            ),
        )
        return EditExpenseStates.EDIT_CURRENCY

    context.user_data["edit_changes"]["currency"] = currency_code
    return await _show_edit_menu(update, context)


# ===================================================================================
# State: EDIT_DATE
# ===================================================================================
async def _prompt_edit_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new date."""
    current = _get_effective_value(context, "expense_date")

    message = (
        "<b>Edit Date</b>\n\n"
        f"Current: {current}\n\n"
        "Enter new date (YYYY-MM-DD format):\n"
        "<i>Example: 2025-01-20</i>\n\n"
        "Or type 'today' to use today's date."
    )
    keyboard = ExpenseKeyboard.get_field_navigation_keyboard(
        ExpenseKeyboard.FIELD_DATE, back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT
    )
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

    if date_text == "today":
        new_date = date.today()
    else:
        try:
            new_date = datetime.strptime(date_text, "%Y-%m-%d").date()
        except ValueError:
            await _send_validation_error(
                update,
                context,
                "Invalid date format. Please use YYYY-MM-DD (e.g., 2025-01-20) or type 'today'.",
                ExpenseKeyboard.get_field_navigation_keyboard(
                    ExpenseKeyboard.FIELD_DATE, back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT
                ),
            )
            return EditExpenseStates.EDIT_DATE

    context.user_data["edit_changes"]["expense_date"] = new_date
    return await _show_edit_menu(update, context)


# ===================================================================================
# State: EDIT_PAYER
# ===================================================================================
async def _prompt_edit_payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new payer selection."""
    members = context.user_data.get("edit_group_members", [])
    current_payer_id = _get_effective_value(context, "payer_id")

    message = "<b>Edit Payer</b>\n\nSelect who paid for this expense:"
    keyboard = ExpenseKeyboard.get_payer_selection_keyboard(
        members, current_payer_id=current_payer_id, back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT
    )
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
        context.user_data["edit_changes"]["payer_id"] = payer_id
        return await _show_edit_menu(update, context)

    return EditExpenseStates.EDIT_PAYER


# ===================================================================================
# State: EDIT_PARTICIPANTS
# ===================================================================================
async def _prompt_edit_participants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for participant selection."""
    members = context.user_data.get("edit_group_members", [])
    selected = context.user_data.get("edit_selected_participants", [])

    message = (
        "<b>Edit Participants</b>\n\n"
        "Select all participants who are splitting this expense.\n"
        "<i>Tap to select/deselect, then press Done.</i>"
    )
    keyboard = ExpenseKeyboard.get_participant_selection_keyboard(
        members, selected, back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT
    )
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
        original = context.user_data.get("edit_original_data", {})
        context.user_data["edit_selected_participants"] = [
            p["user_id"] for p in original.get("participants", [])
        ]
        return await _show_edit_menu(update, context)

    if action == ExpenseKeyboard.ACTION_TOGGLE_PARTICIPANT:
        user_id = int(data)
        selected = context.user_data.get("edit_selected_participants", [])

        if user_id in selected:
            selected.remove(user_id)
        else:
            selected.append(user_id)

        context.user_data["edit_selected_participants"] = selected
        return await _prompt_edit_participants(update, context)

    if action == ExpenseKeyboard.ACTION_DONE_PARTICIPANTS:
        selected = context.user_data.get("edit_selected_participants", [])
        if not selected:
            await query.answer("Please select at least one participant.", show_alert=True)
            return EditExpenseStates.EDIT_PARTICIPANTS

        context.user_data["edit_changes"]["participant_ids"] = selected

        # Check if we need to re-enter split data
        split_type = _get_effective_value(context, "split_type")
        if isinstance(split_type, str):
            split_type = ExpenseSplitType(split_type)

        if split_type == ExpenseSplitType.EQUAL:
            # Auto-recalculate for equal split
            return await _show_edit_menu(update, context)
        else:
            # Need to re-enter split values
            if split_type == ExpenseSplitType.EXACT:
                context.user_data["edit_exact_amounts_pending"] = {
                    "amounts": {},
                    "current_index": 0,
                }
                return await _prompt_exact_amounts(update, context)
            elif split_type == ExpenseSplitType.PERCENTAGE:
                context.user_data["edit_percentages_pending"] = {
                    "percentages": {},
                    "current_index": 0,
                }
                return await _prompt_percentages(update, context)
            elif split_type == ExpenseSplitType.CUSTOM:
                context.user_data["edit_custom_shares_pending"] = {"shares": {}, "current_index": 0}
                return await _prompt_custom_shares(update, context)

        return await _show_edit_menu(update, context)

    return EditExpenseStates.EDIT_PARTICIPANTS


# ===================================================================================
# State: EDIT_SPLIT_TYPE
# ===================================================================================
async def _prompt_edit_split_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for split type selection."""
    current = _get_effective_value(context, "split_type")
    if hasattr(current, "value"):
        current = current.value

    message = "<b>Edit Split Type</b>\n\nSelect how to split this expense:"
    keyboard = ExpenseKeyboard.get_split_type_keyboard(
        current_split_type=current, back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT
    )
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
        context.user_data["edit_changes"]["split_type"] = split_type

        if split_type == ExpenseSplitType.EQUAL:
            return await _show_edit_menu(update, context)
        elif split_type == ExpenseSplitType.EXACT:
            context.user_data["edit_exact_amounts_pending"] = {"amounts": {}, "current_index": 0}
            return await _prompt_exact_amounts(update, context)
        elif split_type == ExpenseSplitType.PERCENTAGE:
            context.user_data["edit_percentages_pending"] = {"percentages": {}, "current_index": 0}
            return await _prompt_percentages(update, context)
        elif split_type == ExpenseSplitType.CUSTOM:
            context.user_data["edit_custom_shares_pending"] = {"shares": {}, "current_index": 0}
            return await _prompt_custom_shares(update, context)

    return EditExpenseStates.EDIT_SPLIT_TYPE


# ===================================================================================
# State: EDIT_CATEGORY
# ===================================================================================
async def _prompt_edit_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for a new category selection."""
    current_val = _get_effective_value(context, "category")
    if current_val:
        try:
            current_label = CATEGORY_DISPLAY[ExpenseCategory(current_val)]
        except (ValueError, KeyError):
            current_label = current_val
    else:
        current_label = "None"

    message = (
        "<b>Edit Category</b>\n\n"
        f"Current category: {current_label}\n\n"
        "Select a new category, or Skip to keep it unchanged.\n"
        "Use 'Remove Category' to clear it."
    )
    keyboard = ExpenseKeyboard.get_category_picker_keyboard(show_remove=True)
    await _send_or_edit_message(update, context, message, keyboard)
    return EditExpenseStates.EDIT_CATEGORY


async def handle_edit_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle category selection during edit."""
    query = update.callback_query
    await query.answer()

    action, data = ExpenseKeyboard.extract_callback_info(query.data)

    if action == ExpenseKeyboard.ACTION_CANCEL:
        return await cancel_edit(update, context)
    if action == ExpenseKeyboard.ACTION_BACK:
        return await _show_edit_menu(update, context)
    if action == ExpenseKeyboard.ACTION_SKIP:
        return await _show_edit_menu(update, context)
    if action == ExpenseKeyboard.ACTION_SELECT_CATEGORY:
        if data == "none":
            context.user_data["edit_changes"]["category"] = None
        else:
            context.user_data["edit_changes"]["category"] = data
        return await _show_edit_menu(update, context)

    return EditExpenseStates.EDIT_CATEGORY


# ===================================================================================
# State: ENTER_EXACT_AMOUNTS
# ===================================================================================
def _exact_amounts_participant_ids(context: ContextTypes.DEFAULT_TYPE) -> list:
    participant_ids = context.user_data.get("edit_selected_participants", [])
    if "participant_ids" in context.user_data.get("edit_changes", {}):
        participant_ids = context.user_data["edit_changes"]["participant_ids"]
    return participant_ids


def _exact_amounts_validate(context, text, already_allocated):
    total_amount = Decimal(str(_get_effective_value(context, "amount")))
    return validate_exact_split_amount(text, total_amount, already_allocated)


def _exact_amounts_build_prompt(context, current_name, current_index, total_count, pending):
    amount = _get_effective_value(context, "amount")
    currency = _get_effective_value(context, "currency")
    entered_so_far = sum(pending["amounts"].values())
    remaining = Decimal(str(amount)) - entered_so_far
    return (
        f"<b>Enter Exact Amounts</b>\n\n"
        f"Total: {currency} {amount}\n"
        f"Remaining: {currency} {remaining}\n\n"
        f"<b>Enter amount for {current_name}:</b>\n"
        f"<i>({current_index + 1} of {total_count} participants)</i>"
    )


def _exact_amounts_build_error(context, error_msg, pending):
    total_amount = Decimal(str(_get_effective_value(context, "amount")))
    currency = _get_effective_value(context, "currency")
    already_allocated = sum(pending.get("amounts", {}).values())
    remaining = total_amount - already_allocated
    return (
        f"{error_msg}\n\n"
        f"Total: {currency} {total_amount}\n"
        f"Already allocated: {currency} {already_allocated}\n"
        f"Remaining: {currency} {remaining}"
    )


def _exact_amounts_check_completion(context, values_list):
    total_entered = sum(values_list)
    amount = _get_effective_value(context, "amount")
    currency = _get_effective_value(context, "currency")
    if abs(total_entered - Decimal(str(amount))) > Decimal("0.01"):
        return (
            f"<b>Amounts don't match!</b>\n\n"
            f"Total expense: {currency} {amount}\n"
            f"Sum of amounts entered: {currency} {total_entered}\n\n"
            "Please re-enter the amounts."
        )
    return None


async def _exact_amounts_on_complete(update, context, values_list):
    context.user_data["edit_changes"]["split_data"] = {"amounts": values_list}
    return await _show_edit_menu(update, context)


_EXACT_AMOUNTS_CONFIG = ParticipantValueCollector(
    pending_key="edit_exact_amounts_pending",
    values_key="amounts",
    message_key=_MESSAGE_KEY,
    collecting_state=EditExpenseStates.ENTER_EXACT_AMOUNTS,
    back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT,
    get_participant_ids=_exact_amounts_participant_ids,
    get_members=lambda context: context.user_data.get("edit_group_members", []),
    validate=_exact_amounts_validate,
    build_keyboard=lambda: ExpenseKeyboard.get_field_navigation_keyboard(
        "exact", back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT
    ),
    build_prompt_text=_exact_amounts_build_prompt,
    build_error_text=_exact_amounts_build_error,
    check_completion=_exact_amounts_check_completion,
    on_complete=_exact_amounts_on_complete,
    on_back_to_start=lambda update, context: _show_edit_menu(update, context),
    cancel_fn=lambda update, context: cancel_edit(update, context),
)


async def _prompt_exact_amounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for exact amounts for each participant."""
    return await prompt_participant_value(update, context, _EXACT_AMOUNTS_CONFIG)


async def handle_exact_amounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle exact amount input."""
    return await handle_participant_value(update, context, _EXACT_AMOUNTS_CONFIG)


# ===================================================================================
# State: ENTER_PERCENTAGES
# ===================================================================================
def _percentages_participant_ids(context: ContextTypes.DEFAULT_TYPE) -> list:
    participant_ids = context.user_data.get("edit_selected_participants", [])
    if "participant_ids" in context.user_data.get("edit_changes", {}):
        participant_ids = context.user_data["edit_changes"]["participant_ids"]
    return participant_ids


def _percentages_validate(context, text, already_allocated):
    return validate_percentage_split(text, already_allocated)


def _percentages_build_prompt(context, current_name, current_index, total_count, pending):
    amount = _get_effective_value(context, "amount")
    currency = _get_effective_value(context, "currency")
    entered_so_far = sum(pending["percentages"].values())
    remaining = Decimal("100") - entered_so_far
    return (
        f"<b>Enter Percentages</b>\n\n"
        f"Total expense: {currency} {amount}\n"
        f"Remaining: {remaining}%\n\n"
        f"<b>Enter percentage for {current_name}:</b>\n"
        f"<i>({current_index + 1} of {total_count} participants)</i>\n"
        f"<i>Example: 25 or 33.33</i>"
    )


def _percentages_build_error(context, error_msg, pending):
    already_allocated = sum(pending.get("percentages", {}).values())
    remaining = Decimal("100") - already_allocated
    return (
        f"⚠️ {error_msg}\n\n"
        f"<b>Enter Percentages</b>\n\n"
        f"Already allocated: {already_allocated}%\n"
        f"Remaining: {remaining}%"
    )


def _percentages_check_completion(context, values_list):
    total_entered = sum(values_list)
    if abs(total_entered - Decimal("100")) > Decimal("0.01"):
        return (
            f"<b>Percentages don't add up!</b>\n\n"
            f"Total: 100%\n"
            f"Sum entered: {total_entered}%\n\n"
            "Please re-enter the percentages."
        )
    return None


async def _percentages_on_complete(update, context, values_list):
    context.user_data["edit_changes"]["split_data"] = {"percentages": values_list}
    return await _show_edit_menu(update, context)


_PERCENTAGES_CONFIG = ParticipantValueCollector(
    pending_key="edit_percentages_pending",
    values_key="percentages",
    message_key=_MESSAGE_KEY,
    collecting_state=EditExpenseStates.ENTER_PERCENTAGES,
    back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT,
    get_participant_ids=_percentages_participant_ids,
    get_members=lambda context: context.user_data.get("edit_group_members", []),
    validate=_percentages_validate,
    build_keyboard=lambda: ExpenseKeyboard.get_field_navigation_keyboard(
        "percentage", back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT
    ),
    build_prompt_text=_percentages_build_prompt,
    build_error_text=_percentages_build_error,
    check_completion=_percentages_check_completion,
    on_complete=_percentages_on_complete,
    on_back_to_start=lambda update, context: _show_edit_menu(update, context),
    cancel_fn=lambda update, context: cancel_edit(update, context),
)


async def _prompt_percentages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for percentages for each participant."""
    return await prompt_participant_value(update, context, _PERCENTAGES_CONFIG)


async def handle_percentages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle percentage input."""
    return await handle_participant_value(update, context, _PERCENTAGES_CONFIG)


# ===================================================================================
# State: ENTER_CUSTOM_SHARES
# ===================================================================================
def _custom_shares_participant_ids(context: ContextTypes.DEFAULT_TYPE) -> list:
    participant_ids = context.user_data.get("edit_selected_participants", [])
    if "participant_ids" in context.user_data.get("edit_changes", {}):
        participant_ids = context.user_data["edit_changes"]["participant_ids"]
    return participant_ids


def _custom_shares_validate(context, text, already_allocated):
    return validate_custom_share(text)


def _custom_shares_build_prompt(context, current_name, current_index, total_count, pending):
    amount = _get_effective_value(context, "amount")
    currency = _get_effective_value(context, "currency")
    shares_so_far = list(pending["shares"].values())
    shares_display = ", ".join(str(s) for s in shares_so_far) if shares_so_far else "None yet"
    return (
        f"<b>Enter Custom Shares</b>\n\n"
        f"Total expense: {currency} {amount}\n"
        f"Shares entered: {shares_display}\n\n"
        f"<b>Enter share for {current_name}:</b>\n"
        f"<i>({current_index + 1} of {total_count} participants)</i>\n\n"
        f"<i>Enter a number representing their share ratio.</i>\n"
        f"<i>E.g., if A=1, B=2, C=1, then B pays double.</i>"
    )


def _custom_shares_build_error(context, error_msg, pending):
    shares_so_far = list(pending.get("shares", {}).values())
    shares_display = ", ".join(str(s) for s in shares_so_far) if shares_so_far else "None yet"
    return (
        f"⚠️ {error_msg}\n\n"
        f"<b>Enter Custom Shares</b>\n\n"
        f"Shares entered so far: {shares_display}\n"
        f"<i>Enter a whole number (1, 2, 3, etc.)</i>"
    )


def _custom_shares_check_completion(context, values_list):
    return None


async def _custom_shares_on_complete(update, context, values_list):
    context.user_data["edit_changes"]["split_data"] = {"shares": values_list}
    return await _show_edit_menu(update, context)


_CUSTOM_SHARES_CONFIG = ParticipantValueCollector(
    pending_key="edit_custom_shares_pending",
    values_key="shares",
    message_key=_MESSAGE_KEY,
    collecting_state=EditExpenseStates.ENTER_CUSTOM_SHARES,
    back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT,
    get_participant_ids=_custom_shares_participant_ids,
    get_members=lambda context: context.user_data.get("edit_group_members", []),
    validate=_custom_shares_validate,
    build_keyboard=lambda: ExpenseKeyboard.get_field_navigation_keyboard(
        "custom", back_action=ExpenseKeyboard.ACTION_BACK_TO_EDIT
    ),
    build_prompt_text=_custom_shares_build_prompt,
    build_error_text=_custom_shares_build_error,
    check_completion=_custom_shares_check_completion,
    on_complete=_custom_shares_on_complete,
    on_back_to_start=lambda update, context: _show_edit_menu(update, context),
    cancel_fn=lambda update, context: cancel_edit(update, context),
)


async def _prompt_custom_shares(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for custom share ratios for each participant."""
    return await prompt_participant_value(update, context, _CUSTOM_SHARES_CONFIG)


async def handle_custom_shares(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom share ratio input."""
    return await handle_participant_value(update, context, _CUSTOM_SHARES_CONFIG)


# ===================================================================================
# State: SUMMARY
# ===================================================================================
async def _show_edit_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show summary of changes before saving."""
    original = context.user_data.get("edit_original_data", {})
    changes = context.user_data.get("edit_changes", {})
    members = context.user_data.get("edit_group_members", [])

    if not changes:
        await _send_or_edit_message(
            update,
            context,
            "No changes to save.",
            ExpenseKeyboard.get_edit_menu_keyboard(has_changes=False),
        )
        return EditExpenseStates.SELECT_FIELD

    # Build change summary
    change_lines = []
    for field, new_value in changes.items():
        if field == "split_data":
            continue

        old_value = original.get(field)
        label = FIELD_LABELS.get(field, field)

        if field == "split_type":
            new_value = (
                new_value.value.title() if hasattr(new_value, "value") else str(new_value).title()
            )
            old_value = (
                old_value.value.title() if hasattr(old_value, "value") else str(old_value).title()
            )
        elif field == "payer_id":
            old_member = next((m for m in members if m.get("user_id") == old_value), {})
            new_member = next((m for m in members if m.get("user_id") == new_value), {})
            old_value = get_display_name(old_member) if old_member else old_value
            new_value = get_display_name(new_member) if new_member else new_value
        elif field == "participant_ids":
            old_names = [
                get_display_name(next((m for m in members if m.get("user_id") == p["user_id"]), {}))
                for p in original.get("participants", [])
            ]
            new_names = [
                get_display_name(next((m for m in members if m.get("user_id") == pid), {}))
                for pid in new_value
            ]
            old_value = ", ".join(old_names) or "—"
            new_value = ", ".join(new_names) or "—"
        elif field == "expense_date" and hasattr(new_value, "isoformat"):
            new_value = new_value.isoformat()
        elif field == "category":
            old_value = _format_category_label(old_value)
            new_value = _format_category_label(new_value)
        elif field == "description":
            old_value = h(old_value)
            new_value = h(new_value)

        change_lines.append(f"  {label}: {old_value} → {new_value}")

    # Calculate new breakdown
    amount = changes.get("amount", original.get("amount"))
    currency = changes.get("currency", original.get("currency"))
    split_type = changes.get("split_type", original.get("split_type"))
    if isinstance(split_type, str):
        split_type = ExpenseSplitType(split_type)

    participant_ids = changes.get(
        "participant_ids", [p["user_id"] for p in original.get("participants", [])]
    )
    split_data = changes.get("split_data")

    # Calculate shares for display
    try:
        if split_type == ExpenseSplitType.EQUAL:
            shares = SplitCalculator.calculate_equal_split(
                Decimal(str(amount)), len(participant_ids)
            )
        elif split_type == ExpenseSplitType.EXACT and split_data:
            shares = split_data.get("amounts", [])
        elif split_type == ExpenseSplitType.PERCENTAGE and split_data:
            shares = SplitCalculator.calculate_percentage_split(
                Decimal(str(amount)), split_data.get("percentages", [])
            )
        elif split_type == ExpenseSplitType.CUSTOM and split_data:
            shares = SplitCalculator.calculate_custom_split(
                Decimal(str(amount)), split_data.get("shares", [])
            )
        else:
            # Use existing shares from original if no changes
            shares = [p["share_amount"] for p in original.get("participants", [])]
    except Exception as e:
        logger.error(f"Error calculating shares for summary: {e}")
        shares = [Decimal("0")] * len(participant_ids)

    # Build breakdown display
    breakdown_lines = []
    for i, pid in enumerate(participant_ids):
        member = next((m for m in members if m.get("user_id") == pid), {})
        name = get_display_name(member) if member else f"User {pid}"
        share = shares[i] if i < len(shares) else Decimal("0")
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

    expense_id = context.user_data.get("edit_expense_id")
    changes = context.user_data.get("edit_changes", {})

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
            await ExpenseService.update_expense(db, expense_id, changes, telegram_user.id)

        logger.info(f"User {telegram_user.id} updated expense {expense_id}")

        _cleanup_conversation(context)

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "View expense",
                        callback_data=ExpenseKeyboard._build_callback_data(
                            ExpenseKeyboard.ACTION_VIEW_DETAILS, str(expense_id)
                        ),
                    )
                ]
            ]
        )
        await query.edit_message_text(
            "<b>Expense updated!</b>\n\nYour changes have been saved.",
            parse_mode="HTML",
            reply_markup=keyboard,
        )

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
    expense_id = context.user_data.get("edit_expense_id")
    _cleanup_conversation(context)

    keyboard = None
    if expense_id:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Back to expense",
                        callback_data=ExpenseKeyboard._build_callback_data(
                            ExpenseKeyboard.ACTION_VIEW_DETAILS, str(expense_id)
                        ),
                    )
                ]
            ]
        )

    message = "Edit cancelled. No changes were saved."
    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=keyboard)
    else:
        await _cleanup_previous_keyboard(update, context)
        await update.message.reply_text(message, reply_markup=keyboard)

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
                pattern=f"^{ExpenseKeyboard.PREFIX}{ExpenseKeyboard.ACTION_EDIT}:",
            )
        ],
        states={
            EditExpenseStates.SELECT_FIELD: [
                CallbackQueryHandler(handle_edit_menu, pattern=f"^{ExpenseKeyboard.PREFIX}")
            ],
            EditExpenseStates.EDIT_DESCRIPTION: [
                CallbackQueryHandler(handle_edit_description, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_description),
            ],
            EditExpenseStates.EDIT_AMOUNT: [
                CallbackQueryHandler(handle_edit_amount, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_amount),
            ],
            EditExpenseStates.EDIT_CURRENCY: [
                CallbackQueryHandler(handle_edit_currency, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_currency),
            ],
            EditExpenseStates.EDIT_DATE: [
                CallbackQueryHandler(handle_edit_date, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_date),
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
            EditExpenseStates.EDIT_CATEGORY: [
                CallbackQueryHandler(handle_edit_category, pattern=f"^{ExpenseKeyboard.PREFIX}")
            ],
            EditExpenseStates.ENTER_EXACT_AMOUNTS: [
                CallbackQueryHandler(handle_exact_amounts, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exact_amounts),
            ],
            EditExpenseStates.ENTER_PERCENTAGES: [
                CallbackQueryHandler(handle_percentages, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_percentages),
            ],
            EditExpenseStates.ENTER_CUSTOM_SHARES: [
                CallbackQueryHandler(handle_custom_shares, pattern=f"^{ExpenseKeyboard.PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_shares),
            ],
            EditExpenseStates.SUMMARY: [
                CallbackQueryHandler(handle_summary, pattern=f"^{ExpenseKeyboard.PREFIX}")
            ],
        },
        fallbacks=[
            CallbackQueryHandler(
                cancel_edit, pattern=f"^{ExpenseKeyboard.PREFIX}{ExpenseKeyboard.ACTION_CANCEL}$"
            )
        ],
        conversation_timeout=CONVERSATION_TIMEOUT,
        name="edit_expense",
        per_chat=True,
        per_user=True,
    )
