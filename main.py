import logging
import os
import asyncio
import subprocess
from dotenv import load_dotenv # For loading environment variables locally
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import re
import time

# --- 0. Configuration and Setup ---

# Load environment variables from .env file for local development
load_dotenv()

# Get your bot token and target channel ID from environment variables
# Set these in your Railway/production environment, or in a .env file locally
BOT_TOKEN = os.getenv("BOT_TOKEN")
TARGET_CHANNEL_ID = os.getenv("CHANNEL_ID") # e.g., -1001234567890 (must be a supergroup/channel ID)
LOCAL_BOT_API_URL = os.getenv("LOCAL_BOT_API_URL", f"http://127.0.0.1:8081/bot{BOT_TOKEN}/") # Default for local server
# If you are NOT using a local Bot API server, set this to "https://api.telegram.org/bot{token}/"
# But remember, default Telegram Bot API has a 50MB upload limit!

DOWNLOAD_DIR = "downloads"
# Ensure the download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# List to store video links temporarily
video_links_queue = []
processing_in_progress = False

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 1. Helper Functions ---

async def download_video(url: str, output_path: str) -> bool:
    """Downloads a video using yt-dlp."""
    try:
        # Use --output and --merge-output-format for consistent filenames and formats
        # -f bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best (prioritize mp4, then best)
        # --recode-video mp4 (ensure final output is mp4)
        # --fragment-retries 10 (robustness for fragmented downloads)
        # --retries 5 (general retries for network issues)
        # --no-warnings (cleaner output)
        # --restrict-filenames (safer filenames)
        # --progress --no-progress-hooks --newline (for better progress output, though not directly used here)

        # For full quality, ensure you select 'best' format
        # yt-dlp will often try to download best video and audio separately and then merge them.
        command = [
            "yt-dlp",
            "-f", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "--output", f"{output_path}.%(ext)s", # yt-dlp adds extension, so we use .%(ext)s
            "--restrict-filenames",
            "--no-warnings",
            url
        ]
        logger.info(f"Attempting to download video from {url} with command: {' '.join(command)}")

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"yt-dlp download failed for {url}: {stderr.decode()}")
            return False

        # Find the actual downloaded file name (yt-dlp adds extension)
        # We need to parse stdout to find the actual filename.
        # This is a bit fragile and might need adjustment if yt-dlp output changes.
        # A more robust way might be to parse yt-dlp's --print filename option.
        output_lines = stdout.decode().splitlines()
        downloaded_file = None
        for line in reversed(output_lines): # Search from end for the "Destination" line
            if "Destination:" in line:
                downloaded_file = line.split("Destination:")[1].strip()
                break
            elif "Merging formats into" in line: # For merged files
                downloaded_file = line.split("Merging formats into")[1].strip().strip('"')
                break

        if downloaded_file and os.path.exists(downloaded_file):
            logger.info(f"Successfully downloaded {url} to {downloaded_file}")
            # Rename to our desired output_path without extension, so it's consistent
            final_path = f"{output_path}.mp4" # Assume mp4 after merge
            os.rename(downloaded_file, final_path)
            return final_path
        else:
            logger.error(f"Could not find downloaded file for {url} after yt-dlp ran.")
            return False

    except FileNotFoundError:
        logger.error("yt-dlp command not found. Please ensure yt-dlp is installed and in your PATH.")
        return False
    except Exception as e:
        logger.error(f"Error during video download for {url}: {e}")
        return False

# --- 2. Telegram Bot Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message when the command /start is issued."""
    await update.message.reply_text(
        "Hello! I can download videos from links and send them to your private channel.\n\n"
        "To get started:\n"
        "1. Send me `/set_channel <YOUR_CHANNEL_ID>` to configure the target channel.\n"
        "2. Send me a list of video links, one per line.\n"
        "3. Use `/process_links` to start downloading and sending the videos."
    )

async def set_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sets the target channel ID."""
    global TARGET_CHANNEL_ID
    if not context.args:
        await update.message.reply_text("Please provide the channel ID. Usage: `/set_channel <CHANNEL_ID>`")
        return

    try:
        new_channel_id = int(context.args[0])
        TARGET_CHANNEL_ID = str(new_channel_id) # Store as string for consistency with env vars
        await update.message.reply_text(f"Target channel ID set to: `{TARGET_CHANNEL_ID}`\n"
                                        "Make sure I am an admin in that channel with 'Post Messages' permission.")
        logger.info(f"Target channel ID updated to: {TARGET_CHANNEL_ID}")
    except ValueError:
        await update.message.reply_text("Invalid channel ID. Please provide a numeric ID (e.g., `-1001234567890`).")
    except Exception as e:
        logger.error(f"Error setting channel ID: {e}")
        await update.message.reply_text("An error occurred while setting the channel ID.")

async def receive_links(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Receives a list of links and adds them to the queue."""
    if not update.message.text:
        return

    links = update.message.text.splitlines()
    valid_links = [link.strip() for link in links if link.strip().startswith(("http://", "https://"))]

    if not valid_links:
        await update.message.reply_text("No valid links found. Please send one link per line, starting with http(s)://")
        return

    global video_links_queue
    video_links_queue.extend(valid_links)
    await update.message.reply_text(
        f"Added {len(valid_links)} links to the queue. Total links in queue: {len(video_links_queue)}.\n"
        "Use `/process_links` to start processing the queue."
    )
    logger.info(f"Added {len(valid_links)} links. Queue size: {len(video_links_queue)}")

async def process_links(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Starts processing the video links queue."""
    global processing_in_progress, video_links_queue

    if processing_in_progress:
        await update.message.reply_text("Video processing is already in progress. Please wait for it to finish.")
        return

    if not TARGET_CHANNEL_ID:
        await update.message.reply_text("Please set the target channel ID first using `/set_channel <CHANNEL_ID>`.")
        return

    if not video_links_queue:
        await update.message.reply_text("The video link queue is empty. Send me some links first!")
        return

    processing_in_progress = True
    await update.message.reply_text(f"Starting to process {len(video_links_queue)} videos. This may take a while...")
    logger.info(f"Starting to process {len(video_links_queue)} videos.")

    processed_count = 0
    failed_links = []
    original_queue_size = len(video_links_queue)

    while video_links_queue and processing_in_progress:
        link = video_links_queue.pop(0) # Get the next link from the front of the queue
        await update.message.reply_text(f"Processing link {processed_count + 1}/{original_queue_size}: {link}")
        logger.info(f"Processing link: {link}")

        file_name = os.path.join(DOWNLOAD_DIR, f"video_{int(time.time())}_{processed_count}")
        downloaded_file_path = await download_video(link, file_name)

        if downloaded_file_path:
            try:
                # Get video info for caption (optional)
                # You might use yt-dlp's --print-json to get more metadata
                caption = f"Downloaded from: {link}"
                if os.path.getsize(downloaded_file_path) > 50 * 1024 * 1024:
                     caption += "\n(Note: This video is large, assuming local Bot API server is used)"

                with open(downloaded_file_path, 'rb') as video_file:
                    await context.bot.send_video(
                        chat_id=TARGET_CHANNEL_ID,
                        video=video_file,
                        caption=caption,
                        supports_streaming=True, # Recommended for videos
                        read_timeout=300, # Extend timeout for large files
                        write_timeout=300, # Extend timeout for large files
                        connect_timeout=60, # Extend timeout for large files
                    )
                await update.message.reply_text(f"Successfully sent video {processed_count + 1} to your channel.")
                logger.info(f"Successfully sent video from {link} to channel {TARGET_CHANNEL_ID}")
                processed_count += 1

            except Exception as e:
                logger.error(f"Failed to send video from {link} to channel: {e}")
                await update.message.reply_text(f"Failed to send video {processed_count + 1} from {link} to channel. Error: {e}")
                failed_links.append(link)
            finally:
                # Clean up the downloaded file
                if os.path.exists(downloaded_file_path):
                    os.remove(downloaded_file_path)
                    logger.info(f"Deleted local file: {downloaded_file_path}")
        else:
            await update.message.reply_text(f"Failed to download video {processed_count + 1} from {link}.")
            failed_links.append(link)

        # Introduce a delay to respect Telegram's rate limits
        await asyncio.sleep(5) # Adjust as needed (e.g., 2-5 seconds per video)

    processing_in_progress = False
    final_message = f"Finished processing videos.\nProcessed: {processed_count} / {original_queue_size}"
    if failed_links:
        final_message += f"\nFailed to process {len(failed_links)} videos. Failed links:\n" + "\n".join(failed_links)
        video_links_queue.extend(failed_links) # Add failed links back to the queue
    else:
        final_message += "\nAll videos processed successfully!"

    await update.message.reply_text(final_message)
    logger.info("Video processing finished.")

async def stop_processing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stops the ongoing video processing."""
    global processing_in_progress
    if processing_in_progress:
        processing_in_progress = False
        await update.message.reply_text("Stopping video processing. Remaining links will stay in the queue.")
        logger.info("Processing stopped by user.")
    else:
        await update.message.reply_text("No video processing is currently in progress.")

async def show_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows current links in the queue."""
    if video_links_queue:
        queue_str = "\n".join(f"{i+1}. {link}" for i, link in enumerate(video_links_queue[:10])) # Show first 10
        if len(video_links_queue) > 10:
            queue_str += f"\n...and {len(video_links_queue) - 10} more."
        await update.message.reply_text(f"Current queue ({len(video_links_queue)} links):\n{queue_str}")
    else:
        await update.message.reply_text("The video link queue is empty.")

async def clear_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clears all links from the queue."""
    global video_links_queue
    video_links_queue = []
    await update.message.reply_text("Video link queue cleared.")
    logger.info("Video link queue cleared by user.")

# --- 3. Main Bot Application Setup ---

def main() -> None:
    """Start the bot."""
    # Build the Application.
    # IMPORTANT: Use base_url if you are running a local Bot API server.
    # Otherwise, remove base_url to use Telegram's default API.
    application = Application.builder().token(BOT_TOKEN).base_url(LOCAL_BOT_API_URL).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("set_channel", set_channel))
    application.add_handler(CommandHandler("process_links", process_links))
    application.add_handler(CommandHandler("stop_processing", stop_processing))
    application.add_handler(CommandHandler("show_queue", show_queue))
    application.add_handler(CommandHandler("clear_queue", clear_queue))

    # Handles any text message that looks like a URL (for adding to queue)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"https?://\S+"), receive_links))

    logger.info("Bot is polling...")
    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
