# 🤖 Rams VIP Bot — v0.4.1

> Bot Telegram berbasis **(Telethon)** dengan sistem langganan VIP.
> Setiap user VIP menjalankan session Telegram miliknya sendiri, sehingga semua fitur berjalan atas nama akun user — bukan bot.

---

## 📋 Daftar Isi

- [Fitur VIP](#-fitur-vip)
- [Command Lengkap](#-command-lengkap)
- [Cara Deploy](#-cara-deploy)
- [Environment Variables](#-environment-variables)
- [Struktur Proyek](#-struktur-proyek)
- [Alur Kerja Bot](#-alur-kerja-bot)
- [Database](#-database)
- [Tech Stack](#-tech-stack)

---

## ✨ Fitur VIP

### ⏱️ 1. Download Media Timer & View Once
Simpan foto atau video yang hanya bisa dilihat sekali (*view once*) maupun media dengan timer. Media didownload ke Saved Messages user sebelum hilang.

- **Manual** — balas pesan view once/timer dengan `.dl`
- **Auto DL** — aktifkan mode otomatis, bot akan menyimpan setiap view once yang masuk ke chat tanpa perlu command

---

### 📣 2. Download dari Channel/Grup Private
Download konten (foto, video, pesan teks, dokumen) dari channel atau grup yang dibatasi — termasuk yang tidak bisa di-*forward*.

- Gunakan link postingan langsung
- Mendukung channel restricted, grup private, dan konten premium

---

### 🎥 3. Download Story
Download story Telegram milik kontak atau akun publik langsung dari link story-nya.

---

### 🏓 4. Ping
Cek status koneksi session Telethon user — apakah masih aktif dan berapa latensi respons server Telegram.

---

### 📢 5. Broadcast ke Semua Grup
Kirim pesan yang sama ke seluruh grup yang user join secara otomatis. Pesan dikirim ulang sebagai pesan baru (bukan *forward*), sehingga tidak ada label "Diteruskan" di chat tujuan.

**Fitur lengkap broadcast:**
- Progress update setiap 5 grup
- Bisa dibatalkan kapan saja dengan `.cancel #task_id`
- Sistem blacklist per-user — kecualikan grup tertentu dari broadcast
- Laporan hasil: berhasil, gagal, dan diskip (blacklist)

---

## 📖 Command Lengkap

> Semua command diawali titik (`.`) dan diketik langsung dari akun Telegram user — bukan di chat bot.

### 🔧 Umum

| Command | Cara Pakai | Keterangan |
|---------|-----------|------------|
| `.ping` | Dari mana saja | Cek latensi koneksi session ke server Telegram |

---

### ⏱️ Download Media

| Command | Cara Pakai | Keterangan |
|---------|-----------|------------|
| `.dl` | Balas pesan view once / timer | Download media view once atau timer ke Saved Messages |
| `.copy <link>` | `.copy https://t.me/channel/123` | Download konten dari channel/grup private atau restricted |
| `.story <link>` | `.story https://t.me/username/s/7` | Download story dari link story |

---

### 📢 Broadcast

| Command | Cara Pakai | Keterangan |
|---------|-----------|------------|
| `.bc <pesan>` | `.bc Halo semua!` | Broadcast pesan ke semua grup yang user join |
| `.cancel #<id>` | `.cancel #abc123` | Batalkan proses broadcast yang sedang berjalan |
| `.addbl` | Ketik di dalam grup | Tambah grup tersebut ke blacklist broadcast |
| `.addbl <id>` | `.addbl -1001234567890` | Tambah grup ke blacklist by ID (dari chat manapun) |
| `.delbl` | Ketik di dalam grup | Hapus grup tersebut dari blacklist broadcast |
| `.delbl <id>` | `.delbl -1001234567890` | Hapus grup dari blacklist by ID |
| `.listbl` | Dari mana saja | Lihat semua grup yang ada di blacklist broadcast |

**Contoh alur broadcast:**
```
1. Ketik: .bc Ada promo menarik nih!

2. Bot membalas di Saved Messages:
   📣 Memproses bc...
   Ketik .cancel #x7k2 untuk membatalkan bc.

3. Setelah selesai:
   💌 Pesan: Ada promo menarik nih!
   ✅ Berhasil: 24 grup
   ❌ Gagal: 1 grup
   ⛔ Diskip (blacklist): 3 grup
```

---

### ⚙️ Bot Command (via chat bot Telegram)

| Command | Keterangan |
|---------|------------|
| `/start` | Tampilkan menu utama |
| `/setup` | Mulai proses setup session Telethon |
| `/cancel` | Batalkan proses yang sedang berjalan (setup, dll) |

---

## 🚀 Cara Deploy

### Deploy ke Railway (Rekomendasi)

Railway adalah platform deploy yang paling mudah dan gratis untuk bot ini.

**1. Fork / Clone repo ini**
```bash
git clone https://github.com/gfrrmd/Rams-VIP-Bot-V.0.4.1.git
cd Rams-VIP-Bot-V.0.4.1
```

**2. Buat project baru di [Railway](https://railway.app)**
- Login ke Railway
- Klik **New Project** → **Deploy from GitHub repo**
- Pilih repo ini

**3. Tambah PostgreSQL database**
- Di dashboard Railway, klik **+ New** → **Database** → **PostgreSQL**
- Railway otomatis menyediakan variable `DATABASE_URL`

**4. Set environment variables**

Buka tab **Variables** di project Railway, lalu tambahkan:

```
BOT_TOKEN       = token bot dari @BotFather
ADMIN_ID        = user ID Telegram kamu (angka)
DATABASE_URL    = (otomatis terisi dari Railway PostgreSQL)
```

**5. Deploy**
- Railway otomatis build & deploy setiap push ke `main`
- Cek tab **Deployments** untuk melihat log

---

### Deploy Manual (VPS / Lokal)

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Siapkan PostgreSQL**
```bash
# Buat database baru
createdb rams_vip_bot
```

**3. Buat file `.env`**
```env
BOT_TOKEN=123456:ABC-your-bot-token
ADMIN_ID=123456789
DATABASE_URL=postgresql://user:password@localhost/rams_vip_bot
```

**4. Jalankan bot**
```bash
python main.py
```

**5. (Opsional) Jalankan sebagai service**
```bash
# Dengan screen
screen -S ramsbot
python main.py
# Ctrl+A lalu D untuk detach

# Atau dengan systemd / supervisor
```

---

### Setup Session User (Setelah Bot Aktif)

Setiap user VIP perlu menghubungkan akun Telegram mereka:

1. Dapatkan **API ID** dan **API Hash** dari [my.telegram.org](https://my.telegram.org)
   - Login → **API development tools** → Buat aplikasi baru
   - Salin `App api_id` dan `App api_hash`

2. Chat bot, klik **Setup Session** atau ketik `/setup`

3. Ikuti langkah:
   - Masukkan **API ID**
   - Masukkan **API Hash**
   - Masukkan **nomor HP** (format internasional: `+62xxxx`)
   - Masukkan **kode OTP** yang dikirim Telegram
   - (Jika aktif) masukkan **password 2FA**

4. Session tersimpan di database — tidak perlu setup ulang kecuali session dicabut.

---

## 🔑 Environment Variables

| Variable | Wajib | Keterangan |
|----------|-------|------------|
| `BOT_TOKEN` | ✅ | Token bot dari [@BotFather](https://t.me/BotFather) |
| `ADMIN_ID` | ✅ | User ID Telegram admin/owner bot |
| `DATABASE_URL` | ✅ | Connection string PostgreSQL (`postgresql://...`) |

---

## 📁 Struktur Proyek

```
Rams-VIP-Bot-V.0.4.1/
│
├── main.py                  # Entry point — inisialisasi bot & jalankan
├── config.py                # Load environment variables
├── database.py              # Semua fungsi database (users, sessions, subscriptions, blacklist)
├── client_manager.py        # Kelola Telethon client per-user (start, stop, reconnect)
├── keyboards.py             # Semua InlineKeyboard layout
├── utils.py                 # Fungsi helper (normalisasi ID, dll)
│
├── handlers/
│   ├── __init__.py
│   ├── commands.py          # Bot commands (/start, /setup, /cancel)
│   ├── callbacks.py         # Inline button callback handler
│   ├── admin.py             # Fitur admin (gift, revoke, backup, restore, blacklist channel)
│   ├── telethon_handlers.py # Handler command userbot (.dl, .copy, .story, .ping, .cancel)
│   └── bc_handler.py        # Handler broadcast (.bc, .addbl, .delbl, .listbl)
│
├── Procfile                 # Konfigurasi proses Railway/Heroku
├── railway.json             # Konfigurasi Railway
├── requirements.txt         # Dependency Python
└── runtime.txt              # Versi Python
```

---

## 🔄 Alur Kerja Bot

```
User chat bot Telegram
        │
        ▼
  python-telegram-bot
  (handlers/commands.py, handlers/callbacks.py)
        │
        ├─── Cek subscription ─── database.py
        │
        ├─── Setup session ──────► client_manager.py
        │                               │
        │                               ▼
        │                        Telethon Client
        │                        (satu per user)
        │
        └─── User pakai fitur ───► handlers/telethon_handlers.py
                                          │
                                          ├── .dl      → download view once
                                          ├── .copy    → download channel private
                                          ├── .story   → download story
                                          ├── .ping    → cek latensi
                                          └── .cancel  → stop task

                                   handlers/bc_handler.py
                                          │
                                          ├── .bc      → broadcast ke semua grup
                                          ├── .addbl   → blacklist grup
                                          ├── .delbl   → whitelist grup
                                          └── .listbl  → lihat blacklist
```

---

## 🗃️ Database

Menggunakan **PostgreSQL**. Tabel diinisialisasi otomatis saat bot pertama kali dijalankan.

| Tabel | Keterangan |
|-------|------------|
| `users` | Data user (user_id, username, full_name) |
| `sessions` | Session Telethon per-user (api_id, api_hash, string_session) |
| `subscriptions` | Status langganan VIP (plan, paid_at, expired_at, is_active) |
| `user_settings` | Pengaturan per-user (auto_dl_view_once) |
| `blacklist_channels` | Blacklist channel/grup untuk fitur `.copy` (admin only) |
| `bc_group_blacklist` | Blacklist grup broadcast per-user untuk fitur `.bc` |

---

## 🛠️ Tech Stack

| Komponen | Library / Platform |
|----------|-------------------|
| Bot Framework | [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v20+ |
| Userbot / Session | [Telethon](https://github.com/LonamiWebs/Telethon) |
| Database | PostgreSQL + [psycopg2](https://pypi.org/project/psycopg2/) |
| Deploy | [Railway](https://railway.app) |
| Runtime | Python 3.11+ |

---

## 👤 Admin Panel

Fitur khusus admin (hanya bisa diakses oleh `ADMIN_ID`):

| Fitur | Keterangan |
|-------|------------|
| 🎁 Gift VIP | Berikan akses VIP ke user tertentu dengan jumlah hari custom |
| 🚫 Revoke VIP | Cabut akses VIP user |
| 📦 Backup DB | Export database ke file `.sql` |
| ♻️ Restore DB | Import database dari file `.sql` |
| 🔒 Blacklist Channel | Blokir channel/grup tertentu dari fitur `.copy` |

---

## ⚠️ Catatan Penting

- **Session Telethon** disimpan terenkripsi di database. Jangan bocorkan `DATABASE_URL`.
- **Broadcast** menggunakan delay antar pesan untuk mencegah *FloodWait* dari Telegram. Jangan kurangi delay terlalu agresif.
- **`.copy`** hanya bisa digunakan jika user sudah join atau memiliki akses ke channel/grup tersebut.
- Bot ini **bukan untuk spam**. Gunakan fitur broadcast secara bertanggung jawab sesuai aturan Telegram.

---

<div align="center">
  <sub>Rams VIP Bot v0.4.1 — Built with ❤️ by <a href="https://github.com/gfrrmd">gfrrmd</a></sub>
</div>
