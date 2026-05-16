import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from PIL import Image
import io

TOKEN = os.environ.get("TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me an image!\nCommands:\n/topng\n/tojpg\n/towebp"
    )

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['file_id'] = update.message.photo[-1].file_id
    await update.message.reply_text("Got it! Now send /topng or /tojpg or /towebp")

async def to_png(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = context.user_data.get('file_id')
    if not file_id:
        await update.message.reply_text("Send an image first!")
        return
    file = await context.bot.get_file(file_id)
    img_bytes = await file.download_as_bytearray()
    img = Image.open(io.BytesIO(img_bytes))
    output = io.BytesIO()
    img.save(output, format='PNG')
    output.seek(0)
    await update.message.reply_document(output, filename="converted.png")

async def to_jpg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = context.user_data.get('file_id')
    if not file_id:
        await update.message.reply_text("Send an image first!")
        return
    file = await context.bot.get_file(file_id)
    img_bytes = await file.download_as_bytearray()
    img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
    output = io.BytesIO()
    img.save(output, format='JPEG', quality=95)
    output.seek(0)
    await update.message.reply_document(output, filename="converted.jpg")

async def to_webp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = context.user_data.get('file_id')
    if not file_id:
        await update.message.reply_text("Send an image first!")
        return
    file = await context.bot.get_file(file_id)
    img_bytes = await file.download_as_bytearray()
    img = Image.open(io.BytesIO(img_bytes))
    output = io.BytesIO()
    img.save(output, format='WEBP')
    output.seek(0)
    await update.message.reply_document(output, filename="converted.webp")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("topng", to_png))
    app.add_handler(CommandHandler("tojpg", to_jpg))
    app.add_handler(CommandHandler("towebp", to_webp))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    print("Bot running...")
    app.run_polling()
