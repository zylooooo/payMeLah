import os
from dotenv import load_dotenv
from pathlib import Path

# Get to the src/ directory of the project from the config.py file (2 levels up)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / '.env')

# Load the environment variables
BOT_API_TOKEN = os.getenv('BOT_API_TOKEN')
if not BOT_API_TOKEN:
    raise ValueError("API token is not set. Check your environment variables.")

BOT_NAME = os.getenv('BOT_NAME')
if not BOT_NAME:
    raise ValueError("Bot name is not set. Check your environment variables.")
