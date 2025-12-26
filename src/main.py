import logging
import os
import sys
from pathlib import Path

from bot.bot import Bot
from shared.logger import setup_logging

# Set up logging
log_level = os.getenv('LOG_LEVEL', 'INFO')
log_file = Path(__file__).parent / 'logs' / 'bot.log'

setup_logging(level=log_level, log_file=log_file)

logger = logging.getLogger(__name__)


def main() -> None:
    """Main entry point for the bot application."""
    try:
        logger.info("=" * 50)
        logger.info("Starting PayMeLah Bot")
        logger.info("=" * 50)

        bot = Bot()
        bot.start()
    
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
