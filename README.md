# Python Discord Bot

A starter Discord bot built with Python and `discord.py`. It currently includes:

- `/ping` for gateway latency
- `/hello` for a user greeting
- `/serverinfo` for basic server details
- Moderation commands: `/timeout`, `/untimeout`, `/warn`, `/warnings`, `/clear`, and
  `/lockdown`
- Automatic invite detection, mass-mention protection, duplicate-message detection, and
  timed spam protection
- CAPTCHA verification, account-age gating, scam-link blocking, and anti-nuke audit-log
  monitors
- Slash-command syncing for either one development server or all servers
- Structured logs and clear startup errors

## Run it

The bot reads its token from the `DISCORD_BOT_TOKEN` Replit Secret.

```bash
python main.py
```

The configured project workflow runs `python main.py` automatically.

## Discord setup

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Open **Bot**, create the bot user, and copy its raw token into the `DISCORD_BOT_TOKEN` Replit Secret. Do not use the Application ID, public key, client secret, or an OAuth URL.
3. In **Bot → Privileged Gateway Intents**, enable **Server Members Intent** and
   **Message Content Intent**, then save the change. The security cog uses the members
   intent for account-age gating and ban/join events, and the message-content intent for
   scam-link blocking. Presence Intent is not required.
4. Open **OAuth2 → URL Generator**.
5. Select the `bot` and `applications.commands` scopes.
6. Select the permissions the bot needs, including **View Channel**, **Send Messages**,
   **Read Message History**, **Manage Messages**, and **Manage Channels** for the
   existing moderation features. Add these security permissions where the corresponding
   feature is enabled:

   | Permission | Used by |
   | --- | --- |
   | View Audit Log | Anti-nuke channel, role, and mass-ban monitors |
   | Moderate Members | Scam-link timeout |
   | Manage Roles | CAPTCHA role assignment and anti-nuke quarantine |
   | Kick Members | Account-age gate for accounts younger than three days |
   | Mention Everyone | Emergency anti-nuke alert in the system channel |

   Do not grant these permissions to unrelated bots or roles. The bot must also be
   above the verified CAPTCHA role and any roles it may quarantine.
7. Open the generated URL and add the bot to your server.

For fast slash-command updates during development, add a non-secret `DISCORD_GUILD_ID`
environment variable containing the server ID. Without it, commands sync globally, which
can take longer to appear.

After the bot connects and commands finish syncing, an administrator can run
`/setup_captcha` and choose the role that verified members should receive. The CAPTCHA
button remains active while the bot is running and each server's button is bound to its
own selected role.

## Extend the bot

Add additional slash commands next to the starter commands in the loaded cogs. Keep
privileged intents disabled unless a feature explicitly needs them, and request only the
permissions required by that feature. The security and moderation cogs are loaded from
`main.py` before slash commands are synced.
