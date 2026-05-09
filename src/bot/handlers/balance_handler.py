from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes, CallbackQueryHandler
from typing import List, Optional
from decimal import Decimal
from infrastructure import get_db
from services import GroupService, UserService
from services.balance_service import BalanceService
from services.payment_service import PaymentService
from bot.keyboards import GroupKeyboard
from bot.keyboards.balance_keyboard import BalanceKeyboard
from bot.utils import (
    validate_chat_type, h, rate_limit, ERROR_MSG, get_display_name,
    can_nudge, record_nudge, cooldown_remaining
)
from shared import (
    GroupNotFoundException,
    UnauthorizedActionException
)
import logging


logger = logging.getLogger(__name__)


async def _send_error(update, text: str, edit: bool = False) -> None:
    """Send an error as an edited message (callbacks) or a reply (commands)."""
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text)
    elif update.message:
        await update.message.reply_text(text)


def _format_amount(amount: Decimal, currency: str) -> str:
    """Format amount with currency."""
    return f"{currency} {amount:,.2f}"


async def _get_effective_simplify(
    db,
    group_id: int,
    user_id: int,
    context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Determine whether to show simplified debts for this balance view.
    Priority: in-view toggle (context) > group default > user preference.
    """
    # In-view toggle always takes precedence (set when user clicks toggle button)
    override = context.user_data.get(f'balance_simplify_{group_id}')
    if override is not None:
        return override

    # No override — use the group's default setting
    group = await GroupService.get_group_by_id(db, group_id)
    if group and group.get('simplify_debts', True):
        return True

    # Group default is off — fall back to the user's own preference
    user = await UserService.get_user_by_id(db, user_id)
    return user.get('simplify_debts', True) if user else True


@rate_limit
@validate_chat_type("private", "group", "supergroup")
async def balances_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /balances command handler.
    Shows all balances within a group. In group chat, shows balances for groups
    associated with that chat. In private chat, prompts user to select a group.
    """
    chat_type = update.effective_chat.type
    telegram_user = update.effective_user

    if not telegram_user:
        logger.warning("Received /balances command without telegram user")
        return

    if chat_type == "private":
        # Private chat - show group selection
        logger.info(f"User {telegram_user.id} requested balances in private chat")

        try:
            async with get_db() as db:
                groups = await GroupService.get_all_groups_by_user_id(db, telegram_user.id)

                if not groups:
                    await update.message.reply_text(
                        "You are not a member of any groups yet.\n"
                        "Join or create a group to start tracking balances!"
                    )
                    return

                # Store groups for pagination
                context.user_data['balance_groups'] = groups
                context.user_data['balance_groups_page'] = 0

                message = (
                    "<b>View Group Balances</b>\n\n"
                    "Select a group to view balances:"
                )
                keyboard = BalanceKeyboard.get_group_selection_keyboard(
                    groups, page=0, action_prefix="balances"
                )

                await update.message.reply_text(
                    message,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
        except Exception as e:
            logger.error(f"Error in balances command: {e}", exc_info=True)
            await update.message.reply_text(ERROR_MSG)

    else:
        # Group chat - show balances for groups in this chat
        telegram_chat_id = update.effective_chat.id
        logger.info(f"Showing balances for chat {telegram_chat_id}")

        try:
            async with get_db() as db:
                groups = await GroupService.get_group_by_chat_id(db, telegram_chat_id)

                if not groups:
                    await update.message.reply_text(
                        "No expense groups found in this chat.\n"
                        "Create one with /newgroup first!"
                    )
                    return

                # Check if user is member of any group
                user_groups = [
                    g for g in groups
                    if await GroupService.is_member(db, g['id'], telegram_user.id)
                ]

                if not user_groups:
                    await update.message.reply_text(
                        "You are not a member of any expense groups in this chat.\n"
                        "Use /groups to join one!"
                    )
                    return

                if len(user_groups) == 1:
                    # Single group - show balances directly
                    async with get_db() as db:
                        simplify = await _get_effective_simplify(db, user_groups[0]['id'], telegram_user.id, context)
                    sent = await _show_group_balances(
                        update, context, user_groups[0]['id'], telegram_user.id, simplify=simplify
                    )
                    if sent:
                        context.chat_data[f'kbd_owner_{sent.message_id}'] = telegram_user.id
                else:
                    # Multiple groups — store per-user and track chat for re-fetch
                    context.user_data['balance_groups'] = user_groups
                    context.user_data['balance_groups_page'] = 0
                    context.user_data['balance_chat_id'] = telegram_chat_id

                    message = (
                        "<b>View Group Balances</b>\n\n"
                        "Select a group to view balances:"
                    )
                    keyboard = BalanceKeyboard.get_group_selection_keyboard(
                        user_groups, page=0, action_prefix="balances"
                    )

                    sent = await update.message.reply_text(
                        message,
                        parse_mode="HTML",
                        reply_markup=keyboard
                    )
                    # Track who owns this keyboard so other group members can't hijack it
                    context.chat_data[f'kbd_owner_{sent.message_id}'] = telegram_user.id
        except Exception as e:
            logger.error(f"Error in balances command: {e}", exc_info=True)
            await update.message.reply_text(ERROR_MSG)


@rate_limit
@validate_chat_type("private", "group", "supergroup")
async def mybalance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /mybalance command handler.
    Shows the current user's balance in a specific group.
    """
    chat_type = update.effective_chat.type
    telegram_user = update.effective_user

    if not telegram_user:
        logger.warning("Received /mybalance command without telegram user")
        return

    if chat_type == "private":
        # Private chat - show group selection
        logger.info(f"User {telegram_user.id} requested mybalance in private chat")

        try:
            async with get_db() as db:
                groups = await GroupService.get_all_groups_by_user_id(db, telegram_user.id)

                if not groups:
                    await update.message.reply_text(
                        "You are not a member of any groups yet.\n"
                        "Join or create a group to start tracking balances!"
                    )
                    return

                # Store groups for pagination
                context.user_data['balance_groups'] = groups
                context.user_data['balance_groups_page'] = 0

                message = (
                    "<b>View My Balance</b>\n\n"
                    "Select a group to view your balance:"
                )
                keyboard = BalanceKeyboard.get_group_selection_keyboard(
                    groups, page=0, action_prefix="mybalance"
                )

                await update.message.reply_text(
                    message,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
        except Exception as e:
            logger.error(f"Error in mybalance command: {e}", exc_info=True)
            await update.message.reply_text(ERROR_MSG)

    else:
        # Group chat
        telegram_chat_id = update.effective_chat.id
        logger.info(f"Showing user balance in chat {telegram_chat_id}")

        try:
            async with get_db() as db:
                groups = await GroupService.get_group_by_chat_id(db, telegram_chat_id)

                if not groups:
                    await update.message.reply_text(
                        "No expense groups found in this chat.\n"
                        "Create one with /newgroup first!"
                    )
                    return

                # Check if user is member of any group
                user_groups = [
                    g for g in groups
                    if await GroupService.is_member(db, g['id'], telegram_user.id)
                ]

                if not user_groups:
                    await update.message.reply_text(
                        "You are not a member of any expense groups in this chat.\n"
                        "Use /groups to join one!"
                    )
                    return

                if len(user_groups) == 1:
                    # Single group - show balance directly
                    async with get_db() as db:
                        simplify = await _get_effective_simplify(db, user_groups[0]['id'], telegram_user.id, context)
                    sent = await _show_user_balance(
                        update, context, user_groups[0]['id'], telegram_user.id, simplify=simplify
                    )
                    if sent:
                        context.chat_data[f'kbd_owner_{sent.message_id}'] = telegram_user.id
                else:
                    # Multiple groups — store per-user and track chat for re-fetch
                    context.user_data['balance_groups'] = user_groups
                    context.user_data['balance_groups_page'] = 0
                    context.user_data['balance_chat_id'] = telegram_chat_id

                    message = (
                        "<b>View My Balance</b>\n\n"
                        "Select a group to view your balance:"
                    )
                    keyboard = BalanceKeyboard.get_group_selection_keyboard(
                        user_groups, page=0, action_prefix="mybalance"
                    )

                    sent = await update.message.reply_text(
                        message,
                        parse_mode="HTML",
                        reply_markup=keyboard
                    )
                    context.chat_data[f'kbd_owner_{sent.message_id}'] = telegram_user.id
        except Exception as e:
            logger.error(f"Error in mybalance command: {e}", exc_info=True)
            await update.message.reply_text(ERROR_MSG)



async def _show_group_balances(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    user_id: int,
    edit_message: bool = False,
    simplify: bool = True
):
    """Show all balances for a group. Returns the sent Message when using reply_text, else None."""
    try:
        async with get_db() as db:
            balances = await BalanceService.get_group_balances(
                db, group_id, user_id, simplify=simplify
            )
            is_private = (update.effective_chat.type == "private") if update.effective_chat else False
            message = _format_group_balances_message(balances, is_private=is_private)
            has_debts = len(balances['debts']) > 0
            keyboard = BalanceKeyboard.get_group_balances_keyboard(group_id, has_debts, is_simplified=simplify)

            if edit_message and update.callback_query:
                await update.callback_query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
                return None
            return await update.message.reply_text(message, parse_mode="HTML", reply_markup=keyboard)
    except GroupNotFoundException:
        await _send_error(update, "Group not found.", edit_message)
    except UnauthorizedActionException:
        await _send_error(update, "You are not a member of this group.", edit_message)
    except Exception as e:
        logger.error(f"Error showing group balances: {e}", exc_info=True)
        await _send_error(update, ERROR_MSG, edit_message)
    return None


async def _show_user_balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    user_id: int,
    edit_message: bool = False,
    simplify: bool = True
):
    """Show a user's balance in a specific group. Returns the sent Message when using reply_text, else None."""
    try:
        async with get_db() as db:
            balance = await BalanceService.get_user_balance_in_group(
                db, group_id, user_id, simplify=simplify
            )
            message = _format_user_balance_message(balance)
            has_debts = len(balance['owes_to']) > 0 or len(balance['owed_by']) > 0
            owes_money = len(balance['owes_to']) > 0
            has_owed_by = len(balance['owed_by']) > 0
            keyboard = BalanceKeyboard.get_user_balance_keyboard(
                group_id, has_debts, owes_money, is_simplified=simplify, has_owed_by=has_owed_by
            )

            if edit_message and update.callback_query:
                await update.callback_query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
                return None
            return await update.message.reply_text(message, parse_mode="HTML", reply_markup=keyboard)
    except GroupNotFoundException:
        await _send_error(update, "Group not found.", edit_message)
    except UnauthorizedActionException:
        await _send_error(update, "You are not a member of this group.", edit_message)
    except Exception as e:
        logger.error(f"Error showing user balance: {e}", exc_info=True)
        await _send_error(update, ERROR_MSG, edit_message)
    return None


def _format_group_balances_message(balances: dict, is_private: bool = False) -> str:
    """Format the group balances message."""
    group = balances['group']
    members = balances['members']
    debts = balances['debts']
    currency = balances['currency']
    conversion_warnings = balances.get('conversion_warnings', [])

    message = f"<b>Balances: {h(group['name'])}</b>\n"
    message += f"<i>Currency: {h(currency)}</i>\n\n"

    if conversion_warnings:
        pairs = ", ".join(conversion_warnings)
        message += (
            f"⚠️ <i>Could not convert rates for: {pairs}. "
            "Some amounts may be in their original currency.</i>\n\n"
        )

    # Check if all settled
    has_unsettled = any(m['balance'] != 0 for m in members)

    if not has_unsettled:
        message += "All settled up! No outstanding balances.\n"
    else:
        # Member balances summary
        message += "<b>Member Summary:</b>\n"
        for member in members:
            name = get_display_name(member)
            balance = member['balance']

            if balance > 0:
                message += f"  {name}: gets back {_format_amount(balance, currency)}\n"
            elif balance < 0:
                message += f"  {name}: owes {_format_amount(abs(balance), currency)}\n"
            else:
                message += f"  {name}: settled up\n"

        # Individual debts
        if debts:
            message += "\n<b>Who Owes Whom:</b>\n"

            members_lookup = {m['user_id']: m for m in members}
            for debt in debts:
                from_user = members_lookup.get(debt['from_user_id'], {})
                to_user = members_lookup.get(debt['to_user_id'], {})
                from_name = get_display_name(from_user) if from_user else f"User {debt['from_user_id']}"
                to_name = get_display_name(to_user) if to_user else f"User {debt['to_user_id']}"
                message += f"  {from_name} ---> {to_name}: {_format_amount(debt['amount'], currency)}\n"

    # Multi-currency breakdown (only shown when group has expenses in multiple currencies)
    per_currency = balances.get('per_currency_totals', {})
    if len(per_currency) > 1:
        message += "\n<b>Expenses by Currency:</b>\n"
        for cur, total in sorted(per_currency.items()):
            message += f"  {h(cur)}: {_format_amount(total, cur)}\n"

    # Always show total group spend (converted to group default currency)
    total_spend = balances.get('total_spend')
    if total_spend is not None and total_spend > 0:
        if len(per_currency) > 1:
            message += f"  → Total ({h(currency)}): {_format_amount(total_spend, currency)}\n"
        else:
            message += f"\n<b>Total Group Spend:</b> {_format_amount(total_spend, currency)}\n"

    requesting_user_stats = balances.get('requesting_user_stats')
    if is_private and requesting_user_stats:
        net_balance = requesting_user_stats['net_balance']
        total_paid = requesting_user_stats['total_paid']
        total_share = requesting_user_stats['total_share']
        message += "\n<b>My Stats:</b>\n"
        message += f"  My expenses:             {_format_amount(total_share, currency)}\n"
        message += f"  Total amount paid first: {_format_amount(total_paid, currency)}\n"
        if net_balance > 0:
            message += f"  My balance:              +{_format_amount(net_balance, currency)}\n"
        elif net_balance < 0:
            message += f"  My balance:              -{_format_amount(abs(net_balance), currency)}\n"
        else:
            message += "  My balance:              Settled up\n"
    elif not is_private:
        # Group chat always shows the hint — personal stats are only visible in private chat
        message += "\n💡 <i>Send me a private message to check your personal balance for this group.</i>\n"

    return message


def _format_user_balance_message(balance: dict) -> str:
    """Format the user balance message."""
    group = balance['group']
    net_balance = balance['net_balance']
    owes_to = balance['owes_to']
    owed_by = balance['owed_by']
    currency = balance['currency']
    conversion_warnings = balance.get('conversion_warnings', [])

    message = f"<b>My Balance: {h(group['name'])}</b>\n"
    message += f"<i>Currency: {h(currency)}</i>\n\n"

    if conversion_warnings:
        pairs = ", ".join(conversion_warnings)
        message += (
            f"⚠️ <i>Could not convert rates for: {pairs}. "
            "Some amounts may be in their original currency.</i>\n\n"
        )

    # Net balance summary
    if net_balance > 0:
        message += f"<b>You are owed {_format_amount(net_balance, currency)}</b>\n\n"
    elif net_balance < 0:
        message += f"<b>You owe {_format_amount(abs(net_balance), currency)}</b>\n\n"
    else:
        message += "<b>You are all settled up!</b>\n\n"

    # Who owes you
    if owed_by:
        message += "<b>People who owe you:</b>\n"
        for debt in owed_by:
            name = get_display_name(debt)
            message += f"  {name}: {_format_amount(debt['amount'], currency)}\n"
        message += "\n"

    # Who you owe
    if owes_to:
        message += "<b>You owe:</b>\n"
        for debt in owes_to:
            name = get_display_name(debt)
            message += f"  {name}: {_format_amount(debt['amount'], currency)}\n"
        message += "\n"

    # Spend stats — always show so users can see their contribution even when settled
    total_paid = balance.get('total_paid')
    total_share = balance.get('total_share')
    total_spend = balance.get('total_spend')
    if total_spend is not None and total_spend > 0:
        message += "<b>Your Stats:</b>\n"
        if total_paid is not None:
            message += f"  Paid:        {_format_amount(total_paid, currency)}\n"
        if total_share is not None:
            message += f"  Your share:  {_format_amount(total_share, currency)}\n"
        message += f"  Group total: {_format_amount(total_spend, currency)}\n"

    return message



async def handle_balance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries from balance keyboards."""
    query = update.callback_query

    telegram_user = update.effective_user
    if not telegram_user:
        logger.warning("Received balance callback without telegram user")
        await query.answer("Session expired. Please try again.", show_alert=True)
        return

    chat_type = update.effective_chat.type if update.effective_chat else "group"
    is_private = chat_type == "private"

    # In group chats, only the user who triggered the command can interact with the keyboard
    if not is_private:
        owner_id = context.chat_data.get(f'kbd_owner_{query.message.message_id}')
        if owner_id is not None and owner_id != telegram_user.id:
            await query.answer("This is not your interaction.", show_alert=True)
            return

    action, data = BalanceKeyboard.extract_callback_info(query.data)

    # Cancel is always safe - answer and close
    if action == BalanceKeyboard.ACTION_CANCEL:
        await query.answer()
        await query.edit_message_text("Closed.")
        return

    if action == BalanceKeyboard.ACTION_TOGGLE_SIMPLIFY:
        await _handle_toggle_simplify(query, context, data, telegram_user.id, is_private=is_private)
        return

    # For pagination, validate context data exists before answering
    if action in [BalanceKeyboard.ACTION_NEXT, BalanceKeyboard.ACTION_PREV]:
        groups = context.user_data.get('balance_groups')
        if not groups:
            await query.answer("This list has expired.", show_alert=True)
            await query.edit_message_text("Session expired. Please use the command again.")
            return

    # For back to list, validate context or prepare to re-fetch
    if action == BalanceKeyboard.ACTION_BACK_TO_LIST:
        groups = context.user_data.get('balance_groups')
        if not groups:
            # Will be re-fetched in _handle_back_to_list, just log for now
            logger.debug(f"Balance groups not in context for user {telegram_user.id}, will re-fetch")

    # Handle NUDGE_PERSON before blanket answer so show_alert works
    if action == BalanceKeyboard.ACTION_NUDGE_PERSON:
        await _handle_nudge_send(query, context, data, telegram_user.id)
        return

    # Validation passed, acknowledge the callback
    await query.answer()

    if action == BalanceKeyboard.ACTION_SELECT_GROUP:
        await _handle_group_selection(query, context, data, telegram_user.id, is_private=is_private)
        return

    if action in [BalanceKeyboard.ACTION_NEXT, BalanceKeyboard.ACTION_PREV]:
        await _handle_pagination(query, context, data, telegram_user.id, is_private)
        return

    if action == BalanceKeyboard.ACTION_REFRESH:
        await _handle_refresh(query, context, data, telegram_user.id, is_private=is_private)
        return

    if action == BalanceKeyboard.ACTION_BACK_TO_LIST:
        await _handle_back_to_list(query, context, telegram_user.id, is_private)
        return

    if action == BalanceKeyboard.ACTION_PAYMENT_HISTORY:
        await _handle_payment_history(query, data, telegram_user.id)
        return

    if action == BalanceKeyboard.ACTION_BACK:
        # Re-render the user balance view for this group
        group_id_str = data
        try:
            group_id = int(group_id_str)
        except (TypeError, ValueError):
            await query.edit_message_text("Invalid group.")
            return
        async with get_db() as db:
            simplify = await _get_effective_simplify(db, group_id, telegram_user.id, context)
            balance = await BalanceService.get_user_balance_in_group(
                db, group_id, telegram_user.id, simplify=simplify
            )
        message = _format_user_balance_message(balance)
        has_debts = len(balance['owes_to']) > 0 or len(balance['owed_by']) > 0
        owes_money = len(balance['owes_to']) > 0
        has_owed_by = len(balance['owed_by']) > 0
        keyboard = BalanceKeyboard.get_user_balance_keyboard(
            group_id, has_debts, owes_money, is_simplified=simplify, has_owed_by=has_owed_by
        )
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
        return

    if action == BalanceKeyboard.ACTION_NUDGE:
        await _handle_nudge_picker(query, context, data, telegram_user.id)
        return


async def _handle_group_selection(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    data: str,
    user_id: int,
    is_private: bool = False
) -> None:
    """Handle group selection for viewing balances."""
    if not data or ':' not in data:
        await query.edit_message_text("Invalid selection.")
        return

    parts = data.split(':')
    action_type = parts[0]  # "balances" or "mybalance"
    group_id = int(parts[1])

    try:
        async with get_db() as db:
            simplify = await _get_effective_simplify(db, group_id, user_id, context)
            if action_type == "balances":
                balances = await BalanceService.get_group_balances(
                    db, group_id, user_id, simplify=simplify
                )
                message = _format_group_balances_message(balances, is_private=is_private)
                has_debts = len(balances['debts']) > 0
                keyboard = BalanceKeyboard.get_group_balances_keyboard(group_id, has_debts, is_simplified=simplify)
            else:
                balance = await BalanceService.get_user_balance_in_group(
                    db, group_id, user_id, simplify=simplify
                )
                message = _format_user_balance_message(balance)
                has_debts = len(balance['owes_to']) > 0 or len(balance['owed_by']) > 0
                owes_money = len(balance['owes_to']) > 0
                has_owed_by = len(balance['owed_by']) > 0
                keyboard = BalanceKeyboard.get_user_balance_keyboard(
                    group_id, has_debts, owes_money, is_simplified=simplify, has_owed_by=has_owed_by
                )

            # Store current view for refresh
            context.user_data['balance_view'] = {
                'type': action_type,
                'group_id': group_id
            }

            await query.edit_message_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
    except GroupNotFoundException:
        await query.edit_message_text("Group not found.")
    except UnauthorizedActionException:
        await query.edit_message_text("You are not a member of this group.")
    except Exception as e:
        logger.error(f"Error handling group selection: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


async def _handle_pagination(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    data: str,
    user_id: int,
    is_private: bool
) -> None:
    """Handle pagination for group list."""
    if not data or ':' not in data:
        await query.edit_message_text("Invalid pagination data.")
        return

    parts = data.split(':')
    action_prefix = parts[0]
    page = int(parts[1])

    # Groups are always stored in user_data (per-user, works for both private and group chats)
    groups = context.user_data.get('balance_groups', [])

    if not groups:
        await query.edit_message_text("Group list expired. Please try the command again.")
        return

    context.user_data['balance_groups_page'] = page

    if action_prefix == "balances":
        title = "View Group Balances"
    else:
        title = "View My Balance"

    message = f"<b>{title}</b>\n\nSelect a group:"
    keyboard = BalanceKeyboard.get_group_selection_keyboard(
        groups, page=page, action_prefix=action_prefix
    )

    await query.edit_message_text(
        message,
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def _handle_refresh(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    data: str,
    user_id: int,
    is_private: bool = False
) -> None:
    """Handle refresh of balance view."""
    if ':' not in data:
        await query.answer("Invalid refresh data.", show_alert=True)
        return

    parts = data.split(':')
    view_type = parts[0]  # "group" or "user"
    group_id = int(parts[1])

    try:
        async with get_db() as db:
            simplify = await _get_effective_simplify(db, group_id, user_id, context)
            if view_type == "group":
                balances = await BalanceService.get_group_balances(
                    db, group_id, user_id, simplify=simplify
                )
                message = _format_group_balances_message(balances, is_private=is_private)
                has_debts = len(balances['debts']) > 0
                keyboard = BalanceKeyboard.get_group_balances_keyboard(group_id, has_debts, is_simplified=simplify)
            else:  # user
                balance = await BalanceService.get_user_balance_in_group(
                    db, group_id, user_id, simplify=simplify
                )
                message = _format_user_balance_message(balance)
                has_debts = len(balance['owes_to']) > 0 or len(balance['owed_by']) > 0
                owes_money = len(balance['owes_to']) > 0
                has_owed_by = len(balance['owed_by']) > 0
                keyboard = BalanceKeyboard.get_user_balance_keyboard(
                    group_id, has_debts, owes_money, is_simplified=simplify, has_owed_by=has_owed_by
                )

            await query.edit_message_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            await query.answer("Refreshed!")
    except BadRequest as e:
        # Handle "message is not modified" error gracefully
        if "message is not modified" in str(e).lower():
            await query.answer("Already up to date!")
        else:
            logger.error(f"Error refreshing balance: {e}", exc_info=True)
            await query.answer("Failed to refresh. Please try again.", show_alert=True)
    except Exception as e:
        logger.error(f"Error refreshing balance: {e}", exc_info=True)
        await query.answer("Failed to refresh. Please try again.", show_alert=True)


async def _handle_toggle_simplify(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    data: str,
    user_id: int,
    is_private: bool = False
) -> None:
    """Toggle between simplified and raw debt view, then refresh."""
    if not data or ':' not in data:
        await query.answer("Invalid toggle data.", show_alert=True)
        return

    view_type, group_id_str = data.split(':', 1)
    group_id = int(group_id_str)

    # Flip the in-view simplify state (default True if not yet set)
    current = context.user_data.get(f'balance_simplify_{group_id}', True)
    new_simplify = not current
    context.user_data[f'balance_simplify_{group_id}'] = new_simplify

    await query.answer()

    try:
        async with get_db() as db:
            if view_type == "group":
                balances = await BalanceService.get_group_balances(
                    db, group_id, user_id, simplify=new_simplify
                )
                message = _format_group_balances_message(balances, is_private=is_private)
                has_debts = len(balances['debts']) > 0
                keyboard = BalanceKeyboard.get_group_balances_keyboard(
                    group_id, has_debts, is_simplified=new_simplify
                )
            else:
                balance = await BalanceService.get_user_balance_in_group(
                    db, group_id, user_id, simplify=new_simplify
                )
                message = _format_user_balance_message(balance)
                has_debts = len(balance['owes_to']) > 0 or len(balance['owed_by']) > 0
                owes_money = len(balance['owes_to']) > 0
                has_owed_by = len(balance['owed_by']) > 0
                keyboard = BalanceKeyboard.get_user_balance_keyboard(
                    group_id, has_debts, owes_money, is_simplified=new_simplify, has_owed_by=has_owed_by
                )

        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    except GroupNotFoundException:
        await query.edit_message_text("Group not found.")
    except UnauthorizedActionException:
        await query.edit_message_text("You are not a member of this group.")
    except Exception as e:
        logger.error(f"Error toggling simplify view: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


async def _handle_back_to_list(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    is_private: bool
) -> None:
    """Handle back to group list navigation."""
    groups = context.user_data.get('balance_groups', [])
    page = context.user_data.get('balance_groups_page', 0)

    # Determine action prefix from stored view
    balance_view = context.user_data.get('balance_view', {})
    action_prefix = balance_view.get('type', 'balances')

    if not groups:
        # Re-fetch groups, respecting the original chat scope
        try:
            async with get_db() as db:
                if not is_private:
                    # In group chat, only show groups for this specific chat
                    chat_id = context.user_data.get('balance_chat_id') or query.message.chat_id
                    all_chat_groups = await GroupService.get_group_by_chat_id(db, chat_id)
                    groups = [g for g in all_chat_groups
                              if await GroupService.is_member(db, g['id'], user_id)]
                else:
                    groups = await GroupService.get_all_groups_by_user_id(db, user_id)
                context.user_data['balance_groups'] = groups
        except Exception as e:
            logger.error(f"Error fetching groups: {e}", exc_info=True)
            await query.edit_message_text("Failed to load groups. Please try the command again.")
            return

    if not groups:
        await query.edit_message_text("You are not a member of any groups.")
        return

    if action_prefix == "balances":
        title = "View Group Balances"
    else:
        title = "View My Balance"

    message = f"<b>{title}</b>\n\nSelect a group:"
    keyboard = BalanceKeyboard.get_group_selection_keyboard(
        groups, page=page, action_prefix=action_prefix
    )

    await query.edit_message_text(
        message,
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def _handle_payment_history(query, data: str, user_id: int) -> None:
    """Show recent payment records for a group."""
    if not data:
        await query.edit_message_text("Invalid request.")
        return

    try:
        group_id = int(data)
    except ValueError:
        await query.edit_message_text("Invalid group.")
        return

    try:
        async with get_db() as db:
            if not await GroupService.is_member(db, group_id, user_id):
                await query.edit_message_text("You are not a member of this group.")
                return

            group = await GroupService.get_group_by_id(db, group_id)
            if not group:
                await query.edit_message_text("Group not found.")
                return

            payments = await PaymentService.get_payments_in_group(db, group_id)
            members = await GroupService.get_group_members_with_details(db, group_id)

        members_lookup = {m['user_id']: m for m in members}

        message = f"<b>Payment History: {h(group['name'])}</b>\n\n"

        if not payments:
            message += "No payments recorded yet."
        else:
            for p in payments[:20]:  # cap at 20 most recent
                from_user = members_lookup.get(p['from_user_id'], {})
                to_user = members_lookup.get(p['to_user_id'], {})
                from_name = get_display_name(from_user) if from_user else h(f"User {p['from_user_id']}")
                to_name = get_display_name(to_user) if to_user else h(f"User {p['to_user_id']}")
                date_str = p['created_at'][:10] if p.get('created_at') else ''
                note = f" — {h(p['description'])}" if p.get('description') else ''
                message += (
                    f"<b>{from_name}</b> paid <b>{to_name}</b>\n"
                    f"  {_format_amount(p['amount'], p['currency'])}{note}\n"
                    f"  <i>{date_str}</i>\n\n"
                )

            if len(payments) > 20:
                message += f"<i>Showing 20 of {len(payments)} payments.</i>\n"

        keyboard = BalanceKeyboard.get_close_keyboard()
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error showing payment history: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


async def _handle_nudge_picker(query, context, data: str, user_id: int) -> None:
    """Show the nudge person picker, marking cooldown and recently-nudged users."""
    if not data:
        await query.edit_message_text("Invalid nudge request.")
        return

    try:
        group_id = int(data)
    except ValueError:
        await query.edit_message_text("Invalid group.")
        return

    try:
        async with get_db() as db:
            simplify = await _get_effective_simplify(db, group_id, user_id, context)
            balance = await BalanceService.get_user_balance_in_group(
                db, group_id, user_id, simplify=simplify
            )
        owed_by = balance.get('owed_by', [])

        if not owed_by:
            await query.edit_message_text("No one owes you in this group right now.")
            return

        on_cooldown = {
            p['user_id'] for p in owed_by
            if not can_nudge(user_id, p['user_id'], group_id)
        }
        recently_nudged = context.user_data.get('recently_nudged', {}).get(group_id, [])

        keyboard = BalanceKeyboard.get_nudge_person_picker_keyboard(
            group_id=group_id,
            owed_by=owed_by,
            on_cooldown_ids=on_cooldown,
            recently_nudged_ids=set(recently_nudged),
        )
        await query.edit_message_text(
            "<b>Who would you like to nudge?</b>",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error showing nudge picker: {e}", exc_info=True)
        await query.edit_message_text(ERROR_MSG)


async def _handle_nudge_send(query, context, data: str, nudger_id: int) -> None:
    """Send a nudge to the selected person. DM first, group chat fallback."""
    if not data or ':' not in data:
        await query.answer("Invalid nudge data.", show_alert=True)
        return

    parts = data.split(':', 1)
    try:
        nudgee_id = int(parts[0])
        group_id = int(parts[1])
    except ValueError:
        await query.answer("Invalid nudge data.", show_alert=True)
        return

    if not can_nudge(nudger_id, nudgee_id, group_id):
        remaining = cooldown_remaining(nudger_id, nudgee_id, group_id)
        hours = int(remaining.total_seconds() // 3600) if remaining else 0
        await query.answer(
            f"You already nudged this person recently. Try again in ~{hours}h.",
            show_alert=True
        )
        return

    try:
        async with get_db() as db:
            group = await GroupService.get_group_by_id(db, group_id)
            nudgee_user = await UserService.get_user_by_id(db, nudgee_id)
            nudger_user = await UserService.get_user_by_id(db, nudger_id)

        if not group or not nudgee_user or not nudger_user:
            await query.answer("Could not load user or group info.", show_alert=True)
            return

        group_name = group.get('name', 'the group')
        nudger_name = nudger_user.get('first_name') or nudger_user.get('username') or f"User {nudger_id}"
        nudgee_name = nudgee_user.get('first_name') or nudgee_user.get('username') or f"User {nudgee_id}"
        currency = group.get('default_currency', 'SGD')

        async with get_db() as db:
            simplify = await _get_effective_simplify(db, group_id, nudger_id, context)
            balance = await BalanceService.get_user_balance_in_group(
                db, group_id, nudger_id, simplify=simplify
            )
        owed_entry = next(
            (d for d in balance.get('owed_by', []) if d['user_id'] == nudgee_id),
            None
        )
        amount_str = f"{currency} {owed_entry['amount']:,.2f}" if owed_entry else "some money"

        dm_text = (
            f"👋 Hey! Just a reminder — you owe <b>{h(nudger_name)}</b> "
            f"<b>{amount_str}</b> in the group <b>{h(group_name)}</b>.\n\n"
            "Use /mybalance to check your balance and settle up!"
        )

        sent_dm = False
        try:
            await context.bot.send_message(
                chat_id=nudgee_id, text=dm_text, parse_mode="HTML"
            )
            sent_dm = True
        except Exception as e:
            logger.debug(f"DM nudge to {nudgee_id} failed: {e}")

        if not sent_dm:
            telegram_chat_id = group.get('telegram_chat_id')
            if telegram_chat_id:
                nudgee_username = nudgee_user.get('username')
                mention = f"@{nudgee_username}" if nudgee_username else h(nudgee_name)
                group_text = (
                    f"{mention} Hey! Just a reminder that you have a pending "
                    f"balance in <b>{h(group_name)}</b>. "
                    "Use /mybalance to check your balance!"
                )
                try:
                    await context.bot.send_message(
                        chat_id=telegram_chat_id, text=group_text, parse_mode="HTML"
                    )
                except Exception as e:
                    logger.debug(f"Group chat nudge to {nudgee_id} in chat {telegram_chat_id} failed: {e}")
                    await query.answer(
                        f"Couldn't reach {nudgee_name} — they may need to start the bot first.",
                        show_alert=True
                    )
                    return
            else:
                await query.answer(
                    f"Couldn't reach {nudgee_name} — they may need to start the bot first.",
                    show_alert=True
                )
                return

        record_nudge(nudger_id, nudgee_id, group_id)
        all_nudged = context.user_data.setdefault('recently_nudged', {})
        recently_nudged = all_nudged.setdefault(group_id, [])
        if nudgee_id not in recently_nudged:
            recently_nudged.append(nudgee_id)

        await query.answer(f"Nudge sent to {nudgee_name}!")

        # Re-render picker with updated state
        async with get_db() as db:
            simplify_rerender = await _get_effective_simplify(db, group_id, nudger_id, context)
            balance = await BalanceService.get_user_balance_in_group(
                db, group_id, nudger_id, simplify=simplify_rerender
            )
        owed_by = balance.get('owed_by', [])
        on_cooldown = {
            p['user_id'] for p in owed_by
            if not can_nudge(nudger_id, p['user_id'], group_id)
        }
        keyboard = BalanceKeyboard.get_nudge_person_picker_keyboard(
            group_id=group_id,
            owed_by=owed_by,
            on_cooldown_ids=on_cooldown,
            recently_nudged_ids=set(recently_nudged),
        )
        await query.edit_message_text(
            "<b>Who would you like to nudge?</b>",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    except Exception as e:
        logger.error(f"Error sending nudge: {e}", exc_info=True)
        await query.answer(ERROR_MSG, show_alert=True)


def create_balance_callback_handler() -> CallbackQueryHandler:
    """
    Factory function to create the balance callback query handler.
    """
    return CallbackQueryHandler(
        handle_balance_callback,
        pattern=f"^{BalanceKeyboard.PREFIX}"
    )
