import datetime
import re
import time

import discord
from discord import app_commands
from discord.ext import commands

from database import add_warning, get_warnings


INVITE_RE = re.compile(
    r"(https?://)?(www\.)?(discord\.(gg|io|me|li)|discord(app)?\.com/invite)/[a-zA-Z0-9]+",
    re.I,
)


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot, self.spam, self.dups = bot, {}, {}

    async def send_log(self, guild: discord.Guild, embed: discord.Embed):
        if ch := (
            discord.utils.get(guild.text_channels, name="mod-logs")
            or discord.utils.get(guild.text_channels, name="سجل-الإدارة")
        ):
            if ch.permissions_for(guild.me).send_messages:
                await ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if (
            msg.author.bot
            or not msg.guild
            or msg.author.guild_permissions.manage_messages
        ):
            return

        now, uid, mem = time.time(), msg.author.id, msg.author

        # منع الإعلانات
        if INVITE_RE.search(msg.content):
            try:
                await msg.delete()
                await msg.channel.send(
                    f"⚠️ {mem.mention} ممنوع نشر الدعوات!",
                    delete_after=5,
                )
                emb = discord.Embed(
                    title="🚨 رصد إعلان",
                    description=f"{mem.mention} في {msg.channel.mention}",
                    color=0xE74C3C,
                )
                return await self.send_log(msg.guild, emb)
            except Exception:
                pass

        # تمنشن جماعي
        if len(msg.mentions) >= 4:
            try:
                await msg.delete()
                await mem.timeout(
                    discord.utils.utcnow() + datetime.timedelta(minutes=10),
                    reason="Mass Mentions",
                )
                return await msg.channel.send(
                    f"🔇 كُتم {mem.mention} 10 دقائق (إشارات متكررة).",
                    delete_after=5,
                )
            except Exception:
                pass

        # مانع التكرار والسبام الزمني
        d = self.dups.get(uid, {"c": "", "n": 0, "t": 0})
        d = {
            "c": msg.content,
            "n": d["n"] + 1
            if d["c"] == msg.content and now - d["t"] < 5
            else 1,
            "t": now,
        }
        self.dups[uid] = d
        t_list = [
            t for t in self.spam.setdefault(uid, []) if now - t < 3
        ] + [now]
        self.spam[uid] = t_list

        if len(t_list) >= 5 or d["n"] >= 4:
            self.spam[uid], self.dups[uid] = [], {"c": "", "n": 0, "t": 0}
            try:
                await msg.channel.purge(
                    limit=5,
                    check=lambda m: m.author.id == uid,
                )
                await mem.timeout(
                    discord.utils.utcnow() + datetime.timedelta(minutes=5),
                    reason="Anti-Spam",
                )
                await msg.channel.send(
                    f"🔇 كُتم {mem.mention} مؤقتاً بسبب السبام.",
                    delete_after=5,
                )
            except Exception:
                pass

    @app_commands.command(name="timeout", description="كتم عضو بالدقائق")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(
        self,
        itx: discord.Interaction,
        member: discord.Member,
        minutes: int,
        reason: str = "غير محدد",
    ):
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
        except Exception:
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
        except Exception:
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
            except Exception:
                pass

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
            deleted = await itx.channel.purge(
                limit=amount,
                check=message_filter,
            )
            await itx.followup.send(
                f"🧹 تم مسح **{len(deleted)}** رسالة.",
                ephemeral=True,
            )
        except Exception:
            await itx.followup.send(
                "❌ تعذر الحذف، تحقق من الصلاحيات.",
                ephemeral=True,
            )

    @app_commands.command(name="lockdown", description="قفل أو فتح الشات")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lockdown(self, itx: discord.Interaction, lock: bool):
        overwrite = itx.channel.overwrites_for(itx.guild.default_role)
        overwrite.send_messages = False if lock else None
        await itx.channel.set_permissions(
            itx.guild.default_role,
            overwrite=overwrite,
        )
        await itx.response.send_message(
            embed=discord.Embed(
                title="🔒 أُغلق الروم" if lock else "🔓 فُتح الروم",
                color=0xE74C3C if lock else 0x2ECC71,
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
