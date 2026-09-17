import asyncio
import logging
import os
import sys

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import init_db


# إعداد سجل العمليات المنظم
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("CoreRunner")

TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    logger.critical("الرمز السري DISCORD_TOKEN أو DISCORD_BOT_TOKEN مفقود في Secrets.")
    sys.exit(1)

# تفعيل كافة الصلاحيات والأحداث اللازمة
intents = discord.Intents.all()


class CentralBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
            application_id=None,
        )

    async def setup_hook(self):
        # تهيئة قاعدة البيانات أولاً لضمان جاهزية الجداول
        await init_db()

        # تحميل حزم الـ Cogs المعيارية
        cogs = [
            "cogs.moderation",
            "cogs.engagement",
            "cogs.economy",
            "cogs.utilities",
        ]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"✅ تم تحميل النظام: {cog}")
            except Exception as error:
                logger.error(f"❌ تعذر تحميل {cog}: {error}")

        # بدء دورة تحديث الحالة الحية
        self.update_presence.start()

    async def on_ready(self):
        logger.info("========================================")
        logger.info(
            f" الأنظمة المركزية نشطة: {self.user.name} (ID: {self.user.id})"
        )
        logger.info(f" زمن الاستجابة: {round(self.latency * 1000)}ms")
        logger.info("========================================")
        try:
            synced = await self.tree.sync()
            logger.info(f"🚀 تمت مزامنة {len(synced)} أمر Slash بنجاح.")
        except Exception as error:
            logger.error(f"⚠️ فشلت مزامنة الأوامر: {error}")

    @tasks.loop(minutes=5)
    async def update_presence(self):
        """تحديث نشاط البوت تلقائياً بحسب إحصائيات السيرفرات الحية"""
        if not self.is_ready():
            return
        total_members = sum(
            guild.member_count for guild in self.guilds if guild.member_count
        )
        status_text = f"{total_members} عضو | /dashboard"
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=status_text,
            ),
            status=discord.Status.online,
        )

    @update_presence.before_loop
    async def before_presence(self):
        await self.wait_until_ready()


bot = CentralBot()


# -------------------------------------------------------------
# معالج الأخطاء العام لكافة أوامر Slash
# -------------------------------------------------------------
@bot.tree.error
async def on_app_command_error(
    itx: discord.Interaction,
    error: app_commands.AppCommandError,
):
    if isinstance(error, app_commands.MissingPermissions):
        message = "⛔ لا تملك الصلاحيات الكافية لتنفيذ هذا الأمر."
    elif isinstance(error, app_commands.BotMissingPermissions):
        message = "❌ البوت يفتقر إلى الصلاحيات الإدارية المطلوبة في هذا الروم."
    elif isinstance(error, app_commands.CommandOnCooldown):
        message = (
            f"⏳ يرجى الانتظار `{error.retry_after:.1f}` ثانية قبل إعادة المحاولة."
        )
    else:
        logger.error(
            f"خطأ غير معالج في الأمر "
            f"{itx.command.name if itx.command else 'Unknown'}: {error}"
        )
        message = "⚠️ حدث خطأ تقني غير متوقع أثناء معالجة الطلب."

    if itx.response.is_done():
        await itx.followup.send(message, ephemeral=True)
    else:
        await itx.response.send_message(message, ephemeral=True)


# -------------------------------------------------------------
# دورة التشغيل والإغلاق الآمن (Graceful Execution)
# -------------------------------------------------------------
async def main():
    async with bot:
        try:
            await bot.start(TOKEN)
        except discord.LoginFailure:
            logger.critical("فشل تسجيل الدخول: الـ DISCORD_TOKEN غير صالح.")
        except Exception as error:
            logger.critical(f"انقطاع غير متوقع في المحرك: {error}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("تم إيقاف تشغيل النظام يدوياً.")
