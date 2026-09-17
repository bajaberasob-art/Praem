import asyncio
import datetime
import logging
import re
import time
from collections import defaultdict
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands

from database import (
    SETTINGS_DEFAULTS,
    add_warning,
    delete_warning,
    get_guild_settings,
    get_recent_warnings,
    get_warning,
    get_warnings,
)


logger = logging.getLogger("ModerationCog")

# One compiled detector keeps message handling cheap. The named groups let
# anti_invites and anti_links be toggled independently.
LINK_RE = re.compile(
    r"(?ix)"
    r"(?P<invite>(?:https?://)?(?:www\.)?"
    r"(?:discord\.gg|discord(?:app)?\.com/invite)/[a-z0-9-]+)"
    r"|(?P<suspicious>(?:https?://)?(?:www\.)?"
    r"(?:bit\.ly|tinyurl\.com|t\.co|is\.gd|ow\.ly|rb\.gy|shorturl\.at|"
    r"rebrand\.ly|cutt\.ly|tiny\.cc|buff\.ly|grabify\.link|iplogger\.(?:org|com)|"
    r"2no\.co|yip\.sx|urlz\.fr)/[^\s<>()]+)",
)

SPAM_WINDOW = 3.0
SPAM_LIMIT = 5
SPAM_TIMEOUT_MINUTES = 5
MENTION_LIMIT = 5
INFRACTION_LIMIT = 100


class Moderation(commands.Cog):
    """Dynamic Auto-Mod engine and the bot's manual moderation commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.spam: defaultdict[tuple[int, int], list[float]] = defaultdict(list)
        self._word_patterns: dict[tuple[str, ...], Optional[re.Pattern]] = {}
        self._last_spam_prune = time.monotonic()

    async def moderation_settings(self, guild_id: int) -> dict[str, Any]:
        """Read Auto-Mod values through database.py's in-memory settings cache."""
        try:
            snapshot = await get_guild_settings(int(guild_id))
            values = snapshot["settings"]
            words = values.get("banned_words_list", [])
            return {
                "anti_invites": bool(values.get("anti_invites", True)),
                "anti_links": bool(values.get("anti_links", True)),
                "anti_spam": bool(values.get("anti_spam", True)),
                "anti_mass_mention": bool(values.get("anti_mass_mention", True)),
                "banned_words_list": words if isinstance(words, list) else [],
                "log_channel_id": values.get("log_channel_id"),
            }
        except Exception:
            logger.exception("[AUTOMOD_CONFIG] تعذر قراءة إعدادات السيرفر %s", guild_id)
            return {
                "anti_invites": True,
                "anti_links": True,
                "anti_spam": True,
                "anti_mass_mention": True,
                "banned_words_list": [],
                "log_channel_id": None,
            }

    async def send_log(self, guild: discord.Guild, embed: discord.Embed):
        config = await self.moderation_settings(guild.id)
        channel = (
            guild.get_channel(int(config["log_channel_id"]))
            if config.get("log_channel_id")
            else None
        )
        if channel is None:
            channel = (
                discord.utils.get(guild.text_channels, name="mod-logs")
                or discord.utils.get(guild.text_channels, name="سجل-الإدارة")
            )
        if channel is None or guild.me is None:
            return
        try:
            if channel.permissions_for(guild.me).send_messages:
                await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("[AUTOMOD_LOG] تعذر إرسال سجل في السيرفر %s", guild.id)

    def _banned_word_pattern(self, words: list[str]) -> Optional[re.Pattern]:
        normalized = tuple(
            sorted(
                {
                    word.strip().casefold()
                    for word in words
                    if isinstance(word, str) and word.strip()
                }
            )
        )
        if not normalized:
            return None
        if normalized not in self._word_patterns:
            if len(self._word_patterns) >= 64:
                self._word_patterns.pop(next(iter(self._word_patterns)))
            self._word_patterns[normalized] = re.compile(
                "|".join(re.escape(word) for word in normalized),
                re.IGNORECASE,
            )
        return self._word_patterns[normalized]

    def _spam_triggered(self, guild_id: int, user_id: int) -> bool:
        now = time.monotonic()
        key = (int(guild_id), int(user_id))
        timestamps = [stamp for stamp in self.spam[key] if now - stamp < SPAM_WINDOW]
        timestamps.append(now)
        self.spam[key] = timestamps
        if now - self._last_spam_prune > 30:
            self._last_spam_prune = now
            for stale_key, values in list(self.spam.items()):
                if not values or now - values[-1] >= SPAM_WINDOW:
                    self.spam.pop(stale_key, None)
        if len(timestamps) > SPAM_LIMIT:
            self.spam.pop(key, None)
            return True
        return False

    async def _resolve_member(
        self,
        guild: discord.Guild,
        user_id: int,
    ) -> Optional[discord.Member]:
        member = guild.get_member(int(user_id))
        if member is not None:
            return member
        try:
            return await guild.fetch_member(int(user_id))
        except discord.NotFound:
            return None
        except (discord.Forbidden, discord.HTTPException, asyncio.TimeoutError):
            logger.warning("[AUTOMOD_MEMBER] تعذر جلب العضو %s", user_id)
            return None

    async def _apply_violation(
        self,
        msg: discord.Message,
        reason: str,
        *,
        timeout_minutes: int = 0,
    ) -> None:
        guild, member = msg.guild, msg.author
        try:
            await msg.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.debug("[AUTOMOD] تعذر حذف الرسالة %s", msg.id, exc_info=True)

        moderator_id = getattr(getattr(self.bot, "user", None), "id", 0)
        warning_count = None
        try:
            warning_count = await add_warning(
                member.id,
                guild.id,
                moderator_id,
                reason,
            )
        except Exception:
            logger.exception("[AUTOMOD] فشل تسجيل الإنذار للسيرفر %s", guild.id)

        timed_out = False
        if timeout_minutes:
            try:
                await member.timeout(
                    discord.utils.utcnow()
                    + datetime.timedelta(minutes=timeout_minutes),
                    reason=reason,
                )
                timed_out = True
            except (discord.Forbidden, discord.HTTPException):
                logger.warning(
                    "[AUTOMOD] فشل تطبيق الكتم على %s في %s",
                    member.id,
                    guild.id,
                    exc_info=True,
                )

        # No public @everyone alert: it mentions only the offender and deletes
        # itself, keeping the moderation channel quiet.
        try:
            await msg.channel.send(
                f"⚠️ {member.mention} تم حذف رسالتك لمخالفة قواعد السيرفر.",
                delete_after=6,
                silent=True,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.debug("[AUTOMOD] تعذر إرسال التنبيه الصامت", exc_info=True)

        embed = discord.Embed(
            title="🛡️ Auto-Mod / مخالفة محجوبة",
            description=f"{member.mention} في {msg.channel.mention}",
            color=0xE74C3C if timed_out else 0xF1C40F,
        )
        embed.add_field(name="السبب", value=reason, inline=False)
        embed.add_field(
            name="الإجراء",
            value=(
                f"حذف + كتم {timeout_minutes} دقائق"
                if timed_out
                else "حذف + تسجيل إنذار"
            ),
            inline=True,
        )
        if warning_count is not None:
            embed.add_field(name="إجمالي الإنذارات", value=str(warning_count), inline=True)
        await self.send_log(guild, embed)
        logger.info(
            "[AUTOMOD] guild=%s user=%s reason=%s timeout=%s",
            guild.id,
            member.id,
            reason,
            timed_out,
        )

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if (
            msg.author.bot
            or not msg.guild
            or msg.author.guild_permissions.manage_messages
        ):
            return

        config = await self.moderation_settings(msg.guild.id)
        link_match = LINK_RE.search(msg.content or "")
        if link_match:
            if link_match.group("invite") and config["anti_invites"]:
                await self._apply_violation(msg, "نشر رابط دعوة Discord ممنوع")
                return
            if link_match.group("suspicious") and config["anti_links"]:
                await self._apply_violation(msg, "رابط تصيد أو اختصار مشبوه")
                return

        word_pattern = self._banned_word_pattern(config["banned_words_list"])
        if word_pattern and word_pattern.search(msg.content or ""):
            await self._apply_violation(msg, "استخدام كلمة محظورة")
            return

        if config["anti_mass_mention"] and len(msg.mentions) > MENTION_LIMIT:
            await self._apply_violation(
                msg,
                f"منشن جماعي يتجاوز {MENTION_LIMIT} أعضاء",
                timeout_minutes=SPAM_TIMEOUT_MINUTES,
            )
            return

        if config["anti_spam"] and self._spam_triggered(msg.guild.id, msg.author.id):
            await self._apply_violation(
                msg,
                f"إرسال أكثر من {SPAM_LIMIT} رسائل خلال {int(SPAM_WINDOW)} ثوان",
                timeout_minutes=SPAM_TIMEOUT_MINUTES,
            )

    async def get_recent_infractions(self, guild_id: int) -> list[dict[str, Any]]:
        return await get_recent_warnings(guild_id, INFRACTION_LIMIT)

    async def revoke_warning(self, warning_id: int) -> Optional[dict[str, Any]]:
        warning = await get_warning(warning_id)
        if warning is None:
            return None
        if not await delete_warning(warning_id):
            return None
        return warning

    async def quick_unmute(self, guild_id: int, user_id: int) -> dict[str, Any]:
        guild = self.bot.get_guild(int(guild_id))
        if guild is None:
            return {"ok": False, "error": "guild_not_found"}
        member = await self._resolve_member(guild, user_id)
        if member is None:
            return {"ok": False, "error": "member_not_found"}
        try:
            await member.timeout(None, reason="Dashboard quick unmute")
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "[AUTOMOD_UNMUTE] فشل فك الكتم عن %s في %s",
                user_id,
                guild_id,
                exc_info=True,
            )
            return {"ok": False, "error": "permission_denied"}
        embed = discord.Embed(
            title="🔊 فك كتم سريع",
            description=f"تم فك الكتم عن {member.mention} من لوحة التحكم.",
            color=0x2ECC71,
        )
        await self.send_log(guild, embed)
        return {"ok": True, "guild_id": int(guild_id), "user_id": int(user_id)}

    @app_commands.command(name="timeout", description="كتم عضو بالدقائق")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(
        self,
        itx: discord.Interaction,
        member: discord.Member,
        minutes: int,
        reason: str = "غير محدد",
    ):
        if not 1 <= minutes <= 40320:
            return await itx.response.send_message(
                "❌ مدة الكتم يجب أن تكون بين دقيقة و28 يوماً.",
                ephemeral=True,
            )
        if member.top_role >= itx.user.top_role and itx.user.id != itx.guild.owner_id:
            return await itx.response.send_message(
                "❌ لا تملك صلاحية على هذا العضو.",
                ephemeral=True,
            )
        try:
            await member.timeout(
                discord.utils.utcnow() + datetime.timedelta(minutes=minutes),
                reason=reason,
            )
            emb = discord.Embed(
                title="🔇 كتم عضو",
                description=f"{member.mention} لمدة {minutes}د | السبب: {reason}",
                color=0xE67E22,
            )
            await itx.response.send_message(embed=emb)
            await self.send_log(itx.guild, emb)
        except (discord.Forbidden, discord.HTTPException):
            await itx.response.send_message(
                "❌ فشل الكتم؛ تأكد من صلاحية ورتبة البوت.",
                ephemeral=True,
            )

    @app_commands.command(name="untimeout", description="فك الكتم عن عضو")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def untimeout(self, itx: discord.Interaction, member: discord.Member):
        try:
            await member.timeout(None)
            await itx.response.send_message(f"🔊 تم فك الكتم عن {member.mention}.")
        except (discord.Forbidden, discord.HTTPException):
            await itx.response.send_message(
                "❌ فشل الإجراء؛ تحقق من الصلاحيات.",
                ephemeral=True,
            )

    @app_commands.command(name="warn", description="تحذير عضو")
    @app_commands.checks.has_permissions(kick_members=True)
    async def warn(
        self,
        itx: discord.Interaction,
        member: discord.Member,
        reason: str,
    ):
        if (
            member.top_role >= itx.user.top_role
            and itx.user.id != itx.guild.owner_id
        ) or member.bot:
            return await itx.response.send_message(
                "❌ لا يمكن تحذير هذا الحساب.",
                ephemeral=True,
            )
        cnt = await add_warning(member.id, itx.guild.id, itx.user.id, reason)
        emb = discord.Embed(
            title="⚠️ تحذير",
            description=(
                f"المخالف: {member.mention}\n"
                f"السبب: {reason}\n"
                f"الإجمالي: **{cnt}**"
            ),
            color=0xF1C40F,
        )
        await itx.response.send_message(embed=emb)
        await self.send_log(itx.guild, emb)
        if cnt >= 3:
            try:
                await member.timeout(
                    discord.utils.utcnow() + datetime.timedelta(hours=1),
                    reason="3 تحذيرات",
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("[MODERATION] تعذر تطبيق عقوبة 3 إنذارات")

    @app_commands.command(name="warnings", description="عرض أرشيف تحذيرات عضو")
    @app_commands.checks.has_permissions(kick_members=True)
    async def show_warnings(
        self,
        itx: discord.Interaction,
        member: discord.Member,
    ):
        recs = await get_warnings(member.id, itx.guild.id)
        if not recs:
            return await itx.response.send_message(
                f"✅ سجل {member.mention} نظيف.",
                ephemeral=True,
            )
        emb = discord.Embed(
            title=f"📋 تحذيرات {member.display_name}",
            color=0x992D22,
        )
        for wid, reason, timestamp in recs:
            emb.add_field(
                name=f"#{wid} | {timestamp[:10]}",
                value=reason,
                inline=False,
            )
        await itx.response.send_message(embed=emb, ephemeral=True)

    @app_commands.command(name="clear", description="مسح رسائل بفلترة ذكية")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(
        self,
        itx: discord.Interaction,
        amount: int,
        member: discord.Member = None,
        bots_only: bool = False,
    ):
        if not 1 <= amount <= 100:
            return await itx.response.send_message(
                "❌ العدد بين 1 و 100.",
                ephemeral=True,
            )
        await itx.response.defer(ephemeral=True)
        message_filter = lambda m: (
            (not member or m.author.id == member.id)
            and (not bots_only or m.author.bot)
        )
        try:
            deleted = await itx.channel.purge(limit=amount, check=message_filter)
            await itx.followup.send(
                f"🧹 تم مسح **{len(deleted)}** رسالة.",
                ephemeral=True,
            )
        except (discord.Forbidden, discord.HTTPException):
            await itx.followup.send(
                "❌ تعذر الحذف، تحقق من الصلاحيات.",
                ephemeral=True,
            )

    @app_commands.command(name="lockdown", description="قفل أو فتح الشات")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lockdown(self, itx: discord.Interaction, lock: bool):
        overwrite = itx.channel.overwrites_for(itx.guild.default_role)
        overwrite.send_messages = False if lock else None
        overwrite.send_messages_in_threads = False if lock else None
        await itx.channel.set_permissions(itx.guild.default_role, overwrite=overwrite)
        await itx.response.send_message(
            embed=discord.Embed(
                title="🔒 أُغلق الروم" if lock else "🔓 فُتح الروم",
                color=0xE74C3C if lock else 0x2ECC71,
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))