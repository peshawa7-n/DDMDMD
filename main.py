from pyrogram import Client, filters
from pytube import YouTube
import os
from dotenv import load_dotenv

# Load secrets from .env file
load_dotenv()
API_ID = int(os.getenv("APITELEGRAM_ID"))
API_HASH = os.getenv("APITELEGRAM_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PRIVATE_CHANNEL = os.getenv("CHANNEL_ID")

app = Client("video_forwarder_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.video | filters.document)
async def handle_video(client, message):
    print("Received a video... downloading...")

    # Download the video file
    file_path = await message.download()
    print(f"Downloaded to {file_path}")

    # Send to your private channel
    await app.send_video(chat_id=PRIVATE_CHANNEL, video=file_path, caption="Forwarded by bot")
    print("Sent to private channel")

    # Clean up
    os.remove(file_path)

@app.on_message(filters.text & filters.private)
async def handle_youtube_link(client, message):
    url = message.text.strip()
    if "youtube.com" in url or "youtu.be" in url:
        try:
            yt = YouTube(url)
            video = yt.streams.get_highest_resolution()
            file_path = video.download()
            print(f"Downloaded from YouTube: {file_path}")

            await app.send_video(chat_id=PRIVATE_CHANNEL, video=file_path, caption=f"{yt.title}")
            os.remove(file_path)
        except Exception as e:
            await message.reply(f"Error: {e}")

app.run()
