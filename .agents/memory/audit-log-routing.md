---
name: Audit log routing
description: Durable constraints for the additive multi-channel Discord audit logger.
---

The audit logger exposes eleven dedicated channel assignments, keeps the six legacy column names as compatibility aliases, and publishes the new route to its process cache only after the SQLite upsert commits.

**Why:** Discord event listeners are high frequency and must not query SQLite on every event, while a failed save must never make an uncommitted route appear live.

**How to apply:** warm the cache on bot ready, refresh it through the dashboard save helper, and resolve legacy listener names to their dedicated route before sending. Keep the legacy moderation log setting untouched. For discord.py embeds, only pass `icon_url` when a URL exists; the current version does not expose `discord.Embed.Empty`.