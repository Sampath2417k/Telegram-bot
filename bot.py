import os
import io
import re
import zipfile
import requests
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

# ---------- FIX for Pillow >= 10.0.0 (moviepy compatibility) ----------
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS

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
        r"pin\.it/",
        r"instagram\.com/p/",
        r"tiktok\.com/@.*/video/",
        r"youtube\.com/shorts/",
        r"youtu\.be/",
        r"twitter\.com/.*/status/",
        r"x\.com/.*/status/",
    ]
    return any(re.search(p, text) for p in patterns)

async def download_media(url: str, output_path: str = "downloads/%(title)s.%(ext)s") -> dict:
    """Try yt-dlp first; if it fails (403), fallback to direct extraction for Pinterest."""
    ydl_opts = {
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "headers": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        },
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            return {"path": file_path, "title": info.get("title", "media"), "filesize": info.get("filesize", 0)}
    except Exception as e:
        # Fallback for Pinterest only
        if "pinterest" in url.lower():
            return await direct_pinterest_download(url, output_path)
        raise e

async def direct_pinterest_download(url: str, output_path: str) -> dict:
    """Extract video/image URL from Pinterest HTML using requests + regex."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise Exception("Cannot fetch pin page")
    html = resp.text

    # Try video URL first
    video_pattern = r'"videoUrl":"(https:[^"]+)"'
    match = re.search(video_pattern, html)
    if match:
        video_url = match.group(1).replace("\\/", "/")
        vid_resp = requests.get(video_url, headers=headers, stream=True, timeout=30)
        if vid_resp.status_code == 200:
            file_path = output_path.replace("%(title)s.%(ext)s", "pinterest_video.mp4")
            with open(file_path, "wb") as f:
                for chunk in vid_resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return {"path": file_path, "title": "Pinterest Video", "filesize": os.path.getsize(file_path)}

    # Fallback to image
    img_pattern = r'"imageUrl":"(https:[^"]+)"'
    match = re.search(img_pattern, html)
    if match:
        img_url = match.group(1).replace("\\/", "/")
        img_resp = requests.get(img_url, headers=headers, stream=True, timeout=30)
        if img_resp.status_code == 200:
            file_path = output_path.replace("%(title)s.%(ext)s", "pinterest_image.jpg")
            with open(file_path, "wb") as f:
                for chunk in img_resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return {"path": file_path, "title": "Pinterest Image", "filesize": os.path.getsize(file_path)}

    raise Exception("Could not extract media URL from pin page")

async def video_to_gif(video_path: str, output_path: str, fps: int = 10, duration: int = 8) -> str:
    clip = VideoFileClip(video_path)
    if clip.duration > duration:
        clip = clip.subclip(0, duration)
    if clip.w > 480:
        clip = clip.resize(width=480)
    clip.write_gif(output_path, fps=fps)
    clip.close()
    return output_path

# ---------- Menu Builders ----------
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

def build_effects_menu():
    keyboard = [
        [InlineKeyboardButton("⚫ Grayscale", callback_data="do_effect_grayscale"),
         InlineKeyboardButton("🔷 Sepia", callback_data="do_effect_sepia")],
        [InlineKeyboardButton("💨 Blur", callback_data="do_effect_blur"),
         InlineKeyboardButton("🔪 Sharpen", callback_data="do_effect_sharpen")],
        [InlineKeyboardButton("✨ Brightness +", callback_data="do_effect_brightness_up"),
         InlineKeyboardButton("🌙 Brightness -", callback_data="do_effect_brightness_down")],
        [InlineKeyboardButton("🎨 Contrast +", callback_data="do_effect_contrast_up"),
         InlineKeyboardButton("📉 Contrast -", callback_data="do_effect_contrast_down")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_rotate_menu():
    keyboard = [
        [InlineKeyboardButton("🔄 90° Clockwise", callback_data="do_rotate_90"),
         InlineKeyboardButton("🔄 90° Counter", callback_data="do_rotate_270")],
        [InlineKeyboardButton("🔄 180°", callback_data="do_rotate_180"),
         InlineKeyboardButton("↕️ Flip Vertical", callback_data="do_flip_vertical")],
        [InlineKeyboardButton("↔️ Flip Horizontal", callback_data="do_flip_horizontal")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_watermark_menu():
    keyboard = [
        [InlineKeyboardButton("✏️ Text Watermark", callback_data="do_watermark_text")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_pdf_menu():
    keyboard = [
        [InlineKeyboardButton("📑 PDF → JPG", callback_data="do_convert_PDF2JPG")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_advanced_menu():
    keyboard = [
        [InlineKeyboardButton("🎯 Resize by %", callback_data="do_percent_resize"),
         InlineKeyboardButton("🌈 Auto Color", callback_data="do_auto_color")],
        [InlineKeyboardButton("🗑️ Remove EXIF", callback_data="do_remove_exif"),
         InlineKeyboardButton("📏 Add Border", callback_data="do_add_border")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_compress_menu():
    keyboard = [
        [InlineKeyboardButton("50 KB", callback_data="do_compress_50"),
         InlineKeyboardButton("100 KB", callback_data="do_compress_100")],
        [InlineKeyboardButton("200 KB", callback_data="do_compress_200"),
         InlineKeyboardButton("500 KB", callback_data="do_compress_500")],
        [InlineKeyboardButton("1 MB", callback_data="do_compress_1000"),
         InlineKeyboardButton("✏️ Custom KB", callback_data="do_compress_custom")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_convert_menu():
    keyboard = [
        [InlineKeyboardButton("🖼 → PNG", callback_data="do_convert_PNG"),
         InlineKeyboardButton("📷 → JPG", callback_data="do_convert_JPG")],
        [InlineKeyboardButton("🌐 → WEBP", callback_data="do_convert_WEBP"),
         InlineKeyboardButton("📄 → PDF", callback_data="do_convert_PDF")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_gif_menu():
    keyboard = [
        [InlineKeyboardButton("🎬 MP4 → GIF", callback_data="do_video_to_gif")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_resize_menu():
    keyboard = [
        [InlineKeyboardButton("HD 1280×720", callback_data="do_resize_1280_720"),
         InlineKeyboardButton("FHD 1920×1080", callback_data="do_resize_1920_1080")],
        [InlineKeyboardButton("Small 640×480", callback_data="do_resize_640_480"),
         InlineKeyboardButton("Thumb 256×256", callback_data="do_resize_256_256")],
        [InlineKeyboardButton("Square 1080×1080", callback_data="do_resize_1080_1080"),
         InlineKeyboardButton("4K 3840×2160", callback_data="do_resize_3840_2160")],
        [InlineKeyboardButton("✏️ Custom Size", callback_data="do_resize_custom"),
         InlineKeyboardButton("📐 Custom Ratio", callback_data="do_ratio_custom")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_batch_menu():
    keyboard = [
        [InlineKeyboardButton("📦 Start Batch Mode", callback_data="do_batch_start")],
        [InlineKeyboardButton("🔄 Batch Resize", callback_data="do_batch_resize"),
         InlineKeyboardButton("🗜 Batch Compress", callback_data="do_batch_compress")],
        [InlineKeyboardButton("⚫ Batch Grayscale", callback_data="do_batch_grayscale")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def send_menu(chat_id, context, text="🎨 *What do you want to do?*"):
    await context.bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=build_main_menu())

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Advanced Bot*\n\nSend me an image, video, PDF, or a Pinterest/Instagram/TikTok link!",
        parse_mode="Markdown"
    )

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if context.user_data.get("waiting_video_for_gif"):
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
    waiting_flags = ["waiting_custom_kb", "waiting_watermark", "waiting_percent", "waiting_custom_size", "waiting_custom_ratio"]
    if is_social_media_link(text) and not any(context.user_data.get(f) for f in waiting_flags):
        await update.message.reply_text("📥 Downloading... Please wait.")
        try:
            result = await download_media(text)
            if result["filesize"] and result["filesize"] > 50 * 1024 * 1024:
                await update.message.reply_text(f"⚠️ File too large ({result['filesize']//(1024*1024)}MB).")
                return
            with open(result["path"], "rb") as f:
                # Try to send as video, fallback to document
                try:
                    await update.message.reply_video(video=f, caption=f"✅ {result['title']}")
                except:
                    await update.message.reply_document(document=f, caption=f"✅ {result['title']}")
            os.remove(result["path"])
        except Exception as e:
            error_msg = str(e)
            if "403" in error_msg or "blocked" in error_msg.lower():
                await update.message.reply_text(
                    "❌ Pinterest is blocking automated downloads.\n"
                    "Please download the media manually and send it to me.\n"
                    "Then I can convert, resize, or compress it for you!"
                )
            else:
                await update.message.reply_text(f"❌ Download failed.\nError: {error_msg[:200]}")
        return

    # Custom KB compression
    if context.user_data.get("waiting_custom_kb"):
        try:
            kb = int(text)
            if not (1 <= kb <= 50000): raise ValueError
        except:
            await update.message.reply_text("❌ Enter a valid number (1–50000 KB)")
            return
        context.user_data["waiting_custom_kb"] = False
        file_id = context.user_data.get("file_id")
        if not file_id:
            await update.message.reply_text("❌ Image expired. Send it again.")
            return
        await update.message.reply_text(f"⏳ Compressing to {kb} KB...")
        img = await get_image(context, file_id)
        buf = compress_to_kb(img, kb)
        actual = buf.seek(0, 2) // 1024
        buf.seek(0)
        await context.bot.send_document(update.message.chat_id, buf, filename=f"compressed_{kb}kb.jpg", caption=f"✅ Done! (~{actual} KB)")
        await send_menu(update.message.chat_id, context)
        return

    # Watermark
    if context.user_data.get("waiting_watermark"):
        context.user_data["waiting_watermark"] = False
        file_id = context.user_data.get("file_id")
        if not file_id:
            await update.message.reply_text("❌ Image expired. Send it again.")
            return
        await update.message.reply_text(f"⏳ Adding watermark: '{text}'...")
        img = await get_image(context, file_id)
        img = apply_watermark(img, text)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(update.message.chat_id, buf, filename="watermarked.png", caption="✅ Watermark added!")
        await send_menu(update.message.chat_id, context)
        return

    # Percent resize
    if context.user_data.get("waiting_percent"):
        try:
            percent = int(text)
            if not (1 <= percent <= 500): raise ValueError
        except:
            await update.message.reply_text("❌ Enter a valid percentage (1-500)")
            return
        context.user_data["waiting_percent"] = False
        file_id = context.user_data.get("file_id")
        if not file_id:
            await update.message.reply_text("❌ Image expired. Send it again.")
            return
        img = await get_image(context, file_id)
        new_w = int(img.width * percent / 100)
        new_h = int(img.height * percent / 100)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(update.message.chat_id, buf, filename=f"resized_{percent}perc.png", caption=f"✅ Resized to {percent}% ({new_w}×{new_h})!")
        await send_menu(update.message.chat_id, context)
        return

    # Custom size
    if context.user_data.get("waiting_custom_size"):
        try:
            parts = text.lower().replace("x", " ").replace(",", " ").split()
            w, h = int(parts[0]), int(parts[1])
            if not (1 <= w <= 10000 and 1 <= h <= 10000): raise ValueError
        except:
            await update.message.reply_text("❌ Invalid. Try: 800x600 or 800 600")
            return
        context.user_data["waiting_custom_size"] = False
        file_id = context.user_data.get("file_id")
        if not file_id:
            await update.message.reply_text("❌ Image expired. Send it again.")
            return
        await update.message.reply_text(f"⏳ Resizing to {w}×{h}...")
        img = await get_image(context, file_id)
        img = img.resize((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(update.message.chat_id, buf, filename=f"resized_{w}x{h}.png", caption=f"✅ Resized to {w}×{h}!")
        await send_menu(update.message.chat_id, context)
        return

    # Custom ratio
    if context.user_data.get("waiting_custom_ratio"):
        try:
            parts = text.replace(":", " ").split()
            rw, rh = int(parts[0]), int(parts[1])
            if rw <= 0 or rh <= 0: raise ValueError
        except:
            await update.message.reply_text("❌ Invalid. Try: 16:9 or 4:3")
            return
        context.user_data["waiting_custom_ratio"] = False
        file_id = context.user_data.get("file_id")
        if not file_id:
            await update.message.reply_text("❌ Image expired. Send it again.")
            return
        await update.message.reply_text(f"⏳ Cropping to {rw}:{rh} ratio...")
        img = await get_image(context, file_id)
        orig_w, orig_h = img.size
        target_ratio = rw / rh
        orig_ratio = orig_w / orig_h
        if orig_ratio > target_ratio:
            new_w = int(orig_h * target_ratio)
            left = (orig_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, orig_h))
        else:
            new_h = int(orig_w / target_ratio)
            top = (orig_h - new_h) // 2
            img = img.crop((0, top, orig_w, top + new_h))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(update.message.chat_id, buf, filename=f"ratio_{rw}x{rh}.png", caption=f"✅ Cropped to {rw}:{rh} ratio!\nNew size: {img.size[0]}×{img.size[1]}")
        await send_menu(update.message.chat_id, context)
        return

    await update.message.reply_text("❌ I didn't understand that. Please use the menu buttons or send a valid link.")

# ---------- Button Handler ----------
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    chat_id = q.message.chat_id
    file_id = context.user_data.get("file_id")

    # Menu navigation
    if d == "menu_main":
        await q.edit_message_text("🎨 *Main Menu*", parse_mode="Markdown", reply_markup=build_main_menu())
        return
    if d == "menu_convert":
        await q.edit_message_text("🔄 *Convert Format*", parse_mode="Markdown", reply_markup=build_convert_menu())
        return
    if d == "menu_resize":
        await q.edit_message_text("📐 *Resize Options*", parse_mode="Markdown", reply_markup=build_resize_menu())
        return
    if d == "menu_compress":
        await q.edit_message_text("🗜 *Compress to Size*", parse_mode="Markdown", reply_markup=build_compress_menu())
        return
    if d == "menu_effects":
        await q.edit_message_text("🎨 *Image Effects*", parse_mode="Markdown", reply_markup=build_effects_menu())
        return
    if d == "menu_rotate":
        await q.edit_message_text("🔄 *Rotate & Flip*", parse_mode="Markdown", reply_markup=build_rotate_menu())
        return
    if d == "menu_watermark":
        await q.edit_message_text("💧 *Watermark Options*", parse_mode="Markdown", reply_markup=build_watermark_menu())
        return
    if d == "menu_pdf":
        await q.edit_message_text("📄 *PDF Tools*", parse_mode="Markdown", reply_markup=build_pdf_menu())
        return
    if d == "menu_advanced":
        await q.edit_message_text("✨ *Advanced Options*", parse_mode="Markdown", reply_markup=build_advanced_menu())
        return
    if d == "menu_batch":
        await q.edit_message_text("📦 *Batch Processing*", parse_mode="Markdown", reply_markup=build_batch_menu())
        return
    if d == "menu_video_gif":
        await q.edit_message_text("🎬 *Video to GIF*\n\nSend me a video and I'll convert it to GIF!\n\n⚠️ Max 8 seconds, max 480px width.", parse_mode="Markdown")
        return
    if d == "menu_downloader":
        await q.edit_message_text("📥 *Media Downloader*\n\nSend me a link from Pinterest, Instagram, TikTok, YouTube Shorts, or Twitter/X.", parse_mode="Markdown")
        return

    # GIF action
    if d == "do_video_to_gif":
        context.user_data["waiting_video_for_gif"] = True
        await q.edit_message_text("🎬 OK! Now send me the video file (max 8 seconds).")
        return

    if not file_id and d not in ["do_batch_start", "do_pdf_merge", "do_pdf_split"]:
        await q.edit_message_text("❌ No file found. Please send an image first.")
        return

    # Batch
    if d == "do_batch_start":
        context.user_data["batch_mode"] = True
        context.user_data["batch_files"] = []
        await q.edit_message_text(f"📦 *Batch Mode Activated*\n\nSend up to {MAX_BATCH_SIZE} images.\nI'll collect them and you can choose an operation.", parse_mode="Markdown")
        return

    if d in ["do_batch_resize", "do_batch_compress", "do_batch_grayscale"]:
        batch_files = context.user_data.get("batch_files", [])
        if len(batch_files) < 2:
            await q.edit_message_text("❌ Need at least 2 images for batch processing. Use 'Start Batch Mode' first.")
            return
        await q.edit_message_text(f"⏳ Processing {len(batch_files)} images...")
        if d == "do_batch_resize":
            await q.edit_message_text("✏️ Send target size (e.g., 800x600):")
            context.user_data["batch_operation"] = "resize"
            context.user_data["waiting_batch_size"] = True
        elif d == "do_batch_compress":
            await q.edit_message_text("✏️ Send target KB (e.g., 100):")
            context.user_data["batch_operation"] = "compress"
            context.user_data["waiting_batch_kb"] = True
        elif d == "do_batch_grayscale":
            results = []
            for fid in batch_files:
                img = await get_image(context, fid)
                img = img.convert("L")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                buf.seek(0)
                results.append(buf)
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                for i, buf in enumerate(results):
                    zf.writestr(f"grayscale_{i+1}.png", buf.getvalue())
            zip_buf.seek(0)
            await context.bot.send_document(chat_id, zip_buf, filename="batch_grayscale.zip")
            await send_menu(chat_id, context)
        return

    # Info
    if d == "do_info":
        img = await get_image(context, file_id)
        await q.edit_message_text(get_image_info(img), parse_mode="Markdown")
        return

    # Effects
    if d.startswith("do_effect_"):
        effect = d.split("_")[-1]
        img = await get_image(context, file_id)
        if effect == "grayscale":
            img = img.convert("L")
            cap = "✅ Grayscale"
        elif effect == "sepia":
            img = img.convert("RGB")
            w, h = img.size
            pix = img.load()
            for x in range(w):
                for y in range(h):
                    r, g, b = pix[x, y]
                    tr = int(0.393*r + 0.769*g + 0.189*b)
                    tg = int(0.349*r + 0.686*g + 0.168*b)
                    tb = int(0.272*r + 0.534*g + 0.131*b)
                    pix[x, y] = (min(tr,255), min(tg,255), min(tb,255))
            cap = "✅ Sepia"
        elif effect == "blur":
            img = img.filter(ImageFilter.BLUR)
            cap = "✅ Blur"
        elif effect == "sharpen":
            img = img.filter(ImageFilter.SHARPEN)
            cap = "✅ Sharpen"
        elif effect == "brightness_up":
            img = ImageEnhance.Brightness(img).enhance(1.5)
            cap = "✅ Brightness +"
        elif effect == "brightness_down":
            img = ImageEnhance.Brightness(img).enhance(0.7)
            cap = "✅ Brightness -"
        elif effect == "contrast_up":
            img = ImageEnhance.Contrast(img).enhance(1.5)
            cap = "✅ Contrast +"
        elif effect == "contrast_down":
            img = ImageEnhance.Contrast(img).enhance(0.7)
            cap = "✅ Contrast -"
        else:
            cap = "✅ Effect applied"
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename=f"{effect}.png", caption=cap)
        await send_menu(chat_id, context)
        return

    # Rotate/Flip
    if d.startswith("do_rotate_"):
        angle = int(d.split("_")[-1])
        img = await get_image(context, file_id)
        img = img.rotate(angle, expand=True)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename=f"rotated_{angle}.png", caption=f"✅ Rotated {angle}°")
        await send_menu(chat_id, context)
        return
    if d == "do_flip_vertical":
        img = await get_image(context, file_id)
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename="flip_v.png", caption="✅ Flipped vertical")
        await send_menu(chat_id, context)
        return
    if d == "do_flip_horizontal":
        img = await get_image(context, file_id)
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename="flip_h.png", caption="✅ Flipped horizontal")
        await send_menu(chat_id, context)
        return

    # Watermark text
    if d == "do_watermark_text":
        context.user_data["waiting_watermark"] = True
        await q.edit_message_text("✏️ Send the watermark text:", parse_mode="Markdown")
        return

    # Advanced
    if d == "do_percent_resize":
        context.user_data["waiting_percent"] = True
        await q.edit_message_text("✏️ Enter percentage (e.g., 50, 200):", parse_mode="Markdown")
        return
    if d == "do_auto_color":
        img = await get_image(context, file_id)
        img = ImageEnhance.Color(img).enhance(1.3)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename="auto_color.png", caption="✅ Auto color")
        await send_menu(chat_id, context)
        return
    if d == "do_remove_exif":
        img = await get_image(context, file_id)
        data = list(img.getdata())
        new = Image.new(img.mode, img.size)
        new.putdata(data)
        buf = io.BytesIO()
        new.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename="no_exif.png", caption="✅ EXIF removed")
        await send_menu(chat_id, context)
        return
    if d == "do_add_border":
        img = await get_image(context, file_id)
        border = 20
        new = Image.new("RGB", (img.width+2*border, img.height+2*border), "white")
        new.paste(img, (border, border))
        buf = io.BytesIO()
        new.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename="bordered.png", caption="✅ Added border")
        await send_menu(chat_id, context)
        return

    # Convert
    if d.startswith("do_convert_"):
        fmt = d.split("_")[-1]
        if fmt == "PDF":
            await q.edit_message_text("⏳ Converting to PDF...")
            img = await get_image(context, file_id)
            img = img.convert("RGB")
            tmp = io.BytesIO()
            img.save(tmp, format="JPEG")
            tmp.seek(0)
            pdf = io.BytesIO(img2pdf.convert(tmp.read()))
            pdf.seek(0)
            await context.bot.send_document(chat_id, pdf, filename="converted.pdf", caption="✅ PDF")
            await send_menu(chat_id, context)
        elif fmt == "PDF2JPG":
            await q.edit_message_text("⏳ PDF to JPG...")
            try:
                from pdf2image import convert_from_bytes
                file = await context.bot.get_file(file_id)
                data = await file.download_as_bytearray()
                pages = convert_from_bytes(bytes(data), dpi=150)
                for i, page in enumerate(pages, 1):
                    buf = io.BytesIO()
                    page.save(buf, format="JPEG", quality=90)
                    buf.seek(0)
                    await context.bot.send_document(chat_id, buf, filename=f"page_{i}.jpg")
                await send_menu(chat_id, context)
            except:
                await context.bot.send_message(chat_id, "⚠️ Poppler not installed.")
                await send_menu(chat_id, context)
        else:
            await q.edit_message_text(f"⏳ Converting to {fmt}...")
            img = await get_image(context, file_id)
            if fmt == "JPG":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG" if fmt=="JPG" else fmt, quality=95)
            buf.seek(0)
            await context.bot.send_document(chat_id, buf, filename=f"converted.{fmt.lower()}", caption=f"✅ {fmt}")
            await send_menu(chat_id, context)
        return

    # Resize presets
    if d.startswith("do_resize_") and d not in ["do_resize_custom"]:
        parts = d.split("_")
        w, h = int(parts[2]), int(parts[3])
        await q.edit_message_text(f"⏳ Resizing to {w}×{h}...")
        img = await get_image(context, file_id)
        img = img.resize((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename=f"resized_{w}x{h}.png", caption=f"✅ {w}×{h}")
        await send_menu(chat_id, context)
        return
    if d == "do_resize_custom":
        clear_waiting(context)
        context.user_data["waiting_custom_size"] = True
        await q.edit_message_text("✏️ Enter custom size (e.g., 800x600):", parse_mode="Markdown")
        return
    if d == "do_ratio_custom":
        clear_waiting(context)
        context.user_data["waiting_custom_ratio"] = True
        await q.edit_message_text("✏️ Enter aspect ratio (e.g., 16:9):", parse_mode="Markdown")
        return

    # Compress
    if d.startswith("do_compress_"):
        val = d.split("_")[-1]
        if val == "custom":
            clear_waiting(context)
            context.user_data["waiting_custom_kb"] = True
            await q.edit_message_text("✏️ Target size in KB (e.g., 150):", parse_mode="Markdown")
            return
        kb = int(val)
        await q.edit_message_text(f"⏳ Compressing to ~{kb} KB...")
        img = await get_image(context, file_id)
        buf = compress_to_kb(img, kb)
        actual = buf.seek(0, 2) // 1024
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename=f"compressed_{kb}kb.jpg", caption=f"✅ ~{actual} KB")
        await send_menu(chat_id, context)
        return

# ---------- Main ----------
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("✅ Bot started successfully with video→GIF and Pinterest fallback!")
    app.run_polling()
