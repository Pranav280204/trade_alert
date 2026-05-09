# polymarket_tracker.py
# Near realtime Polymarket trade tracker for Railway
# Sends Telegram alerts when tracked wallets make trades

import os
import asyncio
import aiohttp
from datetime import datetime

# =========================
# CONFIG FROM RAILWAY ENV
# =========================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# comma separated wallets
# example:
# 0xabc...,0xdef...
TRACKED_WALLETS = {
    wallet.strip().lower()
    for wallet in os.getenv("TRACKED_WALLETS", "").split(",")
    if wallet.strip()
}

# polling speed in seconds
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "3"))

TRADES_API = "https://data-api.polymarket.com/trades"

# memory cache for deduplication
seen_trades = set()

# =========================
# TELEGRAM
# =========================

async def send_telegram(session, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    async with session.post(url, data=payload) as resp:
        return await resp.text()


# =========================
# FORMAT MESSAGE
# =========================

def format_trade(trade, wallet):
    market = trade.get("title", "Unknown market")

    side = trade.get("side", "").upper()
    outcome = trade.get("outcome", "N/A")

    shares = float(trade.get("size", 0))
    price = float(trade.get("price", 0))

    usdc = shares * price

    timestamp = int(trade.get("timestamp", 0))

    dt = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S UTC")

    tx = trade.get("transactionHash", "")

    explorer = f"https://polygonscan.com/tx/{tx}"

    emoji = "🟢" if side == "BUY" else "🔴"

    msg = f"""
<b>🚨 New Polymarket Trade</b>

<b>Wallet:</b>
<code>{wallet}</code>

<b>Market:</b>
{market}

<b>Side:</b>
{emoji} <b>{side}</b>

<b>Outcome:</b>
<code>{outcome}</code>

<b>Shares:</b>
<code>{shares:.2f}</code>

<b>Price:</b>
<code>{price*100:.2f}%</code>

<b>USDC:</b>
<code>${usdc:.2f}</code>

<b>Time:</b>
{dt}

<a href="{explorer}">View Transaction</a>
"""

    return msg


# =========================
# FETCH TRADES
# =========================

async def fetch_trades(session, wallet):
    params = {
        "user": wallet,
        "limit": 20,
        "takerOnly": "true"
    }

    async with session.get(TRADES_API, params=params) as resp:
        if resp.status != 200:
            print(f"API Error {resp.status} for {wallet}")
            return []

        return await resp.json()


# =========================
# TRACK SINGLE WALLET
# =========================

async def track_wallet(session, wallet):
    try:
        trades = await fetch_trades(session, wallet)

        # oldest -> newest
        trades.reverse()

        for trade in trades:
            tx = trade.get("transactionHash")

            if not tx:
                continue

            unique_id = f"{wallet}_{tx}"

            if unique_id in seen_trades:
                continue

            seen_trades.add(unique_id)

            # avoid infinite memory growth
            if len(seen_trades) > 10000:
                seen_trades.clear()

            msg = format_trade(trade, wallet)

            print(f"New trade detected for {wallet}")

            await send_telegram(session, msg)

    except Exception as e:
        print(f"Wallet tracking error: {wallet}")
        print(e)


# =========================
# MAIN LOOP
# =========================

async def main():
    if not TELEGRAM_BOT_TOKEN:
        raise Exception("Missing TELEGRAM_BOT_TOKEN")

    if not TELEGRAM_CHAT_ID:
        raise Exception("Missing TELEGRAM_CHAT_ID")

    if not TRACKED_WALLETS:
        raise Exception("No TRACKED_WALLETS provided")

    print("===================================")
    print("Polymarket Tracker Started")
    print("Tracked wallets:")
    for w in TRACKED_WALLETS:
        print("-", w)

    print("===================================")

    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(timeout=timeout) as session:

        while True:

            tasks = [
                track_wallet(session, wallet)
                for wallet in TRACKED_WALLETS
            ]

            await asyncio.gather(*tasks)

            await asyncio.sleep(POLL_INTERVAL)


# =========================
# START
# =========================

if __name__ == "__main__":
    asyncio.run(main())