import os, io, re, zipfile, csv, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw, ImageFont
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS
import img2pdf, yt_dlp
from moviepy.editor import VideoFileClip
from pypdf import PdfReader, PdfWriter

TOKEN = os.environ.get("TOKEN")
MAX_BATCH = 10

try: import qrcode; QR_OK = True
except: QR_OK = False
try: import pytesseract; OCR_OK = True
except: OCR_OK = False
try: from rembg import remove as rembg_remove; REMBG_OK = True
except: REMBG_OK = False
try: import pdfplumber; PLUMBER_OK = True
except: PLUMBER_OK = False

class S:
    COMPRESS_KB = "compress_kb"; INCREASE_KB = "increase_kb"
    CUSTOM_SIZE = "custom_size"; CUSTOM_RATIO = "custom_ratio"
    PERCENT = "percent"; IMG_WM = "img_wm"; VIDEO_GIF = "video_gif"
    PDF_MERGE = "pdf_merge"; PDF_ENCRYPT = "pdf_encrypt"
    PDF_WM = "pdf_wm"; PDF_COMPRESS_KB = "pdf_compress_kb"
    QR_TEXT = "qr_text"; COLLAGE = "collage_mode"
    BATCH_SIZE = "batch_size"; BATCH_KB = "batch_kb"

def state(ctx): return ctx.user_data.get("st")
def set_state(ctx, s): ctx.user_data["st"] = s
def clear_state(ctx): ctx.user_data["st"] = None

# ── Button builders ──────────────────────────────────────────
def R(*btns):
    return [InlineKeyboardButton(l, callback_data=c) for l, c in btns]

def KB(rows): return InlineKeyboardMarkup(rows)

BACK = ("↩ Back", "menu_main")
CANCEL = ("✖ Cancel", "menu_main")

def sec(title): return R((f"── {title} ──", "noop"))

def image_submenu():
    return KB([
        sec("IMAGE TOOLS"),
        R(("📐 Resize", "menu_img_resize"), ("🔄 Convert", "menu_img_convert")),
        R(("🗜 Compress", "menu_img_compress"), ("📈 Increase KB", "menu_img_increase")),
        R(("✂️ Crop", "menu_img_crop"), ("🔄 Rotate/Flip", "menu_img_rotate")),
        R(("🎨 Effects", "menu_img_effects"), ("💧 Watermark", "do_wm_prompt")),
        R(("🖼 Remove BG", "do_remove_bg"), ("🔍 OCR", "do_ocr")),
        R(("📦 Batch", "menu_batch"), ("🖼 Collage", "menu_collage")),
        R(("📷 EXIF", "do_exif"), ("🌈 Auto Color", "do_auto_color")),
        R(("ℹ️ Info", "do_img_info"), ("📏 Border", "do_add_border")),
        R(BACK),
    ])

def pdf_submenu():
    return KB([
        sec("PDF TOOLS"),
        R(("🗜 Compress", "do_pdf_compress"), ("📝 Extract Text", "do_pdf_text")),
        R(("📊 Tables→CSV", "do_pdf_tables"), ("📑 PDF→JPG", "do_pdf2jpg")),
        R(("🖼 Image→PDF", "do_img2pdf"), ("🔗 Merge", "do_pdf_merge_start")),
        R(("✂️ Split", "do_pdf_split"), ("🔒 Encrypt", "do_pdf_encrypt")),
        R(("🔓 Decrypt", "do_pdf_decrypt"), ("🔄 Rotate", "menu_pdf_rotate")),
        R(("💧 Watermark", "do_pdf_wm_prompt"), ("ℹ️ Info", "do_pdf_info")),
        R(BACK),
    ])

def other_submenu():
    return KB([
        sec("OTHER TOOLS"),
        R(("🎬 Video→GIF", "do_video_gif_prompt"), ("📥 Download Link", "do_dl_prompt")),
        R(("🔲 QR Code", "do_qr_prompt")),
        R(BACK),
    ])

def main_menu():
    return KB([
        R(("🖼 Image Tools", "menu_img"), ("📄 PDF Tools", "menu_pdf")),
        R(("⚡ Other Tools", "menu_other"), ("❓ Help", "menu_help")),
    ])

def resize_menu():
    return KB([
        R(("HD 1280x720", "do_resize_1280_720"), ("FHD 1920x1080", "do_resize_1920_1080"), ("4K 3840x2160", "do_resize_3840_2160")),
        R(("640x480", "do_resize_640_480"), ("Thumb 256x256", "do_resize_256_256"), ("Square 1080x1080", "do_resize_1080_1080")),
        R(("✏️ Custom Size", "do_resize_custom"), ("📐 Custom Ratio", "do_ratio_custom"), ("🎯 By %", "do_percent_prompt")),
        R(BACK, ("🏠 Main", "menu_main")),
    ])

def convert_menu():
    return KB([
        R(("PNG", "do_convert_PNG"), ("JPG", "do_convert_JPG"), ("WEBP", "do_convert_WEBP"), ("PDF", "do_img2pdf")),
        R(BACK, ("🏠 Main", "menu_main")),
    ])

def compress_menu():
    return KB([
        R(("50 KB", "do_compress_50"), ("100 KB", "do_compress_100"), ("200 KB", "do_compress_200"), ("500 KB", "do_compress_500")),
        R(("1 MB", "do_compress_1000"), ("✏️ Custom KB", "do_compress_custom")),
        R(BACK, ("🏠 Main", "menu_main")),
    ])

def increase_menu():
    return KB([
        R(("300 KB", "do_increase_300"), ("500 KB", "do_increase_500"), ("1 MB", "do_increase_1024"), ("2 MB", "do_increase_2048")),
        R(("✏️ Custom KB", "do_increase_custom")),
        R(BACK, ("🏠 Main", "menu_main")),
    ])

def crop_menu():
    return KB([
        R(("⬛ 1:1 Square", "do_crop_square"), ("📱 9:16 Story", "do_crop_story"), ("🖼 4:5 Post", "do_crop_post")),
        R(("🖥 16:9 Wide", "do_crop_wide"), ("🐦 2:1 Twitter", "do_crop_twitter"), ("📐 Custom", "do_ratio_custom")),
        R(BACK, ("🏠 Main", "menu_main")),
    ])

def rotate_menu():
    return KB([
        R(("↻ 90° CW", "do_rotate_90"), ("↺ 90° CCW", "do_rotate_270"), ("🔄 180°", "do_rotate_180")),
        R(("↕ Flip V", "do_flip_v"), ("↔ Flip H", "do_flip_h")),
        R(BACK, ("🏠 Main", "menu_main")),
    ])

def effects_menu():
    return KB([
        R(("⚫ Grayscale", "do_fx_grayscale"), ("🟤 Sepia", "do_fx_sepia"), ("💨 Blur", "do_fx_blur")),
        R(("🔪 Sharpen", "do_fx_sharpen"), ("☀️ Bright+", "do_fx_brightness_up"), ("🌙 Bright-", "do_fx_brightness_down")),
        R(("🎨 Contrast+", "do_fx_contrast_up"), ("📉 Contrast-", "do_fx_contrast_down"), ("🌈 Vivid", "do_fx_vivid")),
        R(("❄️ Cool", "do_fx_cool"), ("🌅 Warm", "do_fx_warm"), ("🎞 Grain", "do_fx_grain")),
        R(BACK, ("🏠 Main", "menu_main")),
    ])

def collage_menu():
    return KB([
        R(("▦ Grid", "do_collage_grid"), ("▶ Horizontal", "do_collage_horizontal"), ("▼ Vertical", "do_collage_vertical")),
        R(CANCEL),
    ])

def batch_menu():
    return KB([
        R(("📦 Start Collecting", "do_batch_start")),
        R(("🔄 Batch Resize", "do_batch_resize"), ("🗜 Batch Compress", "do_batch_compress")),
        R(("⚫ Batch Grayscale", "do_batch_grayscale"), ("🖼 Batch Collage", "do_batch_collage")),
        R(BACK, ("🏠 Main", "menu_main")),
    ])

def pdf_rotate_menu():
    return KB([
        R(("↻ 90° CW", "do_pdf_rotate_90"), ("↺ 90° CCW", "do_pdf_rotate_270"), ("🔄 180°", "do_pdf_rotate_180")),
        R(BACK, ("🏠 Main", "menu_main")),
    ])

# ── Image helpers ─────────────────────────────────────────────
def compress_to_kb(img, target_kb):
    img = img.convert("RGB")
    lo, hi = 1, 95
    for _ in range(14):
        mid = (lo + hi) // 2
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=mid, optimize=True)
        if buf.tell() <= target_kb * 1024: lo = mid
        else: hi = mid
    buf.seek(0); return buf

def increase_to_kb(img, target_kb):
    img = img.convert("RGB"); scale = 1.0
    for _ in range(25):
        w, h = int(img.width * scale), int(img.height * scale)
        r = img.resize((w, h), Image.LANCZOS)
        buf = io.BytesIO(); r.save(buf, "PNG")
        if buf.tell() / 1024 >= target_kb:
            buf.seek(0); return buf
        scale *= 1.15
    buf.seek(0); return buf

def apply_watermark(img, text, opacity=140):
    img = img.copy().convert("RGBA")
    layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(layer)
    font = None
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
               "/System/Library/Fonts/Helvetica.ttc"]:
        if os.path.exists(p):
            try: font = ImageFont.truetype(p, max(20, int(img.height*0.05))); break
            except: pass
    if not font: font = ImageFont.load_default()
    bb = draw.textbbox((0, 0), text, font=font)
    tw, th = bb[2]-bb[0], bb[3]-bb[1]
    x, y = img.width-tw-30, img.height-th-30
    draw.text((x, y), text, fill=(255, 255, 255, opacity), font=font)
    return Image.alpha_composite(img, layer).convert("RGB")

async def get_img(ctx, fid):
    f = await ctx.bot.get_file(fid)
    return Image.open(io.BytesIO(await f.download_as_bytearray()))

async def get_bytes(ctx, fid):
    f = await ctx.bot.get_file(fid)
    return bytes(await f.download_as_bytearray())

def img_buf(img, fmt="PNG", quality=95):
    buf = io.BytesIO()
    if fmt == "JPG": img = img.convert("RGB"); img.save(buf, "JPEG", quality=quality)
    else: img.save(buf, fmt, quality=quality)
    buf.seek(0); return buf

def make_collage(images, mode="grid"):
    TARGET = 900; PAD = 8
    imgs = [i.convert("RGB") for i in images]; n = len(imgs)
    if mode == "horizontal":
        H = TARGET // 2
        strips = [i.resize((int(i.width * H/i.height), H), Image.LANCZOS) for i in imgs]
        W = sum(s.width for s in strips) + PAD*(n-1)
        c = Image.new("RGB", (W, H), (230, 230, 230))
        x = 0
        for s in strips: c.paste(s, (x, 0)); x += s.width + PAD
    elif mode == "vertical":
        W = TARGET // 2
        strips = [i.resize((W, int(i.height * W/i.width)), Image.LANCZOS) for i in imgs]
        H = sum(s.height for s in strips) + PAD*(n-1)
        c = Image.new("RGB", (W, H), (230, 230, 230))
        y = 0
        for s in strips: c.paste(s, (0, y)); y += s.height + PAD
    else:
        cols = 2; rows = (n+1)//2; cell = TARGET//cols
        c = Image.new("RGB", (cols*cell+PAD*(cols-1), rows*cell+PAD*(rows-1)), (230, 230, 230))
        for i, im in enumerate(imgs):
            im = im.resize((cell, cell), Image.LANCZOS)
            c.paste(im, ((i%cols)*(cell+PAD), (i//cols)*(cell+PAD)))
    buf = io.BytesIO(); c.save(buf, "JPEG", quality=92); buf.seek(0); return buf

CROP_PRESETS = {"square": (1,1), "story": (9,16), "post": (4,5), "wide": (16,9), "twitter": (2,1)}

def crop_ratio(img, preset):
    rw, rh = CROP_PRESETS.get(preset, (1,1))
    ow, oh = img.size; tr = rw/rh; or_ = ow/oh
    if or_ > tr:
        nw = int(oh*tr); l = (ow-nw)//2; return img.crop((l, 0, l+nw, oh))
    nh = int(ow/tr); t = (oh-nh)//2; return img.crop((0, t, ow, t+nh))

# ── PDF helpers ───────────────────────────────────────────────
def compress_pdf(raw: bytes) -> io.BytesIO:
    reader = PdfReader(io.BytesIO(raw))
    writer = PdfWriter()
    writer.append(reader)
    for page in writer.pages:
        try: page.compress_content_streams()
        except: pass
    buf = io.BytesIO(); writer.write(buf); buf.seek(0); return buf

def merge_pdfs(byte_list):
    w = PdfWriter()
    for b in byte_list: w.append(PdfReader(io.BytesIO(b)))
    buf = io.BytesIO(); w.write(buf); buf.seek(0); return buf

def split_pdf(raw):
    r = PdfReader(io.BytesIO(raw)); pages = []
    for i, pg in enumerate(r.pages):
        w = PdfWriter(); w.add_page(pg)
        buf = io.BytesIO(); w.write(buf); buf.seek(0)
        pages.append((i+1, buf))
    return pages

def encrypt_pdf(raw, pw):
    r = PdfReader(io.BytesIO(raw)); w = PdfWriter()
    w.append(r); w.encrypt(pw)
    buf = io.BytesIO(); w.write(buf); buf.seek(0); return buf

def rotate_pdf(raw, angle):
    r = PdfReader(io.BytesIO(raw)); w = PdfWriter()
    for pg in r.pages: pg.rotate(angle); w.add_page(pg)
    buf = io.BytesIO(); w.write(buf); buf.seek(0); return buf

def watermark_pdf(raw, text):
    try:
        from reportlab.pdfgen import canvas as rc
        r = PdfReader(io.BytesIO(raw)); w = PdfWriter()
        for pg in r.pages:
            wbuf = io.BytesIO()
            pw, ph = float(pg.mediabox.width), float(pg.mediabox.height)
            c = rc.Canvas(wbuf, pagesize=(pw, ph))
            c.setFont("Helvetica-Bold", 42)
            c.setFillColorRGB(0.7, 0.7, 0.7, alpha=0.35)
            c.translate(pw/2, ph/2); c.rotate(45)
            c.drawCentredString(0, 0, text); c.save()
            wbuf.seek(0)
            pg.merge_page(PdfReader(wbuf).pages[0]); w.add_page(pg)
        buf = io.BytesIO(); w.write(buf); buf.seek(0); return buf
    except: return io.BytesIO(raw)

def pdf_info(raw):
    r = PdfReader(io.BytesIO(raw)); m = r.metadata or {}
    return (f"\U0001f4c4 *PDF Info*\n"
            f"Pages: {len(r.pages)}\nSize: {len(raw)//1024} KB\n"
            f"Title: {m.get('/Title', '—')}\nAuthor: {m.get('/Author', '—')}\n"
            f"Encrypted: {'Yes' if r.is_encrypted else 'No'}")

def extract_pdf_text(raw):
    if PLUMBER_OK:
        parts = []
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for i, pg in enumerate(pdf.pages, 1):
                parts.append(f"Page {i}\n{pg.extract_text() or ''}")
        return "\n\n".join(parts)
    r = PdfReader(io.BytesIO(raw))
    return "\n\n".join(f"Page {i+1}\n{pg.extract_text() or ''}" for i, pg in enumerate(r.pages))

def extract_pdf_tables(raw):
    if not PLUMBER_OK: raise RuntimeError("pdfplumber not installed")
    out = io.StringIO(); w = csv.writer(out)
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for i, pg in enumerate(pdf.pages, 1):
            for j, tbl in enumerate(pg.extract_tables(), 1):
                w.writerow([f"Page {i} Table {j}"])
                for row in tbl: w.writerow([c or "" for c in row])
                w.writerow([])
    buf = io.BytesIO(out.getvalue().encode()); buf.seek(0); return buf

# ── Social Media Download ─────────────────────────────────────
SM_PATTERNS = [r"pinterest\.com/pin/", r"pin\.it/", r"instagram\.com/p/",
               r"tiktok\.com/@.*/video/", r"youtube\.com/shorts/", r"youtu\.be/",
               r"twitter\.com/.*/status/", r"x\.com/.*/status/"]

def is_sm_link(t): return any(re.search(p, t.lower()) for p in SM_PATTERNS)

async def dl_media(url):
    opts = {"outtmpl": "downloads/%(title)s.%(ext)s", "quiet": True, "no_warnings": True,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=True)
            return {"path": y.prepare_filename(info), "title": info.get("title", "media"),
                    "filesize": info.get("filesize", 0)}
    except:
        if "pinterest" in url.lower(): return await _pinterest_dl(url)
        raise

async def _pinterest_dl(url):
    h = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=h, timeout=15); html = r.text
    for pat, ext, key in [(r'"videoUrl":"(https:[^"]+)"', "mp4", "pinterest_video"),
                          (r'"imageUrl":"(https:[^"]+)"', "jpg", "pinterest_image")]:
        m = re.search(pat, html)
        if m:
            mu = m.group(1).replace("\\/", "/")
            rr = requests.get(mu, headers=h, stream=True, timeout=30)
            fp = f"downloads/{key}.{ext}"
            with open(fp, "wb") as f:
                for chunk in rr.iter_content(8192): f.write(chunk)
            return {"path": fp, "title": key.replace("_", " ").title(), "filesize": os.path.getsize(fp)}
    raise Exception("Could not extract media from Pinterest page")

async def video_to_gif(vp, gp, fps=10, dur=8):
    clip = VideoFileClip(vp)
    if clip.duration > dur: clip = clip.subclip(0, dur)
    if clip.w > 480: clip = clip.resize(width=480)
    clip.write_gif(gp, fps=fps, logger=None); clip.close()

# ── Send helpers ──────────────────────────────────────────────
async def show_menu(chat_id, ctx, text, kb):
    await ctx.bot.send_message(chat_id, text, reply_markup=kb)

async def send_doc(ctx, chat_id, buf, fname, cap):
    await ctx.bot.send_document(chat_id, buf, filename=fname, caption=cap)

async def show_main(chat_id, ctx, caption="Choose a category:"):
    await ctx.bot.send_message(chat_id, caption, reply_markup=main_menu())

# ── Command handlers ──────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.first_name or "there"
    await update.message.reply_text(
        f"👋 Hi {uid}! I'm *MediaBot Pro*\n\n"
        f"Send me an image, PDF, video, or social media link, then pick a tool below.",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\U0001f6e0 *MediaBot Pro*\n\n"
        "\U0001f5bc *Image:* resize, crop, compress, effects, watermark, OCR, collage, batch, remove BG\n"
        "\U0001f4c4 *PDF:* compress, merge, split, encrypt, text, tables, watermarks\n"
        "\U0001f3ac *Other:* video\u2192GIF, social media download, QR codes\n\n"
        "Just send a file and pick what you want to do!",
        parse_mode="Markdown"
    )

# ── Message handlers ──────────────────────────────────────────
async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    fid = update.message.photo[-1].file_id
    cid = update.message.chat_id
    if ctx.user_data.get("batch_mode"):
        ctx.user_data.setdefault("batch_files", []).append(fid)
        n = len(ctx.user_data["batch_files"])
        if n >= MAX_BATCH: ctx.user_data["batch_mode"] = False
        await update.message.reply_text(f"\U0001f4e6 Image {n}/{MAX_BATCH}")
        await show_menu(cid, ctx, "Choose batch operation:", batch_menu())
        return
    if state(ctx) == S.COLLAGE:
        ctx.user_data.setdefault("collage_files", []).append(fid)
        await update.message.reply_text(f"\U0001f5bc {len(ctx.user_data['collage_files'])} image(s)")
        await show_menu(cid, ctx, "Send more or pick layout:", collage_menu())
        return
    ctx.user_data["img_id"] = fid; ctx.user_data.pop("pdf_id", None); clear_state(ctx)
    await update.message.reply_text("✅ Image ready!", reply_markup=image_submenu())

async def on_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if state(ctx) == S.VIDEO_GIF:
        vid = update.message.video
        await update.message.reply_text("⏳ Converting to GIF\u2026")
        f = await ctx.bot.get_file(vid.file_id)
        vp = f"tmp_v_{update.message.chat_id}.mp4"
        gp = f"tmp_g_{update.message.chat_id}.gif"
        await f.download_to_drive(vp)
        try:
            await video_to_gif(vp, gp)
            with open(gp, "rb") as ff:
                await update.message.reply_animation(ff, caption="✅ GIF ready!")
        except Exception as e:
            await update.message.reply_text(f"\u274c {str(e)[:100]}")
        finally:
            for p in [vp, gp]:
                try: os.remove(p)
                except: pass
            clear_state(ctx)
        return
    ctx.user_data["vid_id"] = update.message.video.file_id
    await update.message.reply_text("🎬 Video received!",
        reply_markup=KB([R(("🎬 Convert to GIF", "do_video_gif_prompt"))]))

async def on_doc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document; cid = update.message.chat_id
    if state(ctx) == S.PDF_MERGE and doc.mime_type == "application/pdf":
        ctx.user_data.setdefault("merge_list", []).append(doc.file_id)
        await update.message.reply_text(f"\U0001f4ce PDF {len(ctx.user_data['merge_list'])}. Send more or type *done*.",
                                        parse_mode="Markdown")
        return
    if doc.mime_type and doc.mime_type.startswith("image"):
        ctx.user_data["img_id"] = doc.file_id; ctx.user_data.pop("pdf_id", None)
        await update.message.reply_text("✅ Image ready!", reply_markup=image_submenu())
    elif doc.mime_type == "application/pdf":
        ctx.user_data["pdf_id"] = doc.file_id; ctx.user_data.pop("img_id", None)
        sz = (doc.file_size or 0)//1024
        await update.message.reply_text(f"\U0001f4c4 PDF received ({sz} KB)!", reply_markup=pdf_submenu())
    else:
        await update.message.reply_text("\u26a0 Send an image or PDF.")

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    cid = update.message.chat_id
    s = state(ctx)

    if is_sm_link(txt) and not s:
        await update.message.reply_text("\U0001f4e5 Downloading\u2026")
        try:
            res = await dl_media(txt)
            with open(res["path"], "rb") as f:
                try: await update.message.reply_video(f, caption=f"✅ {res['title']}")
                except: await update.message.reply_document(f, caption=f"✅ {res['title']}")
            os.remove(res["path"])
        except Exception as e:
            err = str(e)
            if "403" in err or "blocked" in err.lower():
                await update.message.reply_text("\u274c Blocked. Download manually.")
            else:
                await update.message.reply_text(f"\u274c {err[:150]}")
        return

    if s == S.PDF_MERGE and txt.lower() == "done":
        lst = ctx.user_data.get("merge_list", [])
        if len(lst) < 2:
            await update.message.reply_text("\u274c Need 2+ PDFs.")
            return
        await update.message.reply_text(f"⏳ Merging {len(lst)} PDFs\u2026")
        try:
            bl = [await get_bytes(ctx, fid) for fid in lst]
            buf = merge_pdfs(bl)
            await send_doc(ctx, cid, buf, "merged.pdf", f"✅ Merged {len(lst)} PDFs!")
        except Exception as e:
            await update.message.reply_text(f"\u274c {str(e)[:100]}")
        finally: clear_state(ctx); ctx.user_data["merge_list"] = []
        return

    img_id = ctx.user_data.get("img_id"); pdf_id = ctx.user_data.get("pdf_id")

    handlers = {
        S.COMPRESS_KB: lambda: _handle_compress_kb(update, ctx, txt, img_id, cid),
        S.INCREASE_KB: lambda: _handle_increase_kb(update, ctx, txt, img_id, cid),
        S.CUSTOM_SIZE: lambda: _handle_custom_size(update, ctx, txt, img_id, cid),
        S.CUSTOM_RATIO: lambda: _handle_custom_ratio(update, ctx, txt, img_id, cid),
        S.PERCENT: lambda: _handle_percent(update, ctx, txt, img_id, cid),
        S.IMG_WM: lambda: _handle_watermark(update, ctx, txt, img_id, cid),
        S.PDF_ENCRYPT: lambda: _handle_pdf_encrypt(update, ctx, txt, pdf_id, cid),
        S.PDF_WM: lambda: _handle_pdf_wm(update, ctx, txt, pdf_id, cid),
        S.QR_TEXT: lambda: _handle_qr(update, ctx, txt, cid),
        S.BATCH_SIZE: lambda: _handle_batch_size(update, ctx, txt, cid),
        S.BATCH_KB: lambda: _handle_batch_kb(update, ctx, txt, cid),
    }
    if s in handlers:
        await handlers[s]()
        return

    await update.message.reply_text("\u2753 Send an image, PDF, or social link. Or use /start.")

async def _handle_compress_kb(update, ctx, txt, img_id, cid):
    try:
        kb = int(txt); assert 1 <= kb <= 50000
        img = await get_img(ctx, img_id); buf = compress_to_kb(img, kb)
        actual = buf.seek(0, 2)//1024; buf.seek(0)
        await send_doc(ctx, cid, buf, f"compressed_{kb}kb.jpg", f"✅ ~{actual} KB")
    except: await update.message.reply_text("\u274c Enter 1\u201350000")
    finally: clear_state(ctx)

async def _handle_increase_kb(update, ctx, txt, img_id, cid):
    try:
        kb = int(txt); assert 1 <= kb <= 200000
        img = await get_img(ctx, img_id); buf = increase_to_kb(img, kb)
        actual = buf.seek(0, 2)//1024; buf.seek(0)
        await send_doc(ctx, cid, buf, f"increased_{kb}kb.png", f"✅ ~{actual} KB")
    except: await update.message.reply_text("\u274c Enter 1\u2013200000")
    finally: clear_state(ctx)

async def _handle_custom_size(update, ctx, txt, img_id, cid):
    try:
        parts = re.split(r"[x\u00d7,\s]+", txt.lower()); w, h = int(parts[0]), int(parts[1])
        assert 1 <= w <= 10000 and 1 <= h <= 10000
        img = await get_img(ctx, img_id); img = img.resize((w, h), Image.LANCZOS)
        await send_doc(ctx, cid, img_buf(img), f"resized_{w}x{h}.png", f"✅ {w}\u00d7{h}")
    except: await update.message.reply_text("\u274c Format: 800x600")
    finally: clear_state(ctx)

async def _handle_custom_ratio(update, ctx, txt, img_id, cid):
    try:
        parts = re.split(r"[:\s]+", txt); rw, rh = int(parts[0]), int(parts[1])
        assert rw > 0 and rh > 0
        img = await get_img(ctx, img_id); ow, oh = img.size; tr = rw/rh; orr = ow/oh
        if orr > tr:
            nw = int(oh*tr); l = (ow-nw)//2; img = img.crop((l, 0, l+nw, oh))
        else:
            nh = int(ow/tr); t = (oh-nh)//2; img = img.crop((0, t, ow, t+nh))
        await send_doc(ctx, cid, img_buf(img), f"ratio_{rw}x{rh}.png", f"✅ {rw}:{rh}")
    except: await update.message.reply_text("\u274c Format: 16:9")
    finally: clear_state(ctx)

async def _handle_percent(update, ctx, txt, img_id, cid):
    try:
        p = int(txt); assert 1 <= p <= 500
        img = await get_img(ctx, img_id)
        nw, nh = int(img.width*p/100), int(img.height*p/100)
        img = img.resize((nw, nh), Image.LANCZOS)
        await send_doc(ctx, cid, img_buf(img), f"resized_{p}pct.png", f"✅ {p}% \u2192 {nw}\u00d7{nh}")
    except: await update.message.reply_text("\u274c Enter 1\u2013500")
    finally: clear_state(ctx)

async def _handle_watermark(update, ctx, txt, img_id, cid):
    try:
        img = await get_img(ctx, img_id); img = apply_watermark(img, txt)
        await send_doc(ctx, cid, img_buf(img), "watermarked.png", "✅ Done!")
    except Exception as e: await update.message.reply_text(f"\u274c {e}")
    finally: clear_state(ctx)

async def _handle_pdf_encrypt(update, ctx, txt, pdf_id, cid):
    try:
        raw = await get_bytes(ctx, pdf_id); buf = encrypt_pdf(raw, txt)
        await send_doc(ctx, cid, buf, "encrypted.pdf", f"✅ Password: `{txt}`")
    except Exception as e: await update.message.reply_text(f"\u274c {e}")
    finally: clear_state(ctx)

async def _handle_pdf_wm(update, ctx, txt, pdf_id, cid):
    try:
        raw = await get_bytes(ctx, pdf_id); buf = watermark_pdf(raw, txt)
        await send_doc(ctx, cid, buf, "watermarked.pdf", "✅ Done!")
    except Exception as e: await update.message.reply_text(f"\u274c {e}")
    finally: clear_state(ctx)

async def _handle_qr(update, ctx, txt, cid):
    if not QR_OK:
        await update.message.reply_text("\u274c qrcode library not installed.")
        clear_state(ctx); return
    try:
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
        qr.add_data(txt); qr.make(fit=True)
        qimg = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qimg = qimg.resize((400, 400), Image.LANCZOS)
        await send_doc(ctx, cid, img_buf(qimg), "qrcode.png", "✅ QR code ready!")
    except Exception as e: await update.message.reply_text(f"\u274c {e}")
    finally: clear_state(ctx)

async def _handle_batch_size(update, ctx, txt, cid):
    try:
        parts = re.split(r"[x\u00d7,\s]+", txt.lower()); w, h = int(parts[0]), int(parts[1])
        fids = ctx.user_data.get("batch_files", [])
        await update.message.reply_text(f"⏳ Resizing {len(fids)} images to {w}\u00d7{h}\u2026")
        zb = io.BytesIO()
        with zipfile.ZipFile(zb, "w") as zf:
            for i, fid in enumerate(fids):
                img = await get_img(ctx, fid); img = img.resize((w, h), Image.LANCZOS)
                b = io.BytesIO(); img.save(b, "PNG"); zf.writestr(f"resized_{i+1}.png", b.getvalue())
        zb.seek(0); await send_doc(ctx, cid, zb, "batch_resized.zip", f"✅ {len(fids)} done!")
    except: await update.message.reply_text("\u274c Format: 800x600")
    finally: clear_state(ctx); ctx.user_data["batch_files"] = []

async def _handle_batch_kb(update, ctx, txt, cid):
    try:
        kb = int(txt)
        fids = ctx.user_data.get("batch_files", [])
        await update.message.reply_text(f"⏳ Compressing {len(fids)} images to {kb} KB\u2026")
        zb = io.BytesIO()
        with zipfile.ZipFile(zb, "w") as zf:
            for i, fid in enumerate(fids):
                img = await get_img(ctx, fid); b = compress_to_kb(img, kb)
                zf.writestr(f"compressed_{i+1}.jpg", b.getvalue())
        zb.seek(0); await send_doc(ctx, cid, zb, "batch_compressed.zip", f"✅ {len(fids)} done!")
    except: await update.message.reply_text("\u274c Enter a number")
    finally: clear_state(ctx); ctx.user_data["batch_files"] = []

# ═══════════════════════════════════════════════════════════════
#  BUTTON HANDLER
# ═══════════════════════════════════════════════════════════════
async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    d = q.data; cid = q.message.chat_id
    img_id = ctx.user_data.get("img_id"); pdf_id = ctx.user_data.get("pdf_id")

    if d == "noop": return

    # ── Navigation ──────────────────────────────────────────
    nav = {
        "menu_main": ("Choose a category:", main_menu()),
        "menu_img": ("\U0001f5bc Image Tools:", image_submenu()),
        "menu_pdf": ("\U0001f4c4 PDF Tools:", pdf_submenu()),
        "menu_other": ("\u26a1 Other Tools:", other_submenu()),
        "menu_help": ("\u2753 Send an image, PDF, or link. Pick a tool above!", main_menu()),
        "menu_img_resize": ("\U0001f4d0 Resize:", resize_menu()),
        "menu_img_convert": ("\U0001f504 Convert:", convert_menu()),
        "menu_img_compress": ("\U0001f5dc Compress to:", compress_menu()),
        "menu_img_increase": ("\U0001f4c8 Increase to:", increase_menu()),
        "menu_img_crop": ("\u2702 Crop preset:", crop_menu()),
        "menu_img_rotate": ("\U0001f504 Rotate/Flip:", rotate_menu()),
        "menu_img_effects": ("\U0001f3a8 Effects:", effects_menu()),
        "menu_collage": ("\U0001f5bc Collage:", collage_menu()),
        "menu_batch": ("\U0001f4e6 Batch:", batch_menu()),
        "menu_pdf_rotate": ("\U0001f504 Rotate PDF:", pdf_rotate_menu()),
    }
    if d in nav:
        txt, kb = nav[d]
        await q.edit_message_text(txt, reply_markup=kb)
        return

    # ── Text prompts with Cancel ────────────────────────────
    prompts = {
        "do_compress_custom": (S.COMPRESS_KB, "\u270f Target size in KB (e.g. 150):"),
        "do_increase_custom": (S.INCREASE_KB, "\u270f Target size in KB (e.g. 800):"),
        "do_resize_custom": (S.CUSTOM_SIZE, "\u270f Size (e.g. 800x600):"),
        "do_ratio_custom": (S.CUSTOM_RATIO, "\u270f Ratio (e.g. 16:9):"),
        "do_percent_prompt": (S.PERCENT, "\u270f Percentage (e.g. 75 or 150):"),
        "do_wm_prompt": (S.IMG_WM, "\u270f Watermark text:"),
        "do_video_gif_prompt": (S.VIDEO_GIF, "\U0001f3ac Send video file (max 8s):"),
        "do_qr_prompt": (S.QR_TEXT, "\U0001f532 Enter text or URL:"),
        "do_pdf_encrypt": (S.PDF_ENCRYPT, "\U0001f512 Enter password:"),
        "do_pdf_wm_prompt": (S.PDF_WM, "\u270f Watermark text for PDF:"),
    }
    if d in prompts:
        s, msg = prompts[d]
        set_state(ctx, s)
        cancel_kb = KB([CANCEL])
        if d == "do_video_gif_prompt":
            await q.edit_message_text(msg, reply_markup=cancel_kb)
        elif d == "do_qr_prompt":
            await q.edit_message_text(msg, reply_markup=cancel_kb)
        else:
            await q.edit_message_text(msg, reply_markup=cancel_kb)
        return

    if d == "do_dl_prompt":
        await q.edit_message_text("\U0001f4e5 Send a Pinterest, Instagram, TikTok, YouTube Shorts, or X link.",
                                  reply_markup=KB([CANCEL]))
        return

    if d == "do_pdf_merge_start":
        set_state(ctx, S.PDF_MERGE); ctx.user_data["merge_list"] = []
        await q.edit_message_text("\U0001f4ce Send PDFs one by one. Type *done* to finish.",
                                  parse_mode="Markdown", reply_markup=KB([CANCEL]))
        return

    # ── Collage collection ──────────────────────────────────
    if d in ("do_collage_grid", "do_collage_horizontal", "do_collage_vertical"):
        mode = d.split("_")[-1]
        fids = ctx.user_data.get("collage_files", [])
        if len(fids) < 2:
            set_state(ctx, S.COLLAGE); ctx.user_data["collage_files"] = []
            ctx.user_data["collage_mode"] = mode
            await q.edit_message_text("\U0001f5bc Send images. Pick layout when done.",
                                      reply_markup=collage_menu())
            return
        await q.edit_message_text(f"⏳ Building {mode} collage\u2026")
        try:
            imgs = [await get_img(ctx, fid) for fid in fids]
            buf = make_collage(imgs, mode)
            await send_doc(ctx, cid, buf, "collage.jpg", "\u2705 Ready!")
        except Exception as e:
            await ctx.bot.send_message(cid, f"\u274c {e}")
        finally: clear_state(ctx); ctx.user_data["collage_files"] = []
        await show_main(cid, ctx)
        return

    # ── Batch ops ───────────────────────────────────────────
    if d == "do_batch_start":
        ctx.user_data["batch_mode"] = True; ctx.user_data["batch_files"] = []
        cancel_kb = KB([CANCEL])
        await q.edit_message_text(f"\U0001f4e6 Batch mode on. Send up to {MAX_BATCH} images.",
                                  reply_markup=cancel_kb)
        return

    if d == "do_batch_resize":
        if not ctx.user_data.get("batch_files"):
            await q.edit_message_text("\u274c No images collected."); return
        set_state(ctx, S.BATCH_SIZE)
        await q.edit_message_text("\u270f Target size (e.g. 800x600):", reply_markup=KB([CANCEL]))
        return

    if d == "do_batch_compress":
        if not ctx.user_data.get("batch_files"):
            await q.edit_message_text("\u274c No images collected."); return
        set_state(ctx, S.BATCH_KB)
        await q.edit_message_text("\u270f Target KB:", reply_markup=KB([CANCEL]))
        return

    if d == "do_batch_grayscale":
        fids = ctx.user_data.get("batch_files", [])
        if not fids: await q.edit_message_text("\u274c No images."); return
        await q.edit_message_text(f"⏳ Converting {len(fids)} images\u2026")
        zb = io.BytesIO()
        with zipfile.ZipFile(zb, "w") as zf:
            for i, fid in enumerate(fids):
                img = await get_img(ctx, fid); img = img.convert("L")
                b = io.BytesIO(); img.save(b, "PNG"); zf.writestr(f"gray_{i+1}.png", b.getvalue())
        zb.seek(0); await send_doc(ctx, cid, zb, "batch_grayscale.zip", f"\u2705 {len(fids)} done!")
        ctx.user_data["batch_files"] = []
        await show_main(cid, ctx)
        return

    if d == "do_batch_collage":
        fids = ctx.user_data.get("batch_files", [])
        if len(fids) < 2: await q.edit_message_text("\u274c Need 2+ images."); return
        await q.edit_message_text("⏳ Building collage\u2026")
        imgs = [await get_img(ctx, fid) for fid in fids]
        buf = make_collage(imgs, "grid")
        await send_doc(ctx, cid, buf, "batch_collage.jpg", "\u2705 Ready!")
        ctx.user_data["batch_files"] = []
        await show_main(cid, ctx)
        return

    # ── Image checks ────────────────────────────────────────
    IMAGE_CBS = (
        d.startswith("do_resize_") or d.startswith("do_compress_") or
        d.startswith("do_increase_") or d.startswith("do_convert_") or
        d.startswith("do_fx_") or d.startswith("do_rotate_") or
        d.startswith("do_flip_") or d.startswith("do_crop_") or
        d in ("do_img_info", "do_auto_color", "do_remove_exif", "do_add_border",
              "do_remove_bg", "do_ocr", "do_exif", "do_img2pdf")
    )
    if IMAGE_CBS and not img_id:
        await q.edit_message_text("\u274c No image loaded. Send an image first.",
                                  reply_markup=KB([("📷 Send Image", "menu_main")]))
        return

    PDF_CBS = (d.startswith("do_pdf_") or d in ("do_pdf2jpg",))
    if PDF_CBS and not pdf_id:
        await q.edit_message_text("\u274c No PDF loaded. Send a PDF file first.",
                                  reply_markup=KB([("📄 Send PDF", "menu_main")]))
        return

    # ── Image info ──────────────────────────────────────────
    if d == "do_img_info":
        img = await get_img(ctx, img_id)
        try:
            from PIL.ExifTags import TAGS
            ex = img._getexif()
            exif_str = ""
            if ex:
                bits = []
                for tid, val in list(ex.items())[:8]:
                    if not isinstance(val, bytes):
                        bits.append(f"{TAGS.get(tid, tid)}: {str(val)[:40]}")
                exif_str = "\n".join(bits)
        except: exif_str = ""
        txt = (f"\U0001f4ca *Image Info*\n"
               f"Size: {img.width}\u00d7{img.height} px\nMode: {img.mode}\n"
               f"Format: {img.format or 'memory'}"
               + (f"\n\n*EXIF:*\n{exif_str}" if exif_str else ""))
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=image_submenu())
        return

    # ── Resize presets ──────────────────────────────────────
    if d.startswith("do_resize_"):
        parts = d.split("_"); w, h = int(parts[2]), int(parts[3])
        img = await get_img(ctx, img_id); img = img.resize((w, h), Image.LANCZOS)
        await q.edit_message_text(f"⏳ Resizing to {w}\u00d7{h}\u2026")
        await send_doc(ctx, cid, img_buf(img), f"resized_{w}x{h}.png", f"\u2705 {w}\u00d7{h}")
        await show_main(cid, ctx)
        return

    # ── Compress presets ────────────────────────────────────
    if d.startswith("do_compress_"):
        kb = int(d.split("_")[-1])
        await q.edit_message_text(f"⏳ Compressing to {kb} KB\u2026")
        img = await get_img(ctx, img_id); buf = compress_to_kb(img, kb)
        actual = buf.seek(0, 2)//1024; buf.seek(0)
        await send_doc(ctx, cid, buf, f"compressed_{kb}kb.jpg", f"\u2705 ~{actual} KB")
        await show_main(cid, ctx)
        return

    # ── Increase presets ────────────────────────────────────
    if d.startswith("do_increase_"):
        kb = int(d.split("_")[-1])
        await q.edit_message_text(f"⏳ Increasing to {kb} KB\u2026")
        img = await get_img(ctx, img_id); buf = increase_to_kb(img, kb)
        actual = buf.seek(0, 2)//1024; buf.seek(0)
        await send_doc(ctx, cid, buf, f"increased_{kb}kb.png", f"\u2705 ~{actual} KB")
        await show_main(cid, ctx)
        return

    # ── Crop presets ────────────────────────────────────────
    if d.startswith("do_crop_"):
        preset = d[len("do_crop_"):]
        img = await get_img(ctx, img_id); img = crop_ratio(img, preset)
        await send_doc(ctx, cid, img_buf(img), f"crop_{preset}.png", f"\u2705 {preset}")
        await show_main(cid, ctx)
        return

    # ── Rotate / flip ───────────────────────────────────────
    if d.startswith("do_rotate_"):
        angle = int(d.split("_")[-1])
        img = await get_img(ctx, img_id); img = img.rotate(angle, expand=True)
        await send_doc(ctx, cid, img_buf(img), f"rotated_{angle}.png", f"\u2705 {angle}\u00b0")
        await show_main(cid, ctx)
        return
    if d == "do_flip_v":
        img = await get_img(ctx, img_id); img = img.transpose(Image.FLIP_TOP_BOTTOM)
        await send_doc(ctx, cid, img_buf(img), "flipped_v.png", "\u2705 Vertical")
        await show_main(cid, ctx); return
    if d == "do_flip_h":
        img = await get_img(ctx, img_id); img = img.transpose(Image.FLIP_LEFT_RIGHT)
        await send_doc(ctx, cid, img_buf(img), "flipped_h.png", "\u2705 Horizontal")
        await show_main(cid, ctx); return

    # ── Effects ─────────────────────────────────────────────
    if d.startswith("do_fx_"):
        fx = d[len("do_fx_"):]; await q.edit_message_text("⏳ Applying\u2026")
        img = await get_img(ctx, img_id)
        if fx == "grayscale": img = img.convert("L")
        elif fx == "sepia":
            img = img.convert("RGB"); w, h = img.size; px = img.load()
            for x in range(w):
                for y in range(h):
                    r, g, b = px[x, y]
                    px[x, y] = (min(int(0.393*r+0.769*g+0.189*b), 255),
                                min(int(0.349*r+0.686*g+0.168*b), 255),
                                min(int(0.272*r+0.534*g+0.131*b), 255))
        elif fx == "blur": img = img.filter(ImageFilter.BLUR)
        elif fx == "sharpen": img = img.filter(ImageFilter.SHARPEN)
        elif fx == "brightness_up": img = ImageEnhance.Brightness(img).enhance(1.5)
        elif fx == "brightness_down": img = ImageEnhance.Brightness(img).enhance(0.6)
        elif fx == "contrast_up": img = ImageEnhance.Contrast(img).enhance(1.5)
        elif fx == "contrast_down": img = ImageEnhance.Contrast(img).enhance(0.6)
        elif fx == "vivid": img = ImageEnhance.Color(img).enhance(1.8)
        elif fx == "cool":
            img = img.convert("RGB"); r, g, b = img.split()
            r = r.point(lambda i: max(0, i-20)); b = b.point(lambda i: min(255, i+20))
            img = Image.merge("RGB", (r, g, b))
        elif fx == "warm":
            img = img.convert("RGB"); r, g, b = img.split()
            r = r.point(lambda i: min(255, i+20)); b = b.point(lambda i: max(0, i-15))
            img = Image.merge("RGB", (r, g, b))
        elif fx == "grain":
            import random; img = img.convert("RGB"); px = img.load()
            for x in range(img.width):
                for y in range(img.height):
                    n = random.randint(-18, 18); r, g, b = px[x, y]
                    px[x, y] = (max(0, min(255, r+n)), max(0, min(255, g+n)), max(0, min(255, b+n)))
        await send_doc(ctx, cid, img_buf(img), f"{fx}.png", f"\u2705 {fx.replace('_', ' ').title()}")
        await show_main(cid, ctx)
        return

    # ── Convert ─────────────────────────────────────────────
    if d.startswith("do_convert_"):
        fmt = d.split("_")[-1]
        await q.edit_message_text(f"⏳ Converting to {fmt}\u2026")
        img = await get_img(ctx, img_id)
        await send_doc(ctx, cid, img_buf(img, fmt), f"converted.{fmt.lower()}", f"\u2705 {fmt}")
        await show_main(cid, ctx)
        return

    # ── Image → PDF ────────────────────────────────────────
    if d == "do_img2pdf":
        await q.edit_message_text("⏳ Converting to PDF\u2026")
        img = await get_img(ctx, img_id); img = img.convert("RGB")
        tmp = io.BytesIO(); img.save(tmp, "JPEG"); tmp.seek(0)
        buf = io.BytesIO(img2pdf.convert(tmp.read())); buf.seek(0)
        await send_doc(ctx, cid, buf, "converted.pdf", "\u2705 PDF ready!")
        await show_main(cid, ctx)
        return

    # ── Misc image ops ──────────────────────────────────────
    if d == "do_auto_color":
        img = await get_img(ctx, img_id); img = ImageEnhance.Color(img).enhance(1.3)
        await send_doc(ctx, cid, img_buf(img), "auto_color.png", "\u2705 Done")
        await show_main(cid, ctx); return

    if d == "do_remove_exif":
        img = await get_img(ctx, img_id)
        clean = Image.new(img.mode, img.size); clean.putdata(list(img.getdata()))
        await send_doc(ctx, cid, img_buf(clean), "no_exif.png", "\u2705 Stripped")
        await show_main(cid, ctx); return

    if d == "do_exif":
        img = await get_img(ctx, img_id)
        try:
            from PIL.ExifTags import TAGS
            ex = img._getexif(); lines = ["\U0001f4f7 *Full EXIF*\n"]
            if ex:
                for tid, val in ex.items():
                    if isinstance(val, bytes): continue
                    lines.append(f"*{TAGS.get(tid, tid)}:* {str(val)[:60]}")
            txt = "\n".join(lines) if len(lines) > 1 else "No EXIF data."
        except: txt = "Could not read EXIF."
        await q.edit_message_text(txt[:4000], parse_mode="Markdown", reply_markup=image_submenu())
        return

    if d == "do_add_border":
        img = await get_img(ctx, img_id); B = 20
        c = Image.new("RGB", (img.width+2*B, img.height+2*B), (255, 255, 255))
        c.paste(img, (B, B))
        await send_doc(ctx, cid, img_buf(c), "bordered.png", "\u2705 Border added")
        await show_main(cid, ctx); return

    if d == "do_remove_bg":
        if not REMBG_OK:
            await q.edit_message_text("\u274c rembg not installed."); return
        await q.edit_message_text("⏳ Removing background\u2026")
        raw = await get_bytes(ctx, img_id); result = rembg_remove(raw)
        buf = io.BytesIO(result); buf.seek(0)
        await send_doc(ctx, cid, buf, "no_bg.png", "\u2705 Background removed!")
        await show_main(cid, ctx); return

    if d == "do_ocr":
        if not OCR_OK:
            await q.edit_message_text("\u274c pytesseract not installed."); return
        await q.edit_message_text("⏳ Extracting text\u2026")
        img = await get_img(ctx, img_id)
        txt = pytesseract.image_to_string(img).strip() or "No text found."
        buf = io.BytesIO(txt.encode()); buf.seek(0)
        await send_doc(ctx, cid, buf, "ocr_result.txt", f"\u2705 {len(txt)} chars")
        await show_main(cid, ctx); return

    # ══════════════════════════════════════════════════════════
    #  PDF OPERATIONS
    # ══════════════════════════════════════════════════════════
    if d == "do_pdf_compress":
        await q.edit_message_text("⏳ Compressing PDF\u2026")
        try:
            raw = await get_bytes(ctx, pdf_id)
            orig_kb = len(raw)//1024; buf = compress_pdf(raw)
            new_kb = buf.seek(0, 2)//1024; buf.seek(0)
            await send_doc(ctx, cid, buf, "compressed.pdf",
                           f"\u2705 {orig_kb} KB \u2192 {new_kb} KB")
        except Exception as e:
            await ctx.bot.send_message(cid, f"\u274c {str(e)[:150]}")
        await show_main(cid, ctx); return

    if d == "do_pdf_info":
        raw = await get_bytes(ctx, pdf_id)
        await q.edit_message_text(pdf_info(raw), parse_mode="Markdown", reply_markup=pdf_submenu())
        return

    if d == "do_pdf_text":
        await q.edit_message_text("⏳ Extracting text\u2026")
        raw = await get_bytes(ctx, pdf_id)
        try:
            txt = extract_pdf_text(raw)
            buf = io.BytesIO(txt.encode()); buf.seek(0)
            await send_doc(ctx, cid, buf, "extracted_text.txt", "\u2705 Done!")
        except Exception as e: await ctx.bot.send_message(cid, f"\u274c {e}")
        await show_main(cid, ctx); return

    if d == "do_pdf_tables":
        await q.edit_message_text("⏳ Extracting tables\u2026")
        raw = await get_bytes(ctx, pdf_id)
        try:
            buf = extract_pdf_tables(raw)
            await send_doc(ctx, cid, buf, "tables.csv", "\u2705 CSV ready!")
        except Exception as e: await ctx.bot.send_message(cid, f"\u274c {e}")
        await show_main(cid, ctx); return

    if d == "do_pdf2jpg":
        await q.edit_message_text("⏳ Converting pages to JPG\u2026")
        raw = await get_bytes(ctx, pdf_id)
        try:
            from pdf2image import convert_from_bytes
            pages = convert_from_bytes(raw, dpi=150)
            for i, pg in enumerate(pages, 1):
                buf = io.BytesIO(); pg.save(buf, "JPEG", quality=90); buf.seek(0)
                await ctx.bot.send_document(cid, buf, filename=f"page_{i}.jpg")
        except Exception as e: await ctx.bot.send_message(cid, f"\u274c {e}")
        await show_main(cid, ctx); return

    if d == "do_pdf_split":
        await q.edit_message_text("⏳ Splitting\u2026")
        raw = await get_bytes(ctx, pdf_id); pages = split_pdf(raw)
        if len(pages) <= 10:
            for n, buf in pages: await ctx.bot.send_document(cid, buf, filename=f"page_{n}.pdf")
        else:
            zb = io.BytesIO()
            with zipfile.ZipFile(zb, "w") as zf:
                for n, buf in pages: zf.writestr(f"page_{n}.pdf", buf.getvalue())
            zb.seek(0); await send_doc(ctx, cid, zb, "split_pages.zip", f"\u2705 {len(pages)} pages")
        await show_main(cid, ctx); return

    if d == "do_pdf_decrypt":
        await q.edit_message_text("⏳ Removing encryption\u2026")
        raw = await get_bytes(ctx, pdf_id)
        try:
            r = PdfReader(io.BytesIO(raw))
            if r.is_encrypted: r.decrypt("")
            w = PdfWriter()
            for pg in r.pages: w.add_page(pg)
            buf = io.BytesIO(); w.write(buf); buf.seek(0)
            await send_doc(ctx, cid, buf, "decrypted.pdf", "\u2705 Decrypted!")
        except Exception as e: await ctx.bot.send_message(cid, f"\u274c {str(e)[:100]}")
        await show_main(cid, ctx); return

    if d.startswith("do_pdf_rotate_"):
        angle = int(d.split("_")[-1])
        await q.edit_message_text(f"⏳ Rotating {angle}\u00b0\u2026")
        raw = await get_bytes(ctx, pdf_id); buf = rotate_pdf(raw, angle)
        await send_doc(ctx, cid, buf, f"rotated_{angle}.pdf", f"\u2705 {angle}\u00b0")
        await show_main(cid, ctx); return

    await q.edit_message_text("\u2753 Unknown action.", reply_markup=main_menu())

# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    os.makedirs("downloads", exist_ok=True)
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.VIDEO, on_video))
    app.add_handler(MessageHandler(filters.Document.ALL, on_doc))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("✅ MediaBot Pro started.")
    app.run_polling()
