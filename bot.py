import os
import io
import re
import asyncio
import zipfile
from datetime import datetime
from collections import Counter

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

# ── Constants ─────────────────────────────────────────────────────────────
MAX_BATCH_SIZE = 10
TEMP_STORAGE = {}

# ── Helper Functions ──────────────────────────────────────────────────────

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


async def process_batch_images(context, file_ids, operation, **kwargs):
    results = []
    for file_id in file_ids[:MAX_BATCH_SIZE]:
        try:
            img = await get_image(context, file_id)
            if operation == "resize":
                img = img.resize((kwargs["w"], kwargs["h"]), Image.LANCZOS)
            elif operation == "compress":
                buf = compress_to_kb(img, kwargs["kb"])
                results.append(buf)
                continue
            elif operation == "grayscale":
                img = img.convert("L")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            results.append(buf)
        except:
            continue
    return results


async def get_image(context, file_id) -> Image.Image:
    file = await context.bot.get_file(file_id)
    data = await file.download_as_bytearray()
    return Image.open(io.BytesIO(data))


def get_image_info(img: Image.Image) -> str:
    mode = img.mode
    size = f"{img.width}×{img.height}"
    format_name = img.format or "Unknown"
    colors = "N/A"
    if img.width * img.height < 50000:
        colors = (
            len(img.getcolors(maxcolors=256))
            if img.getcolors(maxcolors=256)
            else ">256"
        )
    return f"""📊 *Image Information*
┌─────────────────┐
│ Dimensions: {size}
│ Format: {format_name}
│ Mode: {mode}
│ Colors: {colors}
└─────────────────┘"""


def clear_waiting(context):
    context.user_data["waiting_custom_kb"] = False
    context.user_data["waiting_custom_size"] = False
    context.user_data["waiting_custom_ratio"] = False
    context.user_data["waiting_watermark"] = False
    context.user_data["waiting_batch"] = False
    context.user_data["waiting_percent"] = False
    context.user_data["waiting_video_for_gif"] = False


def is_social_media_link(text: str) -> bool:
    patterns = [
        r"pinterest\.com/pin/",
        r"instagram\.com/p/",
        r"tiktok\.com/@.*/video/",
        r"youtube\.com/shorts/",
        r"youtu\.be/",
        r"twitter\.com/.*/status/",
        r"x\.com/.*/status/",
    ]
    return any(re.search(pattern, text.lower()) for pattern in patterns)


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
            "duration": info.get("duration", 0),
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


# ── Menu Builders ─────────────────────────────────────────────────────────

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
        [InlineKeyboardButton("🔢 Custom Position", callback_data="do_watermark_custom")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_pdf_menu():
    keyboard = [
        [InlineKeyboardButton("📑 PDF → JPG", callback_data="do_convert_PDF2JPG"),
         InlineKeyboardButton("🔗 Merge PDFs", callback_data="do_pdf_merge")],
        [InlineKeyboardButton("✂️ Split PDF", callback_data="do_pdf_split"),
         InlineKeyboardButton("🔐 PDF Info", callback_data="do_pdf_info")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_advanced_menu():
    keyboard = [
        [InlineKeyboardButton("🎯 Resize by %", callback_data="do_percent_resize"),
         InlineKeyboardButton("📐 Fit to Box", callback_data="do_fit_box")],
        [InlineKeyboardButton("🌈 Auto Color", callback_data="do_auto_color"),
         InlineKeyboardButton("🗑️ Remove EXIF", callback_data="do_remove_exif")],
        [InlineKeyboardButton("📏 Add Border", callback_data="do_add_border")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_compress_menu():
    keyboard = [
        [InlineKeyboardButton("50 KB", callback_data="do_compress_50"),
         InlineKeyboardButton("100 KB", callback_data="do_compress_100"),
         InlineKeyboardButton("200 KB", callback_data="do_compress_200")],
        [InlineKeyboardButton("500 KB", callback_data="do_compress_500"),
         InlineKeyboardButton("1 MB", callback_data="do_compress_1000")],
        [InlineKeyboardButton("✏️ Custom KB", callback_data="do_compress_custom")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_convert_menu():
    keyboard = [
        [InlineKeyboardButton("🖼 → PNG", callback_data="do_convert_PNG"),
         InlineKeyboardButton("📷 → JPG", callback_data="do_convert_JPG"),
         InlineKeyboardButton("🌐 → WEBP", callback_data="do_convert_WEBP")],
        [InlineKeyboardButton("📄 → PDF", callback_data="do_convert_PDF")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_gif_menu():
    keyboard = [
        [InlineKeyboardButton("🎬 MP4 → GIF", callback_data="do_video_to_gif"),
         InlineKeyboardButton("🖼️ Images → GIF", callback_data="do_images_to_gif")],
        [InlineKeyboardButton("⚙️ GIF Settings", callback_data="do_gif_settings"),
         InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
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
    await context.bot.send_message(
        chat_id, text, parse_mode="Markdown", reply_markup=build_main_menu()
    )


# ── Command Handlers ──────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Advanced Image & PDF Converter Bot*\n\n"
        "Send me any *image* and choose from 20+ features!\n\n"
        "✨ *Features:*\n"
        "• Convert formats (PNG/JPG/WEBP/PDF)\n"
        "• Image effects (Grayscale/Sepia/Blur/Sharpen)\n"
        "• Batch processing (up to 10 images)\n"
        "• Watermark text\n"
        "• Rotate/Flip images\n"
        "• PDF tools (Merge/Split/Info)\n"
        "• Advanced editing (Brightness/Contrast)\n"
        "• Image info & metadata\n"
        "• Video to GIF\n"
        "• Download from Pinterest / Instagram / TikTok / Twitter\n\n"
        "📌 *Pro tip:* Send multiple images for batch mode!",
        parse_mode="Markdown",
    )


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("batch_mode"):
        if "batch_files" not in context.user_data:
            context.user_data["batch_files"] = []
        file_id = update.message.photo[-1].file_id
        context.user_data["batch_files"].append(file_id)
        count = len(context.user_data["batch_files"])
        if count >= MAX_BATCH_SIZE:
            await update.message.reply_text(f"✅ Collected {count} images! Ready to process.")
            await send_menu(update.message.chat_id, context)
            context.user_data["batch_mode"] = False
        else:
            await update.message.reply_text(
                f"📦 Image {count}/{MAX_BATCH_SIZE} collected. Send more or choose an operation."
            )
        return

    context.user_data["file_id"] = update.message.photo[-1].file_id
    context.user_data["file_type"] = "image"
    clear_waiting(context)
    await update.message.reply_text("✅ Image received! Choose an option below:")
    await send_menu(update.message.chat_id, context)


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video messages for GIF conversion"""
    video = update.message.video
    context.user_data["video_file_id"] = video.file_id
    context.user_data["file_type"] = "video"
    await update.message.reply_text(
        "🎬 Video received!\n\nWhat would you like to do?",
        reply_markup=build_gif_menu(),
    )


async def handle_video_for_gif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process video and convert to GIF"""
    if not context.user_data.get("waiting_video_for_gif"):
        return

    video = update.message.video
    if not video:
        await update.message.reply_text("❌ Please send a video file.")
        return

    if video.duration and video.duration > 8:
        await update.message.reply_text(
            f"⚠️ Your video is {video.duration} seconds long.\n"
            f"I'll trim it to the first 8 seconds for the GIF."
        )

    await update.message.reply_text("⏳ Converting video to GIF... This may take a moment.")

    file = await context.bot.get_file(video.file_id)
    video_path = f"temp_video_{update.message.chat_id}.mp4"
    gif_path = f"temp_gif_{update.message.chat_id}.gif"

    await file.download_to_drive(video_path)

    try:
        await video_to_gif(video_path, gif_path, fps=10, duration=8)
        with open(gif_path, "rb") as f:
            await update.message.reply_animation(
                animation=f,
                caption="✅ Converted to GIF!",
                reply_markup=build_main_menu(),
            )
        os.remove(video_path)
        os.remove(gif_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Conversion failed: {str(e)[:100]}")
    finally:
        context.user_data["waiting_video_for_gif"] = False


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if doc.mime_type and doc.mime_type.startswith("image"):
        context.user_data["file_id"] = doc.file_id
        context.user_data["file_type"] = "image"
        clear_waiting(context)
        await update.message.reply_text("✅ Image received!")
        await send_menu(update.message.chat_id, context)
    elif doc.mime_type == "application/pdf":
        context.user_data["file_id"] = doc.file_id
        context.user_data["file_type"] = "pdf"
        clear_waiting(context)
        await update.message.reply_text(
            "✅ PDF received!\n\nWhat would you like to do?",
            reply_markup=build_pdf_menu(),
        )
    else:
        await update.message.reply_text("⚠️ Please send an image or PDF file.")


# ── Text Input Handler ─────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # ── Social media link download (Pinterest, etc.) ──
    if is_social_media_link(text) and not any(
        context.user_data.get(k) for k in ["waiting_custom_kb", "waiting_watermark", "waiting_percent", "waiting_custom_size", "waiting_custom_ratio"]
    ):
        await update.message.reply_text("📥 Processing your link... Please wait.")
        try:
            result = await download_media(text)
            if result["filesize"] and result["filesize"] > 50 * 1024 * 1024:
                await update.message.reply_text(
                    f"⚠️ File is too large ({result['filesize'] // (1024*1024)}MB). "
                    f"Telegram limit is 50MB.\n\n📹 {result['title']}"
                )
                return
            with open(result["path"], "rb") as f:
                await update.message.reply_video(
                    video=f, caption=f"✅ Downloaded: {result['title']}"
                )
            os.remove(result["path"])
        except Exception as e:
            await update.message.reply_text(
                f"❌ Failed to download.\nError: {str(e)[:100]}\n\n"
                f"Note: Some platforms may have restrictions."
            )
        return

    # ── Custom KB compression ──
    if context.user_data.get("waiting_custom_kb"):
        try:
            kb = int(text)
            assert 1 <= kb <= 50000
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
        await context.bot.send_document(
            update.message.chat_id,
            buf,
            filename=f"compressed_{kb}kb.jpg",
            caption=f"✅ Done! (~{actual} KB)",
        )
        await send_menu(update.message.chat_id, context)
        return

    # ── Watermark text ──
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
        await context.bot.send_document(
            update.message.chat_id,
            buf,
            filename="watermarked.png",
            caption="✅ Watermark added!",
        )
        await send_menu(update.message.chat_id, context)
        return

    # ── Percent resize ──
    if context.user_data.get("waiting_percent"):
        try:
            percent = int(text)
            assert 1 <= percent <= 500
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
        await context.bot.send_document(
            update.message.chat_id,
            buf,
            filename=f"resized_{percent}perc.png",
            caption=f"✅ Resized to {percent}% ({new_w}×{new_h})!",
        )
        await send_menu(update.message.chat_id, context)
        return

    # ── Custom size ──
    if context.user_data.get("waiting_custom_size"):
        try:
            parts = text.lower().replace("x", " ").replace(",", " ").split()
            w, h = int(parts[0]), int(parts[1])
            assert 1 <= w <= 10000 and 1 <= h <= 10000
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
        await context.bot.send_document(
            update.message.chat_id,
            buf,
            filename=f"resized_{w}x{h}.png",
            caption=f"✅ Resized to {w}×{h}!",
        )
        await send_menu(update.message.chat_id, context)
        return

    # ── Custom ratio ──
    if context.user_data.get("waiting_custom_ratio"):
        try:
            parts = text.replace(":", " ").split()
            rw, rh = int(parts[0]), int(parts[1])
            assert rw > 0 and rh > 0
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
        await context.bot.send_document(
            update.message.chat_id,
            buf,
            filename=f"ratio_{rw}x{rh}.png",
            caption=f"✅ Cropped to {rw}:{rh} ratio!\nNew size: {img.size[0]}×{img.size[1]}",
        )
        await send_menu(update.message.chat_id, context)
        return

    # If none matched, ignore
    await update.message.reply_text("❌ I didn't understand that. Please use the menu buttons.")


# ── Button Handler ─────────────────────────────────────────────────────────

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    chat_id = q.message.chat_id
    file_id = context.user_data.get("file_id")

    # ── Menu navigation ──
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
        await q.edit_message_text(
            "🎬 *Video to GIF Converter*\n\n"
            "Send me a video and I'll convert it to GIF!\n\n"
            "⚠️ *Limitations:*\n"
            "• Max 8 seconds duration\n"
            "• Max 480px width\n"
            "• Optimized for Telegram",
            parse_mode="Markdown",
            reply_markup=build_gif_menu(),
        )
        return
    if d == "menu_downloader":
        await q.edit_message_text(
            "📥 *Media Downloader*\n\n"
            "Send me a link from:\n"
            "• Pinterest\n"
            "• Instagram\n"
            "• TikTok\n"
            "• YouTube Shorts\n"
            "• Twitter/X\n\n"
            "I'll download and send the media to you!\n\n"
            "⚠️ *Limitation:* Max 50MB file size",
            parse_mode="Markdown",
        )
        return

    # ── GIF menu actions ──
    if d == "do_video_to_gif":
        await q.edit_message_text(
            "🎬 Send me a **video** and I'll convert it to GIF!\n\n"
            "Limitations:\n"
            "• Max 8 seconds (will trim longer videos)\n"
            "• Max 480px width\n"
            "• MP4, AVI, MOV formats supported",
            parse_mode="Markdown",
        )
        context.user_data["waiting_video_for_gif"] = True
        return
    if d == "do_gif_settings":
        await q.edit_message_text(
            "⚙️ *GIF Settings*\n\n"
            "You can customize:\n"
            "• FPS (frames per second) - default 10\n"
            "• Duration - max 8 seconds\n"
            "• Quality - Low/Medium/High\n\n"
            "Coming soon! Use defaults for now.",
            parse_mode="Markdown",
        )
        return
    if d == "do_images_to_gif":
        await q.edit_message_text("🖼️ *Images → GIF*: Coming soon! Please use MP4 to GIF for now.", parse_mode="Markdown")
        return

    # ── Check for file before proceeding ──
    if not file_id and d not in ["do_batch_start", "do_pdf_merge", "do_pdf_split"]:
        await q.edit_message_text("❌ No file found. Please send an image first.")
        return

    # ── Batch Processing ──
    if d == "do_batch_start":
        context.user_data["batch_mode"] = True
        context.user_data["batch_files"] = []
        await q.edit_message_text(
            f"📦 *Batch Mode Activated*\n\nSend up to {MAX_BATCH_SIZE} images.\n"
            "I'll collect them and you can choose an operation.\n\nSend your images now!",
            parse_mode="Markdown",
        )
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
            results = await process_batch_images(context, batch_files, "grayscale")
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zip_file:
                for i, buf in enumerate(results):
                    zip_file.writestr(f"grayscale_{i+1}.png", buf.getvalue())
            zip_buf.seek(0)
            await context.bot.send_document(chat_id, zip_buf, filename="batch_grayscale.zip")
            await send_menu(chat_id, context)
        return

    # ── Info ──
    if d == "do_info":
        img = await get_image(context, file_id)
        info = get_image_info(img)
        await q.edit_message_text(info, parse_mode="Markdown")
        return

    # ── Effects ──
    if d.startswith("do_effect_"):
        effect = d.split("_")[-1]
        img = await get_image(context, file_id)
        if effect == "grayscale":
            img = img.convert("L")
            caption = "✅ Converted to grayscale!"
        elif effect == "sepia":
            img = img.convert("RGB")
            width, height = img.size
            pixels = img.load()
            for x in range(width):
                for y in range(height):
                    r, g, b = pixels[x, y]
                    tr = int(0.393 * r + 0.769 * g + 0.189 * b)
                    tg = int(0.349 * r + 0.686 * g + 0.168 * b)
                    tb = int(0.272 * r + 0.534 * g + 0.131 * b)
                    pixels[x, y] = (min(tr, 255), min(tg, 255), min(tb, 255))
            caption = "✅ Applied sepia effect!"
        elif effect == "blur":
            img = img.filter(ImageFilter.BLUR)
            caption = "✅ Applied blur effect!"
        elif effect == "sharpen":
            img = img.filter(ImageFilter.SHARPEN)
            caption = "✅ Applied sharpen effect!"
        elif effect == "brightness_up":
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(1.5)
            caption = "✅ Increased brightness!"
        elif effect == "brightness_down":
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(0.7)
            caption = "✅ Decreased brightness!"
        elif effect == "contrast_up":
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.5)
            caption = "✅ Increased contrast!"
        elif effect == "contrast_down":
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(0.7)
            caption = "✅ Decreased contrast!"
        else:
            caption = "✅ Effect applied!"
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename=f"{effect}.png", caption=caption)
        await send_menu(chat_id, context)
        return

    # ── Rotate/Flip ──
    if d.startswith("do_rotate_"):
        angle = int(d.split("_")[-1])
        img = await get_image(context, file_id)
        img = img.rotate(angle, expand=True)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename=f"rotated_{angle}.png", caption=f"✅ Rotated {angle}°!")
        await send_menu(chat_id, context)
        return

    if d == "do_flip_vertical":
        img = await get_image(context, file_id)
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename="flipped_vertical.png", caption="✅ Flipped vertically!")
        await send_menu(chat_id, context)
        return

    if d == "do_flip_horizontal":
        img = await get_image(context, file_id)
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename="flipped_horizontal.png", caption="✅ Flipped horizontally!")
        await send_menu(chat_id, context)
        return

    # ── Watermark ──
    if d == "do_watermark_text":
        context.user_data["waiting_watermark"] = True
        await q.edit_message_text("✏️ *Send the watermark text:*\n\nExample: `@MyChannel` or `© 2024`", parse_mode="Markdown")
        return

    # ── Advanced Options ──
    if d == "do_percent_resize":
        context.user_data["waiting_percent"] = True
        await q.edit_message_text("✏️ *Enter percentage:*\n\nExamples:\n`50` (half size)\n`200` (double size)\n`150` (1.5x)", parse_mode="Markdown")
        return

    if d == "do_fit_box":
        await q.edit_message_text("✏️ *Enter box size:*\n\nExample: `1080x1080`\nImage will fit into this box while keeping aspect ratio", parse_mode="Markdown")
        context.user_data["waiting_fit_box"] = True
        return

    if d == "do_auto_color":
        img = await get_image(context, file_id)
        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(1.3)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename="auto_color.png", caption="✅ Auto color enhancement applied!")
        await send_menu(chat_id, context)
        return

    if d == "do_remove_exif":
        img = await get_image(context, file_id)
        data = list(img.getdata())
        img_no_exif = Image.new(img.mode, img.size)
        img_no_exif.putdata(data)
        buf = io.BytesIO()
        img_no_exif.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename="no_exif.png", caption="✅ EXIF data removed!")
        await send_menu(chat_id, context)
        return

    if d == "do_add_border":
        img = await get_image(context, file_id)
        border_size = 20
        new_img = Image.new("RGB", (img.width + border_size * 2, img.height + border_size * 2), "white")
        new_img.paste(img, (border_size, border_size))
        buf = io.BytesIO()
        new_img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename="with_border.png", caption="✅ Added white border!")
        await send_menu(chat_id, context)
        return

    # ── Convert ──
    if d.startswith("do_convert_"):
        fmt = d.split("_")[-1]
        if fmt == "PDF":
            await q.edit_message_text("⏳ Converting image to PDF...")
            img = await get_image(context, file_id)
            img = img.convert("RGB")
            tmp = io.BytesIO()
            img.save(tmp, format="JPEG")
            tmp.seek(0)
            pdf_buf = io.BytesIO(img2pdf.convert(tmp.read()))
            pdf_buf.seek(0)
            await context.bot.send_document(chat_id, pdf_buf, filename="converted.pdf", caption="✅ Converted to PDF!")
            await send_menu(chat_id, context)
        elif fmt == "PDF2JPG":
            await q.edit_message_text("⏳ Converting PDF to JPG images...")
            try:
                from pdf2image import convert_from_bytes
                file = await context.bot.get_file(file_id)
                data = await file.download_as_bytearray()
                pages = convert_from_bytes(bytes(data), dpi=150)
                await q.edit_message_text(f"✅ PDF has {len(pages)} page(s). Sending...")
                for i, page in enumerate(pages, 1):
                    buf = io.BytesIO()
                    page.save(buf, format="JPEG", quality=90)
                    buf.seek(0)
                    await context.bot.send_document(chat_id, buf, filename=f"page_{i}.jpg", caption=f"📄 Page {i}/{len(pages)}")
                await send_menu(chat_id, context)
            except Exception as e:
                await context.bot.send_message(chat_id, "⚠️ PDF→JPG needs Poppler installed on server.")
                await send_menu(chat_id, context)
        else:
            await q.edit_message_text(f"⏳ Converting to {fmt}...")
            img = await get_image(context, file_id)
            if fmt == "JPG":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG" if fmt == "JPG" else fmt, quality=95)
            buf.seek(0)
            await context.bot.send_document(chat_id, buf, filename=f"converted.{fmt.lower()}", caption=f"✅ Converted to {fmt}!")
            await send_menu(chat_id, context)
        return

    # ── Resize Presets ──
    if d.startswith("do_resize_") and d not in ["do_resize_custom"]:
        parts = d.split("_")
        w, h = int(parts[2]), int(parts[3])
        await q.edit_message_text(f"⏳ Resizing to {w}×{h}...")
        img = await get_image(context, file_id)
        img = img.resize((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename=f"resized_{w}x{h}.png", caption=f"✅ Resized to {w}×{h}!")
        await send_menu(chat_id, context)
        return

    if d == "do_resize_custom":
        clear_waiting(context)
        context.user_data["waiting_custom_size"] = True
        await q.edit_message_text("✏️ *Enter custom size:*\n\nExamples:\n`800x600`\n`1920 1080`\n`800,600`", parse_mode="Markdown")
        return

    if d == "do_ratio_custom":
        clear_waiting(context)
        context.user_data["waiting_custom_ratio"] = True
        await q.edit_message_text("✏️ *Enter aspect ratio:*\n\nExamples:\n`16:9`\n`4:3`\n`1:1`\n`9:16`", parse_mode="Markdown")
        return

    # ── Compress ──
    if d.startswith("do_compress_"):
        val = d.split("_")[-1]
        if val == "custom":
            clear_waiting(context)
            context.user_data["waiting_custom_kb"] = True
            await q.edit_message_text("✏️ Type the target size in KB (e.g. `150`):", parse_mode="Markdown")
            return
        kb = int(val)
        await q.edit_message_text(f"⏳ Compressing to ~{kb} KB...")
        img = await get_image(context, file_id)
        buf = compress_to_kb(img, kb)
        actual = buf.seek(0, 2) // 1024
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename=f"compressed_{kb}kb.jpg", caption=f"✅ Done! (~{actual} KB)")
        await send_menu(chat_id, context)
        return

    # ── PDF Tools ──
    if d == "do_pdf_merge":
        await q.edit_message_text("📦 *PDF Merge Mode*\n\nSend me multiple PDF files. I'll collect them and merge.\nSend 'done' when finished.", parse_mode="Markdown")
        context.user_data["merge_pdfs"] = []
        context.user_data["waiting_merge"] = True
        return


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video_for_gif))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 Advanced Bot is running with all features (video→GIF + link downloader)!")
    app.run_polling()
