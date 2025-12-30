import os
from dotenv import load_dotenv
from pathlib import Path

# Get to the root directory of the project from the config.py file
BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / '.env')

# Load the environment variables
BOT_API_TOKEN = os.getenv('BOT_API_TOKEN')
if not BOT_API_TOKEN:
    raise ValueError("API token is not set. Check your environment variables.")

BOT_NAME = os.getenv('BOT_NAME')
if not BOT_NAME:
    raise ValueError("Bot name is not set. Check your environment variables.")

DB_URL = os.getenv('DB_URL')
if not DB_URL:
    raise ValueError("Database connection URL is not set. Check your environment variables.")

# Alembic automigration, default is False. If true, Alembic migrations will be run automatically when the bot starts.
AUTO_MIGRATE = os.getenv('AUTO_MIGRATE', 'false').lower() == 'true'

ENV = os.getenv('ENV')
