"""Discord bot entry point."""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.errors import LoginFailure
from interaction_runtime import (
    install_ui_guards,
    send_interaction_message,
    wrap_application_command,
)


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
logger = logging.getLogger("discord_bot")


def configure_logging() -> None:
    """Configure consistent logs for local runs and the Replit workflow."""
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        stream=sys.stdout,
    )
    logging.getLogger("discord.http").setLevel(logging.WARNING)


def configured_guild() -> Optional[discord.Object]:
    """Return the optional development guild used for fast slash-command sync."""
    guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
    if not guild_id:
        return None

    try:
        return discord.Object(id=int(guild_id))
    except ValueError as exc:
        raise ValueError("DISCORD_GUILD_ID must be a numeric Discord server ID.") from exc


def normalized_token() -> str:
    """Read a raw bot token and remove common formatting added during copy/paste."""
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip().strip("\"'")
    if token.lower().startswith("bot "):
        token = token[4:].strip()
    return token


class DiscordBot(commands.Bot):
    """Bot with a small starter command set and explicit command syncing."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        install_ui_guards()
        super().__init__(
            command_prefix=(),
            intents=intents,
            description="A practical starter Discord bot.",
        )
        self.sync_guild = configured_guild()

    async def setup_hook(self) -> None:
        await self.load_extension("cogs.moderation")
        logger.info("Loaded moderation cog.")
        for command in self.tree.walk_commands():
            if isinstance(command, app_commands.Command):
                wrap_application_command(command)

        if self.sync_guild is not None:
            self.tree.copy_global_to(guild=self.sync_guild)
            synced = await self.tree.sync(guild=self.sync_guild)
            logger.info(
                "Synced %d slash command(s) to development guild %s.",
                len(synced),
                self.sync_guild.id,
            )
        else:
            synced = await self.tree.sync()
            logger.info("Synced %d global slash command(s).", len(synced))

    async def on_ready(self) -> None:
        if self.user is None:
            return
        logger.info("Connected as %s (user ID %s).", self.user, self.user.id)
        logger.info("Serving %d guild(s).", len(self.guilds))


bot = DiscordBot()


@bot.tree.command(name="ping", description="Check the bot's response time.")
async def ping(interaction: discord.Interaction) -> None:
    """Return the bot's current gateway latency."""
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! Gateway latency: {latency_ms} ms.")


@bot.tree.command(name="hello", description="Say hello to the bot.")
async def hello(interaction: discord.Interaction) -> None:
    """Send a friendly greeting."""
    display_name = interaction.user.display_name
    await interaction.response.send_message(f"Hello, {display_name}!")


@bot.tree.command(name="serverinfo", description="Show basic information about this server.")
async def serverinfo(interaction: discord.Interaction) -> None:
    """Show server details when invoked inside a server."""
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used inside a server.",
            ephemeral=True,
        )
        return

    guild = interaction.guild
    embed = discord.Embed(
        title=guild.name,
        description="Server information",
        color=discord.Color.blurple(),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="Members", value=str(guild.member_count or "Unknown"))
    embed.add_field(name="Channels", value=str(len(guild.channels)))
    embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, style="D"))
    await interaction.response.send_message(embed=embed)


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    """Keep command failures user-friendly while retaining the full traceback in logs."""
    logger.exception("Slash command failed.", exc_info=error)
    message = "Something went wrong while running that command."
    await send_interaction_message(interaction, message, ephemeral=True)


def main() -> None:
    configure_logging()
    token = normalized_token()
    if not token:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN is not set. Add the bot token as a Replit Secret "
            "before starting the bot."
        )

    try:
        bot.run(token, log_handler=None)
    except LoginFailure as exc:
        raise RuntimeError(
            "Discord rejected DISCORD_BOT_TOKEN. Use the current token from the "
            "Developer Portal's Bot page, not the Application ID, public key, "
            "client secret, or OAuth URL."
        ) from exc


if __name__ == "__main__":
    main()