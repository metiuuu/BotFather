import sqlite3
from datetime import datetime, timedelta
import os
import json
import asyncio
import urllib.request
import urllib.error
import pytz
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)

# ================= CONFIG =================
BOT_TOKEN = "8287396294:AAFADT7sa0pJsy8HejGjPCVFQej1BQG-iEc"
GROUP_CHAT_ID = -4883871034
ADMIN_USERNAMES = ["eemmje"]

JAKARTA_TZ = pytz.timezone("Asia/Jakarta")

# =============== Wiguna API Config ===============
WIGUNA_API_URL = os.getenv("WIGUNA_API_URL", "https://api.wigunainvestment.com/recommendation/stockpick")
WIGUNA_API_TOKEN = os.getenv("WIGUNA_API_TOKEN", "")

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


def stored_owner_key(update: Update) -> tuple[str, str]:
    """Return tuple (display_name, ownership_key) where ownership_key is used for DB compare"""
    uname = update.effective_user.username
    if uname:
        return (update.effective_user.first_name, uname.lower())
    return (update.effective_user.first_name, update.effective_user.first_name)


# ================ WIGUNA SIGNAL (API) =================
@safe_handler
async def set_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kirim sinyal ke API Wiguna: /set_signal KODE ENTRY [KETERANGAN]
    Contoh: /set_signal PSDN 4500 Bullish trend
    """
    await maybe_delete_command(update)

    if not WIGUNA_API_TOKEN:
        await update.message.reply_text("❌ WIGUNA_API_TOKEN belum diset di environment.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /set_signal KODE ENTRY [KETERANGAN]")
        return

    kode = context.args[0].upper()
    try:
        entry = float(context.args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("ENTRY must be a number")
        return
    keterangan = " ".join(context.args[2:]).strip() if len(context.args) > 2 else None

    # ISO8601 UTC with milliseconds and Z suffix, e.g., 2025-09-25T10:00:00.000Z
    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    payload = {
        "tanggal": now_iso,
        "code": kode,
        "entry": entry,
        "keterangan": keterangan,
    }

    def _post():
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            WIGUNA_API_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {WIGUNA_API_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_body = resp.read().decode("utf-8", errors="ignore")
                return resp.status, resp_body
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
            return e.code, body
        except urllib.error.URLError as e:
            return None, str(e)

    status, body = await asyncio.to_thread(_post)

    if status and 200 <= status < 300:
        await update.message.reply_text(f"✅ Sinyal terkirim: {kode} entry {entry}\nResponse: {body[:400]}")
    else:
        await update.message.reply_text(
            f"❌ Gagal kirim sinyal (status: {status}).\nBody/Err: {body[:400]}"
        )

 # ================== MAIN ==================
@safe_handler
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await maybe_delete_command(update)
    msg = """
    📘 *Panduan Bot Wiguna*
    
    🧩 Wiguna Signal (API)
    - `/set_signal KODE ENTRY [KETERANGAN]` → Kirim sinyal ke API Wiguna. Contoh: `/set_signal PSDN 4500 Bullish trend`.
    - Konfigurasi env:
      - `WIGUNA_API_URL` (default: https://api.wigunainvestment.com/recommendation/stockpick)
      - `WIGUNA_API_TOKEN` (wajib)
    """
    await update.message.reply_text(msg, parse_mode="Markdown")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    job_queue = app.job_queue

    # HELP
    app.add_handler(CommandHandler("help", help_command))

    # WIGUNA MONGO
    app.add_handler(CommandHandler("set_signal", set_signal))

    print("🚀 Bot running...")

    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        print(f"⚠️ Unhandled error: {context.error}")
        if getattr(update, "message", None):
            await update.message.reply_text(f"⚠️ Terjadi error: {context.error}")

    app.add_error_handler(error_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
