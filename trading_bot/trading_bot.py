import sqlite3
from datetime import datetime, timedelta
import pytz
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, filters
)

# ================= CONFIG =================
BOT_TOKEN = "8251117512:AAGQaACbjQV525_fNNlEMoM1wD21g9jlSsQ"  # <- replace with BotFather token
GROUP_CHAT_ID = -1003108578811          # <- replace with your group chat_id
ADMIN_USERNAMES = ["eemmje", "Razzled123x"]         # <- replace with your Telegram usernames (no @)

JAKARTA_TZ = pytz.timezone("Asia/Jakarta")

# ================ DATABASE ================
conn = sqlite3.connect("trades.db", check_same_thread=False)
c = conn.cursor()

# ============== HELPER FUNCS ==============
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
async def trade_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a trade P/L entry: /trade add SYMBOL AMOUNT"""
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

async def trade_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit a trade by ID: /trade edit ID NEW_AMOUNT"""
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

async def trade_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a trade by ID: /trade delete ID"""
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

async def trade_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List trades with filters:
    /trade list [--user @username|me] [--symbol SYMBOL] [--from YYYY-MM-DD] [--to YYYY-MM-DD]
    """
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
    await update.message.reply_text(msg)

# ================ COMMANDS (POSITIONS) ================
async def pos_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a position: /pos add SYMBOL QTY AVG_PRICE"""
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

async def pos_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit a position: /pos edit ID QTY AVG_PRICE"""
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

async def pos_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a position: /pos delete ID"""
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

async def pos_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List positions:
    /pos list [--user @username|me]
    """
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

async def pos_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Group positions with totals and weighted average: /pos all"""
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

async def recap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/recap daily|weekly|monthly"""
    period = (context.args[0].lower() if context.args else "monthly")
    if period not in ("daily", "weekly", "monthly"):
        await update.message.reply_text("Usage: /recap [daily|weekly|monthly]")
        return
    await recap(update, context, period)

async def weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await recap(update, context, "weekly")

async def monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await recap(update, context, "monthly")

# ================ LEADERBOARD =================
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# ============== ADMIN POSADD ==============
async def admin_pos_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /admin pos add USER SYMBOL QTY AVG_PRICE"""
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

# ================== MAIN ==================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
📘 *Panduan Bot Trading*

    📝 *Catat/Edit/Hapus Transaksi (Day Trading)*
    `/trade add SAHAM JUMLAH`
    `/trade edit ID JUMLAH_BARU`
    `/trade delete ID`
    `/trade list` → List transaksi (ada filter)
    Contoh:
    `/trade add PSDN +6300000`
    `/trade add BBRI -2000000`
    
    🏦 *Catat/Edit/Hapus Posisi Saham (Swing Trading)*
    `/pos add SAHAM JUMLAH HARGA_RATA`
    `/pos edit ID JUMLAH_BARU HARGA_RATA_BARU`
    `/pos delete ID`
    `/pos list` → List posisi (ada filter)
    `/pos all` → Semua posisi + group totals & average

    Admin: `/admin pos add USER SAHAM JUMLAH HARGA_RATA`
    
    📊 *Rekap*
    `/recap daily|weekly|monthly`
    (Daily recap otomatis jam 16:00 WIB)
    
    🏆 *Leaderboard*
    `/leaderboard` → Ranking bulanan
    
    🔍 *Stock Spesifik*
    `/stock KODE` → Lihat transaksi per saham
    
    👤 *Statistik Pribadi*
    `/mystats` → Statistik bulan ini
    
    ℹ️ *Bantuan*
    `/help` → Tampilkan panduan ini
    """
    await update.message.reply_text(msg, parse_mode="Markdown")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    job_queue = app.job_queue

    # TRADES
    app.add_handler(CommandHandler("trade_add", trade_add))
    app.add_handler(CommandHandler("trade_edit", trade_edit))
    app.add_handler(CommandHandler("trade_delete", trade_delete))
    app.add_handler(CommandHandler("trade_list", trade_list))
    app.add_handler(CommandHandler("pl", trade_add))  # alias

    # POSITIONS
    app.add_handler(CommandHandler("pos_add", pos_add))
    app.add_handler(CommandHandler("pos_edit", pos_edit))
    app.add_handler(CommandHandler("pos_delete", pos_delete))
    app.add_handler(CommandHandler("pos_list", pos_list))
    app.add_handler(CommandHandler("pos_all", pos_all))
    app.add_handler(CommandHandler("admin_pos_add", admin_pos_add))
    app.add_handler(CommandHandler("pos", pos_add))  # alias

    # RECAPS
    app.add_handler(CommandHandler("recap", recap_command))
    app.add_handler(CommandHandler("weekly", weekly))
    app.add_handler(CommandHandler("monthly", monthly))

    # STATS
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("stock", stock))
    app.add_handler(CommandHandler("mystats", mystats))

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
    app.run_polling()

if __name__ == "__main__":
    main()
