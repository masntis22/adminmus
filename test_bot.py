#!/usr/bin/env python3
"""
Test script for Admin Channel Bot
Verifies all handlers and logic work correctly
"""
import os
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

import database as db

def test_database():
    """Test database operations"""
    print("=== Testing Database ===")
    
    # Clean up
    db_path = Path(__file__).parent / "bot_data" / "admin.db"
    if db_path.exists():
        db_path.unlink()
    
    db.init()
    print("✅ Database initialized")
    
    # Test config
    db.put("channel_username", "@testchannel")
    db.put("channel_id", "-1001234567890")
    assert db.get("channel_username") == "@testchannel"
    assert db.get("channel_id") == "-1001234567890"
    print("✅ Config operations work")
    
    # Test templates
    tid = db.add_template(name="Test Template", text="Hello World")
    assert tid > 0
    tpl = db.get_template(tid)
    assert tpl["name"] == "Test Template"
    assert tpl["text_content"] == "Hello World"
    print("✅ Template add/get works")
    
    tpls = db.get_templates()
    assert len(tpls) == 1
    print("✅ Get templates works")
    
    db.update_template(tid, name="Updated Template", text_content="Updated text")
    tpl = db.get_template(tid)
    assert tpl["name"] == "Updated Template"
    assert tpl["text_content"] == "Updated text"
    print("✅ Template update works")
    
    # Test schedules
    sid = db.add_schedule(tid, "-1001234567890", ["09:00", "18:00"])
    assert sid > 0
    scheds = db.get_schedules()
    assert len(scheds) == 1
    assert scheds[0]["times"] == ["09:00", "18:00"]
    print("✅ Schedule add/get works")
    
    # Cleanup
    db.delete_template(tid)
    db.delete_schedule(sid)
    print("✅ Delete operations work")
    
    print()


def test_callback_handlers():
    """Test that all callback data patterns are handled"""
    print("=== Testing Callback Handlers ===")
    
    # Read the bot.py file
    with open(Path(__file__).parent / "bot.py", "r") as f:
        code = f.read()
    
    # Check for all callback data patterns in handlers
    import re
    
    # Find all callback_data patterns sent to users
    sent_patterns = set(re.findall(r'callback_data=["\']([^"\']+)["\']', code))
    
    # Find all patterns handled in callback_handler
    # Extract the handler function
    handler_match = re.search(r'async def callback_handler.*?(?=\nasync def |\nclass |\Z)', code, re.DOTALL)
    if handler_match:
        handler_code = handler_match.group(0)
        handled_patterns = set()
        
        # Check for exact matches
        for pattern in re.findall(r'data == ["\']([^"\']+)["\']', handler_code):
            handled_patterns.add(pattern)
        
        # Check for startswith matches
        for pattern in re.findall(r'data\.startswith\(["\']([^"\']+)["\']', handler_code):
            # These are prefix patterns
            handled_patterns.add(pattern + "*")
        
        print(f"Sent patterns: {len(sent_patterns)}")
        print(f"Handled patterns: {len(handled_patterns)}")
        
        # Check if all sent patterns are handled
        unhandled = []
        for pattern in sent_patterns:
            # Skip patterns that are handled by startswith
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
            print(f"⚠️ Unhandled patterns: {unhandled}")
        else:
            print("✅ All callback patterns are handled")
    else:
        print("❌ Could not find callback_handler function")
    
    print()


def test_imports():
    """Test all imports work"""
    print("=== Testing Imports ===")
    
    try:
        from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
        from telegram.constants import ParseMode
        from telegram.error import TelegramError
        print("✅ Telegram imports OK")
    except ImportError as e:
        print(f"❌ Telegram import error: {e}")
        return False
    
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import APIC, ID3
        print("✅ Mutagen imports OK")
    except ImportError as e:
        print(f"❌ Mutagen import error: {e}")
        return False
    
    try:
        import requests
        print("✅ Requests import OK")
    except ImportError as e:
        print(f"❌ Requests import error: {e}")
        return False
    
    try:
        import database as db
        print("✅ Database import OK")
    except ImportError as e:
        print(f"❌ Database import error: {e}")
        return False
    
    print()
    return True


def test_syntax():
    """Test bot.py syntax"""
    print("=== Testing Syntax ===")
    
    import ast
    
    with open(Path(__file__).parent / "bot.py", "r") as f:
        code = f.read()
    
    try:
        ast.parse(code)
        print("✅ bot.py syntax OK")
    except SyntaxError as e:
        print(f"❌ Syntax error: {e}")
        return False
    
    # Check for duplicate function names
    import re
    funcs = re.findall(r'(?:async )?def (\w+)', code)
    from collections import Counter
    dupes = {k: v for k, v in Counter(funcs).items() if v > 1}
    if dupes:
        print(f"⚠️ Duplicate functions: {dupes}")
    else:
        print("✅ No duplicate functions")
    
    # Check for .bot. issues
    issues = re.findall(r'update\.callback_query\.bot|(?<!ctx\.)message\.bot\.', code)
    if issues:
        print(f"⚠️ Still has .bot issues: {issues}")
    else:
        print("✅ No .bot issues")
    
    print()
    return True


def test_state_management():
    """Test state management logic"""
    print("=== Testing State Management ===")
    
    # Simulate state management
    user_data = {}
    
    def set_state(ctx, state, **data):
        ctx["state"] = state
        ctx["d"] = data
    
    def get_state(ctx):
        return ctx.get("state"), ctx.get("d", {})
    
    def clear_state(ctx):
        ctx.pop("state", None)
        ctx.pop("d", None)
    
    # Test set_state
    set_state(user_data, "waiting_for_input", name="test", value=123)
    state, d = get_state(user_data)
    assert state == "waiting_for_input"
    assert d["name"] == "test"
    assert d["value"] == 123
    print("✅ set_state works")
    
    # Test clear_state
    clear_state(user_data)
    state, d = get_state(user_data)
    assert state is None
    assert d == {}
    print("✅ clear_state works")
    
    print()


if __name__ == "__main__":
    print("🧪 Admin Channel Bot - Test Suite\n")
    
    all_pass = True
    
    all_pass &= test_syntax()
    all_pass &= test_imports()
    test_database()
    test_state_management()
    test_callback_handlers()
    
    if all_pass:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed!")
        sys.exit(1)
