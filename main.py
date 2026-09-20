import os
import html
import sqlite3
import threading
import time

from flask import Flask
import telebot
from telebot import types


# =========================
# CONFIGURATION
# =========================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID_RAW = os.environ.get("ADMIN_ID", "2016851713")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    ADMIN_ID = 2016851713

DB_PATH = os.environ.get("DB_PATH", "creator_bot.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing. Set BOT_TOKEN before starting the bot.")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

app = Flask(__name__)
db_lock = threading.RLock()


# =========================
# FLASK KEEP-ALIVE (Render Support)
# =========================

@app.route("/")
def home():
    return "Bot is running 24/7!"


@app.route("/health")
def health():
    return "OK", 200


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True
    )


# =========================
# DATABASE
# =========================

def get_db():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db():
    with db_lock:
        conn = get_db()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                uid INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                points INTEGER DEFAULT 0,
                status TEXT DEFAULT 'new',
                slot TEXT DEFAULT '',
                step TEXT DEFAULT '',
                name TEXT DEFAULT '',
                age INTEGER DEFAULT 0,
                city TEXT DEFAULT '',
                insta TEXT DEFAULT '',
                photo_id TEXT DEFAULT '',
                claim_pending INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()


def get_user(uid):
    with db_lock:
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM users WHERE uid = ?",
            (uid,)
        ).fetchone()
        conn.close()
        return row


def create_user(uid, username):
    with db_lock:
        conn = get_db()
        conn.execute("""
            INSERT OR IGNORE INTO users
            (uid, username, status, step)
            VALUES (?, ?, 'new', 'name')
        """, (uid, username or ""))

        conn.execute("""
            UPDATE users
            SET username = ?
            WHERE uid = ?
        """, (username or "", uid))

        conn.commit()
        conn.close()


def update_user(uid, **fields):
    allowed = {
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

    clean_fields = {
        key: value
        for key, value in fields.items()
        if key in allowed
    }

    if not clean_fields:
        return

    query = ", ".join(f"{key} = ?" for key in clean_fields)
    values = list(clean_fields.values()) + [uid]

    with db_lock:
        conn = get_db()
        conn.execute(
            f"UPDATE users SET {query} WHERE uid = ?",
            values
        )
        conn.commit()
        conn.close()


# =========================
# START / CANCEL
# =========================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    uid = message.from_user.id
    username = message.from_user.username or ""

    create_user(uid, username)

    update_user(
        uid,
        status="onboarding",
        step="name"
    )

    bot.send_message(
        uid,
        "Welcome!\n\nPlease enter your name:"
    )


@bot.message_handler(commands=["cancel"])
def cancel_cmd(message):
    uid = message.from_user.id

    if get_user(uid):
        update_user(
            uid,
            status="cancelled",
            step=""
        )

    bot.send_message(
        uid,
        "Process cancelled. Send /start to begin again."
    )


# =========================
# USER ONBOARDING
# =========================

@bot.message_handler(
    func=lambda message: (
        get_user(message.from_user.id) is not None
        and get_user(message.from_user.id)["status"] == "onboarding"
        and get_user(message.from_user.id)["step"] == "name"
    ),
    content_types=["text"]
)
def get_name(message):
    uid = message.from_user.id
    name = message.text.strip()

    if not name:
        bot.reply_to(message, "Please enter a valid name.")
        return

    update_user(
        uid,
        name=name,
        step="age"
    )

    bot.send_message(uid, "Enter your age:")


@bot.message_handler(
    func=lambda message: (
        get_user(message.from_user.id) is not None
        and get_user(message.from_user.id)["status"] == "onboarding"
        and get_user(message.from_user.id)["step"] == "age"
    ),
    content_types=["text"]
)
def get_age(message):
    uid = message.from_user.id

    try:
        age = int(message.text.strip())
    except ValueError:
        bot.reply_to(message, "Please enter your age as a number.")
        return

    if age < 18:
        bot.send_message(
            uid,
            "This service is restricted to adults. "
            "You cannot continue with this registration."
        )
        update_user(uid, status="restricted", step="")
        return

    update_user(
        uid,
        age=age,
        step="city"
    )

    bot.send_message(uid, "Enter your city:")


@bot.message_handler(
    func=lambda message: (
        get_user(message.from_user.id) is not None
        and get_user(message.from_user.id)["status"] == "onboarding"
        and get_user(message.from_user.id)["step"] == "city"
    ),
    content_types=["text"]
)
def get_city(message):
    uid = message.from_user.id

    update_user(
        uid,
        city=message.text.strip(),
        step="instagram"
    )

    bot.send_message(
        uid,
        "Enter your Instagram username:"
    )


@bot.message_handler(
    func=lambda message: (
        get_user(message.from_user.id) is not None
        and get_user(message.from_user.id)["status"] == "onboarding"
        and get_user(message.from_user.id)["step"] == "instagram"
    ),
    content_types=["text"]
)
def get_instagram(message):
    uid = message.from_user.id

    update_user(
        uid,
        insta=message.text.strip(),
        step="photo"
    )

    bot.send_message(
        uid,
        "Please send your photo."
    )


@bot.message_handler(
    func=lambda message: (
        get_user(message.from_user.id) is not None
        and get_user(message.from_user.id)["status"] == "onboarding"
        and get_user(message.from_user.id)["step"] == "photo"
    ),
    content_types=["photo"]
)
def get_photo(message):
    uid = message.from_user.id
    photo_id = message.photo[-1].file_id

    update_user(
        uid,
        photo_id=photo_id,
        step="consent"
    )

    bot.send_message(
        uid,
        "Please confirm that you are eligible to use this service.\n\n"
        "Type: <b>AGREE - 18+</b>"
    )


@bot.message_handler(
    func=lambda message: (
        get_user(message.from_user.id) is not None
        and get_user(message.from_user.id)["status"] == "onboarding"
        and get_user(message.from_user.id)["step"] == "consent"
    ),
    content_types=["text"]
)
def get_consent(message):
    uid = message.from_user.id

    if message.text.strip().upper() != "AGREE - 18+":
        bot.reply_to(
            message,
            "Please type exactly: AGREE - 18+"
        )
        return

    update_user(
        uid,
        status="pending",
        step=""
    )

    bot.send_message(
        uid,
        "Your registration has been submitted for admin approval."
    )

    user = get_user(uid)

    caption = (
        "<b>New Registration</b>\n\n"
        f"User ID: <code>{uid}</code>\n"
        f"Username: @{html.escape(user['username']) if user['username'] else 'N/A'}\n"
        f"Name: {html.escape(user['name'])}\n"
        f"Age: {user['age']}\n"
        f"City: {html.escape(user['city'])}\n"
        f"Instagram: {html.escape(user['insta'])}"
    )

    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton(
            "✅ Approve",
            callback_data=f"adm_app_{uid}"
        ),
        types.InlineKeyboardButton(
            "❌ Reject",
            callback_data=f"adm_rej_{uid}"
        )
    )

    if user["photo_id"]:
        bot.send_photo(
            ADMIN_ID,
            user["photo_id"],
            caption=caption,
            reply_markup=markup
        )
    else:
        bot.send_message(
            ADMIN_ID,
            caption,
            reply_markup=markup
        )


# =========================
# ADMIN APPROVAL
# =========================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("adm_")
)
def admin_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(
            call.id,
            "Not authorized.",
            show_alert=True
        )
        return

    parts = call.data.split("_")

    if len(parts) != 3:
        bot.answer_callback_query(call.id, "Invalid request.")
        return

    action = parts[1]

    try:
        uid = int(parts[2])
    except ValueError:
        bot.answer_callback_query(call.id, "Invalid user ID.")
        return

    if action == "app":
        update_user(
            uid,
            status="approved"
        )

        try:
            bot.send_message(
                uid,
                "✅ Your registration has been approved."
            )
        except Exception:
            pass

        bot.answer_callback_query(
            call.id,
            "Approved."
        )

    elif action == "rej":
        update_user(
            uid,
            status="rejected"
        )

        try:
            bot.send_message(
                uid,
                "❌ Your registration was rejected."
            )
        except Exception:
            pass

        bot.answer_callback_query(
            call.id,
            "Rejected."
        )


# =========================
# POINTS & LEADERBOARD
# =========================

def change_points(uid, amount):
    with db_lock:
        conn = get_db()
        row = conn.execute(
            "SELECT points FROM users WHERE uid = ?",
            (uid,)
        ).fetchone()

        if not row:
            conn.close()
            return False

        new_points = row["points"] + amount
        if new_points < 0:
            conn.close()
            return False

        conn.execute(
            "UPDATE users SET points = ? WHERE uid = ?",
            (new_points, uid)
        )
        conn.commit()
        conn.close()
        return True


@bot.message_handler(commands=["points"])
def points_cmd(message):
    user = get_user(message.from_user.id)
    if not user:
        bot.reply_to(message, "Send /start first.")
        return

    bot.reply_to(
        message,
        f"⭐ Your points: <b>{user['points']}</b>"
    )


@bot.message_handler(commands=["leaderboard"])
def leaderboard_cmd(message):
    with db_lock:
        conn = get_db()
        rows = conn.execute("""
            SELECT username, points
            FROM users
            WHERE status = 'approved'
            ORDER BY points DESC
            LIMIT 10
        """).fetchall()
        conn.close()

    if not rows:
        bot.send_message(
            message.chat.id,
            "No approved users yet."
        )
        return

    text = "<b>🏆 Leaderboard</b>\n\n"
    for index, row in enumerate(rows, start=1):
        username = (
            f"@{html.escape(row['username'])}"
            if row["username"]
            else "User"
        )
        text += f"{index}. {username} — <b>{row['points']}</b>\n"

    bot.send_message(message.chat.id, text)


# =========================
# ADMIN POINT COMMANDS
# =========================

@bot.message_handler(commands=["addpoints"])
def addpoints_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "Usage: /addpoints USER_ID POINTS")
        return

    try:
        uid = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        bot.reply_to(message, "Invalid numbers.")
        return

    if amount <= 0:
        bot.reply_to(message, "Points must be positive.")
        return

    if not change_points(uid, amount):
        bot.reply_to(message, "User not found.")
        return

    bot.reply_to(message, f"✅ Added {amount} points to {uid}.")
    try:
        bot.send_message(uid, f"⭐ You received <b>{amount}</b> points.")
    except Exception:
        pass


@bot.message_handler(commands=["setpoints"])
def setpoints_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "Usage: /setpoints USER_ID POINTS")
        return

    try:
        uid = int(parts[1])
        points = int(parts[2])
    except ValueError:
        bot.reply_to(message, "Invalid numbers.")
        return

    if points < 0:
        bot.reply_to(message, "Points cannot be negative.")
        return

    with db_lock:
        conn = get_db()
        cur = conn.execute(
            "UPDATE users SET points = ? WHERE uid = ?",
            (points, uid)
        )
        conn.commit()
        conn.close()

    if cur.rowcount == 0:
        bot.reply_to(message, "User not found.")
        return

    bot.reply_to(message, f"✅ Points set to {points} for {uid}.")


# =========================
# ERROR-SAFE POLLING
# =========================

def run_bot():
    while True:
        try:
            print("Bot polling started...")
            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                skip_pending=True
            )
        except Exception as exc:
            print("Polling error:", repr(exc))
            time.sleep(5)


# =========================
# MAIN
# =========================

def main():
    init_db()

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )
    flask_thread.start()

    run_bot()


if __name__ == "__main__":
    main()
