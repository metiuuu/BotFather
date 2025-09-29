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
ADMIN_USERNAME = "eemmje"         # <- replace with your Telegram username (no @)

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

# ================ COMMANDS ================
async def pl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log a trade"""
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /pl STOCK AMOUNT")
        return

    stock = context.args[0].upper()
    try:
        amount = float(context.args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Amount must be a number")
        return

    user = update.effective_user.first_name
    date = today_str()

    c.execute("INSERT INTO logs (user, stock, amount, date) VALUES (?, ?, ?, ?)",
              (user, stock, amount, date))
    conn.commit()

    await update.message.reply_text(f"✅ Logged {stock} {format_amount(amount)} for {user}")

async def edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit a trade by ID"""
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /edit ID NEW_AMOUNT")
        return

    trade_id = context.args[0]
    try:
        new_amount = float(context.args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Amount must be a number")
        return

    user = update.effective_user.first_name
    username = update.effective_user.username or ""

    c.execute("SELECT user FROM logs WHERE id=?", (trade_id,))
    row = c.fetchone()
    if not row:
        await update.message.reply_text("❌ Trade not found")
        return

    owner = row[0]
    if owner != user and username != ADMIN_USERNAME:
        await update.message.reply_text("⛔ You can only edit your own trades")
        return

    c.execute("UPDATE logs SET amount=? WHERE id=?", (new_amount, trade_id))
    conn.commit()
    await update.message.reply_text(f"✏️ Updated trade {trade_id} → {format_amount(new_amount)}")

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a trade by ID"""
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /delete ID")
        return

    trade_id = context.args[0]
    user = update.effective_user.first_name
    username = update.effective_user.username or ""

    c.execute("SELECT user FROM logs WHERE id=?", (trade_id,))
    row = c.fetchone()
    if not row:
        await update.message.reply_text("❌ Trade not found")
        return

    owner = row[0]
    if owner != user and username != ADMIN_USERNAME:
        await update.message.reply_text("⛔ You can only delete your own trades")
        return

    c.execute("DELETE FROM logs WHERE id=?", (trade_id,))
    conn.commit()
    await update.message.reply_text(f"🗑️ Deleted trade {trade_id}")

async def posedit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit a position by ID"""
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /posedit ID NEW_QTY NEW_AVG")
        return

    pos_id = context.args[0]
    try:
        new_qty = float(context.args[1].replace(",", ""))
        new_avg = float(context.args[2].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Quantity and Avg Price must be numbers")
        return

    user = update.effective_user.first_name
    username = update.effective_user.username or ""

    c.execute("SELECT user FROM positions WHERE id=?", (pos_id,))
    row = c.fetchone()
    if not row:
        await update.message.reply_text("❌ Position not found")
        return

    owner = row[0]
    if owner != user and username != ADMIN_USERNAME:
        await update.message.reply_text("⛔ You can only edit your own positions")
        return

    now_str = datetime.now(JAKARTA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "UPDATE positions SET quantity=?, avg_price=?, updated_at=? WHERE id=?",
        (new_qty, new_avg, now_str, pos_id)
    )
    conn.commit()
    await update.message.reply_text(f"✏️ Updated position {pos_id} → Qty: {new_qty}, Avg Price: {new_avg}")

async def posdel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a position by ID"""
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /posdel ID")
        return

    pos_id = context.args[0]
    user = update.effective_user.first_name
    username = update.effective_user.username or ""

    c.execute("SELECT user FROM positions WHERE id=?", (pos_id,))
    row = c.fetchone()
    if not row:
        await update.message.reply_text("❌ Position not found")
        return

    owner = row[0]
    if owner != user and username != ADMIN_USERNAME:
        await update.message.reply_text("⛔ You can only delete your own positions")
        return

    c.execute("DELETE FROM positions WHERE id=?", (pos_id,))
    conn.commit()
    await update.message.reply_text(f"🗑️ Deleted position {pos_id}")

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

async def pos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log a position"""
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /pos STOCK QUANTITY AVG_PRICE")
        return

    stock = context.args[0].upper()
    try:
        quantity = float(context.args[1].replace(",", ""))
        avg_price = float(context.args[2].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Quantity and Avg Price must be numbers")
        return

    user = update.effective_user.first_name
    date = today_str()

    now_str = datetime.now(JAKARTA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO positions (user, stock, quantity, avg_price, date, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user, stock, quantity, avg_price, date, now_str, now_str)
    )
    conn.commit()

    await update.message.reply_text(f"✅ Logged position {stock} Qty: {quantity} Avg Price: {avg_price} for {user}")

async def mypos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    c.execute("SELECT stock, quantity, avg_price, date FROM positions WHERE user=?", (user,))
    rows = c.fetchall()

    if not rows:
        await update.message.reply_text(f"📊 No positions found for {user}")
        return

    msg = f"📊 Positions for {user}:\n\n"
    for stock, quantity, avg_price, date in rows:
        msg += f"{stock}: Qty={quantity}, Avg Price={avg_price}, Date={date}\n"

    await update.message.reply_text(msg)

async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c.execute("SELECT user, stock, quantity, avg_price FROM positions ORDER BY user")
    rows = c.fetchall()

    if not rows:
        await update.message.reply_text("📊 No positions found.")
        return

    summary = {}
    stock_totals = {}
    for user, stock, quantity, avg_price in rows:
        summary.setdefault(user, []).append((stock, quantity, avg_price))
        # Calculate per stock totals and average price
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

    # Append per stock totals and group average price
    if stock_totals:
        msg += "------\n"
        msg += "🧮 Group Stock Totals:\n"
        for stock, data in stock_totals.items():
            total_qty = data["total_qty"]
            total_amt = data["total_amount"]
            avg_price = (total_amt / total_qty) if total_qty != 0 else 0
            msg += f"{stock}: Total Qty={total_qty}, Group Avg Price={avg_price:.2f}\n"

    await update.message.reply_text(msg)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
        📘 Panduan Bot Trading
        
        📝 Catat Transaksi
        /pl SAHAM JUMLAH
        contoh:
        /pl PSDN +6300000
        /pl BBRI -2000000
        
        ✏️ Edit & Hapus
        /edit ID JUMLAH_BARU
        /delete ID

        🏦 Posisi Saham
        /pos SAHAM JUMLAH HARGA_RATA
        /posedit ID JUMLAH_BARU HARGA_RATA_BARU
        /posdel ID
        /mypos → Posisi saya
        /positions → Semua posisi
        
        📊 Rekap
        /weekly  → Rekap Mingguan
        /monthly → Rekap Bulanan
        (Harian otomatis jam 16:00 WIB)
        
        /leaderboard → Ranking bulanan
        /stock KODE → Lihat transaksi 1 saham
        /mystats → Statistik pribadi bulan ini
    """
    await update.message.reply_text(msg)

# ================== MAIN ==================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    job_queue = app.job_queue

    app.add_handler(CommandHandler("pl", pl))
    app.add_handler(CommandHandler("edit", edit))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(CommandHandler("weekly", weekly))
    app.add_handler(CommandHandler("monthly", monthly))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("stock", stock))
    app.add_handler(CommandHandler("mystats", mystats))
    app.add_handler(CommandHandler("pos", pos))
    app.add_handler(CommandHandler("posedit", posedit))
    app.add_handler(CommandHandler("posdel", posdel))
    app.add_handler(CommandHandler("mypos", mypos))
    app.add_handler(CommandHandler("positions", positions_command))
    app.add_handler(CommandHandler("help", help_command))

    # Daily recap at 16:00 WIB
    job_queue.run_daily(
        daily_recap,
        time=datetime.now(JAKARTA_TZ).replace(hour=16, minute=0, second=0, microsecond=0).timetz(),
        days=(0,1,2,3,4),  # Mon-Fri
        name="daily_recap"
    )

    print("🚀 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
