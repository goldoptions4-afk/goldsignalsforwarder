# Gold Signals Forwarder Bot

Watches a private holding channel, reformats signals into Kevin's template, posts to VIP channel.

## Environment Variables (set in Railway)

| Variable | Value |
|----------|-------|
| BOT_TOKEN | Your bot token from BotFather |
| HOLDING_CHANNEL | -1002083673417 |
| VIP_CHANNEL | -1005532840418 |

## What it detects

- ✅ New trade signals (BUY/SELL) → reformats into template
- ✅ TP hits → posts TP HIT message
- ✅ Breakeven mentions → posts MOVE TO BREAKEVEN
- ✅ SL hit / close / invalid → posts SL HIT message

## Entry Logic

- BUY: keeps top entry, subtracts 7 from bottom
- SELL: keeps bottom entry, adds 7 to top

## Deploy Steps

1. Push to GitHub
2. Connect repo to Railway
3. Set environment variables
4. Deploy as Worker
