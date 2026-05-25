import io
import re
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID
from database import (
    upsert_user, is_subscribed, activate_subscription, revoke_subscription,
    get_user_by_username, blacklist_add, blacklist_remove,
)
from client_manager import stop_client_for_user
from keyboards import admin_keyboard, blacklist_keyboard
from handlers.commands import waiting_restore, waiting_gift, waiting_revoke

# import waiting sets blacklist dari callbacks (lazy import untuk hindari circular)
def _get_bl_sets():
    from handlers.callbacks import waiting_bl_add, waiting_bl_remove
    return waiting_bl_add, waiting_bl_remove


def _find_subscribed_user(target_str: str):
    clean = target_str.lstrip("@")
    if clean.isdigit():
        return int(clean)
    return get_user_by_username(clean)


async def _do_gift(target_str: str, days: int, context) -> tuple:
    clean = target_str.lstrip("@")
    if clean.isdigit():
        target_id = int(clean)
    else:
        target_id = get_user_by_username(clean)
        if target_id is None:
            return False, (
                f"❌ Username @{clean} tidak ditemukan di database.\n\n"
                f"💡 Gunakan user ID (angka) agar bisa gift tanpa user perlu klik /start dulu.\n"
                "User ID bisa didapat dari @userinfobot atau forward pesan user ke @getidsbot."
            )
    upsert_user(target_id, None, None)
    expired = activate_subscription(target_id, days=days)

    notif_sent = False
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"🎁 Selamat! VIP kamu telah diaktifkan!\n\n"
                f"📅 Aktif hingga: {expired.strftime('%d %b %Y')}\n"
                f"⏳ Durasi: {days} hari\n\n"
                f"Ketik /start untuk melihat status VIP kamu."
            )
        )
        notif_sent = True
    except Exception:
        pass

    notif_info = "" if notif_sent else "\n⚠️ Notifikasi ke user gagal dikirim (user belum pernah start bot)."
    return True, (
        f"🎁 VIP berhasil diberikan ke {target_id} selama {days} hari\n"
        f"Aktif hingga: {expired.strftime('%d %b %Y')}"
        f"{notif_info}"
    )


async def _do_revoke(target_str: str, context) -> tuple:
    target_id = _find_subscribed_user(target_str)
    if target_id is None:
        return False, (
            f"❌ User {target_str} tidak ditemukan di database.\n\n"
            "Gunakan user ID (angka) jika username tidak terdaftar."
        )
    if not is_subscribed(target_id):
        return False, (
            f"⚠️ User {target_id} tidak memiliki langganan VIP aktif.\n\n"
            "Mungkin VIP sudah pernah dicabut sebelumnya."
        )
    revoke_subscription(target_id)
    await stop_client_for_user(target_id)

    notif_sent = False
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "🚫 VIP kamu telah dicabut oleh admin.\n\n"
                "Fitur .dl dan .copy tidak lagi bisa digunakan.\n"
                "Hubungi admin jika ada pertanyaan."
            )
        )
        notif_sent = True
    except Exception:
        pass
    notif_info = "" if notif_sent else "\n⚠️ Notifikasi ke user gagal dikirim."
    return True, f"✅ VIP user {target_id} berhasil dicabut. Client langsung dihentikan.{notif_info}"


async def _do_backup(context) -> bytes:
    """
    Backup semua tabel PostgreSQL ke format SQL dump.
    INSERT menggunakan ON CONFLICT DO NOTHING agar restore aman dari duplicate key.
    """
    from database import get_conn
    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    tables = [row[0] for row in cur.fetchall()]

    lines = []
    for table in tables:
        cur.execute("""
            SELECT column_name, data_type, character_maximum_length,
                   is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name   = %s
            ORDER BY ordinal_position
        """, (table,))
        cols_info = cur.fetchall()

        col_defs = []
        for col_name, data_type, char_max_len, is_nullable, col_default in cols_info:
            if data_type in ("character varying", "varchar"):
                type_str = f"VARCHAR({char_max_len})" if char_max_len else "TEXT"
            elif data_type == "character":
                type_str = f"CHAR({char_max_len})" if char_max_len else "CHAR"
            else:
                type_str = data_type.upper()
            nullable = "" if is_nullable == "YES" else " NOT NULL"
            default  = f" DEFAULT {col_default}" if col_default else ""
            col_defs.append(f"    {col_name} {type_str}{nullable}{default}")

        lines.append(f"-- Table: {table}")
        lines.append(f"CREATE TABLE IF NOT EXISTS {table} (")
        lines.append(",\n".join(col_defs))
        lines.append(");")
        lines.append("")

        cur.execute(f'SELECT * FROM "{table}"')
        rows      = cur.fetchall()
        col_names = [desc[0] for desc in cur.description]

        for row in rows:
            vals = ", ".join(
                "'" + str(v).replace("'", "''") + "'" if v is not None else "NULL"
                for v in row
            )
            lines.append(
                f"INSERT INTO {table} ({', '.join(col_names)}) VALUES ({vals}) ON CONFLICT DO NOTHING;"
            )
        lines.append("")

    conn.close()
    return "\n".join(lines).encode("utf-8")


def _split_sql_statements(sql: str) -> list[str]:
    stmts   = []
    current = []
    depth   = 0

    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        depth += stripped.count("(") - stripped.count(")")
        current.append(line)
        if stripped.endswith(";") and depth <= 0:
            stmt = "\n".join(current).strip()
            if stmt:
                stmts.append(stmt)
            current = []
            depth   = 0

    if current:
        stmt = "\n".join(current).strip().rstrip(";")
        if stmt:
            stmts.append(stmt)
    return stmts


# ── ADMIN MESSAGE HANDLER (group=2) ──────────────────────────────
async def admin_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        return

    waiting_bl_add, waiting_bl_remove = _get_bl_sets()

    in_any = (
        uid in waiting_gift or uid in waiting_revoke
        or uid in waiting_restore
        or uid in waiting_bl_add or uid in waiting_bl_remove
    )
    if not in_any:
        return

    # ── Restore ──────────────────────────────────────────────────
    if uid in waiting_restore:
        waiting_restore.discard(uid)
        if not update.message.document:
            await update.message.reply_text(
                "❌ Kirim file .sql yang valid, atau ketik /cancel untuk batal."
            )
            waiting_restore.add(uid)
            return
        file = await context.bot.get_file(update.message.document.file_id)
        buf  = io.BytesIO()
        await file.download_to_memory(buf)
        sql  = buf.getvalue().decode()
        try:
            from database import get_conn
            conn  = get_conn()
            cur   = conn.cursor()
            stmts = _split_sql_statements(sql)
            for stmt in stmts:
                cur.execute(stmt)
            conn.commit()
            conn.close()
            await update.message.reply_text(
                f"✅ Restore berhasil! ({len(stmts)} statement dijalankan)",
                reply_markup=admin_keyboard()
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Restore gagal: {e}", reply_markup=admin_keyboard())
        return

    # ── Gift ─────────────────────────────────────────────────────
    if uid in waiting_gift:
        waiting_gift.discard(uid)
        text  = update.message.text.strip() if update.message.text else ""
        parts = text.split()
        if not parts:
            await update.message.reply_text("❌ Input tidak valid. Ketik /cancel untuk batal.")
            waiting_gift.add(uid)
            return
        target_str = parts[0]
        days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 30
        ok, msg = await _do_gift(target_str, days, context)
        await update.message.reply_text(msg, reply_markup=admin_keyboard())
        return

    # ── Revoke ───────────────────────────────────────────────────
    if uid in waiting_revoke:
        waiting_revoke.discard(uid)
        text = update.message.text.strip() if update.message.text else ""
        if not text:
            await update.message.reply_text("❌ Input tidak valid. Ketik /cancel untuk batal.")
            waiting_revoke.add(uid)
            return
        ok, msg = await _do_revoke(text, context)
        await update.message.reply_text(msg, reply_markup=admin_keyboard())
        return

    # ── Blacklist Add ────────────────────────────────────────────
    if uid in waiting_bl_add:
        waiting_bl_add.discard(uid)
        text  = update.message.text.strip() if update.message.text else ""
        parts = text.split(maxsplit=1)
        if not parts:
            await update.message.reply_text("❌ Input tidak valid. Ketik /cancel untuk batal.")
            waiting_bl_add.add(uid)
            return
        identifier = parts[0].lstrip("@")
        note       = parts[1] if len(parts) > 1 else ""
        ok = blacklist_add(identifier, note)
        if ok:
            await update.message.reply_text(
                f"✅ `{identifier}` berhasil ditambahkan ke blacklist.",
                parse_mode="Markdown",
                reply_markup=blacklist_keyboard(),
            )
        else:
            await update.message.reply_text(
                f"⚠️ `{identifier}` sudah ada di blacklist.",
                parse_mode="Markdown",
                reply_markup=blacklist_keyboard(),
            )
        return

    # ── Blacklist Remove ─────────────────────────────────────────
    if uid in waiting_bl_remove:
        waiting_bl_remove.discard(uid)
        text = update.message.text.strip() if update.message.text else ""
        if not text:
            await update.message.reply_text("❌ Input tidak valid. Ketik /cancel untuk batal.")
            waiting_bl_remove.add(uid)
            return
        identifier = text.lstrip("@")
        ok = blacklist_remove(identifier)
        if ok:
            await update.message.reply_text(
                f"✅ `{identifier}` berhasil dihapus dari blacklist.",
                parse_mode="Markdown",
                reply_markup=blacklist_keyboard(),
            )
        else:
            await update.message.reply_text(
                f"❌ `{identifier}` tidak ditemukan di blacklist.",
                parse_mode="Markdown",
                reply_markup=blacklist_keyboard(),
            )
        return
