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

# Google Sheets dependencies - disabled for now
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

# Configuration - removed Google Sheets references
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
    """
     Calculate margin rate with flat 2.5% margin
    """
def calculate_margin_rate(base_rate, is_buying=True):
    # Flat 2.5% margin
    margin_percent = 2.5

    if is_buying:
        # For buying: reduce rate (less TRY for same IDR)
        margin_multiplier = (100 - margin_percent) / 100
    else:
        # For selling: reduce rate (less IDR for same TRY)  
        margin_multiplier = (100 - margin_percent) / 100

    return base_rate * margin_multiplier


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


def save_transaction(transaction_data):
    """Save transaction - simplified without Google Sheets"""
    # For now, just log the transaction data
    logger.info(f"Transaction data: {transaction_data}")
    # You can add other storage methods here (database, file, etc.)
    return True


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
            "📱 Telegram: @lirakuid\n"
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
        
    elif query.data == "back":
        # Handle back navigation
        current_state = context.user_data.get('current_state', None)
        
        if current_state == 'buy_amount':
            # Back to buy lira menu
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
            # Back to amount input
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
            # Back to name input
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
        elif current_state == 'sell_amount':
            await query.edit_message_text(
                "💵 **Jual Lira (TRY ke IDR)**\n\n"
                "Masukkan jumlah Lira Turki yang ingin dijual.\n\n"
                "Contoh: 100",
                reply_markup=get_back_menu_keyboard(),
                parse_mode='Markdown'
            )
            return WAITING_SELL_AMOUNT
        elif current_state == 'sell_name':
            await query.edit_message_text(
                "💵 **Jual Lira (TRY ke IDR)**\n\n"
                "Masukkan jumlah Lira Turki yang ingin dijual.\n\n"
                "Contoh: 100",
                reply_markup=get_back_menu_keyboard(),
                parse_mode='Markdown'
            )
            context.user_data['current_state'] = 'sell_amount'
            return WAITING_SELL_AMOUNT
        elif current_state == 'sell_account':
            await query.edit_message_text(
                f"💰 **Estimasi Konversi**\n\n"
                f"🇹🇷 Lira: ₺{context.user_data.get('sell_amount_try', 0):,.2f}\n"
                f"💵 Estimasi IDR: {format_currency(context.user_data.get('sell_estimated_idr', 0))}\n\n"
                f"Masukkan nama lengkap Anda:",
                reply_markup=get_back_menu_keyboard(),
                parse_mode='Markdown'
            )
            context.user_data['current_state'] = 'sell_name'
            return WAITING_SELL_NAME
        else:
            # Default back to main menu
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
    
    # Calculate rates with flat 2.5% margin
    buy_rate = calculate_margin_rate(idr_to_try_rate, is_buying=True)
    sell_rate = calculate_margin_rate(try_to_idr_rate, is_buying=False)
    
    simulation_message = (
        "💱 **Simulasi Tukar IDR ke TRY**\n"
        f"💸 Rp100.000 ≈ 🇹🇷 ₺{100000 * buy_rate:.2f}\n"
        f"💸 Rp500.000 ≈ 🇹🇷 ₺{500000 * buy_rate:.2f}\n"
        f"💸 Rp1.000.000 ≈ 🇹🇷 ₺{1000000 * buy_rate:.2f}\n\n"
        "💱 **Simulasi Tukar TRY ke IDR**\n"
        f"🇹🇷 ₺100 ≈ {format_currency(100 * sell_rate)}\n"
        f"🇹🇷 ₺500 ≈ {format_currency(500 * sell_rate)}\n"
        f"🇹🇷 ₺1.000 ≈ {format_currency(1000 * sell_rate)}\n\n"
        f"*Margin flat 2.5% untuk semua nominal*\n"
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
        
        # Apply flat 2.5% margin
        rate_with_margin = calculate_margin_rate(base_rate, is_buying=True)
        estimated_try = amount * rate_with_margin
        
        # Store in context
        context.user_data['buy_amount_idr'] = amount
        context.user_data['buy_estimated_try'] = estimated_try
        context.user_data['current_state'] = 'buy_name'
        
        await update.message.reply_text(
            f"💰 **Estimasi Konversi**\n\n"
            f"💸 Nominal: {format_currency(amount)}\n"
            f"🇹🇷 Estimasi TRY: ₺{estimated_try:.2f}\n"
            f"📊 Margin: 2.5%\n\n"
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
    iban = update.message.text.strip().upper()
    
    # Validate IBAN format
    if not iban.startswith('TR') or len(iban) != 26 or not iban[2:].isdigit():
        await update.message.reply_text(
            "❌ Format IBAN tidak valid.\n"
            "IBAN Turki harus dimulai dengan 'TR' diikuti 24 angka.\n"
            "Contoh: `TR123456789012345678901234`",
            reply_markup=get_back_menu_keyboard(),
            parse_mode='Markdown'
        )
        return WAITING_BUY_IBAN
    
    context.user_data['buy_iban'] = iban
    
    # Calculate totals
    amount = context.user_data['buy_amount_idr']
    estimated_try = context.user_data['buy_estimated_try']
    admin_fee = 7000
    total_payment = amount + admin_fee
    
    context.user_data['buy_total_payment'] = total_payment
    context.user_data['buy_admin_fee'] = admin_fee
    context.user_data['current_state'] = 'buy_payment'
    
    summary_message = (
        "📋 **Detail Pembelian**\n\n"
        f"👤 Nama: {context.user_data['buy_name']}\n"
        f"🏦 IBAN: {iban}\n"
        f"💰 Nominal: {format_currency(amount)}\n"
        f"💸 Biaya Admin: {format_currency(admin_fee)}\n"
        f"💳 **Total Pembayaran: {format_currency(total_payment)}**\n"
        f"🇹🇷 Estimasi TRY: ₺{estimated_try:.0f}\n"
        f"📊 Margin: 2.5%\n\n"
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
    
    # Check if we have the necessary data
    if not all(key in context.user_data for key in ['buy_name', 'buy_iban', 'buy_amount_idr', 'buy_estimated_try', 'buy_total_payment']):
        await query.edit_message_text(
            "❌ Data transaksi tidak lengkap. Silakan mulai transaksi baru.",
            reply_markup=get_main_keyboard()
        )
        return
    
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
    save_success = save_transaction(transaction_data)
    
    # Send notification to admin
    admin_message = (
        "🔔 **PESANAN MASUK - Beli Lira**\n\n"
        f"👤 **Nama:** {context.user_data.get('buy_name', '')}\n"
        f"🆔 **Username:** @{user.username or 'Tidak ada'}\n"
        f"🆔 **User ID:** {user.id}\n"
        f"🏦 **IBAN:** `{context.user_data.get('buy_iban', '')}`\n"
        f"💰 **Nominal:** {format_currency(context.user_data.get('buy_amount_idr', 0))}\n"
        f"💸 **Biaya Admin:** {format_currency(context.user_data.get('buy_admin_fee', 0))}\n"
        f"💳 **Total Bayar:** {format_currency(context.user_data.get('buy_total_payment', 0))}\n"
        f"🇹🇷 **Estimasi TRY:** ₺{context.user_data.get('buy_estimated_try', 0):.0f}\n"
        f"📊 **Margin:** 2.5%\n"
        f"⏰ **Waktu:** {now.strftime('%d/%m/%Y %H:%M:%S')}\n"
        f"💾 **Status Simpan:** {'✅ Berhasil' if save_success else '❌ Gagal'}\n\n"
        f"**Silakan verifikasi pembayaran dan proses transaksi ini.**"
    )
    
    try:
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_message,
                parse_mode='Markdown'
            )
            logger.info(f"Admin notification sent for buy transaction from user {user.id}")
        else:
            logger.warning("ADMIN_CHAT_ID not configured, admin notification not sent")
    except Exception as e:
        logger.error(f"Error sending admin notification: {e}")
    
    # Send confirmation to user
    await query.edit_message_text(
        "✅ **Konfirmasi Pembayaran Diterima!**\n\n"
        "Terima kasih! Transaksi Anda sedang diproses.\n"
        "Admin akan segera memverifikasi pembayaran dan mengirim Lira ke IBAN Anda.\n\n"
        "📱 **Estimasi Waktu Proses:** 5-15 menit\n"
        "💬 **Jika ada pertanyaan:** @lirakuid\n\n"
        f"🏦 **Rekening BCA Kami:** `7645257260`\n"
        f"👤 **a.n.** Muhammad Haikal Sutanto\n\n"
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
        
        # Apply flat 2.5% margin
        rate_with_margin = calculate_margin_rate(base_rate, is_buying=False)
        estimated_idr = amount * rate_with_margin
        
        # Store in context
        context.user_data['sell_amount_try'] = amount
        context.user_data['sell_estimated_idr'] = estimated_idr
        context.user_data['current_state'] = 'sell_name'
        
        await update.message.reply_text(
            f"💰 **Estimasi Konversi**\n\n"
            f"🇹🇷 Lira: ₺{amount:,.2f}\n"
            f"💵 Estimasi IDR: {format_currency(estimated_idr)}\n"
            f"📊 Margin: 2.5%\n\n"
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
