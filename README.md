# 🎵 Admin Channel Bot

<div dir="rtl">

## فارسی

ربات تلگرام ادمین برای مدیریت محتوای کانال. با این ربات می‌تونید پیام‌ها رو زمان‌بندی کنید، موزیک ویرایش کنید و محتوا رو به کانال ارسال کنید.

</div>

## English

A Telegram admin bot for managing channel content. Schedule posts, edit music metadata, and send configured messages to your channel.

---

<div dir="rtl">

### ✨ امکانات

| قابلیت | توضیح |
|--------|-------|
| 📤 **ارسال پیام** | ارسال پیام کانفیگ شده (عکس + متن + موزیک) به کانال |
| ⏰ **زمان‌بندی** | ارسال خودکار روزانه در ساعات مشخص |
| 🎵 **ویرایش موزیک** | تغییر عنوان، هنرمند و کاور آرت |
| ⚙️ **تنظیمات** | ساخت، ویرایش و حذف پیام‌ها |

</div>

### ✨ Features

| Feature | Description |
|---------|-------------|
| 📤 **Send Now** | Send configured message (image + text + music) to channel |
| ⏰ **Schedule** | Auto-send daily at specific times |
| 🎵 **Music Editor** | Change title, artist and cover art |
| ⚙️ **Config** | Create, edit and delete message templates |

---

<div dir="rtl">

### 📋 پیش‌نیازها

- پایتون 3.8 به بالا
- توکن ربات تلگرام (از @BotFather)
- ربات باید ادمین کانال باشه

</div>

### 📋 Prerequisites

- Python 3.8+
- Telegram Bot Token (from @BotFather)
- Bot must be admin in the channel

---

<div dir="rtl">

### 🚀 نصب و اجرا

```bash
# 1. کلون کردن ریپو
git clone https://github.com/masntis22/adminmus.git
cd adminmus

# 2. نصب پکیج‌ها
pip install -r requirements.txt

# 3. تنظیم متغیرهای محیطی
export BOT_TOKEN="توکن_ربات_تلگرام"
export ADMIN_IDS="633606748,5008894513"

# 4. اجرا
python3 bot.py
```

</div>

### 🚀 Installation & Setup

```bash
# 1. Clone the repo
git clone https://github.com/masntis22/adminmus.git
cd adminmus

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment variables
export BOT_TOKEN="your_bot_token"
export ADMIN_IDS="633606748,5008894513"

# 4. Run the bot
python3 bot.py
```

---

<div dir="rtl">

### 📖 نحوه استفاده

#### مرحله ۱: تنظیمات اولیه
1. ربات رو با `/start` شروع کنید
2. نام کانال رو وارد کنید (مثلاً `@mychannel` یا `-1001234567890`)
3. آیدی عددی ادمین‌ها رو وارد کنید (با کاما جدا کنید)

#### مرحله ۲: ساخت پیام
1. از منوی اصلی «تنظیمات پیام‌ها» رو بزنید
2. «پیام جدید» رو انتخاب کنید
3. نام، عکس، متن و موزیک رو تنظیم کنید

#### مرحله ۳: ارسال
1. «ارسال پیام به کانال» رو بزنید
2. پیام مورد نظر رو انتخاب کنید
3. پیش‌نمایش رو ببینید و تأیید کنید

#### مرحله ۴: زمان‌بندی
1. «زمان‌بندی ارسال» رو بزنید
2. پیام و ساعت‌ها رو انتخاب کنید
3. ذخیره کنید - هر روز در این ساعات ارسال می‌شه

</div>

### 📖 Usage Guide

#### Step 1: Initial Setup
1. Start the bot with `/start`
2. Enter channel name (e.g., `@mychannel` or `-1001234567890`)
3. Enter admin user IDs (comma separated)

#### Step 2: Create Messages
1. Go to "Config" from main menu
2. Select "Add New"
3. Set name, image, text and music

#### Step 3: Send
1. Click "Send to Channel"
2. Select your message
3. Preview and confirm

#### Step 4: Schedule
1. Click "Schedule"
2. Select message and times
3. Save - messages will be sent daily at those times

---

<div dir="rtl">

### 🗂️ ساختار پروژه

```
adminmus/
├── bot.py           # فایل اصلی ربات
├── database.py      # عملیات پایگاه داده
├── requirements.txt # پکیج‌های مورد نیاز
├── test_bot.py      # اسکریپت تست
├── README.md        # راهنما
└── .gitignore       # فایل‌های غیرضروری
```

</div>

### 🗂️ Project Structure

```
adminmus/
├── bot.py           # Main bot file with all handlers
├── database.py      # SQLite database operations
├── requirements.txt # Python dependencies
├── test_bot.py      # Test suite
├── README.md        # Documentation
└── .gitignore       # Git ignore rules
```

---

<div dir="rtl">

### 🔧 دستورات ربات

| دستور | توضیح |
|-------|-------|
| `/start` | شروع ربات و نمایش منوی اصلی |
| `/cancel` | لغو عملیات جاری |
| `/skip` | رد کردن مرحله فعلی |

</div>

### 🔧 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Start bot and show main menu |
| `/cancel` | Cancel current operation |
| `/skip` | Skip current step |

---

<div dir="rtl">

### ❗ نکات مهم

- ربات باید ادمین کانال باشه تا بتونه پیام ارسال کنه
- فایل‌های دانلود شده در پوشه `temp/` ذخیره می‌شن و بعد از ارسال پاک می‌شن
- اطلاعات کاربران در `bot_data/admin.db` ذخیره می‌شه
- برای اجرا به عنوان سرویس، از systemd استفاده کنید

</div>

### ❗ Important Notes

- Bot must be admin in the channel to send messages
- Downloaded files are stored in `temp/` and deleted after sending
- User data is stored in `bot_data/admin.db`
- Use systemd to run as a service

---

<div dir="rtl">

### 📄 لایسنس

MIT License - فقط برای مقاصد آموزشی

</div>

### 📄 License

MIT License - For educational purposes only.
