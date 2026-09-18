import datetime
import random

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import (
    add_xp,
    get_economy_leaderboard,
    get_guild_settings,
    get_or_create_user,
    claim_daily_reward,
    add_giveaway_entry,
    cancel_giveaway,
    complete_giveaway,
    create_giveaway,
    get_due_giveaways,
    get_giveaway_entries,
    get_open_giveaways,
    set_giveaway_message,
    transfer_balance,
    move_balance,
)


class LiveGiveaway(discord.ui.View):
    def __init__(self, prize: str, giveaway_id: int):
        super().__init__(timeout=None)
        self.prize = prize
        self.giveaway_id = int(giveaway_id)
        button = discord.ui.Button(
            label="دخول السحب 🎉",
            style=discord.ButtonStyle.success,
            custom_id=f"giveaway:enter:{self.giveaway_id}",
        )
        button.callback = self.enter
        self.add_item(button)

    async def enter(self, itx: discord.Interaction):
        if not await add_giveaway_entry(self.giveaway_id, itx.user.id):
            return await itx.response.send_message(
                "❌ أنت مسجل مسبقاً في هذا السحب!",
                ephemeral=True,
            )
        await itx.response.send_message(
            f"✅ تم اشتراكك في السحب على: **{self.prize}**",
            ephemeral=True,
        )


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cooldowns = {}
        self.giveaway_task.start()

    async def cog_load(self):
        for giveaway in await get_open_giveaways():
            self.bot.add_view(
                LiveGiveaway(giveaway["prize"], giveaway["id"]),
                message_id=int(giveaway["message_id"]),
            )

    def cog_unload(self):
        self.giveaway_task.cancel()

    @tasks.loop(seconds=10)
    async def giveaway_task(self):
        for giveaway in await get_due_giveaways():
            channel = self.bot.get_channel(int(giveaway["channel_id"]))
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(int(giveaway["channel_id"]))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    continue
            entries = await get_giveaway_entries(int(giveaway["id"]))
            try:
                if entries:
                    winner_id = random.choice(entries)
                    winner = channel.guild.get_member(winner_id)
                    mention = winner.mention if winner else f"<@{winner_id}>"
                    await channel.send(
                        f"🎊 مبارك {mention}! فزت بسحب: **{giveaway['prize']}** 🎉"
                    )
                else:
                    await channel.send(
                        f"⚠️ انتهى السحب على **{giveaway['prize']}** دون أي مشتركين."
                    )
                try:
                    message = await channel.fetch_message(int(giveaway["message_id"]))
                    await message.edit(view=None)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            except (discord.Forbidden, discord.HTTPException):
                continue
            await complete_giveaway(int(giveaway["id"]))

    @giveaway_task.before_loop
    async def before_giveaway_task(self):
        await self.bot.wait_until_ready()

    def check_cd(self, key: str, sec: int) -> int:
        now = int(discord.utils.utcnow().timestamp())
        left = sec - (now - self.cooldowns.get(key, 0))
        if left > 0:
            return left
        self.cooldowns[key] = now
        return 0

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author.bot or not msg.guild:
            return
        if self.check_cd(f"xp_{msg.author.id}", 60) > 0:
            return

        leveled_up, level = await add_xp(
            msg.author.id,
            msg.guild.id,
            random.randint(15, 25),
        )
        if leveled_up:
            await msg.channel.send(
                f"🎊 مبارك {msg.author.mention}! ارتقيت إلى المستوى "
                f"**{level}**! 🚀",
                delete_after=8,
            )

    @app_commands.command(name="profile", description="عرض الملف المالي والشخصي")
    async def profile(
        self,
        itx: discord.Interaction,
        member: discord.Member = None,
    ):
        target = member or itx.user
        user = await get_or_create_user(target.id, itx.guild.id)
        required_xp = user["level"] * 120
        embed = discord.Embed(
            title=f"💳 بطاقة: {target.display_name}",
            color=0x2ECC71,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(
            name="المستوى 🎖️",
            value=f"**{user['level']}**",
            inline=True,
        )
        embed.add_field(
            name="الخبرة ⚡",
            value=f"`{user['xp']}/{required_xp}`",
            inline=True,
        )
        embed.add_field(
            name="الكاش 💵",
            value=f"`{user['balance']:,}`",
            inline=True,
        )
        embed.add_field(
            name="البنك 🏦",
            value=f"`{user['bank']:,}`",
            inline=True,
        )
        embed.add_field(
            name="الإجمالي 💎",
            value=f"`{user['balance'] + user['bank']:,}`",
            inline=True,
        )
        await itx.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="المكافأة اليومية")
    async def daily(self, itx: discord.Interaction):
        today = discord.utils.utcnow().strftime("%Y-%m-%d")
        settings = await get_guild_settings(itx.guild.id)
        base_reward = int(settings["settings"].get("daily_amount", 450))
        reward = random.randint(
            max(1, int(base_reward * 0.8)),
            max(1, int(base_reward * 1.2)),
        )
        if not await claim_daily_reward(
            itx.user.id,
            itx.guild.id,
            today,
            reward,
        ):
            return await itx.response.send_message(
                "❌ استلمت راتبك اليومي مسبقاً! عد غداً.",
                ephemeral=True,
            )
        await itx.response.send_message(
            f"💰 استلمت راتبك اليومي بقيمة **{reward:,}** عملة!"
        )

    @app_commands.command(name="work", description="العمل وكسب المال")
    async def work(self, itx: discord.Interaction):
        left = self.check_cd(f"work_{itx.user.id}", 300)
        if left:
            return await itx.response.send_message(
                f"⏳ أنت متعب، يمكنك العمل مجدداً بعد "
                f"`{left // 60}د {left % 60}ث`.",
                ephemeral=True,
            )
        earned = random.randint(80, 250)
        await update_balance(
            itx.user.id,
            itx.guild.id,
            earned,
            "balance",
        )
        await itx.response.send_message(
            f"💼 أتممت عملاً شاقاً وحصلت على **{earned:,}** عملة نقدية."
        )

    @app_commands.command(name="pay", description="تحويل كاش إلى عضو آخر")
    async def pay(
        self,
        itx: discord.Interaction,
        target: discord.Member,
        amount: int,
    ):
        if target.bot or target.id == itx.user.id or amount <= 0:
            return await itx.response.send_message(
                "❌ اختر عضواً صالحاً وأدخل مبلغاً أكبر من صفر.",
                ephemeral=True,
            )
        if not await transfer_balance(itx.guild.id, itx.user.id, target.id, amount):
            return await itx.response.send_message(
                "❌ لا يملك رصيدك النقدي ما يكفي لإتمام التحويل.",
                ephemeral=True,
            )
        await itx.response.send_message(
            f"💸 تم تحويل **{amount:,}** عملة إلى {target.mention}.",
        )

    @app_commands.command(name="leaderboard", description="عرض المتصدرين في اقتصاد السيرفر")
    async def leaderboard(self, itx: discord.Interaction):
        rows = await get_economy_leaderboard(itx.guild.id, 10)
        if not rows:
            return await itx.response.send_message(
                "لا توجد حسابات اقتصادية بعد.",
                ephemeral=True,
            )
        lines = []
        for index, row in enumerate(rows, 1):
            member = itx.guild.get_member(int(row["user_id"]))
            name = member.display_name if member else f"عضو {row['user_id']}"
            lines.append(
                f"**{index}.** {name} — `{int(row['total']):,}` عملة "
                f"(مستوى {int(row['level'])})"
            )
        embed = discord.Embed(
            title="🏆 لوحة المتصدرين الاقتصادية",
            description="\n".join(lines),
            color=0xF1C40F,
        )
        await itx.response.send_message(embed=embed)

    @app_commands.command(
        name="deposit",
        description="إيداع أموال في حسابك البنكي",
    )
    async def deposit(self, itx: discord.Interaction, amount: int):
        if amount <= 0:
            return await itx.response.send_message(
                "❌ أدخل رقماً صالحاً.",
                ephemeral=True,
            )
        if not await move_balance(
            itx.user.id,
            itx.guild.id,
            amount,
            "balance",
            "bank",
        ):
            return await itx.response.send_message(
                "❌ رصيد الكاش لا يكفي!",
                ephemeral=True,
            )
        await itx.response.send_message(
            f"🏦 تم إيداع **{amount:,}** عملة في البنك بأمان."
        )

    @app_commands.command(name="withdraw", description="سحب أموال من البنك")
    async def withdraw(self, itx: discord.Interaction, amount: int):
        if amount <= 0:
            return await itx.response.send_message(
                "❌ أدخل رقماً صالحاً.",
                ephemeral=True,
            )
        if not await move_balance(
            itx.user.id,
            itx.guild.id,
            amount,
            "bank",
            "balance",
        ):
            return await itx.response.send_message(
                "❌ رصيد البنك لا يكفي!",
                ephemeral=True,
            )
        await itx.response.send_message(
            f"💵 تم سحب **{amount:,}** عملة كاش إلى محفظتك."
        )

    @app_commands.command(
        name="rob",
        description="محاولة سرقة كاش عضو آخر (مخاطرة عالية)",
    )
    async def rob(self, itx: discord.Interaction, target: discord.Member):
        if target.id == itx.user.id or target.bot:
            return await itx.response.send_message(
                "❌ لا يمكنك استهداف هذا الحساب.",
                ephemeral=True,
            )
        left = self.check_cd(f"rob_{itx.user.id}", 600)
        if left:
            return await itx.response.send_message(
                f"🚨 الشرطة تلاحقك! انتظر `{left // 60}د {left % 60}ث`.",
                ephemeral=True,
            )

        target_user = await get_or_create_user(target.id, itx.guild.id)
        if target_user["balance"] < 100:
            return await itx.response.send_message(
                f"⚠️ {target.mention} لا يملك ما يكفي من الكاش للسرقة!",
                ephemeral=True,
            )

        if random.random() < 0.45:
            stolen = int(target_user["balance"] * random.uniform(0.2, 0.5))
            if not await transfer_balance(
                itx.guild.id,
                target.id,
                itx.user.id,
                stolen,
            ):
                return await itx.response.send_message(
                    "⚠️ تغيّر رصيد الهدف قبل إتمام العملية؛ حاول مجدداً.",
                    ephemeral=True,
                )
            await itx.response.send_message(
                f"🥷 نجحت بالسطو على {target.mention} وسرقت "
                f"**{stolen:,}** عملة!"
            )
        else:
            robber = await get_or_create_user(itx.user.id, itx.guild.id)
            penalty = min(200, robber["balance"])
            await update_balance(
                itx.user.id,
                itx.guild.id,
                -penalty,
                "balance",
            )
            await itx.response.send_message(
                f"🚔 كشفتك الشرطة! تم تغريمك **{penalty:,}** عملة كاش وتعويضها."
            )

    @app_commands.command(
        name="giveaway",
        description="إطلاق سحب مؤقت بالدقائق",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def giveaway(
        self,
        itx: discord.Interaction,
        minutes: int,
        prize: str,
    ):
        if minutes < 1:
            return await itx.response.send_message(
                "❌ المدة دقيقة على الأقل.",
                ephemeral=True,
            )
        ends_at = (
            discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
        ).strftime("%Y-%m-%d %H:%M:%S")
        giveaway_id = await create_giveaway(
            itx.guild.id,
            itx.channel.id,
            prize,
            ends_at,
            itx.user.id,
        )
        view = LiveGiveaway(prize, giveaway_id)
        embed = discord.Embed(
            title="🎁 سحب مؤقت!",
            description=(
                f"الجائزة: **{prize}**\n"
                f"المدة: `{minutes}` دقيقة\n"
                "اضغط بالأسفل للاشتراك!"
            ),
            color=0x9B59B6,
        )
        try:
            message = await itx.channel.send(embed=embed, view=view)
        except (discord.Forbidden, discord.HTTPException):
            await cancel_giveaway(giveaway_id)
            raise
        await set_giveaway_message(giveaway_id, message.id)
        self.bot.add_view(view, message_id=message.id)
        await itx.response.send_message("✅ أُطلق السحب.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
