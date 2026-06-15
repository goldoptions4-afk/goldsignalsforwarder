import os
import re
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
HOLDING_CHANNEL = int(os.environ.get("HOLDING_CHANNEL", "-1002083673417"))
VIP_CHANNEL = int(os.environ.get("VIP_CHANNEL", "-1005532840418"))

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def extract_prices(text):
    """Extract all price-like numbers from text (4 digits, optionally with decimal)"""
    return [float(p) for p in re.findall(r'\b4[0-9]{2,3}(?:\.[0-9]+)?\b', text)]

def extract_entry(text):
    """
    Returns (top_entry, bottom_entry) with bottom always = top - 7 for buys.
    For sells, top + 7.
    Handles single price or range like 4340-4337 or 4340 - 4337
    """
    range_match = re.search(
        r'(4[0-9]{2,3}(?:\.[0-9]+)?)\s*[-–]\s*(4[0-9]{2,3}(?:\.[0-9]+)?)', text
    )
    if range_match:
        p1 = float(range_match.group(1))
        p2 = float(range_match.group(2))
        top = max(p1, p2)
        bottom = min(p1, p2)
        return top, bottom  # we'll apply the -7/+7 logic per direction later
    else:
        prices = extract_prices(text)
        # Try to find entry price — first price mentioned near BUY/SELL keyword
        entry_match = re.search(
            r'(?:buy|sell|now|@|entry|limit)\s*[:\s]?\s*(4[0-9]{2,3}(?:\.[0-9]+)?)',
            text, re.IGNORECASE
        )
        if entry_match:
            p = float(entry_match.group(1))
            return p, p
        elif prices:
            return prices[0], prices[0]
    return None, None

def extract_tps(text):
    """Extract all TP values in order"""
    tps = []
    # Match patterns like TP1: 4350, TP 4360, 🥷TP2 4315 etc
    matches = re.finditer(
        r'(?:tp|target)\s*\d*\s*[:\s]?\s*(4[0-9]{2,3}(?:\.[0-9]+)?)',
        text, re.IGNORECASE
    )
    for m in matches:
        val = m.group(1)
        if val.lower() != 'open':
            tps.append(float(val))
    return tps

def extract_sl(text):
    """Extract SL value"""
    sl_match = re.search(
        r'(?:sl|stop\s*loss|stoploss)\s*[:\s]?\s*(4[0-9]{2,3}(?:\.[0-9]+)?)',
        text, re.IGNORECASE
    )
    if sl_match:
        return float(sl_match.group(1))
    return None

def format_price(p):
    if p == int(p):
        return str(int(p))
    return f"{p:.1f}"

# ─────────────────────────────────────────────
# SIGNAL DETECTION
# ─────────────────────────────────────────────

def is_new_signal(text):
    has_direction = bool(re.search(r'\b(buy|sell)\b', text, re.IGNORECASE))
    has_price = bool(re.search(r'\b4[0-9]{2,3}(?:\.[0-9]+)?\b', text))
    has_tp = bool(re.search(r'\btp\b', text, re.IGNORECASE))
    has_sl = bool(re.search(r'\bsl\b', text, re.IGNORECASE))
    return has_direction and has_price and (has_tp or has_sl)

def is_tp_hit(text):
    tp_words = bool(re.search(r'\btp\d?\b', text, re.IGNORECASE))
    hit_words = bool(re.search(
        r'\b(hit|check|reached|done|pips|round|touch|secured|profit|close|partial|half)\b',
        text, re.IGNORECASE
    ))
    return tp_words and hit_words

def is_breakeven(text):
    return bool(re.search(
        r'\b(breakeven|break\s*even|move\s*(sl|stop)\s*to\s*entry|set\s*be)\b',
        text, re.IGNORECASE
    ))

def is_sl_hit(text):
    return bool(re.search(
        r'\b(sl\s*hit|stop\s*loss\s*hit|stopped\s*out|setup\s*invalid|invalid\s*setup|closing\s*the\s*trade|close\s*now|cut\s*(the\s*)?trade|loss|missed)\b',
        text, re.IGNORECASE
    ))

def get_direction(text):
    if re.search(r'\bsell\b', text, re.IGNORECASE):
        return "SELL"
    if re.search(r'\bbuy\b', text, re.IGNORECASE):
        return "BUY"
    return None

def get_tp_number(text):
    """Try to extract which TP was hit"""
    m = re.search(r'tp\s*(\d)', text, re.IGNORECASE)
    if m:
        return m.group(1)
    return None

# ─────────────────────────────────────────────
# MESSAGE FORMATTERS
# ─────────────────────────────────────────────

def format_signal(text):
    direction = get_direction(text)
    if not direction:
        return None

    top_entry, bottom_entry = extract_entry(text)
    tps = extract_tps(text)
    sl = extract_sl(text)

    if top_entry is None:
        return None

    # Apply 7 point range logic
    if direction == "BUY":
        bottom_display = top_entry - 7
        entry_str = f"{format_price(top_entry)} - {format_price(bottom_display)}"
    else:  # SELL
        top_display = top_entry + 7
        entry_str = f"{format_price(top_display)} - {format_price(top_entry)}"

    emoji = "🟢" if direction == "BUY" else "🔴"

    lines = [
        f"{direction} {emoji}",
        f"XAU/USD | GOLD",
        f"",
        f"📥 ENTRY: {entry_str}",
        f"",
    ]

    if tps:
        for i, tp in enumerate(tps, 1):
            if len(tps) == 1:
                lines.append(f"✅ TP: {format_price(tp)}")
            else:
                lines.append(f"✅ TP{i}: {format_price(tp)}")
        lines.append("")

    if sl:
        lines.append(f"🛑 SL: {format_price(sl)}")

    lines.append("")
    lines.append("Use appropriate lot sizes")

    return "\n".join(lines)

def format_tp_hit(text):
    tp_num = get_tp_number(text)
    direction = get_direction(text)
    dir_str = f" {direction} 🟢" if direction == "BUY" else f" {direction} 🔴" if direction else ""

    if tp_num:
        return (
            f"✅ TP{tp_num} HIT!\n"
            f"XAU/USD | GOLD{dir_str}\n\n"
            f"Well done! Secure your profits 💰"
        )
    else:
        return (
            f"✅ TP HIT!\n"
            f"XAU/USD | GOLD{dir_str}\n\n"
            f"Well done! Secure your profits 💰"
        )

def format_breakeven():
    return (
        f"🔒 MOVE TO BREAKEVEN\n"
        f"XAU/USD | GOLD\n\n"
        f"Move your SL to your entry price now!"
    )

def format_sl_hit():
    return (
        f"❌ SL HIT\n"
        f"XAU/USD | GOLD\n\n"
        f"Setup invalid. Close the trade.\n"
        f"Manage your risk and stay disciplined 💪"
    )

# ─────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post or update.message
    if not message or not message.text:
        return

    chat_id = message.chat.id
    logger.info(f"Message from chat {chat_id}")

    # Only process messages from holding channel
    if chat_id != HOLDING_CHANNEL:
        return

    text = message.text.strip()
    logger.info(f"Processing: {text[:80]}")

    output = None

    if is_new_signal(text):
        output = format_signal(text)
        logger.info("Detected: NEW SIGNAL")
    elif is_tp_hit(text):
        output = format_tp_hit(text)
        logger.info("Detected: TP HIT")
    elif is_breakeven(text):
        output = format_breakeven()
        logger.info("Detected: BREAKEVEN")
    elif is_sl_hit(text):
        output = format_sl_hit()
        logger.info("Detected: SL HIT")
    else:
        logger.info("No pattern matched — skipping")
        return

    if output:
        await context.bot.send_message(
            chat_id=VIP_CHANNEL,
            text=output
        )
        logger.info("Message sent to VIP channel ✅")

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
