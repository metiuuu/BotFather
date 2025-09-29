
# 📘 Trading Bot Documentation

## 1. Overview
This Telegram bot helps our trading group log and manage:
- Daily trade profit/loss (P/L)
- Swing trading positions (lots + average price)
- Daily, weekly, monthly recaps
- Leaderboard ranking
- Stock-specific stats and personal stats

Built using:
- Python 3
- [python-telegram-bot](https://docs.python-telegram-bot.org/)
- SQLite for storage
- Alembic for migrations

---

## 2. Installation on VPS

### Step 1 — Connect to VPS
```bash
ssh user@your-vps-ip
```

### Step 2 — Install Dependencies
```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip tmux sqlite3 git
```

### Step 3 — Setup Project
```bash
git clone https://github.com/metiuuu/wiguna-telegram.git
cd wiguna-telegram
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 3. Configuration
Inside `trading_bot.py`, configure:
```python
BOT_TOKEN = "YOUR_BOTFATHER_TOKEN"
GROUP_CHAT_ID = -100XXXXXXXXX
ADMIN_USERNAME = "yourusername"  # without @
```

---

## 4. Running the Bot

### Option A — Using tmux (simple & effective)
```bash
tmux new -s tradingbot
source venv/bin/activate
python trading_bot.py
```
Detach: `Ctrl+B, D`  
Reattach: `tmux attach -t tradingbot`  

### Option B — Using systemd (auto-start on reboot)
Create a service:
```bash
sudo nano /etc/systemd/system/tradingbot.service
```
Content:
```
[Unit]
Description=Telegram Trading Bot
After=network.target

[Service]
ExecStart=/root/tradingbot/venv/bin/python /root/tradingbot/trading_bot.py
WorkingDirectory=/root/tradingbot
StandardOutput=append:/var/log/tradingbot.log
StandardError=append:/var/log/tradingbot.log
Restart=always
User=root

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable tradingbot
sudo systemctl start tradingbot
```

Check logs:
```bash
sudo journalctl -u tradingbot -f
```

---

## 5. Bot Commands

### 📌 Logging Trades
```
/pl STOCK AMOUNT
```

### ✏️ Edit & Delete Trades
```
/edit ID NEW_AMOUNT
/delete ID
```

### 🏦 Swing Trading Positions
```
/pos STOCK QTY AVG_PRICE
/mypos
/positions
/posedit ID NEW_QTY NEW_AVG
/posdel ID
```

### 📊 Recaps
```
/weekly
/monthly
```

### 🏆 Leaderboard
```
/leaderboard
```

### 🔍 Stock-Specific
```
/stock SYMBOL
```

### 👤 Personal Stats
```
/mystats
```

### 📘 Help
```
/help
```

---

## 6. Database
- **logs** → stores trades (user, stock, amount, date)
- **positions** → stores swing positions (user, stock, qty, avg_price, date, created_at, updated_at)

SQLite file: `trades.db`

---

## 7. Admin Privileges
- Admin can edit/delete **any trade or position**
- Normal users can only edit/delete **their own**

Configured via `ADMIN_USERNAME`.

---

## 8. Python Dependencies
From `pip freeze`:
```
alembic==1.16.5
anyio==4.11.0
APScheduler==3.11.0
certifi==2025.8.3
exceptiongroup==1.3.0
greenlet==3.2.4
h11==0.16.0
httpcore==1.0.9
httpx==0.28.1
idna==3.10
Mako==1.3.10
MarkupSafe==3.0.3
python-telegram-bot==22.5
pytz==2025.2
sniffio==1.3.1
SQLAlchemy==2.0.43
tomli==2.2.1
typing_extensions==4.15.0
tzlocal==5.3.1
```

These should also be captured in a `requirements.txt` file for reproducibility.

---

## 9. Notes
- Keep bot running with tmux or systemd.
- Backup `trades.db` regularly to avoid data loss.
- Update bot by pulling new code and restarting service.

🚀 Happy Trading & Logging!
