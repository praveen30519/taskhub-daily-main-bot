import os
import html
import json
import sqlite3
import threading
import time

from flask import Flask
import telebot
from telebot import types


# =========================================================
# CONFIGURATION
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.environ.get("ADMIN_ID", "2016851713").strip()
DB_PATH = os.environ.get("DB_PATH", "creator_bot.db")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN environment variable is missing. "
        "Add BOT_TOKEN in your hosting environment."
    )

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except (TypeError, ValueError):
    raise RuntimeError("ADMIN_ID must be a valid numeric Telegram user ID.")


bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML"
)

app = Flask(__name__)
db_lock = threading.RLock()


# =========================================================
# FLASK SERVER (Render Keep-Alive)
# =========================================================

@app.route("/")
def home():
    return "CreatorDesk Bot is running!"


@app.route("/health")
def health():
    return "OK", 200


def run_flask():
    try:
        port = int(os.environ.get("PORT", "10000"))
        app.run(
            host="0.0.0.0",
            port=port,
            debug=False,
            use_reloader=False,
            threaded=True
        )
    except Exception as exc:
        print("Flask error:", repr(exc))


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def column_exists(conn, table_name, column_name):
    rows = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()
    return any(row["name"] == column_name for row in rows)


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
                photo_ids TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        required_columns = {
            "username": "TEXT DEFAULT ''",
            "points": "INTEGER DEFAULT 0",
            "status": "TEXT DEFAULT 'new'",
            "slot": "TEXT DEFAULT ''",
            "step": "TEXT DEFAULT ''",
            "name": "TEXT DEFAULT ''",
            "age": "INTEGER DEFAULT 0",
            "city": "TEXT DEFAULT ''",
            "insta": "TEXT DEFAULT ''",
            "photo_ids": "TEXT DEFAULT '[]'",
        }

        for column, definition in required_columns.items():
            if not column_exists(conn, "users", column):
                try:
                    conn.execute(
                        f"ALTER TABLE users ADD COLUMN {column} {definition}"
                    )
                except sqlite3.OperationalError as exc:
                    print(f"Could not add column {column}: {exc}")

        conn.execute("""
            UPDATE users
            SET photo_ids = '[]'
            WHERE photo_ids IS NULL OR TRIM(photo_ids) = ''
        """)

        conn.commit()
        conn.close()

    print("Database initialized successfully.")


def get_user(uid):
    with db_lock:
        conn = get_db()
        try:
            return conn.execute(
                "SELECT * FROM users WHERE uid = ?",
                (uid,)
            ).fetchone()
        finally:
            conn.close()


def create_user(uid, username):
    with db_lock:
        conn = get_db()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO users
                (uid, username, status, step, photo_ids)
                VALUES (?, ?, 'new', '', '[]')
            """, (uid, username or ""))

            conn.execute("""
                UPDATE users
                SET username = ?
                WHERE uid = ?
            """, (username or "", uid))

            conn.commit()
        finally:
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
        "photo_ids",
    }

    clean_fields = {
        key: value
        for key, value in fields.items()
        if key in allowed
    }

    if not clean_fields:
        return False

    query = ", ".join(f"{key} = ?" for key in clean_fields)
    values = list(clean_fields.values())
    values.append(uid)

    with db_lock:
        conn = get_db()
        try:
            cursor = conn.execute(
                f"UPDATE users SET {query} WHERE uid = ?",
                values
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


# =========================================================
# PHOTO JSON HELPERS
# =========================================================

def load_photos(user):
    if not user:
        return []
    raw = user["photo_ids"]
    if not raw:
        return []
    try:
        photos = json.loads(raw)
        if not isinstance(photos, list):
            return []
        return [str(photo) for photo in photos if photo]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def save_photos(uid, photos):
    return update_user(
        uid,
        photo_ids=json.dumps(photos, ensure_ascii=False)
    )


# =========================================================
# /START & CANCEL
# =========================================================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    uid = message.from_user.id
    username = message.from_user.username or ""

    try:
        create_user(uid, username)
        user = get_user(uid)
        points = user["points"] or 0 if user else 0

        welcome_text = (
            "👋 <b>Welcome to CreatorDesk Portal!</b> 🌟\n\n"
            "Aapka account successfully initialize ho chuka hai.\n\n"
            "📌 <b>YOUR CREATOR PROFILE</b>\n"
            "• Portal Status: <i>Pending Verification</i>\n"
            f"• Worker Tag: <code>{uid}</code>\n"
            f"• Live Balance: {points} Points\n"
            "<i>(Aage kisi bhi task proof ya query ke liye apna Worker Tag mention karein)</i>\n\n"
            "📋 <b>ONBOARDING VERIFICATION</b>\n"
            "Campaign tasks aur Welcome Bonus unlock karne ke liye verification mandatory hai.\n\n"
            "👉 <b>Shuru karne ke liye niche button dabayein:</b>"
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "📝 Start Verification (18+)",
                callback_data="start_onboarding"
            )
        )

        bot.send_message(uid, welcome_text, reply_markup=markup)

    except Exception as exc:
        print("Start command error:", repr(exc))
        bot.send_message(uid, "⚠️ Temporary error. Please try /start again.")


@bot.message_handler(commands=["cancel"])
def cancel_cmd(message):
    uid = message.from_user.id
    if get_user(uid):
        update_user(uid, status="cancelled", step="", photo_ids="[]")
    bot.send_message(uid, "Process cancel ho gaya hai. Dobara shuru karne ke liye /start karein.")


# =========================================================
# ONBOARDING FLOW
# =========================================================

@bot.callback_query_handler(func=lambda call: call.data == "start_onboarding")
def handle_start(call):
    uid = call.from_user.id
    try:
        user = get_user(uid)
        if not user:
            create_user(uid, call.from_user.username or "")

        update_user(uid, status="onboarding", step="name", photo_ids="[]")
        bot.answer_callback_query(call.id)
        bot.send_message(
            uid,
            "📝 <b>Question 1/4:</b>\nKripya apna poora <b>Naam (Name)</b> likhein:"
        )
    except Exception as exc:
        print("Start onboarding error:", repr(exc))


@bot.message_handler(
    func=lambda m: (
        get_user(m.from_user.id) is not None
        and get_user(m.from_user.id)["status"] == "onboarding"
        and get_user(m.from_user.id)["step"] == "name"
    ),
    content_types=["text"]
)
def get_name(message):
    uid = message.from_user.id
    name = (message.text or "").strip()
    if not name:
        bot.reply_to(message, "Kripya sahi naam likhein.")
        return

    update_user(uid, name=name, step="age")
    bot.send_message(
        uid,
        "🎂 <b>Question 2/4:</b>\nApni <b>Umar (Age)</b> number me darj karein:"
    )


@bot.message_handler(
    func=lambda m: (
        get_user(m.from_user.id) is not None
        and get_user(m.from_user.id)["status"] == "onboarding"
        and get_user(m.from_user.id)["step"] == "age"
    ),
    content_types=["text"]
)
def get_age(message):
    uid = message.from_user.id
    try:
        age = int((message.text or "").strip())
    except (ValueError, TypeError):
        bot.reply_to(message, "Kripya umar sirf number me likhein (jaise 22).")
        return

    if age < 18:
        update_user(uid, status="restricted", step="")
        bot.send_message(uid, "⚠️ Ye service kewal 18+ ke liye hai. Aap register nahi kar sakte.")
        return

    update_user(uid, age=age, step="city")
    bot.send_message(
        uid,
        "📍 <b>Question 3/4:</b>\nApne <b>Shahar (City)</b> ka naam likhein:"
    )


@bot.message_handler(
    func=lambda m: (
        get_user(m.from_user.id) is not None
        and get_user(m.from_user.id)["status"] == "onboarding"
        and get_user(m.from_user.id)["step"] == "city"
    ),
    content_types=["text"]
)
def get_city(message):
    uid = message.from_user.id
    city = (message.text or "").strip()
    if not city:
        bot.reply_to(message, "Kripya city ka naam likhein.")
        return

    update_user(uid, city=city, step="instagram")
    bot.send_message(
        uid,
        "📸 <b>Question 4/4:</b>\nApna <b>Instagram username</b> likhein:"
    )


@bot.message_handler(
    func=lambda m: (
        get_user(m.from_user.id) is not None
        and get_user(m.from_user.id)["status"] == "onboarding"
        and get_user(m.from_user.id)["step"] == "instagram"
    ),
    content_types=["text"]
)
def get_instagram(message):
    uid = message.from_user.id
    insta = (message.text or "").strip()
    if not insta:
        bot.reply_to(message, "Kripya Instagram username likhein.")
        return

    update_user(uid, insta=insta, step="photo_1", photo_ids="[]")
    bot.send_message(
        uid,
        "🖼️ <b>Photo Verification (Total 4 Photos)</b>\n\n"
        "Kripya apni <b>Pehli Photo (1/4)</b> upload karein:"
    )


# =========================================================
# 4 PHOTOS HANDLER
# =========================================================

@bot.message_handler(
    func=lambda m: (
        get_user(m.from_user.id) is not None
        and get_user(m.from_user.id)["step"].startswith("photo_")
    ),
    content_types=["photo"]
)
def handle_photos(message):
    uid = message.from_user.id
    user = get_user(uid)
    if not user:
        return

    step = user["step"]
    if step not in {"photo_1", "photo_2", "photo_3", "photo_4"}:
        return

    photos = load_photos(user)
    if len(photos) >= 4:
        update_user(uid, step="consent")
        return

    photo_id = message.photo[-1].file_id
    photos.append(photo_id)
    save_photos(uid, photos)

    if step == "photo_1":
        update_user(uid, step="photo_2")
        bot.send_message(uid, "✅ Pehli photo save ho gayi.\n\nAb apni <b>Dusri Photo (2/4)</b> upload karein:")
    elif step == "photo_2":
        update_user(uid, step="photo_3")
        bot.send_message(uid, "✅ Dusri photo save ho gayi.\n\nAb apni <b>Teesri Photo (3/4)</b> upload karein:")
    elif step == "photo_3":
        update_user(uid, step="photo_4")
        bot.send_message(uid, "✅ Teesri photo save ho gayi.\n\nAb apni <b>Aakhri Photo (4/4)</b> upload karein:")
    elif step == "photo_4":
        update_user(uid, step="consent")
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "✅ I AGREE (18+)",
                callback_data="agree_consent"
            )
        )
        bot.send_message(
            uid,
            "🎉 <b>Sabhi 4 Photos receive ho chuki hain!</b>\n\n"
            "Final Step: Kripya confirm karein ki aap 18+ hain aur rules agree karte hain.\n\n"
            "Niche button dabayein:",
            reply_markup=markup
        )


# =========================================================
# CONSENT & SUBMISSION
# =========================================================

@bot.callback_query_handler(func=lambda call: call.data == "agree_consent")
def handle_agree_consent(call):
    uid = call.from_user.id
    try:
        user = get_user(uid)
        if not user or user["step"] != "consent":
            bot.answer_callback_query(call.id, "Invalid action.", show_alert=True)
            return

        photos = load_photos(user)
        if len(photos) != 4:
            bot.answer_callback_query(call.id, "Please upload 4 photos first.", show_alert=True)
            return

        update_user(uid, status="pending", step="")
        bot.answer_callback_query(call.id, "Submitted!")
        bot.send_message(
            uid,
            "✅ <b>Aapka profile verification ke liye submit ho gaya hai!</b>\n\n"
            "Admin review ke baad approve karega."
        )

        user = get_user(uid)
        caption = (
            "<b>New Profile Verification Request</b>\n\n"
            f"User ID: <code>{uid}</code>\n"
            f"Username: @{html.escape(user['username']) if user['username'] else 'N/A'}\n"
            f"Name: {html.escape(user['name'])}\n"
            f"Age: {user['age']}\n"
            f"City: {html.escape(user['city'])}\n"
            f"Instagram: {html.escape(user['insta'])}\n"
            f"Total Photos: {len(photos)}"
        )

        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_{uid}"),
            types.InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_{uid}")
        )

        # Media album bhejein admin ko
        media = [types.InputMediaPhoto(photo_id) for photo_id in photos]
        try:
            bot.send_media_group(ADMIN_ID, media)
        except Exception as exc:
            print("Admin media group error:", repr(exc))

        bot.send_message(ADMIN_ID, caption, reply_markup=markup)

    except Exception as exc:
        print("Consent submission error:", repr(exc))


# =========================================================
# ADMIN APPROVAL / REJECTION
# =========================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("adm_"))
def admin_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Unauthorized.", show_alert=True)
        return

    parts = call.data.split("_")
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "Invalid action.")
        return

    action, uid_str = parts[1], parts[2]
    try:
        uid = int(uid_str)
    except ValueError:
        bot.answer_callback_query(call.id, "Invalid user ID.")
        return

    if action == "app":
        update_user(uid, status="approved")
        try:
            bot.send_message(uid, "🎉 <b>Badhai ho!</b> Aapka verification approve ho gaya hai.")
        except Exception:
            pass
        bot.answer_callback_query(call.id, "Approved!")

    elif action == "rej":
        update_user(uid, status="rejected")
        try:
            bot.send_message(uid, "❌ Aapka verification reject kar diya gaya hai.")
        except Exception:
            pass
        bot.answer_callback_query(call.id, "Rejected!")


# =========================================================
# POINTS COMMAND
# =========================================================

@bot.message_handler(commands=["points"])
def points_cmd(message):
    user = get_user(message.from_user.id)
    if not user:
        bot.reply_to(message, "Pehle /start karein.")
        return
    bot.reply_to(message, f"⭐ Aapke points: <b>{user['points']}</b>")


# =========================================================
# MAIN & BOT RUNNER
# =========================================================

def run_bot():
    while True:
        try:
            print("Bot polling started...")
            bot.infinity_polling(timeout=30, long_polling_timeout=30, skip_pending=True)
        except Exception as exc:
            print("Polling error:", repr(exc))
            time.sleep(5)


def main():
    init_db()
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    run_bot()


if __name__ == "__main__":
    main()
        
