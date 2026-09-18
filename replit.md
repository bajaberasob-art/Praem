# Python Discord Bot

A Python Discord bot with slash commands for latency checks, greetings, and basic server information.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `python main.py` — run the Discord bot (the canonical entry point)
- `python bot.py` — compatibility wrapper for older run commands
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- Python 3.11, discord.py
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)

## Where things live

- `main.py` — active Discord bot entry point and slash-command synchronization
- `cogs/security.py` — CAPTCHA, account-age, scam-link, and anti-nuke protections
- `pyproject.toml` / `uv.lock` — Python dependency metadata and lockfile
- `README.md` — Discord setup and run instructions

## Architecture decisions

- Slash commands are used instead of prefix commands, but the security cog requires the
  privileged Message Content and Server Members intents for scam-link and account-age
  protections.
- `DISCORD_GUILD_ID` is optional: when present, commands sync quickly to one development server; otherwise they sync globally.
- `DISCORD_BOT_TOKEN` is read only from the environment and is never stored in source files.

## Product

A reusable Discord bot foundation with a small set of working slash commands and a clear path for adding features.

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- Global slash-command sync can take time to propagate; use `DISCORD_GUILD_ID` while developing.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
