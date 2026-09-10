# Sistem Kalkulasi Gaji & Insentif XL SATU (Telegram Bot)

Sistem bot Telegram terintegrasi untuk membaca, menghitung, dan menyajikan estimasi perolehan gaji pokok, insentif produk, multiplier insentif, dan insentif pemasangan bagi Sales Agent (SA) XL SATU.

---

## 🚀 Fitur Utama

1. **Sinkronisasi Live Google Spreadsheet**:
   - Membaca data langsung dari Google Spreadsheet [XL SATU Calculation](https://docs.google.com/spreadsheets/d/1Y6ex2HGUcGcDm18PMTPNKJlEZUrn-8YNU3hBg8o1XCo/edit?usp=sharing).
   - Menggunakan endpoint Google Visualization API (GViz) tanpa perlu setup OAuth kompleks atau GCP Service Account.
   - Caching otomatis cerdas untuk efisiensi kuota dan kecepatan respon.

2. **Mesin Kalkulasi Lengkap & Akurat**:
   - **Gaji Pokok**: Sesuai level SA (OJT: Rp 2.500.000, PRO: Rp 3.500.000, ELITE: Rp 4.000.000).
   - **Insentif Produk Reguler**: 8 kelompok paket produk (FTTH < 228k s.d >= 600k, FWA Monthly, FWA & FTTH 3-5 bln, FWA & FTTH >= 6 bln).
   - **Spesial Insentif**: Khusus paket FWA & FTTH periode 3–5 bln dan >= 6 bln.
   - **Insentif Multiplier**: Penambahan pengali (hingga 4.65x) berbasis total unit terjual untuk posisi PRO & ELITE.
   - **Insentif Pemasangan**: Skema *Progressive Slab Tier* (1-6 unit @Rp 80rb, 7-9 unit @Rp 100rb, 10-13 unit @Rp 130rb, dst.).
   - **Take Home Pay (THP)**: `Gaji Pokok + Total Insentif - Potongan`.

3. **Interaktif di Telegram**:
   - Tombol Inline Keyboard memudahkan navigasi tanpa perlu banyak mengetik.
   - Fitur cek slip gaji per SA (`/cek <nama>`).
   - Fitur simulasi proyeksi pendapatan (`/simulasi` atau `/hitung <posisi> <unit>`).
   - Informasi skema tarif lengkap (`/info`).
   - Refresh data realtime dari spreadsheet (`/refresh`).

---

## 🤖 Informasi Bot Telegram

- **Nama Bot**: Income Calculations (`PaySim_bot`)
- **Username**: [@IncomeSim_bot](https://t.me/IncomeSim_bot)
- **Token**: Tersimpan aman di file `.env`

---

## 📁 Struktur File

```
├── config.py             # Konfigurasi katalog produk, gaji pokok, tier pemasangan, & URL
├── user_manager.py       # Manajemen database SQLite user, autentikasi, & normalisasi no HP
├── calculator.py         # Engine kalkulasi matematika & generator slip format Telegram
├── sheet_reader.py       # Reader live Google Spreadsheet (GViz CSV parser)
├── bot.py                # Server Telegram Bot (Long-polling, auth gate, event loop)
├── test_auth.py          # Unit test manajemen autentikasi & validasi nomor HP
├── test_auth_bot_flow.py # Integration test alur login & interaksi bot Telegram
├── test_calculator.py    # Unit test verifikasi logika kalkulasi (100% Match)
├── test_bot_integration.py # Integration test bot client & live sheet
├── .env                  # Konfigurasi variabel lingkungan (Token & Spreadsheet ID)
├── requirements.txt      # Daftar dependensi Python
└── README.md             # Dokumentasi proyek
```

---

## 🔐 Sistem Login & Verifikasi Pengguna (Nama & No HP)

Sebelum dapat mengakses fitur kalkulasi, bot mewajibkan pengguna untuk melakukan verifikasi:
1. **Langkah 1**: Memasukkan **Nama Lengkap** (sesuai nama Sales Agent).
2. **Langkah 2**: Memasukkan **Nomor HP** (dapat menggunakan tombol *📱 Bagikan Kontak Saya* native Telegram atau ketik manual).
3. **Penyimpanan Persisten**: Tersimpan di database lokal SQLite (`users.db`), zero external dependency.
4. **Otomatisasi Slip**: Bot secara cerdas mencocokkan nama terdaftar dengan nama agen di sheet sehingga pengguna dapat langsung melihat slip gajinya dalam 1 klik.
5. **Manajemen Akun**: Pengguna dapat melihat profil (`/profil`) atau berganti akun kapan saja (`/logout`).

---

## 🛠️ Cara Menjalankan Bot

### 1. Pastikan Python 3 Terpasang
Bot ini dirancang **Zero External Dependency** (menggunakan library bawaan Python `urllib`, `sqlite3`, `ssl`, `json`). Anda bisa langsung menjalankannya dengan:

```bash
python3 bot.py
```

Atau jika ingin menggunakan background process:
```bash
nohup python3 bot.py > bot.log 2>&1 &
```

---

## 💬 Panduan Perintah Telegram

| Perintah | Deskripsi |
|---|---|
| `/start` | Membuka menu utama atau memicu alur login jika belum terdaftar |
| `/profil` | Melihat detail profil pengguna, nomor HP terdaftar, dan status akun |
| `/logout` | Keluar dari akun saat ini dan mengunci kembali akses bot |
| `/cek <nama>` | Cek data slip gaji agen tertentu (contoh: `/cek Noorman`) |
| `/hitung <posisi> <unit>` | Simulasi cepat (contoh: `/hitung PRO 12` atau `/hitung ELITE 25`) |
| `/simulasi` | Mode simulasi interaktif step-by-step |
| `/agen` | Menampilkan daftar seluruh nama agen di Google Spreadsheet |
| `/info` | Menampilkan tabel kompensasi, tarif insentif, multiplier & tier |
| `/refresh` | Memperbarui cache dari Google Spreadsheet secara instan |
| `/help` | Menampilkan panduan bantuan |
