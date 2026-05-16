import os, io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from PIL import Image
import img2pdf

TOKEN = os.environ.get("TOKEN")

# ── helpers ──────────────────────────────────────────────────────────────────

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

def build_main_menu():
    keyboard = [
        [InlineKeyboardButton("🔄 Convert Format", callback_data="menu_convert"),
         InlineKeyboardButton("📐 Resize",          callback_data="menu_resize")],
        [InlineKeyboardButton("🗜 Compress to KB",  callback_data="menu_compress")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_convert_menu():
    keyboard = [
        [InlineKeyboardButton("🖼 → PNG",  callback_data="do_convert_PNG"),
         InlineKeyboardButton("📷 → JPG",  callback_data="do_convert_JPG"),
         InlineKeyboardButton("🌐 → WEBP", callback_data="do_convert_WEBP")],
        [InlineKeyboardButton("📄 → PDF",  callback_data="do_convert_PDF"),
         InlineKeyboardButton("📑 PDF → JPG", callback_data="do_convert_PDF2JPG")],
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
        [InlineKeyboardButton("✏️ Custom Width×Height", callback_data="do_resize_custom")],
        [InlineKeyboardButton("✏️ Custom Aspect Ratio", callback_data="do_ratio_custom")],
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

async def get_image(context, file_id) -> Image.Image:
    file = await context.bot.get_file(file_id)
    data = await file.download_as_bytearray()
    return Image.open(io.BytesIO(data))

def clear_waiting(context):
    context.user_data["waiting_custom_kb"]    = False
    context.user_data["waiting_custom_size"]  = False
    context.user_data["waiting_custom_ratio"] = False

# ── command handlers ──────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Image & PDF Converter Bot*\n\n"
        "Send me any *image* or *PDF* and choose what to do!\n\n"
        "✅ Convert: PNG, JPG, WEBP, PDF\n"
        "✅ PDF → JPG\n"
        "✅ Resize by pixels or ratio\n"
        "✅ Compress to exact KB",
        parse_mode="Markdown"
    )

# ── receive image ─────────────────────────────────────────────────────────────

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["file_id"]   = update.message.photo[-1].file_id
    context.user_data["file_type"] = "image"
    clear_waiting(context)
    await update.message.reply_text("✅ Image received!")
    await send_menu(update.message.chat_id, context)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if doc.mime_type and doc.mime_type.startswith("image"):
        context.user_data["file_id"]   = doc.file_id
        context.user_data["file_type"] = "image"
        clear_waiting(context)
        await update.message.reply_text("✅ Image received!")
        await send_menu(update.message.chat_id, context)
    elif doc.mime_type == "application/pdf":
        context.user_data["file_id"]   = doc.file_id
        context.user_data["file_type"] = "pdf"
        clear_waiting(context)
        await update.message.reply_text(
            "✅ PDF received!\n\nWhat do you want to do?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📑 PDF → JPG", callback_data="do_convert_PDF2JPG")],
            ])
        )
    else:
        await update.message.reply_text("⚠️ Please send an image or PDF file.")

# ── text input handler ────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    file_id = context.user_data.get("file_id")

    # Custom KB
    if context.user_data.get("waiting_custom_kb"):
        try:
            kb = int(text)
            assert 1 <= kb <= 50000
        except:
            await update.message.reply_text("❌ Enter a valid number e.g. 150")
            return
        clear_waiting(context)
        if not file_id:
            await update.message.reply_text("❌ Image expired. Send it again.")
            return
      async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Custom KB compression
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
        actual = buf.seek(0, 2) // 1024; buf.seek(0)
        await context.bot.send_document(
            update.message.chat_id, buf,
            filename=f"compressed_{kb}kb.jpg",
            caption=f"✅ Done! (~{actual} KB)"
        )
        await send_menu(update.message.chat_id, context)

    # Custom width x height
    elif context.user_data.get("waiting_custom_size"):
        try:
            # Accept formats: 800x600 or 800 600 or 800,600
            parts = text.lower().replace("x", " ").replace(",", " ").split()
            w, h = int(parts[0]), int(parts[1])
            assert 1 <= w <= 10000 and 1 <= h <= 10000
        except:
            await update.message.reply_text("❌ Invalid format. Try: 800x600 or 800 600")
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
            update.message.chat_id, buf,
            filename=f"resized_{w}x{h}.png",
            caption=f"✅ Resized to {w}×{h}!"
        )
        await send_menu(update.message.chat_id, context)

    # Custom aspect ratio
    elif context.user_data.get("waiting_custom_ratio"):
        try:
            # Accept formats: 16:9 or 16 9 or 4:3
            parts = text.replace(":", " ").split()
            rw, rh = int(parts[0]), int(parts[1])
            assert rw > 0 and rh > 0
        except:
            await update.message.reply_text("❌ Invalid format. Try: 16:9 or 4:3")
            return
        context.user_data["waiting_custom_ratio"] = False
        file_id = context.user_data.get("file_id")
        if not file_id:
            await update.message.reply_text("❌ Image expired. Send it again.")
            return
        await update.message.reply_text(f"⏳ Cropping to {rw}:{rh} ratio...")
        img = await get_image(context, file_id)
        orig_w, orig_h = img.size

        # Calculate crop box to match ratio
        target_ratio = rw / rh
        orig_ratio = orig_w / orig_h

        if orig_ratio > target_ratio:
            # Crop width
            new_w = int(orig_h * target_ratio)
            left = (orig_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, orig_h))
        else:
            # Crop height
            new_h = int(orig_w / target_ratio)
            top = (orig_h - new_h) // 2
            img = img.crop((0, top, orig_w, top + new_h))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(
            update.message.chat_id, buf,
            filename=f"ratio_{rw}x{rh}.png",
            caption=f"✅ Cropped to {rw}:{rh} ratio!\nNew size: {img.size[0]}×{img.size[1]}"
        )
        await send_menu(update.message.chat_id, context)
        await update.message.reply_text(f"⏳ Compressing to ~{kb} KB...")
        img = await get_image(context, file_id)
        buf = compress_to_kb(img, kb)
        actual = buf.seek(0, 2) // 1024
        buf.seek(0)
        await context.bot.send_document(
            update.message.chat_id, buf,
            filename=f"compressed_{kb}kb.jpg",
            caption=f"✅ Done! (~{actual} KB)"
        )
        await send_menu(update.message.chat_id, context)

    # Custom size
    elif context.user_data.get("waiting_custom_size"):
        try:
            parts = text.lower().replace("x", " ").replace(",", " ").split()
            w, h = int(parts[0]), int(parts[1])
            assert 1 <= w <= 10000 and 1 <= h <= 10000
        except:
            await update.message.reply_text("❌ Invalid. Try: 800x600 or 800 600")
            return
        clear_waiting(context)
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
            update.message.chat_id, buf,
            filename=f"resized_{w}x{h}.png",
            caption=f"✅ Resized to {w}×{h}!"
        )
        await send_menu(update.message.chat_id, context)

    # Custom ratio
    elif context.user_data.get("waiting_custom_ratio"):
        try:
            parts = text.replace(":", " ").split()
            rw, rh = int(parts[0]), int(parts[1])
            assert rw > 0 and rh > 0
        except:
            await update.message.reply_text("❌ Invalid. Try: 16:9 or 4:3")
            return
        clear_waiting(context)
        if not file_id:
            await update.message.reply_text("❌ Image expired. Send it again.")
            return
        await update.message.reply_text(f"⏳ Cropping to {rw}:{rh} ratio...")
        img = await get_image(context, file_id)
        orig_w, orig_h = img.size
        target_ratio = rw / rh
        orig_ratio   = orig_w / orig_h
        if orig_ratio > target_ratio:
            new_w = int(orig_h * target_ratio)
            left  = (orig_w - new_w) // 2
            img   = img.crop((left, 0, left + new_w, orig_h))
        else:
            new_h = int(orig_w / target_ratio)
            top   = (orig_h - new_h) // 2
            img   = img.crop((0, top, orig_w, top + new_h))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_document(
            update.message.chat_id, buf,
            filename=f"ratio_{rw}_{rh}.png",
            caption=f"✅ Cropped to {rw}:{rh}!\nNew size: {img.size[0]}×{img.size[1]}"
        )
        await send_menu(update.message.chat_id, context)

# ── button handler ────────────────────────────────────────────────────────────

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q       = update.callback_query
    await q.answer()
    d       = q.data
    chat_id = q.message.chat_id
    file_id = context.user_data.get("file_id")

    # menus
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
        await q.edit_message_text("🗜 *Choose target size:*",
                                  parse_mode="Markdown",
                                  reply_markup=build_compress_menu())
        return

    if not file_id:
        await q.edit_message_text("❌ No file found. Please send an image or PDF first.")
        return

    # ── convert ──
    if d.startswith("do_convert_"):
        fmt = d.split("_")[-1]

        # Image → PDF
        if fmt == "PDF":
            await q.edit_message_text("⏳ Converting image to PDF...")
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

        # PDF → JPG
        elif fmt == "PDF2JPG":
            await q.edit_message_text("⏳ Converting PDF to JPG images...")
            try:
                from pdf2image import convert_from_bytes
                file  = await context.bot.get_file(file_id)
                data  = await file.download_as_bytearray()
                pages = convert_from_bytes(bytes(data), dpi=150)
                await q.edit_message_text(f"✅ PDF has {len(pages)} page(s). Sending...")
                for i, page in enumerate(pages, 1):
                    buf = io.BytesIO()
                    page.save(buf, format="JPEG", quality=90)
                    buf.seek(0)
                    await context.bot.send_document(
                        chat_id, buf,
                        filename=f"page_{i}.jpg",
                        caption=f"📄 Page {i}/{len(pages)}"
                    )
                    elif d == "do_resize_custom":
        context.user_data["waiting_custom_size"] = True
        context.user_data["waiting_custom_ratio"] = False
        context.user_data["waiting_custom_kb"] = False
        await q.edit_message_text(
            "✏️ *Enter custom size:*\n\nFormats accepted:\n`800x600`\n`1920 1080`\n`800,600`",
            parse_mode="Markdown"
        )

    elif d == "do_ratio_custom":
        context.user_data["waiting_custom_ratio"] = True
        context.user_data["waiting_custom_size"] = False
        context.user_data["waiting_custom_kb"] = False
        await q.edit_message_text(
            "✏️ *Enter aspect ratio:*\n\nFormats accepted:\n`16:9`\n`4:3`\n`1:1`\n`9:16`",
            parse_mode="Markdown"
        )
                await send_menu(chat_id, context)
            except Exception as e:
                await context.bot.send_message(
                    chat_id,
                    "⚠️ PDF→JPG needs Poppler installed on server.\n"
                    "Railway free tier doesn't support it easily.\n"
                    "Try sending the PDF to @pdf2imagebot as alternative."
                )
                await send_menu(chat_id, context)

        # Image → PNG / JPG / WEBP
        else:
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

    # ── resize presets ──
    elif d.startswith("do_resize_") and d != "do_resize_custom":
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

    elif d == "do_resize_custom":
        clear_waiting(context)
        context.user_data["waiting_custom_size"] = True
        await q.edit_message_text(
            "✏️ *Enter custom size:*\n\nExamples:\n`800x600`\n`1920 1080`\n`800,600`",
            parse_mode="Markdown"
        )

    elif d == "do_ratio_custom":
        clear_waiting(context)
        context.user_data["waiting_custom_ratio"] = True
        await q.edit_message_text(
            "✏️ *Enter aspect ratio:*\n\nExamples:\n`16:9`\n`4:3`\n`1:1`\n`9:16`",
            parse_mode="Markdown"
        )

    # ── compress ──
    elif d.startswith("do_compress_"):
        val = d.split("_")[-1]
        if val == "custom":
            clear_waiting(context)
            context.user_data["waiting_custom_kb"] = True
            await q.edit_message_text("✏️ Type the target size in KB (e.g. `150`):",
                                      parse_mode="Markdown")
            return
        kb = int(val)
        await q.edit_message_text(f"⏳ Compressing to ~{kb} KB...")
        img = await get_image(context, file_id)
        buf = compress_to_kb(img, kb)
        actual = buf.seek(0, 2) // 1024
        buf.seek(0)
        await context.bot.send_document(chat_id, buf,
                                        filename=f"compressed_{kb}kb.jpg",
                                        caption=f"✅ Done! (~{actual} KB)")
        await send_menu(chat_id, context)

# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Bot running...")
    app.run_polling()
