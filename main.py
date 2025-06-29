import os
import requests
from telethon import TelegramClient, events
from urllib.parse import urlencode

# --- Configuration (replace with your actual values) ---
API_ID = os.getenv('APITELEGRAM_ID')
API_HASH = os.getenv('APITELEGRAM_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN') # If you want to use a bot to interact
PHONE_NUMBER = os.getenv('PHONE_NUMBER') # For Telethon user client (recommended for private channels)

STREAMTAPE_API_USERNAME = os.getenv('STREAMTAPE_API_USERNAME')
STREAMTAPE_API_PASSWORD = os.getenv('STREAMTAPE_API_USERNAME')

# --- Initialize Telegram Client ---
# For a user client (recommended for private channels)
client = TelegramClient('telegram_session', API_ID, API_HASH)

# For a bot client (more limited for private channels)
# bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# --- Function to Download Video from Telegram ---
async def download_telegram_video(event):
    # This function needs to be triggered by a Telegram event,
    # e.g., when a message containing a video is received.

    # Check if the message contains media (a video in this case)
    if event.media and hasattr(event.media, 'document') and event.media.document.mime_type.startswith('video/'):
        print("Video detected. Downloading...")
        file_name = event.media.document.attributes[0].file_name if event.media.document.attributes else f"telegram_video_{event.id}.mp4"
        download_path = await event.download_media(file=file_name)
        print(f"Video downloaded to: {download_path}")
        return download_path
    else:
        print("No video found in the message.")
        return None

# --- Function to Upload Video to Streamtape ---
def upload_to_streamtape(file_path):
    print(f"Uploading {file_path} to Streamtape...")
    upload_url = f"https://api.streamtape.com/file/ul?login={STREAMTAPE_API_USERNAME}&key={STREAMTAPE_API_PASSWORD}"

    try:
        with open(file_path, 'rb') as f:
            files = {'file1': f}
            response = requests.post(upload_url, files=files)
            response.raise_for_status() # Raise an exception for HTTP errors
            result = response.json()

            if result['status'] == 200:
                streamtape_file_code = result['result']['url'].split('/')[-1] # Extract file code from URL
                print(f"Upload successful! Streamtape file code: {streamtape_file_code}")
                return result['result']['url'] # Return the direct Streamtape URL
            else:
                print(f"Streamtape upload failed: {result.get('msg', 'Unknown error')}")
                return None
    except requests.exceptions.RequestException as e:
        print(f"Error uploading to Streamtape: {e}")
        return None
    except FileNotFoundError:
        print(f"Error: File not found at {file_path}")
        return None

# --- Main Logic for Telegram Handler ---
@client.on(events.NewMessage(incoming=True, chats=YOUR_PRIVATE_CHANNEL_ID_OR_USERNAME)) # Replace with your channel ID/username
async def handle_new_message(event):
    print(f"Received message in private channel: {event.id}")
    video_path = await download_telegram_video(event)

    if video_path:
        streamtape_url = upload_to_streamtape(video_path)
        if streamtape_url:
            await event.reply(f"Video downloaded and uploaded to Streamtape! Link: {streamtape_url}")
        else:
            await event.reply("Failed to upload video to Streamtape.")

        # Clean up the downloaded file
        try:
            os.remove(video_path)
            print(f"Cleaned up local file: {video_path}")
        except OSError as e:
            print(f"Error deleting file {video_path}: {e}")

# --- Run the Telegram Client ---
async def main():
    await client.start(phone=PHONE_NUMBER) # For user client, this will prompt for phone/code
    # await bot.start() # For bot client
    print("Telegram client started. Listening for messages...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    # You might need to run this in an async context
    import asyncio
    asyncio.run(main())
