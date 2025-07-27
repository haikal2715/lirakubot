import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
# Admin dan lainnya tetap bisa disimpan langsung
ADMIN_ID = 5715651828