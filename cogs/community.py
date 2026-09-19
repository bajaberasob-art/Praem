import asyncio
import datetime
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
    unclaim_ticket,
    close_ticket,
    create_ticket,
    escalate_ticket,
    add_ticket_note,
    get_active_tickets,
    get_ticket_archive,
    get_ticket,
    get_staff_kpis,
    get_ticket_by_channel,
    get_ticket_panels,
    get_ticket_transcripts,
    get_ticket_transcript,
    get_canned_responses,
    save_canned_response,
    delete_canned_response,
    cancel_reminder,
    record_ticket_response,
    record_ticket_user_message,
    set_ticket_status,
    set_ticket_priority,
    reopen_ticket,
    get_ticket_notes,
    save_ticket_panel,
    save_ticket_rating,
    save_ticket_transcript,
    complete_reminder,
    create_reminder,
    get_due_reminders,
    get_user_reminders,
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
            "intake_fields": [
                {
                    "key": re.sub(
                        r"[^a-zA-Z0-9_-]+",
                        "_",
                        str(field.get("key") or f"field_{field_index + 1}").strip().lower(),
                    ).strip("_")[:40] or f"field_{field_index + 1}",
                    "label": str(field.get("label") or f"معلومة إضافية {field_index + 1}").strip()[:45],
                    "placeholder": str(field.get("placeholder") or "").strip()[:100],
                    "required": bool(field.get("required", False)),
                }
                for field_index, field in enumerate(raw.get("intake_fields", [])[:3])
                if isinstance(field, dict)
                and str(field.get("label") or "").strip()
            ],
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
        self.extra_inputs = []
        for index, raw in enumerate(category.get("intake_fields", [])[:3]):
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label") or f"معلومة إضافية {index + 1}")[:45]
            field = discord.ui.TextInput(
                label=label,
                placeholder=str(raw.get("placeholder") or "")[:100],
                max_length=500,
                required=bool(raw.get("required", False)),
            )
            self.extra_inputs.append((str(raw.get("key") or f"field_{index + 1}")[:40], field))
        self.add_item(self.subject)
        self.add_item(self.details)
        for _, field in self.extra_inputs:
            self.add_item(field)

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
            {key: str(field) for key, field in self.extra_inputs if str(field).strip()},
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


class InternalNoteModal(discord.ui.Modal, title="إضافة ملاحظة داخلية"):
    note = discord.ui.TextInput(
        label="الملاحظة",
        placeholder="لن تظهر هذه الملاحظة لصاحب التذكرة",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=True,
    )

    async def on_submit(self, itx: discord.Interaction):
        cog = itx.client.get_cog("Community")
        if cog is None:
            return await itx.response.send_message("نظام التذاكر غير متاح حالياً.", ephemeral=True)
        await cog.add_internal_note_from_interaction(itx, str(self.note))


def _member_id_from_text(value: str) -> int | None:
    match = re.search(r"(?<!\d)(\d{15,25})(?!\d)", str(value or ""))
    return int(match.group(1)) if match else None


class TicketMemberActionModal(discord.ui.Modal):
    def __init__(self, action: str):
        titles = {
            "add": "إضافة عضو إلى التذكرة",
            "remove": "طرد عضو من التذكرة",
            "transfer": "تحويل التذكرة",
        }
        super().__init__(title=titles[action])
        self.action = action
        self.member_id = discord.ui.TextInput(
            label="معرّف Discord أو منشن العضو",
            placeholder="مثال: 123456789012345678",
            max_length=40,
            required=True,
        )
        self.add_item(self.member_id)

    async def on_submit(self, itx: discord.Interaction):
        cog = itx.client.get_cog("Community")
        if cog is None:
            return await itx.response.send_message("نظام التذاكر غير متاح حالياً.", ephemeral=True)
        await cog.handle_ticket_member_action(itx, self.action, str(self.member_id))


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

    @discord.ui.button(
        label="بانتظار العميل",
        style=discord.ButtonStyle.secondary,
        emoji="⏳",
        custom_id="ticket:waiting-user",
    )
    async def waiting_user(self, itx: discord.Interaction, btn: discord.ui.Button):
        cog = await self._cog(itx)
        if cog:
            await cog.set_ticket_status_from_interaction(itx, "waiting_user")

    @discord.ui.button(
        label="ملاحظة داخلية",
        style=discord.ButtonStyle.secondary,
        emoji="📝",
        custom_id="ticket:internal-note",
    )
    async def internal_note(self, itx: discord.Interaction, btn: discord.ui.Button):
        cog = await self._cog(itx)
        if cog:
            await cog.show_internal_note_modal(itx)

    @discord.ui.button(
        label="إضافة عضو",
        style=discord.ButtonStyle.secondary,
        emoji="➕",
        custom_id="ticket:add-member",
    )
    async def add_member(self, itx: discord.Interaction, btn: discord.ui.Button):
        cog = await self._cog(itx)
        if cog:
            await cog.show_ticket_member_modal(itx, "add")

    @discord.ui.button(
        label="طرد عضو",
        style=discord.ButtonStyle.secondary,
        emoji="➖",
        custom_id="ticket:remove-member",
    )
    async def remove_member(self, itx: discord.Interaction, btn: discord.ui.Button):
        cog = await self._cog(itx)
        if cog:
            await cog.show_ticket_member_modal(itx, "remove")

    @discord.ui.button(
        label="ترك التذكرة",
        style=discord.ButtonStyle.secondary,
        emoji="🚪",
        custom_id="ticket:unclaim",
    )
    async def unclaim(self, itx: discord.Interaction, btn: discord.ui.Button):
        cog = await self._cog(itx)
        if cog:
            await cog.unclaim_ticket_from_interaction(itx)

    @discord.ui.button(
        label="تحويل التذكرة",
        style=discord.ButtonStyle.primary,
        emoji="🔁",
        custom_id="ticket:transfer",
    )
    async def transfer(self, itx: discord.Interaction, btn: discord.ui.Button):
        cog = await self._cog(itx)
        if cog:
            await cog.show_ticket_member_modal(itx, "transfer")


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
        self.reminder_task.start()
        logger.info("Community counter updater initialized.")

    def cog_unload(self):
        self.update_counters_task.cancel()
        self.reminder_task.cancel()

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

    async def get_ticket_archive(
        self,
        guild_id: int,
        query: str = "",
    ) -> list[dict]:
        return await get_ticket_archive(guild_id, query)

    async def get_ticket_transcript(
        self,
        guild_id: int,
        ticket_id: int,
    ) -> dict | None:
        return await get_ticket_transcript(guild_id, ticket_id)

    async def get_staff_kpis(self, guild_id: int) -> list[dict]:
        return await get_staff_kpis(guild_id)

    async def get_canned_responses(self, guild_id: int) -> list[dict]:
        return await get_canned_responses(guild_id)

    async def get_ticket_notes(self, guild_id: int, ticket_id: int) -> list[dict]:
        return await get_ticket_notes(guild_id, ticket_id)

    async def get_ticket(self, guild_id: int, ticket_id: int) -> dict | None:
        return await get_ticket(guild_id, ticket_id)

    async def save_canned_response(
        self,
        guild_id: int,
        title: str,
        content: str,
        category: str = "عام",
        created_by: int | str | None = None,
        response_id: int | None = None,
        shortcut: str | None = None,
        sticker_id: int | str | None = None,
    ) -> dict:
        return await save_canned_response(
            guild_id,
            title,
            content,
            category,
            created_by,
            response_id,
            shortcut,
            sticker_id,
        )

    async def delete_canned_response(self, guild_id: int, response_id: int) -> bool:
        return await delete_canned_response(guild_id, response_id)

    @staticmethod
    def _render_ticket_reply(template: str, itx: discord.Interaction, ticket: dict) -> str:
        guild = itx.guild
        channel = itx.channel
        values = {
            "user": f"<@{ticket['user_id']}>",
            "staff": getattr(itx.user, "mention", f"<@{itx.user.id}>"),
            "channel": getattr(channel, "mention", f"#{getattr(channel, 'name', 'ticket')}"),
            "server": getattr(guild, "name", "السيرفر"),
            "count": f"{getattr(guild, 'member_count', 0):,}",
            "members": f"{getattr(guild, 'member_count', 0):,}",
            "ticket": str(ticket["id"]),
            "subject": ticket.get("subject", ""),
            "category": ticket.get("category_label", ""),
        }
        rendered = str(template or "")
        for key, value in values.items():
            rendered = rendered.replace("{" + key + "}", str(value))

        def choose(match: re.Match) -> str:
            options = [item.strip() for item in match.group(1).split("|") if item.strip()]
            return options[0] if options else ""

        return re.sub(r"\{random:([^{}|]+(?:\|[^{}|]+)+)\}", choose, rendered)[:2000]

    async def _find_ticket_sticker(self, guild, sticker_id):
        if sticker_id in (None, ""):
            return None
        for sticker in getattr(guild, "stickers", ()) or ():
            if int(getattr(sticker, "id", 0)) == int(sticker_id):
                return sticker
        fetch_stickers = getattr(guild, "fetch_stickers", None)
        if fetch_stickers is not None:
            try:
                for sticker in await fetch_stickers():
                    if int(getattr(sticker, "id", 0)) == int(sticker_id):
                        return sticker
            except (discord.Forbidden, discord.HTTPException):
                logger.debug("Unable to resolve canned response sticker", exc_info=True)
        return None

    @app_commands.command(
        name="ticket_reply",
        description="إرسال رد سريع داخل التذكرة مع دعم المتغيرات والملصقات",
    )
    @app_commands.describe(response="اسم الرد السريع أو اختصاره")
    async def ticket_reply(self, itx: discord.Interaction, response: str):
        ticket = await get_ticket_by_channel(itx.channel.id)
        if not ticket or ticket["status"] == "closed":
            return await itx.response.send_message("هذا الأمر يعمل داخل تذكرة مفتوحة فقط.", ephemeral=True)
        if not self._is_ticket_staff(itx.user, ticket):
            return await self._ticket_denied(itx)
        query = str(response).strip().casefold()
        choices = await get_canned_responses(itx.guild.id)
        selected = next(
            (
                item for item in choices
                if query in {
                    str(item.get("title", "")).casefold(),
                    str(item.get("shortcut", "")).casefold(),
                    str(item.get("id", "")),
                }
            ),
            None,
        )
        if not selected:
            return await itx.response.send_message(
                "لم أجد رداً سريعاً بهذا الاسم أو الاختصار.", ephemeral=True
            )
        content = self._render_ticket_reply(selected["content"], itx, ticket)
        sticker = await self._find_ticket_sticker(itx.guild, selected.get("sticker_id"))
        try:
            await itx.channel.send(
                content,
                stickers=[sticker] if sticker else [],
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=False, everyone=False
                ),
            )
        except (discord.Forbidden, discord.HTTPException):
            return await itx.response.send_message("تعذر إرسال الرد السريع في هذه القناة.", ephemeral=True)
        await record_ticket_response(ticket["guild_id"], ticket["id"])
        await itx.response.send_message(
            f"✅ تم إرسال الرد السريع: **{selected['title']}**",
            ephemeral=True,
        )

    async def add_internal_note(
        self, guild_id: int, ticket_id: int, staff_id: int, content: str
    ) -> dict | None:
        return await add_ticket_note(guild_id, ticket_id, staff_id, content)

    async def reassign_ticket(
        self,
        guild_id: int,
        ticket_id: int,
        staff_id: int,
    ) -> dict | None:
        return await claim_ticket(guild_id, ticket_id, staff_id)

    async def update_ticket_priority(
        self, guild_id: int, ticket_id: int, priority: str
    ) -> dict | None:
        return await set_ticket_priority(guild_id, ticket_id, priority)

    async def set_ticket_status(
        self, guild_id: int, ticket_id: int, status: str, staff_id: int | None = None
    ) -> dict | None:
        return await set_ticket_status(guild_id, ticket_id, status, staff_id=staff_id)

    async def reopen_ticket(
        self, guild_id: int, ticket_id: int, staff_id: int
    ) -> dict | None:
        ticket = await reopen_ticket(guild_id, ticket_id, staff_id)
        if not ticket:
            return None
        channel = self.bot.get_channel(ticket["channel_id"])
        if channel is not None:
            try:
                await channel.edit(
                    name=f"ticket-reopened-{ticket['id']}"[:100],
                    topic=f"Ticket • {ticket['category_label']} • reopened by dashboard",
                )
                member = channel.guild.get_member(ticket["user_id"])
                if member:
                    overwrite = channel.overwrites_for(member)
                    overwrite.view_channel = True
                    overwrite.send_messages = True
                    overwrite.read_message_history = True
                    await channel.set_permissions(member, overwrite=overwrite)
                for role_id in ticket.get("support_role_ids", []):
                    role = channel.guild.get_role(int(role_id))
                    if role:
                        overwrite = channel.overwrites_for(role)
                        overwrite.view_channel = True
                        overwrite.send_messages = True
                        overwrite.read_message_history = True
                        await channel.set_permissions(role, overwrite=overwrite)
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Could not reopen ticket channel %s", ticket["channel_id"])
        return ticket

    async def _delete_ticket_channel_after_delay(self, channel, ticket_id: int):
        await asyncio.sleep(10)
        try:
            await channel.delete(reason=f"Ticket #{ticket_id} closed; delayed cleanup")
        except discord.NotFound:
            return
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Could not delete closed ticket channel %s", getattr(channel, "id", "?"))

    def _schedule_ticket_channel_deletion(self, channel, ticket_id: int):
        asyncio.create_task(self._delete_ticket_channel_after_delay(channel, ticket_id))

    async def force_close_ticket(
        self,
        guild_id: int,
        ticket_id: int,
        staff_id: int,
        reason: str = "أُغلقت من لوحة الإدارة",
    ) -> dict | None:
        active = await get_active_tickets(guild_id)
        ticket = next((item for item in active if item["id"] == int(ticket_id)), None)
        if not ticket:
            return None
        channel = self.bot.get_channel(ticket["channel_id"])
        if channel is not None:
            text, content_html = await self._build_transcript(channel, ticket)
            text += f"\n\nClose reason: {reason}"
            content_html = content_html.replace(
                "</body></html>",
                f"<hr><p><strong>سبب الإغلاق:</strong> {html.escape(reason)}</p></body></html>",
            )
            await save_ticket_transcript(
                ticket["id"], ticket["guild_id"], ticket["channel_id"], text, content_html
            )
            try:
                await channel.edit(
                    name=f"archived-ticket-{ticket['id']}"[:100],
                    topic=f"Archived ticket • closed by dashboard",
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Could not archive ticket channel %s", ticket["channel_id"])
        closed = await close_ticket(guild_id, ticket_id, staff_id, reason)
        if closed and channel is not None:
            self._schedule_ticket_channel_deletion(channel, closed["id"])
        return closed

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
        intake_data: dict | None = None,
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
            intake_data=intake_data,
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
            name="الحالة",
            value={
                "active": "🟢 قيد المعالجة",
                "waiting_user": "⏳ بانتظار العميل",
                "waiting_staff": "📥 بانتظار فريق الدعم",
            }.get(ticket.get("status"), "🟢 قيد المعالجة"),
            inline=True,
        )
        for key, value in list(ticket.get("intake_data", {}).items())[:3]:
            embed.add_field(name=str(key)[:256], value=str(value)[:1024] or "—", inline=True)
        embed.add_field(
            name="التعليمات",
            value=(
                "استلم التذكرة، أضف أو أزل أعضاء عند الحاجة، حوّلها لموظف آخر "
                "أو اتركها للفريق، ثم أغلقها بعد حل الطلب."
            ),
            inline=False,
        )
        return embed

    async def claim_ticket_from_interaction(self, itx: discord.Interaction):
        ticket = await get_ticket_by_channel(itx.channel.id)
        if not ticket or ticket["status"] == "closed":
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

    async def _resolve_ticket_member(self, guild, raw_value: str):
        member_id = _member_id_from_text(raw_value)
        if member_id is None:
            return None
        member = guild.get_member(member_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(member_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def show_ticket_member_modal(self, itx: discord.Interaction, action: str):
        ticket = await get_ticket_by_channel(itx.channel.id)
        if not ticket or ticket["status"] == "closed":
            return await itx.response.send_message("هذه التذكرة مغلقة.", ephemeral=True)
        if not self._is_ticket_staff(itx.user, ticket):
            return await self._ticket_denied(itx)
        await itx.response.send_modal(TicketMemberActionModal(action))

    async def handle_ticket_member_action(
        self,
        itx: discord.Interaction,
        action: str,
        raw_member: str,
    ):
        ticket = await get_ticket_by_channel(itx.channel.id)
        if not ticket or ticket["status"] == "closed":
            return await itx.response.send_message("هذه التذكرة مغلقة.", ephemeral=True)
        if not self._is_ticket_staff(itx.user, ticket):
            return await self._ticket_denied(itx)
        member = await self._resolve_ticket_member(itx.guild, raw_member)
        if member is None:
            return await itx.response.send_message(
                "لم أجد هذا العضو داخل السيرفر. أرسل Discord ID صحيحاً أو منشن العضو.",
                ephemeral=True,
            )
        if action == "add":
            await itx.channel.set_permissions(
                member,
                overwrite=discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                ),
            )
            return await itx.response.send_message(
                f"✅ تمت إضافة {member.mention} إلى التذكرة.",
                ephemeral=True,
            )
        if action == "remove":
            if member.id == ticket["user_id"]:
                return await itx.response.send_message(
                    "لا يمكن طرد صاحب التذكرة. استخدم إغلاق التذكرة عند انتهاء الطلب.",
                    ephemeral=True,
                )
            if itx.guild.me and member.id == itx.guild.me.id:
                return await itx.response.send_message(
                    "لا يمكن إزالة البوت من قناة التذكرة.",
                    ephemeral=True,
                )
            member_role_ids = {str(role.id) for role in getattr(member, "roles", [])}
            support_role_ids = {str(role_id) for role_id in ticket.get("support_role_ids", [])}
            if member_role_ids.intersection(support_role_ids):
                await itx.channel.set_permissions(
                    member,
                    overwrite=discord.PermissionOverwrite(
                        view_channel=False,
                        send_messages=False,
                        read_message_history=False,
                    ),
                )
            else:
                await itx.channel.set_permissions(member, overwrite=None)
            return await itx.response.send_message(
                f"✅ تمت إزالة {member.mention} من التذكرة.",
                ephemeral=True,
            )
        if action == "transfer":
            if not self._is_ticket_staff(member, ticket):
                return await itx.response.send_message(
                    "لا يمكن تحويل التذكرة إلا إلى عضو من فريق الدعم أو الإدارة.",
                    ephemeral=True,
                )
            if ticket.get("claimed_by") == member.id:
                return await itx.response.send_message(
                    "التذكرة مستلمة بالفعل من هذا العضو.",
                    ephemeral=True,
                )
            old_staff = (
                itx.guild.get_member(ticket["claimed_by"])
                if ticket.get("claimed_by")
                else None
            )
            ticket = await claim_ticket(itx.guild.id, ticket["id"], member.id)
            if old_staff and old_staff.id != member.id:
                old_overwrite = itx.channel.overwrites_for(old_staff)
                old_overwrite.send_messages = None
                await itx.channel.set_permissions(old_staff, overwrite=old_overwrite)
            for role_id in ticket.get("support_role_ids", []):
                role = itx.guild.get_role(int(role_id))
                if role:
                    role_overwrite = itx.channel.overwrites_for(role)
                    role_overwrite.send_messages = False
                    await itx.channel.set_permissions(role, overwrite=role_overwrite)
            target_overwrite = itx.channel.overwrites_for(member)
            target_overwrite.view_channel = True
            target_overwrite.send_messages = True
            target_overwrite.read_message_history = True
            await itx.channel.set_permissions(member, overwrite=target_overwrite)
            await itx.channel.edit(
                topic=f"Ticket • {ticket['category_label']} • مستلمة بواسطة {member.display_name}"
            )
            return await itx.response.send_message(
                f"🔁 تم تحويل التذكرة إلى {member.mention}.",
                ephemeral=True,
            )
        await itx.response.send_message("إجراء التذكرة غير معروف.", ephemeral=True)

    async def unclaim_ticket_from_interaction(self, itx: discord.Interaction):
        ticket = await get_ticket_by_channel(itx.channel.id)
        if not ticket or ticket["status"] == "closed":
            return await itx.response.send_message("هذه التذكرة مغلقة.", ephemeral=True)
        if not self._is_ticket_staff(itx.user, ticket):
            return await self._ticket_denied(itx)
        if ticket.get("claimed_by") != itx.user.id:
            return await itx.response.send_message(
                "لا يمكنك ترك تذكرة لم تستلمها أنت.",
                ephemeral=True,
            )
        ticket = await unclaim_ticket(itx.guild.id, ticket["id"], itx.user.id)
        if not ticket:
            return await itx.response.send_message(
                "تعذر ترك التذكرة؛ ربما استلمها موظف آخر.",
                ephemeral=True,
            )
        for role_id in ticket.get("support_role_ids", []):
            role = itx.guild.get_role(int(role_id))
            if role:
                role_overwrite = itx.channel.overwrites_for(role)
                role_overwrite.view_channel = True
                role_overwrite.send_messages = True
                await itx.channel.set_permissions(role, overwrite=role_overwrite)
        overwrite = itx.channel.overwrites_for(itx.user)
        overwrite.send_messages = None
        await itx.channel.set_permissions(itx.user, overwrite=overwrite)
        await itx.channel.edit(
            topic=f"Ticket • {ticket['category_label']} • بانتظار فريق الدعم"
        )
        await itx.response.send_message(
            "🚪 تركت التذكرة وأصبحت متاحة لفريق الدعم من جديد.",
            ephemeral=True,
        )

    async def escalate_ticket_from_interaction(self, itx: discord.Interaction):
        ticket = await get_ticket_by_channel(itx.channel.id)
        if not ticket or ticket["status"] == "closed":
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

    async def set_ticket_status_from_interaction(
        self, itx: discord.Interaction, status: str
    ):
        ticket = await get_ticket_by_channel(itx.channel.id)
        if not ticket or ticket["status"] == "closed":
            return await itx.response.send_message("هذه التذكرة مغلقة.", ephemeral=True)
        if not self._is_ticket_staff(itx.user, ticket):
            return await self._ticket_denied(itx)
        ticket = await set_ticket_status(itx.guild.id, ticket["id"], status, staff_id=itx.user.id)
        labels = {"active": "قيد المعالجة", "waiting_user": "بانتظار العميل", "waiting_staff": "بانتظار فريق الدعم"}
        await itx.channel.edit(topic=f"Ticket • {ticket['category_label']} • {labels[status]}")
        await itx.response.send_message(f"تم تحديث الحالة إلى: **{labels[status]}**.", ephemeral=True)

    async def show_internal_note_modal(self, itx: discord.Interaction):
        ticket = await get_ticket_by_channel(itx.channel.id)
        if not ticket or ticket["status"] == "closed":
            return await itx.response.send_message("هذه التذكرة مغلقة.", ephemeral=True)
        if not self._is_ticket_staff(itx.user, ticket):
            return await self._ticket_denied(itx)
        await itx.response.send_modal(InternalNoteModal())

    async def add_internal_note_from_interaction(self, itx: discord.Interaction, content: str):
        ticket = await get_ticket_by_channel(itx.channel.id)
        if not ticket or not self._is_ticket_staff(itx.user, ticket):
            return await self._ticket_denied(itx)
        note = await self.add_internal_note(itx.guild.id, ticket["id"], itx.user.id, content)
        if not note:
            return await itx.response.send_message("تعذر حفظ الملاحظة.", ephemeral=True)
        await itx.response.send_message("📝 تم حفظ الملاحظة الداخلية.", ephemeral=True)

    async def show_close_modal(self, itx: discord.Interaction):
        ticket = await get_ticket_by_channel(itx.channel.id)
        if not ticket or ticket["status"] == "closed":
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
        if not ticket or ticket["status"] == "closed":
            return await itx.response.send_message("هذه التذكرة مغلقة.", ephemeral=True)
        if not self._is_ticket_staff(itx.user, ticket):
            return await self._ticket_denied(itx)
        await itx.response.defer(ephemeral=True)
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
        self._schedule_ticket_channel_deletion(itx.channel, ticket["id"])
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
        await itx.followup.send(
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
        if not ticket or ticket["status"] == "closed":
            return
        if message.author.id == ticket["user_id"]:
            await record_ticket_user_message(ticket["guild_id"], ticket["id"])
        elif self._is_ticket_staff(message.author, ticket):
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
                        logger.warning("Could not update member counter in guild %s", guild.id, exc_info=True)
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
                        logger.warning("Could not update boost counter in guild %s", guild.id, exc_info=True)

    @update_counters_task.before_loop
    async def before_counter(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=10)
    async def reminder_task(self):
        """Deliver queued reminders from SQLite so restarts do not lose them."""
        for item in await get_due_reminders():
            delivered = False
            content = (
                f"🔔 <@{item['user_id']}> تذكيرك المستحق:\n"
                f"**{item['reminder']}**"
            )
            channel = self.bot.get_channel(int(item["channel_id"]))
            if channel is not None:
                try:
                    await channel.send(content)
                    delivered = True
                except (discord.Forbidden, discord.HTTPException):
                    logger.warning(
                        "[REMINDER] تعذر الإرسال في القناة %s",
                        item["channel_id"],
                    )
            if not delivered:
                try:
                    user = self.bot.get_user(int(item["user_id"])) or await self.bot.fetch_user(int(item["user_id"]))
                    await user.send(f"🔔 تذكيرك المستحق:\n**{item['reminder']}**")
                    delivered = True
                except (discord.Forbidden, discord.HTTPException):
                    logger.warning(
                        "[REMINDER] تعذر الإرسال الخاص للمستخدم %s",
                        item["user_id"],
                    )
            if delivered:
                await complete_reminder(int(item["id"]))

    @reminder_task.before_loop
    async def before_reminder(self):
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
        due_at = (
            discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
        ).strftime("%Y-%m-%d %H:%M:%S")
        reminder_id = await create_reminder(
            itx.guild.id,
            itx.user.id,
            itx.channel.id,
            reminder,
            due_at,
        )
        await itx.response.send_message(
            "⏰ تم حفظ التذكير بنجاح.\n"
            f"الرقم: `{reminder_id}` | بعد: `{minutes}` دقيقة\n"
            "سيستمر حتى لو أعيد تشغيل البوت."
        )

    @app_commands.command(
        name="reminders",
        description="عرض تذكيراتك المحفوظة في هذا السيرفر",
    )
    async def reminders(self, itx: discord.Interaction):
        items = await get_user_reminders(itx.guild.id, itx.user.id)
        if not items:
            return await itx.response.send_message(
                "لا توجد لديك تذكيرات معلقة.",
                ephemeral=True,
            )
        lines = [
            f"`#{item['id']}` — <t:{int(datetime.datetime.fromisoformat(item['due_at']).replace(tzinfo=datetime.timezone.utc).timestamp())}:R> — {item['reminder']}"
            for item in items
        ]
        await itx.response.send_message(
            "⏰ **تذكيراتك المعلقة**\n" + "\n".join(lines),
            ephemeral=True,
        )

    @app_commands.command(
        name="reminder_cancel",
        description="إلغاء تذكير محفوظ بالرقم",
    )
    async def reminder_cancel(self, itx: discord.Interaction, reminder_id: int):
        if await cancel_reminder(itx.guild.id, itx.user.id, reminder_id):
            return await itx.response.send_message(
                f"✅ تم إلغاء التذكير `#{reminder_id}`.",
                ephemeral=True,
            )
        await itx.response.send_message(
            "❌ لم أجد تذكيراً نشطاً بهذا الرقم يخصك.",
            ephemeral=True,
        )

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
        category = discord.utils.get(guild.categories, name="📊 إحصائيات السيرفر")
        if category is None:
            category = await guild.create_category("📊 إحصائيات السيرفر")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=False)
        }
        member_channel = discord.utils.get(category.voice_channels, name__startswith="👥 الأعضاء:")
        if member_channel is None:
            member_channel = await guild.create_voice_channel(
                name=f"👥 الأعضاء: {guild.member_count}",
                category=category,
                overwrites=overwrites,
            )
        else:
            await member_channel.edit(name=f"👥 الأعضاء: {guild.member_count}")
        boost_channel = discord.utils.get(category.voice_channels, name__startswith="🚀 البوست:")
        if boost_channel is None:
            boost_channel = await guild.create_voice_channel(
                name=f"🚀 البوست: {guild.premium_subscription_count}",
                category=category,
                overwrites=overwrites,
            )
        else:
            await boost_channel.edit(name=f"🚀 البوست: {guild.premium_subscription_count}")
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
