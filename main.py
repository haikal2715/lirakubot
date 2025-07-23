import os
import logging
import requests
import gspread
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
EXCHANGE_API_KEY = os.getenv('EXCHANGE_API_KEY')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')  # Chat ID admin untuk notifikasi

# Google Sheets configuration
GOOGLE_SHEETS_CREDS = 'lirakubot.json'
SHEET_NAME = 'DATA LIRAKU.ID'

# Constants
MARGIN_PER_100K = 3500  # Margin Rp3.500 per Rp100.000
ADMIN_FEE = 7000  # Biaya admin Rp7.000
BCA_ACCOUNT = "7645257260"
ACCOUNT_NAME = "Muhammad Haikal Sutanto"

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Temporary storage for user sessions
user_sessions = {}

# Google Sheets setup
def setup_google_sheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SHEETS_CREDS, scope)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).sheet1
        return sheet
    except Exception as e:
        logger.error(f"Error setting up Google Sheets: {e}")
        return None

def get_exchange_rate():
    """Get IDR to TRY exchange rate from exchangerate-api.com"""
    try:
        url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_API_KEY}/pair/IDR/TRY"
        response = requests.get(url)
        data = response.json()
        
        if data['result'] == 'success':
            base_rate = data['conversion_rate']
            # Add margin (Rp3.500 per Rp100.000 = 3.5% margin)
            margin_rate = base_rate * 0.965  # Reduce rate by 3.5% to add margin
            return margin_rate
        else:
            logger.error(f"Exchange API error: {data}")
            return 0.000213  # Fallback rate
    except Exception as e:
        logger.error(f"Error fetching exchange rate: {e}")
        return 0.000213  # Fallback rate

def calculate_try_amount(idr_amount, rate):
    """Calculate TRY amount after margin"""
    return idr_amount * rate

def format_currency(amount):
    """Format currency with dots as thousand separators"""
    return f"{amount:,.0f}".replace(',', '.')

def create_main_menu():
    """Create main menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("💸 Beli Lira", callback_data="buy_lira")],
        [InlineKeyboardButton("💱 Lihat Simulasi Kurs", callback_data="check_rate")],
        [InlineKeyboardButton("👤 Kontak Admin", callback_data="contact_admin")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_back_menu():
    """Create back and main menu buttons"""
    keyboard = [
        [InlineKeyboardButton("🔙 Kembali", callback_data="back")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_payment_menu():
    """Create payment confirmation menu"""
    keyboard = [
        [InlineKeyboardButton("✅ Saya sudah bayar", callback_data="payment_done")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="back")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    welcome_text = """💚 Selamat datang di LiraKuBot!

✅ Proses cepat & aman
✅ Langsung kirim ke IBAN
✅ Lebih hemat dibanding beli di bandara & bank

Silakan pilih menu:"""
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=create_main_menu()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "main_menu":
        await show_main_menu(query)
    elif data == "buy_lira":
        await start_buy_process(query, context)
    elif data == "check_rate":
        await show_exchange_rate(query)
    elif data == "contact_admin":
        await show_contact_info(query)
    elif data == "back":
        await handle_back(query, context)
    elif data == "payment_done":
        await handle_payment_confirmation(query, context)

async def show_main_menu(query):
    """Show main menu"""
    welcome_text = """💚 Selamat datang di LiraKuBot!

✅ Proses cepat & aman
✅ Langsung kirim ke IBAN
✅ Lebih hemat dibanding beli di bandara & bank

Silakan pilih menu:"""
    
    await query.edit_message_text(
        welcome_text,
        reply_markup=create_main_menu()
    )

async def show_exchange_rate(query):
    """Show exchange rate simulation"""
    rate = get_exchange_rate()
    
    simulation_text = """💱 Simulasi Tukar IDR ke TRY

💸 Rp100.000 ≈ 🇹🇷 TRY {:.2f}
💸 Rp500.000 ≈ 🇹🇷 TRY {:.2f}
💸 Rp1.000.000 ≈ 🇹🇷 TRY {:.2f}
💸 Rp2.000.000 ≈ 🇹🇷 TRY {:.2f}

✅ Lebih hemat dari bandara & bank
✅ Langsung kirim ke IBAN""".format(
        calculate_try_amount(100000, rate),
        calculate_try_amount(500000, rate),
        calculate_try_amount(1000000, rate),
        calculate_try_amount(2000000, rate)
    )
    
    await query.edit_message_text(
        simulation_text,
        reply_markup=create_back_menu()
    )

async def show_contact_info(query):
    """Show admin contact info"""
    contact_text = """👤 Kontak Admin

📱 Telegram: @haikal2715
📞 WhatsApp: 087773834406

Silakan hubungi admin untuk bantuan atau pertanyaan."""
    
    await query.edit_message_text(
        contact_text,
        reply_markup=create_back_menu()
    )

async def start_buy_process(query, context):
    """Start the buying process"""
    user_id = query.from_user.id
    user_sessions[user_id] = {'step': 'amount'}
    
    text = """💸 Beli Lira Turki

Masukkan jumlah Rupiah yang ingin ditukar:
(Contoh: Rp500.000 tulis 500000)

Minimal pembelian: Rp100.000"""
    
    await query.edit_message_text(text, reply_markup=create_back_menu())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages during buying process"""
    user_id = update.message.from_user.id
    
    if user_id not in user_sessions:
        return
    
    session = user_sessions[user_id]
    step = session.get('step')
    
    if step == 'amount':
        await process_amount(update, context)
    elif step == 'name':
        await process_name(update, context)
    elif step == 'iban':
        await process_iban(update, context)

async def process_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process amount input"""
    user_id = update.message.from_user.id
    text = update.message.text.replace('.', '').replace(',', '').replace('Rp', '').replace('rp', '').strip()
    
    try:
        amount = int(text)
        if amount < 100000:
            await update.message.reply_text(
                "❌ Minimal pembelian Rp100.000\n\nSilakan masukkan nominal yang valid:",
                reply_markup=create_back_menu()
            )
            return
        
        user_sessions[user_id]['amount'] = amount
        user_sessions[user_id]['step'] = 'name'
        
        formatted_amount = format_currency(amount)
        rate = get_exchange_rate()
        try_amount = calculate_try_amount(amount, rate)
        
        text = f"""💸 Jumlah: Rp{formatted_amount}
🇹🇷 Estimasi TRY: {try_amount:.2f}

Sekarang masukkan nama lengkap Anda:
(Sesuai dengan yang akan menerima transfer)"""
        
        await update.message.reply_text(text, reply_markup=create_back_menu())
        
    except ValueError:
        await update.message.reply_text(
            "❌ Format tidak valid. Masukkan angka saja.\n\nContoh: 500000",
            reply_markup=create_back_menu()
        )

async def process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process name input"""
    user_id = update.message.from_user.id
    name = update.message.text.strip()
    
    if len(name) < 2:
        await update.message.reply_text(
            "❌ Nama terlalu pendek. Masukkan nama lengkap Anda:",
            reply_markup=create_back_menu()
        )
        return
    
    user_sessions[user_id]['name'] = name
    user_sessions[user_id]['step'] = 'iban'
    
    text = f"""👤 Nama: {name}

Sekarang masukkan nomor IBAN Turki Anda:
(Format: TR diikuti 24 digit angka)

Contoh: TR123456789012345678901234"""
    
    await update.message.reply_text(text, reply_markup=create_back_menu())

async def process_iban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process IBAN input"""
    user_id = update.message.from_user.id
    iban = update.message.text.strip().upper()
    
    # Validate IBAN format (TR + 24 digits)
    if not iban.startswith('TR') or len(iban) != 26 or not iban[2:].isdigit():
        await update.message.reply_text(
            "❌ Format IBAN tidak valid.\n\nFormat yang benar: TR diikuti 24 digit angka\nContoh: TR123456789012345678901234",
            reply_markup=create_back_menu()
        )
        return
    
    user_sessions[user_id]['iban'] = iban
    
    # Show transaction summary
    session = user_sessions[user_id]
    amount = session['amount']
    name = session['name']
    
    rate = get_exchange_rate()
    try_amount = calculate_try_amount(amount, rate)
    total_payment = amount + ADMIN_FEE
    
    formatted_amount = format_currency(amount)
    formatted_total = format_currency(total_payment)
    
    summary_text = f"""📋 Detail Pembelian

👤 Nama: {name}
🏦 IBAN: {iban}
💰 Nominal: Rp{formatted_amount}
💸 Biaya Admin: Rp{format_currency(ADMIN_FEE)}
💳 Total Pembayaran: Rp{formatted_total}
🇹🇷 Estimasi TRY diterima: {try_amount:.2f}

💳 Silakan transfer ke:

Rekening: BCA - {BCA_ACCOUNT}
Atas Nama: {ACCOUNT_NAME}

Setelah transfer, klik tombol di bawah dan kirim bukti pembayaran ke admin."""
    
    await update.message.reply_text(
        summary_text,
        reply_markup=create_payment_menu()
    )

async def handle_payment_confirmation(query, context):
    """Handle payment confirmation"""
    user_id = query.from_user.id
    username = query.from_user.username or "Tidak ada username"
    
    if user_id not in user_sessions:
        await query.edit_message_text(
            "❌ Sesi tidak ditemukan. Silakan mulai dari awal.",
            reply_markup=create_main_menu()
        )
        return
    
    session = user_sessions[user_id]
    amount = session['amount']
    name = session['name']
    iban = session['iban']
    
    rate = get_exchange_rate()
    try_amount = calculate_try_amount(amount, rate)
    total_payment = amount + ADMIN_FEE
    net_amount = amount  # Amount after admin fee is deducted from total
    
    # Send notification to admin
    admin_text = f"""📥 PEMBELIAN BARU MASUK

👤 Nama: {name}
🏦 IBAN: {iban}
💰 Total Pembayaran: Rp{format_currency(total_payment)}
💸 Biaya Admin: Rp{format_currency(ADMIN_FEE)}
🪙 Dana Bersih: Rp{format_currency(net_amount)}
🇹🇷 Estimasi TRY diterima: TRY {try_amount:.2f}
📞 Username: @{username}
🆔 User ID: {user_id}"""
    
    try:
        if ADMIN_CHAT_ID:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_text)
    except Exception as e:
        logger.error(f"Error sending admin notification: {e}")
    
    # Save to Google Sheets
    try:
        sheet = setup_google_sheets()
        if sheet:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = [
                timestamp,
                name,
                iban,
                format_currency(amount),
                f"{try_amount:.2f}",
                "Menunggu Bukti",
                f"@{username}",
                str(user_id)
            ]
            sheet.append_row(row)
    except Exception as e:
        logger.error(f"Error saving to Google Sheets: {e}")
    
    # Clear user session
    del user_sessions[user_id]
    
    confirmation_text = f"""✅ Terima kasih! Pesanan Anda telah diterima.

Silakan kirim bukti transfer ke admin:
📱 Telegram: @haikal2715
📞 WhatsApp: 087773834406

Lira akan dikirim ke IBAN Anda setelah pembayaran dikonfirmasi.

Terima kasih telah menggunakan LiraKuBot! 💚"""
    
    await query.edit_message_text(
        confirmation_text,
        reply_markup=create_main_menu()
    )

async def handle_back(query, context):
    """Handle back button"""
    user_id = query.from_user.id
    
    if user_id not in user_sessions:
        await show_main_menu(query)
        return
    
    session = user_sessions[user_id]
    step = session.get('step')
    
    if step == 'amount':
        await show_main_menu(query)
        del user_sessions[user_id]
    elif step == 'name':
        session['step'] = 'amount'
        text = """💸 Beli Lira Turki

Masukkan jumlah Rupiah yang ingin ditukar:
(Contoh: Rp500.000 tulis 500000)

Minimal pembelian: Rp100.000"""
        await query.edit_message_text(text, reply_markup=create_back_menu())
    elif step == 'iban':
        session['step'] = 'name'
        name = session.get('name', '')
        text = f"""💸 Jumlah: Rp{format_currency(session['amount'])}

Sekarang masukkan nama lengkap Anda:
(Sesuai dengan yang akan menerima transfer)"""
        await query.edit_message_text(text, reply_markup=create_back_menu())

def main():
    """Start the bot"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
        return
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start the bot
    logger.info("Starting LiraKu Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()