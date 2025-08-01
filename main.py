import os
import logging
import asyncio
import requests
import threading
import json
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, CommandHandler, CallbackQueryHandler, 
        MessageHandler, filters, ContextTypes, ConversationHandler
    )
except ImportError as e:
    print(f"❌ Error importing telegram libraries: {e}")
    print("💡 Coba install ulang dengan: pip install --upgrade python-telegram-bot==20.3")
    exit(1)

# Import Google Sheets dependencies
try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("⚠️ Google Sheets dependencies not found. Install with: pip install gspread google-auth")
    gspread = None
    Credentials = None

# Load environment variables
load_dotenv()

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
EXCHANGE_API_KEY = os.getenv('EXCHANGE_API_KEY')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')
ADMIN_IBAN = os.getenv('ADMIN_IBAN', 'TR1234567890123456789012345')

# Feature toggles
BUY_LIRA_ACTIVE = True
SELL_LIRA_ACTIVE = True

# Conversation states
(WAITING_BUY_AMOUNT, WAITING_BUY_NAME, WAITING_BUY_IBAN, 
 WAITING_SELL_AMOUNT, WAITING_SELL_NAME, WAITING_SELL_ACCOUNT,
 WAITING_VERIFICATION) = range(7)

# Google Sheets setup
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'lirakubot.json'
SPREADSHEET_NAME = 'DATA LIRAKU.ID'

def get_google_sheets_client():
    """Initialize Google Sheets client"""
    try:
        if not gspread or not Credentials:
            logger.warning("Google Sheets dependencies not available")
            return None

        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            logger.error(f"Service account file {SERVICE_ACCOUNT_FILE} not found")
            return None

        creds = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        client = gspread.authorize(creds)
        logger.info("Google Sheets client initialized successfully")
        return client
    except Exception as e:
        logger.error(f"Error initializing Google Sheets: {e}")
        return None

def get_exchange_rate(from_currency='IDR', to_currency='TRY'):
    """Get exchange rate from exchangerate-api"""
    try:
        url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_API_KEY}/pair/{from_currency}/{to_currency}"
        response = requests.get(url, timeout=10)
        data = response.json()

        if data['result'] == 'success':
            return float(data['conversion_rate'])
        else:
            logger.error(f"Exchange rate API error: {data}")
            return None
    except Exception as e:
        logger.error(f"Error fetching exchange rate: {e}")
        return None

def save_to_sheets(transaction_data):
    """Save transaction to Google Sheets"""
    try:
        gc = get_google_sheets_client()
        if not gc:
            logger.warning("Google Sheets not available, skipping save")
            return True

        # Open spreadsheet by name
        try:
            spreadsheet = gc.open(SPREADSHEET_NAME)
            sheet = spreadsheet.sheet1
            logger.info(f"Successfully opened spreadsheet: {SPREADSHEET_NAME}")
        except gspread.SpreadsheetNotFound:
            logger.error(f"Spreadsheet '{SPREADSHEET_NAME}' not found")
            return False

        # Add headers if sheet is empty
        try:
            records = sheet.get_all_records()
            if not records:
                headers = ['Tanggal', 'User ID', 'Username', 'Nama Lengkap', 'IBAN', 'Nominal IDR', 'Jumlah TRY', 'Metode Bayar', 'Fee', 'Total Bayar']
                sheet.append_row(headers)
                logger.info("Headers added to empty spreadsheet")
        except Exception as e:
            logger.warning(f"Could not check/add headers: {e}")

        # Add transaction data
        sheet.append_row(transaction_data)
        logger.info(f"Transaction data saved to spreadsheet")
        return True
        
    except Exception as e:
        logger.error(f"Error saving to sheets: {e}")
        return False

def save_transaction(transaction_data):
    """Save transaction - wrapper function with enhanced logging"""
    logger.info(f"Attempting to save transaction for user {transaction_data[1]}")
    success = save_to_sheets(transaction_data)
    if success:
        logger.info("✅ Transaction saved successfully to Google Sheets")
    else:
        logger.error("❌ Failed to save transaction to Google Sheets")
    return success

def get_main_keyboard():
    """Create main menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("💸 Beli Lira", callback_data="buy_lira")],
        [InlineKeyboardButton("💵 Jual Lira", callback_data="sell_lira")],
        [InlineKeyboardButton("💱 Lihat Simulasi Kurs", callback_data="simulation")],
        [InlineKeyboardButton("👤 Kontak Admin", callback_data="contact_admin")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_menu_keyboard():
    """Create back and menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("🔙 Kembali", callback_data="back")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_verification_keyboard():
    """Create verification keyboard"""
    keyboard = [
        [InlineKeyboardButton("✅ Data Sudah Benar", callback_data="data_correct")],
        [InlineKeyboardButton("❌ Ada yang Salah", callback_data="data_wrong")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="back")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_payment_keyboard():
    """Create payment confirmation keyboard"""
    keyboard = [
        [InlineKeyboardButton("✅ Saya sudah bayar", callback_data="payment_sent")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="back")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def format_currency(amount, currency='IDR'):
    """Format currency display"""
    if currency == 'IDR':
        return f"Rp{amount:,.0f}".replace(',', '.')
    elif currency == 'TRY':
        return f"₺{amount:,.2f}".replace(',', '.')
    return f"{amount:,.2f}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    welcome_message = (
        "💚 **Selamat datang di LiraKuBot!**\n\n"
        "✅ Proses cepat & aman\n"
        "✅ Langsung kirim ke IBAN\n"
        "✅ Lebih hemat dibanding beli di bandara & bank\n\n"
        "Silakan pilih menu:"
    )

    await update.message.reply_text(
        welcome_message,
        reply_markup=get_main_keyboard(),
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()

    if query.data == "main_menu":
        welcome_message = (
            "💚 **Selamat datang di LiraKuBot!**\n\n"
            "✅ Proses cepat & aman\n"
            "✅ Langsung kirim ke IBAN\n"
            "✅ Lebih hemat dibanding beli di bandara & bank\n\n"
            "Silakan pilih menu:"
        )
        await query.edit_message_text(
            welcome_message,
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    elif query.data == "buy_lira":
        if not BUY_LIRA_ACTIVE:
            await query.edit_message_text(
                "❌ Maaf, pembelian Lira sedang tidak tersedia.",
                reply_markup=get_back_menu_keyboard()
            )
            return ConversationHandler.END

        await query.edit_message_text(
            "💸 **Beli Lira (IDR ke TRY)**\n\n"
            "Masukkan nominal dalam Rupiah yang ingin dikonversi ke Lira Turki.\n"
            "Minimal pembelian: Rp100.000\n\n"
            "Contoh: 500000",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        return WAITING_BUY_AMOUNT

    elif query.data == "sell_lira":
        if not SELL_LIRA_ACTIVE:
            await query.edit_message_text(
                "❌ Maaf, penjualan Lira sedang tidak tersedia.",
                reply_markup=get_back_menu_keyboard()
            )
            return ConversationHandler.END

        await query.edit_message_text(
            "💵 **Jual Lira (TRY ke IDR)**\n\n"
            "Masukkan jumlah Lira Turki yang ingin dijual.\n\n"
            "Contoh: 100",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        return WAITING_SELL_AMOUNT

    elif query.data == "simulation":
        await show_simulation(query)

    elif query.data == "contact_admin":
        contact_message = (
            "👤 **Kontak Admin**\n\n"
            "📱 Telegram: @lirakuid\n"
            "📞 WhatsApp: 087773834406"
        )
        await query.edit_message_text(
            contact_message,
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )

    elif query.data == "data_correct":
        await handle_data_verification(update, context, True)

    elif query.data == "data_wrong":
        await handle_data_verification(update, context, False)

    elif query.data == "payment_sent":
        await handle_payment_confirmation(update, context)

    elif query.data == "sell_sent":
        await handle_sell_confirmation(update, context)

    elif query.data == "back":
        await handle_back_navigation(update, context)

async def handle_back_navigation(update, context):
    """Handle back navigation"""
    query = update.callback_query
    current_state = context.user_data.get('current_state', None)

    if current_state == 'buy_amount':
        await query.edit_message_text(
            "💸 **Beli Lira (IDR ke TRY)**\n\n"
            "Masukkan nominal dalam Rupiah yang ingin dikonversi ke Lira Turki.\n"
            "Minimal pembelian: Rp100.000\n\n"
            "Contoh: 500000",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        return WAITING_BUY_AMOUNT
    elif current_state == 'buy_name':
        await query.edit_message_text(
            "💸 **Beli Lira (IDR ke TRY)**\n\n"
            "Masukkan nominal dalam Rupiah yang ingin dikonversi ke Lira Turki.\n"
            "Minimal pembelian: Rp100.000\n\n"
            "Contoh: 500000",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        context.user_data['current_state'] = 'buy_amount'
        return WAITING_BUY_AMOUNT
    elif current_state == 'buy_iban':
        await query.edit_message_text(
            f"💰 **Estimasi Konversi**\n\n"
            f"💸 Nominal: {format_currency(context.user_data.get('buy_amount_idr', 0))}\n"
            f"🇹🇷 Estimasi TRY: ₺{context.user_data.get('buy_estimated_try', 0):.2f}\n\n"
            f"Masukkan nama lengkap sesuai IBAN Anda:",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        context.user_data['current_state'] = 'buy_name'
        return WAITING_BUY_NAME
    else:
        welcome_message = (
            "💚 **Selamat datang di LiraKuBot!**\n\n"
            "✅ Proses cepat & aman\n"
            "✅ Langsung kirim ke IBAN\n"
            "✅ Lebih hemat dibanding beli di bandara & bank\n\n"
            "Silakan pilih menu:"
        )
        await query.edit_message_text(
            welcome_message,
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
        return ConversationHandler.END

async def show_simulation(query):
    """Show exchange rate simulation"""
    idr_to_try_rate = get_exchange_rate('IDR', 'TRY')
    try_to_idr_rate = get_exchange_rate('TRY', 'IDR')

    if not idr_to_try_rate or not try_to_idr_rate:
        await query.edit_message_text(
            "❌ Gagal mengambil data kurs. Silakan coba lagi.",
            reply_markup=get_back_menu_keyboard()
        )
        return

    # Calculate simulation values with 2.5% margin from total
    simulation_message = (
        "💱 **Simulasi Tukar IDR ke TRY**\n"
        f"💸 Rp100.000 ≈ 🇹🇷 ₺{(100000 * idr_to_try_rate * 0.975):.2f}\n"
        f"💸 Rp500.000 ≈ 🇹🇷 ₺{(500000 * idr_to_try_rate * 0.975):.2f}\n"
        f"💸 Rp1.000.000 ≈ 🇹🇷 ₺{(1000000 * idr_to_try_rate * 0.975):.2f}\n\n"
        "💱 **Simulasi Tukar TRY ke IDR**\n"
        f"🇹🇷 ₺100 ≈ {format_currency(100 * try_to_idr_rate * 0.975)}\n"
        f"🇹🇷 ₺500 ≈ {format_currency(500 * try_to_idr_rate * 0.975)}\n"
        f"🇹🇷 ₺1.000 ≈ {format_currency(1000 * try_to_idr_rate * 0.975)}\n\n"
        f"*Margin flat 2.5% dari total untuk semua nominal*\n"
        f"*Update: {datetime.now().strftime('%H:%M %d/%m/%Y')}*"
    )

    await query.edit_message_text(
        simulation_message,
        reply_markup=get_back_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_buy_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buy amount input"""
    try:
        amount = int(update.message.text.replace('.', '').replace(',', ''))

        if amount < 100000:
            await update.message.reply_text(
                "❌ Minimal pembelian adalah Rp100.000\n"
                "Silakan masukkan nominal yang valid.",
                reply_markup=get_back_menu_keyboard()
            )
            return WAITING_BUY_AMOUNT

        # Get exchange rate
        base_rate = get_exchange_rate('IDR', 'TRY')
        if not base_rate:
            await update.message.reply_text(
                "❌ Gagal mengambil data kurs. Silakan coba lagi.",
                reply_markup=get_back_menu_keyboard()
            )
            return WAITING_BUY_AMOUNT

        # Calculate dengan margin 2.5% dari total
        estimated_try = amount * base_rate * 0.975
        fee = amount * 0.025
        total_bayar = amount

        # Store in context
        context.user_data['buy_amount_idr'] = amount
        context.user_data['buy_estimated_try'] = estimated_try
        context.user_data['buy_fee'] = fee
        context.user_data['buy_total_bayar'] = total_bayar
        context.user_data['current_state'] = 'buy_name'

        await update.message.reply_text(
            f"💰 **Estimasi Konversi**\n\n"
            f"🇹🇷 Lira: ₺{amount:,.2f}\n"
            f"💵 IDR kotor: {format_currency(gross_idr)}\n"
            f"💳 Fee (2.5%): {format_currency(fee)}\n"
            f"💰 IDR yang diterima: {format_currency(estimated_idr)}\n\n"
            f"Masukkan nama lengkap Anda:",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        return WAITING_SELL_NAME

    except ValueError:
        await update.message.reply_text(
            "❌ Format jumlah tidak valid. Masukkan angka saja.\n"
            "Contoh: 100 atau 100.50",
            reply_markup=get_back_menu_keyboard()
        )
        return WAITING_SELL_AMOUNT

async def handle_sell_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sell name input"""
    name = update.message.text.strip()

    if len(name) < 2:
        await update.message.reply_text(
            "❌ Nama terlalu pendek. Masukkan nama lengkap yang valid.",
            reply_markup=get_back_menu_keyboard()
        )
        return WAITING_SELL_NAME

    context.user_data['sell_name'] = name
    context.user_data['current_state'] = 'sell_account'

    await update.message.reply_text(
        f"👤 Nama: **{name}**\n\n"
        "Masukkan nomor rekening bank Indonesia Anda.\n"
        "Format: [Nama Bank] - [Nomor Rekening]\n"
        "Contoh: `BCA - 1234567890`",
        reply_markup=get_back_menu_keyboard(),
        parse_mode='Markdown'
    )
    return WAITING_SELL_ACCOUNT

async def handle_sell_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sell account input"""
    account = update.message.text.strip()

    if len(account) < 5 or '-' not in account:
        await update.message.reply_text(
            "❌ Format rekening tidak valid.\n"
            "Format: [Nama Bank] - [Nomor Rekening]\n"
            "Contoh: `BCA - 1234567890`",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        return WAITING_SELL_ACCOUNT

    context.user_data['sell_account'] = account
    context.user_data['current_state'] = 'sell_verification'

    # Show verification for sell
    verification_message = (
        "📋 **Verifikasi Data Penjualan**\n\n"
        f"👤 Nama: {context.user_data['sell_name']}\n"
        f"🏦 Rekening: `{account}`\n"
        f"🇹🇷 TRY yang dikirim: ₺{context.user_data['sell_amount_try']:,.2f}\n"
        f"💵 IDR yang diterima: {format_currency(context.user_data['sell_estimated_idr'])}\n"
        f"💳 Fee: {format_currency(context.user_data['sell_fee'])}\n\n"
        "❓ **Apakah semua data sudah benar?**"
    )

    await update.message.reply_text(
        verification_message,
        reply_markup=get_verification_keyboard(),
        parse_mode='Markdown'
    )
    return WAITING_VERIFICATION

async def handle_sell_verification(update: Update, context: ContextTypes.DEFAULT_TYPE, is_correct: bool):
    """Handle sell data verification"""
    query = update.callback_query
    
    if not is_correct:
        # Data salah - kembali ke input amount
        await query.edit_message_text(
            "❌ **Data dibatalkan**\n\n"
            "Silakan masukkan ulang jumlah Lira Turki:\n\n"
            "Contoh: 100",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        context.user_data['current_state'] = 'sell_amount'
        return WAITING_SELL_AMOUNT
    
    # Data benar - lanjut ke pengiriman
    context.user_data['current_state'] = 'sell_payment'

    summary_message = (
        "✅ **Data Dikonfirmasi - Silakan Kirim Lira**\n\n"
        f"👤 Nama: {context.user_data['sell_name']}\n"
        f"🏦 Rekening: `{context.user_data['sell_account']}`\n"
        f"🪙 TRY yang dikirim: ₺{context.user_data['sell_amount_try']:,.2f}\n"
        f"💵 IDR yang diterima: {format_currency(context.user_data['sell_estimated_idr'])}\n\n"
        f"🏦 **Kirim Lira ke IBAN Admin:**\n"
        f"`{ADMIN_IBAN}`\n\n"
        f"Setelah mengirim, klik tombol di bawah:"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Saya sudah kirim", callback_data="sell_sent")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="back")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        summary_message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def handle_sell_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sell confirmation"""
    query = update.callback_query
    user = query.from_user

    # Check if we have the necessary data
    required_keys = ['sell_name', 'sell_account', 'sell_amount_try', 'sell_estimated_idr', 'sell_fee']
    if not all(key in context.user_data for key in required_keys):
        await query.edit_message_text(
            "❌ Data transaksi tidak lengkap. Silakan mulai transaksi baru.",
            reply_markup=get_main_keyboard()
        )
        return

    # Prepare transaction data untuk spreadsheet
    now = datetime.now()
    transaction_data = [
        now.strftime('%Y-%m-%d %H:%M:%S'),                    # Tanggal
        str(user.id),                                         # User ID
        user.username or '',                                  # Username
        context.user_data.get('sell_name', ''),              # Nama Lengkap
        context.user_data.get('sell_account', ''),            # Rekening (instead of IBAN)
        round(context.user_data.get('sell_estimated_idr', 0)), # Nominal IDR yang diterima
        context.user_data.get('sell_amount_try', 0),          # Jumlah TRY
        'Lira Transfer',                                      # Metode Bayar
        context.user_data.get('sell_fee', 0),                # Fee
        round(context.user_data.get('sell_estimated_idr', 0)) # Total yang diterima
    ]

    # Save transaction
    save_success = save_transaction(transaction_data)

    # Send simple notification to admin (copyable format)
    admin_message = (
        f"🔔 PESANAN JUAL LIRA\n\n"
        f"Nama: {context.user_data.get('sell_name', '')}\n"
        f"Username: @{user.username or 'Tidak ada'}\n"
        f"Rekening: {context.user_data.get('sell_account', '')}\n"
        f"TRY Dikirim: ₺{context.user_data.get('sell_amount_try', 0):,.2f}\n"
        f"IDR Diterima: {format_currency(context.user_data.get('sell_estimated_idr', 0))}\n"
        f"Fee: {format_currency(context.user_data.get('sell_fee', 0))}\n"
        f"IBAN Admin: {ADMIN_IBAN}\n"
        f"Waktu: {now.strftime('%d/%m/%Y %H:%M')}\n"
        f"User ID: {user.id}"
    )

    try:
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_message
            )
            logger.info(f"Admin notification sent for sell transaction from user {user.id}")
    except Exception as e:
        logger.error(f"Error sending admin notification: {e}")

    # Send confirmation to user
    await query.edit_message_text(
        "✅ **Konfirmasi Pengiriman Diterima!**\n\n"
        "Terima kasih! Transaksi Anda sedang diproses.\n"
        "Admin akan segera memverifikasi penerimaan Lira dan mengirim Rupiah ke rekening Anda.\n\n"
        f"📱 **Estimasi Waktu Proses:** 5-15 menit\n"
        f"💬 **Jika ada pertanyaan:** @lirakuid\n\n"
        "Kami akan mengirim notifikasi setelah transfer selesai.",
        reply_markup=get_back_menu_keyboard(),
        parse_mode='Markdown'
    )

    # Clear user data
    context.user_data.clear()

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel conversation"""
    await update.message.reply_text(
        "❌ Transaksi dibatalkan.",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

def main():
    """Main function to run the bot"""
    try:
        # Validate environment variables
        if not BOT_TOKEN:
            raise ValueError("BOT_TOKEN tidak ditemukan dalam environment variables")
        if not EXCHANGE_API_KEY:
            raise ValueError("EXCHANGE_API_KEY tidak ditemukan dalam environment variables")
        if not ADMIN_CHAT_ID:
            logger.warning("ADMIN_CHAT_ID tidak ditemukan, notifikasi admin tidak akan dikirim")

        logger.info("Initializing bot application...")

        # Create application with error handling
        try:
            application = Application.builder().token(BOT_TOKEN).build()
        except Exception as e:
            logger.error(f"Error creating application: {e}")
            from telegram.ext import ApplicationBuilder
            application = ApplicationBuilder().token(BOT_TOKEN).build()

        # Add conversation handler for buy lira with verification
        buy_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(button_handler, pattern="^buy_lira$")],
            states={
                WAITING_BUY_AMOUNT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_amount),
                    CallbackQueryHandler(button_handler, pattern="^(back|main_menu)$")
                ],
                WAITING_BUY_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_name),
                    CallbackQueryHandler(button_handler, pattern="^(back|main_menu)$")
                ],
                WAITING_BUY_IBAN: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_iban),
                    CallbackQueryHandler(button_handler, pattern="^(back|main_menu)$")
                ],
                WAITING_VERIFICATION: [
                    CallbackQueryHandler(button_handler, pattern="^(data_correct|data_wrong|back|main_menu)$")
                ],
            },
            fallbacks=[
                CommandHandler('cancel', cancel),
                CallbackQueryHandler(button_handler, pattern="^(back|main_menu)$")
            ],
            allow_reentry=True
        )

        # Add conversation handler for sell lira with verification
        sell_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(button_handler, pattern="^sell_lira$")],
            states={
                WAITING_SELL_AMOUNT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sell_amount),
                    CallbackQueryHandler(button_handler, pattern="^(back|main_menu)$")
                ],
                WAITING_SELL_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sell_name),
                    CallbackQueryHandler(button_handler, pattern="^(back|main_menu)$")
                ],
                WAITING_SELL_ACCOUNT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sell_account),
                    CallbackQueryHandler(button_handler, pattern="^(back|main_menu)$")
                ],
                WAITING_VERIFICATION: [
                    CallbackQueryHandler(button_handler, pattern="^(data_correct|data_wrong|back|main_menu)$")
                ],
            },
            fallbacks=[
                CommandHandler('cancel', cancel),
                CallbackQueryHandler(button_handler, pattern="^(back|main_menu)$")
            ],
            allow_reentry=True
        )

        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(buy_conv_handler)
        application.add_handler(sell_conv_handler)
        application.add_handler(CallbackQueryHandler(button_handler))

        # Start polling with error handling
        print("🤖 LiraKuBot is starting...")
        logger.info("Bot started successfully")

        # Use run_polling with proper parameters
        application.run_polling(
            timeout=30,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )

    except Exception as e:
        logger.error(f"Critical error starting bot: {e}")
        print(f"❌ Error starting bot: {e}")
        return False

class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for health checks"""
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'LiraKuBot is running!')

    def log_message(self, format, *args):
        # Disable HTTP server logging
        return

def start_http_server():
    """Start simple HTTP server for Render health checks"""
    port = int(os.getenv('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"HTTP server starting on port {port}")
    server.serve_forever()

if __name__ == '__main__':
    # Check if we need HTTP server (for Render Web Service)
    if os.getenv('RENDER'):
        # Start HTTP server in background thread
        http_thread = threading.Thread(target=start_http_server, daemon=True)
        http_thread.start()
        logger.info("HTTP server started for Render")

    # Start the bot
    main()💰 **Estimasi Konversi**\n\n"
            f"💸 Nominal: {format_currency(amount)}\n"
            f"🇹🇷 Estimasi TRY: ₺{estimated_try:.2f}\n"
            f"💳 Fee (2.5%): {format_currency(fee)}\n"
            f"💰 Total Bayar: {format_currency(total_bayar)}\n\n"
            f"Masukkan nama lengkap sesuai IBAN Anda:",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        return WAITING_BUY_NAME

    except ValueError:
        await update.message.reply_text(
            "❌ Format nominal tidak valid. Masukkan angka saja.\n"
            "Contoh: 500000",
            reply_markup=get_back_menu_keyboard()
        )
        return WAITING_BUY_AMOUNT

async def handle_buy_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buy name input"""
    name = update.message.text.strip()

    if len(name) < 2:
        await update.message.reply_text(
            "❌ Nama terlalu pendek. Masukkan nama lengkap yang valid.",
            reply_markup=get_back_menu_keyboard()
        )
        return WAITING_BUY_NAME

    context.user_data['buy_name'] = name
    context.user_data['current_state'] = 'buy_iban'

    await update.message.reply_text(
        f"👤 Nama: **{name}**\n\n"
        f"Masukkan IBAN Turki Anda (format: TR + 24 angka)\n"
        f"Contoh: `TR123456789012345678901234`",
        reply_markup=get_back_menu_keyboard(),
        parse_mode='Markdown'
    )
    return WAITING_BUY_IBAN

async def handle_buy_iban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buy IBAN input"""
    iban = update.message.text.strip().upper().replace(' ', '')

    # IBAN validation
    if not iban.startswith('TR'):
        await update.message.reply_text(
            "❌ IBAN harus dimulai dengan 'TR' untuk Turki.\n"
            "Contoh: `TR123456789012345678901234`",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        return WAITING_BUY_IBAN
    
    if len(iban) < 24 or len(iban) > 28:
        await update.message.reply_text(
            f"❌ Panjang IBAN tidak valid.\n"
            f"📏 Panjang saat ini: {len(iban)} karakter\n"
            f"📏 Standar Turki: 26 karakter (TR + 24 angka)\n\n"
            f"Contoh: `TR123456789012345678901234`",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        return WAITING_BUY_IBAN
    
    if not iban[2:].isdigit():
        await update.message.reply_text(
            "❌ IBAN harus berupa 'TR' diikuti angka saja.\n"
            "Contoh: `TR123456789012345678901234`",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        return WAITING_BUY_IBAN

    context.user_data['buy_iban'] = iban
    context.user_data['current_state'] = 'verification'

    # Show data verification
    verification_message = (
        "📋 **Verifikasi Data Pembelian**\n\n"
        f"👤 Nama: {context.user_data['buy_name']}\n"
        f"🏦 IBAN: `{iban}`\n"
        f"💸 Nominal: {format_currency(context.user_data['buy_amount_idr'])}\n"
        f"🇹🇷 TRY yang diterima: ₺{context.user_data['buy_estimated_try']:.2f}\n"
        f"💳 Fee: {format_currency(context.user_data['buy_fee'])}\n"
        f"💰 Total Bayar: {format_currency(context.user_data['buy_total_bayar'])}\n\n"
        "❓ **Apakah semua data sudah benar?**"
    )

    await update.message.reply_text(
        verification_message,
        reply_markup=get_verification_keyboard(),
        parse_mode='Markdown'
    )
    return WAITING_VERIFICATION

async def handle_data_verification(update: Update, context: ContextTypes.DEFAULT_TYPE, is_correct: bool):
    """Handle data verification response"""
    query = update.callback_query
    
    if not is_correct:
        # Data salah - kembali ke input nominal
        await query.edit_message_text(
            "❌ **Data dibatalkan**\n\n"
            "Silakan masukkan ulang nominal dalam Rupiah:\n"
            "Minimal: Rp100.000\n\n"
            "Contoh: 500000",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        context.user_data['current_state'] = 'buy_amount'
        return WAITING_BUY_AMOUNT
    
    # Data benar - lanjut ke pembayaran
    context.user_data['current_state'] = 'buy_payment'

    summary_message = (
        "✅ **Data Dikonfirmasi - Silakan Transfer**\n\n"
        f"👤 Nama: {context.user_data['buy_name']}\n"
        f"🏦 IBAN: `{context.user_data['buy_iban']}`\n"
        f"💰 Total Transfer: {format_currency(context.user_data['buy_total_bayar'])}\n"
        f"🇹🇷 TRY yang diterima: ₺{context.user_data['buy_estimated_try']:.2f}\n\n"
        f"💳 **Transfer ke:**\n"
        f"🏦 Bank: BCA\n"
        f"💳 Rekening: `7645257260`\n"
        f"👤 a.n. Muhammad Haikal Sutanto\n\n"
        f"Setelah transfer, klik tombol di bawah:"
    )

    await query.edit_message_text(
        summary_message,
        reply_markup=get_payment_keyboard(),
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def handle_payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment confirmation"""
    query = update.callback_query
    user = query.from_user

    # Check if we have the necessary data
    required_keys = ['buy_name', 'buy_iban', 'buy_amount_idr', 'buy_estimated_try', 'buy_fee', 'buy_total_bayar']
    if not all(key in context.user_data for key in required_keys):
        await query.edit_message_text(
            "❌ Data transaksi tidak lengkap. Silakan mulai transaksi baru.",
            reply_markup=get_main_keyboard()
        )
        return

    # Prepare transaction data untuk spreadsheet
    now = datetime.now()
    transaction_data = [
        now.strftime('%Y-%m-%d %H:%M:%S'),                    # Tanggal
        str(user.id),                                         # User ID
        user.username or '',                                  # Username
        context.user_data.get('buy_name', ''),              # Nama Lengkap
        context.user_data.get('buy_iban', ''),              # IBAN
        context.user_data.get('buy_amount_idr', 0),          # Nominal IDR
        round(context.user_data.get('buy_estimated_try', 0), 2),  # Jumlah TRY
        'BCA Transfer',                                       # Metode Bayar
        context.user_data.get('buy_fee', 0),                # Fee
        context.user_data.get('buy_total_bayar', 0)         # Total Bayar
    ]

    # Save transaction
    save_success = save_transaction(transaction_data)

    # Send simple notification to admin (copyable format)
    admin_message = (
        f"🔔 PESANAN BELI LIRA\n\n"
        f"Nama: {context.user_data.get('buy_name', '')}\n"
        f"Username: @{user.username or 'Tidak ada'}\n"
        f"IBAN: {context.user_data.get('buy_iban', '')}\n"
        f"Nominal: {format_currency(context.user_data.get('buy_amount_idr', 0))}\n"
        f"TRY: ₺{context.user_data.get('buy_estimated_try', 0):.2f}\n"
        f"Fee: {format_currency(context.user_data.get('buy_fee', 0))}\n"
        f"Total: {format_currency(context.user_data.get('buy_total_bayar', 0))}\n"
        f"Waktu: {now.strftime('%d/%m/%Y %H:%M')}\n"
        f"User ID: {user.id}"
    )

    try:
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_message
            )
            logger.info(f"Admin notification sent for buy transaction from user {user.id}")
    except Exception as e:
        logger.error(f"Error sending admin notification: {e}")

    # Send confirmation to user
    await query.edit_message_text(
        "✅ **Konfirmasi Pembayaran Diterima!**\n\n"
        "Terima kasih! Transaksi Anda sedang diproses.\n"
        "Admin akan segera memverifikasi pembayaran dan mengirim Lira ke IBAN Anda.\n\n"
        f"📱 **Estimasi Waktu Proses:** 5-15 menit\n"
        f"💬 **Jika ada pertanyaan:** @lirakuid\n\n"
        "Kami akan mengirim notifikasi setelah transfer selesai.",
        reply_markup=get_back_menu_keyboard(),
        parse_mode='Markdown'
    )

    # Clear user data
    context.user_data.clear()

async def handle_sell_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sell amount input"""
    try:
        amount = float(update.message.text.replace(',', '.'))

        if amount <= 0:
            await update.message.reply_text(
                "❌ Jumlah harus lebih dari 0.\n"
                "Silakan masukkan jumlah yang valid.",
                reply_markup=get_back_menu_keyboard()
            )
            return WAITING_SELL_AMOUNT

        # Get exchange rate
        base_rate = get_exchange_rate('TRY', 'IDR')
        if not base_rate:
            await update.message.reply_text(
                "❌ Gagal mengambil data kurs. Silakan coba lagi.",
                reply_markup=get_back_menu_keyboard()
            )
            return WAITING_SELL_AMOUNT

        # Calculate dengan margin 2.5% dari total
        gross_idr = amount * base_rate
        fee = gross_idr * 0.025
        estimated_idr = gross_idr - fee

        # Store in context
        context.user_data['sell_amount_try'] = amount
        context.user_data['sell_estimated_idr'] = estimated_idr
        context.user_data['sell_fee'] = fee
        context.user_data['current_state'] = 'sell_name'

        await update.message.reply_text(
            f"
