import os
import html
import sqlite3
import threading
import time
import logging

from flask import Flask
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException


# ============================================================
# 1. CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN environment variable is missing. "
        "Set BOT_TOKEN before starting the bot."
    )

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "2016851713"))
except ValueError:
    raise RuntimeError("ADMIN_ID must be a valid integer.")

DB_PATH = os.getenv("DB_PATH", "creator_bot.db")

db_lock = threading.RLock()

bot = telebot.TeleBot(
    BOT_TOKEN,
    threaded=True,
    num_threads=4
)


# ============================================================
# 2. LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("CreatorDesk")


# ============================================================
# 3. HELPERS
# ============================================================

def safe_html(value):
    """Escape user-controlled text before putting it into HTML messages."""
    if value is None:
        return ""
    return html.escape(str(value))


def normalize_username(username):
    if username:
        return f"@{username}"
    return "Creator"


# ============================================================
# 4. DATABASE
# ============================================================

ALLOWED_USER_FIELDS = {
    "username",
    "points",
    "status",
    "slot",
    "step",
    "name",
    "age",
    "city",
    "insta",
    "photo_id",
    "claim_pending",
}


def get_db_connection():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    # Better SQLite behavior under concurrent access
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    return conn


def init_sqlite():
    with db_lock:
        conn = get_db_connection()

        try:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    uid TEXT PRIMARY KEY,
                    username TEXT,
                    points INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'unverified',
                    slot TEXT NOT NULL DEFAULT 'Not Set',
                    step TEXT NOT NULL DEFAULT 'none',
                    name TEXT DEFAULT '',
                    age TEXT DEFAULT '',
                    city TEXT DEFAULT '',
                    insta TEXT DEFAULT '',
                    photo_id TEXT DEFAULT '',
                    claim_pending INTEGER NOT NULL DEFAULT 0
                )
            """)

            # Migration support for older databases
            cursor.execute("PRAGMA table_info(users)")
            existing_columns = {
                row[1] for row in cursor.fetchall()
            }

            if "claim_pending" not in existing_columns:
                cursor.execute("""
                    ALTER TABLE users
                    ADD COLUMN claim_pending INTEGER NOT NULL DEFAULT 0
                """)

            conn.commit()

        finally:
            conn.close()


init_sqlite()


def get_user(uid):
    s_uid = str(uid)

    with db_lock:
        conn = get_db_connection()

        try:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM users WHERE uid = ?",
                (s_uid,)
            )

            row = cursor.fetchone()

            return dict(row) if row else None

        finally:
            conn.close()


def init_user(uid, username=None):
    s_uid = str(uid)
    u_name = normalize_username(username)

    with db_lock:
        conn = get_db_connection()

        try:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR IGNORE INTO users (
                    uid,
                    username,
                    points,
                    status,
                    slot,
                    step,
                    name,
                    age,
                    city,
                    insta,
                    photo_id,
                    claim_pending
                )
                VALUES (?, ?, 0, 'unverified', 'Not Set',
                        'none', '', '', '', '', '', 0)
            """, (s_uid, u_name))

            # Update username if Telegram username changed
            cursor.execute("""
                UPDATE users
                SET username = ?
                WHERE uid = ?
            """, (u_name, s_uid))

            conn.commit()

        finally:
            conn.close()


def update_user(uid, **kwargs):
    if not kwargs:
        return

    invalid_fields = set(kwargs.keys()) - ALLOWED_USER_FIELDS

    if invalid_fields:
        raise ValueError(
            f"Invalid database fields: {', '.join(invalid_fields)}"
        )

    s_uid = str(uid)

    set_clause = ", ".join(
        f"{field} = ?"
        for field in kwargs.keys()
    )

    values = list(kwargs.values())
    values.append(s_uid)

    with db_lock:
        conn = get_db_connection()

        try:
            cursor = conn.cursor()

            cursor.execute(
                f"""
                UPDATE users
                SET {set_clause}
                WHERE uid = ?
                """,
                values
            )

            conn.commit()

        finally:
            conn.close()


def change_points(uid, amount):
    """
    Atomically change points.
    Returns the new balance.
    """

    s_uid = str(uid)

    with db_lock:
        conn = get_db_connection()

        try:
            cursor = conn.cursor()

            cursor.execute("BEGIN IMMEDIATE")

            cursor.execute("""
                SELECT points
                FROM users
                WHERE uid = ?
            """, (s_uid,))

            row = cursor.fetchone()

            if not row:
                conn.rollback()
                return None

            current_points = int(row["points"] or 0)

            new_points = current_points + int(amount)

            # Never allow negative points
            new_points = max(0, new_points)

            cursor.execute("""
                UPDATE users
                SET points = ?
                WHERE uid = ?
            """, (new_points, s_uid))

            conn.commit()

            return new_points

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()


# ============================================================
# 5. FLASK KEEP-ALIVE
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "CreatorDesk Engine Active"


def run_web():
    port = int(os.environ.get("PORT", "8080"))

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )


# ============================================================
# 6. DASHBOARD
# ============================================================

def get_dashboard_menu(uid):

    user = get_user(uid)

    if not user:
        return None

    points = int(user.get("points", 0) or 0)

    markup = types.InlineKeyboardMarkup(row_width=2)

    markup.add(
        types.InlineKeyboardButton(
            f"💰 Balance: {points} Pts",
            callback_data="btn_points"
        ),
        types.InlineKeyboardButton(
            "⏰ Change Time Slot",
            callback_data="btn_slot"
        ),
        types.InlineKeyboardButton(
            "🏆 Leaderboard",
            callback_data="btn_leaderboard"
        ),
        types.InlineKeyboardButton(
            "🎁 Claim Amazon Voucher",
            callback_data="btn_claim"
        )
    )

    return markup


def is_approved(uid):
    user = get_user(uid)

    return bool(
        user and
        user.get("status") == "approved"
    )


# ============================================================
# 7. START
# ============================================================

@bot.message_handler(commands=["start"])
def start_cmd(message):

    uid = str(message.from_user.id)

    init_user(
        uid,
        message.from_user.username
    )

    user = get_user(uid)

    if not user:
        bot.send_message(
            message.chat.id,
            "❌ Account initialization failed. Please try again."
        )
        return

    status_text = (
        "Active"
        if user["status"] == "approved"
        else "Pending Verification"
    )

    points = int(user.get("points", 0) or 0)

    first_name = safe_html(
        message.from_user.first_name
    )

    welcome_text = (
        f"👋 <b>Welcome to CreatorDesk Portal, "
        f"{first_name}!</b> 🌟\n\n"

        "Aapka account successfully initialize ho chuka hai.\n\n"

        "📌 <b>YOUR CREATOR PROFILE</b>\n"

        f"• <b>Portal Status:</b> "
        f"<code>{safe_html(status_text)}</code>\n"

        f"• <b>Worker Tag:</b> "
        f"<code>{safe_html(uid)}</code>\n"

        f"• <b>Live Balance:</b> "
        f"<code>{points} Points</code>\n\n"

        "📋 <b>ONBOARDING VERIFICATION</b>\n"

        "Campaign tasks aur Welcome Bonus unlock "
        "karne ke liye verification mandatory hai.\n\n"

        "👉 Shuru karne ke liye niche button dabayein:"
    )

    if user["status"] != "approved":

        markup = types.InlineKeyboardMarkup()

        markup.add(
            types.InlineKeyboardButton(
                "📝 Start Verification (18+)",
                callback_data="start_onboarding"
            )
        )

    else:
        markup = get_dashboard_menu(uid)

    bot.send_message(
        message.chat.id,
        welcome_text,
        parse_mode="HTML",
        reply_markup=markup
    )


# ============================================================
# 8. START ONBOARDING
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "start_onboarding"
)
def start_steps(call):

    uid = str(call.from_user.id)

    init_user(
        uid,
        call.from_user.username
    )

    update_user(
        uid,
        step="step_name",
        name="",
        age="",
        city="",
        insta="",
        photo_id="",
        claim_pending=0
    )

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,

        "📋 <b>Step 1/6: Full Legal Name</b>\n\n"
        "Apna poora legal naam likhkar bhejein:",

        parse_mode="HTML"
    )


# ============================================================
# 9. ADMIN REPLY ROUTING
# ============================================================

def extract_worker_id_from_text(text):

    if not text:
        return None

    marker = "Worker Tag:"

    if marker not in text:
        return None

    try:
        after_marker = text.split(
            marker,
            1
        )[1]

        worker_id = (
            after_marker
            .strip()
            .split()[0]
            .replace("`", "")
            .replace("<code>", "")
            .replace("</code>", "")
        )

        if not worker_id.isdigit():
            return None

        return int(worker_id)

    except Exception:
        return None


# ============================================================
# 10. USER INPUT ROUTER
# ============================================================

@bot.message_handler(
    func=lambda m: True,
    content_types=["text", "photo"]
)
def handle_all_messages(message):

    uid = str(message.from_user.id)

    init_user(
        uid,
        message.from_user.username
    )

    # --------------------------------------------------------
    # ADMIN REPLY
    # --------------------------------------------------------

    if message.from_user.id == ADMIN_ID:

        if not message.reply_to_message:
            return

        replied = message.reply_to_message

        raw_text = (
            replied.text
            or replied.caption
            or ""
        )

        target_id = extract_worker_id_from_text(
            raw_text
        )

        if not target_id:
            return

        target_user = get_user(target_id)

        if not target_user:
            bot.reply_to(
                message,
                "❌ Worker database me nahi mila."
            )
            return

        if message.content_type != "text":
            bot.reply_to(
                message,
                "❌ Admin reply ke liye text message use karein."
            )
            return

        clean_reply = safe_html(
            message.text
        )

        target_points = int(
            target_user.get("points", 0) or 0
        )

        try:

            bot.send_message(
                target_id,

                "💬 <b>Support Desk Reply:</b>\n\n"
                f"{clean_reply}\n\n"
                f"<i>💰 Live Balance: "
                f"{target_points} Pts</i>",

                parse_mode="HTML"
            )

            bot.reply_to(
                message,
                "✅ User ko reply bhej diya gaya hai."
            )

        except Exception as exc:

            logger.exception(
                "Failed to send admin reply"
            )

            bot.reply_to(
                message,
                f"❌ Reply bhejne me error: "
                f"{safe_html(exc)}"
            )

        return

    # --------------------------------------------------------
    # USER FLOW
    # --------------------------------------------------------

    user = get_user(uid)

    if not user:
        return

    current_step = user.get(
        "step",
        "none"
    )

    # ========================================================
    # STEP 1 - NAME
    # ========================================================

    if current_step == "step_name":

        if message.content_type != "text":
            bot.reply_to(
                message,
                "❌ Kripya text me apna naam likhein."
            )
            return

        name = message.text.strip()

        if not name or len(name) > 100:
            bot.reply_to(
                message,
                "❌ Kripya valid naam enter karein."
            )
            return

        update_user(
            uid,
            name=name,
            step="step_age"
        )

        bot.send_message(
            message.chat.id,

            "📋 <b>Step 2/6: Age (18+ only)</b>\n\n"
            "Apni umar number me enter karein:",

            parse_mode="HTML"
        )

        return

    # ========================================================
    # STEP 2 - AGE
    # ========================================================

    if current_step == "step_age":

        if message.content_type != "text":
            bot.reply_to(
                message,
                "❌ Kripya age number me enter karein."
            )
            return

        age_text = message.text.strip()

        if not age_text.isdigit():

            bot.reply_to(
                message,
                "⚠️ Kripya valid age enter karein."
            )
            return

        age = int(age_text)

        if age < 18 or age > 120:

            bot.reply_to(
                message,
                "⚠️ Is platform ke liye 18+ hona anivarya hai. "
                "Kripya valid 18+ age enter karein."
            )
            return

        update_user(
            uid,
            age=str(age),
            step="step_city"
        )

        bot.send_message(
            message.chat.id,

            "📋 <b>Step 3/6: Current City</b>\n\n"
            "Apna current shehar likhkar bhejein:",

            parse_mode="HTML"
        )

        return

    # ========================================================
    # STEP 3 - CITY
    # ========================================================

    if current_step == "step_city":

        if message.content_type != "text":

            bot.reply_to(
                message,
                "❌ Kripya city ka naam likhein."
            )
            return

        city = message.text.strip()

        if not city or len(city) > 100:

            bot.reply_to(
                message,
                "❌ Kripya valid city enter karein."
            )
            return

        update_user(
            uid,
            city=city,
            step="step_insta"
        )

        bot.send_message(
            message.chat.id,

            "📋 <b>Step 4/6: Instagram Handle</b>\n\n"
            "Apna Instagram username bhejein "
            "(example: <code>@username</code>):",

            parse_mode="HTML"
        )

        return

    # ========================================================
    # STEP 4 - INSTAGRAM
    # ========================================================

    if current_step == "step_insta":

        if message.content_type != "text":

            bot.reply_to(
                message,
                "❌ Kripya Instagram handle likhein."
            )
            return

        insta = message.text.strip()

        if not insta or len(insta) > 100:

            bot.reply_to(
                message,
                "❌ Kripya valid Instagram handle enter karein."
            )
            return

        update_user(
            uid,
            insta=insta,
            step="step_photo"
        )

        bot.send_message(
            message.chat.id,

            "📋 <b>Step 5/6: Pose Photo</b>\n\n"

            "📸 Kripya apni clear "
            "<b>Pose Photo</b> upload karein.\n\n"

            "⚠️ Photo upload kiye bina "
            "verification complete nahi hogi.",

            parse_mode="HTML"
        )

        return

    # ========================================================
    # STEP 5 - PHOTO
    # ========================================================

    if current_step == "step_photo":

        if message.content_type != "photo":

            bot.reply_to(
                message,
                "🚫 <b>Photo zaroori hai!</b>\n"
                "Kripya photo upload karein.",

                parse_mode="HTML"
            )

            return

        photo_id = message.photo[-1].file_id

        update_user(
            uid,
            photo_id=photo_id,
            step="step_consent"
        )

        bot.send_message(
            message.chat.id,

            "📋 <b>Step 6/6: Eligibility & Consent</b>\n\n"

            "Is platform ke tasks ke liye "
            "18+ hona anivarya hai.\n\n"

            "Confirmation ke liye exact text bhejein:\n\n"

            "👉 <code>AGREE - 18+</code>",

            parse_mode="HTML"
        )

        return

    # ========================================================
    # STEP 6 - CONSENT
    # ========================================================

    if current_step == "step_consent":

        if (
            message.content_type != "text"
            or message.text.strip().upper()
            != "AGREE - 18+"
        ):

            bot.reply_to(
                message,

                "⚠️ Confirmation ke liye exactly "
                "<code>AGREE - 18+</code> "
                "likhkar send karein.",

                parse_mode="HTML"
            )

            return

        update_user(
            uid,
            step="completed_pending"
        )

        u_data = get_user(uid)

        if not u_data or not u_data.get("photo_id"):
            bot.send_message(
                message.chat.id,
                "❌ Photo data missing hai. Please /start se dobara try karein."
    )
