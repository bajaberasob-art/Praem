---
name: Dashboard settings & DB conventions
description: Non-obvious decisions behind the guild-settings persistence, dashboard authorization and how to test the dashboard without Discord OAuth.
---

- Never drop/recreate `guild_settings`; extend it additively and keep legacy columns mirrored.
  **Why:** the live SQLite file already holds user balances/XP; the user ruled out recreating tables.
- Concurrency control is an integer revision, not timestamps. A nonzero expected revision must never create a row (that would let a stale client resurrect deleted settings).
  **Why:** second-resolution timestamps collide; the upsert insert arm silently bypassed the predicate once.
- The settings cache is process-local and published only after commit; any writer outside `database.py` must invalidate it or accept up to a minute of staleness.
- Dashboard authorization is per request AND per SSE tick: owner or Administrator bit, checked live through the bot, never trusted from the login-time guild list. Streams must drop as soon as a re-check fails.
- Frontend rule: rebase only the user's delta onto newer snapshots (SSE/409). Replacing the baseline while keeping a full old draft turns remote edits into "local changes" and overwrites them.
- Frontend URLs stay relative (no leading slash) because the dashboard may be mounted under a path prefix; snowflakes travel as strings.
- To test the dashboard in a browser without OAuth, use the harness under `tests/` that fakes the bot and seeds a session; the workspace bot is in zero guilds and OAuth env vars are not configured.
