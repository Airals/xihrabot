import discord
from discord.ext import commands, tasks
import os

TOKEN = os.getenv("DISCORD_TOKEN")

SOURCE_CHANNEL_ID = 123456789012345678
TARGET_CHANNEL_ID = 987654321098765432

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

last_seen_message_id = None


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    poll_source_channel.start()


@tasks.loop(seconds=30)
async def poll_source_channel():
    global last_seen_message_id

    source = bot.get_channel(SOURCE_CHANNEL_ID)
    target = bot.get_channel(TARGET_CHANNEL_ID)

    if not source or not target:
        return

    async for message in source.history(limit=10, oldest_first=True):
        if last_seen_message_id and message.id <= last_seen_message_id:
            continue

        # Plain text only
        if not message.content:
            continue

        await target.send(message.content)
        last_seen_message_id = message.id


bot.run(TOKEN)
