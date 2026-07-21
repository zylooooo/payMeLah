import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.utils import h, validate_chat_type
from infrastructure import get_db
from services import UserService

logger = logging.getLogger(__name__)


def _format_profile_message(user: dict) -> str:
    """Format the user's profile into a readable message."""
    if not user:
        return (
            "<b>No profile information found.</b>\n\n"
            "If you are a new user, please use the /start command to begin using the bot."
        )

    username = h(user.get("username")) or "Not set"
    first_name = h(user.get("first_name")) or "Not set"
    last_name = h(user.get("last_name")) or "Not set"
    preferred_currency = user.get("preferred_currency", "SGD")
    simplify_display = "Simplified ✓" if user.get("simplify_debts", True) else "Raw Debts"

    username_display = f"@{username}" if username and username != "Not set" else username

    return (
        "<b><u>Your Profile</u></b>\n\n"
        f"<b>Telegram username:</b> {username_display}\n"
        f"<b>First name:</b> {first_name}\n"
        f"<b>Last name:</b> {last_name}\n"
        f"<b>Preferred currency:</b> {preferred_currency}\n"
        f"<b>Debt view preference:</b> {simplify_display}\n\n"
        "Use /update to change any of these settings."
    )


@validate_chat_type("private")
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/profile command handler. Shows the user's current profile settings."""
    telegram_user = update.effective_user
    if not telegram_user:
        logger.warning("Received /profile command without telegram user information")
        return

    logger.info(f"Showing profile for user {telegram_user.id}")
    try:
        async with get_db() as db:
            user = await UserService.get_user_by_id(db, telegram_user.id)

        await update.message.reply_text(_format_profile_message(user), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in profile command for user {telegram_user.id}: {e}", exc_info=True)
        await update.message.reply_text(
            "An unexpected error occurred while getting your profile information. Please try again later."
        )
