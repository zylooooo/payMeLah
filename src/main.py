import logging
import os
import subprocess
import sys
from pathlib import Path

from bot.bot import Bot
from config import AUTO_MIGRATE, ENV, PORT, WEBHOOK_URL
from models import (  # noqa: E402, F401
    Expense,
    ExpenseParticipant,
    Group,
    GroupMember,
    Payment,
    User,
)
from shared.logger import setup_logging

# Set up logging
log_level = os.getenv('LOG_LEVEL', 'INFO')
log_file = Path(__file__).parent / 'logs' / 'bot.log'

setup_logging(level=log_level, log_file=log_file)

logger = logging.getLogger(__name__)


def run_alembic_migrations():
    """Run Alembic migrations upon startup if AUTO_MIGRATE is True"""
    if not AUTO_MIGRATE:
        logger.info("Alembic auto migration is disabled. Skipping database migrations...")
        return

    logger.info("Running Alembic database migrations...")
    try:
        result = subprocess.run(
            ['alembic', 'upgrade', 'head'],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True
        )

        # Check if any migrations were actually applied
        if 'Running upgrade' in result.stdout:
            logger.info("Applied pending migrations")
        else:
            logger.info("Database is up to date (no pending migrations)")

        if result.stdout:
            logger.debug(f"Migration output: {result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Migration failed: {e.stderr}")
        logger.error(f"Migration output: {e.stdout}")
        logger.warning("Bot will continue starting, but database may be out of sync.")
        # We don't raise here in development to allow the container to stay alive
        # In production, you might want to raise to prevent the bot from running with old schema
        if ENV == 'production':
            raise
    except FileNotFoundError:
        logger.warning("Alembic not found. Ensure migrations are run manually.")
        logger.warning("Run: alembic upgrade head")


def main():
    """Main entry point for the bot application."""
    try:
        logger.info("=" * 50)
        logger.info("Starting PayMeLah Bot")
        logger.info("=" * 50)

        # Database migrations on every startup
        run_alembic_migrations()

        if WEBHOOK_URL:
            logger.info("Starting bot in WEBHOOK mode")
            bot = Bot(use_webhook=True)
            bot.start_webhook(WEBHOOK_URL, PORT)
        else:
            logger.info("Starting bot in POLLING mode")
            bot = Bot()
            bot.start()

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("Bot shutdown successfully")


if __name__ == "__main__":
    main()
