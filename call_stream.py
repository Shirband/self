# -*- coding: utf-8 -*-
"""
ماژول استریم فیلم/آهنگ (صدا+تصویر) تو Voice Chat گروه‌ها.
از اکانت خودِ کاربر (همون userbot که قبلاً لاگین کرده) به‌عنوان assistant
برای join شدن به ویس‌چت و پخش استفاده می‌کنه.

پیش‌نیازها (تو requirements.txt اضافه شدن):
    py-tgcalls
    yt-dlp

پیش‌نیاز سیستمی: ffmpeg باید نصب باشه (رو Railway با nixpacks.toml اضافه شده).

منابع پشتیبانی‌شده برای دستور «پخش <لینک>»:
    - لینک مستقیم فایل (mp4/mkv/...)
    - لینک یوتیوب
    - لینک اینستاگرام (پست/ریلز عمومی)
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque

try:
    from pytgcalls import PyTgCalls
    from pytgcalls.types import MediaStream
    from pytgcalls.exceptions import NoActiveGroupCall
    _PYTGCALLS_AVAILABLE = True
except ImportError:
    _PYTGCALLS_AVAILABLE = False
    PyTgCalls = None
    MediaStream = None
    NoActiveGroupCall = Exception

try:
    import yt_dlp
    _YTDLP_AVAILABLE = True
except ImportError:
    _YTDLP_AVAILABLE = False
    yt_dlp = None


# هر یوزر (اکانتی که لاگین کرده) یه نمونه‌ی PyTgCalls جدا داره
_PTC_INSTANCES: dict[int, "PyTgCalls"] = {}
# صف پخش هر چت: {(user_id, chat_id): deque([link, link, ...])}
_QUEUES: dict[tuple, deque] = {}
# لینک/عنوان در حال پخش فعلی هر چت
_NOW_PLAYING: dict[tuple, str] = {}

DIRECT_EXTENSIONS = (".mp4", ".mkv", ".mov", ".webm", ".mp3", ".m4a", ".ogg", ".flac")


def feature_available() -> str | None:
    """اگه کتابخونه‌ای کم باشه، پیام خطا برمی‌گردونه؛ وگرنه None."""
    missing = []
    if not _PYTGCALLS_AVAILABLE:
        missing.append("py-tgcalls")
    if not _YTDLP_AVAILABLE:
        missing.append("yt-dlp")
    if missing:
        return (
            "❌ قابلیت استریم فعال نیست. این کتابخونه‌ها رو سرور نصب نیست: "
            + ", ".join(missing)
            + "\nاول باید تو requirements.txt اضافه بشن و همچنین ffmpeg رو سیستم نصب باشه."
        )
    return None


async def get_ptc(client) -> "PyTgCalls":
    """نمونه‌ی PyTgCalls رو برای این کلاینت (اکانت) می‌گیره یا می‌سازه."""
    user_id = client.me.id
    if user_id not in _PTC_INSTANCES:
        app = PyTgCalls(client)
        await app.start()
        _PTC_INSTANCES[user_id] = app
    return _PTC_INSTANCES[user_id]


def _is_direct_link(link: str) -> bool:
    low = link.lower().split("?")[0]
    return low.startswith("http") and low.endswith(DIRECT_EXTENSIONS)


async def resolve_stream_url(link: str) -> tuple[str, str]:
    """
    لینک ورودی (مستقیم / یوتیوب / اینستاگرام) رو به یه URL قابل پخش با ffmpeg
    و یه عنوان نمایشی تبدیل می‌کنه.
    """
    if _is_direct_link(link):
        return link, link.rsplit("/", 1)[-1]

    if not _YTDLP_AVAILABLE:
        raise RuntimeError("yt-dlp نصب نیست؛ لینک یوتیوب/اینستاگرام قابل پردازش نیست.")

    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    loop = asyncio.get_event_loop()

    def _extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(link, download=False)

    info = await loop.run_in_executor(None, _extract)
    if not info:
        raise RuntimeError("نتونستم اطلاعات این لینک رو بگیرم.")

    stream_url = info.get("url")
    if not stream_url and info.get("formats"):
        stream_url = info["formats"][-1].get("url")
    if not stream_url:
        raise RuntimeError("لینک قابل استریم از این آدرس پیدا نشد.")

    title = info.get("title") or link
    return stream_url, title


async def _play_next(client, chat_id: int):
    key = (client.me.id, chat_id)
    queue = _QUEUES.get(key)
    if not queue:
        _NOW_PLAYING.pop(key, None)
        try:
            app = await get_ptc(client)
            await app.leave_call(chat_id)
        except Exception:
            pass
        return

    link = queue.popleft()
    try:
        stream_url, title = await resolve_stream_url(link)
    except Exception as e:
        logging.error(f"خطا در resolve لینک استریم: {e}")
        await _play_next(client, chat_id)
        return

    app = await get_ptc(client)
    _NOW_PLAYING[key] = title
    try:
        await app.play(chat_id, MediaStream(stream_url))
    except NoActiveGroupCall:
        raise RuntimeError("تو این گروه ویس‌چت فعالی وجود نداره؛ اول باید ویس‌چت رو استارت کنی.")


async def enqueue_and_play(client, chat_id: int, link: str) -> str:
    """لینک رو به صف اضافه می‌کنه و اگه چیزی در حال پخش نیست، شروعش می‌کنه."""
    err = feature_available()
    if err:
        raise RuntimeError(err)

    key = (client.me.id, chat_id)
    queue = _QUEUES.setdefault(key, deque())

    if key in _NOW_PLAYING:
        queue.append(link)
        return f"➕ به صف اضافه شد (جایگاه {len(queue)})."

    queue.append(link)
    await _play_next(client, chat_id)
    title = _NOW_PLAYING.get(key, link)
    return f"▶️ در حال پخش: {title}"


async def skip_current(client, chat_id: int) -> str:
    key = (client.me.id, chat_id)
    if key not in _NOW_PLAYING:
        return "چیزی در حال پخش نیست."
    _NOW_PLAYING.pop(key, None)
    await _play_next(client, chat_id)
    new_title = _NOW_PLAYING.get(key)
    return f"⏭ رد شد. الان: {new_title}" if new_title else "⏭ رد شد. صف خالیه."


async def stop_playback(client, chat_id: int) -> str:
    key = (client.me.id, chat_id)
    _QUEUES.pop(key, None)
    _NOW_PLAYING.pop(key, None)
    try:
        app = await get_ptc(client)
        await app.leave_call(chat_id)
    except Exception:
        pass
    return "⏹ پخش متوقف شد و از ویس‌چت خارج شدم."


def now_playing_text(client, chat_id: int) -> str:
    key = (client.me.id, chat_id)
    title = _NOW_PLAYING.get(key)
    queue = _QUEUES.get(key)
    if not title:
        return "چیزی در حال پخش نیست."
    txt = f"🎬 الان: {title}"
    if queue:
        txt += f"\n📋 {len(queue)} مورد تو صف مونده."
    return txt


# ==================== هندلرهای پیام (filters.me) ====================

async def play_command_handler(client, message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply_text(
            "لینک رو بعد از دستور بنویس.\nمثال: `پخش https://youtube.com/watch?v=xxxx`"
        )
        return

    link = parts[1].strip()
    status = await message.reply_text("⏳ در حال پردازش لینک...")
    try:
        result = await enqueue_and_play(client, message.chat.id, link)
        await status.edit_text(result)
    except Exception as e:
        await status.edit_text(f"❌ خطا: {e}")


async def skip_command_handler(client, message):
    try:
        result = await skip_current(client, message.chat.id)
        await message.reply_text(result)
    except Exception as e:
        await message.reply_text(f"❌ خطا: {e}")


async def stop_command_handler(client, message):
    try:
        result = await stop_playback(client, message.chat.id)
        await message.reply_text(result)
    except Exception as e:
        await message.reply_text(f"❌ خطا: {e}")


async def now_playing_command_handler(client, message):
    await message.reply_text(now_playing_text(client, message.chat.id))


def register_call_stream_handlers(client):
    """این تابع از start_bot_instance صدا زده می‌شه تا هندلرهای پخش رجیستر بشن."""
    from pyrogram import filters
    from pyrogram.handlers import MessageHandler

    client.add_handler(MessageHandler(
        play_command_handler, filters.me & filters.regex(r"^(پخش|play) .+$")
    ))
    client.add_handler(MessageHandler(
        skip_command_handler, filters.me & filters.regex(r"^(رد شو|اسکیپ|skip)$")
    ))
    client.add_handler(MessageHandler(
        stop_command_handler, filters.me & filters.regex(r"^(استاپ|توقف پخش|stop)$")
    ))
    client.add_handler(MessageHandler(
        now_playing_command_handler, filters.me & filters.regex(r"^(الان چی پخشه|np|now playing)$")
    ))
