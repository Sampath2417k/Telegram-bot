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

# ---------- Pillow Core Backward Compatibility Fix ----------
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS

import img2pdf
import yt_dlp
from moviepy.editor import VideoFileClip
from pypdf import PdfReader, PdfWriter

TOKEN = os.environ.get("TOKEN")
MAX_BATCH_SIZE = 10

# ═══════════════════════════════════════════════════════════
#  CENTRALIZED STATE MANAGEMENT
# ═══════════════════════════════════════════════════════════

class UserStates:
    WAIT_COMPRESS_KB      = "wait_compress_kb"
    WAIT_INCREASE_KB      = "wait_increase_kb"
    WAIT_CUSTOM_SIZE      = "wait_custom_size"
    WAIT_CUSTOM_RATIO     = "wait_custom_ratio"
    WAIT_PERCENT_RESIZE   = "wait_percent_resize"
    WAIT_IMAGE_WATERMARK  = "wait_image_watermark"
    WAIT_VIDEO_FOR_GIF    = "wait_video_for_gif"
    WAIT_PDF_MERGE        = "wait_pdf_merge"
    WAIT_PDF_ENCRYPT      = "wait_pdf_encrypt"
    WAIT_PDF_WATERMARK    = "wait_pdf_watermark"

def clear_waiting(context: ContextTypes.DEFAULT_TYPE):
    """Resets all transient interaction flags safely."""
    context.user_data["current_state"] = None

# ═══════════════════════════════════════════════════════════
#  CORE ALGORITHMS & IMAGE PROCESSING
# ═══════════════════════════════════════════════════════════

def compress_to_kb(img: Image.Image, target_kb: int) -> io.BytesIO:
    """Compress image down to target KB using binary search on JPEG quality."""
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


def increase_to_kb(img: Image.Image, target_kb: int) -> io.BytesIO:
    """Increase image file size up to target KB via lossless dimension scaling."""
    img = img.convert("RGB")
    scale = 1.0
    buf = io.BytesIO()
    for _ in range(20):
        w = int(img.width * scale)
        h = int(img.height * scale)
        resized = img.resize((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format="PNG")
        size_kb = buf.tell() / 1024
        if size_kb >= target_kb:
            buf.seek(0)
            return buf
        scale *= 1.15
    buf.seek(0)
    return buf


def apply_watermark(img: Image.Image, text: str, opacity: int = 128) -> Image.Image:
    """Applies a clean, alpha-blended text watermark layer."""
    img = img.copy().convert("RGBA")
    txt_layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(txt_layer)
    
    # Platform agnostic font discovery fallback loop
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc"
    ]
    font = None
    for path in font_paths:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, int(img.height * 0.05))
                break
            except Exception:
                continue
    if not font:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = img.width - tw - 30, img.height - th - 30
    
    draw.text((x, y), text, fill=(255, 255, 255, opacity), font=font)
    return Image.alpha_composite(img, txt_layer).convert("RGB")


async def get_image(context, file_id) -> Image.Image:
    file = await context.bot.get_file(file_id)
    data = await file.download_as_bytearray()
    return Image.open(io.BytesIO(data))


async def get_bytes(context, file_id) -> bytes:
    file = await context.bot.get_file(file_id)
    return bytes(await file.download_as_bytearray())


def get_image_info(img: Image.Image) -> str:
    return (
        f"📊 *Image Matrix Summary*\n"
        f"┌ 📐 *Dimensions:* {img.width} × {img.height} px\n"
        f"├ 🎨 *Color Mode:* {img.mode}\n"
        f"└ 💾 *Format:* {img.format or 'RAW / Memory Stream'}"
    )

# ═══════════════════════════════════════════════════════════
#  NETWORKING & DATA EXTRACTION
# ═══════════════════════════════════════════════════════════

def is_social_media_link(text: str) -> bool:
    patterns = [
        r"pinterest\.com/pin/", r"pin\.it/", r"instagram\.com/p/",
        r"tiktok\.com/@.*/video/", r"youtube\.com/shorts/", r"youtu\.be/",
        r"twitter\.com/.*/status/", r"x\.com/.*/status/"
    ]
    return any(re.search(p, text.lower()) for p in patterns)


async def download_media(url: str, output_path: str = "downloads/%(title)s.%(ext)s") -> dict:
    ydl_opts = {
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            return {"path": file_path, "title": info.get("title", "media"), "filesize": info.get("filesize", 0)}
    except Exception as e:
        if "pinterest" in url.lower():
            return await direct_pinterest_download(url, output_path)
        raise e


async def direct_pinterest_download(url: str, output_path: str) -> dict:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise Exception("Access Denied on Pin Target Page Extraction")
    
    html = resp.text
    v_match = re.search(r'"videoUrl":"(https:[^"]+)"', html)
    if v_match:
        video_url = v_match.group(1).replace("\\/", "/")
        vid_resp = requests.get(video_url, headers=headers, stream=True, timeout=30)
        file_path = output_path.replace("%(title)s.%(ext)s", "pinterest_video.mp4")
        with open(file_path, "wb") as f:
            for chunk in vid_resp.iter_content(8192): f.write(chunk)
        return {"path": file_path, "title": "Pinterest Video", "filesize": os.path.getsize(file_path)}
        
    img_match = re.search(r'"imageUrl":"(https:[^"]+)"', html)
    if img_match:
        img_url = img_match.group(1).replace("\\/", "/")
        img_resp = requests.get(img_url, headers=headers, stream=True, timeout=30)
        file_path = output_path.replace("%(title)s.%(ext)s", "pinterest_image.jpg")
        with open(file_path, "wb") as f:
            for chunk in img_resp.iter_content(8192): f.write(chunk)
        return {"path": file_path, "title": "Pinterest Image", "filesize": os.path.getsize(file_path)}
    raise Exception("No resolvable source asset pointers discovered inside page DOM")


async def video_to_gif(video_path: str, output_path: str, fps: int = 10, duration: int = 8) -> str:
    clip = VideoFileClip(video_path)
    if clip.duration > duration:
        clip = clip.subclip(0, duration)
    if clip.w > 480:
        clip = clip.resize(width=480)
    clip.write_gif(output_path, fps=fps, logger=None)
    clip.close()
    return output_path

# ═══════════════════════════════════════════════════════════
#  DOCUMENT ENGINE (PDF EXTENSIONS)
# ═══════════════════════════════════════════════════════════

def compress_pdf_bytes(pdf_bytes: bytes) -> io.BytesIO:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page in reader.pages:
        page.compress_content_streams()
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf


def merge_pdf_bytes(pdf_bytes_list: list) -> io.BytesIO:
    writer = PdfWriter()
    for b in pdf_bytes_list:
        reader = PdfReader(io.BytesIO(b))
        for page in reader.pages: writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf


def split_pdf_bytes(pdf_bytes: bytes) -> list:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for i, page in enumerate(reader.pages):
        writer = PdfWriter()
        writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        pages.append((i + 1, buf))
    return pages


def encrypt_pdf_bytes(pdf_bytes: bytes, password: str) -> io.BytesIO:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page in reader.pages: writer.add_page(page)
    writer.encrypt(password)
    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf


def rotate_pdf_bytes(pdf_bytes: bytes, angle: int) -> io.BytesIO:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page in reader.pages:
        page.rotate(angle)
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf


def pdf_watermark_bytes(pdf_bytes: bytes, text: str) -> io.BytesIO:
    try:
        from reportlab.pdfgen import canvas as rl_canvas
        reader = PdfReader(io.BytesIO(pdf_bytes))
        writer = PdfWriter()
        for page in reader.pages:
            wm_buf = io.BytesIO()
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            c = rl_canvas.Canvas(wm_buf, pagesize=(w, h))
            c.setFont("Helvetica-Bold", 42)
            c.setFillColorRGB(0.7, 0.7, 0.7, alpha=0.35)
            c.translate(w / 2, h / 2)
            c.rotate(45)
            c.drawCentredString(0, 0, text)
            c.save()
            wm_buf.seek(0)
            page.merge_page(PdfReader(wm_buf).pages[0])
            writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        return buf
    except ImportError:
        return io.BytesIO(pdf_bytes)


def pdf_info_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    meta = reader.metadata or {}
    return (
        f"📄 *Document Structural Overview*\n"
        f"┌ 📄 *Total Pages:* {len(reader.pages)}\n"
        f"├ 📦 *File Volume:* {len(pdf_bytes) // 1024} KB\n"
        f"├ 🏷 *Meta-Title:* {meta.get('/Title', 'Unassigned')}\n"
        f"├ 👤 *Author:* {meta.get('/Author', 'Unknown')}\n"
        f"└ 🔒 *Security Enforced:* {'Yes' if reader.is_encrypted else 'No'}"
    )

# ═══════════════════════════════════════════════════════════
#  MODERNIZED UI GENERATOR ENGINE (LAYOUT & MARKUP)
# ═══════════════════════════════════════════════════════════

def build_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Convert Format", callback_data="menu_convert"), InlineKeyboardButton("📐 Spatial Resize", callback_data="menu_resize")],
        [InlineKeyboardButton("🗜 Compress Size", callback_data="menu_compress"), InlineKeyboardButton("📈 Upscale Scale", callback_data="menu_increase")],
        [InlineKeyboardButton("🎨 Creative Filters", callback_data="menu_effects"), InlineKeyboardButton("💧 Inject Watermark", callback_data="menu_watermark")],
        [InlineKeyboardButton("📄 PDF Toolset", callback_data="menu_pdf"), InlineKeyboardButton("🎬 Extract MP4 → GIF", callback_data="menu_video_gif")],
        [InlineKeyboardButton("📦 Batch Engine", callback_data="menu_batch"), InlineKeyboardButton("✨ Advanced Matrix", callback_data="menu_advanced")],
        [InlineKeyboardButton("ℹ️ System Analysis", callback_data="do_info")]
    ])

def build_convert_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Export as PNG", callback_data="do_convert_PNG"), InlineKeyboardButton("Export as JPG", callback_data="do_convert_JPG")],
        [InlineKeyboardButton("Convert WEBP", callback_data="do_convert_WEBP"), InlineKeyboardButton("Compile to PDF", callback_data="do_convert_PDF")],
        [InlineKeyboardButton("🗂 Return to Dashboard", callback_data="menu_main")]
    ])

def build_resize_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("HD (1280×720)", callback_data="do_resize_1280_720"), InlineKeyboardButton("FHD (1920×1080)", callback_data="do_resize_1920_1080")],
        [InlineKeyboardButton("Web Square (1080×1080)", callback_data="do_resize_1080_1080"), InlineKeyboardButton("UltraHD 4K", callback_data="do_resize_3840_2160")],
        [InlineKeyboardButton("✏️ Custom Resolution", callback_data="do_resize_custom"), InlineKeyboardButton("📐 Force Aspect Ratio", callback_data="do_ratio_custom")],
        [InlineKeyboardButton("🗂 Return to Dashboard", callback_data="menu_main")]
    ])

def build_compress_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Target: 50 KB", callback_data="do_compress_50"), InlineKeyboardButton("Target: 100 KB", callback_data="do_compress_100")],
        [InlineKeyboardButton("Target: 200 KB", callback_data="do_compress_200"), InlineKeyboardButton("Target: 500 KB", callback_data="do_compress_500")],
        [InlineKeyboardButton("✏️ Custom Target Bounds", callback_data="do_compress_custom"), InlineKeyboardButton("🗂 Return", callback_data="menu_main")]
    ])

def build_increase_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Expand to 300 KB", callback_data="do_increase_300"), InlineKeyboardButton("Expand to 500 KB", callback_data="do_increase_500")],
        [InlineKeyboardButton("Expand to 1.0 MB", callback_data="do_increase_1024"), InlineKeyboardButton("Expand to 2.0 MB", callback_data="do_increase_2048")],
        [InlineKeyboardButton("✏️ Manual KB Value Input", callback_data="do_increase_custom"), InlineKeyboardButton("🗂 Return", callback_data="menu_main")]
    ])

def build_effects_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Grayscale", callback_data="do_effect_grayscale"), InlineKeyboardButton("Sepia Tone", callback_data="do_effect_sepia")],
        [InlineKeyboardButton("Gaussian Blur", callback_data="do_effect_blur"), InlineKeyboardButton("High Sharpen", callback_data="do_effect_sharpen")],
        [InlineKeyboardButton("Brightness +", callback_data="do_effect_brightness_up"), InlineKeyboardButton("Brightness -", callback_data="do_effect_brightness_down")],
        [InlineKeyboardButton("Contrast +", callback_data="do_effect_contrast_up"), InlineKeyboardButton("Contrast -", callback_data="do_effect_contrast_down")],
        [InlineKeyboardButton("🗂 Return to Dashboard", callback_data="menu_main")]
    ])

def build_rotate_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("↻ 90° CW", callback_data="do_rotate_90"), InlineKeyboardButton("↺ 90° CCW", callback_data="do_rotate_270")],
        [InlineKeyboardButton("↕️ Flip Vertical", callback_data="do_flip_vertical"), InlineKeyboardButton("↔️ Flip Horizontal", callback_data="do_flip_horizontal")],
        [InlineKeyboardButton("🗂 Return", callback_data="menu_main")]
    ])

def build_pdf_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗜 Compress Native PDF", callback_data="do_pdf_compress"), InlineKeyboardButton("ℹ️ Parse Info Context", callback_data="do_pdf_info")],
        [InlineKeyboardButton("📑 Burst PDF → Pictures", callback_data="do_convert_PDF2JPG"), InlineKeyboardButton("🔗 Merge Array of PDFs", callback_data="do_pdf_merge_start")],
        [InlineKeyboardButton("✂️ Split Page Units", callback_data="do_pdf_split"), InlineKeyboardButton("🔒 Lock (Encrypt)", callback_data="do_pdf_encrypt")],
        [InlineKeyboardButton("🔄 Rotate Canvas Pages", callback_data="do_pdf_rotate"), InlineKeyboardButton("💧 Apply Layer Stamp", callback_data="do_pdf_watermark")],
        [InlineKeyboardButton("🗂 Return to Dashboard", callback_data="menu_main")]
    ])

def build_pdf_rotate_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("90° Clockwise", callback_data="do_pdf_rotate_90"), InlineKeyboardButton("180° Half-Turn", callback_data="do_pdf_rotate_180")],
        [InlineKeyboardButton("270° Flip", callback_data="do_pdf_rotate_270"), InlineKeyboardButton("↩️ Document Menu", callback_data="menu_pdf")]
    ])

def build_batch_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Initialize Batch Registry", callback_data="do_batch_start")],
        [InlineKeyboardButton("📐 Bulk Resize", callback_data="do_batch_resize"), InlineKeyboardButton("🗜 Bulk Compress", callback_data="do_batch_compress")],
        [InlineKeyboardButton("⚫ Run Desaturate Sequence", callback_data="do_batch_grayscale"), InlineKeyboardButton("🗂 Return", callback_data="menu_main")]
    ])

def build_advanced_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Scale by Scalar %", callback_data="do_percent_resize"), InlineKeyboardButton("🌈 Balanced Auto-Color", callback_data="do_auto_color")],
        [InlineKeyboardButton("🗑️ Flush EXIF Traces", callback_data="do_remove_exif"), InlineKeyboardButton("📏 Compound Framing Border", callback_data="do_add_border")],
        [InlineKeyboardButton("🗂 Return to Dashboard", callback_data="menu_main")]
    ])

async def send_menu(chat_id, context, text="💎 *System Control Core*\nSelect execution parameter vector:"):
    await context.bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=build_main_menu())

# ═══════════════════════════════════════════════════════════
#  CONTROLLER PIPELINE FILTERS & EVENT HANDLERS
# ═══════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ *Advanced Processing Engine Online*\n\n"
        "Deploy single or multiple workloads by forwarding directly:\n"
        "📊 *Image Vector:* Automation scaling, targets compression, filters.\n"
        "📄 *PDF Units:* Native compression, matrix merge/split, crypto lockers.\n"
        "🎬 *Motion Frames:* Video clips to standalone high-speed GIFs.\n"
        "🔗 *Stream URLs:* Deep-scraping downloads from Pinterest, Instagram, X.",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💡 *Interactive System Operations Guide:* Use standard runtime button interface matrices to process data blocks natively.", parse_mode="Markdown")

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("batch_mode"):
        if "batch_files" not in context.user_data: context.user_data["batch_files"] = []
        context.user_data["batch_files"].append(update.message.photo[-1].file_id)
        count = len(context.user_data["batch_files"])
        if count >= MAX_BATCH_SIZE:
            await update.message.reply_text(f"✅ Maximum batch array filled ({MAX_BATCH_SIZE} targets). Resolving pipeline.")
            await send_menu(update.message.chat_id, context)
            context.user_data["batch_mode"] = False
        else:
            await update.message.reply_text(f"📦 Pipeline Queue Element Enlisted: [{count}/{MAX_BATCH_SIZE}]")
        return
        
    context.user_data["file_id"] = update.message.photo[-1].file_id
    context.user_data.pop("pdf_file_id", None)
    clear_waiting(context)
    await update.message.reply_text("✨ *Media target loaded into volatile memory cache.*", parse_mode="Markdown")
    await send_menu(update.message.chat_id, context)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("current_state") == UserStates.WAIT_VIDEO_FOR_GIF:
        video = update.message.video
        await update.message.reply_text("⚡ *Processing frame sequence extraction arrays...*")
        file = await context.bot.get_file(video.file_id)
        v_path, g_path = f"v_{update.message.chat_id}.mp4", f"g_{update.message.chat_id}.gif"
        await file.download_to_drive(v_path)
        try:
            await video_to_gif(v_path, g_path)
            with open(g_path, "rb") as f:
                await update.message.reply_animation(animation=f, caption="✅ Transcoding stream complete.")
            os.remove(v_path); os.remove(g_path)
        except Exception as e:
            await update.message.reply_text(f"🚨 Engine Fault: {str(e)[:80]}")
        finally:
            clear_waiting(context)
    else:
        context.user_data["video_file_id"] = update.message.video.file_id
        await update.message.reply_text("🎬 *Video payload discovered.*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Transcode to GIF", callback_data="do_video_to_gif")]]))

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if context.user_data.get("current_state") == UserStates.WAIT_PDF_MERGE:
        if doc.mime_type == "application/pdf":
            if "pdf_merge_list" not in context.user_data: context.user_data["pdf_merge_list"] = []
            context.user_data["pdf_merge_list"].append(doc.file_id)
            await update.message.reply_text(f"📎 Enqueued PDF [{len(context.user_data['pdf_merge_list'])}]. Provide additional elements or type 'done'.")
        return

    if doc.mime_type and doc.mime_type.startswith("image"):
        context.user_data["file_id"] = doc.file_id
        await update.message.reply_text("✅ Target image accepted.")
        await send_menu(update.message.chat_id, context)
    elif doc.mime_type == "application/pdf":
        context.user_data["pdf_file_id"] = doc.file_id
        await update.message.reply_text("📄 *Document payload accepted.*", reply_markup=build_pdf_menu(), parse_mode="Markdown")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    state = context.user_data.get("current_state")

    if is_social_media_link(text) and not state:
        await update.message.reply_text("📥 *Asynchronous connection request active. Querying remote mirrors...*", parse_mode="Markdown")
        try:
            res = await download_media(text)
            with open(res["path"], "rb") as f:
                await update.message.reply_video(video=f, caption=f"✅ Asset Downloaded: {res['title']}")
            os.remove(res["path"])
        except Exception as e:
            await update.message.reply_text(f"🚨 Mirror extraction failed or timed out: {str(e)[:120]}")
        return

    if state == UserStates.WAIT_PDF_MERGE and text.lower() == "done":
        p_list = context.user_data.get("pdf_merge_list", [])
        if len(p_list) < 2:
            await update.message.reply_text("🚨 Execution failure: Minimum sequence length parameters unmet.")
            return
        await update.message.reply_text("⚡ *Merging stream matrices...*")
        try:
            bytes_array = [await get_bytes(context, fid) for fid in p_list]
            merged_res = merge_pdf_bytes(bytes_array)
            await context.bot.send_document(update.message.chat_id, merged_res, filename="merged_output.pdf", caption="✅ Struct cluster merge finalized.")
        except Exception as e:
            await update.message.reply_text(f"🚨 Fatal stream merge interruption: {e}")
        finally:
            clear_waiting(context)
        return

    if state == UserStates.WAIT_COMPRESS_KB:
        try:
            kb = int(text)
            file_id = context.user_data.get("file_id")
            img = await get_image(context, file_id)
            buf = compress_to_kb(img, kb)
            await context.bot.send_document(update.message.chat_id, buf, filename="compressed_target.jpg", caption=f"✅ Processed matrix footprint limit reached.")
        except Exception:
            await update.message.reply_text("🚨 Parsing failure: Provide valid integer boundaries.")
        finally:
            clear_waiting(context)
        return

    if state == UserStates.WAIT_INCREASE_KB:
        try:
            kb = int(text)
            file_id = context.user_data.get("file_id")
            img = await get_image(context, file_id)
            buf = increase_to_kb(img, kb)
            await context.bot.send_document(update.message.chat_id, buf, filename="upscaled_target.png", caption=f"✅ Lossless volume scaling finalized.")
        except Exception:
            await update.message.reply_text("🚨 Parsing failure: Numeric variables are bounded between 1 and 100000.")
        finally:
            clear_waiting(context)
        return

    if state == UserStates.WAIT_IMAGE_WATERMARK:
        try:
            file_id = context.user_data.get("file_id")
            img = await get_image(context, file_id)
            processed_img = apply_watermark(img, text)
            buf = io.BytesIO()
            processed_img.save(buf, format="PNG")
            buf.seek(0)
            await context.bot.send_document(update.message.chat_id, buf, filename="watermarked.png", caption="✅ Visual transparency matrix injection completed.")
        except Exception as e:
            await update.message.reply_text(f"🚨 Pipeline error: {e}")
        finally:
            clear_waiting(context)
        return

    if state == UserStates.WAIT_PDF_ENCRYPT:
        try:
            pdf_id = context.user_data.get("pdf_file_id")
            raw_pdf = await get_bytes(context, pdf_id)
            encrypted_pdf = encrypt_pdf_bytes(raw_pdf, text)
            await context.bot.send_document(update.message.chat_id, encrypted_pdf, filename="secure_locked.pdf", caption="✅ Cryptographic envelope locked successfully.")
        except Exception as e:
            await update.message.reply_text(f"🚨 Cryptographic loop fault: {e}")
        finally:
            clear_waiting(context)
        return

    if state == UserStates.WAIT_PDF_WATERMARK:
        try:
            pdf_id = context.user_data.get("pdf_file_id")
            raw_pdf = await get_bytes(context, pdf_id)
            watermarked_pdf = pdf_watermark_bytes(raw_pdf, text)
            await context.bot.send_document(update.message.chat_id, watermarked_pdf, filename="watermarked_doc.pdf", caption="✅ Canvas text watermark rendering pipeline completed.")
        except Exception as e:
            await update.message.reply_text(f"🚨 Canvas overlay rendering breakdown: {e}")
        finally:
            clear_waiting(context)
        return

    await update.message.reply_text("🚨 *Command pipeline parsing mismatch.* Invalid terminal command strings or sequence data structures.", parse_mode="Markdown")

# ═══════════════════════════════════════════════════════════
#  INTERACTIVE TELEMETRY QUERY HANDLERS (CALLBACK DISPATCHER)
# ═══════════════════════════════════════════════════════════

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    chat_id = q.message.chat_id
    file_id = context.user_data.get("file_id")
    pdf_id  = context.user_data.get("pdf_file_id")

    # Navigation Context Map
    nav = {
        "menu_main":      ("💎 *Main Matrix Controller*", build_main_menu()),
        "menu_convert":   ("🔄 *Format Conversion Control*", build_convert_menu()),
        "menu_resize":    ("📐 *Spatial Transformation Array*", build_resize_menu()),
        "menu_compress":  ("🗜 *Dynamic Bitrate Compression Settings*", build_compress_menu()),
        "menu_increase":  ("📈 *Lossless Allocation Upscaling System*", build_increase_menu()),
        "menu_effects":   ("🎨 *Creative Filtering Core*", build_effects_menu()),
        "menu_rotate":    ("🔄 *Canvas Orientation Transformers*", build_rotate_menu()),
        "menu_pdf":       ("📄 *Native Document Processing Node*", build_pdf_menu()),
        "menu_advanced":  ("✨ *Advanced Parameter Management Matrix*", build_advanced_menu()),
        "menu_batch":     ("📦 *Parallel High-Throughput Batch System*", build_batch_menu()),
    }

    if d in nav:
        txt, kb = nav[d]
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=kb)
        return

    if d == "do_video_to_gif":
        context.user_data["current_state"] = UserStates.WAIT_VIDEO_FOR_GIF
        await q.edit_message_text("🎬 *Pipeline Ready:* Forward target video component stream.")
        return

    if d == "do_compress_custom":
        context.user_data["current_state"] = UserStates.WAIT_COMPRESS_KB
        await q.edit_message_text("✏️ *Input Request:* Provide integer bounds parameter (in KB):")
        return

    if d == "do_increase_custom":
        context.user_data["current_state"] = UserStates.WAIT_INCREASE_KB
        await q.edit_message_text("✏️ *Input Request:* Provide size array boundary baseline (in KB):")
        return

    if d == "do_watermark_text":
        context.user_data["current_state"] = UserStates.WAIT_IMAGE_WATERMARK
        await q.edit_message_text("✏️ *Input Request:* Provide alpha-layer overlay text string:")
        return

    if d == "do_pdf_encrypt":
        context.user_data["current_state"] = UserStates.WAIT_PDF_ENCRYPT
        await q.edit_message_text("🔒 *Security Configuration:* Provide cryptographic alphanumeric string passkey:")
        return

    if d == "do_pdf_watermark":
        context.user_data["current_state"] = UserStates.WAIT_PDF_WATERMARK
        await q.edit_message_text("✏️ *Input Request:* Provide metadata canvas layer text stamp:")
        return

    if d == "do_pdf_merge_start":
        context.user_data["current_state"] = UserStates.WAIT_PDF_MERGE
        context.user_data["pdf_merge_list"] = []
        await q.edit_message_text("🔗 *Batch Pipeline Active:* Supply sequence materials sequentially. Conclude execution by providing `done` argument string.")
        return

    if d == "do_info":
        if not file_id:
            await q.edit_message_text("🚨 Volatile allocation block unallocated. Supply a target baseline file first.")
            return
        img = await get_image(context, file_id)
        await q.edit_message_text(get_image_info(img), parse_mode="Markdown", reply_markup=build_main_menu())
        return

    if d == "do_pdf_info":
        if not pdf_id:
            await q.edit_message_text("🚨 Structural mapping context empty. Pass active document pointer first.")
            return
        raw_pdf = await get_bytes(context, pdf_id)
        await q.edit_message_text(pdf_info_text(raw_pdf), parse_mode="Markdown", reply_markup=build_pdf_menu())
        return

    # Image Transform Process Actions Execution Branch Block
    if d.startswith("do_effect_") and file_id:
        effect = d[len("do_effect_"):]
        await q.edit_message_text("⚡ *Recalculating color channel matrices...*")
        img = await get_image(context, file_id)
        
        if effect == "grayscale": img = img.convert("L")
        elif effect == "sepia":
            img = img.convert("RGB")
            w, h = img.size
            pix = img.load()
            for x in range(w):
                for y in range(h):
                    r, g, b = pix[x, y]
                    pix[x, y] = (
                        min(int(0.393*r + 0.769*g + 0.189*b), 255),
                        min(int(0.349*r + 0.686*g + 0.168*b), 255),
                        min(int(0.272*r + 0.534*g + 0.131*b), 255)
                    )
        elif effect == "blur": img = img.filter(ImageFilter.BLUR)
        elif effect == "sharpen": img = img.filter(ImageFilter.SHARPEN)
        elif effect == "brightness_up": img = ImageEnhance.Brightness(img).enhance(1.4)
        elif effect == "brightness_down": img = ImageEnhance.Brightness(img).enhance(0.65)
        elif effect == "contrast_up": img = ImageEnhance.Contrast(img).enhance(1.4)
        elif effect == "contrast_down": img = ImageEnhance.Contrast(img).enhance(0.65)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename=f"fx_{effect}.png", caption=f"✅ Visual transform evaluation complete.")
        await send_menu(chat_id, context)
        return

    # Direct Compress Value Presets Resolver
    if d.startswith("do_compress_") and file_id:
        kb = int(d.split("_")[-1])
        await q.edit_message_text(f"⏳ *Executing compression down to target boundary threshold:* {kb} KB...")
        img = await get_image(context, file_id)
        buf = compress_to_kb(img, kb)
        await context.bot.send_document(chat_id, buf, filename=f"compressed_{kb}kb.jpg", caption=f"✅ Downscaling complete.")
        await send_menu(chat_id, context)
        return

    # Conversions Resolver Core
    if d.startswith("do_convert_") and file_id:
        fmt = d.split("_")[-1]
        await q.edit_message_text(f"⏳ *Recompiling raw image bitstream to extension target:* {fmt}...")
        img = await get_image(context, file_id)
        buf = io.BytesIO()
        if fmt == "JPG":
            img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=95)
        elif fmt == "PDF":
            img = img.convert("RGB")
            tmp = io.BytesIO()
            img.save(tmp, format="JPEG")
            tmp.seek(0)
            buf = io.BytesIO(img2pdf.convert(tmp.read()))
        else:
            img.save(buf, format=fmt)
        buf.seek(0)
        await context.bot.send_document(chat_id, buf, filename=f"converted.{fmt.lower()}", caption=f"✅ Transcoding process pipeline clean.")
        await send_menu(chat_id, context)
        return

    await q.edit_message_text("🚨 *Runtime Execution Aborted:* System command routing vector was contextually invalid or missing initial object allocations.", reply_markup=build_main_menu())

# ═══════════════════════════════════════════════════════════
#  APPLICATION INSTANTIATION ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    os.makedirs("downloads", exist_ok=True)
    if not TOKEN:
        raise RuntimeError("🚨 Fatal Configuration Error: Application token string variable key missing from environmental path.")
        
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(button))
    
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🚀 Hardware Automation Script Loop Engaged. Core components online.")
    app.run_polling()
