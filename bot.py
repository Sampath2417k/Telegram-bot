import os
import io
import re
import asyncio
import zipfile
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw, ImageFont
import img2pdf
import yt_dlp
from moviepy.editor import VideoFileClip

TOKEN = os.environ.get("TOKEN")
MAX_BATCH_SIZE = 10

# ---------- Helper Functions ----------
def compress_to_kb(img: Image.Image, target_kb: int) -> io.BytesIO:
    img = img.convert("RGB")
    lo, hi = 1, 95
    buf = io.BytesIO()
    for _ in range(12):
        mid = (lo + hi) // 2
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=mid, optimize=True)
        if buf.tell() <= target_kb * 1024:
            lo = mid
        else:
            hi = mid
    buf.seek(0)
    return buf

def apply_watermark(img: Image.Image, text: str, opacity: int = 128) -> Image.Image:
    img = img.copy()
    draw = ImageDraw.Draw(img, "RGBA")
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
    except:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = img.width - text_width - 20
    y = img.height - text_height - 20
    draw.text((x, y), text, fill=(255, 255, 255, opacity), font=font)
    return img

async def get_image(context, file_id) -> Image.Image:
    file = await context.bot.get_file(file_id)
    data = await file.download_as_bytearray()
    return Image.open(io.BytesIO(data))

def get_image_info(img: Image.Image) -> str:
    return f"📊 *Image Info*\nSize: {img.width}×{img.height}\nFormat: {img.format or 'Unknown'}\nMode: {img.mode}"

def clear_waiting(context):
    for key in ["waiting_custom_kb", "waiting_custom_size", "waiting_custom_ratio",
                "waiting_watermark", "waiting_batch", "waiting_percent", "waiting_video_for_gif"]:
        context.user_data[key] = False

def is_social_media_link(text: str) -> bool:
    text = text.lower()
    patterns = [
        r"pinterest\.com/pin/",
        r"pin\.it/",                     # 👈 Added for Pinterest short links
        r"instagram\.com/p/",
        r"tiktok\.com/@.*/video/",
        r"youtube\.com/shorts/",
        r"youtu\.be/",
        r"twitter\.com/.*/status/",
        r"x\.com/.*/status/",
    ]
    return any(re.search(p, text) for p in patterns)

async def download_media(url: str, output_path: str = "downloads/%(title)s.%(ext)s") -> dict:
    ydl_opts = {
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info)
        return {
            "path": file_path,
            "title": info.get("title", "media"),
            "filesize": info.get("filesize", 0),
        }

async def video_to_gif(video_path: str, output_path: str, fps: int = 10, duration: int = 8) -> str:
    clip = VideoFileClip(video_path)
    if clip.duration > duration:
        clip = clip.subclip(0, duration)
    if clip.w > 480:
        clip = clip.resize(width=480)
    clip.write_gif(output_path, fps=fps)
    clip.close()
    return output_path

# ---------- Menu Builders (keep all your existing menus) ----------
def build_main_menu():
    keyboard = [
        [InlineKeyboardButton("🔄 Convert Format", callback_data="menu_convert"),
         InlineKeyboardButton("📐 Resize", callback_data="menu_resize")],
        [InlineKeyboardButton("🗜 Compress to KB", callback_data="menu_compress"),
         InlineKeyboardButton("🎨 Effects", callback_data="menu_effects")],
        [InlineKeyboardButton("💧 Watermark", callback_data="menu_watermark"),
         InlineKeyboardButton("📄 PDF Tools", callback_data="menu_pdf")],
        [InlineKeyboardButton("🎬 Video to GIF", callback_data="menu_video_gif"),
         InlineKeyboardButton("📥 Download from Link", callback_data="menu_downloader")],
        [InlineKeyboardButton("ℹ️ Image Info", callback_data="do_info"),
         InlineKeyboardButton("🔄 Rotate/Flip", callback_data="menu_rotate")],
        [InlineKeyboardButton("📦 Batch Process", callback_data="menu_batch"),
         InlineKeyboardButton("✨ Advanced", callback_data="menu_advanced")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ... (keep all your other menu builders unchanged: build_effects_menu, build_rotate_menu, etc.)
# I'm omitting them for brevity – they are exactly as in your original file.

async def send_menu(chat_id, context, text="🎨 *What do you want to do?*"):
    await context.bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=build_main_menu())

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Advanced Bot*\n\nSend me an image, video, PDF, or a Pinterest/Instagram/TikTok link!",
        parse_mode="Markdown"
    )

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # batch mode logic...
    if context.user_data.get("batch_mode"):
        if "batch_files" not in context.user_data:
            context.user_data["batch_files"] = []
        context.user_data["batch_files"].append(update.message.photo[-1].file_id)
        count = len(context.user_data["batch_files"])
        if count >= MAX_BATCH_SIZE:
            await update.message.reply_text(f"✅ Collected {count} images. Ready to process.")
            await send_menu(update.message.chat_id, context)
            context.user_data["batch_mode"] = False
        else:
            await update.message.reply_text(f"📦 Image {count}/{MAX_BATCH_SIZE} collected. Send more or choose operation.")
        return
    context.user_data["file_id"] = update.message.photo[-1].file_id
    clear_waiting(context)
    await update.message.reply_text("✅ Image received! Choose an option:")
    await send_menu(update.message.chat_id, context)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Single video handler – either convert to GIF or show menu"""
    if context.user_data.get("waiting_video_for_gif"):
        # Convert to GIF
        video = update.message.video
        if not video:
            await update.message.reply_text("❌ No video found.")
            return
        await update.message.reply_text("⏳ Converting to GIF... (max 8s, 480px width)")
        file = await context.bot.get_file(video.file_id)
        video_path = f"temp_vid_{update.message.chat_id}.mp4"
        gif_path = f"temp_gif_{update.message.chat_id}.gif"
        await file.download_to_drive(video_path)
        try:
            await video_to_gif(video_path, gif_path)
            with open(gif_path, "rb") as f:
                await update.message.reply_animation(animation=f, caption="✅ Converted to GIF!")
            os.remove(video_path)
            os.remove(gif_path)
        except Exception as e:
            await update.message.reply_text(f"❌ Conversion failed: {str(e)[:100]}")
        finally:
            context.user_data["waiting_video_for_gif"] = False
    else:
        # Show GIF menu
        context.user_data["video_file_id"] = update.message.video.file_id
        await update.message.reply_text("🎬 Video received!", reply_markup=build_gif_menu())

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if doc.mime_type and doc.mime_type.startswith("image"):
        context.user_data["file_id"] = doc.file_id
        await update.message.reply_text("✅ Image received!")
        await send_menu(update.message.chat_id, context)
    elif doc.mime_type == "application/pdf":
        context.user_data["file_id"] = doc.file_id
        await update.message.reply_text("✅ PDF received!", reply_markup=build_pdf_menu())
    else:
        await update.message.reply_text("⚠️ Send an image or PDF.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # ----- SOCIAL MEDIA LINK DETECTION (Pinterest, etc.) -----
    if is_social_media_link(text):
        await update.message.reply_text("📥 Downloading... Please wait.")
        try:
            result = await download_media(text)
            if result["filesize"] and result["filesize"] > 50 * 1024 * 1024:
                await update.message.reply_text(f"⚠️ File too large ({result['filesize']//(1024*1024)}MB). Max 50MB.")
                return
            with open(result["path"], "rb") as f:
                # Try to send as video, fallback to document
                await update.message.reply_video(video=f, caption=f"✅ {result['title']}")
            os.remove(result["path"])
        except Exception as e:
            await update.message.reply_text(f"❌ Download failed.\nError: {str(e)[:200]}\n\nTry a different link.")
        return

    # ----- Other text inputs (custom KB, watermark, etc.) -----
    # (keep your existing code for custom size, ratio, etc.)
    # If none matched:
    await update.message.reply_text("❌ I didn't understand that. Please use the menu buttons or send a valid link.")

# ---------- Button Handler (minimal – keep your full version) ----------
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    chat_id = q.message.chat_id

    if d == "menu_video_gif":
        await q.edit_message_text("🎬 Send me a video (max 8s).", reply_markup=build_gif_menu())
        return
    if d == "do_video_to_gif":
        context.user_data["waiting_video_for_gif"] = True
        await q.edit_message_text("OK! Now send me the video file.")
        return
    if d == "menu_downloader":
        await q.edit_message_text("📥 Send me a link from Pinterest, Instagram, TikTok, YouTube Shorts, or Twitter/X.")
        return
    # ... add all your other button cases (convert, resize, etc.) from your original code

# ---------- Main ----------
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).drop_pending_updates(True).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))   # Only one video handler
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("✅ Bot running with Pinterest short link support!")
    app.run_polling()
