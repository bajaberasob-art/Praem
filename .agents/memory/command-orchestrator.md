---
name: Command orchestrator architecture
description: Durable rules for dynamic prefixes, command policies, and cached auto-responder behavior.
---

Dynamic prefixes must resolve through the shared guild-settings cache, while command policies must be applied to both prefix checks and the global Slash CommandTree check.

**Why:** This bot currently exposes most user-facing commands as Slash Commands, so a prefix-only `bot.check` would leave disabled or role-restricted commands reachable.

**How to apply:** Keep the policy cache lazy and refreshable per guild; preserve the original tree check when registering the orchestrator and restore it when unloading the cog.

Auto-responder registries are process-local views of durable SQLite rows and must be rehydrated on every ready event; cooldown state is intentionally ephemeral.

**Why:** Discord reconnects recreate the in-memory event environment, but trigger definitions and shortcut bindings must survive restarts while user-level token buckets should not block users after a restart.

**How to apply:** Load enabled responders and shortcuts on ready or first message, compile regexes during sync, and treat invalid patterns as inactive rather than crashing message dispatch.