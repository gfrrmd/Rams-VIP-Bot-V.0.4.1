from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import ADMIN_ID
from database import get_auto_dl_view_once


def main_keyboard(uid):
    rows = [
        [
            InlineKeyboardButton("⚙️ Setup Session",    callback_data="menu_setup"),
            InlineKeyboardButton("⌛️ Status Langganan", callback_data="menu_subscription"),
        ],
        [
            InlineKeyboardButton("✨ Fitur VIP", callback_data="menu_fitur"),
            InlineKeyboardButton("💎 Beli VIP",  callback_data="menu_beli"),
        ],
    ]
    if uid == ADMIN_ID:
        rows.append([InlineKeyboardButton("👤 Menu Admin", callback_data="menu_admin")])
    return InlineKeyboardMarkup(rows)


def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📦 Backup DB",   callback_data="admin_backup"),
            InlineKeyboardButton("♻️ Restore DB",  callback_data="admin_restore"),
        ],
        [
            InlineKeyboardButton("🎁 Gift VIP",    callback_data="admin_gift"),
            InlineKeyboardButton("🚫 Revoke VIP",  callback_data="admin_revoke"),
        ],
        [
            InlineKeyboardButton("🔒 Blacklist",   callback_data="admin_blacklist"),
        ],
        [InlineKeyboardButton("🔙 Kembali", callback_data="menu_back")],
    ])


def blacklist_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Tambah",    callback_data="bl_add"),
            InlineKeyboardButton("➖ Hapus",     callback_data="bl_remove"),
        ],
        [
            InlineKeyboardButton("📋 Lihat List", callback_data="bl_list"),
        ],
        [InlineKeyboardButton("🔙 Kembali ke Admin", callback_data="menu_admin")],
    ])


def fitur_vip_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏱️ Media Timer",  callback_data="fitur_timer"),
            InlineKeyboardButton("📣 Channel/Grup", callback_data="fitur_copy"),
        ],
        [
            InlineKeyboardButton("🎥 Story",        callback_data="fitur_story"),
            InlineKeyboardButton("📢 Broadcast",    callback_data="fitur_broadcast"),
        ],
        [
            InlineKeyboardButton("🏓 Ping",         callback_data="fitur_ping"),
            InlineKeyboardButton("💎 Beli VIP",     callback_data="menu_beli"),
        ],
        [
            InlineKeyboardButton("🔙 Kembali",      callback_data="menu_back"),
        ],
    ])


def broadcast_keyboard():
    """Sub-menu fitur Broadcast."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⛔ Blacklist Grup", callback_data="bc_blacklist_menu"),
        ],
        [
            InlineKeyboardButton("🔙 Kembali ke Fitur VIP", callback_data="menu_fitur"),
        ],
    ])


def bc_blacklist_keyboard():
    """Sub-menu kelola blacklist BC."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 List Blacklist", callback_data="bc_bl_list"),
        ],
        [
            InlineKeyboardButton("🔙 Kembali ke Broadcast", callback_data="fitur_broadcast"),
        ],
    ])


def beli_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💬 Hubungi Admin", url=f"tg://user?id={ADMIN_ID}"),
        ],
        [
            InlineKeyboardButton("🔙 Kembali", callback_data="menu_back"),
        ],
    ])


def timer_keyboard(uid):
    auto_on = get_auto_dl_view_once(uid)
    label   = f"⏱️ Auto DL: {'ON ✅' if auto_on else 'OFF ❌'}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data="vip_toggle_auto_dl")],
        [InlineKeyboardButton("🔙 Kembali ke Fitur VIP", callback_data="menu_fitur")],
    ])


def back_to_fitur_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Kembali ke Fitur VIP", callback_data="menu_fitur")]
    ])
