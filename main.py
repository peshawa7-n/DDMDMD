import os
import asyncio
import logging
import subprocess
import requests
import re
from queue import Queue
from threading import Thread

# Install required libraries:
# pip install python-telegram-bot yt-dlp requests

# --- Configuration ---
# You NEED to get these values. Do NOT share them publicly.
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') # Get this from BotFather on Telegram.
STREAMTAPE_API_USERNAME = os.getenv('STREAMTAPE_API_USERNAME') # Get this from your Streamtape account API page.
STREAMTAPE_API_KEY = os.getenv('STREAMTAPE_API_KEY') # Get this from your Streamtape account API page.

# Directory to store downloaded videos temporarily
DOWNLOAD_DIR = "downloads"
# Maximum number of videos to keep in download directory before cleaning up
MAX_DOWNLOADED_VIDEOS = 10

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Global Queue and Processing Status ---
video_queue = Queue()
is_processing = False

# --- Helper Functions ---

def clean_filename(filename):
    """Cleans a filename to be safe for file systems and URLs."""
    # Remove characters that are not alphanumeric, spaces, dashes, or underscores
    filename = re.sub(r'[^\w\s-]', '', filename)
    # Replace spaces with underscores
    filename = re.sub(r'\s+', '_', filename)
    return filename

def download_youtube_video(youtube_url, output_path):
    """
    Downloads a YouTube video in the best available quality (preferably 1080p).
    Uses yt-dlp.
    """
    try:
        logger.info(f"Starting download for: {youtube_url}")
        # Command to download the video.
        # -f "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best" attempts 1080p or best available.
        # --output "%(title)s.%(ext)s" uses the video title as filename.
        # --merge-output-format mp4 ensures video and audio are merged into mp4 if separate streams are downloaded.
        # --no-playlist prevents downloading entire playlists if a playlist URL is provided.
        # --retries 5 for robustness
        # --buffer-size 16K can help with some buffering issues.
        command = [
            "yt-dlp",
            "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "--merge-output-format", "mp4",
            "--no-playlist",
            "--retries", "5",
            "--buffer-size", "16K",
            "-o", f"{output_path}/%(title)s.%(ext)s",
            youtube_url
        ]
        process = subprocess.run(command, capture_output=True, text=True, check=True)
        logger.info(f"Download command output: {process.stdout}")
        if process.stderr:
            logger.error(f"Download command error: {process.stderr}")

        # Find the downloaded file
        # yt-dlp prints the final file path to stdout, often on a line like "[download] Destination: ..."
        match = re.search(r"\[download\] Destination: (.+)", process.stdout)
        if match:
            downloaded_file = match.group(1).strip()
            # Ensure the path is relative to the DOWNLOAD_DIR if yt-dlp outputs an absolute path
            if os.path.isabs(downloaded_file):
                downloaded_file = os.path.relpath(downloaded_file, start=output_path)
            # Prepend output_path to get the full path
            full_path = os.path.join(output_path, downloaded_file)
            logger.info(f"Video downloaded to: {full_path}")
            return full_path
        else:
            logger.error("Could not find downloaded file path in yt-dlp output.")
            return None

    except subprocess.CalledProcessError as e:
        logger.error(f"Error during video download: {e.stderr}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred during download: {e}")
        return None

def upload_to_streamtape(file_path):
    """
    Uploads a file to Streamtape using their API.
    Returns the direct video URL or None on failure.
    """
    logger.info(f"Starting upload for: {file_path}")
    upload_url = "https://api.streamtape.com/file/ul"
    params = {
        "login": STREAMTAPE_API_USERNAME,
        "key": STREAMTAPE_API_KEY
    }

    try:
        # Get upload server URL first
        response = requests.get(upload_url, params=params)
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        upload_data = response.json()

        if upload_data["status"] != 200:
            logger.error(f"Failed to get Streamtape upload URL: {upload_data.get('message', 'Unknown error')}")
            return None

        actual_upload_url = upload_data["result"]["url"]
        logger.info(f"Obtained Streamtape upload URL: {actual_upload_url}")

        with open(file_path, "rb") as f:
            files = {"file1": (os.path.basename(file_path), f)}
            upload_response = requests.post(actual_upload_url, files=files)
            upload_response.raise_for_status() # Raise an HTTPError for bad responses
            upload_result = upload_response.json()

        if upload_result["status"] == 200:
            file_code = upload_result["result"]["code"]
            direct_url = f"https://streamtape.com/v/{file_code}"
            logger.info(f"File uploaded successfully to Streamtape. URL: {direct_url}")
            return direct_url
        else:
            logger.error(f"Streamtape upload failed: {upload_result.get('message', 'Unknown error')}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Network or API error during Streamtape upload: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred during Streamtape upload: {e}")
        return None

def cleanup_old_videos():
    """Removes older videos from the download directory to manage space."""
    try:
        files = [(os.path.getmtime(os.path.join(DOWNLOAD_DIR, f)), os.path.join(DOWNLOAD_DIR, f))
                 for f in os.listdir(DOWNLOAD_DIR) if os.path.isfile(os.path.join(DOWNLOAD_DIR, f))]
        files.sort() # Sort by modification time (oldest first)

        if len(files) > MAX_DOWNLOADED_VIDEOS:
            for i in range(len(files) - MAX_DOWNLOADED_VIDEOS):
                oldest_file = files[i][1]
                try:
                    os.remove(oldest_file)
                    logger.info(f"Cleaned up old file: {oldest_file}")
                except OSError as e:
                    logger.warning(f"Error removing old file {oldest_file}: {e}")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")


# --- Telegram Bot Logic ---
# Importing necessary parts from python-telegram-bot
# This import needs to be here because `import telegram` is slow.
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message when the command /start is issued."""
    await update.message.reply_text(
        "Hello! Send me a YouTube video link and I'll download it and upload it to Streamtape for you."
        "You can send multiple links, and I will process them one by one."
    )

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles YouTube links, adds them to a queue, and starts processing."""
    youtube_url = update.message.text
    # Basic URL validation for YouTube
    if not re.match(r"^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$", youtube_url):
        await update.message.reply_text("That doesn't look like a valid YouTube link. Please send a direct YouTube URL.")
        return

    await update.message.reply_text(f"Received your link: {youtube_url}\nAdding it to the queue...")
    video_queue.put((youtube_url, update.effective_chat.id)) # Store chat ID to send updates back

    # Start the processing thread if not already running
    global is_processing
    if not is_processing:
        is_processing = True
        Thread(target=process_queue, daemon=True).start()
        logger.info("Started queue processing thread.")
    else:
        logger.info("Queue processing thread is already running.")


def process_queue():
    """Processes videos from the queue one by one."""
    global is_processing
    while not video_queue.empty():
        youtube_url, chat_id = video_queue.get()
        logger.info(f"Processing URL: {youtube_url} for chat_id: {chat_id}")

        asyncio.run(send_message_to_chat(chat_id, f"🎬 Starting download for: {youtube_url}"))

        # Ensure download directory exists
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        downloaded_file = download_youtube_video(youtube_url, DOWNLOAD_DIR)

        if downloaded_file:
            asyncio.run(send_message_to_chat(chat_id, f"✅ Download complete! Now uploading '{os.path.basename(downloaded_file)}' to Streamtape..."))
            streamtape_url = upload_to_streamtape(downloaded_file)
            if streamtape_url:
                asyncio.run(send_message_to_chat(chat_id, f"🎉 Upload complete! Here's your Streamtape link:\n{streamtape_url}"))
                # Clean up the downloaded file after successful upload
                try:
                    os.remove(downloaded_file)
                    logger.info(f"Removed downloaded file: {downloaded_file}")
                except OSError as e:
                    logger.warning(f"Error removing downloaded file {downloaded_file}: {e}")
            else:
                asyncio.run(send_message_to_chat(chat_id, f"❌ Failed to upload '{os.path.basename(downloaded_file)}' to Streamtape."))
        else:
            asyncio.run(send_message_to_chat(chat_id, f"❌ Failed to download video from: {youtube_url}"))

        # Clean up old videos occasionally
        cleanup_old_videos()

    is_processing = False
    logger.info("Queue processing finished. No more videos in queue.")


async def send_message_to_chat(chat_id, text):
    """Sends a message to a specific chat ID. Used by the processing thread."""
    # Ensure the Application instance is available.
    # This assumes `application` is a global variable or passed around.
    # For simplicity, we'll try to access the global application object.
    try:
        await application.bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Failed to send message to chat {chat_id}: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a message to the user."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and update.effective_message:
        await update.effective_message.reply_text("An error occurred while processing your request. Please try again later.")


def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    global application # Make application accessible globally for send_message_to_chat
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # On different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start_command))

    # On non command i.e. message - echo the message on Telegram
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_link))

    # Error handler
    application.add_error_handler(error_handler)

    # Run the bot until the user presses Ctrl-C
    logger.info("Bot started polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
