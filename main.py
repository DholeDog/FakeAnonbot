import os
import json
import time
import threading
from typing import Dict, Set

from flask import Flask
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# -----------------------------
# Config
# -----------------------------
TOKEN = os.environ["BOT_TOKEN"]
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])

DATA_DIR = os.environ.get("DATA_DIR", ".")
BLOCK_FILE = os.path.join(DATA_DIR, "blocked.json")
MAP_FILE = os.path.join(DATA_DIR, "map.json")

# Anti-spam (ساده و سبک)
MIN_SECONDS_BETWEEN_MSGS = int(os.environ.get("MIN_SECONDS_BETWEEN_MSGS", "2"))

# -----------------------------
# Tiny persistence helpers
# توجه: روی هاست‌های رایگان ممکنه بعد از redeploy فایل‌ها پاک بشن
# ولی برای کارکرد روزمره خوبه.
# -----------------------------
def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path: str, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass

blocked_users: Set[int] = set(load_json(BLOCK_FILE, []))
# map: admin_message_id -> user_id (برای اینکه اگر ادمین روی پیام ریپلای کرد، بفهمیم برای کیه)
admin_msg_to_user: Dict[str, int] = load_json(MAP_FILE, {})

# rate limit in-memory: user_id -> last_time
last_msg_time: Dict[int, float] = {}

# -----------------------------
# Keep-alive web server
# -----------------------------
web_app = Flask(__name__)

@web_app.get("/health")
def health():
    return "ok", 200

def run_web():
    port = int(os.environ.get("PORT", "8080"))
    web_app.run(host="0.0.0.0", port=port)

# -----------------------------
# Bot logic
# -----------------------------
def user_display(u) -> str:
    # اطلاعاتی که فقط ادمین می‌بیند
    name = (u.full_name or "").strip()
    username = f"@{u.username}" if u.username else "(no username)"
    return f"{name} | {username} | id={u.id}"

def admin_keyboard(user_id: int, is_blocked: bool) -> InlineKeyboardMarkup:
    if is_blocked:
        btn = InlineKeyboardButton("✅ Unblock", callback_data=f"unblock:{user_id}")
    else:
        btn = InlineKeyboardButton("⛔ Block", callback_data=f"block:{user_id}")
    return InlineKeyboardMarkup([[btn]])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! پیام‌تو بنویس؛ من ناشناس ارسالش می‌کنم برای پژمان."
    )

async def help_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return
    await update.message.reply_text(
        "راهنما (ادمین):\n"
        "• برای جواب دادن، روی پیام کاربر که برات میاد Reply کن.\n"
        "• /block <user_id>\n"
        "• /unblock <user_id>\n"
        "• /blocked (لیست بلاک‌ها)\n"
    )

async def blocked_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return
    if not blocked_users:
        await update.message.reply_text("لیست بلاک خالیه.")
        return
    await update.message.reply_text("Blocked user_ids:\n" + "\n".join(map(str, sorted(blocked_users))))

async def cmd_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text("استفاده: /block <user_id>")
        return
    try:
        uid = int(context.args[0])
        blocked_users.add(uid)
        save_json(BLOCK_FILE, list(blocked_users))
        await update.message.reply_text(f"⛔ Blocked: {uid}")
    except ValueError:
        await update.message.reply_text("user_id باید عددی باشه.")

async def cmd_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text("استفاده: /unblock <user_id>")
        return
    try:
        uid = int(context.args[0])
        blocked_users.discard(uid)
        save_json(BLOCK_FILE, list(blocked_users))
        await update.message.reply_text(f"✅ Unblocked: {uid}")
    except ValueError:
        await update.message.reply_text("user_id باید عددی باشه.")

async def on_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    user = update.effective_user
    user_id = user.id

    # اگر بلاک است، هیچ واکنشی نده یا یک پیام کوتاه بده
    if user_id in blocked_users:
        # برای اینکه لو نره بلاک شده، می‌تونی سکوت کنی؛ ولی اینجا مودبانه جواب می‌دیم:
        await msg.reply_text("فعلاً امکان ارسال پیام نیست.")
        return

    # rate limit ساده برای جلوگیری از اسپم و فشار روی هاست
    now = time.time()
    last = last_msg_time.get(user_id, 0)
    if now - last < MIN_SECONDS_BETWEEN_MSGS:
        await msg.reply_text("لطفاً کمی صبر کن و دوباره بفرست.")
        return
    last_msg_time[user_id] = now

    text = msg.text or ""
    if not text.strip():
        await msg.reply_text("فقط پیام متنی پشتیبانی می‌شود.")
        return

    # پیام به ادمین: هویت کامل + متن
    header = (
        "📩 پیام جدید (برای کاربر ناشناس)\n"
        f"👤 {user_display(user)}\n"
        "—\n"
    )
    sent = await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=header + text,
        reply_markup=admin_keyboard(user_id, user_id in blocked_users),
    )

    # مپ کردن message_id ادمین به user_id برای Reply
    admin_msg_to_user[str(sent.message_id)] = user_id
    save_json(MAP_FILE, admin_msg_to_user)

    await msg.reply_text("✅ ارسال شد.")

async def on_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ادمین روی پیام “ارسال شده به ادمین” Reply می‌زند
    msg = update.message
    if not msg or msg.chat_id != ADMIN_CHAT_ID:
        return
    if not msg.reply_to_message:
        return

    replied_id = str(msg.reply_to_message.message_id)
    target_user_id = admin_msg_to_user.get(replied_id)
    if not target_user_id:
        return  # این ریپلای مربوط به پیام‌های ربات نبود

    if target_user_id in blocked_users:
        await msg.reply_text("این کاربر بلاک است. اگر می‌خواهی جواب دهی، اول Unblock کن.")
        return

    text = msg.text or ""
    if not text.strip():
        await msg.reply_text("فقط پیام متنی برای ریپلای پشتیبانی می‌شود.")
        return

    # ارسال جواب به کاربر
    await context.bot.send_message(chat_id=target_user_id, text=f"📨 پاسخ پژمان:\n{text}")
    await msg.reply_text("✅ ارسال شد به کاربر.")

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    await q.answer()

    if q.message.chat_id != ADMIN_CHAT_ID:
        return

    data = q.data or ""
    try:
        action, uid_s = data.split(":", 1)
        uid = int(uid_s)
    except Exception:
        return

    if action == "block":
        blocked_users.add(uid)
        save_json(BLOCK_FILE, list(blocked_users))
        await q.edit_message_reply_markup(reply_markup=admin_keyboard(uid, True))
        await q.message.reply_text(f"⛔ Blocked: {uid}")

    elif action == "unblock":
        blocked_users.discard(uid)
        save_json(BLOCK_FILE, list(blocked_users))
        await q.edit_message_reply_markup(reply_markup=admin_keyboard(uid, False))
        await q.message.reply_text(f"✅ Unblocked: {uid}")

def main():
    # start keep-alive web
    threading.Thread(target=run_web, daemon=True).start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_admin))
    app.add_handler(CommandHandler("block", cmd_block))
    app.add_handler(CommandHandler("unblock", cmd_unblock))
    app.add_handler(CommandHandler("blocked", blocked_list))

    # دکمه‌های بلاک/آن‌بلاک زیر پیام‌های ادمین
    app.add_handler(CallbackQueryHandler(on_button))

    # پیام کاربران (متن)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Chat(ADMIN_CHAT_ID), on_user_message))

    # ریپلای ادمین روی پیام‌های ربات
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Chat(ADMIN_CHAT_ID), on_admin_reply))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()