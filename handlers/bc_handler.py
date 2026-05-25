import asyncio

from telethon import events
from telethon.tl.types import Channel, Chat

from database import (
    is_subscribed,
    bc_blacklist_add, bc_blacklist_remove,
    bc_blacklist_get, bc_blacklist_ids,
)
from client_manager import stop_client_for_user
from handlers.telethon_handlers import _active_tasks, _make_task_id


# -- NORMALIZE GROUP ID --
# Telethon menyimpan entity.id tanpa prefix -100, misal: 1234567890
# Tapi user sering input -1001234567890 (format Telegram API penuh)
# Fungsi ini selalu kembalikan bare ID (tanpa -100)
def _normalize_gid(raw_id: int) -> int:
    s = str(raw_id)
    if s.startswith("-100"):
        return int(s[4:])
    if s.startswith("-"):
        return int(s[1:])
    return raw_id


# -- HELPER: resolve grup dari event atau arg ID --
async def _resolve_group(client, event, arg):
    if arg:
        raw_id     = int(arg)
        group_id   = _normalize_gid(raw_id)   # simpan bare ID
        try:
            entity     = await client.get_entity(raw_id)
            group_name = getattr(entity, "title", "") or str(raw_id)
        except Exception:
            group_name = str(raw_id)
        return group_id, group_name
    else:
        chat = await event.get_chat()
        if not isinstance(chat, (Channel, Chat)):
            raise ValueError(
                "⚠️ Command ini hanya bisa dipakai langsung di dalam grup, "
                "atau sertakan ID grup.\n\n"
                "Contoh: `.addbl -1001234567890`"
            )
        group_id   = _normalize_gid(chat.id)  # Telethon kadang return bare, kadang penuh
        group_name = getattr(chat, "title", "") or str(chat.id)
        return group_id, group_name


# -- PROSES .bc broadcast --
async def _process_bc(client, text: str, status_msg, task_id: str, user_id: int):
    success = 0
    try:
        # blocked_ids sudah berisi bare ID (tanpa -100)
        blocked_ids = bc_blacklist_ids(user_id)

        groups   = []
        seen_ids = set()
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if not isinstance(entity, (Channel, Chat)):
                continue
            eid = _normalize_gid(getattr(entity, "id", 0))  # normalisasi juga saat filter
            if not eid or eid in seen_ids:
                continue
            if eid in blocked_ids:
                seen_ids.add(eid)
                continue
            is_broadcast_channel = (
                isinstance(entity, Channel)
                and getattr(entity, "broadcast", False)
                and not getattr(entity, "megagroup", False)
            )
            if not is_broadcast_channel:
                seen_ids.add(eid)
                groups.append(entity)

        total     = len(groups)
        failed    = 0
        processed = 0
        cancelled = False
        semaphore = asyncio.Semaphore(5)

        async def send_to_group(group):
            nonlocal success, failed, processed, cancelled
            if cancelled:
                return
            async with semaphore:
                if cancelled:
                    return
                try:
                    await client.send_message(group, text)
                    success += 1
                except Exception:
                    failed += 1
                finally:
                    processed += 1
                    if processed % 5 == 0 or processed == total:
                        try:
                            await status_msg.edit(
                                f"📣 Memproses bc... ({processed}/{total})\n\n"
                                f"Ketik `.cancel #{task_id}` untuk membatalkan bc."
                            )
                        except Exception:
                            pass
                    await asyncio.sleep(0.5)

        batch_tasks = [asyncio.create_task(send_to_group(g)) for g in groups]
        try:
            await asyncio.gather(*batch_tasks)
        except asyncio.CancelledError:
            cancelled = True
            for t in batch_tasks:
                t.cancel()
            raise

        skipped = len(blocked_ids)
        result  = (
            f"📣 **Pesan:** {text}\n"
            f"✨ **Berhasil:** {success}\n"
            f"☹️ **Gagal:** {failed}"
        )
        if skipped:
            result += f"\n😹 **Skip:** {skipped}"
        await status_msg.edit(result)

    except asyncio.CancelledError:
        try:
            await status_msg.edit(
                f"😭 Broadcast `#{task_id}` dibatalkan.\n\n"
                f"✨ Terkirim sebelum cancel: {success} grup"
            )
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            await status_msg.edit(f"😵 Broadcast gagal: {e}")
        except Exception:
            pass


# -- REGISTER HANDLER --
def register_bc_handler(client, user_id: int):

    # -- .bc <pesan> --
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.bc\s+(.+)$"))
    async def bc_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id)
            await event.client.send_message("me",
                "❌ Langganan VIP kamu sudah habis atau dicabut.\n"
                "Hubungi admin untuk memperpanjang."
            )
            return

        text = event.pattern_match.group(1).strip()
        await event.delete()

        task_id    = _make_task_id(user_id)
        status_msg = await client.send_message(
            "me",
            f"📣 Memproses bc...\n\n"
            f"Ketik `.cancel #{task_id}` untuk membatalkan bc."
        )

        task = asyncio.ensure_future(
            _process_bc(client, text, status_msg, task_id, user_id)
        )
        _active_tasks[task_id] = task
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            _active_tasks.pop(task_id, None)

    # -- .addbl [group_id] --
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.addbl(?:\s+(-?\d+))?$"))
    async def addbl_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id)
            await event.client.send_message("me",
                "❌ Langganan VIP kamu sudah habis atau dicabut."
            )
            return
        await event.delete()

        arg = event.pattern_match.group(1)
        try:
            group_id, group_name = await _resolve_group(client, event, arg)
        except ValueError as e:
            await client.send_message("me", str(e))
            return

        added = bc_blacklist_add(user_id, group_id, group_name)
        if added:
            await client.send_message("me",
                f"⛔ **{group_name}** ditambahkan ke blacklist bc.\n"
                f"`{group_id}`\n\n"
                f"Grup ini tidak akan menerima broadcast kamu."
            )
        else:
            await client.send_message("me",
                f"⚠️ **{group_name}** (`{group_id}`) sudah ada di blacklist bc."
            )

    # -- .delbl [group_id] --
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.delbl(?:\s+(-?\d+))?$"))
    async def delbl_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id)
            await event.client.send_message("me",
                "❌ Langganan VIP kamu sudah habis atau dicabut."
            )
            return
        await event.delete()

        arg = event.pattern_match.group(1)
        try:
            group_id, group_name = await _resolve_group(client, event, arg)
        except ValueError as e:
            await client.send_message("me", str(e))
            return

        removed = bc_blacklist_remove(user_id, group_id)
        if removed:
            await client.send_message("me",
                f"✅ **{group_name}** dihapus dari blacklist bc.\n"
                f"`{group_id}`\n\n"
                f"Grup ini akan kembali menerima broadcast kamu."
            )
        else:
            await client.send_message("me",
                f"⚠️ **{group_name}** (`{group_id}`) tidak ada di blacklist bc."
            )

    # -- .listbl --
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.listbl$"))
    async def listbl_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id)
            await event.client.send_message("me",
                "❌ Langganan VIP kamu sudah habis atau dicabut."
            )
            return
        await event.delete()

        rows = bc_blacklist_get(user_id)
        if not rows:
            await client.send_message("me",
                "📝 **Blacklist BC kosong.**\n\n"
                "Semua grup akan menerima broadcast kamu."
            )
            return

        lines = [f"🚫 **Blacklist BC** ({len(rows)} grup)\n"]
        for i, r in enumerate(rows, 1):
            name = r['group_name'] or '—'
            lines.append(f"{i}. **{name}**\n   `{r['group_id']}`")
        lines.append("\n💡 Ketik `.delbl <id>` untuk whitelist kembali.")

        await client.send_message("me", "\n".join(lines))
