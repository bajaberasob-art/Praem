import asyncio

import discord
from discord import app_commands
from discord.ext import commands


class TicketControl(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="استلام التذكرة (Claim)",
        style=discord.ButtonStyle.secondary,
        emoji="📌",
        custom_id="btn_claim_t",
    )
    async def claim(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        if not itx.user.guild_permissions.manage_channels:
            return await itx.response.send_message(
                "❌ هذا الإجراء متاح للمشرفين فقط.",
                ephemeral=True,
            )
        btn.disabled = True
        btn.label = f"مستلمة بواسطة {itx.user.display_name}"
        await itx.message.edit(view=self)
        await itx.response.send_message(
            f"📌 تم استلام التذكرة من قبل المشرف: {itx.user.mention}"
        )

    @discord.ui.button(
        label="إغلاق التذكرة",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="btn_close_t",
    )
    async def close(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        await itx.response.send_message(
            "⚠️ سيتم إغلاق التذكرة وحذف القناة خلال 5 ثوانٍ..."
        )
        await asyncio.sleep(5)
        try:
            await itx.channel.delete()
        except Exception:
            pass


class TicketLauncher(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="فتح تذكرة دعم",
        style=discord.ButtonStyle.success,
        emoji="📩",
        custom_id="btn_open_t",
    )
    async def open(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        guild = itx.guild
        category = discord.utils.get(guild.categories, name="Tickets")
        if category is None:
            category = await guild.create_category("Tickets")

        # منع العضو من إنشاء أكثر من تذكرة مفتوحة
        ticket_name = f"ticket-{itx.user.name.lower()}"
        if discord.utils.get(category.text_channels, name=ticket_name):
            return await itx.response.send_message(
                "❌ لديك تذكرة مفتوحة بالفعل داخل السيرفر!",
                ephemeral=True,
            )

        permissions = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            itx.user: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                attach_files=True,
            ),
            guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_channels=True,
            ),
        }
        channel = await guild.create_text_channel(
            name=ticket_name,
            category=category,
            overwrites=permissions,
        )
        embed = discord.Embed(
            title=f"🎫 تذكرة الدعم | {itx.user.display_name}",
            description=(
                "أهلاً بك، تفضل بطرح مشكلتك بالتفصيل وسيقوم أحد المشرفين "
                "بمساعدتك قريباً."
            ),
            color=0x2ECC71,
        )
        embed.set_footer(
            text="يمكن للمشرفين استلام التذكرة أو إغلاقها عبر الأزرار أدناه"
        )
        await channel.send(
            f"{itx.user.mention} تم إنشاء تذكرتك بنجاح.",
            embed=embed,
            view=TicketControl(),
        )
        await itx.response.send_message(
            f"✅ تم فتح تذكرتك: {channel.mention}",
            ephemeral=True,
        )


class RoleSelector(discord.ui.Select):
    def __init__(self, roles):
        options = [
            discord.SelectOption(
                label=role.name,
                value=str(role.id),
                emoji="🏷️",
            )
            for role in roles[:25]
        ]
        super().__init__(
            placeholder="اختر رتبك واهتماماتك...",
            min_values=1,
            max_values=min(len(options), 5),
            options=options,
            custom_id="slct_multi_roles",
        )

    async def callback(self, itx: discord.Interaction):
        added, removed = [], []
        for value in self.values:
            role = itx.guild.get_role(int(value))
            if not role or role >= itx.guild.me.top_role:
                continue
            if role in itx.user.roles:
                await itx.user.remove_roles(role)
                removed.append(role.name)
            else:
                await itx.user.add_roles(role)
                added.append(role.name)

        result = []
        if added:
            result.append(f"➕ مُنحت: **{', '.join(added)}**")
        if removed:
            result.append(f"➖ أُزيلت: **{', '.join(removed)}**")
        await itx.response.send_message(
            "\n".join(result) if result else "لم يتم تغيير أي رتبة.",
            ephemeral=True,
        )


class Engagement(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, mem: discord.Member):
        # 1. إسناد الرتبة التلقائية
        role = discord.utils.get(mem.guild.roles, name="Member")
        if role is not None:
            try:
                await mem.add_roles(role)
            except Exception:
                pass

        # 2. إشعار الترحيب المتقدم
        channel = mem.guild.system_channel
        if channel is not None:
            embed = discord.Embed(
                title=f"مرحباً بك في {mem.guild.name}! 🎉",
                description=(
                    f"أهلاً {mem.mention}، نورت السيرفر!\n"
                    f"• أنت العضو رقم: **#{mem.guild.member_count}**\n"
                    f"• تاريخ إنشاء الحساب: "
                    f"**<t:{int(mem.created_at.timestamp())}:R>**"
                ),
                color=0x3498DB,
            )
            embed.set_thumbnail(url=mem.display_avatar.url)
            await channel.send(embed=embed)

    @app_commands.command(
        name="setup_tickets",
        description="تثبيت لوحة تذاكر الدعم الفني",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_tickets(self, itx: discord.Interaction):
        embed = discord.Embed(
            title="🎫 مركز المساعدة والدعم الفني",
            description=(
                "هل تحتاج إلى استفسار، إبلاغ، أو طلب مساعدة من الإدارة؟\n"
                "اضغط على الزر بالأسفل لفتح قناة خاصة."
            ),
            color=0x3498DB,
        )
        await itx.channel.send(embed=embed, view=TicketLauncher())
        await itx.response.send_message(
            "✅ تم تثبيت اللوحة بنجاح.",
            ephemeral=True,
        )

    @app_commands.command(
        name="setup_roles",
        description="لوحة اختيار الرتب التفاعلية",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_roles(self, itx: discord.Interaction):
        roles = [
            role
            for role in itx.guild.roles
            if (
                not role.is_default()
                and not role.managed
                and role < itx.guild.me.top_role
            )
        ]
        if not roles:
            return await itx.response.send_message(
                "❌ لا توجد رتب متاحة للإسناد تحت رتبة البوت.",
                ephemeral=True,
            )
        view = discord.ui.View(timeout=None)
        view.add_item(RoleSelector(roles))
        embed = discord.Embed(
            title="🎭 اختيار الرتب الذاتية",
            description=(
                "حدد الرتب المناسبة لك من القائمة لتفعيلها أو إزالتها تلقائياً:"
            ),
            color=0x9B59B6,
        )
        await itx.channel.send(embed=embed, view=view)
        await itx.response.send_message(
            "✅ تم إرسال لوحة الرتب.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    bot.add_view(TicketLauncher())
    bot.add_view(TicketControl())
    await bot.add_cog(Engagement(bot))
