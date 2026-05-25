import asyncio
import time

from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ConversationHandler,
)

from config import BOT_TOKEN
from database import init_db, get_user_session, is_subscribed
from client_manager import active_clients, dl_locks, _start_time, build_client
from handlers.telethon_handlers import register_handlers
from handlers.bc_handler import register_bc_handler
from handlers.commands import (
    cmd_start, cmd_cancel, cmd_gift, cmd_revoke, cmd_setup,
    setup_api_id, setup_api_hash, setup_phone, setup_code, setup_password,
    API_ID_STEP, API_HASH_STEP, PHONE_STEP, CODE_STEP, PASSWORD_STEP,
)
from handlers.callbacks import callback_handler
from handlers.admin import admin_message_handler


# ── POST INIT ─────────────────────────────────────────────────────
async def post_init(app):
    try:
        init_db()
        print("✅ Database siap.")
    except Exception as e:
        print(f"❌ Gagal init database: {e}")
        return
    try:
        from database import get_conn
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("SELECT user_id, api_id, api_hash, string_session FROM sessions")
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        print(f"❌ Gagal load sessions: {e}")
        return
    if not rows:
        print("ℹ️ Tidak ada session tersimpan.")
        return
    print(f"🔄 Memuat {len(rows)} session tersimpan...")
    for row in rows:
        user_id = row[0]
        if not is_subscribed(user_id):
            print(f"⏭️ Skip session user {user_id} (VIP tidak aktif)")
            continue
        try:
            client = build_client(row[1], row[2], row[3])
            if user_id not in dl_locks:
                dl_locks[user_id] = asyncio.Lock()
            await client.start()
            _start_time[user_id] = time.monotonic()
            register_handlers(client, user_id)
            register_bc_handler(client, user_id)
            active_clients[user_id] = client
            asyncio.ensure_future(client.run_until_disconnected())
            print(f"✅ Session user {user_id} berhasil dimuat.")
        except Exception as e:
            print(f"⚠️ Gagal load session user {user_id}: {e}")
    print("✅ Semua session berhasil dimuat!")


# ── MAIN ──────────────────────────────────────────────────────────
def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    setup_conv = ConversationHandler(
        entry_points=[CommandHandler("setup", cmd_setup)],
        states={
            API_ID_STEP:   [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_api_id)],
            API_HASH_STEP: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_api_hash)],
            PHONE_STEP:    [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_phone)],
            CODE_STEP:     [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_code)],
            PASSWORD_STEP: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_password)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("gift",   cmd_gift))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(setup_conv)
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ALL, admin_message_handler), group=2)

    print("🤖 Bot berjalan...")
    app.run_polling()


if __name__ == "__main__":
    main()
