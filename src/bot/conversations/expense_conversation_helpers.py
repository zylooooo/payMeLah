"""
Shared helpers for the create/edit expense ConversationHandlers.

Both conversations manage a "last bot message" (to edit in place rather than
spam new messages) and a set of user_data keys to clear on exit. They differ
only in which user_data key holds the message id and which keys get cleared,
so every function here is parameterized by that.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, List, Optional, Tuple

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards import ExpenseKeyboard
from bot.utils import get_display_name

logger = logging.getLogger(__name__)


def cleanup_conversation(context: ContextTypes.DEFAULT_TYPE, keys_to_remove: list) -> None:
    """Cleanup conversation state."""
    for key in keys_to_remove:
        context.user_data.pop(key, None)


async def cleanup_previous_keyboard(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message_key: str
) -> None:
    """Clean up inline keyboard from previous bot message."""
    message_id = context.user_data.get(message_key)
    if not message_id:
        return

    chat_id = update.effective_chat.id
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=None
        )
    except Exception as e:
        # Cleanup failures do not block the conversation, fail silently
        logger.warning(
            f"Failed to remove keyboard for message {message_id} in chat {chat_id}: {e}",
            exc_info=True,
        )
    finally:
        context.user_data.pop(message_key, None)


async def send_or_edit_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    message_key: str,
    keyboard=None,
) -> None:
    """Unified message handler for both callback queries and text messages."""
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="HTML", reply_markup=keyboard
        )
        context.user_data[message_key] = update.callback_query.message.message_id
    else:
        await cleanup_previous_keyboard(update, context, message_key)
        sent_message = await update.message.reply_text(
            text, parse_mode="HTML", reply_markup=keyboard
        )
        context.user_data[message_key] = sent_message.message_id


async def send_validation_error(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: str,
    message_key: str,
    keyboard=None,
) -> None:
    """
    Send validation error message with proper keyboard cleanup.
    Tries to edit the previous message first, falls back to sending new message.
    """
    message_id = context.user_data.get(message_key)
    chat_id = update.effective_chat.id

    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=error_msg,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            return
        except Exception as e:
            logger.debug(f"Failed to edit message {message_id} for validation error: {e}")

    await cleanup_previous_keyboard(update, context, message_key)
    sent_message = await update.message.reply_text(
        error_msg, parse_mode="HTML", reply_markup=keyboard
    )
    context.user_data[message_key] = sent_message.message_id


@dataclass
class ParticipantValueCollector:
    """
    Config for the generic per-participant value collection state machine
    (used for exact-amount / percentage / custom-share entry in both the
    create and edit expense conversations).
    """

    pending_key: str
    values_key: str
    message_key: str
    collecting_state: Any
    back_action: str
    get_participant_ids: Callable[[ContextTypes.DEFAULT_TYPE], List[int]]
    get_members: Callable[[ContextTypes.DEFAULT_TYPE], List[dict]]
    validate: Callable[[ContextTypes.DEFAULT_TYPE, str, Decimal], Tuple[bool, Optional[str], Any]]
    build_keyboard: Callable[[], Any]
    build_prompt_text: Callable[[ContextTypes.DEFAULT_TYPE, str, int, int, dict], str]
    build_error_text: Callable[[ContextTypes.DEFAULT_TYPE, str, dict], str]
    check_completion: Callable[[ContextTypes.DEFAULT_TYPE, list], Optional[str]]
    on_complete: Callable[[Update, ContextTypes.DEFAULT_TYPE, list], Any]
    on_back_to_start: Callable[[Update, ContextTypes.DEFAULT_TYPE], Any]
    cancel_fn: Callable[[Update, ContextTypes.DEFAULT_TYPE], Any]


async def prompt_participant_value(
    update: Update, context: ContextTypes.DEFAULT_TYPE, cfg: ParticipantValueCollector
) -> int:
    """Show the prompt for the next uncollected participant, or finish the collection."""
    participant_ids = cfg.get_participant_ids(context)
    members = cfg.get_members(context)

    if cfg.pending_key not in context.user_data:
        context.user_data[cfg.pending_key] = {cfg.values_key: {}, "current_index": 0}
    pending = context.user_data[cfg.pending_key]
    current_index = pending["current_index"]

    if current_index >= len(participant_ids):
        values_list = [pending[cfg.values_key][pid] for pid in participant_ids]
        mismatch_msg = cfg.check_completion(context, values_list)
        if mismatch_msg:
            await send_or_edit_message(
                update, context, mismatch_msg, cfg.message_key, cfg.build_keyboard()
            )
            context.user_data[cfg.pending_key] = {cfg.values_key: {}, "current_index": 0}
            return await prompt_participant_value(update, context, cfg)
        return await cfg.on_complete(update, context, values_list)

    current_participant_id = participant_ids[current_index]
    current_member = next((m for m in members if m.get("user_id") == current_participant_id), {})
    current_name = get_display_name(current_member)

    message = cfg.build_prompt_text(
        context, current_name, current_index, len(participant_ids), pending
    )
    keyboard = cfg.build_keyboard()
    await send_or_edit_message(update, context, message, cfg.message_key, keyboard)
    return cfg.collecting_state


async def handle_participant_value(
    update: Update, context: ContextTypes.DEFAULT_TYPE, cfg: ParticipantValueCollector
) -> int:
    """Handle a callback (cancel/back) or text-message input for the current participant."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, _ = ExpenseKeyboard.extract_callback_info(query.data)

        if action == ExpenseKeyboard.ACTION_CANCEL:
            return await cfg.cancel_fn(update, context)
        if action == cfg.back_action:
            pending = context.user_data.get(cfg.pending_key, {})
            current_index = pending.get("current_index", 0)

            if current_index > 0:
                participant_ids = cfg.get_participant_ids(context)
                prev_participant_id = participant_ids[current_index - 1]
                pending[cfg.values_key].pop(prev_participant_id, None)
                pending["current_index"] = current_index - 1
                return await prompt_participant_value(update, context, cfg)
            else:
                context.user_data.pop(cfg.pending_key, None)
                return await cfg.on_back_to_start(update, context)

        return cfg.collecting_state

    pending = context.user_data.get(cfg.pending_key, {})
    current_index = pending.get("current_index", 0)
    already_allocated = sum(pending.get(cfg.values_key, {}).values())

    is_valid, error_msg, value = cfg.validate(context, update.message.text, already_allocated)

    if not is_valid:
        enhanced_error = cfg.build_error_text(context, error_msg, pending)
        await send_validation_error(
            update, context, enhanced_error, cfg.message_key, cfg.build_keyboard()
        )
        return cfg.collecting_state

    participant_ids = cfg.get_participant_ids(context)
    current_participant_id = participant_ids[current_index]
    pending[cfg.values_key][current_participant_id] = value
    pending["current_index"] = current_index + 1

    return await prompt_participant_value(update, context, cfg)
