import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
import os

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Replace with your actual bot token
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context):
    await update.message.reply_text("Hello! Send me a video, and I'll try to download it for you.")

async def download_video(update: Update, context):
    if update.message.video:
        file_id = update.message.video.file_id
        file_name = update.message.video.file_name or "telegram_video.mp4"
        
        # Get file object from Telegram
        new_file = await context.bot.get_file(file_id)
        
        # Define the download path
        download_path = os.path.join("downloads", file_name)
        os.makedirs("downloads", exist_ok=True) # Create 'downloads' directory if it doesn't exist
        
        # Download the file
        await new_file.download_to_drive(download_path)
        
        await update.message.reply_text(f"Video downloaded successfully to: {download_path}")
        logging.info(f"Downloaded video: {file_name}")
    else:
        await update.message.reply_text("Please send a video for me to download.")

async def echo(update: Update, context):
    """Echo all other messages back to the user."""
    await update.message.reply_text("I can only download videos for now. Please send a video or /start.")

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VIDEO, download_video))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
