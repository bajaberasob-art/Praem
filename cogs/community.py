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

    async def deploy_ticket_panel(
        self,
        channel_id: int,
        categories_config: list[dict] | None = None,
    ) -> dict:
        """Publish and persist a category panel with durable custom IDs."""
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            raise ValueError("ticket panel channel was not found")
        categories = normalize_ticket_categories(categories_config)
        embed = discord.Embed(
            title="🎫 مركز الدعم والتذاكر",
            description=(
                "اختر التصنيف الأقرب لطلبك. ستظهر لك نافذة قصيرة لجمع "
                "التفاصيل قبل فتح قناة خاصة مع فريق الدعم."
            ),
            color=0x00D9A6,
        )
        embed.set_footer(text="Help Desk • اختر تصنيفاً لبدء المحادثة")
        view = TicketPanelView(categories)
        message = await channel.send(embed=embed, view=view)
        try:
            await message.pin()
        except (AttributeError, discord.Forbidden, discord.HTTPException):
            logger.debug("Unable to pin ticket panel message", exc_info=True)
        self.bot.add_view(view, message_id=message.id)
        return await save_ticket_panel(
            channel.guild.id,
            channel.id,
            message.id,
            categories,
        )

    async def get_active_tickets(self, guild_id: int) -> list[dict]:
        return await get_active_tickets(guild_id)

    async def get_ticket_transcripts(
        self,
        guild_id: int,
        query: str = "",
    ) -> list[dict]:
        return await get_ticket_transcripts(guild_id, query)

    async def get_staff_kpis(self, guild_id: int) -> list[dict]:
        return await get_staff_kpis(guild_id)

    @staticmethod
    def _is_ticket_staff(member, ticket: dict) -> bool:
        permissions = getattr(member, "guild_permissions", None)
        if permissions and (
            getattr(permissions, "administrator", False)
            or getattr(permissions, "manage_channels", False)
            or getattr(permissions, "manage_guild", False)
        ):
            return True
        allowed = {str(role_id) for role_id in ticket.get("support_role_ids", [])}
        return bool(
            allowed.intersection(
                {str(role.id) for role in getattr(member, "roles", [])}
            )
        )

    async def _ticket_denied(self, itx: discord.Interaction):
        message = "⛔ هذا الإجراء متاح لفريق الدعم والإدارة فقط."
        if itx.response.is_done():
            await itx.followup.send(message, ephemeral=True)
        else:
            await itx.response.send_message(message, ephemeral=True)

    async def open_ticket(
        self,
        itx: discord.Interaction,
        category: dict,
        subject: str,
        details: str,
    ) -> dict | None:
        guild = itx.guild
        if guild is None:
            return await itx.response.send_message(
                "🔒 فتح التذاكر متاح داخل السيرفرات فقط.", ephemeral=True
            )
        active = await get_active_tickets(guild.id)
        if any(ticket["user_id"] == itx.user.id for ticket in active):
            return await itx.response.send_message(
                "📌 لديك تذكرة مفتوحة بالفعل. أغلقها قبل فتح تذكرة جديدة.",
                ephemeral=True,
            )
        parent = None
        if category.get("category_id"):
            parent = guild.get_channel(int(category["category_id"]))
            if not isinstance(parent, discord.CategoryChannel):
                parent = None
        if parent is None and isinstance(itx.channel, discord.TextChannel):
            parent = itx.channel.category
        safe_name = re.sub(r"[^a-zA-Z0-9-]+", "-", itx.user.display_name.lower()).strip("-")
        safe_name = (safe_name or f"user-{itx.user.id}")[:45]
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            itx.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
        }
        for role_id in category.get("support_role_ids", []):
            role = guild.get_role(int(role_id))
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
            )
        channel = await guild.create_text_channel(
            name=f"ticket-{safe_name}-{itx.user.id}"[:100],
            category=parent,
            overwrites=overwrites,
            topic=f"Ticket • {category['label']} • Normal • {subject[:80]}",
        )
        ticket = await create_ticket(
            guild.id,
            channel.id,
            itx.user.id,
            category["key"],
            category["label"],
            subject,
            details,
            category.get("support_role_ids"),
            category.get("senior_role_ids"),
        )
        embed = self._ticket_embed(ticket)
        message = await channel.send(
            content=itx.user.mention,
            embed=embed,
            view=TicketControlView(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        try:
            await message.pin()
        except (AttributeError, discord.Forbidden, discord.HTTPException):
            logger.debug("Unable to pin ticket control message", exc_info=True)
        await itx.response.send_message(
            f"✅ تم فتح تذكرتك: {channel.mention}", ephemeral=True
        )
        return ticket

    @staticmethod
    def _ticket_embed(ticket: dict) -> discord.Embed:
        priority = {
            "normal": "🟢 عادية",
            "high": "🟠 عالية",
            "management": "🔴 تصعيد إداري",
        }.get(ticket.get("priority"), "🟢 عادية")
        embed = discord.Embed(
            title=f"🎫 {ticket['category_label']} · #{ticket['id']}",
            description=ticket["details"],
            color={
                "normal": 0x00D9A6,
                "high": 0xF59E0B,
                "management": 0xEF4444,
            }.get(ticket.get("priority"), 0x00D9A6),
        )
        embed.add_field(name="الموضوع", value=ticket["subject"], inline=False)
        embed.add_field(name="الأولوية", value=priority, inline=True)
        embed.add_field(
            name="التعليمات",
            value="استلم التذكرة، صعّدها عند الحاجة، ثم أغلقها بعد حل الطلب.",
            inline=False,
        )
        return embed

    async def claim_ticket_from_interaction(self, itx: discord.Interaction):
        ticket = await get_ticket_by_channel(itx.channel.id)
        if not ticket or ticket["status"] != "active":
            return await itx.response.send_message("هذه التذكرة مغلقة.", ephemeral=True)
        if not self._is_ticket_staff(itx.user, ticket):
            return await self._ticket_denied(itx)
        if ticket.get("claimed_by") and ticket["claimed_by"] != itx.user.id:
            return await itx.response.send_message(
                "👤 التذكرة مستلمة من عضو آخر في فريق الدعم.", ephemeral=True
            )
        ticket = await claim_ticket(itx.guild.id, ticket["id"], itx.user.id)
        overwrites = itx.channel.overwrites
        for role_id in ticket.get("support_role_ids", []):
            role = itx.guild.get_role(int(role_id))
            if role:
                overwrite = itx.channel.overwrites_for(role)
                overwrite.send_messages = False
                await itx.channel.set_permissions(role, overwrite=overwrite)
        overwrite = itx.channel.overwrites_for(itx.user)
        overwrite.view_channel = True
        overwrite.send_messages = True
        await itx.channel.set_permissions(itx.user, overwrite=overwrite)
        await itx.channel.edit(
            topic=f"Ticket • {ticket['category_label']} • مستلمة بواسطة {itx.user.display_name}"
        )
        await itx.response.send_message("✅ تم استلام التذكرة حصرياً لك.", ephemeral=True)

    async def escalate_ticket_from_interaction(self, itx: discord.Interaction):
        ticket = await get_ticket_by_channel(itx.channel.id)
        if not ticket or ticket["status"] != "active":
            return await itx.response.send_message("هذه التذكرة مغلقة.", ephemeral=True)
        if not self._is_ticket_staff(itx.user, ticket):
            return await self._ticket_denied(itx)
        current = ticket.get("priority", "normal")
        priority = TICKET_PRIORITIES[
            min(TICKET_PRIORITIES.index(current) + 1, len(TICKET_PRIORITIES) - 1)
        ]
        ticket = await escalate_ticket(itx.guild.id, ticket["id"], priority)
        await itx.channel.edit(
            topic=f"Ticket • {ticket['category_label']} • {priority.upper()}"
        )
        mentions = [
            itx.guild.get_role(int(role_id)).mention
            for role_id in ticket.get("senior_role_ids", [])
            if itx.guild.get_role(int(role_id))
        ]
        if mentions:
            await itx.channel.send(
                " ".join(mentions) + " 🚨 تم تصعيد هذه التذكرة.",
                allowed_mentions=discord.AllowedMentions(roles=True, everyone=False),
            )
        await itx.response.send_message(
            f"🚨 تم تحديث الأولوية إلى: **{priority}**.", ephemeral=True
        )

    async def show_close_modal(self, itx: discord.Interaction):
        ticket = await get_ticket_by_channel(itx.channel.id)
        if not ticket or ticket["status"] != "active":
            return await itx.response.send_message("هذه التذكرة مغلقة.", ephemeral=True)
        if not self._is_ticket_staff(itx.user, ticket):
            return await self._ticket_denied(itx)
        await itx.response.send_modal(CloseTicketModal())

    async def close_ticket_from_interaction(
        self,
        itx: discord.Interaction,
        reason: str,
    ):
        ticket = await get_ticket_by_channel(itx.channel.id)
        if not ticket or ticket["status"] != "active":
            return await itx.response.send_message("هذه التذكرة مغلقة.", ephemeral=True)
        if not self._is_ticket_staff(itx.user, ticket):
            return await self._ticket_denied(itx)
        text, content_html = await self._build_transcript(itx.channel, ticket)
        text += f"\n\nClose reason: {reason}"
        content_html = content_html.replace(
            "</body></html>",
            f"<hr><p><strong>سبب الإغلاق:</strong> {html.escape(reason)}</p></body></html>",
        )
        await save_ticket_transcript(
            ticket["id"], ticket["guild_id"], ticket["channel_id"], text, content_html
        )
        ticket = await close_ticket(ticket["guild_id"], ticket["id"], itx.user.id, reason)
        await itx.channel.edit(
            name=f"archived-ticket-{ticket['id']}"[:100],
            topic=f"Archived ticket • closed by {itx.user.display_name}",
        )
        for target in [itx.guild.get_member(ticket["user_id"]), itx.user]:
            if target:
                overwrite = itx.channel.overwrites_for(target)
                overwrite.send_messages = False
                await itx.channel.set_permissions(target, overwrite=overwrite)
        self.bot.add_view(
            TicketRatingView(ticket["id"], ticket["user_id"], ticket["guild_id"])
        )
        user = itx.guild.get_member(ticket["user_id"])
        if user is None:
            try:
                user = await self.bot.fetch_user(ticket["user_id"])
            except (discord.NotFound, discord.HTTPException):
                user = None
        if user:
            try:
                await user.send(
                    f"📁 تم إغلاق تذكرتك **#{ticket['id']}**.\n"
                    "نقدّر تقييمك لتجربة الدعم:",
                    files=[
                        discord.File(
                            io.BytesIO(content_html.encode("utf-8")),
                            filename=f"ticket-{ticket['id']}.html",
                        ),
                        discord.File(
                            io.BytesIO(text.encode("utf-8")),
                            filename=f"ticket-{ticket['id']}.txt",
                        ),
                    ],
                    view=TicketRatingView(
                        ticket["id"], ticket["user_id"], ticket["guild_id"]
                    ),
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.info("Could not DM transcript for ticket %s", ticket["id"])
        await itx.response.send_message(
            "✅ أُغلقت التذكرة وحُفظ transcript وأُرسل للمستخدم.", ephemeral=True
        )

    async def _build_transcript(self, channel, ticket):
        lines = [
            f"Ticket #{ticket['id']} — {ticket['category_label']}",
            f"Subject: {ticket['subject']}",
            f"Opened by: {ticket['user_id']}",
            "",
        ]
        html_lines = [
            "<!doctype html><html lang='ar' dir='rtl'><meta charset='utf-8'>",
            "<style>body{background:#050505;color:#e5edf8;font:15px system-ui;padding:28px}"
            ".msg{border:1px solid #1e293b;border-radius:10px;padding:10px;margin:8px 0}"
            ".meta{color:#7dd3fc;font-size:12px}</style><body>",
            f"<h1>Ticket #{ticket['id']} · {html.escape(ticket['category_label'])}</h1>",
            f"<p>{html.escape(ticket['subject'])}</p>",
        ]
        try:
            history = channel.history(limit=None, oldest_first=True)
            async for message in history:
                created = getattr(message, "created_at", None)
                stamp = created.isoformat() if created else ""
                author = html.escape(getattr(message.author, "display_name", str(message.author)))
                content = str(getattr(message, "content", "") or "")
                lines.append(f"[{stamp}] {author}: {content}")
                html_lines.append(
                    f"<div class='msg'><div class='meta'>{author} · {html.escape(stamp)}</div>"
                    f"<div>{html.escape(content).replace(chr(10), '<br>')}</div></div>"
                )
        except (AttributeError, discord.HTTPException):
            logger.warning("Could not read transcript history for ticket %s", ticket["id"])
        html_lines.append("</body></html>")
        return "\n".join(lines), "\n".join(html_lines)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        ticket = await get_ticket_by_channel(message.channel.id)
        if (
            ticket
            and ticket["status"] == "active"
            and message.author.id != ticket["user_id"]
            and self._is_ticket_staff(message.author, ticket)
        ):
            await record_ticket_response(ticket["guild_id"], ticket["id"])

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
    bot.add_view(TicketControlView())
    for panel in await get_ticket_panels():
        if bot.get_channel(panel["channel_id"]):
            bot.add_view(
                TicketPanelView(panel["categories"]),
                message_id=panel["message_id"],
            )
    community = Community(bot)
    await bot.add_cog(community)
    logger.info(
        "Community cog initialized with /suggest, /poll, /remind, "
        "/setup_counters, and persistent ticket controls."
    )
