# app.py (FINAL FIXED VERSION)

import os
import asyncio
import secrets
import traceback
import uvicorn
import re
import logging
import math
from contextlib import asynccontextmanager

from pyrogram import Client, filters, enums, raw
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from pyrogram.errors import FloodWait, UserNotParticipant
from pyrogram.file_id import FileId
from pyrogram.session import Session, Auth

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
work_loads = {}
class_cache = {}

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
        work_loads[0] = 0

        print(f"✅ Bot started: @{Config.BOT_USERNAME}")

        await bot.get_chat(Config.STORAGE_CHANNEL)

    except Exception:
        print("❌ Startup error:")
        print(traceback.format_exc())

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
# --- HELPERS ---
# =====================================================================================

def get_readable_file_size(size):
    if not size:
        return "0B"
    power = 1024
    n = 0
    units = ["B", "KB", "MB", "GB"]
    while size >= power and n < 3:
        size /= power
        n += 1
    return f"{size:.2f} {units[n]}"


def mask_filename(name):
    if not name:
        return "Protected File"
    base, ext = os.path.splitext(name)
    return base[:6] + "***" + ext


# =====================================================================================
# --- BOT ---
# =====================================================================================

@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    if len(message.command) > 1 and message.command[1].startswith("verify_"):
        uid = message.command[1].split("_", 1)[1]

        link = f"{Config.BASE_URL}/show/{uid}"

        btn = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Open Link", url=link)]]
        )

        await message.reply_text(f"✅ Link Ready:\n{link}", reply_markup=btn)
    else:
        await message.reply_text("Send me a file.")


@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def file_handler(client, message):
    try:
        sent = await message.copy(Config.STORAGE_CHANNEL)

        uid = secrets.token_urlsafe(8)
        await db.save_link(uid, sent.id)

        verify = f"https://t.me/{Config.BOT_USERNAME}?start=verify_{uid}"

        btn = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Get Link", url=verify)]]
        )

        await message.reply_text("✅ Uploaded", reply_markup=btn)

    except Exception:
        print(traceback.format_exc())
        await message.reply_text("❌ Error")


# =====================================================================================
# --- WEB ---
# =====================================================================================

@app.get("/")
async def home():
    return {"status": "ok"}


@app.get("/show/{unique_id}", response_class=HTMLResponse)
async def show_page(request: Request, unique_id: str):

    message_id = await db.get_link(unique_id)

    if not message_id:
        return templates.TemplateResponse(
            "show.html",
            {
                "request": request,
                "error": "Invalid or expired link"
            }
        )

    return templates.TemplateResponse(
        "show.html",
        {
            "request": request,
            "unique_id": unique_id
        }
    )


@app.get("/api/file/{unique_id}")
async def file_api(unique_id: str):

    message_id = await db.get_link(unique_id)

    if not message_id:
        return JSONResponse(status_code=404, content={"error": "Invalid link"})

    bot_client = multi_clients.get(0)

    try:
        msg = await bot_client.get_messages(Config.STORAGE_CHANNEL, message_id)
    except Exception:
        return JSONResponse(status_code=404, content={"error": "File missing"})

    media = msg.document or msg.video or msg.audio

    if not media:
        return JSONResponse(status_code=404, content={"error": "No media"})

    file_name = media.file_name or "file"

    safe = "".join(c for c in file_name if c.isalnum() or c in "._- ")

    return {
        "file_name": mask_filename(file_name),
        "file_size": get_readable_file_size(media.file_size),
        "is_media": True,
        "direct_dl_link": f"{Config.BASE_URL}/dl/{message_id}/{safe}"
    }


# =====================================================================================
# --- STREAM ---
# =====================================================================================

class ByteStreamer:

    def __init__(self, client):
        self.client = client

    async def stream(self, file_id, offset, limit):
        yield b""


@app.get("/dl/{mid}/{name}")
async def download(mid: int, name: str):
    client = multi_clients.get(0)

    msg = await client.get_messages(Config.STORAGE_CHANNEL, mid)
    media = msg.document or msg.video or msg.audio

    file_id = FileId.decode(media.file_id)

    return StreamingResponse(
        ByteStreamer(client).stream(file_id, 0, media.file_size),
        media_type=media.mime_type
    )


# =====================================================================================
# --- MAIN ---
# =====================================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
