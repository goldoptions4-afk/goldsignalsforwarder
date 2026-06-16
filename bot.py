import os
import re
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
HOLDING_CHANNEL = int(os.environ.get("HOLDING_CHANNEL", "-1002083673417"))
VIP_CHANNEL = int(os.environ.get("VIP_CHANNEL", "-1004347840465"))

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def format_price(p):
    return f"{float(p):.2f}"

def extract_entry(text):
    range_match = re.search(
        r'(4[0-9]{2,3}(?:\.[0-9]+)?)\s*[-–]\s*(4[0-9]{2,3}(?:\.[0-9]+)?)', text
    )
    if range_match:
        p1 = float(range_match.group(1))
        p2 = float(range_match.group(2))
        return max(p1, p2), min(p1, p2)

    entry_match = re.search(
        r'(?:buy|sell|now|@|entry|limit)\s*[:\s]?\s*(4[0-9]{2,3}(?:\.[0-9]+)?)',
        text, re.IGNORECASE
    )
    if entry_match:
        p = float(entry_match.group(1))
        return p, p

    prices = re.findall(r'\b4[0-9]{2,3}(?:\.[0-9]+)?\b', text)
    if prices:
        p = float(prices[0])
        return p, p

    return None, None

def extract_tps(text):
    tps = []
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
    sl_match = re.search(
        r'(?:sl|stop\s*loss|stoploss)[:\s🚫☹️]*\s*(4[0-9]{2,3}(?:\.[0-9]+)?)',
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
        return m.group(1)
    return None

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
    """
    Catches any mention of TP1/TP2/TP3 being triggered:
    - "TP1✅", "TP2 ✅✅", "TP3✅✅✅"
    - "TP1 hit", "Target 2 reached", "TP3 done" etc
    But excludes full new-signal messages (handled separately, checked first)
    """
    has_tp_number = bool(re.search(r'\btp\s*\d', text, re.IGNORECASE))
    if not has_tp_number:
        return False
    if is_new_signal(text):
        return False
    return True

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

# ─────────────────────────────────────────────
# FORMATTERS
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

    return "\n".join(lines)

def format_tp_hit(text):
    tp_num = get_tp_number(text)
    direction = get_direction(text)
    dir_str = f" {direction} 🟢" if direction == "BUY" else f" {direction} 🔴" if direction else ""
    tp_label = f"TP{tp_num}" if tp_num else "TP"

    return (
        f"✅ {tp_label} HIT!\n"
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
    if not message:
        return

    # Skip videos, documents, stickers, animations entirely (no text value in these for us)
    if message.video or message.document or message.sticker or message.animation:
        logger.info("Skipping non-text media message (video/doc/sticker/gif)")
        return

    # Get text from either a plain text message OR the caption of a photo
    # (providers often send charts/screenshots WITH the trade as the caption)
    text = None
    if message.text:
        text = message.text.strip()
    elif message.photo and message.caption:
        text = message.caption.strip()
    elif message.photo and not message.caption:
        logger.info("Skipping photo with no caption — nothing to extract")
        return
    else:
        return

    chat_id = message.chat.id
    logger.info(f"Message from chat {chat_id}")

    if chat_id != HOLDING_CHANNEL:
        return

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
