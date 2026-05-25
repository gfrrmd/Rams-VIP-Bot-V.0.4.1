import io
import time
import asyncio

from telethon import events
from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument,
    DocumentAttributeVideo, InputPeerChannel,
    Channel, Chat,
)

from database import is_subscribed, get_auto_dl_view_once
from client_manager import active_clients, dl_locks, _start_time, stop_client_for_user
from utils import (
    _dl_dedup_check, _build_caption,
    download_bytes_with_progress, make_upload_progress,
    is_no_forward, is_view_once, is_sticker_doc,
    get_video_attributes, get_file_name, is_channel_restricted,
    escape_md,
)

import re
from datetime import timezone, timedelta

TG_LINK_RE = re.compile(
    r"(?:https?://)?t\.me/"
    r"(?:c/(?P<channel_id>\d+)/(?P<msg_id2>\d+)|"
    r"(?P<username>[a-zA-Z0-9_]+)/(?P<msg_id>\d+))"
)
TG_STORY_RE = re.compile(
    r"(?:https?://)?t\.me/(?P<username>[a-zA-Z0-9_]+)/s/(?P<story_id>\d+)"
)

WIB = timezone(timedelta(hours=7))

# ── ACTIVE CANCEL TASKS ───────────────────────────────────────────
_active_tasks: dict[str, asyncio.Task] = {}


def _make_task_id(user_id: int) -> str:
    return str(int(time.time()))[-5:]


# ── SEND MEDIA HELPER ─────────────────────────────────────────────
async def _send_media_file(client, msg, media_bytes, status_msg, caption="", task_id=""):
    file_obj = io.BytesIO(media_bytes)
    up_cb    = make_upload_progress(status_msg, task_id)

    if isinstance(msg.media, MessageMediaPhoto):
        file_obj.name = "photo.jpg"
        await client.send_file(
            "me", file=file_obj, caption=caption, parse_mode="markdown",
            progress_callback=up_cb,
        )

    elif isinstance(msg.media, MessageMediaDocument):
        doc  = msg.media.document
        mime = getattr(doc, "mime_type", "") or ""

        if is_sticker_doc(doc):
            if "webp" in mime:        file_obj.name = "sticker.webp"
            elif "tgsticker" in mime: file_obj.name = "sticker.tgs"
            elif "video" in mime:     file_obj.name = "sticker.webm"
            else:                      file_obj.name = "sticker.webp"
            await client.send_file(
                "me", file=file_obj, force_document=False,
                progress_callback=up_cb,
            )

        elif "video" in mime or "mp4" in mime:
            video_attr = get_video_attributes(doc)
            fname      = get_file_name(doc) or "video.mp4"
            file_obj.name = fname
            send_attrs = []
            if video_attr:
                send_attrs = [DocumentAttributeVideo(
                    duration=video_attr.duration,
                    w=video_attr.w, h=video_attr.h,
                    supports_streaming=True, round_message=False,
                )]
            await client.send_file(
                "me", file=file_obj, caption=caption, parse_mode="markdown",
                attributes=send_attrs if send_attrs else None, allow_cache=False,
                progress_callback=up_cb,
            )

        elif mime in ("image/jpeg", "image/png", "image/webp"):
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(mime, ".jpg")
            file_obj.name = f"photo{ext}"
            await client.send_file(
                "me", file=file_obj, caption=caption, parse_mode="markdown",
                force_document=False, allow_cache=False,
                progress_callback=up_cb,
            )

        else:
            fname = get_file_name(doc) or "document"
            if "." not in fname:
                ext_map = {
                    "audio/mpeg": ".mp3", "audio/ogg": ".ogg",
                    "application/pdf": ".pdf", "video/webm": ".webm",
                    "image/gif": ".gif", "image/jpeg": ".jpg",
                    "image/png": ".png", "image/webp": ".webp",
                }
                fname += ext_map.get(mime, "")
            file_obj.name = fname
            await client.send_file(
                "me", file=file_obj, caption=caption, parse_mode="markdown",
                force_document=False, allow_cache=False,
                progress_callback=up_cb,
            )
    else:
        await client.send_file(
            "me", file=file_obj, caption=caption, parse_mode="markdown",
            progress_callback=up_cb,
        )

    try:
        await status_msg.delete()
    except Exception:
        pass


# ── STORY MEDIA SEND HELPER ───────────────────────────────────────
async def _send_story_file(client, story_media, media_bytes, status_msg, caption_text, task_id=""):
    file_obj = io.BytesIO(media_bytes)
    up_cb    = make_upload_progress(status_msg, task_id)

    if isinstance(story_media, MessageMediaPhoto):
        file_obj.name = "story_photo.jpg"
        await client.send_file(
            "me", file=file_obj, caption=caption_text, parse_mode="markdown",
            progress_callback=up_cb,
        )

    elif isinstance(story_media, MessageMediaDocument):
        doc        = story_media.document
        mime       = getattr(doc, "mime_type", "") or ""
        video_attr = get_video_attributes(doc)

        if "video" in mime or "mp4" in mime:
            fname = get_file_name(doc) or "story_video.mp4"
            file_obj.name = fname
            send_attrs = []
            if video_attr:
                send_attrs = [DocumentAttributeVideo(
                    duration=video_attr.duration,
                    w=video_attr.w, h=video_attr.h,
                    supports_streaming=True, round_message=False,
                )]
            await client.send_file(
                "me", file=file_obj, caption=caption_text, parse_mode="markdown",
                attributes=send_attrs if send_attrs else None, allow_cache=False,
                progress_callback=up_cb,
            )
        else:
            fname = get_file_name(doc) or "story_media"
            if "." not in fname:
                ext_map = {
                    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
                    "image/gif": ".gif", "video/webm": ".webm",
                }
                fname += ext_map.get(mime, "")
            file_obj.name = fname
            await client.send_file(
                "me", file=file_obj, caption=caption_text, parse_mode="markdown",
                force_document=False, allow_cache=False,
                progress_callback=up_cb,
            )
    else:
        await status_msg.edit("⚠️ Tipe media story ini tidak didukung.")
        return

    try:
        await status_msg.delete()
    except Exception:
        pass


# ── REGISTER HANDLERS ─────────────────────────────────────────────
def register_handlers(client, user_id: int):

    # ── .ping ─────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.ping$"))
    async def ping_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id)
            await event.client.send_message("me",
                "❌ Langganan VIP kamu sudah habis atau dicabut.\n"
                "Hubungi admin untuk memperpanjang."
            )
            return
        start   = time.monotonic()
        msg     = await event.edit("🏓 Pinging...")
        ping_ms = (time.monotonic() - start) * 1000
        uptime  = int(time.monotonic() - _start_time.get(user_id, time.monotonic()))
        h, rem  = divmod(uptime, 3600)
        m, s    = divmod(rem, 60)
        me      = await client.get_me()
        first   = getattr(me, "first_name", "") or ""
        last    = getattr(me, "last_name",  "") or ""
        owner   = (f"{first} {last}").strip() or "Unknown"
        uname   = f" (@{me.username})" if me.username else ""
        await msg.edit(
            f"🏓 **Ping:** `{ping_ms:.2f} ms`\n"
            f"⏰ **Uptime:** `{h}h:{m:02d}m:{s:02d}s`\n"
            f"⭐ **Owner:** [{owner}](tg://user?id={me.id}){uname}"
        )

    # ── .cancel <task_id> atau .cancel #<task_id> ─────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.cancel\s+#?(\S+)$"))
    async def cancel_handler(event):
        task_id = event.pattern_match.group(1).strip()
        task    = _active_tasks.get(task_id)
        await event.delete()
        if task and not task.done():
            task.cancel()
            _active_tasks.pop(task_id, None)
            await client.send_message("me", f"⛔ Task `#{task_id}` berhasil dibatalkan.")
        else:
            await client.send_message("me", f"⚠️ Task `#{task_id}` tidak ditemukan atau sudah selesai.")

    # ── .dl ───────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.dl$"))
    async def dl_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id)
            await event.client.send_message("me",
                "❌ Langganan VIP kamu sudah habis atau dicabut.\n"
                "Hubungi admin untuk memperpanjang."
            )
            return
        if _dl_dedup_check(user_id, event.id):
            return
        lock    = dl_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            task_id = _make_task_id(user_id)
            task    = asyncio.ensure_future(_process_dl(event, client, user_id, task_id))
            _active_tasks[task_id] = task
            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                _active_tasks.pop(task_id, None)

    # ── .copy ─────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.copy\s+(https?://t\.me/\S+)$"))
    async def copy_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id)
            await event.client.send_message("me",
                "❌ Langganan VIP kamu sudah habis atau dicabut.\n"
                "Hubungi admin untuk memperpanjang."
            )
            return
        await event.delete()

        url = event.pattern_match.group(1).strip()
        m   = TG_LINK_RE.match(url)
        if not m:
            await client.send_message("me", "❌ Link tidak valid. Gunakan format: .copy https://t.me/channel/123")
            return

        channel_id_part = m.group("channel_id")
        msg_id2_part    = m.group("msg_id2")
        username_part   = m.group("username")
        msg_id_part     = m.group("msg_id")

        check_id = channel_id_part if channel_id_part else username_part
        if is_channel_restricted(check_id):
            await client.send_message("me",
                "🚫 **Konten dari channel ini tidak dapat di-copy.**\n\n"
                "Channel ini termasuk dalam daftar yang dibatasi oleh admin."
            )
            return

        if channel_id_part and msg_id2_part:
            try:
                channel_entity = await client.get_entity(
                    InputPeerChannel(channel_id=int(channel_id_part), access_hash=0)
                )
            except Exception:
                try:
                    from telethon.tl.types import PeerChannel
                    channel_entity = await client.get_entity(PeerChannel(int(channel_id_part)))
                except Exception as e:
                    await client.send_message("me",
                        f"❌ Gagal mengakses channel {channel_id_part}.\n"
                        f"Pastikan akun kamu sudah bergabung ke channel tersebut.\nError: {e}"
                    )
                    return
            msg_id = int(msg_id2_part)
        elif username_part and msg_id_part:
            channel_entity = username_part
            msg_id = int(msg_id_part)
        else:
            await client.send_message("me", "❌ Format link tidak dikenali.")
            return

        status_msg = await client.send_message("me", "⏳ Sedang mengambil pesan...")
        try:
            fetched_msg = await client.get_messages(channel_entity, ids=msg_id)
        except Exception as e:
            await status_msg.edit(
                f"❌ Gagal mengambil pesan: {e}\n\n"
                "Pastikan akun kamu sudah bergabung ke channel tersebut."
            )
            return

        if fetched_msg is None:
            await status_msg.edit("❌ Pesan tidak ditemukan.")
            return

        if not fetched_msg.media:
            text_content = fetched_msg.text or fetched_msg.message or ""
            if text_content:
                await status_msg.edit(f"📋 Dari channel:\n\n{text_content}")
            else:
                await status_msg.edit("⚠️ Pesan kosong atau tidak ada konten.")
            return

        try:
            copy_sender = await client.get_entity(channel_entity)
        except Exception:
            copy_sender = None

        if channel_id_part:
            source_type = "📣 Channel" if (copy_sender and getattr(copy_sender, "broadcast", False)) else "👥 Grup"
        else:
            source_type = None

        if not is_no_forward(fetched_msg):
            try:
                await client.forward_messages("me", fetched_msg)
                await status_msg.delete()
                return
            except Exception:
                pass

        task_id = _make_task_id(user_id)
        task    = asyncio.ensure_future(
            _copy_download(client, fetched_msg, status_msg, task_id, copy_sender, source_type)
        )
        _active_tasks[task_id] = task
        try:
            await task
        except asyncio.CancelledError:
            try:
                await status_msg.edit(f"⛔ Unduhan `#{task_id}` dibatalkan.")
            except Exception:
                pass
        finally:
            _active_tasks.pop(task_id, None)

    # ── .story ────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.story\s+(https?://t\.me/\S+)$"))
    async def story_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id)
            await event.client.send_message("me",
                "❌ Langganan VIP kamu sudah habis atau dicabut.\n"
                "Hubungi admin untuk memperpanjang."
            )
            return
        await event.delete()

        url = event.pattern_match.group(1).strip()
        m   = TG_STORY_RE.match(url)
        if not m:
            await client.send_message("me",
                "❌ Link story tidak valid.\n"
                "Format yang didukung: `.story https://t.me/username/s/123`"
            )
            return

        username   = m.group("username")
        story_id   = int(m.group("story_id"))
        status_msg = await client.send_message("me", "⏳ Sedang mengambil story...")

        try:
            peer = await client.get_entity(username)
        except Exception as e:
            await status_msg.edit(
                f"❌ Gagal menemukan akun @{username}.\n"
                f"Pastikan username benar dan akun tidak private.\nError: {e}"
            )
            return

        story_media = None
        story_date  = None
        story_text  = None

        try:
            from telethon.tl.functions.stories import GetStoriesByIDRequest
            result  = await client(GetStoriesByIDRequest(peer=peer, id=[story_id]))
            stories = getattr(result, "stories", []) or []
            if stories:
                s           = stories[0]
                story_media = getattr(s, "media", None)
                story_date  = getattr(s, "date",  None)
                story_text  = getattr(s, "caption", None) or ""
        except Exception:
            pass

        if story_media is None:
            try:
                msgs   = await client.get_messages(peer, ids=story_id)
                target = msgs if not isinstance(msgs, list) else (msgs[0] if msgs else None)
                if target:
                    story_media = getattr(target, "media",   None)
                    story_date  = getattr(target, "date",    None)
                    story_text  = (getattr(target, "text", None) or getattr(target, "message", None) or "")
            except Exception:
                pass

        if story_media is None:
            try:
                from telethon.tl.functions.stories import GetPeerStoriesRequest
                result2      = await client(GetPeerStoriesRequest(peer=peer))
                peer_stories = getattr(result2, "stories", None)
                all_stories  = getattr(peer_stories, "stories", []) or []
                for s in all_stories:
                    if getattr(s, "id", None) == story_id:
                        story_media = getattr(s, "media",   None)
                        story_date  = getattr(s, "date",    None)
                        story_text  = getattr(s, "caption", None) or ""
                        break
            except Exception:
                pass

        if story_media is None:
            await status_msg.edit(
                "❌ Story tidak dapat diambil.\n\n"
                "Kemungkinan penyebab:\n"
                "• Story sudah dihapus atau kedaluwarsa\n"
                "• Akun pemilik story menggunakan privasi ketat\n"
                "• Kamu belum follow/kontak akun tersebut"
            )
            return

        try:
            date_str = story_date.astimezone(WIB).strftime("%d/%m/%y, %H:%M") if story_date else "—"
        except Exception:
            date_str = story_date.strftime("%d/%m/%y, %H:%M") if story_date else "—"

        first_name   = getattr(peer, "first_name", "") or ""
        last_name    = getattr(peer, "last_name",  "") or ""
        title        = getattr(peer, "title",      "") or ""
        display_name = escape_md((title or f"{first_name} {last_name}").strip() or username)
        story_uname  = getattr(peer, "username", None) or username
        peer_id      = getattr(peer, "id", "—")

        caption_text = (
            f"📥 **Dari:** [{display_name}](tg://user?id={peer_id})\n"
            f"🔖 **Username:** @{story_uname}\n"
            f"🆔 **ID:** `{peer_id}`\n"
            f"📆 **Tanggal:** {date_str}\n"
            f"🗄️ **Sumber:** 📸 Story"
        )
        if story_text:
            caption_text += f"\n\n📝 **Caption:** {story_text}"

        task_id = _make_task_id(user_id)
        task    = asyncio.ensure_future(
            _story_download(client, story_media, status_msg, caption_text, task_id)
        )
        _active_tasks[task_id] = task
        try:
            await task
        except asyncio.CancelledError:
            try:
                await status_msg.edit(f"⛔ Unduhan story `#{task_id}` dibatalkan.")
            except Exception:
                pass
        finally:
            _active_tasks.pop(task_id, None)

    # ── AUTO DL ───────────────────────────────────────────────────
    @client.on(events.NewMessage(incoming=True))
    async def auto_dl_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id)
            return
        if not get_auto_dl_view_once(user_id):
            return
        if _dl_dedup_check(user_id, event.id):
            return
        if not event.is_private:
            return
        msg = event.message
        if not msg or not msg.media:
            return
        if not is_view_once(msg) and not is_no_forward(msg):
            return
        lock = dl_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            task_id = _make_task_id(user_id)
            task    = asyncio.ensure_future(_auto_dl_process(client, msg, user_id, task_id))
            _active_tasks[task_id] = task
            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                _active_tasks.pop(task_id, None)


# ── PROSES .dl ────────────────────────────────────────────────────
async def _process_dl(event, client, user_id, task_id: str):
    if not is_subscribed(user_id):
        await stop_client_for_user(user_id)
        await event.client.send_message("me",
            "❌ Langganan VIP kamu sudah habis atau dicabut.\n"
            "Hubungi admin untuk memperpanjang."
        )
        return
    await event.delete()
    if not event.is_reply:
        return
    replied = await event.get_reply_message()
    if not replied or not replied.media:
        return

    sender  = await replied.get_sender()
    caption = _build_caption(sender, msg=replied)

    status_msg = await client.send_message("me", "⏳ Sedang memproses...")

    is_view_once_media = bool(getattr(replied.media, "ttl_seconds", None))

    if not is_view_once_media and not is_no_forward(replied):
        try:
            await client.forward_messages("me", replied)
            await status_msg.edit(caption, parse_mode="markdown")
            return
        except Exception:
            pass

    try:
        media_bytes = await download_bytes_with_progress(
            client, replied.media, status_msg, task_id
        )
    except asyncio.CancelledError:
        try:
            await status_msg.edit(f"⛔ Unduhan `#{task_id}` dibatalkan.")
        except Exception:
            pass
        raise
    except Exception as e:
        await status_msg.edit(f"❌ Gagal mendownload: {e}")
        return
    if not media_bytes:
        await status_msg.delete()
        return

    await _send_media_file(client, replied, media_bytes, status_msg, caption, task_id)


# ── PROSES .copy download ─────────────────────────────────────────
async def _copy_download(client, msg, status_msg, task_id: str, sender=None, source_override=None):
    caption = _build_caption(sender, msg=msg, source_override=source_override)
    try:
        media_bytes = await download_bytes_with_progress(
            client, msg.media, status_msg, task_id,
            start_text="⏳ Mendownload",
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        await status_msg.edit(f"❌ Gagal mendownload media: {e}")
        return
    if not media_bytes:
        await status_msg.edit("❌ Gagal mendownload media.")
        return
    await _send_media_file(client, msg, media_bytes, status_msg, caption, task_id)


# ── PROSES .story download ────────────────────────────────────────
async def _story_download(client, story_media, status_msg, caption_text, task_id: str):
    try:
        media_bytes = await download_bytes_with_progress(
            client, story_media, status_msg, task_id,
            start_text="⏳ Mendownload story",
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        await status_msg.edit(f"❌ Gagal mendownload media story: {e}")
        return
    if not media_bytes:
        await status_msg.edit("❌ Gagal mendownload story.")
        return

    await _send_story_file(client, story_media, media_bytes, status_msg, caption_text, task_id)


# ── PROSES AUTO DL ────────────────────────────────────────────────
async def _auto_dl_process(client, msg, user_id: int, task_id: str):
    try:
        status_msg  = await client.send_message(
            "me",
            f"⏱️ Auto DL terdeteksi... 0.00%\n\n⛔ Ketik `.cancel #{task_id}` untuk membatalkan"
        )
        media_bytes = await download_bytes_with_progress(
            client, msg.media, status_msg, task_id,
            start_text="⏱️ Auto DL terdeteksi",
        )
    except asyncio.CancelledError:
        try:
            await client.send_message("me", f"⛔ Auto DL `#{task_id}` dibatalkan.")
        except Exception:
            pass
        raise
    except Exception as e:
        await client.send_message("me", f"❌ Auto DL error: {e}")
        return

    if not media_bytes:
        await status_msg.edit("❌ Auto DL gagal: media kosong.")
        return

    sender  = await msg.get_sender()
    caption = _build_caption(sender, msg=msg)
    await _send_media_file(client, msg, media_bytes, status_msg, caption, task_id)
