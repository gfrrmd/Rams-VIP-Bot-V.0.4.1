import re
import time
import asyncio
from datetime import timezone, timedelta

from config import RESTRICTED_CHANNELS
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeFilename

WIB = timezone(timedelta(hours=7))

# Lebar progress bar (jumlah karakter)
_BAR_WIDTH = 14


# ── TEXT HELPERS ──────────────────────────────────────────────────
def escape_md(text):
    if not text:
        return "Unknown"
    for ch in ["[", "]", "(", ")", "*", "_", "`"]:
        text = text.replace(ch, f"\\{ch}")
    return text


def _format_progress(current: int, total: int) -> str:
    if total <= 0:
        return "0.00%"
    return f"{(current / total) * 100:.2f}%"


def _build_bar(current: int, total: int) -> str:
    """
    Buat progress bar visual.
    Contoh: ████████░░░░░░  57.3%
    """
    pct   = (current / total) if total > 0 else 0.0
    filled = int(pct * _BAR_WIDTH)
    empty  = _BAR_WIDTH - filled
    bar    = "█" * filled + "░" * empty
    return f"{bar}  {pct * 100:.1f}%"


def _build_eta(current: int, total: int, elapsed: float) -> str:
    """
    Hitung ETA dan kecepatan transfer.
    Return string mis: '~12 dtk lagi  •  1.2 MB/s'
    Jika tidak bisa dihitung, return string kosong.
    """
    if current <= 0 or elapsed <= 0 or total <= 0:
        return ""
    speed = current / elapsed  # bytes per second
    remaining = total - current
    eta_sec   = remaining / speed if speed > 0 else 0

    # Format kecepatan
    if speed >= 1_048_576:
        speed_str = f"{speed / 1_048_576:.1f} MB/s"
    elif speed >= 1024:
        speed_str = f"{speed / 1024:.0f} KB/s"
    else:
        speed_str = f"{speed:.0f} B/s"

    # Format ETA
    if eta_sec < 60:
        eta_str = f"~{int(eta_sec)} dtk lagi"
    else:
        eta_str = f"~{int(eta_sec // 60)}m {int(eta_sec % 60)}s lagi"

    return f"{eta_str}  •  {speed_str}"


# ── MEDIA CHECKS ─────────────────────────────────────────────────
def is_no_forward(message):
    return bool(getattr(message, "noforwards", False))


def is_view_once(message):
    media = getattr(message, "media", None)
    if media is None:
        return False
    return bool(getattr(media, "ttl_seconds", None))


def is_sticker_doc(doc):
    if doc is None:
        return False
    mime = getattr(doc, "mime_type", "") or ""
    has_stickerset = any(
        getattr(attr, "stickerset", None) is not None
        for attr in getattr(doc, "attributes", [])
    )
    return has_stickerset or "sticker" in mime


def get_video_attributes(doc):
    if doc is None:
        return None
    for attr in getattr(doc, "attributes", []):
        if isinstance(attr, DocumentAttributeVideo):
            return attr
    return None


def get_file_name(doc):
    if doc is None:
        return None
    for attr in getattr(doc, "attributes", []):
        if isinstance(attr, DocumentAttributeFilename):
            return attr.file_name
    return None


# ── SOURCE TYPE DETECTOR ─────────────────────────────────────────
def _detect_source_type(sender) -> str:
    if sender is None:
        return "❓ Unknown"
    if getattr(sender, "bot", False):
        return "🤖 Bot"
    try:
        from telethon.tl.types import Channel, Chat
        if isinstance(sender, Channel):
            return "📣 Channel" if getattr(sender, "broadcast", False) else "👥 Grup"
        if isinstance(sender, Chat):
            return "👥 Grup"
    except Exception:
        pass
    return "👤 Private Chat"


# ── CAPTION BUILDER ───────────────────────────────────────────────
def _build_caption(
    sender,
    msg=None,
    source_override: str | None = None,
) -> str:
    if sender:
        first   = getattr(sender, "first_name", "") or ""
        last    = getattr(sender, "last_name",  "") or ""
        title   = getattr(sender, "title",      "") or ""
        display = escape_md((title or f"{first} {last}").strip() or "Unknown")
        sender_id    = sender.id
        mention      = f"[{display}](tg://user?id={sender_id})"
        username     = getattr(sender, "username", None)
        username_str = f"@{username}" if username else "—"
    else:
        mention      = "Unknown"
        sender_id    = "—"
        username_str = "—"

    date_str = "—"
    if msg is not None:
        date_obj = getattr(msg, "date", None)
        if date_obj:
            try:
                date_str = date_obj.astimezone(WIB).strftime("%d/%m/%y, %H:%M")
            except Exception:
                try:
                    date_str = date_obj.strftime("%d/%m/%y, %H:%M")
                except Exception:
                    pass

    source_str = source_override if source_override else _detect_source_type(sender)

    return (
        f"📥 **Dari:** {mention}\n"
        f"🔖 **Username:** {username_str}\n"
        f"🆔 **ID:** `{sender_id}`\n"
        f"📆 **Tanggal:** {date_str}\n"
        f"🗄️ **Sumber:** {source_str}"
    )


# ── CHANNEL RESTRICTION HELPERS ──────────────────────────────────
def _normalize_channel_id(raw: str) -> set:
    s = raw.strip().lstrip("@")
    if not s.lstrip("-").isdigit():
        return {s.lower()}
    bare = s.lstrip("-")
    if bare.startswith("100") and len(bare) >= 12:
        bare = bare[3:]
    return {
        bare,
        f"-100{bare}",
        f"100{bare}",
    }


def is_channel_restricted(channel_identifier) -> bool:
    """Cek config statis LALU tabel blacklist di database."""
    sid = str(channel_identifier)

    # 1. Cek config statis (RESTRICTED_CHANNELS)
    if RESTRICTED_CHANNELS:
        input_variants = _normalize_channel_id(sid)
        for restricted in RESTRICTED_CHANNELS:
            if input_variants & _normalize_channel_id(str(restricted)):
                return True

    # 2. Cek tabel blacklist_channels di database
    try:
        from database import is_channel_blacklisted
        if is_channel_blacklisted(sid):
            return True
    except Exception:
        pass

    return False


# ── DEDUP HELPERS ─────────────────────────────────────────────────
dl_seen: dict[int, set] = {}


def _dl_dedup_check(user_id: int, event_id: int) -> bool:
    seen = dl_seen.setdefault(user_id, set())
    if event_id in seen:
        return True
    seen.add(event_id)
    if len(seen) > 50:
        to_remove = list(seen)[:25]
        for x in to_remove:
            seen.discard(x)
    return False


# ── PROGRESS BAR + ETA BUILDER ────────────────────────────────────
def _build_progress_text(
    label: str,
    current: int,
    total: int,
    start_ts: float,
    task_id: str | None = None,
) -> str:
    """
    Buat teks progress lengkap:
      ⏳ Mendownload...
      ████████░░░░░░  57.3%
      ~12 dtk lagi  •  1.2 MB/s

      ⛔ Ketik `.cancel 94821` untuk membatalkan
    """
    bar     = _build_bar(current, total)
    elapsed = time.monotonic() - start_ts
    eta     = _build_eta(current, total, elapsed)

    lines = [f"{label}...", bar]
    if eta:
        lines.append(eta)
    if task_id:
        lines.append(f"\n⛔ Ketik `.cancel {task_id}` untuk membatalkan")
    return "\n".join(lines)


# ── DOWNLOAD WITH PROGRESS ────────────────────────────────────────
async def download_bytes_with_progress(
    client,
    media,
    status_msg,
    task_id: str,
    start_text: str | None = None,
):
    label      = start_text or "⏳ Mendownload"
    start_ts   = time.monotonic()
    loop       = asyncio.get_running_loop()
    state      = {"last_ts": 0.0, "last_pct": -1.0}

    try:
        await status_msg.edit(
            _build_progress_text(label, 0, 1, start_ts, task_id)
        )
    except Exception:
        pass

    async def _dl_progress(current, total):
        now = loop.time()
        pct = (current / total * 100) if total else 0.0
        if (now - state["last_ts"] < 1.0) and (pct - state["last_pct"] < 1.5):
            return
        state["last_ts"]  = now
        state["last_pct"] = pct
        try:
            await status_msg.edit(
                _build_progress_text(label, current, total, start_ts, task_id)
            )
        except Exception:
            pass

    data = await client.download_media(media, bytes, progress_callback=_dl_progress)

    # Transisi ke fase upload
    try:
        await status_msg.edit(
            _build_progress_text("☁️ Mengupload", 0, 1, time.monotonic(), task_id)
        )
    except Exception:
        pass

    return data


# ── UPLOAD PROGRESS CALLBACK ──────────────────────────────────────
def make_upload_progress(status_msg, task_id: str):
    """
    Kembalikan async callback untuk progress_callback= pada client.send_file.
    Menampilkan progress bar + ETA fase upload.
    """
    loop     = asyncio.get_event_loop()
    state    = {"last_ts": 0.0, "last_pct": -1.0}
    start_ts = time.monotonic()

    async def _up_progress(current, total):
        now = loop.time()
        pct = (current / total * 100) if total else 0.0
        if (now - state["last_ts"] < 1.0) and (pct - state["last_pct"] < 1.5):
            return
        state["last_ts"]  = now
        state["last_pct"] = pct
        try:
            await status_msg.edit(
                _build_progress_text("☁️ Mengupload", current, total, start_ts, task_id)
            )
        except Exception:
            pass

    return _up_progress


# ── MAKE PROGRESS CALLBACK (generic) ─────────────────────────────
def make_progress_callback(status_msg, label: str, task_id: str | None = None):
    loop     = asyncio.get_event_loop()
    state    = {"last_ts": 0.0, "last_pct": -1.0}
    start_ts = time.monotonic()

    async def _cb(current, total):
        now = loop.time()
        pct = (current / total * 100) if total else 0.0
        if (now - state["last_ts"] < 1.0) and (pct - state["last_pct"] < 1.5):
            return
        state["last_ts"]  = now
        state["last_pct"] = pct
        try:
            await status_msg.edit(
                _build_progress_text(label, current, total, start_ts, task_id)
            )
        except Exception:
            pass

    return _cb
