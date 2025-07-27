import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import GOOGLE_SHEET_NAME, GOOGLE_CREDENTIALS_FILE

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open(LIRAKU.ID).sheet1

def log_transaction(data: dict):
    sheet.append_row(list(data.values()))