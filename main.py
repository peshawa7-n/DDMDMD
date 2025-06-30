import os
import asyncio
from telethon.sync import TelegramClient
from telethon.tl.types import InputMessagesFilterVideo

# Use your own Telegram API credentials
API_ID = int(os.getenv("APITELEGRAM_ID"))
API_HASH = os.getenv("APITELEGRAM_HASH")
SESSION_NAME = "session"  # Uses session.session file

# Channel to download videos from
SOURCE_CHAT = os.getenv("CHANNEL_ID")  # Example: -1001234567890 or @channelname

# Create download folder
os.makedirs("downloads", exist_ok=True)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

async def download_videos():
    await client.start()
    print("✅ Logged in to Telegram")

    # Download all videos from the source channel
    async for message in client.iter_messages(SOURCE_CHAT, filter=InputMessagesFilterVideo):
        if message.video:
            file_name = f"downloads/video_{message.id}.mp4"
            print(f"⏬ Downloading: {file_name}")
            await message.download_media(file=file_name)
            print(f"✅ Saved: {file_name}")

    print("📁 All videos downloaded!")

if __name__ == "__main__":
    asyncio.run(download_videos())
