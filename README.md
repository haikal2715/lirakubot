# LiraKuBot - Bot Telegram Jual Beli Lira Turki

Bot Telegram untuk layanan jual beli Lira Turki (TRY) dengan fitur lengkap dan terintegrasi dengan Google Sheets.

## 🚀 Fitur Utama

- 💸 **Beli Lira**: Konversi IDR ke TRY dengan margin 3.5%
- 💵 **Jual Lira**: Konversi TRY ke IDR tanpa margin
- 💱 **Simulasi Kurs**: Tampilkan estimasi kurs real-time
- 👤 **Kontak Admin**: Informasi kontak admin
- 📊 **Otomatis ke Google Sheets**: Semua transaksi tersimpan otomatis
- 🔔 **Notifikasi Admin**: Admin mendapat notifikasi setiap transaksi
- ⚡ **Toggle Fitur**: Dapat mematikan/menghidupkan fitur beli/jual

## 🛠️ Setup & Instalasi

### 1. Persiapan Bot Telegram

1. Buat bot baru di [@BotFather](https://t.me/botfather)
2. Gunakan command `/newbot`
3. Beri nama bot: `LiraKuBot`
4. Username bot: `LiraKuBot` (atau yang tersedia)
5. Simpan token yang diberikan

### 2. Setup Exchange Rate API

1. Daftar di [ExchangeRate-API](https://exchangerate-api.com/)
2. Dapatkan API key gratis (1500 requests/bulan)
3. Simpan API key

### 3. Setup Google Sheets

#### A. Buat Service Account
1. Buka [Google Cloud Console](https://console.cloud.google.com/)
2. Buat project baru atau pilih yang sudah ada
3. Enable Google Sheets API
4. Buat Service Account:
   - IAM & Admin → Service Accounts → Create Service Account
   - Beri nama: `lirakubot`
   - Grant role: `Editor`
5. Generate JSON key file:
   - Klik service account → Keys → Add Key → Create New Key
   - Pilih JSON
   - Download dan rename menjadi `lirakubot.json`

#### B. Setup Spreadsheet
1. Buka Google Sheets
2. Buat spreadsheet baru dengan nama: `DATA LIRAKU.ID`
3. Share spreadsheet dengan email service account (dari file JSON)
4. Berikan akses `Editor`

### 4. Setup Environment

1. Clone/download source code
2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Buat file `.env` dari template:
```bash
cp .env.example .env
```

4. Edit file `.env`:
```env
BOT_TOKEN=1234567890:AABBCCDDEEFFgghhiijjkkllmmnnoopp
EXCHANGE_API_KEY=your_exchangerate_api_key
ADMIN_CHAT_ID=123456789
ADMIN_IBAN=TR1234567890123456789012345
```

5. Letakkan file `lirakubot.json` di folder yang sama dengan bot

### 5. Mendapatkan Admin Chat ID

Untuk mendapatkan chat ID admin:

1. Start bot Anda
2. Kirim pesan `/start` ke bot
3. Buka URL: `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates`
4. Cari `chat.id` dari response JSON
5. Masukkan ke file `.env`

### 6. Menjalankan Bot

```bash
python lirakubot.py
```

Bot akan berjalan dengan polling mode dan siap menerima pesan.

## 📋 Struktur Database (Google Sheets)

Kolom-kolom yang akan dibuat otomatis:

| Kolom | Deskripsi |
|-------|-----------|
| Waktu | Timestamp transaksi |
| Nama | Nama lengkap user |
| IBAN/Rekening | IBAN (beli) atau rekening (jual) |
| IDR | Jumlah Rupiah |
| TRY | Jumlah Lira Turki |
| Status | Status transaksi |
| Username | Username Telegram |
| User ID | ID user Telegram |
| Jenis | "Beli Lira" atau "Jual Lira" |

## ⚙️ Konfigurasi

### Toggle Fitur

Untuk mematikan/menghidupkan fitur, edit variabel di awal file `lirakubot.py`:

```python
# Feature toggles
BUY_LIRA_ACTIVE = True   # Set False untuk menonaktifkan beli lira
SELL_LIRA_ACTIVE = True  # Set False untuk menonaktifkan jual lira
```

### Margin & Fee

- **Margin beli**: 3.5% (sudah termasuk dalam kode)
- **Fee admin**: Rp7.000 (dapat diubah di kode)
- **Margin jual**: 0% (tanpa margin)

## 🔄 Alur Transaksi

### Beli Lira (IDR → TRY)
1. User input nominal IDR (min Rp100.000)
2. Tampilkan estimasi TRY dengan margin 3.5%
3. Input nama lengkap sesuai IBAN
4. Input IBAN Turki (format TR + 24 angka)
5. Tampilkan ringkasan + rekening BCA untuk transfer
6. Konfirmasi pembayaran
7. Notifikasi ke admin + simpan ke Sheets

### Jual Lira (TRY → IDR)
1. User input jumlah TRY
2. Tampilkan estimasi IDR (tanpa margin)
3. Input nama lengkap
4. Input rekening bank Indonesia
5. Tampilkan IBAN admin untuk transfer TRY
6. Konfirmasi pengiriman
7. Notifikasi ke admin + simpan ke Sheets

## 🛡️ Keamanan & Validasi

- ✅ Validasi format IBAN Turki (TR + 24 angka)
- ✅ Validasi nominal minimum
- ✅ Sanitasi input user
- ✅ Error handling untuk API calls
- ✅ Logging untuk debugging

## 📱 Commands & Navigasi

- `/start` - Mulai bot dan tampilkan menu utama
- `/cancel` - Batalkan transaksi yang sedang berjalan
- `🔙 Kembali` - Kembali ke step sebelumnya
- `🏠 Menu Utama` - Kembali ke menu utama

## 🔧 Troubleshooting

### Error: AttributeError 'Updater' object has no attribute

Ini adalah masalah kompatibilitas dengan Python 3.13 atau versi `python-telegram-bot`. Solusi:

#### Opsi 1: Gunakan Fix Script (Recommended)
```bash
python fix_installation.py
```

#### Opsi 2: Manual Fix
```bash
# Uninstall semua telegram packages
pip uninstall -y python-telegram-bot telegram python-telegram pytelegram

# Install versi yang kompatibel
pip install python-telegram-bot==20.3

# Atau jika masih error, gunakan versi lama yang stabil:
pip install python-telegram-bot==13.15
```

#### Opsi 3: Gunakan Python 3.11/3.12
Python 3.13 masih terlalu baru dan beberapa package belum sepenuhnya kompatibel.

### Test Installation
Sebelum menjalankan bot utama, test dulu dengan:
```bash
python simple_test_bot.py
```

### Bot tidak merespon
- Periksa token bot di `.env`
- Pastikan bot sudah di-start di BotFather

### Error Google Sheets
- Periksa file `lirakubot.json` sudah ada
- Pastikan spreadsheet sudah di-share dengan service account
- Cek nama spreadsheet: `DATA LIRAKU.ID`

### Error Exchange Rate
- Periksa API key exchangerate-api
- Cek koneksi internet
- Pastikan belum mencapai limit API (1500/bulan)

### Notifikasi admin tidak masuk
- Periksa `ADMIN_CHAT_ID` di `.env`
- Pastikan admin sudah kirim `/start` ke bot minimal sekali

## 📊 Monitoring

Bot akan mencatat semua aktivitas di console log. Untuk production, gunakan:

```bash
python lirakubot.py > bot.log 2>&1 &
```

## 🔄 Update & Maintenance

Untuk update kurs dan monitoring:
- Kurs diambil real-time dari exchangerate-api
- Data tersimpan otomatis di Google Sheets
- Log transaksi dapat dimonitor via Sheets

## 📞 Support

Untuk pertanyaan teknis, hubungi developer atau periksa log error di console.

## ⚖️ Disclaimer

Bot ini dibuat untuk keperluan bisnis jual beli mata uang. Pastikan mematuhi regulasi keuangan yang berlaku di wilayah Anda.
