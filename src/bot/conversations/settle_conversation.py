import logging
from decimal import Decimal, InvalidOperation

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.handlers.balance_handler import _get_effective_simplify
from bot.keyboards.balance_keyboard import BalanceKeyboard
from bot.keyboards.settle_keyboard import SettleKeyboard
from bot.utils import ERROR_MSG, h
from infrastructure import get_db
from services.balance_service import BalanceService
from services.payment_service import PaymentService

from .states import SettleStates

logger = logging.getLogger(__name__)

CONVERSATION_TIMEOUT = 300  # 5 minutes
EXPIRED_MSG = "This settle session has expired. Please start again from /balances."

# Flow modes
MODE_USER = "user"    # "Settle My Debts": presser pays their own debts
MODE_GROUP = "group"  # "Settle Up": record a payment for any debt in the group


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _cleanup(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in [
        'settle_mode', 'settle_group_id', 'settle_currency', 'settle_debts',
        'settle_member_names', 'settle_from_user_id', 'settle_from_name',
        'settle_to_user_id', 'settle_to_name', 'settle_amount'
    ]:
        context.user_data.pop(key, None)


def _display_name(user_dict: dict) -> str:
    """
    Plain (unescaped) display name for inline-keyboard button labels.
    Any use inside a parse_mode="HTML" message body must be wrapped in h().
    """
    first = user_dict.get('first_name')
    if first:
        last = user_dict.get('last_name')
        return f"{first} {last}" if last else first
    return (
        user_dict.get('username')
        or f"User {user_dict.get('user_id', '?')}"
    )


async def _answer_quietly(query) -> None:
    """Answer a callback query, ignoring 'already answered' errors."""
    try:
        await query.answer()
    except Exception:
        pass


def _parse_settle_entry(data: str) -> tuple:
    """
    Parse settle entry callback data into (mode, group_id).
    Formats: 'group:{gid}', 'user:{gid}', or legacy '{gid}' (treated as user mode).
    """
    if ':' in data:
        mode, gid = data.split(':', 1)
        if mode not in (MODE_USER, MODE_GROUP):
            raise ValueError(f"Unknown settle mode: {mode}")
        return mode, int(gid)
    return MODE_USER, int(data)


def _recipient_prompt(context: ContextTypes.DEFAULT_TYPE) -> tuple:
    """Build (message, keyboard) for the selection step of the current mode."""
    currency = context.user_data.get('settle_currency', 'SGD')
    debts = context.user_data.get('settle_debts', [])
    if context.user_data.get('settle_mode') == MODE_GROUP:
        message = "<b>Settle Up</b>\n\nSelect a debt to record as paid:"
        keyboard = SettleKeyboard.get_debt_selection_keyboard(
            debts, context.user_data.get('settle_member_names', {}), currency
        )
    else:
        message = "<b>Settle Up</b>\n\nSelect who you want to pay:"
        keyboard = SettleKeyboard.get_recipient_keyboard(debts, currency)
    return message, keyboard


def _confirm_text(context: ContextTypes.DEFAULT_TYPE, amount: Decimal) -> str:
    currency = context.user_data.get('settle_currency', 'SGD')
    to_name = h(context.user_data.get('settle_to_name', 'recipient'))
    if context.user_data.get('settle_mode') == MODE_GROUP:
        from_name = h(context.user_data.get('settle_from_name', 'payer'))
        action = f"Record <b>{currency} {amount:,.2f}</b> paid by {from_name} to {to_name}?"
    else:
        action = f"Pay <b>{currency} {amount:,.2f}</b> to {to_name}?"
    return (
        f"<b>Confirm Payment</b>\n\n"
        f"{action}\n\n"
        "This will be recorded as a payment."
    )


# ─── Entry point ─────────────────────────────────────────────────────────────

async def start_settle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Entry point: user tapped 'Settle Up' (group mode) or 'Settle My Debts'
    (user mode) from a balance view.
    Callback data: balance_settle_up:group:{gid} | balance_settle_up:user:{gid}
    (legacy: balance_settle_up:{gid} → user mode).

    NOTE: the callback query is answered exactly once — with an alert when
    there is nothing to settle, plainly otherwise.
    """
    query = update.callback_query
    user_id = update.effective_user.id

    # In group chats, only the user who triggered the balance view may use its
    # keyboard — same anti-hijack guard as handle_balance_callback.
    chat = update.effective_chat
    if chat and chat.type != "private":
        owner_id = context.chat_data.get(f'kbd_owner_{query.message.message_id}')
        if owner_id is not None and owner_id != user_id:
            await query.answer("This is not your interaction.", show_alert=True)
            return ConversationHandler.END

    _, data = BalanceKeyboard.extract_callback_info(query.data)
    if not data:
        await _answer_quietly(query)
        await query.edit_message_text("Invalid settle request. Please try again.")
        return ConversationHandler.END

    try:
        mode, group_id = _parse_settle_entry(data)
    except ValueError:
        await _answer_quietly(query)
        await query.edit_message_text("Invalid settle request. Please try again.")
        return ConversationHandler.END

    try:
        async with get_db() as db:
            # Match whatever simplified/raw view the user is looking at
            simplify = await _get_effective_simplify(db, group_id, user_id, context)

            if mode == MODE_GROUP:
                balances = await BalanceService.get_group_balances(
                    db, group_id, user_id, simplify=simplify
                )
                currency = balances['currency']
                member_names = {
                    m['user_id']: _display_name(m) for m in balances['members']
                }
                # Payments can only be recorded between current members, so
                # drop debts involving users who have left the group.
                debts = [
                    d for d in balances['debts']
                    if d['from_user_id'] in member_names and d['to_user_id'] in member_names
                ]
            else:
                balance = await BalanceService.get_user_balance_in_group(
                    db, group_id, user_id, simplify=simplify
                )
                debts = balance['owes_to']
                currency = balance['currency']
                member_names = {}

        if not debts:
            no_debt_msg = (
                "No outstanding debts in this group!"
                if mode == MODE_GROUP
                else "You have no outstanding debts in this group!"
            )
            await query.answer(no_debt_msg, show_alert=True)
            return ConversationHandler.END

        await query.answer()

        context.user_data['settle_mode'] = mode
        context.user_data['settle_group_id'] = group_id
        context.user_data['settle_currency'] = currency
        context.user_data['settle_debts'] = debts
        context.user_data['settle_member_names'] = member_names

        message, keyboard = _recipient_prompt(context)
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
        return SettleStates.SELECT_RECIPIENT

    except Exception as e:
        logger.error(f"Error starting settle for user {user_id}, group {group_id}: {e}", exc_info=True)
        await _answer_quietly(query)
        await query.edit_message_text(ERROR_MSG)
        return ConversationHandler.END


# ─── State: SELECT_RECIPIENT ─────────────────────────────────────────────────

async def handle_recipient(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User selected a recipient (user mode) or a debt pair (group mode)."""
    query = update.callback_query
    await query.answer()

    action, data = SettleKeyboard.extract_callback_info(query.data)

    if action == SettleKeyboard.ACTION_CANCEL:
        _cleanup(context)
        await query.edit_message_text("Settle up cancelled.")
        return ConversationHandler.END

    if action != SettleKeyboard.ACTION_SELECT or not data:
        return SettleStates.SELECT_RECIPIENT

    mode = context.user_data.get('settle_mode', MODE_USER)
    debts = context.user_data.get('settle_debts', [])
    currency = context.user_data.get('settle_currency', 'SGD')

    try:
        if mode == MODE_GROUP:
            # data: "{from_user_id}:{to_user_id}"
            from_str, to_str = data.split(':', 1)
            from_user_id, to_user_id = int(from_str), int(to_str)
            debt = next(
                (d for d in debts
                 if d['from_user_id'] == from_user_id and d['to_user_id'] == to_user_id),
                None
            )
            member_names = context.user_data.get('settle_member_names', {})
            from_name = member_names.get(from_user_id, f"User {from_user_id}")
            to_name = member_names.get(to_user_id, f"User {to_user_id}")
        else:
            to_user_id = int(data)
            from_user_id = update.effective_user.id
            debt = next((d for d in debts if d['user_id'] == to_user_id), None)
            from_name = "You"
            to_name = _display_name(debt) if debt else None
    except ValueError:
        # Callback data doesn't match the stored mode — this happens when a
        # parallel settle flow in another chat overwrote user_data. Don't
        # _cleanup(): the current state belongs to that other flow.
        await query.edit_message_text(EXPIRED_MSG)
        return ConversationHandler.END

    if not debt:
        await query.edit_message_text("Selection no longer valid. Please try again.")
        _cleanup(context)
        return ConversationHandler.END

    amount = debt['amount']
    context.user_data['settle_from_user_id'] = from_user_id
    context.user_data['settle_from_name'] = from_name
    context.user_data['settle_to_user_id'] = to_user_id
    context.user_data['settle_to_name'] = to_name
    context.user_data['settle_amount'] = amount

    if mode == MODE_GROUP:
        header = f"<b>{h(from_name)} pays {h(to_name)}</b>"
    else:
        header = f"<b>Pay {h(to_name)}</b>"
    message = (
        f"{header}\n\n"
        f"Amount owed: <b>{currency} {amount:,.2f}</b>\n\n"
        "Tap to record the full amount, or type a custom amount:"
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

    if action == SettleKeyboard.ACTION_CANCEL:
        _cleanup(context)
        await query.edit_message_text("Settle up cancelled.")
        return ConversationHandler.END

    if action == SettleKeyboard.ACTION_BACK:
        message, keyboard = _recipient_prompt(context)
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
        return SettleStates.SELECT_RECIPIENT

    if action == SettleKeyboard.ACTION_PAY_FULL:
        amount = context.user_data.get('settle_amount')
        if amount is None:
            # State lost (timeout cleanup or a parallel flow overwrote it)
            await query.edit_message_text(EXPIRED_MSG)
            return ConversationHandler.END
        message = _confirm_text(context, amount)
        keyboard = SettleKeyboard.get_confirm_keyboard()
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
        return SettleStates.CONFIRM

    return SettleStates.ENTER_AMOUNT


async def handle_amount_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle free-text custom amount entry."""
    currency = context.user_data.get('settle_currency', 'SGD')
    full_amount = context.user_data.get('settle_amount')
    if full_amount is None:
        await update.message.reply_text(EXPIRED_MSG)
        return ConversationHandler.END

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
            f"Amount cannot exceed the debt ({currency} {full_amount:,.2f}). "
            f"Please enter a valid amount:"
        )
        return SettleStates.ENTER_AMOUNT

    # Store the custom amount and show confirmation
    context.user_data['settle_amount'] = amount

    message = _confirm_text(context, amount)
    keyboard = SettleKeyboard.get_confirm_keyboard()
    await update.message.reply_text(message, parse_mode="HTML", reply_markup=keyboard)
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

    mode = context.user_data.get('settle_mode')
    group_id = context.user_data.get('settle_group_id')
    from_user_id = context.user_data.get('settle_from_user_id')
    from_name = context.user_data.get('settle_from_name')
    to_user_id = context.user_data.get('settle_to_user_id')
    to_name = context.user_data.get('settle_to_name')
    amount = context.user_data.get('settle_amount')
    currency = context.user_data.get('settle_currency')

    # Fail fast on lost or clobbered state — recording a payment with silently
    # defaulted values would create a wrong financial record.
    state_incomplete = None in (mode, group_id, from_user_id, to_user_id, amount, currency)
    presser_mismatch = (mode == MODE_USER and from_user_id != update.effective_user.id)
    if state_incomplete or presser_mismatch:
        await query.edit_message_text(EXPIRED_MSG)
        return ConversationHandler.END

    try:
        async with get_db() as db:
            await PaymentService.record_payment(
                db, group_id, from_user_id, to_user_id, amount, currency
            )

        _cleanup(context)
        if mode == MODE_GROUP:
            summary = f"Recorded <b>{currency} {amount:,.2f}</b> paid by {h(from_name)} to {h(to_name)}."
        else:
            summary = f"Paid <b>{currency} {amount:,.2f}</b> to {h(to_name)}."
        await query.edit_message_text(
            f"<b>Payment Recorded!</b>\n\n"
            f"{summary}\n\n"
            "Use /balances to see updated balances.",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error recording payment: {e}", exc_info=True)
        _cleanup(context)
        await query.edit_message_text("Failed to record payment. Please try again.")
        return ConversationHandler.END


# ─── Timeout ─────────────────────────────────────────────────────────────────

async def handle_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Conversation timed out: clear state and disable the stale keyboard so
    later presses don't spin forever with no handler to answer them.
    """
    _cleanup(context)
    message = update.effective_message
    if message is not None:
        try:
            await message.edit_text("Settle up timed out. Please start again from /balances.")
        except Exception:
            # Last update may be the user's own text message (not editable by
            # the bot) or the message may be gone — nothing to disable then.
            pass
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
    Entry point matches the 'Settle Up' / 'Settle My Debts' buttons from the
    balance keyboards.
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
            ConversationHandler.TIMEOUT: [
                CallbackQueryHandler(handle_timeout),
                MessageHandler(filters.ALL, handle_timeout),
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
        allow_reentry=True,
    )
