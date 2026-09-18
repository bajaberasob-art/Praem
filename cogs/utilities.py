import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from database import (
    get_auto_responders,
    get_command_controls,
    get_guild_settings,
    get_shortcuts,
    delete_auto_responder,
    record_auto_responder_execution,
    save_auto_responder,
    save_command_control,
    save_shortcut,
)


HUB_NAME = "➕ اضغط للإنشاء"
LOGGER = logging.getLogger("UtilitiesOrchestrator")
MATCH_TYPES = {"exact", "contains", "regex"}
SHORTCUT_TYPES = {"command", "announcement"}


async def dynamic_prefix(
    bot: commands.Bot,
    message: discord.Message,
) -> list[str]:
    """Resolve mentions plus the guild prefix from the shared settings cache."""
    prefix = "!"
    if message.guild is not None:
        try:
            snapshot = await get_guild_settings(message.guild.id)
            configured = snapshot["settings"].get("prefix")
            if isinstance(configured, str) and configured.strip():
                prefix = configured.strip()[:5]
        except Exception:
            LOGGER.exception("[PREFIX] تعذر قراءة بادئة السيرفر %s", message.guild.id)
    return commands.when_mentioned_or(prefix)(bot, message)


class CommandIntercepted(commands.CheckFailure):
    """A command was intentionally blocked by a guild policy."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class TokenBucket:
    tokens: float
    updated_at: float


class ShortcutInteractionResponse:
    def __init__(self, interaction: "ShortcutInteraction"):
        self.interaction = interaction
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def defer(self, **kwargs):
        self._done = True

    async def send_message(self, content=None, **kwargs):
        self._done = True
        await self.interaction.channel.send(content, **kwargs)


class ShortcutFollowup:
    def __init__(self, interaction: "ShortcutInteraction"):
        self.interaction = interaction

    async def send(self, content=None, **kwargs):
        return await self.interaction.channel.send(content, **kwargs)


class ShortcutInteraction:
    """Small interaction adapter for no-argument slash command shortcuts."""

    def __init__(self, message: discord.Message):
        self.message = message
        self.user = message.author
        self.guild = message.guild
        self.channel = message.channel
        self.client = message._state._get_client() if getattr(message, "_state", None) else None
        self.response = ShortcutInteractionResponse(self)
        self.followup = ShortcutFollowup(self)


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
        self.auto_responders: dict[int, list[dict[str, Any]]] = {}
        self.shortcuts: dict[int, list[dict[str, Any]]] = {}
        self.command_controls: dict[int, dict[str, dict[str, Any]]] = {}
        self._cooldowns: dict[tuple[int, int, int], TokenBucket] = {}
        self._check_registered = False
        self._original_tree_check = getattr(self.bot.tree, "interaction_check", None)
        self.bot.tree.interaction_check = self.app_command_interceptor
        self.bot.add_check(self.command_interceptor)
        self._check_registered = True

    async def cog_unload(self):
        if self._check_registered:
            self.bot.remove_check(self.command_interceptor)
            self._check_registered = False
        if self._original_tree_check is not None:
            self.bot.tree.interaction_check = self._original_tree_check

    async def get_guild_commands_status(self, guild_id: int) -> dict[str, Any]:
        """Return command policy state merged with the commands currently loaded."""
        guild_id = int(guild_id)
        controls = await get_command_controls(guild_id)
        self.command_controls[guild_id] = controls
        snapshot = await get_guild_settings(guild_id)
        known = {}
        for command in self.bot.commands:
            if command.hidden:
                continue
            known[command.qualified_name] = {
                "command_name": command.qualified_name,
                "cog": getattr(command, "cog_name", None) or "Commands",
                "enabled": True,
                "allowed_roles": [],
                "configured": False,
                "aliases": list(command.aliases),
            }
        for command in self.bot.tree.walk_commands():
            if getattr(command, "hidden", False):
                continue
            binding = getattr(command, "binding", None)
            known.setdefault(
                command.qualified_name,
                {
                    "command_name": command.qualified_name,
                    "cog": binding.__class__.__name__ if binding else "Slash Commands",
                    "enabled": True,
                    "allowed_roles": [],
                    "configured": False,
                    "aliases": [],
                },
            )
        for name, control in controls.items():
            item = known.setdefault(
                name,
                {
                    "command_name": name,
                    "cog": "Configured",
                    "enabled": True,
                    "allowed_roles": [],
                    "configured": False,
                    "aliases": [],
                },
            )
            item.update(
                enabled=bool(control["enabled"]),
                allowed_roles=list(control["allowed_roles"]),
                configured=True,
                updated_at=control.get("updated_at"),
            )
        return {
            "guild_id": str(guild_id),
            "prefix": snapshot["settings"].get("prefix", "!"),
            "commands": sorted(known.values(), key=lambda item: item["command_name"]),
        }

    async def toggle_command(
        self,
        guild_id: int,
        command_name: str,
        enabled: bool,
        allowed_roles: list[int | str] | None = None,
    ) -> dict[str, Any]:
        """Persist and publish a command's enabled/role policy."""
        name = str(command_name).strip().lower()
        if not name or len(name) > 100:
            raise ValueError("command_name must be a non-empty command name")
        roles = [str(role_id) for role_id in (allowed_roles or []) if str(role_id).isdigit()]
        if len(roles) > 25:
            raise ValueError("allowed_roles cannot contain more than 25 roles")
        result = await save_command_control(guild_id, name, bool(enabled), roles)
        self.command_controls.setdefault(int(guild_id), {})[name] = result
        return result

    async def sync_auto_responders(self, guild_id: int) -> dict[str, int]:
        """Refresh the in-memory trigger and shortcut registries for one guild."""
        guild_id = int(guild_id)
        responders = await get_auto_responders(guild_id)
        valid = []
        for responder in responders:
            if responder["match_type"] not in MATCH_TYPES:
                LOGGER.warning("[AUTORESPONDER] نوع مطابقة غير معروف: %s", responder)
                continue
            if responder["match_type"] == "regex":
                try:
                    responder["_compiled"] = re.compile(
                        responder["trigger"], re.IGNORECASE
                    )
                except re.error:
                    LOGGER.warning(
                        "[AUTORESPONDER] Regex غير صالح في السيرفر %s: %s",
                        guild_id,
                        responder["trigger"],
                    )
                    continue
            valid.append(responder)
        self.auto_responders[guild_id] = valid
        self.shortcuts[guild_id] = await get_shortcuts(guild_id)
        self._prune_buckets(guild_id)
        return {
            "responders": len(valid),
            "shortcuts": len(self.shortcuts[guild_id]),
        }

    async def add_auto_responder(
        self,
        guild_id: int,
        trigger: str,
        match_type: str,
        response: str,
        *,
        enabled: bool = True,
        cooldown_seconds: float = 5.0,
        bucket_capacity: int = 1,
        channel_id: int | str | None = None,
    ) -> dict[str, Any]:
        """Management helper for creating a trigger without touching SQL."""
        match_type = str(match_type).strip().lower()
        trigger = str(trigger).strip()
        if match_type not in MATCH_TYPES:
            raise ValueError(f"match_type must be one of {sorted(MATCH_TYPES)}")
        if not trigger or len(trigger) > 500:
            raise ValueError("trigger must contain 1-500 characters")
        if match_type == "regex":
            re.compile(trigger, re.IGNORECASE)
        if not str(response).strip() or len(str(response)) > 2000:
            raise ValueError("response must contain 1-2000 characters")
        item = await save_auto_responder(
            guild_id,
            trigger,
            match_type,
            response,
            enabled=enabled,
            cooldown_seconds=cooldown_seconds,
            bucket_capacity=bucket_capacity,
            channel_id=channel_id,
        )
        await self.sync_auto_responders(guild_id)
        return item

    async def delete_auto_responder(self, guild_id: int, rule_id: int) -> bool:
        deleted = await delete_auto_responder(guild_id, rule_id)
        if deleted:
            await self.sync_auto_responders(guild_id)
        return deleted

    async def add_shortcut(
        self,
        guild_id: int,
        trigger: str,
        target_type: str,
        *,
        target: str = "",
        announcement: str = "",
        enabled: bool = True,
    ) -> dict[str, Any]:
        target_type = str(target_type).strip().lower()
        trigger = str(trigger).strip()
        if target_type not in SHORTCUT_TYPES:
            raise ValueError(f"target_type must be one of {sorted(SHORTCUT_TYPES)}")
        if not trigger or len(trigger) > 100:
            raise ValueError("shortcut trigger must contain 1-100 characters")
        if target_type == "command" and not str(target).strip():
            raise ValueError("command shortcuts need a target command")
        if target_type == "announcement" and not str(announcement).strip():
            raise ValueError("announcement shortcuts need announcement text")
        item = await save_shortcut(
            guild_id,
            trigger,
            target_type,
            target=target,
            announcement=announcement,
            enabled=enabled,
        )
        await self.sync_auto_responders(guild_id)
        return item

    async def command_interceptor(self, ctx: commands.Context) -> bool:
        """Apply the guild command matrix before a prefix command is invoked."""
        if ctx.guild is None or ctx.command is None:
            return True
        guild_id = int(ctx.guild.id)
        controls = self.command_controls.get(guild_id)
        if controls is None:
            controls = await get_command_controls(guild_id)
            self.command_controls[guild_id] = controls
        control = controls.get(ctx.command.qualified_name.lower())
        if not control:
            return True
        member = ctx.author
        permissions = getattr(member, "guild_permissions", None)
        if permissions and getattr(permissions, "administrator", False):
            return True
        if not control["enabled"]:
            raise CommandIntercepted(
                f"الأمر `{ctx.command.qualified_name}` معطّل في هذا السيرفر."
            )
        allowed_roles = {str(role_id) for role_id in control["allowed_roles"]}
        if allowed_roles:
            member_roles = {
                str(role.id) for role in getattr(member, "roles", [])
            }
            if not member_roles.intersection(allowed_roles):
                raise CommandIntercepted(
                    f"لا تملك رتبة مسموحة للأمر `{ctx.command.qualified_name}`."
                )
        return True

    async def app_command_interceptor(self, interaction: discord.Interaction) -> bool:
        """Apply the same policy to Slash Commands before Discord invokes them."""
        if interaction.guild is None or interaction.command is None:
            return True
        guild_id = int(interaction.guild.id)
        controls = self.command_controls.get(guild_id)
        if controls is None:
            controls = await get_command_controls(guild_id)
            self.command_controls[guild_id] = controls
        command_name = interaction.command.qualified_name.lower()
        control = controls.get(command_name)
        if not control:
            return True
        permissions = getattr(interaction.user, "guild_permissions", None)
        if permissions and getattr(permissions, "administrator", False):
            return True
        reason = None
        if not control["enabled"]:
            reason = f"الأمر `/{interaction.command.qualified_name}` معطّل في هذا السيرفر."
        else:
            allowed_roles = {str(role_id) for role_id in control["allowed_roles"]}
            member_roles = {
                str(role.id) for role in getattr(interaction.user, "roles", [])
            }
            if allowed_roles and not member_roles.intersection(allowed_roles):
                reason = (
                    f"لا تملك رتبة مسموحة للأمر "
                    f"`/{interaction.command.qualified_name}`."
                )
        if reason:
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(reason, ephemeral=True)
                else:
                    await interaction.response.send_message(reason, ephemeral=True)
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.debug("[COMMAND_POLICY] تعذر إرسال حظر Slash", exc_info=True)
            return False
        return True

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in list(self.bot.guilds):
            try:
                await self.sync_auto_responders(guild.id)
                await self.get_guild_commands_status(guild.id)
            except Exception:
                LOGGER.exception(
                    "[ORCHESTRATOR] تعذر مزامنة إعدادات السيرفر %s", guild.id
                )

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, CommandIntercepted):
            try:
                await ctx.send(f"⛔ {error.reason}", delete_after=7)
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.debug("[COMMAND_POLICY] تعذر إرسال رسالة الحظر", exc_info=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        guild_id = int(message.guild.id)
        if guild_id not in self.auto_responders:
            await self.sync_auto_responders(guild_id)
        content = str(message.content or "")
        if not content.strip():
            return
        if await self._dispatch_shortcut(message):
            return
        for responder in self.auto_responders.get(guild_id, []):
            if (
                responder.get("channel_id") is not None
                and str(responder["channel_id"]) != str(message.channel.id)
            ):
                continue
            if not self._matches(responder, content):
                continue
            if not self._consume_bucket(message, responder):
                continue
            rendered = self.render_response(responder["response"], message)
            if not rendered.strip():
                continue
            try:
                await message.channel.send(
                    rendered,
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.warning(
                    "[AUTORESPONDER] تعذر إرسال رد في السيرفر %s",
                    guild_id,
                    exc_info=True,
                )
            else:
                responder["execution_count"] = await record_auto_responder_execution(
                    guild_id, int(responder["id"])
                )
            break

    @staticmethod
    def _matches(responder: dict[str, Any], content: str) -> bool:
        trigger = str(responder.get("trigger", ""))
        match_type = responder.get("match_type")
        if match_type == "exact":
            return content.strip().casefold() == trigger.casefold()
        if match_type == "contains":
            return trigger.casefold() in content.casefold()
        if match_type == "regex":
            compiled = responder.get("_compiled")
            return bool(compiled and compiled.search(content))
        return False

    def _consume_bucket(
        self,
        message: discord.Message,
        responder: dict[str, Any],
    ) -> bool:
        trigger_id = int(responder.get("id") or hash(responder.get("trigger", "")))
        key = (int(message.guild.id), trigger_id, int(message.author.id))
        now = time.monotonic()
        capacity = max(1, int(responder.get("bucket_capacity", 1)))
        refill = max(0.0, float(responder.get("cooldown_seconds", 5.0)))
        bucket = self._cooldowns.get(key)
        if bucket is None:
            bucket = TokenBucket(float(capacity), now)
        elif refill > 0:
            bucket.tokens = min(
                float(capacity),
                bucket.tokens + ((now - bucket.updated_at) / refill),
            )
        bucket.updated_at = now
        if bucket.tokens < 1:
            self._cooldowns[key] = bucket
            return False
        bucket.tokens -= 1
        self._cooldowns[key] = bucket
        if len(self._cooldowns) > 20000:
            self._prune_buckets()
        return True

    def _prune_buckets(self, guild_id: int | None = None) -> None:
        now = time.monotonic()
        for key, bucket in list(self._cooldowns.items()):
            if guild_id is not None and key[0] != int(guild_id):
                continue
            if now - bucket.updated_at > 3600:
                self._cooldowns.pop(key, None)
        if len(self._cooldowns) > 20000:
            oldest = sorted(
                self._cooldowns.items(), key=lambda item: item[1].updated_at
            )[:5000]
            for key, _ in oldest:
                self._cooldowns.pop(key, None)

    @staticmethod
    def render_response(template: str, message: discord.Message) -> str:
        guild = message.guild
        channel = message.channel
        values = {
            "user": getattr(message.author, "mention", f"<@{message.author.id}>"),
            "channel": getattr(channel, "mention", f"#{getattr(channel, 'name', 'channel')}"),
            "server": getattr(guild, "name", "السيرفر"),
            "members": f"{getattr(guild, 'member_count', 0):,}",
        }
        rendered = str(template or "")
        for key, value in values.items():
            rendered = rendered.replace("{" + key + "}", str(value))

        def choose(match: re.Match) -> str:
            options = [item.strip() for item in match.group(1).split("|") if item.strip()]
            return random.choice(options) if options else ""

        return re.sub(r"\{random:([^{}|]+(?:\|[^{}|]+)+)\}", choose, rendered)[:2000]

    async def _dispatch_shortcut(self, message: discord.Message) -> bool:
        trigger = message.content.strip().casefold()
        for shortcut in self.shortcuts.get(int(message.guild.id), []):
            if str(shortcut.get("trigger", "")).strip().casefold() != trigger:
                continue
            if shortcut["target_type"] == "announcement":
                embed = discord.Embed(
                    description=self.render_response(shortcut["announcement"], message),
                    color=0x5865F2,
                )
                await message.channel.send(embed=embed)
                return True
            return await self._dispatch_command_shortcut(message, shortcut["target"])
        return False

    async def _dispatch_command_shortcut(
        self,
        message: discord.Message,
        target: str,
    ) -> bool:
        target = str(target).strip()
        command_name = target.lstrip("!/").split()[0].lower() if target else ""
        if not command_name:
            return False
        slash_command = self.bot.tree.get_command(command_name)
        if slash_command is not None and target.startswith("/"):
            callback = slash_command.callback
            interaction = ShortcutInteraction(message)
            try:
                binding = getattr(slash_command, "binding", None)
                if binding is not None:
                    await callback(binding, interaction)
                else:
                    await callback(interaction)
                return True
            except Exception:
                LOGGER.exception(
                    "[SHORTCUT] فشل تشغيل الأمر Slash /%s", command_name
                )
                return False
        command = self.bot.get_command(command_name)
        if command is None:
            await message.channel.send(f"⚠️ الأمر `{command_name}` غير موجود حالياً.")
            return True
        ctx = await self.bot.get_context(message)
        try:
            await ctx.invoke(command)
            return True
        except Exception:
            LOGGER.exception("[SHORTCUT] فشل تشغيل الأمر %s", command_name)
            return False

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
        category = discord.utils.get(itx.guild.categories, name="🔊 القنوات التفاعلية")
        if category is None:
            category = await itx.guild.create_category("🔊 القنوات التفاعلية")
        hub = discord.utils.get(category.voice_channels, name=HUB_NAME)
        if hub is None:
            hub = await itx.guild.create_voice_channel(
                name=HUB_NAME,
                category=category,
            )
        await itx.response.send_message(
            f"✅ نظام الرومات المؤقتة جاهز: {hub.mention}",
            ephemeral=True,
        )

    @app_commands.command(
        name="help",
        description="عرض دليل أوامر PRIME حسب الأقسام",
    )
    @app_commands.describe(category="القسم المطلوب، اتركه فارغاً لعرض الأقسام")
    async def help_command(
        self,
        itx: discord.Interaction,
        category: str = None,
    ):
        commands_list = [
            command
            for command in self.bot.tree.walk_commands()
            if not getattr(command, "hidden", False)
            and command.name != "help"
        ]
        aliases = {
            "mod": {"timeout", "untimeout", "warn", "unwarn", "warnings", "clear", "lockdown", "slowmode"},
            "security": {"setup_captcha"},
            "tickets": {"setup_tickets", "suggest"},
            "ai": {"ask_ai", "imagine", "summarize", "transcript", "backup_structure"},
            "economy": {"profile", "daily", "work", "pay", "leaderboard", "deposit", "withdraw", "rob", "giveaway"},
            "tournament": {"scrim_split", "scrim_teams", "map_randomizer", "tournament_open", "match_record", "standings"},
            "server": {"ping", "serverinfo", "avatar", "say", "setup_voice", "radio", "stop_radio"},
            "community": {"poll", "remind", "reminders", "reminder_cancel", "setup_counters"},
        }
        selected = category.strip().lower() if category else None
        if selected and selected not in aliases:
            return await itx.response.send_message(
                "❌ القسم غير معروف. الأقسام المتاحة: "
                + ", ".join(f"`{key}`" for key in aliases),
                ephemeral=True,
            )
        embed = discord.Embed(
            title="📚 دليل أوامر PRIME",
            description=(
                "استخدم `/help category:<القسم>` للحصول على أوامر قسم محدد.\n"
                "الأوامر الحساسة تتطلب صلاحيات Discord مناسبة."
            ),
            color=0x5865F2,
        )
        if selected is None:
            for key, names in aliases.items():
                available = [f"`/{name}`" for name in sorted(names) if any(command.name == name for command in commands_list)]
                if available:
                    embed.add_field(name=f"• {key}", value=" ".join(available), inline=False)
        else:
            allowed = aliases[selected]
            for command in sorted(commands_list, key=lambda item: item.name):
                if command.name in allowed:
                    embed.add_field(
                        name=f"/{command.name}",
                        value=command.description or "لا يوجد وصف",
                        inline=False,
                    )
        await itx.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="status",
        description="عرض صحة البوت والاتصال والخدمات",
    )
    async def status(self, itx: discord.Interaction):
        websocket = round(self.bot.latency * 1000) if self.bot.latency != float("inf") else 0
        embed = discord.Embed(title="🛰️ حالة PRIME", color=0x2ECC71)
        embed.add_field(name="Discord Gateway", value=f"🟢 متصل · `{websocket}ms`", inline=True)
        embed.add_field(name="السيرفرات", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name="الأعضاء", value=f"`{sum(g.member_count or 0 for g in self.bot.guilds):,}`", inline=True)
        embed.add_field(name="الأوامر", value=f"`{len(list(self.bot.tree.walk_commands()))}` أمر Slash", inline=True)
        await itx.response.send_message(embed=embed, ephemeral=True)

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
        ai_cog = self.bot.get_cog("AITools")
        if ai_cog is not None:
            await ai_cog.answer_ai(itx, question)
            return
        await itx.response.send_message(
            "⚠️ محرك الذكاء الاصطناعي غير متاح حالياً. جرّب لاحقاً.",
            ephemeral=True,
        )

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
