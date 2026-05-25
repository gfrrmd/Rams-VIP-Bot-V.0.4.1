from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID
from database import (
    get_subscription_info, get_auto_dl_view_once,
    set_auto_dl_view_once, get_user_session,
    blacklist_list, is_subscribed,
    bc_blacklist_get,
)
from client_manager import active_clients, stop_client_for_user
from keyboards import (
    main_keyboard, admin_keyboard, fitur_vip_keyboard,
    timer_keyboard, back_to_fitur_keyboard, blacklist_keyboard,
    beli_keyboard, broadcast_keyboard, bc_blacklist_keyboard,
)
from handlers.commands import waiting_gift, waiting_revoke, waiting_restore
from handlers.admin import _do_backup


# waiting sets untuk blacklist
waiting_bl_add    : set[int] = set()
waiting_bl_remove : set[int] = set()


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = query.from_user.id
    data = query.data

    # ── MAIN MENU ────────────────────────────────────────────────
    if data == "menu_back":
        await query.edit_message_text(
            "🏠 *Menu Utama*",
            reply_markup=main_keyboard(uid),
            parse_mode="Markdown",
        )
        return

    if data == "menu_setup":
        has_session = bool(get_user_session(uid))
        if has_session:
            client = active_clients.get(uid)
            status = "🟢 Aktif" if client and client.is_connected() else "🔴 Tidak terhubung"
            await query.edit_message_text(
                f"⚙️ *Session kamu sudah terpasang*\nStatus: {status}\n\n"
                "Kirim /setup untuk setup ulang.",
                parse_mode="Markdown",
            )
        elif not is_subscribed(uid):
            await query.edit_message_text(
                "❌ Kamu belum berlangganan VIP.\nHubungi admin untuk berlangganan.",
                parse_mode="Markdown",
                reply_markup=main_keyboard(uid),
            )
        else:
            await query.edit_message_text(
                "⚙️ *Setup Session Telegram*\n\n"
                "Proses ini menghubungkan akun Telegram kamu ke bot.\n\n"
                "━━━━━━━━━━━━━━━━━\n"
                "📌 *Cara mendapatkan API ID & API Hash:*\n"
                "1. Buka https://my.telegram.org di browser\n"
                "2. Login dengan nomor HP Telegram kamu\n"
                "3. Masukkan kode OTP yang dikirim ke Telegram\n"
                "4. Klik *API development tools*\n"
                "5. Isi *App title* dan *Short Name* bebas, Description kosongkan. Klik Create application\n"
                "6. Salin dan simpan *APP_ID* dan *API_HASH*\n\n"
                "━━━━━━━━━━━━━━━━━\n"
                "Setelah siap, ketik /setup untuk memulai proses setup.",
                parse_mode="Markdown",
            )
        return

    if data == "menu_subscription":
        row = get_subscription_info(uid)
        if not row:
            text = "❌ Kamu belum memiliki langganan VIP."
        else:
            paid_at, expired_at, is_active = row
            from datetime import datetime
            try:
                exp = datetime.fromisoformat(expired_at)
                sisa = (exp - datetime.now()).days
                status = "✅ Aktif" if is_active and sisa >= 0 else "❌ Expired"
                text = (
                    f"💎 *Status Langganan VIP*\n\n"
                    f"📅 Aktif sejak: {paid_at[:10] if paid_at else '—'}\n"
                    f"⏳ Berlaku hingga: {expired_at[:10]}\n"
                    f"🧉 Sisa: {max(sisa, 0)} hari\n"
                    f"Status: {status}"
                )
            except Exception:
                text = "⚠️ Data langganan tidak valid."
        await query.edit_message_text(text, parse_mode="Markdown",
                                       reply_markup=main_keyboard(uid))
        return

    if data == "menu_fitur":
        await query.edit_message_text(
            "✨ *Fitur VIP*\n\nPilih fitur di bawah:",
            reply_markup=fitur_vip_keyboard(),
            parse_mode="Markdown",
        )
        return

    if data == "menu_beli":
        await query.edit_message_text(
            "💎 *Beli VIP*\n\n"
            "Klik tombol di bawah untuk menghubungi admin dan mendapatkan akses VIP.",
            parse_mode="Markdown",
            reply_markup=beli_keyboard(),
        )
        return

    if data == "menu_admin" and uid == ADMIN_ID:
        await query.edit_message_text(
            "👤 *Menu Admin*",
            reply_markup=admin_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── FITUR VIP ────────────────────────────────────────────────
    if data == "fitur_timer":
        await query.edit_message_text(
            "⏱️ *Download Media Timer & View Once*\n\n"
            "Simpan foto/video timer yang hanya bisa dilihat sekali (view once).\n\n"
            "📲 *Cara pakai - Manual:*\n"
            "Balas pesan view once/timer dengan perintah:\n"
            "`.dl`\n\n"
            "🤖 *Cara pakai - Auto DL (Otomatis):*\n"
            "Aktifkan Auto DL agar bot otomatis menyimpan setiap media view once yang masuk ke chat kamu.\n\n"
            "Gunakan tombol di bawah untuk ON/OFF.",
            reply_markup=timer_keyboard(uid),
            parse_mode="Markdown",
        )
        return

    if data == "vip_toggle_auto_dl":
        current = get_auto_dl_view_once(uid)
        set_auto_dl_view_once(uid, not current)
        new_status = "ON ✅" if not current else "OFF ❌"
        await query.edit_message_text(
            f"⏱️ *Auto DL View Once*\n\nSekarang: {new_status}",
            reply_markup=timer_keyboard(uid),
            parse_mode="Markdown",
        )
        return

    if data == "fitur_copy":
        await query.edit_message_text(
            "📥 *Download dari Channel/Grup Private*\n\n"
            "Download pesan, foto, atau video dari channel/grup yang dibatasi (restricted/tidak bisa di-forward).\n\n"
            "📝 *Cara pakai:*\n"
            "Ketik dimanapun dengan command:\n"
            "`.copy (link postingan)`\n\n"
            "💡 *Contoh:*\n"
            "`.copy https://t.me/koleksijee/456`",
            reply_markup=back_to_fitur_keyboard(),
            parse_mode="Markdown",
        )
        return

    if data == "fitur_story":
        await query.edit_message_text(
            "🎥 *Download Story*\n\n"
            "Download story Telegram milik orang lain langsung dari link story-nya.\n\n"
            "📝 *Cara pakai:*\n"
            "Kirim link story yang ingin didownload:\n"
            "`.story (link story)`\n\n"
            "💡 *Contoh:*\n"
            "`.story https://t.me/username/s/7`",
            reply_markup=back_to_fitur_keyboard(),
            parse_mode="Markdown",
        )
        return

    if data == "fitur_ping":
        await query.edit_message_text(
            "🏓 *Ping*\n\n"
            "Cek apakah koneksi session Telethon kamu masih aktif dan berapa lama waktu responnya.\n\n"
            "📝 *Cara pakai:*\n"
            "Buka *Saved Messages* di Telegram kamu, lalu kirim:\n"
            "`.ping`\n\n"
            "💡 *Contoh hasil:*\n"
            "`🏓 Pong! 42ms`",
            reply_markup=back_to_fitur_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── FITUR BROADCAST ──────────────────────────────────────────
    if data == "fitur_broadcast":
        await query.edit_message_text(
            "📢 *Broadcast*\n\n"
            "Kirim pesan yang sama ke semua grup yang kamu join secara otomatis.\n\n"
            "📝 *Cara pakai:*\n"
            "Ketik command berikut dari chat manapun:\n"
            "`.bc (pesan kamu)`\n\n"
            "💡 *Contoh:*\n"
            "`.bc Hai, ada yang mau berteman?`\n\n"
            "🚫 *Batalkan broadcast:*\n"
            "`.cancel #task_id`",
            reply_markup=broadcast_keyboard(),
            parse_mode="Markdown",
        )
        return

    if data == "bc_blacklist_menu":
        rows = bc_blacklist_get(uid)
        if not rows:
            bl_text = "📋 Blacklist kamu kosong.\nSemua grup akan menerima broadcast."
        else:
            lines = [f"🚫 *{len(rows)} grup diblacklist:*\n"]
            for i, r in enumerate(rows, 1):
                name = r['group_name'] or '—'
                lines.append(f"{i}. *{name}*\n   `{r['group_id']}`")
            bl_text = "\n".join(lines)

        await query.edit_message_text(
            f"⛔ *Blacklist Broadcast*\n\n"
            
            "Untuk mengelola blacklist, gunakan command:\n\n"
            "`.addbl` :\n"
            "Tambah ke blacklist\n\n"
            "`.addbl (ID Grup)` :\n"
            "Tambah ke blacklist by ID\n\n"
            "`.delbl` :\n"
            "Hapus blacklist\n\n"
            "`.delbl (ID Grup)` :\n"
            "Hapus blacklist by ID\n\n"
            "`.listbl` :\n"
            "Lihat list blacklist lengkap",
            reply_markup=bc_blacklist_keyboard(),
            parse_mode="Markdown",
        )
        return

    if data == "bc_bl_list":
        rows = bc_blacklist_get(uid)
        if not rows:
            text = "📝 *Blacklist BC Kosong*\n\nSemua grup akan menerima broadcast kamu."
        else:
            lines = [f"🚫 *Blacklist BC* ({len(rows)} grup)\n"]
            for i, r in enumerate(rows, 1):
                name = r['group_name'] or '—'
                date = r['added_at'][:10] if r.get('added_at') else ''
                lines.append(f"{i}. *{name}*\n   `{r['group_id']}` _({date})_")
            text = "\n".join(lines)
        await query.edit_message_text(
            text,
            reply_markup=bc_blacklist_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── ADMIN ────────────────────────────────────────────────────
    if uid != ADMIN_ID:
        return

    if data == "admin_backup":
        await query.edit_message_text("⏳ Sedang membuat backup...")
        try:
            sql_bytes = await _do_backup(context)
            from datetime import datetime
            fname = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
            await context.bot.send_document(
                chat_id=uid,
                document=sql_bytes,
                filename=fname,
                caption="✅ Backup database berhasil!",
            )
            await query.edit_message_text("✅ Backup selesai!", reply_markup=admin_keyboard())
        except Exception as e:
            await query.edit_message_text(f"❌ Backup gagal: {e}", reply_markup=admin_keyboard())
        return

    if data == "admin_restore":
        waiting_restore.add(uid)
        await query.edit_message_text(
            "♻️ *Restore Database*\n\n"
            "Kirim file `.sql` backup kamu sekarang.\n"
            "Atau ketik /cancel untuk batal.",
            parse_mode="Markdown",
        )
        return

    if data == "admin_gift":
        waiting_gift.add(uid)
        await query.edit_message_text(
            "🎁 *Gift VIP*\n\n"
            "Kirim: `<user_id atau @username> <jumlah_hari>`\n"
            "Contoh: `123456789 30`\n\n"
            "Atau ketik /cancel untuk batal.",
            parse_mode="Markdown",
        )
        return

    if data == "admin_revoke":
        waiting_revoke.add(uid)
        await query.edit_message_text(
            "🚫 *Revoke VIP*\n\n"
            "Kirim user ID atau @username yang ingin dicabut VIP-nya.\n"
            "Atau ketik /cancel untuk batal.",
            parse_mode="Markdown",
        )
        return

    # ── BLACKLIST MENU ───────────────────────────────────────────
    if data == "admin_blacklist":
        await query.edit_message_text(
            "🔒 *Blacklist Channel*\n\n"
            "Kelola daftar channel/grup yang diblokir dari .copy",
            reply_markup=blacklist_keyboard(),
            parse_mode="Markdown",
        )
        return

    if data == "bl_add":
        waiting_bl_add.add(uid)
        await query.edit_message_text(
            "➕ *Tambah ke Blacklist*\n\n"
            "Kirim username atau ID channel.\n"
            "Format: `@username` atau `-100xxxxxxxxxx`\n"
            "Bisa tambah catatan: `@username alasan`\n\n"
            "Ketik /cancel untuk batal.",
            parse_mode="Markdown",
        )
        return

    if data == "bl_remove":
        waiting_bl_remove.add(uid)
        await query.edit_message_text(
            "➖ *Hapus dari Blacklist*\n\n"
            "Kirim username atau ID channel yang ingin dihapus.\n"
            "Ketik /cancel untuk batal.",
            parse_mode="Markdown",
        )
        return

    if data == "bl_list":
        rows = blacklist_list()
        if not rows:
            text = "🔒 *Blacklist Channel*\n\nDaftar kosong."
        else:
            lines = ["🔒 *Blacklist Channel*\n"]
            for i, r in enumerate(rows, 1):
                note = f" — {r['note']}" if r.get("note") else ""
                date = r.get("added_at", "")[:10]
                lines.append(f"{i}. `{r['identifier']}`{note} _(ditambah {date})_")
            text = "\n".join(lines)
        await query.edit_message_text(
            text,
            reply_markup=blacklist_keyboard(),
            parse_mode="Markdown",
        )
        return
