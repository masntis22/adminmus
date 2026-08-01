#!/usr/bin/env python3
"""
Admin Channel Bot v1
ربات ادمین مدیریت کانال تلگرام

Features / امکانات:
- Send configured messages to channel (image + text + music)
  ارسال پیام کانفیگ شده به کانال (عکس + متن + موزیک)
- Schedule daily sends at specific times
  زمان‌بندی ارسال روزانه در ساعات مشخص
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
from pathlib import Path
from datetime import datetime, time

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

# ─── Config ───────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

BASE_DIR = Path(__file__).parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# Initialize music tools / مقداردهی ابزار موزیک
music = MusicTools(str(TEMP_DIR))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


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

    # ── Schedule flow ──
    elif data.startswith("sch_tpl_"):
        tpl_id = int(data.split("_")[-1])
        await schedule_set_times(update, ctx, tpl_id)
    elif data.startswith("sch_add_"):
        time_val = data.split("_")[-1]
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

    # ── Schedule new ──
    elif data == "sch_new":
        templates = db.get_templates()
        if not templates:
            await query.edit_message_text(
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
            rows.append([InlineKeyboardButton(f"📋 {t['name']}", callback_data=f"sch_tpl_{t['id']}")])
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="schedule")])

        await query.edit_message_text(
            "⏰ **زمان‌بندی جدید**\n\nیک پیام رو انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.MARKDOWN,
        )


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
    # Show existing schedules first
    scheds = db.get_schedules()
    templates = db.get_templates()

    if scheds:
        rows = []
        for s in scheds:
            tpl = db.get_template(s["template_id"])
            tpl_name = tpl["name"] if tpl else "❌ حذف شده"
            status = "✅" if s["active"] else "⏸️"
            times_str = ", ".join(s["times"]) if s["times"] else "بدون زمان"
            rows.append([InlineKeyboardButton(
                f"{status} {tpl_name} ({times_str})",
                callback_data=f"sch_view_{s['id']}"
            )])
        rows.append([InlineKeyboardButton("➕ زمان‌بندی جدید", callback_data="sch_new")])
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])

        text = "⏰ **زمان‌بندی‌های فعال:**\n\nروی یکی کلیک کنید:"
    else:
        rows = []
        if templates:
            rows.append([InlineKeyboardButton("➕ زمان‌بندی جدید", callback_data="sch_new")])
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
        text = "⏰ **زمان‌بندی ارسال**\n\nهنوز زمان‌بندی‌ای تنظیم نشده."

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


async def schedule_set_times(update, ctx, tpl_id):
    tpl = db.get_template(tpl_id)
    if not tpl:
        await update.callback_query.answer("❌ پیام یافت نشد!", show_alert=True)
        return

    set_state(ctx, "sch_set_times", tpl_id=tpl_id, times=[])

    # Quick time buttons
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
        f"⏰ **زمان‌بندی: {tpl['name']}**\n\n"
        f"ساعت‌های ارسال رو انتخاب کنید:\n"
        f"(هر روز در این ساعات به کانال ارسال می‌شه)\n\n"
        f"📋 **زمان‌های انتخاب شده:** هنوز هیچ",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


async def schedule_add_time(update, ctx, time_val):
    state, d = get_state(ctx)
    times = d.get("times", [])

    if time_val not in times:
        times.append(time_val)
        times.sort()

    set_state(ctx, "sch_set_times", tpl_id=d["tpl_id"], times=times)

    tpl = db.get_template(d["tpl_id"])
    times_display = ", ".join(times) if times else "هنوز هیچ"

    # Rebuild keyboard with highlight on selected times
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
        f"⏰ **زمان‌بندی: {tpl['name']}**\n\n"
        f"📋 **زمان‌های انتخاب شده:** `{times_display}`",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


async def schedule_del_time(update, ctx, time_val):
    state, d = get_state(ctx)
    times = d.get("times", [])
    if time_val in times:
        times.remove(time_val)

    set_state(ctx, "sch_set_times", tpl_id=d["tpl_id"], times=times)
    await schedule_add_time(update, ctx, time_val)  # Refresh display


async def schedule_save(update, ctx):
    state, d = get_state(ctx)
    tpl_id = d.get("tpl_id")
    times = d.get("times", [])

    if not times:
        await update.callback_query.answer("❌ حداقل یک ساعت انتخاب کنید!", show_alert=True)
        return

    ch_name, ch_id = get_channel()
    db.add_schedule(tpl_id, ch_id, times)

    tpl = db.get_template(tpl_id)
    clear_state(ctx)

    await update.callback_query.edit_message_text(
        f"✅ **زمان‌بندی ذخیره شد!**\n\n"
        f"📋 پیام: {tpl['name']}\n"
        f"🕐 ساعت‌ها: {', '.join(times)}\n"
        f"📢 کانال: `{ch_name}`\n\n"
        f"هر روز در این ساعات پیام به کانال ارسال می‌شه.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏰ زمان‌بندی‌ها", callback_data="schedule")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
        ]),
    )


async def schedule_view(update, ctx, sch_id):
    scheds = db.get_schedules()
    sch = next((s for s in scheds if s["id"] == sch_id), None)
    if not sch:
        await update.callback_query.answer("❌ زمان‌بندی یافت نشد!", show_alert=True)
        return

    tpl = db.get_template(sch["template_id"])
    tpl_name = tpl["name"] if tpl else "❌ حذف شده"
    status = "✅ فعال" if sch["active"] else "⏸️ غیرفعال"
    times_str = ", ".join(sch["times"]) if sch["times"] else "بدون زمان"

    keyboard = [
        [InlineKeyboardButton(
            "⏸️ غیرفعال کن" if sch["active"] else "✅ فعال کن",
            callback_data=f"sch_toggle_{sch_id}"
        )],
        [InlineKeyboardButton("🗑️ حذف", callback_data=f"sch_del_{sch_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="schedule")],
    ]

    await update.callback_query.edit_message_text(
        f"⏰ **جزئیات زمان‌بندی**\n\n"
        f"📋 پیام: {tpl_name}\n"
        f"🕐 ساعت‌ها: `{times_str}`\n"
        f"📊 وضعیت: {status}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


async def schedule_toggle(update, ctx, sch_id):
    scheds = db.get_schedules()
    sch = next((s for s in scheds if s["id"] == sch_id), None)
    if not sch:
        return

    new_active = 0 if sch["active"] else 1
    db.update_schedule(sch_id, active=new_active)

    await schedule_view(update, ctx, sch_id)


async def schedule_delete(update, ctx, sch_id):
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


# ══════════════════════════════════════════════════════════════
# 3) MUSIC EDIT - ویرایش موزیک
# ══════════════════════════════════════════════════════════════

async def flow_edit_music(update, ctx):
    """Show music tools menu / نمایش منوی ابزار موزیک"""
    keyboard = [
        [InlineKeyboardButton("📝 ویرایش متادیتا", callback_data="mt_meta")],
        [InlineKeyboardButton("🖼️ مدیریت کاور", callback_data="mt_cover")],
        [InlineKeyboardButton("🔄 تبدیل فرمت", callback_data="mt_convert")],
        [InlineKeyboardButton("🔊 تنظیم صدا", callback_data="mt_volume")],
        [InlineKeyboardButton("✂️ برش صدا", callback_data="mt_trim")],
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
# 4) CONFIG - تنظیمات پیام‌ها
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
        # Try to get channel ID
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
        # Make sure current user is included
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

    # Music editing
    if state in ("music_waiting",):
        await music_received(update, ctx, message)
        return

    if state == "music_waiting_cover":
        photo = message.photo[-1] if message.photo else None
        if photo:
            # Download cover
            file = await ctx.bot.get_file(photo.file_id)
            cover_path = str(TEMP_DIR / f"cover_{uuid.uuid4().hex}.jpg")
            await file.download_to_drive(cover_path)

            # Store cover path - will be applied when user clicks "done"
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
    clear_state(ctx)
    await update.message.reply_text("❌ عملیات لغو شد.\n\nاز /start استفاده کنید.")


# ─── Main ─────────────────────────────────────────────────────
def main():
    db.init()
    print("🤖 ربات Admin Channel در حال راه‌اندازی...")

    app = Application.builder().token(BOT_TOKEN).build()

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
