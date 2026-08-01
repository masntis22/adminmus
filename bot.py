#!/usr/bin/env python3
"""
Admin Channel Bot v2
ربات ادمین مدیریت کانال تلگرام

Features / امکانات:
- Send configured messages to channel (image + text + music)
  ارسال پیام کانفیگ شده به کانال (عکس + متن + موزیک)
- Schedule sends: recurring (تبلیغاتی) and one-time (یک بار مصرف)
  زمان‌بندی ارسال: تبلیغاتی و یک بار مصرف
- Schedule management: view, edit, delete, pause/resume
  مدیریت زمان‌بندی: مشاهده، ویرایش، حذف، فعال/غیرفعال
- Multi-task message collection
  جمع‌آوری چند پیامی
- Edit music metadata (title, artist, cover art)
  ویرایش متادیتای موزیک (عنوان، هنرمند، کاور آرت)
- Config management (CRUD for message templates)
  مدیریت تنظیمات (ساخت، ویرایش، حذف پیام‌ها)

Requirements / پیش‌نیازها:
- Python 3.8+ / پایتون 3.8 به بالا
- Telegram Bot Token / توکن ربات تلگرام
- Bot must be admin in channel / ربات باید ادمین کانال باشه

Usage / نحوه استفاده:
    export BOT_TOKEN="your_token"
    export ADMIN_IDS="633606748,5008894513"
    python3 bot.py
"""

import os
import re
import uuid
import asyncio
import logging
import shutil
import tempfile
import json
from pathlib import Path
from datetime import datetime, time, timedelta, timezone

import requests
from mutagen.easyid3 import EasyID3
from mutagen.id3 import APIC, ID3
from mutagen import File as MutagenFile

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

import database as db
from music_tools import MusicTools
from auto_music import AutoMusic
from demo_music import DemoMusic

# ─── Config ───────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

BASE_DIR = Path(__file__).parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# Initialize music tools / مقداردهی ابزار موزیک
music = MusicTools(str(TEMP_DIR))
auto = AutoMusic()
demo = DemoMusic(str(TEMP_DIR))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Job references for scheduled sends / مراجع job برای ارسال‌های زمان‌بندی شده
_scheduled_jobs = {}  # {schedule_id: Job}


# ─── Helpers ──────────────────────────────────────────────────
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_channel():
    return db.get("channel_username"), db.get("channel_id")


def kb(*rows):
    return InlineKeyboardMarkup(list(rows))


def set_state(ctx, state, **data):
    ctx.user_data["state"] = state
    ctx.user_data["d"] = data


def get_state(ctx):
    return ctx.user_data.get("state"), ctx.user_data.get("d", {})


def clear_state(ctx):
    ctx.user_data.pop("state", None)
    ctx.user_data.pop("d", None)


def parse_time(time_str: str) -> float:
    """Parse time string to seconds / تبدیل رشته زمان به ثانیه"""
    time_str = time_str.strip()
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return float(time_str)


# ─── Solar Hijri (Persian) Date Helpers ──────────────────────

# Precompute: cumulative days for each year position within a 33-year cycle
# Each 33-year cycle has 8 leap years (positions 1,5,9,13,17,22,26,30)
_CYCLE_DAYS = [0]  # 0 years = 0 days
for _y in range(1, 34):
    _leap = _y % 33 in (1, 5, 9, 13, 17, 22, 26, 30)
    _CYCLE_DAYS.append(_CYCLE_DAYS[-1] + (366 if _leap else 365))
# _CYCLE_DAYS[33] = total days in one 33-year cycle
_SolarCycleDays = _CYCLE_DAYS[33]

# Precompute epoch: 1 Farvardin 1398 AE = March 21, 2019 CE (Gregorian)
# We need total days from year 1 to year 1397
_EPOCH_TOTAL = _CYCLE_DAYS[33] * (1397 // 33) + _CYCLE_DAYS[1397 % 33]


def _solar_to_gregorian(sy, sm, sd):
    """Convert Solar Hijri date to Gregorian / تبدیل تاریخ شمسی به میلادی"""
    from datetime import date, timedelta

    # Days from Solar epoch to 1 Farvardin of year sy
    cycles = (sy - 1) // 33
    rem = (sy - 1) % 33
    year_days = _SolarCycleDays * cycles + _CYCLE_DAYS[rem]

    # Days from start of year sy to (sm, sd)
    mdays = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
    if sm == 12 and _is_solar_leap(sy):
        mdays[11] = 30
    month_days = sum(mdays[:sm - 1]) if sm > 1 else 0
    day_offset = year_days + month_days + (sd - 1)

    # Reference: 1 Farvardin 1398 AE = March 21, 2019 CE
    ref = date(2019, 3, 21)
    target = ref + timedelta(days=day_offset - _EPOCH_TOTAL)
    return target.year, target.month, target.day


def _is_solar_leap(sy):
    """Check if Solar Hijri year is leap / بررسی سال کبیسه شمسی"""
    return sy % 33 in (1, 5, 9, 13, 17, 22, 26, 30)


def _parse_date(text):
    """Parse date from text, supporting Gregorian and Solar Hijri.
    تحلیل تاریخ از متن، با پشتیبانی از میلادی و شمسی.

    Formats:
      Gregorian: 2026-08-01 or 2026/08/01
      Solar: 1405-05-10 or 1405/05/10
    Returns (year, month, day, is_gregorian) or None
    """
    text = text.strip()

    # Try Gregorian first: YYYY-MM-DD or YYYY/MM/DD
    m = re.match(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$', text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Heuristic: if year > 1700, it's Gregorian
        if y > 1700:
            return (y, mo, d, True)
        # If year 1000-1700, likely Solar Hijri
        return (y, mo, d, False)

    # Try short Solar: 5/10 or 05/10 (current year assumed)
    m = re.match(r'^(\d{1,2})[-/](\d{1,2})$', text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        # Assume current Solar year
        now = datetime.now()
        # Approximate current Solar year
        gyear = now.year
        sy = gyear - 621 if now.month >= 3 else gyear - 622
        return (sy, mo, d, False)

    return None


def _format_persian_date(year, month, day, is_gregorian=True):
    """Format date in Persian / فرمت تاریخ به فارسی"""
    if is_gregorian:
        return f"{year}/{month:02d}/{day:02d} (میلادی)"
    else:
        return f"{year}/{month:02d}/{day:02d} (شمسی)"


def _get_now_persian():
    """Get approximate current Solar Hijri date / دریافت تاریخ شمسی تقریبی"""
    now = datetime.now()
    gyear = now.year
    gmonth = now.month
    # Approximate Solar year
    sy = gyear - 621 if gmonth >= 3 else gyear - 622
    # Approximate Solar month
    sm = (gmonth + 9) % 12 + 1
    return sy, sm


# ─── /start ───────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ دسترسی غیرمجاز!")
        return

    # Check setup
    ch = db.get("channel_username")
    if not ch:
        await update.message.reply_text(
            "👋 **به ربات ادمین کانال خوش آمدید!**\n\n"
            "برای شروع، ابتدا تنظیمات اولیه رو انجام بدید.\n\n"
            "📢 **نام کانال رو بفرستید:**\n"
            "(مثال: `@mychannel` یا آیدی عددی `-1001234567890`)",
            parse_mode=ParseMode.MARKDOWN,
        )
        set_state(ctx, "setup_channel")
        return

    await show_main_menu(update, ctx)


# ─── Setup Wizard ─────────────────────────────────────────────
async def show_main_menu(update, ctx):
    user = update.effective_user
    ch_name, ch_id = get_channel()

    keyboard = [
        [InlineKeyboardButton("📤 ارسال پیام به کانال", callback_data="send_now")],
        [InlineKeyboardButton("⏰ زمان‌بندی ارسال", callback_data="schedule")],
        [InlineKeyboardButton("🎵 ویرایش موزیک", callback_data="edit_music")],
        [InlineKeyboardButton("⚙️ تنظیمات پیام‌ها", callback_data="config")],
        [InlineKeyboardButton("📨 جمع‌آوری و ارسال", callback_data="mcollect")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f"🎵 **پنل مدیریت کانال**\n\n"
        f"📢 کانال: `{ch_name}`\n"
        f"👑 ادمین: {user.first_name}\n\n"
        f"یکی از گزینه‌ها رو انتخاب کنید:"
    )

    if hasattr(update, "message") and update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    elif hasattr(update, "callback_query") and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)


# ─── Callback Router ──────────────────────────────────────────
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    if not is_admin(user.id):
        await query.answer("⛔ دسترسی غیرمجاز!", show_alert=True)
        return

    state, d = get_state(ctx)

    # ── Main menu buttons ──
    if data == "send_now":
        await flow_send_now(update, ctx)
    elif data == "schedule":
        await flow_schedule(update, ctx)
    elif data == "edit_music":
        await flow_edit_music(update, ctx)
    elif data == "config":
        await flow_config(update, ctx)
    elif data == "main_menu":
        await show_main_menu(update, ctx)

    # ── Send now flow ──
    elif data.startswith("snd_tpl_"):
        tpl_id = int(data.split("_")[-1])
        await send_now_preview(update, ctx, tpl_id)
    elif data == "snd_confirm":
        await send_now_confirm(update, ctx)
    elif data == "snd_cancel":
        clear_state(ctx)
        await show_main_menu(update, ctx)

    # ── Schedule flow (legacy template-based) ──
    elif data.startswith("sch_tpl_"):
        tpl_id = int(data.split("_")[-1])
        await schedule_set_times(update, ctx, tpl_id)
    elif data.startswith("sch_add_"):
        time_val = data.split("_", 2)[-1]
        await schedule_add_time(update, ctx, time_val)
    elif data == "sch_save":
        await schedule_save(update, ctx)
    elif data == "sch_cancel":
        clear_state(ctx)
        await show_main_menu(update, ctx)
    elif data.startswith("sch_view_"):
        sch_id = int(data.split("_")[-1])
        await schedule_view(update, ctx, sch_id)
    elif data.startswith("sch_toggle_"):
        sch_id = int(data.split("_")[-1])
        await schedule_toggle(update, ctx, sch_id)
    elif data.startswith("sch_del_"):
        sch_id = int(data.split("_")[-1])
        await schedule_delete(update, ctx, sch_id)

    # ── Schedule NEW: choose type ──
    elif data == "sch_new":
        await schedule_choose_type(update, ctx)
    elif data == "sch_type_recurring":
        await schedule_new_recurring_start(update, ctx)
    elif data == "sch_type_onetime":
        await schedule_new_onetime_start(update, ctx)

    # ── Schedule: edit ──
    elif data.startswith("sch_edit_"):
        sch_id = int(data.split("_")[-1])
        await schedule_edit_menu(update, ctx, sch_id)
    elif data.startswith("sch_edname_"):
        sch_id = int(data.split("_")[-1])
        await schedule_ask_edit_name(update, ctx, sch_id)
    elif data.startswith("sch_edtime_"):
        sch_id = int(data.split("_")[-1])
        await schedule_edit_times(update, ctx, sch_id)
    elif data.startswith("sch_eddate_"):
        sch_id = int(data.split("_")[-1])
        await schedule_ask_edit_dates(update, ctx, sch_id)
    elif data.startswith("sch_edmsg_"):
        sch_id = int(data.split("_")[-1])
        await schedule_ask_edit_message(update, ctx, sch_id)

    # ── Schedule: edit add time ──
    elif data.startswith("sch_eaddtime_"):
        parts = data.split("_")
        time_val = parts[2]  # sch_eaddtime_HH:MM
        await schedule_edit_add_time(update, ctx, time_val)
    elif data.startswith("sch_esave_"):
        sch_id = int(data.split("_")[-1])
        await schedule_edit_save_times(update, ctx, sch_id)

    # ── Multi-collection flow ──
    elif data == "mcollect":
        await mcollect_start(update, ctx)
    elif data == "mcollect_confirm":
        await mcollect_confirm(update, ctx)
    elif data == "mcollect_continue":
        await mcollect_continue(update, ctx)
    elif data == "mcollect_cancel":
        clear_state(ctx)
        db.clear_collected_messages(user.id, f"mc_{user.id}")
        await show_main_menu(update, ctx)

    # ── Music edit flow ──
    elif data.startswith("mt_") or data.startswith("mtm_") or data.startswith("mtc_") or data.startswith("mtf_") or data.startswith("mtv_"):
        await music_tools_callback(update, ctx)
    elif data == "music_done":
        await music_finish(update, ctx)
    elif data == "music_cancel":
        clear_state(ctx)
        await show_main_menu(update, ctx)

    # ── Config flow ──
    elif data == "cfg_list":
        await config_list(update, ctx)
    elif data == "cfg_add":
        await config_add_start(update, ctx)
    elif data.startswith("cfg_edit_"):
        tpl_id = int(data.split("_")[-1])
        await config_edit_menu(update, ctx, tpl_id)
    elif data.startswith("cfg_del_"):
        tpl_id = int(data.split("_")[-1])
        await config_delete(update, ctx, tpl_id)
    elif data.startswith("cfg_chname_"):
        tpl_id = int(data.split("_")[-1])
        await config_ask_name(update, ctx, tpl_id)
    elif data.startswith("cfg_chimg_"):
        tpl_id = int(data.split("_")[-1])
        await config_ask_image(update, ctx, tpl_id)
    elif data.startswith("cfg_chtxt_"):
        tpl_id = int(data.split("_")[-1])
        await config_ask_text(update, ctx, tpl_id)
    elif data.startswith("cfg_chmus_"):
        tpl_id = int(data.split("_")[-1])
        await config_ask_music(update, ctx, tpl_id)
    elif data.startswith("cfg_delimg_"):
        tpl_id = int(data.split("_")[-1])
        await config_delete_image(update, ctx, tpl_id)
    elif data.startswith("cfg_delmus_"):
        tpl_id = int(data.split("_")[-1])
        await config_delete_music(update, ctx, tpl_id)

    # ── Back buttons inside schedule views ──
    elif data == "sch_back_list":
        await flow_schedule(update, ctx)

    else:
        logger.warning(f"Unhandled callback data: {data}")


# ══════════════════════════════════════════════════════════════
# 1) SEND NOW - ارسال پیام کانفیگ شده به کانال
# ══════════════════════════════════════════════════════════════

async def flow_send_now(update, ctx):
    templates = db.get_templates()
    if not templates:
        await update.callback_query.edit_message_text(
            "❌ **هنوز پیامی کانفیگ نشده!**\n\n"
            "ابتدا از بخش «تنظیمات پیام‌ها» یک پیام بسازید.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ تنظیمات پیام‌ها", callback_data="config")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
            ]),
        )
        return

    rows = []
    for t in templates:
        rows.append([InlineKeyboardButton(f"📋 {t['name']}", callback_data=f"snd_tpl_{t['id']}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])

    await update.callback_query.edit_message_text(
        "📤 **ارسال پیام به کانال**\n\nیک پیام رو انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


async def send_now_preview(update, ctx, tpl_id):
    tpl = db.get_template(tpl_id)
    if not tpl:
        await update.callback_query.answer("❌ پیام یافت نشد!", show_alert=True)
        return

    set_state(ctx, "send_preview", tpl_id=tpl_id)
    ch_name, _ = get_channel()

    text_preview = tpl["text_content"][:200] + "..." if len(tpl["text_content"] or "") > 200 else (tpl["text_content"] or "(بدون متن)")

    info = f"📋 **پیش‌نمایش پیام:**\n\n"
    info += f"📝 **متن:**\n{text_preview}\n\n"
    info += f"🖼️ **عکس:** {'✅ دارد' if tpl['image_file_id'] else '❌ ندارد'}\n"
    info += f"🎵 **موزیک:** {'✅ دارد' if tpl['music_file_id'] else '❌ ندارد'}\n\n"
    info += f"📢 **ارسال به:** `{ch_name}`"

    keyboard = [
        [InlineKeyboardButton("✅ ارسال هم‌اکنون", callback_data="snd_confirm")],
        [InlineKeyboardButton("❌ لغو", callback_data="snd_cancel")],
    ]

    await update.callback_query.edit_message_text(
        info,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


async def send_now_confirm(update, ctx):
    state, d = get_state(ctx)
    tpl_id = d.get("tpl_id")
    tpl = db.get_template(tpl_id)
    if not tpl:
        await update.callback_query.answer("❌ پیام یافت نشد!", show_alert=True)
        return

    ch_name, ch_id = get_channel()
    bot = ctx.bot

    try:
        # Send image + text
        if tpl["image_file_id"]:
            if tpl["text_content"]:
                await bot.send_photo(
                    chat_id=ch_id,
                    photo=tpl["image_file_id"],
                    caption=tpl["text_content"],
                    parse_mode=ParseMode.HTML,
                )
            else:
                await bot.send_photo(chat_id=ch_id, photo=tpl["image_file_id"])
        elif tpl["text_content"]:
            await bot.send_message(chat_id=ch_id, text=tpl["text_content"], parse_mode=ParseMode.HTML)

        # Send music if exists
        if tpl["music_file_id"]:
            await bot.send_audio(chat_id=ch_id, audio=tpl["music_file_id"])

        clear_state(ctx)
        await update.callback_query.edit_message_text(
            f"✅ **پیام با موفقیت ارسال شد!**\n\n📢 کانال: `{ch_name}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 ارسال مجدد", callback_data="send_now")],
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
            ]),
        )
    except TelegramError as e:
        logger.error(f"Send error: {e}")
        await update.callback_query.edit_message_text(
            f"❌ **خطا در ارسال:**\n`{str(e)[:200]}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 تلاش مجدد", callback_data=f"snd_tpl_{tpl_id}")],
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
            ]),
        )


# ══════════════════════════════════════════════════════════════
# 2) SCHEDULE - زمان‌بندی ارسال
# ══════════════════════════════════════════════════════════════

async def flow_schedule(update, ctx):
    """BUG FIX: Show templates if none exist, otherwise show schedule list."""
    templates = db.get_templates()

    # BUG FIX: If no templates exist, tell user to create a message first
    if not templates:
        await update.callback_query.edit_message_text(
            "⏰ **زمان‌بندی ارسال**\n\n"
            "❌ **هنوز پیامی تعریف نشده!**\n\n"
            "برای زمان‌بندی ارسال، ابتدا باید یک پیام بسازید.\n"
            "از بخش «تنظیمات پیام‌ها» یک پیام جدید اضافه کنید.\n\n"
            "یا می‌توانید مستقیماً پیام‌های خود رو بفرستید.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ تنظیمات پیام‌ها", callback_data="config")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
            ]),
        )
        return

    scheds = db.get_schedules()

    if scheds:
        rows = []
        for s in scheds:
            tpl = db.get_template(s["template_id"]) if s["template_id"] else None
            # Use schedule name if set, otherwise template name
            display_name = s.get("name") or (tpl["name"] if tpl else s.get("message_text", "")[:20])
            if not display_name:
                display_name = "پیام مستقیم"

            status = "✅" if s["active"] else "⏸️"
            stype = "🔄" if s["schedule_type"] == "recurring" else "📍"

            if s["schedule_type"] == "recurring":
                times_str = ", ".join(s["times"]) if s["times"] else "بدون زمان"
                info = f"{times_str}"
                if s.get("start_date") and s.get("end_date"):
                    info += f" | {s['start_date']} تا {s['end_date']}"
            else:
                info = s.get("send_datetime", "نامشخص")[:16]

            rows.append([InlineKeyboardButton(
                f"{status}{stype} {display_name} ({info})",
                callback_data=f"sch_view_{s['id']}"
            )])
        rows.append([InlineKeyboardButton("➕ زمان‌بندی جدید", callback_data="sch_new")])
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])

        text = "⏰ **زمان‌بندی‌های فعال:**\n\n🔄 تبلیغاتی | 📍 یک بار مصرف\n\nروی یکی کلیک کنید:"
    else:
        rows = [
            [InlineKeyboardButton("➕ زمان‌بندی جدید", callback_data="sch_new")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]
        text = "⏰ **زمان‌بندی ارسال**\n\nهنوز زمان‌بندی‌ای تنظیم نشده.\nیک زمان‌بندی جدید بسازید:"

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Schedule: Choose type ─────────────────────────────────────

async def schedule_choose_type(update, ctx):
    """Choose between recurring and one-time schedule / انتخاب نوع زمان‌بندی"""
    templates = db.get_templates()
    if not templates:
        await update.callback_query.edit_message_text(
            "❌ **هنوز پیامی کانفیگ نشده!**\n\n"
            "ابتدا از بخش «تنظیمات پیام‌ها» یک پیام بسازید.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ تنظیمات پیام‌ها", callback_data="config")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="schedule")],
            ]),
        )
        return

    await update.callback_query.edit_message_text(
        "⏰ **زمان‌بندی جدید**\n\n"
        "نوع زمان‌بندی رو انتخاب کنید:\n\n"
        "🔄 **تبلیغاتی** — ارسال روزانه در بازه زمانی مشخص\n"
        "📍 **یک بار مصرف** — ارسال در یک زمان مشخص",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تبلیغاتی (ارسال روزانه)", callback_data="sch_type_recurring")],
            [InlineKeyboardButton("📍 یک بار مصرف", callback_data="sch_type_onetime")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="schedule")],
        ]),
    )


# ── Schedule: Recurring (تبلیغاتی) ───────────────────────────

async def schedule_new_recurring_start(update, ctx):
    """Start creating a recurring schedule / شروع ساخت زمان‌بندی تبلیغاتی"""
    templates = db.get_templates()
    rows = []
    for t in templates:
        rows.append([InlineKeyboardButton(f"📋 {t['name']}", callback_data=f"sch_tpl_{t['id']}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="sch_new")])

    await update.callback_query.edit_message_text(
        "🔄 **زمان‌بندی تبلیغاتی**\n\n"
        "یک پیام رو انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


async def schedule_set_times(update, ctx, tpl_id):
    tpl = db.get_template(tpl_id)
    if not tpl:
        await update.callback_query.answer("❌ پیام یافت نشد!", show_alert=True)
        return

    set_state(ctx, "sch_set_times", tpl_id=tpl_id, times=[], schedule_type="recurring")

    hours = ["06:00", "07:00", "08:00", "09:00", "10:00", "11:00",
             "12:00", "13:00", "14:00", "15:00", "16:00", "17:00",
             "18:00", "19:00", "20:00", "21:00", "22:00", "23:00"]

    rows = []
    for i in range(0, len(hours), 3):
        row = []
        for h in hours[i:i+3]:
            row.append(InlineKeyboardButton(f"🕐 {h}", callback_data=f"sch_add_{h}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("💾 ذخیره", callback_data="sch_save")])
    rows.append([InlineKeyboardButton("❌ لغو", callback_data="sch_cancel")])

    await update.callback_query.edit_message_text(
        f"🔄 **زمان‌بندی تبلیغاتی: {tpl['name']}**\n\n"
        f"ساعت‌های ارسال رو انتخاب کنید:\n"
        f"(هر روز در این ساعات به کانال ارسال می‌شه)\n\n"
        f"📋 **زمان‌های انتخاب شده:** هنوز هیچ",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


async def schedule_add_time(update, ctx, time_val):
    state, d = get_state(ctx)
    times = d.get("times", [])

    if time_val in times:
        times.remove(time_val)  # Toggle off
    else:
        times.append(time_val)
        times.sort()

    set_state(ctx, "sch_set_times", tpl_id=d["tpl_id"], times=times,
              schedule_type=d.get("schedule_type", "recurring"))

    tpl = db.get_template(d["tpl_id"])
    times_display = ", ".join(times) if times else "هنوز هیچ"

    hours = ["06:00", "07:00", "08:00", "09:00", "10:00", "11:00",
             "12:00", "13:00", "14:00", "15:00", "16:00", "17:00",
             "18:00", "19:00", "20:00", "21:00", "22:00", "23:00"]

    rows = []
    for i in range(0, len(hours), 3):
        row = []
        for h in hours[i:i+3]:
            marker = "✅" if h in times else "🕐"
            row.append(InlineKeyboardButton(f"{marker} {h}", callback_data=f"sch_add_{h}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("💾 ذخیره", callback_data="sch_save")])
    rows.append([InlineKeyboardButton("❌ لغو", callback_data="sch_cancel")])

    await update.callback_query.edit_message_text(
        f"🔄 **زمان‌بندی تبلیغاتی: {tpl['name']}**\n\n"
        f"📋 **زمان‌های انتخاب شده:** `{times_display}`",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


async def schedule_save(update, ctx):
    state, d = get_state(ctx)
    tpl_id = d.get("tpl_id")
    times = d.get("times", [])

    if not times:
        await update.callback_query.answer("❌ حداقل یک ساعت انتخاب کنید!", show_alert=True)
        return

    sch_type = d.get("schedule_type", "recurring")

    if sch_type == "onetime":
        # For one-time: save with send_datetime
        send_dt = d.get("send_datetime")
        if not send_dt:
            await update.callback_query.answer("❌ زمان ارسال تنظیم نشده!", show_alert=True)
            return
        ch_name, ch_id = get_channel()
        tpl = db.get_template(tpl_id)
        sid = db.add_schedule(
            template_id=tpl_id, channel_id=ch_id, times=[],
            schedule_type="onetime", send_datetime=send_dt,
            name=tpl["name"] if tpl else "",
            message_text=tpl["text_content"] if tpl else "",
            image_file_id=tpl["image_file_id"] if tpl else None,
            music_file_id=tpl["music_file_id"] if tpl else None,
        )
        # Schedule the job
        _schedule_job(ctx, sid, d)

        clear_state(ctx)
        await update.callback_query.edit_message_text(
            f"✅ **زمان‌بندی یک بار مصرف ذخیره شد!**\n\n"
            f"📋 پیام: {tpl['name'] if tpl else '?'}\n"
            f"📍 زمان ارسال: `{send_dt}`\n"
            f"📢 کانال: `{ch_name}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏰ زمان‌بندی‌ها", callback_data="schedule")],
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
            ]),
        )
    else:
        # For recurring: save times and optionally date range
        start_date = d.get("start_date")
        end_date = d.get("end_date")
        ch_name, ch_id = get_channel()
        tpl = db.get_template(tpl_id)
        sid = db.add_schedule(
            template_id=tpl_id, channel_id=ch_id, times=times,
            schedule_type="recurring", start_date=start_date, end_date=end_date,
            name=tpl["name"] if tpl else "",
            message_text=tpl["text_content"] if tpl else "",
            image_file_id=tpl["image_file_id"] if tpl else None,
            music_file_id=tpl["music_file_id"] if tpl else None,
        )
        # Schedule the job
        _schedule_job(ctx, sid, d)

        clear_state(ctx)
        date_info = ""
        if start_date and end_date:
            date_info = f"\n📅 بازه: `{start_date}` تا `{end_date}`"

        await update.callback_query.edit_message_text(
            f"✅ **زمان‌بندی ذخیره شد!**\n\n"
            f"📋 پیام: {tpl['name'] if tpl else '?'}\n"
            f"🕐 ساعت‌ها: {', '.join(times)}\n"
            f"📢 کانال: `{ch_name}`"
            f"{date_info}\n\n"
            f"هر روز در این ساعات پیام به کانال ارسال می‌شه.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏰ زمان‌بندی‌ها", callback_data="schedule")],
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
            ]),
        )


# ── Schedule: One-time (یک بار مصرف) ─────────────────────────

async def schedule_new_onetime_start(update, ctx):
    """Start creating a one-time schedule / شروع ساخت زمان‌بندی یک بار مصرف"""
    templates = db.get_templates()
    rows = []
    for t in templates:
        rows.append([InlineKeyboardButton(f"📋 {t['name']}", callback_data=f"sch_tpl_{t['id']}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="sch_new")])

    await update.callback_query.edit_message_text(
        "📍 **زمان‌بندی یک بار مصرف**\n\n"
        "یک پیام رو انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


async def schedule_onetime_set_datetime(update, ctx, tpl_id):
    """Ask for date and time for one-time schedule / دریافت تاریخ و ساعت"""
    tpl = db.get_template(tpl_id)
    if not tpl:
        await update.callback_query.answer("❌ پیام یافت نشد!", show_alert=True)
        return

    sy, sm = _get_now_persian()
    set_state(ctx, "sch_onetime_datetime", tpl_id=tpl_id,
              schedule_type="onetime", times=[])

    await update.callback_query.edit_message_text(
        f"📍 **زمان‌بندی یک بار مصرف: {tpl['name']}**\n\n"
        f"📅 **تاریخ ارسال رو بفرستید:**\n"
        f"فرمت میلادی: `2026-08-05` یا `2026/08/05`\n"
        f"فرمت شمسی: `1405-05-10` یا `1405/05/10`\n\n"
        f"(تاریخ تقریبی فعلی شمسی: `{sy}/{sm}`)",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="sch_cancel")],
        ]),
    )


async def schedule_onetime_set_time(update, ctx):
    """Ask for time after date is set / دریافت ساعت پس از تاریخ"""
    state, d = get_state(ctx)
    date_str = d.get("date_input", "")
    tpl_id = d.get("tpl_id")
    tpl = db.get_template(tpl_id)

    hours = ["06:00", "07:00", "08:00", "09:00", "10:00", "11:00",
             "12:00", "13:00", "14:00", "15:00", "16:00", "17:00",
             "18:00", "19:00", "20:00", "21:00", "22:00", "23:00"]

    rows = []
    for i in range(0, len(hours), 3):
        row = []
        for h in hours[i:i+3]:
            row.append(InlineKeyboardButton(f"🕐 {h}", callback_data=f"sch_add_{h}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("💾 ذخیره", callback_data="sch_save")])
    rows.append([InlineKeyboardButton("❌ لغو", callback_data="sch_cancel")])

    await update.callback_query.edit_message_text(
        f"📍 **زمان‌بندی یک بار مصرف: {tpl['name'] if tpl else '?'}**\n\n"
        f"📅 تاریخ: `{date_str}`\n\n"
        f"🕐 **ساعت ارسال رو انتخاب کنید:**",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Schedule: View ────────────────────────────────────────────

async def schedule_view(update, ctx, sch_id):
    scheds = db.get_schedules()
    sch = next((s for s in scheds if s["id"] == sch_id), None)
    if not sch:
        await update.callback_query.answer("❌ زمان‌بندی یافت نشد!", show_alert=True)
        return

    tpl = db.get_template(sch["template_id"]) if sch["template_id"] else None
    display_name = sch.get("name") or (tpl["name"] if tpl else "پیام مستقیم")
    status = "✅ فعال" if sch["active"] else "⏸️ غیرفعال"

    if sch["schedule_type"] == "recurring":
        type_label = "🔄 تبلیغاتی (ارسال روزانه)"
        times_str = ", ".join(sch["times"]) if sch["times"] else "بدون زمان"
        date_info = ""
        if sch.get("start_date") and sch.get("end_date"):
            date_info = f"\n📅 بازه: `{sch['start_date']}` تا `{sch['end_date']}`"
        else:
            date_info = "\n📅 بازه: همیشه"
        extra = f"🕐 ساعت‌ها: `{times_str}`{date_info}"
    else:
        type_label = "📍 یک بار مصرف"
        extra = f"📍 زمان ارسال: `{sch.get('send_datetime', 'نامشخص')}`"

    msg_preview = (sch.get("message_text") or "")[:100]
    msg_info = f"\n📝 پیام: `{msg_preview}...`" if msg_preview else ""

    if sch.get("last_sent_at"):
        last_sent = sch["last_sent_at"][:16]
        msg_info += f"\n📤 آخرین ارسال: `{last_sent}`"

    keyboard = [
        [InlineKeyboardButton(
            "⏸️ غیرفعال کن" if sch["active"] else "✅ فعال کن",
            callback_data=f"sch_toggle_{sch_id}"
        )],
        [InlineKeyboardButton("✏️ ویرایش", callback_data=f"sch_edit_{sch_id}")],
        [InlineKeyboardButton("🗑️ حذف", callback_data=f"sch_del_{sch_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="schedule")],
    ]

    await update.callback_query.edit_message_text(
        f"⏰ **جزئیات زمان‌بندی**\n\n"
        f"📋 نام: {display_name}\n"
        f"📊 نوع: {type_label}\n"
        f"📊 وضعیت: {status}\n"
        f"{extra}{msg_info}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Schedule: Toggle ──────────────────────────────────────────

async def schedule_toggle(update, ctx, sch_id):
    scheds = db.get_schedules()
    sch = next((s for s in scheds if s["id"] == sch_id), None)
    if not sch:
        return

    new_active = 0 if sch["active"] else 1
    db.update_schedule(sch_id, active=new_active)

    if new_active:
        _schedule_job(ctx, sch_id, sch)
        await update.callback_query.answer("✅ زمان‌بندی فعال شد!", show_alert=True)
    else:
        _remove_job(sch_id)
        await update.callback_query.answer("⏸️ زمان‌بندی غیرفعال شد!", show_alert=True)

    await schedule_view(update, ctx, sch_id)


# ── Schedule: Delete ──────────────────────────────────────────

async def schedule_delete(update, ctx, sch_id):
    _remove_job(sch_id)
    db.delete_schedule(sch_id)
    clear_state(ctx)
    await update.callback_query.edit_message_text(
        "✅ **زمان‌بندی حذف شد!**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏰ زمان‌بندی‌ها", callback_data="schedule")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
        ]),
    )


# ── Schedule: Edit ────────────────────────────────────────────

async def schedule_edit_menu(update, ctx, sch_id):
    """Show edit options for a schedule / نمایش گزینه‌های ویرایش"""
    sch = db.get_schedule(sch_id)
    if not sch:
        await update.callback_query.answer("❌ زمان‌بندی یافت نشد!", show_alert=True)
        return

    display_name = sch.get("name") or "پیام مستقیم"

    keyboard = [
        [InlineKeyboardButton("📛 تغییر نام", callback_data=f"sch_edname_{sch_id}")],
        [InlineKeyboardButton("📝 تغییر پیام", callback_data=f"sch_edmsg_{sch_id}")],
    ]

    if sch["schedule_type"] == "recurring":
        keyboard.append([InlineKeyboardButton("🕐 تغییر ساعت‌ها", callback_data=f"sch_edtime_{sch_id}")])
        keyboard.append([InlineKeyboardButton("📅 تغییر بازه زمانی", callback_data=f"sch_eddate_{sch_id}")])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"sch_view_{sch_id}")])

    await update.callback_query.edit_message_text(
        f"✏️ **ویرایش زمان‌بندی: {display_name}**\n\n"
        f"چه چیزی رو می‌خواید تغییر بدید؟",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def schedule_ask_edit_name(update, ctx, sch_id):
    """Ask for new name / دریافت نام جدید"""
    set_state(ctx, "sch_editing_name", sch_id=sch_id)
    await update.callback_query.edit_message_text(
        "📛 **نام جدید رو بفرستید:**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data=f"sch_edit_{sch_id}")],
        ]),
    )


async def schedule_edit_times(update, ctx, sch_id):
    """Edit times for recurring schedule / ویرایش ساعت‌ها"""
    sch = db.get_schedule(sch_id)
    if not sch:
        return

    set_state(ctx, "sch_editing_times", sch_id=sch_id, times=sch["times"])

    hours = ["06:00", "07:00", "08:00", "09:00", "10:00", "11:00",
             "12:00", "13:00", "14:00", "15:00", "16:00", "17:00",
             "18:00", "19:00", "20:00", "21:00", "22:00", "23:00"]

    rows = []
    for i in range(0, len(hours), 3):
        row = []
        for h in hours[i:i+3]:
            marker = "✅" if h in sch["times"] else "🕐"
            row.append(InlineKeyboardButton(f"{marker} {h}", callback_data=f"sch_eaddtime_{h}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("💾 ذخیره", callback_data=f"sch_esave_{sch_id}")])
    rows.append([InlineKeyboardButton("❌ لغو", callback_data=f"sch_edit_{sch_id}")])

    times_display = ", ".join(sch["times"]) if sch["times"] else "هنوز هیچ"

    await update.callback_query.edit_message_text(
        f"🕐 **ویرایش ساعت‌ها**\n\n"
        f"📋 ساعت‌های فعلی: `{times_display}`\n\n"
        f"ساعات جدید رو انتخاب کنید (روی ساعت‌ها کلیک کنید):",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


async def schedule_edit_add_time(update, ctx, time_val):
    """Toggle time during edit / تغییر وضعیت ساعت در حالت ویرایش"""
    state, d = get_state(ctx)
    times = d.get("times", [])

    if time_val in times:
        times.remove(time_val)
    else:
        times.append(time_val)
        times.sort()

    sch_id = d["sch_id"]
    set_state(ctx, "sch_editing_times", sch_id=sch_id, times=times)

    hours = ["06:00", "07:00", "08:00", "09:00", "10:00", "11:00",
             "12:00", "13:00", "14:00", "15:00", "16:00", "17:00",
             "18:00", "19:00", "20:00", "21:00", "22:00", "23:00"]

    rows = []
    for i in range(0, len(hours), 3):
        row = []
        for h in hours[i:i+3]:
            marker = "✅" if h in times else "🕐"
            row.append(InlineKeyboardButton(f"{marker} {h}", callback_data=f"sch_eaddtime_{h}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("💾 ذخیره", callback_data=f"sch_esave_{sch_id}")])
    rows.append([InlineKeyboardButton("❌ لغو", callback_data=f"sch_edit_{sch_id}")])

    times_display = ", ".join(times) if times else "هنوز هیچ"

    await update.callback_query.edit_message_text(
        f"🕐 **ویرایش ساعت‌ها**\n\n"
        f"📋 ساعت‌های انتخاب شده: `{times_display}`",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


async def schedule_edit_save_times(update, ctx, sch_id):
    """Save edited times / ذخیره ساعت‌های ویرایش شده"""
    state, d = get_state(ctx)
    times = d.get("times", [])

    if not times:
        await update.callback_query.answer("❌ حداقل یک ساعت انتخاب کنید!", show_alert=True)
        return

    db.update_schedule(sch_id, times=times)
    _remove_job(sch_id)
    sch = db.get_schedule(sch_id)
    if sch:
        _schedule_job(ctx, sch_id, sch)

    clear_state(ctx)
    await schedule_view(update, ctx, sch_id)


async def schedule_ask_edit_dates(update, ctx, sch_id):
    """Ask for new date range / دریافت بازه زمانی جدید"""
    set_state(ctx, "sch_editing_dates", sch_id=sch_id)
    sy, sm = _get_now_persian()
    await update.callback_query.edit_message_text(
        "📅 **بازه زمانی جدید رو بفرستید:**\n\n"
        "فرمت: `تاریخ شروع - تاریخ پایان`\n\n"
        "مثال میلادی: `2026-08-01 - 2026-08-15`\n"
        "مثال شمسی: `1405-05-10 - 1405-05-25`\n\n"
        "یا `هیچ` برای ارسال همیشه\n\n"
        f"(تاریخ تقریبی فعلی شمسی: `{sy}/{sm}`)",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data=f"sch_edit_{sch_id}")],
        ]),
    )


async def schedule_ask_edit_message(update, ctx, sch_id):
    """Ask for new message content / دریافت متن پیام جدید"""
    set_state(ctx, "sch_editing_message", sch_id=sch_id)
    await update.callback_query.edit_message_text(
        "📝 **متن پیام جدید رو بفرستید:**\n\n"
        "(یا یک پیام با عکس/موزیک بفرستید)\n\n"
        "💡 از HTML برای فرمت‌بندی استفاده کنید:\n"
        "`<b>بولد</b>` `<i>ایتالیک</i>`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data=f"sch_edit_{sch_id}")],
        ]),
    )


# ── Schedule: JobQueue Integration ────────────────────────────

def _schedule_job(ctx, sch_id, sch_data):
    """Create a scheduled job / ساخت job زمان‌بندی"""
    job_queue = ctx.job_queue
    if not job_queue:
        logger.warning("JobQueue not available")
        return

    _remove_job(sch_id)

    if sch_data.get("schedule_type") == "onetime":
        # One-time: schedule for specific datetime
        send_dt_str = sch_data.get("send_datetime")
        if not send_dt_str:
            return
        try:
            send_dt = datetime.fromisoformat(send_dt_str)
            now = datetime.now()
            if send_dt <= now:
                logger.warning(f"One-time schedule {sch_id} is in the past: {send_dt_str}")
                return
            job = job_queue.run_once(
                _execute_schedule,
                when=send_dt,
                data={"schedule_id": sch_id},
                name=f"sch_{sch_id}",
            )
            _scheduled_jobs[sch_id] = job
            logger.info(f"Scheduled one-time job {sch_id} for {send_dt_str}")
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to schedule one-time job {sch_id}: {e}")
    else:
        # Recurring: schedule daily check
        interval = 60  # Check every minute for matching times
        job = job_queue.run_repeating(
            _check_recurring_schedule,
            interval=interval,
            first=5,
            data={"schedule_id": sch_id},
            name=f"sch_{sch_id}",
        )
        _scheduled_jobs[sch_id] = job
        logger.info(f"Scheduled recurring job {sch_id}")


def _remove_job(sch_id):
    """Remove a scheduled job / حذف job زمان‌بندی"""
    if sch_id in _scheduled_jobs:
        job = _scheduled_jobs.pop(sch_id)
        try:
            job.schedule_removal()
        except Exception:
            pass


async def _execute_schedule(context: ContextTypes.DEFAULT_TYPE):
    """Execute a one-time scheduled send / اجرای ارسال یک بار مصرف"""
    sch_id = context.job.data["schedule_id"]
    sch = db.get_schedule(sch_id)
    if not sch or not sch["active"]:
        return

    await _send_schedule_message(context.bot, sch)
    db.update_schedule(sch_id, active=0, last_sent_at=datetime.now().isoformat())
    _remove_job(sch_id)


async def _check_recurring_schedule(context: ContextTypes.DEFAULT_TYPE):
    """Check if it's time to send a recurring schedule / بررسی زمان ارسال تکراری"""
    sch_id = context.job.data["schedule_id"]
    sch = db.get_schedule(sch_id)
    if not sch or not sch["active"]:
        _remove_job(sch_id)
        return

    now = datetime.now()
    current_time = f"{now.hour:02d}:{now.minute:02d}"

    # Check if current time matches any scheduled time
    if current_time not in sch.get("times", []):
        return

    # Check date range if set
    if sch.get("start_date") and sch.get("end_date"):
        today = now.strftime("%Y-%m-%d")
        if today < sch["start_date"] or today > sch["end_date"]:
            return

    # Check if already sent today
    last_sent = sch.get("last_sent_at", "")
    if last_sent and last_sent[:10] == now.strftime("%Y-%m-%d"):
        return

    await _send_schedule_message(context.bot, sch)
    db.update_schedule(sch_id, last_sent_at=now.isoformat())


async def _send_schedule_message(bot, sch):
    """Send message to channel based on schedule data / ارسال پیام به کانال"""
    ch_id = sch.get("channel_id")
    if not ch_id:
        ch_name, ch_id = get_channel()

    try:
        # Try to get message content from template first
        if sch.get("template_id"):
            tpl = db.get_template(sch["template_id"])
            if tpl:
                if tpl["image_file_id"]:
                    if tpl["text_content"]:
                        await bot.send_photo(
                            chat_id=ch_id,
                            photo=tpl["image_file_id"],
                            caption=tpl["text_content"],
                            parse_mode=ParseMode.HTML,
                        )
                    else:
                        await bot.send_photo(chat_id=ch_id, photo=tpl["image_file_id"])
                elif tpl["text_content"]:
                    await bot.send_message(chat_id=ch_id, text=tpl["text_content"], parse_mode=ParseMode.HTML)
                if tpl["music_file_id"]:
                    await bot.send_audio(chat_id=ch_id, audio=tpl["music_file_id"])
                return

        # Fallback: use direct message content
        if sch.get("image_file_id"):
            if sch.get("message_text"):
                await bot.send_photo(
                    chat_id=ch_id,
                    photo=sch["image_file_id"],
                    caption=sch["message_text"],
                    parse_mode=ParseMode.HTML,
                )
            else:
                await bot.send_photo(chat_id=ch_id, photo=sch["image_file_id"])
        elif sch.get("message_text"):
            await bot.send_message(chat_id=ch_id, text=sch["message_text"], parse_mode=ParseMode.HTML)

        if sch.get("music_file_id"):
            await bot.send_audio(chat_id=ch_id, audio=sch["music_file_id"])

    except TelegramError as e:
        logger.error(f"Scheduled send error (sch {sch.get('id')}): {e}")


async def _start_all_schedules(application):
    """Load and start all active schedules on bot startup / بارگذاری تمام زمان‌بندی‌ها"""
    job_queue = application.job_queue
    if not job_queue:
        logger.warning("JobQueue not available on startup")
        return

    active = db.get_active_schedules()
    count = 0
    for sch in active:
        sch_id = sch["id"]
        if sch["schedule_type"] == "onetime":
            send_dt_str = sch.get("send_datetime")
            if send_dt_str:
                try:
                    send_dt = datetime.fromisoformat(send_dt_str)
                    if send_dt > datetime.now():
                        job = job_queue.run_once(
                            _execute_schedule,
                            when=send_dt,
                            data={"schedule_id": sch_id},
                            name=f"sch_{sch_id}",
                        )
                        _scheduled_jobs[sch_id] = job
                        count += 1
                except (ValueError, TypeError):
                    pass
        else:
            job = job_queue.run_repeating(
                _check_recurring_schedule,
                interval=60,
                first=5,
                data={"schedule_id": sch_id},
                name=f"sch_{sch_id}",
            )
            _scheduled_jobs[sch_id] = job
            count += 1

    logger.info(f"Started {count} scheduled jobs")


# ══════════════════════════════════════════════════════════════
# 3) MULTI-COLLECTION - جمع‌آوری چند پیامی
# ══════════════════════════════════════════════════════════════

async def mcollect_start(update, ctx):
    """Start multi-message collection / شروع جمع‌آوری پیام‌ها"""
    user = update.effective_user
    session_id = f"mc_{user.id}"

    # Clear any previous collection
    db.clear_collected_messages(user.id, session_id)

    set_state(ctx, "mcollect_collecting", session_id=session_id, start_time=datetime.now().isoformat())

    await update.callback_query.edit_message_text(
        "📨 **جمع‌آوری و ارسال پیام**\n\n"
        "پیام‌های خود رو بفرستید (متن، عکس، موزیک).\n\n"
        "⏱️ **بعد از هر پیام، ۵ ثانیه صبر می‌کنم سپس پیام‌ها رو پردازش می‌کنم.**\n\n"
        "وقتی آماده بودید، روی دکمه «تایید» بزنید.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تایید و ارسال", callback_data="mcollect_confirm")],
            [InlineKeyboardButton("➕ ادامه (پیام بیشتر)", callback_data="mcollect_continue")],
            [InlineKeyboardButton("❌ لغو", callback_data="mcollect_cancel")],
        ]),
    )


async def mcollect_continue(update, ctx):
    """Continue collecting / ادامه جمع‌آوری"""
    state, d = get_state(ctx)
    if state != "mcollect_collecting":
        await update.callback_query.answer("❌ وضعیت نامعتبر!", show_alert=True)
        return

    await update.callback_query.answer("✅ منتظر پیام‌های بعدی...", show_alert=False)

    # Update keyboard to show current count
    user = update.effective_user
    session_id = d.get("session_id", f"mc_{user.id}")
    msgs = db.get_collected_messages(user.id, session_id)

    text_counts = sum(1 for m in msgs if m["message_type"] == "text")
    photo_counts = sum(1 for m in msgs if m["message_type"] == "photo")
    audio_counts = sum(1 for m in msgs if m["message_type"] == "audio")

    summary_parts = []
    if text_counts:
        summary_parts.append(f"{text_counts} متن")
    if photo_counts:
        summary_parts.append(f"{photo_counts} عکس")
    if audio_counts:
        summary_parts.append(f"{audio_counts} موزیک")
    summary = ", ".join(summary_parts) if summary_parts else "هنوز پیامی نیست"

    await update.callback_query.edit_message_text(
        f"📨 **جمع‌آوری و ارسال پیام**\n\n"
        f"📊 پیام‌های جمع‌آوری شده: **{summary}**\n\n"
        f"پیام‌های بعدی رو بفرستید.\n"
        f"وقتی آماده بودید، روی «تایید» بزنید.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تایید و ارسال", callback_data="mcollect_confirm")],
            [InlineKeyboardButton("➕ ادامه (پیام بیشتر)", callback_data="mcollect_continue")],
            [InlineKeyboardButton("❌ لغو", callback_data="mcollect_cancel")],
        ]),
    )


async def mcollect_confirm(update, ctx):
    """Confirm and send all collected messages / تایید و ارسال پیام‌ها"""
    state, d = get_state(ctx)
    user = update.effective_user
    session_id = d.get("session_id", f"mc_{user.id}")

    msgs = db.get_collected_messages(user.id, session_id)
    if not msgs:
        await update.callback_query.answer("❌ هیچ پیامی جمع‌آوری نشده!", show_alert=True)
        return

    ch_name, ch_id = get_channel()
    bot = ctx.bot
    sent_count = 0
    errors = []

    await update.callback_query.edit_message_text(
        "📤 در حال ارسال پیام‌ها به کانال...",
        parse_mode=ParseMode.MARKDOWN,
    )

    for msg in msgs:
        try:
            if msg["message_type"] == "text" and msg["text_content"]:
                await bot.send_message(chat_id=ch_id, text=msg["text_content"], parse_mode=ParseMode.HTML)
                sent_count += 1
            elif msg["message_type"] == "photo" and msg["file_id"]:
                await bot.send_photo(chat_id=ch_id, photo=msg["file_id"])
                sent_count += 1
            elif msg["message_type"] == "audio" and msg["file_id"]:
                await bot.send_audio(chat_id=ch_id, audio=msg["file_id"])
                sent_count += 1
        except TelegramError as e:
            errors.append(str(e)[:100])
            logger.error(f"Multi-collect send error: {e}")

    # Cleanup
    db.clear_collected_messages(user.id, session_id)
    clear_state(ctx)

    error_msg = ""
    if errors:
        error_msg = f"\n\n⚠️ خطاها:\n" + "\n".join(errors[:3])

    await update.callback_query.edit_message_text(
        f"✅ **ارسال پیام‌ها انجام شد!**\n\n"
        f"📤 تعداد ارسال شده: **{sent_count}**\n"
        f"📢 کانال: `{ch_name}`"
        f"{error_msg}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📨 جمع‌آوری مجدد", callback_data="mcollect")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
        ]),
    )


# ── Handle collected messages ─────────────────────────────────

async def handle_mcollect_message(update, ctx, message):
    """Handle a message during collection phase / مدیریت پیام در فاز جمع‌آوری"""
    user = update.effective_user
    state, d = get_state(ctx)
    session_id = d.get("session_id", f"mc_{user.id}")

    if message.text:
        db.add_collected_message(user.id, session_id, "text", text_content=message.text)
        await message.reply_text("✅ متن ذخیره شد. پیام بعدی رو بفرستید یا تایید کنید.")
    elif message.photo:
        photo = message.photo[-1]
        db.add_collected_message(user.id, session_id, "photo", file_id=photo.file_id, file_type="photo")
        await message.reply_text("✅ عکس ذخیره شد. پیام بعدی رو بفرستید یا تایید کنید.")
    elif message.audio or (message.document and message.document.mime_type and message.document.mime_type.startswith("audio")):
        audio = message.audio or message.document
        db.add_collected_message(user.id, session_id, "audio", file_id=audio.file_id, file_type="audio")
        await message.reply_text("✅ موزیک ذخیره شد. پیام بعدی رو بفرستید یا تایید کنید.")
    else:
        await message.reply_text("❌ نوع پیام پشتیبانی نمی‌شه. فقط متن، عکس و موزیک.")
        return

    # Show updated count and controls
    msgs = db.get_collected_messages(user.id, session_id)
    text_counts = sum(1 for m in msgs if m["message_type"] == "text")
    photo_counts = sum(1 for m in msgs if m["message_type"] == "photo")
    audio_counts = sum(1 for m in msgs if m["message_type"] == "audio")

    summary_parts = []
    if text_counts:
        summary_parts.append(f"{text_counts} متن")
    if photo_counts:
        summary_parts.append(f"{photo_counts} عکس")
    if audio_counts:
        summary_parts.append(f"{audio_counts} موزیک")
    summary = ", ".join(summary_parts)

    await message.reply_text(
        f"📊 جمع‌آوری شده: **{summary}**\n\n"
        f"پیام بعدی رو بفرستید یا روی دکمه‌ها کلیک کنید:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تایید و ارسال", callback_data="mcollect_confirm")],
            [InlineKeyboardButton("➕ ادامه", callback_data="mcollect_continue")],
            [InlineKeyboardButton("❌ لغو", callback_data="mcollect_cancel")],
        ]),
    )


# ══════════════════════════════════════════════════════════════
# 4) MUSIC EDIT - ویرایش موزیک
# ══════════════════════════════════════════════════════════════

async def flow_edit_music(update, ctx):
    """Show music tools menu / نمایش منوی ابزار موزیک"""
    keyboard = [
        [InlineKeyboardButton("📝 ویرایش متادیتا", callback_data="mt_meta")],
        [InlineKeyboardButton("🖼️ مدیریت کاور", callback_data="mt_cover")],
        [InlineKeyboardButton("🔄 تبدیل فرمت", callback_data="mt_convert")],
        [InlineKeyboardButton("🔊 تنظیم صدا", callback_data="mt_volume")],
        [InlineKeyboardButton("✂️ برش صدا", callback_data="mt_trim")],
        [InlineKeyboardButton("🤖 اتو موزیک", callback_data="mt_auto")],
        [InlineKeyboardButton("🎬 دمو موزیک", callback_data="mt_demo")],
        [InlineKeyboardButton("📋 نمایش اطلاعات", callback_data="mt_info")],
        [InlineKeyboardButton("❌ لغو", callback_data="music_cancel")],
    ]
    await update.callback_query.edit_message_text(
        "🎵 **ابزار ویرایش موزیک**\n\n"
        "یک فایل صوتی بفرستید، سپس ابزار مورد نظر رو انتخاب کنید.\n\n"
        "📌 **قابلیت‌ها:**\n"
        "📝 ویرایش متادیتا (عنوان، هنرمند، آلبوم، سال، ژانر)\n"
        "🖼️ مدیریت کاور آرت\n"
        "🔄 تبدیل فرمت (MP3, M4A, FLAC, WAV)\n"
        "🔊 تنظیم صدا و نرمال‌سازی\n"
        "✂️ برش صدا\n"
        "📋 نمایش کامل اطلاعات",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def music_received(update, ctx, message):
    """Handle received audio file / دریافت فایل صوتی"""
    state, d = get_state(ctx)
    if state != "music_waiting":
        return

    audio_msg = message.audio or message.document
    if not audio_msg:
        await message.reply_text("❌ لطفاً یک فایل صوتی بفرستید.")
        return

    # Download file
    file = await ctx.bot.get_file(audio_msg.file_id)
    ext = os.path.splitext(file.file_path)[1] or ".mp3"
    tmp_path = str(TEMP_DIR / f"{uuid.uuid4().hex}{ext}")
    await file.download_to_drive(tmp_path)

    # Get metadata using music_tools
    meta = music.get_metadata(tmp_path)

    # Save state
    set_state(ctx, "music_editing",
              file_id=audio_msg.file_id,
              file_path=tmp_path,
              title=meta["title"],
              artist=meta["artist"],
              album=meta["album"],
              year=meta["year"],
              genre=meta["genre"],
              has_cover=meta["has_cover"])

    await show_music_edit_menu(update, ctx, f"✅ فایل دریافت شد ({meta['format'].upper()})")


async def show_music_edit_menu(update, ctx, status_msg=""):
    """Show music editing menu / نمایش منوی ویرایش موزیک"""
    state, d = get_state(ctx)
    meta = music.get_metadata(d.get("file_path", ""))

    prefix = f"{status_msg}\n\n" if status_msg else ""

    keyboard = [
        [InlineKeyboardButton("📝 ویرایش متادیتا", callback_data="mt_meta")],
        [InlineKeyboardButton("🖼️ مدیریت کاور", callback_data="mt_cover")],
        [InlineKeyboardButton("🔄 تبدیل فرمت", callback_data="mt_convert")],
        [InlineKeyboardButton("🔊 تنظیم صدا", callback_data="mt_volume")],
        [InlineKeyboardButton("✂️ برش صدا", callback_data="mt_trim")],
        [InlineKeyboardButton("📋 نمایش اطلاعات", callback_data="mt_info")],
        [InlineKeyboardButton("✅ ذخیره و ارسال", callback_data="music_done")],
        [InlineKeyboardButton("❌ لغو", callback_data="music_cancel")],
    ]

    duration_str = music._format_duration(meta["duration"])

    await update.callback_query.edit_message_text(
        f"{prefix}🎵 **ابزار موزیک**\n\n"
        f"📌 عنوان: {meta['title'] or '(خالی)'}\n"
        f"🎤 هنرمند: {meta['artist'] or '(خالی)'}\n"
        f"💿 آلبوم: {meta['album'] or '(خالی)'}\n"
        f"📅 سال: {meta['year'] or '(خالی)'}\n"
        f"🎵 ژانر: {meta['genre'] or '(خالی)'}\n"
        f"🖼️ کاور: {'✅' if meta['has_cover'] else '❌'}\n"
        f"⏱️ مدت: {duration_str}\n"
        f"📁 فرمت: {meta['format'].upper()}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ─── Music Tools Callbacks ────────────────────────────────────

async def music_tools_callback(update, ctx):
    """Handle music tools callbacks / مدیریت کالبک‌های ابزار موزیک"""
    query = update.callback_query
    await query.answer()
    data = query.data
    state, d = get_state(ctx)

    file_path = d.get("file_path")
    if not file_path or not os.path.exists(file_path):
        await query.edit_message_text("❌ فایل یافت نشد. دوباره موزیک بفرستید.")
        clear_state(ctx)
        return

    # ── Metadata editing ──
    if data == "mt_meta":
        keyboard = [
            [InlineKeyboardButton("✏️ عنوان", callback_data="mtm_title"),
             InlineKeyboardButton("🎤 هنرمند", callback_data="mtm_artist")],
            [InlineKeyboardButton("💿 آلبوم", callback_data="mtm_album"),
             InlineKeyboardButton("📅 سال", callback_data="mtm_year")],
            [InlineKeyboardButton("🎵 ژانر", callback_data="mtm_genre")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="mt_back")],
        ]
        await query.edit_message_text(
            "📝 **ویرایش متادیتا**\n\nکدوم فیلد رو می‌خواید تغییر بدید؟",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("mtm_"):
        field = data.replace("mtm_", "")
        field_names = {
            "title": "عنوان", "artist": "هنرمند", "album": "آلبوم",
            "year": "سال", "genre": "ژانر",
        }
        set_state(ctx, f"music_changing_{field}", **d)
        await query.edit_message_text(
            f"✏️ **{field_names.get(field, field)} جدید رو بفرستید:**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="mt_back")],
            ]),
        )

    # ── Cover art ──
    elif data == "mt_cover":
        keyboard = [
            [InlineKeyboardButton("🔄 تغییر کاور", callback_data="mtc_change")],
            [InlineKeyboardButton("🗑️ حذف کاور", callback_data="mtc_remove")],
            [InlineKeyboardButton("📥 استخراج کاور", callback_data="mtc_extract")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="mt_back")],
        ]
        has_cover = d.get("has_cover", False)
        await query.edit_message_text(
            f"🖼️ **مدیریت کاور**\n\n"
            f"وضعیت فعلی: {'✅ کاور دارد' if has_cover else '❌ بدون کاور'}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data == "mtc_change":
        set_state(ctx, "music_waiting_cover", **d)
        await query.edit_message_text(
            "🖼️ **عکس کاور جدید رو بفرستید:**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="mt_back")],
            ]),
        )

    elif data == "mtc_remove":
        if music.remove_cover(file_path):
            ctx.user_data["d"]["has_cover"] = False
            await show_music_edit_menu(update, ctx, "✅ کاور حذف شد")
        else:
            await query.answer("❌ خطا در حذف کاور!", show_alert=True)

    elif data == "mtc_extract":
        cover_path = str(TEMP_DIR / f"cover_{uuid.uuid4().hex}.jpg")
        if music.save_cover_to_file(file_path, cover_path):
            with open(cover_path, "rb") as f:
                await query.message.reply_photo(
                    photo=f, caption="🖼️ کاور استخراج شده"
                )
            music.cleanup(cover_path)
        else:
            await query.answer("❌ کاوری برای استخراج وجود ندارد!", show_alert=True)

    # ── Format conversion ──
    elif data == "mt_convert":
        keyboard = [
            [InlineKeyboardButton("MP3 128kbps", callback_data="mtf_mp3_128"),
             InlineKeyboardButton("MP3 320kbps", callback_data="mtf_mp3_320")],
            [InlineKeyboardButton("M4A", callback_data="mtf_m4a_256"),
             InlineKeyboardButton("FLAC", callback_data="mtf_flac_0")],
            [InlineKeyboardButton("WAV", callback_data="mtf_wav_0")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="mt_back")],
        ]
        await query.edit_message_text(
            "🔄 **تبدیل فرمت**\n\nفرمت خروجی رو انتخاب کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("mtf_"):
        parts = data.replace("mtf_", "").split("_")
        fmt = parts[0]
        bitrate = parts[1] if len(parts) > 1 else "320"

        await query.edit_message_text(f"🔄 در حال تبدیل به {fmt.upper()}...")

        output = music.convert_format(file_path, fmt, bitrate)
        if output:
            ctx.user_data["d"]["file_path"] = output
            ctx.user_data["d"]["converted_format"] = fmt
            await show_music_edit_menu(update, ctx, f"✅ تبدیل به {fmt.upper()} انجام شد")
        else:
            await show_music_edit_menu(update, ctx, "❌ خطا در تبدیل فرمت")

    # ── Volume ──
    elif data == "mt_volume":
        keyboard = [
            [InlineKeyboardButton("🔊 +3dB", callback_data="mtv_3"),
             InlineKeyboardButton("🔊 +6dB", callback_data="mtv_6")],
            [InlineKeyboardButton("🔉 -3dB", callback_data="mtv_-3"),
             InlineKeyboardButton("🔉 -6dB", callback_data="mtv_-6")],
            [InlineKeyboardButton("📏 نرمال‌سازی", callback_data="mtv_norm")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="mt_back")],
        ]
        await query.edit_message_text(
            "🔊 **تنظیم صدا**\n\nعملیات مورد نظر رو انتخاب کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("mtv_"):
        action = data.replace("mtv_", "")

        await query.edit_message_text("🔊 در حال پردازش...")

        if action == "norm":
            output = music.normalize_volume(file_path)
        else:
            db_val = float(action)
            output = music.change_volume(file_path, db_val)

        if output:
            ctx.user_data["d"]["file_path"] = output
            await show_music_edit_menu(update, ctx, "✅ تنظیم صدا انجام شد")
        else:
            await show_music_edit_menu(update, ctx, "❌ خطا در تنظیم صدا")

    # ── Trim ──
    elif data == "mt_trim":
        set_state(ctx, "music_trim_start", **d)
        await query.edit_message_text(
            "✂️ **برش صدا**\n\n"
            "زمان شروع رو بفرستید (ثانیه):\n"
            "مثال: `10` یا `1:30`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="mt_back")],
            ]),
        )

    # ── Info ──
    elif data == "mt_info":
        info_text = music.get_metadata_text(file_path)
        await query.edit_message_text(
            info_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="mt_back")],
            ]),
        )

    # ── Auto Music (Mood & Hashtags) ──
    elif data == "mt_auto":
        await query.edit_message_text("🤖 در حال تحلیل مود موزیک...")
        try:
            result = auto.format_hashtags_text(file_path)
            await query.edit_message_text(
                result,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 تحلیل مجدد", callback_data="mt_auto")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="mt_back")],
                ]),
            )
        except Exception as e:
            logger.error(f"Auto music error: {e}")
            await show_music_edit_menu(update, ctx, "❌ خطا در تحلیل مود")

    # ── Demo Music ──
    elif data == "mt_demo":
        set_state(ctx, "demo_waiting_start", **d)
        await query.edit_message_text(
            "🎬 **ساخت دموی موزیک**\n\n"
            "زمان شروع رو بفرستید (ثانیه):\n"
            "مثال: `10` یا `1:30`\n\n"
            "⏱️ **اطلاعات موزیک:**\n"
            f"مدت کل: {music._format_duration(music.get_metadata(file_path)['duration'])}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="mt_back")],
            ]),
        )

    # ── Back to main music menu ──
    elif data == "mt_back":
        await show_music_edit_menu(update, ctx)


async def music_ask_title(update, ctx):
    state, d = get_state(ctx)
    set_state(ctx, "music_changing_title", **d)
    await update.callback_query.edit_message_text(
        "✏️ **عنوان جدید رو بفرستید:**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="mt_back")],
        ]),
    )


async def music_ask_artist(update, ctx):
    state, d = get_state(ctx)
    set_state(ctx, "music_changing_artist", **d)
    await update.callback_query.edit_message_text(
        "🎤 **نام هنرمند جدید رو بفرستید:**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="mt_back")],
        ]),
    )


async def music_ask_cover(update, ctx):
    state, d = get_state(ctx)
    set_state(ctx, "music_waiting_cover", **d)
    await update.callback_query.edit_message_text(
        "🖼️ **عکس کاور جدید رو بفرستید:**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="mt_back")],
        ]),
    )


async def music_apply_changes(update, ctx):
    """Apply all metadata changes / اعمال تمام تغییرات متادیتا"""
    state, d = get_state(ctx)
    file_path = d.get("file_path")
    if not file_path or not os.path.exists(file_path):
        return

    # Apply metadata
    music.set_metadata(
        file_path,
        title=d.get("title"),
        artist=d.get("artist"),
        album=d.get("album"),
        year=d.get("year"),
        genre=d.get("genre"),
    )

    # Apply cover art
    cover_path = d.get("cover_path")
    if cover_path and os.path.exists(cover_path):
        music.set_cover(file_path, cover_path)


async def music_finish(update, ctx):
    """Finish editing and send / پایان ویرایش و ارسال"""
    state, d = get_state(ctx)
    file_path = d.get("file_path")

    if not file_path or not os.path.exists(file_path):
        await update.callback_query.edit_message_text("❌ فایل یافت نشد.")
        clear_state(ctx)
        return

    # Apply changes
    await music_apply_changes(update, ctx)

    # Send back to admin
    try:
        meta = music.get_metadata(file_path)
        title = meta["title"] or "Unknown"
        artist = meta["artist"] or "Unknown"

        with open(file_path, "rb") as f:
            await update.callback_query.message.reply_audio(
                audio=f,
                title=title,
                performer=artist,
            )

        clear_state(ctx)
        await update.callback_query.edit_message_text(
            f"✅ **موزیک با موفقیت ویرایش شد!**\n\n"
            f"📌 عنوان: {title}\n"
            f"🎤 هنرمند: {artist}\n"
            f"📁 فرمت: {meta['format'].upper()}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎵 ویرایش مجدد", callback_data="edit_music")],
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
            ]),
        )
    except TelegramError as e:
        logger.error(f"Send music error: {e}")
        await update.callback_query.edit_message_text(
            f"❌ **خطا در ارسال:** `{str(e)[:200]}`",
            parse_mode=ParseMode.MARKDOWN,
        )

    # Cleanup
    music.cleanup(file_path, d.get("cover_path"))


# ══════════════════════════════════════════════════════════════
# 5) CONFIG - تنظیمات پیام‌ها
# ══════════════════════════════════════════════════════════════

async def flow_config(update, ctx):
    templates = db.get_templates()

    if templates:
        rows = []
        for t in templates:
            img = "🖼️" if t["image_file_id"] else "⬜"
            txt = "📝" if t["text_content"] else "⬜"
            mus = "🎵" if t["music_file_id"] else "⬜"
            rows.append([InlineKeyboardButton(
                f"{t['name']}  {img}{txt}{mus}",
                callback_data=f"cfg_edit_{t['id']}"
            )])
        rows.append([InlineKeyboardButton("➕ پیام جدید", callback_data="cfg_add")])
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])

        text = "⚙️ **تنظیمات پیام‌ها**\n\nروی یک پیام کلیک کنید:\n(🖼️=عکس 📝=متن 🎵=موزیک)"
    else:
        rows = [
            [InlineKeyboardButton("➕ پیام جدید", callback_data="cfg_add")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]
        text = "⚙️ **تنظیمات پیام‌ها**\n\nهنوز پیامی وجود نداره. یک پیام جدید بسازید:"

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


async def config_list(update, ctx):
    await flow_config(update, ctx)


async def config_add_start(update, ctx):
    set_state(ctx, "cfg_add_name")
    await update.callback_query.edit_message_text(
        "➕ **پیام جدید**\n\n"
        "📝 **نام پیام رو بفرستید:**\n"
        "(مثال: انتشار جدید، میکس روزانه)",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="config")],
        ]),
    )


async def config_add_name_received(update, ctx, text):
    state, d = get_state(ctx)
    if state != "cfg_add_name":
        return

    name = text.strip()
    if not name:
        await update.message.reply_text("❌ نام نمی‌تونه خالی باشه.")
        return

    tpl_id = db.add_template(name=name)
    set_state(ctx, "cfg_add_image", tpl_id=tpl_id, name=name)

    await update.message.reply_text(
        f"✅ نام پیام: **{name}**\n\n"
        f"🖼️ **عکس پیام رو بفرستید:**\n"
        f"(یا /skip برای رد کردن)",
        parse_mode=ParseMode.MARKDOWN,
    )


async def config_add_image_received(update, ctx, message):
    state, d = get_state(ctx)
    if state != "cfg_add_image":
        return

    photo = message.photo[-1] if message.photo else None
    if photo:
        db.update_template(d["tpl_id"], image_file_id=photo.file_id)
        img_status = "✅ عکس ذخیره شد"
    else:
        img_status = "⬜ بدون عکس"

    set_state(ctx, "cfg_add_text", tpl_id=d["tpl_id"], name=d["name"])

    await message.reply_text(
        f"{img_status}\n\n"
        f"📝 **متن پیام رو بفرستید:**\n"
        f"(یا /skip برای رد کردن)\n\n"
        f"💡 از HTML برای فرمت‌بندی استفاده کنید:\n"
        f"`<b>بولد</b>` `<i>ایتالیک</i>` `<a href='url'>لینک</a>`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def config_add_text_received(update, ctx, text):
    state, d = get_state(ctx)
    if state != "cfg_add_text":
        return

    if text != "/skip":
        db.update_template(d["tpl_id"], text_content=text)

    set_state(ctx, "cfg_add_music", tpl_id=d["tpl_id"], name=d["name"])

    await update.message.reply_text(
        "📝 متن ذخیره شد.\n\n"
        "🎵 **فایل موزیک بفرستید:**\n"
        "(یا /skip برای رد کردن)",
        parse_mode=ParseMode.MARKDOWN,
    )


async def config_add_music_received(update, ctx, message):
    state, d = get_state(ctx)
    if state != "cfg_add_music":
        return

    audio = message.audio or message.document
    if audio:
        db.update_template(d["tpl_id"], music_file_id=audio.file_id)
        mus_status = "✅ موزیک ذخیره شد"
    else:
        mus_status = "⬜ بدون موزیک"

    clear_state(ctx)
    tpl = db.get_template(d["tpl_id"])

    await message.reply_text(
        f"✅ **پیام جدید ساخته شد!**\n\n"
        f"📋 نام: {tpl['name']}\n"
        f"🖼️ عکس: {'✅' if tpl['image_file_id'] else '❌'}\n"
        f"📝 متن: {'✅' if tpl['text_content'] else '❌'}\n"
        f"🎵 موزیک: {'✅' if tpl['music_file_id'] else '❌'}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ تنظیمات", callback_data="config")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
        ]),
    )


async def config_edit_menu(update, ctx, tpl_id):
    tpl = db.get_template(tpl_id)
    if not tpl:
        await update.callback_query.answer("❌ پیام یافت نشد!", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(f"📛 تغییر نام: {tpl['name']}", callback_data=f"cfg_chname_{tpl_id}")],
        [InlineKeyboardButton(
            "🖼️ تغییر عکس" if tpl["image_file_id"] else "🖼️ اضافه عکس",
            callback_data=f"cfg_chimg_{tpl_id}"
        )],
        [InlineKeyboardButton(
            "🗑️ حذف عکس" if tpl["image_file_id"] else "⬜ بدون عکس",
            callback_data=f"cfg_delimg_{tpl_id}"
        )],
        [InlineKeyboardButton(
            "📝 تغییر متن" if tpl["text_content"] else "📝 اضافه متن",
            callback_data=f"cfg_chtxt_{tpl_id}"
        )],
        [InlineKeyboardButton(
            "🎵 تغییر موزیک" if tpl["music_file_id"] else "🎵 اضافه موزیک",
            callback_data=f"cfg_chmus_{tpl_id}"
        )],
        [InlineKeyboardButton(
            "🗑️ حذف موزیک" if tpl["music_file_id"] else "⬜ بدون موزیک",
            callback_data=f"cfg_delmus_{tpl_id}"
        )],
        [InlineKeyboardButton("🗑️ حذف پیام", callback_data=f"cfg_del_{tpl_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="config")],
    ]

    text = (
        f"⚙️ **ویرایش پیام: {tpl['name']}**\n\n"
        f"🖼️ **عکس:** {'✅' if tpl['image_file_id'] else '❌'}\n"
        f"📝 **متن:** {(tpl['text_content'] or '(خالی)')[:100]}\n"
        f"🎵 **موزیک:** {'✅' if tpl['music_file_id'] else '❌'}"
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


async def config_delete(update, ctx, tpl_id):
    tpl = db.get_template(tpl_id)
    db.delete_template(tpl_id)
    clear_state(ctx)
    await update.callback_query.edit_message_text(
        f"✅ **پیام «{tpl['name'] if tpl else '?'}» حذف شد!**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ تنظیمات", callback_data="config")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
        ]),
    )


async def config_ask_name(update, ctx, tpl_id):
    set_state(ctx, "cfg_changing_name", tpl_id=tpl_id)
    await update.callback_query.edit_message_text(
        "📛 **نام جدید رو بفرستید:**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data=f"cfg_edit_{tpl_id}")],
        ]),
    )


async def config_ask_image(update, ctx, tpl_id):
    set_state(ctx, "cfg_changing_image", tpl_id=tpl_id)
    await update.callback_query.edit_message_text(
        "🖼️ **عکس جدید رو بفرستید:**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data=f"cfg_edit_{tpl_id}")],
        ]),
    )


async def config_ask_text(update, ctx, tpl_id):
    set_state(ctx, "cfg_changing_text", tpl_id=tpl_id)
    tpl = db.get_template(tpl_id)
    current = (tpl["text_content"] or "(خالی)")[:200]
    await update.callback_query.edit_message_text(
        f"📝 **متن جدید رو بفرستید:**\n\n"
        f"📝 متن فعلی:\n`{current}`\n\n"
        f"💡 از HTML برای فرمت‌بندی استفاده کنید.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data=f"cfg_edit_{tpl_id}")],
        ]),
    )


async def config_ask_music(update, ctx, tpl_id):
    set_state(ctx, "cfg_changing_music", tpl_id=tpl_id)
    await update.callback_query.edit_message_text(
        "🎵 **موزیک جدید رو بفرستید:**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data=f"cfg_edit_{tpl_id}")],
        ]),
    )


async def config_delete_image(update, ctx, tpl_id):
    db.update_template(tpl_id, image_file_id=None)
    await config_edit_menu(update, ctx, tpl_id)


async def config_delete_music(update, ctx, tpl_id):
    db.update_template(tpl_id, music_file_id=None)
    await config_edit_menu(update, ctx, tpl_id)


# ══════════════════════════════════════════════════════════════
# Message Router
# ══════════════════════════════════════════════════════════════

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return

    state, d = get_state(ctx)
    text = update.message.text

    # ── Setup states ──
    if state == "setup_channel":
        channel = text.strip()
        db.put("channel_username", channel)
        if channel.startswith("-"):
            db.put("channel_id", channel)
        else:
            db.put("channel_id", channel)

        set_state(ctx, "setup_admin_ids")
        await update.message.reply_text(
            f"✅ کانال `{channel}` ذخیره شد.\n\n"
            f"👑 **آیدی عددی ادمین‌ها رو بفرستید:**\n"
            f"(با کاما جدا کنید، مثال: `123456789,987654321`)",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if state == "setup_admin_ids":
        ids = [int(x.strip()) for x in text.split(",") if x.strip().isdigit()]
        if user.id not in ids:
            ids.append(user.id)
        db.put("admin_ids", ",".join(str(i) for i in ids))

        clear_state(ctx)
        await update.message.reply_text(
            f"✅ **تنظیمات اولیه کامل شد!**\n\n"
            f"👑 ادمین‌ها: {', '.join(str(i) for i in ids)}\n\n"
            f"از /start استفاده کنید.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── Config states ──
    if state == "cfg_add_name":
        await config_add_name_received(update, ctx, text)
        return

    if state == "cfg_add_text":
        await config_add_text_received(update, ctx, text)
        return

    if state == "cfg_changing_name":
        tpl_id = d["tpl_id"]
        db.update_template(tpl_id, name=text.strip())
        clear_state(ctx)
        await update.message.reply_text(
            f"✅ نام تغییر کرد: **{text.strip()}**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ بازگشت", callback_data=f"cfg_edit_{tpl_id}")],
            ]),
        )
        return

    if state == "cfg_changing_text":
        tpl_id = d["tpl_id"]
        db.update_template(tpl_id, text_content=text)
        clear_state(ctx)
        await update.message.reply_text(
            "✅ متن ذخیره شد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ بازگشت", callback_data=f"cfg_edit_{tpl_id}")],
            ]),
        )
        return

    # ── Schedule editing states ──
    if state == "sch_editing_name":
        sch_id = d["sch_id"]
        db.update_schedule(sch_id, name=text.strip())
        clear_state(ctx)
        await update.message.reply_text(
            f"✅ نام تغییر کرد: **{text.strip()}**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ بازگشت", callback_data=f"sch_edit_{sch_id}")],
            ]),
        )
        return

    if state == "sch_editing_dates":
        sch_id = d["sch_id"]
        text_clean = text.strip()

        if text_clean == "هیچ":
            db.update_schedule(sch_id, start_date=None, end_date=None)
            clear_state(ctx)
            await update.message.reply_text(
                "✅ بازه زمانی حذف شد (ارسال همیشه).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⚙️ بازگشت", callback_data=f"sch_edit_{sch_id}")],
                ]),
            )
            return

        # Parse "date1 - date2"
        parts = re.split(r'\s*[-–]\s*', text_clean)
        if len(parts) != 2:
            await update.message.reply_text(
                "❌ فرمت نامعتبر!\nمثال: `2026-08-01 - 2026-08-15`"
            )
            return

        start_parsed = _parse_date(parts[0].strip())
        end_parsed = _parse_date(parts[1].strip())

        if not start_parsed or not end_parsed:
            await update.message.reply_text(
                "❌ تاریخ نامعتبر!\n"
                "فرمت میلادی: `2026-08-01`\n"
                "فرمت شمسی: `1405-05-10`"
            )
            return

        # Convert Solar to Gregorian if needed
        if not start_parsed[3]:  # Solar
            sy, sm, sd = start_parsed[0], start_parsed[1], start_parsed[2]
            gy, gm, gd = _solar_to_gregorian(sy, sm, sd)
            start_date = f"{gy:04d}-{gm:02d}-{gd:02d}"
        else:
            start_date = f"{start_parsed[0]:04d}-{start_parsed[1]:02d}-{start_parsed[2]:02d}"

        if not end_parsed[3]:  # Solar
            sy, sm, sd = end_parsed[0], end_parsed[1], end_parsed[2]
            gy, gm, gd = _solar_to_gregorian(sy, sm, sd)
            end_date = f"{gy:04d}-{gm:02d}-{gd:02d}"
        else:
            end_date = f"{end_parsed[0]:04d}-{end_parsed[1]:02d}-{end_parsed[2]:02d}"

        db.update_schedule(sch_id, start_date=start_date, end_date=end_date)

        # Restart the job with new dates
        _remove_job(sch_id)
        sch = db.get_schedule(sch_id)
        if sch:
            _schedule_job(ctx, sch_id, sch)

        clear_state(ctx)
        await update.message.reply_text(
            f"✅ بازه زمانی ذخیره شد:\n"
            f"📅 `{start_date}` تا `{end_date}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ بازگشت", callback_data=f"sch_edit_{sch_id}")],
            ]),
        )
        return

    if state == "sch_editing_message":
        sch_id = d["sch_id"]
        sch = db.get_schedule(sch_id)
        if not sch:
            clear_state(ctx)
            return

        # Check if there's a photo
        update_data = {"message_text": text}
        if update.message.photo:
            photo = update.message.photo[-1]
            update_data["image_file_id"] = photo.file_id

        db.update_schedule(sch_id, **update_data)
        clear_state(ctx)
        await update.message.reply_text(
            "✅ پیام زمان‌بندی به‌روزرسانی شد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ بازگشت", callback_data=f"sch_edit_{sch_id}")],
            ]),
        )
        return

    # ── Schedule: one-time datetime ──
    if state == "sch_onetime_datetime":
        date_parsed = _parse_date(text.strip())
        if not date_parsed:
            await update.message.reply_text(
                "❌ تاریخ نامعتبر!\n"
                "فرمت میلادی: `2026-08-05`\n"
                "فرمت شمسی: `1405-05-10`"
            )
            return

        # Convert to Gregorian if Solar
        if not date_parsed[3]:  # Solar
            sy, sm, sd = date_parsed[0], date_parsed[1], date_parsed[2]
            gy, gm, gd = _solar_to_gregorian(sy, sm, sd)
            date_str = f"{gy:04d}-{gm:02d}-{gd:02d}"
            date_display = _format_persian_date(sy, sm, sd, False)
        else:
            date_str = f"{date_parsed[0]:04d}-{date_parsed[1]:02d}-{date_parsed[2]:02d}"
            date_display = _format_persian_date(date_parsed[0], date_parsed[1], date_parsed[2], True)

        set_state(ctx, "sch_onetime_time", tpl_id=d["tpl_id"],
                  schedule_type="onetime", date_input=date_str,
                  date_display=date_display, times=[])

        # Show time picker
        hours = ["06:00", "07:00", "08:00", "09:00", "10:00", "11:00",
                 "12:00", "13:00", "14:00", "15:00", "16:00", "17:00",
                 "18:00", "19:00", "20:00", "21:00", "22:00", "23:00"]

        rows = []
        for i in range(0, len(hours), 3):
            row = []
            for h in hours[i:i+3]:
                row.append(InlineKeyboardButton(f"🕐 {h}", callback_data=f"sch_add_{h}"))
            rows.append(row)
        rows.append([InlineKeyboardButton("💾 ذخیره", callback_data="sch_save")])
        rows.append([InlineKeyboardButton("❌ لغو", callback_data="sch_cancel")])

        tpl = db.get_template(d["tpl_id"])
        await update.message.reply_text(
            f"📍 **زمان‌بندی یک بار مصرف: {tpl['name'] if tpl else '?'}**\n\n"
            f"📅 تاریخ: `{date_display}`\n\n"
            f"🕐 **ساعت ارسال رو انتخاب کنید:**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if state == "sch_onetime_time":
        # Handle time selection through buttons, not text
        # But if user sends time as text, parse it
        try:
            time_val = text.strip()
            if ":" in time_val:
                parts = time_val.split(":")
                if len(parts) == 2:
                    h, m = int(parts[0]), int(parts[1])
                    if 0 <= h <= 23 and 0 <= m <= 59:
                        time_str = f"{h:02d}:{m:02d}"
                        # Build send_datetime
                        date_str = d.get("date_input", "")
                        send_dt = f"{date_str}T{time_str}:00"

                        tpl_id = d.get("tpl_id")
                        ch_name, ch_id = get_channel()
                        tpl = db.get_template(tpl_id)

                        sid = db.add_schedule(
                            template_id=tpl_id, channel_id=ch_id, times=[],
                            schedule_type="onetime", send_datetime=send_dt,
                            name=tpl["name"] if tpl else "",
                            message_text=tpl["text_content"] if tpl else "",
                            image_file_id=tpl["image_file_id"] if tpl else None,
                            music_file_id=tpl["music_file_id"] if tpl else None,
                        )
                        _schedule_job(ctx, sid, {"id": sid, "schedule_type": "onetime", "send_datetime": send_dt, "active": 1})
                        clear_state(ctx)

                        await update.message.reply_text(
                            f"✅ **زمان‌بندی یک بار مصرف ذخیره شد!**\n\n"
                            f"📋 پیام: {tpl['name'] if tpl else '?'}\n"
                            f"📍 زمان ارسال: `{send_dt}`\n"
                            f"📢 کانال: `{ch_name}`",
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("⏰ زمان‌بندی‌ها", callback_data="schedule")],
                                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
                            ]),
                        )
                        return
        except (ValueError, IndexError):
            pass
        await update.message.reply_text("❌ فرمت نامعتبر! از دکمه‌های ساعت استفاده کنید یا `HH:MM` بفرستید.")
        return

    # ── Music edit states ──
    if state == "music_changing_title":
        ctx.user_data["d"]["title"] = text.strip()
        set_state(ctx, "music_editing", **ctx.user_data["d"])
        await show_music_edit_menu(update, ctx, "✅ عنوان تغییر کرد")
        return

    if state == "music_changing_artist":
        ctx.user_data["d"]["artist"] = text.strip()
        set_state(ctx, "music_editing", **ctx.user_data["d"])
        await show_music_edit_menu(update, ctx, "✅ هنرمند تغییر کرد")
        return

    if state == "music_changing_album":
        ctx.user_data["d"]["album"] = text.strip()
        set_state(ctx, "music_editing", **ctx.user_data["d"])
        await show_music_edit_menu(update, ctx, "✅ آلبوم تغییر کرد")
        return

    if state == "music_changing_year":
        ctx.user_data["d"]["year"] = text.strip()
        set_state(ctx, "music_editing", **ctx.user_data["d"])
        await show_music_edit_menu(update, ctx, "✅ سال تغییر کرد")
        return

    if state == "music_changing_genre":
        ctx.user_data["d"]["genre"] = text.strip()
        set_state(ctx, "music_editing", **ctx.user_data["d"])
        await show_music_edit_menu(update, ctx, "✅ ژانر تغییر کرد")
        return

    if state == "music_trim_start":
        try:
            start = parse_time(text.strip())
            ctx.user_data["d"]["trim_start"] = start
            set_state(ctx, "music_trim_end", **ctx.user_data["d"])
            await update.message.reply_text(
                "✂️ **زمان پایان رو بفرستید:**\n"
                "(برای برش تا انتها `0` بفرستید)",
                parse_mode=ParseMode.MARKDOWN,
            )
        except ValueError:
            await update.message.reply_text("❌ فرمت نامعتبر! مثال: `10` یا `1:30`")
        return

    if state == "music_trim_end":
        try:
            end = parse_time(text.strip())
            start = ctx.user_data["d"].get("trim_start", 0)
            file_path = ctx.user_data["d"].get("file_path")

            await update.message.reply_text("✂️ در حال برش...")

            output = music.trim(file_path, start, end)
            if output:
                ctx.user_data["d"]["file_path"] = output
                set_state(ctx, "music_editing", **ctx.user_data["d"])
                await show_music_edit_menu(update, ctx, "✅ برش انجام شد")
            else:
                await show_music_edit_menu(update, ctx, "❌ خطا در برش")
        except ValueError:
            await update.message.reply_text("❌ فرمت نامعتبر! مثال: `30` یا `2:00`")
        return

    # ── Demo music states ──
    if state == "demo_waiting_start":
        try:
            start = parse_time(text.strip())
            ctx.user_data["d"]["demo_start"] = start
            set_state(ctx, "demo_waiting_end", **ctx.user_data["d"])
            await update.message.reply_text(
                "🎬 **زمان پایان دمو رو بفرستید:**\n"
                "(برای دمو تا انتها `0` بفرستید)",
                parse_mode=ParseMode.MARKDOWN,
            )
        except ValueError:
            await update.message.reply_text("❌ فرمت نامعتبر! مثال: `10` یا `1:30`")
        return

    if state == "demo_waiting_end":
        try:
            end = parse_time(text.strip())
            start = ctx.user_data["d"].get("demo_start", 0)
            file_path = ctx.user_data["d"].get("file_path")

            await update.message.reply_text("🎬 در حال ساخت دمو...")

            output = demo.create_voice_demo(file_path, start, end)
            if output:
                with open(output, "rb") as f:
                    await update.message.reply_voice(
                        voice=f,
                        caption=f"🎬 دمو: {music._format_duration(start)} - {music._format_duration(end)}",
                    )
                demo.cleanup(output)
                set_state(ctx, "music_editing", **ctx.user_data["d"])
                await show_music_edit_menu(update, ctx, "✅ دمو ساخته شد")
            else:
                await show_music_edit_menu(update, ctx, "❌ خطا در ساخت دمو")
        except ValueError:
            await update.message.reply_text("❌ فرمت نامعتبر! مثال: `30` یا `2:00`")
        return

    # Default: if no state, check if it's a download request
    if not state:
        await update.message.reply_text(
            "از /start استفاده کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 شروع", callback_data="main_menu")],
            ]),
        )

async def handle_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return

    state, d = get_state(ctx)
    message = update.message

    # Multi-collection: handle collected messages
    if state == "mcollect_collecting":
        await handle_mcollect_message(update, ctx, message)
        return

    # Music editing
    if state in ("music_waiting",):
        await music_received(update, ctx, message)
        return

    if state == "music_waiting_cover":
        photo = message.photo[-1] if message.photo else None
        if photo:
            file = await ctx.bot.get_file(photo.file_id)
            cover_path = str(TEMP_DIR / f"cover_{uuid.uuid4().hex}.jpg")
            await file.download_to_drive(cover_path)

            ctx.user_data["d"]["has_cover"] = True
            ctx.user_data["d"]["cover_path"] = cover_path
            set_state(ctx, "music_editing", **ctx.user_data["d"])

            await show_music_edit_menu(update, ctx, "✅ کاور جدید دریافت شد. روی «ذخیره و ارسال» بزنید.")
            return
        else:
            await message.reply_text("❌ لطفاً یک عکس بفرستید.")
        return

    # Config: add image
    if state == "cfg_add_image":
        await config_add_image_received(update, ctx, message)
        return

    # Config: change image
    if state == "cfg_changing_image":
        photo = message.photo[-1] if message.photo else None
        if photo:
            tpl_id = d["tpl_id"]
            db.update_template(tpl_id, image_file_id=photo.file_id)
            clear_state(ctx)
            await message.reply_text(
                "✅ عکس ذخیره شد.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⚙️ بازگشت", callback_data=f"cfg_edit_{tpl_id}")],
                ]),
            )
        else:
            await message.reply_text("❌ لطفاً یک عکس بفرستید.")
        return

    # Config: add music
    if state == "cfg_add_music":
        await config_add_music_received(update, ctx, message)
        return

    # Config: change music
    if state == "cfg_changing_music":
        audio = message.audio or message.document
        if audio:
            tpl_id = d["tpl_id"]
            db.update_template(tpl_id, music_file_id=audio.file_id)
            clear_state(ctx)
            await message.reply_text(
                "✅ موزیک ذخیره شد.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⚙️ بازگشت", callback_data=f"cfg_edit_{tpl_id}")],
                ]),
            )
        else:
            await message.reply_text("❌ لطفاً یک فایل صوتی بفرستید.")
        return

    # Schedule editing message
    if state == "sch_editing_message":
        await handle_message(update, ctx)
        return


# ─── /skip command ────────────────────────────────────────────
async def cmd_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state, d = get_state(ctx)
    if state == "cfg_add_image":
        set_state(ctx, "cfg_add_text", tpl_id=d["tpl_id"], name=d["name"])
        await update.message.reply_text(
            "⬜ عکس رد شد.\n\n"
            "📝 **متن پیام رو بفرستید:**\n(یا /skip)",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif state == "cfg_add_text":
        set_state(ctx, "cfg_add_music", tpl_id=d["tpl_id"], name=d["name"])
        await update.message.reply_text(
            "⬜ متن رد شد.\n\n"
            "🎵 **فایل موزیک بفرستید:**\n(یا /skip)",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif state == "cfg_add_music":
        clear_state(ctx)
        tpl = db.get_template(d["tpl_id"])
        await update.message.reply_text(
            f"✅ **پیام جدید ساخته شد!**\n\n📋 نام: {tpl['name']}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ تنظیمات", callback_data="config")],
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
            ]),
        )


# ─── /cancel command ──────────────────────────────────────────
async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state, d = get_state(ctx)

    # Clear multi-collection if active
    if state == "mcollect_collecting":
        user = update.effective_user
        session_id = d.get("session_id", f"mc_{user.id}")
        db.clear_collected_messages(user.id, session_id)

    clear_state(ctx)
    await update.message.reply_text("❌ عملیات لغو شد.\n\nاز /start استفاده کنید.")


# ─── Main ─────────────────────────────────────────────────────
def main():
    db.init()
    print("🤖 ربات Admin Channel در حال راه‌اندازی...")

    app = Application.builder().token(BOT_TOKEN).build()

    # Post-init: start scheduled jobs
    app.post_init = _start_all_schedules

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("skip", cmd_skip))

    # Callbacks
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Messages (text + media)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.AUDIO | filters.Document.AUDIO, handle_media))
    app.add_handler(MessageHandler(filters.PHOTO, handle_media))

    print("✅ ربات آماده!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
