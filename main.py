# ===== KEEP ALIVE SETUP =====
from flask import Flask
from threading import Thread
import logging
logging.basicConfig(
    filename='bot_errors.log',
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

import os
import time

TOKEN = os.environ["BOT_TOKEN"]
DEV_MODE = os.environ.get("DEV_MODE", "False") == "True"
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

app = Flask(__name__)

@app.route('/')
def home():
    return "EarningClubBot is running!"

@app.route('/health')
def health():
    return {"status": "healthy", "timestamp": time.time()}

@app.route('/status')
def status():
    return {"bot": "EarningClubBot", "status": "active", "uptime": time.time()}

@app.route('/heartbeat')
def heartbeat():
    """Simple heartbeat endpoint for monitoring"""
    return {"alive": True, "timestamp": time.time(), "message": "Bot is running"}

@app.route('/ping')
def ping():
    """Simple ping endpoint"""
    return "pong"

def run():
    retry_count = 0
    max_retries = 5
    port = int(os.environ.get('PORT', 10000))  # Use Render's default port

    while retry_count < max_retries:
        try:
            logging.info(f"🌐 Starting Flask server on port {port} (attempt {retry_count + 1})...")
            app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)
            break
        except Exception as e:
            retry_count += 1
            logging.info(f"❌ Flask server error (attempt {retry_count}): {e}")
            if retry_count < max_retries:
                wait_time = min(retry_count * 2, 30)
                logging.info(f"🔄 Restarting server in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logging.info("❌ Max retries reached. Keep-alive server failed to start.")
                break

def keep_alive():
    # Start keep-alive server
    t = Thread(target=run)
    t.daemon = True
    t.start()
    logging.info("✅ Keep-alive server thread started")

    # Add a health check thread to restart if needed
    def health_monitor():
        import requests
        while True:
            try:
                time.sleep(300)  # Check every 5 minutes
                port = int(os.environ.get('PORT', 8080))
                response = requests.get(f'http://localhost:{port}/health', timeout=10)
                if response.status_code != 200:
                    logging.info("⚠️ Health check failed, restarting keep-alive...")
                    # Restart the server thread if it died
                    if not t.is_alive():
                        new_t = Thread(target=run)
                        new_t.daemon = True
                        new_t.start()
            except Exception as e:
                logging.info(f"⚠️ Health monitor error: {e}")

    monitor_t = Thread(target=health_monitor)
    monitor_t.daemon = True
    monitor_t.start()

keep_alive()

# ===== BOT IMPORTS =====
import requests
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    MenuButton,
    MenuButtonCommands
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ===== DATABASE SETUP =====
import sqlite3
import json
from contextlib import contextmanager

@contextmanager
def db_connection():
    """Database connection context manager with proper error handling"""
    conn = sqlite3.connect('bot_data.db', timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # Enable column access by name
    try:
        yield conn
    except Exception as e:
        conn.rollback()
        logging.error(f"Database error: {e}")
        raise
    finally:
        conn.close()

def init_db():
    """Initialize SQLite database"""
    with db_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id TEXT PRIMARY KEY, 
                      data TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admin_state
                     (admin_id TEXT PRIMARY KEY, 
                      data TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS banned_users
                     (user_id TEXT PRIMARY KEY,
                      banned_at TEXT,
                      reason TEXT)''')
        conn.commit()

def get_all_users():
    """Get all users from database"""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT user_id, data FROM users")
    rows = c.fetchall()
    users = {}
    for row in rows:
        users[row[0]] = json.loads(row[1])
    conn.close()
    return users

def get_user(user_id: int) -> dict:
    user_id = str(user_id)
    default_user_data = {
        "verified": False,
        "referral_count": 0,
        "referrals": [],
        "join_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "first_name": "",
        "username": "",
        "last_check": datetime.now().timestamp(),
        "referred_by": None,
        "banned": False,
        "last_login": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    try:
        with db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT data FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()

            if row:
                try:
                    user_data = json.loads(row[0])
                    # Ensure all required fields exist
                    for key, value in default_user_data.items():
                        if key not in user_data:
                            user_data[key] = value
                    return user_data
                except json.JSONDecodeError:
                    logging.error(f"Invalid JSON for user {user_id}")
                    return default_user_data
            else:
                # Save new user
                c.execute("INSERT INTO users VALUES (?, ?)", (user_id, json.dumps(default_user_data)))
                conn.commit()
                return default_user_data

    except sqlite3.Error as e:
        logging.error(f"Database error for user {user_id}: {e}")
        return default_user_data

def save_user(user_id: int, data: dict):
    """Save user data to database"""
    user_id = str(user_id)
    with db_connection() as conn:
        c = conn.cursor()
        c.execute("REPLACE INTO users VALUES (?, ?)", 
                 (user_id, json.dumps(data)))
        conn.commit()

def get_admin_state(admin_id: int) -> dict:
    """Get admin state from database"""
    admin_id = str(admin_id)
    with sqlite3.connect('bot_data.db') as conn:
        c = conn.cursor()
        c.execute("SELECT data FROM admin_state WHERE admin_id=?", (admin_id,))
        row = c.fetchone()

        return json.loads(row[0]) if row else {}

def save_admin_state(admin_id: int, data: dict):
    """Save admin state to database"""
    admin_id = str(admin_id)
    with sqlite3.connect('bot_data.db') as conn:
        c = conn.cursor()
        c.execute("REPLACE INTO admin_state VALUES (?, ?)", 
                 (admin_id, json.dumps(data)))
        conn.commit()

def delete_admin_state(admin_id: int):
    """Delete admin state from database"""
    admin_id = str(admin_id)
    with sqlite3.connect('bot_data.db') as conn:
        c = conn.cursor()
        c.execute("DELETE FROM admin_state WHERE admin_id=?", (admin_id,))
        conn.commit()

# ===== CONFIGURATION =====
class Config:
    # Security
    MAX_LOGIN_ATTEMPTS = 5
    SESSION_TIMEOUT = 3600  # 1 hour
    
    # Performance
    DB_TIMEOUT = 30
    CACHE_SIZE = 1000
    
    # Features
    ENABLE_2FA = False  # Can be enabled later
    CLOUD_BACKUPS = False
    
    # Bot settings
    MIN_REFERRALS_FOR_MINING = 5
    BOT_TOKEN = os.environ.get('BOT_TOKEN')
    ADMIN_ID = int(os.environ.get('ADMIN_ID', 0))
    DEV_MODE = os.environ.get('DEV_MODE', 'False').lower() == 'true'
    MAINTENANCE_MODE = os.environ.get('MAINTENANCE_MODE', 'False').lower() == 'true'
    
    @staticmethod
    def validate_config():
        required_vars = ['BOT_TOKEN', 'ADMIN_ID']
        missing_vars = []
        
        if not Config.BOT_TOKEN:
            missing_vars.append('BOT_TOKEN')
        if not Config.ADMIN_ID:
            missing_vars.append('ADMIN_ID')
            
        return missing_vars

# Initialize config
config = Config()
MIN_REFERRALS_FOR_MINING = config.MIN_REFERRALS_FOR_MINING
BOT_TOKEN = config.BOT_TOKEN
ADMIN_ID = config.ADMIN_ID
DEV_MODE = config.DEV_MODE

# ===== BOT DESCRIPTION =====
BOT_DESCRIPTION = """
🌟 *Welcome to Earning Club Bot!* 🌟

Your complete crypto earning solution with:
- 🆓 Free withdrawal bots
- 💎 Premium earning platforms
- ⛏️ Mining opportunities

🔐 *Verification Required:* Join our channels to unlock all features!
"""

# ===== CHANNEL CONFIGURATION =====
CHANNELS = [
    {"name": "Earning Club Tele", "url": "https://t.me/earningclubtele", "id": "@earningclubtele"},
    {"name": "Earning Club Latest", "url": "https://t.me/earningclubletest", "id": "@earningclubletest"},
    {"name": "Soloaex", "url": "https://t.me/soloaex", "id": "@soloaex"}
]

# ===== COMPLETE BOT RESOURCES WITH ALL LINKS =====
WITHDRAWABLE_BOTS_FREE = {
    "TRX": "https://t.me/TrxFreeAirdropsBot?start=1342140242",
    "TON": "https://t.me/TonAirdrop_ibot?start=r03339503340",
    "USD": "https://t.me/USDTRewardRobot?start=1342140242",
    "REFI": "https://t.me/ReficoinvipBot?start=1342140242",
    "DOGs": "https://t.me/Dogs_droppbot?start=1342140242"
}

WITHDRAWABLE_BOTS_ALL = {
    "NEI": "https://t.me/Neurashivipbot?start=1342140242",
    "PENDLE": "https://t.me/ClaimPendleAirdrop_bot?start=r03339503340",
    "REFI VIP": "https://t.me/Refivipbot?start=1342140242",
    "BNB": "https://t.me/BnbAirVBot?start=1342140242",
    "STRIKE": "https://t.me/Strikecoinbot?start=1342140242",
    "LIYTCOIN": "https://t.me/litecoin_automatic_bot?start=1342140242",
    "SPHYNX": "https://t.me/SPHYNXAirdrop_Robot?start=Bot45119933",
    "MONEY BUX": "https://t.me/easy_money_bux_bot?start=1342140242",
    "BNB PAY": "https://t.me/Free_Binance_Bnb_Pay_Bot?start=r03339503340",
    "INR": "https://t.me/FreeeUpiCashh_bot?start=1342140242",
    "ETHEREUM": "https://t.me/ETH_MaxLootBot?start=1342140242",
    "TELEGRAM MEMBERS": "https://t.me/Itzdhruvsmmtue_bot?start=1342140242",
    "USDT": "https://t.me/CryptoEarning6AirdropBot?start=1342140242",
    "TON PAY": "https://t.me/TONPayAiRbot?start=1342140242",
    "APE": "https://t.me/ApeAirdrop_iBot?start=r03339503340",
    "USDT REWARD": "https://t.me/UsdtAirdropR1Bot?start=1342140242",
    "INR PAY": "https://t.me/InstantoPayBot?start=1342140242",
    "PEPE": "https://t.me/EarnPepeV5Bot?start=1342140242",
    "BNB GIVEAWAY": "https://t.me/BnbTokenGiveawayBot?start=1342140242",
    "QexSwap": "https://t.me/QexSwapAirdropBot?start=Bot45119933",
    "MEMBERS 1": "https://t.me/itzdhruvfrismm_bot?start=1342140242",
    "MEMBERS 2": "https://t.me/itzdhruvsmmfri_bot?start=1342140242",
    "USDT AIRDROP": "https://t.me/BitgetWallet_USDTAirdrop_Bot?start=1342140242",
    "TRX AIRDROP": "https://t.me/Trxairdrop_ibot?start=r03339503340",
    "USDT FREE": "https://t.me/USDT_FREE3_BOT?start=1342140242",
    "FOX TRX": "https://t.me/FoxTRX_bot?start=1342140242",
    "USDT SECURE": "https://t.me/UsdtAirdrop_ibot?start=r03339503340",
    "SOL": "https://t.me/SOLMinedProV2bot?start=1342140242",
    "USDT MINING": "https://t.me/UsdtSecureMiningBot?start=1342140242",
    "TRX AUTO": "https://t.me/Trx_autopayerr_bot?start=1342140242",
    "TRON GIVER": "https://t.me/TronGiver_ibot?start=r03339503340",
    "BNB MINING": "https://t.me/BNBMiningTitanV2Bot?start=1342140242",
    "SOLANA": "https://t.me/Solana_Sphere_bot?start=1342140242",
    "XCOIN": "https://t.me/XCOINTokenAirdrop_bot?start=1342140242",
    "DERROT TRX": "https://t.me/Derrotrxbot?start=1342140242",
    "DOGELON": "https://t.me/DogelonMarAirdropBot?start=1342140242",
    "TON RUSSIA": "https://t.me/Russia_usdt77_bot?start=7481692974",
    "ARPA": "https://t.me/ArpaNerworkAirdropBot?start=r03339503340",
    "SPHYNX AIRDROP": "https://t.me/SphynxAidrop_Bot?start=1342140242",
    "PEPE AUTO": "https://t.me/PEPEAutopayaibot?start=1342140242",
    "BNB WITHDRAW": "https://t.me/WithdrawUSDT_bot?start=1342140242",
    "TRUMP": "https://t.me/OfficialTrumpFreeBot?start=1342140242",
    "TONX": "https://t.me/Tonxxpay_bot?start=1342140242",
    "USDT MILLION": "https://t.me/MillionUSDTGiveaway_Bot?start=1342140242",
    "ETH FREE": "https://t.me/EthFreeAirdropbot?start=1342140242",
    "PEPE INSTANT": "https://t.me/PepeFreeInstantPayBot?start=1342140242",
    "TRX MAX": "https://t.me/TRXAutopayMaxbot?start=1342140242",
    "TON CHAIN": "https://t.me/TONChainPaybot?start=1342140242",
    "STAR": "https://t.me/Itzdhruvthu_bot?start=1342140242",
    "TON": "https://t.me/TON_FREE_100_Bot?start=1342140242",
    "METAMASK": "https://t.me/metamask_ETH_FREE_bot?start=1342140242",
    "CELO": "https://t.me/celocoinpay1bot?start=1342140242",
    "USDT": "https://t.me/Usdt_Dropzbot?start=1342140242",
    "NOT": "https://t.me/NOTdroppbot?start=1342140242",
    "BD71": "https://t.me/EarningBD71AirdropBot?start=1342140242",
    "TETHER": "https://t.me/TetherCloudStationBot?start=1342140242",
    "BNB": "https://t.me/BNBMiningTitanV3Bot?start=1342140242",
    "DOGE": "https://t.me/Dogecoin_Free_Mining_Bot?start=r03339503340",
    "OP": "https://t.me/OP_Sphere_GiveawayBot?start=r03339503340",
    "STARGLOW": "https://t.me/StarglowGuaranteedAirdropBot?start=1342140242",
    "DEVIL": "https://t.me/DevilAutopayAirdropBot?start=1342140242",
    "VOLTIX": "https://t.me/VoltixUsdt_bot?start=1342140242",
    "JBC": "https://t.me/jbc_collective_bot?start=85222"
}

PREMIUM_BOTS = {
    "NOBU": "https://t.me/NobuAirdropBot?start=1342140242",
    "KNC": "https://t.me/KNCAIRBOT?start=r03339503340",
}

# Special bots with custom referral requirements
SPECIAL_BOTS = {
    "CLICK BEE VIP": {
        "url": "https://t.me/ClickBeeBot?start=1342140242",
        "referrals_needed": 3
    }
}

MINING_BOTS = {
    "MINEVERS": "https://t.me/MineVerseBot/app?startapp=r_1342140242",
    "IMINER": "https://t.me/iMiner_bot/mining?startapp=r_6R6ZvvQcQ90e",
    "JAQPOT": "https://t.me/jolly_jackpot_bot/login?startapp=1342140242&size=large",
    "TONGRAM": "http://t.me/TongramAppBot/start?startapp=1342140242",
    "TONSTARTER": "https://t.me/tonstarterAppbot/Start?startapp=1342140242",
    "TONIX": "https://t.me/Mining_TonixBot?start=1342140242",
    "LAND HASH": "https://t.me/lendhash_bot?start=1342140242",
    "LIONS": "https://t.me/Lionsapp_bot/LIONS?startapp=r_1342140242",
    "WINBOX": "https://t.me/appgiftabot/gift?startapp=6277986420510520430",
    "XWORLD": "https://t.me/xworld/app?startapp=bT10Z19pbnZpdGUmYz0xODAxMTE3MzM2",
    "RICH DOG": "https://t.me/RichDogGameBot/Play?startapp=kentId1342140242",
    "GIFTANIA": "https://t.me/GiftomaniaBot/?startapp=ref_VZ1LU7",
    "CASE": "https://t.me/case_official_bot/case?startapp=ref_he0xC0GAPYL9raz",
    "QZINO": "https://t.me/qzino_official_bot/app/?startapp=nhffNVS",
    "RICH AI": "https://h5.2cm.top/go?i=fdsqka_1342140242_copy",
    "WORK DOGS": "https://h5.2cm.top/go?i=gnhzej_1342140242_copy",
    "FREE TON": "https://h5.2vc.top/go?i=dvkael_1342140242_copy",
    "CLICKBIT": "https://t.me/clickbit_app_bot/clickbit?startapp=4A4FD70FF1",
    "FOMO100": "https://t.me/fomo100_bot/join_fomo?startapp=ref_2k59g2o",
    "GIFTBOX": "https://t.me/giftbox_official_bot/app?startapp=ref_V1MUfCat",
    "QUANTGUARD AI": "https://h5.2cm.top/go?i=jwjvbs_1342140242_copy"
}

# ===== HELPER FUNCTIONS =====
async def check_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        for channel in CHANNELS:
            try:
                member = await context.bot.get_chat_member(
                    chat_id=channel['id'],
                    user_id=user_id
                )
                if member.status not in ['member', 'administrator', 'creator']:
                    return False
            except Exception as channel_error:
                logging.error(f"Channel check error for {channel['id']}: {channel_error}")
                # If we can't check a channel, assume not member
                return False
        return True
    except Exception as e:
        logging.error(f"General channel check error: {e}")
        return False

def create_button_menu(items, back_button=True, prefix="", page=0, items_per_page=8):
    items_list = list(items.items())
    start = page * items_per_page
    end = start + items_per_page
    page_items = items_list[start:end]

    keyboard = []
    for i in range(0, len(page_items), 2):
        row = []
        for j, (name, url) in enumerate(page_items[i:i+2]):
            # Add numbering to button text
            button_number = start + i + j + 1
            numbered_name = f"{button_number}. {name}"
            row.append(InlineKeyboardButton(numbered_name, url=url))
        if row:
            keyboard.append(row)

    # Pagination controls if needed
    if len(items_list) > items_per_page:
        controls = []
        if page > 0:
            controls.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{prefix}_page_{page-1}"))
        if end < len(items_list):
            controls.append(InlineKeyboardButton("Next ➡️", callback_data=f"{prefix}_page_{page+1}"))
        if controls:
            keyboard.append(controls)

    if back_button:
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="main_menu")])

    return InlineKeyboardMarkup(keyboard)

# ===== HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    # Check maintenance mode
    if config.MAINTENANCE_MODE and user_id != ADMIN_ID:
        await update.message.reply_text(
            "🔧 *Bot is under maintenance*\n\n"
            "Please try again later. We'll be back soon!",
            parse_mode="Markdown"
        )
        return

    # Check if user is new BEFORE creating user data
    all_users = get_all_users()
    is_new_user = str(user_id) not in all_users

    # Now get/create user data
    user_data = get_user(user_id)
    
    # Check if user is banned
    if user_data.get("banned", False):
        await update.message.reply_text(
            "🚫 Your account is banned.\n\n"
            "Contact admin if you believe this is an error."
        )
        return

    # Store user info
    user_data["first_name"] = user.first_name
    user_data["username"] = user.username or ""
    user_data["last_check"] = datetime.now().timestamp()

    # Process referral if exists - only for completely new users
    if (context.args and context.args[0].startswith('ref_') and is_new_user):
        referrer_id = context.args[0][4:]

        # Get referrer data
        all_users = get_all_users()
        if (referrer_id in all_users and 
            referrer_id != str(user_id) and
            user_data.get("referred_by") is None):  # Ensure not already referred

            # Update referrer data
            referrer_data = get_user(int(referrer_id))
            referrer_data["referral_count"] += 1
            referrer_data["referrals"].append(str(user_id))
            save_user(int(referrer_id), referrer_data)

            # Update current user
            user_data["referred_by"] = referrer_id
            save_user(user_id, user_data)

            # Notify referrer
            try:
                await context.bot.send_message(
                    int(referrer_id),
                    f"🎉 *New Referral!*\n\n"
                    f"User: {user.first_name}\n"
                    f"Total Referrals: {referrer_data['referral_count']}\n"
                    f"Keep sharing to unlock more features!",
                    parse_mode="Markdown"
                )
            except:
                pass

    # Save user data
    save_user(user_id, user_data)

    # First send the bot description clearly
    await update.message.reply_text(
        BOT_DESCRIPTION,
        parse_mode="Markdown"
    )

    # Then send channel verification requirements
    keyboard = [
        [InlineKeyboardButton(f"Join {ch['name']}", url=ch['url'])]
        for ch in CHANNELS
    ]
    keyboard.append([InlineKeyboardButton("✅ Verify Membership", callback_data="verify")])

    await update.message.reply_text(
        "🔑 *To unlock all features:*\n\n"
        "1️⃣ Join all our channels above\n"
        "2️⃣ Click 'Verify Membership' button\n"
        "3️⃣ Access all earning bots!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_verify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)

    if await check_membership(context, user_id):
        user_data["verified"] = True
        user_data["last_check"] = datetime.now().timestamp()
        save_user(user_id, user_data)

        await query.edit_message_text(
            "✅ *Verification Successful!*\n\n"
            "Welcome to Earning Club! You now have access to all features.",
            parse_mode="Markdown"
        )

        # Automatically show main menu after successful verification
        await show_main_menu(update, context)
    else:
        # Show verification failed with back button
        keyboard = [
            [InlineKeyboardButton("🔄 Try Again", callback_data="verify")],
            [InlineKeyboardButton("⬅️ Back to Channels", callback_data="show_channels")]
        ]

        await query.edit_message_text(
            "❌ *Verification Failed!*\n\n"
            "Please join ALL channels first:\n"
            + "\n".join([f"• {ch['name']}" for ch in CHANNELS]) +
            "\n\nThen click 'Try Again'",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def show_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton(f"Join {ch['name']}", url=ch['url'])]
        for ch in CHANNELS
    ]
    keyboard.append([InlineKeyboardButton("✅ Verify Membership", callback_data="verify")])

    await query.edit_message_text(
        "🔑 *Join Required Channels:*\n\n"
        "Please join all channels below and then verify:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle both Update and CallbackQuery objects
    if hasattr(update, 'callback_query') and update.callback_query:
        query = update.callback_query
        if not query.message:
            return
        await query.answer()
        user_id = query.from_user.id
        message = query.message
        edit_message = True
    else:
        # Direct call from /start or after verification
        user_id = update.effective_user.id
        message = update.effective_message
        edit_message = False

    user_data = get_user(user_id)

    # Verify membership again if last check was more than 1 hour ago
    if datetime.now().timestamp() - user_data["last_check"] > 3600:
        if not await check_membership(context, user_id):
            user_data["verified"] = False
            save_user(user_id, user_data)
            if edit_message:
                await query.edit_message_text(
                    "❌ Session expired! Please verify again.",
                    parse_mode="Markdown"
                )
            return

    keyboard = [
        [InlineKeyboardButton("🆓 Withdrawable Bots", callback_data="withdraw")],
        [InlineKeyboardButton("💎 Premium Bots", callback_data="premium")],
    ]

    # Show mining bots if unlocked
    if user_data["referral_count"] >= 5:
        keyboard.append([InlineKeyboardButton("⛏️ Mining Bots", callback_data="mining")])
    else:
        keyboard.append([InlineKeyboardButton(
            f"🔒 Mining Bots ({user_data['referral_count']}/5 refs)", 
            callback_data="mining_locked"
        )])

    # Add profile and referral buttons
    keyboard.append([
        InlineKeyboardButton("👤 Profile", callback_data="profile"),
        InlineKeyboardButton("📤 Referral", callback_data="referral")
    ])
    keyboard.append([InlineKeyboardButton("ℹ️ About Us", callback_data="about")])

    menu_text = "🎮 *Main Menu* 🎮\n\nChoose a category:"

    # Send or edit message based on context
    if edit_message:
        await query.edit_message_text(
            text=menu_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await context.bot.send_message(
            chat_id=message.chat_id,
            text=menu_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def show_withdraw_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)

    # Verify membership
    if not user_data["verified"] or (not DEV_MODE and not await check_membership(context, user_id)):
        await query.answer("❌ Please verify first!", show_alert=True)
        return

    keyboard = []
    # Add free bots with pagination
    free_bots_list = list(WITHDRAWABLE_BOTS_FREE.items())
    for i in range(0, len(free_bots_list), 2):
        row = []
        for j, (name, url) in enumerate(free_bots_list[i:i+2]):
            # Add numbering to button text
            button_number = i + j + 1
            numbered_name = f"{button_number}. {name}"
            row.append(InlineKeyboardButton(numbered_name, url=url))
        if row:
            keyboard.append(row)

    # Add "All Bots" with referral requirement
    if user_data["referral_count"] >= 2:
        keyboard.append([InlineKeyboardButton("🌟 ALL BOTS", callback_data="all_bots")])
    else:
        keyboard.append([InlineKeyboardButton(
            f"🔒 ALL BOTS ({user_data['referral_count']}/2 refs)", 
            callback_data="need_refs"
        )])

    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="main_menu")])

    await query.edit_message_text(
        text="🆓 *Withdrawable Bots*\n\n"
        "Free instant withdrawal bots:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_all_withdraw_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)

    if user_data["referral_count"] < 2:
        await query.answer("❌ You need 2 referrals to unlock all bots!", show_alert=True)
        return

    markup = create_button_menu(WITHDRAWABLE_BOTS_ALL, prefix="all_bots")
    await query.edit_message_text(
        text="🌟 *All Withdrawable Bots*\n\n"
        f"Total: {len(WITHDRAWABLE_BOTS_ALL)} bots available",
        parse_mode="Markdown",
        reply_markup=markup
    )

async def show_premium_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)

    # Verify membership
    if not user_data["verified"] or (not DEV_MODE and not await check_membership(context, user_id)):
        await query.answer("❌ Please verify first!", show_alert=True)
        return

    # Create keyboard with regular premium bots
    keyboard = []
    premium_bots_list = list(PREMIUM_BOTS.items())
    for i in range(0, len(premium_bots_list), 2):
        row = []
        for j, (name, url) in enumerate(premium_bots_list[i:i+2]):
            # Add numbering to button text
            button_number = i + j + 1
            numbered_name = f"{button_number}. {name}"
            row.append(InlineKeyboardButton(numbered_name, url=url))
        if row:
            keyboard.append(row)

    # Add Click Bee Bot with referral requirement
    click_bee = SPECIAL_BOTS["CLICK BEE VIP"]
    next_number = len(premium_bots_list) + 1
    if user_data["referral_count"] >= click_bee["referrals_needed"]:
        keyboard.append([InlineKeyboardButton(f"{next_number}. 🐝 CLICK BEE VIP", url=click_bee["url"])])
    else:
        needed = click_bee["referrals_needed"] - user_data["referral_count"]
        keyboard.append([InlineKeyboardButton(
            f"{next_number}. 🔒 CLICK BEE VIP ({user_data['referral_count']}/{click_bee['referrals_needed']} refs)", 
            callback_data="click_bee_locked"
        )])

    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="main_menu")])

    total_bots = len(PREMIUM_BOTS) + 1  # Include Click Bee
    await query.edit_message_text(
        text="💎 *Premium Bots*\n\n"
        f"Total: {total_bots} premium bots available",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_mining_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏳ Loading mining bots...")
    user_id = query.from_user.id
    user_data = get_user(user_id)

    # Verify membership
    if not user_data["verified"] or (not DEV_MODE and not await check_membership(context, user_id)):
        await query.answer("❌ Please verify first!", show_alert=True)
        return

    if user_data["referral_count"] < 5:
        await query.answer(f"❌ Need {5-user_data['referral_count']} more referrals!", show_alert=True)
        return

    markup = create_button_menu(MINING_BOTS, prefix="mining_bots")
    await query.edit_message_text(
        text="⛏️ *Mining Bots*\n\n"
        f"Total: {len(MINING_BOTS)} mining bots available",
        parse_mode="Markdown",
        reply_markup=markup
    )

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_data = get_user(user.id)

    keyboard = []

    # Add set username button only if username is not set
    if not user.username:
        keyboard.append([InlineKeyboardButton("📝 Set Username", callback_data="set_username")])

    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="main_menu")])

    # Display custom username if set, otherwise use Telegram username
    display_username = user_data.get("custom_username", user.username)

    await query.edit_message_text(
        text=f"👤 *Your Profile*\n\n"
        f"Name: {user.first_name}\n"
        f"Username: @{display_username or 'N/A'}\n"
        f"Join Date: {user_data['join_date']}\n"
        f"Referrals: {user_data['referral_count']}\n"
        f"Status: {'✅ Verified' if user_data['verified'] else '❌ Not Verified'}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_data = get_user(user.id)

    referral_link = f"https://t.me/{context.bot.username}?start=ref_{user.id}"

    await query.edit_message_text(
        text=f"📤 *Referral Program*\n\n"
        f"Your referrals: {user_data['referral_count']}\n\n"
        f"🔗 Your referral link:\n"
        f"`{referral_link}`\n\n"
        f"🎁 *Rewards:*\n"
        f"• 2 refs = Unlock ALL withdrawal bots\n"
        f"• 3 refs = Unlock Click Bee VIP (Premium referral bot)\n"
        f"• 5 refs = Unlock mining bots\n\n"
        f"🐝 *Click Bee Bot* is a premium referral bot - invite others and earn through referrals!\n\n"
        f"Share and earn together! 🚀",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]
        ])
    )

async def show_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        text="ℹ️ *About Earning Club Bot*\n\n"
        "Your ultimate crypto earning platform with:\n"
        "• 50+ verified earning bots\n"
        "• Instant withdrawal options\n"
        "• Premium mining opportunities\n"
        "• Referral rewards system\n\n"
        "Start small, earn big, and grow your crypto portfolio!\n\n"
        "💡 *Tip:* Invite friends to unlock more features!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]
        ])
    )

async def handle_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("all_bots_page_"):
        page = int(data.split("_")[-1])
        markup = create_button_menu(WITHDRAWABLE_BOTS_ALL, prefix="all_bots", page=page)
        await query.edit_message_text(
            "🌟 *All Withdrawable Bots*\n\n"
            f"Total: {len(WITHDRAWABLE_BOTS_ALL)} bots available",
            parse_mode="Markdown",
            reply_markup=markup
        )
    elif data.startswith("premium_bots_page_"):
        page = int(data.split("_")[-1])
        markup = create_button_menu(PREMIUM_BOTS, prefix="premium_bots", page=page)
        await query.edit_message_text(
            "💎 *Premium Bots*\n\n"
            f"Total: {len(PREMIUM_BOTS)} premium bots available",
            parse_mode="Markdown",
            reply_markup=markup
        )
    elif data.startswith("mining_bots_page_"):
        page = int(data.split("_")[-1])
        markup = create_button_menu(MINING_BOTS, prefix="mining_bots", page=page)
        await query.edit_message_text(
            "⛏️ *Mining Bots*\n\n"
            f"Total: {len(MINING_BOTS)} mining bots available",
            parse_mode="Markdown",
            reply_markup=markup
        )

async def handle_need_refs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle need referrals callback"""
    query = update.callback_query
    await query.answer("❌ You need 2 referrals to unlock all bots! Use the referral menu to invite friends.", show_alert=True)

async def handle_mining_locked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle mining locked callback"""
    query = update.callback_query
    user_data = get_user(query.from_user.id)
    needed = 5 - user_data["referral_count"]
    await query.answer(f"❌ Mining bots need 5 referrals! You need {needed} more. Use referral menu to invite friends.", show_alert=True)

async def handle_click_bee_locked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Click Bee locked callback"""
    query = update.callback_query
    user_data = get_user(query.from_user.id)
    needed = 3 - user_data["referral_count"]
    await query.answer(f"🐝 To unlock Click Bee Bot you will have to refer 3 friends! You need {needed} more referrals.", show_alert=True)

async def handle_set_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle set username callback"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # Set admin state for username setting
    admin_state = {"action": "set_username", "step": "waiting"}
    save_admin_state(user_id, admin_state)

    await query.edit_message_text(
        text="📝 *Set Your Username*\n\n"
        "Please send your desired username (without @):\n\n"
        "Example: `myusername`\n\n"
        "Note: This will be stored in your profile for display purposes.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="profile")]
        ])
    )

async def handle_username_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle username setting messages"""
    user_id = update.effective_user.id

    # Check if user is in username setting mode
    admin_state = get_admin_state(user_id)
    if (admin_state.get("action") == "set_username" and
        admin_state.get("step") == "waiting"):

        username = update.message.text.strip().replace("@", "")

        # Validate username (basic validation)
        if len(username) < 3 or len(username) > 32:
            await update.message.reply_text(
                "❌ Username must be between 3-32 characters long. Please try again:"
            )
            return

        if not username.replace("_", "").isalnum():
            await update.message.reply_text(
                "❌ Username can only contain letters, numbers, and underscores. Please try again:"
            )
            return

        # Store the username in user data
        user_data = get_user(user_id)
        user_data["custom_username"] = username
        save_user(user_id, user_data)

        # Clear the admin state
        delete_admin_state(user_id)

        await update.message.reply_text(
            f"✅ Username set to: @{username}\n\n"
            "Your profile has been updated!",
            parse_mode="Markdown"
        )

        # Show updated profile
        await show_profile_after_username_set(update, context, user_id)
        return True

    return False

async def show_profile_after_username_set(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Show profile after username is set"""
    user = await context.bot.get_chat(user_id)
    user_data = get_user(user_id)

    # Display custom username if set, otherwise use Telegram username
    display_username = user_data.get("custom_username", user.username)

    await context.bot.send_message(
        chat_id=user_id,
        text=f"👤 *Your Profile*\n\n"
        f"Name: {user.first_name}\n"
        f"Username: @{display_username or 'N/A'}\n"
        f"Join Date: {user_data['join_date']}\n"
        f"Referrals: {user_data['referral_count']}\n"
        f"Status: {'✅ Verified' if user_data['verified'] else '❌ Not Verified'}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]
        ])
    )

async def handle_unknown_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unknown callback queries"""
    query = update.callback_query
    await query.answer("⚠️ Unknown action. Please try again.", show_alert=True)

# ===== USER COMMANDS =====
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = """
🤖 *Bot Commands Help*

📌 *Available Commands:*
• `/start` - Start the bot and access main menu
• `/help` - Show this help message
• `/request` - Send a message to admin
• `/restart` - Restart your bot session

💡 *How to use:*
1. Join our channels to get verified
2. Use referrals to unlock more bots
3. Use /request to contact admin for support

🔗 *Quick Access:*
Use /start to return to main menu anytime!
    """
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def request_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /request command"""
    user = update.effective_user
    if len(context.args) == 0:
        await update.message.reply_text(
            "💬 *Send a Request to Admin*\n\n"
            "Usage: `/request your message here`\n\n"
            "Example: `/request I need help with withdrawal`",
            parse_mode="Markdown"
        )
        return

    message = " ".join(context.args)

    # Input validation
    if len(message) > 1000:
        await update.message.reply_text(
            "❌ Message too long! Please keep it under 1000 characters.",
            parse_mode="Markdown"
        )
        return

    if len(message.strip()) < 3:
        await update.message.reply_text(
            "❌ Message too short! Please provide more details.",
            parse_mode="Markdown"
        )
        return

    user_data = get_user(user.id)

    # Send to admin
    admin_message = (
        f"📩 *New User Request*\n\n"
        f"👤 From: {user.first_name} (@{user.username or 'N/A'})\n"
        f"🆔 ID: `{user.id}`\n"
        f"📝 Message: {message}\n\n"
        f"Reply with: `/reply {user.id} your response`"
    )

    try:
        await context.bot.send_message(ADMIN_ID, admin_message, parse_mode="Markdown")
        await update.message.reply_text(
            "✅ Your request has been sent to admin!\n"
            "You'll receive a reply soon.",
            parse_mode="Markdown"
        )
        logging.info(f"Request sent from user {user.id}: {message[:50]}...")
    except Exception as e:
        logging.error(f"Failed to send request from user {user.id}: {e}")
        await update.message.reply_text(
            "❌ Failed to send request. Please try again later.",
            parse_mode="Markdown"
        )

async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /restart command"""
    user_id = update.effective_user.id
    user_data = get_user(user_id)

    # Reset verification status to force re-verification
    user_data["verified"] = False
    user_data["last_check"] = 0
    save_user(user_id, user_data)

    await update.message.reply_text(
        "🔄 *Bot Restarted!*\n\n"
        "Your session has been reset. Please use /start to begin again.",
        parse_mode="Markdown"
    )

# ===== ADMIN COMMANDS =====
async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin reply to user requests"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/reply user_id your message here`\n"
            "Example: `/reply 123456789 Your issue has been resolved`"
        )
        return

    try:
        target_user_id = int(context.args[0])
        message = " ".join(context.args[1:])

        # Input validation
        if len(message) > 4000:
            await update.message.reply_text("❌ Message too long (max 4000 characters)")
            return

        reply_message = (
            f"💬 *Reply from Admin*\n\n"
            f"📝 {message}\n\n"
            f"Need more help? Use `/request your question`"
        )

        await context.bot.send_message(target_user_id, reply_message, parse_mode="Markdown")
        await update.message.reply_text(f"✅ Reply sent to user {target_user_id}")

    except ValueError:
        await update.message.reply_text("❌ Invalid user ID format")
    except Exception as e:
        logging.error(f"Reply command error: {e}")
        await update.message.reply_text(f"❌ Failed to send reply: {str(e)}")

async def send_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin send message command"""
    if update.effective_user.id != ADMIN_ID:
        return

    keyboard = [
        [InlineKeyboardButton("📤 Send to Specific User", callback_data="admin_send_specific")],
        [InlineKeyboardButton("📢 Send to All Users", callback_data="admin_send_all")],
        [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
    ]

    await update.message.reply_text(
        "👑 *Admin Message Panel*\n\n"
        "Choose how you want to send your message:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_admin_send_specific(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin send to specific user"""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Admin only!", show_alert=True)
        return

    await query.answer()
    admin_state = {"action": "send_specific", "step": "user_id"}
    save_admin_state(ADMIN_ID, admin_state)

    await query.edit_message_text(
        "👤 *Send to Specific User*\n\n"
        "Please send the user ID (number only):",
        parse_mode="Markdown"
    )

async def handle_admin_send_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin send to all users"""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Admin only!", show_alert=True)
        return

    await query.answer()
    admin_state = {"action": "send_all", "step": "message"}
    save_admin_state(ADMIN_ID, admin_state)

    await query.edit_message_text(
        "📢 *Send to All Users*\n\n"
        "Please type your message:",
        parse_mode="Markdown"
    )

async def handle_admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin cancel action"""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Admin only!", show_alert=True)
        return

    await query.answer()
    delete_admin_state(ADMIN_ID)

    await query.edit_message_text("❌ Action cancelled.")

async def handle_admin_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin message flow and username setting"""
    # First check if this is a username setting message
    if await handle_username_messages(update, context):
        return

    # Then check admin messages
    if update.effective_user.id != ADMIN_ID:
        return

    admin_state = get_admin_state(ADMIN_ID)
    if not admin_state:
        return

    if admin_state["action"] == "send_specific":
        if admin_state["step"] == "user_id":
            try:
                target_user_id = int(update.message.text.strip())
                admin_state["target_user_id"] = target_user_id
                admin_state["step"] = "message"
                save_admin_state(ADMIN_ID, admin_state)

                await update.message.reply_text(
                    f"✅ Target user: {target_user_id}\n\n"
                    "Now type your message:"
                )
            except ValueError:
                await update.message.reply_text("❌ Invalid user ID. Please send numbers only.")

        elif admin_state["step"] == "message":
            message = update.message.text
            target_id = admin_state["target_user_id"]

            try:
                admin_message = f"👑 *Message from Admin*\n\n{message}"
                await context.bot.send_message(target_id, admin_message, parse_mode="Markdown")
                await update.message.reply_text(f"✅ Message sent to user {target_id}")
            except Exception as e:
                await update.message.reply_text(f"❌ Failed to send: {str(e)}")

            delete_admin_state(ADMIN_ID)

    elif admin_state["action"] == "send_all":
        if admin_state["step"] == "message":
            message = update.message.text
            success_count = 0
            fail_count = 0

            admin_message = f"👑 *Message from Admin*\n\n{message}"
            all_users = get_all_users()

            for user_id in all_users:
                try:
                    await context.bot.send_message(int(user_id), admin_message, parse_mode="Markdown")
                    success_count += 1
                except:
                    fail_count += 1

            await update.message.reply_text(
                f"📊 *Broadcast Complete*\n\n"
                f"✅ Sent: {success_count}\n"
                f"❌ Failed: {fail_count}\n"
                f"👥 Total users: {len(all_users)}"
            )

            delete_admin_state(ADMIN_ID)

async def handle_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin broadcast to all users"""
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) == 0:
        await update.message.reply_text(
            "📢 *Broadcast to All Users*\n\n"
            "Usage: `/broadcast your message here`\n\n"
            "Example: `/broadcast Important update: New bots added!`",
            parse_mode="Markdown"
        )
        return

    message = " ".join(context.args)
    success_count = 0
    fail_count = 0

    admin_message = f"👑 *Broadcast from Admin*\n\n{message}"
    all_users = get_all_users()

    for user_id in all_users:
        try:
            await context.bot.send_message(int(user_id), admin_message, parse_mode="Markdown")
            success_count += 1
        except:
            fail_count += 1

    await update.message.reply_text(
        f"📊 *Broadcast Complete*\n\n"
        f"✅ Sent: {success_count}\n"
        f"❌ Failed: {fail_count}\n"
        f"👥 Total users: {len(all_users)}",
        parse_mode="Markdown"
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin stats command"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return

    try:
        all_users = get_all_users()
        if not all_users:
            await update.message.reply_text("📊 No users found in database")
            return

        verified = sum(1 for u in all_users.values() if u.get("verified", False))
        total_referrals = sum(u.get("referral_count", 0) for u in all_users.values())
        avg_referrals = total_referrals / len(all_users) if all_users else 0

        # Find top referrer
        top_referrer = max(all_users.items(), key=lambda x: x[1].get("referral_count", 0))

        stats_text = (
            f"📊 *Bot Statistics*\n\n"
            f"👥 Total Users: {len(all_users)}\n"
            f"✅ Verified: {verified} ({verified/len(all_users)*100:.1f}%)\n"
            f"📈 Total Referrals: {total_referrals}\n"
            f"📊 Avg Referrals: {avg_referrals:.1f}\n"
            f"🏆 Top Referrer: {top_referrer[1].get('first_name', 'Unknown')} ({top_referrer[1].get('referral_count', 0)} refs)\n\n"
            f"🎯 Mining Bot Access: {sum(1 for u in all_users.values() if u.get('referral_count', 0) >= 5)} users"
        )

        await update.message.reply_text(stats_text, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Stats command error: {e}")
        await update.message.reply_text(f"❌ Error generating stats: {str(e)}")

async def export_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export user data as CSV"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return

    try:
        await update.message.reply_text("📊 Exporting user data...")

        all_users = get_all_users()
        csv_data = "User ID,First Name,Username,Referrals,Join Date,Verified,Last Check\n"

        for user_id, data in all_users.items():
            csv_data += f"{user_id}," \
                       f"\"{data.get('first_name', '').replace(',', ';')}\"," \
                       f"{data.get('username', '')}," \
                       f"{data.get('referral_count', 0)}," \
                       f"{data.get('join_date', '')}," \
                       f"{data.get('verified', False)}," \
                       f"{data.get('last_check', '')}\n"

        # Save to file
        filename = f"users_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(csv_data)

        # Send file to admin
        with open(filename, 'rb') as f:
            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=f,
                filename=filename,
                caption=f"📊 User export completed\nTotal users: {len(all_users)}"
            )

        # Clean up file
        import os
        os.remove(filename)

    except Exception as e:
        logging.error(f"Export failed: {e}")
        await update.message.reply_text(f"❌ Export failed: {str(e)}")

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual database backup command"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return

    try:
        await update.message.reply_text("💾 Creating database backup...")
        backup_name = backup_database()

        if backup_name:
            # Send backup file to admin
            with open(backup_name, 'rb') as f:
                await context.bot.send_document(
                    chat_id=ADMIN_ID,
                    document=f,
                    filename=backup_name,
                    caption="💾 Database backup created successfully"
                )

            # Clean up local backup file
            import os
            os.remove(backup_name)
        else:
            await update.message.reply_text("❌ Backup failed")

    except Exception as e:
        logging.error(f"Backup command failed: {e}")
        await update.message.reply_text(f"❌ Backup failed: {str(e)}")

async def ban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ban a user from using the bot"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return

    if len(context.args) < 1:
        await update.message.reply_text(
            "Usage: `/ban user_id [reason]`\n"
            "Example: `/ban 123456789 Spam behavior`",
            parse_mode="Markdown"
        )
        return

    try:
        target_user_id = int(context.args[0])
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason provided"
        
        # Update user data
        user_data = get_user(target_user_id)
        user_data["banned"] = True
        save_user(target_user_id, user_data)
        
        # Add to rate limiter ban list
        rate_limiter.ban_user(target_user_id)
        
        # Store ban info in database
        with db_connection() as conn:
            c = conn.cursor()
            c.execute("REPLACE INTO banned_users VALUES (?, ?, ?)", 
                     (str(target_user_id), datetime.now().isoformat(), reason))
            conn.commit()
        
        await update.message.reply_text(f"✅ User {target_user_id} banned\nReason: {reason}")
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"🚫 Your account has been banned\nReason: {reason}\n\nContact admin if you believe this is an error."
            )
        except:
            pass  # User might have blocked the bot

    except ValueError:
        await update.message.reply_text("❌ Invalid user ID format")
    except Exception as e:
        logging.error(f"Ban command error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def unban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unban a user"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return

    if len(context.args) < 1:
        await update.message.reply_text(
            "Usage: `/unban user_id`\n"
            "Example: `/unban 123456789`",
            parse_mode="Markdown"
        )
        return

    try:
        target_user_id = int(context.args[0])
        
        # Update user data
        user_data = get_user(target_user_id)
        user_data["banned"] = False
        save_user(target_user_id, user_data)
        
        # Remove from rate limiter ban list
        rate_limiter.unban_user(target_user_id)
        
        # Remove from banned_users table
        with db_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM banned_users WHERE user_id = ?", (str(target_user_id),))
            conn.commit()
        
        await update.message.reply_text(f"✅ User {target_user_id} unbanned")
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="✅ Your account has been unbanned. You can now use the bot again."
            )
        except:
            pass

    except ValueError:
        await update.message.reply_text("❌ Invalid user ID format")
    except Exception as e:
        logging.error(f"Unban command error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def daily_tasks(context: ContextTypes.DEFAULT_TYPE):
    """Run daily maintenance tasks"""
    try:
        logging.info("🔄 Running daily maintenance tasks...")

        # Create backup
        backup_name = backup_database()
        if backup_name:
            logging.info(f"✅ Daily backup created: {backup_name}")

        # Send daily stats to admin
        all_users = get_all_users()
        if all_users:
            verified = sum(1 for u in all_users.values() if u.get("verified", False))
            total_referrals = sum(u.get("referral_count", 0) for u in all_users.values())

            daily_report = (
                f"📊 *Daily Report*\n\n"
                f"👥 Total Users: {len(all_users)}\n"
                f"✅ Verified: {verified}\n"
                f"📈 Total Referrals: {total_referrals}\n"
                f"💾 Backup: {'✅ Created' if backup_name else '❌ Failed'}"
            )

            try:
                await context.bot.send_message(ADMIN_ID, daily_report, parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Failed to send daily report: {e}")

        logging.info("✅ Daily maintenance completed")

    except Exception as e:
        logging.error(f"Daily tasks error: {e}")

# ===== COMMAND MENU HANDLER =====
async def show_command_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show message for unknown commands."""
    command = update.message.text

    await update.message.reply_text(
        f"❓ *Unknown Command: {command}*\n\n"
        "Available commands:\n"
        "• `/start` - Start the bot\n"
        "• `/help` - Show help\n"
        "• `/request` - Contact admin\n"
        "• `/restart` - Restart session\n\n"
        "Use `/help` for more information.",
        parse_mode="Markdown"
    )

# ===== Database backup functionality =====
def cleanup_old_backups(max_backups=5):
    """Keep only the most recent backup files"""
    import os
    try:
        backup_files = sorted(
            [f for f in os.listdir() if f.startswith('bot_data_backup_')],
            key=os.path.getmtime,
            reverse=True
        )
        for old_backup in backup_files[max_backups:]:
            try:
                os.remove(old_backup)
                logging.info(f"Removed old backup: {old_backup}")
            except Exception as e:
                logging.error(f"Failed to remove backup {old_backup}: {e}")
    except Exception as e:
        logging.error(f"Backup cleanup error: {e}")

def backup_database():
    """Create a backup of the database"""
    try:
        backup_name = f"bot_data_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db"
        with sqlite3.connect('bot_data.db') as conn:
            backup_conn = sqlite3.connect(backup_name)
            conn.backup(backup_conn)
            backup_conn.close()
        logging.info(f"Database backup created: {backup_name}")

        # Cleanup old backups
        cleanup_old_backups()

        return backup_name
    except Exception as e:
        logging.error(f"Backup failed: {e}")
        return None

# ===== Enhanced Rate Limiting System =====
from telegram.ext import TypeHandler
from collections import defaultdict
from datetime import datetime, timedelta
from telegram import constants

class RateLimiter:
    def __init__(self):
        self.user_activity = defaultdict(list)
        self.banned_users = set()
    
    async def check_rate_limit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        now = datetime.now()
        
        # Check if user is banned
        if user_id in self.banned_users:
            await update.message.reply_text("🚫 Your account is banned.")
            return False
        
        # Clear old entries (>1 minute)
        self.user_activity[user_id] = [
            t for t in self.user_activity[user_id] 
            if now - t < timedelta(minutes=1)
        ]
        
        # Check rate limit (10 requests per minute)
        if len(self.user_activity[user_id]) >= 10:
            await update.message.reply_text(
                "⚠️ Too many requests. Please wait 1 minute.",
                parse_mode="Markdown"
            )
            return False
        
        self.user_activity[user_id].append(now)
        return True
    
    def ban_user(self, user_id: int):
        self.banned_users.add(user_id)
    
    def unban_user(self, user_id: int):
        self.banned_users.discard(user_id)

# Initialize rate limiter
rate_limiter = RateLimiter()

async def rate_limit_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await rate_limiter.check_rate_limit(update, context)

# ===== Enhanced User Profile =====
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_data = get_user(user.id)

    keyboard = []

    # Add set username button only if username is not set
    if not user.username:
        keyboard.append([InlineKeyboardButton("📝 Set Username", callback_data="set_username")])

    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="main_menu")])

    # Display custom username if set, otherwise use Telegram username
    display_username = user_data.get("custom_username", user.username)

    # Add referral progress bar
    referral_progress = min(user_data["referral_count"] / 5 * 100, 100)
    text = (
        f"👤 *Your Profile*\n\n"
        f"Name: {user.first_name}\n"
        f"Username: @{display_username or 'N/A'}\n"
        f"Join Date: {user_data['join_date']}\n"
        f"Referrals: {user_data['referral_count']}\n"
        f"Progress to Mining: {'▰' * int(referral_progress/10)}{'▱' * (10 - int(referral_progress/10))} {referral_progress:.0f}%\n"
        f"Status: {'✅ Verified' if user_data['verified'] else '❌ Not Verified'}"
    )

    await query.edit_message_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ===== MAIN FUNCTION =====
def main() -> None:
    try:
        logging.info(f"🚀 Starting bot with token: {BOT_TOKEN[:10]}...")

        # Validate token format
        if not BOT_TOKEN or len(BOT_TOKEN) < 20:
            raise ValueError("Invalid bot token format")

        application = Application.builder().token(BOT_TOKEN).build()

        # Add command handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("request", request_command))
        application.add_handler(CommandHandler("restart", restart_command))
        application.add_handler(CommandHandler("reply", reply_command))
        application.add_handler(CommandHandler("sendmessage", send_message_command))
        application.add_handler(CommandHandler("broadcast", handle_admin_broadcast))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("export", export_users_command))
        application.add_handler(CommandHandler("backup", backup_command))
        application.add_handler(CommandHandler("ban", ban_user_command))
        application.add_handler(CommandHandler("unban", unban_user_command))

        # Add callback query handlers
        application.add_handler(CallbackQueryHandler(handle_verify, pattern="^verify$"))
        application.add_handler(CallbackQueryHandler(show_channels, pattern="^show_channels$"))
        application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))
        application.add_handler(CallbackQueryHandler(show_withdraw_bots, pattern="^withdraw$"))
        application.add_handler(CallbackQueryHandler(show_all_withdraw_bots, pattern="^all_bots$"))
        application.add_handler(CallbackQueryHandler(show_premium_bots, pattern="^premium$"))
        application.add_handler(CallbackQueryHandler(show_mining_bots, pattern="^mining$"))
        application.add_handler(CallbackQueryHandler(show_profile, pattern="^profile$"))
        application.add_handler(CallbackQueryHandler(show_referral, pattern="^referral$"))
        application.add_handler(CallbackQueryHandler(show_about, pattern="^about$"))
        application.add_handler(CallbackQueryHandler(handle_need_refs, pattern="^need_refs$"))
        application.add_handler(CallbackQueryHandler(handle_mining_locked, pattern="^mining_locked$"))
        application.add_handler(CallbackQueryHandler(handle_click_bee_locked, pattern="^click_bee_locked$"))
        application.add_handler(CallbackQueryHandler(handle_set_username, pattern="^set_username$"))
        application.add_handler(CallbackQueryHandler(handle_admin_send_specific, pattern="^admin_send_specific$"))
        application.add_handler(CallbackQueryHandler(handle_admin_send_all, pattern="^admin_send_all$"))
        application.add_handler(CallbackQueryHandler(handle_admin_cancel, pattern="^admin_cancel$"))

        # Pagination handlers
        application.add_handler(CallbackQueryHandler(handle_pagination, pattern=".*_page_.*"))

        # Catch-all for unknown callbacks
        application.add_handler(CallbackQueryHandler(handle_unknown_callback))

        # Message handlers
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_messages))
        application.add_handler(MessageHandler(filters.COMMAND, show_command_menu))

        # Rate Limiting Handler
        application.add_handler(TypeHandler(Update, rate_limit_check))

        # Add Job Queue for Daily Tasks
        application.job_queue.run_repeating(daily_tasks, interval=86400, first=10)

        async def post_init(application):
            try:
                logging.info("🔧 Setting up bot commands...")
                await application.bot.set_my_commands([
                    ("start", "Start the bot and access main menu"),
                    ("help", "Show help information"),
                    ("request", "Send a message to admin"),
                    ("restart", "Restart your bot session"),
                    ("stats", "Show bot statistics (Admin only)"),
                    ("export", "Export user data (Admin only)"),
                    ("backup", "Backup database (Admin only)"),
                    ("ban", "Ban a user (Admin only)"),
                    ("unban", "Unban a user (Admin only)")
                ])
                logging.info("✅ Bot commands set successfully")
            except Exception as e:
                logging.error(f"❌ Post init error: {e}")

        application.post_init = post_init
        logging.info("🔄 Starting polling...")
        application.run_polling(
            allowed_updates=None,
            drop_pending_updates=True,
            close_loop=False
        )

    except ValueError as e:
        logging.error(f"❌ Configuration error: {e}")
        exit(1)
    except Exception as e:
        logging.error(f"❌ Critical error in main: {e}")
        import time
        time.sleep(10)
        raise e

# ===== MAIN EXECUTION =====
if __name__ == '__main__':
    # Simple logging setup
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('bot.log'),
            logging.StreamHandler()
        ]
    )
    
    logging.info("🚀 EarningClubBot Starting...")
    logging.info(f"🆔 Admin ID: {ADMIN_ID}")
    logging.info(f"🔧 Dev Mode: {DEV_MODE}")
    
    # Initialize database
    try:
        init_db()
        logging.info("✅ Database initialized")
    except Exception as e:
        logging.error(f"❌ Database error: {e}")
        exit(1)

    # Auto-restart loop
    while True:
        try:
            main()
        except KeyboardInterrupt:
            logging.info("🛑 Bot stopped by user")
            break
        except Exception as e:
            logging.error(f"💥 Bot crashed: {e}")
            logging.info("🔄 Restarting in 10 seconds...")
            time.sleep(10)
