import io
import json
import logging
from urllib.parse import quote

import aiohttp
import discord
from deep_translator import GoogleTranslator
from discord import app_commands
from discord.ext import commands

LOGGER = logging.getLogger("AITools")

# خريطة الأعلام واللغات المدعومة
FLAG_MAP = {
    "🇸🇦": "ar",
    "🇦🇪": "ar",
    "🇪🇬": "ar",
    "🇾🇪": "ar",
    "🇺🇸": "en",
    "🇬🇧": "en",
    "🇫🇷": "fr",
    "🇪🇸": "es",
    "🇩🇪": "de",
    "🇹🇷": "tr",
    "🇯🇵": "ja",
    "🇨🇳": "zh-CN",
    "🇷🇺": "ru",
    "🇰🇷": "ko",
}


class AITools(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session and not self.session.closed:
            await self.session.close()

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self,
        payload: discord.RawReactionActionEvent,
    ):
        """الترجمة اللحظية بمجرد وضع رياكشن علم الدولة"""
        target_lang = FLAG_MAP.get(str(payload.emoji))
        if not target_lang:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
            if not message.content or message.author.bot:
                return

            translated = GoogleTranslator(
                source="auto",
                target=target_lang,
            ).translate(message.content)
            embed = discord.Embed(
                title=f"🌐 الترجمة الفورية ({target_lang.upper()})",
                description=translated,
                color=0x3498DB,
            )
            requester = (
                payload.member.display_name
                if payload.member
                else "عضو"
            )
            embed.set_footer(text=f"طلب: {requester}")
            await channel.send(embed=embed, reference=message)
        except Exception as error:
            print(f"[TRANSLATE_ERR] {error}")

    @app_commands.command(
        name="ask_ai",
        description="طرح سؤال ذكي وتلقي إجابة تحليلية فورية",
    )
    @app_commands.describe(
        question="اكتب سؤالك التقني أو العام هنا",
    )
    async def ask_ai(
        self,
        itx: discord.Interaction,
        question: str,
    ):
        await self.answer_ai(itx, question)

    async def answer_ai(self, itx: discord.Interaction, question: str):
        question = str(question).strip()[:2000]
        await itx.response.defer()
        encoded_question = quote(question, safe="")
        url = (
            f"https://text.pollinations.ai/{encoded_question}"
            "?model=openai"
        )

        try:
            async with self.session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status == 200:
                    answer = await response.text()
                    if len(answer) > 1900:
                        answer = answer[:1900] + "..."
                    embed = discord.Embed(
                        title="🤖 المساعد الذكي",
                        description=answer,
                        color=0x2ECC71,
                    )
                    embed.set_footer(
                        text="مدعوم بمحرك المعالجة العصبية",
                    )
                    await itx.followup.send(embed=embed)
                else:
                    await itx.followup.send(
                        "⚠️ تعذر الاتصال بمحرك الذكاء الاصطناعي حالياً."
                    )
        except Exception as error:
            LOGGER.exception("[AI] فشل طلب الذكاء الاصطناعي: %s", error)
            await itx.followup.send("❌ تعذر إكمال الطلب حالياً. حاول لاحقاً.")

    @app_commands.command(
        name="imagine",
        description="توليد صورة فنية رقمية بالذكاء الاصطناعي",
    )
    @app_commands.describe(
        prompt="وصف الصورة باللغة الإنجليزية لأفضل نتيجة",
    )
    async def imagine(
        self,
        itx: discord.Interaction,
        prompt: str,
    ):
        await itx.response.defer()
        clean_prompt = quote(prompt, safe="")
        image_url = (
            f"https://image.pollinations.ai/prompt/{clean_prompt}"
            "?width=800&height=600&nologo=true"
        )

        embed = discord.Embed(
            title="🎨 توليد الصور بالذكاء الاصطناعي",
            description=f"**الوصف:** {prompt}",
            color=0x9B59B6,
        )
        embed.set_image(url=image_url)
        embed.set_footer(
            text=f"طلب بواسطة: {itx.user.display_name}",
        )
        await itx.followup.send(embed=embed)

    @app_commands.command(
        name="summarize",
        description="تحليل وتلخيص آخر رسائل الروم في نقاط",
    )
    @app_commands.describe(
        limit="عدد الرسائل المراد فحصها (20 - 100)",
    )
    async def summarize(
        self,
        itx: discord.Interaction,
        limit: int = 50,
    ):
        if limit < 20 or limit > 100:
            return await itx.response.send_message(
                "❌ النطاق المسموح به بين 20 و 100 رسالة.",
                ephemeral=True,
            )

        await itx.response.defer()
        history_messages = []
        authors = set()

        async for message in itx.channel.history(limit=limit):
            if message.content and not message.author.bot:
                history_messages.append(
                    f"{message.author.display_name}: {message.content}"
                )
                authors.add(message.author.display_name)

        if len(history_messages) < 5:
            return await itx.followup.send(
                "⚠️ لا توجد رسائل كافية لاستخراج ملخص دقيق."
            )

        history_messages.reverse()
        combined = " \n ".join(history_messages[-15:])

        embed = discord.Embed(
            title="📝 موجز نقاشات الروم الذكي",
            color=0xF39C12,
        )
        embed.add_field(
            name="📊 إحصائيات الجلسة",
            value=(
                f"• الرسائل المفحوصة: `{len(history_messages)}`\n"
                f"• الأعضاء المتفاعلون: `{len(authors)}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="💬 أحدث محاور الحوار",
            value=combined[:950],
            inline=False,
        )
        embed.set_footer(
            text=f"تم استخراجه لـ: {itx.user.display_name}",
        )
        await itx.followup.send(embed=embed)

    @app_commands.command(
        name="transcript",
        description="تصدير سجل رسائل الروم كملف أرشيف نصي",
    )
    @app_commands.describe(
        limit="عدد الرسائل المراد أرشفتها (أقصى حد: 200)",
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def transcript(
        self,
        itx: discord.Interaction,
        limit: int = 100,
    ):
        await itx.response.defer(ephemeral=True)
        limit = min(limit, 200)
        logs = []

        async for message in itx.channel.history(
            limit=limit,
            oldest_first=True,
        ):
            time_string = message.created_at.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            logs.append(
                f"[{time_string}] {message.author} "
                f"({message.author.id}): {message.clean_content}"
            )

        data = "\n".join(logs)
        file = discord.File(
            io.BytesIO(data.encode("utf-8")),
            filename=f"transcript-{itx.channel.name}.txt",
        )
        await itx.followup.send(
            f"📁 تم تصدير سجل الروم بنجاح ({len(logs)} رسالة):",
            file=file,
            ephemeral=True,
        )

    @app_commands.command(
        name="backup_structure",
        description="أخذ نسخة احتياطية كاملة من هيكل السيرفر ورتبه",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def backup_structure(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        guild = itx.guild

        backup_data = {
            "guild_name": guild.name,
            "guild_id": guild.id,
            "roles": [
                {
                    "name": role.name,
                    "permissions": role.permissions.value,
                    "color": str(role.color),
                }
                for role in guild.roles
                if not role.is_default()
            ],
            "categories": [
                {
                    "name": category.name,
                    "position": category.position,
                }
                for category in guild.categories
            ],
            "text_channels": [
                {
                    "name": channel.name,
                    "category": (
                        channel.category.name
                        if channel.category
                        else None
                    ),
                }
                for channel in guild.text_channels
            ],
            "voice_channels": [
                {
                    "name": channel.name,
                    "category": (
                        channel.category.name
                        if channel.category
                        else None
                    ),
                }
                for channel in guild.voice_channels
            ],
        }

        file_bytes = io.BytesIO(
            json.dumps(
                backup_data,
                indent=2,
                ensure_ascii=False,
            ).encode("utf-8")
        )
        discord_file = discord.File(
            file_bytes,
            filename=f"backup_{guild.id}.json",
        )

        embed = discord.Embed(
            title="📦 تم إنشاء النسخة الاحتياطية بنجاح",
            description=(
                f"تم حفظ هيكل: **{guild.name}**\n"
                f"- الرتب: `{len(backup_data['roles'])}`\n"
                f"- الفئات: `{len(backup_data['categories'])}`\n"
                "- القنوات النصية: "
                f"`{len(backup_data['text_channels'])}`\n"
                "- القنوات الصوتية: "
                f"`{len(backup_data['voice_channels'])}`"
            ),
            color=0x1ABC9C,
        )
        await itx.followup.send(
            embed=embed,
            file=discord_file,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AITools(bot))
