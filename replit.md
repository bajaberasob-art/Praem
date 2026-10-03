# PRIME Discord Bot

A production-oriented Python Discord bot using `discord.py` with a large set of preserved cogs for moderation, tickets, community tools, economy, clan operations, and leveling.

## Run

- `python main.py` — canonical Discord bot entry point
- `python bot.py` — compatibility wrapper
- `pytest -q` — run the Python test suite

## PRIME Leveling architecture

- `database.py` stores lifetime XP, timestamped XP events, and periodic TOP run claims.
- `level_progression.py` owns level/XP calculations.
- `cogs/levels.py` owns XP awarding, level-up events, role rewards, voice XP, and scheduled TOP publishing.
- `cogs/rank_commands.py` owns `/rank` and `/top` command delivery only.
- `cogs/card_generator.py` owns the PRIME Rank Card renderer and its five layouts/particle modes.
- `prime_level_controls.py` is the shared PRIME configuration/default/validation layer.
- `leveling_api.py` maps authenticated Dashboard settings into the runtime configuration while retaining legacy fields for compatibility.
- `dashboard/app.js` renders the leveling control center.

Manual `/rank` is a single PRIME PNG by default. `/top` is a lifetime leaderboard with Text/Voice modes. Daily/Weekly/Monthly TOP are scheduled period leaderboards and never reset lifetime XP or levels.

## Database safety

Runtime SQLite databases are ignored by Git. Production should set `DB_PATH` to a persistent location before removing any legacy tracked database file. Never delete a live production database as part of a code-only deployment.

## Discord requirements

Keep only the intents and permissions required by the features enabled in the bot. Leveling requires the member/message capabilities already documented in `README.md`.

## Development rule

Leveling changes should remain surgical: preserve unrelated cogs and database tables, prefer backwards-compatible migrations, add regression tests, and run CI before merging.
