#!/usr/bin/env python3
"""
Admin Channel Bot v1
ربات ادمین مدیریت کانال تلگرام
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

# ─── Config ───────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

BASE_DIR = Path(__file__).parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

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
    elif data.startswith("sch_del_"):
        time_val = data.split("_")[-1]
        await schedule_del_time(update, ctx, time_val)
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
        if data.startswith("sch_deltime_"):
            pass  # handled above
        else:
            sch_id = int(data.split("_")[-1])
            await schedule_delete(update, ctx, sch_id)

    # ── Music edit flow ──
    elif data == "music_change_title":
        await music_ask_title(update, ctx)
    elif data == "music_change_artist":
        await music_ask_artist(update, ctx)
    elif data == "music_change_cover":
        await music_ask_cover(update, ctx)
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
    bot = update.callback_query.bot

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


# Handle "sch_new" callback
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    if not is_admin(user.id):
        await query.answer("⛔ دسترسی غیرمجاز!", show_alert=True)
        return

    state, d = get_state(ctx)

    if data == "sch_new":
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
        return

    # All other callbacks handled by the main callback_handler
    # This is a re-implementation - see below
    pass


# Override the callback handler to include all logic
# (We need to handle sch_new in the main handler too)
# This will be merged into the main callback_handler


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
    set_state(ctx, "music_waiting")
    await update.callback_query.edit_message_text(
        "🎵 **ویرایش موزیک**\n\n"
        "یک فایل صوتی بفرستید تا متادیتای اون رو ویرایش کنید.\n\n"
        "📌 قابلیت‌ها:\n"
        "• تغییر نام آهنگ\n"
        "• تغییر نام هنرمند\n"
        "• تغییر کاور آرت",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="music_cancel")],
        ]),
    )


async def music_received(update, ctx, message):
    """Handle received audio file for editing."""
    state, d = get_state(ctx)
    if state != "music_waiting":
        return

    audio = message.audio or message.document
    if not audio:
        await message.reply_text("❌ لطفاً یک فایل صوتی بفرستید.")
        return

    # Download file
    file = await message.bot.get_file(audio.file_id)
    ext = os.path.splitext(file.file_path)[1] or ".mp3"
    tmp_path = TEMP_DIR / f"{uuid.uuid4().hex}{ext}"
    await file.download_to_drive(str(tmp_path))

    # Read metadata
    try:
        audio_file = EasyID3(str(tmp_path))
        title = audio_file.get("title", ["نامشخص"])[0]
        artist = audio_file.get("artist", ["نامشخص"])[0]
    except Exception:
        title = audio.title or "نامشخص"
        artist = "نامشخص"

    # Check for cover art
    has_cover = False
    try:
        af = ID3(str(tmp_path))
        has_cover = any(k.startswith("APIC") for k in af.keys())
    except Exception:
        pass

    # Save state
    set_state(ctx, "music_editing",
              file_id=audio.file_id,
              file_path=str(tmp_path),
              title=title,
              artist=artist,
              has_cover=has_cover)

    keyboard = [
        [InlineKeyboardButton(f"✏️ عنوان: {title}", callback_data="music_change_title")],
        [InlineKeyboardButton(f"🎤 هنرمند: {artist}", callback_data="music_change_artist")],
        [InlineKeyboardButton(
            "🖼️ تغییر کاور" if has_cover else "🖼️ اضافه کاور",
            callback_data="music_change_cover"
        )],
        [InlineKeyboardButton("✅ ذخیره و ارسال", callback_data="music_done")],
        [InlineKeyboardButton("❌ لغو", callback_data="music_cancel")],
    ]

    await message.reply_text(
        f"🎵 **ویرایش موزیک**\n\n"
        f"📌 **عنوان:** {title}\n"
        f"🎤 **هنرمند:** {artist}\n"
        f"🖼️ **کاور:** {'✅ دارد' if has_cover else '❌ ندارد'}\n\n"
        f"چه چیزی رو می‌خواید تغییر بدید؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


async def music_ask_title(update, ctx):
    state, d = get_state(ctx)
    set_state(ctx, "music_changing_title", **d)
    await update.callback_query.edit_message_text(
        "✏️ **عنوان جدید رو بفرستید:**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="music_cancel")],
        ]),
    )


async def music_ask_artist(update, ctx):
    state, d = get_state(ctx)
    set_state(ctx, "music_changing_artist", **d)
    await update.callback_query.edit_message_text(
        "🎤 **نام هنرمند جدید رو بفرستید:**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="music_cancel")],
        ]),
    )


async def music_ask_cover(update, ctx):
    state, d = get_state(ctx)
    set_state(ctx, "music_waiting_cover", **d)
    await update.callback_query.edit_message_text(
        "🖼️ **عکس کاور جدید رو بفرستید:**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="music_cancel")],
        ]),
    )


async def music_apply_changes(update, ctx):
    """Apply all metadata changes to the file."""
    state, d = get_state(ctx)
    file_path = d.get("file_path")
    if not file_path or not os.path.exists(file_path):
        await update.message.reply_text("❌ فایل یافت نشد. دوباره موزیک بفرستید.")
        clear_state(ctx)
        return

    try:
        audio = EasyID3(file_path)
        audio["title"] = d.get("title", "نامشخص")
        audio["artist"] = d.get("artist", "نامشخص")
        audio.save()
    except Exception:
        pass

    # Apply cover art if changed
    cover_path = d.get("cover_path")
    if cover_path and os.path.exists(cover_path):
        try:
            af = ID3(file_path)
            # Remove old cover
            af.delall("APIC")
            # Add new cover
            with open(cover_path, "rb") as f:
                cover_data = f.read()
            af.add(APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,
                desc="Cover",
                data=cover_data,
            ))
            af.save()
        except Exception as e:
            logger.warning(f"Cover art error: {e}")

    return file_path


async def music_finish(update, ctx):
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
        title = d.get("title", "Unknown")
        artist = d.get("artist", "Unknown")

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
            f"🎤 هنرمند: {artist}",
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
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        cover_path = d.get("cover_path")
        if cover_path and os.path.exists(cover_path):
            os.remove(cover_path)
    except Exception:
        pass


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

    # Default: if no state, check if it's a download request
    if not state:
        await update.message.reply_text(
            "از /start استفاده کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 شروع", callback_data="main_menu")],
            ]),
        )


async def show_music_edit_menu(update, ctx, status_msg=""):
    state, d = get_state(ctx)
    title = d.get("title", "نامشخص")
    artist = d.get("artist", "نامشخص")
    has_cover = d.get("has_cover", False)

    prefix = f"{status_msg}\n\n" if status_msg else ""

    keyboard = [
        [InlineKeyboardButton(f"✏️ عنوان: {title}", callback_data="music_change_title")],
        [InlineKeyboardButton(f"🎤 هنرمند: {artist}", callback_data="music_change_artist")],
        [InlineKeyboardButton(
            "🖼️ تغییر کاور" if has_cover else "🖼️ اضافه کاور",
            callback_data="music_change_cover"
        )],
        [InlineKeyboardButton("✅ ذخیره و ارسال", callback_data="music_done")],
        [InlineKeyboardButton("❌ لغو", callback_data="music_cancel")],
    ]

    await update.message.reply_text(
        f"{prefix}🎵 **ویرایش موزیک**\n\n"
        f"📌 **عنوان:** {title}\n"
        f"🎤 **هنرمند:** {artist}\n"
        f"🖼️ **کاور:** {'✅ دارد' if has_cover else '❌ ندارد'}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
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
            file = await message.bot.get_file(photo.file_id)
            cover_path = str(TEMP_DIR / f"cover_{uuid.uuid4().hex}.jpg")
            await file.download_to_drive(cover_path)

            # Apply cover immediately
            file_path = d.get("file_path")
            if file_path and os.path.exists(file_path):
                try:
                    af = ID3(file_path)
                    af.delall("APIC")
                    with open(cover_path, "rb") as f:
                        cover_data = f.read()
                    af.add(APIC(
                        encoding=3,
                        mime="image/jpeg",
                        type=3,
                        desc="Cover",
                        data=cover_data,
                    ))
                    af.save()

                    ctx.user_data["d"]["has_cover"] = True
                    ctx.user_data["d"]["cover_path"] = cover_path
                    set_state(ctx, "music_editing", **ctx.user_data["d"])

                    await show_music_edit_menu(update, ctx, "✅ کاور تغییر کرد")
                    return
                except Exception as e:
                    logger.error(f"Cover apply error: {e}")
                    await message.reply_text("❌ خطا در اعمال کاور.")
            else:
                await message.reply_text("❌ فایل موزیک یافت نشد.")
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
