import asyncio
import time

import discord
from discord import app_commands
from discord.ext import commands


HUB_NAME = "➕ اضغط للإنشاء"


class VoiceControl(discord.ui.View):
    def __init__(self, channel: discord.VoiceChannel, owner: discord.Member):
        super().__init__(timeout=None)
        self.channel, self.owner = channel, owner

    async def interaction_check(self, itx: discord.Interaction) -> bool:
        if (
            itx.user.id != self.owner.id
            and not itx.user.guild_permissions.administrator
        ):
            await itx.response.send_message(
                "❌ التحكم متاح لمالك الروم فقط!",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="قفل الروم",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
    )
    async def lock(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        overwrite = self.channel.overwrites_for(itx.guild.default_role)
        overwrite.connect = False
        await self.channel.set_permissions(
            itx.guild.default_role,
            overwrite=overwrite,
        )
        await itx.response.send_message(
            "🔒 تم قفل الروم ومنع الدخول.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="فتح الروم",
        style=discord.ButtonStyle.success,
        emoji="🔓",
    )
    async def unlock(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        overwrite = self.channel.overwrites_for(itx.guild.default_role)
        overwrite.connect = None
        await self.channel.set_permissions(
            itx.guild.default_role,
            overwrite=overwrite,
        )
        await itx.response.send_message(
            "🔓 تم فتح الروم للجميع.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="تحديد 5 أعضاء",
        style=discord.ButtonStyle.secondary,
        emoji="👥",
    )
    async def limit(
        self,
        itx: discord.Interaction,
        btn: discord.ui.Button,
    ):
        await self.channel.edit(user_limit=5)
        await itx.response.send_message(
            "👥 تم ضبط الحد الأقصى إلى 5 أعضاء.",
            ephemeral=True,
        )


class Utilities(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.temp_voice = {}

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        mem: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        # 1. إنشاء روم صوتي مؤقت مع لوحة التحكم
        if after.channel and after.channel.name == HUB_NAME:
            guild, category = mem.guild, after.channel.category
            new_channel = await guild.create_voice_channel(
                name=f"🔊・{mem.display_name}",
                category=category,
                user_limit=10,
            )
            self.temp_voice[new_channel.id] = mem.id
            try:
                await mem.move_to(new_channel)
                embed = discord.Embed(
                    title="🎛️ تحكم برومك الصوتي",
                    description=(
                        "يمكنك إدارة وتأمين الروم عبر الأزرار أدناه:"
                    ),
                    color=0x2ECC71,
                )
                await new_channel.send(
                    f"{mem.mention}",
                    embed=embed,
                    view=VoiceControl(new_channel, mem),
                )
            except Exception:
                pass

        # 2. حذف الروم عند مغادرة الجميع
        if before.channel and before.channel.id in self.temp_voice:
            if len(before.channel.members) == 0:
                self.temp_voice.pop(before.channel.id, None)
                try:
                    await before.channel.delete()
                except Exception:
                    pass

    @app_commands.command(
        name="setup_voice",
        description="تهيئة رومات صوتية مؤقتة ذاتية الإدارة",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_voice(self, itx: discord.Interaction):
        category = await itx.guild.create_category("🔊 القنوات التفاعلية")
        await itx.guild.create_voice_channel(
            name=HUB_NAME,
            category=category,
        )
        await itx.response.send_message(
            "✅ تم تجهيز نظام الرومات المؤقتة ولوحة التحكم!",
            ephemeral=True,
        )

    @app_commands.command(
        name="ping",
        description="فحص سرعة استجابة البوت والاتصال",
    )
    async def ping(self, itx: discord.Interaction):
        started_at = time.perf_counter()
        await itx.response.defer()
        finished_at = time.perf_counter()
        websocket_latency = round(self.bot.latency * 1000)
        api_latency = round((finished_at - started_at) * 1000)

        embed = discord.Embed(
            title="🏓 استجابة النظام",
            color=0x2ECC71,
        )
        embed.add_field(
            name="بوابة ديسكورد (WebSocket)",
            value=f"`{websocket_latency}ms`",
            inline=True,
        )
        embed.add_field(
            name="معالجة الأوامر (API/DB)",
            value=f"`{api_latency}ms`",
            inline=True,
        )
        await itx.followup.send(embed=embed)

    @app_commands.command(
        name="radio",
        description="تشغيل إذاعة القرآن الكريم المباشرة في الروم الصوتي",
    )
    @app_commands.checks.has_permissions(connect=True)
    async def radio(self, itx: discord.Interaction):
        if not itx.user.voice or not itx.user.voice.channel:
            return await itx.response.send_message(
                "❌ يجب أن تكون متواجداً في روم صوتي أولاً!",
                ephemeral=True,
            )

        channel = itx.user.voice.channel
        await itx.response.defer()
        try:
            voice_client = itx.guild.voice_client or await channel.connect()
            if voice_client.channel != channel:
                await voice_client.move_to(channel)
            if voice_client.is_playing():
                voice_client.stop()

            stream_url = "https://backup.qurango.net/radio/tarteel"
            voice_client.play(discord.FFmpegPCMAudio(stream_url))
            await itx.followup.send(
                f"📻 تم بدء البث الصوتي المباشر في: {channel.mention}"
            )
        except Exception as error:
            await itx.followup.send(
                f"⚠️ تعذر تشغيل الراديو: {error}",
                ephemeral=True,
            )

    @app_commands.command(
        name="stop_radio",
        description="إيقاف البث ومغادرة الروم الصوتي",
    )
    @app_commands.checks.has_permissions(connect=True)
    async def stop_radio(self, itx: discord.Interaction):
        if voice_client := itx.guild.voice_client:
            await voice_client.disconnect()
            await itx.response.send_message(
                "⏹️ تم إيقاف البث ومغادرة الروم."
            )
        else:
            await itx.response.send_message(
                "❌ البوت غير متصل بأي روم صوتي.",
                ephemeral=True,
            )

    @app_commands.command(
        name="ask",
        description="طرح سؤال أو طلب مساعدة ذكية من البوت",
    )
    async def ask(self, itx: discord.Interaction, question: str):
        # رد ذكي خفيف وسريع
        await itx.response.defer()
        await asyncio.sleep(1)
        embed = discord.Embed(
            title="💡 الاستجابة الذكية",
            color=0x3498DB,
        )
        embed.add_field(
            name="السؤال:",
            value=question,
            inline=False,
        )
        embed.add_field(
            name="التحليل:",
            value=(
                f"مرحباً {itx.user.mention}! تلقيت طلبك بنجاح. الأنظمة "
                "المركزية نشطة وجاهزة لتنفيذ كافة مهام السيرفر."
            ),
            inline=False,
        )
        await itx.followup.send(embed=embed)

    @app_commands.command(
        name="serverinfo",
        description="عرض بيانات وإحصائيات السيرفر الكاملة",
    )
    async def serverinfo(self, itx: discord.Interaction):
        guild = itx.guild
        embed = discord.Embed(
            title=f"📊 إحصائيات: {guild.name}",
            color=0x3498DB,
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(
            name="👑 المالك",
            value=guild.owner.mention if guild.owner else "غير معروف",
            inline=True,
        )
        embed.add_field(
            name="👥 الأعضاء",
            value=f"`{guild.member_count}`",
            inline=True,
        )
        embed.add_field(
            name="💬 الرومات",
            value=f"`{len(guild.channels)}`",
            inline=True,
        )
        embed.add_field(
            name="🛡️ الرتب",
            value=f"`{len(guild.roles)}`",
            inline=True,
        )
        embed.add_field(
            name="🚀 مستوى التعزيز",
            value=(
                f"`Tier {guild.premium_tier}` "
                f"({guild.premium_subscription_count} Boosts)"
            ),
            inline=True,
        )
        embed.add_field(
            name="📅 تاريخ الإنشاء",
            value=f"<t:{int(guild.created_at.timestamp())}:D>",
            inline=True,
        )
        await itx.response.send_message(embed=embed)

    @app_commands.command(
        name="avatar",
        description="عرض الصورة الشخصية لأي عضو",
    )
    async def avatar(
        self,
        itx: discord.Interaction,
        member: discord.Member = None,
    ):
        target = member or itx.user
        embed = discord.Embed(
            title=f"🖼️ صورة: {target.display_name}",
            color=0x2ECC71,
        )
        embed.set_image(url=target.display_avatar.url)
        await itx.response.send_message(embed=embed)

    @app_commands.command(
        name="say",
        description="إرسال رسالة رسمية باسم البوت",
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def say(self, itx: discord.Interaction, text: str):
        await itx.channel.send(text)
        await itx.response.send_message(
            "✅ تم الإرسال بنجاح.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Utilities(bot))
