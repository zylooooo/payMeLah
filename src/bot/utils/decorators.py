from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
import logging
from bot.keyboards import ChatRedirectKeyboard

logger = logging.getLogger(__name__)

def validate_chat_type(*allowed_chat_types: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            chat_type = update.effective_chat.type
            command = update.message.text.split()[0]
            if chat_type not in allowed_chat_types:
                logger.warning(f"User tried to access {command} in an invalid chat type: {chat_type}")

                # Redirect user to private chat if they attempt to access a private command in a group chat
                if chat_type in ["group", "supergroup"] and "private" in allowed_chat_types:
                    await update.message.reply_text(
                        f"<b>⚠️ The {command} command is not available in group chats!</b>\n\n"
                        "Click the button below to access the command in a private chat!",
                        reply_markup=ChatRedirectKeyboard.get_keyboard(),
                        parse_mode="HTML"
                    )
                else:
                    await update.message.reply_text(
                        f"⚠️ This command is not available in {chat_type} chats!\n"
                        f"Please use this command in these {', '.join(allowed_chat_types)} chats where I am added to!"
                    )
                return
            return await func(update, context)
        return wrapper
    return decorator
