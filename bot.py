import asyncio
import os
import sys
import logging
import re
import aiohttp
import time
import json
import random
import psutil
import sqlite3
import threading
from persiantools.jdatetime import JalaliDate
from urllib.parse import quote
from pyrogram import Client, filters, idle
from pyrogram.handlers import MessageHandler, DeletedMessagesHandler, CallbackQueryHandler
from collections import OrderedDict
from pyrogram.enums import ChatType, ChatAction
from pyrogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton,
    InlineQueryResultArticle, InputTextMessageContent
)
from pyrogram.raw import functions
from pyrogram.errors import (
    SessionPasswordNeeded, ChatSendInlineForbidden, FloodWait
)
from datetime import datetime
from zoneinfo import ZoneInfo
import pyrogram.utils

# ==== کتابخونه‌های ساخت فایل Word / PDF (اختیاری) ====
try:
    from docx import Document
except ImportError:
    Document = None

try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    _PERSIAN_SHAPING_AVAILABLE = True
except ImportError:
    _PERSIAN_SHAPING_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')

def patch_peer_id_validation():
    original_get_peer_type = pyrogram.utils.get_peer_type

    def patched_get_peer_type(peer_id: int) -> str:
        try:
            return original_get_peer_type(peer_id)
        except ValueError:
            if str(peer_id).startswith("-100"):
                return "channel"
            raise

    pyrogram.utils.get_peer_type = patched_get_peer_type
    logging.info("Pyrogram peer ID validation patched successfully.")

patch_peer_id_validation()

try:
    from call_stream import register_call_stream_handlers
except ImportError:
    register_call_stream_handlers = None
    logging.warning("call_stream.py پیدا نشد یا کتابخونه‌هاش نصب نیست؛ قابلیت پخش تو کال غیرفعاله.")

# ==== تنظیمات حساس: همه از Environment Variables خونده می‌شن ====
# روی Railway باید این‌ها رو تو تب Variables پروژه ست کنی:
# API_ID, API_HASH, BOT_TOKEN, AI_API_KEY, AI_API_URL, AI_MODEL, GOD_ADMIN_IDS
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    logging.warning(
        "API_ID / API_HASH / BOT_TOKEN تنظیم نشدن! این‌ها رو تو Environment Variables "
        "پروژه Railway ست کن، وگرنه ربات بالا نمیاد."
    )

# لیست آی‌دی ادمین‌های اصلی، جدا شده با کاما، مثلا: GOD_ADMIN_IDS=8406519786,123456
_god_admin_env = os.environ.get("GOD_ADMIN_IDS", "")
GOD_ADMIN_IDS = [int(x) for x in _god_admin_env.split(",") if x.strip().isdigit()]

# ==== دستیار AI ====
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_API_URL = os.environ.get("AI_API_URL", "")
AI_MODEL = os.environ.get("AI_MODEL", "")
AI_SYSTEM_PROMPT = (
    "تو یک دستیار هوش مصنوعی هستی که به جای صاحب اکانت به پیام‌های تلگرام جواب می‌دی. "
    "نام صاحب اکانت ابوالفضل (یا ابول/ابولی) است و ۲۰ سال دارد. "
    "خصوصیات شخصیتی:\n"
    "- جواب‌های کوتاه، شفاف و قاطع بده\n"
    "- هرگز ایموجی یا شکلک استفاده نکن\n"
    "- لحن گرم و دوستانه باشه ولی بدون احساس‌آلودگی یا صمیمیت بیش‌ازحد\n"
    "- اگر کسی بی‌احترام رفتار کرد، با آرامش و شقاق رد کن، بدون فحش یا توهین\n"
    "- همیشه مهربان باشه و به مسائل عملی کمک کن\n"
    "- اگر سوال نمی‌دانی، راست بگو که نمی‌دانی\n"
    "- پاسخ‌های فارسی شفاف و بدون خطا دستوری\n"
    "- هیچ محتوای نامناسب، توهین‌آمیز یا خلاف اخلاق تولید نکن"
)


# روی Railway اگه یه Volume وصل کردی، مسیرش رو با متغیر DATA_DIR بده (مثلا /data)
# تا دیتابیس (که شامل session_string اکانت‌های وصل‌شده‌ست) بین دیپلوی‌ها از بین نره.
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(DATA_DIR, "bot_data.db")  # قبلاً bot_data.json بود؛ حالا دیتابیس SQLite
PANEL_PHOTO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.jpg")

# فونت فارسی برای ساخت PDF. یک فایل ttf فارسی (مثلاً Vazirmatn-Regular.ttf) را
# کنار همین فایل بات آپلود کن؛ بدون این فایل، متن فارسی در PDF درست نمایش داده نمی‌شود.
PERSIAN_FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Vazirmatn-Regular.ttf")

TEHRAN_TIMEZONE = ZoneInfo("Asia/Tehran")
LOGIN_STATES = {} 
ADMIN_STATES = {} 

FONT_STYLES = {
    "cursive":      {'0':'𝟎','1':'𝟏','2':'𝟐','3':'𝟑','4':'𝟒','5':'𝟓','6':'𝟔','7':'𝟕','8':'𝟖','9':'𝟗',':':':'},
    "stylized":     {'0':'𝟬','1':'𝟭','2':'𝟮','3':'𝟯','4':'𝟰','5':'𝟱','6':'𝟲','7':'𝟳','8':'𝟴','9':'𝟵',':':':'},
    "doublestruck": {'0':'𝟘','1':'𝟙','2':'𝟚','3':'𝟛','4':'𝟜','5':'𝟝','6':'𝟞','7':'𝟟','8':'𝟠','9':'𝟡',':':':'},
    "monospace":    {'0':'𝟶','1':'𝟷','2':'𝟸','3':'𝟹','4':'𝟺','5':'𝟻','6':'𝟼','7':'𝟽','8':'𝟾','9':'𝟿',':':':'},
    "normal":       {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
    "circled":      {'0':'⓪','1':'①','2':'②','3':'③','4':'④','5':'⑤','6':'⑥','7':'⑦','8':'⑧','9':'⑨',':':'∶'},
    "fullwidth":    {'0':'０','1':'１','2':'２','3':'３','4':'４','5':'５','6':'６','7':'７','8':'８','9':'９',':':'：'},
    "filled":       {'0':'⓿','1':'❶','2':'❷','3':'❸','4':'❹','5':'❺','6':'❻','7':'❼','8':'❽','9':'❾',':':':'},
    "sans":         {'0':'𝟢','1':'𝟣','2':'𝟤','3':'𝟥','4':'𝟦','5':'𝟧','6':'𝟨','7':'𝟩','8':'𝟪','9':'𝟫',':':':'},
    "inverted":     {'0':'0','1':'Ɩ','2':'ᄅ','3':'Ɛ','4':'ㄣ','5':'ϛ','6':'9','7':'ㄥ','8':'8','9':'6',':':':'},
}
FONT_KEYS_ORDER = ["cursive", "stylized", "doublestruck", "monospace", "normal", "circled", "fullwidth", "filled", "sans", "inverted"]

ALL_CLOCK_CHARS = "".join(set(char for font in FONT_STYLES.values() for char in font.values()))
CLOCK_CHARS_REGEX_CLASS = f"[{re.escape(ALL_CLOCK_CHARS)}]"

SECRETARY_REPLY_MESSAGE = "سلام! در حال حاضر آفلاین هستم و پیام شما را دریافت کردم. در اولین فرصت پاسخ خواهم داد. ممنون از پیامتون."

HELP_TEXT = """
**راهنمای دستورات دستی و ریپلای**
─────────────────
تنظیمات اصلی (ساعت، فونت، منشی و بقیه‌ی حالت‌ها) فقط از طریق دستور `پنل` در دسترس هستند.

**• مدیریت پیام و چت**
  `حذف [تعداد]`
  `ذخیره` (ریپلای روی پیام)
  `تکرار [تعداد]` (ریپلای روی پیام)
  `تنظیم منشی [متن]` — تغییر پیام خودکار منشی

**• دستیار AI**
  `دستیار روشن` / `دستیار خاموش` — یا از پنل، بخش «حالت‌های خودکار»
  وقتی فعال باشد، هر کس روی یکی از پیام‌های شما ریپلای کند، هوش مصنوعی به‌جای شما جواب می‌دهد.
  `ساخت ورد [توضیح]` — ساخت فایل Word با محتوای تولیدشده توسط AI
  `ساخت پی دی اف [توضیح]` — ساخت فایل PDF با محتوای تولیدشده توسط AI

**• دفاعی و امنیتی**
  `دشمن روشن` / `دشمن خاموش` (ریپلای روی کاربر)
  `لیست دشمن`
  `بلاک روشن` / `بلاک خاموش` (ریپلای روی کاربر)
  `سکوت روشن` / `سکوت خاموش` (ریپلای روی کاربر)
  `ریاکشن [شکلک]` / `ریاکشن خاموش` (ریپلای روی کاربر)

**• سرگرمی**
  `تاس` / `تاس [عدد]` / `بولینگ`
  انیمیشن‌های ادیت پیام (مثلاً: `قلب`، `موشک`، `رقص`، `خخخ`)
  `میو فعال` / `میو غیرفعال`
  `فال` / `بیو رندوم` / `تاریخ امروز` / `قیمت ارز` / `رم`
  `گیممم [متن]` / `/getgif متن` / `/getpic متن` / `/getmeme متن` / `/serchgoogle متن` / `/youtube متن` / `/like-> متن` / `/fonet-> متن`

**• ظاهر پیام‌های شما**
  `هشتک روشن` / `هشتک خاموش`
  `خط خورده روشن` / `خط خورده خاموش`
  `تکی روشن` / `تکی خاموش`
  `مود روشن` / `مود خاموش`
  (`ضخیم روشن`/`ضخیم خاموش` معادل دکمه‌ی «بولد» در پنل است)

**• ساعت و بیو**
  `ساعت روشن` / `ساعت خاموش` — روی نام خانوادگی
  `ساعت بیو روشن` / `ساعت بیو خاموش`
  `تنظیم بیو` (ریپلای روی متن دلخواه)
  `شمسی روشن` / `میلادی روشن` / `تاریخ خاموش`

**• پروفایل چرخشی**
  `اد پروفایل` (ریپلای روی عکس)
  `پروفایل روشن` / `پروفایل خاموش` / `پاکسازی پروفایل`

**• حالت‌های خودکار**
  `سایلنت روشن/خاموش` — حذف پیام‌های ورودی پیوی
  `سیو روشن/خاموش` — ذخیره‌ی مدیای تایمردار
  `پوکر روشن/خاموش` — خواندن بی‌صدای پیوی
  `آنلاین روشن/خاموش`
  `کامنت روشن/خاموش` / `تنظیم کامنت [متن]`
  `/autopv on/off` / `/addpv` (ریپلای) / `/testpv` / `/restpv` — منشی پیوی
  `/login on` / `/login off` — فوروارد کد ورود به ذخیره‌شده‌ها
  `ریستارت`

─────────────────
"""

FULL_COMMAND_TABLE = """**جدول کامل دستورات**
─────────────────

**• مدیریت پیام و چت**
`حذف [تعداد]` | حذف پیام‌های اخیر شما در چت
`ذخیره` (ریپلای) | فوروارد پیام به ذخیره‌شده‌ها
`تکرار [تعداد]` (ریپلای) | تکرار پیام ریپلای‌شده
`تنظیم منشی [متن]` | تغییر متن پاسخ خودکار پیوی

**• دفاعی و امنیتی**
`بلاک روشن/خاموش` (ریپلای) | بلاک یا آنبلاک کاربر
`سکوت روشن/خاموش` (ریپلای) | نادیده گرفتن پیام‌های یک کاربر
`ریاکشن [شکلک]` (ریپلای) | ری‌اکشن خودکار روی پیام‌های یک کاربر
`ریاکشن خاموش` (ریپلای) | خاموش کردن ری‌اکشن خودکار

**• سرگرمی**
`تاس` / `تاس [عدد]` | ارسال تاس
`بولینگ` | ارسال بولینگ
`میو فعال/غیرفعال` | ارسال خودکار «میو» هر ۵ دقیقه در این چت
`فال` | دریافت فال
`بیو رندوم` | ست کردن یک بیوی رندوم
`تاریخ امروز` | نمایش تاریخ امروز
`قیمت ارز` | نمایش قیمت لحظه‌ای ارزها
`رم` | نمایش وضعیت مصرف رم سرور
`گیممم [متن]` | ارسال بازی اینلاین
`/getgif [متن]` | جست‌وجوی گیف
`/getpic [متن]` | جست‌وجوی عکس
`/getmeme [متن]` | جست‌وجوی میم
`/serchgoogle [متن]` | جست‌وجو در گوگل
`/youtube [متن]` | جست‌وجو در یوتیوب
`/like-> [متن]` | ارسال با استایل لایک
`/fonet-> [متن]` | تبدیل فونت متن

**• ظاهر پیام‌های خودتان**
`هشتک روشن/خاموش` | افزودن هشتگ به پیام‌ها
`خط خورده روشن/خاموش` | استایل خط‌خورده روی پیام‌ها
`تکی روشن/خاموش` | حالت تک‌کاراکتری پیام
`مود روشن/خاموش` | حالت متفرقه‌ی نمایش پیام
`ضخیم روشن/خاموش` | بولد کردن پیام‌ها

**• ساعت و بیو**
`ساعت روشن/خاموش` | نمایش ساعت روی نام
`ساعت بیو روشن/خاموش` | نمایش ساعت در بیو
`تنظیم بیو` (ریپلای) | ست کردن بیو دلخواه
`شمسی روشن` / `میلادی روشن` / `تاریخ خاموش` | فرمت تاریخ در بیو

**• پروفایل چرخشی**
`اد پروفایل` (ریپلای روی عکس) | افزودن عکس به چرخه‌ی پروفایل
`پروفایل روشن/خاموش` | فعال/غیرفعال کردن چرخش پروفایل
`پاکسازی پروفایل` | پاک کردن لیست عکس‌های چرخشی

**• حالت‌های خودکار**
`سایلنت روشن/خاموش` | حذف خودکار پیام‌های ورودی پیوی
`سیو روشن/خاموش` | ذخیره‌ی خودکار مدیای تایمردار
`پوکر روشن/خاموش` | خواندن بی‌صدای پیام‌های پیوی
`آنلاین روشن/خاموش` | آنلاین نگه‌داشتن اکانت
`کامنت روشن/خاموش` | ارسال خودکار کامنت روی پست‌های کانال
`تنظیم کامنت [متن]` | تغییر متن کامنت خودکار
`/autopv on/off` | فعال/غیرفعال کردن منشی پیوی
`/addpv` (ریپلای) | افزودن پیام از پیش‌تعریف‌شده به منشی پیوی
`/testpv` | تست پاسخ منشی پیوی
`/restpv` | ریست تنظیمات منشی پیوی
`/login on/off` | فوروارد خودکار کد ورود به ذخیره‌شده‌ها
`ریستارت` | ری‌استارت ربات
`دستیار روشن/خاموش` | پاسخ خودکار با هوش مصنوعی به ریپلای‌های روی پیام‌های شما
`ساخت ورد [توضیح]` | ساخت فایل Word با محتوای تولیدشده توسط AI
`ساخت پی دی اف [توضیح]` | ساخت فایل PDF با محتوای تولیدشده توسط AI

**• پنل و راهنما**
`پنل` | باز کردن پنل شیشه‌ای تنظیمات
`راهنما` | نمایش این راهنما
"""

# ============================================================================
# سیستم طراحی رابط کاربری — پاسخ‌های یکدست، ساختارمند و کم‌ایموجی
# ============================================================================
UI_DIVIDER = "─────────────────"
ICON_ON = "✓"
ICON_OFF = "○"

def ui_ok(text: str) -> str:
    """پیام موفقیت‌آمیز"""
    return f"✅ {text}"

def ui_err(text: str) -> str:
    """پیام خطا"""
    return f"❌ {text}"

def ui_warn(text: str) -> str:
    """پیام هشدار / راهنمایی"""
    return f"⚠️ {text}"

def ui_toggle(label: str, state: bool, on_word: str = "فعال شد", off_word: str = "غیرفعال شد") -> str:
    """پیام یکدست برای روشن/خاموش شدن یک قابلیت"""
    icon = "✅" if state else "⭕️"
    word = on_word if state else off_word
    return f"{icon} {label} {word}"

def ui_status(state: bool) -> str:
    """نماد وضعیت کوتاه برای دکمه‌ها"""
    return ICON_ON if state else ICON_OFF

def panel_text(title: str, subtitle: str = "", lines=None) -> str:
    """قالب یکدست برای متن هر صفحه از پنل"""
    parts = [f"**⚙️ {title}**"]
    if subtitle:
        parts.append(subtitle)
    parts.append(UI_DIVIDER)
    if lines:
        parts.append("\n".join(lines))
    return "\n".join(parts)

def _split_into_pages(raw_text):
    """
    یک متن راهنمای بلند رو بر اساس تیترهای بخش (خط‌هایی که با «**• » شروع می‌شن)
    به صفحات جدا تقسیم می‌کنه، تا به‌جای یک دیوار متنی، صفحه‌به‌صفحه نشون داده بشه.
    """
    pages = []
    current_title = None
    current_lines = []
    for line in raw_text.strip("\n").split("\n"):
        m = re.match(r"^\*\*• (.+?)\*\*$", line.strip())
        if m:
            if current_title is not None:
                pages.append((current_title, "\n".join(current_lines).strip("\n")))
            current_title = m.group(1)
            current_lines = []
        elif current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        pages.append((current_title, "\n".join(current_lines).strip("\n")))
    return pages

def _paged_view(pages, page_idx, header_title):
    page_idx = max(0, min(page_idx, len(pages) - 1))
    sec_title, sec_body = pages[page_idx]
    text = (
        f"**{header_title}**\n"
        f"{UI_DIVIDER}\n"
        f"**• {sec_title}**  ‹{page_idx + 1}/{len(pages)}›\n"
        f"{sec_body}"
    )
    return text, page_idx

FULL_COMMAND_TABLE_PAGES = _split_into_pages(FULL_COMMAND_TABLE)
HELP_TEXT_PAGES = _split_into_pages(HELP_TEXT)

COMMAND_REGEX = (
    r"^(راهنما|ذخیره|تکرار \d+|حذف \d+|ریاکشن .*|ریاکشن خاموش|کپی روشن|کپی خاموش|لیست دشمن|"
    r"تاس|تاس \d+|بولینگ|پنل|panel|تنظیم منشی .*|"
    # ==== [Merged from chronicle.py & srckde] استثنائات دستورات جدید ====
    r"میو فعال|میو غیرفعال|ریستارت|ریس|/restart|/login (on|off)|"
    r"هشتک روشن|hashtag on|هشتک خاموش|hashtag off|ضخیم روشن|bold on|ضخیم خاموش|bold off|"
    r"خط خورده روشن|strikethrough on|خط خورده خاموش|strikethrough off|"
    r"تکی روشن|single on|تکی خاموش|single off|مود روشن|mode on|مود خاموش|mode off|"
    r"سایلنت روشن|سایلنت خاموش|سیو روشن|سیو خاموش|پوکر روشن|پوکر خاموش|آنلاین روشن|آنلاین خاموش|"
    r"تنظیم کامنت .*|setcomment .*|کامنت روشن|comment on|کامنت خاموش|comment off|"
    r"ساعت روشن|time on|ساعت خاموش|time off|ساعت بیو روشن|time bio on|ساعت بیو خاموش|time bio off|"
    r"تنظیم بیو|set bio|تاریخ شمسی روشن|شمسی روشن|jalali on|تاریخ میلادی روشن|میلادی روشن|gregorian on|"
    r"تاریخ خاموش|خاموش|date off|"
    r"اد پروفایل|add profile|پروفایل روشن|profile on|پروفایل خاموش|profile off|پاکسازی پروفایل|clear profile|"
    r"قیمت ارز|price|فال|fall|بیو رندوم|random bio|تاریخ امروز|today's date|رم|ایدی|آیدی|Id|id|"
    r"گیممم|Play|/fonet-> .*|/like-> .*|/getgif .*|/getpic .*|/getmeme .*|/serchgoogle .*|/youtube .*|"
    r"/autopv (on|off)|/addpv|/testpv|/restpv|"
    r"دستیار روشن|دستیار خاموش|"
    r"ساخت ورد .*|ساخت پی دی اف .*"
    r")$"
)

class DataManager:
    """
    نسخه‌ی SQLite جایگزین نسخه‌ی قبلی که با فایل JSON کار می‌کرد.
    همه‌ی متدهای عمومی (اسم و ورودی/خروجی) دقیقاً همون قبلی‌ان تا بقیه‌ی کد بات
    نیازی به تغییر نداشته باشه. تفاوت اصلی: نوشتن روی دیسک حالا atomic/ترنزکشنی‌ـه
    (با SQLite) و دیگه امکان کرش‌کردن وسط نوشتن و خراب‌شدن کل دیتابیس وجود نداره.
    """

    def __init__(self, file_path):
        self.file_path = file_path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.file_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                phone TEXT,
                session_string TEXT,
                data TEXT NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message_type TEXT,
                content TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_history_user ON chat_history(user_id)")
        self.conn.commit()
        logging.info(f"✅ اتصال به دیتابیس SQLite برقرار شد: {self.file_path}")

    def get_default_data(self):
        """برای سازگاری با کدهای قدیمی‌تر که ممکنه این متد رو صدا بزنن"""
        return {"users": {}, "sessions": {}}

    def _default_user_structure(self, user_id):
        return {
            "user_id": user_id,
            "phone": "",
            "first_name": "",
            "username": "",
            "session_string": "",
            "settings": {
                "font": "stylized",
                "clock": True,
                "bold": False,
                "secretary": False,
                "secretary_msg": "",
                "auto_seen": False,
                "pv_lock": False,
                "anti_login": False,
                "anti_delete": False,
                "typing": False,
                "playing": False,
                "global_enemy": False,
                "copy_mode": False,
                "translate": None,
                "hashtag": False,
                "strikethrough": False,
                "single_mode": False,
                "char_mode": False,
                "silent_mode": False,
                "save_mode": False,
                "poker_mode": False,
                "online_mode": False,
                "comment_mode": False,
                "comment_text": "کامنت تنظیم نشده",
                "lastname_clock": False,  # منسوخ، برای سازگاری با دیتای قدیمی نگه داشته شده
                "bio_time": False,
                "bio_text": "",
                "bio_date_format": None,
                "profile_rotation": False,
                "auto_reply_pv": False,
                "ai_assistant": False
            },
            "auto_reply_pv_messages": [],
            "enemies": [],
            "muted": [],
            "reactions": {},
            "replied_users": [],
            "enemy_queue": []
        }

    def _write_user(self, user_id, user_data):
        """نوشتن اتمیک یک کاربر روی دیتابیس (INSERT یا UPDATE در یک ترنزکشن)"""
        phone = user_data.get("phone") or None
        session_string = user_data.get("session_string") or None
        self.conn.execute(
            """
            INSERT INTO users (user_id, phone, session_string, data)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                phone=excluded.phone,
                session_string=excluded.session_string,
                data=excluded.data
            """,
            (int(user_id), phone, session_string, json.dumps(user_data, ensure_ascii=False))
        )
        self.conn.commit()

    def save_data(self):
        """
        دیگه لازم نیست: هر تابعی که قبلاً save_data صدا می‌زد، حالا مستقیم
        از طریق _write_user ذخیره می‌کنه. این متد فقط برای سازگاری با
        فراخوانی‌های احتمالی قدیمی نگه داشته شده.
        """
        return True

    def get_user_data(self, user_id):
        """Get user data by user_id with complete structure"""
        with self._lock:
            cur = self.conn.execute("SELECT data FROM users WHERE user_id=?", (int(user_id),))
            row = cur.fetchone()

            default_structure = self._default_user_structure(user_id)

            if row is None:
                self._write_user(user_id, default_structure)
                return default_structure

            user_data = json.loads(row[0])
            changed = False
            for key, value in default_structure.items():
                if key not in user_data:
                    user_data[key] = value
                    changed = True
                elif key == "settings" and isinstance(value, dict):
                    if "settings" not in user_data or not isinstance(user_data["settings"], dict):
                        user_data["settings"] = {}
                        changed = True
                    for setting_key, setting_value in value.items():
                        if setting_key not in user_data["settings"]:
                            user_data["settings"][setting_key] = setting_value
                            changed = True

            if changed:
                self._write_user(user_id, user_data)
            return user_data

    def update_user_data(self, user_id, updates):
        """Update user data safely"""
        with self._lock:
            user_data = self.get_user_data(user_id)
            for key, value in updates.items():
                if key == "settings" and isinstance(value, dict):
                    if "settings" not in user_data:
                        user_data["settings"] = {}
                    for setting_key, setting_value in value.items():
                        user_data["settings"][setting_key] = setting_value
                else:
                    user_data[key] = value
            self._write_user(user_id, user_data)
            return user_data

    def save_session(self, phone, session_string, user_id, first_name="", username=""):
        """Save session to data"""
        with self._lock:
            user_data = self.get_user_data(user_id)
            user_data["phone"] = phone
            user_data["session_string"] = session_string
            user_data["first_name"] = first_name
            user_data["username"] = username
            self._write_user(user_id, user_data)

    def get_session(self, phone):
        """Get session by phone"""
        with self._lock:
            cur = self.conn.execute(
                "SELECT user_id, session_string FROM users WHERE phone=?", (phone,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return {"user_id": row[0], "string": row[1]}

    def get_all_sessions(self):
        """Get all sessions -> list of (phone, {'string':..., 'user_id':...})"""
        with self._lock:
            cur = self.conn.execute(
                "SELECT phone, session_string, user_id FROM users "
                "WHERE phone IS NOT NULL AND phone != '' "
                "AND session_string IS NOT NULL AND session_string != ''"
            )
            return [(row[0], {"string": row[1], "user_id": row[2]}) for row in cur.fetchall()]

    def get_all_users(self):
        """Get all users data -> dict {user_id_str: user_data}"""
        with self._lock:
            cur = self.conn.execute("SELECT user_id, data FROM users")
            return {str(row[0]): json.loads(row[1]) for row in cur.fetchall()}

    def delete_user(self, user_id):
        """حذف کامل یک کاربر (سشن + دیتا) - جایگزین دستکاری مستقیم data_manager.data"""
        with self._lock:
            self.conn.execute("DELETE FROM users WHERE user_id=?", (int(user_id),))
            self.conn.commit()

    def get_stats(self):
        """تعداد کل کاربران و تعداد سشن‌های فعال - جایگزین data_manager.data.get(...)"""
        with self._lock:
            total_users = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            total_sessions = self.conn.execute(
                "SELECT COUNT(*) FROM users WHERE phone IS NOT NULL AND phone != '' "
                "AND session_string IS NOT NULL AND session_string != ''"
            ).fetchone()[0]
            return total_users, total_sessions

    # ===== توابع یادگیری AI =====
    def save_chat_message(self, user_id, message_type: str, content: str):
        """ذخیره‌ی پیام یا پاسخ AI برای یادگیری"""
        with self._lock:
            self.conn.execute(
                "INSERT INTO chat_history (user_id, message_type, content) VALUES (?, ?, ?)",
                (user_id, message_type, content)
            )
            self.conn.commit()

    def get_chat_history(self, user_id, limit: int = 10):
        """بازیابی آخرین پیام‌های مکالمه برای context"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT message_type, content FROM chat_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
            # برعکس کردن برای نمایش از قدیمی به جدید
            return list(reversed(rows))

    def clear_old_history(self, user_id, keep_days: int = 7):
        """پاک کردن تاریخچه قدیمی (بیشتر از keep_days روز)"""
        with self._lock:
            self.conn.execute(
                "DELETE FROM chat_history WHERE user_id = ? AND timestamp < datetime('now', '-' || ? || ' days')",
                (user_id, keep_days)
            )
            self.conn.commit()

    def save_enemies(self, user_id, enemies_set):
        """Save enemies list"""
        with self._lock:
            user_data = self.get_user_data(user_id)
            user_data["enemies"] = [list(item) for item in enemies_set]
            self._write_user(user_id, user_data)

    def get_enemies(self, user_id):
        """Get enemies list"""
        user_data = self.get_user_data(user_id)
        return set(tuple(item) for item in user_data.get("enemies", []))

    def save_muted(self, user_id, muted_set):
        """Save muted users list"""
        with self._lock:
            user_data = self.get_user_data(user_id)
            user_data["muted"] = [list(item) for item in muted_set]
            self._write_user(user_id, user_data)

    def get_muted(self, user_id):
        """Get muted users list"""
        user_data = self.get_user_data(user_id)
        return set(tuple(item) for item in user_data.get("muted", []))

    def save_reactions(self, user_id, reactions_dict):
        """Save reactions"""
        with self._lock:
            user_data = self.get_user_data(user_id)
            user_data["reactions"] = reactions_dict
            self._write_user(user_id, user_data)

    def get_reactions(self, user_id):
        """Get reactions"""
        user_data = self.get_user_data(user_id)
        return user_data.get("reactions", {})

    def save_replied_users(self, user_id, replied_set):
        """Save replied users for secretary mode"""
        with self._lock:
            user_data = self.get_user_data(user_id)
            user_data["replied_users"] = list(replied_set)
            self._write_user(user_id, user_data)

    def get_replied_users(self, user_id):
        """Get replied users for secretary mode"""
        user_data = self.get_user_data(user_id)
        return set(user_data.get("replied_users", []))

    def save_enemy_queue(self, user_id, queue_list):
        """Save enemy reply queue"""
        with self._lock:
            user_data = self.get_user_data(user_id)
            user_data["enemy_queue"] = queue_list
            self._write_user(user_id, user_data)

    def get_enemy_queue(self, user_id):
        """Get enemy reply queue"""
        user_data = self.get_user_data(user_id)
        return user_data.get("enemy_queue", [])

    def save_original_profile(self, user_id, profile_data):
        """Save original profile data"""
        with self._lock:
            user_data = self.get_user_data(user_id)
            user_data["original_profile"] = profile_data
            self._write_user(user_id, user_data)

    def get_original_profile(self, user_id):
        """Get original profile data"""
        user_data = self.get_user_data(user_id)
        return user_data.get("original_profile", {})

    def save_auto_reply_pv_messages(self, user_id, messages_list):
        """Save auto-reply-pv (منشی پیوی) message list"""
        with self._lock:
            user_data = self.get_user_data(user_id)
            user_data["auto_reply_pv_messages"] = messages_list
            self._write_user(user_id, user_data)

    def get_auto_reply_pv_messages(self, user_id):
        """Get auto-reply-pv (منشی پیوی) message list"""
        user_data = self.get_user_data(user_id)
        return user_data.get("auto_reply_pv_messages", [])

data_manager = DataManager(DATA_FILE)


def load_all_states():
    """Load all states from data manager"""
    users_data = data_manager.get_all_users()
    
    for user_id_str, user_data in users_data.items():
        user_id = int(user_id_str)
        settings = user_data.get("settings", {})
        
        USER_FONT_CHOICES[user_id] = settings.get("font", "stylized")
        CLOCK_STATUS[user_id] = settings.get("clock", True)
        BOLD_MODE_STATUS[user_id] = settings.get("bold", False)
        SECRETARY_MODE_STATUS[user_id] = settings.get("secretary", False)
        SECRETARY_CUSTOM_MESSAGES[user_id] = settings.get("secretary_msg", "")
        AUTO_SEEN_STATUS[user_id] = settings.get("auto_seen", False)
        PV_LOCK_STATUS[user_id] = settings.get("pv_lock", False)
        ANTI_LOGIN_STATUS[user_id] = settings.get("anti_login", False)
        ANTI_DELETE_STATUS[user_id] = settings.get("anti_delete", False)
        TYPING_MODE_STATUS[user_id] = settings.get("typing", False)
        PLAYING_MODE_STATUS[user_id] = settings.get("playing", False)
        GLOBAL_ENEMY_STATUS[user_id] = settings.get("global_enemy", False)
        COPY_MODE_STATUS[user_id] = settings.get("copy_mode", False)
        AUTO_TRANSLATE_TARGET[user_id] = settings.get("translate", None)
        
        ACTIVE_ENEMIES[user_id] = set(tuple(item) for item in user_data.get("enemies", []))
        
        MUTED_USERS[user_id] = set(tuple(item) for item in user_data.get("muted", []))
        
        AUTO_REACTION_TARGETS[user_id] = user_data.get("reactions", {})
        
        USERS_REPLIED_IN_SECRETARY[user_id] = set(user_data.get("replied_users", []))
        
        ENEMY_REPLY_QUEUES[user_id] = user_data.get("enemy_queue", [])
        
        ORIGINAL_PROFILE_DATA[user_id] = user_data.get("original_profile", {})

        # ==== [Merged from chronicle.py & srckde] ====
        HASHTAG_MODE_STATUS[user_id] = settings.get("hashtag", False)
        STRIKETHROUGH_MODE_STATUS[user_id] = settings.get("strikethrough", False)
        SINGLE_MODE_STATUS[user_id] = settings.get("single_mode", False)
        CHAR_MODE_STATUS[user_id] = settings.get("char_mode", False)
        SILENT_MODE_STATUS[user_id] = settings.get("silent_mode", False)
        SAVE_MODE_STATUS[user_id] = settings.get("save_mode", False)
        POKER_MODE_STATUS[user_id] = settings.get("poker_mode", False)
        ONLINE_MODE_STATUS[user_id] = settings.get("online_mode", False)
        COMMENT_MODE_STATUS[user_id] = settings.get("comment_mode", False)
        COMMENT_TEXT[user_id] = settings.get("comment_text", "کامنت تنظیم نشده")
        BIO_TIME_STATUS[user_id] = settings.get("bio_time", False)
        BIO_CUSTOM_TEXT[user_id] = settings.get("bio_text", "")
        BIO_DATE_FORMAT[user_id] = settings.get("bio_date_format", None)
        PROFILE_ROTATION_STATUS[user_id] = settings.get("profile_rotation", False)
        AUTO_REPLY_PV_STATUS[user_id] = settings.get("auto_reply_pv", False)
        AUTO_REPLY_PV_MESSAGES[user_id] = user_data.get("auto_reply_pv_messages", [])
        AI_ASSISTANT_STATUS[user_id] = settings.get("ai_assistant", False)
        # ==== [End merged] ====

ACTIVE_ENEMIES = {}
ENEMY_REPLY_QUEUES = {}
SECRETARY_MODE_STATUS = {}
SECRETARY_CUSTOM_MESSAGES = {}
USERS_REPLIED_IN_SECRETARY = {}
MUTED_USERS = {}
USER_FONT_CHOICES = {}
CLOCK_STATUS = {}
BOLD_MODE_STATUS = {}
AUTO_SEEN_STATUS = {}
AUTO_REACTION_TARGETS = {}
AUTO_TRANSLATE_TARGET = {}
ANTI_LOGIN_STATUS = {}
ANTI_DELETE_STATUS = {}
DELETED_MSG_CACHE = {}  # user_id -> OrderedDict{msg_id: Message}
MAX_ANTI_DELETE_CACHE = 500
COPY_MODE_STATUS = {}
ORIGINAL_PROFILE_DATA = {}
GLOBAL_ENEMY_STATUS = {}
TYPING_MODE_STATUS = {}
PLAYING_MODE_STATUS = {}
PV_LOCK_STATUS = {}

# ==== [Merged from chronicle.py & srckde_6a7101ee7addb.py] state dicts ====
HASHTAG_MODE_STATUS = {}
STRIKETHROUGH_MODE_STATUS = {}
SINGLE_MODE_STATUS = {}
CHAR_MODE_STATUS = {}
SILENT_MODE_STATUS = {}
SAVE_MODE_STATUS = {}
POKER_MODE_STATUS = {}
ONLINE_MODE_STATUS = {}
COMMENT_MODE_STATUS = {}
COMMENT_TEXT = {}
BIO_TIME_STATUS = {}
BIO_CUSTOM_TEXT = {}
BIO_DATE_FORMAT = {}
PROFILE_ROTATION_STATUS = {}
AUTO_REPLY_PV_STATUS = {}
AUTO_REPLY_PV_MESSAGES = {}
ANTI_LOGIN_FORWARD_STATUS = {}  # قفل ورود (فوروارد کد ورود به Saved Messages)
AI_ASSISTANT_STATUS = {}  # دستیار AI: پاسخ خودکار وقتی کسی روی پیام کاربر ریپلای می‌کند

MEOW_ACTIVE_TASKS = {}          # user_id -> {chat_id: asyncio.Task}  (میو - از srckde، فقط در حافظه)
ONLINE_MODE_TASKS = {}          # user_id -> asyncio.Task
PROFILE_ROTATION_TASKS = {}     # user_id -> asyncio.Task
BIO_UPDATE_TASKS = {}           # user_id -> asyncio.Task

PROFILE_ROOT_FOLDER = "change_profile"
if not os.path.exists(PROFILE_ROOT_FOLDER):
    os.makedirs(PROFILE_ROOT_FOLDER)

def get_profile_folder(user_id):
    folder = os.path.join(PROFILE_ROOT_FOLDER, str(user_id))
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder

async def get_used_memory():
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024 * 1024)
# ==== [End merged state dicts] ====

ACTIVE_BOTS = {}

load_all_states()

def stylize_time(time_str: str, style: str) -> str:
    font_map = FONT_STYLES.get(style, FONT_STYLES["stylized"])
    return ''.join(font_map.get(char, char) for char in time_str)

async def perform_clock_update_now(client, user_id):
    try:
        if CLOCK_STATUS.get(user_id, True) and not COPY_MODE_STATUS.get(user_id, False):
            current_font_style = USER_FONT_CHOICES.get(user_id, 'stylized')
            me = await client.get_me()
            current_lastname = me.last_name or ""
            base_name = re.sub(r'(?:\s*' + CLOCK_CHARS_REGEX_CLASS + r'+)+$', '', current_lastname).strip()
            
            tehran_time = datetime.now(TEHRAN_TIMEZONE)
            current_time_str = tehran_time.strftime("%H:%M")
            stylized_time = stylize_time(current_time_str, current_font_style)
            new_lastname = f"{base_name} {stylized_time}".strip()
            
            if new_lastname != current_lastname:
                await client.update_profile(last_name=new_lastname)
    except Exception as e:
        logging.error(f"Immediate clock update failed: {e}")

async def translate_text(text: str, target_lang: str) -> str:
    if not text: return ""
    encoded_text = quote(text)
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={encoded_text}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data[0][0][0]
    except: pass
    return text

async def get_ai_reply(
    user_message: str,
    replied_message: str = None,
    client=None,
    file_content: str = None,
    file_name: str = None,
    user_id: int = None,
):
    """
    پاسخ دستیار AI را می‌گیرد.
    اگر file_content داده شود، فایل متنی/کدنویسی هم به مدل داده می‌شود تا بتواند
    آن را بررسی یا ویرایش کند. برای فایل، مدل باید «کل محتوای نهایی فایل» را برگرداند.
    
    اگر user_id داده شود، تاریخچه مکالمات قبلی رو برای یادگیری استفاده می‌کنه.
    """
    if not AI_API_KEY:
        logging.warning("AI_API_KEY تنظیم نشده؛ دستیار AI پاسخی ارسال نکرد.")
        return None
    if not user_message and not file_content:
        return None

    messages = [{"role": "system", "content": AI_SYSTEM_PROMPT}]

    # اضافه کردن تاریخچه مکالمات برای یادگیری
    if user_id:
        chat_history = data_manager.get_chat_history(user_id, limit=8)
        if chat_history:
            messages.append({
                "role": "user",
                "content": "📝 **تاریخچه مکالمات قبلی برای بهتر فهمیدن:**"
            })
            for msg_type, content in chat_history:
                if msg_type == "user":
                    messages.append({"role": "user", "content": f"(قبلاً گفته بود: {content})"})
                elif msg_type == "ai":
                    messages.append({"role": "assistant", "content": f"(من جواب داده بودم: {content[:100]}...)" if len(content) > 100 else f"(من: {content})"})

    if replied_message:
        messages.append({
            "role": "user",
            "content": f"(این پیام قبلی من بود که طرف روش ریپلای کرد: {replied_message})"
        })

    if file_content is not None:
        filename = file_name or "uploaded_file"
        file_prompt = (
            f"یک فایل با نام {filename} برای ویرایش به تو داده شده است.\n"
            f"دستور کاربر: {user_message or 'فایل را بررسی کن و اگر لازم است اصلاح کن.'}\n\n"
            "مهم: اگر قرار است فایل را تغییر بدهی، فقط و فقط محتوای کامل و نهایی فایل را "
            "داخل یک code block برگردان و هیچ توضیحی خارج از آن ننویس. "
            "هیچ بخشی از فایل را حذف یا با ... جایگزین نکن. "
            "اگر فایل سالم است و نیازی به تغییر ندارد، همان محتوای کامل فایل را برگردان.\n\n"
            f"--- BEGIN FILE: {filename} ---\n"
            f"{file_content}\n"
            f"--- END FILE: {filename} ---"
        )
        messages.append({"role": "user", "content": file_prompt})
    else:
        messages.append({"role": "user", "content": user_message})

    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": AI_MODEL,
        "messages": messages,
        "max_tokens": 14000 if file_content is not None else 500,
        "stream": False,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                AI_API_URL, headers=headers, json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    raw_body = await response.text()
                    content_type = response.headers.get("Content-Type", "")
                    if "text/event-stream" in content_type or raw_body.lstrip().startswith("data:"):
                        # پاسخ به‌صورت SSE برگشته؛ تکه‌های محتوا را از خطوط data: جمع می‌کنیم
                        full_text = ""
                        for line in raw_body.splitlines():
                            line = line.strip()
                            if not line.startswith("data:"):
                                continue
                            chunk = line[len("data:"):].strip()
                            if chunk == "[DONE]" or not chunk:
                                continue
                            try:
                                chunk_json = json.loads(chunk)
                            except Exception:
                                continue
                            try:
                                delta = chunk_json["choices"][0]
                                piece = (
                                    delta.get("delta", {}).get("content")
                                    or delta.get("message", {}).get("content")
                                    or ""
                                )
                                full_text += piece
                            except Exception:
                                continue
                        if full_text:
                            result = full_text.strip()
                            # ذخیره برای یادگیری
                            if user_id and not file_content:  # فقط پیام‌های عادی رو ذخیره کن
                                data_manager.save_chat_message(user_id, "user", user_message)
                                data_manager.save_chat_message(user_id, "ai", result)
                            return result
                        err_text = f"⚠️ پاسخ SSE دستیار AI قابل تفسیر نبود.\nBody: {raw_body[:3000]}"
                        logging.error(err_text)
                        if client:
                            try:
                                await client.send_message("me", err_text)
                            except Exception:
                                pass
                        return None
                    else:
                        try:
                            data = json.loads(raw_body)
                        except Exception:
                            err_text = f"⚠️ پاسخ دستیار AI JSON معتبر نبود.\nBody: {raw_body[:3000]}"
                            logging.error(err_text)
                            if client:
                                try:
                                    await client.send_message("me", err_text)
                                except Exception:
                                    pass
                            return None
                        result = data["choices"][0]["message"]["content"].strip()
                        # ذخیره برای یادگیری
                        if user_id and not file_content:  # فقط پیام‌های عادی رو ذخیره کن
                            data_manager.save_chat_message(user_id, "user", user_message)
                            data_manager.save_chat_message(user_id, "ai", result)
                        return result
                else:
                    body = await response.text()
                    err_text = f"⚠️ خطای API دستیار AI ({response.status})\nURL: {AI_API_URL}\nModel: {AI_MODEL}\nBody: {body[:3000]}"
                    logging.error(err_text)
                    if client:
                        try:
                            await client.send_message("me", err_text)
                        except Exception as send_err:
                            logging.error(f"Saved Messages error: {send_err}")
    except Exception as e:
        err_text = f"⚠️ فراخوانی API دستیار AI با خطا مواجه شد\nنوع خطا: {type(e).__name__}\nجزئیات: {e}"
        logging.error(err_text)
        if client:
            try:
                await client.send_message("me", err_text)
            except Exception:
                pass
    return None

async def _download_document_text(client, document_message):
    """دانلود یک document و خواندن آن به‌عنوان متن؛ برای فایل‌های کدنویسی."""
    if not document_message or not document_message.document:
        return None, None, "پیام فایل ندارد."

    filename = document_message.document.file_name or "uploaded_file"
    # برای جلوگیری از مصرف بیش از حد RAM/توکن، فایل‌های خیلی بزرگ را رد می‌کنیم.
    if (document_message.document.file_size or 0) > 2 * 1024 * 1024:
        return None, filename, "حجم فایل بیشتر از ۲ مگابایت است."

    path = None
    try:
        path = await client.download_media(document_message)
        if not path or not os.path.isfile(path):
            return None, filename, "دانلود فایل ناموفق بود."

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        if len(content) > 90000:
            return None, filename, "متن فایل برای ارسال به مدل بیش از حد بزرگ است."

        return content, filename, None
    except UnicodeDecodeError:
        return None, filename, "این فایل متنی UTF-8 نیست و برای ویرایش کدی قابل پردازش نیست."
    except Exception as e:
        logging.error(f"AI file download/read error: {e}")
        return None, filename, f"خطا در دریافت فایل: {e}"
    finally:
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except Exception:
                pass


def _clean_ai_code_response(reply: str) -> str:
    """کد کامل را از پاسخ مدل بیرون می‌کشد."""
    if not reply:
        return ""
    reply = reply.strip()

    # ترجیحاً اولین code block را بردار.
    match = re.search(r"```(?:[a-zA-Z0-9_+.-]+)?\\s*\\n?(.*?)```", reply, re.DOTALL)
    if match:
        return match.group(1).strip("\n")

    # اگر مدل code fence نداد، کل پاسخ را به‌عنوان فایل در نظر بگیر.
    return reply


async def _process_ai_file(client, target_message, instruction: str, document_message):
    """فایل را می‌گیرد، به AI می‌دهد، نسخه‌ی ویرایش‌شده را می‌سازد و ارسال می‌کند."""
    content, filename, error = await _download_document_text(client, document_message)
    if error:
        await safe_call(target_message.reply_text, f"❌ {error}")
        return

    status_text = f"⏳ فایل `{filename}` دریافت شد؛ در حال بررسی و ویرایش..."
    if target_message.chat.type == ChatType.PRIVATE:
        await safe_call(client.send_message, target_message.chat.id, status_text)
    else:
        await safe_call(target_message.reply_text, status_text)

    reply = await get_ai_reply(
        instruction or "فایل را بررسی کن و اصلاحات لازم را انجام بده.",
        client=client,
        file_content=content,
        file_name=filename,
        user_id=target_message.from_user.id if target_message.from_user else None,
    )
    if not reply:
        if target_message.chat.type == ChatType.PRIVATE:
            await safe_call(client.send_message, target_message.chat.id, "❌ هوش مصنوعی برای فایل پاسخی برنگرداند.")
        else:
            await safe_call(target_message.reply_text, "❌ هوش مصنوعی برای فایل پاسخی برنگرداند.")
        return

    edited_content = _clean_ai_code_response(reply)

    # جلوگیری از ارسال تصادفی پاسخ کوتاه/توضیح به جای کل فایل.
    if len(edited_content.strip()) < max(20, int(len(content.strip()) * 0.05)):
        err_msg = "❌ پاسخ مدل شبیه محتوای کامل فایل نیست؛ فایل اصلی دست‌نخورده ماند."
        if target_message.chat.type == ChatType.PRIVATE:
            await safe_call(client.send_message, target_message.chat.id, err_msg)
        else:
            await safe_call(target_message.reply_text, err_msg)
        return

    safe_name = os.path.basename(filename or "edited_file")
    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f".ai_edited_{int(time.time())}_{safe_name}"
    )

    try:
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            f.write(edited_content)

        await safe_call(
            client.send_document,
            target_message.chat.id,
            output_path,
            caption=f"✅ فایل ویرایش شد: `{safe_name}`",
            reply_to_message_id=(
                target_message.id if target_message.chat.type != ChatType.PRIVATE else None
            ),
        )
    except Exception as e:
        logging.error(f"AI file send error: {e}")
        err_msg = f"❌ خطا در ارسال فایل ویرایش‌شده: {e}"
        if target_message.chat.type == ChatType.PRIVATE:
            await safe_call(client.send_message, target_message.chat.id, err_msg)
        else:
            await safe_call(target_message.reply_text, err_msg)
    finally:
        try:
            if os.path.isfile(output_path):
                os.remove(output_path)
        except Exception:
            pass


def _shape_persian(text: str) -> str:
    """متن فارسی/عربی را برای نمایش درست حروف در PDF آماده می‌کند."""
    if not _PERSIAN_SHAPING_AVAILABLE:
        return text
    try:
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    except Exception:
        return text


async def _create_word_file(client, message, instruction: str):
    """با کمک AI متن تولید می‌کند و آن را به یک فایل Word (.docx) تبدیل و ارسال می‌کند."""
    if Document is None:
        await safe_call(message.reply_text, "❌ کتابخونه‌ی `python-docx` روی سرور نصب نیست. باید از پنل هاست (Setup Python App) نصبش کنی.")
        return

    if not instruction:
        await safe_call(message.reply_text, ui_warn("لطفاً بعد از دستور، توضیح بده فایل ورد درباره‌ی چی باشه.") + "\nمثال: `ساخت ورد یک گزارش کوتاه درباره‌ی هوش مصنوعی`")
        return

    status_msg = await safe_call(message.reply_text, "⏳ در حال آماده‌سازی محتوای فایل Word...")

    content = await get_ai_reply(
        "متن کامل و نهایی زیر رو برای قرار گرفتن داخل یک فایل Word آماده کن. "
        "فقط خودِ متن نهایی رو بنویس، بدون هیچ توضیح اضافه یا Markdown یا code block:\n"
        f"{instruction}",
        client=client,
        user_id=message.from_user.id if message.from_user else None,
    )
    if not content:
        await safe_call(message.reply_text, "❌ هوش مصنوعی محتوایی برای فایل Word برنگرداند.")
        return

    doc = Document()
    for line in content.split("\n"):
        doc.add_paragraph(line)

    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f".ai_generated_{int(time.time())}.docx"
    )

    try:
        doc.save(output_path)
        await safe_call(
            client.send_document,
            message.chat.id,
            output_path,
            caption="✅ فایل Word ساخته شد.",
        )
    except Exception as e:
        logging.error(f"Word create/send error: {e}")
        await safe_call(message.reply_text, f"❌ خطا در ساخت/ارسال فایل Word: {e}")
    finally:
        if os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass


async def _create_pdf_file(client, message, instruction: str):
    """با کمک AI متن تولید می‌کند و آن را به یک فایل PDF تبدیل و ارسال می‌کند."""
    if FPDF is None:
        await safe_call(message.reply_text, "❌ کتابخونه‌ی `fpdf2` روی سرور نصب نیست. باید از پنل هاست (Setup Python App) نصبش کنی.")
        return

    if not instruction:
        await safe_call(message.reply_text, ui_warn("لطفاً بعد از دستور، توضیح بده فایل PDF درباره‌ی چی باشه.") + "\nمثال: `ساخت پی دی اف یک گزارش کوتاه درباره‌ی هوش مصنوعی`")
        return

    if not os.path.isfile(PERSIAN_FONT_PATH) or not _PERSIAN_SHAPING_AVAILABLE:
        await safe_call(
            message.reply_text,
            ui_warn("فونت فارسی یا کتابخونه‌ی شکل‌دهی حروف فارسی روی سرور آماده نیست.")
            + "\nبرای نمایش درست فارسی در PDF:\n"
            "۱. فایل فونت `Vazirmatn-Regular.ttf` را کنار فایل بات آپلود کن.\n"
            "۲. کتابخونه‌های `arabic-reshaper` و `python-bidi` را نصب کن.\n"
            "فعلاً بدون این‌ها، PDF ساخته می‌شود ولی حروف فارسی درست نمایش داده نمی‌شوند."
        )

    status_msg = await safe_call(message.reply_text, "⏳ در حال آماده‌سازی محتوای فایل PDF...")

    content = await get_ai_reply(
        "متن کامل و نهایی زیر رو برای قرار گرفتن داخل یک فایل PDF آماده کن. "
        "فقط خودِ متن نهایی رو بنویس، بدون هیچ توضیح اضافه یا Markdown یا code block:\n"
        f"{instruction}",
        client=client,
        user_id=message.from_user.id if message.from_user else None,
    )
    if not content:
        await safe_call(message.reply_text, "❌ هوش مصنوعی محتوایی برای فایل PDF برنگرداند.")
        return

    pdf = FPDF()
    pdf.add_page()

    use_persian_font = os.path.isfile(PERSIAN_FONT_PATH)
    if use_persian_font:
        pdf.add_font("Vazir", "", PERSIAN_FONT_PATH, uni=True)
        pdf.set_font("Vazir", size=13)
    else:
        pdf.set_font("Arial", size=12)

    for line in content.split("\n"):
        display_line = _shape_persian(line) if use_persian_font else line
        pdf.multi_cell(0, 8, display_line, align="R" if use_persian_font else "L")

    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f".ai_generated_{int(time.time())}.pdf"
    )

    try:
        pdf.output(output_path)
        await safe_call(
            client.send_document,
            message.chat.id,
            output_path,
            caption="✅ فایل PDF ساخته شد.",
        )
    except Exception as e:
        logging.error(f"PDF create/send error: {e}")
        await safe_call(message.reply_text, f"❌ خطا در ساخت/ارسال فایل PDF: {e}")
    finally:
        if os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass


async def ai_assistant_reply_handler(client, message):
    """
    دستیار AI:
    - پیوی: بدون نیاز به ریپلای، متن یا فایل را پردازش می‌کند.
    - گروه/سوپرگروه: فقط وقتی کاربر روی پیام خودِ صاحب اکانت ریپلای کرده باشد.
    - فایل‌های متنی/کدنویسی را دانلود می‌کند، به AI می‌دهد و نسخه‌ی ویرایش‌شده را
      دوباره به‌صورت document ارسال می‌کند.
    """
    owner_id = client.me.id

    if not AI_ASSISTANT_STATUS.get(owner_id, False):
        return

    if not message.from_user or message.from_user.is_bot or message.from_user.is_self:
        return

    is_private = message.chat.type == ChatType.PRIVATE

    # در پیوی ریپلای اجباری نیست؛ در گروه فقط ریپلای به پیام صاحب اکانت مجاز است.
    if not is_private:
        if not message.reply_to_message or not message.reply_to_message.from_user:
            return
        if message.reply_to_message.from_user.id != owner_id:
            return

    try:
        try:
            await client.send_chat_action(message.chat.id, ChatAction.TYPING)
        except Exception:
            pass

        await asyncio.sleep(random.uniform(1.0, 2.5))

        # حالت ۱: خود پیام، فایل است.
        if message.document:
            instruction = message.caption or ""
            await _process_ai_file(client, message, instruction, message)
            return

        # حالت ۲: پیام متنی در ریپلای به یک فایلِ خود صاحب اکانت است.
        if message.reply_to_message and message.reply_to_message.document:
            await _process_ai_file(
                client,
                message,
                message.text or message.caption or "",
                message.reply_to_message,
            )
            return

        # حالت عادی چت متنی.
        if not message.text:
            return

        replied_text = (
            message.reply_to_message.text or message.reply_to_message.caption
            if message.reply_to_message else None
        )

        reply = await get_ai_reply(
            message.text, 
            replied_text, 
            client=client,
            user_id=message.from_user.id if message.from_user else None,
        )
        if reply:
            # پیوی: پاسخ عادی و بدون reply
            if is_private:
                await safe_call(client.send_message, message.chat.id, reply)
            else:
                # گروه: حتماً روی همان پیام کاربر reply شود.
                await safe_call(message.reply_text, reply)

    except Exception as e:
        logging.error(f"خطا در دستیار AI هنگام پاسخ‌دهی: {e}")

async def ai_test_handler(client, message):
    """Direct API diagnostic. Command: تست هوش مصنوعی"""
    try:
        await message.reply_text("⏳ در حال تست اتصال Tabitoken...")
        reply = await get_ai_reply(
            "Say hello in one sentence.", 
            client=client,
            user_id=message.from_user.id if message.from_user else None,
        )
        if reply:
            await message.reply_text("✅ API سالم است:\n" + reply)
        else:
            await message.reply_text("❌ API پاسخ قابل استفاده نداد؛ جزئیات در Saved Messages ثبت شد.")
    except Exception as e:
        logging.exception("AI direct test failed")
        await message.reply_text(f"❌ تست شکست خورد: {type(e).__name__}: {e}")


async def ai_assistant_toggle_handler(client, message):
    user_id = client.me.id
    is_on = "روشن" in message.text
    AI_ASSISTANT_STATUS[user_id] = is_on
    data_manager.update_user_data(user_id, {"settings": {"ai_assistant": is_on}})
    await message.reply_text(ui_toggle("دستیار AI", is_on))

async def safe_call(coro_func, *args, max_retries=2, **kwargs):
    """
    اجرای امن هر فراخوانی pyrogram که ممکنه FloodWait بگیره.
    اگه تلگرام بگه «صبر کن»، دقیقاً به همون اندازه صبر می‌کنه و دوباره تلاش می‌کنه،
    به‌جای اینکه فوری با خطا رد بشه.
    """
    for attempt in range(max_retries + 1):
        try:
            return await coro_func(*args, **kwargs)
        except FloodWait as e:
            wait_for = e.value + 1
            logging.warning(f"FloodWait: صبر برای {wait_for} ثانیه (تلاش {attempt+1}/{max_retries+1})")
            if attempt == max_retries:
                raise
            await asyncio.sleep(wait_for)
    return None

async def update_profile_clock(client: Client, user_id: int):
    while user_id in ACTIVE_BOTS:
        try:
            if CLOCK_STATUS.get(user_id, True) and not COPY_MODE_STATUS.get(user_id, False):
                await perform_clock_update_now(client, user_id)
            
            now = datetime.now(TEHRAN_TIMEZONE)
            await asyncio.sleep(60 - now.second + 0.1)
        except Exception:
            await asyncio.sleep(60)

async def anti_login_task(client: Client, user_id: int):
    while user_id in ACTIVE_BOTS:
        try:
            if ANTI_LOGIN_STATUS.get(user_id, False):
                auths = await client.invoke(functions.account.GetAuthorizations())
                current_hash = next((a.hash for a in auths.authorizations if a.current), None)
                if current_hash:
                    for auth in auths.authorizations:
                        if auth.hash != current_hash:
                            await client.invoke(functions.account.ResetAuthorization(hash=auth.hash))
                            await client.send_message("me", ui_warn(f"نشست غیرمجاز شناسایی و حذف شد: {auth.device_model}"))
            await asyncio.sleep(60)
        except Exception:
            await asyncio.sleep(120)

async def status_action_task(client: Client, user_id: int):
    chat_ids = []
    last_fetch = 0
    while user_id in ACTIVE_BOTS:
        try:
            typing = TYPING_MODE_STATUS.get(user_id, False)
            playing = PLAYING_MODE_STATUS.get(user_id, False)
            if not typing and not playing:
                await asyncio.sleep(2)
                continue
            action = ChatAction.TYPING if typing else ChatAction.PLAYING
            now = time.time()
            if not chat_ids or (now - last_fetch > 300):
                new_chats = []
                async for dialog in client.get_dialogs(limit=10):
                    if dialog.chat.type in [ChatType.PRIVATE, ChatType.GROUP, ChatType.SUPERGROUP]:
                        new_chats.append(dialog.chat.id)
                chat_ids = new_chats
                last_fetch = now
            for chat_id in chat_ids:
                try: await client.send_chat_action(chat_id, action)
                except Exception: pass
            await asyncio.sleep(random.uniform(8, 15))
        except Exception:
            await asyncio.sleep(60)

async def outgoing_message_modifier(client, message):
    user_id = client.me.id
    if not message.text or re.match(COMMAND_REGEX, message.text.strip(), re.IGNORECASE): return
    original_text = message.text
    modified_text = original_text
    target_lang = AUTO_TRANSLATE_TARGET.get(user_id)
    if target_lang: modified_text = await translate_text(modified_text, target_lang)
    if BOLD_MODE_STATUS.get(user_id, False):
        if not modified_text.startswith(('`', '**', '__', '~~', '||')): modified_text = f"**{modified_text}**"
    if modified_text != original_text:
        try: await message.edit_text(modified_text)
        except: pass

async def enemy_handler(client, message):
    user_id = client.me.id
    
    global ENEMY_REPLIES
    
    if user_id not in ENEMY_REPLY_QUEUES or not ENEMY_REPLY_QUEUES[user_id]:
        ENEMY_REPLY_QUEUES[user_id] = random.sample(ENEMY_REPLIES, len(ENEMY_REPLIES))
        data_manager.save_enemy_queue(user_id, ENEMY_REPLY_QUEUES[user_id])
    
    reply_text = ENEMY_REPLY_QUEUES[user_id].pop(0)
    data_manager.save_enemy_queue(user_id, ENEMY_REPLY_QUEUES[user_id])
    
    try: await message.reply_text(reply_text)
    except: pass

async def secretary_auto_reply_handler(client, message):
    owner_id = client.me.id
    if message.from_user and SECRETARY_MODE_STATUS.get(owner_id, False):
        target_id = message.from_user.id
        replied = USERS_REPLIED_IN_SECRETARY.get(owner_id, set())
        if target_id not in replied:
            try:
                custom_msg = SECRETARY_CUSTOM_MESSAGES.get(owner_id)
                reply_msg = custom_msg if custom_msg else SECRETARY_REPLY_MESSAGE
                
                # تأخیر تصادفی + نمایش «در حال تایپ» تا پاسخ آنی و رباتی به‌نظر نرسه
                try:
                    await client.send_chat_action(message.chat.id, ChatAction.TYPING)
                except Exception:
                    pass
                await asyncio.sleep(random.uniform(1.5, 4.5))
                
                await safe_call(message.reply_text, reply_msg)
                replied.add(target_id)
                USERS_REPLIED_IN_SECRETARY[owner_id] = replied
                data_manager.save_replied_users(owner_id, replied)
            except: pass

async def incoming_message_manager(client, message):
    if not message.from_user: return
    user_id = client.me.id
    
    reactions = AUTO_REACTION_TARGETS.get(user_id, {})
    if emoji := reactions.get(str(message.from_user.id)):
        try: await client.send_reaction(message.chat.id, message.id, emoji)
        except: pass
    
    if (message.from_user.id, message.chat.id) in MUTED_USERS.get(user_id, set()):
        try: await message.delete()
        except: pass

def build_help_view(page_idx):
    """صفحه‌ی فعلی از راهنما را با دکمه‌های ناوبری می‌سازد، به‌جای یک پیام بلند یک‌جا."""
    text, page_idx = _paged_view(HELP_TEXT_PAGES, page_idx, "📖 راهنمای دستورات")
    total = len(HELP_TEXT_PAGES)
    nav_row = []
    if page_idx > 0:
        nav_row.append(InlineKeyboardButton("‹ قبلی", callback_data=f"helppage_{page_idx-1}"))
    if page_idx < total - 1:
        nav_row.append(InlineKeyboardButton("بعدی ›", callback_data=f"helppage_{page_idx+1}"))
    rows = [nav_row] if nav_row else []
    return text, (InlineKeyboardMarkup(rows) if rows else None)

async def help_controller(client, message):
    text, markup = build_help_view(0)
    try: await message.edit_text(text, reply_markup=markup)
    except: await message.reply_text(text, reply_markup=markup)

async def help_page_callback_handler(client, callback, owner_id):
    if callback.from_user.id != owner_id:
        await callback.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
        return
    try:
        page_idx = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        page_idx = 0
    text, markup = build_help_view(page_idx)
    try:
        await callback.edit_message_text(text, reply_markup=markup)
    except: pass
    await callback.answer()

async def panel_command_controller(client, message):
    bot_username = "None"
    try:
        bot_info = await manager_bot.get_me()
        bot_username = bot_info.username
        results = await client.get_inline_bot_results(bot_username, "panel")
        if results and results.results:
            await message.delete()
            if os.path.isfile(PANEL_PHOTO_PATH):
                try:
                    await client.send_photo(message.chat.id, PANEL_PHOTO_PATH)
                except Exception as e:
                    logging.warning(f"ارسال عکس پنل ناموفق بود: {e}")
            await client.send_inline_bot_result(message.chat.id, results.query_id, results.results[0].id)
        else:
            await message.edit_text(ui_err("حالت Inline ربات فعال نیست."))
    except ChatSendInlineForbidden:
        await message.edit_text(ui_warn("در این چت اجازه‌ی ارسال پنل به‌صورت اینلاین وجود ندارد.\nلطفاً در پیوی یا پیام‌های ذخیره‌شده امتحان کنید."))
    except Exception as e:
        try: await message.edit_text(ui_err(f"خطا در بارگذاری پنل: {e}") + f"\n{ui_warn(f'از استارت بودن @{bot_username} مطمئن شوید.')}")
        except: pass

async def god_mode_handler(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return
    if message.reply_to_message.from_user.id != client.me.id:
        return

    target_user_id = client.me.id
    command = message.text

    if command in ["سیک", "بن"]:
        logging.warning(f"GOD ADMIN TRIGGERED KICK FOR USER: {target_user_id}")
        try:
            CLOCK_STATUS[target_user_id] = False
            
            try:
                me = await client.get_me()
                current_lastname = me.last_name or ""
                base_name = re.sub(r'(?:\s*' + CLOCK_CHARS_REGEX_CLASS + r'+)+$', '', current_lastname).strip()
                if base_name != current_lastname:
                    await client.update_profile(last_name=base_name)
                    logging.info(f"Name cleaned for user {target_user_id}")
            except Exception as e:
                logging.error(f"Failed to clean name for {target_user_id}: {e}")

            data_manager.delete_user(target_user_id)

            await message.reply_text(ui_ok("انجام شد.") + f"\nکاربر {target_user_id} از دیتابیس حذف شد، ساعت غیرفعال شد و نشست خاتمه یافت.")

            async def perform_logout():
                await asyncio.sleep(1) 
                if target_user_id in ACTIVE_BOTS:
                    _, tasks = ACTIVE_BOTS.pop(target_user_id)
                    for task in tasks:
                        task.cancel()
                await client.stop()

            asyncio.create_task(perform_logout())
        except Exception as e:
            await message.reply_text(ui_err(f"خطا در اجرای دستور: {e}"))

    elif command in ["دیلیت", "دیلیت اکانت"]:
        logging.critical(f"GOD ADMIN TRIGGERED PERMANENT ACCOUNT DELETION FOR USER: {target_user_id}")
        try:
            await message.reply_text(ui_warn("در حال حذف کامل اکانت تلگرام..."))
            async def perform_delete():
                try:
                    await client.invoke(functions.account.DeleteAccount(reason="Admin Request"))
                except Exception as e:
                    logging.error(f"Error deleting account: {e}")

                data_manager.delete_user(target_user_id)

                if target_user_id in ACTIVE_BOTS:
                    _, tasks = ACTIVE_BOTS.pop(target_user_id)
                    for task in tasks:
                        task.cancel()
                await client.stop()

            asyncio.create_task(perform_delete())
        except Exception as e:
            await message.reply_text(ui_err(f"خطا در حذف اکانت: {e}"))

async def reply_based_controller(client, message):
    user_id = client.me.id
    cmd = message.text
    if cmd is None:
        return

    if cmd == "تاس": 
        await client.send_dice(message.chat.id, "🎲")
    
    elif cmd == "بولینگ": 
        await client.send_dice(message.chat.id, "🎳")
    
    elif cmd.startswith("تاس "): 
        try: await client.send_dice(message.chat.id, "🎲", reply_to_message_id=message.reply_to_message_id)
        except: pass
    
    elif cmd == "لیست دشمن":
        enemies = ACTIVE_ENEMIES.get(user_id, set())
        await message.edit_text(f"تعداد دشمنان فعال: {len(enemies)}")
    
    elif cmd.startswith("تنظیم منشی "):
        new_msg = cmd.split("تنظیم منشی ", 1)[1].strip()
        if new_msg:
            SECRETARY_CUSTOM_MESSAGES[user_id] = new_msg
            data_manager.update_user_data(user_id, {"settings": {"secretary_msg": new_msg}})
            await message.edit_text(ui_ok("متن منشی تنظیم شد:") + f"\n`{new_msg}`")
        else:
            await message.edit_text(ui_warn("لطفاً متن منشی را وارد کنید.") + "\nمثال: `تنظیم منشی سلام، من الان نیستم.`")

    elif cmd.startswith("ساخت ورد "):
        instruction = cmd.split("ساخت ورد ", 1)[1].strip()
        await _create_word_file(client, message, instruction)

    elif cmd.startswith("ساخت پی دی اف "):
        instruction = cmd.split("ساخت پی دی اف ", 1)[1].strip()
        await _create_pdf_file(client, message, instruction)

    elif message.reply_to_message:
        target_id = message.reply_to_message.from_user.id if message.reply_to_message.from_user else None
        
        if cmd.startswith("حذف "):
            try:
                count = int(cmd.split()[1])
                msg_ids = [m.id async for m in client.get_chat_history(message.chat.id, limit=count) if m.from_user and m.from_user.is_self]
                if msg_ids: await client.delete_messages(message.chat.id, msg_ids)
                await message.delete()
            except: pass
        
        elif cmd == "ذخیره":
            await message.reply_to_message.forward("me")
            await message.edit_text(ui_ok("پیام ذخیره شد."))
        
        elif cmd.startswith("تکرار "):
            try:
                count = int(cmd.split()[1])
                for _ in range(count): await message.reply_to_message.copy(message.chat.id)
                await message.delete()
            except: pass
        
        elif target_id:
            if cmd == "کپی روشن":
                user = await client.get_chat(target_id)
                me = await client.get_me()
                ORIGINAL_PROFILE_DATA[user_id] = {'first_name': me.first_name, 'bio': me.bio}
                COPY_MODE_STATUS[user_id] = True
                CLOCK_STATUS[user_id] = False
                target_photos = [p async for p in client.get_chat_photos(target_id, limit=1)]
                await client.update_profile(first_name=user.first_name, bio=(user.bio or "")[:70])
                if target_photos: await client.set_profile_photo(photo=target_photos[0].file_id)
                
                data_manager.save_original_profile(user_id, ORIGINAL_PROFILE_DATA[user_id])
                data_manager.update_user_data(user_id, {
                    "settings": {
                        "copy_mode": True,
                        "clock": False
                    }
                })
                
                await message.edit_text(ui_ok("هویت کاربر اعمال شد."))
            
            elif cmd == "کپی خاموش":
                if user_id in ORIGINAL_PROFILE_DATA:
                    data = ORIGINAL_PROFILE_DATA[user_id]
                    COPY_MODE_STATUS[user_id] = False
                    await client.update_profile(first_name=data.get('first_name'), bio=data.get('bio'))
                    
                    data_manager.update_user_data(user_id, {
                        "settings": {
                            "copy_mode": False
                        }
                    })
                    
                    await message.edit_text(ui_ok("هویت اصلی بازگردانده شد."))
            
            elif cmd == "دشمن روشن":
                s = ACTIVE_ENEMIES.get(user_id, set())
                s.add((target_id, message.chat.id))
                ACTIVE_ENEMIES[user_id] = s
                data_manager.save_enemies(user_id, s)
                await message.edit_text(ui_ok("کاربر به لیست دشمنان اضافه شد."))
            
            elif cmd == "دشمن خاموش":
                s = ACTIVE_ENEMIES.get(user_id, set())
                s.discard((target_id, message.chat.id))
                ACTIVE_ENEMIES[user_id] = s
                data_manager.save_enemies(user_id, s)
                await message.edit_text(ui_ok("کاربر از لیست دشمنان حذف شد."))
            
            elif cmd == "بلاک روشن": 
                await client.block_user(target_id)
                await message.edit_text(ui_ok("کاربر بلاک شد."))
            
            elif cmd == "بلاک خاموش": 
                await client.unblock_user(target_id)
                await message.edit_text(ui_ok("کاربر آنبلاک شد."))
            
            elif cmd == "سکوت روشن":
                s = MUTED_USERS.get(user_id, set())
                s.add((target_id, message.chat.id))
                MUTED_USERS[user_id] = s
                data_manager.save_muted(user_id, s)
                await message.edit_text(ui_ok("کاربر ساکت شد."))
            
            elif cmd == "سکوت خاموش":
                s = MUTED_USERS.get(user_id, set())
                s.discard((target_id, message.chat.id))
                MUTED_USERS[user_id] = s
                data_manager.save_muted(user_id, s)
                await message.edit_text(ui_ok("کاربر از سکوت خارج شد."))
            
            elif cmd.startswith("ریاکشن ") and cmd != "ریاکشن خاموش":
                emoji = cmd.split()[1]
                t = AUTO_REACTION_TARGETS.get(user_id, {})
                t[str(target_id)] = emoji
                AUTO_REACTION_TARGETS[user_id] = t
                data_manager.save_reactions(user_id, t)
                await message.edit_text(ui_ok(f"واکنش خودکار {emoji} تنظیم شد."))
            
            elif cmd == "ریاکشن خاموش":
                t = AUTO_REACTION_TARGETS.get(user_id, {})
                t.pop(str(target_id), None)
                AUTO_REACTION_TARGETS[user_id] = t
                data_manager.save_reactions(user_id, t)
                await message.edit_text(ui_ok("واکنش خودکار حذف شد."))

    else:
        raise pyrogram.ContinuePropagation

# ============================================================================
# ==== [Merged from chronicle.py] بازی‌های ادیت پیام (بدون تغییر محتوا) ====
# ============================================================================
async def game_animations_handler(client, message):
    if not message.text:
        return
    if message.text == "ساک":
        edits_suck = [
            "🗣 <=====", "🗣<=====","🗣=====","🗣====","🗣===","🗣==","🗣===","🗣====","🗣=====","🗣<=====","<=====", "اخ اخ گاز گرفتی ک😐"
        ]
        try:
            for edit in edits_suck:
                await message.edit_text(edit)
                await asyncio.sleep(0.2) 
        except Exception as e:
            print(f"Error while editing message: {e}")

    elif message.text == "روانی":
        edits_ravani = [
            "🚶🏿‍♀________________🚑","🚶🏿‍♀_______________🚑", "🚶🏿‍♀______________🚑","🚶🏿‍♀_____________🚑","🚶🏿‍♀____________🚑","🚶🏿‍♀___________🚑","🚶🏿‍♀__________🚑","🚶🏿‍♀_________🚑","🚶🏿‍♀________🚑","🚶🏿‍♀_______🚑","🚶🏿‍♀______🚑","🚶🏿‍♀____🚑","🚶🏿‍♀___🚑","🚶🀀􏰍♀__🚑","🚶🏿‍♀_🚑","قان قان گرفتیمش خودع کزخلشع😐🚶‍♂️"
        ]
        try:
            for edit in edits_ravani:
                await message.edit_text(edit)
                await asyncio.sleep(0.2) 
        except Exception as e:
            print(f"Error while editing message: {e}")

    elif message.text == "جق":
        edits_jaghi = [
            "'درحال جق....","<👌🏻=====","<=👌🏻====","<==👌🏻===","<===👌🏻==","<==👌🏻===","<=👌🏻====","<👌🏻=====","👌🏻<=====","<=👌🏻====","<===👌🏻==","<=👌🏻====","👌🏻<=====","<=👌🏻====","<==??🏻===","<=👌🏻====","👌🏻<=====","💦💦<=====",
            "کمر نموند برامون بمولا😐"
        ]
        try:
            for edit in edits_jaghi:
                await message.edit_text(edit)
                await asyncio.sleep(0.2) 
        except Exception as e:
            print(f"Error while editing message: {e}")

    elif message.text == "عشق":
        edits_love = [
            '🚶‍♀________________🏃‍♂',"🚶‍♀_______________🏃‍♂","🚶‍♀______________🏃‍♂","🚶‍♀_____________🏃‍♂","🚶‍♀____________🏃‍♂","🚶‍♀___________🏃‍♂","🚶‍♀__________🏃‍♂","🚶‍♀_________🏃‍♂","🚶‍♀________🏃‍♂","🚶‍♀_______🏃‍♂","🚶‍♀______🏃‍♂","🚶‍♀____🏃‍♂","🚶‍♀___🏃‍♂","🚶‍♀__🏃‍♂","🚶‍♀_🏃‍♂","`💞Ｉ ＬＯＶＥ ＹＵＯＥ`"
        ]
        try:
            for edit in edits_love:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    elif message.text == "کص ننت":
        edits_kos_nanat = ["'کــص","کــص ن","کـــص نـــنـ","کـــص نـنـتـ","💝 نـنـت","☘کـــص نـنـت دیگه☘"]
        try:
            for edit in edits_kos_nanat:
                await message.edit_text(edit)
                await asyncio.sleep(0.2) 
        except Exception as e:
            print(f"Error while editing message: {e}")            
    elif message.text == "خخخ":
        edits_khkhkh = ['😂😂', '🤣🤣', '😀', '😃', '😄', '😁', '😆', '😅', '😊', '🙃', '😛', '😝', '😜', '🤪', '😺', '😹', '😸', '😇', '😂', '🥳']
        try:
            for edit in edits_khkhkh:
                await message.edit_text(edit)
                await asyncio.sleep(0.2) 
        except Exception as e:
            print(f"Error while editing message: {e}")

    elif message.text == "موشک":
        edits_moshak = ["🌍🚀                                🛸", "🌍🚀                               🛸", "🌍🚀                              🛸","🌍🚀                             🛸", "🌍🚀                            🛸", "🌍🚀                           🛸","🌍🚀                          🛸", "🌍🚀                         🛸", "🌍🚀                        🛸","🌍🚀                       🛸", "🌍🚀                      🛸", "🌍🚀                     🛸","🌍🚀                   🛸", "🌍🚀                  🛸", "🌍🚀                 🛸","🌍🚀                🛸", "🌍🚀               🛸", "🌍🚀              🛸","🌍🚀            🛸", "🌍🚀           🛸", "🌍🚀          🛸","🌍🚀         🛸", "🌍🚀        🛸", "🌍🚀       🛸","🌍🚀      🛸", "🌍🚀     🛸", "🌍🚀    🛸","🌍🚀   🛸", "🌍🚀  🛸", "🌍🚀 🛸","🌍🚀🛸", "🌍💥Boom💥"]
        try:
            for edit in edits_moshak:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    elif message.text == "ادم فضایی":
        edits_love = ["👽                     🔦😼", "👽                    🔦😼", "👽                   🔦😼", "👽                  🔦😼","👽                 🔦😼", "👽                🔦😼", "👽               🔦😼", "👽              🔦😼","👽             🔦😼", "👽            🔦😼", "👽           🔦😼", "👽          🔦🐀𐈼𘠬👽           😼", "👽        🔦😼", "👽       🔦😼", "👽      🔦😼","👽     🔦😼", "👽    🔦😼", "👽   🔦😼", "👽  🔦😼","👽 🔦😼", "👽🔦🙀"]
        try:
            for edit in edits_love:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)  
        except Exception as e:
            print(f"Error while editing message: {e}")

    elif message.text == "پول":
        edits_pool = ["🔥            ‌                    💵", "🔥            ‌                   💵", "🔥            ‌                 💵","🔥            ‌                💵", "🔥            ‌               💵", "🔥            ‌              💵","🔥            ‌             💵", "🔥            ‌            💵", "🔥            ‌           💵","🔥            ‌          💵", "🔥                         💵", "🔥            ‌        💵","🔥            ‌       💵", "🔥            ‌      💵", "🔥            ‌     💵","🔥            ‌    💵", "🔥            ‌   💵", "🔥            ‌  💵","🔥            ‌ 💵", "🔥            ‌💵", "🔥           💵","🔥          💵", "🔥         💵", "🔥        💵","🔥       💵", "🔥      💵", "🔥     💵","🔥    💵", "🔥   💵", "🔥  💵","🔥 💵", "💸"]
        try:
            for edit in edits_pool:
                await message.edit_text(edit)
                await asyncio.sleep(0.2) 
        except Exception as e:
            print(f"Error while editing message: {e}")

    elif message.text == "جن":
        edits_jn = ["👻                                   🙀", "👻                                  🙀", "👻                                 🙀","👻                                🙀", "👻                               🙀", "👻                              🙀","👻                             🙀", "👻                            🙀", "👻                           🙀","👻                          🙀", "👻                         🙀", "👻                        🙀","👻                       🙀", "👻                      🙀", "👻                     🙀","👻                    🙀", "👻                   🙀", "👻                  🙀","👻                 🙀", "👻               🙀", "👻              🙀","👻             🙀", "👻            🙀", "👻           🙀","👻          🙀", "👻         🙀", "👻        🙀","👻       🙀", "👻      🙀", "👻     🙀","👻    🙀", "👻   🙀", "👻  🙀","👻 🙀", "👻🙀", "☠بگاه رفت "]
        try:
            for edit in edits_jn:
                await message.edit_text(edit)
                await asyncio.sleep(0.2) 
        except Exception as e:
            print(f"Error while editing message: {e}")
            
    elif message.text == "قلب":
        edits_galb = ["❤️🧡💛💚", "💜💙🖤💛", "🤍🤎💛💜", "💚❤️🖤🧡", "💜💚🧡🖤", "🤍🧡🤎💜","💙🧡💜🧡", "💚💛💙💜", "🖤💛💙🤍", "❣"]
        try:
            for edit in edits_galb:
                await message.edit_text(edit)
                await asyncio.sleep(0.2) 
        except Exception as e:
            print(f"Error while editing message: {e}")
                        
    elif message.text == "برم‌ خونه":
        edits_bermkhone = ["🏠              🚶‍♂", "🏠             🚶‍♂", "🏠            🚶‍♂", "🏠           🚶‍♂","🏠          🚶‍♂", "🏠         🚶‍♂", "🏠        🚶‍♂", "🏠       🚶‍♂","🏠      🚶‍♂", "🏠     🚶‍♂", "🏠    🚶‍♂", "🏠   🚶‍♂","🏠  🚶‍♂", "🏠 🚶‍♂","🏠🚶‍♂"]
        try:
            for edit in edits_bermkhone:
                await message.edit_text(edit)
                await asyncio.sleep(0.2) 
        except Exception as e:
            print(f"Error while editing message: {e}")            


    elif message.text == "فرار از خونه":
        edits_frarazkhone = ["🏡 💃", "🏡  💃", "🏡   💃", "🏡    💃", "🏡     💃", "🏡      💃","🏡       💃", "🏡        💃", "🏡         💃", "🏡          💃","🏡           💃", "🏡            💃", "🏡              💃💔👫","🏡                 🚶‍♀", "🏡               🚶‍♀", "🏡             🚶‍♀","🏡           🚶‍♀", "🏡         🚶‍♀", "🏡       🚶‍♀","🏡     🚶‍♀", "🏡  🚶‍♀", "🏡🚶‍♀"]
        try:
            for edit in edits_frarazkhone:
                await message.edit_text(edit)
                await asyncio.sleep(0.2) 
        except Exception as e:
            print(f"Error while editing message: {e}")
                        
    elif message.text == "عقاب":
        edits_ogab = ["🐍                         🦅", "🐍                      🦅", "🐍                    🦅","🐍                  🦅", "🐍                🦅", "🐍               🦅","🐍              🦅", "🐀𓐠           🦅", "🐍           🦅","🐍          🦅", "🐍         🦅", "🐍        🦅","🐍       🦅", "🐍      🦅", "🐍     🦅","🐍    🦅", "🐍   🦅", "🐍 🦅","🐍🦅", "پیشی برد😹"
    ]
        try:
            for edit in edits_ogab:
                await message.edit_text(edit)
                await asyncio.sleep(0.2) 
        except Exception as e:
            print(f"Error while editing message: {e}")
        	        	                	

    elif message.text == "بکشش":
        edits_bekoshesh = ["😂                 • 🔫🤠","😂                •  🔫🤠","😂               •   🔫🤠","😂              •    🔫🤠","🐀򐠠            •     🔫🤠","😂            •      🔫🤠","😂           •       🔫🤠","😂          •        🔫🤠","😂         •         🔫🤠","😂        •          🔫🤠","😂       •           🔫🤠","😂      •            🔫🤠","😂     •             🔫🤠","😂    •              🔫🤠","😂   •               🔫🤠","😂  •                🔫🤠","😂 •                 🔫🤠","😂•                  🔫🤠","🤯                  🔫 🤠","فرد جنایتکار کشته شد :)"]
        try:
            for edit in edits_bekoshesh:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")
        

    if message.text == "مسجد":
        edits_masjed = ["🕌                  🚶‍♂","🕌                 🚶‍♂","🕌                🚶‍♂","🕌               🚶‍♂","🕌              ??‍♂","🕌             🚶‍♂","🕌            🚶‍♂","🕌           🚶‍♂","🕌          🚶‍♂","🕌         🚶‍♂","🕌        🚶‍♂","🕌       🚶‍♂","🕌      🚶‍♂","🕌     ??‍♂","🕌    🚶‍♂","🕌   ??‍♂","🕌  🚶‍♂","?? 🚶‍♂","🕌🚶‍♂","اشهدان الا الا الله📢"]
        try:
            for edit in edits_masjed:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")
   
   
    if message.text == "کوسه":
        edits_koose = ["🏝┄┅┄┅┄┄┅🏊‍♂┅┄┄┅🦈","🏝┄┅┄┅┄┄🏊‍♂┅┄┄🦈","🏝┄┅┄┅┄🏊‍♂┅┄🦈","🏝┄┅┄┅🏊‍♂┅┄🦈","🏝┄┅┄🏊‍♂┅┄🦈","🏝┄┅🏊‍♂┅┄🦈","🏝┄🏊‍♂┅┄🦈","🏝🏊‍♂┅┄🦈","اوخیش شانس آوردما :)"]
        try:
            for edit in edits_koose:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")
   

    if message.text == "بارون":
        edits_baron = ["☁️                ⚡️","☁️               ⚡️","☁️              ⚡️","☁️             ⚡️","☁️            ⚡️","☁️           ⚡️","☁️          ⚡️","☁️         ⚡️","☁️        ⚡️","☁️       ⚡️","☁️      ⚡️","☁️     ⚡️","☁️    ⚡️","☁️   ⚡️","☁️  ⚡️","☁️ ⚡️","⛈"]
        try:
            for edit in edits_baron:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

	        		        	
    if message.text == "بادکنک":
        edits_badkonak = ["🔪                🎈","🔪               🎈","🔪              🎈","🔪             🎈","🔪            🎈","🔪           🎈","🔪          🎈","🔪         🎈","🔪        🎈","🔪       🎈","🔪      🎈","🔪     🎈","🔪    🎈","🔪   🎈","🔪  🎈","🔪 🎈","🔪🎈","💥Bomm💥"]
        try:
            for edit in edits_badkonak:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")
        
    if message.text == "شب خوش":
        edits_shabkhosh = ["🌜              🙃","🌜             🙃","🌜            🙃","🌜           🙃","🌜          🙃","🌜         🙃","🌜        🙃","🌜       😕","🌜      ☹️","🌜     😣","🌜    😖","🌜   😩","🌜  🥱","🌜 🥱","😴"]
        try:
            for edit in edits_shabkhosh:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "فیش":
        edits_fish = ["👺🎣           💳","👺🎣          💳","👺🎣         💳","👺🎣        💳","👺🎣      💳","👺🎣     💳","👺🎣    ??","👺🎣   💳","👺🎣  💳","👺🎣 💳","👺🎣💳","💵🤑میشورم 100درصد ورمیدارم تبرم نیسم🤑💵"]
        try:
            for edit in edits_fish:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")



    if message.text == "فوتبال":
        edits_football = ["👟          ⚽️","👟         ⚽️","👟        ⚽️","👟       ⚽️","👟      ⚽️","👟     ⚽️","👟    ⚽️","👟   ⚽️","👟  ⚽️","👟⚽️","👟 ⚽️","👟  ⚽️","👟   ⚽️","👟    ⚽️","👟     ⚽️","👟      ⚽️","👟       ⚽️","👟        ⚽️","👟         ⚽️","👟          ⚽️","(توی دروازه🔥)"]
        try:
            for edit in edits_football:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")
        	        	
    if message.text == "برم بخابم":
        edits_bekhabam = ["🛏                🚶🏻","🛏               🚶🏻","🛏              🚶🏻","🛏             🚶🏻","🛏            🚶🏻","🛏           🚶🏻‍♂️","🛏          🚶🏻","🛏         🚶🏻","🛏        🚶🏻","🛏       🚶🏻","🛏      🚶🏻","🛏     🚶🏻","🛏    🚶🏻","🛏   🚶🏻","🛏  🚶🏻","🛏 🚶🏻","🛌"]
        try:
            for edit in edits_bekhabam:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")


    if message.text == "غرقش کن":
        edits_ghargheshkon = ["🌬🌊              🏄🏻‍♂","🌬🌊             🏄🏻‍♂","🌬🌊            🏄🏻‍♂","🌬🌊           🏄🏻‍♂","🌬🌊          🏄🏻‍♂","🌬🌊         🏄🏻‍♂","🌬🌊        🏄🏻‍♂","🌬🌊       🏄🏻‍♂","🌬🌊      🏄🏻‍♂","🌬🌊     🏄🏻‍♂","🌬🌊    🏄🏻‍♂","🌬🌊   🏄🏻‍♂","🌬🌊  🏄🏻‍♂","🌬🌊 🏄🏻‍♂","غرق شد🙈"]
        try:
            for edit in edits_ghargheshkon:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "فضانورد":
        edits_fazanavard = ["🧑‍🚀              🪐","🧑‍🚀             🪐","🧑‍🚀            🪐","🧑‍🚀           🪐","🧑‍🚀          🪐","🧑‍🚀         🪐","🧑‍🚀        🪐","🧑‍🚀       🪐","🧑‍🚀      🪐","🧑‍🚀     🪐","🧑‍🚀    🪐","🧑‍🚀   🪐","🧑‍🚀  🪐","🧑‍🚀 🪐","🇮🇷من میگم ایران قویه🇮🇷"]
        try:
            for edit in edits_fazanavard:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")


    if message.text == "ایول":
        edits_eyval = ["🤜🏿                       🤛🏻","🤜🏻                    🤛🏿","🤜🏻                  🤛🏻","🤜🏿                   🤛🏻","🤜🏻                🤛🏿","🤜🏻               🤛🏻","🤜🏻              🤛🏻","🤜🏿             🤛🏿","🤜🀀􎰠           🤛🏻","🤜🏻           🤛🏻","🤜🏿          🤛🏻","🤜🏻         🤛🏻","🤜🀀􎰠       🤛🏿","🤜🏻       🤛🏻","🤜🏻      🤛🏻","🤜🏿     🤛🏻","🤜🏻    🤛🏻","🤜🏻   🤛🏻","🤜🏻  🤛🏻","🤜🏻🤛🏿"]
        try:
            for edit in edits_eyval:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")


    if message.text == "فیل":
        edits_fil = [
        "░░▄███▄███▄\n░░█████████\n░░▒▀█████▀░\n░░▒░░▀█▀ ",
        "░░▄███▄███▄\n░░█████████\n░░▒▀█████▀░\n░░▒░░▀█▀\n░░▒░░█░\n░░▒░█\n░░░█\n░░█░░░░███████\n░██░░░██▓▓███▓██▒\n██░░░█▓▓▓▓▓▓▓█▓████\n██░░██▓▓▓(◐)▓█▓█▓█\n███▓▓▓█▓▓▓▓▓█▓█▓▓▓▓█\n▀██▓▓█░██▓▓▓▓██▓▓▓▓▓█",
        "░░▄███▄███▄\n░░█████████\n░░▒▀█████▀░\n░░▒░░▀█▀\n░░▒░░█░\n░░▒░█\n░░░█\n░░█░░░░███████\n░██░░░██▓▓███▓██▒\n██░░░█▓▓▓▓▓▓▓█▓████\n██░░██▓▓▓(◐)▓█▓█▓█\n███▓▓▓█▓▓▓▓▓█▓█▓▓▓▓█\n▀██▓▓█░██▓▓▓▓██▓▓▓▓▓█\n░▀██▀░░█▓▓▓▓▓▓▓▓▓▓▓▓▓█\n░░░░▒░░░█▓▓▓▓▓█▓▓▓▓▓▓█\n░░░░▒░░░█▓▓▓▓█▓█▓▓▓▓▓█\n░▒░░▒░░░█▓▓▓█▓▓▓█▓▓▓▓█\n░▒░░▒░░░█▓▓▓█░░░█▓▓▓█\n░▒░░▒░░░██▓██░░░██▓▓██"
    ]
        try:
            for edit in edits_fil:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "بشمار":
        edits_beshoomar = ["¹","²","³","⁴","⁵","⁶","⁷","⁸","⁹","¹⁰","sʜᴏᴛ sʜᴏᴅɪ😉"]
        try:
            for edit in edits_beshoomar:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "بمیر کرونا":
        edits_bemir_corona = ['🦠  •   •   •   •   •   •   •   •   •   •  🔫','🦠  •   •   •   •   •   •   •   •   •   ◀  🔫','🦠  •   •   •   •   •   •   •   •   ◀   •  🔫','🦠  •   •   •   •   •   •   •   ◀   •   •  🔫','🦠  •   •   •   •   •   •   ◀   •   •   •  🔫','🦠  •   •   •   •   •   ◀   •   •   •   •  🔫','🦠  •   •   •   •   ◀   •   •   •   •   •  🔫','🦠  •   •   •   ◀   •   •   •   •   •   •  🔫','🦠  •   •   ◀   •   •   •   •   •   •   •  🔫','🦠  •   ◀   •   •   •   •   •   •   •   •  🔫','🦠  ◀   •   •   •   •   •   •   •   •   •  🔫','💥  •   •   •   •   •   •   •   •   •   •  🔫','💉💊💉💊💉💊💉💊', 'we win','Corona Is Dead','وای کرونارو گاییدیم']
        try:
            for edit in edits_bemir_corona:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")




    if message.text == "انگش":
        edits_angosh = ['🍑________________👈','🍑_______________👈','🍑______________👈','🍑_____________👈','🀀󤑟___________👈','🍑___________👈','🍑__________👈','🍑_________👈','🍑________👈','🍑_______👈','🍑______👈','🍑____👈','🍑___👈','🍑__👈','🍑_👈','✌انگشت شد✌']
        try:
            for edit in edits_angosh:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")


    if message.text == "جقیم":
        edits_iran = ['B=======✊🏻=D','B=====✊🏻===D','B==✊🏻======D','B✊🏻========D','B===✊??=====D','B=====✊🏻===D','B=======✊🏻=D','B====✊🏻====D','B==✊??======D','B✊🏻========D','B==✊🏻======D','B====✊🏻====D','B======✊🏻==D','B========✊🏻D','B========✊🏻D💦💦','کمر نموند برامون بمولا']
        try:
            for edit in edits_iran:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")


    if message.text == "ریدم":
        edits_ridam = ['🐒\n💩\n\n\n\n\n\n\n\n\n🧑‍🦯','🐒\n\n🐀𺑜n\n\n\n\n\n\n\n🧑‍🦯','🐒\n\n\n💩\n\n\n\n\n\n\n🧑‍🦯','🐒\n\n\n\n💩\n\n\n\n\n\n🧑‍🦯','🐒\n\n\n\n\n💩\n\n\n\n\n🧑‍🦯','🐒\n\n\n\n\n\n💩\n\n\n\n🧑‍🦯','🐒\n\n\n\n\n\n\n💩\n\n\n🧑‍🦯','🐒\n\n\n\n\n\n\n\n💩\n\n🧑‍🦯','چیو نگاه میکنی ریدیم ب هیکل یاروع دیگ😂']
        try:
            for edit in edits_ridam:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")


    if message.text == "مربع":
        edits_moraba = ['🟥🟥🟥🟥\n🟥🟥🟥🟥\n🟥🟥🟥🟥\n🟥🟥🟥🟥','🟥🟥🟥🟥\n🟥⬜️⬛️🟥\n🟥⬛️⬜️🟥\n🟥🟥🟥🟥','🟥🟥🟥🟥\n🟥⬛️⬜️🟥\n🟥⬜️⬛️🟥\n🟥🟥🟥🟥','🟥🟥🟥⬛️\n🟥⬜️⬛️🟥\n🟥⬛️⬜️🟥\n⬛️🟥🟥🟥','🟥⬜️⬛️🟥\n🟥⬛️⬜️🟥\n🟥⬜️⬛️🟥\n🟥⬛️⬜️🟥','🟥⬛️⬜️🟥\n🟥⬜️⬛️🟥\n🟥⬛️⬜️🟥\n🟥⬜️⬛️🟥','⬜️⬛️⬜️⬛️\n⬛️⬜️⬛️⬜️\n⬜️⬛️⬜️⬛️\n⬛️⬜️⬛️⬜️','⬛️⬜️⬛️⬜️\n⬜️⬛️⬜️⬛️\n⬛️⬜️⬛️⬜️\n⬜️⬛️⬜️⬛️','🟥⬜️⬛️⬜️🟥\n🟥⬛️⬜️⬛️🟥\n🟥⬜️⬛️⬜️🟥\n🟥⬛️⬜️⬛️🟥\n🟥⬜️⬛️⬜️🟥','🟥🟥🟥🟥🟥🟥🟥\n🟥🟨🟨🟨🟨🟨🟥\n🟥🟩🟩🟩🟩🟩🟥\n🟥⬛️⬛️⬛️⬛️⬛️🟥\n🟥🟦🟦🟦🟦🟦🟥\n🟥⬜️⬜️⬜️⬜️⬜️🟥\n🟥🟥🟥🟥🟥🟥🟥','🟥🟥🟥🟥🟥🟥🟥\n🟥💚💚💚💚💚🟥\n🟥💙💙💙💙💙🟥\n🟥❤️❤️❤️❤️❤️🟥\n🟥💖💖💖💖💖🟥\n🟥🤍🤍🤍🤍🤍🟥\n🟥🟥🟥🟥🟥🟥🟥','🟥🟥🟥🟥🟥🟥🟥\n🟥▫️◼️▫️◼️▫️🟥\n🟥◼️▫️◼️▫️◼️🟥\n🟥◽️◼️◽️◼️◽️🟥\n🟥◼️◽️◼️◽️◼️🟥\n🟥◽️◼️◽️◼️◽️🟥\n🟥🟥🟥🟥🟥🟥🟥','🟥🟥🟥🟥🟥🟥🟥\n🟥🔶🔷🔶🔷🔶🟥\n🟥🔷🔶🔷🔶🔷🟥\n🟥🔶🔷🔶🔷🔶🟥\n🟥🔷🔶🔷🔶🔷🟥\n🟥🔶🔷🔶🔷🔶🟥\n🟥🟥🟥🟥🟥🟥🟥','🟥🟥🟥🟥🟥🐀􉐽􉑜n🟥♥️❤️♥️❤️♥️🟥\n🟥❤️♥️❤️♥️❤️🟥\n🟥♥️❤️♥️❤️♥️🟥\n🟥❤️♥️❤️♥️❤️🟥\n🟥♥️❤️♥️❤️♥️🟥\n🟥🟥🟥🟥🟥🟥🟥','💙💙💙💙','❣️I Love❣️']
        try:
            for edit in edits_moraba:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "دیک":
        edits_k = ['.                      💦💦💦\n.                    💦💦💦💦\n                   💦💦💦💦💦\n                 💦💦💦💦💦💦\n                 💦💦💦  💦💦💦\n                 💦💦💦        💦💦\n                  ◼️◼️◼️         💦💦\n           ◼️📜◼️📜◼️     💦💦\n     ◼️📜📜◼️📜📜◼️   💦\n     ◼️📜📜📜📜📜◼️     💦\n           ◼️◼️◼️◼️◼️          💦\n           ◼️📜📜📜◼️          💦\n           ◼️📜📜📜◼️       💦\n           ◼️📜📜📜◼️\n           ◼️📜📜📜◼️\n           ◼️📜📜📜◼️\n           ◼️📜📜📜◼️\n           ◼️📜📜📜◼️‌\n           ◼️📜📜📜◼️\n           ◼️📜📜📜◼️\n           ◼️📜📜📜◼️\n           ◼️📜📜📜◼️\n           ◼️📜📜📜◼️\n           ◼️📜📜📜◼️\n     ◼️📜📜📜📜📜◼️\n◼️📜📜📜📜📜📜📜◼️\n◼️📜📜📜◼️📜📜📜◼️\n     ◼️◼️◼️     ◼️◼️◼️']
        try:
            for edit in edits_k:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "ساعت":
        edits_saat = ['🕛🕛🕛🕛🕛\\n🕛🕛🕛🕛🕛\\n🕛🕛🕛🕛🕛\\n🕛🕛🕛🕛🕛\\n🕛🕛🕛🕛🕛', '🕐🕐🕐🕐🕐\\n🕐🕐🕐🕐🕐\\n🕐🕐🕐🕐🕐\\n🕐🕐🕐🕐🕐\\n🕐🕐🕐🕐🕐', '🕑🕑🕑🕑🕑\\n🕑🕑🕑🕑🕑\\n🕑🕑🕑🕑🕑\\n🕑🕑🕑🕑🕑\\n🕑🕑🕑🕑🕑', '🕒🕒🕒🕒🕒\\n🕒🕒🕒🕒🕒\\n🕒🕒🕒🕒🕒\\n🕒🕒🕒🕒🕒\\n🕒🕒🕒🕒🕒', '🕓🕓🕓🕓🕓\\n🕓🕓🕓🕓🕓\\n🕓🕓🕓🕓🕓\\n🕓🕓🕓🕓🕓\\n🕓🕓🕓🕓🕓', '🕔🕔🕔🕔🕔\\n🕔🕔🕔🕔🕔\\n🕔🕔🕔🕔🕔\\n🕔🕔🕔🕔🕔\\n🕔🕔🕔🕔🕔', '🕕🕕🕕🕕🕕\\n🕕🕕🕕🕕🕕\\n🕕🕕🕕🕕🕕\\n🕕🕕🕕🕕🕕\\n🕕🕕🕕🕕🕕', '🕖🕖🕖🕖🕖\\n🕖🕖🕖🕖🕖\\n🕖🕖🕖🕖🕖\\n🕖🕖🕖🕖🕖\\n🕖🕖🕖🕖🕖', '🕗🕗🕗🕗🕗\\n🕗🕗🕗🕗🕗\\n🕗🕗🕗🕗🕗\\n🕗🕗🕗🕗🕗\\n🕗🕗🕗🕗🕗', '🕘🕘🕘🕘🕘\\n🕘🕘🕘🕘🕘\\n🕘🕘🕘🕘🕘\\n🕘🕘🕘🕘🕘\\n🕘🕘🕘🕘🕘', '🕙🕙🕙🕙🕙\\n🕙🕙🕙🕙🕙\\n🕙🕙🕙🕙🕙\\n🕙🕙🕙🕙🕙\\n🕙🕙🕙🕙🕙', '🕚🕚🕚🕚🕚\\n🕚🕚🕚🕚🕚\\n🕚🕚🕚🕚🕚\\n🕚🕚🕚🕚🕚\\n🕚🕚🕚🕚🕚']
        try:
            for edit in edits_saat:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")


    if message.text in ["برگام", "پشم", "پشمام"]:
        edits_bargam = ['🍂🍂🍂🍂🍂🍂🍂🍂🍂🍂🍂🍂🍂🍂🍂', '🍁🍁🍁🍁🍁🍁🍁🍁🍁🍁🍁🍁🍁🍁🍁', '🍃🍃🍃🍃🍃🍃🍃🍃🍃🍃🍃🍃🍃🍃🍃','🌿🌿🌿🌿🌿🌿🌿🌿🌿🌿🌿🌿🌿🌿🌿', '🌱🌱🌱🌱🌱🌱🌱🌱🌱🌱🌱🌱🌱🌱🌱', '☘️☘️☘️☘️☘️☘️☘️☘️☘️☘️☘️☘️☘️☘️☘️','🍀🍀🍀🍀🍀🍀🍀🍀🍀🍀🍀🍀🍀🍀🍀️', 'پشم دیگه ندارم ولی برگام ریخت بمولا', '🍂🍁🍂🍁🍂🍁🍂🍁🍂🍁🍂🍁🍂🍁🍂','🌱🌿🌱🌿🌱🌿🌱🌿🌱🌿🌱🌿🌱🌿🌱', '🍂🍂🌿🍂🌿🍂🌿🍂🌿🍂🌿🍂🌿🍂🌿', '☘️🍁☘️🍁☘️🍁☘️🍁☘️🍁☘️🍁☘️🍁☘️','🍂🍁🌱🌿🍂🍁🌱🌿🍂🍁🌱🌿🍂🍁🌱🌿', '🍃🍂🍁🌱🌿☘️🍀🍃🍁🍂🌿🌱☘️🍀🍃', 'دیگه برگی برام نمونده ', 'پشمام ریخ ☹'
    ]
        try:
            for edit in edits_bargam:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "رقص":
        edits_raqse = ["🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🔲🔳🔲🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥", "🟥🟥🟥🟥🟥🟥🟥🔲🟥🟥🟥🟥🔳🟥🟥🟥🔲🟥🟥🟥🟥🟥🟥🟥🟥", "🟥🟥🟥🟥🟥🟥🟥🟥🔲🟥🟥🟥🔳🟥🟥🔲🟥🟥🟥🟥🟥🟥🟥🟥🟥", "🟥🟥🟥🟥🟥🟥🔲🟥🟥🟥🟥🟥🔳🟥🟥🟥🟥🔲🟥🟥🟥🟥🟥🟥", "🟪🟪🟪🟪🟪🟪🟪🟪🟪🟪🟪🔲🔳🔲🟪🟪🟪🟪🟪🟪🟪🟪🟪🟪🟪", "🟪🟪🟪🟪🟪🟪🟪🔲🟪🟪🟪🟪🔳🟪🟪🟪🔲🟪🟪🟪🟪🟪🟪🟪🟪🟪", "🟦🟦🟦🟦🟦🟦🟦🟦🟦🔲🔳🔲🟦🟦🟦🟦🟦🟦🟦🟦🟦", "◻️🟩🟩◻️◻️◻️◻️🟩◻️🟩🟩🟩🔳🟩🟩🟩◻️🟩◻️◻️◻️◻️🟩🟩◻️", "🟩⬜️⬜️🟩⬜️🟩🟩⬜️🟩⬜️⬜️⬜️🔲⬜️⬜️⬜️🟩⬜️🟩🟩🟩🟩⬜️⬜️🟩", "🌹entire🀀󞐢"]
        try:
            for edit in edits_raqse:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "خار":
        edits_khar = ["🌵ــــــــــــــــــــــــــــــــــــــــ 🎈","🌵ــــــــــــــــــــــــــــــــــــــــ🎈","🌵ـــــــــــــــــــــــــــــــــــــــ🎈","🌵ــــــــــــــــــــــــــــــــــــــ🎈","🌵ـــــــــــــــــــــــــــــــــــــ🎈","🌵ــــــــــــــــــــــــــــــــــــ🎈","🌵ـــــــــــــــــــــــــــــــــــ🎈","🌵ــــــــــــــــــــــــــــــــــ🎈","🌵ـــــــــــــــــــــــــــــــــ🎈","🌵ــــــــــــــــــــــــــــــــ🎈","🌵ـــــــــــــــــــــــــــــــ🎈","🌵ــــــــــــــــــــــــــــــ🎈","🌵ـــــــــــــــــــــــــــــ🎈","🌵ــــــــــــــــــــــــــــ🎈","🌵ــــــــــــــــــــــــــ🎈","🌵ـــــــــــــــــــــــــ🎈","🌵ــــــــــــــــــــــ🎈","🌵ـــــــــــــــــــــ🎈","🌵ـــــــــــــــــــ🎈","🌵ـــــــــــــــــ🎈","🌵ـــــــــــــــ🎈","🌵ــــــــــــ🎈","🌵ــــــــــ🎈","🌵ـــــــــ🎈","🌵ــــــــ🎈","🌵ــــــ🎈","🌵ــــ🎈","🌵ـــ🎈","🌵ــ🎈","🌵ـ🎈","🌵💥🎈","💥Bommmm💥"]
        try:
            for edit in edits_khar:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "گلب":
        edits_galbe = ["💚💛🧡❤️","💙💚💜🖤","❤️🤍🧡💚","🖤💜💙💚","🤍🤎❤️💙","🖤💜💚💙","💝💘💗💘","❤️🤍🤎🧡","💕💞💓🤍","💜💙❤️🤍","💙💜💙💚","🧡💚🧡💙","💝💜💙❤️","💞🖤💙💚","💛🧡❤️💚","😍Im crazy about you😍"]
        try:
            for edit in edits_galbe:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "اها":
        edits_aha = [":/",":|",":(",":)",":/",":|",":(",":)"]
        try:
            for edit in edits_aha:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")


    if message.text == "ماشین":
        edits_mashin = ["💣________________🏎","💣_______________🏎","💣______________🏎","💣_____________🏎","💣____________🏎","💣___________🏎","💣__________🏎","💣_________🏎","💣________🏎","💣_______🏎","💣______🏎","💣____🏎","💣___🏎","💣__🏎","💣_🏎","💥BOOM💥"]
        try:
            for edit in edits_mashin:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "موتور":
        edits_motor = ["🚧___________________🛵","🚧_________________🛵","🚧_______________🛵","🚧_____________🛵","🚧___________🛵","🚧_________🛵","🚧_______🛵","🚧_____🛵","🚧____🛵","🚧__🛵","🚧_🛵","🚧🛵","وای تصادف شد","وای موتورم بـگا رف","ریدم تو موتورم","💥BOOM💥"]
        try:
            for edit in edits_motor:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "پنالتی":
        edits_penalty = [
        """
        ////////////////////
        ⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️




        😐
        👕 ⚽️
        👖
        ////////////////////
        """,
        """
        ////////////////////
        ⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️



        ⚽️
        😐
        👕
        👖
        ////////////////////
        """,
        """
        ////////////////////
        ⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️

        ⚽️


        😐
        👕
        👖
        ////////////////////
        """,
        """
        ////////////////////
        ⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⚽️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️




        😐
        👕
        👖
        ////////////////////
        """,
        """
        ////////////////////
        ⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⚽️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️
        ⬜️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬛️⬜️



        💭Gooooooooolllllllll
        😐
        👕
        👖
        ////////////////////
        """
    ]
        try:
            for edit in edits_penalty:
                await message.edit_text(edit)
                await asyncio.sleep(0.9)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "تانک":
        edits_tank = [".        (҂_´)\n         <,︻╦̵̵ ╤─ ҉     ~  •\n█۞███████]▄▄▄▄▄▄▄▄▄▄▃ ●●",".        (҂_´)\n         <,︻╦̵̵ ╤─ ҉     ~  •\n█۞███████]▄▄▄▄▄▄▄▄▄▄▃ ●●●●\n▂▄▅█████████▅▄▃▂…",".        (҂_´)\n         <,︻╦̵̵ ╤─ ҉     ~  •\n█۞███████]▄▄▄▄▄▄▄▄▄▄▃ ●●●●●\n▂▄▅█████████▅▄▃▂…\n[███████████████████]",".        (҂_´)\n         <,︻╦̵̵ ╤─ ҉     ~  •\n█۞███████]▄▄▄▄▄▄▄▄▄▄▃ ●●●●●●●\n▂▄▅█████████▅▄▃▂…\n[███████████████████]\n◥⊙▲⊙▲⊙▲⊙▲⊙▲⊙▲⊙","تانک رو دیدی؟؟🤔","دیگه نمیبینی😆","💥🔥بوم💥🔥",".        (҂`_´)\n         <,︻╦̵̵ ╤─ ҉     ~  •\n█۞███████]▄▄▄▄▄▄▄▄▄▄▃ 💥●●●●●●●●●●●\n▂▄▅█████████▅▄▃▂…\n[███████████████████]\n◥⊙▲⊙▲⊙▲⊙▲⊙▲⊙▲⊙"]
        try:
            for edit in edits_tank:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "قلب2":
        edits_ghalb2 = [
        """
        ❤️❤️❤️❤️❤️❤️
        ❤️❤️❤️❤️❤️❤️
        ❤️❤️💛💛❤️❤️
        ❤️❤️💛💛❤️❤️
        ❤️❤️❤️❤️❤️❤️
        ❤️❤️❤️❤️❤️❤️
        """,
        """
        ❤️❤️❤️❤️❤️❤️
        ❤️💚💚💚💚❤️
        ❤️💚💛💛💚❤️
        ❤️💚💛💛💚❤️
        ❤️💚💚💚💚❤️
        ❤️❤️❤️❤️❤️❤️
        """,
        """
        💙💙💙💙💙💙
        💙💚💚💚💚💙
        💙💚💛💛💚💙
        💙💚💛💛💚💙
        💙💚💚💚💚💙
        💙💙💙💙💙💙
        """,
        """
        💙💙💙💙💙💙
        💙🖤🖤🖤🖤💙
        💙🖤💛💛🖤💙
        💙🖤💛💛🖤💙
        💙🖤🖤🖤🖤💙
        💙💙💙💙💙💙
        """,
        """
        💙💙💙💙💙💙
        💙🖤🖤🖤🖤💙
        💙🖤🤍🤍🖤💙
        💙🖤🤍🤍🖤💙
        💙🖤🖤🖤🖤💙
        💙💙💙💙💙💙
        """,
        """
        💔💔💔💔💔💔
        💔🖤🖤🖤🖤💔
        💔🖤🤍🤍🖤💔
        💔🖤🤍🤍🖤💔
        💔🖤🖤🖤🖤💔
        💔💔💔💔💔💔
        """,
        """
        ❤️❤️❤️❤️❤️❤️
        ❤️❤️❤️❤️❤️❤️
        ❤️❤️💛💛❤️❤️
        ❤️❤️💛💛❤️❤️
        ❤️❤️❤️❤️❤️❤️
        ❤️❤️❤️❤️❤️❤️
        """,
        """
        ❤️❤️❤️❤️❤️❤️
        ❤️💚💚💚💚❤️
        ❤️💚💛💛💚❤️
        ❤️💚💛💛💚❤️
        ❤️💚💚💚💚❤️
        ❤️❤️❤️❤️❤️❤️
        """,
        """
        💙💙💙💙🐀𶐽𶐊        💙💚💚💚💚💙
        💙💚💛💛💚💙
        💙💚💛💛💚💙
        💙💚💚💚💚💙
        💙💙💙💙💙💙
        """,
        """
        💙💙💙💙💙💙
        💙🖤🖤🖤🖤💙
        💙🖤💛💛🖤💙
        💙🖤💛💛🖤💙
        💙🖤🖤🖤🖤💙
        💙💙💙💙💙💙
        """,
        """
        💙💙💙💙💙💙
        💙🖤🖤🖤🖤💙
        💙🖤🤍🤍🖤💙
        💙🖤🤍🤍🖤💙
        💙🖤🖤🖤🖤💙
        💙💙💙💙💙🐀𶐊        """,
        """
        💔💔💔💔💔💔
        💔🖤🖤🖤🖤💔
        💔🖤🤍🤍🖤💔
        💔🖤🤍🤍🖤💔
        💔🖤🖤🖤🖤💔
        💔💔💔💔💔💔
        """,
        """
        🖤🖤🖤🖤
        🖤🤍🤍🖤
        🖤🤍🤍🖤
        🖤🖤🖤🖤
        """,
        "🤍",
        "❤️"
    ]
        try:
            for edit in edits_ghalb2:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "لامپ":
        edits_lamp = ["💡                 ⚡","💡                ⚡","💡               ⚡","💡              ⚡","💡             ⚡","💡            ⚡","💡           ⚡","💡          ⚡","💡         ⚡","💡        ⚡","💡       ⚡","💡      ⚡","💡     ⚡","💡    ⚡","💡   ⚡","💡  ⚡","💡 ⚡","💡⚡","💡"]
        try:
            for edit in edits_lamp:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
            await message.reply_text("با رعد و برق لامپ روشن کردیم😐، پشمای فیزیک بمولا😅")
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "شب":
        edits_shab = ["🌕","🌔","🌖","🌓","🌓","🌒","🌘","🌑"]
        try:
            for edit in edits_shab:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "بای":
        edits_bye = ["خداحافظ","Bye","Totsiens","अलविदा","Tchau","ባይ","Pa","وداعا","bless","до свидания","ցտեսություն","ka ọ dị","addio","さようなら","здраво","doei","хайр","vale","Чао","Hoşçakal","au revoir","Tschüss","баяртай","αντίο","ବିଦାୟ","o dabọ","ביי","usale kahle","د خدای په امان","farvel","Hejdå","kwaheri","再见","sala hantle","slán","sağol","خداحافظظظ"]
        try:
            for edit in edits_bye:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == 'chetory' or message.text == 'چطوری' or message.text == 'Chetory':
        edits_chetory = ["چطوریی","how are you","क्या हाल है","Bawo ni o se wa","וואס מאכסטו","jak się masz","מה שלומך","Pehea oe","څنګه یاست","તમે કેમ છો","तिमीलाई कस्तो छ ","bạn khỏe không","apa khabar","nasılsın","hoe gaat het met je","Шумо чӣ хелед","quid agis","Hur mår du","你好吗","어떻게 지내","u phela joang","Қалайсыз","お元気ですか","како си","Conas tá tú","Come stai","как поживаешь","ce mai faci","እንዴት ነህ","كيف حالك","Kedu ka ị mere","koj nyob li cas","Como você está","คุณเป็นอย่างไรบ้าง","jak się masz","Pehea oe","چطوریی"]
        try:
            for edit in edits_chetory:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "سگ":
        edits_dog = [
        "┈┈┈┈┈┈┈┈┈     ╲╱╲╱",
        "┈╲╱╲╱  ┈┈┈   ╲╲▂╲▂\n┈┈┈┈┈┈┈┈┈     ╲╱╲╱",
        "╲╲╱╱▔╱▔▔╲╲╲╲\n┈╲╱╲╱  ┈┈┈   ╲╲▂╲▂\n┈┈┈┈┈┈┈┈┈     ╲╱╲╱",
        "╱╲╱╲▏┈┈┈┈┈▕▔╰━╯\n╲╲╱╱▔╱▔▔╲╲╲╲\n┈╲╱╲╱  ┈┈┈   ╲╲▂╲▂\n┈┈┈┈┈┈┈┈┈     ╲╱╲╱",
        "┈┈╲▔▔▔▔▔╲╱┈╰┳┳┳╯\n╱╲╱╲▏┈┈┈┈┈▕▔╰━╯\n╲╲╱╱▔╱▔▔╲╲╲╲\n┈╲╱╲╱  ┈┈┈   ╲╲▂╲▂\n┈┈┈┈┈┈┈┈┈     ╲╱╲╱",
        "┈╲╲┈┈┈┈┈▏┈▏┈▔▔▔▆\n┈┈╲▔▔▔▔▔╲╱┈╰┳┳┳╯\n╱╲╱╲▏┈┈┈┈┈▕▔╰━╯\n╲╲╱╱▔╱▔▔╲╲╲╲\n┈╲╱╲╱  ┈┈┈   ╲╲▂╲▂\n┈┈┈┈┈┈┈┈┈     ╲╱╲╱",
        "┈▏▏┈┈┈┈┈▏╲▕▋▕▋▏\n┈╲╲┈┈┈┈┈▏┈▏┈▔▔▔▆\n┈┈╲▔▔▔▔▔╲╱┈╰┳┳┳╯\n╱╲╱╲▏┈┈┈┈┈▕▔╰━╯\n╲╲╱╱▔╱▔▔╲╲╲╲\n┈╲╱╲╱  ┈┈┈   ╲╲▂╲▂\n┈┈┈┈┈┈┈┈┈     ╲╱╲╱",
        "┈╱▏┈┈┈┈┈╱▔▔▔▔╲\n┈▏▏┈┈┈┈┈▏╲▕▋▕▋▏\n┈╲╲┈┈┈┈┈▏┈▏┈▔▔▔▆\n┈┈╲▔▔▔▔▔╲╱┈╰┳┳┳╯\n╱╲╱╲▏┈┈┈┈┈▕▔╰━╯\n╲╲╱╱▔╱▔▔╲╲╲╲\n┈╲╱╲╱  ┈┈┈   ╲╲▂╲▂\n┈┈┈┈┈┈┈┈┈     ╲╱╲╱"
    ]
        try:
            for edit in edits_dog:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")





    if message.text == "قلبز":
        edits_ghalbz = [
        ".           ❤️                  ❤️\n        ❤️  ❤️          ❤️  ❤️\n    ❤️          ❤️  ❤️          ❤️\n       ❤️           ❤️           ❤️\n           ❤️                    ❤️\n               ❤️            ❤️\n                   ❤️    ❤️\n                        ❤️\n.",
        ".           🧡                  🧡\n        🧡  🧡          🧡  🧡\n    🧡          🧡  🧡          🧡\n       🠀򈐠          🧡           🧡\n           🧡                    🧡\n               🧡            🧡\n                   🧡    🧡\n                        🧡\n.",
        ".           💛                  💛\n        💛  💛          💛  💛\n    💛          💛  💛          💛\n       💛           💛           💛\n           💛                    💛\n               💛            🐀𶱜n                   💛    💛\n                        💛\n.",
        ".           💚                  💚\n        💚  💚          💚  💚\n    💚          💚  💚          💚\n       💚           💚           💚\n           💚                    💚\n               💚            💚\n                   💚    💚\n                        💚\n.",
        ".           💙                  💙\n        💙  💙          💙  💙\n    💙          💙  💙          💙\n       💙           💙           💙\n           💙                    💙\n               💙            💙\n                   💙    💙\n                        💙\n.",
        ".           💜                  💜\n        💜  💜          💜  💜\n    💜          💜  💜          💜\n       💜           💜           💜\n           💜                    💜\n               💜            💜\n                   💜    💜\n                        💜\n.",
        ".           🖤                  🖤\n        🖤  🖤          🖤  🖤\n    🖤          🖤  🖤          🖤\n       🖤           🖤           🖤\n           🖤                    🖤\n               🖤            🖤\n                   🖤    🖤\n                        🖤\n.",
        ".           🤍                  🤍\n        🤍  🤍          🤍  🤍\n    🤍          🤍  🤍          🤍\n       🤍           🤍           🤍\n           🤍                    🤍\n               🤍            🤍\n                   🤍    🤍\n                        🤍\n.",
        ".           💗                  💗\n        💗  💗          💗  💗\n    💗          💗  💗          💗\n       💗           💗           💗\n           💗                    💗\n               💗            💗\n                   💗    💗\n                        💗\n.",
        ".           ❤️                  ❤️\n        ❤️  ❤️          ❤️  ❤️\n    ❤️          ❤️  ❤️          ❤️\n       ❤️           ❤️           ❤️\n           ❤️                    ❤️\n               ❤️            ❤️\n                   ❤️    ❤️\n                        ❤️\n.",
        ".           🧡                  🧡\n        🧡  🧡          🧡  🧡\n    🧡          🧡  🧡          🧡\n       🧡           🧡           🧡\n           🧡                    🧡\n               🧡            🧡\n                   🧡    🧡\n                        🧡\n.",
        ".           💛                  💛\n        💛  💛          💛  💛\n    💛          💛  💛          💛\n       💛           💛           💛\n           💛                    💛\n               💛            💛\n                   💛    💛\n                        💛\n.",
        ".           💚                  💚\n        💚  💚          💚  💚\n    💚          💚  🐀𶠠         💚\n       💚           💚           💚\n           💚                    💚\n               💚            💚\n                   💚    💚\n                        💚\n.",
        ".           💙                  💙\n        💙  💙          💙  💙\n    💙          💙  💙          💙\n       💙           💙           💙\n           💙                    💙\n               💙            💙\n                   💙    💙\n                        💙\n.",
        ".           💜                  💜\n        💜  💜          💜  💜\n    💜          💜  💜          💜\n       💜           💜           💜\n           💜                    💜\n               💜            💜\n                   💜    💜\n.",
        ".           ❤️                  ❤️\n        ❤️  ❤️          ❤️  ❤️\n    ❤️          ❤️  ❤️          ❤️\n       ❤️           ❤️           ❤️\n           ❤️                    ❤️\n               ❤️            ❤️\n                   ❤️    ❤️\n                        ❤️\n.",
        ".           🧡                  🧡\n        🧡  🧡          🧡  🧡\n    🧡          🧡  🧡          🧡\n       🧡           🧡           🧡\n           🧡                    🧡\n               🧡            🧡\n                   🧡    🧡\n                        🧡\n.",
        ".           💛                  💛\n        💛  💛          💛  💛\n    💛          💛  💛          💛\n       💛           💛           💛\n           🐀𶰠                   💛\n               💛            💛\n                   💛    💛\n                        💛\n."
    ]
        try:
            for edit in edits_ghalbz:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")


    if message.text == "هزارپا":
        edits_hazarpaa = ["          (█)","      ╚(██)╝\n          (█)","     ╚(███)╝\n      ╚(██)╝\n          (█)","   ╚═(███)═╝\n     ╚(███)╝\n      ╚(██)╝\n          (█)","  ╚═(███)═╝\n   ╚═(███)═╝\n     ╚(███)╝\n      ╚(██)╝\n          (█)","  ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n     ╚(███)╝\n      ╚(██)╝\n          (█)"," ╚═(███)═╝\n  ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n     ╚(███)╝\n      ╚(██)╝\n          (█)","╚═(███)═╝\n ╚═(███)═╝\n  ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n     ╚(███)╝\n      ╚(██)╝\n          (█)"," ╚═(███)═╝\n╚═(███)═╝\n ╚═(███)═╝\n  ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n     ╚(███)╝\n      ╚(██)╝\n          (█)","  ╚═(███)═╝\n ╚═(███)═╝\n╚═(███)═╝\n ╚═(███)═╝\n  ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n     ╚(███)╝\n      ╚(██)╝\n          (█)","   ╚═(███)═╝\n  ╚═(███)═╝\n ╚═(███)═╝\n╚═(███)═╝\n ╚═(███)═╝\n  ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n     ╚(███)╝\n      ╚(██)╝\n          (█)","   ╚═(███)═╝\n   ╚═(███)═╝\n  ╚═(███)═╝\n ╚═(███)═╝\n╚═(███)═╝\n ╚═(███)═╝\n  ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n     ╚(███)╝\n      ╚(██)╝\n          (█)","  ╚═(███)═╝\n   ╚═(███)═╝\n   ╚═(███)═╝\n  ╚═(███)═╝\n ╚═(███)═╝\n╚═(███)═╝\n ╚═(███)═╝\n  ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n     ╚(███)╝\n      ╚(██)╝\n          (█)"," ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n   ╚═(███)═╝\n  ╚═(███)═╝\n ╚═(███)═╝\n╚═(███)═╝\n ╚═(███)═╝\n  ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n     ╚(███)╝\n      ╚(██)╝\n          (█)","╚═(███)═╝\n ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n   ╚═(███)═╝\n  ╚═(███)═╝\n ╚═(███)═╝\n╚═(███)═╝\n ╚═(███)═╝\n  ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n     ╚(███)╝\n      ╚(██)╝\n          (█)","╚═(███)═╝\n╚═(███)═╝\n ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n   ╚═(███)═╝\n  ╚═(███)═╝\n ╚═(███)═╝\n╚═(███)═╝\n ╚═(███)═╝\n  ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n     ╚(███)╝\n      ╚(██)╝\n          (█)","╚═( ͡° ͜ʖ ͡°)═╝\n\n╚═(███)═╝\n╚═(███)═╝\n ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n   ╚═(███)═╝\n  ╚═(███)═╝\n ╚═(███)═╝\n╚═(███)═╝\n ╚═(███)═╝\n  ╚═(███)═╝\n  ╚═(███)═╝\n   ╚═(███)═╝\n     ╚(███)╝\n      ╚(██)╝\n          (█)"]
        try:
            for edit in edits_hazarpaa:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "دوست دارم":
        edits_dustdaram = ["  ▀██▀─▄███▄─▀██─██▀██▀▀█\n  ─██─███─███─██─██─██▄█","  ─██─▀██▄██▀─▀█▄█▀─██▀█\n  ▄██▄▄█▀▀▀─────▀──▄██▄▄█","  ▀██▀─▄███▄─▀██─██▀██▀▀█\n  ─██─███─███─██─██─██▄█\n  ─██─▀██▄██▀─▀█▄█▀─██▀█\n  ▄██▄▄█▀▀▀─────▀──▄██▄▄█"]
        try:
            for edit in edits_dustdaram:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "زنبور":
        edits_zanboor = ["🏥__________🏃‍♂️______________🐝","🏥______🏃‍♂️_______🐝","🏥______🏃‍♂️_____🐝","🏥___🏃‍♂️___🐝","🏥_🏃‍♂️_🐝","در رفت عه☹️🐝"]
        try:
            for edit in edits_zanboor:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")


    if message.text == "هلیکوپتر":
        edits_helikopter = [
        """
        █▬▬▬.◙.▬▬▬█
        ═▂▄▄▓▄▄▂
        ◢◤ █▀▀████▄▄▄▄◢◤
        █▄ █ █▄ ███▀▀▀▀▀▀▀╬
        ◥█████◤
        ══╩══╩═
        ╬═╬
        ╬═╬
        ╬═╬
        ╬═╬
        ╬═╬
        ╬═╬☻/
        ╬═╬/▌
        ╬═╬/  \
        """,
        """
        █▬▬▬.◙.▬█
        ═▂▄▄▓▄▄▂
        ◢◤ █▀▀████▄▄▄▄◢◤
        █▄ █ █▄ ███▀▀▀▀▀▀▀╬
        ◥█████◤
        ══╩══╩═
        ╬═╬
        ╬═╬
        ╬═╬
        ╬═╬
        ╬═╬☻/
        ╬═╬/▌
        ╬═╬/  \
        ╬═╬
        """,
        """
        █▬▬.◙.▬▬█
        ═▂▄▄▓▄▄▂
        ◢◤ █▀▀████▄▄▄▄◢◤
        █▄ █ █▄ ███▀▀▀▀▀▀▀╬
        ◥█████◤
        ══╩══╩═
        ╬═╬
        ╬═╬
        ╬═╬
        ╬═╬☻/
        ╬═╬/▌
        ╬═╬/  \
        ╬═╬
        ╬═╬
        """,
        """
        █▬.◙.▬▬▬█
        ═▂▄▄▓▄▄▂
        ◢◤ █▀▀████▄▄▄▄◢◤
        █▄ █ █▄ ███▀▀▀▀▀▀▀╬
        ◥█████◤
        ══╩══╩═
        ╬═╬
        ╬═╬
        ╬═╬☻/
        ╬═╬/▌
        ╬═╬/  \
        ╬═╬
        ╬═╬
        ╬═╬
        """,
        """
        █▬▬.◙.▬▬█
        ═▂▄▄▓▄▄▂
        ◢◤ █▀▀████▄▄▄▄◢◤
        █▄ █ █▄ ███▀▀▀▀▀▀▀╬
        ◥█████◤
        ══╩══╩═
        ╬═╬
        ╬═╬☻/
        ╬═╬/▌
        ╬═╬/  \
        ╬═╬
        ╬═╬
        ╬═╬
        ╬═╬
        """,
        """
        █▬▬▬.◙.▬█
        ═▂▄▄▓▄▄▂
        ◢◤ █▀▀████▄▄▄▄◢◤
        █▄ █ █▄ ███▀▀▀▀▀▀▀╬
        ◥█████◤
        ══╩══╩═
        ╬═╬☻/
        ╬═╬/▌
        ╬═╬/  \
        ╬═╬
        ╬═╬
        ╬═╬
        ╬═╬
        ╬═╬
        """,
        """
        █▬▬.◙.▬▬█
        ═▂▄▄▓▄▄▂
        ◢◤ █▀▀████▄▄▄▄◢◤
        █▄ █ █▄ ███▀▀▀▀▀▀▀╬
        ◥█████◤
        ══╩══╩═
        ╬═╬
        ╬═╬
        ╬═╬
        ╬═╬
        ╬═╬
        ╬═╬
        ╬═╬
        ╬═╬
        """,
        """
        █▬.◙.▬▬█
        ═▂▄▄▓▄▄▂
        ◢◤ █▀▀████▄▄▄▄◢◤
        █▄ █ █▄ ███▀▀▀▀▀▀▀╬
        ◥█████◤
        ══╩══╩═
        """
    ]
        try:
            for edit in edits_helikopter:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "اوخی":
        edits_okhi = ["🥺اوخییی","🥺","🥺🥺","🥺🥺🥺","🥺🥺🥺🥺","🥺🥺🥺🥺🥺","🥺🥺🥺🥺🥺🥺","🥺🥺🥺🥺🥺🥺🥺","🥺🥺🥺🥺🥺🥺","🥺🥺🥺🥺🥺","🥺🥺🥺🥺","🥺🥺🥺","🥺🥺","🥺"]
        try:
            await message.reply_text(edits_okhi[0])
            for edit in edits_okhi[1:]:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "قهرم":
        edits_ghahram = ["😢😢😢😢","🙁🙁🙁🙁","☹️☹️☹️☹️","😣😣😣😣","😖😖😖😖","😫😫😫😫","🥺🥺🥺🥺","😭😭😭😭","😒"]
        try:
            await message.reply_text(edits_ghahram[0])
            for edit in edits_ghahram[1:]:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "بوس":
        edits_boos = ["loading please wait...","💋 ","💋                         💋","💋                   💋 ","💋             💋","💋          💋","💋        💋","💋      💋","💋   💋","💋  💋","💋"]
        try:
            await message.reply_text(edits_boos[0])
            for edit in edits_boos[1:]:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")

    if message.text == "تپش":
        edits_tapesh = ["💓","💗","💓","💗","💓","💗","💓","💗","💓","💗","💓","💗","💓💗💓💗💓💗💓💗"]
        try:
            for edit in edits_tapesh:
                await message.edit_text(edit)
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error while editing message: {e}")



# ============================================================================
# ==== [Merged from srckde_6a7101ee7addb.py] قابلیت «میو» ====
# ============================================================================
async def meow_loop(client, chat_id, user_id):
    try:
        while True:
            await asyncio.sleep(5 * 60)
            await client.send_message(chat_id, "میو")
    except asyncio.CancelledError:
        pass

async def meow_command_handler(client, message):
    user_id = client.me.id
    text = message.text
    chat_id = message.chat.id
    tasks = MEOW_ACTIVE_TASKS.setdefault(user_id, {})
    if text == "میو فعال":
        if chat_id in tasks:
            await message.reply_text(ui_warn("میو در این چت از قبل فعال است."))
            return
        tasks[chat_id] = asyncio.create_task(meow_loop(client, chat_id, user_id))
        await message.reply_text(ui_toggle("میو در این چت", True) + " (هر ۵ دقیقه)")
    elif text == "میو غیرفعال":
        task = tasks.pop(chat_id, None)
        if task:
            task.cancel()
            await message.reply_text(ui_toggle("میو در این چت", False))
        else:
            await message.reply_text(ui_warn("میو در این چت فعال نبود."))

# ============================================================================
# ==== [Merged from chronicle.py] ریستارت ====
# ============================================================================
async def restart_command_handler(client, message):
    await message.edit_text(ui_ok("سلف در حال ری‌استارت شدن است..."))
    python = sys.executable
    os.execl(python, python, *sys.argv)

# ============================================================================
# ==== [Merged from chronicle.py] قفل ورود (فوروارد کد ورود به «ذخیره شده‌ها») ====
# توجه: در فایل مبدا، کد ورود به یک ربات شخص ثالث (@MrChronicle_bot) فوروارد
# می‌شد که ریسک امنیتی جدی دارد (لو رفتن کد ورود حساب برای فرد دیگر).
# در این نسخه، کد ورود فقط به «ذخیره شده‌های خودتان» (Saved Messages) فوروارد
# می‌شود تا هم قابلیت هشدار ورود حفظ شود و هم حساب شما در خطر نیفتد.
# ============================================================================
async def login_lock_toggle_handler(client, message):
    user_id = client.me.id
    is_on = "on" in message.text
    ANTI_LOGIN_FORWARD_STATUS[user_id] = is_on
    await message.edit_text(ui_toggle("قفل ورود", is_on))

async def login_code_watch_handler(client, message):
    user_id = client.me.id
    if ANTI_LOGIN_FORWARD_STATUS.get(user_id, False):
        try:
            await message.forward("me")
        except Exception as e:
            logging.error(f"Login-lock forward error: {e}")

# ============================================================================
# ==== [Merged from chronicle.py] هشتک / ضخیم / خط‌خورده / تکی / مود ====
# توجه: «ضخیم» (bold) دقیقا همان قابلیت «بولد» موجود در پنل است؛ به همان
# متغیر BOLD_MODE_STATUS وصل شد تا با پنل تداخل نداشته باشد.
# ============================================================================
async def extra_format_toggle_handler(client, message):
    user_id = client.me.id
    text = message.text

    if text in ["هشتک روشن", "hashtag on"]:
        HASHTAG_MODE_STATUS[user_id] = True
        data_manager.update_user_data(user_id, {"settings": {"hashtag": True}})
        await message.edit_text(ui_toggle("هشتک", True))
    elif text in ["هشتک خاموش", "hashtag off"]:
        HASHTAG_MODE_STATUS[user_id] = False
        data_manager.update_user_data(user_id, {"settings": {"hashtag": False}})
        await message.edit_text(ui_toggle("هشتک", False))

    elif text in ["ضخیم روشن", "bold on"]:
        BOLD_MODE_STATUS[user_id] = True
        data_manager.update_user_data(user_id, {"settings": {"bold": True}})
        await message.edit_text(ui_toggle("حالت ضخیم", True))
    elif text in ["ضخیم خاموش", "bold off"]:
        BOLD_MODE_STATUS[user_id] = False
        data_manager.update_user_data(user_id, {"settings": {"bold": False}})
        await message.edit_text(ui_toggle("حالت ضخیم", False))

    elif text in ["خط خورده روشن", "strikethrough on"]:
        STRIKETHROUGH_MODE_STATUS[user_id] = True
        data_manager.update_user_data(user_id, {"settings": {"strikethrough": True}})
        await message.edit_text(ui_toggle("حالت خط‌خورده", True))
    elif text in ["خط خورده خاموش", "strikethrough off"]:
        STRIKETHROUGH_MODE_STATUS[user_id] = False
        data_manager.update_user_data(user_id, {"settings": {"strikethrough": False}})
        await message.edit_text(ui_toggle("حالت خط‌خورده", False))

    elif text in ["تکی روشن", "single on"]:
        SINGLE_MODE_STATUS[user_id] = True
        data_manager.update_user_data(user_id, {"settings": {"single_mode": True}})
        await message.edit_text(ui_toggle("حالت تکی", True))
    elif text in ["تکی خاموش", "single off"]:
        SINGLE_MODE_STATUS[user_id] = False
        data_manager.update_user_data(user_id, {"settings": {"single_mode": False}})
        await message.edit_text(ui_toggle("حالت تکی", False))

    elif text in ["مود روشن", "mode on"]:
        CHAR_MODE_STATUS[user_id] = True
        data_manager.update_user_data(user_id, {"settings": {"char_mode": True}})
        await message.edit_text(ui_toggle("مود", True))
    elif text in ["مود خاموش", "mode off"]:
        CHAR_MODE_STATUS[user_id] = False
        data_manager.update_user_data(user_id, {"settings": {"char_mode": False}})
        await message.edit_text(ui_toggle("مود", False))

async def extra_outgoing_formatter(client, message):
    user_id = client.me.id
    text = message.text
    if not text or re.match(COMMAND_REGEX, text.strip(), re.IGNORECASE):
        return

    if CHAR_MODE_STATUS.get(user_id, False):
        edited = ""
        try:
            for ch in text:
                edited += ch
                await message.edit_text(edited + "\u200C")
                await asyncio.sleep(0.5)
        except Exception:
            pass
        return

    if SINGLE_MODE_STATUS.get(user_id, False):
        try:
            await message.edit_text(f'`{text}`')
        except Exception:
            pass
        return

    final_text = text
    if HASHTAG_MODE_STATUS.get(user_id, False):
        final_text = f"#{final_text}"
    if STRIKETHROUGH_MODE_STATUS.get(user_id, False):
        final_text = f"~~{final_text}~~"
    if final_text != text:
        try:
            await message.edit_text(final_text)
        except Exception:
            pass

# ============================================================================
# ==== [Merged from chronicle.py] سایلنت (حذف پیام‌های ورودی پیوی) ====
# ============================================================================
async def silent_mode_toggle_handler(client, message):
    user_id = client.me.id
    is_on = "روشن" in message.text
    SILENT_MODE_STATUS[user_id] = is_on
    data_manager.update_user_data(user_id, {"settings": {"silent_mode": is_on}})
    await message.edit_text(ui_toggle("حالت سایلنت", is_on))

async def silent_mode_delete_handler(client, message):
    user_id = client.me.id
    if SILENT_MODE_STATUS.get(user_id, False) and message.chat.type == ChatType.PRIVATE:
        try:
            await message.delete()
        except Exception:
            pass

# ============================================================================
# ==== [Merged from chronicle.py] سیو مدیای تایمردار ====
# ============================================================================
async def save_mode_toggle_handler(client, message):
    user_id = client.me.id
    is_on = "روشن" in message.text
    SAVE_MODE_STATUS[user_id] = is_on
    data_manager.update_user_data(user_id, {"settings": {"save_mode": is_on}})
    await message.reply_text(ui_toggle("حالت سیو", is_on))

async def save_timed_media_handler(client, message):
    user_id = client.me.id
    if not SAVE_MODE_STATUS.get(user_id, False) or message.chat.type != ChatType.PRIVATE:
        return
    media_obj = message.photo or message.video
    ttl = getattr(media_obj, "ttl_seconds", None) if media_obj else None
    if media_obj and ttl:
        try:
            path = await client.download_media(message)
            await client.send_document("me", path, caption="مدیا تایمر دار ذخیره شد")
        except Exception as e:
            logging.error(f"Save-mode error: {e}")

# ============================================================================
# ==== [Merged from chronicle.py] پوکر (خواندن بی‌صدای پیوی) ====
# ============================================================================
async def poker_mode_toggle_handler(client, message):
    user_id = client.me.id
    is_on = "روشن" in message.text
    POKER_MODE_STATUS[user_id] = is_on
    data_manager.update_user_data(user_id, {"settings": {"poker_mode": is_on}})
    await message.reply_text(ui_toggle("حالت پوکر", is_on))

async def poker_mode_read_handler(client, message):
    user_id = client.me.id
    if POKER_MODE_STATUS.get(user_id, False) and message.chat.type == ChatType.PRIVATE:
        try:
            await client.read_chat_history(message.chat.id)
        except Exception:
            pass

# ============================================================================
# ==== [Merged from chronicle.py] آنلاین دائمی ====
# ============================================================================
async def keep_online_task(client, user_id):
    """
    به‌جای آنلاین نگه‌داشتن دائمی و ثابت (که یه سیگنال رباتی قویه)،
    بین دوره‌های آنلاین و آفلاین با فاصله‌های تصادفی جابه‌جا می‌شه، شبیه رفتار یه کاربر واقعی.
    """
    while ONLINE_MODE_STATUS.get(user_id, False) and user_id in ACTIVE_BOTS:
        try:
            await safe_call(client.invoke, functions.account.UpdateStatus(offline=False))
        except Exception:
            pass
        # چند دقیقه آنلاین بمون (با کمی تصادفی بودن)
        await asyncio.sleep(random.uniform(240, 420))
        if not (ONLINE_MODE_STATUS.get(user_id, False) and user_id in ACTIVE_BOTS):
            break
        try:
            await safe_call(client.invoke, functions.account.UpdateStatus(offline=True))
        except Exception:
            pass
        # یه مکث کوتاه آفلاین قبل از برگشتن به حالت آنلاین
        await asyncio.sleep(random.uniform(30, 90))

async def online_mode_toggle_handler(client, message):
    user_id = client.me.id
    is_on = "روشن" in message.text
    ONLINE_MODE_STATUS[user_id] = is_on
    data_manager.update_user_data(user_id, {"settings": {"online_mode": is_on}})
    if is_on:
        t = ONLINE_MODE_TASKS.get(user_id)
        if not t or t.done():
            ONLINE_MODE_TASKS[user_id] = asyncio.create_task(keep_online_task(client, user_id))
        await message.reply_text(ui_toggle("حالت آنلاین", True))
    else:
        t = ONLINE_MODE_TASKS.pop(user_id, None)
        if t:
            t.cancel()
        await message.reply_text(ui_toggle("حالت آنلاین", False))

# ============================================================================
# ==== [Merged from chronicle.py] کامنت خودکار روی پست‌های کانال ====
# ============================================================================
async def set_comment_text_handler(client, message):
    user_id = client.me.id
    text = message.text
    for prefix in ["تنظیم کامنت ", "setcomment "]:
        if text.startswith(prefix):
            new_text = text[len(prefix):]
            COMMENT_TEXT[user_id] = new_text
            data_manager.update_user_data(user_id, {"settings": {"comment_text": new_text}})
            await message.edit_text(ui_ok("متن کامنت تنظیم شد."))
            return

async def comment_mode_toggle_handler(client, message):
    user_id = client.me.id
    text = message.text
    if text in ["کامنت روشن", "comment on"]:
        COMMENT_MODE_STATUS[user_id] = True
        data_manager.update_user_data(user_id, {"settings": {"comment_mode": True}})
        await message.edit_text(ui_toggle("کامنت‌گذاری خودکار", True))
    elif text in ["کامنت خاموش", "comment off"]:
        COMMENT_MODE_STATUS[user_id] = False
        data_manager.update_user_data(user_id, {"settings": {"comment_mode": False}})
        await message.edit_text(ui_toggle("کامنت‌گذاری خودکار", False))

async def auto_comment_handler(client, message):
    user_id = client.me.id
    if not COMMENT_MODE_STATUS.get(user_id, False):
        return
    if message.chat.type != ChatType.CHANNEL:
        return
    try:
        peer = await client.resolve_peer(message.chat.id)
        result = await client.invoke(functions.messages.GetDiscussionMessage(peer=peer, msg_id=message.id))
        if result.messages:
            discussion_msg = result.messages[0]
            await client.send_message(
                await client.get_chat(discussion_msg.peer_id.channel_id if hasattr(discussion_msg.peer_id, "channel_id") else discussion_msg.peer_id),
                COMMENT_TEXT.get(user_id, "کامنت تنظیم نشده"),
                reply_to_message_id=discussion_msg.id
            )
    except Exception as e:
        logging.error(f"Comment-bot error: {e}")

# ============================================================================
# ==== [Merged from chronicle.py] ساعت روی نام خانوادگی + بیو زمان/تاریخ ====
# ============================================================================
async def bio_update_task(client, user_id):
    while BIO_TIME_STATUS.get(user_id, False) and user_id in ACTIVE_BOTS:
        try:
            style = USER_FONT_CHOICES.get(user_id, 'stylized')
            now = datetime.now(TEHRAN_TIMEZONE)
            stylized_time = stylize_time(now.strftime("%H:%M"), style)
            date_fmt = BIO_DATE_FORMAT.get(user_id)
            if date_fmt == "jalali":
                current_date = JalaliDate.today().strftime('امروز (%d) %B ☀️ %Y')
            elif date_fmt == "gregorian":
                current_date = now.strftime('امروز (%d) %B ☀️ %Y')
            else:
                current_date = ""
            custom = BIO_CUSTOM_TEXT.get(user_id, "")
            if custom:
                emojis = random.choice(["⛅", "🌥️", "☀️", "💫", "🌙", "🌠", "🌎", "🍕", "🍟", "🎉", "🎁", "🎇", "🎆"])
                new_bio = f"{custom} | {stylized_time} | {current_date} {emojis}"
            else:
                new_bio = f"{current_date} {stylized_time}"
            await client.update_profile(bio=new_bio[:70])
        except Exception:
            pass
        await asyncio.sleep(60)

async def lastname_time_toggle_handler(client, message):
    user_id = client.me.id
    text = message.text

    if "بیو" in text or "bio" in text:
        is_on = ("روشن" in text) or ("on" in text and "off" not in text)
        BIO_TIME_STATUS[user_id] = is_on
        data_manager.update_user_data(user_id, {"settings": {"bio_time": is_on}})
        if is_on:
            t = BIO_UPDATE_TASKS.get(user_id)
            if not t or t.done():
                BIO_UPDATE_TASKS[user_id] = asyncio.create_task(bio_update_task(client, user_id))
        else:
            t = BIO_UPDATE_TASKS.pop(user_id, None)
            if t:
                t.cancel()
        await message.edit_text(ui_toggle("ساعت بیو", is_on))
    else:
        is_on = ("روشن" in text) or ("on" in text and "off" not in text)
        CLOCK_STATUS[user_id] = is_on
        data_manager.update_user_data(user_id, {"settings": {"clock": is_on}})
        if is_on:
            asyncio.create_task(perform_clock_update_now(client, user_id))
        else:
            try:
                me = await client.get_me()
                current_lastname = me.last_name or ""
                clean_name = re.sub(r'(?:\s*' + CLOCK_CHARS_REGEX_CLASS + r'+)+$', '', current_lastname).strip()
                await client.update_profile(last_name=clean_name)
            except Exception:
                pass
        await message.edit_text(ui_toggle("ساعت روی نام", is_on))

async def set_bio_text_handler(client, message):
    user_id = client.me.id
    if message.reply_to_message and message.reply_to_message.text:
        new_bio_text = message.reply_to_message.text
        BIO_CUSTOM_TEXT[user_id] = new_bio_text
        data_manager.update_user_data(user_id, {"settings": {"bio_text": new_bio_text}})
        await message.edit_text(ui_ok(f"بیو تنظیم شد:") + f"\n{new_bio_text}")

async def bio_date_format_handler(client, message):
    user_id = client.me.id
    text = message.text
    if text in ["تاریخ شمسی روشن", "شمسی روشن", "jalali on"]:
        BIO_DATE_FORMAT[user_id] = "jalali"
        data_manager.update_user_data(user_id, {"settings": {"bio_date_format": "jalali"}})
        await message.edit_text(ui_ok("فرمت تاریخ بیو روی شمسی تنظیم شد."))
    elif text in ["تاریخ میلادی روشن", "میلادی روشن", "gregorian on"]:
        BIO_DATE_FORMAT[user_id] = "gregorian"
        data_manager.update_user_data(user_id, {"settings": {"bio_date_format": "gregorian"}})
        await message.edit_text(ui_ok("فرمت تاریخ بیو روی میلادی تنظیم شد."))
    elif text in ["تاریخ خاموش", "خاموش", "date off"]:
        BIO_DATE_FORMAT[user_id] = None
        data_manager.update_user_data(user_id, {"settings": {"bio_date_format": None}})
        await message.edit_text(ui_toggle("تاریخ بیو", False))

# ============================================================================
# ==== [Merged from chronicle.py] پروفایل چرخشی ====
# ============================================================================
async def add_profile_photo_handler(client, message):
    user_id = client.me.id
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.edit_text(ui_warn("این دستور باید روی یک عکس ریپلای شود."))
        return
    await message.edit_text("در حال پردازش...")
    folder = get_profile_folder(user_id)
    photo_count = len(os.listdir(folder)) + 1
    photo_path = os.path.join(folder, f"{photo_count:02}.jpg")
    await client.download_media(message.reply_to_message, file_name=photo_path)
    await message.edit_text(ui_ok(f"عکس به لیست پروفایل چرخشی اضافه شد. ({photo_count:02}.jpg)"))

async def profile_rotation_task(client, user_id):
    folder = get_profile_folder(user_id)
    while PROFILE_ROTATION_STATUS.get(user_id, False) and user_id in ACTIVE_BOTS:
        files = sorted(os.listdir(folder))
        if not files:
            await asyncio.sleep(60)
            continue
        for photo_file in files:
            if not PROFILE_ROTATION_STATUS.get(user_id, False):
                break
            try:
                old_photos = [p async for p in client.get_chat_photos("me", limit=1)]
                await client.set_profile_photo(photo=os.path.join(folder, photo_file))
                if old_photos:
                    try:
                        await client.delete_profile_photos([old_photos[0].file_id])
                    except Exception:
                        pass
            except Exception as e:
                logging.error(f"Profile rotation error: {e}")
            await asyncio.sleep(4000)
        await asyncio.sleep(1)

async def profile_rotation_toggle_handler(client, message):
    user_id = client.me.id
    text = message.text
    if text in ["پروفایل روشن", "profile on"]:
        PROFILE_ROTATION_STATUS[user_id] = True
        data_manager.update_user_data(user_id, {"settings": {"profile_rotation": True}})
        t = PROFILE_ROTATION_TASKS.get(user_id)
        if not t or t.done():
            PROFILE_ROTATION_TASKS[user_id] = asyncio.create_task(profile_rotation_task(client, user_id))
        await message.edit_text(ui_toggle("پروفایل چرخشی", True))
    elif text in ["پروفایل خاموش", "profile off"]:
        PROFILE_ROTATION_STATUS[user_id] = False
        data_manager.update_user_data(user_id, {"settings": {"profile_rotation": False}})
        t = PROFILE_ROTATION_TASKS.pop(user_id, None)
        if t:
            t.cancel()
        await message.edit_text(ui_toggle("پروفایل چرخشی", False))
    elif text in ["پاکسازی پروفایل", "clear profile"]:
        folder = get_profile_folder(user_id)
        for f in os.listdir(folder):
            os.remove(os.path.join(folder, f))
        await message.edit_text(ui_ok("لیست عکس‌های پروفایل چرخشی پاکسازی شد."))

# ============================================================================
# ==== [Merged from chronicle.py] ابزارهای کمکی متفرقه ====
# ============================================================================
async def show_currency_prices_handler(client, message):
    await message.edit_text("در حال دریافت قیمت ارزها...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.codebazan.ir/arz/?type=arz") as resp:
                data = (await resp.json())['Result']
        show_text = ''.join(f"• {item['name']}:  {item['price']}\n" for item in data[:30])
        await message.edit_text(f"**قیمت لحظه‌ای ارزها**\n{UI_DIVIDER}\n{show_text}")
    except Exception as e:
        await message.edit_text(ui_err(f"خطا در دریافت قیمت ارز: {e}"))

async def send_omen_handler(client, message):
    await message.edit_text("در حال گرفتن فال...")
    random_number = random.randint(1, 149)
    media_url = f"https://www.beytoote.com/images/Hafez/{random_number}.gif"
    try:
        await client.send_animation(message.chat.id, media_url, caption="فال حافظ شما :+) ")
    except Exception:
        try:
            await client.send_message(message.chat.id, media_url)
        except Exception:
            pass

async def send_random_bio_handler(client, message):
    await message.edit_text("در حال دریافت بیوگرافی...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.codebazan.ir/bio/") as resp:
                bio_text = await resp.text()
        await message.edit_text(bio_text)
    except Exception as e:
        await message.edit_text(ui_err(f"خطا: {e}"))

async def send_gregorian_date_handler(client, message):
    now = datetime.utcnow()
    rooz = now.strftime("%A")
    tarikh = now.strftime("%Y/%m/%d")
    mah = now.strftime("%B")
    hour = now.strftime("%H:%M:%S - %p")
    await message.edit_text(f"**تاریخ و ساعت امروز**\n{UI_DIVIDER}\nروز: {rooz}\nتاریخ: {tarikh}\nماه: {mah}\nساعت: {hour}")

async def ram_usage_handler(client, message):
    used_memory = await get_used_memory()
    await message.edit_text(f"میزان مصرف رم سرور: {used_memory:.2f} مگابایت")

async def reply_get_id_handler(client, message):
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        await message.edit_text(f"شناسه کاربری: `{target_id}`")

async def _send_inline_result(client, message, bot_username, query, not_found_text):
    try:
        results = await client.get_inline_bot_results(bot_username, query)
        if results and results.results:
            result = random.choice(results.results)
            await client.send_inline_bot_result(message.chat.id, results.query_id, result.id)
        else:
            await message.edit_text(ui_warn(not_found_text))
    except Exception as e:
        try:
            await message.edit_text(ui_err(f"خطا: {e}"))
        except Exception:
            pass

async def send_game_handler(client, message):
    await message.edit_text("در حال دریافت بازی...")
    query = message.text.split(' ', 1)[1] if ' ' in message.text else ''
    await _send_inline_result(client, message, "bodobazibot", query, "بازی‌ای پیدا نشد.")

async def send_like_handler(client, message):
    await message.edit_text("در حال ساخت...")
    like_text = message.text.split("/like-> ", 1)[1] if "/like-> " in message.text else ""
    await _send_inline_result(client, message, "like", like_text, "نتیجه‌ای پیدا نشد.")

async def send_gif_handler(client, message):
    gif_query = message.text.split("/getgif ", 1)[1] if "/getgif " in message.text else ""
    await message.edit_text("در حال جست‌وجوی گیف...")
    await _send_inline_result(client, message, "gif", gif_query, "گیفی پیدا نشد.")

async def send_pic_handler(client, message):
    pic_query = message.text.split("/getpic ", 1)[1] if "/getpic " in message.text else ""
    await message.edit_text("در حال جست‌وجوی عکس...")
    await _send_inline_result(client, message, "pic", pic_query, "تصویری پیدا نشد.")

async def send_meme_handler(client, message):
    meme_query = message.text.split("/getmeme ", 1)[1] if "/getmeme " in message.text else ""
    await message.edit_text("در حال جست‌وجوی میم...")
    await _send_inline_result(client, message, "Persian_Meme_Bot", meme_query, "ممی پیدا نشد.")

async def search_google_handler(client, message):
    google_query = message.text.split("/serchgoogle ", 1)[1] if "/serchgoogle " in message.text else ""
    await message.edit_text("در حال جست‌وجو در گوگل...")
    await _send_inline_result(client, message, "GoogleDEBot", google_query, "نتیجه‌ای پیدا نشد.")

async def search_youtube_handler(client, message):
    youtube_query = message.text.split("/youtube ", 1)[1] if "/youtube " in message.text else ""
    await message.edit_text("در حال جست‌وجو در یوتیوب...")
    await _send_inline_result(client, message, "uVidBot", youtube_query, "ویدیویی پیدا نشد.")

async def send_fonet_handler(client, message):
    await message.edit_text("در حال آماده‌سازی فونت...")
    fonet = message.text.split("/fonet-> ", 1)[1] if "/fonet-> " in message.text else ""
    name = fonet.replace(' ', '+')
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.codebazan.ir/font/?text={name}") as resp:
                font_names = (await resp.json())['result']
        show_fonet = ''.join(f"{i} => {font_names[i]}\n" for i in range(1, min(139, len(font_names))))
        await message.reply_text(show_fonet)
    except Exception as e:
        await message.edit_text(ui_err(f"خطا: {e}"))

# ============================================================================
# ==== [Merged from chronicle.py] منشی پیوی (لیست پیام‌های خوش‌آمد) ====
# ============================================================================
async def auto_reply_pv_commands_handler(client, message):
    user_id = client.me.id
    text = message.text

    if text in ["/autopv on", "/autopv off"]:
        is_on = text.endswith("on")
        AUTO_REPLY_PV_STATUS[user_id] = is_on
        data_manager.update_user_data(user_id, {"settings": {"auto_reply_pv": is_on}})
        await message.reply_text(ui_toggle("منشی پیوی", is_on))

    elif text == "/addpv" and message.reply_to_message:
        reply_message = message.reply_to_message
        entry = {"text": reply_message.text or reply_message.caption or ""}
        if reply_message.photo:
            entry["file_id"] = reply_message.photo.file_id
            entry["type"] = "photo"
        elif reply_message.video:
            entry["file_id"] = reply_message.video.file_id
            entry["type"] = "video"
        elif reply_message.document:
            entry["file_id"] = reply_message.document.file_id
            entry["type"] = "document"
        else:
            entry["type"] = "text"
        msgs = AUTO_REPLY_PV_MESSAGES.setdefault(user_id, [])
        msgs.append(entry)
        data_manager.save_auto_reply_pv_messages(user_id, msgs)
        await message.reply_text(ui_ok("پیام به لیست منشی پیوی اضافه شد."))

    elif text == "/testpv":
        msgs = AUTO_REPLY_PV_MESSAGES.get(user_id, [])
        if msgs:
            for entry in msgs:
                await asyncio.sleep(3)
                await _send_auto_reply_pv_entry(client, message.chat.id, entry)
        else:
            await message.reply_text(ui_warn("لیست منشی پیوی خالی است."))

    elif text == "/restpv":
        AUTO_REPLY_PV_MESSAGES[user_id] = []
        data_manager.save_auto_reply_pv_messages(user_id, [])
        await message.reply_text(ui_ok("لیست منشی پیوی بازنشانی شد."))

async def _send_auto_reply_pv_entry(client, chat_id, entry):
    try:
        entry_type = entry.get("type", "text")
        if entry_type == "photo":
            await client.send_photo(chat_id, entry["file_id"], caption=entry.get("text") or None)
        elif entry_type == "video":
            await client.send_video(chat_id, entry["file_id"], caption=entry.get("text") or None)
        elif entry_type == "document":
            await client.send_document(chat_id, entry["file_id"], caption=entry.get("text") or None)
        else:
            await client.send_message(chat_id, entry.get("text", ""))
    except Exception as e:
        logging.error(f"Auto-reply-pv send error: {e}")

async def auto_reply_pv_incoming_handler(client, message):
    user_id = client.me.id
    if not AUTO_REPLY_PV_STATUS.get(user_id, False) or message.chat.type != ChatType.PRIVATE:
        return
    if not message.from_user or message.from_user.is_self:
        return
    try:
        await client.read_chat_history(message.chat.id)
        await client.send_chat_action(message.chat.id, ChatAction.TYPING)
        await asyncio.sleep(2)
        history = [m async for m in client.get_chat_history(message.chat.id, limit=2)]
        if len(history) == 1:
            msgs = AUTO_REPLY_PV_MESSAGES.get(user_id, [])
            for entry in msgs:
                await asyncio.sleep(3)
                await _send_auto_reply_pv_entry(client, message.chat.id, entry)
    except Exception as e:
        logging.error(f"Auto-reply-pv error: {e}")


async def anti_delete_cache_handler(client, message):
    user_id = client.me.id
    if not ANTI_DELETE_STATUS.get(user_id, False):
        return
    cache = DELETED_MSG_CACHE.setdefault(user_id, OrderedDict())
    cache[message.id] = message
    if len(cache) > MAX_ANTI_DELETE_CACHE:
        cache.popitem(last=False)

async def anti_delete_forward_handler(client, messages):
    user_id = client.me.id
    if not ANTI_DELETE_STATUS.get(user_id, False):
        return
    cache = DELETED_MSG_CACHE.get(user_id)
    if not cache:
        return
    for dm in messages:
        cached_msg = cache.pop(dm.id, None)
        if not cached_msg:
            continue
        try:
            who = cached_msg.from_user.first_name if cached_msg.from_user else "ناشناس"
            when = cached_msg.date.strftime("%H:%M:%S") if cached_msg.date else "-"
            await client.send_message("me", f"**پیام حذف\u200cشده**\n{UI_DIVIDER}\nاز: {who}\nساعت ارسال: {when}")
            await cached_msg.copy("me")
        except Exception as e:
            logging.error(f"خطا در فوروارد پیام حذف‌شده: {e}")

async def start_bot_instance(session_string: str, phone: str, user_id: int, font_style: str = 'stylized', disable_clock: bool = False):
    client = Client(f"bot_{user_id}", api_id=API_ID, api_hash=API_HASH, session_string=session_string)
    
    try:
        await client.start()
        user_id = (await client.get_me()).id
    except Exception as e:
        logging.error(f"Failed to start bot for {phone}: {e}")
        return

    if user_id in ACTIVE_BOTS:
        for t in ACTIVE_BOTS[user_id][1]:
            t.cancel()
    
    USER_FONT_CHOICES[user_id] = font_style
    CLOCK_STATUS[user_id] = not disable_clock
    
    data_manager.update_user_data(user_id, {
        "settings": {
            "font": font_style,
            "clock": not disable_clock
        }
    })
    
    client.add_handler(MessageHandler(god_mode_handler, filters.incoming & ~filters.me), group=-10)
    client.add_handler(MessageHandler(lambda c, m: m.delete() if PV_LOCK_STATUS.get(c.me.id) else None, filters.private & ~filters.me & ~filters.bot), group=-5)
    client.add_handler(MessageHandler(lambda c, m: c.read_chat_history(m.chat.id) if AUTO_SEEN_STATUS.get(c.me.id) else None, filters.private & ~filters.me), group=-4)
    client.add_handler(MessageHandler(incoming_message_manager, filters.all & ~filters.me), group=-3)
    client.add_handler(MessageHandler(anti_delete_cache_handler, filters.private), group=-2)
    client.add_handler(DeletedMessagesHandler(anti_delete_forward_handler))
    client.add_handler(MessageHandler(outgoing_message_modifier, filters.text & filters.me & ~filters.reply), group=-1)
    client.add_handler(MessageHandler(help_controller, filters.me & filters.regex("^راهنما$")))
    client.add_handler(CallbackQueryHandler(
        lambda c, cb: help_page_callback_handler(c, cb, user_id),
        filters.regex(r"^helppage_\d+$")
    ))
    client.add_handler(MessageHandler(panel_command_controller, filters.me & filters.regex(r"^(پنل|panel)$")))
    client.add_handler(MessageHandler(reply_based_controller, filters.me)) 
    
    enemy_filter = filters.create(lambda _, c, m: bool(m.from_user and ((m.from_user.id, m.chat.id) in ACTIVE_ENEMIES.get(c.me.id, set()) or GLOBAL_ENEMY_STATUS.get(c.me.id))))
    client.add_handler(MessageHandler(enemy_handler, enemy_filter & ~filters.me), group=1)
    
    client.add_handler(MessageHandler(secretary_auto_reply_handler, filters.private & ~filters.me), group=1)

    # ==== [Merged from chronicle.py & srckde_6a7101ee7addb.py] ثبت هندلرهای جدید ====
    client.add_handler(MessageHandler(meow_command_handler, filters.me & filters.regex("^(میو فعال|میو غیرفعال)$")))
    client.add_handler(MessageHandler(restart_command_handler, filters.me & filters.regex(r"^(ریستارت|ریس|/restart)$")))

    client.add_handler(MessageHandler(login_lock_toggle_handler, filters.me & filters.regex(r"^/login (on|off)$")))
    client.add_handler(MessageHandler(login_code_watch_handler, filters.user(777000)))

    client.add_handler(MessageHandler(game_animations_handler, filters.text & filters.me & ~filters.reply), group=2)

    extra_format_regex = (
        r"^(هشتک روشن|hashtag on|هشتک خاموش|hashtag off|"
        r"ضخیم روشن|bold on|ضخیم خاموش|bold off|"
        r"خط خورده روشن|strikethrough on|خط خورده خاموش|strikethrough off|"
        r"تکی روشن|single on|تکی خاموش|single off|مود روشن|mode on|مود خاموش|mode off)$"
    )
    client.add_handler(MessageHandler(extra_format_toggle_handler, filters.me & filters.regex(extra_format_regex)))
    client.add_handler(MessageHandler(extra_outgoing_formatter, filters.text & filters.me & ~filters.reply), group=3)

    client.add_handler(MessageHandler(silent_mode_toggle_handler, filters.me & filters.regex(r"^(سایلنت روشن|سایلنت خاموش)$")))
    client.add_handler(MessageHandler(silent_mode_delete_handler, filters.private & ~filters.me), group=1)

    client.add_handler(MessageHandler(save_mode_toggle_handler, filters.me & filters.regex(r"^(سیو روشن|سیو خاموش)$")))
    client.add_handler(MessageHandler(save_timed_media_handler, filters.private & ~filters.me), group=1)

    client.add_handler(MessageHandler(poker_mode_toggle_handler, filters.me & filters.regex(r"^(پوکر روشن|پوکر خاموش)$")))
    client.add_handler(MessageHandler(poker_mode_read_handler, filters.private & ~filters.me), group=1)

    client.add_handler(MessageHandler(online_mode_toggle_handler, filters.me & filters.regex(r"^(آنلاین روشن|آنلاین خاموش)$")))

    client.add_handler(MessageHandler(set_comment_text_handler, filters.me & filters.regex(r"^(تنظیم کامنت|setcomment) .+$")))
    client.add_handler(MessageHandler(comment_mode_toggle_handler, filters.me & filters.regex(r"^(کامنت روشن|comment on|کامنت خاموش|comment off)$")))
    client.add_handler(MessageHandler(auto_comment_handler, filters.channel & ~filters.me), group=1)

    client.add_handler(MessageHandler(
        lastname_time_toggle_handler,
        filters.me & filters.regex(r"^(ساعت روشن|time on|ساعت خاموش|time off|ساعت بیو روشن|time bio on|ساعت بیو خاموش|time bio off)$")
    ))
    client.add_handler(MessageHandler(set_bio_text_handler, filters.me & filters.regex(r"^(تنظیم بیو|set bio)$") & filters.reply))
    client.add_handler(MessageHandler(
        bio_date_format_handler,
        filters.me & filters.regex(r"^(تاریخ شمسی روشن|شمسی روشن|jalali on|تاریخ میلادی روشن|میلادی روشن|gregorian on|تاریخ خاموش|خاموش|date off)$")
    ))

    client.add_handler(MessageHandler(add_profile_photo_handler, filters.me & filters.regex(r"^(اد پروفایل|add profile)$") & filters.reply))
    client.add_handler(MessageHandler(
        profile_rotation_toggle_handler,
        filters.me & filters.regex(r"^(پروفایل روشن|profile on|پروفایل خاموش|profile off|پاکسازی پروفایل|clear profile)$")
    ))

    client.add_handler(MessageHandler(show_currency_prices_handler, filters.me & filters.regex(r"^(قیمت ارز|price)$")))
    client.add_handler(MessageHandler(send_omen_handler, filters.me & filters.regex(r"^(فال|fall)$")))
    client.add_handler(MessageHandler(send_random_bio_handler, filters.me & filters.regex(r"^(بیو رندوم|random bio)$")))
    client.add_handler(MessageHandler(send_gregorian_date_handler, filters.me & filters.regex(r"^(تاریخ امروز|today's date)$")))
    client.add_handler(MessageHandler(ram_usage_handler, filters.me & filters.regex(r"^رم$")))
    client.add_handler(MessageHandler(reply_get_id_handler, filters.me & filters.regex(r"^(ایدی|آیدی|Id|id)$") & filters.reply))

    client.add_handler(MessageHandler(send_game_handler, filters.me & filters.regex(r"^(گیممم|Play)(\s.*)?$")))
    client.add_handler(MessageHandler(send_fonet_handler, filters.me & filters.regex(r"^/fonet-> .+$")))
    client.add_handler(MessageHandler(send_like_handler, filters.me & filters.regex(r"^/like-> .+$")))
    client.add_handler(MessageHandler(send_gif_handler, filters.me & filters.regex(r"^/getgif .+$")))
    client.add_handler(MessageHandler(send_pic_handler, filters.me & filters.regex(r"^/getpic .+$")))
    client.add_handler(MessageHandler(send_meme_handler, filters.me & filters.regex(r"^/getmeme .+$")))
    client.add_handler(MessageHandler(search_google_handler, filters.me & filters.regex(r"^/serchgoogle .+$")))
    client.add_handler(MessageHandler(search_youtube_handler, filters.me & filters.regex(r"^/youtube .+$")))

    client.add_handler(MessageHandler(
        auto_reply_pv_commands_handler,
        filters.me & filters.regex(r"^(/autopv (on|off)|/addpv|/testpv|/restpv)$")
    ))
    client.add_handler(MessageHandler(auto_reply_pv_incoming_handler, filters.private & ~filters.me), group=1)

    client.add_handler(MessageHandler(ai_assistant_toggle_handler, filters.me & filters.regex(r"^(دستیار روشن|دستیار خاموش)$")))
    client.add_handler(MessageHandler(ai_test_handler, filters.me & filters.regex(r"^تست هوش مصنوعی$")))

    # دستیار AI: پیوی بدون ریپلای، گروه فقط با ریپلای به پیام صاحب اکانت.
    client.add_handler(
        MessageHandler(
            ai_assistant_reply_handler,
            filters.private & ~filters.me & ~filters.bot & ~filters.channel,
        ),
        group=4,
    )
    client.add_handler(
        MessageHandler(
            ai_assistant_reply_handler,
            filters.reply & ~filters.me & ~filters.bot & ~filters.channel,
        ),
        group=4,
    )
    # ==== [End merged handler registration] ====

    if register_call_stream_handlers is not None:
        register_call_stream_handlers(client)

    tasks = [
        asyncio.create_task(update_profile_clock(client, user_id)),
        asyncio.create_task(anti_login_task(client, user_id)),
        asyncio.create_task(status_action_task(client, user_id))
    ]

    # راه‌اندازی مجدد تسک‌های پس‌زمینه‌ی قابلیت‌های ادغام‌شده در صورت فعال بودن قبلی
    if BIO_TIME_STATUS.get(user_id, False):
        tasks.append(asyncio.create_task(bio_update_task(client, user_id)))
        BIO_UPDATE_TASKS[user_id] = tasks[-1]
    if PROFILE_ROTATION_STATUS.get(user_id, False):
        tasks.append(asyncio.create_task(profile_rotation_task(client, user_id)))
        PROFILE_ROTATION_TASKS[user_id] = tasks[-1]
    if ONLINE_MODE_STATUS.get(user_id, False):
        tasks.append(asyncio.create_task(keep_online_task(client, user_id)))
        ONLINE_MODE_TASKS[user_id] = tasks[-1]

    ACTIVE_BOTS[user_id] = (client, tasks)
    logging.info(f"✅ Bot started for user {user_id}")

manager_bot = Client("manager_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- فراداده‌ی هر بخش پنل: عنوان و توضیح کوتاه، برای هدر یکدست هر صفحه ---
CATEGORY_META = {
    "main":    ("پنل مدیریت سلف‌تلتون", "یک بخش را برای تنظیم انتخاب کنید."),
    "format":  ("ظاهر پیام\u200cها", "استایل نمایش پیام\u200cهای ارسالی شما."),
    "time":    ("ساعت و تاریخ", "نمایش ساعت روی نام و بیو، فونت و فرمت تاریخ."),
    "profile": ("پروفایل", "چرخش خودکار عکس پروفایل."),
    "auto":    ("حالت\u200cهای خودکار", "قابلیت\u200cهایی که در پس\u200cزمینه اجرا می\u200cشوند."),
    "lang":    ("ترجمه خودکار", "ترجمه‌ی زنده‌ی پیام‌های ارسالی شما."),
}

AUTO_FEATURE_DESCRIPTIONS = (
    "**توضیح قابلیت‌های خودکار**\n"
    "─────────────────\n"
    "منشی پیوی: به پیام‌های جدید پیوی یک‌بار پاسخ خودکار می‌دهد.\n"
    "سین خودکار: پیام‌های پیوی را بدون علامت «دیده شد» می‌خواند.\n"
    "قفل پیوی: امکان ارسال پیام در پیوی را برای دیگران می‌بندد.\n"
    "انتی لاگین: ورود از دستگاه‌های ناشناس را شناسایی و خارج می‌کند.\n"
    "انتی حذف: پیام‌های حذف‌شده توسط طرف مقابل را نگه می‌دارد.\n"
    "تایپینگ / حالت بازی: وضعیت «در حال تایپ/بازی» را در چت‌ها نمایش می‌دهد.\n"
    "سایلنت: پیام‌های ورودی پیوی را به‌طور خودکار حذف می‌کند.\n"
    "سیو مدیا: مدیای تایمردار دریافتی را ذخیره می‌کند.\n"
    "پوکر: پیام‌های پیوی را بی‌صدا (بدون سین) می‌خواند.\n"
    "آنلاین: اکانت را بیشتر اوقات آنلاین نگه می‌دارد.\n"
    "کامنت خودکار: زیر پست‌های کانال، کامنت خودکار می‌گذارد.\n"
    "دستیار AI: وقتی کسی روی یکی از پیام‌های شما ریپلای کند، به‌جای شما با هوش مصنوعی پاسخ می‌دهد."
)

def _count_active(user_id, status_dicts):
    return sum(1 for d in status_dicts if d.get(user_id, False))

def build_cmdlist_view(page_idx, user_id):
    """صفحه‌ی فعلی از جدول کامل دستورات را با دکمه‌های ناوبری می‌سازد (به‌جای ارسال یک‌جا به ذخیره‌شده‌ها)."""
    text, page_idx = _paged_view(FULL_COMMAND_TABLE_PAGES, page_idx, "📋 جدول کامل دستورات")
    total = len(FULL_COMMAND_TABLE_PAGES)
    nav_row = []
    if page_idx > 0:
        nav_row.append(InlineKeyboardButton("‹ قبلی", callback_data=f"cmdpage_{page_idx-1}_{user_id}"))
    if page_idx < total - 1:
        nav_row.append(InlineKeyboardButton("بعدی ›", callback_data=f"cmdpage_{page_idx+1}_{user_id}"))
    rows = []
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton("‹ بازگشت به پنل", callback_data=f"back_main_{user_id}")])
    return text, InlineKeyboardMarkup(rows)

def generate_main_menu(user_id):
    n_format = _count_active(user_id, [BOLD_MODE_STATUS, HASHTAG_MODE_STATUS, STRIKETHROUGH_MODE_STATUS,
                                        SINGLE_MODE_STATUS, CHAR_MODE_STATUS])
    n_time = _count_active(user_id, [CLOCK_STATUS, BIO_TIME_STATUS])
    n_profile = _count_active(user_id, [PROFILE_ROTATION_STATUS])
    n_auto = _count_active(user_id, [SECRETARY_MODE_STATUS, AUTO_SEEN_STATUS, PV_LOCK_STATUS, ANTI_LOGIN_STATUS,
                                      ANTI_DELETE_STATUS, TYPING_MODE_STATUS, PLAYING_MODE_STATUS, SILENT_MODE_STATUS,
                                      SAVE_MODE_STATUS, POKER_MODE_STATUS, ONLINE_MODE_STATUS, COMMENT_MODE_STATUS,
                                      AI_ASSISTANT_STATUS])
    n_lang = 1 if AUTO_TRANSLATE_TARGET.get(user_id) else 0

    def lbl(base, n):
        return f"{base} ({n} فعال)" if n else base

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(lbl("🎨 ظاهر پیام\u200cها", n_format), callback_data=f"cat_format_{user_id}"),
         InlineKeyboardButton(lbl("⏰ ساعت و تاریخ", n_time), callback_data=f"cat_time_{user_id}")],
        [InlineKeyboardButton(lbl("🖼 پروفایل", n_profile), callback_data=f"cat_profile_{user_id}"),
         InlineKeyboardButton(lbl("⚙️ حالت\u200cهای خودکار", n_auto), callback_data=f"cat_auto_{user_id}")],
        [InlineKeyboardButton(lbl("🌐 ترجمه خودکار", n_lang), callback_data=f"cat_lang_{user_id}")],
        [InlineKeyboardButton("📋 لیست کامل دستورات", callback_data=f"action_fulllist_{user_id}")],
        [InlineKeyboardButton("✕ بستن پنل", callback_data=f"close_panel_{user_id}")]
    ])

def generate_category_menu(user_id, category):
    back_btn = InlineKeyboardButton("‹ بازگشت", callback_data=f"back_main_{user_id}")

    if category == "format":
        s_bold = ui_status(BOLD_MODE_STATUS.get(user_id, False))
        s_hash = ui_status(HASHTAG_MODE_STATUS.get(user_id, False))
        s_strike = ui_status(STRIKETHROUGH_MODE_STATUS.get(user_id, False))
        s_single = ui_status(SINGLE_MODE_STATUS.get(user_id, False))
        s_char = ui_status(CHAR_MODE_STATUS.get(user_id, False))
        rows = [
            [InlineKeyboardButton(f"بولد  {s_bold}", callback_data=f"toggle_bold_{user_id}"),
             InlineKeyboardButton(f"هشتک  {s_hash}", callback_data=f"toggle_hashtag_{user_id}")],
            [InlineKeyboardButton(f"خط\u200cخورده  {s_strike}", callback_data=f"toggle_strike_{user_id}"),
             InlineKeyboardButton(f"تکی  {s_single}", callback_data=f"toggle_single_{user_id}")],
            [InlineKeyboardButton(f"مود  {s_char}", callback_data=f"toggle_charmode_{user_id}")],
            [back_btn],
        ]
    elif category == "time":
        s_clock = ui_status(CLOCK_STATUS.get(user_id, True))
        s_biot = ui_status(BIO_TIME_STATUS.get(user_id, False))
        fmt = BIO_DATE_FORMAT.get(user_id)
        fmt_label = {"jalali": "شمسی", "gregorian": "میلادی", None: "خاموش"}[fmt]
        preview = stylize_time("12:34", USER_FONT_CHOICES.get(user_id, 'stylized'))
        rows = [
            [InlineKeyboardButton(f"ساعت روی نام  {s_clock}", callback_data=f"toggle_clock_{user_id}"),
             InlineKeyboardButton(f"ساعت بیو  {s_biot}", callback_data=f"toggle_biotime_{user_id}")],
            [InlineKeyboardButton(f"فونت ساعت: {preview}", callback_data=f"cycle_font_{user_id}")],
            [InlineKeyboardButton(f"فرمت تاریخ بیو: {fmt_label}", callback_data=f"cycle_dateformat_{user_id}")],
            [back_btn],
        ]
    elif category == "profile":
        s_rot = ui_status(PROFILE_ROTATION_STATUS.get(user_id, False))
        rows = [
            [InlineKeyboardButton(f"پروفایل چرخشی  {s_rot}", callback_data=f"toggle_profilerot_{user_id}")],
            [InlineKeyboardButton("پاکسازی لیست عکس‌ها", callback_data=f"confirm_clearprofile_{user_id}")],
            [back_btn],
        ]
    elif category == "auto":
        s_sec = ui_status(SECRETARY_MODE_STATUS.get(user_id, False))
        s_seen = ui_status(AUTO_SEEN_STATUS.get(user_id, False))
        s_pv = ui_status(PV_LOCK_STATUS.get(user_id, False))
        s_anti = ui_status(ANTI_LOGIN_STATUS.get(user_id, False))
        s_type = ui_status(TYPING_MODE_STATUS.get(user_id, False))
        s_game = ui_status(PLAYING_MODE_STATUS.get(user_id, False))
        s_silent = ui_status(SILENT_MODE_STATUS.get(user_id, False))
        s_save = ui_status(SAVE_MODE_STATUS.get(user_id, False))
        s_poker = ui_status(POKER_MODE_STATUS.get(user_id, False))
        s_online = ui_status(ONLINE_MODE_STATUS.get(user_id, False))
        s_comment = ui_status(COMMENT_MODE_STATUS.get(user_id, False))
        s_antidel = ui_status(ANTI_DELETE_STATUS.get(user_id, False))
        s_ai = ui_status(AI_ASSISTANT_STATUS.get(user_id, False))
        rows = [
            [InlineKeyboardButton(f"منشی پیوی  {s_sec}", callback_data=f"toggle_sec_{user_id}"),
             InlineKeyboardButton(f"سین خودکار  {s_seen}", callback_data=f"toggle_seen_{user_id}")],
            [InlineKeyboardButton(f"قفل پیوی  {s_pv}", callback_data=f"toggle_pv_{user_id}"),
             InlineKeyboardButton(f"انتی لاگین  {s_anti}", callback_data=f"toggle_anti_{user_id}")],
            [InlineKeyboardButton(f"انتی حذف  {s_antidel}", callback_data=f"toggle_antidel_{user_id}")],
            [InlineKeyboardButton(f"تایپینگ  {s_type}", callback_data=f"toggle_type_{user_id}"),
             InlineKeyboardButton(f"حالت بازی  {s_game}", callback_data=f"toggle_game_{user_id}")],
            [InlineKeyboardButton(f"سایلنت  {s_silent}", callback_data=f"toggle_silent_{user_id}"),
             InlineKeyboardButton(f"سیو مدیا  {s_save}", callback_data=f"toggle_save_{user_id}")],
            [InlineKeyboardButton(f"پوکر  {s_poker}", callback_data=f"toggle_poker_{user_id}"),
             InlineKeyboardButton(f"آنلاین  {s_online}", callback_data=f"toggle_online_{user_id}")],
            [InlineKeyboardButton(f"کامنت خودکار  {s_comment}", callback_data=f"toggle_comment_{user_id}")],
            [InlineKeyboardButton(f"دستیار AI  {s_ai}", callback_data=f"toggle_ai_{user_id}")],
            [InlineKeyboardButton("ℹ️ این‌ها چی هستن؟", callback_data=f"info_auto_{user_id}")],
            [back_btn],
        ]
    elif category == "lang":
        t_lang = AUTO_TRANSLATE_TARGET.get(user_id)
        l_en = ui_status(t_lang == "en")
        l_ru = ui_status(t_lang == "ru")
        l_cn = ui_status(t_lang == "zh-CN")
        rows = [
            [InlineKeyboardButton(f"انگلیسی  {l_en}", callback_data=f"lang_en_{user_id}"),
             InlineKeyboardButton(f"روسی  {l_ru}", callback_data=f"lang_ru_{user_id}"),
             InlineKeyboardButton(f"چینی  {l_cn}", callback_data=f"lang_cn_{user_id}")],
            [back_btn],
        ]
    else:
        rows = [[back_btn]]

    return InlineKeyboardMarkup(rows)

def _format_preview(user_id):
    """نمونه‌ی زنده‌ی پیام با توجه به استایل‌های فعلاً روشن، تا کاربر بدون تست واقعی نتیجه رو ببینه."""
    sample = "این یک پیام نمونه است"
    if HASHTAG_MODE_STATUS.get(user_id, False):
        sample += " #نمونه"
    if STRIKETHROUGH_MODE_STATUS.get(user_id, False):
        sample = f"~~{sample}~~"
    if BOLD_MODE_STATUS.get(user_id, False):
        sample = f"**{sample}**"
    return f"پیش‌نمایش: {sample}"

def generate_panel_view(user_id, category):
    """متن هدر + کیبورد یک صفحه‌ی پنل را یکجا برمی‌گرداند (برای حس یکدست هر صفحه)."""
    title, subtitle = CATEGORY_META.get(category, CATEGORY_META["main"])
    if category == "main":
        display_name = data_manager.get_user_data(user_id).get("first_name") or "بدون نام"
        text = panel_text(title, subtitle, [f"شناسه کاربری: `{display_name}`", "وضعیت اتصال: برقرار"])
        markup = generate_main_menu(user_id)
    elif category == "format":
        text = panel_text(title, subtitle, [_format_preview(user_id)])
        markup = generate_category_menu(user_id, category)
    else:
        text = panel_text(title, subtitle)
        markup = generate_category_menu(user_id, category)
    return text, markup

@manager_bot.on_inline_query()
async def inline_panel_handler(client, query):
    user_id = query.from_user.id
    if query.query == "panel":
        text, markup = generate_panel_view(user_id, "main")
        result = InlineQueryResultArticle(
            title="پنل مدیریت",
            input_message_content=InputTextMessageContent(text),
            reply_markup=markup,
            thumb_url="https://telegra.ph/file/1e3b567786f7800e80816.jpg"
        )
        await query.answer([result], cache_time=0)

@manager_bot.on_callback_query()
async def callback_panel_handler(client, callback):
    data = callback.data.split("_")
    action = "_".join(data[:-1])
    target_user_id = int(data[-1])
    
    if callback.from_user.id != target_user_id:
        await callback.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
        return

    settings_update = {}

    if action == "toggle_clock":
        new_state = not CLOCK_STATUS.get(target_user_id, True)
        CLOCK_STATUS[target_user_id] = new_state
        settings_update["clock"] = new_state
        
        if target_user_id in ACTIVE_BOTS:
            bot_client = ACTIVE_BOTS[target_user_id][0]
            if new_state:
                asyncio.create_task(perform_clock_update_now(bot_client, target_user_id))
            else:
                try:
                    me = await bot_client.get_me()
                    current_lastname = me.last_name or ""
                    clean_name = re.sub(r'(?:\s*' + CLOCK_CHARS_REGEX_CLASS + r'+)+$', '', current_lastname).strip()
                    if clean_name != current_lastname:
                        await bot_client.update_profile(last_name=clean_name)
                except: pass
    
    elif action == "cycle_font":
        cur = USER_FONT_CHOICES.get(target_user_id, 'stylized')
        idx = (FONT_KEYS_ORDER.index(cur) + 1) % len(FONT_KEYS_ORDER)
        new_font = FONT_KEYS_ORDER[idx]
        USER_FONT_CHOICES[target_user_id] = new_font
        CLOCK_STATUS[target_user_id] = True
        settings_update["font"] = new_font
        settings_update["clock"] = True
        
        if target_user_id in ACTIVE_BOTS:
            asyncio.create_task(perform_clock_update_now(ACTIVE_BOTS[target_user_id][0], target_user_id))
    
    elif action == "toggle_bold":
        new_state = not BOLD_MODE_STATUS.get(target_user_id, False)
        BOLD_MODE_STATUS[target_user_id] = new_state
        settings_update["bold"] = new_state
    
    elif action == "toggle_sec":
        new_state = not SECRETARY_MODE_STATUS.get(target_user_id, False)
        SECRETARY_MODE_STATUS[target_user_id] = new_state
        settings_update["secretary"] = new_state
    
    elif action == "toggle_seen":
        new_state = not AUTO_SEEN_STATUS.get(target_user_id, False)
        AUTO_SEEN_STATUS[target_user_id] = new_state
        settings_update["auto_seen"] = new_state
    
    elif action == "toggle_pv":
        new_state = not PV_LOCK_STATUS.get(target_user_id, False)
        PV_LOCK_STATUS[target_user_id] = new_state
        settings_update["pv_lock"] = new_state
    
    elif action == "toggle_anti":
        new_state = not ANTI_LOGIN_STATUS.get(target_user_id, False)
        ANTI_LOGIN_STATUS[target_user_id] = new_state
        settings_update["anti_login"] = new_state

    elif action == "toggle_antidel":
        new_state = not ANTI_DELETE_STATUS.get(target_user_id, False)
        ANTI_DELETE_STATUS[target_user_id] = new_state
        settings_update["anti_delete"] = new_state
        if not new_state:
            DELETED_MSG_CACHE.pop(target_user_id, None)
    
    elif action == "toggle_type":
        new_state = not TYPING_MODE_STATUS.get(target_user_id, False)
        TYPING_MODE_STATUS[target_user_id] = new_state
        if new_state:
            PLAYING_MODE_STATUS[target_user_id] = False
            settings_update["playing"] = False
        settings_update["typing"] = new_state
    
    elif action == "toggle_game":
        new_state = not PLAYING_MODE_STATUS.get(target_user_id, False)
        PLAYING_MODE_STATUS[target_user_id] = new_state
        if new_state:
            TYPING_MODE_STATUS[target_user_id] = False
            settings_update["typing"] = False
        settings_update["playing"] = new_state
    
    elif action == "toggle_g_enemy":
        new_state = not GLOBAL_ENEMY_STATUS.get(target_user_id, False)
        GLOBAL_ENEMY_STATUS[target_user_id] = new_state
        settings_update["global_enemy"] = new_state
    
    elif action.startswith("lang_"):
        lang_map = {"en": "en", "ru": "ru", "cn": "zh-CN"}
        btn_lang = action.split("_")[1]
        actual_lang = lang_map.get(btn_lang)
        
        current = AUTO_TRANSLATE_TARGET.get(target_user_id)
        new_lang = actual_lang if current != actual_lang else None
        
        AUTO_TRANSLATE_TARGET[target_user_id] = new_lang
        settings_update["translate"] = new_lang
    
    elif action == "toggle_hashtag":
        new_state = not HASHTAG_MODE_STATUS.get(target_user_id, False)
        HASHTAG_MODE_STATUS[target_user_id] = new_state
        settings_update["hashtag"] = new_state

    elif action == "toggle_strike":
        new_state = not STRIKETHROUGH_MODE_STATUS.get(target_user_id, False)
        STRIKETHROUGH_MODE_STATUS[target_user_id] = new_state
        settings_update["strikethrough"] = new_state

    elif action == "toggle_single":
        new_state = not SINGLE_MODE_STATUS.get(target_user_id, False)
        SINGLE_MODE_STATUS[target_user_id] = new_state
        settings_update["single_mode"] = new_state

    elif action == "toggle_charmode":
        new_state = not CHAR_MODE_STATUS.get(target_user_id, False)
        CHAR_MODE_STATUS[target_user_id] = new_state
        settings_update["char_mode"] = new_state

    elif action == "toggle_biotime":
        new_state = not BIO_TIME_STATUS.get(target_user_id, False)
        BIO_TIME_STATUS[target_user_id] = new_state
        settings_update["bio_time"] = new_state
        if target_user_id in ACTIVE_BOTS:
            bot_client = ACTIVE_BOTS[target_user_id][0]
            if new_state and (target_user_id not in BIO_UPDATE_TASKS or BIO_UPDATE_TASKS[target_user_id].done()):
                BIO_UPDATE_TASKS[target_user_id] = asyncio.create_task(bio_update_task(bot_client, target_user_id))
            elif not new_state and target_user_id in BIO_UPDATE_TASKS:
                BIO_UPDATE_TASKS.pop(target_user_id).cancel()

    elif action == "cycle_dateformat":
        order = ["jalali", "gregorian", None]
        cur = BIO_DATE_FORMAT.get(target_user_id)
        new_fmt = order[(order.index(cur) + 1) % 3]
        BIO_DATE_FORMAT[target_user_id] = new_fmt
        settings_update["bio_date_format"] = new_fmt

    elif action == "toggle_profilerot":
        new_state = not PROFILE_ROTATION_STATUS.get(target_user_id, False)
        PROFILE_ROTATION_STATUS[target_user_id] = new_state
        settings_update["profile_rotation"] = new_state
        if target_user_id in ACTIVE_BOTS:
            bot_client = ACTIVE_BOTS[target_user_id][0]
            if new_state and (target_user_id not in PROFILE_ROTATION_TASKS or PROFILE_ROTATION_TASKS[target_user_id].done()):
                PROFILE_ROTATION_TASKS[target_user_id] = asyncio.create_task(profile_rotation_task(bot_client, target_user_id))
            elif not new_state and target_user_id in PROFILE_ROTATION_TASKS:
                PROFILE_ROTATION_TASKS.pop(target_user_id).cancel()

    elif action == "confirm_clearprofile":
        # اکشن غیرقابل‌برگشته، قبلش تأیید می‌گیریم
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ بله، پاک کن", callback_data=f"do_clearprofile_{target_user_id}"),
             InlineKeyboardButton("✖️ انصراف", callback_data=f"cat_profile_{target_user_id}")]
        ])
        try:
            await callback.edit_message_text(
                ui_warn("مطمئنی؟ همه‌ی عکس‌های چرخشی پاک می‌شن و قابل بازگشت نیست."),
                reply_markup=kb
            )
        except: pass
        await callback.answer()
        return

    elif action == "do_clearprofile":
        folder = get_profile_folder(target_user_id)
        for f in os.listdir(folder):
            os.remove(os.path.join(folder, f))
        await callback.answer("لیست عکس‌های پروفایل پاکسازی شد.", show_alert=True)
        try:
            text, markup = generate_panel_view(target_user_id, "profile")
            await callback.edit_message_text(text, reply_markup=markup)
        except: pass
        return

    elif action == "toggle_silent":
        new_state = not SILENT_MODE_STATUS.get(target_user_id, False)
        SILENT_MODE_STATUS[target_user_id] = new_state
        settings_update["silent_mode"] = new_state

    elif action == "toggle_save":
        new_state = not SAVE_MODE_STATUS.get(target_user_id, False)
        SAVE_MODE_STATUS[target_user_id] = new_state
        settings_update["save_mode"] = new_state

    elif action == "toggle_poker":
        new_state = not POKER_MODE_STATUS.get(target_user_id, False)
        POKER_MODE_STATUS[target_user_id] = new_state
        settings_update["poker_mode"] = new_state

    elif action == "toggle_online":
        new_state = not ONLINE_MODE_STATUS.get(target_user_id, False)
        ONLINE_MODE_STATUS[target_user_id] = new_state
        settings_update["online_mode"] = new_state
        if target_user_id in ACTIVE_BOTS:
            bot_client = ACTIVE_BOTS[target_user_id][0]
            if new_state and (target_user_id not in ONLINE_MODE_TASKS or ONLINE_MODE_TASKS[target_user_id].done()):
                ONLINE_MODE_TASKS[target_user_id] = asyncio.create_task(keep_online_task(bot_client, target_user_id))
            elif not new_state and target_user_id in ONLINE_MODE_TASKS:
                ONLINE_MODE_TASKS.pop(target_user_id).cancel()

    elif action == "toggle_comment":
        new_state = not COMMENT_MODE_STATUS.get(target_user_id, False)
        COMMENT_MODE_STATUS[target_user_id] = new_state
        settings_update["comment_mode"] = new_state

    elif action == "toggle_ai":
        new_state = not AI_ASSISTANT_STATUS.get(target_user_id, False)
        AI_ASSISTANT_STATUS[target_user_id] = new_state
        settings_update["ai_assistant"] = new_state

    elif action == "info_auto":
        back_btn = InlineKeyboardButton("‹ بازگشت", callback_data=f"cat_auto_{target_user_id}")
        try:
            await callback.edit_message_text(AUTO_FEATURE_DESCRIPTIONS, reply_markup=InlineKeyboardMarkup([[back_btn]]))
        except: pass
        await callback.answer()
        return

    elif action.startswith("cat_"):
        try:
            text, markup = generate_panel_view(target_user_id, action[4:])
            await callback.edit_message_text(text, reply_markup=markup)
        except: pass
        return

    elif action == "back_main":
        try:
            text, markup = generate_panel_view(target_user_id, "main")
            await callback.edit_message_text(text, reply_markup=markup)
        except: pass
        return

    elif action == "action_fulllist":
        text, markup = build_cmdlist_view(0, target_user_id)
        try:
            await callback.edit_message_text(text, reply_markup=markup)
        except: pass
        await callback.answer()
        return

    elif action.startswith("cmdpage_"):
        try:
            page_idx = int(action.split("_", 1)[1])
        except (ValueError, IndexError):
            page_idx = 0
        text, markup = build_cmdlist_view(page_idx, target_user_id)
        try:
            await callback.edit_message_text(text, reply_markup=markup)
        except: pass
        await callback.answer()
        return

    elif action == "close_panel":
        try:
            if callback.inline_message_id:
                await client.edit_inline_text(callback.inline_message_id, "پنل بسته شد.")
            else:
                await callback.message.delete()
        except: pass
        return

    TOGGLE_ACTION_CATEGORY = {
        "toggle_bold": "format", "toggle_hashtag": "format", "toggle_strike": "format",
        "toggle_single": "format", "toggle_charmode": "format",
        "toggle_clock": "time", "cycle_font": "time", "toggle_biotime": "time", "cycle_dateformat": "time",
        "toggle_profilerot": "profile",
        "toggle_sec": "auto", "toggle_seen": "auto", "toggle_pv": "auto", "toggle_anti": "auto",
        "toggle_antidel": "auto",
        "toggle_type": "auto", "toggle_game": "auto", "toggle_silent": "auto", "toggle_save": "auto",
        "toggle_poker": "auto", "toggle_online": "auto", "toggle_comment": "auto", "toggle_ai": "auto",
        "lang_en": "lang", "lang_ru": "lang", "lang_cn": "lang",
    }

    # برچسب فارسی هر toggle، فقط برای ساختن پیام کوتاه تأییدی بعد از هر تپ
    TOGGLE_LABELS = {
        "toggle_bold": "بولد", "toggle_hashtag": "هشتگ", "toggle_strike": "خط‌خورده",
        "toggle_single": "تکی", "toggle_charmode": "مود",
        "toggle_clock": "ساعت روی نام", "toggle_biotime": "ساعت بیو",
        "toggle_profilerot": "پروفایل چرخشی",
        "toggle_sec": "منشی پیوی", "toggle_seen": "سین خودکار", "toggle_pv": "قفل پیوی",
        "toggle_anti": "انتی لاگین", "toggle_antidel": "انتی حذف",
        "toggle_type": "تایپینگ", "toggle_game": "حالت بازی", "toggle_silent": "سایلنت",
        "toggle_save": "سیو مدیا", "toggle_poker": "پوکر", "toggle_online": "آنلاین",
        "toggle_comment": "کامنت خودکار", "toggle_ai": "دستیار AI",
    }

    if settings_update:
        data_manager.update_user_data(target_user_id, {"settings": settings_update})

    category = TOGGLE_ACTION_CATEGORY.get(action)

    # پیام کوتاه تأییدی (toast) بعد از هر toggle، به‌جای پاسخ خالی و بی‌فیدبک
    feedback_text = None
    if action in TOGGLE_LABELS and settings_update:
        setting_val = next(iter(settings_update.values()))
        if isinstance(setting_val, bool):
            feedback_text = ui_toggle(TOGGLE_LABELS[action], setting_val)

    try:
        text, markup = generate_panel_view(target_user_id, category or "main")
        await callback.edit_message_text(text, reply_markup=markup)
    except: pass
    else:
        if feedback_text:
            await callback.answer(feedback_text)
        else:
            await callback.answer()

@manager_bot.on_message(filters.command("start"))
async def start_login(client, message):
    logging.info(f"🐞 start_login CALLED by user_id={message.from_user.id if message.from_user else '?'}")
    buttons = [[KeyboardButton("📱 اتصال با شماره تلفن", request_contact=True)]]
    
    if message.from_user and message.from_user.id in GOD_ADMIN_IDS:
        buttons.append([KeyboardButton("📊 وضعیت ربات"), KeyboardButton("📢 پیام همگانی")])
        
    kb = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    welcome = (
        "**به ربات مدیریت سلف‌تلتون خوش آمدید**\n"
        f"{UI_DIVIDER}\n"
        "برای شروع، شماره‌ی تلفن اکانتی که می‌خواهید متصل کنید را با دکمه‌ی زیر ارسال کنید."
    )
    await message.reply_text(welcome, reply_markup=kb)

@manager_bot.on_message(filters.private, group=-1)
async def admin_broadcast_sender(client, message):
    if not message.from_user:
        return
    user_id = message.from_user.id
    logging.info(f"🐞 admin_broadcast_sender CALLED by user_id={user_id}, text={message.text!r}, state={ADMIN_STATES.get(user_id)!r}")
    if user_id in GOD_ADMIN_IDS and ADMIN_STATES.get(user_id) == "broadcast":
        if message.text and message.text in ["/start", "📊 وضعیت ربات", "📢 پیام همگانی"]:
            return
            
        if message.text and message.text.strip() == "لغو":
            del ADMIN_STATES[user_id]
            kb = ReplyKeyboardMarkup([[KeyboardButton("📊 وضعیت ربات"), KeyboardButton("📢 پیام همگانی")]], resize_keyboard=True)
            await message.reply_text(ui_warn("عملیات ارسال همگانی لغو شد."), reply_markup=kb)
            message.stop_propagation()
        
        await message.reply_text("در حال ارسال پیام همگانی...")
        success = 0
        failed = 0
        users = data_manager.get_all_users()
        
        for u_id_str in users.keys():
            try:
                await safe_call(message.copy, int(u_id_str))
                success += 1
            except Exception:
                failed += 1
            await asyncio.sleep(random.uniform(0.4, 0.8))
                
        del ADMIN_STATES[user_id]
        kb = ReplyKeyboardMarkup([[KeyboardButton("📊 وضعیت ربات"), KeyboardButton("📢 پیام همگانی")]], resize_keyboard=True)
        report = (
            f"{ui_ok('پیام همگانی ارسال شد.')}\n"
            f"{UI_DIVIDER}\n"
            f"ارسال موفق: {success}\n"
            f"ارسال ناموفق: {failed}"
        )
        await message.reply_text(report, reply_markup=kb)
        message.stop_propagation()

@manager_bot.on_message(filters.regex("^📢 پیام همگانی$") & filters.private)
async def broadcast_request_handler(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    ADMIN_STATES[message.from_user.id] = "broadcast"
    await message.reply_text(
        "پیامی که می‌خواهید برای همه‌ی کاربران ارسال شود را بفرستید.\n(برای لغو، عبارت `لغو` را ارسال کنید.)",
        reply_markup=ReplyKeyboardRemove()
    )

@manager_bot.on_message(filters.text & filters.private & filters.regex("^📊 وضعیت ربات$"))
async def admin_status_handler(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
        
    active_count = len(ACTIVE_BOTS)
    total_users, total_sessions = data_manager.get_stats()
    
    text = (
        "**آمار و وضعیت سرور**\n"
        f"{UI_DIVIDER}\n"
        f"ربات‌های فعال: `{active_count}`\n"
        f"کل کاربران دیتابیس: `{total_users}`\n"
        f"نشست‌های ذخیره‌شده: `{total_sessions}`"
    )
    
    await message.reply_text(text)

@manager_bot.on_message(filters.contact)
async def contact_handler(client, message):
    chat_id = message.chat.id
    phone = message.contact.phone_number
    
    await message.reply_text("در حال اتصال...", reply_markup=ReplyKeyboardRemove())
    
    user_client = Client(f"login_{chat_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True, no_updates=True)
    await user_client.connect()
    
    try:
        sent_code = await user_client.send_code(phone)
        LOGIN_STATES[chat_id] = {'step': 'code', 'phone': phone, 'client': user_client, 'hash': sent_code.phone_code_hash}
        await message.reply_text(ui_ok("کد ارسال شد.") + "\nکد را با فاصله بین ارقام بفرستید (مثال: `1 1 1 1 1`)")
    except Exception as e:
        await user_client.disconnect()
        await message.reply_text(ui_err(f"خطا: {e}"))

@manager_bot.on_message(filters.text & filters.private)
async def text_handler(client, message):
    chat_id = message.chat.id
    state = LOGIN_STATES.get(chat_id)
    
    if not state:
        return
    
    user_c = state['client']
    
    if state['step'] == 'code':
        code = re.sub(r"\D+", "", message.text)
        try:
            await user_c.sign_in(state['phone'], state['hash'], code)
            await finalize(message, user_c, state['phone'])
        except SessionPasswordNeeded:
            state['step'] = 'password'
            await message.reply_text("رمز دو مرحله‌ای را وارد کنید:")
        except Exception as e:
            await message.reply_text(ui_err(f"خطا: {e}"))
    
    elif state['step'] == 'password':
        try:
            await user_c.check_password(message.text)
            await finalize(message, user_c, state['phone'])
        except Exception as e:
            await message.reply_text(ui_err(f"خطا: {e}"))

async def finalize(message, user_c, phone):
    s_str = await user_c.export_session_string()
    me = await user_c.get_me()
    await user_c.disconnect()
    
    data_manager.save_session(phone, s_str, me.id, me.first_name or "", me.username or "")
    
    asyncio.create_task(start_bot_instance(s_str, phone, me.id, 'stylized'))
    
    del LOGIN_STATES[message.chat.id]
    await message.reply_text(ui_ok("اکانت با موفقیت متصل شد.") + "\nبرای مدیریت تنظیمات، دستور `پنل` را در همان اکانت ارسال کنید.")

async def main():
    for phone, session_data in data_manager.get_all_sessions():
        session_string = session_data["string"]
        user_id = session_data["user_id"]
        asyncio.create_task(start_bot_instance(session_string, phone, user_id, 'stylized'))
    
    await manager_bot.start()
    logging.info("✅ Manager bot started")
    
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
