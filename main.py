import asyncio
import datetime
import json
import os
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import uvicorn

# === SOZLAMALAR ===
BOT_TOKEN = "9093218376:AAFZAUaVz0Tg7aTMAKZcTA4wbID6mKIzTy8"
WEBAPP_URL = "https://vinezone-bot.onrender.com"


 

YOUTUBE_VIDEOS = [
    {"id": "0ivy1Ktniaw", "title": "1-Video"}
]

REWARD_PER_5_SEC = 10      # Har 5 soniyada beriladigan so'm
REFERRAL_BONUS = 10000     # Do'sti 1 soat ko'rsa beriladigan bonus
MIN_WITHDRAW = 30000       # Minimal pul yechish summasi
WITHDRAW_MONTH = 11        # 11-oy (Noyabr)
WITHDRAW_DAY = 15          # 15-sana

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

async def init_db():
    async with aiosqlite.connect("vidipay.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                watched_seconds INTEGER DEFAULT 0,
                referrer_id INTEGER DEFAULT NULL,
                ref_bonus_paid INTEGER DEFAULT 0
            )
        """)
        await db.commit()

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    args = message.text.split()
    ref_id = int(args) if len(args) > 1 and args.isdigit() else None

    async with aiosqlite.connect("vidipay.db") as db:
        cursor = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if not await cursor.fetchone():
            if ref_id == user_id:
                ref_id = None
            await db.execute("INSERT INTO users (user_id, referrer_id) VALUES (?, ?)", (user_id, ref_id))
            await db.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Videoni ko'rish (Pul ishlash)", web_app=WebAppInfo(url=f"{WEBAPP_URL}/watch?uid={user_id}"))],
        [InlineKeyboardButton(text="💰 Balans / Pul yechish", callback_data="balance"),
         InlineKeyboardButton(text="👥 Do'stlarni taklif qilish", callback_data="referral")]
    ])
    await message.answer(
        f"👋 Assalomu alaykum, {message.from_user.first_name}!\n\n"
        f"🎥 **VineZone** videosini ko'ring va har 5 soniyada **{REWARD_PER_5_SEC} so'm** ishlang!\n"
        f"👥 Taklif qilgan do'stingiz 1 soat video ko'rsa — **{REFERRAL_BONUS:,} so'm** bonus!",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "balance")
async def show_balance(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect("vidipay.db") as db:
        cursor = await db.execute("SELECT balance, watched_seconds FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()

    balance, seconds = row if row else (0, 0)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Pul yechish (30,000 so'm)", callback_data="withdraw")]
    ])
    await callback.message.answer(
        f"💰 **Balansingiz:** {balance:,} so'm\n"
        f"⏱ **Ko'rilgan vaqt:** {seconds // 60} daqiqa ({seconds} soniya)\n"
        f"📅 **Yechish sanasi:** 15-noyabr",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "referral")
async def show_referral(callback: types.CallbackQuery):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me{bot_info.username}?start={callback.from_user.id}"
    await callback.message.answer(
        f"🔗 **Taklif havolangiz:**\n`{ref_link}`\n\n"
        f"Do'stingiz shu havola orqali kirib **1 soat** video ko'rsa, sizga **{REFERRAL_BONUS:,} so'm** beriladi!",
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "withdraw")
async def process_withdraw(callback: types.CallbackQuery):
    today = datetime.date.today()
    if today.month != WITHDRAW_MONTH or today.day != WITHDRAW_DAY:
        await callback.answer("❌ Pul yechish faqat 15-noyabr kuni ochiladi!", show_alert=True)
        return

    user_id = callback.from_user.id
    async with aiosqlite.connect("vidipay.db") as db:
        cursor = await db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        balance = row if row else 0

        if balance < MIN_WITHDRAW:
            await callback.answer(f"❌ Minimal yechish summasi {MIN_WITHDRAW:,} so'm!", show_alert=True)
            return

        await db.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
        await db.commit()

    await callback.message.answer("✅ So'rovingiz qabul qilindi! To'lov uchun karta raqamingizni yuboring:")

@app.get("/watch", response_class=HTMLResponse)
async def watch_page(uid: int):
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("{{USER_ID}}", str(uid)).replace("{{VIDEOS_JSON}}", json.dumps(YOUTUBE_VIDEOS))
    return html

@app.post("/api/tick")
async def video_tick(request: Request):
    data = await request.json()
    user_id = int(data.get("user_id"))

    async with aiosqlite.connect("vidipay.db") as db:
        cursor = await db.execute(
            "SELECT balance, watched_seconds, referrer_id, ref_bonus_paid FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return {"status": "error"}

        balance, watched_seconds, referrer_id, ref_bonus_paid = row
        new_balance = balance + REWARD_PER_5_SEC
        new_seconds = watched_seconds + 5

        await db.execute(
            "UPDATE users SET balance = ?, watched_seconds = ? WHERE user_id = ?",
            (new_balance, new_seconds, user_id)
        )

        if referrer_id and ref_bonus_paid == 0 and new_seconds >= 3600:
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (REFERRAL_BONUS, referrer_id))
            await db.execute("UPDATE users SET ref_bonus_paid = 1 WHERE user_id = ?", (user_id,))
            try:
                await bot.send_message(referrer_id, f"🎉 Do'stingiz 1 soat video ko'rdi! Sizga {REFERRAL_BONUS:,} so'm bonus berildi!")
            except:
                pass

        await db.commit()

    return {"status": "ok", "balance": new_balance}

async def main():
    await init_db()
    port = int(os.environ.get("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port)
    server = uvicorn.Server(config)
    await asyncio.gather(dp.start_polling(bot), server.serve())

if __name__ == "__main__":
    asyncio.run(main())
