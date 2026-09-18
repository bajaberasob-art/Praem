import asyncio
import html
import io
import json
import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import (
    claim_ticket,
    close_ticket,
    create_ticket,
    escalate_ticket,
    get_active_tickets,
    get_staff_kpis,
    get_ticket_by_channel,
    get_ticket_panels,
    get_ticket_transcripts,
    record_ticket_response,
    save_ticket_panel,
    save_ticket_rating,
    save_ticket_transcript,
)


logger = logging.getLogger(__name__)
TICKET_PRIORITIES = ("normal", "high", "management")
DEFAULT_TICKET_CATEGORIES = [
    {
        "key": "general",
        "label": "شكاوى عامة",
        "emoji": "📣",
        "support_role_ids": [],
        "senior_role_ids": [],
    },
    {
        "key": "questions",
        "label": "استفسارات",
        "emoji": "❓",
        "support_role_ids": [],
        "senior_role_ids": [],
    },
    {
        "key": "billing",
        "label": "دعم الشحن",
        "emoji": "💳",
        "support_role_ids": [],
        "senior_role_ids": [],
    },
    {
        "key": "tournaments",
        "label": "بطولات",
        "emoji": "🏆",
        "support_role_ids": [],
        "senior_role_ids": [],
    },
]


def normalize_ticket_categories(categories_config):
    source = categories_config or DEFAULT_TICKET_CATEGORIES
    normalized = []
    for index, raw in enumerate(source[:25]):
        if isinstance(raw, str):
            raw = {"key": raw, "label": raw}
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("name") or f"تصنيف {index + 1}").strip()
        key = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(raw.get("key") or label).strip().lower()).strip("-")
        if not key or not label:
            continue
        normalized.append({
            "key": key[:60],
            "label": label[:80],
            "emoji": str(raw.get("emoji") or "🎫")[:2],
            "category_id": str(raw["category_id"]) if raw.get("category_id") else None,
            "support_role_ids": [str(item) for item in raw.get("support_role_ids", []) if str(item).isdigit()],
            "senior_role_ids": [str(item) for item in raw.get("senior_role_ids", []) if str(item).isdigit()],
        })
    return normalized or normalize_ticket_categories(DEFAULT_TICKET_CATEGORIES)


class TicketCategoryModal(discord.ui.Modal):
    def __init__(self, category: dict):
        super().__init__(title=f"فتح تذكرة · {category['label']}"[:45])
        self.category = category
        self.subject = discord.ui.TextInput(
            label="عنوان المشكلة",
            placeholder="اكتب عنواناً مختصراً وواضحاً",
            max_length=200,
            required=True,
        )
        self.details = discord.ui.TextInput(
            label="التفاصيل والطلب",
            placeholder="اشرح المشكلة أو ما تحتاجه بالتفصيل",
            style=discord.TextStyle.paragraph,
            max_length=4000,
            required=True,
        )
        self.add_item(self.subject)
        self.add_item(self.details)

    async def on_submit(self, itx: discord.Interaction):
        cog = itx.client.get_cog("Community")
        if cog is None:
            return await itx.response.send_message(
                "⚠️ نظام التذاكر غير متاح حالياً.", ephemeral=True
            )
        await cog.open_ticket(
            itx,
            self.category,
            str(self.subject),
            str(self.details),
        )


class CloseTicketModal(discord.ui.Modal, title="إغلاق وأرشفة التذكرة"):
    reason = discord.ui.TextInput(
        label="سبب الإغلاق",
        placeholder="اكتب ملخص الحل أو سبب الإغلاق",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True,
    )

    async def on_submit(self, itx: discord.Interaction):
        cog = itx.client.get_cog("Community")
        if cog is None:
            return await itx.response.send_message(
                "⚠️ نظام التذاكر غير متاح حالياً.", ephemeral=True
            )
        await cog.close_ticket_from_interaction(itx, str(self.reason))


class TicketPanelView(discord.ui.View):
    def __init__(self, categories_config):
        super().__init__(timeout=None)
        self.categories = normalize_ticket_categories(categories_config)
        for category in self.categories:
            button = discord.ui.Button(
                label=category["label"][:80],
                emoji=category["emoji"],
                style=discord.ButtonStyle.primary,
                custom_id=f"ticket:category:{category['key']}",
            )

            async def callback(itx: discord.Interaction, selected=category):
                await itx.response.send_modal(TicketCategoryModal(selected))

            button.callback = callback
            self.add_item(button)


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _cog(self, itx):
        return itx.client.get_cog("Community")

    @discord.ui.button(
        label="استلام التذكرة",
        style=discord.ButtonStyle.success,
        emoji="🙋",
        custom_id="ticket:claim",
    )
    async def claim(self, itx: discord.Interaction, btn: discord.ui.Button):
        cog = await self._cog(itx)
        if cog:
            await cog.claim_ticket_from_interaction(itx)

    @discord.ui.button(
        label="تصعيد التذكرة",
        style=discord.ButtonStyle.primary,
        emoji="🚨",
        custom_id="ticket:escalate",
    )
    async def escalate(self, itx: discord.Interaction, btn: discord.ui.Button):
        cog = await self._cog(itx)
        if cog:
            await cog.escalate_ticket_from_interaction(itx)

    @discord.ui.button(
        label="إغلاق وأرشفة",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="ticket:close",
    )
    async def close(self, itx: discord.Interaction, btn: discord.ui.Button):
        cog = await self._cog(itx)
        if cog:
            await cog.show_close_modal(itx)


class TicketRatingView(discord.ui.View):
    def __init__(self, ticket_id: int, user_id: int, guild_id: int):
        super().__init__(timeout=None)
        self.ticket_id, self.user_id, self.guild_id = ticket_id, user_id, guild_id
        for stars in range(1, 6):
            button = discord.ui.Button(
                label=f"{stars} نجوم",
                style=discord.ButtonStyle.secondary if stars < 4 else discord.ButtonStyle.success,
                custom_id=f"ticket:rating:{ticket_id}:{stars}",
            )

            async def callback(itx: discord.Interaction, value=stars):
                if itx.user.id != self.user_id:
                    return await itx.response.send_message(
                        "هذا التقييم مخصص لصاحب التذكرة.", ephemeral=True
                    )
                await save_ticket_rating(
                    self.ticket_id,
                    self.guild_id,
                    self.user_id,
                    value,
                )
                for child in self.children:
                    child.disabled = True
                await itx.response.edit_message(
                    content=f"✅ شكراً لك، تم تسجيل تقييمك: {value}/5",
                    view=self,
                )

            button.callback = callback
            self.add_item(button)


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
