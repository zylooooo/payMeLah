from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import BOT_NAME


class ChatRedirectKeyboard:
    @classmethod
    def get_keyboard(cls) -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton(
                    "Access private chat",
                    url=f"https://t.me/{BOT_NAME}?start=private"
                )
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
