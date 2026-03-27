"""
Jira Telegram Bot - Asosiy fayl
Jira (edoc.uztelecom.uz) bilan integratsiya
"""

import asyncio
import logging
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import TELEGRAM_TOKEN, POLL_INTERVAL_SECONDS
from jira_client import JiraClient

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Foydalanuvchi sessiyalari: {chat_id: {"jira": JiraClient, "username": str}}
user_sessions: dict = {}
# Kuzatilgan topshiriqlar (yangi issue aniqlash uchun): {chat_id: set(issue_keys)}
tracked_issues: dict = {}


# ─────────────────────────────────────────────
# YORDAMCHI FUNKSIYALAR
# ─────────────────────────────────────────────

def get_jira(chat_id: int) -> JiraClient | None:
    session = user_sessions.get(chat_id)
    return session["jira"] if session else None


def format_issue(issue: dict, detailed: bool = False) -> str:
    """Issue ma'lumotini chiroyli matn formatiga o'girish."""
    fields = issue.get("fields", {})
    key = issue.get("key", "N/A")
    summary = fields.get("summary", "Noma'lum")
    status = fields.get("status", {}).get("name", "N/A")
    priority = fields.get("priority", {}).get("name", "N/A")
    assignee = (fields.get("assignee") or {}).get("displayName", "Tayinlanmagan")
    reporter = (fields.get("reporter") or {}).get("displayName", "N/A")
    due_date = fields.get("duedate", "Muddati yo'q")

    emoji_status = {
        "Open": "🔵", "In Progress": "🟡", "Done": "✅",
        "Closed": "⛔", "Resolved": "✅", "Reopened": "🔴",
    }.get(status, "⚪")

    emoji_priority = {
        "Highest": "🔴", "High": "🟠", "Medium": "🟡",
        "Low": "🟢", "Lowest": "⚪",
    }.get(priority, "⚪")

    text = (
        f"📋 *{key}*\n"
        f"📝 {summary}\n"
        f"{emoji_status} Holat: *{status}*\n"
        f"{emoji_priority} Muhimlik: {priority}\n"
        f"👤 Bajaruvchi: {assignee}\n"
        f"📅 Muddat: {due_date}\n"
    )

    if detailed:
        description = fields.get("description", "Tavsif yo'q") or "Tavsif yo'q"
        if len(description) > 300:
            description = description[:300] + "..."
        text += (
            f"📣 Muallif: {reporter}\n"
            f"\n📄 *Tavsif:*\n{description}\n"
        )

    return text


def issue_keyboard(issue_key: str) -> InlineKeyboardMarkup:
    """Issue uchun inline tugmalar."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Batafsil ko'rish", callback_data=f"detail_{issue_key}")],
        [InlineKeyboardButton("🌐 Saytda ochish", url=f"https://edoc.uztelecom.uz/browse/{issue_key}")],
    ])


# ─────────────────────────────────────────────
# KOMANDALAR
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bot boshlash va tizimga kirish."""
    chat_id = update.effective_chat.id

    if chat_id in user_sessions:
        username = user_sessions[chat_id]["username"]
        await update.message.reply_text(
            f"✅ Siz allaqachon tizimga kirgansiz, *{username}*!\n\n"
            "📌 *Mavjud buyruqlar:*\n"
            "/myissues — Mening topshiriqlarim\n"
            "/search — Topshiriq qidirish\n"
            "/deadlines — Muddati yaqin topshiriqlar\n"
            "/notifications — Xabarnomalar sozlamalari\n"
            "/logout — Tizimdan chiqish",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        "👋 *Jira Bot*ga xush kelibsiz!\n\n"
        "🔐 Tizimga kirish uchun quyidagi formatda ma'lumot yuboring:\n\n"
        "`/login foydalanuvchi_nomi:parol`\n\n"
        "📌 Misol:\n`/login john.doe:mypassword123`\n\n"
        "⚠️ Xavfsizlik uchun xabarni yuborganingizdan keyin o'chiring.",
        parse_mode="Markdown",
    )


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Jira tizimiga kirish."""
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text(
            "❌ Format: `/login foydalanuvchi_nomi:parol`",
            parse_mode="Markdown",
        )
        return

    credentials = " ".join(context.args)
    if ":" not in credentials:
        await update.message.reply_text("❌ Format noto'g'ri. Misol: `/login user:password`", parse_mode="Markdown")
        return

    username, password = credentials.split(":", 1)
    username = username.strip()
    password = password.strip()

    # Xabarni o'chirish (xavfsizlik)
    try:
        await update.message.delete()
    except Exception:
        pass

    msg = await update.effective_chat.send_message("⏳ Tizimga kirilmoqda...")

    jira = JiraClient(username=username, password=password)
    success, error_msg = jira.test_connection()

    if success:
        user_sessions[chat_id] = {"jira": jira, "username": username}
        tracked_issues[chat_id] = set()
        await msg.edit_text(
            f"✅ *Xush kelibsiz, {jira.display_name}!*\n\n"
            "📌 *Mavjud buyruqlar:*\n"
            "• /myissues — Mening topshiriqlarim\n"
            "• /search `<kalit so'z>` — Qidirish\n"
            "• /deadlines — Muddati yaqin topshiriqlar\n"
            "• /notifications — Xabarnoma sozlamalari\n"
            "• /logout — Chiqish\n\n"
            "🔔 Yangi topshiriqlar va xabarnomalar avtomatik yuboriladi!",
            parse_mode="Markdown",
        )
        # Polling ishga tushirish
        context.job_queue.run_repeating(
            poll_new_issues,
            interval=POLL_INTERVAL_SECONDS,
            first=10,
            chat_id=chat_id,
            name=f"poll_{chat_id}",
        )
    else:
        await msg.edit_text(f"❌ Kirish muvaffaqiyatsiz:\n`{error_msg}`", parse_mode="Markdown")


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tizimdan chiqish."""
    chat_id = update.effective_chat.id
    if chat_id in user_sessions:
        username = user_sessions[chat_id]["username"]
        del user_sessions[chat_id]
        tracked_issues.pop(chat_id, None)
        # Polling to'xtatish
        jobs = context.job_queue.get_jobs_by_name(f"poll_{chat_id}")
        for job in jobs:
            job.schedule_removal()
        await update.message.reply_text(f"👋 *{username}*, tizimdan chiqdingiz.", parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ Siz tizimga kirmagansiz.")


async def my_issues(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Foydalanuvchiga tayinlangan topshiriqlar."""
    chat_id = update.effective_chat.id
    jira = get_jira(chat_id)
    if not jira:
        await update.message.reply_text("🔐 Avval tizimga kiring: /login")
        return

    msg = await update.message.reply_text("⏳ Topshiriqlar yuklanmoqda...")
    issues, error = jira.get_my_issues()

    if error:
        await msg.edit_text(f"❌ Xatolik: {error}")
        return

    if not issues:
        await msg.edit_text("📭 Sizga tayinlangan topshiriq yo'q.")
        return

    await msg.edit_text(f"📋 *Sizning topshiriqlaringiz* ({len(issues)} ta):", parse_mode="Markdown")

    for issue in issues[:10]:  # Max 10 ta
        text = format_issue(issue)
        keyboard = issue_keyboard(issue["key"])
        await update.effective_chat.send_message(text, parse_mode="Markdown", reply_markup=keyboard)


async def search_issues(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """JQL yoki kalit so'z bo'yicha qidirish."""
    chat_id = update.effective_chat.id
    jira = get_jira(chat_id)
    if not jira:
        await update.message.reply_text("🔐 Avval tizimga kiring: /login")
        return

    if not context.args:
        await update.message.reply_text(
            "🔍 *Qidirish:*\n`/search <kalit so'z>`\n\nMisol:\n`/search server xatosi`",
            parse_mode="Markdown",
        )
        return

    query = " ".join(context.args)
    msg = await update.message.reply_text(f"🔍 *{query}* qidirilmoqda...")

    issues, error = jira.search_issues(query)

    if error:
        await msg.edit_text(f"❌ Xatolik: {error}")
        return

    if not issues:
        await msg.edit_text(f"🔍 *{query}* bo'yicha natija topilmadi.", parse_mode="Markdown")
        return

    await msg.edit_text(
        f"🔍 *'{query}'* bo'yicha {len(issues)} ta natija:", parse_mode="Markdown"
    )

    for issue in issues[:8]:
        text = format_issue(issue)
        keyboard = issue_keyboard(issue["key"])
        await update.effective_chat.send_message(text, parse_mode="Markdown", reply_markup=keyboard)


async def deadlines(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muddati yaqinlashgan topshiriqlar (7 kun ichida)."""
    chat_id = update.effective_chat.id
    jira = get_jira(chat_id)
    if not jira:
        await update.message.reply_text("🔐 Avval tizimga kiring: /login")
        return

    msg = await update.message.reply_text("⏳ Muddatlar tekshirilmoqda...")
    issues, error = jira.get_upcoming_deadlines(days=7)

    if error:
        await msg.edit_text(f"❌ Xatolik: {error}")
        return

    if not issues:
        await msg.edit_text("✅ Yaqin 7 kun ichida muddati tugaydigan topshiriq yo'q.")
        return

    await msg.edit_text(
        f"⏰ *Muddati yaqin topshiriqlar* ({len(issues)} ta):", parse_mode="Markdown"
    )

    for issue in issues:
        fields = issue.get("fields", {})
        due_date_str = fields.get("duedate", "")
        days_left = ""
        if due_date_str:
            due = datetime.strptime(due_date_str, "%Y-%m-%d")
            delta = (due - datetime.now()).days
            if delta < 0:
                days_left = f" ⚠️ *{abs(delta)} kun kechikkan!*"
            elif delta == 0:
                days_left = " 🚨 *Bugun muddati tugaydi!*"
            else:
                days_left = f" ⏳ *{delta} kun qoldi*"

        text = format_issue(issue) + days_left
        keyboard = issue_keyboard(issue["key"])
        await update.effective_chat.send_message(text, parse_mode="Markdown", reply_markup=keyboard)


async def notifications_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xabarnoma sozlamalari menyu."""
    chat_id = update.effective_chat.id
    if chat_id not in user_sessions:
        await update.message.reply_text("🔐 Avval tizimga kiring: /login")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 Yangi topshiriqlar", callback_data="notif_new")],
        [InlineKeyboardButton("⏰ Muddatlar eslatmasi", callback_data="notif_deadlines")],
        [InlineKeyboardButton("📊 Holdurum o'zgarishlari", callback_data="notif_status")],
        [InlineKeyboardButton("❌ Barcha xabarnomalarni o'chirish", callback_data="notif_off")],
    ])
    await update.message.reply_text(
        "🔔 *Xabarnoma sozlamalari*\n\nQaysi xabarnomalarni olmoqchisiz?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ─────────────────────────────────────────────
# CALLBACK QUERY HANDLER
# ─────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline tugmalar uchun handler."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    if data.startswith("detail_"):
        issue_key = data.split("_", 1)[1]
        jira = get_jira(chat_id)
        if not jira:
            await query.message.reply_text("🔐 Sessiya tugagan. /login")
            return
        issue, error = jira.get_issue(issue_key)
        if error:
            await query.message.reply_text(f"❌ {error}")
            return
        text = format_issue(issue, detailed=True)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Saytda ochish", url=f"https://edoc.uztelecom.uz/browse/{issue_key}")]
        ])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

    elif data == "notif_new":
        await query.edit_message_text(
            "✅ *Yangi topshiriqlar* xabarnomasi yoqilgan!\n"
            f"Har {POLL_INTERVAL_SECONDS // 60} daqiqada tekshiriladi.",
            parse_mode="Markdown",
        )
    elif data == "notif_deadlines":
        jobs = context.job_queue.get_jobs_by_name(f"deadline_{chat_id}")
        if not jobs:
            context.job_queue.run_daily(
                daily_deadline_reminder,
                time=datetime.strptime("09:00", "%H:%M").time(),
                chat_id=chat_id,
                name=f"deadline_{chat_id}",
            )
        await query.edit_message_text(
            "✅ *Muddatlar eslatmasi* yoqilgan!\nHar kuni soat 09:00 da xabar yuboriladi.",
            parse_mode="Markdown",
        )
    elif data == "notif_status":
        await query.edit_message_text(
            "✅ *Holat o'zgarishi* xabarnomasi yoqilgan!\nTopshiriq holati o'zgarganda xabar olasiz.",
            parse_mode="Markdown",
        )
    elif data == "notif_off":
        jobs = context.job_queue.get_jobs_by_name(f"deadline_{chat_id}")
        for job in jobs:
            job.schedule_removal()
        await query.edit_message_text("🔕 Barcha qo'shimcha xabarnomalar o'chirildi.")


# ─────────────────────────────────────────────
# POLLING FUNKSIYALARI
# ─────────────────────────────────────────────

async def poll_new_issues(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Yangi topshiriqlarni avtomatik tekshirish."""
    chat_id = context.job.chat_id
    jira = get_jira(chat_id)
    if not jira:
        return

    issues, error = jira.get_my_issues(max_results=50)
    if error or not issues:
        return

    current_keys = {issue["key"] for issue in issues}

    if not tracked_issues.get(chat_id):
        tracked_issues[chat_id] = current_keys
        return

    new_keys = current_keys - tracked_issues[chat_id]
    tracked_issues[chat_id] = current_keys

    for key in new_keys:
        issue = next((i for i in issues if i["key"] == key), None)
        if issue:
            text = f"🆕 *Yangi topshiriq keldi!*\n\n" + format_issue(issue)
            keyboard = issue_keyboard(key)
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

    # Muddati bugun tugaydi-mi?
    await check_todays_deadlines(context, chat_id, jira)


async def check_todays_deadlines(context, chat_id: int, jira: JiraClient) -> None:
    """Bugun muddati tugaydigan topshiriqlarni tekshirish."""
    issues, error = jira.get_upcoming_deadlines(days=1)
    if error or not issues:
        return

    today = datetime.now().strftime("%Y-%m-%d")
    for issue in issues:
        due = issue.get("fields", {}).get("duedate", "")
        if due == today:
            text = f"🚨 *Bugun muddati tugaydi!*\n\n" + format_issue(issue)
            keyboard = issue_keyboard(issue["key"])
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )


async def daily_deadline_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Har kunlik muddat eslatmasi (soat 09:00)."""
    chat_id = context.job.chat_id
    jira = get_jira(chat_id)
    if not jira:
        return

    issues, error = jira.get_upcoming_deadlines(days=7)
    if error:
        return

    if not issues:
        await context.bot.send_message(
            chat_id=chat_id,
            text="✅ *Kunlik hisobot:* Yaqin 7 kun ichida muddati tugaydigan topshiriq yo'q.",
            parse_mode="Markdown",
        )
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"📅 *Kunlik eslatma:* {len(issues)} ta topshiriqning muddati yaqin!",
        parse_mode="Markdown",
    )
    for issue in issues:
        text = format_issue(issue)
        keyboard = issue_keyboard(issue["key"])
        await context.bot.send_message(
            chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=keyboard
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 *Yordam — Jira Bot*\n\n"
        "🔐 *Kirish/Chiqish:*\n"
        "• /start — Botni boshlash\n"
        "• /login `user:pass` — Tizimga kirish\n"
        "• /logout — Tizimdan chiqish\n\n"
        "📋 *Topshiriqlar:*\n"
        "• /myissues — Mening topshiriqlarim\n"
        "• /search `<so'z>` — Qidirish\n"
        "• /deadlines — Muddati yaqin (7 kun)\n\n"
        "🔔 *Xabarnomalar:*\n"
        "• /notifications — Sozlamalar\n\n"
        "❓ *Yordam:*\n"
        "• /help — Ushbu menyu",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("myissues", my_issues))
    app.add_handler(CommandHandler("search", search_issues))
    app.add_handler(CommandHandler("deadlines", deadlines))
    app.add_handler(CommandHandler("notifications", notifications_menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("🤖 Jira Bot ishga tushdi...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
