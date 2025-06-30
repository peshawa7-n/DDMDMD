import os
import logging
from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeVideo
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.WARNING)

# --- Configuration Variables ---
API_ID = int(os.getenv('APITELEGRAM_ID'))
API_HASH = os.getenv('APITELEGRAM_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
SESSION_NAME = os.getenv('SESSION_NAME', 'my_telegram_session') # Name for your Telethon session file
PRIVATE_CHANNEL_ID = int(os.getenv('CHANNEL_ID')) # Your private channel ID
DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', 'downloads') # Directory to save downloaded videos temporarily

# Create download directory if it doesn't exist
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Initialize the TelegramClient with your session
# We'll use the SESSION_NAME to store the user session
user_client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# Initialize the bot client
bot_client = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

@bot_client.on(events.NewMessage(pattern='/start'))
async def start(event):
    """Handles the /start command."""
    await event.respond('Hello! Send me a Telegram video link, and I will download it and send it to your private channel.')

@bot_client.on(events.NewMessage(pattern='^(https?://)?t.me/c/(\d+)/(\d+)$'))
async def download_and_repost_telegram_video(event):
    """
    Handles incoming Telegram video links, downloads the video, and reposts it
    to the specified private channel.
    """
    if event.is_private: # Only process messages in private chat with the bot
        try:
            message_link = event.pattern_match.group(0)
            chat_id = int(f"-100{event.pattern_match.group(2)}") # Convert to actual channel ID format
            message_id = int(event.pattern_match.group(3))

            await event.respond(f"Received link: `{message_link}`. Attempting to download...", parse_mode='markdown')

            # Use the user_client to get the message and download the media
            # Ensure the user_client is connected
            if not user_client.is_connected():
                await user_client.connect()
                if not await user_client.is_user_authorized():
                    await event.respond("User client not authorized. Please run the script locally once to generate the session file or ensure your API_ID/API_HASH are correct.")
                    return

            # Get the message from the source channel
            source_message = await user_client.get_messages(chat_id, ids=message_id)

            if not source_message or not source_message.media:
                await event.respond("Could not find media in the provided link or the link is invalid.")
                return

            if isinstance(source_message.media, (
                type(None), # No media
                events.ChatAction, # Chat action like user joined
                events.MessageService, # Service message like pin
            )):
                await event.respond("The provided link does not contain a downloadable video.")
                return

            # Check if it's a video
            is_video = False
            file_name = None
            caption = source_message.text if source_message.text else ""

            if source_message.video:
                is_video = True
                file_name = source_message.file.name or f"video_{message_id}.mp4"
            elif source_message.document and any(isinstance(attr, DocumentAttributeVideo) for attr in getattr(source_message.document, 'attributes', [])):
                is_video = True
                file_name = source_message.file.name or f"document_video_{message_id}.mp4"
            else:
                await event.respond("The provided link does not point to a video file.")
                return

            download_path = os.path.join(DOWNLOAD_DIR, file_name)

            await event.respond(f"Downloading video: `{file_name}`...", parse_mode='markdown')

            # Download the video using the user client
            await user_client.download_media(source_message.media, file=download_path, progress_callback=lambda current, total: progress_bar(event, current, total))

            await event.respond("Download complete! Uploading to your private channel...")

            # Upload the video to the private channel using the bot client
            await bot_client.send_file(
                PRIVATE_CHANNEL_ID,
                download_path,
                caption=caption,
                supports_streaming=True, # Recommended for large videos
                progress_callback=lambda current, total: progress_bar(event, current, total)
            )

            await event.respond(f"Video `{file_name}` successfully sent to your private channel! ✅", parse_mode='markdown')

            # --- Explicit Cleanup Step ---
            # Delete the downloaded file to free up space
            if os.path.exists(download_path):
                os.remove(download_path)
                logging.info(f"Cleaned up {download_path}")
            # --- End Cleanup Step ---

        except ValueError as e:
            await event.respond(f"Error processing link: {e}. Please ensure it's a valid Telegram channel link (e.g., `https://t.me/c/12345/678`).")
        except Exception as e:
            logging.error(f"An error occurred: {e}", exc_info=True)
            await event.respond(f"An unexpected error occurred: `{e}`. Please try again or check the logs for more details.", parse_mode='markdown')
    else:
        await event.respond("Please send video links in a private chat with me.")

async def progress_bar(event, current, total):
    """Sends a progress bar update."""
    percentage = (current / total) * 100
    bar_length = 20
    filled_length = int(bar_length * current // total)
    bar = '█' * filled_length + '-' * (bar_length - filled_length)
    status_text = f"`[{bar}] {percentage:.1f}%`"
    
    # Avoid sending too many updates, update only every 5%
    if int(percentage) % 5 == 0 or percentage == 100.0:
        try:
            # Edit the last message if possible to avoid spamming
            if hasattr(event, '_last_progress_message_id'):
                await event.client.edit_message(event.chat_id, event._last_progress_message_id, status_text, parse_mode='markdown')
            else:
                msg = await event.respond(status_text, parse_mode='markdown')
                event._last_progress_message_id = msg.id
        except Exception:
            pass # Ignore errors if message cannot be edited (e.g., too old)

async def main():
    """Main function to run the bot."""
    print("Starting user client...")
    await user_client.start() # Start the user client to ensure session is loaded/created
    if not await user_client.is_user_authorized():
        print("User client not authorized. Please authorize it now.")
        # This will prompt for phone number and code if no session exists or it's invalid
        await user_client.run_until_disconnected()
        print("User client authorized.")
    else:
        print("User client is already authorized.")

    print("Starting bot client...")
    await bot_client.run_until_disconnected()

if __name__ == '__main__':
    try:
        user_client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("Bot stopped by user.")
    finally:
        # Ensure clients are disconnected on exit
        if user_client.is_connected():
            user_client.disconnect()
        if bot_client.is_connected():
            bot_client.disconnect()
