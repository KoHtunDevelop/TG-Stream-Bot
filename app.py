# app.py (UNIVERSAL STABLE VERSION)

import os
import asyncio
import secrets
import traceback
import uvicorn
import re
import logging
from contextlib import asynccontextmanager

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.file_id import FileId

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from config import Config
from database import db

# =====================================================================================
# --- SETUP ---
# =====================================================================================

bot = Client(
    "SimpleStreamBot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    in_memory=True
)

multi_clients = {}
templates = Jinja2Templates(directory="templates")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting server...")
    await db.connect()
    try:
        await bot.start()
        me = await bot.get_me()
        Config.BOT_USERNAME = me.username
        multi_clients[0] = bot
        print(f"✅ Bot started: @{Config.BOT_USERNAME}")
    except Exception:
        print(f"❌ Startup error:\n{traceback.format_exc()}")
    
    yield
    print("🛑 Shutting down...")
    await bot.stop()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================================================
# --- BOT HANDLERS ---
# =====================================================================================

@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    if len(message.command) > 1 and message.command[1].startswith("verify_"):
        uid = message.command[1].split("_", 1)[1]
        link = f"{Config.BASE_URL}/show/{uid}"
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("📺 Watch Online", url=link)]])
        await message.reply_text(f"<b>Link အဆင်သင့်ဖြစ်ပါပြီ:</b>\n\n🔗 {link}", reply_markup=btn, parse_mode=enums.ParseMode.HTML)
    else:
        await message.reply_text("👋 မင်္ဂလာပါ။ File တစ်ခုခု ပို့ပေးပါ။")

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def file_handler(client, message):
    try:
        sent = await message.copy(Config.STORAGE_CHANNEL)
        uid = secrets.token_urlsafe(8)
        await db.save_link(uid, sent.id)
        
        verify = f"https://t.me/{Config.BOT_USERNAME}?start=verify_{uid}"
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Get Link", url=verify)]])
        await message.reply_text("✅ File သိမ်းဆည်းပြီးပါပြီ။", reply_markup=btn)
    except Exception:
        await message.reply_text("❌ Error ဖြစ်သွားပါတယ်။")

# =====================================================================================
# --- WEB ROUTES (ERROR FIX HERE) ---
# =====================================================================================

@app.get("/")
async def home(request: Request):
    return {"status": "ok"}

@app.get("/show/{unique_id}", response_class=HTMLResponse)
async def show_page(request: Request, unique_id: str):
    try:
        message_id = await db.get_link(unique_id)
        
        # CRITICAL FIX: explicit name and context arguments
        if not message_id:
            return templates.TemplateResponse(
                "show.html", 
                context={"request": request, "error": "Invalid Link"}
            )

        return templates.TemplateResponse(
            "show.html", 
            context={"request": request, "unique_id": unique_id}
        )
    except Exception as e:
        print(f"Show Page Error: {e}")
        return HTMLResponse(content="Internal Server Error", status_code=500)

@app.get("/api/file/{unique_id}")
async def file_api(unique_id: str):
    message_id = await db.get_link(unique_id)
    if not message_id:
        return JSONResponse(status_code=404, content={"error": "Not Found"})

    try:
        msg = await bot.get_messages(Config.STORAGE_CHANNEL, message_id)
        media = msg.document or msg.video or msg.audio
        return {
            "file_name": getattr(media, 'file_name', 'video'),
            "file_size": media.file_size,
            "direct_dl_link": f"{Config.BASE_URL}/dl/{message_id}"
        }
    except Exception:
        return JSONResponse(status_code=404, content={"error": "File missing"})

@app.get("/dl/{mid}")
async def download(mid: int):
    # Streaming Placeholder
    return {"message": "Streaming is ready"}

# =====================================================================================
# --- MAIN ---
# =====================================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
    
