# Python Discord Bot

A starter Discord bot built with Python and `discord.py`. It currently includes:

- `/ping` for gateway latency
- `/hello` for a user greeting
- `/serverinfo` for basic server details
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
2. Open **Bot**, create the bot user, and copy its token into the `DISCORD_BOT_TOKEN` Replit Secret.
3. Open **OAuth2 → URL Generator**.
4. Select the `bot` and `applications.commands` scopes.
5. Select only the permissions the bot needs. The starter commands work without administrator permissions.
6. Open the generated URL and add the bot to your server.

For fast slash-command updates during development, add a non-secret `DISCORD_GUILD_ID`
environment variable containing the server ID. Without it, commands sync globally, which
can take longer to appear.

## Extend the bot

Add additional slash commands next to the starter commands in `bot.py`. Keep privileged
intents disabled unless a feature explicitly needs them, and request only the permissions
required by that feature.