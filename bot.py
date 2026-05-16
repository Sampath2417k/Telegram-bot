import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from PIL import Image
import io

TOKEN = os.environ.get("TOKEN")

# /start command with buttons
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📷 Send Image to Convert", callback_data='info')],
        [InlineKeyboardButton("ℹ️ Help", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 *Image Converter Bot*\n\nSend me any image and I'll show you options!",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

# Handle button clicks
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'help':
        await query.edit_message_text(
            "📖 *How to use:*\n\n"
            "1. Send me any image\n"
            "2. Choose format: PNG, JPG, WEBP\n"
            "3. Choose size if needed\n"
            "4. Get your converted image!\n\n"
            "Supported formats: PNG, JPG, WEBP",
            parse_mode='Markdown'
        )
    elif data == 'info':
        await query.edit_message_text("Just send me an image directly! 📸")

    elif data.startswith('convert_'):
        fmt = data.split('_')[1].upper()
        file_id = context.user_data.get('file_id')
        if not file_id:
            await query.edit_message_text("❌ Image expired. Please send it again.")
            return
        await query.edit_message_text(f"⏳ Converting to {fmt}...")
        file = await context.bot.get_file(file_id)
        img_bytes = await file.download_as_bytearray()
        img = Image.open(io.BytesIO(img_bytes))
        if fmt == 'JPG':
            img = img.convert('RGB')
        output = io.BytesIO()
        img.save(output, format='JPEG' if fmt == 'JPG' else fmt, quality=95)
        output.seek(0)
        await context.bot.send_document(
            query.message.chat_id,
            output,
            filename=f"converted.{fmt.lower()}",
            caption=f"✅ Converted to {fmt}!"
        )
        await show_options(query.message.chat_id, context)

    elif data.startswith('resize_'):
        size = data.split('_')[1]
        file_id = context.user_data.get('file_id')
        if not file_id:
            await query.edit_message_text("❌ Image expired. Please send it again.")
            return
        sizes = {
            'hd': (1280, 720),
            'fhd': (1920, 1080),
            'small': (640, 480),
            'thumb': (256, 256),
            'sq1k': (1080, 1080),
        }
        w, h = sizes[size]
        await query.edit_message_text(f"⏳ Resizing to {w}x{h}...")
        file = await context.bot.get_file(file_id)
        img_bytes = await file.download_as_bytearray()
        img = Image.open(io.BytesIO(img_bytes))
        img = img.resize((w, h), Image.LANCZOS)
        output = io.BytesIO()
        img.save(output, format='PNG')
        output.seek(0)
        await context.bot.send_document(
            query.message.chat_id,
            output,
            filename=f"resized_{w}x{h}.png",
            caption=f"✅ Resized to {w}x{h}!"
        )
        await show_options(query.message.chat_id, context)

    elif data == 'compress':
        file_id = context.user_data.get('file_id')
        if not file_id:
            await query.edit_message_text("❌ Image expired. Please send it again.")
            return
        await query.edit_message_text("⏳ Compressing image...")
        file = await context.bot.get_file(file_id)
        img_bytes = await file.download_as_bytearray()
        img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=40, optimize=True)
        output.seek(0)
        await context.bot.send_document(
            query.message.chat_id,
            output,
            filename="compressed.jpg",
            caption="✅ Compressed!"
        )
        await show_options(query.message.chat_id, context)

# Show options menu
async def show_options(chat_id, context):
    keyboard = [
        [
            InlineKeyboardButton("🖼 PNG", callback_data='convert_PNG'),
            InlineKeyboardButton("📷 JPG", callback_data='convert_JPG'),
            InlineKeyboardButton("🌐 WEBP", callback_data='convert_WEBP'),
        ],
        [
            InlineKeyboardButton("📐 HD 720p", callback_data='resize_hd'),
            InlineKeyboardButton("📐 FHD 1080p", callback_data='resize_fhd'),
        ],
        [
            InlineKeyboardButton("📐 Small 640x480", callback_data='resize_small'),
            InlineKeyboardButton("📐 Thumb 256x256", callback_data='resize_thumb'),
        ],
        [
            InlineKeyboardButton("📐 Square 1080x1080", callback_data='resize_sq1k'),
            InlineKeyboardButton("🗜 Compress", callback_data='compress'),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id,
        "🎨 *What do you want to do?*\nChoose format or size:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

# Handle incoming image
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['file_id'] = update.message.photo[-1].file_id
    await update.message.reply_text("✅ Image received!")
    await show_options(update.message.chat_id, context)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    print("Bot running...")
    app.run_polling()
