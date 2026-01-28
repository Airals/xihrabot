import discord
from discord.ext import commands
import os

TOKEN = os.getenv("DISCORD_TOKEN")

SOURCE_CHANNEL_ID = 123456789012345678  # channel the scheduler posts in
TARGET_CHANNEL_ID = 987654321098765432  # channel to relay to

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


async def relay_message(message: discord.Message):
    # Ignore bots except the scheduler
    if message.channel.id != SOURCE_CHANNEL_ID:
        return

    if not message.content:
        return

    target_channel = bot.get_channel(TARGET_CHANNEL_ID)
    if not target_channel:
        return

    await target_channel.send(message.content)


@bot.event
async def on_message(message: discord.Message):
    # Normal messages (humans, normal bots)
    await relay_message(message)

    await bot.process_commands(message)


@bot.event
async def on_raw_message_create(payload):
    # Catches scheduler / app / system messages
    if payload.channel_id != SOURCE_CHANNEL_ID:
        return

    channel = bot.get_channel(payload.channel_id)
    if not channel:
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return

    await relay_message(message)


bot.run(TOKEN)
