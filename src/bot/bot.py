import asyncio

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from config import BOT_API_TOKEN
from bot.config import setup_commands
from bot.handlers import (
    start_command,
    profile_command,
    groups_command,
    create_group_callback_handler,
    expenses_command,
    create_expense_view_callback_handler,
    balances_command,
    mybalance_command,
    create_balance_callback_handler
)
from bot.conversations import (
    create_update_conversation_handler,
    create_group_conversation_handler,
    create_expense_conversation_handler,
    create_edit_expense_conversation_handler,
    create_settle_conversation_handler
)
from infrastructure import close_db
import logging

logger = logging.getLogger(__name__)


class Bot:
    def __init__(self, use_webhook: bool = False):
        logger.info("Initializing bot...")
        builder = Application.builder().token(BOT_API_TOKEN)
        if use_webhook:
            # Disable the built-in Updater so our Starlette server handles updates
            builder = builder.updater(None)
        self.app = builder.build()

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
        self.app.add_handler(create_expense_conversation_handler())
        self.app.add_handler(create_edit_expense_conversation_handler())
        # Settle handler must be before the balance callback handler so it
        # intercepts balance_settle_up callbacks before the generic handler does.
        self.app.add_handler(create_settle_conversation_handler())

        # Add command handlers
        self.app.add_handler(CommandHandler("start", start_command))
        self.app.add_handler(CommandHandler("profile", profile_command))
        self.app.add_handler(CommandHandler('groups', groups_command))
        self.app.add_handler(CommandHandler('expenses', expenses_command))
        self.app.add_handler(CommandHandler('balances', balances_command))
        self.app.add_handler(CommandHandler('mybalance', mybalance_command))

        # Add callback query handlers (these run after stale handler validation)
        self.app.add_handler(create_group_callback_handler())
        self.app.add_handler(create_expense_view_callback_handler())
        self.app.add_handler(create_balance_callback_handler())

        # Add error handler
        self.app.add_error_handler(self.error_handler)
        
        logger.info("Handlers registered successfully")
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors in the bot."""
        logger.error("Exception while handling an update", exc_info=context.error)
    
    async def _cleanup(self, app: Application):
        """Cleanup function called when bot shuts down."""
        await close_db()
    
    def start_webhook(self, webhook_url: str, port: int) -> None:
        """Start the bot in webhook mode (production)."""
        logger.info(f"Starting bot in webhook mode on port {port}...")
        asyncio.run(self._run_webhook(webhook_url, port))

    async def _run_webhook(self, webhook_url: str, port: int) -> None:
        """Run a Starlette web server that handles Telegram webhook updates."""
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import PlainTextResponse, Response
        from starlette.routing import Route
        import uvicorn

        ptb_app = self.app

        async def health(_: Request) -> PlainTextResponse:
            return PlainTextResponse("OK")

        async def webhook(request: Request) -> Response:
            """Put the incoming Telegram update onto PTB's internal queue."""
            await ptb_app.update_queue.put(
                Update.de_json(data=await request.json(), bot=ptb_app.bot)
            )
            return Response()

        starlette_app = Starlette(
            routes=[
                Route("/health", health, methods=["GET"]),
                Route("/webhook", webhook, methods=["POST"]),
            ]
        )

        server = uvicorn.Server(
            config=uvicorn.Config(
                app=starlette_app,
                port=port,
                host="0.0.0.0",
                use_colors=False,
            )
        )

        async with ptb_app:
            await ptb_app.start()
            await ptb_app.bot.set_webhook(
                url=webhook_url,
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
            )
            logger.info(f"Webhook registered at: {webhook_url}")
            await server.serve()
            await ptb_app.stop()

    def start(self):
        """Start the bot in polling mode (local development)."""
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
