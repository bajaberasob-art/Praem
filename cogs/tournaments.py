import random

import discord
from discord import app_commands
from discord.ext import commands


class TournamentEntryView(discord.ui.View):
    def __init__(self, title: str, max_players: int):
        super().__init__(timeout=None)
        self.title, self.max_players = title, max_players
        self.players = []

    @discord.ui.button(
        label="تسجيل اشتراك 🎯",
        style=discord.ButtonStyle.success,
        custom_id="btn_join_tourney",
    )
    async def join(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        if itx.user.id in [player.id for player in self.players]:
            return await itx.response.send_message(
                "❌ أنت مسجل بالفعل في هذه البطولة!",
                ephemeral=True,
            )
        if len(self.players) >= self.max_players:
            return await itx.response.send_message(
                "⚠️ اكتمل العدد الأقصى للمشاركين!",
                ephemeral=True,
            )

        self.players.append(itx.user)
        await itx.response.send_message(
            f"✅ تم تسجيلك بنجاح! ({len(self.players)}/{self.max_players})",
            ephemeral=True,
        )

    @discord.ui.button(
        label="إغلاق وقرعة المواجهات ⚔️",
        style=discord.ButtonStyle.danger,
        custom_id="btn_start_bracket",
    )
    async def generate_bracket(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        if not itx.user.guild_permissions.manage_events:
            return await itx.response.send_message(
                "❌ هذا الإجراء متاح لمنظمي الفعاليات فقط.",
                ephemeral=True,
            )
        if len(self.players) < 2:
            return await itx.response.send_message(
                "⚠️ يجب تسجيل لاعبين على الأقل لبدء القرعة!",
                ephemeral=True,
            )

        self.stop()
        random.shuffle(self.players)
        matches = []
        for index in range(0, len(self.players), 2):
            player_one = self.players[index].mention
            player_two = (
                self.players[index + 1].mention
                if index + 1 < len(self.players)
                else "تأهل تلقائي (BYE)"
            )
            matches.append(
                f"**المباراة {len(matches) + 1}:** "
                f"{player_one} 🆚 {player_two}"
            )

        embed = discord.Embed(
            title=f"🏆 شجرة مواجهات بطولة: {self.title}",
            description="\n\n".join(matches),
            color=0xF1C40F,
        )
        await itx.channel.send(embed=embed)
        await itx.message.edit(view=None)


class Tournaments(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.team_scores: dict[str, int] = {}

    @app_commands.command(
        name="scrim_split",
        description="توزيع لاعبي الروم الصوتي بالتساوي بين رومين",
    )
    @app_commands.checks.has_permissions(move_members=True)
    async def scrim_split(
        self,
        itx: discord.Interaction,
        target_voice: discord.VoiceChannel,
    ):
        if not itx.user.voice or not itx.user.voice.channel:
            return await itx.response.send_message(
                "❌ يجب أن تتواجد في روم صوتي أولاً!",
                ephemeral=True,
            )

        source = itx.user.voice.channel
        players = [member for member in source.members if not member.bot]
        if len(players) < 2:
            return await itx.response.send_message(
                "⚠️ لا يوجد عدد كافٍ لعمل قرعة.",
                ephemeral=True,
            )

        await itx.response.defer()
        random.shuffle(players)
        midpoint = len(players) // 2
        team_a, team_b = players[:midpoint], players[midpoint:]

        for member in team_b:
            try:
                await member.move_to(
                    target_voice,
                    reason="Scrims Balancing",
                )
            except discord.HTTPException:
                pass

        embed = discord.Embed(
            title="⚔️ قرعة السكريمات المتوازنة",
            color=0xE74C3C,
        )
        embed.add_field(
            name=f"🔴 الفريق 1 ({source.name})",
            value="\n".join(member.mention for member in team_a) or "فارغ",
            inline=False,
        )
        embed.add_field(
            name=f"🔵 الفريق 2 ({target_voice.name})",
            value="\n".join(member.mention for member in team_b) or "فارغ",
            inline=False,
        )
        await itx.followup.send(embed=embed)

    @app_commands.command(
        name="scrim_teams",
        description="تقسيم لاعبي الروم إلى فرق محددة (سولو، ديو، سكواد)",
    )
    @app_commands.describe(
        size="حجم كل فريق (2 = ديو, 3 = تريو, 4 = سكواد)",
    )
    async def scrim_teams(
        self,
        itx: discord.Interaction,
        size: int,
    ):
        if size < 2:
            return await itx.response.send_message(
                "❌ حجم الفريق يجب أن يكون شخصين على الأقل.",
                ephemeral=True,
            )
        if not itx.user.voice or not itx.user.voice.channel:
            return await itx.response.send_message(
                "❌ ادخل روم صوتي أولاً!",
                ephemeral=True,
            )

        players = [
            member
            for member in itx.user.voice.channel.members
            if not member.bot
        ]
        if len(players) < size:
            return await itx.response.send_message(
                f"⚠️ عدد اللاعبين أقل من حجم الفريق ({size}).",
                ephemeral=True,
            )

        random.shuffle(players)
        teams = [
            players[index : index + size]
            for index in range(0, len(players), size)
        ]

        embed = discord.Embed(
            title=f"🎮 تشكيل الفرق التكتيكية (أحجام {size})",
            color=0x3498DB,
        )
        for index, squad in enumerate(teams, 1):
            embed.add_field(
                name=f"فريق {index} 🛡️",
                value="\n".join(member.mention for member in squad),
                inline=True,
            )
        await itx.response.send_message(embed=embed)

    @app_commands.command(
        name="map_randomizer",
        description="اختيار خريطة عشوائية لمباراة تكتيكية",
    )
    @app_commands.describe(
        maps_list=(
            "اكتب الخرائط مفصولة بفاصلة "
            "(مثال: الشوتر, الفيراري, الميناء)"
        ),
    )
    async def map_randomizer(
        self,
        itx: discord.Interaction,
        maps_list: str,
    ):
        maps = [item.strip() for item in maps_list.split(",") if item.strip()]
        if not maps:
            return await itx.response.send_message(
                "❌ أدخل قائمة خرائط صالحة.",
                ephemeral=True,
            )
        chosen = random.choice(maps)
        embed = discord.Embed(
            title="🗺️ قرعة الخرائط العشوائية",
            description=f"الخريطة المختارة للمواجهة:\n# **{chosen}**",
            color=0x2ECC71,
        )
        await itx.response.send_message(embed=embed)

    @app_commands.command(
        name="tournament_open",
        description="فتح باب التسجيل لبطولة رسمية وتوليد الجدول",
    )
    @app_commands.describe(
        title="اسم البطولة",
        max_players="الحد الأقصى للمشاركين",
    )
    @app_commands.checks.has_permissions(manage_events=True)
    async def tournament_open(
        self,
        itx: discord.Interaction,
        title: str,
        max_players: int = 16,
    ):
        embed = discord.Embed(
            title=f"🏆 إعلان بطولة: {title}",
            description=(
                f"المقاعد المتاحة: `{max_players}` لاعب\n"
                "اضغط على الزر بالأسفل للاشتراك فوراً!"
            ),
            color=0xF1C40F,
        )
        embed.set_footer(
            text="سيقوم المنظم بإنشاء جدول المواجهات عند اكتمال العدد",
        )
        await itx.channel.send(
            embed=embed,
            view=TournamentEntryView(title, max_players),
        )
        await itx.response.send_message(
            "✅ تم فتح التسجيل للبطولة.",
            ephemeral=True,
        )

    @app_commands.command(
        name="match_record",
        description="توثيق نتيجة وتوزيع نقاط الفوز",
    )
    @app_commands.checks.has_permissions(manage_events=True)
    async def match_record(
        self,
        itx: discord.Interaction,
        winner_team: str,
        loser_team: str,
        score: str,
    ):
        self.team_scores[winner_team] = (
            self.team_scores.get(winner_team, 0) + 3
        )
        embed = discord.Embed(
            title="🏆 توثيق نتيجة مباراة رسمية",
            color=0x2ECC71,
        )
        embed.add_field(
            name="الفائز 🥇 (+3 نقاط)",
            value=f"**{winner_team}**",
            inline=True,
        )
        embed.add_field(
            name="النتيجة 📊",
            value=f"`{score}`",
            inline=True,
        )
        embed.add_field(
            name="الخاسر 🥈",
            value=f"**{loser_team}**",
            inline=True,
        )
        embed.set_footer(
            text=f"وثّق النتيجة: {itx.user.display_name}",
        )
        await itx.channel.send(embed=embed)
        await itx.response.send_message(
            "✅ تم تسجيل النتيجة وتحديث النقاط.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Tournaments(bot))
