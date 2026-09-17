import datetime
import logging
import random
import re
import time

import discord
from discord import app_commands
from discord.ext import commands


logger = logging.getLogger("SecurityCog")


# فحص روابط التصيد وسرقة الحسابات
SCAM_REGEX = re.compile(
    r"(https?://)?(www\.)?(discord\.(gg|io|me|li)|discordapp\.com/invite|"
    r"discord\.gift|nitro-gift|steamcommunity-link)[^\s]+",
    re.I,
)


class MathCaptchaModal(discord.ui.Modal, title="بوابة التحقق البشري الذكية"):
    def __init__(self, a: int, b: int, role_id: int):
        super().__init__()
        self.answer = str(a + b)
        self.role_id = role_id
        self.input = discord.ui.TextInput(
            label=f"حل المسألة التالية: {a} + {b} = ؟",
            placeholder="اكتب الناتج فقط هنا...",
            min_length=1,
            max_length=4,
        )
        self.add_item(self.input)

    async def on_submit(self, itx: discord.Interaction):
        if self.input.value.strip() == self.answer:
            role = itx.guild.get_role(self.role_id)
            if role and role < itx.guild.me.top_role:
                await itx.user.add_roles(role)
                return await itx.response.send_message(
                    "✅ تم التحقق البشري بنجاح ومُنحت رتبة الدخول!",
                    ephemeral=True,
                )
            return await itx.response.send_message(
                "⚠️ خطأ: رتبة التفعيل أعلى من صلاحيات البوت.",
                ephemeral=True,
            )
        await itx.response.send_message(
            "❌ إجابة خاطئة! أعد المحاولة مرة أخرى.",
            ephemeral=True,
        )


class CaptchaView(discord.ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id
        # A role-specific ID prevents one server's CAPTCHA view from routing
        # interactions to another server's verified role.
        button = next(
            item
            for item in self.children
            if isinstance(item, discord.ui.Button)
        )
        button.custom_id = f"btn_sec_cap:{role_id}"

    @discord.ui.button(
        label="بدء التحقق 🛡️",
        style=discord.ButtonStyle.success,
        custom_id="btn_sec_cap",
    )
    async def verify(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        a, b = random.randint(1, 20), random.randint(1, 20)
        await itx.response.send_modal(MathCaptchaModal(a, b, self.role_id))


class Security(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rate_limits: dict[str, list[float]] = {}

    def check_abuse(
        self,
        uid: int,
        action: str,
        limit: int = 3,
        window: int = 60,
    ) -> bool:
        """فحص تكرار العمليات الإدارية الحساسة خلال نافذة زمنية محددة"""
        key = f"{uid}_{action}"
        now = time.time()
        timestamps = [
            timestamp
            for timestamp in self.rate_limits.setdefault(key, [])
            if now - timestamp < window
        ] + [now]
        self.rate_limits[key] = timestamps
        return len(timestamps) >= limit

    async def quarantine_admin(
        self,
        guild: discord.Guild,
        member: discord.Member,
        reason: str,
    ):
        """تجريد المشرف فوراً من كافة صلاحياته لمنع استمرار الهجوم"""
        try:
            await member.edit(
                roles=[],
                reason=f"Anti-Nuke Triggered: {reason}",
            )
            channel = guild.system_channel
            if channel:
                embed = discord.Embed(
                    title="🚨 تدخل أمني طارئ (Anti-Nuke)",
                    color=0x992D22,
                )
                embed.add_field(
                    name="المخرب",
                    value=f"{member.mention} ({member.id})",
                    inline=True,
                )
                embed.add_field(
                    name="السبب",
                    value=reason,
                    inline=False,
                )
                await channel.send(
                    "@everyone ⚠️ تم عزل المشرف وإلغاء صلاحياته فوراً "
                    "لحماية السيرفر!",
                    embed=embed,
                )
        except Exception as error:
            logger.exception("[SECURITY_CRITICAL] فشل عزل المشرف: %s", error)

    @commands.Cog.listener()
    async def on_member_join(self, mem: discord.Member):
        # 1. فحص عمر الحساب (Account Age Gate < 3 أيام)
        if (discord.utils.utcnow() - mem.created_at).days < 3:
            try:
                await mem.kick(reason="حساب جديد مشبوه (عمره أقل من 3 أيام)")
                channel = mem.guild.system_channel
                if channel:
                    await channel.send(
                        f"🛡️ تم طرد الحساب المشبوه {mem.mention} تلقائياً "
                        "(تاريخ الإنشاء حديث)."
                    )
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if (
            msg.author.bot
            or not msg.guild
            or msg.author.guild_permissions.manage_guild
        ):
            return
        # 2. فحص روابط التصيد والاحتيال والنيترو الوهمي
        if SCAM_REGEX.search(msg.content):
            try:
                await msg.delete()
                timeout_time = discord.utils.utcnow() + datetime.timedelta(hours=2)
                await msg.author.timeout(
                    timeout_time,
                    reason="إرسال روابط تصيد مشبوهة",
                )
                await msg.channel.send(
                    f"🚨 {msg.author.mention} تم حجب الرابط وكتمك لمدة ساعتين "
                    "لحماية الأعضاء!",
                    delete_after=6,
                )
            except Exception:
                pass

    # -------------------------------------------------------------
    # رصد هجمات التخريب السريع (Audit Logs Monitors)
    # -------------------------------------------------------------
    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self,
        channel: discord.abc.GuildChannel,
    ):
        guild = channel.guild
        async for entry in guild.audit_logs(
            limit=1,
            action=discord.AuditLogAction.channel_delete,
        ):
            user = entry.user
            if (
                not user
                or user.id == guild.owner_id
                or user.id == self.bot.user.id
            ):
                return
            if self.check_abuse(user.id, "ch_del", limit=3, window=60):
                member = guild.get_member(user.id)
                if member:
                    await self.quarantine_admin(
                        guild,
                        member,
                        "حذف أكثر من قناتين خلال دقيقة واحدة",
                    )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        guild = role.guild
        async for entry in guild.audit_logs(
            limit=1,
            action=discord.AuditLogAction.role_delete,
        ):
            user = entry.user
            if (
                not user
                or user.id == guild.owner_id
                or user.id == self.bot.user.id
            ):
                return
            if self.check_abuse(user.id, "rl_del", limit=3, window=60):
                member = guild.get_member(user.id)
                if member:
                    await self.quarantine_admin(
                        guild,
                        member,
                        "حذف رتب متعددة بسرعة فائقة",
                    )

    @commands.Cog.listener()
    async def on_member_ban(
        self,
        guild: discord.Guild,
        member: discord.User,
    ):
        async for entry in guild.audit_logs(
            limit=1,
            action=discord.AuditLogAction.ban,
        ):
            user = entry.user
            if (
                not user
                or user.id == guild.owner_id
                or user.id == self.bot.user.id
            ):
                return
            if self.check_abuse(user.id, "mass_ban", limit=3, window=60):
                moderator = guild.get_member(user.id)
                if moderator:
                    await self.quarantine_admin(
                        guild,
                        moderator,
                        "محاولة حظر جماعي للأعضاء (Mass Ban)",
                    )

    @app_commands.command(
        name="setup_captcha",
        description="تثبيت بوابة التحقق البشري الذكية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(
        manage_roles=True,
        send_messages=True,
        embed_links=True,
    )
    async def setup_captcha(
        self,
        itx: discord.Interaction,
        verified_role: discord.Role,
    ):
        guild = itx.guild
        bot_member = guild.me
        if bot_member is None or verified_role >= bot_member.top_role:
            await itx.response.send_message(
                "⚠️ رتبة التفعيل يجب أن تكون أسفل أعلى رتبة للبوت.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🛡️ بوابة التحقق البشري والأمان الفائق",
            description=(
                "لحماية السيرفر من حسابات السبام وغارات البوتات المخربة:\n"
                "اضغط على الزر أدناه وقم بحل المسألة الرياضية البسيطة "
                "لتفعيل حسابك."
            ),
            color=0x2ECC71,
        )
        embed.set_footer(text="نظام الحماية المركزي النشط")
        view = CaptchaView(verified_role.id)
        self.bot.add_view(view)
        await itx.channel.send(
            embed=embed,
            view=view,
        )
        await itx.response.send_message(
            "✅ تم نشر بوابة الكابتشا بنجاح.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Security(bot))
