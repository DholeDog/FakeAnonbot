import os
import json
from aiohttp import web
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, ContextTypes, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters
)

# بارگذاری متغیرهای محیطی
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))

USERS_FILE = "data/users.json"
BLOCKED_FILE = "data/blocked.json"

# ابزار JSON ساده
def load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)

# شروع برای کاربر ناشناس
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    blocked = load_json(BLOCKED_FILE)
    if str(user_id) in blocked:
        await update.message.reply_text("❌ شما بلاک شده‌اید و نمی‌توانید پیام دهید.")
        return
    await update.message.reply_text(
        "به ربات ناشناس پژمان خوش اومدی 💬\n"
        "هر پیامی بفرستی، ناشناس برای پژمان ارسال میشه. ✉️"
    )

# دریافت پیام از کاربران ناشناس
async def handle_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    message = update.message

    blocked = load_json(BLOCKED_FILE)
    if str(user_id) in blocked:
        await message.reply_text("❌ شما بلاک شده‌اید.")
        return

    users = load_json(USERS_FILE)
    msg_id = str(message.message_id)
    users[msg_id] = {"from_id": user_id, "type": "new"}
    save_json(USERS_FILE, users)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✉️ پاسخ به این پیام", callback_data=f"reply_{msg_id}")],
        [InlineKeyboardButton("🚫 بلاک کاربر", callback_data=f"block_{user_id}")]
    ])

    await context.bot.forward_message(OWNER_ID, user_id, message.message_id)
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=(
            f"👤 پیام جدید\n"
            f"▪️ نام: {user.full_name}\n"
            f"▪️ یوزرنیم: @{user.username or 'ندارد'}\n"
            f"▪️ آیدی عددی: {user.id}"
        ),
        reply_markup=keyboard
    )

    await message.reply_text("✅ پیامت ارسال شد.")

# پاسخ پژمان به کاربر
async def handle_pezhman_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    reply_to = context.user_data.get("reply_to")
    if not reply_to:
        await update.message.reply_text("⛔ اول دکمه «پاسخ به پیام» رو بزن.")
        return

    users = load_json(USERS_FILE)
    info = users.get(reply_to)
    if not info:
        await update.message.reply_text("⛔ پیام اصلی پیدا نشد.")
        return

    target_id = info["from_id"]
    reply_text = update.message.text

    prompt = await context.bot.send_message(
        chat_id=target_id,
        text="📩 شما یک پیام جدید دارید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📬 مشاهده پیام", callback_data=f"seen_{update.message.message_id}_{reply_to}")]
        ])
    )

    context.bot_data[f"reply_msg_{update.message.message_id}"] = reply_text
    context.user_data["reply_to"] = None
    await update.message.reply_text("✅ پیام ارسال شد.")

# مشاهده پیام توسط کاربر ناشناس
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("reply_"):
        msg_id = data.split("_")[1]
        context.user_data["reply_to"] = msg_id
        await query.message.reply_text("📝 پیام خودت رو بنویس.")

    elif data.startswith("block_"):
        target_id = data.split("_")[1]
        blocked = load_json(BLOCKED_FILE)
        blocked[str(target_id)] = True
        save_json(BLOCKED_FILE, blocked)
        await query.message.reply_text("✅ کاربر بلاک شد.")

    elif data.startswith("seen_"):
        parts = data.split("_")
        reply_msg_id = parts[1]
        user_msg_id = parts[2]
        users = load_json(USERS_FILE)
        info = users.get(user_msg_id)
        if info:
            reply_text = context.bot_data.get(f"reply_msg_{reply_msg_id}", "")
            await query.message.reply_text(reply_text, reply_to_message_id=int(user_msg_id))
            await context.bot.send_message(
                OWNER_ID,
                text="👁 پیام خونده شد.",
                reply_to_message_id=int(reply_msg_id)
            )

# لیست کاربران بلاک‌شده + آنبلاک
async def blocked_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    blocked = load_json(BLOCKED_FILE)
    if not blocked:
        await update.message.reply_text("🚫 هیچ کاربری بلاک نیست.")
        return
    buttons = [
        [InlineKeyboardButton(f"✅ آنبلاک {uid}", callback_data=f"unblock_{uid}")]
        for uid in blocked.keys()
    ]
    await update.message.reply_text("لیست کاربران بلاک‌شده:", reply_markup=InlineKeyboardMarkup(buttons))

async def unblock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data.startswith("unblock_"):
        uid = data.split("_")[1]
        blocked = load_json(BLOCKED_FILE)
        blocked.pop(uid, None)
        save_json(BLOCKED_FILE, blocked)
        await update.callback_query.message.reply_text("🔓 کاربر آنبلاک شد.")
        await update.callback_query.answer()

# Webhook endpoint
async def webhook_handler(request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return web.Response(text="ok")

# راه‌اندازی
application = Application.builder().token(BOT_TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("blocked", blocked_list))
application.add_handler(CallbackQueryHandler(unblock_callback, pattern="^unblock_"))
application.add_handler(CallbackQueryHandler(handle_callback))
application.add_handler(MessageHandler(filters.TEXT & filters.User(user_id=OWNER_ID), handle_pezhman_reply))
application.add_handler(MessageHandler(filters.TEXT & ~filters.User(user_id=OWNER_ID), handle_user))

app = web.Application()
app.router.add_post("/webhook", webhook_handler)

if __name__ == "__main__":
    web.run_app(app, port=10000)
