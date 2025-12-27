from telegram import Update
from telegram.ext import ContextTypes
from config import BOT_NAME
import logging

logger = logging.getLogger(__name__)

NEW_USER_WELCOME_MSG: str = (
    f"<b>Welcome to {BOT_NAME}!</b>\n\n"
    "Use this bot to ✨automate the bill splitting process✨ with anyone!\n\n"
    "Click on the \"menu\" button to see the list of commands that I will be able to perform!\n\n"
    "If you have any question, please contact my developer at @zhiyiloo"
)

ERROR_MSG: str = (
    "An unexpected error has occurred. Please try again later."
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command"""
    user = update.effective_user
    
    if not user:
        logger.warning("Received /start command without user information")
        return
    
    logger.info(f"Start command from user: {user.id} (@{user.username})")
    
    try:
        await update.message.reply_text(NEW_USER_WELCOME_MSG, parse_mode="HTML")
        logger.debug(f"Successfully sent welcome message to user {user.id}")
    except Exception as e:
        logger.error(f"Error handling start command for user {user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(ERROR_MSG)
        except Exception as send_error:
            logger.error(f"Could not send error message to user: {send_error}")
    