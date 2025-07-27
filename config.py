import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME")
GOOGLE_SHEET_CREDENTIAL = os.getenv("GOOGLE_SHEET_CREDENTIAL")

MARGIN_PER_100K = int(os.getenv("MARGIN_PER_100K"))
BIAYA_ADMIN = int(os.getenv("BIAYA_ADMIN"))

REKENING_BCA = os.getenv("REKENING_BCA")
IBAN_ADMIN = os.getenv("IBAN_ADMIN")