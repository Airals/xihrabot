import discord
from discord.ext import commands
from datetime import timedelta
import os
from dotenv import load_dotenv

# Define intents BEFORE creating the bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # needed to detect joins

# Now create the bot
bot = commands.Bot(command_prefix="!", intents=intents)

# Load token from .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
bot = commands.Bot(command_prefix="!", intents=intents)

# --- CONFIG ---
SPAM_MESSAGE_THRESHOLD = 5  # messages in X seconds
SPAM_TIME_WINDOW = 5  # seconds
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

    # --- 1️⃣ Remove embeds if message has more than one ---
    if len(message.embeds) > 1:
        try:
            await message.edit(suppress=True)
            await message.channel.send(
                f"{message.author.mention}, multiple embeds aren't allowed. They’ve been removed.",
                delete_after=5
            )
        except discord.Forbidden:
            print("Bot lacks permissions to edit/suppress embeds.")

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
        # Optionally check if user joined recently
        joined_recently = (discord.utils.utcnow() - message.author.joined_at).total_seconds() < 3600
        if joined_recently:
            await handle_spammer(message.author, message.guild)

    import datetime

    # Replace this with the ID of the channel you want it active in
    APRIL_FOOLS_CHANNEL_ID = 123456789012345678  # ← put your channel ID here

    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            return

        # --- 🐸 April Fools auto-react ---
        today = datetime.datetime.utcnow().date()
        if today.month == 4 and today.day == 1 and message.channel.id == APRIL_FOOLS_CHANNEL_ID:
            # Get the custom emoji
            emoji = discord.utils.get(message.guild.emojis, name="YoshiWhat")
            if emoji:
                await message.add_reaction(emoji)
            else:
                # If emoji not found, fallback to a default emoji
                await message.add_reaction("😂")

        # --- your other anti-spam / embed logic here ---
        await bot.process_commands(message)  # keep command handling working


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