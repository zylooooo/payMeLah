from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from config import BOT_API_TOKEN
from bot.config import setup_commands
from bot.handlers import start_command, profile_command, groups_command, create_group_callback_handler
from bot.conversations import (
    create_update_conversation_handler,
    create_group_conversation_handler
)
from infrastructure import close_db
import logging

logger = logging.getLogger(__name__)


class Bot:
    def __init__(self):
        logger.info("Initializing bot...")
        # Create the application
        self.app = Application.builder().token(BOT_API_TOKEN).build()

        # Setup commands after the app starts
        self.app.post_init = self._setup_commands

        # Setup cleanup function
        self.app.post_shutdown = self._cleanup

        # Register the command handlers
        self.setup_handlers()
        logger.info("Bot initialized successfully!")

    async def _setup_commands(self, app: Application):
        """Setup commands after app initialization (has event loop)."""
        await setup_commands(app.bot)
    
    def setup_handlers(self):
        logger.info("Setting up handlers...")
        # Add conversation handlers first (order matters - they should be before command handlers)
        self.app.add_handler(create_update_conversation_handler())
        self.app.add_handler(create_group_conversation_handler())

        # Add command handlers
        self.app.add_handler(CommandHandler("start", start_command))
        self.app.add_handler(CommandHandler("profile", profile_command))
        self.app.add_handler(CommandHandler('groups', groups_command))

        # Add callback query handler
        self.app.add_handler(create_group_callback_handler())

        # Add error handler
        self.app.add_error_handler(self.error_handler)
        
        logger.info("Handlers registered successfully")
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors in the bot."""
        logger.error("Exception while handling an update", exc_info=context.error)
    
    async def _cleanup(self, app: Application):
        """Cleanup function called when bot shuts down."""
        await close_db()
    
    def start(self):
        """Start the bot in polling mode."""
        logger.info("Starting bot in polling mode...")
        try:
            self.app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
            )
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Error running bot: {e}", exc_info=True)
            raise
        finally:
            logger.info("Bot shutdown complete")
