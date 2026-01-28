import discord
from discord.ext import commands, tasks
import os
import json
from dotenv import load_dotenv

# ---------- ENV ----------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

SOURCE_CHANNEL_ID = int(os.getenv("SOURCE_ANNOUNCEMENT_CHANNEL_ID", 0))
TARGET_CHANNEL_ID = int(os.getenv("TARGET_ANNOUNCEMENT_CHANNEL_ID", 0))

STATE_FILE = "last_message.json"

# ---------- INTENTS ----------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- STATE ----------
last_message_id = None


def load_state():
    global last_message_id
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            last_message_id = data.get("last_message_id")


def save_state(message_id: int):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_message_id": message_id}, f)


# ---------- EVENTS ----------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    load_state()
    poll_announcements.start()


# ---------- POLLER ----------
@tasks.loop(seconds=20)
async def poll_announcements():
    global last_message_id

    source = bot.get_channel(SOURCE_CHANNEL_ID)
    target = bot.get_channel(TARGET_CHANNEL_ID)

    if not source or not target:
        return

    messages = []

    async for msg in source.history(limit=25, oldest_first=True):
        if last_message_id and msg.id <= last_message_id:
            continue
        messages.append(msg)

    for msg in messages:
        files = [await a.to_file() for a in msg.attachments]

        await target.send(
            content=msg.content or None,
            files=files,
            allowed_mentions=discord.AllowedMentions.none()
        )

        last_message_id = msg.id
        save_state(msg.id)

        print(f"📣 Relayed message {msg.id}")


# ---------- MODERATION (unchanged) ----------
@bot.event
async def on_message(message: discord.Message):
    if not message.guild:
        return

    # moderation logic lives here ONLY
    await bot.process_commands(message)


# ---------- RUN ----------
bot.run(TOKEN)
