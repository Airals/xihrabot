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

NEW_USER_WATCH_SECONDS = 1_814_400  # 3 weeks
OLD_EDIT_THRESHOLD = 604800  # 7 days

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

                    if isinstance(target_channel, discord.TextChannel) and target_channel.is_news():
                        try:
                            await sent_message.publish()
                        except discord.Forbidden:
                            print("❌ Missing permission to publish announcement.")

                    print("📣 Announcement relayed")

                except discord.HTTPException as e:
                    print(f"❌ Failed to relay announcement: {e}")

    # ---------- IGNORE BOTS ----------
    if message.author.bot:
        return

    # ---------- STAFF BYPASS ----------
    if message.author.guild_permissions.manage_messages:
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

    # ---------- NEW USER WATCH (3 WEEKS) ----------
    if message.author.joined_at:
        joined_recently = (
            discord.utils.utcnow() - message.author.joined_at
        ).total_seconds() < NEW_USER_WATCH_SECONDS

        content_lower = message.content.lower()

        suspicious_keywords = [
            "commission",
            "commissions open",
            "dm for art",
            "art for sale",
            "digital art",
            "illustration services",
            "graphic design services",
            "crypto",
            "bitcoin",
            "ethereum",
            "nft",
            "nfts",
            "blockchain",
            "token sale",
            "invest now",
            "forex",
            "trading signal"
        ]

        suspicious = any(keyword in content_lower for keyword in suspicious_keywords)

        if joined_recently and suspicious:
            log_channel = (
                message.guild.get_channel(LOG_CHANNEL_ID)
                if LOG_CHANNEL_ID
                else discord.utils.get(message.guild.text_channels, name="logs")
            )

            if log_channel:
                await log_channel.send(
                    f"⚠️ **Suspicious promotional message from new user (<3 weeks)** {message.author.mention}\n"
                    f"Channel: {message.channel.mention}\n"
                    f"> {message.content}"
                )

            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass

            return  # stop further processing

    # ---------- SPAM DETECTION ----------
    now = message.created_at.timestamp()
    user_id = message.author.id

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


@bot.event
async def on_message_edit(before, after):
    if before.author.bot:
        return

    if not before.guild:
        return

    if before.content == after.content:
        return

    message_age_seconds = (
        discord.utils.utcnow() - before.created_at
    ).total_seconds()

    if message_age_seconds < OLD_EDIT_THRESHOLD:
        return

    log_channel = (
        before.guild.get_channel(LOG_CHANNEL_ID)
        if LOG_CHANNEL_ID
        else discord.utils.get(before.guild.text_channels, name="logs")
    )

    if log_channel:
        await log_channel.send(
            f"✏️ **Old message edited (>7 days)**\n"
            f"User: {before.author.mention}\n"
            f"Channel: {before.channel.mention}\n\n"
            f"**Before:**\n> {before.content}\n\n"
            f"**After:**\n> {after.content}"
        )


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