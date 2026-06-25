import os
import re
import json
import logging
import httpx
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
HOLDING_CHANNEL = int(os.environ.get("HOLDING_CHANNEL", "-1002083673417"))
KEVINGOLD_CHANNEL = int(os.environ.get("KEVINGOLD_CHANNEL", "-1001673250065"))
VIP_CHANNEL = int(os.environ.get("VIP_CHANNEL", "-1004347840465"))
RAY_GOLD_URL = os.environ.get("RAY_GOLD_URL", "https://web-production-f54d0.up.railway.app")
WHATSAPP_URL = os.environ.get("WHATSAPP_URL", "https://web-production-6cec8d.up.railway.app")

# ─────────────────────────────────────────────
# RAYGOLDSIGNALS — send signal to MT5
# ─────────────────────────────────────────────

async def send_to_mt5(text):
    try:
        # Strip backticks (Telegram monospace formatting)
        text = text.replace('`', '')
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{RAY_GOLD_URL}/new_signal",
                json={"text": text}
            )
            if r.status_code == 200:
                logger.info(f"✅ Signal sent to MT5: {r.json()}")
            else:
                logger.warning(f"⚠️ MT5 signal failed: {r.status_code}")
    except Exception as e:
        logger.error(f"❌ MT5 send error: {e}")

async def send_to_whatsapp(message, group=None, image_url=None):
    """Send message to WhatsApp — specific group or all groups, with optional image"""
    try:
        payload = {"message": message}
        if group:
            payload["group"] = group
        if image_url:
            payload["image_url"] = image_url
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{WHATSAPP_URL}/send",
                json=payload
            )
            if r.status_code == 200:
                logger.info(f"✅ Message sent to WhatsApp{' → ' + group if group else ''}")
            else:
                logger.warning(f"⚠️ WhatsApp send failed: {r.status_code} {r.text}")
    except Exception as e:
        logger.error(f"❌ WhatsApp send error: {e}")

# ─────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────

STATE_FILE = "/tmp/gold_state.json"

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"last_signal_direction": None, "last_signal_hash": None, "last_signal_time": 0}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")

def is_duplicate_signal(text, state):
    """Prevent same signal firing twice within 60 seconds"""
    import hashlib, time
    h = hashlib.md5(text.encode()).hexdigest()[:8]
    now = time.time()
    if h == state.get("last_signal_hash") and (now - state.get("last_signal_time", 0)) < 60:
        logger.info(f"Duplicate signal blocked: {h}")
        return True
    state["last_signal_hash"] = h
    state["last_signal_time"] = now
    return False

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def format_price(p):
    return f"{float(p):.2f}"

def extract_entry(text):
    range_match = re.search(
        r'([3-9][0-9]{2,3}(?:\.[0-9]+)?)\s*[-–]\s*([3-9][0-9]{2,3}(?:\.[0-9]+)?)', text
    )
    if range_match:
        p1 = float(range_match.group(1))
        p2 = float(range_match.group(2))
        return max(p1, p2), min(p1, p2)

    entry_match = re.search(
        r'(?:buy|sell|now|@|entry|limit)\s*[:\s]?\s*([3-9][0-9]{2,3}(?:\.[0-9]+)?)',
        text, re.IGNORECASE
    )
    if entry_match:
        p = float(entry_match.group(1))
        return p, p

    prices = re.findall(r'\b[3-9][0-9]{2,3}(?:\.[0-9]+)?\b', text)
    if prices:
        p = float(prices[0])
        return p, p

    return None, None

def extract_tps(text):
    tps = []
    matches = re.finditer(
        r'(?:tp|target)\s*\d*\s*[:\s]?\s*([3-9][0-9]{2,3}(?:\.[0-9]+)?)',
        text, re.IGNORECASE
    )
    for m in matches:
        val = m.group(1)
        if val.lower() != 'open':
            tps.append(float(val))
    return tps

def extract_all_tps(text):
    """Extract ALL TPs including TP4, TP5 etc — skip 'Open' and non-numeric values"""
    tps = []
    # Match TP followed by optional number, then a price value
    for m in re.finditer(
        r'(?:tp|target)\s*\d*\s*[:\s]?\s*([^\n\r,]+)',
        text, re.IGNORECASE
    ):
        val = m.group(1).strip().replace('`', '')
        # Skip if 'open', 'hold', or not a number
        if re.match(r'^[3-9][0-9]{2,3}(?:\.[0-9]+)?$', val):
            tps.append(float(val))
    return tps

def extract_sl(text):
    sl_match = re.search(
        r'(?:sl|stop\s*loss|stoploss)[:\s🚫☹️]*\s*([3-9][0-9]{2,3}(?:\.[0-9]+)?)',
        text, re.IGNORECASE
    )
    if sl_match:
        return float(sl_match.group(1))
    return None

def get_direction(text):
    if re.search(r'\bsell\b', text, re.IGNORECASE):
        return "SELL"
    if re.search(r'\bbuy\b', text, re.IGNORECASE):
        return "BUY"
    return None

def get_tp_number(text):
    m = re.search(r'tp\s*(\d)', text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None

# ─────────────────────────────────────────────
# SIGNAL DETECTION
# ─────────────────────────────────────────────

def is_new_signal(text):
    has_direction = bool(re.search(r'\b(buy|sell)\b', text, re.IGNORECASE))
    has_price = bool(re.search(r'\b[3-9][0-9]{2,3}(?:\.[0-9]+)?\b', text))
    has_tp = bool(re.search(r'\btp\b', text, re.IGNORECASE))
    has_sl = bool(re.search(r'\b(sl|stop\s*loss)\b', text, re.IGNORECASE))
    return has_direction and has_price and (has_tp or has_sl)

def is_tp_hit(text):
    has_tp_number = bool(re.search(r'\btp\s*\d', text, re.IGNORECASE))
    if not has_tp_number:
        return False
    if is_new_signal(text):
        return False
    return True

def is_secure_profits(text):
    """Catches TP4+ and 'close now / secure profits' messages — but NOT new signals"""
    if is_new_signal(text):
        return False
    has_tp4_plus = bool(re.search(r'\btp\s*[4-9]\b', text, re.IGNORECASE))
    has_close_msg = bool(re.search(
        r'\b(close\s*(our|the|all|now|trade)|secure\s*(your\s*)?profits?|take\s*profits?|let.s\s*close|touch\s*and|pips\s*✅)\b',
        text, re.IGNORECASE
    ))
    return has_tp4_plus or has_close_msg

def is_sl_hit(text):
    return bool(re.search(
        r'\b(sl\s*hit|stop\s*loss\s*hit|stopped\s*out|setup\s*invalid|invalid\s*setup|closing\s*the\s*trade|cut\s*(the\s*)?trade|missed)\b',
        text, re.IGNORECASE
    ))

# ─────────────────────────────────────────────
# FORMATTERS
# ─────────────────────────────────────────────

def format_signal(text):
    direction = get_direction(text)
    if not direction:
        return None, None

    top_entry, bottom_entry = extract_entry(text)
    tps = extract_all_tps(text)
    sl = extract_sl(text)

    if top_entry is None:
        return None, None

    if direction == "BUY":
        entry_top = top_entry
        entry_bottom = top_entry - 7
    else:
        entry_top = bottom_entry + 7
        entry_bottom = bottom_entry

    emoji = "🟢" if direction == "BUY" else "🔴"

    lines = [
        f"{direction} {emoji}",
        f"XAU/USD | GOLD",
        f"",
        f"ENTRY: {format_price(entry_top)} - {format_price(entry_bottom)}",
        f"",
    ]

    if tps:
        for i, tp in enumerate(tps, 1):
            lines.append(f"✅ TP{i} {format_price(tp)}")
        lines.append("")

    if sl:
        lines.append(f"🛑 SL {format_price(sl)}")

    lines.append("")
    lines.append("Use Appropriate Lot Sizes")

    return "\n".join(lines), direction

def format_tp_hit(text):
    tp_num = get_tp_number(text)

    if tp_num == 1:
        return (
            f"✅ TP1 HIT!\n"
            f"XAU/USD | GOLD\n\n"
            f"Close the trade or move SL to entry 🔒"
        )
    elif tp_num == 2:
        return (
            f"💥 TP2 HIT!\n"
            f"XAU/USD | GOLD\n\n"
            f"Secure partials and hold for more 🎯"
        )
    elif tp_num == 3:
        return (
            f"🔥🔥 TP3 DESTROYED!\n"
            f"XAU/USD | GOLD\n\n"
            f"What a trade! Close all positions 👑\n"
            f"This is the power of Kevin's Gold VIP 💎"
        )
    else:
        # TP4+ falls through to secure profits
        return format_secure_profits()

def format_secure_profits():
    return (
        f"💰 SECURE YOUR PROFITS!\n"
        f"XAU/USD | GOLD\n\n"
        f"Close your positions and bank those gains 🏆\n"
        f"This is the power of Kevin's Gold VIP 💎"
    )

def format_sl_hit():
    return (
        f"❌ SL HIT\n"
        f"XAU/USD | GOLD\n\n"
        f"Setup invalid. We will be looking for more trades 🔍"
    )

# ─────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post or update.message
    if not message:
        return

    # Skip videos, documents, stickers, animations
    if message.video or message.document or message.sticker or message.animation:
        logger.info("Skipping non-text media message")
        return

    # Get text from plain message OR photo caption
    text = None
    if message.text:
        text = message.text.strip()
    elif message.photo and message.caption:
        text = message.caption.strip()
    elif message.photo and not message.caption:
        logger.info("Skipping photo with no caption")
        return
    else:
        return

    chat_id = message.chat.id
    logger.info(f"Message from chat {chat_id}")

    # ── CHANNEL 1: -1001673250065 (kevingoldsignals) ──────────────
    # Already formatted — forward as-is to all 4 WhatsApp groups
    if chat_id == KEVINGOLD_CHANNEL:
        logger.info(f"📤 kevingoldsignals → ALL WhatsApp groups: {text[:80]}")
        # Extract image URL — check direct photo, forward, and effective_attachment
        image_url = None
        photo = None
        if message.photo:
            photo = message.photo[-1]
        elif message.effective_attachment and hasattr(message.effective_attachment, '__iter__'):
            try:
                photo = list(message.effective_attachment)[-1]
            except:
                pass
        elif hasattr(message, 'forward_origin') and message.forward_origin:
            if message.photo:
                photo = message.photo[-1]

        if photo:
            try:
                photo_file = await context.bot.get_file(photo.file_id)
                image_url = photo_file.file_path
                logger.info(f"📷 Image detected: {image_url}")
            except Exception as e:
                logger.warning(f"⚠️ Could not get image file: {e}")
        else:
            logger.info("📝 No image found in message")

        # Send to all groups at once — no filtering needed
        await send_to_whatsapp(text, image_url=image_url)
        return

    # ── CHANNEL: -1004347840465 (testingtradesfiltered) ──────────
    # Already formatted — send to PREMIUM GOLD GROUP + MT5 only
    if chat_id == VIP_CHANNEL:
        logger.info(f"📤 testingtradesfiltered → MT5 only (WhatsApp PAUSED): {text[:80]}")
        # PAUSED: await send_to_whatsapp(text, group="PREMIUM GOLD GROUP")
        await send_to_mt5(text)
        return

    # ── HOLDING CHANNEL: filter & reformat ────────────────────────
    if chat_id != HOLDING_CHANNEL:
        return

    logger.info(f"📥 RECEIVED: {text[:150]}")

    state = load_state()
    output = None

    if is_new_signal(text):
        if is_duplicate_signal(text, state):
            save_state(state)
            return
        output, direction = format_signal(text)
        if output:
            state["last_signal_direction"] = direction
            save_state(state)
            logger.info(f"Detected: NEW SIGNAL ({direction})")

    elif is_tp_hit(text):
        output = format_tp_hit(text)
        logger.info("Detected: TP HIT")

    elif is_secure_profits(text):
        output = format_secure_profits()
        logger.info("Detected: SECURE PROFITS")

    elif is_sl_hit(text):
        output = format_sl_hit()
        logger.info("Detected: SL HIT")

    else:
        logger.info(f"⏭️ SKIPPED — no pattern matched: {text[:80]}")
        return

    if output:
        # Send to Telegram VIP channel
        await context.bot.send_message(
            chat_id=VIP_CHANNEL,
            text=output
        )
        logger.info("Message sent to VIP channel ✅")

        # PAUSED: send to WhatsApp PREMIUM GOLD GROUP
        # await send_to_whatsapp(output, group="PREMIUM GOLD GROUP")
        # logger.info("Message sent to WhatsApp PREMIUM GOLD GROUP ✅")

        # MT5 handled by testingtradesfiltered channel only — not here

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    logger.info("Bot started — listening for signals...")
    app.run_polling(allowed_updates=["channel_post", "message"])

if __name__ == "__main__":
    main()
