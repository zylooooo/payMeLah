from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes, CallbackQueryHandler
from typing import List, Optional
from decimal import Decimal
from infrastructure import get_db
from services import GroupService, UserService
from services.balance_service import BalanceService
from bot.keyboards import GroupKeyboard
from bot.keyboards.balance_keyboard import BalanceKeyboard
from bot.utils import validate_chat_type
from shared import (
    GroupNotFoundException,
    UnauthorizedActionException
)
import logging


logger = logging.getLogger(__name__)

ERROR_MSG: str = "An unexpected error has occurred. Please try again later."


def _get_display_name(user_data: dict) -> str:
    """Get display name from user data."""
    if user_data.get('first_name'):
        name = user_data['first_name']
        if user_data.get('last_name'):
            name += f" {user_data['last_name']}"
        return name
    return user_data.get('username') or f"User {user_data.get('user_id')}"


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
                    await _show_group_balances(
                        update, context, user_groups[0]['id'], telegram_user.id, simplify=simplify
                    )
                else:
                    # Multiple groups - show selection
                    context.chat_data['balance_groups'] = user_groups
                    context.chat_data['balance_groups_page'] = 0

                    message = (
                        "<b>View Group Balances</b>\n\n"
                        "Select a group to view balances:"
                    )
                    keyboard = BalanceKeyboard.get_group_selection_keyboard(
                        user_groups, page=0, action_prefix="balances"
                    )

                    await update.message.reply_text(
                        message,
                        parse_mode="HTML",
                        reply_markup=keyboard
                    )
        except Exception as e:
            logger.error(f"Error in balances command: {e}", exc_info=True)
            await update.message.reply_text(ERROR_MSG)


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
                    await _show_user_balance(
                        update, context, user_groups[0]['id'], telegram_user.id, simplify=simplify
                    )
                else:
                    # Multiple groups - show selection
                    context.chat_data['balance_groups'] = user_groups
                    context.chat_data['balance_groups_page'] = 0

                    message = (
                        "<b>View My Balance</b>\n\n"
                        "Select a group to view your balance:"
                    )
                    keyboard = BalanceKeyboard.get_group_selection_keyboard(
                        user_groups, page=0, action_prefix="mybalance"
                    )

                    await update.message.reply_text(
                        message,
                        parse_mode="HTML",
                        reply_markup=keyboard
                    )
        except Exception as e:
            logger.error(f"Error in mybalance command: {e}", exc_info=True)
            await update.message.reply_text(ERROR_MSG)


@validate_chat_type("private")
async def mytotal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /mytotal command handler.
    Shows the user's total balances across all groups.
    Only available in private chat.
    """
    telegram_user = update.effective_user

    if not telegram_user:
        logger.warning("Received /mytotal command without telegram user")
        return

    logger.info(f"User {telegram_user.id} requested total balances")

    try:
        async with get_db() as db:
            total_balances = await BalanceService.get_user_total_balances(
                db, telegram_user.id
            )

            if not total_balances['groups']:
                await update.message.reply_text(
                    "You are not a member of any groups yet.\n"
                    "Join or create a group to start tracking balances!"
                )
                return

            message = _format_total_balances_message(total_balances)
            keyboard = BalanceKeyboard.get_total_balances_keyboard()

            await update.message.reply_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
    except Exception as e:
        logger.error(f"Error in mytotal command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_MSG)


async def _show_group_balances(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    user_id: int,
    edit_message: bool = False,
    simplify: bool = True
) -> None:
    """Show all balances for a group."""
    try:
        async with get_db() as db:
            balances = await BalanceService.get_group_balances(
                db, group_id, user_id, simplify=simplify
            )

            message = _format_group_balances_message(balances)
            has_debts = len(balances['debts']) > 0
            keyboard = BalanceKeyboard.get_group_balances_keyboard(group_id, has_debts, is_simplified=simplify)

            if edit_message and update.callback_query:
                await update.callback_query.edit_message_text(
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
    except GroupNotFoundException:
        error_msg = "Group not found."
        if edit_message and update.callback_query:
            await update.callback_query.edit_message_text(error_msg)
        else:
            await update.message.reply_text(error_msg)
    except UnauthorizedActionException:
        error_msg = "You are not a member of this group."
        if edit_message and update.callback_query:
            await update.callback_query.edit_message_text(error_msg)
        else:
            await update.message.reply_text(error_msg)
    except Exception as e:
        logger.error(f"Error showing group balances: {e}", exc_info=True)
        error_msg = ERROR_MSG
        if edit_message and update.callback_query:
            await update.callback_query.edit_message_text(error_msg)
        else:
            await update.message.reply_text(error_msg)


async def _show_user_balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    user_id: int,
    edit_message: bool = False,
    simplify: bool = True
) -> None:
    """Show a user's balance in a specific group."""
    try:
        async with get_db() as db:
            balance = await BalanceService.get_user_balance_in_group(
                db, group_id, user_id, simplify=simplify
            )

            message = _format_user_balance_message(balance)
            has_debts = len(balance['owes_to']) > 0 or len(balance['owed_by']) > 0
            owes_money = len(balance['owes_to']) > 0
            keyboard = BalanceKeyboard.get_user_balance_keyboard(
                group_id, has_debts, owes_money, is_simplified=simplify
            )

            if edit_message and update.callback_query:
                await update.callback_query.edit_message_text(
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
    except GroupNotFoundException:
        error_msg = "Group not found."
        if edit_message and update.callback_query:
            await update.callback_query.edit_message_text(error_msg)
        else:
            await update.message.reply_text(error_msg)
    except UnauthorizedActionException:
        error_msg = "You are not a member of this group."
        if edit_message and update.callback_query:
            await update.callback_query.edit_message_text(error_msg)
        else:
            await update.message.reply_text(error_msg)
    except Exception as e:
        logger.error(f"Error showing user balance: {e}", exc_info=True)
        error_msg = ERROR_MSG
        if edit_message and update.callback_query:
            await update.callback_query.edit_message_text(error_msg)
        else:
            await update.message.reply_text(error_msg)


def _format_group_balances_message(balances: dict) -> str:
    """Format the group balances message."""
    group = balances['group']
    members = balances['members']
    debts = balances['debts']
    currency = balances['currency']

    message = f"<b>Balances: {group['name']}</b>\n"
    message += f"<i>Currency: {currency}</i>\n\n"

    # Check if all settled
    has_unsettled = any(m['balance'] != 0 for m in members)

    if not has_unsettled:
        message += "All settled up! No outstanding balances.\n"
        return message

    # Member balances summary
    message += "<b>Member Summary:</b>\n"
    for member in members:
        name = _get_display_name(member)
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

        # Get member lookup
        members_lookup = {m['user_id']: m for m in members}

        for debt in debts:
            from_user = members_lookup.get(debt['from_user_id'], {})
            to_user = members_lookup.get(debt['to_user_id'], {})
            from_name = _get_display_name(from_user) if from_user else f"User {debt['from_user_id']}"
            to_name = _get_display_name(to_user) if to_user else f"User {debt['to_user_id']}"
            amount = debt['amount']

            message += f"  {from_name} -> {to_name}: {_format_amount(amount, currency)}\n"

    return message


def _format_user_balance_message(balance: dict) -> str:
    """Format the user balance message."""
    group = balance['group']
    net_balance = balance['net_balance']
    owes_to = balance['owes_to']
    owed_by = balance['owed_by']
    currency = balance['currency']

    message = f"<b>My Balance: {group['name']}</b>\n"
    message += f"<i>Currency: {currency}</i>\n\n"

    # Net balance summary
    if net_balance > 0:
        message += f"<b>You are owed {_format_amount(net_balance, currency)}</b>\n\n"
    elif net_balance < 0:
        message += f"<b>You owe {_format_amount(abs(net_balance), currency)}</b>\n\n"
    else:
        message += "<b>You are all settled up!</b>\n\n"
        return message

    # Who owes you
    if owed_by:
        message += "<b>People who owe you:</b>\n"
        for debt in owed_by:
            name = _get_display_name(debt)
            message += f"  {name}: {_format_amount(debt['amount'], currency)}\n"
        message += "\n"

    # Who you owe
    if owes_to:
        message += "<b>You owe:</b>\n"
        for debt in owes_to:
            name = _get_display_name(debt)
            message += f"  {name}: {_format_amount(debt['amount'], currency)}\n"

    return message


def _format_total_balances_message(total_balances: dict) -> str:
    """Format the total balances message."""
    groups = total_balances['groups']
    total_owed = total_balances['total_owed']
    total_owes = total_balances['total_owes']

    message = "<b>My Total Balances</b>\n\n"

    # Overall summary by currency
    if total_owed or total_owes:
        message += "<b>Overall Summary:</b>\n"
        all_currencies = set(total_owed.keys()) | set(total_owes.keys())

        for currency in sorted(all_currencies):
            owed = total_owed.get(currency, Decimal('0'))
            owes = total_owes.get(currency, Decimal('0'))
            net = owed - owes

            if net > 0:
                message += f"  {currency}: You are owed {_format_amount(net, currency)}\n"
            elif net < 0:
                message += f"  {currency}: You owe {_format_amount(abs(net), currency)}\n"
            else:
                message += f"  {currency}: Settled up\n"
        message += "\n"

    # Per-group breakdown
    message += "<b>By Group:</b>\n"
    for group_balance in groups:
        group_name = group_balance['group_name']
        currency = group_balance['currency']
        net = group_balance['net_balance']

        if net > 0:
            status = f"owed {_format_amount(net, currency)}"
        elif net < 0:
            status = f"owe {_format_amount(abs(net), currency)}"
        else:
            status = "settled"

        message += f"  <b>{group_name}</b>: {status}\n"

    return message


async def handle_balance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries from balance keyboards."""
    query = update.callback_query

    telegram_user = update.effective_user
    if not telegram_user:
        logger.warning("Received balance callback without telegram user")
        await query.answer("Session expired. Please try again.", show_alert=True)
        return

    chat_type = update.effective_chat.type if update.effective_chat else "private"
    is_private = chat_type == "private"

    action, data = BalanceKeyboard.extract_callback_info(query.data)

    # Cancel is always safe - answer and close
    if action == BalanceKeyboard.ACTION_CANCEL:
        await query.answer()
        await query.edit_message_text("Closed.")
        return

    # Settle up feature not yet implemented
    if action == BalanceKeyboard.ACTION_SETTLE_UP:
        await query.answer("Settlement feature coming soon!", show_alert=True)
        return

    if action == BalanceKeyboard.ACTION_TOGGLE_SIMPLIFY:
        await _handle_toggle_simplify(query, context, data, telegram_user.id)
        return

    # For pagination, validate context data exists before answering
    if action in [BalanceKeyboard.ACTION_NEXT, BalanceKeyboard.ACTION_PREV]:
        groups = context.user_data.get('balance_groups') if is_private else context.chat_data.get('balance_groups')
        if not groups:
            await query.answer("This list has expired.", show_alert=True)
            await query.edit_message_text("Session expired. Please use the command again.")
            return

    # For back to list, validate context or prepare to re-fetch
    if action == BalanceKeyboard.ACTION_BACK_TO_LIST:
        groups = context.user_data.get('balance_groups') if is_private else context.chat_data.get('balance_groups')
        if not groups:
            # Will be re-fetched in _handle_back_to_list, just log for now
            logger.debug(f"Balance groups not in context for user {telegram_user.id}, will re-fetch")

    # Validation passed, acknowledge the callback
    await query.answer()

    if action == BalanceKeyboard.ACTION_SELECT_GROUP:
        await _handle_group_selection(query, context, data, telegram_user.id)
        return

    if action in [BalanceKeyboard.ACTION_NEXT, BalanceKeyboard.ACTION_PREV]:
        await _handle_pagination(query, context, data, telegram_user.id, is_private)
        return

    if action == BalanceKeyboard.ACTION_REFRESH:
        await _handle_refresh(query, context, data, telegram_user.id)
        return

    if action == BalanceKeyboard.ACTION_BACK_TO_LIST:
        await _handle_back_to_list(query, context, telegram_user.id, is_private)
        return


async def _handle_group_selection(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    data: str,
    user_id: int
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
                message = _format_group_balances_message(balances)
                has_debts = len(balances['debts']) > 0
                keyboard = BalanceKeyboard.get_group_balances_keyboard(group_id, has_debts, is_simplified=simplify)
            else:
                balance = await BalanceService.get_user_balance_in_group(
                    db, group_id, user_id, simplify=simplify
                )
                message = _format_user_balance_message(balance)
                has_debts = len(balance['owes_to']) > 0 or len(balance['owed_by']) > 0
                owes_money = len(balance['owes_to']) > 0
                keyboard = BalanceKeyboard.get_user_balance_keyboard(
                    group_id, has_debts, owes_money, is_simplified=simplify
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

    # Get groups from context
    if is_private:
        groups = context.user_data.get('balance_groups', [])
    else:
        groups = context.chat_data.get('balance_groups', [])

    if not groups:
        await query.edit_message_text("Group list expired. Please try the command again.")
        return

    # Update page
    if is_private:
        context.user_data['balance_groups_page'] = page
    else:
        context.chat_data['balance_groups_page'] = page

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
    user_id: int
) -> None:
    """Handle refresh of balance view."""
    if data == "total":
        # Refresh total balances
        try:
            async with get_db() as db:
                total_balances = await BalanceService.get_user_total_balances(
                    db, user_id
                )
                message = _format_total_balances_message(total_balances)
                keyboard = BalanceKeyboard.get_total_balances_keyboard()

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
                logger.error(f"Error refreshing total balances: {e}", exc_info=True)
                await query.answer("Failed to refresh. Please try again.", show_alert=True)
        except Exception as e:
            logger.error(f"Error refreshing total balances: {e}", exc_info=True)
            await query.answer("Failed to refresh. Please try again.", show_alert=True)
        return

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
                message = _format_group_balances_message(balances)
                has_debts = len(balances['debts']) > 0
                keyboard = BalanceKeyboard.get_group_balances_keyboard(group_id, has_debts, is_simplified=simplify)
            else:  # user
                balance = await BalanceService.get_user_balance_in_group(
                    db, group_id, user_id, simplify=simplify
                )
                message = _format_user_balance_message(balance)
                has_debts = len(balance['owes_to']) > 0 or len(balance['owed_by']) > 0
                owes_money = len(balance['owes_to']) > 0
                keyboard = BalanceKeyboard.get_user_balance_keyboard(
                    group_id, has_debts, owes_money, is_simplified=simplify
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
    user_id: int
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
                message = _format_group_balances_message(balances)
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
                keyboard = BalanceKeyboard.get_user_balance_keyboard(
                    group_id, has_debts, owes_money, is_simplified=new_simplify
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
    # Get stored groups and page
    if is_private:
        groups = context.user_data.get('balance_groups', [])
        page = context.user_data.get('balance_groups_page', 0)
    else:
        groups = context.chat_data.get('balance_groups', [])
        page = context.chat_data.get('balance_groups_page', 0)

    # Determine action prefix from stored view
    balance_view = context.user_data.get('balance_view', {})
    action_prefix = balance_view.get('type', 'balances')

    if not groups:
        # Re-fetch groups
        try:
            async with get_db() as db:
                groups = await GroupService.get_all_groups_by_user_id(db, user_id)
                if is_private:
                    context.user_data['balance_groups'] = groups
                else:
                    context.chat_data['balance_groups'] = groups
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


def create_balance_callback_handler() -> CallbackQueryHandler:
    """
    Factory function to create the balance callback query handler.
    """
    return CallbackQueryHandler(
        handle_balance_callback,
        pattern=f"^{BalanceKeyboard.PREFIX}"
    )
