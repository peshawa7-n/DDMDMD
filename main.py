import os
from telethon.sync import TelegramClient
from telethon.tl.types import InputMessagesFilterVideo
import asyncio

# 🔐 ENV variables
API_ID = int(os.getenv("APITELEGRAM_ID"))
API_HASH = os.getenv("APITELEGRAM_HASH")
SOURCE_CHAT = os.getenv("@RENGTVKURD")  # channel or group username or ID
TARGET_CHAT = os.getenv("CHANNEL_ID")  # your private channel ID
SESSION_NAME = "anon"  # Session file name, will be stored

client = TelegramClient(session.session, API_ID, API_HASH)

async def download_and_forward_videos():
    await client.start()
    print("✅ Client logged in.")

    # 📥 Download videos
    async for msg in client.iter_messages(SOURCE_CHAT, filter=InputMessagesFilterVideo):
        if msg.video:
            filename = f"downloads/{msg.video.file_name or msg.id}.mp4"
            print("⏬ Downloading:", filename)
            await msg.download_media(file=filename)

            # 📤 Upload to another channel
            print("🚀 Sending to target channel...")
            await client.send_file(TARGET_CHAT, filename, caption="Auto uploaded")
            os.remove(filename)

    print("🎉 All videos done.")

if __name__ == "__main__":
    asyncio.run(download_and_forward_videos())
