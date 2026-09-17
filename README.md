# Python Discord Bot

A starter Discord bot built with Python and `discord.py`. It currently includes:

- `/ping` for gateway latency
- `/hello` for a user greeting
- `/serverinfo` for basic server details
- Moderation commands: `/timeout`, `/untimeout`, `/warn`, `/warnings`, `/clear`, and
  `/lockdown`
- Automatic invite detection, mass-mention protection, duplicate-message detection, and
  timed spam protection
- Slash-command syncing for either one development server or all servers
- Structured logs and clear startup errors

## Run it

The bot reads its token from the `DISCORD_BOT_TOKEN` Replit Secret.

```bash
python bot.py
```

The configured project workflow runs the same command automatically.

## Discord setup

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Open **Bot**, create the bot user, and copy its raw token into the `DISCORD_BOT_TOKEN` Replit Secret. Do not use the Application ID, public key, client secret, or an OAuth URL.
3. In **Bot → Privileged Gateway Intents**, enable **Message Content Intent** and save
   the change. The bot requests this intent so its automatic moderation protections can
   inspect normal messages.
4. Open **OAuth2 → URL Generator**.
5. Select the `bot` and `applications.commands` scopes.
6. Select the permissions the bot needs, including **View Channel**, **Send Messages**,
   **Read Message History**, **Manage Messages**, **Moderate Members**, and
   **Manage Channels**.
7. Open the generated URL and add the bot to your server.

For fast slash-command updates during development, add a non-secret `DISCORD_GUILD_ID`
environment variable containing the server ID. Without it, commands sync globally, which
can take longer to appear.

## Extend the bot

Add additional slash commands next to the starter commands in `bot.py`. Keep privileged
intents disabled unless a feature explicitly needs them, and request only the permissions
required by that feature. The moderation cog is loaded from `cogs/moderation.py` during
startup, before slash commands are synced.
