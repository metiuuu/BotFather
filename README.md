# 📘 Trading Bot Documentation

## 1. Overview

This Telegram bot helps our trading group log and manage: - Daily trade
profit/loss (P/L) - Swing trading positions (lots + average price) -
Daily, weekly, monthly recaps - Leaderboard ranking - Stock-specific
stats and personal stats

Built using: - Python 3 -
[python-telegram-bot](https://docs.python-telegram-bot.org/) - SQLite
for storage

------------------------------------------------------------------------

## 2. Installation on VPS

### Step 1 --- Connect to VPS

``` bash
ssh user@your-vps-ip
```

### Step 2 --- Install Dependencies

``` bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip tmux sqlite3
```

### Step 3 --- Setup Project

``` bash
mkdir ~/tradingbot && cd ~/tradingbot
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install "python-telegram-bot[job-queue]"
```

### Step 4 --- Add Bot Script

Save the `trading_bot.py` code into `~/tradingbot/trading_bot.py`.

------------------------------------------------------------------------

## 3. Configuration

Inside `trading_bot.py`, configure:

``` python
BOT_TOKEN = "YOUR_BOTFATHER_TOKEN"
GROUP_CHAT_ID = -100XXXXXXXXX
ADMIN_USERNAME = "yourusername"  # without @
```

------------------------------------------------------------------------

## 4. Running the Bot

### Option A --- Using tmux (simple & effective)

``` bash
tmux new -s tradingbot
source ~/tradingbot/venv/bin/activate
python trading_bot.py
```

Detach: `Ctrl+B, D`\
Reattach: `tmux attach -t tradingbot`

### Option B --- Using systemd (auto-start on reboot)

Create a service:

``` bash
sudo nano /etc/systemd/system/tradingbot.service
```

Content:

    [Unit]
    Description=Telegram Trading Bot
    After=network.target

    [Service]
    ExecStart=/home/youruser/tradingbot/venv/bin/python /home/youruser/tradingbot/trading_bot.py
    WorkingDirectory=/home/youruser/tradingbot
    StandardOutput=append:/var/log/tradingbot.log
    StandardError=append:/var/log/tradingbot.log
    Restart=always
    User=youruser

    [Install]
    WantedBy=multi-user.target

Enable and start:

``` bash
sudo systemctl daemon-reload
sudo systemctl enable tradingbot
sudo systemctl start tradingbot
```

Check logs:

``` bash
sudo journalctl -u tradingbot -f
```

------------------------------------------------------------------------

## 5. Bot Commands

### 📌 Logging Trades

    /pl STOCK AMOUNT

Example:

    /pl PSDN +6300000
    /pl BBRI -2000000

### ✏️ Edit & Delete Trades

    /edit ID NEW_AMOUNT
    /delete ID

### 🏦 Swing Trading Positions

    /pos STOCK QTY AVG_PRICE
    /mypos
    /positions
    /posedit ID NEW_QTY NEW_AVG
    /posdel ID

### 📊 Recaps

    /weekly
    /monthly

(Daily recap auto-posted at 16:00 WIB)

### 🏆 Leaderboard

    /leaderboard

### 🔍 Stock-Specific

    /stock SYMBOL

### 👤 Personal Stats

    /mystats

### 📘 Help

    /help

------------------------------------------------------------------------

## 6. Database

-   **logs** → stores trades (user, stock, amount, date)
-   **positions** → stores swing positions (user, stock, qty, avg_price,
    date)

SQLite file: `trades.db`

------------------------------------------------------------------------

## 7. Admin Privileges

-   Admin can edit/delete **any trade or position**
-   Normal users can only edit/delete **their own**

Configured via `ADMIN_USERNAME`.

------------------------------------------------------------------------

## 8. Notes

-   Keep bot running with tmux or systemd.
-   Backup `trades.db` regularly to avoid data loss.
-   Update bot by pulling new code and restarting service.

🚀 Happy Trading & Logging!
