from telegram import (
    BotCommand,
    Bot,
    BotCommandScopeAllPrivateChats
)
import logging

logger = logging.getLogger(__name__)

PRIVATE_COMMANDS = [
    BotCommand(command="start", description="Start using PayMeLah"),
    BotCommand(command="profile", description="View your profile information"),
    BotCommand(command="update", description="Update your profile information")
]

async def setup_commands(bot: Bot) -> None:
    """Setup the commands for the bot"""
    try:
        logger.info("Setting up bot commands...")

        # Set up commands for private chats
        await bot.set_my_commands(
            PRIVATE_COMMANDS,
            scope=BotCommandScopeAllPrivateChats()
        )
    
        logger.info("Bot commands setup successfully")
    except Exception as e:
        logger.error(f"Error setting up bot commands: {e}", exc_info=True)
        raise
