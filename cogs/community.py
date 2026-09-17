import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks


logger = logging.getLogger(__name__)


# --- نظام أزرار الاقتراحات المتقدم ---
class SuggestionActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def check_admin(self, itx: discord.Interaction) -> bool:
        if not itx.user.guild_permissions.manage_guild:
            await itx.response.send_message(
                "❌ هذا الإجراء متاح لإدارة السيرفر فقط!",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="قبول",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="sug_accept",
    )
    async def accept(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        if not await self.check_admin(itx):
            return
        embed = itx.message.embeds[0].copy()
        embed.color = 0x2ECC71
        embed.add_field(
            name="📌 القرار الإداري",
            value=f"🟢 **تم القبول** بواسطة {itx.user.mention}",
            inline=False,
        )
        await itx.message.edit(embed=embed, view=None)
        await itx.response.send_message(
            "✅ تم قبول الاقتراح واعتماده.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="قيد الدراسة",
        style=discord.ButtonStyle.primary,
        emoji="⏳",
        custom_id="sug_progress",
    )
    async def progress(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        if not await self.check_admin(itx):
            return
        embed = itx.message.embeds[0].copy()
        embed.color = 0xF39C12
        embed.add_field(
            name="📌 الحالة",
            value=(
                f"🟡 **قيد التنفيذ والدراسة** بواسطة "
                f"{itx.user.mention}"
            ),
            inline=False,
        )
        await itx.message.edit(embed=embed, view=None)
        await itx.response.send_message(
            "⏳ تم تحويل الاقتراح إلى قيد التنفيذ.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="رفض",
        style=discord.ButtonStyle.danger,
        emoji="❌",
        custom_id="sug_reject",
    )
    async def reject(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        if not await self.check_admin(itx):
            return
        embed = itx.message.embeds[0].copy()
        embed.color = 0xE74C3C
        embed.add_field(
            name="📌 القرار الإداري",
            value=f"🔴 **تم الرفض** بواسطة {itx.user.mention}",
            inline=False,
        )
        await itx.message.edit(embed=embed, view=None)
        await itx.response.send_message(
            "❌ تم رفض الاقتراح.",
            ephemeral=True,
        )


# --- نظام التصويت الحي بالأزرار والنسب المئوية ---
class LivePollView(discord.ui.View):
    def __init__(self, question: str, opt_a: str, opt_b: str):
        super().__init__(timeout=None)
        self.question, self.opt_a, self.opt_b = question, opt_a, opt_b
        self.votes_a, self.votes_b = set(), set()

    def make_embed(self) -> discord.Embed:
        total = len(self.votes_a) + len(self.votes_b)
        percent_a = (
            round((len(self.votes_a) / total) * 100)
            if total > 0
            else 0
        )
        percent_b = (
            round((len(self.votes_b) / total) * 100)
            if total > 0
            else 0
        )
        embed = discord.Embed(
            title="📊 تصويت تفاعلي حي",
            description=f"### {self.question}",
            color=0x3498DB,
        )
        embed.add_field(
            name=f"1️⃣ {self.opt_a}",
            value=f"**{len(self.votes_a)}** صوت ({percent_a}%)",
            inline=True,
        )
        embed.add_field(
            name=f"2️⃣ {self.opt_b}",
            value=f"**{len(self.votes_b)}** صوت ({percent_b}%)",
            inline=True,
        )
        embed.set_footer(text=f"إجمالي الأصوات: {total}")
        return embed

    @discord.ui.button(
        label="الخيار الأول",
        style=discord.ButtonStyle.secondary,
        emoji="1️⃣",
        custom_id="btn_poll_a",
    )
    async def vote_a(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        self.votes_b.discard(itx.user.id)
        self.votes_a.add(itx.user.id)
        await itx.response.edit_message(
            embed=self.make_embed(),
            view=self,
        )

    @discord.ui.button(
        label="الخيار الثاني",
        style=discord.ButtonStyle.secondary,
        emoji="2️⃣",
        custom_id="btn_poll_b",
    )
    async def vote_b(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        self.votes_a.discard(itx.user.id)
        self.votes_b.add(itx.user.id)
        await itx.response.edit_message(
            embed=self.make_embed(),
            view=self,
        )


class Community(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.counters: dict[int, dict[str, int]] = {}
        self.update_counters_task.start()
        logger.info("Community counter updater initialized.")

    def cog_unload(self):
        self.update_counters_task.cancel()

    @tasks.loop(minutes=10)
    async def update_counters_task(self):
        for guild_id, channels in list(self.counters.items()):
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            if channel_id := channels.get("members"):
                if channel := guild.get_channel(channel_id):
                    try:
                        await channel.edit(
                            name=f"👥 الأعضاء: {guild.member_count}",
                        )
                    except discord.HTTPException:
                        pass
            if channel_id := channels.get("boosts"):
                if channel := guild.get_channel(channel_id):
                    try:
                        await channel.edit(
                            name=(
                                "🚀 البوست: "
                                f"{guild.premium_subscription_count}"
                            ),
                        )
                    except discord.HTTPException:
                        pass

    @update_counters_task.before_loop
    async def before_counter(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="suggest",
        description="إرسال اقتراح وطرحه للتصويت والإدارة",
    )
    @app_commands.checks.bot_has_permissions(
        view_channel=True,
        send_messages=True,
        embed_links=True,
        add_reactions=True,
        read_message_history=True,
    )
    @app_commands.describe(idea="تفاصيل فكرة الاقتراح")
    async def suggest(
        self,
        itx: discord.Interaction,
        idea: str,
    ):
        embed = discord.Embed(
            title=f"💡 اقتراح جديد من: {itx.user.display_name}",
            description=idea,
            color=0x3498DB,
        )
        embed.set_thumbnail(url=itx.user.display_avatar.url)
        embed.set_footer(
            text="صوّت عبر الرياكشن | القرار الإداري متاح بالأزرار",
        )
        message = await itx.channel.send(
            embed=embed,
            view=SuggestionActionView(),
        )
        await message.add_reaction("👍")
        await message.add_reaction("👎")
        await itx.response.send_message(
            "✅ تم إرسال الاقتراح للمناقشة والتصويت.",
            ephemeral=True,
        )

    @app_commands.command(
        name="poll",
        description="طرح تصويت حي بالأزرار مع نسب مئوية فورية",
    )
    @app_commands.checks.bot_has_permissions(
        view_channel=True,
        send_messages=True,
        embed_links=True,
        read_message_history=True,
    )
    @app_commands.describe(
        question="سؤال الاستطلاع",
        opt_a="الخيار الأول",
        opt_b="الخيار الثاني",
    )
    async def poll(
        self,
        itx: discord.Interaction,
        question: str,
        opt_a: str,
        opt_b: str,
    ):
        poll_view = LivePollView(question, opt_a, opt_b)
        await itx.channel.send(
            embed=poll_view.make_embed(),
            view=poll_view,
        )
        await itx.response.send_message(
            "✅ تم إنشاء التصويت التفاعلي بنجاح.",
            ephemeral=True,
        )

    @app_commands.command(
        name="remind",
        description="ضبط منبه تذكير بالدقائق",
    )
    @app_commands.checks.bot_has_permissions(
        view_channel=True,
        send_messages=True,
    )
    @app_commands.describe(
        minutes="المدة بالدقائق",
        reminder="الرسالة المطلوب التذكير بها",
    )
    async def remind(
        self,
        itx: discord.Interaction,
        minutes: int,
        reminder: str,
    ):
        if minutes < 1:
            return await itx.response.send_message(
                "❌ أقل وقت للتذكير هو دقيقة واحدة.",
                ephemeral=True,
            )
        await itx.response.send_message(
            "⏰ تم ضبط المنبه بنجاح! سأقوم بتذكيرك بـ "
            f"**{reminder}** بعد `{minutes}` دقيقة."
        )
        await asyncio.sleep(minutes * 60)
        try:
            await itx.channel.send(
                f"🔔 {itx.user.mention} **تذكيرك المستحق:** {reminder}"
            )
        except discord.HTTPException:
            try:
                await itx.user.send(
                    f"🔔 **تذكيرك المستحق:** {reminder}"
                )
            except discord.HTTPException:
                pass

    @app_commands.command(
        name="setup_counters",
        description="تثبيت قنوات صوتية حية لعرض إحصائيات السيرفر",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(
        view_channel=True,
        send_messages=True,
        manage_channels=True,
    )
    async def setup_counters(self, itx: discord.Interaction):
        guild = itx.guild
        category = await guild.create_category("📊 إحصائيات السيرفر")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=False)
        }
        member_channel = await guild.create_voice_channel(
            name=f"👥 الأعضاء: {guild.member_count}",
            category=category,
            overwrites=overwrites,
        )
        boost_channel = await guild.create_voice_channel(
            name=f"🚀 البوست: {guild.premium_subscription_count}",
            category=category,
            overwrites=overwrites,
        )
        self.counters[guild.id] = {
            "members": member_channel.id,
            "boosts": boost_channel.id,
        }
        await itx.response.send_message(
            "✅ تم إنشاء قنوات الإحصائيات الحية بنجاح!",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    bot.add_view(SuggestionActionView())
    await bot.add_cog(Community(bot))
    logger.info(
        "Community cog initialized with /suggest, /poll, /remind, "
        "and /setup_counters."
    )
