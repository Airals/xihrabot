import discord
from discord.ext import commands
from datetime import timedelta
import os
from dotenv import load_dotenv
import re

# Define intents BEFORE creating the bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # needed to detect joins

# Create the bot
bot = commands.Bot(command_prefix="!", intents=intents)

# Load token from .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# --- CONFIG ---
SPAM_MESSAGE_THRESHOLD = 5  # messages in X seconds
SPAM_TIME_WINDOW = 5        # seconds
MUTE_DURATION = timedelta(hours=24)

# Store recent messages to detect spam
recent_messages = {}


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")


@bot.event
async def on_message(message: discord.Message):
    # Ignore bot messages
    if message.author.bot:
        return

    # --- 1️⃣ Remove embeds if message has 5+ embeds AND 3+ links ---
    if len(message.embeds) >= 5:
        link_count = len(re.findall(r'https?://\S+', message.content))

        if link_count >= 3:
            try:
                await message.edit(suppress=True)
                await message.channel.send(
                    f"{message.author.mention}, messages with 5+ embeds and 3+ links aren't allowed. They’ve been removed.",
                    delete_after=5
                )
            except discord.Forbidden:
                print("Bot lacks permissions to edit/suppress embeds.")
            except discord.HTTPException:
                print("Failed to suppress embeds due to a network or Discord error.")

    # --- 2️⃣ Detect spam from new users ---
    now = message.created_at.timestamp()
    user_id = message.author.id
    recent_messages.setdefault(user_id, []).append(now)

    # Keep only recent messages
    recent_messages[user_id] = [
        t for t in recent_messages[user_id] if now - t <= SPAM_TIME_WINDOW
    ]

    # Check if user is spamming
    if len(recent_messages[user_id]) >= SPAM_MESSAGE_THRESHOLD:
        joined_recently = (discord.utils.utcnow() - message.author.joined_at).total_seconds() < 3600
        if joined_recently:
            await handle_spammer(message.author, message.guild)

    # --- 3️⃣ New User Watch System ---
    joined_recently = (discord.utils.utcnow() - message.author.joined_at).total_seconds() < 600  # 10 minutes
    if joined_recently and ("http" in message.content.lower() or "commission" in message.content.lower()):
        log_channel = discord.utils.get(message.guild.text_channels, name="logs")
        if log_channel:
            await log_channel.send(
                f"⚠️ **Suspicious message from new user {message.author.mention}:**\n> {message.content}"
            )

        # Optionally delete the message
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            pass


async def handle_spammer(member: discord.Member, guild: discord.Guild):
    # Delete recent messages from the spammer
    for channel in guild.text_channels:
        try:
            async for msg in channel.history(limit=200):
                if msg.author == member:
                    await msg.delete()
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            pass

    # Mute the member (requires “Muted” role or Timeout feature)
    try:
        await member.edit(timed_out_until=discord.utils.utcnow() + MUTE_DURATION)
        print(f"Muted {member} for 24 hours due to spam.")
    except discord.Forbidden:
        print("Bot lacks permission to timeout members.")


bot.run(TOKEN)
