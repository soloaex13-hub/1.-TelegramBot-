# Earning Club Telegram Bot

A Telegram bot for crypto earning and referral tracking, with a verification system, admin tools, and a 24/7 keep-alive Flask server.

---

## 🌐 Features

- User referral tracking with rewards
- Channel membership verification
- Admin broadcast, reply, and user messaging
- Free, premium, and mining bot directories
- SQLite database for persistent storage
- Flask-based keep-alive server for uptime
- Compatible with [Render.com](https://render.com) deployment

---

## 🚀 Deploy on Render

1. **Push this code to GitHub**
2. **Create a Web Service on Render**
   - Runtime: Python
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python main.py`
3. **Set Environment Variables**:
   - `BOT_TOKEN`: Your bot token from @BotFather
   - `ADMIN_ID`: Your Telegram numeric user ID
   - `DEV_MODE`: Optional (True or False)

---

## 🧪 Local Development

```bash
pip install -r requirements.txt
python main.py
```

---

## 📂 Project Structure

```
earning_club_bot/
├── main.py             # Bot code with Flask keep-alive
├── requirements.txt    # Dependencies
├── README.md           # This file
```

---

## 📬 Credits

Developed for Earning Club Crypto community.

For support or collaboration, contact the admin via the bot.
