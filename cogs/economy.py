import asyncio
import random

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from database import (
    DB_NAME,
    add_xp,
    get_economy_leaderboard,
    get_guild_settings,
    get_or_create_user,
    transfer_balance,
    update_balance,
)


class LiveGiveaway(discord.ui.View):
    def __init__(self, prize: str):
        super().__init__(timeout=None)
        self.prize, self.entries = prize, set()

    @discord.ui.button(
        label="دخول السحب 🎉",
        style=discord.ButtonStyle.success,
        custom_id="btn_live_gw",
    )
    async def enter(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        if itx.user.id in self.entries:
            return await itx.response.send_message(
                "❌ أنت مسجل مسبقاً في هذا السحب!",
                ephemeral=True,
            )
        self.entries.add(itx.user.id)
        await itx.response.send_message(
            f"✅ تم اشتراكك في السحب على: **{self.prize}**",
            ephemeral=True,
        )


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cooldowns = {}

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
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT last_daily FROM users "
                "WHERE user_id = ? AND guild_id = ?",
                (itx.user.id, itx.guild.id),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row and row[0] == today:
                return await itx.response.send_message(
                    "❌ استلمت راتبك اليومي مسبقاً! عد غداً.",
                    ephemeral=True,
                )
            settings = await get_guild_settings(itx.guild.id)
            base_reward = int(settings["settings"].get("daily_amount", 450))
            reward = random.randint(max(1, int(base_reward * 0.8)), max(1, int(base_reward * 1.2)))
            await update_balance(
                itx.user.id,
                itx.guild.id,
                reward,
                "balance",
            )
            await db.execute(
                "UPDATE users SET last_daily = ? "
                "WHERE user_id = ? AND guild_id = ?",
                (today, itx.user.id, itx.guild.id),
            )
            await db.commit()
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
        user = await get_or_create_user(itx.user.id, itx.guild.id)
        if user["balance"] < amount:
            return await itx.response.send_message(
                "❌ رصيد الكاش لا يكفي!",
                ephemeral=True,
            )
        await update_balance(
            itx.user.id,
            itx.guild.id,
            -amount,
            "balance",
        )
        await update_balance(
            itx.user.id,
            itx.guild.id,
            amount,
            "bank",
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
        user = await get_or_create_user(itx.user.id, itx.guild.id)
        if user["bank"] < amount:
            return await itx.response.send_message(
                "❌ رصيد البنك لا يكفي!",
                ephemeral=True,
            )
        await update_balance(
            itx.user.id,
            itx.guild.id,
            -amount,
            "bank",
        )
        await update_balance(
            itx.user.id,
            itx.guild.id,
            amount,
            "balance",
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
            await update_balance(
                target.id,
                itx.guild.id,
                -stolen,
                "balance",
            )
            await update_balance(
                itx.user.id,
                itx.guild.id,
                stolen,
                "balance",
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
        view = LiveGiveaway(prize)
        embed = discord.Embed(
            title="🎁 سحب مؤقت!",
            description=(
                f"الجائزة: **{prize}**\n"
                f"المدة: `{minutes}` دقيقة\n"
                "اضغط بالأسفل للاشتراك!"
            ),
            color=0x9B59B6,
        )
        message = await itx.channel.send(embed=embed, view=view)
        await itx.response.send_message("✅ أُطلق السحب.", ephemeral=True)

        await asyncio.sleep(minutes * 60)
        view.stop()
        if not view.entries:
            return await itx.channel.send(
                f"⚠️ انتهى السحب على **{prize}** دون أي مشتركين."
            )
        winner = itx.guild.get_member(random.choice(list(view.entries)))
        if winner is not None:
            await itx.channel.send(
                f"🎊 مبارك {winner.mention}! فزت بسحب: **{prize}** 🎉"
            )
        await message.edit(view=None)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
