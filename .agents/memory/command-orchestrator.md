---
name: Command orchestrator architecture
description: Durable rules for dynamic prefixes, command policies, and cached auto-responder behavior.
---

Dynamic prefixes must resolve through the shared guild-settings cache, while command policies must be applied to both prefix checks and the global Slash CommandTree check.

**Why:** This bot currently exposes most user-facing commands as Slash Commands, so a prefix-only `bot.check` would leave disabled or role-restricted commands reachable.

**How to apply:** Keep the policy cache lazy and refreshable per guild; preserve the original tree check when registering the orchestrator and restore it when unloading the cog.

Policy aliases use one metadata-driven message adapter for registered Slash and prefix commands; it resolves typed entities, durations, quantities, booleans, and trailing text before invoking the real command.

**Why:** Discord resolves typed Slash arguments before invoking callbacks, while an alias arrives as untyped message content; maintaining per-command action branches caused typed aliases to bypass the real handler.

**How to apply:** Resolve commands from the live registry, populate the interaction namespace, run the normal policy and app-command checks, invoke the callback, and classify callback-reported errors before sending the shared confirmation.

Legacy shortcut targets may begin with `/` even when they point to a Prefix command; resolve the target from the live Slash tree before choosing the interaction path, then invoke Prefix commands with a real `Context`.

**Why:** Treating the target marker as the command type calls Prefix callbacks without `ctx`, breaking existing shortcuts such as Arabic economy commands.

**How to apply:** Keep Slash lookup separate from the general command lookup in shortcut dispatch; only use `ShortcutInteraction` for a command found in the tree, and route the fallback through `bot.get_command()` and `Context.invoke()`.

Auto-responder registries are process-local views of durable SQLite rows and must be rehydrated on every ready event; cooldown state is intentionally ephemeral.

**Why:** Discord reconnects recreate the in-memory event environment, but trigger definitions and shortcut bindings must survive restarts while user-level token buckets should not block users after a restart.

**How to apply:** Load enabled responders and shortcuts on ready or first message, compile regexes during sync, and treat invalid patterns as inactive rather than crashing message dispatch.

The commands dashboard should reuse the existing settings revision endpoint for prefix edits and the shared live guild authorization plus CSRF checks for all mutations.

**Why:** The dashboard already has conflict-safe settings saves and live permission rechecks; introducing a second write protocol would create inconsistent authorization and stale prefix state.

**How to apply:** Keep command/trigger routes behind `authorize(req, write=True)`, send the current settings revision for prefix updates, and refresh the orchestrator registry after trigger changes.

Discord's 100-command application limit applies to top-level entries; preserve larger
command surfaces by grouping leaf commands and treating discord.utils.MISSING as a
global-registration sentinel when routing during cog injection.

**Why:** A bot can have more than 100 total leaf commands, but registering every
leaf at the root prevents startup and leaves the dashboard with no connected guilds.

**How to apply:** Keep grouped leaf callbacks discoverable through walk_commands,
resolve shortcuts by leaf name, and count tree.get_commands() before syncing.