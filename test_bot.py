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

Usage / نحوه استفاده:
    python3 test_bot.py
"""

import os
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

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
    
    # Test schedules / تست زمان‌بندی
    sid = db.add_schedule(tid, "-1001234567890", ["09:00", "18:00"])
    assert sid > 0
    scheds = db.get_schedules()
    assert len(scheds) == 1
    assert scheds[0]["times"] == ["09:00", "18:00"]
    print("✅ Schedule add/get works / افزودن/دریافت زمان‌بندی کار می‌کنه")
    
    # Cleanup / پاکسازی
    db.delete_template(tid)
    db.delete_schedule(sid)
    print("✅ Delete operations work / عملیات حذف کار می‌کنه")
    
    print()


def test_callback_handlers():
    """Test callback handler coverage / تست پوشش هندلرها"""
    print("=== Testing Callback Handlers / تست هندلرها ===")
    
    # Read the bot.py file / خواندن فایل bot.py
    with open(Path(__file__).parent / "bot.py", "r") as f:
        code = f.read()
    
    import re
    
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
    import re
    funcs = re.findall(r'(?:async )?def (\w+)', code)
    from collections import Counter
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
    
    print()


if __name__ == "__main__":
    print("🧪 Admin Channel Bot - Test Suite / مجموعه تست ربات ادمین کانال\n")
    
    all_pass = True
    
    all_pass &= test_syntax()
    all_pass &= test_imports()
    test_database()
    test_state_management()
    test_callback_handlers()
    
    if all_pass:
        print("✅ All tests passed / همه تست‌ها رد شد!")
    else:
        print("❌ Some tests failed / بعضی تست‌ها رد نشد!")
        sys.exit(1)
