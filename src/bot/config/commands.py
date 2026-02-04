from telegram import (
    BotCommand,
    Bot,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeAllGroupChats
)
import logging

logger = logging.getLogger(__name__)

PRIVATE_COMMANDS = [
    BotCommand(command="start", description="Start using PayMeLah"),
    BotCommand(command="profile", description="View your profile information"),
    BotCommand(command="update", description="Update your profile information"),
    BotCommand(command="groups", description="View and manage all of your expense groups"),
    BotCommand(command="addexpense", description="Add a new expense to an existing expense group"),
    BotCommand(command="expenses", description="View expenses in your groups"),
    BotCommand(command="balances", description="View all balances in a group"),
    BotCommand(command="mybalance", description="View your balance in a group"),
    BotCommand(command="mytotal", description="View your total balances across all groups")
]

GROUP_COMMANDS = [
    BotCommand(command="newgroup", description="Create a new expense group"),
    BotCommand(command="groups", description="View and manage all of the expense groups in this chat"),
    BotCommand(command="addexpense", description="Add a new expense to an existing expense group"),
    BotCommand(command="expenses", description="View expenses in this group"),
    BotCommand(command="balances", description="View all balances in a group"),
    BotCommand(command="mybalance", description="View your balance in this group")
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
        
        # Set up commands for group chats
        await bot.set_my_commands(
            GROUP_COMMANDS,
            scope=BotCommandScopeAllGroupChats()
        )
    
        logger.info("Bot commands setup successfully")
    except Exception as e:
        logger.error(f"Error setting up bot commands: {e}", exc_info=True)
        raise
