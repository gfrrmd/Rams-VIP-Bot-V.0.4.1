import io
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

from config import ADMIN_ID
from database import (
    upsert_user, is_subscribed, get_subscription_info,
    save_user_session, get_user_session,
)
from client_manager import active_clients, build_client, stop_client_for_user
from keyboards import main_keyboard, admin_keyboard

# ── CONVERSATION STATES ───────────────────────────────────────────
API_ID_STEP, API_HASH_STEP, PHONE_STEP, CODE_STEP, PASSWORD_STEP = range(5)

# ── GLOBAL STATE ─────────────────────────────────────────────────
waiting_restore: set = set()
waiting_gift:    set = set()
waiting_revoke:  set = set()
temp_store:      dict = {}


def _clear_user_state(uid: int):
    temp_store.pop(uid, None)
    waiting_restore.discard(uid)
    waiting_gift.discard(uid)
    waiting_revoke.discard(uid)


# ── /start ────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    user = update.effective_user
    _clear_user_state(uid)
    upsert_user(uid, user.username, user.full_name)
    session = get_user_session(uid)
    client  = active_clients.get(uid)
    if session and client and client.is_connected():
        status = "✅ *Aktif*"
    elif session:
        status = "⚠️ *Session tersimpan, client belum terhubung*"
    else:
        status = "❌ *Belum diatur*"
    if is_subscribed(uid):
        info       = get_subscription_info(uid)
        expired    = datetime.fromisoformat(info[1])
        sub_status = f"\n💳 Langganan: ✅ Aktif s/d *{expired.strftime('%d %b %Y')}*"
    else:
        sub_status = "\n💳 Langganan: ❌ Tidak aktif"
    await update.message.reply_text(
        f"👋 *Selamat datang di Rams VIP Bot!*\n\n"
        f"Status session: {status}{sub_status}\n\nPilih menu di bawah:",
        parse_mode="Markdown",
        reply_markup=main_keyboard(uid)
    )
    return ConversationHandler.END


# ── /cancel ───────────────────────────────────────────────────────
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    _clear_user_state(uid)
    await update.message.reply_text(
        "❌ Dibatalkan. Kembali ke menu utama.",
        reply_markup=main_keyboard(uid)
    )
    return ConversationHandler.END


# ── /gift ─────────────────────────────────────────────────────────
async def cmd_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        await update.message.reply_text("❌ Kamu tidak memiliki izin.")
        return
    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ Format: /gift <user_id atau @username> [hari]\nContoh: /gift 123456789 30"
        )
        return
    from handlers.admin import _do_gift
    target_str = args[0].strip()
    days = int(args[1]) if len(args) > 1 and args[1].isdigit() else 30
    ok, msg = await _do_gift(target_str, days, context)
    await update.message.reply_text(msg, reply_markup=admin_keyboard() if ok else None)


# ── /revoke ───────────────────────────────────────────────────────
async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        await update.message.reply_text("❌ Kamu tidak memiliki izin.")
        return
    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ Format: /revoke <user_id atau @username>\nContoh: /revoke 123456789"
        )
        return
    from handlers.admin import _do_revoke
    ok, msg = await _do_revoke(args[0].strip(), context)
    await update.message.reply_text(msg, reply_markup=admin_keyboard() if ok else None)


# ── /setup CONVERSATION ───────────────────────────────────────────
async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_subscribed(uid):
        await update.message.reply_text(
            "❌ Kamu belum berlangganan VIP.\nHubungi admin untuk berlangganan.",
            reply_markup=main_keyboard(uid)
        )
        return ConversationHandler.END
    temp_store.pop(uid, None)
    await update.message.reply_text(
        "🔧 *Setup Session Telegram*\n\n"
        "Proses ini menghubungkan akun Telegram kamu ke bot.\n"
        "Ketik /cancel kapan saja untuk membatalkan.\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "*Langkah 1 dari 5 - API ID*\n\n"
        "API ID adalah kode angka unik untuk aplikasi Telegram kamu.\n\n"
        "📌 Cara mendapatkan API ID:\n"
        "1. Buka https://my.telegram.org di browser\n"
        "2. Login dengan nomor HP Telegram kamu\n"
        "3. Masukkan kode OTP yang dikirim ke Telegram\n"
        "4. Klik API development tools\n"
        "5. Isi *App title* dan *Short Name* bebas, Description kosongkan. Klik Create application\n"
        "6. Salin dan simpan *APP_ID* dan *API_HASH*.\n\n"
        "Kirim angka dari *API_ID* tersebut di sini:",
        parse_mode="Markdown"
    )
    return API_ID_STEP


async def setup_api_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text(
            "❌ API ID harus berupa angka saja.\nContoh: 12345678\n\nCoba kirim ulang, atau /cancel untuk batal:"
        )
        return API_ID_STEP
    temp_store.setdefault(uid, {})["api_id"] = int(text)
    await update.message.reply_text(
        "✅ API ID tersimpan!\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "*Langkah 2 dari 5 - API Hash*\n\n"
        "API Hash adalah kode acak 32 karakter (campuran huruf dan angka).\n\n"
        "📌 Di halaman my.telegram.org, salin teks di kolom App api hash.\n"
        "Contoh: a1b2c3d4e5f6... (32 karakter)\n\n"
        "Kirim API Hash kamu, atau /cancel untuk batal:",
        parse_mode="Markdown"
    )
    return API_HASH_STEP


async def setup_api_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()
    if len(text) < 10:
        await update.message.reply_text(
            "❌ API Hash terlalu pendek. Harus 32 karakter.\n\nCoba kirim ulang, atau /cancel untuk batal:"
        )
        return API_HASH_STEP
    temp_store.setdefault(uid, {})["api_hash"] = text
    await update.message.reply_text(
        "✅ API Hash tersimpan!\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "*Langkah 3 dari 5 - Nomor HP*\n\n"
        "Masukkan nomor HP yang terdaftar di akun Telegram kamu.\n\n"
        "📌 Format: awali dengan kode negara, tanpa spasi.\n"
        "Contoh untuk Indonesia: +6281234567890\n\n"
        "Kirim nomor HP kamu, atau /cancel untuk batal:",
        parse_mode="Markdown"
    )
    return PHONE_STEP


async def setup_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    phone = update.message.text.strip()
    data  = temp_store.get(uid, {})
    client = build_client(data["api_id"], data["api_hash"])
    try:
        await client.connect()
        result = await client.send_code_request(phone)
        temp_store[uid]["phone"]      = phone
        temp_store[uid]["phone_hash"] = result.phone_code_hash
        temp_store[uid]["client"]     = client
        await update.message.reply_text(
            "📨 Kode OTP berhasil dikirim ke Telegram kamu!\n\n"
            "━━━━━━━━━━━━━━━━━\n"
            "*Langkah 4 dari 5 - Kode OTP*\n\n"
            "Buka aplikasi Telegram, cari pesan dari Telegram berisi 5 digit kode verifikasi.\n\n"
            "📌 Ketik kode dengan spasi di antara setiap angka.\n"
            "Contoh: jika kode 12345, kirim: 1 2 3 4 5\n\n"
            "Kirim kode OTP kamu, atau /cancel untuk batal:",
            parse_mode="Markdown"
        )
        return CODE_STEP
    except Exception as e:
        await client.disconnect()
        temp_store.pop(uid, None)
        await update.message.reply_text(
            f"❌ Gagal mengirim OTP: {e}\n\n"
            "Kemungkinan penyebab: nomor salah format, atau API ID/Hash salah.\n\n"
            "Silakan /setup ulang dari awal.",
            reply_markup=main_keyboard(uid)
        )
        return ConversationHandler.END


async def setup_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    code = update.message.text.strip().replace(" ", "")
    data = temp_store.get(uid, {})
    client = data.get("client")
    try:
        await client.sign_in(data["phone"], code, phone_code_hash=data["phone_hash"])
    except SessionPasswordNeededError:
        await update.message.reply_text(
            "🔐 *Akun ini mengaktifkan verifikasi 2 langkah (2FA)*\n\n"
            "━━━━━━━━━━━━━━━━━\n"
            "*Langkah 5 dari 5 - Password 2FA*\n\n"
            "Masukkan password 2FA Telegram kamu.\n\n"
            "📌 Password ini dibuat di:\n"
            "Telegram > Pengaturan > Privasi dan Keamanan > Verifikasi 2 Langkah\n\n"
            "Kirim password kamu, atau /cancel untuk batal:",
            parse_mode="Markdown"
        )
        return PASSWORD_STEP
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        await client.disconnect()
        temp_store.pop(uid, None)
        await update.message.reply_text(
            "❌ Kode OTP salah atau sudah kadaluarsa.\nSilakan /setup ulang untuk mendapatkan kode baru."
        )
        return ConversationHandler.END
    except Exception as e:
        await client.disconnect()
        temp_store.pop(uid, None)
        await update.message.reply_text(f"❌ Terjadi error: {e}\n\nSilakan /setup ulang.")
        return ConversationHandler.END
    return await _finish_setup(update, uid, data, client)


async def setup_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid      = update.effective_user.id
    password = update.message.text.strip()
    data     = temp_store.get(uid, {})
    client   = data.get("client")
    try:
        await client.sign_in(password=password)
    except Exception as e:
        await client.disconnect()
        temp_store.pop(uid, None)
        await update.message.reply_text(f"❌ Password 2FA salah: {e}\n\nSilakan /setup ulang.")
        return ConversationHandler.END
    return await _finish_setup(update, uid, data, client)


async def _finish_setup(update, uid, data, client):
    from client_manager import _start_time
    import asyncio, time
    from handlers.telethon_handlers import register_handlers

    string_session = client.session.save()
    save_user_session(uid, data["api_id"], data["api_hash"], string_session)

    # Start client & register handlers
    from client_manager import active_clients, dl_locks
    old = active_clients.get(uid)
    if old and old.is_connected():
        await old.disconnect()
    if uid not in dl_locks:
        dl_locks[uid] = asyncio.Lock()
    await client.start()
    _start_time[uid] = time.monotonic()
    register_handlers(client, uid)
    active_clients[uid] = client
    asyncio.ensure_future(client.run_until_disconnected())

    temp_store.pop(uid, None)
    await update.message.reply_text(
        "✅ *Setup berhasil! Session kamu sudah aktif.*\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "⚠️ *PENTING: Jangan logout dari sesi ini!*\n\n"
        "Bot bekerja menggunakan sesi login akun Telegram kamu yang sudah tersimpan. "
        "Jika kamu logout dari perangkat tempat sesi ini dibuat, "
        "maka fitur .dl dan .copy akan berhenti berfungsi dan kamu perlu /setup ulang.\n\n"
        "💡 Gunakan tombol *✨ Fitur VIP* di menu utama untuk panduan lengkap setiap fitur.",
        parse_mode="Markdown",
        reply_markup=main_keyboard(uid)
    )
    return ConversationHandler.END
