import os, io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from PIL import Image
import img2pdf

TOKEN = os.environ.get("TOKEN")

# ── helpers ──────────────────────────────────────────────────────────────────

def compress_to_kb(img: Image.Image, target_kb: int) -> io.BytesIO:
    """Binary-search JPEG quality until file fits target KB."""
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

def build_main_menu():
    keyboard = [
        [InlineKeyboardButton("🔄 Convert Format", callback_data="menu_convert"),
         InlineKeyboardButton("📐 Resize", callback_data="menu_resize")],
        [InlineKeyboardButton("🗜 Compress to KB", callback_data="menu_compress"),
         InlineKeyboardButton("📄 To PDF", callback_data="do_pdf")],
        [InlineKeyboardButton("📑 PDF → JPG", callback_data="menu_pdf2jpg")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_convert_menu():
    keyboard = [
        [InlineKeyboardButton("🖼 PNG",  callback_data="do_convert_PNG"),
         InlineKeyboardButton("📷 JPG",  callback_data="do_convert_JPG"),
         InlineKeyboardButton("🌐 WEBP", callback_data="do_convert_WEBP")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_resize_menu():
    keyboard = [
        [InlineKeyboardButton("HD 1280×720",   callback_data="do_resize_1280_720"),
         InlineKeyboardButton("FHD 1920×1080", callback_data="do_resize_1920_1080")],
        [InlineKeyboardButton("Small 640×480", callback_data="do_resize_640_480"),
         InlineKeyboardButton("Thumb 256×256", callback_data="do_resize_256_256")],
        [InlineKeyboardButton("Square 1080×1080", callback_data="do_resize_1080_1080"),
         InlineKeyboardButton("4K 3840×2160",     callback_data="do_resize_3840_2160")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_compress_menu():
    keyboard = [
        [InlineKeyboardButton("50 KB",  callback_data="do_compress_50"),
         InlineKeyboardButton("100 KB", callback_data="do_compress_100"),
         InlineKeyboardButton("200 KB", callback_data="do_compress_200")],
        [InlineKeyboardButton("500 KB", callback_data="do_compress_500"),
         InlineKeyboardButton("1 MB",   callback_data="do_compress_1000")],
        [InlineKeyboardButton("✏️ Custom KB", callback_data="do_compress_custom")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def send_menu(chat_id, context, text="🎨 *What do you want to do?*"):
    await context.bot.send_message(
        chat_id, text,
        parse_mode="Markdown",
        reply_markup=build_main_menu()
    )

async def get_image(context, file_id) -> Image.Image | None:
    file = await context.bot.get_file(file_id)
    data = await file.download_as_bytearray()
    return Image.open(io.BytesIO(data))

# ── handlers ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Image Converter Bot*\n\nSend me any image and choose what to do!",
        parse_mode="Markdown"
    )

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["file_id"] = update.message.photo[-1].file_id
    context.user_data["waiting_custom_kb"] = False
    await update.message.reply_text("✅ Image received!")
    await send_menu(update.message.chat_id, context)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if doc.mime_type and doc.mime_type.startswith("image"):
        context.user_data["file_id"] = doc.file_id
        context.user_data["waiting_custom_kb"] = False
        await update.message.reply_text("✅ Image received!")
        await send_menu(update.message.chat_id, context)
    else:
        await update.message.reply_text("⚠️ Please send an image file.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_custom_kb"):
        try:
            kb = int(update.message.text.strip())
            assert 1 <= kb <= 50000
        except:
            await update.message.reply_text("❌ Enter a valid number (1–50000 KB)")
            return
        context.user_data["waiting_custom_kb"] = False
        file_id = context.user_data.get("file_id")
        if not file_id:
            await update.message.reply_text("❌ Image expired. Send it again.")
            return
        msg = await update.message.reply_text(f"⏳ Compressing to {kb} KB...")
        img = await get_image(context, file_id)
        buf = compress_to_kb(img, kb)
        actual = buf.seek(0, 2) // 1024; buf.seek(0)
        await context.bot.send_document(
            update.message.chat_id, buf,
            filename=f"compressed_{kb}kb.jpg",
            caption=f"✅ Done! (~{actual} KB)"
        )
        await send_menu(update.message.chat_id, context)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    chat_id = q.message.chat_id

    # ── menus ──
    if d == "menu_main":
        await q.edit_message_text("🎨 *What do you want to do?*",
                                  parse_mode="Markdown",
                                  reply_markup=build_main_menu())
        return
    if d == "menu_convert":
        await q.edit_message_text("🔄 *Choose output format:*",
                                  parse_mode="Markdown",
                                  reply_markup=build_convert_menu())
        return
    if d == "menu_resize":
        await q.edit_message_text("📐 *Choose target size:*",
                                  parse_mode="Markdown",
                                  reply_markup=build_resize_menu())
        return
    if d == "menu_compress":
        await q.edit_message_text("🗜 *Choose target size in KB:*",
                                  parse_mode="Markdown",
                                  reply_markup=build_compress_menu())
        return

    # ── need image for everything below ──
    file_id = context.user_data.get("file_id")
    if not file_id:
        await q.edit_message_text("❌ No image found. Please send an image first.")
        return

    # ── convert ──
    if d.startswith("do_convert_"):
        fmt = d.split("_")[-1]
        await q.edit_message_text(f"⏳ Converting to {fmt}...")
        img = await get_image(context, file_id)
        if fmt == "JPG":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG" if fmt == "JPG" else fmt, quality=95)
        buf.seek(0)
        await context.bot.send_document(chat_id, buf,
                                        filename=f"converted.{fmt.lower()}",
                                        caption=f"✅ Converted to {fmt}!")
        await send_menu(chat_id, context)

    # ── resize ──
    elif d.startswith("do_resize_"):
        _, _, w, h = d.split("_")
        w, h = int(w), int(h)
        await q.edit_message_text(f"⏳ Resizing to {w}×{h}...")
        img = await get_image(context, file_id)
        img = img.resize((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(chat_id, buf,
                                        filename=f"resized_{w}x{h}.png",
                                        caption=f"✅ Resized to {w}×{h}!")
        await send_menu(chat_id, context)

    # ── compress preset ──
    elif d.startswith("do_compress_"):
        val = d.split("_")[-1]
        if val == "custom":
            context.user_data["waiting_custom_kb"] = True
            await q.edit_message_text("✏️ Type the target size in KB (e.g. 150):")
            return
        kb = int(val)
        await q.edit_message_text(f"⏳ Compressing to {kb} KB...")
        img = await get_image(context, file_id)
        buf = compress_to_kb(img, kb)
        actual = buf.seek(0, 2) // 1024; buf.seek(0)
        await context.bot.send_document(chat_id, buf,
                                        filename=f"compressed_{kb}kb.jpg",
                                        caption=f"✅ Done! (~{actual} KB)")
        await send_menu(chat_id, context)

    # ── image → PDF ──
    elif d == "do_pdf":
        await q.edit_message_text("⏳ Converting to PDF...")
        img = await get_image(context, file_id)
        img = img.convert("RGB")
        tmp = io.BytesIO()
        img.save(tmp, format="JPEG")
        tmp.seek(0)
        pdf_buf = io.BytesIO(img2pdf.convert(tmp.read()))
        pdf_buf.seek(0)
        await context.bot.send_document(chat_id, pdf_buf,
                                        filename="converted.pdf",
                                        caption="✅ Converted to PDF!")
        await send_menu(chat_id, context)

    elif d == "menu_pdf2jpg":
        await q.edit_message_text(
            "📑 *PDF → JPG*\n\nSend the PDF file as a *document* and I'll convert it.\n_(Coming soon — send image for now)_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_main")]])
        )

# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Bot running...")
    app.run_polling()
