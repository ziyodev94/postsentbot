import os
from dotenv import load_dotenv

# .env faylni yuklash
load_dotenv("config.env")  # yoki agar `.env` bo‘lsa: load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
