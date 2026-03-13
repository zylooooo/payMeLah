from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
from decimal import Decimal, InvalidOperation
from infrastructure import get_db
from services import GroupService, UserService
from services.balance_service import BalanceService
from services.payment_service import PaymentService
from bot.keyboards.balance_keyboard import BalanceKeyboard
from bot.keyboards.settle_keyboard import SettleKeyboard
from .states import SettleStates
import logging


logger = logging.getLogger(__name__)

ERROR_MSG = "An unexpected error occurred. Please try again later."
CONVERSATION_TIMEOUT = 300  # 5 minutes


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _cleanup(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in [
        'settle_group_id', 'settle_currency', 'settle_debts',
        'settle_to_user_id', 'settle_to_name', 'settle_amount'
    ]:
        context.user_data.pop(key, None)


def _display_name(user_dict: dict) -> str:
    return (
        user_dict.get('first_name')
        or user_dict.get('username')
        or f"User {user_dict.get('user_id', '?')}"
    )


# ─── Entry point ─────────────────────────────────────────────────────────────

async def start_settle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Entry point: user tapped 'Settle Up' or 'Settle My Debts' from a balance view.
    Callback data: balance_settle_up:{group_id}
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    _, data = BalanceKeyboard.extract_callback_info(query.data)
    if not data:
        await query.edit_message_text("Invalid settle request. Please try again.")
        return ConversationHandler.END

    group_id = int(data)

    try:
        async with get_db() as db:
            # Use simplified view to match what the user sees on the balance screen
            balance = await BalanceService.get_user_balance_in_group(
                db, group_id, user_id, simplify=True
            )

        owes_to = balance['owes_to']
        if not owes_to:
            await query.answer(
                "You have no outstanding debts in this group!",
                show_alert=True
            )
            return ConversationHandler.END

        currency = balance['currency']
        context.user_data['settle_group_id'] = group_id
        context.user_data['settle_currency'] = currency
        context.user_data['settle_debts'] = owes_to

        message = "<b>Settle Up</b>\n\nSelect who you want to pay:"
        keyboard = SettleKeyboard.get_recipient_keyboard(owes_to, currency)
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
        return SettleStates.SELECT_RECIPIENT

    except Exception as e:
        logger.error(f"Error starting settle for user {user_id}, group {group_id}: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)
        return ConversationHandler.END


# ─── State: SELECT_RECIPIENT ─────────────────────────────────────────────────

async def handle_recipient(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User selected a recipient from the debt list."""
    query = update.callback_query
    await query.answer()

    action, data = SettleKeyboard.extract_callback_info(query.data)

    if action == SettleKeyboard.ACTION_CANCEL:
        _cleanup(context)
        await query.edit_message_text("Settle up cancelled.")
        return ConversationHandler.END

    if action != SettleKeyboard.ACTION_SELECT or not data:
        return SettleStates.SELECT_RECIPIENT

    to_user_id = int(data)
    debts = context.user_data.get('settle_debts', [])
    currency = context.user_data.get('settle_currency', 'SGD')

    debt = next((d for d in debts if d['user_id'] == to_user_id), None)
    if not debt:
        await query.edit_message_text("Selection no longer valid. Please try again.")
        _cleanup(context)
        return ConversationHandler.END

    name = _display_name(debt)
    amount = debt['amount']

    context.user_data['settle_to_user_id'] = to_user_id
    context.user_data['settle_to_name'] = name
    context.user_data['settle_amount'] = amount

    message = (
        f"<b>Pay {name}</b>\n\n"
        f"Amount owed: <b>{currency} {amount:,.2f}</b>\n\n"
        "Tap to pay the full amount, or type a custom amount:"
    )
    keyboard = SettleKeyboard.get_amount_keyboard(amount, currency)
    await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    return SettleStates.ENTER_AMOUNT


# ─── State: ENTER_AMOUNT ─────────────────────────────────────────────────────

async def handle_amount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle pay_full / back / cancel buttons in the amount step."""
    query = update.callback_query
    await query.answer()

    action, _ = SettleKeyboard.extract_callback_info(query.data)
    currency = context.user_data.get('settle_currency', 'SGD')

    if action == SettleKeyboard.ACTION_CANCEL:
        _cleanup(context)
        await query.edit_message_text("Settle up cancelled.")
        return ConversationHandler.END

    if action == SettleKeyboard.ACTION_BACK:
        debts = context.user_data.get('settle_debts', [])
        message = "<b>Settle Up</b>\n\nSelect who you want to pay:"
        keyboard = SettleKeyboard.get_recipient_keyboard(debts, currency)
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
        return SettleStates.SELECT_RECIPIENT

    if action == SettleKeyboard.ACTION_PAY_FULL:
        amount = context.user_data.get('settle_amount')
        to_name = context.user_data.get('settle_to_name', 'recipient')
        return await _show_confirm(query, context, amount, to_name, currency)

    return SettleStates.ENTER_AMOUNT


async def handle_amount_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle free-text custom amount entry."""
    currency = context.user_data.get('settle_currency', 'SGD')
    full_amount = context.user_data.get('settle_amount', Decimal('0'))
    to_name = context.user_data.get('settle_to_name', 'recipient')

    text = update.message.text.strip()
    try:
        amount = Decimal(text.replace(',', '')).quantize(Decimal('0.01'))
        if amount <= 0:
            raise ValueError()
    except (ValueError, InvalidOperation):
        await update.message.reply_text(
            f"Invalid amount. Please enter a positive number (e.g. {full_amount:,.2f}):"
        )
        return SettleStates.ENTER_AMOUNT

    if amount > full_amount:
        await update.message.reply_text(
            f"Amount cannot exceed what you owe ({currency} {full_amount:,.2f}). "
            f"Please enter a valid amount:"
        )
        return SettleStates.ENTER_AMOUNT

    # Store the custom amount and show confirmation
    context.user_data['settle_amount'] = amount

    message = (
        f"<b>Confirm Payment</b>\n\n"
        f"Pay <b>{currency} {amount:,.2f}</b> to {to_name}?\n\n"
        "This will be recorded as a payment."
    )
    keyboard = SettleKeyboard.get_confirm_keyboard()
    await update.message.reply_text(message, parse_mode="HTML", reply_markup=keyboard)
    return SettleStates.CONFIRM


async def _show_confirm(query, context, amount, to_name, currency) -> int:
    """Shared helper: render the confirmation screen."""
    message = (
        f"<b>Confirm Payment</b>\n\n"
        f"Pay <b>{currency} {amount:,.2f}</b> to {to_name}?\n\n"
        "This will be recorded as a payment."
    )
    keyboard = SettleKeyboard.get_confirm_keyboard()
    await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    return SettleStates.CONFIRM


# ─── State: CONFIRM ───────────────────────────────────────────────────────────

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User confirmed or cancelled the payment."""
    query = update.callback_query
    await query.answer()

    action, _ = SettleKeyboard.extract_callback_info(query.data)

    if action == SettleKeyboard.ACTION_CANCEL:
        _cleanup(context)
        await query.edit_message_text("Settle up cancelled.")
        return ConversationHandler.END

    if action != SettleKeyboard.ACTION_CONFIRM:
        return SettleStates.CONFIRM

    group_id = context.user_data.get('settle_group_id')
    from_user_id = update.effective_user.id
    to_user_id = context.user_data.get('settle_to_user_id')
    to_name = context.user_data.get('settle_to_name')
    amount = context.user_data.get('settle_amount')
    currency = context.user_data.get('settle_currency')

    try:
        async with get_db() as db:
            await PaymentService.record_payment(
                db, group_id, from_user_id, to_user_id, amount, currency
            )

        _cleanup(context)
        await query.edit_message_text(
            f"<b>Payment Recorded!</b>\n\n"
            f"Paid <b>{currency} {amount:,.2f}</b> to {to_name}.\n\n"
            "Use /balances or /mybalance to see updated balances.",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error recording payment: {e}", exc_info=True)
        _cleanup(context)
        await query.edit_message_text("Failed to record payment. Please try again.")
        return ConversationHandler.END


# ─── Fallback ────────────────────────────────────────────────────────────────

async def cancel_settle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _cleanup(context)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Settle up cancelled.")
    else:
        await update.message.reply_text("Settle up cancelled.")
    return ConversationHandler.END


# ─── Factory ─────────────────────────────────────────────────────────────────

def create_settle_conversation_handler() -> ConversationHandler:
    """
    Factory for the settle conversation handler.
    Entry point matches the 'Settle Up' button from the balance keyboard.
    Must be registered BEFORE the balance callback handler in bot.py.
    """
    settle_cancel_pattern = (
        f"^{SettleKeyboard.PREFIX}{SettleKeyboard.ACTION_CANCEL}$"
    )

    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                start_settle,
                pattern=f"^{BalanceKeyboard.PREFIX}{BalanceKeyboard.ACTION_SETTLE_UP}:"
            )
        ],
        states={
            SettleStates.SELECT_RECIPIENT: [
                CallbackQueryHandler(
                    handle_recipient,
                    pattern=f"^{SettleKeyboard.PREFIX}"
                )
            ],
            SettleStates.ENTER_AMOUNT: [
                CallbackQueryHandler(
                    handle_amount_callback,
                    pattern=f"^{SettleKeyboard.PREFIX}"
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handle_amount_text
                )
            ],
            SettleStates.CONFIRM: [
                CallbackQueryHandler(
                    handle_confirmation,
                    pattern=f"^{SettleKeyboard.PREFIX}"
                )
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_settle, pattern=settle_cancel_pattern),
            MessageHandler(filters.COMMAND, cancel_settle),
        ],
        conversation_timeout=CONVERSATION_TIMEOUT,
        name="settle_conversation",
        per_chat=True,
        per_user=True,
        per_message=False,
    )
