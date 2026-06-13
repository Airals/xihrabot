import discord
from discord.ext import commands
from datetime import timedelta
import datetime
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
APRIL_FOOLS_CHANNEL_ID = int(os.getenv("APRIL_FOOLS_CHANNEL_ID", 0))

RAW_BLACKLIST = os.getenv("ANNOUNCEMENT_BLACKLIST", "")
ANNOUNCEMENT_BLACKLIST = {
    word.strip().lower()
    for word in RAW_BLACKLIST.split(",")
    if word.strip()
}

RAW_HONEYPOT_CHANNEL_IDS = os.getenv("HONEYPOT_CHANNEL_IDS", "")
HONEYPOT_CHANNEL_IDS = {
    int(channel_id.strip())
    for channel_id in RAW_HONEYPOT_CHANNEL_IDS.split(",")
    if channel_id.strip().isdigit()
}

ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))

# ---------- CONFIG ----------
SPAM_MESSAGE_THRESHOLD = 5
SPAM_TIME_WINDOW = 5
MUTE_DURATION = timedelta(hours=24)

NEW_USER_WATCH_SECONDS = 1_814_400  # 3 weeks
OLD_EDIT_THRESHOLD = 604800  # 7 days
ENABLE_OLD_EDIT_DETECTION = False


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

def clean_announcement_content(content: str) -> str:
    # Remove role mentions (<@&123>)
    content = re.sub(r"<@&\d+>", "@role", content)
    # Remove user mentions (<@123> / <@!123>)
    content = re.sub(r"<@!?\d+>", "@user", content)
    # Prevent everyone/here
    content = content.replace("@everyone", "@everyone (removed)")
    content = content.replace("@here", "@here (removed)")
    return content


# ---------- EVENTS ----------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    print(f"📣 Relaying from {SOURCE_ANNOUNCEMENT_CHANNEL_ID} → {TARGET_ANNOUNCEMENT_CHANNEL_ID}")
    print(f"🍯 Honeypot channels: {HONEYPOT_CHANNEL_IDS}")
    print(f"🛡️ Admin role: {ADMIN_ROLE_ID}")


@bot.event
async def on_message(message: discord.Message):
    if not message.guild:
        return
    
    if message.channel.id in HONEYPOT_CHANNEL_IDS:
    print(
        f"🍯 Honeypot hit by {message.author} "
        f"in {message.channel.name} ({message.channel.id})"
    )
    
    if message.author.bot:
        return

    # --- 🐸 April Fools auto-react (07:00–12:00 UTC, April 1st only) ---
    now = datetime.datetime.utcnow()

    if (
        now.month == 4
        and now.day == 1
        and 7 <= now.hour < 12
        and message.channel.id == APRIL_FOOLS_CHANNEL_ID
    ):
        emoji = discord.utils.get(message.guild.emojis, name="YoshiWhat")

        try:
            if emoji:
                await message.add_reaction(emoji)
            else:
                await message.add_reaction("🍆")
        except (discord.Forbidden, discord.HTTPException):
            pass

    # ---------- ANNOUNCEMENT RELAY ----------
    if (
        SOURCE_ANNOUNCEMENT_CHANNEL_ID
        and TARGET_ANNOUNCEMENT_CHANNEL_ID
        and message.channel.id == SOURCE_ANNOUNCEMENT_CHANNEL_ID
    ):
        content = clean_announcement_content(message.content or "")

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
    
        # ---------- HONEYPOT CHANNELS ----------
    if message.channel.id in HONEYPOT_CHANNEL_IDS:
        member = message.author

        joined_recently = True

        if member.joined_at:
            joined_recently = (
                discord.utils.utcnow() - member.joined_at
            ).total_seconds() < HONEYPOT_GRACE_SECONDS

        log_channel = (
            message.guild.get_channel(LOG_CHANNEL_ID)
            if LOG_CHANNEL_ID
            else discord.utils.get(message.guild.text_channels, name="logs")
        )

        if joined_recently:
            try:
                await member.ban(
                    reason=f"Honeypot channel triggered: #{message.channel.name}",
                    delete_message_days=1
                )

                if log_channel:
                    await log_channel.send(
                        f"🚨 **User banned for triggering honeypot**\n"
                        f"User: {member} / {member.mention}\n"
                        f"Channel: {message.channel.mention}\n"
                        f"Joined: {member.joined_at}\n\n"
                        f"**Message:**\n> {message.content or '*No content*'}",
                        allowed_mentions=discord.AllowedMentions.none()
                    )

            except discord.Forbidden:
                if log_channel:
                    await log_channel.send(
                        f"❌ Tried to ban {member.mention} for honeypot trigger, but I lack permission.",
                        allowed_mentions=discord.AllowedMentions.none()
                    )
            except discord.HTTPException as e:
                print(f"❌ Failed to ban honeypot user: {e}")

            return

        # Older account / long-time server member: warn admins instead
        if log_channel:
            admin_ping = f"<@&{ADMIN_ROLE_ID}> " if ADMIN_ROLE_ID else ""

            try:
                await log_channel.send(
                    f"{admin_ping}⚠️ **Long-term member posted in honeypot channel**\n"
                    f"User: {member.mention} / {member}\n"
                    f"Channel: {message.channel.mention}\n"
                    f"Joined: {member.joined_at}\n\n"
                    f"**Message:**\n> {message.content or '*No content*'}",
                    allowed_mentions=discord.AllowedMentions(roles=True)
                )
            except discord.Forbidden:
                print("❌ Missing permission to send honeypot warning.")

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

    # ---------- NEW USER WATCH ----------
    if message.author.joined_at:
        joined_recently = (
            discord.utils.utcnow() - message.author.joined_at
        ).total_seconds() < NEW_USER_WATCH_SECONDS

        content_lower = message.content.lower()

        suspicious_keywords = [
            "commission", "commissions open", "dm for art", "art for sale",
            "digital art", "illustration services", "graphic design services",
            "crypto", "bitcoin", "ethereum", "nft", "nfts", "blockchain",
            "token sale", "invest now", "forex", "trading signal"
        ]

        suspicious = any(keyword in content_lower for keyword in suspicious_keywords)

        if joined_recently and suspicious:
            log_channel = (
                message.guild.get_channel(LOG_CHANNEL_ID)
                if LOG_CHANNEL_ID
                else discord.utils.get(message.guild.text_channels, name="logs")
            )

            if log_channel:
                try:
                    await log_channel.send(
                        f"⚠️ **Suspicious promotional message from new user (<3 weeks)** {message.author.mention}\n"
                        f"Channel: {message.channel.mention}\n"
                        f"> {message.content}",
                        allowed_mentions=discord.AllowedMentions.none()
                    )
                except discord.Forbidden:
                    print("❌ Missing permission to send messages in log channel.")

            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass

            return

    # ---------- SPAM DETECTION ----------
    now_ts = message.created_at.timestamp()
    user_id = message.author.id

    recent_messages.setdefault(user_id, []).append(now_ts)
    recent_messages[user_id] = [
        t for t in recent_messages[user_id]
        if now_ts - t <= SPAM_TIME_WINDOW
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


# ---------- OLD EDIT DETECTION ----------
@bot.event
async def on_raw_message_edit(payload: discord.RawMessageUpdateEvent):
    if not ENABLE_OLD_EDIT_DETECTION:
        return

    if not payload.guild_id:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return

    channel = guild.get_channel(payload.channel_id)
    if not channel:
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return

    if message.author.bot:
        return

    if not message.edited_at:
        return

    message_age_seconds = (
        discord.utils.utcnow() - message.created_at
    ).total_seconds()

    if message_age_seconds < OLD_EDIT_THRESHOLD:
        return

    log_channel = (
        guild.get_channel(LOG_CHANNEL_ID)
        if LOG_CHANNEL_ID
        else discord.utils.get(guild.text_channels, name="logs")
    )

    if log_channel:
        await log_channel.send(
            f"✏️ **Old message edited (>7 days)**\n"
            f"User: {message.author.mention}\n"
            f"Channel: {channel.mention}\n\n"
            f"**Current Content:**\n> {message.content or '*No content*'}",
            allowed_mentions=discord.AllowedMentions.none()
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