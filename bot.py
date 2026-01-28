import discord
from discord.ext import commands
from datetime import timedelta
import os
from dotenv import load_dotenv
import re

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

# ---------- CONFIG ----------
SPAM_MESSAGE_THRESHOLD = 5
SPAM_TIME_WINDOW = 5
MUTE_DURATION = timedelta(hours=24)

# ---------- STATE ----------
recent_messages: dict[int, list[float]] = {}
handled_spammers: set[int] = set()


# ---------- HELPERS ----------
def contains_blacklisted_keyword(content: str) -> bool:
    content = content.lower()
    for word in ANNOUNCEMENT_BLACKLIST:
        if re.search(rf"\b{re.escape(word)}\b", content):
            return True
    return False


# ---------- EVENTS ----------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    print(f"📣 Relaying from {SOURCE_ANNOUNCEMENT_CHANNEL_ID} → {TARGET_ANNOUNCEMENT_CHANNEL_ID}")


@bot.event
async def on_message(message: discord.Message):
    # Ignore DMs
    if not message.guild:
        return

    # ---------- ANNOUNCEMENT RELAY ----------
    if (
        SOURCE_ANNOUNCEMENT_CHANNEL_ID
        and TARGET_ANNOUNCEMENT_CHANNEL_ID
        and message.channel.id == SOURCE_ANNOUNCEMENT_CHANNEL_ID
    ):
        content = message.content or ""

        if ANNOUNCEMENT_BLACKLIST and contains_blacklisted_keyword(content):
            print("⛔ Announcement blocked due to blacklist keyword.")
        else:
            target_channel = bot.get_channel(TARGET_ANNOUNCEMENT_CHANNEL_ID)

            if target_channel:
                try:
                    files = [await a.to_file() for a in message.attachments]

                    sent_message = await target_channel.send(
                        content=content if content else None,
                        files=files,
                        allowed_mentions=discord.AllowedMentions.none()
                    )

                    # Auto-publish if announcement channel
                    if isinstance(target_channel, discord.TextChannel) and target_channel.is_news():
                        try:
                            await sent_message.publish()
                        except discord.Forbidden:
                            print("❌ Missing permission to publish announcement.")

                    print("📣 Announcement relayed")

                except discord.HTTPException as e:
                    print(f"❌ Failed to relay announcement: {e}")

    # ---------- IGNORE BOTS FOR MODERATION ----------
    if message.author.bot:
        await bot.process_commands(message)
        return

    # ---------- STAFF BYPASS ----------
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

    # ---------- SAFETY ----------
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

    suspicious = any(
        word in message.content.lower()
        for word in ("http", "commission")
    )

    if joined_recently_10m and suspicious:
        log_channel = (
            message.guild.get_channel(LOG_CHANNEL_ID)
            if LOG_CHANNEL_ID
            else discord.utils.get(message.guild.text_channels, name="logs")
        )

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
