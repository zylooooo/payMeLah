from telegram import Update
from telegram.ext import ContextTypes
from config import BOT_NAME
from services import UserService
from infrastructure import get_db
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
    """
    Handle the /start command. Auto creates a new user if the user does not alredy exists.
    Sends a self-introduction message to the user to explain the bot's purpose.
    """
    telegram_user = update.effective_user
    
    if not telegram_user:
        logger.warning("Received /start command without user information")
        return
    
    logger.info(f"Start command from user: {telegram_user.id} (@{telegram_user.username})")
    
    try:
        async with get_db() as db:
            # Check if the user already exists
            user = await UserService.get_user_by_id(db, telegram_user.id)
            
            if not user:
                # Create the new user if user does not already exists
                user = await UserService.create_user(
                    db,
                    telegram_user.id,
                    telegram_user.username,
                    telegram_user.first_name,
                    telegram_user.last_name
                )
        
        # Send the welcome message
        await update.message.reply_text(NEW_USER_WELCOME_MSG, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error handling start command for user {telegram_user.id}: {e}", exc_info=True)
        await update.message.reply_text(ERROR_MSG)
    