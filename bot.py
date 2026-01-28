import discord
from discord.ext import commands, tasks
import os
import json

TOKEN = os.getenv("DISCORD_TOKEN")

SOURCE_CHANNEL_ID = 123456789012345678
TARGET_CHANNEL_ID = 987654321098765432

STATE_FILE = "last_message.json"

intents = discord.Intents.default()
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


def load_last_message_id():
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE, "r") as f:
        return json.load(f).get("last_id")


def save_last_message_id(message_id: int):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_id": message_id}, f)


last_seen_message_id = None


@bot.event
async def on_ready():
    global last_seen_message_id
    last_seen_message_id = load_last_message_id()
    print(f"Logged in as {bot.user}")
    poll_source_channel.start()


@tasks.loop(seconds=20)
async def poll_source_channel():
    global last_seen_message_id

    source = bot.get_channel(SOURCE_CHANNEL_ID)
    target = bot.get_channel(TARGET_CHANNEL_ID)

    if not source or not target:
        return

    async for message in source.history(limit=15, oldest_first=True):
        if last_seen_message_id and message.id <= last_seen_message_id:
            continue

        # Only forward plain text messages
        if not message.content:
            continue

        await target.send(message.content)
        last_seen_message_id = message.id
        save_last_message_id(message.id)


bot.run(TOKEN)
