import asyncio
import logging
import os
import sys
import time
from collections import deque

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import init_db
from cogs.utilities import dynamic_prefix
from interaction_runtime import (
    install_ui_guards,
    send_interaction_message,
    wrap_application_command,
)
from web_server import start_web_server


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("CoreRunner")

TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    logger.critical(
        "⚠️ مفتاح DISCORD_TOKEN أو DISCORD_BOT_TOKEN مفقود "
        "تماماً داخل Replit Secrets!"
    )
    sys.exit(1)

intents = discord.Intents.all()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.emojis_and_stickers = True


def configured_sync_guild() -> discord.Object | None:
    """Return the optional guild used for fast slash-command synchronization."""
    guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
    if not guild_id:
        return None

    try:
        return discord.Object(id=int(guild_id))
    except ValueError:
        logger.warning(
            "DISCORD_GUILD_ID is not numeric; falling back to global command sync."
        )
        return None


class EnterpriseBot(commands.Bot):
    def __init__(self):
        install_ui_guards()
        super().__init__(
            command_prefix=dynamic_prefix,
            intents=intents,
            help_command=None,
            max_messages=1000,
            chunk_guilds_at_startup=True,
        )
        self.session: aiohttp.ClientSession | None = None
        self.dashboard_runner = None
        self.presence_step = 0
        self.sync_guild = configured_sync_guild()
        self.metrics: deque[dict[str, int | float | str | None]] = deque(maxlen=600)

    async def add_cog(self, cog, /, *, override=False, guild=None, guilds=None):
        options = {"override": override}
        if guild is not None:
            options["guild"] = guild
        if guilds is not None:
            options["guilds"] = guilds
        result = await super().add_cog(cog, **options)
        self.install_interaction_guards()
        return result

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        """Keep listener exceptions from disappearing inside discord.py."""
        logger.error(
            "[EVENT] listener failed: %s args=%s",
            event_method,
            len(args),
            exc_info=True,
        )

    def install_interaction_guards(self) -> int:
        wrapped = 0
        for command in self.tree.walk_commands():
            if isinstance(command, app_commands.Command):
                wrapped += int(wrap_application_command(command))
        if wrapped:
            logger.info("🛡️ تم تأمين %d أمر Slash بطبقة ACK والأخطاء الموحدة.", wrapped)
        return wrapped

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()

        try:
            await init_db()
            logger.info("📦 تم التحقق من سلامة قاعدة البيانات بنجاح.")
        except Exception as error:
            await self.session.close()
            self.session = None
            raise RuntimeError("قاعدة البيانات غير جاهزة؛ أوقف الإقلاع لحماية البيانات.") from error

        try:
            self.dashboard_runner = await start_web_server(self)
            logger.info(
                "🌐 لوحة التحكم (Web Dashboard) نشطة على المنفذ %s.",
                os.getenv("DASHBOARD_PORT", "8080"),
            )
        except Exception as error:
            await self.session.close()
            self.session = None
            raise RuntimeError("تعذر تشغيل لوحة التحكم؛ أوقف الإقلاع بدلاً من تشغيل نسخة ناقصة.") from error

        modules = [
            # Load protection before the remaining feature cogs so the security
            # listeners are registered as soon as the bot connects.
            "cogs.security",
            "cogs.moderation",
            "cogs.engagement",
            "cogs.economy",
            "cogs.utilities",
            "cogs.tournaments",
            "cogs.community",
            "cogs.ai_tools",
        ]

        for module in modules:
            try:
                await self.load_extension(module)
                logger.info(f"✅ تم تحميل الوحدة بنجاح: {module}")
            except commands.ExtensionAlreadyLoaded:
                logger.debug("الوحدة محملة مسبقاً: %s", module)
            except Exception as error:
                raise RuntimeError(f"فشل تحميل الوحدة {module}; أوقف الإقلاع.") from error

        self.install_interaction_guards()
        try:
            if self.sync_guild is not None:
                self.tree.copy_global_to(guild=self.sync_guild)
                synced = await self.tree.sync(guild=self.sync_guild)
                logger.info(
                    "✨ تمت مزامنة %d أمر Slash مع سيرفر التطوير %s.",
                    len(synced),
                    self.sync_guild.id,
                )
            else:
                synced = await self.tree.sync()
                logger.info("✨ تمت مزامنة %d أمر Slash عالمياً بنجاح.", len(synced))
        except discord.HTTPException as error:
            logger.error("⚠️ فشل مزامنة أوامر Slash: %s", error)

        self.rotate_status.start()

    async def close(self):
        logger.info("🛑 جاري إنهاء الجلسات وإيقاف البوت بأمان...")
        self.rotate_status.cancel()
        if self.dashboard_runner:
            await self.dashboard_runner.cleanup()
            self.dashboard_runner = None
        if self.session and not self.session.closed:
            await self.session.close()
        await super().close()

    async def on_ready(self):
        self.record_metrics()
        logger.info("=" * 45)
        logger.info(
            f"🚀 المحرك المركزي جاهز للخدمة: "
            f"{self.user.name} (ID: {self.user.id})"
        )
        logger.info(
            f"📡 السيرفرات النشطة: {len(self.guilds)} | الأعضاء: "
            f"{sum(guild.member_count for guild in self.guilds if guild.member_count)}"
        )
        logger.info(
            f"⚡ زمن الاستجابة الشبكي (Ping): "
            f"{round(self.latency * 1000)}ms"
        )
        logger.info("[GATEWAY] Bot Tag: %s | Latency: %sms", self.user, round(self.latency * 1000))
        logger.info("[GATEWAY] Connected Guilds: %d", len(self.guilds))
        logger.info("[GATEWAY] Cached members by guild:")
        for guild in self.guilds:
            logger.info(
                "  - %s (%s): %d cached members | chunked=%s | emojis=%d | roles=%d",
                guild.name,
                guild.id,
                len(guild.members),
                bool(getattr(guild, "chunked", False)),
                len(guild.emojis),
                len(guild.roles),
            )
        logger.info("=" * 45)

    async def on_message(self, message: discord.Message):
        """Keep prefix-command dispatch active alongside cog listeners."""
        await self.process_commands(message)

    def record_metrics(self) -> None:
        """Capture live gateway and guild values for the dashboard charts."""
        latency = self.latency
        latency_ms = (
            round(latency * 1000)
            if latency == latency and latency != float("inf")
            else None
        )
        timestamp = time.time()
        for guild in self.guilds:
            self.metrics.append(
                {
                    "guild_id": str(guild.id),
                    "ts": timestamp,
                    "latency_ms": latency_ms,
                    "members": guild.member_count,
                }
            )

    def metrics_for_guild(self, guild_id: int) -> list[dict]:
        """Return a bounded, JSON-ready metric history for one guild."""
        self.record_metrics()
        return [
            dict(item)
            for item in self.metrics
            if str(item.get("guild_id")) == str(guild_id)
        ][-120:]

    @tasks.loop(seconds=30)
    async def rotate_status(self):
        if not self.is_ready():
            return

        total_members = sum(
            guild.member_count
            for guild in self.guilds
            if guild.member_count
        )
        statuses = [
            (
                discord.ActivityType.watching,
                f"{total_members:,} عضو | /help",
            ),
            (
                discord.ActivityType.competing,
                f"{len(self.guilds)} سيرفر | Shield Active 🛡️",
            ),
            (
                discord.ActivityType.listening,
                f"لوحة التحكم | Port {os.getenv('DASHBOARD_PORT', '8080')} ⚡",
            ),
        ]

        activity_type, activity_name = statuses[
            self.presence_step % len(statuses)
        ]
        await self.change_presence(
            activity=discord.Activity(
                type=activity_type,
                name=activity_name,
            ),
            status=discord.Status.online,
        )
        self.presence_step += 1

    @rotate_status.before_loop
    async def before_rotate(self):
        await self.wait_until_ready()


bot = EnterpriseBot()


@bot.tree.error
async def on_app_command_error(
    itx: discord.Interaction,
    error: app_commands.AppCommandError,
):
    if isinstance(error, app_commands.CommandOnCooldown):
        message = (
            f"⏳ يرجى الانتظار `{error.retry_after:.1f}` ثانية "
            "قبل إعادة استخدام هذا الأمر."
        )
    elif isinstance(error, app_commands.MissingPermissions):
        missing = ", ".join(
            f"`{permission}`"
            for permission in error.missing_permissions
        )
        message = (
            "⛔ لا تمتلك الصلاحيات الكافية لتنفيذ هذا الإجراء: "
            f"{missing}"
        )
    elif isinstance(error, app_commands.BotMissingPermissions):
        missing = ", ".join(
            f"`{permission}`"
            for permission in error.missing_permissions
        )
        message = (
            "❌ يفتقر البوت إلى الصلاحيات المطلوبة في هذه القناة: "
            f"{missing}"
        )
    elif isinstance(error, app_commands.NoPrivateMessage):
        message = (
            "🔒 هذا الأمر متاح للاستخدام داخل السيرفرات فقط "
            "وليس في الرسائل الخاصة."
        )
    else:
        command_name = itx.command.name if itx.command else "مجهول"
        logger.error(
            f"خطأ غير معالج في الأمر [{command_name}]: {error}"
        )
        message = (
            "⚠️ حدث خطأ تقني غير متوقع أثناء معالجة الطلب، "
            "تم تدوين الخطأ لمراجعته."
        )

    await send_interaction_message(itx, message, ephemeral=True)


async def main():
    async with bot:
        retry_delay = 5
        while not bot.is_closed():
            try:
                await bot.start(TOKEN)
            except discord.LoginFailure:
                logger.critical(
                    "🚨 رمز DISCORD_TOKEN غير صالح أو تم تغييره، "
                    "تم إيقاف المحرك فوراً."
                )
                break
            except discord.PrivilegedIntentsRequired:
                logger.critical(
                    "يلزم تفعيل Server Members Intent وMessage Content Intent "
                    "في Discord Developer Portal "
                    "→ Bot → Privileged Gateway Intents. تم إيقاف المحرك."
                )
                break
            except (
                discord.ConnectionClosed,
                aiohttp.ClientConnectorError,
            ) as error:
                logger.warning(
                    "⚠️ فقدان مؤقت للاتصال بخوادم ديسكورد "
                    f"({error}). إعادة المحاولة خلال "
                    f"{retry_delay} ثوانٍ..."
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)
            except Exception as error:
                logger.critical(
                    f"❌ انقطاع غير معالج في الحلقة التشغيلية: {error}"
                )
                await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🚪 تم إيقاف تشغيل الخادم يدوياً بواسطة المطور.")