import logging
import re
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from config import *
from exchange import convert_idr_to_try, convert_try_to_idr
from sheets import log_transaction
from templates.menu import main_menu

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# State untuk beli Lira
BUY_NOMINAL, BUY_NAMA, BUY_IBAN = range(3)

# State untuk jual Lira
SELL_NOMINAL, SELL_NAMA, SELL_REKENING = range(3, 6)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Selamat datang di LiraKuBot 🇹🇷\n\nSilakan pilih menu:",
        reply_markup=main_menu()
    )

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'buy':
        await query.message.reply_text("💸 Masukkan nominal pembelian (minimal Rp100.000):")
        return BUY_NOMINAL
    elif data == 'sell':
        await query.message.reply_text("💵 Masukkan jumlah Lira (TRY) yang ingin dijual:")
        return SELL_NOMINAL
    elif data == 'kurs':
        await show_kurs(query)
    elif data == 'contact':
        await query.message.reply_text("Kontak Admin:\nTelegram: @haikal2715\nWhatsApp: 087773834406")
    return ConversationHandler.END

async def beli_nominal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace('.', '').replace(',', '')
    if not text.isdigit() or int(text) < 100000:
        await update.message.reply_text("⚠️ Masukkan minimal Rp100.000 (gunakan titik jika perlu).")
        return BUY_NOMINAL

    context.user_data['nominal'] = int(text)
    await update.message.reply_text("✍️ Masukkan nama lengkap kamu:")
    return BUY_NAMA

async def beli_nama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['nama'] = update.message.text
    await update.message.reply_text("🏦 Masukkan IBAN kamu (24 digit):")
    return BUY_IBAN

async def beli_iban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    iban = update.message.text.strip().replace(' ', '')
    if not re.match(r'^TR\d{22}$', iban):
        await update.message.reply_text("⚠️ Format IBAN salah. Contoh: TR1234567890123456789012")
        return BUY_IBAN

    context.user_data['iban'] = iban
    nominal = context.user_data['nominal']
    nama = context.user_data['nama']
    lira = convert_idr_to_try(nominal)

    instruksi = (
        f"✅ Data kamu:\n"
        f"Nama: {nama}\n"
        f"Nominal: Rp{nominal:,}\n"
        f"IBAN: {iban}\n\n"
        f"💱 Kamu akan menerima sekitar {lira} Lira Turki 🇹🇷\n"
        f"Silakan transfer Rp{nominal + 7000:,} ke rekening berikut:\n\n"
        f"🏦 *BCA 7645257260 a.n. Muhammad Haikalstanto*\n\n"
        f"📸 Setelah transfer, kirim bukti via Telegram ke @haikal2715 atau WhatsApp ke 087773834406\n"
    )

    await update.message.reply_text(instruksi, parse_mode='Markdown')

    # Kirim notifikasi ke admin
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 *PEMBELIAN MASUK!*\n\nNama: {nama}\nNominal: Rp{nominal:,}\nIBAN: {iban}\nEstimasi: {lira} Lira",
        parse_mode='Markdown'
    )

    # Simpan ke Google Sheets
    log_transaction('Beli', nama, nominal, lira, iban)

    return ConversationHandler.END

async def jual_nominal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace('.', '').replace(',', '')
    if not text.isdigit() or int(text) < 50:
        await update.message.reply_text("⚠️ Masukkan minimal 50 Lira.")
        return SELL_NOMINAL

    context.user_data['lira'] = int(text)
    await update.message.reply_text("✍️ Masukkan nama lengkap kamu:")
    return SELL_NAMA


async def jual_nama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['nama'] = update.message.text
    await update.message.reply_text("🏦 Masukkan nomor rekening + nama bank kamu:")
    return SELL_REKENING


async def jual_rekening(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['rekening'] = update.message.text
    lira = context.user_data['lira']
    nama = context.user_data['nama']
    rekening = context.user_data['rekening']
    rupiah = convert_try_to_idr(lira)

    info = (
        f"✅ Data kamu:\n"
        f"Nama: {nama}\n"
        f"Jumlah: {lira} TRY\n"
        f"Rekening: {rekening}\n\n"
        f"💸 Kamu akan menerima sekitar Rp{rupiah:,}.\n"
        f"Kirim {lira} Lira ke IBAN berikut:\n\n"
        f"🏦 *TR330006100519103308107595*\n\n"
        f"📸 Setelah transfer, kirim bukti via Telegram ke @haikal2715 atau WhatsApp ke 087773834406"
    )

    await update.message.reply_text(info, parse_mode='Markdown')

    # Notifikasi ke admin
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📤 *PENJUALAN MASUK!*\n\nNama: {nama}\nLira: {lira} TRY\nRek: {rekening}\nEstimasi bayar: Rp{rupiah:,}",
        parse_mode='Markdown'
    )

    # Simpan ke Google Sheets
    log_transaction('Jual', nama, rupiah, lira, rekening)

    return ConversationHandler.END

conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(beli_start, pattern='^beli_lira$'),
        CallbackQueryHandler(jual_start, pattern='^jual_lira$'),
    ],

    states={
        BUY_NOMINAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, beli_nominal)],
        BUY_NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, beli_nama)],
        BUY_IBAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, beli_iban)],

        SELL_NOMINAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, jual_nominal)],
        SELL_NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, jual_nama)],
        SELL_REKENING: [MessageHandler(filters.TEXT & ~filters.COMMAND, jual_rekening)],
    },

    fallbacks=[]
)


app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(conv_handler)
app.add_handler(CallbackQueryHandler(button_handler))


@app.post(f"/{BOT_TOKEN}")
async def webhook(request):
    if request.method == "POST":
        await app.update_queue.put(Update.de_json(await request.json(), app.bot))
    return web.Response(text="Webhook received")


def main():
    import asyncio
    from aiohttp import web

    asyncio.run(start_bot())


async def start_bot():
    await app.bot.set_webhook(url=f"https://lirakubot.onrender.com/{BOT_TOKEN}")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8000)
    await site.start()

    print("🚀 Bot berjalan di webhook mode...")
    await asyncio.Event().wait()


if __name__ == "__main__":
    main()