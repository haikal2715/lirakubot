import
import re
import asyncio
import logging
import base64
import hashlib
import hmac
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

import httpx
import gspread
from google.oauth2.service_account import Credentials
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import uvicorn

# Konfigurasi logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Konfigurasi Bot
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # URL webhook Replit
EXCHANGE_API_KEY = os.getenv("EXCHANGE_API_KEY")  # exchangerate-api.com

# Konfigurasi Midtrans
MIDTRANS_SERVER_KEY = os.getenv("MIDTRANS_SERVER_KEY")
MIDTRANS_CLIENT_KEY = os.getenv("MIDTRANS_CLIENT_KEY")
MIDTRANS_IS_PRODUCTION = os.getenv("MIDTRANS_IS_PRODUCTION", "false").lower() == "true"
MIDTRANS_BASE_URL = "https://api.midtrans.com/v2" if MIDTRANS_IS_PRODUCTION else "https://api.sandbox.midtrans.com/v2"

# Konstanta
ADMIN_TELEGRAM = "@haikal2715"
ADMIN_WHATSAPP = "087773834406"
TELEGRAM_CHANNEL = "https://t.me/+FwH-_TeJg3pjNDJl"
QRIS_FEE_PERCENT = 0.77
VA_FEE_FIXED = 4400
MARGIN_PER_100K = 3500  # Margin Rp3.500 per Rp100.000

# Global variables
bot_client: httpx.AsyncClient = None
sheets_client = None
user_states: Dict[int, Dict[str, Any]] = {}

class TelegramUpdate(BaseModel):
    update_id: int
    message: Optional[Dict] = None
    callback_query: Optional[Dict] = None

class MidtransNotification(BaseModel):
    order_id: str
    status_code: str
    gross_amount: str
    signature_key: str
    transaction_status: str
    fraud_status: Optional[str] = None
    payment_type: str
    transaction_time: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global bot_client, sheets_client
    bot_client = httpx.AsyncClient(timeout=30.0)
    
    # Initialize Google Sheets
    try:
        scope = ["https://spreadsheets.google.com/feeds", 
                "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file("lirakubot.json", scopes=scope)
        sheets_client = gspread.authorize(creds)
        logger.info("Google Sheets client initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheets: {e}")
    
    # Set webhook
    await set_webhook()
    
    yield
    
    # Shutdown
    if bot_client:
        await bot_client.aclose()

app = FastAPI(lifespan=lifespan)

async def set_webhook():
    """Set webhook URL untuk bot"""
    try:
        webhook_url = WEBHOOK_URL  # ✅ BENAR - langsung pakai tanpa /webhook
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
        data = {"url": webhook_url}
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data)
            if response.status_code == 200:
                logger.info(f"Webhook set successfully: {webhook_url}")
            else:
                logger.error(f"Failed to set webhook: {response.text}")
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")

async def send_message(chat_id: int, text: str, reply_markup: Optional[Dict] = None):
    """Kirim pesan ke Telegram"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        if reply_markup:
            data["reply_markup"] = reply_markup
            
        response = await bot_client.post(url, json=data)
        return response.json()
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return None

async def answer_callback_query(callback_query_id: str, text: str = ""):
    """Jawab callback query"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
        data = {"callback_query_id": callback_query_id, "text": text}
        await bot_client.post(url, json=data)
    except Exception as e:
        logger.error(f"Error answering callback query: {e}")

async def get_exchange_rate() -> Optional[float]:
    """Ambil kurs USD ke TRY dari exchangerate-api"""
    try:
        url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_API_KEY}/latest/USD"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            data = response.json()
            
            if response.status_code == 200 and data.get("result") == "success":
                usd_to_try = data["conversion_rates"]["TRY"]
                usd_to_idr = data["conversion_rates"]["IDR"]
                
                # Hitung kurs IDR ke TRY
                idr_to_try = usd_to_try / usd_to_idr
                return idr_to_try
            else:
                logger.error(f"Exchange rate API error: {data}")
                return None
    except Exception as e:
        logger.error(f"Error getting exchange rate: {e}")
        return None

def calculate_try_amount(idr_amount: float) -> float:
    """Hitung jumlah TRY dengan margin tersembunyi"""
    # Ambil kurs dari cache atau database (untuk demo, gunakan nilai tetap)
    # Dalam implementasi nyata, simpan kurs di cache/database
    base_rate = 0.000525  # Contoh kurs dasar IDR ke TRY
    
    # Hitung margin
    margin_multiplier = MARGIN_PER_100K / 100000  # 3500/100000 = 0.035
    adjusted_rate = base_rate * (1 - margin_multiplier)
    
    return idr_amount * adjusted_rate

def format_currency(amount: float, is_idr: bool = True) -> str:
    """Format mata uang dengan titik pemisah"""
    if is_idr:
        return f"Rp{amount:,.0f}".replace(",", ".")
    else:
        return f"TRY {amount:.2f}"

def validate_iban(iban: str) -> bool:
    """Validasi format IBAN Turki"""
    pattern = r'^TR\d{24}$'
    return bool(re.match(pattern, iban))

def save_transaction_to_sheets(data: Dict[str, Any]):
    """Simpan transaksi ke Google Sheets"""
    try:
        if not sheets_client:
            logger.error("Google Sheets client not initialized")
            return False
            
        # Buka spreadsheet
        sheet = sheets_client.open("DATA LIRAKU.ID").sheet1
        
        # Format data untuk sheet
        row = [
            data.get("nama", ""),
            data.get("iban", ""),
            data.get("idr", ""),
            data.get("try", ""),
            data.get("metode_pembayaran", ""),
            data.get("timestamp", ""),
            data.get("status", "PENDING"),
            data.get("order_id", ""),
            data.get("payment_url", "")
        ]
        
        # Append row
        sheet.append_row(row)
        logger.info("Transaction saved to Google Sheets")
        return True
        
    except Exception as e:
        logger.error(f"Error saving to Google Sheets: {e}")
        return False

def update_transaction_status(order_id: str, status: str):
    """Update status transaksi di Google Sheets"""
    try:
        if not sheets_client:
            logger.error("Google Sheets client not initialized")
            return False
            
        sheet = sheets_client.open("DATA LIRAKU.ID").sheet1
        
        # Cari baris berdasarkan order_id
        orders = sheet.col_values(8)  # Kolom H (order_id)
        
        for i, order in enumerate(orders, start=1):
            if order == order_id:
                sheet.update_cell(i, 7, status)  # Kolom G (status)
                logger.info(f"Transaction {order_id} status updated to {status}")
                return True
        
        logger.warning(f"Order {order_id} not found in sheets")
        return False
        
    except Exception as e:
        logger.error(f"Error updating transaction status: {e}")
        return False

async def create_midtrans_payment(order_id: str, amount: int, customer_details: Dict, payment_type: str) -> Optional[Dict]:
    """Buat pembayaran Midtrans"""
    try:
        url = f"{MIDTRANS_BASE_URL}/charge"
        
        # Basic auth dengan server key
        auth_string = f"{MIDTRANS_SERVER_KEY}:"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_b64}"
        }
        
        # Payment data
        if payment_type == "qris":
            payment_data = {
                "payment_type": "qris",
                "transaction_details": {
                    "order_id": order_id,
                    "gross_amount": amount
                },
                "qris": {
                    "acquirer": "gopay"
                },
                "customer_details": customer_details
            }
        else:  # VA
            payment_data = {
                "payment_type": "bank_transfer",
                "transaction_details": {
                    "order_id": order_id,
                    "gross_amount": amount
                },
                "bank_transfer": {
                    "bank": "bca"
                },
                "customer_details": customer_details
            }
        
        response = await bot_client.post(url, json=payment_data, headers=headers)
        
        if response.status_code == 201:
            return response.json()
        else:
            logger.error(f"Midtrans payment creation failed: {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error creating Midtrans payment: {e}")
        return None

def verify_midtrans_signature(notification: Dict) -> bool:
    """Verifikasi signature Midtrans"""
    try:
        order_id = notification.get("order_id")
        status_code = notification.get("status_code")
        gross_amount = notification.get("gross_amount")
        signature_key = notification.get("signature_key")
        
        # Buat signature string
        signature_string = f"{order_id}{status_code}{gross_amount}{MIDTRANS_SERVER_KEY}"
        
        # Hash dengan SHA512
        calculated_signature = hashlib.sha512(signature_string.encode()).hexdigest()
        
        return calculated_signature == signature_key
        
    except Exception as e:
        logger.error(f"Error verifying Midtrans signature: {e}")
        return False

def get_main_menu_keyboard():
    """Keyboard menu utama"""
    return {
        "inline_keyboard": [
            [{"text": "💸 Beli Lira", "callback_data": "buy_lira"}],
            [{"text": "💱 Lihat Simulasi Kurs", "callback_data": "simulation"}],
            [{"text": "👤 Kontak Admin", "callback_data": "contact_admin"}]
        ]
    }

def get_back_menu_keyboard():
    """Keyboard kembali dan menu utama"""
    return {
        "inline_keyboard": [
            [
                {"text": "🔙 Kembali", "callback_data": "back"},
                {"text": "🏠 Menu Utama", "callback_data": "main_menu"}
            ]
        ]
    }

def get_payment_method_keyboard():
    """Keyboard metode pembayaran"""
    return {
        "inline_keyboard": [
            [{"text": "💳 QRIS (Fee 0.77%)", "callback_data": "payment_qris"}],
            [{"text": "🏦 Virtual Account (Fee Rp4.400)", "callback_data": "payment_va"}],
            [
                {"text": "🔙 Kembali", "callback_data": "back"},
                {"text": "🏠 Menu Utama", "callback_data": "main_menu"}
            ]
        ]
    }

async def show_main_menu(chat_id: int):
    """Tampilkan menu utama"""
    text = """🇹🇷 <b>LIRAKU.ID - Jual Beli Lira Turki</b> 🇹🇷

Selamat datang di layanan jual beli Lira Turki terpercaya!

Silakan pilih menu di bawah ini:"""
    
    await send_message(chat_id, text, get_main_menu_keyboard())

async def show_simulation(chat_id: int):
    """Tampilkan simulasi kurs"""
    # Untuk demo, gunakan nilai tetap. Dalam implementasi nyata, ambil dari API
    simulations = [
        (100000, 1.87),
        (500000, 9.37),
        (1000000, 18.74),
        (2000000, 37.48)
    ]
    
    text = "💱 <b>Simulasi Kurs IDR ke TRY</b>\n\n"
    
    for idr, try_amount in simulations:
        text += f"💸 {format_currency(idr)} ≈ 🇹🇷 TRY {try_amount}\n"
    
    text += "\n📝 <i>Kurs dapat berubah sewaktu-waktu</i>"
    
    await send_message(chat_id, text, get_back_menu_keyboard())

async def show_contact_admin(chat_id: int):
    """Tampilkan kontak admin"""
    text = f"""👤 <b>Kontak Admin</b>

📞 <b>WhatsApp:</b> {ADMIN_WHATSAPP}
💬 <b>Telegram:</b> {ADMIN_TELEGRAM}
📢 <b>Channel:</b> <a href="{TELEGRAM_CHANNEL}">Join Channel</a>

Silakan hubungi admin untuk bantuan lebih lanjut."""
    
    await send_message(chat_id, text, get_back_menu_keyboard())

async def start_buy_process(chat_id: int):
    """Mulai proses pembelian"""
    user_states[chat_id] = {"step": "input_nama"}
    
    text = """💸 <b>Proses Pembelian Lira</b>

Silakan masukkan nama lengkap Anda:"""
    
    await send_message(chat_id, text, get_back_menu_keyboard())

async def handle_text_message(chat_id: int, text: str, user_id: int):
    """Handle pesan teks dari user"""
    user_state = user_states.get(chat_id, {})
    current_step = user_state.get("step")
    
    if current_step == "input_nama":
        user_states[chat_id]["nama"] = text
        user_states[chat_id]["step"] = "input_iban"
        
        reply_text = """✅ Nama berhasil disimpan!

Sekarang masukkan IBAN rekening Turki Anda:
<i>Format: TR + 24 digit angka</i>
<b>Contoh:</b> TR123456789012345678901234"""
        
        await send_message(chat_id, reply_text, get_back_menu_keyboard())
    
    elif current_step == "input_iban":
        if validate_iban(text.upper()):
            user_states[chat_id]["iban"] = text.upper()
            user_states[chat_id]["step"] = "input_idr"
            
            reply_text = """✅ IBAN berhasil disimpan!

Masukkan jumlah Rupiah yang ingin ditukar:
<i>Gunakan titik sebagai pemisah (contoh: 1.000.000)</i>"""
            
            await send_message(chat_id, reply_text, get_back_menu_keyboard())
        else:
            reply_text = """❌ Format IBAN tidak valid!

Format yang benar: TR + 24 digit angka
<b>Contoh:</b> TR123456789012345678901234

Silakan input ulang:"""
            
            await send_message(chat_id, reply_text, get_back_menu_keyboard())
    
    elif current_step == "input_idr":
        try:
            # Remove dots and convert to float
            idr_amount = float(text.replace(".", ""))
            
            if idr_amount < 100000:
                reply_text = "❌ Minimum transaksi Rp100.000\nSilakan input ulang:"
                await send_message(chat_id, reply_text, get_back_menu_keyboard())
                return
            
            try_amount = calculate_try_amount(idr_amount)
            
            user_states[chat_id]["idr_amount"] = idr_amount
            user_states[chat_id]["try_amount"] = try_amount
            user_states[chat_id]["step"] = "select_payment"
            
            reply_text = f"""💰 <b>Ringkasan Pesanan</b>

👤 <b>Nama:</b> {user_state['nama']}
🏦 <b>IBAN:</b> {user_state['iban']}
💸 <b>Rupiah:</b> {format_currency(idr_amount)}
🇹🇷 <b>Lira yang diterima:</b> TRY {try_amount:.2f}

Pilih metode pembayaran:"""
            
            await send_message(chat_id, reply_text, get_payment_method_keyboard())
            
        except ValueError:
            reply_text = """❌ Format angka tidak valid!

Gunakan titik sebagai pemisah (contoh: 1.000.000)
Silakan input ulang:"""
            
            await send_message(chat_id, reply_text, get_back_menu_keyboard())

async def handle_payment_selection(chat_id: int, payment_method: str):
    """Handle pemilihan metode pembayaran"""
    user_state = user_states.get(chat_id, {})
    idr_amount = user_state.get("idr_amount", 0)
    
    if payment_method == "qris":
        fee = idr_amount * (QRIS_FEE_PERCENT / 100)
        total_payment = idr_amount + fee
        method_name = "💳 QRIS"
        fee_text = f"Fee {QRIS_FEE_PERCENT}%: {format_currency(fee)}"
        payment_type = "qris"
    else:  # VA
        fee = VA_FEE_FIXED
        total_payment = idr_amount + fee
        method_name = "🏦 Virtual Account"
        fee_text = f"Fee Admin: {format_currency(fee)}"
        payment_type = "va"
    
    # Generate order ID
    order_id = f"LIRA_{chat_id}_{int(datetime.now().timestamp())}"
    
    # Customer details untuk Midtrans
    customer_details = {
        "first_name": user_state["nama"],
        "email": f"customer_{chat_id}@liraku.id",
        "phone": "+62812345678"  # Default phone
    }
    
    # Buat pembayaran Midtrans
    payment_result = await create_midtrans_payment(
        order_id=order_id,
        amount=int(total_payment),
        customer_details=customer_details,
        payment_type=payment_type
    )
    
    if not payment_result:
        error_text = "❌ Maaf, terjadi kesalahan saat membuat pembayaran. Silakan coba lagi atau hubungi admin."
        await send_message(chat_id, error_text, get_back_menu_keyboard())
        return
    
    # Extract payment info
    if payment_type == "qris":
        qr_string = payment_result.get("actions", [{}])[0].get("url", "")
        payment_info = f"🔗 <a href='{qr_string}'>Klik untuk membuka QRIS</a>"
        payment_instructions = "📱 Scan QR Code atau klik link di atas untuk membayar"
    else:
        va_numbers = payment_result.get("va_numbers", [])
        if va_numbers:
            va_number = va_numbers[0].get("va_number", "")
            bank = va_numbers[0].get("bank", "").upper()
            payment_info = f"🏦 <b>Virtual Account {bank}:</b> <code>{va_number}</code>"
            payment_instructions = f"💳 Transfer ke Virtual Account {bank} di atas"
        else:
            payment_info = "Virtual Account sedang diproses"
            payment_instructions = "Informasi pembayaran akan dikirim segera"
    
    # Simpan data transaksi
    transaction_data = {
        "nama": user_state["nama"],
        "iban": user_state["iban"],
        "idr": idr_amount,
        "try": user_state["try_amount"],
        "metode_pembayaran": method_name,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "PENDING",
        "order_id": order_id,
        "payment_url": qr_string if payment_type == "qris" else va_number if payment_type == "va" else ""
    }
    
    # Simpan ke Google Sheets
    save_transaction_to_sheets(transaction_data)
    
    # Pesan konfirmasi pembayaran
    confirmation_text = f"""✅ <b>Pesanan Berhasil Dibuat!</b>

📋 <b>Detail Pesanan:</b>
🆔 Order ID: <code>{order_id}</code>
👤 Nama: {user_state['nama']}
🏦 IBAN: {user_state['iban']}
💸 Rupiah: {format_currency(idr_amount)}
🇹🇷 Lira: TRY {user_state['try_amount']:.2f}
💳 Pembayaran: {method_name}
{fee_text}
💰 <b>Total Bayar: {format_currency(total_payment)}</b>

💳 <b>Informasi Pembayaran:</b>
{payment_info}

📋 <b>Cara Pembayar:</b>
{payment_instructions}
⏰ Batas waktu: 24 jam

🔔 <b>Status pembayaran akan diupdate otomatis setelah berhasil</b>

📢 Jangan lupa join channel kami: {TELEGRAM_CHANNEL}"""
    
    await send_message(chat_id, confirmation_text, get_back_menu_keyboard())
    
    # Reset user state
    user_states.pop(chat_id, None)

@app.post("/webhook")
async def webhook(request: Request):
    """Webhook endpoint untuk menerima update dari Telegram"""
    try:
        data = await request.json()
        update = TelegramUpdate(**data)
        
        # Handle pesan biasa
        if update.message:
            chat_id = update.message["chat"]["id"]
            user_id = update.message["from"]["id"]
            
            if "text" in update.message:
                text = update.message["text"]
                
                if text == "/start":
                    user_states.pop(chat_id, None)  # Reset state
                    await show_main_menu(chat_id)
                else:
                    await handle_text_message(chat_id, text, user_id)
        
        # Handle callback query
        elif update.callback_query:
            callback_data = update.callback_query["data"]
            chat_id = update.callback_query["message"]["chat"]["id"]
            callback_query_id = update.callback_query["id"]
            
            await answer_callback_query(callback_query_id)
            
            if callback_data == "main_menu":
                user_states.pop(chat_id, None)  # Reset state
                await show_main_menu(chat_id)
            elif callback_data == "buy_lira":
                await start_buy_process(chat_id)
            elif callback_data == "simulation":
                await show_simulation(chat_id)
            elif callback_data == "contact_admin":
                await show_contact_admin(chat_id)
            elif callback_data == "payment_qris":
                await handle_payment_selection(chat_id, "qris")
            elif callback_data == "payment_va":
                await handle_payment_selection(chat_id, "va")
            elif callback_data == "back":
                # Handle back button logic berdasarkan state
                user_state = user_states.get(chat_id, {})
                current_step = user_state.get("step")
                
                if current_step in ["input_nama"]:
                    await show_main_menu(chat_id)
                elif current_step == "input_iban":
                    await start_buy_process(chat_id)
                elif current_step in ["input_idr"]:
                    user_states[chat_id]["step"] = "input_iban"
                    await send_message(chat_id, "Masukkan IBAN rekening Turki Anda:", get_back_menu_keyboard())
                elif current_step == "select_payment":
                    user_states[chat_id]["step"] = "input_idr"
                    await send_message(chat_id, "Masukkan jumlah Rupiah yang ingin ditukar:", get_back_menu_keyboard())
                else:
                    await show_main_menu(chat_id)
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/midtrans-notification")
async def midtrans_notification(request: Request):
    """Webhook untuk notifikasi Midtrans"""
    try:
        data = await request.json()
        logger.info(f"Midtrans notification: {data}")
        
        # Verifikasi signature
        if not verify_midtrans_signature(data):
            logger.error("Invalid Midtrans signature")
            raise HTTPException(status_code=400, detail="Invalid signature")
        
        order_id = data.get("order_id")
        transaction_status = data.get("transaction_status")
        fraud_status = data.get("fraud_status")
        payment_type = data.get("payment_type")
        
        # Tentukan status akhir
        if transaction_status == "capture":
            if fraud_status == "challenge":
                status = "CHALLENGE"
            elif fraud_status == "accept":
                status = "SUCCESS"
            else:
                status = "PENDING"
        elif transaction_status == "settlement":
            status = "SUCCESS"
        elif transaction_status in ["cancel", "deny", "expire"]:
            status = "FAILED"
        elif transaction_status == "pending":
            status = "PENDING"
        else:
            status = "UNKNOWN"
        
        # Update status di Google Sheets
        update_transaction_status(order_id, status)
        
        # Kirim notifikasi ke user jika pembayaran berhasil
        if status == "SUCCESS":
            # Extract chat_id dari order_id (format: LIRA_{chat_id}_{timestamp})
            try:
                chat_id = int(order_id.split("_")[1])
                
                success_text = f"""🎉 <b>Pembayaran Berhasil!</b>

✅ <b>Order ID:</b> <code>{order_id}</code>
💳 <b>Metode:</b> {payment_type.upper()}
💰 <b>Status:</b> BERHASIL

🇹🇷 Lira Turki akan segera dikirim ke IBAN Anda dalam 1x24 jam.

📞 Jika ada kendala, hubungi admin:
💬 Telegram: {ADMIN_TELEGRAM}
📱 WhatsApp: {ADMIN_WHATSAPP}

📢 Join channel: {TELEGRAM_CHANNEL}

Terima kasih telah menggunakan layanan LIRAKU.ID! 🙏"""
                
                await send_message(chat_id, success_text)
                
            except (IndexError, ValueError) as e:
                logger.error(f"Failed to extract chat_id from order_id {order_id}: {e}")
        
        elif status == "FAILED":
            try:
                chat_id = int(order_id.split("_")[1])
                
                failed_text = f"""❌ <b>Pembayaran Gagal</b>

🆔 <b>Order ID:</b> <code>{order_id}</code>
💳 <b>Metode:</b> {payment_type.upper()}
💰 <b>Status:</b> GAGAL

Silakan coba lagi atau hubungi admin jika memerlukan bantuan.

📞 Kontak admin:
💬 Telegram: {ADMIN_TELEGRAM}
📱 WhatsApp: {ADMIN_WHATSAPP}"""
                
                await send_message(chat_id, failed_text, get_main_menu_keyboard())
                
            except (IndexError, ValueError) as e:
                logger.error(f"Failed to extract chat_id from order_id {order_id}: {e}")
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Midtrans notification error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Liraku Bot is running", "status": "active"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
