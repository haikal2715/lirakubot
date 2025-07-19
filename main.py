import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import gspread
import httpx
import midtransclient
from fastapi import FastAPI, Request
from google.oauth2.service_account import Credentials
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, 
    CallbackQueryHandler, 
    CommandHandler, 
    ContextTypes, 
    ConversationHandler, 
    MessageHandler, 
    filters
)

# Konfigurasi
TELEGRAM_TOKEN = "7720606847:AAH-NT6ptPtNqcWeS-KnE9OlTVn3PvbVjts"
WEBHOOK_URL = "https://yourdomain.com/webhook"
MIDTRANS_SERVER_KEY = "Mid-server-7066syb35LCzEaOUNjKXUiHJ"
MIDTRANS_CLIENT_KEY = "Mid-client-PdQTT3NqbaHyQE0Z"
ADMIN_CHAT_ID = "5715651828"
EXCHANGE_API_KEY = "b7dae8052fd7953bf7c7f66e"

# Constants untuk conversation states
INPUT_NOMINAL, INPUT_NAMA, INPUT_IBAN, PILIH_PEMBAYARAN, UPLOAD_BUKTI = range(5)

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global variables
application = None
transaction_data = {}

# Midtrans configuration
snap = midtransclient.Snap(
    is_production=False,  # Set to True for production
    server_key=MIDTRANS_SERVER_KEY,
    client_key=MIDTRANS_CLIENT_KEY
)

# Google Sheets setup
def get_sheets_client():
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    
    creds = Credentials.from_service_account_file(
        'lirakubot.json', 
        scopes=scope
    )
    
    return gspread.authorize(creds)

def log_to_sheets(data):
    try:
        gc = get_sheets_client()
        sheet = gc.open("DATA LIRAKU.ID").sheet1
        
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data.get('nama', ''),
            data.get('nominal_idr', ''),
            data.get('nominal_try', ''),
            data.get('iban', ''),
            data.get('metode_bayar', ''),
            data.get('status', 'pending')
        ]
        
        sheet.append_row(row)
        logger.info("Data berhasil disimpan ke Google Sheets")
    except Exception as e:
        logger.error(f"Error menyimpan ke Google Sheets: {e}")

async def get_exchange_rate():
    """Ambil kurs IDR ke TRY dari exchangerate-api"""
    try:
        async with httpx.AsyncClient() as client:
            url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_API_KEY}/pair/IDR/TRY"
            response = await client.get(url)
            data = response.json()
            
            if data.get("result") == "success":
                return data["conversion_rate"]
            else:
                logger.error("Error fetching exchange rate")
                return 0.0000689  # Fallback rate
    except Exception as e:
        logger.error(f"Error fetching exchange rate: {e}")
        return 0.0000689  # Fallback rate

def calculate_lira_with_margin(idr_amount, exchange_rate):
    """Hitung Lira dengan margin Rp3.500 per Rp100.000"""
    margin_per_100k = 3500
    margin_rate = margin_per_100k / 100000  # 0.035
    
    # Kurangi margin dari jumlah IDR
    idr_after_margin = idr_amount * (1 - margin_rate)
    
    # Konversi ke TRY
    try_amount = idr_after_margin * exchange_rate
    
    return try_amount

def format_currency(amount):
    """Format mata uang dengan titik pemisah ribuan"""
    return f"{amount:,.0f}".replace(",", ".")

def parse_currency(text):
    """Parse input currency dari user (dengan titik sebagai pemisah ribuan)"""
    # Hapus semua karakter selain angka dan titik
    cleaned = re.sub(r'[^\d.]', '', text)
    # Replace titik dengan koma untuk parsing
    cleaned = cleaned.replace('.', '')
    try:
        return int(cleaned)
    except ValueError:
        return None

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk command /start"""
    keyboard = [
        [InlineKeyboardButton("✅ Beli Lira", callback_data="beli_lira")],
        [InlineKeyboardButton("📊 Lihat Kurs", callback_data="lihat_kurs")],
        [InlineKeyboardButton("🙋 Bantuan Admin", callback_data="bantuan_admin")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "🇹🇷 Selamat datang di **LiraKuBot**!\n\n"
        "💱 Bot terpercaya untuk tukar Rupiah ke Turkish Lira\n"
        "⚡ Proses cepat & aman\n"
        "💰 Rate terbaik se-Indonesia\n\n"
        "Silakan pilih menu di bawah:"
    )
    
    await update.message.reply_text(
        welcome_text, 
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk inline keyboard callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "beli_lira":
        await query.edit_message_text(
            "💸 Masukkan nominal Rupiah yang ingin ditukar:\n\n"
            "Contoh: 1.000.000 (untuk satu juta rupiah)\n"
            "Minimum: 100.000\n\n"
            "Ketik /cancel untuk membatalkan"
        )
        return INPUT_NOMINAL
        
    elif query.data == "lihat_kurs":
        await show_exchange_rate(query)
        
    elif query.data == "bantuan_admin":
        await query.edit_message_text(
            "🙋 **Butuh bantuan?**\n\n"
            "📱 Hubungi admin kami:\n"
            "• Telegram: @lirakuadmin\n"
            "• WhatsApp: wa.me/6281234567890\n\n"
            "⏰ Jam operasional: 09:00 - 21:00 WIB\n\n"
            "Kembali ke /start",
            parse_mode='Markdown'
        )
        
    elif query.data.startswith("payment_"):
        await handle_payment_selection(query, context)

async def show_exchange_rate(query):
    """Tampilkan simulasi kurs"""
    exchange_rate = await get_exchange_rate()
    
    # Simulasi untuk 100rb dan 1jt
    try_100k = calculate_lira_with_margin(100000, exchange_rate)
    try_1m = calculate_lira_with_margin(1000000, exchange_rate)
    
    text = (
        "📊 **Simulasi Tukar:**\n\n"
        f"💸 Rp100.000 = 🇹🇷 {try_100k:.2f} Lira\n"
        f"💸 Rp1.000.000 = 🇹🇷 {try_1m:.1f} Lira\n\n"
        "✅ Lebih murah dari bandara atau bank!\n\n"
        "Kembali ke /start"
    )
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def input_nominal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk input nominal IDR"""
    text = update.message.text
    
    if text == "/cancel":
        await update.message.reply_text("❌ Transaksi dibatalkan. Ketik /start untuk memulai lagi.")
        return ConversationHandler.END
    
    nominal = parse_currency(text)
    
    if not nominal or nominal < 100000:
        await update.message.reply_text(
            "❌ Nominal tidak valid!\n\n"
            "Minimum Rp100.000\n"
            "Contoh: 1.000.000\n\n"
            "Silakan coba lagi atau ketik /cancel"
        )
        return INPUT_NOMINAL
    
    # Simpan data transaksi
    user_id = update.effective_user.id
    transaction_data[user_id] = {"nominal_idr": nominal}
    
    # Hitung konversi
    exchange_rate = await get_exchange_rate()
    try_amount = calculate_lira_with_margin(nominal, exchange_rate)
    transaction_data[user_id]["nominal_try"] = try_amount
    
    # Tampilkan hasil konversi
    await update.message.reply_text(
        f"🇹🇷 **Hasil Konversi:**\n\n"
        f"💸 Rp{format_currency(nominal)}\n"
        f"= 🇹🇷 {try_amount:.2f} Turkish Lira\n\n"
        "✅ Rate sudah termasuk fee transaksi\n\n"
        "Selanjutnya, masukkan **nama lengkap** sesuai rekening Turki:",
        parse_mode='Markdown'
    )
    
    return INPUT_NAMA

async def input_nama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk input nama lengkap"""
    if update.message.text == "/cancel":
        await update.message.reply_text("❌ Transaksi dibatalkan. Ketik /start untuk memulai lagi.")
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    nama = update.message.text.strip()
    
    if len(nama) < 3:
        await update.message.reply_text(
            "❌ Nama terlalu pendek!\n\n"
            "Masukkan nama lengkap sesuai rekening Turki\n"
            "Silakan coba lagi atau ketik /cancel"
        )
        return INPUT_NAMA
    
    transaction_data[user_id]["nama"] = nama
    
    await update.message.reply_text(
        f"👤 Nama: **{nama}**\n\n"
        "Sekarang masukkan **IBAN atau nomor rekening Turki** tujuan:",
        parse_mode='Markdown'
    )
    
    return INPUT_IBAN

async def input_iban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk input IBAN/rekening Turki"""
    if update.message.text == "/cancel":
        await update.message.reply_text("❌ Transaksi dibatalkan. Ketik /start untuk memulai lagi.")
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    iban = update.message.text.strip()
    
    if len(iban) < 10:
        await update.message.reply_text(
            "❌ IBAN/rekening tidak valid!\n\n"
            "Masukkan IBAN atau nomor rekening Turki yang benar\n"
            "Silakan coba lagi atau ketik /cancel"
        )
        return INPUT_IBAN
    
    transaction_data[user_id]["iban"] = iban
    
    # Tampilkan pilihan pembayaran
    keyboard = [
        [InlineKeyboardButton("1️⃣ QRIS (Biaya Rp7.000)", callback_data="payment_qris")],
        [InlineKeyboardButton("2️⃣ Virtual Account (Biaya Rp4.400)", callback_data="payment_va")],
        [InlineKeyboardButton("3️⃣ Transfer Manual ke BCA (tanpa biaya)", callback_data="payment_bca")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    data = transaction_data[user_id]
    await update.message.reply_text(
        f"📋 **Ringkasan Transaksi:**\n\n"
        f"👤 Nama: {data['nama']}\n"
        f"🏦 IBAN/Rekening: {data['iban']}\n"
        f"💸 Jumlah: Rp{format_currency(data['nominal_idr'])}\n"
        f"🇹🇷 Akan diterima: {data['nominal_try']:.2f} TRY\n\n"
        "🔘 **Pilih Metode Pembayaran:**",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return PILIH_PEMBAYARAN

async def handle_payment_selection(query, context):
    """Handler untuk pemilihan metode pembayaran"""
    user_id = query.from_user.id
    data = transaction_data.get(user_id)
    
    if not data:
        await query.edit_message_text("❌ Data transaksi tidak ditemukan. Silakan mulai ulang dengan /start")
        return ConversationHandler.END
    
    if query.data == "payment_qris":
        await process_qris_payment(query, context, data)
        
    elif query.data == "payment_va":
        await process_va_payment(query, context, data)
        
    elif query.data == "payment_bca":
        await process_bca_payment(query, context, data)

async def process_qris_payment(query, context, data):
    """Proses pembayaran via QRIS"""
    user_id = query.from_user.id
    total_amount = data["nominal_idr"] + 7000  # Biaya QRIS
    
    # Parameter Midtrans
    transaction_details = {
        "order_id": f"LIRA-QRIS-{user_id}-{int(datetime.now().timestamp())}",
        "gross_amount": total_amount
    }
    
    item_details = [
        {
            "id": "lira_qris",
            "price": data["nominal_idr"],
            "quantity": 1,
            "name": f"Pembelian {data['nominal_try']:.2f} Turkish Lira"
        },
        {
            "id": "fee_qris",
            "price": 7000,
            "quantity": 1,
            "name": "Biaya QRIS"
        }
    ]
    
    customer_details = {
        "first_name": data["nama"],
        "phone": "08123456789"  # Bisa diambil dari input user jika perlu
    }
    
    param = {
        "transaction_details": transaction_details,
        "item_details": item_details,
        "customer_details": customer_details,
        "enabled_payments": ["qris"]
    }
    
    try:
        transaction = snap.create_transaction(param)
        payment_url = transaction['redirect_url']
        
        data["metode_bayar"] = "QRIS"
        data["order_id"] = transaction_details["order_id"]
        data["total_amount"] = total_amount
        
        # Log ke Google Sheets
        log_to_sheets(data)
        
        await query.edit_message_text(
            f"📱 **Pembayaran QRIS**\n\n"
            f"💰 Total: Rp{format_currency(total_amount)}\n"
            f"(Termasuk biaya QRIS Rp7.000)\n\n"
            f"🔗 [Klik di sini untuk bayar]({payment_url})\n\n"
            "⏰ Selesaikan pembayaran dalam 15 menit\n"
            "✅ Status akan otomatis terupdate setelah pembayaran berhasil",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error creating QRIS payment: {e}")
        await query.edit_message_text(
            "❌ Terjadi kesalahan saat membuat pembayaran QRIS.\n"
            "Silakan coba lagi atau pilih metode lain.\n\n"
            "Ketik /start untuk memulai ulang"
        )

async def process_va_payment(query, context, data):
    """Proses pembayaran via Virtual Account"""
    user_id = query.from_user.id
    total_amount = data["nominal_idr"] + 4400  # Biaya VA
    
    # Parameter Midtrans
    transaction_details = {
        "order_id": f"LIRA-VA-{user_id}-{int(datetime.now().timestamp())}",
        "gross_amount": total_amount
    }
    
    item_details = [
        {
            "id": "lira_va",
            "price": data["nominal_idr"],
            "quantity": 1,
            "name": f"Pembelian {data['nominal_try']:.2f} Turkish Lira"
        },
        {
            "id": "fee_va",
            "price": 4400,
            "quantity": 1,
            "name": "Biaya Virtual Account"
        }
    ]
    
    customer_details = {
        "first_name": data["nama"],
        "phone": "08123456789"
    }
    
    param = {
        "transaction_details": transaction_details,
        "item_details": item_details,
        "customer_details": customer_details,
        "enabled_payments": ["bank_transfer"]
    }
    
    try:
        transaction = snap.create_transaction(param)
        payment_url = transaction['redirect_url']
        
        data["metode_bayar"] = "Virtual Account"
        data["order_id"] = transaction_details["order_id"]
        data["total_amount"] = total_amount
        
        # Log ke Google Sheets
        log_to_sheets(data)
        
        await query.edit_message_text(
            f"🏦 **Pembayaran Virtual Account**\n\n"
            f"💰 Total: Rp{format_currency(total_amount)}\n"
            f"(Termasuk biaya VA Rp4.400)\n\n"
            f"🔗 [Klik di sini untuk bayar]({payment_url})\n\n"
            "⏰ Selesaikan pembayaran dalam 24 jam\n"
            "✅ Status akan otomatis terupdate setelah pembayaran berhasil",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error creating VA payment: {e}")
        await query.edit_message_text(
            "❌ Terjadi kesalahan saat membuat pembayaran VA.\n"
            "Silakan coba lagi atau pilih metode lain.\n\n"
            "Ketik /start untuk memulai ulang"
        )

async def process_bca_payment(query, context, data):
    """Proses pembayaran via Transfer Manual BCA"""
    user_id = query.from_user.id
    
    data["metode_bayar"] = "Transfer BCA Manual"
    data["total_amount"] = data["nominal_idr"]  # Tanpa biaya tambahan
    
    # Log ke Google Sheets
    log_to_sheets(data)
    
    await query.edit_message_text(
        f"💳 **Transfer Manual ke BCA**\n\n"
        f"💰 Total Transfer: Rp{format_currency(data['nominal_idr'])}\n"
        f"(Tanpa biaya tambahan)\n\n"
        f"**Detail Rekening:**\n"
        f"🏦 Bank: BCA\n"
        f"👤 Nama: Muhammad Haikal sutanto\n"
        f"💳 Rekening: 7645257260\n\n"
        "📤 Setelah transfer, kirim **bukti transfer** ke chat ini.\n"
        "⏰ Lira akan dikirim setelah verifikasi (maks 2 jam)",
        parse_mode='Markdown'
    )
    
    # Update conversation state untuk menunggu bukti transfer
    return UPLOAD_BUKTI

async def upload_bukti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk upload bukti transfer"""
    user_id = update.effective_user.id
    data = transaction_data.get(user_id)
    
    if not data:
        await update.message.reply_text("❌ Data transaksi tidak ditemukan. Silakan mulai ulang dengan /start")
        return ConversationHandler.END
    
    if update.message.photo:
        # Kirim bukti transfer ke admin
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=update.message.photo[-1].file_id,
            caption=f"🔔 **Bukti Transfer Baru**\n\n"
                   f"👤 User ID: {user_id}\n"
                   f"👤 Nama: {data['nama']}\n"
                   f"🏦 IBAN: {data['iban']}\n"
                   f"💸 Nominal: Rp{format_currency(data['nominal_idr'])}\n"
                   f"🇹🇷 TRY: {data['nominal_try']:.2f}\n"
                   f"💳 Metode: {data['metode_bayar']}\n\n"
                   f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode='Markdown'
        )
        
        await update.message.reply_text(
            "✅ **Bukti transfer berhasil dikirim!**\n\n"
            "🔍 Tim kami akan memverifikasi dalam 2 jam\n"
            "📱 Anda akan mendapat notifikasi setelah verifikasi selesai\n\n"
            "📢 Yuk gabung channel kami untuk info kurs & promo terbaru!\n"
            "👉 https://t.me/+FwH-_TeJg3pjNDJl",
            parse_mode='Markdown'
        )
        
        return ConversationHandler.END
        
    else:
        await update.message.reply_text(
            "❌ Mohon kirim **foto/gambar** bukti transfer.\n\n"
            "Atau ketik /cancel untuk membatalkan"
        )
        return UPLOAD_BUKTI

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk cancel conversation"""
    user_id = update.effective_user.id
    if user_id in transaction_data:
        del transaction_data[user_id]
    
    await update.message.reply_text(
        "❌ Transaksi dibatalkan.\n\n"
        "Ketik /start untuk memulai transaksi baru."
    )
    return ConversationHandler.END

# FastAPI untuk webhook
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan handler untuk setup dan cleanup"""
    global application
    
    # Startup
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Conversation handler untuk alur beli lira
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_callback, pattern="^beli_lira$")],
        states={
            INPUT_NOMINAL: [MessageHandler(filters.TEXT, input_nominal)],
            INPUT_NAMA: [MessageHandler(filters.TEXT, input_nama)],
            INPUT_IBAN: [MessageHandler(filters.TEXT, input_iban)],
            PILIH_PEMBAYARAN: [CallbackQueryHandler(button_callback, pattern="^payment_")],
            UPLOAD_BUKTI: [MessageHandler(filters.PHOTO | filters.TEXT, upload_bukti)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)]
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Initialize application
    await application.initialize()
    await application.start()
    
    # Set webhook
    await application.bot.set_webhook(url=WEBHOOK_URL)
    
    yield
    
    # Cleanup
    await application.stop()
    await application.shutdown()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(request: Request):
    """Webhook endpoint untuk menerima update dari Telegram"""
    try:
        json_data = await request.json()
        update = Update.de_json(json_data, application.bot)
        await application.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return {"status": "error"}

@app.post("/midtrans-webhook")
async def midtrans_webhook(request: Request):
    """Webhook untuk notifikasi pembayaran dari Midtrans"""
    try:
        json_data = await request.json()
        
        order_id = json_data.get('order_id')
        transaction_status = json_data.get('transaction_status')
        fraud_status = json_data.get('fraud_status', 'accept')
        
        if transaction_status == 'settlement' and fraud_status == 'accept':
            # Payment successful
            await handle_payment_success(order_id)
            
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Error processing Midtrans webhook: {e}")
        return {"status": "error"}

async def handle_payment_success(order_id: str):
    """Handle pembayaran sukses"""
    try:
        # Extract user_id dari order_id
        parts = order_id.split('-')
        if len(parts) >= 3:
            user_id = int(parts[2])
            
            # Kirim notifikasi ke user
            await application.bot.send_message(
                chat_id=user_id,
                text="✅ **Pembayaran berhasil!**\n\n"
                     "🇹🇷 Lira akan segera dikirim ke rekening kamu.\n\n"
                     "📢 Yuk gabung channel kami untuk info kurs & promo terbaru!\n"
                     "👉 https://t.me/+FwH-_TeJg3pjNDJl",
                parse_mode='Markdown'
            )
            
            # Update status di Google Sheets bisa ditambahkan di sini
            
    except Exception as e:
        logger.error(f"Error handling payment success: {e}")

@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "LiraKuBot is running!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
