import asyncio
import json
import os
import urllib.error
import urllib.request
from datetime import datetime

import pytz
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("WIGUNA_BOT_TOKEN", "")
GROUP_CHAT_ID = os.getenv("WIGUNA_GROUP_ID")
ADMIN_USERNAMES = ["eemmje"]

JAKARTA_TZ = pytz.timezone("Asia/Jakarta")

# =============== Wiguna API Config ===============
WIGUNA_API_URL = os.getenv("WIGUNA_API_URL", "https://api.wigunainvestment.com/recommendation/stockpick")
WIGUNA_AUTH_URL = os.getenv("WIGUNA_AUTH_URL", "https://api.wigunainvestment.com/auth/token")
WIGUNA_API_TOKEN = os.getenv("WIGUNA_API_TOKEN", "")


def resolve_wiguna_token(force_refresh: bool = False) -> str:
    """Return a valid Wiguna API token based on the simplified token response format."""
    global WIGUNA_API_TOKEN

    if WIGUNA_API_TOKEN and not force_refresh:
        return WIGUNA_API_TOKEN

    email = os.getenv("WIGUNA_EMAIL")
    password = os.getenv("WIGUNA_PASSWORD")
    if not email or not password:
        raise RuntimeError("WIGUNA_EMAIL dan/atau WIGUNA_PASSWORD belum diset di environment.")

    payload = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        WIGUNA_AUTH_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            try:
                data = json.loads(body) if body else {}
            except Exception:
                data = {}

            # Expected simple response: {"token": "xxx"}
            token = data.get("token")
            if not token:
                # As a fallback, if body is a plain string token
                if isinstance(data, str) and data.strip():
                    token = data.strip()
                else:
                    raise RuntimeError(f"Tidak bisa mendapatkan token dari response auth: {body[:400]}")

            WIGUNA_API_TOKEN = token
            os.environ["WIGUNA_API_TOKEN"] = token
            return token

    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
        raise RuntimeError(f"Auth gagal (HTTP {e.code}): {err_body[:400]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Auth gagal (URLError): {e}")

# ============== HELPER FUNCS ==============
def safe_handler(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            await func(update, context)
        except Exception as e:
            print(f"⚠️ Error in {func.__name__}: {e}")
            if update.message:
                await send_text(update, context, f"⚠️ Terjadi error: {e}")
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

async def send_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, parse_mode: str | None = None):
    """Send a plain message to the chat without replying to a (possibly deleted) message."""
    try:
        chat = getattr(update, "effective_chat", None)
        if chat is None:
            return
        await context.bot.send_message(chat_id=chat.id, text=text, parse_mode=parse_mode)
    except Exception as e:
        # Avoid breaking command flow if sending fails
        print(f"⚠️ Failed to send message: {e}")

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
    """Kirim sinyal ke API Wiguna: /ss KODE ENTRY [KETERANGAN]
    Contoh: /ss PSDN 4500 Bullish trend
    """
    await maybe_delete_command(update)

    try:
        token = await asyncio.to_thread(resolve_wiguna_token)
    except Exception as e:
        await send_text(update, context, f"❌ Gagal mendapatkan token Wiguna: {e}")
        return

    if len(context.args) < 2:
        await send_text(update, context, "Usage: /set_signal KODE ENTRY [KETERANGAN]")
        return

    kode = context.args[0].upper()
    try:
        entry = float(context.args[1].replace(",", ""))
    except ValueError:
        await send_text(update, context, "ENTRY must be a number")
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
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp_body = resp.read().decode("utf-8", errors="ignore")
                return resp.status, resp_body
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
            return e.code, body
        except urllib.error.URLError as e:
            return None, str(e)

    status, body = await asyncio.to_thread(_post)

    if status and 200 <= status < 300:
        await send_text(update, context, f"✅ Sinyal terkirim: {kode} entry {entry}\nResponse: {body[:400]}")
    else:
        await send_text(
            update,
            context,
            f"❌ Gagal kirim sinyal (status: {status}).\nBody/Err: {body[:400]}"
        )

@safe_handler
async def get_exp2_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ambil data dari endpoint exp2 Wiguna berdasarkan tanggal hari ini (weekday date)."""
    await maybe_delete_command(update)

    try:
        token = await asyncio.to_thread(resolve_wiguna_token)
    except Exception as e:
        await send_text(update, context, f"❌ Gagal mendapatkan token Wiguna: {e}")
        return

    # Default: tanggal hari ini di zona Asia/Jakarta
    today_jakarta = datetime.now(JAKARTA_TZ).strftime("%Y-%m-%d")
    url = f"https://api.wigunainvestment.com/saham/exp2?tanggal={today_jakarta}"

    def _get():
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                return resp.status, body
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
            return e.code, body
        except urllib.error.URLError as e:
            return None, str(e)

    status, body = await asyncio.to_thread(_get)

    if status and 200 <= status < 300:
        preview = body[:1000]  # Limit panjang respons
        await send_text(update, context, f"✅ Data exp2 untuk {today_jakarta}:\n\n{preview}")
    else:
        await send_text(
            update,
            context,
            f"❌ Gagal ambil data exp2 (status: {status}).\nBody/Err: {body[:400]}"
        )

 # ================== MAIN ==================
@safe_handler
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await maybe_delete_command(update)
    msg = """
📘 Panduan Cepat Wiguna

Signal
- /ss KODE ENTRY [KETERANGAN]
Contoh: /ss PSDN 4500 Bullish trend

Data Exp2
- /exp2
Ambil data ekspor saham (exp2) berdasarkan tanggal hari ini (weekday date).
"""
    await send_text(update, context, msg, parse_mode="Markdown")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    job_queue = app.job_queue

    # HELP
    app.add_handler(CommandHandler("help", help_command))

    # WIGUNA SIGNAL (mobile-friendly)
    app.add_handler(CommandHandler("ss", set_signal))

    # EXP2 DATA
    app.add_handler(CommandHandler("exp2", get_exp2_data))

    print("🚀 Bot running...")

    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        print(f"⚠️ Unhandled error: {context.error}")
        if getattr(update, "message", None):
            await send_text(update, context, f"⚠️ Terjadi error: {context.error}")

    app.add_error_handler(error_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
