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
 WAITING_SELL_AMOUNT, WAITING_SELL_NAME, WAITING_SELL_ACCOUNT) = range(6)

# Google Sheets setup
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'lirakubot.json'
SPREADSHEET_NAME = 'DATA LIRAKU.ID'

def get_google_sheets_client():
    """Initialize Google Sheets client"""
    try:
        creds = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        return gspread.authorize(creds)
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
            return False
            
        sheet = gc.open(SPREADSHEET_NAME).sheet1
        
        # Add headers if sheet is empty
        if not sheet.get_all_records():
            headers = ['Waktu', 'Nama', 'IBAN/Rekening', 'IDR', 'TRY', 'Status', 'Username', 'User ID', 'Jenis']
            sheet.append_row(headers)
        
        sheet.append_row(transaction_data)
        return True
    except Exception as e:
        logger.error(f"Error saving to sheets: {e}")
        return False

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
            "📱 Telegram: @haikal2715\n"
            "📞 WhatsApp: 087773834406"
        )
        await query.edit_message_text(
            contact_message,
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        
    elif query.data == "payment_sent":
        await handle_payment_confirmation(update, context)
        
    elif query.data == "sell_sent":
        await handle_sell_confirmation(update, context)

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
    
    # Apply 3.5% margin for IDR to TRY
    idr_to_try_with_margin = idr_to_try_rate * 0.965
    
    simulation_message = (
        "💱 **Simulasi Tukar IDR ke TRY**\n"
        f"💸 Rp100.000 ≈ 🇹🇷 ₺{100000 * idr_to_try_with_margin:.2f}\n"
        f"💸 Rp500.000 ≈ 🇹🇷 ₺{500000 * idr_to_try_with_margin:.2f}\n"
        f"💸 Rp1.000.000 ≈ 🇹🇷 ₺{1000000 * idr_to_try_with_margin:.2f}\n\n"
        "💱 **Simulasi Tukar TRY ke IDR**\n"
        f"🇹🇷 ₺100 ≈ {format_currency(100 * try_to_idr_rate)}\n"
        f"🇹🇷 ₺500 ≈ {format_currency(500 * try_to_idr_rate)}\n"
        f"🇹🇷 ₺1.000 ≈ {format_currency(1000 * try_to_idr_rate)}\n\n"
        f"*Kurs IDR→TRY sudah termasuk margin 3.5%*\n"
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
        rate = get_exchange_rate('IDR', 'TRY')
        if not rate:
            await update.message.reply_text(
                "❌ Gagal mengambil data kurs. Silakan coba lagi.",
                reply_markup=get_back_menu_keyboard()
            )
            return WAITING_BUY_AMOUNT
        
        # Apply 3.5% margin
        rate_with_margin = rate * 0.965
        estimated_try = amount * rate_with_margin
        
        # Store in context
        context.user_data['buy_amount_idr'] = amount
        context.user_data['buy_estimated_try'] = estimated_try
        
        await update.message.reply_text(
            f"💰 **Estimasi Konversi**\n\n"
            f"💸 Nominal: {format_currency(amount)}\n"
            f"🇹🇷 Estimasi TRY: ₺{estimated_try:.2f}\n\n"
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
    
    await update.message.reply_text(
        f"👤 Nama: **{name}**\n\n"
        f"Masukkan IBAN Turki Anda (format: TR + 24 angka)\n"
        f"Contoh: TR123456789012345678901234",
        reply_markup=get_back_menu_keyboard(),
        parse_mode='Markdown'
    )
    return WAITING_BUY_IBAN

async def handle_buy_iban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buy IBAN input"""
    iban = update.message.text.strip().upper()
    
    # Validate IBAN format
    if not iban.startswith('TR') or len(iban) != 26 or not iban[2:].isdigit():
        await update.message.reply_text(
            "❌ Format IBAN tidak valid.\n"
            "IBAN Turki harus dimulai dengan 'TR' diikuti 24 angka.\n"
            "Contoh: TR123456789012345678901234",
            reply_markup=get_back_menu_keyboard()
        )
        return WAITING_BUY_IBAN
    
    context.user_data['buy_iban'] = iban
    
    # Calculate totals
    amount = context.user_data['buy_amount_idr']
    estimated_try = context.user_data['buy_estimated_try']
    admin_fee = 7000
    total_payment = amount + admin_fee
    
    context.user_data['buy_total_payment'] = total_payment
    
    summary_message = (
        "📋 **Detail Pembelian**\n\n"
        f"👤 Nama: {context.user_data['buy_name']}\n"
        f"🏦 IBAN: {iban}\n"
        f"💰 Nominal: {format_currency(amount)}\n"
        f"💸 Biaya Admin: {format_currency(admin_fee)}\n"
        f"💳 **Total Pembayaran: {format_currency(total_payment)}**\n"
        f"🇹🇷 Estimasi TRY: ₺{estimated_try:.0f}\n\n"
        f"💳 **Transfer ke:**\n"
        f"🏦 Bank: BCA\n"
        f"💳 Rekening: 7645257260\n"
        f"👤 a.n. Muhammad Haikal Sutanto\n\n"
        f"Setelah transfer, klik tombol di bawah:"
    )
    
    await update.message.reply_text(
        summary_message,
        reply_markup=get_payment_keyboard(),
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def handle_payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment confirmation"""
    query = update.callback_query
    user = query.from_user
    
    # Prepare transaction data
    now = datetime.now()
    transaction_data = [
        now.strftime('%Y-%m-%d %H:%M:%S'),
        context.user_data.get('buy_name', ''),
        context.user_data.get('buy_iban', ''),
        context.user_data.get('buy_amount_idr', 0),
        round(context.user_data.get('buy_estimated_try', 0), 2),
        'Menunggu Konfirmasi',
        user.username or '',
        str(user.id),
        'Beli Lira'
    ]
    
    # Save transaction
    if save_transaction(transaction_data):
        # Send notification to admin
        admin_message = (
            "🔔 **Transaksi Baru - Beli Lira**\n\n"
            f"👤 Nama: {context.user_data.get('buy_name', '')}\n"
            f"🆔 Username: @{user.username or 'Tidak ada'}\n"
            f"🆔 User ID: {user.id}\n"
            f"🏦 IBAN: {context.user_data.get('buy_iban', '')}\n"
            f"💰 Nominal: {format_currency(context.user_data.get('buy_amount_idr', 0))}\n"
            f"💳 Total Bayar: {format_currency(context.user_data.get('buy_total_payment', 0))}\n"
            f"🇹🇷 Estimasi TRY: ₺{context.user_data.get('buy_estimated_try', 0):.0f}\n"
            f"⏰ Waktu: {now.strftime('%d/%m/%Y %H:%M:%S')}"
        )
        
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error sending admin notification: {e}")
        
        await query.edit_message_text(
            "✅ **Konfirmasi Diterima!**\n\n"
            "Terima kasih! Transaksi Anda sedang diproses.\n"
            "Admin akan segera memverifikasi pembayaran dan mengirim Lira ke IBAN Anda.\n\n"
            "💬 Jika ada pertanyaan, hubungi admin di @haikal2715",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text(
            "❌ Terjadi kesalahan sistem. Silakan hubungi admin.",
            reply_markup=get_back_menu_keyboard()
        )

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
        rate = get_exchange_rate('TRY', 'IDR')
        if not rate:
            await update.message.reply_text(
                "❌ Gagal mengambil data kurs. Silakan coba lagi.",
                reply_markup=get_back_menu_keyboard()
            )
            return WAITING_SELL_AMOUNT
        
        estimated_idr = amount * rate
        
        # Store in context
        context.user_data['sell_amount_try'] = amount
        context.user_data['sell_estimated_idr'] = estimated_idr
        
        await update.message.reply_text(
            f"💰 **Estimasi Konversi**\n\n"
            f"🇹🇷 Lira: ₺{amount:,.2f}\n"
            f"💵 Estimasi IDR: {format_currency(estimated_idr)}\n\n"
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
    
    await update.message.reply_text(
        f"👤 Nama: **{name}**\n\n"
        f"Masukkan nomor rekening bank Indonesia Anda.\n"
        f"Format: [Nama Bank] - [Nomor Rekening]\n"
        f"Contoh: BCA - 1234567890",
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
            "Contoh: BCA - 1234567890",
            reply_markup=get_back_menu_keyboard()
        )
        return WAITING_SELL_ACCOUNT
    
    context.user_data['sell_account'] = account
    
    # Show summary
    amount = context.user_data['sell_amount_try']
    estimated_idr = context.user_data['sell_estimated_idr']
    
    summary_message = (
        "📋 **Penjualan Lira**\n\n"
        f"👤 Nama: {context.user_data['sell_name']}\n"
        f"🏦 Rekening: {account}\n"
        f"🪙 TRY: ₺{amount:,.2f}\n"
        f"💵 Estimasi Rupiah: {format_currency(estimated_idr)}\n\n"
        f"🏦 **Kirim Lira ke IBAN Admin:**\n"
        f"📋 {ADMIN_IBAN}\n\n"
        f"Setelah mengirim, klik tombol di bawah:"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ Saya sudah kirim", callback_data="sell_sent")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="back")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]
    ]
    
    await update.message.reply_text(
        summary_message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def handle_sell_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sell confirmation"""
    query = update.callback_query
    user = query.from_user
    
    # Prepare transaction data
    now = datetime.now()
    transaction_data = [
        now.strftime('%Y-%m-%d %H:%M:%S'),
        context.user_data.get('sell_name', ''),
        context.user_data.get('sell_account', ''),
        round(context.user_data.get('sell_estimated_idr', 0)),
        context.user_data.get('sell_amount_try', 0),
        'Menunggu Konfirmasi',
        user.username or '',
        str(user.id),
        'Jual Lira'
    ]
    
    # Save transaction
    if save_transaction(transaction_data):
        # Send notification to admin
        admin_message = (
            "🔔 **Transaksi Baru - Jual Lira**\n\n"
            f"👤 Nama: {context.user_data.get('sell_name', '')}\n"
            f"🆔 Username: @{user.username or 'Tidak ada'}\n"
            f"🆔 User ID: {user.id}\n"
            f"🏦 Rekening: {context.user_data.get('sell_account', '')}\n"
            f"🪙 TRY: ₺{context.user_data.get('sell_amount_try', 0):,.2f}\n"
            f"💵 Estimasi IDR: {format_currency(context.user_data.get('sell_estimated_idr', 0))}\n"
            f"⏰ Waktu: {now.strftime('%d/%m/%Y %H:%M:%S')}"
        )
        
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error sending admin notification: {e}")
        
        await query.edit_message_text(
            "✅ **Konfirmasi Diterima!**\n\n"
            "Terima kasih! Transaksi Anda sedang diproses.\n"
            "Admin akan segera memverifikasi penerimaan Lira dan mengirim Rupiah ke rekening Anda.\n\n"
            "💬 Jika ada pertanyaan, hubungi admin di @haikal2715",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text(
            "❌ Terjadi kesalahan sistem. Silakan hubungi admin.",
            reply_markup=get_back_menu_keyboard()
        )

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
            raise ValueError("ADMIN_CHAT_ID tidak ditemukan dalam environment variables")
        
        # Create application with error handling
        try:
            application = Application.builder().token(BOT_TOKEN).build()
        except Exception as e:
            logger.error(f"Error creating application: {e}")
            # Try alternative method
            from telegram.ext import ApplicationBuilder
            application = ApplicationBuilder().token(BOT_TOKEN).build()
        
        # Add conversation handler for buy lira
        buy_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(button_handler, pattern="^buy_lira$")],
            states={
                WAITING_BUY_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_amount)],
                WAITING_BUY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_name)],
                WAITING_BUY_IBAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_iban)],
            },
            fallbacks=[
                CommandHandler('cancel', cancel),
                CallbackQueryHandler(button_handler, pattern="^(back|main_menu)$")
            ],
            allow_reentry=True
        )
        
        # Add conversation handler for sell lira
        sell_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(button_handler, pattern="^sell_lira$")],
            states={
                WAITING_SELL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sell_amount)],
                WAITING_SELL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sell_name)],
                WAITING_SELL_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sell_account)],
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
    main()
