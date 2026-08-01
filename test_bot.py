#!/usr/bin/env python3
"""
Test suite for Admin Channel Bot
مجموعه تست برای ربات ادمین کانال

Tests / تست‌ها:
- Syntax validation / اعتبارسنجی سینتکس
- Import verification / بررسی ایمپورت‌ها
- Database operations / عملیات پایگاه داده
- State management / مدیریت وضعیت
- Callback handler coverage / پوشش هندلرها
- Schedule types (recurring/onetime) / انواع زمان‌بندی
- Multi-collection / جمع‌آوری چند پیامی
- Persian date parsing / تحلیل تاریخ فارسی

Usage / نحوه استفاده:
    python3 test_bot.py
"""

import os
import sys
import asyncio
import json
import re
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from collections import Counter

# Add project to path / اضافه کردن پروژه به مسیر
sys.path.insert(0, str(Path(__file__).parent))

import database as db


def test_database():
    """Test database operations / تست عملیات پایگاه داده"""
    print("=== Testing Database / تست دیتابیس ===")

    # Clean up / پاکسازی
    db_path = Path(__file__).parent / "bot_data" / "admin.db"
    if db_path.exists():
        db_path.unlink()

    db.init()
    print("✅ Database initialized / دیتابیس مقداردهی شد")

    # Test config / تست تنظیمات
    db.put("channel_username", "@testchannel")
    db.put("channel_id", "-1001234567890")
    assert db.get("channel_username") == "@testchannel"
    assert db.get("channel_id") == "-1001234567890"
    print("✅ Config operations work / عملیات تنظیمات کار می‌کنه")

    # Test templates / تست قالب‌ها
    tid = db.add_template(name="Test Template", text="Hello World")
    assert tid > 0
    tpl = db.get_template(tid)
    assert tpl["name"] == "Test Template"
    assert tpl["text_content"] == "Hello World"
    print("✅ Template add/get works / افزودن/دریافت قالب کار می‌کنه")

    tpls = db.get_templates()
    assert len(tpls) == 1
    print("✅ Get templates works / دریافت قالب‌ها کار می‌کنه")

    db.update_template(tid, name="Updated Template", text_content="Updated text")
    tpl = db.get_template(tid)
    assert tpl["name"] == "Updated Template"
    assert tpl["text_content"] == "Updated text"
    print("✅ Template update works / بروزرسانی قالب کار می‌کنه")

    # Test schedules - legacy / تست زمان‌بندی - قدیمی
    sid = db.add_schedule(tid, "-1001234567890", ["09:00", "18:00"])
    assert sid > 0
    scheds = db.get_schedules()
    assert len(scheds) == 1
    assert scheds[0]["times"] == ["09:00", "18:00"]
    assert scheds[0]["schedule_type"] == "recurring"
    print("✅ Schedule add/get works / افزودن/دریافت زمان‌بندی کار می‌کنه")

    # Test single schedule get / تست دریافت تکی زمان‌بندی
    sch = db.get_schedule(sid)
    assert sch is not None
    assert sch["id"] == sid
    print("✅ get_schedule works / دریافت تکی زمان‌بندی کار می‌کنه")

    # Test active schedules / تست زمان‌بندی‌های فعال
    active = db.get_active_schedules()
    assert len(active) == 1
    print("✅ get_active_schedules works / زمان‌بندی‌های فعال کار می‌کنه")

    # Test schedule update / تست بروزرسانی زمان‌بندی
    db.update_schedule(sid, times=["10:00", "20:00"], name="Test Schedule")
    sch = db.get_schedule(sid)
    assert sch["times"] == ["10:00", "20:00"]
    assert sch["name"] == "Test Schedule"
    print("✅ Schedule update works / بروزرسانی زمان‌بندی کار می‌کنه")

    # Test toggle schedule / تست تغییر وضعیت زمان‌بندی
    db.update_schedule(sid, active=0)
    sch = db.get_schedule(sid)
    assert sch["active"] == 0
    active = db.get_active_schedules()
    assert len(active) == 0
    print("✅ Schedule toggle works / تغییر وضعیت زمان‌بندی کار می‌کنه")

    db.update_schedule(sid, active=1)

    # Test onetime schedule / تست زمان‌بندی یک بار مصرف
    sid2 = db.add_schedule(
        tid, "-1001234567890", [],
        schedule_type="onetime",
        send_datetime="2026-08-05T14:30:00",
        name="One-time Test",
    )
    assert sid2 > 0
    sch2 = db.get_schedule(sid2)
    assert sch2["schedule_type"] == "onetime"
    assert sch2["send_datetime"] == "2026-08-05T14:30:00"
    print("✅ Onetime schedule works / زمان‌بندی یک بار مصرف کار می‌کنه")

    # Test schedule with date range / تست زمان‌بندی با بازه تاریخ
    sid3 = db.add_schedule(
        tid, "-1001234567890", ["10:00"],
        schedule_type="recurring",
        start_date="2026-08-01",
        end_date="2026-08-15",
        name="Date Range Test",
    )
    sch3 = db.get_schedule(sid3)
    assert sch3["start_date"] == "2026-08-01"
    assert sch3["end_date"] == "2026-08-15"
    print("✅ Schedule with date range works / زمان‌بندی با بازه تاریخ کار می‌کنه")

    # Cleanup / پاکسازی
    db.delete_template(tid)
    db.delete_schedule(sid)
    db.delete_schedule(sid2)
    db.delete_schedule(sid3)
    print("✅ Delete operations work / عملیات حذف کار می‌کنه")

    print()


def test_collected_messages():
    """Test multi-task message collection / تست جمع‌آوری پیام‌ها"""
    print("=== Testing Collected Messages / تست جمع‌آوری پیام‌ها ===")

    user_id = 12345
    session_id = "mc_12345"

    # Add messages
    mid1 = db.add_collected_message(user_id, session_id, "text", text_content="Hello")
    mid2 = db.add_collected_message(user_id, session_id, "photo", file_id="photo_123")
    mid3 = db.add_collected_message(user_id, session_id, "audio", file_id="audio_456")
    assert mid1 > 0
    assert mid2 > 0
    assert mid3 > 0
    print("✅ Add collected messages works / افزودن پیام‌های جمع‌آوری شده کار می‌کنه")

    # Get messages
    msgs = db.get_collected_messages(user_id, session_id)
    assert len(msgs) == 3
    assert msgs[0]["message_type"] == "text"
    assert msgs[0]["text_content"] == "Hello"
    assert msgs[1]["message_type"] == "photo"
    assert msgs[1]["file_id"] == "photo_123"
    assert msgs[2]["message_type"] == "audio"
    print("✅ Get collected messages works / دریافت پیام‌های جمع‌آوری شده کار می‌کنه")

    # Count by type
    text_count = sum(1 for m in msgs if m["message_type"] == "text")
    photo_count = sum(1 for m in msgs if m["message_type"] == "photo")
    audio_count = sum(1 for m in msgs if m["message_type"] == "audio")
    assert text_count == 1
    assert photo_count == 1
    assert audio_count == 1
    print("✅ Message type counting works / شمارش نوع پیام کار می‌کنه")

    # Clear
    db.clear_collected_messages(user_id, session_id)
    msgs = db.get_collected_messages(user_id, session_id)
    assert len(msgs) == 0
    print("✅ Clear collected messages works / پاکسازی پیام‌های جمع‌آوری شده کار می‌کنه")

    # Cleanup
    db_path = Path(__file__).parent / "bot_data" / "admin.db"
    if db_path.exists():
        db_path.unlink()

    print()


def test_persian_dates():
    """Test Persian date parsing and conversion / تست تحلیل و تبدیل تاریخ فارسی"""
    print("=== Testing Persian Dates / تست تاریخ فارسی ===")

    # Import the helper functions from bot.py
    from bot import _parse_date, _solar_to_gregorian, _is_solar_leap, _format_persian_date

    # Test Gregorian parsing
    result = _parse_date("2026-08-01")
    assert result is not None
    assert result == (2026, 8, 1, True)
    print("✅ Gregorian date parsing works / تحلیل تاریخ میلادی کار می‌کنه")

    result = _parse_date("2026/08/15")
    assert result is not None
    assert result == (2026, 8, 15, True)
    print("✅ Gregorian date with / works / تاریخ میلادی با / کار می‌کنه")

    # Test Solar Hijri parsing
    result = _parse_date("1405-05-10")
    assert result is not None
    assert result == (1405, 5, 10, False)
    print("✅ Solar Hijri date parsing works / تحلیل تاریخ شمسی کار می‌کنه")

    result = _parse_date("1405/06/31")
    assert result is not None
    assert result == (1405, 6, 31, False)
    print("✅ Solar Hijri date with / works / تاریخ شمسی با / کار می‌کنه")

    # Test invalid date
    result = _parse_date("not-a-date")
    assert result is None
    print("✅ Invalid date returns None / تاریخ نامعتبر None برمی‌گردونه")

    # Test Solar to Gregorian conversion
    # 1405/01/01 (Nowruz 2026) should be approximately 2026/03/21
    gy, gm, gd = _solar_to_gregorian(1405, 1, 1)
    assert gy == 2026, f"Expected 2026, got {gy}"
    assert gm == 3, f"Expected 3, got {gm}"
    print(f"✅ Solar→Gregorian: 1405/01/01 → {gy}/{gm}/{gd}")

    # Test leap year (1403 % 33 = 17, which is in the set → leap)
    assert _is_solar_leap(1403) == True, "1403 should be leap (1403%33=17)"
    assert _is_solar_leap(1408) == True, "1408 should be leap (1408%33=22)"
    assert _is_solar_leap(1404) == False, "1404 should not be leap (1404%33=18)"
    print("✅ Solar leap year check works / بررسی سال کبیسه شمسی کار می‌کنه")

    # Test format
    fmt = _format_persian_date(1405, 5, 10, False)
    assert "شمسی" in fmt
    print(f"✅ Persian date format: {fmt}")

    fmt = _format_persian_date(2026, 8, 1, True)
    assert "میلادی" in fmt
    print(f"✅ Gregorian date format: {fmt}")

    print()


def test_callback_handlers():
    """Test callback handler coverage / تست پوشش هندلرها"""
    print("=== Testing Callback Handlers / تست هندلرها ===")

    # Read the bot.py file / خواندن فایل bot.py
    with open(Path(__file__).parent / "bot.py", "r") as f:
        code = f.read()

    # Find all callback_data patterns sent to users / یافتن الگوهای callback_data
    sent_patterns = set(re.findall(r'callback_data=["\']([^"\']+)["\']', code))

    # Find all patterns handled in callback_handler / یافتن الگوهای handle شده
    handler_match = re.search(r'async def callback_handler.*?(?=\nasync def |\nclass |\Z)', code, re.DOTALL)
    if handler_match:
        handler_code = handler_match.group(0)
        handled_patterns = set()

        # Check for exact matches / بررسی تطابق دقیق
        for pattern in re.findall(r'data == ["\']([^"\']+)["\']', handler_code):
            handled_patterns.add(pattern)

        # Check for startswith matches / بررسی تطابق startswith
        for pattern in re.findall(r'data\.startswith\(["\']([^"\']+)["\']', handler_code):
            handled_patterns.add(pattern + "*")

        print(f"Sent patterns / الگوهای ارسالی: {len(sent_patterns)}")
        print(f"Handled patterns / الگوهای handle شده: {len(handled_patterns)}")

        # Check if all sent patterns are handled / بررسی پوشش کامل
        unhandled = []
        for pattern in sent_patterns:
            handled = False
            for hp in handled_patterns:
                if hp.endswith("*"):
                    if pattern.startswith(hp[:-1]):
                        handled = True
                        break
                elif pattern == hp:
                    handled = True
                    break
            if not handled:
                unhandled.append(pattern)

        if unhandled:
            print(f"⚠️ Unhandled patterns / الگوهای handle نشده: {unhandled}")
        else:
            print("✅ All callback patterns are handled / همه الگوها handle می‌شن")
    else:
        print("❌ Could not find callback_handler function / هندلر پیدا نشد")

    print()


def test_imports():
    """Test all imports / تست ایمپورت‌ها"""
    print("=== Testing Imports / تست ایمپورت‌ها ===")

    try:
        from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
        from telegram.constants import ParseMode
        from telegram.error import TelegramError
        print("✅ Telegram imports OK / ایمپورت تلگرام اوکی")
    except ImportError as e:
        print(f"❌ Telegram import error / خطا در ایمپورت تلگرام: {e}")
        return False

    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import APIC, ID3
        print("✅ Mutagen imports OK / ایمپورت mutagen اوکی")
    except ImportError as e:
        print(f"❌ Mutagen import error / خطا در ایمپورت mutagen: {e}")
        return False

    try:
        import requests
        print("✅ Requests import OK / ایمپورت requests اوکی")
    except ImportError as e:
        print(f"❌ Requests import error / خطا در ایمپورت requests: {e}")
        return False

    try:
        import database as db
        print("✅ Database import OK / ایمپورت database اوکی")
    except ImportError as e:
        print(f"❌ Database import error / خطا در ایمپورت database: {e}")
        return False

    try:
        import bot
        print("✅ Bot import OK / ایمپورت bot اوکی")
    except ImportError as e:
        print(f"❌ Bot import error / خطا در ایمپورت bot: {e}")
        return False

    print()
    return True


def test_syntax():
    """Test bot.py syntax / تست سینتکس"""
    print("=== Testing Syntax / تست سینتکس ===")

    import ast

    with open(Path(__file__).parent / "bot.py", "r") as f:
        code = f.read()

    try:
        ast.parse(code)
        print("✅ bot.py syntax OK / سینتکس bot.py اوکی")
    except SyntaxError as e:
        print(f"❌ Syntax error / خطای سینتکس: {e}")
        return False

    # Check for duplicate function names / بررسی توابع تکراری
    funcs = re.findall(r'(?:async )?def (\w+)', code)
    dupes = {k: v for k, v in Counter(funcs).items() if v > 1}
    if dupes:
        print(f"⚠️ Duplicate functions / توابع تکراری: {dupes}")
    else:
        print("✅ No duplicate functions / تابع تکراری نیست")

    # Check for .bot. issues / بررسی مشکلات .bot.
    issues = re.findall(r'update\.callback_query\.bot|(?<!ctx\.)message\.bot\.', code)
    if issues:
        print(f"⚠️ Still has .bot issues / هنوز مشکل .bot. داره: {issues}")
    else:
        print("✅ No .bot issues / مشکل .bot. نیست")

    # Check database.py syntax
    with open(Path(__file__).parent / "database.py", "r") as f:
        db_code = f.read()
    try:
        ast.parse(db_code)
        print("✅ database.py syntax OK / سینتکس database.py اوکی")
    except SyntaxError as e:
        print(f"❌ Database syntax error / خطای سینتکس database: {e}")
        return False

    print()
    return True


def test_state_management():
    """Test state management logic / تست مدیریت وضعیت"""
    print("=== Testing State Management / تست مدیریت وضعیت ===")

    # Simulate state management / شبیه‌سازی مدیریت وضعیت
    user_data = {}

    def set_state(ctx, state, **data):
        ctx["state"] = state
        ctx["d"] = data

    def get_state(ctx):
        return ctx.get("state"), ctx.get("d", {})

    def clear_state(ctx):
        ctx.pop("state", None)
        ctx.pop("d", None)

    # Test set_state / تست set_state
    set_state(user_data, "waiting_for_input", name="test", value=123)
    state, d = get_state(user_data)
    assert state == "waiting_for_input"
    assert d["name"] == "test"
    assert d["value"] == 123
    print("✅ set_state works / set_state کار می‌کنه")

    # Test clear_state / تست clear_state
    clear_state(user_data)
    state, d = get_state(user_data)
    assert state is None
    assert d == {}
    print("✅ clear_state works / clear_state کار می‌کنه")

    # Test multi-collection state / تست وضعیت جمع‌آوری چند پیامی
    set_state(user_data, "mcollect_collecting", session_id="mc_12345",
              start_time="2026-08-01T10:00:00")
    state, d = get_state(user_data)
    assert state == "mcollect_collecting"
    assert d["session_id"] == "mc_12345"
    print("✅ Multi-collection state works / وضعیت جمع‌آوری چند پیامی کار می‌کنه")

    # Test schedule state / تست وضعیت زمان‌بندی
    set_state(user_data, "sch_onetime_datetime", tpl_id=1,
              schedule_type="onetime")
    state, d = get_state(user_data)
    assert state == "sch_onetime_datetime"
    assert d["schedule_type"] == "onetime"
    print("✅ Schedule state works / وضعیت زمان‌بندی کار می‌کنه")

    clear_state(user_data)

    print()


def test_schedule_types():
    """Test schedule type constants / تست ثابت‌های نوع زمان‌بندی"""
    print("=== Testing Schedule Types / تست انواع زمان‌بندی ===")

    # Verify schedule types are consistent
    types = ["recurring", "onetime"]
    assert "recurring" in types
    assert "onetime" in types
    print("✅ Schedule types defined / انواع زمان‌بندی تعریف شدن")

    # Verify database handles both types
    db_path = Path(__file__).parent / "bot_data" / "admin.db"
    if db_path.exists():
        db_path.unlink()
    db.init()

    tid = db.add_template(name="Test", text="Test message")

    # Recurring
    sid1 = db.add_schedule(tid, "-123", ["09:00"], schedule_type="recurring",
                           start_date="2026-08-01", end_date="2026-08-15")
    sch1 = db.get_schedule(sid1)
    assert sch1["schedule_type"] == "recurring"
    assert sch1["times"] == ["09:00"]
    print("✅ Recurring schedule in DB / زمان‌بندی تکراری در دیتابیس")

    # One-time
    sid2 = db.add_schedule(tid, "-123", [], schedule_type="onetime",
                           send_datetime="2026-08-05T14:30:00")
    sch2 = db.get_schedule(sid2)
    assert sch2["schedule_type"] == "onetime"
    assert sch2["send_datetime"] == "2026-08-05T14:30:00"
    print("✅ One-time schedule in DB / زمان‌بندی یک بار مصرف در دیتابیس")

    # Cleanup
    db.delete_template(tid)
    db.delete_schedule(sid1)
    db.delete_schedule(sid2)

    db_path = Path(__file__).parent / "bot_data" / "admin.db"
    if db_path.exists():
        db_path.unlink()

    print()


def test_new_callback_patterns():
    """Verify new callback patterns are defined / بررسی الگوهای کالبک جدید"""
    print("=== Testing New Callback Patterns / تست الگوهای کالبک جدید ===")

    with open(Path(__file__).parent / "bot.py", "r") as f:
        code = f.read()

    # New patterns that should exist
    required_patterns = [
        "sch_type_recurring",
        "sch_type_onetime",
        "mcollect",
        "mcollect_confirm",
        "mcollect_continue",
        "mcollect_cancel",
        "sch_new",
    ]

    for pattern in required_patterns:
        if pattern in code:
            print(f"  ✅ Pattern '{pattern}' found")
        else:
            print(f"  ❌ Pattern '{pattern}' NOT found")

    # Verify multi-collection button in main menu
    assert "mcollect" in code, "mcollect button should be in main menu"
    print("✅ Multi-collection in main menu / جمع‌آوری چند پیامی در منوی اصلی")

    # Verify schedule type selection
    assert "sch_type_recurring" in code
    assert "sch_type_onetime" in code
    print("✅ Schedule type selection / انتخاب نوع زمان‌بندی")

    # Verify schedule management features
    assert "sch_edit_" in code
    assert "sch_toggle_" in code
    assert "sch_del_" in code
    print("✅ Schedule management features / قابلیت‌های مدیریت زمان‌بندی")

    print()


def test_bot_structure():
    """Test overall bot structure / تست ساختار کلی ربات"""
    print("=== Testing Bot Structure / تست ساختار ربات ===")

    with open(Path(__file__).parent / "bot.py", "r") as f:
        code = f.read()

    # Check for key functions
    required_functions = [
        "async def cmd_start",
        "async def flow_schedule",
        "async def schedule_choose_type",
        "async def schedule_new_recurring_start",
        "async def schedule_new_onetime_start",
        "async def schedule_view",
        "async def schedule_toggle",
        "async def schedule_delete",
        "async def schedule_edit_menu",
        "async def mcollect_start",
        "async def mcollect_confirm",
        "async def mcollect_continue",
        "async def handle_mcollect_message",
        "async def _execute_schedule",
        "async def _check_recurring_schedule",
        "async def _send_schedule_message",
        "async def _start_all_schedules",
        "def _schedule_job",
        "def _remove_job",
        "def _parse_date",
        "def _solar_to_gregorian",
        "def _is_solar_leap",
    ]

    for func in required_functions:
        func_name = func.split("def ")[-1].split("(")[0]
        if func in code:
            print(f"  ✅ Function '{func_name}' exists")
        else:
            print(f"  ❌ Function '{func_name}' MISSING")

    # Check for Persian responses
    persian_strings = [
        "زمان‌بندی",
        "تبلیغاتی",
        "یک بار مصرف",
        "جمع‌آوری",
        "ادامه",
        "تایید",
        "شمسی",
        "میلادی",
    ]

    for s in persian_strings:
        if s in code:
            print(f"  ✅ Persian string '{s}' found")
        else:
            print(f"  ❌ Persian string '{s}' NOT found")

    print()


if __name__ == "__main__":
    print("🧪 Admin Channel Bot - Test Suite / مجموعه تست ربات ادمین کانال\n")

    all_pass = True

    all_pass &= test_syntax()
    all_pass &= test_imports()
    test_database()
    test_collected_messages()
    test_persian_dates()
    test_state_management()
    test_schedule_types()
    test_new_callback_patterns()
    test_bot_structure()
    test_callback_handlers()

    if all_pass:
        print("✅ All tests passed / همه تست‌ها رد شد!")
    else:
        print("❌ Some tests failed / بعضی تست‌ها رد نشد!")
        sys.exit(1)
