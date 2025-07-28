import os
import logging
import requests
import gspread
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from google.oauth2.service_account import Credentials
from flask import Flask
import threading

=== KONFIGURASI BOT ===

TELEGRAM_BOT_TOKEN = os.getenv('BOT_TOKEN') EXCHANGE_API_KEY = os.getenv('EXCHANGE_API_KEY') ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID') GOOGLE_SHEETS_CREDS = 'lirakubot.json' SHEET_NAME = 'DATA LIRAKU.ID'

=== KONSTANTA ===

MARGIN_PER_100K = 3500 ADMIN_FEE = 7000 BCA_ACCOUNT = "7645257260" ACCOUNT_NAME = "Muhammad Haikal Sutanto" BUY_LIRA_ACTIVE = True   # Ubah jadi False jika ingin menonaktifkan fitur beli SELL_LIRA_ACTIVE = True  # Ubah jadi False jika ingin menonaktifkan fitur jual

=== LOGGING ===

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO) logger = logging.getLogger(name)

=== INISIALISASI APLIKASI ===

application = Application.builder().token(TELEGRAM_BOT_TOKEN).build() user_sessions = {}  # Untuk menyimpan sesi user sementara

=== SETUP GOOGLE SHEETS ===

def setup_google_sheets(): try: scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'] credentials = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDS, scopes=scopes) client = gspread.authorize(credentials) return client.open(SHEET_NAME).sheet1 except Exception as e: logger.error(f"Google Sheets error: {e}") return None

=== AMBIL KURS DENGAN MARGIN ===

def get_rate(direction='IDR_TO_TRY'): try: if direction == 'IDR_TO_TRY': url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_API_KEY}/pair/IDR/TRY" margin_factor = 0.965  # 3.5% margin dikurangi else: url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_API_KEY}/pair/TRY/IDR" margin_factor = 1.035  # 3.5% margin ditambah

response = requests.get(url)
    data = response.json()
    if data['result'] == 'success':
        base_rate = data['conversion_rate']
        return base_rate * margin_factor
    else:
        logger.error(f"Exchange API error: {data}")
        return 0.000213 if direction == 'IDR_TO_TRY' else 4700
except Exception as e:
    logger.error(f"Error fetching rate: {e}")
    return 0.000213 if direction == 'IDR_TO_TRY' else 4700

=== FORMAT RUPIAH ===

def format_currency(amount): return f"{amount:,.0f}".replace(",", ".")

def calculate_idr_amount(try_amount, rate):
    """Calculate IDR amount after reverse margin"""
    return try_amount / rate

def create_main_menu():
    """Create main menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("💸 Beli Lira (IDR → TRY)", callback_data="buy_lira")],
        [InlineKeyboardButton("💰 Jual Lira (TRY → IDR)", callback_data="sell_lira")],
        [InlineKeyboardButton("💱 Lihat Simulasi Kurs", callback_data="check_rate")],
        [InlineKeyboardButton("👤 Kontak Admin", callback_data="contact_admin")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_back_menu():
    keyboard = [
        [InlineKeyboardButton("🔙 Kembali", callback_data="back")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_payment_menu():
    keyboard = [
        [InlineKeyboardButton("✅ Saya sudah bayar", callback_data="payment_done")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="back")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_send_menu():
    keyboard = [
        [InlineKeyboardButton("📤 Saya sudah kirim Lira", callback_data="send_done")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="back")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """ Selamat datang di LiraKuBot!

✅ Proses cepat & aman
✅ Bisa jual atau beli Lira
✅ Langsung kirim ke IBAN
✅ Lebih hemat dibanding bandara/bank

Silakan pilih menu:"""
    await update.message.reply_text(welcome_text, reply_markup=create_main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "main_menu":
        await show_main_menu(query)
    elif data == "buy_lira":
        if not BUY_LIRA_ACTIVE:
            await query.edit_message_text("❌ Maaf, pembelian Lira sedang tidak tersedia.", reply_markup=create_main_menu())
            return
        await start_buy_process(query, context)
    elif data == "sell_lira":
        if not SELL_LIRA_ACTIVE:
            await query.edit_message_text("❌ Maaf, penjualan Lira sedang tidak tersedia.", reply_markup=create_main_menu())
            return
        await start_sell_process(query, context)
    elif data == "check_rate":
        await show_exchange_rate(query)
    elif data == "contact_admin":
        await show_contact_info(query)
    elif data == "back":
        await handle_back(query, context)
    elif data == "payment_done":
        await handle_payment_confirmation(query, context)
    elif data == "send_done":
        await handle_send_confirmation(query, context)

async def show_main_menu(query):
    welcome_text = """💚 Selamat datang di LiraKuBot!

✅ Proses cepat & aman
✅ Bisa jual atau beli Lira
✅ Langsung kirim ke IBAN
✅ Lebih hemat dibanding bandara/bank

Silakan pilih menu:"""
    await query.edit_message_text(welcome_text, reply_markup=create_main_menu())

async def start_buy_process(query, context):
    """Start buying Lira (IDR → TRY)"""
    user_id = query.from_user.id
    user_sessions[user_id] = {'step': 'amount', 'type': 'buy'}

    text = """💸 Beli Lira Turki

Masukkan jumlah Rupiah yang ingin ditukar:
(Contoh: Rp500.000 tulis 500000)

Minimal pembelian: Rp100.000"""
    await query.edit_message_text(text, reply_markup=create_back_menu())

async def start_sell_process(query, context):
    """Start selling Lira (TRY → IDR)"""
    user_id = query.from_user.id
    user_sessions[user_id] = {'step': 'amount', 'type': 'sell'}

    text = """💰 Jual Lira ke Rupiah

Masukkan jumlah Lira yang ingin dijual:
(Contoh: TRY 200 tulis 200)

Minimal penjualan: TRY 100"""
    await query.edit_message_text(text, reply_markup=create_back_menu())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle input messages"""
    user_id = update.message.from_user.id
    if user_id not in user_sessions:
        return

    session = user_sessions[user_id]
    step = session.get('step')
    tx_type = session.get('type')

    if step == 'amount':
        await process_amount(update, context, tx_type)
    elif step == 'name':
        await process_name(update, context)
    elif step == 'iban_or_rekening':
        await process_iban_or_rekening(update, context)

async def process_amount(update: Update, context: ContextTypes.DEFAULT_TYPE, tx_type):
    """Handle amount for buy/sell"""
    user_id = update.message.from_user.id
    text = update.message.text.strip().replace('.', '').replace(',', '').replace('rp', '').replace('RP', '').replace(' ', '')

    try:
        amount = int(text)
        if tx_type == 'buy' and amount < 100000:
            await update.message.reply_text("❌ Minimal pembelian Rp100.000.\n\nSilakan masukkan nominal yang valid:", reply_markup=create_back_menu())
            return
        if tx_type == 'sell' and amount < 100:
            await update.message.reply_text("❌ Minimal penjualan TRY 100.\n\nSilakan masukkan nominal yang valid:", reply_markup=create_back_menu())
            return

        user_sessions[user_id]['amount'] = amount
        user_sessions[user_id]['step'] = 'name'

        if tx_type == 'buy':
            rate = get_exchange_rate()
            try_amount = calculate_try_amount(amount, rate)
            text = f"""💰 Nominal: Rp{format_currency(amount)}
🇹🇷 Estimasi TRY: {try_amount:.0f}

👤 Masukkan Nama Lengkap Sesuai Nomor IBAN:
(Nama harus sama dengan pemilik IBAN)"""
        else:
            rate = get_exchange_rate()
            idr_amount = calculate_idr_amount(amount, rate)
            total_received = idr_amount - ADMIN_FEE
            text = f"""🪙 Nominal: TRY {amount}
💰 Estimasi Rupiah: Rp{format_currency(idr_amount)}
💸 Setelah Biaya Admin: Rp{format_currency(total_received)}

👤 Masukkan Nama Lengkap Kamu:"""

        await update.message.reply_text(text, reply_markup=create_back_menu())

    except ValueError:
        await update.message.reply_text("❌ Format nominal tidak valid. Contoh: 500000", reply_markup=create_back_menu())

async def process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    name = update.message.text.strip()

    if len(name) < 2:
        await update.message.reply_text("❌ Nama terlalu pendek.\n\nMasukkan nama lengkap:", reply_markup=create_back_menu())
        return

    user_sessions[user_id]['name'] = name
    user_sessions[user_id]['step'] = 'iban_or_rekening'

    tx_type = user_sessions[user_id]['type']

    if tx_type == 'buy':
        text = f"""✅ Nama: {name}

🏦 Masukkan nomor IBAN tujuan (format: TR1234567890...)

Contoh: TR123456789012345678901234"""
    else:
        text = f"""✅ Nama: {name}

🏦 Masukkan nomor rekening BCA kamu untuk menerima Rupiah:"""

    await update.message.reply_text(text, reply_markup=create_back_menu())

text = f"""💰 Nominal: Rp{formatted_amount}
🇹🇷 Estimasi TRY: {try_amount:.2f}

👤 Masukkan Nama Lengkap Sesuai Nomor IBAN:
(Nama harus sama dengan pemilik IBAN)"""
        await query.edit_message_text(text, reply_markup=create_back_menu())
    
    elif step == 'sell_name':
        session['step'] = 'sell_amount'
        await query.edit_message_text(
            "💸 Masukkan jumlah Lira (TRY) yang ingin Anda jual ke Rupiah:",
            reply_markup=create_back_menu()
        )

elif step == 'sell_iban':
        session['step'] = 'sell_name'
        await query.edit_message_text(
            "👤 Masukkan nama lengkap Anda sesuai rekening penerima:",
            reply_markup=create_back_menu()
        )
    elif step == 'sell_amount':
        session['step'] = 'sell_method'
        await query.edit_message_text(
            "💰 Masukkan metode pembayaran (contoh: BCA, Dana, dll):",
            reply_markup=create_back_menu()
        )

def main():
    """Start the bot"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
        return

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start bot with polling
    logger.info("Starting LiraKu Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

from fastapi import FastAPI, Request
import uvicorn
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# FastAPI app for webhook
app = FastAPI()

@app.post("/")
async def webhook_handler(request: Request):
    """Handle incoming Telegram updates via webhook"""
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": False}

@app.on_event("startup")
async def startup():
    # Set webhook to current URL (change URL to your Render or server domain)
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # contoh: https://lirakubot.onrender.com
    try:
        await application.bot.set_webhook(WEBHOOK_URL)
        logger.info("Webhook set successfully.")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
    else:
        logger.info("Starting LiraKu Bot via Webhook (FastAPI)...")
        uvicorn.run("main:app", host="0.0.0.0", port=10000)