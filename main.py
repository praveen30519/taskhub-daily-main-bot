import os
import json
import threading
import time
from flask import Flask
import telebot
from telebot import types

# 1. Background Web Server (Render Port Timeout Fix)
app = Flask(__name__)

@app.route('/')
def home():
    return "CreatorDesk Daily Bot is Running 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# 2. Bot Credentials
BOT_TOKEN = "8774903120:AAGCXoaMVckLVRbtKvHjHqAs2XT5gyXFBN4"

ADMIN_ID = 2016851713

bot = telebot.TeleBot(BOT_TOKEN)
DATA_FILE = "creatordesk_main_db.json"

# Purana Livegram Webhook saaf karna
try:
    bot.remove_webhook()
    print("Purana webhook saaf kar diya gaya!")
except Exception as e:
    print(f"Webhook warning: {e}")

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

db = load_data()

def init_user(uid, username):
    s_uid = str(uid)
    if s_uid not in db:
        db[s_uid] = {
            "username": f"@{username}" if username else "Creator",
            "points": 0,
            "status": "unverified",
            "slot": "Not Set",
            "step": "none",
            "form": {}
        }
        save_data(db)

def get_dashboard_menu(uid):
    s_uid = str(uid)
    pts = db[s_uid].get("points", 0)
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton(f"💰 Balance: {pts} Pts", callback_data="btn_points")
    btn2 = types.InlineKeyboardButton("⏰ Change Time Slot", callback_data="btn_slot")
    btn3 = types.InlineKeyboardButton("🏆 Leaderboard", callback_data="btn_leaderboard")
    btn4 = types.InlineKeyboardButton("🎁 Claim Amazon Voucher", callback_data="btn_claim")
    markup.add(btn1, btn2, btn3, btn4)
    return markup

# --- START COMMAND ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = str(message.from_user.id)
    init_user(uid, message.from_user.username)
    
    status_text = "Active" if db[uid]["status"] == "approved" else "Pending Verification"
    pts = db[uid].get("points", 0)

    welcome_text = (
        f"👋 *Welcome to CreatorDesk Portal, {message.from_user.first_name}!* 🌟\n\n"
        "Aapka account successfully initialize ho chuka hai.\n\n"
        "📌 *YOUR CREATOR PROFILE*\n"
        f"• **Portal Status:** `{status_text}`\n"
        f"• **Worker Tag:** `{uid}`\n"
        f"• **Live Balance:** `{pts} Points`\n"
        "_(Aage kisi bhi task proof ya query ke liye apna Worker Tag mention karein)_\n\n"
        "📋 *ONBOARDING VERIFICATION*\n"
        "Campaign tasks aur Welcome Bonus unlock karne ke liye verification mandatory hai.\n\n"
        "👉 Shuru karne ke liye niche button dabayein:"
    )

    markup = types.InlineKeyboardMarkup()
    if db[uid]["status"] != "approved":
        markup.add(types.InlineKeyboardButton("📝 Start Verification (18+)", callback_data="start_onboarding"))
    else:
        markup = get_dashboard_menu(uid)

    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown", reply_markup=markup)

# --- START ONBOARDING STEPS ---
@bot.callback_query_handler(func=lambda call: call.data == "start_onboarding")
def start_steps(call):
    uid = str(call.from_user.id)
    init_user(uid, call.from_user.username)
    db[uid]["step"] = "step_name"
    db[uid]["form"] = {}
    save_data(db)
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "📋 *Step 1/6: Full Legal Name*\n\nApna poora legal naam likhkar bhejein:",
        parse_mode="Markdown"
    )

# --- USER MESSAGE & STEP CONTROLLER ---
@bot.message_handler(func=lambda m: True, content_types=['text', 'photo'])
def handle_all_messages(message):
    uid = str(message.from_user.id)
    init_user(uid, message.from_user.username)

    # Admin Direct Anonymous Reply
    if message.from_user.id == ADMIN_ID:
        if message.reply_to_message and "Worker Tag: `" in (message.reply_to_message.text or message.reply_to_message.caption or ""):
            try:
                full_text = message.reply_to_message.text or message.reply_to_message.caption
                target_id = int(full_text.split("Worker Tag: `")[1].split("`")[0])
                bot.send_message(
                    target_id,
                    f"💬 *Support Desk Reply:*\n\n{message.text}\n\n_(💰 Live Balance: {db[str(target_id)].get('points', 0)} Pts)_",
                    parse_mode="Markdown"
                )
                bot.reply_to(message, "✅ User ko reply bhej diya gaya hai.")
            except Exception as e:
                bot.reply_to(message, f"❌ Error: {e}")
        return

    current_step = db[uid].get("step", "none")

    if current_step == "step_name":
        if message.content_type != 'text':
            bot.reply_to(message, "❌ Kripya text me apna naam likhein.")
            return
        db[uid]["form"]["name"] = message.text
        db[uid]["step"] = "step_age"
        save_data(db)
        bot.send_message(message.chat.id, "📋 *Step 2/6: Age (18+ only)*\n\nApni umar (Age) number me enter karein:", parse_mode="Markdown")
        return

    elif current_step == "step_age":
        if not message.text or not message.text.strip().isdigit() or int(message.text.strip()) < 18:
            bot.reply_to(message, "⚠️ Is platform ke liye 18+ hona anivarya hai. Kripya valid 18+ age enter karein:")
            return
        db[uid]["form"]["age"] = message.text.strip()
        db[uid]["step"] = "step_city"
        save_data(db)
        bot.send_message(message.chat.id, "📋 *Step 3/6: Current City*\n\nApna current shehar (City) likhkar bhejein:", parse_mode="Markdown")
        return

    elif current_step == "step_city":
        if message.content_type != 'text':
            bot.reply_to(message, "❌ Kripya city ka naam likhein.")
            return
        db[uid]["form"]["city"] = message.text
        db[uid]["step"] = "step_insta"
        save_data(db)
        bot.send_message(message.chat.id, "📋 *Step 4/6: Active Instagram Handle*\n\nApna Instagram username (e.g. `@username`) bhejein:", parse_mode="Markdown")
        return

    elif current_step == "step_insta":
        if message.content_type != 'text':
            bot.reply_to(message, "❌ Kripya apna Instagram handle likhein.")
            return
        db[uid]["form"]["insta"] = message.text
        db[uid]["step"] = "step_photo"
        save_data(db)
        bot.send_message(
            message.chat.id,
            "📋 *Step 5/6: 4/5 Pose Photo*\n\n"
            "📸 Kripya apni clear *Pose Photo* upload karein.\n"
            "⚠️ *Dhyan rahe: Jab tak aap photo upload nahi karenge, verification process aage nahi badhega.*",
            parse_mode="Markdown"
        )
        return

    elif current_step == "step_photo":
        if message.content_type != 'photo':
            bot.reply_to(message, "🚫 *Photo zaroori hai!* Kripya apni photo upload karein, text allow nahi hai.")
            return
        db[uid]["form"]["photo_id"] = message.photo[-1].file_id
        db[uid]["step"] = "step_consent"
        save_data(db)
        bot.send_message(
            message.chat.id,
            "📋 *Step 6/6: 🔞 ELIGIBILITY & CONSENT*\n\n"
            "Is platform ke tasks aur guidelines ke mutabik aapka 18+ hona anivarya hai.\n\n"
            "Confirmation ke liye neeche diya gaya exact text likhkar bhejein:\n"
            "👉 `AGREE - 18+`",
            parse_mode="Markdown"
        )
        return

    elif current_step == "step_consent":
        if not message.text or message.text.strip().upper() != "AGREE - 18+":
            bot.reply_to(message, "⚠️ Confirmation ke liye exactly `AGREE - 18+` likhkar send karein.")
            return
        
        db[uid]["step"] = "completed_pending"
        save_data(db)

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Approve Profile", callback_data=f"adm_app_{uid}"),
            types.InlineKeyboardButton("❌ Reject Profile", callback_data=f"adm_rej_{uid}")
        )
        
        caption_details = (
            "📋 *NEW ONBOARDING SUBMISSION*\n"
            f"• **Name:** {db[uid]['form'].get('name')}\n"
            f"• **Age:** {db[uid]['form'].get('age')}\n"
            f"• **City:** {db[uid]['form'].get('city')}\n"
            f"• **Instagram:** {db[uid]['form'].get('insta')}\n"
            f"• **Consent:** Confirmed (18+)\n"
            f"• **Worker Tag:** `{uid}`\n"
            f"• **Telegram User:** {db[uid].get('username')}"
        )
        
        bot.send_photo(ADMIN_ID, db[uid]["form"]["photo_id"], caption=caption_details, parse_mode="Markdown", reply_markup=markup)

        bot.send_message(
            message.chat.id,
            "✅ *Details Successfully Submitted!*\n\n"
            "⚠️ **Verification Guidelines:**\n"
            "• Details submit hote hi profile review team verify karegi.\n"
            "• Approval ke baad aapka ₹250 Welcome Bonus credit ho jayega.\n"
            "• Payouts instant Amazon Pay Vouchers ke through release hote hain.\n\n"
            "Kripya approval ka intezar karein.",
            parse_mode="Markdown"
        )
        return

    pts = db[uid].get("points", 0)
    admin_box = (
        f"📩 *Incoming Message*\n"
        f"👤 From: {db[uid].get('username')}\n"
        f"🆔 Worker Tag: `{uid}`\n"
        f"💰 Live Balance: `{pts} Pts`\n\n"
        f"💬 {message.text if message.content_type == 'text' else '[Photo/File Sent]'}"
    )
    bot.send_message(ADMIN_ID, admin_box, parse_mode="Markdown")
    bot.reply_to(message, f"✅ Message admin team ko bhej diya gaya hai.\n_(Aapka Live Balance: {pts} Pts)_")

# --- ADMIN APPROVE/REJECT BUTTONS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("adm_"))
def admin_verification_decision(call):
    if call.from_user.id != ADMIN_ID:
        return
    bot.answer_callback_query(call.id)
    action, target_uid = call.data.split("_")[1], call.data.split("_")[2]

    if action == "app":
        db[target_uid]["status"] = "approved"
        db[target_uid]["points"] = db[target_uid].get("points", 0) + 50
        save_data(db)
        
        bot.send_message(
            int(target_uid),
            "🎉 *Badhai ho! Aapki Creator Profile APPROVE ho gayi hai!*\n\n"
            "Aapka Welcome Bonus credit ho chuka hai. Niche diye gaye menu se time slot aur details manage karein.",
            parse_mode="Markdown",
            reply_markup=get_dashboard_menu(target_uid)
        )
        bot.edit_message_caption("✅ *Profile Approved & Bonus Credited*", chat_id=ADMIN_ID, message_id=call.message.message_id)

    elif action == "rej":
        db[target_uid]["status"] = "unverified"
        db[target_uid]["step"] = "none"
        save_data(db)
        
        bot.send_message(
            int(target_uid),
            "❌ *Verification Update:*\n\nAapki profile review me reject ho gayi hai (photo clear na hone ya galat details ke karan).\n\nDobara form bharne ke liye `/start` karein.",
            parse_mode="Markdown"
        )
        bot.edit_message_caption("❌ *Profile Rejected*", chat_id=ADMIN_ID, message_id=call.message.message_id)

# --- TIME SLOTS (2 Options) ---
@bot.callback_query_handler(func=lambda call: call.data == "btn_slot")
def select_slot(call):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_noon = types.InlineKeyboardButton("☀️ Dopahar: 01:00 PM - 03:00 PM", callback_data="slot_01to03pm")
    btn_night = types.InlineKeyboardButton("🌙 Raat: 09:00 PM - 12:00 AM", callback_data="slot_09to12am")
    markup.add(btn_noon, btn_night)
    bot.send_message(call.message.chat.id, "⏰ *Apna working time slot chunein:*", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("slot_"))
def save_slot(call):
    uid = str(call.from_user.id)
    slot_mapping = {
        "slot_01to03pm": "01:00 PM - 03:00 PM (Dopahar)",
        "slot_09to12am": "09:00 PM - 12:00 AM (Raat)"
    }
    chosen_slot = slot_mapping.get(call.data, "09:00 PM - 12:00 AM")
    db[uid]["slot"] = chosen_slot
    save_data(db)
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, f"✅ Aapka Time Slot successfully set ho gaya hai:\n📍 *{chosen_slot}*", parse_mode="Markdown")
    bot.send_message(ADMIN_ID, f"⏰ *Slot Update:*\nWorker Tag: `{uid}` ({db[uid].get('username')}) ne slot `{chosen_slot}` select kiya.", parse_mode="Markdown")

# --- POINTS & REWARDS DASHBOARD ---
@bot.callback_query_handler(func=lambda call: call.data == "btn_points")
def view_points(call):
    uid = str(call.from_user.id)
    pts = db[uid].get("points", 0)
    slot = db[uid].get("slot", "Not Set")
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        f"📊 *YOUR CREATOR WALLET*\n\n"
        f"• **Current Points:** `{pts}` / 100\n"
        f"• **Active Slot:** {slot}\n"
        f"• **Status:** {db[uid].get('status', 'Pending').capitalize()}\n\n"
        "_(100 Points hote hi aap Amazon Pay Gift Card claim kar sakte hain)_",
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data == "btn_leaderboard")
def view_leaderboard(call):
    bot.answer_callback_query(call.id)
    sorted_users = sorted(db.items(), key=lambda x: x[1].get("points", 0), reverse=True)[:10]
    board = "🏆 *Top Creators Leaderboard:*\n\n"
    for i, (k, v) in enumerate(sorted_users, 1):
        board += f"{i}. {v.get('username', 'Creator')} — `{v.get('points', 0)} Pts`\n"
    bot.send_message(call.message.chat.id, board, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "btn_claim")
def claim_reward(call):
    uid = str(call.from_user.id)
    pts = db[uid].get("points", 0)
    bot.answer_callback_query(call.id)

    if pts < 100:
        bot.send_message(
            call.message.chat.id,
            f"❌ *Claim Not Allowed!*\n\nAapke wallet me abhi sirf *{pts} Points* hain. Minimum *100 Points* hone ke baad hi Amazon Gift Card release hota hai.",
            parse_mode="Markdown"
        )
    else:
        bot.send_message(call.message.chat.id, "✅ *Redeem Request Sent!*\n\nAdmin verification ke baad Amazon Pay Voucher code yahan deliver karenge.", parse_mode="Markdown")
        bot.send_message(
            ADMIN_ID,
            f"🎁 *New Voucher Claim Request!*\n"
            f"• Worker Tag: `{uid}` ({db[uid].get('username')})\n"
            f"• Points: `{pts}`\n\n"
            f"Voucher code bhejne ke liye command use karein:\n"
            f"`/sendvoucher {uid} AMAZON_CODE_HERE`",
            parse_mode="Markdown"
        )

# --- ADMIN COMMANDS: SET/ADD POINTS & SEND VOUCHER ---
@bot.message_handler(commands=['setpoints'])
def set_points_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, target_uid, pts = message.text.split()
        target_uid = str(target_uid)
        pts = int(pts)
        if target_uid in db:
            db[target_uid]["points"] = pts
            save_data(db)
            bot.reply_to(message, f"✅ Worker `{target_uid}` ke points `{pts}` set ho gaye.")
            bot.send_message(int(target_uid), f"🔔 *Wallet Updated:* Aapka balance ab `{pts} Points` ho chuka hai.", parse_mode="Markdown")
    except:
        bot.reply_to(message, "Usage: `/setpoints <worker_tag> <points>`")

@bot.message_handler(commands=['addpoints'])
def add_points_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, target_uid, pts = message.text.split()
        target_uid = str(target_uid)
        pts = int(pts)
        if target_uid in db:
            db[target_uid]["points"] = db[target_uid].get("points", 0) + pts
            save_data(db)
            bot.reply_to(message, f"✅ Worker `{target_uid}` me +{pts} add ho gaye. (Total: {db[target_uid]['points']})")
            bot.send_message(int(target_uid), f"🎁 *Points Credited:* +{pts} Points add hue!\nTotal Balance: `{db[target_uid]['points']}` Pts", parse_mode="Markdown")
    except:
        bot.reply_to(message, "Usage: `/addpoints <worker_tag> <points>`")

@bot.message_handler(commands=['sendvoucher'])
def send_voucher_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.split(maxsplit=2)
        target_uid = str(parts[1])
        voucher_code = parts[2]
        
        if target_uid in db:
            db[target_uid]["points"] = max(0, db[target_uid].get("points", 0) - 100)
            save_data(db)
            bot.send_message(
                int(target_uid),
                f"🎉 *Badhai ho! Aapka Amazon Pay Gift Card aa gaya hai:*\n\n"
                f"🏷️ **Voucher Code:** `{voucher_code}`\n\n"
                f"Aap ise apne Amazon App me jakar *Amazon Pay > Add Gift Card* me add kar sakte hain.\n"
                f"_(Bacha hua Balance: {db[target_uid]['points']} Pts)_",
                parse_mode="Markdown"
            )
            bot.reply_to(message, f"✅ Voucher code safely bhej diya gaya aur 100 points deduct ho gaye.")
    except:
        bot.reply_to(message, "Usage: `/sendvoucher <worker_tag> <VOUCHER_CODE>`")

# Flask Server Thread
threading.Thread(target=run_web).start()

# Polling Loop
print("CreatorDesk Bot Polling Running 24/7...")
while True:
    try:
        bot.infinity_polling(timeout=20, long_polling_timeout=10)
    except Exception as e:
        print(f"Reconnect error: {e}")
        time.sleep(3)
      
