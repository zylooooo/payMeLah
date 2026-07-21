from decimal import Decimal
from typing import List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


class SettleKeyboard:
    """Keyboards for the settle-up conversation flow."""

    PREFIX = "settle_"

    # Actions
    ACTION_SELECT = "select"      # Pick a recipient
    ACTION_PAY_FULL = "pay_full"  # Confirm the full owed amount
    ACTION_CONFIRM = "confirm"    # Final confirmation
    ACTION_BACK = "back"
    ACTION_CANCEL = "cancel"

    @classmethod
    def get_recipient_keyboard(cls, debts: List[dict], currency: str) -> InlineKeyboardMarkup:
        """
        Show all people the user owes money to as selectable buttons.

        Args:
            debts: owes_to list from BalanceService (each has user_id, first_name,
                   username, last_name, amount).
            currency: The group currency code.
        """
        buttons = []
        for debt in debts:
            name = (
                debt.get('first_name')
                or debt.get('username')
                or f"User {debt['user_id']}"
            )
            label = f"{name}  ({currency} {debt['amount']:,.2f})"
            buttons.append([
                InlineKeyboardButton(
                    label,
                    callback_data=cls._build_callback_data(
                        cls.ACTION_SELECT, str(debt['user_id'])
                    )
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "X Cancel",
                callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
            )
        ])
        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_debt_selection_keyboard(
        cls,
        debts: List[dict],
        member_names: dict,
        currency: str
    ) -> InlineKeyboardMarkup:
        """
        Group mode: show every outstanding debt in the group as a selectable button.

        Args:
            debts: debts list from BalanceService (each has from_user_id,
                   to_user_id, amount).
            member_names: {user_id: display_name} lookup for labels.
            currency: The group currency code.
        """
        buttons = []
        for debt in debts:
            from_name = member_names.get(debt['from_user_id'], f"User {debt['from_user_id']}")
            to_name = member_names.get(debt['to_user_id'], f"User {debt['to_user_id']}")
            label = f"{from_name} → {to_name}  ({currency} {debt['amount']:,.2f})"
            buttons.append([
                InlineKeyboardButton(
                    label,
                    callback_data=cls._build_callback_data(
                        cls.ACTION_SELECT,
                        f"{debt['from_user_id']}:{debt['to_user_id']}"
                    )
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "X Cancel",
                callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
            )
        ])
        return InlineKeyboardMarkup(buttons)

    @classmethod
    def get_amount_keyboard(cls, full_amount: Decimal, currency: str) -> InlineKeyboardMarkup:
        """Confirm full amount or let user type a custom amount."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"Pay Full  ({currency} {full_amount:,.2f})",
                    callback_data=cls._build_callback_data(cls.ACTION_PAY_FULL)
                )
            ],
            [
                InlineKeyboardButton(
                    "<< Back",
                    callback_data=cls._build_callback_data(cls.ACTION_BACK)
                ),
                InlineKeyboardButton(
                    "X Cancel",
                    callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
                )
            ]
        ])

    @classmethod
    def get_confirm_keyboard(cls) -> InlineKeyboardMarkup:
        """Final confirm / cancel."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✓ Confirm",
                    callback_data=cls._build_callback_data(cls.ACTION_CONFIRM)
                ),
                InlineKeyboardButton(
                    "X Cancel",
                    callback_data=cls._build_callback_data(cls.ACTION_CANCEL)
                )
            ]
        ])

    @classmethod
    def _build_callback_data(cls, action: str, data: Optional[str] = None) -> str:
        if data:
            return f"{cls.PREFIX}{action}:{data}"
        return f"{cls.PREFIX}{action}"

    @classmethod
    def extract_callback_info(cls, callback_data: str) -> Tuple[Optional[str], Optional[str]]:
        if not callback_data or not callback_data.startswith(cls.PREFIX):
            return None, None
        data_str = callback_data[len(cls.PREFIX):]
        if ':' in data_str:
            action, data = data_str.split(':', 1)
            return action, data
        return data_str, None

    @classmethod
    def matches_prefix(cls, callback_data: str) -> bool:
        return bool(callback_data and callback_data.startswith(cls.PREFIX))
