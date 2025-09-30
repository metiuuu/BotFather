import os
import sqlite3
from datetime import datetime, timedelta

import pytz
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("TRADING_BOT_TOKEN")  # <- replace with BotFather token
GROUP_CHAT_ID = os.getenv("TRADING_GROUP_ID")          # <- replace with your group chat_id
ADMIN_USERNAMES = ["eemmje", "Razzled123x"]         # <- replace with your Telegram usernames (no @)

JAKARTA_TZ = pytz.timezone("Asia/Jakarta")

# ================ DATABASE ================
conn = sqlite3.connect("trades.db", check_same_thread=False)
c = conn.cursor()

# ============== HELPER FUNCS ==============
def safe_handler(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            await func(update, context)
        except Exception as e:
            print(f"⚠️ Error in {func.__name__}: {e}")
            if update.message:
                await update.message.reply_text(f"⚠️ Terjadi error: {e}")
    return wrapper

async def maybe_delete_command(update: Update):
    """Try to delete the user's command message to reduce chat clutter.
    Requires the bot to have 'Delete messages' admin permission in groups.
    Silently ignores failures (e.g., lack of permission or 48h limit).
    """
    try:
        if update and getattr(update, "message", None):
            await update.message.delete()
    except Exception as e:
        # Don't break command flow if deletion fails
        print(f"⚠️ Could not delete command message: {e}")

def format_amount(amount: float) -> str:
    emoji = "📈" if amount > 0 else "📉" if amount < 0 else "➖"
    return f"{amount:+,.0f} {emoji}"

def today_str():
    return datetime.now(JAKARTA_TZ).strftime("%Y-%m-%d")

def parse_flags(args: list[str]) -> dict:
    """Minimal flag parser for commands like /trade list and /pos list"""
    flags = {"--user": None, "--symbol": None, "--from": None, "--to": None, "args": []}
    i = 0
    while i < len(args):
        tok = args[i]
        if tok in ("--user", "--symbol", "--from", "--to"):
            if i + 1 < len(args):
                flags[tok] = args[i + 1]
                i += 2
            else:
                flags["args"].append(tok)
                i += 1
        else:
            flags["args"].append(tok)
            i += 1
    return flags

def user_is_admin(update: Update) -> bool:
    username = (update.effective_user.username or "").lower()
    return username in [u.lower() for u in ADMIN_USERNAMES]

def effective_owner(update: Update) -> str:
    """Prefer Telegram username (stable) fallback to first_name"""
    uname = update.effective_user.username
    return ("@" + uname) if uname else update.effective_user.first_name

def stored_owner_key(update: Update) -> tuple[str, str]:
    """Return tuple (display_name, ownership_key) where ownership_key is used for DB compare"""
    uname = update.effective_user.username
    if uname:
        return (update.effective_user.first_name, uname.lower())
    return (update.effective_user.first_name, update.effective_user.first_name)

# ================ COMMANDS (TRADES) ================
@safe_handler
async def trade_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a trade P/L entry: /trade add SYMBOL AMOUNT"""
    await maybe_delete_command(update)
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /trade add SYMBOL AMOUNT")
        return
    stock = context.args[0].upper()
    try:
        amount = float(context.args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Amount must be a number")
        return
    display_name, owner_key = stored_owner_key(update)
    date = today_str()
    c.execute("INSERT INTO logs (user, stock, amount, date) VALUES (?, ?, ?, ?)",
              (display_name, stock, amount, date))
    conn.commit()
    await update.message.reply_text(f"✅ Logged {stock} {format_amount(amount)} for {display_name}")

@safe_handler
async def trade_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit a trade by ID: /trade edit ID NEW_AMOUNT"""
    await maybe_delete_command(update)
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /trade edit ID NEW_AMOUNT")
        return
    trade_id = context.args[0]
    try:
        new_amount = float(context.args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Amount must be a number")
        return
    display_name, owner_key = stored_owner_key(update)
    username = update.effective_user.username or ""
    c.execute("SELECT id, user FROM logs WHERE id=?", (trade_id,))
    row = c.fetchone()
    if not row:
        await update.message.reply_text("❌ Trade not found")
        return
    owner_display = row[1]
    # Allow if admin or same display name (backward compatible)
    if owner_display != display_name and not user_is_admin(update):
        await update.message.reply_text("⛔ You can only edit your own trades")
        return
    c.execute("UPDATE logs SET amount=? WHERE id=?", (new_amount, trade_id))
    conn.commit()
    await update.message.reply_text(f"✏️ Updated trade {trade_id} → {format_amount(new_amount)}")

@safe_handler
async def trade_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a trade by ID: /trade delete ID"""
    await maybe_delete_command(update)
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /trade delete ID")
        return
    trade_id = context.args[0]
    display_name, owner_key = stored_owner_key(update)
    c.execute("SELECT id, user FROM logs WHERE id=?", (trade_id,))
    row = c.fetchone()
    if not row:
        await update.message.reply_text("❌ Trade not found")
        return
    owner_display = row[1]
    if owner_display != display_name and not user_is_admin(update):
        await update.message.reply_text("⛔ You can only delete your own trades")
        return
    c.execute("DELETE FROM logs WHERE id=?", (trade_id,))
    conn.commit()
    await update.message.reply_text(f"🗑️ Deleted trade {trade_id}")

@safe_handler
async def trade_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List trades with filters:
    /trade list [--user @username|me] [--symbol SYMBOL] [--from YYYY-MM-DD] [--to YYYY-MM-DD]
    """
    await maybe_delete_command(update)
    f = parse_flags(context.args)
    user_filter = f["--user"]
    symbol_filter = f["--symbol"]
    from_filter = f["--from"]
    to_filter = f["--to"]

    params = []
    where = []
    if user_filter:
        if user_filter.lower() == "me":
            display_name, _ = stored_owner_key(update)
            where.append("user = ?")
            params.append(display_name)
        elif user_filter.startswith("@"):
            # We only stored display names historically; best effort: match first_name equal to me if @me, else cannot map reliably.
            await update.message.reply_text("⚠️ Filtering by @username not fully supported yet; use --user me or omit.")
        else:
            where.append("user = ?")
            params.append(user_filter)
    if symbol_filter:
        where.append("stock = ?")
        params.append(symbol_filter.upper())
    if from_filter:
        where.append("date >= ?")
        params.append(from_filter)
    if to_filter:
        where.append("date <= ?")
        params.append(to_filter)

    query = "SELECT user, stock, amount, date, id FROM logs"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY date DESC, id DESC"
    c.execute(query, tuple(params))
    trades = c.fetchall()

    if not trades:
        await update.message.reply_text("📊 No trades found for given filters.")
        return

    # Group by user for compactness
    summary = {}
    total = 0.0
    for user, stock, amount, date, tid in trades:
        summary.setdefault(user, []).append((date, tid, stock, amount))
        total += amount

    msg = "📊 Trades\n\n"
    for user, items in summary.items():
        msg += f"{user}:\n"
        for date, tid, stock, amount in items[:50]:
            msg += f"  [{tid}] {date} {stock}: {format_amount(amount)}\n"
        if len(items) > 50:
            msg += f"  ... and {len(items)-50} more\n"
        msg += "\n"
    msg += f"💰 Group Total: {total:+,.0f} {'✅' if total>=0 else '❌'}"
    # Split long messages into 4000-char chunks to avoid Telegram limits
    MAX_LEN = 4000
    for i in range(0, len(msg), MAX_LEN):
        await update.message.reply_text(msg[i:i + MAX_LEN])


# ================ TRADES ALL SHORTCUT ================
@safe_handler
async def trades_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shortcut: list all trades (no filters)"""
    await maybe_delete_command(update)
    # Call trade_list with no args
    context.args = []
    await trade_list(update, context)

# ================ COMMANDS (POSITIONS) ================
@safe_handler
async def pos_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a position: /pos add SYMBOL QTY AVG_PRICE"""
    await maybe_delete_command(update)
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /pos add SYMBOL QTY AVG_PRICE")
        return
    stock = context.args[0].upper()
    try:
        quantity = float(context.args[1].replace(",", ""))
        avg_price = float(context.args[2].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Quantity and Avg Price must be numbers")
        return
    display_name, owner_key = stored_owner_key(update)
    date = today_str()
    now_str = datetime.now(JAKARTA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO positions (user, stock, quantity, avg_price, date, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (display_name, stock, quantity, avg_price, date, now_str, now_str)
    )
    conn.commit()
    await update.message.reply_text(f"✅ Logged position {stock} Qty: {quantity} Avg Price: {avg_price} for {display_name}")

@safe_handler
async def pos_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit a position: /pos edit ID QTY AVG_PRICE"""
    await maybe_delete_command(update)
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /pos edit ID QTY AVG_PRICE")
        return
    pos_id = context.args[0]
    try:
        new_qty = float(context.args[1].replace(",", ""))
        new_avg = float(context.args[2].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Quantity and Avg Price must be numbers")
        return
    display_name, owner_key = stored_owner_key(update)
    c.execute("SELECT user FROM positions WHERE id=?", (pos_id,))
    row = c.fetchone()
    if not row:
        await update.message.reply_text("❌ Position not found")
        return
    owner_display = row[0]
    if owner_display != display_name and not user_is_admin(update):
        await update.message.reply_text("⛔ You can only edit your own positions")
        return
    now_str = datetime.now(JAKARTA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "UPDATE positions SET quantity=?, avg_price=?, updated_at=? WHERE id=?",
        (new_qty, new_avg, now_str, pos_id)
    )
    conn.commit()
    await update.message.reply_text(f"✏️ Updated position {pos_id} → Qty: {new_qty}, Avg Price: {new_avg}")

@safe_handler
async def pos_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a position: /pos delete ID"""
    await maybe_delete_command(update)
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /pos delete ID")
        return
    pos_id = context.args[0]
    display_name, owner_key = stored_owner_key(update)
    c.execute("SELECT user FROM positions WHERE id=?", (pos_id,))
    row = c.fetchone()
    if not row:
        await update.message.reply_text("❌ Position not found")
        return
    owner_display = row[0]
    if owner_display != display_name and not user_is_admin(update):
        await update.message.reply_text("⛔ You can only delete your own positions")
        return
    c.execute("DELETE FROM positions WHERE id=?", (pos_id,))
    conn.commit()
    await update.message.reply_text(f"🗑️ Deleted position {pos_id}")

@safe_handler
async def pos_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List positions:
    /pos list [--user @username|me]
    """
    await maybe_delete_command(update)
    f = parse_flags(context.args)
    user_filter = f["--user"]
    params = []
    where = []
    if user_filter:
        if user_filter.lower() == "me":
            display_name, _ = stored_owner_key(update)
            where.append("user = ?")
            params.append(display_name)
        else:
            where.append("user = ?")
            params.append(user_filter)
    query = "SELECT user, stock, quantity, avg_price FROM positions"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY user"
    c.execute(query, tuple(params))
    rows = c.fetchall()
    if not rows:
        await update.message.reply_text("📊 No positions found.")
        return

    summary = {}
    for user, stock, quantity, avg_price in rows:
        summary.setdefault(user, []).append((stock, quantity, avg_price))

    msg = "📊 Positions\n\n"
    for user, positions in summary.items():
        msg += f"{user}:\n"
        for stock, quantity, avg_price in positions:
            msg += f"  - {stock}: Qty={quantity}, Avg Price={avg_price}\n"
        msg += "\n"
    await update.message.reply_text(msg)

@safe_handler
async def pos_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Group positions with totals and weighted average: /pos all"""
    await maybe_delete_command(update)
    c.execute("SELECT user, stock, quantity, avg_price FROM positions ORDER BY user")
    rows = c.fetchall()
    if not rows:
        await update.message.reply_text("📊 No positions found.")
        return
    summary = {}
    stock_totals = {}
    for user, stock, quantity, avg_price in rows:
        summary.setdefault(user, []).append((stock, quantity, avg_price))
        if stock not in stock_totals:
            stock_totals[stock] = {"total_qty": 0.0, "total_amount": 0.0}
        stock_totals[stock]["total_qty"] += quantity
        stock_totals[stock]["total_amount"] += quantity * avg_price
    msg = "📊 All Positions:\n\n"
    for user, positions in summary.items():
        msg += f"{user}:\n"
        for stock, quantity, avg_price in positions:
            msg += f"  - {stock}: Qty={quantity}, Avg Price={avg_price}\n"
        msg += "\n"
    msg += "------\n🧮 Group Stock Totals:\n"
    for stock, data in stock_totals.items():
        total_qty = data["total_qty"]
        total_amt = data["total_amount"]
        avg_price = (total_amt / total_qty) if total_qty != 0 else 0
        msg += f"{stock}: Total Qty={total_qty}, Group Avg Price={avg_price:.2f}\n"
    await update.message.reply_text(msg)

# ========== DAILY / WEEKLY / MONTHLY ==========
@safe_handler
async def daily_recap(context: ContextTypes.DEFAULT_TYPE):
    """Auto recap at 16:00 WIB"""
    today = today_str()
    c.execute("SELECT user, stock, amount FROM logs WHERE date=?", (today,))
    trades = c.fetchall()

    if not trades:
        msg = f"📊 Daily Recap — {today}\n\nNo trades logged today."
    else:
        summary = {}
        total = 0
        for user, stock, amount in trades:
            summary.setdefault(user, []).append((stock, amount))
            total += amount

        msg = f"📊 Daily Recap — {today}\n\n"
        for user, logs in summary.items():
            msg += f"{user}:\n"
            for stock, amount in logs:
                msg += f"  - {stock}: {format_amount(amount)}\n"
            msg += "\n"
        msg += f"💰 Group Total: {total:+,.0f} {'✅' if total>=0 else '❌'}"

    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)

@safe_handler
async def recap(update: Update, context: ContextTypes.DEFAULT_TYPE, period: str):
    """Generic recap: weekly or monthly"""
    today = datetime.now(JAKARTA_TZ)
    if period == "weekly":
        start = today - timedelta(days=7)
        title = "📅 Weekly Recap"
    elif period == "daily":
        start = today
        title = "📅 Daily Recap"
    else:
        start = today.replace(day=1)
        title = "📅 Monthly Recap"

    start_str = start.strftime("%Y-%m-%d")
    c.execute("SELECT user, stock, amount FROM logs WHERE date>=?", (start_str,))
    trades = c.fetchall()

    if not trades:
        await update.message.reply_text(f"{title}\n\nNo trades found.")
        return

    summary = {}
    total = 0
    for user, stock, amount in trades:
        summary.setdefault(user, []).append((stock, amount))
        total += amount

    msg = f"{title}\n\n"
    for user, logs in summary.items():
        subtotal = sum(a for _, a in logs)
        msg += f"{user}: {subtotal:+,.0f} {'📈' if subtotal>=0 else '📉'}\n"
    msg += f"\n💰 Group Total: {total:+,.0f} {'✅' if total>=0 else '❌'}"

    await update.message.reply_text(msg)

@safe_handler
async def recap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/recap daily|weekly|monthly"""
    await maybe_delete_command(update)
    period = (context.args[0].lower() if context.args else "monthly")
    if period not in ("daily", "weekly", "monthly"):
        await update.message.reply_text("Usage: /recap [daily|weekly|monthly]")
        return
    await recap(update, context, period)

@safe_handler
async def weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await maybe_delete_command(update)
    await recap(update, context, "weekly")

@safe_handler
async def monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await maybe_delete_command(update)
    await recap(update, context, "monthly")

# ================ LEADERBOARD =================
@safe_handler
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await maybe_delete_command(update)
    today = datetime.now(JAKARTA_TZ)
    start = today.replace(day=1)
    start_str = start.strftime("%Y-%m-%d")

    c.execute("SELECT user, SUM(amount) FROM logs WHERE date>=? GROUP BY user ORDER BY SUM(amount) DESC", (start_str,))
    rows = c.fetchall()

    if not rows:
        await update.message.reply_text("🏆 Leaderboard\n\nNo trades yet.")
        return

    msg = "🏆 Leaderboard — This Month\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (user, total) in enumerate(rows, start=1):
        medal = medals[i-1] if i <= 3 else f"{i}."
        msg += f"{medal} {user}: {total:+,.0f} {'📈' if total>=0 else '📉'}\n"

    await update.message.reply_text(msg)

# ================ STOCK FILTER =================
@safe_handler
async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await maybe_delete_command(update)
    if not context.args:
        await update.message.reply_text("Usage: /stock SYMBOL")
        return

    symbol = context.args[0].upper()
    c.execute("SELECT user, amount FROM logs WHERE stock=?", (symbol,))
    trades = c.fetchall()

    if not trades:
        await update.message.reply_text(f"📊 No trades for {symbol}")
        return

    summary = {}
    total = 0
    for user, amount in trades:
        summary.setdefault(user, []).append(amount)
        total += amount

    msg = f"📊 Trades for {symbol}\n\n"
    for user, amounts in summary.items():
        subtotal = sum(amounts)
        for amt in amounts:
            msg += f"  {user}: {format_amount(amt)}\n"
        msg += f"  Subtotal: {subtotal:+,.0f} {'💰'}\n\n"

    msg += f"Group Net: {total:+,.0f} {'✅' if total>=0 else '❌'}"
    await update.message.reply_text(msg)

# ================ MY STATS =================
@safe_handler
async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await maybe_delete_command(update)
    user = update.effective_user.first_name
    today = datetime.now(JAKARTA_TZ)
    start = today.replace(day=1)
    start_str = start.strftime("%Y-%m-%d")

    c.execute("SELECT stock, amount FROM logs WHERE user=? AND date>=?", (user, start_str))
    trades = c.fetchall()

    if not trades:
        await update.message.reply_text(f"📊 No trades for {user} this month")
        return

    summary = {}
    total = 0
    for stock, amount in trades:
        summary.setdefault(stock, 0)
        summary[stock] += amount
        total += amount

    msg = f"📊 My Stats — {today.strftime('%b %Y')} ({user})\n\n"
    for stock, amt in summary.items():
        msg += f"{stock}: {format_amount(amt)}\n"
    msg += f"\n💰 Total: {total:+,.0f} {'✅' if total>=0 else '❌'}"

    await update.message.reply_text(msg)

# ============== ADMIN COMMANDS ==============
@safe_handler
async def admin_pos_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /admin pos add USER SYMBOL QTY AVG_PRICE"""
    await maybe_delete_command(update)
    if not user_is_admin(update):
        await update.message.reply_text("⛔ Only admins can use /admin pos add")
        return
    if len(context.args) < 4:
        await update.message.reply_text("Usage: /admin pos add USER SYMBOL QTY AVG_PRICE")
        return

    user = context.args[0]
    stock = context.args[1].upper()
    try:
        quantity = float(context.args[2].replace(",", ""))
        avg_price = float(context.args[3].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Quantity and Avg Price must be numbers")
        return

    date = today_str()
    now_str = datetime.now(JAKARTA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO positions (user, stock, quantity, avg_price, date, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user, stock, quantity, avg_price, date, now_str, now_str)
    )
    conn.commit()

    await update.message.reply_text(f"✅ Added position {stock} Qty: {quantity} Avg Price: {avg_price} for {user}")


# ============== ADMIN TRADE ADD ==============
@safe_handler
async def admin_trade_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /admin trade add USER SYMBOL AMOUNT"""
    await maybe_delete_command(update)
    if not user_is_admin(update):
        await update.message.reply_text("⛔ Only admins can use /admin trade add")
        return
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /admin trade add USER SYMBOL AMOUNT")
        return
    user = context.args[0]
    stock = context.args[1].upper()
    try:
        amount = float(context.args[2].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Amount must be a number")
        return
    date = today_str()
    c.execute("INSERT INTO logs (user, stock, amount, date) VALUES (?, ?, ?, ?)",
              (user, stock, amount, date))
    conn.commit()
    await update.message.reply_text(f"✅ Added trade {stock} {format_amount(amount)} for {user}")

 # ================== MAIN ==================
@safe_handler
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await maybe_delete_command(update)
    msg = """
📘 Panduan Cepat Bot Trading

Trades
- Add: /tadd SYMBOL AMOUNT
- Edit: /tedit ID NEW_AMOUNT
- Delete: /tdel ID
- List: /tlist [--user me|NAME] [--symbol SYM] [--from YYYY-MM-DD] [--to YYYY-MM-DD]

Positions
- Add: /padd SYMBOL QTY AVG_PRICE
- Edit: /pedit ID NEW_QTY NEW_AVG_PRICE
- Delete: /pdel ID
- List: /plist [--user me|NAME]
- Summary: /pall

Recaps
- /rc daily|weekly|monthly
- /wd (weekly), /mo (monthly)

Stats
- /lb — Leaderboard
- /s SYMBOL — Stock view
- /me — My stats

Admin
- /admin_trade_add USER SYMBOL AMOUNT
- /admin_pos_add USER SYMBOL QTY AVG_PRICE

Tips
- Numbers can use +/− and commas, e.g. +1,250,000
- Trade AMOUNT is per-trade P/L
"""
    await update.message.reply_text(msg, parse_mode="Markdown")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    job_queue = app.job_queue

    # TRADES (new commands only)
    app.add_handler(CommandHandler("tadd", trade_add))
    app.add_handler(CommandHandler("tedit", trade_edit))
    app.add_handler(CommandHandler("tdel", trade_delete))
    app.add_handler(CommandHandler("tlist", trade_list))
    app.add_handler(CommandHandler("admin_trade_add", admin_trade_add))

    # POSITIONS (new commands only)
    app.add_handler(CommandHandler("padd", pos_add))
    app.add_handler(CommandHandler("pedit", pos_edit))
    app.add_handler(CommandHandler("pdel", pos_delete))
    app.add_handler(CommandHandler("plist", pos_list))
    app.add_handler(CommandHandler("pall", pos_all))
    app.add_handler(CommandHandler("admin_pos_add", admin_pos_add))

    # RECAPS (new commands only)
    app.add_handler(CommandHandler("rc", recap_command))
    app.add_handler(CommandHandler("wd", weekly))
    app.add_handler(CommandHandler("mo", monthly))

    # STATS (new commands only)
    app.add_handler(CommandHandler("lb", leaderboard))
    app.add_handler(CommandHandler("s", stock))
    app.add_handler(CommandHandler("me", mystats))

    # HELP
    app.add_handler(CommandHandler("help", help_command))

    # Daily recap at 18:00 WIB
    job_queue.run_daily(
        daily_recap,
        time=datetime.now(JAKARTA_TZ).replace(hour=18, minute=0, second=0, microsecond=0).timetz(),
        days=(0,1,2,3,4),  # Mon-Fri
        name="daily_recap"
    )

    print("🚀 Bot running...")

    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        print(f"⚠️ Unhandled error: {context.error}")
        if getattr(update, "message", None):
            await update.message.reply_text(f"⚠️ Terjadi error: {context.error}")

    app.add_error_handler(error_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
