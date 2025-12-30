from telegram import Update
from telegram.ext import ContextTypes
from infrastructure import get_db
from services import UserService
import logging

logger = logging.getLogger(__name__)

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/profile command handler to show the user's profile information."""
    telegram_user = update.effective_user
    response_msg: str = ""
    if not telegram_user:
        logger.warning("Recieved /profile command without telegram user information")
        return
    
    logger.info(f"Show profile information for user: {telegram_user.id} (@{telegram_user.username})")
    try:
        async with get_db() as db:
            user = await UserService.get_user_by_id(db, telegram_user.id)

            # Format the profile information
            response_msg = format_profile_information(user)

            await update.message.reply_text(response_msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"An unexpected error occurred while handling profile command for user {telegram_user.id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred while getting your profile information. Please try again later.")

# Helper function to format the profile information
def format_profile_information(user: dict) -> str:
    """Format the user's profile into a readable message to be displayed to the user."""
    response_msg: str = ""
    # Format response message if the user has not yet been created
    if not user:
        response_msg = (
            "<b>No profile information found.</b>\n\n"
            "If you are a new user, please use the /start command to begin using the bot."
        )
    else:
        # Format response message if the user has already been created
        username = user.get('username') or 'Not set'
        first_name = user.get('first_name') or 'Not set'
        last_name = user.get('last_name') or 'Not set'
        preferred_currency = user.get('preferred_currency', 'SGD')
        
        # Format username with @ if it exists
        username_display = f"@{username}" if username and username != 'Not set' else username
        response_msg = (
            "<b><u>These are your current profile information:</u></b>\n\n"
            f"<b>1.) Telegram username:</b> {username_display}\n"
            f"<b>2.) First name:</b> {first_name}\n"
            f"<b>3.) Last name:</b> {last_name}\n"
            f"<b>4.) Preferred currency:</b> {preferred_currency}\n\n"
            "To update your profile information, please use the /update command."
        )

    return response_msg
