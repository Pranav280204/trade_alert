# app.py
# Polymarket Whale Tracker Telegram Bot
# Railway Ready

import os
import sqlite3
import asyncio
import aiohttp
from datetime import datetime

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)

# ============================================
# CONFIG
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

POLL_INTERVAL = int(
    os.getenv("POLL_INTERVAL", "5")
)

TRADES_API = (
    "https://data-api.polymarket.com/trades"
)

DB_NAME = "traders.db"

# ============================================
# DATABASE
# ============================================

def init_db():

    conn = sqlite3.connect(DB_NAME)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS traders (
        wallet TEXT PRIMARY KEY,
        name TEXT
    )
    """)

    conn.commit()
    conn.close()


def add_trader(name, wallet):

    conn = sqlite3.connect(DB_NAME)

    conn.execute(
        """
        INSERT OR REPLACE INTO traders
        (wallet, name)
        VALUES (?, ?)
        """,
        (
            wallet.lower(),
            name
        )
    )

    conn.commit()
    conn.close()


def remove_trader(wallet):

    conn = sqlite3.connect(DB_NAME)

    conn.execute(
        """
        DELETE FROM traders
        WHERE wallet=?
        """,
        (wallet.lower(),)
    )

    conn.commit()
    conn.close()


def get_all_traders():

    conn = sqlite3.connect(DB_NAME)

    rows = conn.execute(
        """
        SELECT wallet, name
        FROM traders
        """
    ).fetchall()

    conn.close()

    return {
        wallet: name
        for wallet, name in rows
    }

# ============================================
# MEMORY CACHE
# ============================================

seen_trades = set()

# ============================================
# HELPERS
# ============================================

def whale_emoji(amount):

    if amount >= 10000:
        return "🐳"

    elif amount >= 2500:
        return "🐋"

    elif amount >= 500:
        return "🦈"

    return "🐟"


def format_trade(
    trade,
    wallet,
    trader_name
):

    market = trade.get(
        "title",
        "Unknown market"
    )

    side = trade.get(
        "side",
        ""
    ).upper()

    outcome = trade.get(
        "outcome",
        "N/A"
    )

    shares = float(
        trade.get("size", 0)
    )

    price = float(
        trade.get("price", 0)
    )

    usdc = shares * price

    timestamp = int(
        trade.get("timestamp", 0)
    )

    dt = datetime.utcfromtimestamp(
        timestamp
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    tx = trade.get(
        "transactionHash",
        ""
    )

    explorer = (
        f"https://polygonscan.com/tx/{tx}"
    )

    market_slug = trade.get("slug")

    polymarket_link = ""

    if market_slug:

        polymarket_link = (
            "https://polymarket.com/event/"
            f"{market_slug}"
        )

    side_emoji = (
        "🟢"
        if side == "BUY"
        else "🔴"
    )

    whale = whale_emoji(usdc)

    message = f"""
<b>🚨 New Polymarket Trade</b>

<b>Trader:</b>
{whale} <b>{trader_name}</b>

<b>Wallet:</b>
<code>{wallet}</code>

<b>Market:</b>
{market}

<b>Side:</b>
{side_emoji} <b>{side}</b>

<b>Outcome:</b>
<code>{outcome}</code>

<b>Shares:</b>
<code>{shares:,.2f}</code>

<b>Price:</b>
<code>{price*100:.2f}%</code>

<b>USDC:</b>
<code>${usdc:,.2f}</code>

<b>Time:</b>
{dt}
"""

    if polymarket_link:

        message += (
            f'\n<a href="{polymarket_link}">'
            'Open Market</a>'
        )

    if explorer:

        message += (
            f'\n<a href="{explorer}">'
            'View Transaction</a>'
        )

    return message

# ============================================
# TELEGRAM SEND
# ============================================

async def send_message(
    session,
    message
):

    url = (
        "https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    async with session.post(
        url,
        data=payload
    ) as response:

        return await response.text()

# ============================================
# FETCH TRADES
# ============================================

async def fetch_trades(
    session,
    wallet
):

    params = {
        "user": wallet,
        "limit": 20,
        "takerOnly": "true"
    }

    async with session.get(
        TRADES_API,
        params=params
    ) as response:

        if response.status != 200:

            print(
                f"API Error {response.status}"
            )

            return []

        return await response.json()

# ============================================
# TRACK WALLET
# ============================================

async def track_wallet(
    session,
    wallet,
    trader_name
):

    try:

        trades = await fetch_trades(
            session,
            wallet
        )

        trades.reverse()

        for trade in trades:

            tx = trade.get(
                "transactionHash"
            )

            if not tx:
                continue

            unique_id = (
                f"{wallet}_{tx}"
            )

            if unique_id in seen_trades:
                continue

            seen_trades.add(unique_id)

            if len(seen_trades) > 10000:
                seen_trades.clear()

            message = format_trade(
                trade,
                wallet,
                trader_name
            )

            print(
                f"Trade detected:"
                f" {trader_name}"
            )

            await send_message(
                session,
                message
            )

    except Exception as e:

        print(e)

# ============================================
# BACKGROUND TRACKER LOOP
# ============================================

async def tracker_loop():

    timeout = aiohttp.ClientTimeout(
        total=20
    )

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        while True:

            traders = get_all_traders()

            tasks = []

            for (
                wallet,
                trader_name
            ) in traders.items():

                tasks.append(
                    track_wallet(
                        session,
                        wallet,
                        trader_name
                    )
                )

            if tasks:

                await asyncio.gather(
                    *tasks
                )

            await asyncio.sleep(
                POLL_INTERVAL
            )

# ============================================
# TELEGRAM COMMANDS
# ============================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = """
🤖 Polymarket Whale Tracker

Commands:

/add NAME WALLET
/remove WALLET
/list
/help
"""

    await update.message.reply_text(
        text
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = """
📚 Commands

/add NAME WALLET
/remove WALLET
/list

Example:

/add ToughFilling 0xa8fa...
"""

    await update.message.reply_text(
        text
    )


async def add(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        name = context.args[0]

        wallet = (
            context.args[1]
            .lower()
            .strip()
        )

        add_trader(
            name,
            wallet
        )

        await update.message.reply_text(
            f"✅ Added trader\n\n"
            f"👤 {name}\n"
            f"{wallet}"
        )

    except:

        await update.message.reply_text(
            "Usage:\n"
            "/add NAME WALLET"
        )


async def remove(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        wallet = (
            context.args[0]
            .lower()
            .strip()
        )

        remove_trader(wallet)

        await update.message.reply_text(
            f"❌ Removed\n{wallet}"
        )

    except:

        await update.message.reply_text(
            "Usage:\n"
            "/remove WALLET"
        )


async def list_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    traders = get_all_traders()

    if not traders:

        await update.message.reply_text(
            "No traders tracked"
        )

        return

    text = (
        "📊 Tracked Traders\n\n"
    )

    for (
        wallet,
        name
    ) in traders.items():

        text += (
            f"👤 <b>{name}</b>\n"
            f"<code>{wallet}</code>\n\n"
        )

    await update.message.reply_html(
        text
    )

# ============================================
# MAIN
# ============================================

async def main():

    if not BOT_TOKEN:

        raise Exception(
            "Missing BOT_TOKEN"
        )

    if not TELEGRAM_CHAT_ID:

        raise Exception(
            "Missing TELEGRAM_CHAT_ID"
        )

    init_db()

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    app.add_handler(
        CommandHandler(
            "add",
            add
        )
    )

    app.add_handler(
        CommandHandler(
            "remove",
            remove
        )
    )

    app.add_handler(
        CommandHandler(
            "list",
            list_command
        )
    )

    asyncio.create_task(
        tracker_loop()
    )

    print(
        "============================"
    )

    print(
        "Polymarket Tracker Started"
    )

    print(
        "============================"
    )

    await app.initialize()

    await app.start()

    await app.updater.start_polling()

    while True:

        await asyncio.sleep(3600)

# ============================================
# START
# ============================================

if __name__ == "__main__":

    asyncio.run(main())
