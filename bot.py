import discord
from discord.ext import commands
from datetime import timedelta
import os
from dotenv import load_dotenv
import re
import asyncio

# ---------- INTENTS ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- ENV ----------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", 0))
SOURCE_ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("SOURCE_ANNOUNCEMENT_CHANNEL_ID", 0))
TARGET_ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("TARGET_ANNOUNCEMENT_CHANNEL_ID", 0))

RAW_BLACKLIST = os.getenv("ANNOUNCEMENT_BLACKLIST", "")
ANNOUNCEMENT_BLACKLIST = {
    word.strip().lower()
    for word in RAW_BLACKLIST.split(",")
    if word.strip()
}

def contains_blacklisted_keyword(content: str) -> bool:
    content = content.lower()
    for word in ANNOUNCEMENT_BLACKLIST:
        if re.search(rf"\b{re.escape(word)}\b", content):
            return True
    return False


# ---------- CONFIG ----------
SPAM_MESSAGE_THRESHOLD = 5
SPAM_TIME_WINDOW = 5
MUTE_DURATION = timedelta(hours=24)

# ---------- STATE ----------
recent_messages: dict[int, list[float]] = {}
handled_spammers: set[int] = set()
relayed_messages: set[int] = set()  # prevents duplicates


# ---------- ANNOUNCEMENT RELAY ----------
async def relay_announcement(message: discord.Message):
    if not message.guild:
        return

    if message.id in relayed_messages:
        return

    if not (
        SOURCE_ANNOUNCEMENT_CHANNEL_ID
        and TARGET_ANNOUNCEMENT_CHANNEL_ID
        and message.channel.id == SOURCE_ANNOUNCEMENT_CHANNEL_ID
    ):
        return

    content = message.content or ""
    if not content:
        return

    if ANNOUNCEMENT_BLACKLIST and contains_blacklisted_keyword(content):
        print("⛔ Announcement blocked due to blacklist keyword.")
        return

    target_channel = message.guild.get_channel(TARGET_ANNOUNCEMENT_CHANNEL_ID)
    if not target_channel:
        return

    try:
        sent_message = await target_channel.send(
            content=content,
            allowed_mentions=discord.AllowedMentions.none()
        )

        if isinstance(target_channel, discord.TextChannel) and target_channel.is_news():
            await sent_message.publish()

        relayed_messages.add(message.id)

    except discord.HTTPException as e:
        print(f"❌ Failed to relay announcement: {e}")


# ---------- EVENTS ----------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")


# Normal messages (humans + some bots)
@bot.event
async def on_message(message: discord.Message):
    await relay_announcement(message)

    if not message.guild or message.author.bot:
        return

    # Staff bypass
    if message.author.guild_permissions.manage_messages:
        await bot.process_commands(message)
        return

    # ---------- EMBED + LINK CONTROL ----------
    if len(message.embeds) >= 2:
        link_count = len(re.findall(r"https?://\S+", message.content))
        if link_count >= 2:
            try:
                await message.edit(suppress=True)
                await message.channel.send(
                    f"{message.author.mention}, messages with **2+ embeds** aren’t allowed.\n"
                    "Please wrap links in `< >` to prevent embeds.",
                    delete_after=5
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

    if not message.author.joined_at:
        await bot.process_commands(message)
        return

    now = message.created_at.timestamp()
    user_id = message.author.id

    # ---------- SPAM DETECTION ----------
    recent_messages.setdefault(user_id, []).append(now)
    recent_messages[user_id] = [
        t for t in recent_messages[user_id]
        if now - t <= SPAM_TIME_WINDOW
    ]

    joined_recently_1h = (
        discord.utils.utcnow() - message.author.joined_at
    ).total_seconds() < 3600

    if (
        joined_recently_1h
        and len(recent_messages[user_id]) >= SPAM_MESSAGE_THRESHOLD
        and user_id not in handled_spammers
    ):
        handled_spammers.add(user_id)
        await handle_spammer(message)
        recent_messages.pop(user_id, None)

    # ---------- NEW USER WATCH ----------
    joined_recently_10m = (
        discord.utils.utcnow() - message.author.joined_at
    ).total_seconds() < 600

    if joined_recently_10m and any(w in message.content.lower() for w in ("http", "commission")):
        log_channel = message.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(
                f"⚠️ **Suspicious message from new user** {message.author.mention}\n"
                f"Channel: {message.channel.mention}\n"
                f"> {message.content}"
            )

        try:
            await message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

    await bot.process_commands(message)


# 🔥 RAW EVENT — catches scheduled app messages
@bot.event
async def on_raw_message_create(payload: discord.RawMessageCreateEvent):
    if payload.channel_id != SOURCE_ANNOUNCEMENT_CHANNEL_ID:
        return

    channel = bot.get_channel(payload.channel_id)
    if not channel:
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return

    await relay_announcement(message)


# ---------- SPAM HANDLER ----------
async def handle_spammer(message: discord.Message):
    member = message.author

    try:
        async for msg in message.channel.history(limit=20):
            if msg.author == member:
                await msg.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass

    try:
        await member.edit(
            timed_out_until=discord.utils.utcnow() + MUTE_DURATION,
            reason="Automated spam detection"
        )
        print(f"🔇 Muted {member} for 24 hours.")
    except discord.Forbidden:
        print("❌ Missing permission to timeout members.")


# ---------- RUN ----------
bot.run(TOKEN)
